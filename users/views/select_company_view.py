from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.forms.company_form import CompanyForm
from core.models import Company
from users.models import CompanyMembership


class SelectCompanyView(LoginRequiredMixin, TemplateView):
    template_name = "users/select_company.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["memberships"] = (
            CompanyMembership.objects
            .select_related("company")
            .filter(
                user=self.request.user,
                is_active=True,
            )
            .order_by("company__name")
        )

        return context

@login_required
@require_POST
def select_company(request):
    company_id = request.POST.get("company_id")

    membership = (
        CompanyMembership.objects
        .filter(
            user=request.user,
            company_id=company_id,
            is_active=True,
        )
        .first()
    )

    if not membership:
        messages.error(
            request,
            "You do not have access to that company.",
        )
        return redirect("users:select-company")

    request.session["active_company_id"] = membership.company_id

    return redirect("users:home")

@login_required
@require_POST
def switch_company(request, company_id):
    membership = (
        CompanyMembership.objects
        .filter(
            user=request.user,
            company_id=company_id,
            is_active=True,
        )
        .first()
    )

    if not membership:
        messages.error(
            request,
            "You do not have access to that company.",
        )
        return redirect("users:home")

    request.session["active_company_id"] = str(membership.company_id)

    return redirect("users:home")

@login_required
def create_first_company(request):
    company_form = CompanyForm(user=request.user)

    context = {
        "company_form": company_form,
        "form_context": "first_company",
        "back_url": reverse("users:select-company"),
    }

    template = (
        "core/settings/company/partials/company_detail_partial.html"
        if request.headers.get("HX-Request")
        else "core/settings/company/company_detail.html"
    )

    return render(request, template, context)


