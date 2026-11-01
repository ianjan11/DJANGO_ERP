from decimal import Decimal
from django.db import models

from core.services.currency_exchange_service import _get_rate
from inventory.models import StockMove, StockLocation

ZERO = Decimal('0')


# --------------------------------------------------------------------------- #
# Location Boundary Helpers (Single Source of Truth for Inflows / Outflows)
# --------------------------------------------------------------------------- #
def _is_incoming_move(move):
    """Determine if a move brings stock IN based on physical location boundaries."""
    internal = StockLocation.Usage.INTERNAL
    src = getattr(move.source_location, 'usage', None)
    dst = getattr(move.dest_location, 'usage', None)  # Fixed from destination_location
    if not src or not dst:
        picking = getattr(move, 'picking', None)
        if picking:
            src = getattr(picking.source_location, 'usage', None)
            dst = getattr(picking.dest_location, 'usage', None)
    return dst == internal and src != internal


def _is_outgoing_move(move):
    """Determine if a move sends stock OUT based on physical location boundaries."""
    internal = StockLocation.Usage.INTERNAL
    src = getattr(move.source_location, 'usage', None)
    dst = getattr(move.dest_location, 'usage', None)  # Fixed from destination_location
    if not src or not dst:
        picking = getattr(move, 'picking', None)
        if picking:
            src = getattr(picking.source_location, 'usage', None)
            dst = getattr(picking.dest_location, 'usage', None)
    return src == internal and dst != internal

# --------------------------------------------------------------------------- #
# Incoming cost (single source of truth: used by GRNI valuation AND by layers)
# --------------------------------------------------------------------------- #
def _storage_qty(quantity, uom, product):
    """Convert a quantity expressed in `uom` into the product's storage UoM."""
    uom = uom or product.uom
    return Decimal(str(uom.convert_to(quantity, product.uom)))


def _non_recoverable_tax(tax_data):
    """
    Taxes the company cannot reclaim are a real cost of the goods
    (import duty, non-deductible VAT, excise) and must be capitalised.
    Recoverable taxes (normal input VAT) are NOT part of inventory cost.
    """
    total = ZERO
    for item in tax_data.get('lines') or []:
        tax = item['tax']
        if not tax.is_recoverable:
            total += item['amount']
    return total


def get_receipt_unit_cost_document(stock_move):
    """
    Cost of ONE storage-UoM unit of a received move, in the PURCHASE-ORDER
    currency. Returns (unit_cost, currency); currency is None when the cost
    is already in company currency (fallback to product_cost).
    """
    product = stock_move.product
    purchase_line = getattr(stock_move, 'purchase_line', None)

    if purchase_line is None:
        return product.product_cost, None

    tax_data = purchase_line.compute_taxes(tax_use='PURCHASE')
    base = tax_data.get('base')
    if base is None:
        raise Exception(f'Purchase line {purchase_line.pk} has no tax-exclusive base.')

    ordered_qty = _storage_qty(
        Decimal(str(purchase_line.quantity)),
        getattr(purchase_line, 'product_uom', None),
        product,
    )
    if ordered_qty <= 0:
        raise Exception(f'Purchase line {purchase_line.pk} has an invalid quantity.')

    total_cost = Decimal(str(base)) + _non_recoverable_tax(tax_data)
    return total_cost / ordered_qty, purchase_line.purchase_order.currency


def get_receipt_unit_cost(stock_move):
    """Same as above but converted to COMPANY currency at the receipt date."""
    unit_cost, currency = get_receipt_unit_cost_document(stock_move)
    if unit_cost is None:
        return None
    company = stock_move.product.company
    if currency is None or currency == company.currency:
        return Decimal(unit_cost)

    picking = getattr(stock_move, 'picking', None)
    when = (picking.date_done if picking else None) or stock_move.created_at
    rate = _get_rate(company=company, currency=currency, date=when)
    if not rate or Decimal(str(rate)) <= 0:
        raise Exception(f'No valid exchange rate for {currency} on {when}.')
    return Decimal(unit_cost) * Decimal(str(rate))


