from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounting.models import AccountMove, Journal
from accounting.services import PeriodValidator
from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company, round2, make_move_line,
)


def inventory_adjustment_service(product, user, previous_quantity, current_quantity, location,
                                 *, stock_move=None, picking=None, company=None, unit_cost=None):
    """
    Post the shrinkage/gain journal entry for a stock quantity adjustment.

      loss : DR adjustment expense / CR inventory valuation
      gain : DR inventory valuation / CR adjustment gain

    `user` is a User (not a request). `unit_cost` should be the product cost captured
    BEFORE the stock picking was validated, so that validation (which may recompute
    average cost) cannot change the value booked here. Falls back to product.product_cost.

    Returns the posted AccountMove, or None when there is nothing to book.
    Call inside the same transaction as the stock change.
    Do NOT use for cost-per-unit corrections -- use inventory_revaluation_service.
    """
    company = company or getattr(user, 'company', None)
    if company is None:
        raise ValidationError("Company could not be determined for this adjustment.")

    settings_map = company.get_settings_dict()


    date = timezone.localdate()
    PeriodValidator.validate_period(company, date)

    if current_quantity < 0:
        raise ValidationError("Inventory quantity cannot be negative.")
    if location.company_id != company.pk:
        raise ValidationError("Location does not belong to company.")

    quantity_difference = round2(current_quantity - previous_quantity)
    if quantity_difference == 0:
        return None

    cost = unit_cost if unit_cost is not None else product.product_cost
    value_difference = round2(quantity_difference * cost)
    if value_difference == 0:
        return None     # stock changed, but there is no value to book

    if not product.category:
        raise ValidationError(
            f"Product '{product.name}' has no category assigned; cannot determine valuation account.")
    inventory_account = product.category.get_valuation_account()
    if not inventory_account:
        raise ValidationError(
            f"No inventory valuation account configured for category '{product.category.name}'.")

    assert_same_company(inventory_account, company, "property_valuation_account")


    gain = value_difference > 0
    if gain:
        offset_account =settings_map.get("default_inventory_adjustment_gain")
        offset_field, offset_label = 'default_inventory_adjustment_gain', 'gain'
    else:
        offset_account = settings_map.get("default_inventory_adjustment_expense")
        offset_field, offset_label = 'default_inventory_adjustment_expense', 'expense'
    if not offset_account:
        raise ValidationError(
            f"No default inventory adjustment {offset_label} account configured for "
            f"company '{company.name}'.")
    assert_same_company(offset_account, company, offset_field)

    journal = Journal.objects.filter(company=company, type="INVENTORY", currency=company.currency).first()
    if not journal:
        raise ValidationError("No inventory journal configured for this company.")

    amount = abs(value_difference)
    memo = (f"Inventory adjustment - {product.name} @ {location.name} "
            f"from {previous_quantity} to {current_quantity}")
    zero = Decimal("0")

    with transaction.atomic():
        move = AccountMove.objects.create(
            move_type=AccountMove.MoveType.ENTRY,
            issue_date=date,
            currency=company.currency,
            company=company,
            journal=journal,
            created_by=user,
            amount_total=amount,
            ref=picking.name if picking else '',
            narration=memo,
            origin_type='stock_picking' if picking else None,
            origin_id=picking.pk if picking else None,
        )

        if gain:
            inv_line = make_move_line(move=move, account=inventory_account, partner=None,
                                      debit=amount, credit=zero, date=date, memo=memo, foreign_currency=None)
            offset_line = make_move_line(move=move, account=offset_account, partner=None,
                                         debit=zero, credit=amount, date=date, memo=memo, foreign_currency=None)
        else:
            offset_line = make_move_line(move=move, account=offset_account, partner=None,
                                         debit=amount, credit=zero, date=date, memo=memo, foreign_currency=None)
            inv_line = make_move_line(move=move, account=inventory_account, partner=None,
                                      debit=zero, credit=amount, date=date, memo=memo, foreign_currency=None)

        if round2(inv_line.debit + offset_line.debit) != round2(inv_line.credit + offset_line.credit):
            raise ValidationError("Unbalanced inventory adjustment entry. This is a bug -- please report it.")

        if stock_move is not None:
            inv_line.stock_move = stock_move

        # Save unconditionally. save() inserts a new row or updates an existing one,
        # so this is correct whether or not make_move_line() already persisted them.
        inv_line.save()
        offset_line.save()

        move.post(user)          # assigns the journal sequence name; is_balanced() re-checked there

        if picking is not None:
            picking.account_move = move
            picking.save(update_fields=['account_move'])

    return move