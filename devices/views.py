import json
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from .models import Device
from .rpc_handlers import RPC_HANDLER_REGISTRY

@csrf_exempt  # Caso o ThingsBoard ou gateway não envie o token CSRF
def rpc_endpoint(request, device_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Apenas requisições POST são permitidas.")
    
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest("Payload inválido.")
    
    method = payload.get("method")
    params = payload.get("params")
    if not method:
        return HttpResponseBadRequest("Campo 'method' é obrigatório.")
    
    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        return HttpResponseNotFound("Dispositivo não encontrado.")
    
    # Utiliza o nome do tipo (em letras minúsculas) para recuperar o handler apropriado.
    device_type_name = device.device_type.name.lower()
    handler_class = RPC_HANDLER_REGISTRY.get(device_type_name)
    if not handler_class:
        return HttpResponseBadRequest("Tipo de dispositivo não suportado para RPC.")
    
    handler = handler_class(device)
    result = handler.handle(method, params)
    return JsonResponse(result)
