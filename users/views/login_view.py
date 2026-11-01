from django.contrib.auth.views import LoginView
from django.urls import reverse, reverse_lazy
from users.forms.login_form import LoginAuthenticationForm


class CustomLoginView(LoginView):
    template_name = "users/login.html"
    authentication_form = LoginAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("users:select-company")




