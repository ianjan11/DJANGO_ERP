import json
from pygments.lexers import data
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required


@login_required
def check_auth(request):
    return JsonResponse({'authenticated': True})














