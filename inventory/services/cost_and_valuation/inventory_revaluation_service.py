from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounting.models import AccountMove, Journal
from accounting.services import PeriodValidator
from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company, round2, make_move_line,
)


def inventory_revaluation_service(product, user, previous_valuation, current_valuation, *, company=None):
    """
    Post the gain/expense journal entry for an inventory cost revaluation.

      gain : DR inventory valuation / CR revaluation gain
      loss : DR revaluation expense / CR inventory valuation

    `user` is a User (not a request).
    Returns the posted AccountMove, or None when there is no change in valuation.
    Call inside the same transaction as the cost change.
    """
    company = company or getattr(user, 'company', None)
    if company is None:
        raise ValidationError("Company could not be determined for this revaluation.")

    settings_map = company.get_settings_dict()

    date = timezone.localdate()
    PeriodValidator.validate_period(company, date)

    diff = round2(current_valuation - previous_valuation)
    if diff == 0:
        return None

    if not product.category:
        raise ValidationError(
            f"Product '{product.name}' has no category assigned; cannot determine valuation account."
        )

    inventory_account = product.category.get_valuation_account()
    if not inventory_account:
        raise ValidationError(
            f"No inventory valuation account configured for category '{product.category.name}'."
        )

    gain = diff > 0
    if gain:
        offset_account = settings_map.get("default_inventory_revaluation_gain")
        offset_field, offset_label = 'default_inventory_revaluation_gain', 'gain'
    else:
        offset_account = settings_map.get("default_inventory_revaluation_expense")
        offset_field, offset_label = 'default_inventory_revaluation_expense', 'expense'

    if not offset_account:
        raise ValidationError(
            f"No default inventory revaluation {offset_label} account configured for "
            f"company '{company.name}'."
        )
    assert_same_company(offset_account, company, offset_field)

    journal = Journal.objects.filter(company=company, type="INVENTORY", currency=company.currency).first()
    if not journal:
        raise ValidationError("No inventory journal configured for this company.")

    amount = abs(diff)
    memo = (
        f"Inventory cost revaluation - {product.name} "
        f"from {previous_valuation} to {current_valuation}"
    )
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
            ref='',
            narration=memo,
            origin_type='product_revaluation',
            origin_id=product.pk,
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
            raise ValidationError("Unbalanced inventory revaluation entry. This is a bug -- please report it.")

        inv_line.save()
        offset_line.save()

        move.post(user)  # Assigns sequence name and validates balance via accounting engine

    return move