from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.conf import settings
import requests

from .models import Device

@receiver(post_delete, sender=Device)
def delete_device_on_thingsboard(sender, instance, **kwargs):
    if getattr(settings, "ALLOW_THINGSBOARD_DELETE", False):
        tb_device_id = getattr(instance, "thingsboard_id", None)
        if tb_device_id:
            try:
                resp = requests.post(
                    f"{settings.THINGSBOARD_HOST}/api/auth/login",
                    json={"username": settings.THINGSBOARD_USER, "password": settings.THINGSBOARD_PASSWORD},
                    timeout=10
                )
                resp.raise_for_status()
                jwt_token = resp.json().get("token")
                if not jwt_token:
                    print("Não foi possível obter o token JWT do ThingsBoard.")
                    return

                headers = {"X-Authorization": f"Bearer {jwt_token}"}
                delete_url = f"{settings.THINGSBOARD_HOST}/api/device/{tb_device_id}"
                del_resp = requests.delete(delete_url, headers=headers, timeout=10)
                if del_resp.status_code != 200:
                    print(f"Erro ao deletar device no ThingsBoard: {del_resp.status_code} - {del_resp.text}")
            except Exception as e:
                print(f"Falha ao deletar device no ThingsBoard: {e}")
        else:
            print("thingsboard_id não encontrado no modelo Device.")
