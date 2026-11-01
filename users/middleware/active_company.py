from django.utils.functional import SimpleLazyObject
from users.models import CompanyMembership


def get_active_company(request):
    if not request.user.is_authenticated:
        return None

    company_id = request.session.get("active_company_id")

    if not company_id:
        return None

    membership = (
        CompanyMembership.objects
        .select_related("company")
        .filter(
            user=request.user,
            company_id=company_id,
            is_active=True,
        )
        .first()
    )

    if not membership:
        # Session contains an invalid or no-longer-authorized company.
        request.session.pop("active_company_id", None)
        return None

    return membership.company


class ActiveCompanyMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = SimpleLazyObject(
            lambda: get_active_company(request)
        )

        return self.get_response(request)
