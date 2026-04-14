import json
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from .models import Device, System, Unit, DeviceType, GatewayIOT
from .rpc_handlers import RPC_HANDLER_REGISTRY
from .simulator_control import read_recent_logs, start_simulator, stop_simulator, get_runtime_status
from .thingsboard_gateway import get_active_gateway, test_gateway_connection


def index(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('simulator-dashboard')
    return redirect('/admin/login/?next=/')


@staff_member_required
def dashboard(request):
    runtime = get_runtime_status()
    active_gateway = get_active_gateway(required=False)
    context = {
        'site_header': admin.site.site_header,
        'site_title': admin.site.site_title,
        'runtime': runtime,
        'recent_logs': read_recent_logs(),
        'stats': {
            'devices_total': Device.objects.count(),
            'devices_with_token': Device.objects.exclude(token='').count(),
            'devices_without_token': Device.objects.filter(token='').count(),
            'gateways_total': GatewayIOT.objects.count(),
            'gateways_active': GatewayIOT.objects.filter(is_active=True).count(),
            'systems_total': System.objects.count(),
            'units_total': Unit.objects.count(),
            'device_types_total': DeviceType.objects.count(),
        },
        'active_gateway': {
            'id': active_gateway.id,
            'name': active_gateway.name,
            'base_url': active_gateway.base_url,
            'auth_method': active_gateway.auth_method,
        } if active_gateway else None,
        'admin_links': [
            {'label': 'Dashboard', 'url': '/dashboard/', 'icon': 'radar'},
            {'label': 'Devices', 'url': '/admin/devices/device/', 'icon': 'memory'},
            {'label': 'Gateways IoT', 'url': '/admin/devices/gatewayiot/', 'icon': 'router'},
            {'label': 'Systems', 'url': '/admin/devices/system/', 'icon': 'lan'},
            {'label': 'Units', 'url': '/admin/devices/unit/', 'icon': 'grid_view'},
            {'label': 'Device Types', 'url': '/admin/devices/devicetype/', 'icon': 'tune'},
            {'label': 'Django Admin', 'url': '/admin/', 'icon': 'admin_panel_settings'},
        ],
        'simulator_flags': {
            'randomize': getattr(settings, 'SIMULATOR_RANDOMIZE_DEFAULT', True),
            'memory': getattr(settings, 'SIMULATOR_MEMORY_DEFAULT', True),
            'use_influxdb': bool(getattr(settings, 'INFLUXDB_TOKEN', '')),
        },
    }
    return render(request, 'devices/dashboard.html', context)


@staff_member_required
def dashboard_status(request):
    runtime = get_runtime_status()
    active_gateway = get_active_gateway(required=False)
    data = {
        'runtime': runtime,
        'stats': {
            'devices_total': Device.objects.count(),
            'devices_with_token': Device.objects.exclude(token='').count(),
            'devices_without_token': Device.objects.filter(token='').count(),
            'gateways_total': GatewayIOT.objects.count(),
            'gateways_active': GatewayIOT.objects.filter(is_active=True).count(),
        },
        'active_gateway': {
            'id': active_gateway.id,
            'name': active_gateway.name,
            'base_url': active_gateway.base_url,
            'auth_method': active_gateway.auth_method,
        } if active_gateway else None,
        'recent_logs': read_recent_logs(),
    }
    return JsonResponse(data)


@staff_member_required
@csrf_exempt
def dashboard_start(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    payload = json.loads(request.body.decode('utf-8') or '{}') if request.body else {}
    active_gateway = get_active_gateway(required=False)
    if not active_gateway:
        return JsonResponse(
            {
                'ok': False,
                'error': 'gateway_not_configured',
                'message': 'Nenhum GatewayIOT ativo configurado. Cadastre e ative um gateway no admin.',
            },
            status=409,
        )

    ok, detail = test_gateway_connection(gateway=active_gateway)
    if not ok:
        return JsonResponse(
            {
                'ok': False,
                'error': 'gateway_connection_failed',
                'message': f"Gateway ativo sem acesso/autenticacao valida: {detail}",
            },
            status=409,
        )

    result = start_simulator(
        randomize=payload.get('randomize', True),
        use_memory=payload.get('memory', True),
        use_influxdb=payload.get('use_influxdb', bool(getattr(settings, 'INFLUXDB_TOKEN', ''))),
        system=payload.get('system') or None,
        device_type=payload.get('device_type') or None,
    )
    status = 200 if result.get('ok') else 409
    return JsonResponse(result, status=status)


@staff_member_required
@csrf_exempt
def dashboard_stop(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    result = stop_simulator()
    status = 200 if result.get('ok') else 409
    return JsonResponse(result, status=status)


@staff_member_required
def dashboard_logs(request):
    return JsonResponse({'lines': read_recent_logs()})


@staff_member_required
@csrf_exempt
def dashboard_check_gateway(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    active_gateway = get_active_gateway(required=False)
    if not active_gateway:
        return JsonResponse(
            {
                'ok': False,
                'error': 'gateway_not_configured',
                'message': 'Nenhum GatewayIOT ativo configurado.',
            },
            status=409,
        )

    ok, detail = test_gateway_connection(gateway=active_gateway)
    return JsonResponse(
        {
            'ok': ok,
            'gateway': {
                'id': active_gateway.id,
                'name': active_gateway.name,
                'base_url': active_gateway.base_url,
                'auth_method': active_gateway.auth_method,
            },
            'message': 'Gateway acessivel e autenticado.' if ok else f'Falha ao validar gateway: {detail}',
        },
        status=200 if ok else 409,
    )
