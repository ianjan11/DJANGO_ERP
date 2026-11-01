from datetime import date
import calendar

def get_fiscal_year_start(company, as_of=None):
    as_of = as_of or date.today()
    month = company.fiscal_year_start_month
    day = company.fiscal_year_start_day

    def safe_date(year, month, day):
        # clamp to the last valid day of that month (handles Feb 29 on non-leap years)
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(day, last_day))

    candidate = safe_date(as_of.year, month, day)

    if as_of >= candidate:
        return candidate
    return safe_date(as_of.year - 1, month, day)


