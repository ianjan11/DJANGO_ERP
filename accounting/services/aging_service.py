# accounting/services/aging_service.py
from datetime import date
from decimal import Decimal

from django.contrib.admin.templatetags.admin_list import pagination
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from ..models import AccountMove, AccountMoveLine, PartialReconcile

BUCKETS = [
    ('current',   'Current', 0,  0),
    ('b_1_30',    '1-30',    1,  30),
    ('b_31_60',   '31-60',   31, 60),
    ('b_61_90',   '61-90',   61, 90),
    ('b_91_plus', '91+',     91, None),
]

def _empty_buckets():
    return {key: Decimal('0') for key, *_ in BUCKETS}


def _assign_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:   return 'current'
    elif days_overdue <= 30: return 'b_1_30'
    elif days_overdue <= 60: return 'b_31_60'
    elif days_overdue <= 90: return 'b_61_90'
    else:                    return 'b_91_plus'


def _get_residual(move: AccountMove, as_of: date) -> Decimal:
    """
    Sum all PartialReconcile rows that touch any line of this invoice,
    filtered to reconciliations created on or before as_of.

    Your model:
        debit_line  → AccountMoveLine (related: matched_debit_ids)
        credit_line → AccountMoveLine (related: matched_credit_ids)
    """
    move_lines = move.lines.filter(account__allow_reconciliation=True)

    reconciled = (
        PartialReconcile.objects
        .filter(
            Q(debit_line__in=move_lines) | Q(credit_line__in=move_lines),
            date__lte=as_of,
        )
        .distinct()
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )

    return max(move.amount_total - reconciled, Decimal('0'))


def get_aging_report(company, request, partner_type: str, as_of: date = None,):


    search_partner = request.GET.get("search_partner", "").strip()

    as_of = as_of or date.today()

    if partner_type == 'customer':
        move_types = ['out_invoice', 'out_refund']
    else:
        move_types = ['in_invoice', 'in_refund']

    filters = {
        "company": company,
        "move_type__in": move_types,
        "state": "posted",
        "issue_date__lte": as_of,
    }

    if search_partner:
        filters["partner__name__icontains"] = search_partner

    moves   = (
        AccountMove.objects
        .filter( **filters)
        .select_related('partner', 'currency')
        .prefetch_related('lines__matched_debit_ids', 'lines__matched_credit_ids')
        .order_by('partner__name', 'due_date')
    )

    partner_map = {}

    for move in moves:
        residual = _get_residual(move, as_of)



        if residual == Decimal('0'):
            continue

        # Credit notes carry a negative balance
        if move.move_type in ('out_refund', 'in_refund'):
            residual = -abs(residual)

        due_date = move.due_date or move.date
        days_overdue = (as_of - due_date).days
        bucket = _assign_bucket(days_overdue)

        pid = move.partner_id
        if pid not in partner_map:
            partner_map[pid] = {
                'partner_id':   pid,
                'partner_name': move.partner.name if move.partner else '—',
                **_empty_buckets(),
                'total':    Decimal('0'),
                'invoices': [],
            }

        row = partner_map[pid]
        row[bucket] += residual
        row['total'] += residual
        row['invoices'].append({
            'id':           move.id,
            'name':         move.name,
            'date':         move.issue_date,
            'due_date':     due_date,
            'days_overdue': max(days_overdue, 0),
            'currency':     move.currency.symbol if move.currency else '',
            'amount_total': move.amount_total,
            'residual':     residual,
            'bucket':       bucket,
            'move_type':    move.move_type,
        })

    partners = sorted(partner_map.values(), key=lambda r: r['partner_name'])

    totals = _empty_buckets()
    totals['total'] = Decimal('0')
    for row in partners:
        for key, *_ in BUCKETS:
            totals[key] += row[key]
        totals['total'] += row['total']

    paginator = Paginator(partners, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return {
        'as_of':        as_of,
        'partner_type': partner_type,
        'partners':     page_obj,
        'totals':       totals,
        'buckets':      BUCKETS,
    }