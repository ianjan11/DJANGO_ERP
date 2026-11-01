from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from accounting.services.reconciliation_service.get_open_reconciliation_lines import get_open_reconciliation_lines
from datetime import datetime
from django.utils import timezone
from accounting.utils.get_fiscal_year import get_fiscal_year_start
from core.utils import htmx_error


@login_required
def reconciliation_page_view(request):
    user = request.user
    company = request.company
    today = timezone.now().date()

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    search_line = request.GET.get("search_line", "").strip()

    try:
        end_date = (
            datetime.strptime(
                end_date_str,
                "%Y-%m-%d",
            ).date()
            if end_date_str
            else today
        )

        start_date = (
            datetime.strptime(
                start_date_str,
                "%Y-%m-%d",
            ).date()
            if start_date_str
            else get_fiscal_year_start(
                company,
                as_of=end_date,
            )
        )

    except ValueError:
        return htmx_error(
            request,
            "Invalid date format, expected YYYY-MM-DD.",
        )

    if start_date > end_date:
        return htmx_error(
            request,
            "start_date must be on or before end_date.",
        )

    reconciliation_lines = get_open_reconciliation_lines(
        company=company,
        start_date=start_date,
        end_date=end_date,
        search_line=search_line,
    )

    for account in reconciliation_lines.values():
        account["partner_count"] = len(account["partners"])
        account["line_count"] = sum(
            len(partner["lines"])
            for partner in account["partners"].values()
        )

    context = {
        "candidates": reconciliation_lines,
        "start_date": start_date,
        "end_date": end_date,
        "search_line": search_line,
    }

    template = (
        "accounting/reconciliation/partials/reconciliation_page_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/reconciliation/reconciliation_page.html"
    )

    return render(request, template, context)