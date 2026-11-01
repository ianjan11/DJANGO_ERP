from datetime import date, datetime
from django.core.exceptions import ValidationError


class PeriodValidator:

    @staticmethod
    def validate_period(company, entry_date):

        if isinstance(entry_date, datetime):
            entry_date = entry_date.date()

        if entry_date > date.today():
            raise ValidationError("Cannot post future-dated entries.")
        if company.lock_date and entry_date <= company.lock_date:
            raise ValidationError(
                f"Period locked up to {company.lock_date}."
            )

    @staticmethod
    def validate_tax_period(company, entry_date):

        if isinstance(entry_date, datetime):
            entry_date = entry_date.date()

        if entry_date > date.today():
            raise ValidationError("Cannot post future-dated entries.")
        if company.tax_lock_date and entry_date <= company.tax_lock_date:
            raise ValidationError(
                f"Tax period locked up to {company.tax_lock_date}."
            )