def _layer_unit_cost(move):
    """Best-known company-currency unit cost for a single IN move."""
    if move.purchase_line_id:
        return get_receipt_unit_cost(move)
    return move.product.product_cost


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #
def _completed_moves(product, before=None, exclude_move_ids=()):
    """
    Query completed moves crossing internal company boundaries, ordered chronologically
    by completion date (`picking__date_done`) with fallback to creation time.
    Internal-to-internal transfers are automatically filtered out.
    """
    internal = StockLocation.Usage.INTERNAL

    qs = (
        StockMove.objects
        .filter(product=product, status='COMPLETED')
        .filter(
            (models.Q(source_location__usage=internal) & ~models.Q(dest_location__usage=internal)) |
            (~models.Q(source_location__usage=internal) & models.Q(dest_location__usage=internal))
        )
        .select_related(
            'product', 'product__company', 'purchase_line',
            'purchase_line__purchase_order', 'picking',
            'source_location', 'dest_location'
        )
        .order_by('picking__date_done', 'created_at', 'pk')
    )
    if before is not None:
        qs = qs.filter(picking__date_done__lt=before)
    if exclude_move_ids:
        qs = qs.exclude(pk__in=list(exclude_move_ids))
    return qs

def _build_fifo_layers(product, before=None, exclude_move_ids=()):
    """Layers still on hand, oldest first: [{'quantity', 'unit_cost'}, ...]."""
    layers = []
    for move in _completed_moves(product, before, exclude_move_ids):
        qty = Decimal(str(move.quantity_in_storage_uom))

        if _is_incoming_move(move):
            layers.append([qty, Decimal(str(_layer_unit_cost(move)))])
        elif _is_outgoing_move(move):
            remaining = qty
            for layer in layers:
                if remaining <= 0:
                    break
                consume = min(layer[0], remaining)
                layer[0] -= consume
                remaining -= consume
            # Graceful absorption of historical stock gaps without hard-crashing
    return [{'quantity': q, 'unit_cost': c} for q, c in layers if q > 0]


def _moving_average_cost(product, before=None, exclude_move_ids=()):
    """
    True moving average: OUT moves leave at the running average.
    Gracefully handles historical deficits caused by out-of-order data entry.
    """
    qty, value = ZERO, ZERO
    for move in _completed_moves(product, before, exclude_move_ids):
        q = Decimal(str(move.quantity_in_storage_uom))

        if _is_incoming_move(move):
            qty += q
            value += q * Decimal(str(_layer_unit_cost(move)))
        elif _is_outgoing_move(move):
            if q > qty:
                # Historical gap detected; reset balance cleanly instead of throwing 500 error
                qty = ZERO
                value = ZERO
                continue
            value -= q * (value / qty)
            qty -= q

    return (value / qty) if qty > 0 else product.product_cost


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def get_cost(product, quantity=1, before=None, exclude_move_ids=()):
    """
    Unit cost (company currency, per storage UoM) for `quantity` units.

    When valuing an already-completed outgoing picking pass
    `before=<earliest date_done of its moves>` and `exclude_move_ids=<its move ids>`
    so the cost is the cost AT THE TIME OF SALE, not after the sale consumed stock.
    """
    method = product.get_costing_method()
    if method is None:
        raise Exception('No costing method defined')

    if method == 'manual':
        return product.product_cost

    if method == 'average':
        avg = _moving_average_cost(product, before, exclude_move_ids)
        return avg if avg is not None else product.product_cost

    if method == 'fifo':
        layers = _build_fifo_layers(product, before, exclude_move_ids)
        if not layers:
            return product.product_cost

        remaining = Decimal(str(quantity))
        total_value, covered = ZERO, ZERO
        for layer in layers:
            if remaining <= 0:
                break
            take = min(layer['quantity'], remaining)
            total_value += take * layer['unit_cost']
            covered += take
            remaining -= take

        if remaining > 0:  # beyond tracked layers: cover at product_cost
            total_value += remaining * product.product_cost
            covered += remaining
        return total_value / covered

    raise Exception(f'Unknown costing method: {method}')