from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect, render

from users.forms.register_form import UserSignUpForm
from users.models import UserProfile


def public_register_view(request):
    if request.user.is_authenticated:
        return redirect("users:select-company")

    form = UserSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("users:select-company")

    return render(request, "users/register.html", {"form": form})