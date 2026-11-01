from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.urls import reverse




def home(request):
    if not request.user.is_authenticated:
        return HttpResponseRedirect(reverse("users:login"))

    context = {

    }

    return render(request, "users/dashboard.html", context)


