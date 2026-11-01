from django.contrib.auth.decorators import login_required
from django.http import  JsonResponse


@login_required
def check_auth(request):
    return JsonResponse({'authenticated': True})



