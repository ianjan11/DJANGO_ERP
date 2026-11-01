from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib import messages


def csrf_failure_view(request, reason=""):
    messages.error(request,"your session has expired. please login again")
    return HttpResponseRedirect(reverse("users:login"))