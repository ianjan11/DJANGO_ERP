from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.urls import reverse

from core.utils import htmx_error


def home(request):
    if not request.user.is_authenticated:
        return HttpResponseRedirect(reverse("users:login"))

    if not request.company:
        return htmx_error(request, "You must select a company to continue ")

    context = {

    }

    return render(request, "users/dashboard.html", context)


