from django.db import models
from django.conf import settings
import requests
import json

DEVICE_RPC_METADATA = {
    "led": {
        "properties": {
            "status": {
                "rpc_read_method": "checkStatus",
                "rpc_write_method": "switchLed",
                "type": "Boolean"
            }
        }
    },
    "lightbulb": {
        "properties": {
            "status": {
                "rpc_read_method": "checkStatus",
                "rpc_write_method": "switchLed",
                "type": "Boolean"
            }
        }
    },
    "temperature sensor": {
        "properties": {
            "temperature": {
                "rpc_read_method": "checkStatus",
                "type": "Double"
            }
        }
    },
    "soilhumidity sensor": {
        "properties": {
            "humidity": {
                "rpc_read_method": "checkStatus",
                "type": "Double"
            }
        }
    },
    "gas sensor": {
        "properties": {
            # Adicione propriedades se necessário
        }
    },
    "airconditioner": {
        "properties": {
            "temperature": {
                "rpc_read_method": "checkStatus",
                "type": "Double"
            },
            "humidity": {
                "rpc_read_method": "checkStatus",
                "type": "Double"
            },
            "status": {
                "rpc_read_method": "checkStatus",
                "rpc_write_method": "switchStatus",
                "type": "Boolean"
            }
        }
    },
    "pump": {
        "properties": {
            "status": {
                "rpc_read_method": "checkStatus",
                "rpc_write_method": "switchPump",
                "type": "Boolean"
            }
        }
    },
    "pool": {
        "properties": {
            "status": {
                "rpc_read_method": "checkStatus",
                "rpc_write_method": "switchPool",
                "type": "Boolean"
            }
        }
    },
    "garden": {
        "properties": {
            # Adicione propriedades se necessário
        }
    },
    "irrigation": {
        "properties": {
            "status": {
                "rpc_read_method": "checkStatus",
                "rpc_write_method": "switchIrrigation",
                "type": "Boolean"
            }
        }
    }
}

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

    def get_rpc_metadata(self):
        device_type_name = self.device_type.name.lower()
        return DEVICE_RPC_METADATA.get(device_type_name, {})

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        # Sempre tenta garantir thingsboard_id e token válidos
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

        # Busca ou cria o device no ThingsBoard
        url_search = f"{THINGSBOARD_API_URL}/tenant/devices?deviceName={self.device_id}"
        tb_device_id = None
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
                    print(f"Device {self.device_id} já existe no ThingsBoard (409). Buscando ID...")
                    # Busca o ID mesmo assim
                    resp = requests.get(url_search, headers=headers)
                    if resp.status_code == 200 and resp.json().get("data"):
                        tb_device_id = resp.json()["data"][0]["id"]["id"]
                else:
                    print(f"Erro ao criar device no ThingsBoard: {resp.status_code} - {resp.text}")
                    return
            # Salva o thingsboard_id no modelo se mudou
            if tb_device_id and self.thingsboard_id != tb_device_id:
                self.thingsboard_id = tb_device_id
                super().save(update_fields=["thingsboard_id"])
        except Exception as e:
            print(f"Erro ao consultar/criar device no ThingsBoard: {e}")
            return

        # Sempre tenta buscar e salvar o token
        try:
            url_token = f"{THINGSBOARD_API_URL}/device/{tb_device_id}/credentials"
            resp = requests.get(url_token, headers=headers)
            resp.raise_for_status()
            device_token = resp.json().get("credentialsId")
            if device_token:
                if self.token != device_token:
                    self.token = device_token
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
                # if resp.status_code in (200, 201):
                #     print(f"Etiqueta (label) atualizada para o device {self.device_id} no ThingsBoard.")
                # else:
                #     print(f"Erro ao atualizar etiqueta: {resp.status_code} - {resp.text}")
            except Exception as e:
                print(f"Erro ao atualizar etiqueta do device no ThingsBoard: {e}")
        # Após atualizar o label, envie os atributos compartilhados/client-side
        if self.thingsboard_id:
            rpc_metadata = self.get_rpc_metadata()
            if rpc_metadata:
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
                    # Envia como atributo compartilhado (shared)
                    url_shared = f"{THINGSBOARD_API_URL}/plugins/telemetry/DEVICE/{self.thingsboard_id}/SHARED_SCOPE"
                    resp = requests.post(url_shared, headers=headers, json=rpc_metadata)
                    if resp.status_code in (200, 201):
                        print(f"Metadados RPC enviados como atributo compartilhado para o device {self.device_id}.")
                    else:
                        print(f"Erro ao enviar metadados RPC (shared): {resp.status_code} - {resp.text}")
                    # Se quiser enviar como client-side attribute, troque SHARED_SCOPE por CLIENT_SCOPE
                    # url_client = f"{THINGSBOARD_API_URL}/plugins/telemetry/DEVICE/{self.thingsboard_id}/CLIENT_SCOPE"
                    # requests.post(url_client, headers=headers, json=rpc_metadata)
                except Exception as e:
                    print(f"Erro ao enviar metadados RPC para o ThingsBoard: {e}")