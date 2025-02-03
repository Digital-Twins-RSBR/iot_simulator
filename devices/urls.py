from django.urls import path
from . import views

urlpatterns = [
    # Endpoint para que o gateway do ThingsBoard envie comandos RPC para um dispositivo específico.
    path('rpc/<str:device_id>/', views.rpc_endpoint, name='rpc_endpoint'),
]
