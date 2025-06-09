from django.db import models
from django.conf import settings
import requests
import json

class DeviceType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return self.name

class System(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Unit(models.Model):
    name = models.CharField(max_length=100)
    system = models.ForeignKey(System, on_delete=models.CASCADE, related_name='units')

    class Meta:
        unique_together = ('name', 'system')

    def __str__(self):
        return f"{self.system.name} - {self.name}"

class Device(models.Model):
    device_id = models.CharField(max_length=50, unique=True)
    device_type = models.ForeignKey(DeviceType, on_delete=models.CASCADE)
    token = models.CharField(max_length=100)
    thingsboard_id = models.CharField(max_length=64, blank=True, null=True)  # <-- novo campo
    # Field to store the device state (e.g., {"status": true} or {"temperature": 25.0, "humidity": 50.0})
    state = models.JSONField(default=dict)  # Available in Django 3.1+; otherwise, use a JSONField from a specific package.
    system = models.ForeignKey(System, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='devices')

    def __str__(self):
        return self.device_id

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            # Cria o device no ThingsBoard via API REST autenticando com usuário/senha
            THINGSBOARD_HOST = settings.THINGSBOARD_HOST.rstrip('/')
            THINGSBOARD_API_URL = f"{THINGSBOARD_HOST}/api"
            TB_USER = getattr(settings, "THINGSBOARD_USER", None)
            TB_PASSWORD = getattr(settings, "THINGSBOARD_PASSWORD", None)
            if not TB_USER or not TB_PASSWORD:
                print("THINGSBOARD_USER ou THINGSBOARD_PASSWORD não configurados no settings.")
                return

            # Autentica e obtém JWT
            try:
                resp = requests.post(
                    f"{THINGSBOARD_API_URL}/auth/login",
                    json={"username": TB_USER, "password": TB_PASSWORD},
                    headers={"Content-Type": "application/json"}
                )
                resp.raise_for_status()
                jwt_token = resp.json().get("token")
            except Exception as e:
                print(f"Erro ao autenticar no ThingsBoard: {e}")
                return

            headers = {
                "Content-Type": "application/json",
                "X-Authorization": f"Bearer {jwt_token}"
            }

            # Verifica se o device já existe pelo nome
            url_search = f"{THINGSBOARD_API_URL}/tenant/devices?deviceName={self.device_id}"
            try:
                resp = requests.get(url_search, headers=headers)
                if resp.status_code == 200 and resp.json().get("data"):
                    print(f"Device {self.device_id} já existe no ThingsBoard.")
                    tb_device_id = resp.json()["data"][0]["id"]["id"]
                else:
                    # Cria o device
                    payload = {
                        "name": self.device_id,
                        "type": self.device_type.name if hasattr(self.device_type, "name") else "default"
                    }
                    url_create = f"{THINGSBOARD_API_URL}/device"
                    resp = requests.post(url_create, headers=headers, data=json.dumps(payload))
                    if resp.status_code in (200, 201):
                        tb_device_id = resp.json()["id"]["id"]
                        print(f"Device {self.device_id} criado no ThingsBoard.")
                    elif resp.status_code == 409:
                        print(f"Device {self.device_id} já existe no ThingsBoard (409).")
                        return
                    else:
                        print(f"Erro ao criar device no ThingsBoard: {resp.status_code} - {resp.text}")
                        return
                # Salva o thingsboard_id no modelo
                self.thingsboard_id = tb_device_id
                super().save(update_fields=["thingsboard_id"])
            except Exception as e:
                print(f"Erro ao consultar/criar device no ThingsBoard: {e}")
                return

            # Recupera o token do device
            try:
                url_token = f"{THINGSBOARD_API_URL}/device/{tb_device_id}/credentials"
                resp = requests.get(url_token, headers=headers)
                resp.raise_for_status()
                device_token = resp.json().get("credentialsId")
                if device_token:
                    self.token = device_token
                    # Salva novamente apenas o token
                    super().save(update_fields=["token"])
                    print(f"Token do device {self.device_id} salvo no modelo.")
                else:
                    print(f"Não foi possível recuperar o token do device {self.device_id}.")
            except Exception as e:
                print(f"Erro ao recuperar token do device no ThingsBoard: {e}")

        
        # Atualiza o campo etiqueta (label) do device no ThingsBoard
        if self.thingsboard_id and (self.system or self.unit):
            label = ""
            if self.system and self.unit:
                label = f"{self.system.name} - {self.unit.name}"
            elif self.system:
                label = self.system.name
            elif self.unit:
                label = self.unit.name
            try:
                THINGSBOARD_HOST = settings.THINGSBOARD_HOST.rstrip('/')
                THINGSBOARD_API_URL = f"{THINGSBOARD_HOST}/api"
                TB_USER = getattr(settings, "THINGSBOARD_USER", None)
                TB_PASSWORD = getattr(settings, "THINGSBOARD_PASSWORD", None)
                # Autentica e obtém JWT
                resp = requests.post(
                    f"{THINGSBOARD_API_URL}/auth/login",
                    json={"username": TB_USER, "password": TB_PASSWORD},
                    headers={"Content-Type": "application/json"}
                )
                resp.raise_for_status()
                jwt_token = resp.json().get("token")
                headers = {
                    "Content-Type": "application/json",
                    "X-Authorization": f"Bearer {jwt_token}"
                }
                # Recupera o device atual
                url_get = f"{THINGSBOARD_API_URL}/device/{self.thingsboard_id}"
                resp = requests.get(url_get, headers=headers)
                resp.raise_for_status()
                device_data = resp.json()
                # Atualiza o campo label
                device_data["label"] = label
                # Atualiza o device via POST em /api/device
                url_update = f"{THINGSBOARD_API_URL}/device"
                resp = requests.post(url_update, headers=headers, data=json.dumps(device_data))
                if resp.status_code in (200, 201):
                    print(f"Etiqueta (label) atualizada para o device {self.device_id} no ThingsBoard.")
                else:
                    print(f"Erro ao atualizar etiqueta: {resp.status_code} - {resp.text}")
            except Exception as e:
                print(f"Erro ao atualizar etiqueta do device no ThingsBoard: {e}")