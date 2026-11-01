from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginAuthenticationForm(AuthenticationForm):

    username = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Email",
            "autocomplete": "email",
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Password",
            "autocomplete": "current-password",
        })
    )