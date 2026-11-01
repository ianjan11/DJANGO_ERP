from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.forms.company_form import CompanyForm
from core.models import Company


def settings_view(request):


    company = request.company
    company_form = CompanyForm(
        instance=company,
        user=request.user,
    )

    context = {
        'company_form': company_form,
        'company': company,
    }

    template = (
        "core/settings/settings.html"
    )

    return render(request,template, context)

