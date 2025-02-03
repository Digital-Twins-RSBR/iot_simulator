import json
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Device
from .rpc_handlers import RPC_HANDLER_REGISTRY


def index(request):
    return render(request, 'index.html')
