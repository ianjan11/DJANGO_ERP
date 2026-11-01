from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from accounting.services.aging_service import get_aging_report
from accounting.utils import _parse_date


def build_context(as_of, data, report_type):

    if report_type == "ar":
        report_url = reverse("accounting:ar_aging")
        title = "AR Report"

    elif report_type == "ap":
        report_url = reverse("accounting:ap_aging")
        title = "AP Report"

    else:
        raise ValueError("Invalid report type")

    return {
        "as_of": as_of,
        "report_type": report_type,
        "report_url": report_url,
        "tittle": title,
        **data,
    }


def render_aging_report(request, *, partner_type, report_type):
    """
    Shared AR/AP aging report handler.

    Filtering, partner_id handling, search and pagination
    are delegated to get_aging_report().
    """

    as_of = (
         _parse_date(request.GET.get("as_of"))
        or date.today()
    )

    data = get_aging_report(
        company=request.company,
        request=request,
        partner_type=partner_type,
        as_of=as_of,
    )

    context = build_context(
        as_of=as_of,
        data=data,
        report_type=report_type,
    )

    template = (
        "accounting/reports/partials/aging_report_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/reports/aging_report.html"
    )

    return render(request, template, context)


@login_required
def ap_aging_report(request):
    return render_aging_report(
        request,
        partner_type="supplier",
        report_type="ap",
    )


@login_required
def ar_aging_report(request):
    return render_aging_report(
        request,
        partner_type="customer",
        report_type="ar",
    )