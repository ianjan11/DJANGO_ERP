from django.core.exceptions import ValidationError

from accounting.services.account_move_services.shared.account_utils import round2

def check_balance(lines):


    total_debit = round2(
        sum(line.debit for line in lines)
    )

    total_credit = round2(
        sum(line.credit for line in lines)
    )

    if total_debit != total_credit:
        raise ValidationError(
            f"Unbalanced journal entry: "
            f"DR {total_debit} != CR {total_credit}. "
            f"This is an accounting configuration or "
            f"calculation error."
        )


    for line in lines:


        if line.debit < 0:
            raise ValidationError(
                "Journal line debit cannot be negative."
            )

        if line.credit < 0:
            raise ValidationError(
                "Journal line credit cannot be negative."
            )

        if line.debit and line.credit:
            raise ValidationError(
                "A journal line cannot contain both "
                "debit and credit."
            )

        line.full_clean()


