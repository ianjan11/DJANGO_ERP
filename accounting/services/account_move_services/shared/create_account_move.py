
# common/move_builder.py

from accounting.models import AccountMove



def create_account_move(
    *,
    company,
    partner,
    journal,
    move_type,
    date,
    due_date,
    currency,
    name,
    ref=None,
    amount_untaxed,
    amount_tax,
    amount_total,
    amount_residual,
    created_by,
    currency_rate,
    origin_id,
    origin_type,
    payment_term,
):
    return AccountMove(
        move_type=move_type,
        date=date,
        due_date=due_date,
        partner=partner,
        currency=currency,
        company=company,
        journal=journal,
        ref=ref,
        name=name,

        amount_untaxed=amount_untaxed,
        amount_tax=amount_tax,
        amount_total=amount_total,
        amount_residual=amount_residual,

        created_by=created_by,

        currency_rate=currency_rate,

        payment_term=payment_term,


        origin_type=origin_type,
        origin_id=origin_id,
    )



