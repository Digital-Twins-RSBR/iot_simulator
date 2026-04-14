from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.conf import settings
import requests

from .models import Device
from .thingsboard_gateway import get_active_gateway, get_gateway_connection, get_management_headers

@receiver(post_delete, sender=Device)
def delete_device_on_thingsboard(sender, instance, **kwargs):
    if getattr(settings, "ALLOW_THINGSBOARD_DELETE", False):
        tb_device_id = getattr(instance, "thingsboard_id", None)
        if tb_device_id:
            try:
                gateway = get_active_gateway(required=True)
                connection = get_gateway_connection(gateway)
                headers = get_management_headers(gateway=gateway)
                delete_url = f"{connection.base_url}/api/device/{tb_device_id}"
                del_resp = requests.delete(delete_url, headers=headers, timeout=10)
                if del_resp.status_code == 401:
                    headers = get_management_headers(gateway=gateway, force_refresh=True)
                    del_resp = requests.delete(delete_url, headers=headers, timeout=10)
                if del_resp.status_code != 200:
                    print(f"Erro ao deletar device no ThingsBoard: {del_resp.status_code} - {del_resp.text}")
            except Exception as e:
                print(f"Falha ao deletar device no ThingsBoard: {e}")
        else:
            print("thingsboard_id não encontrado no modelo Device.")
