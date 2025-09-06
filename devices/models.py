from django.db import models
from django.conf import settings
import requests
import json
import time
import re
import random

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

        # Busca ou cria o device no ThingsBoard com tentativas e reconciliação
        from urllib.parse import quote_plus
        url_search = f"{THINGSBOARD_API_URL}/tenant/devices?deviceName={quote_plus(self.device_id)}"
        tb_device_id = None
        max_attempts = 12
        attempt = 0
        last_was_conflict = False

        def _extract_device_id_from_search(resp):
            """Handle multiple TB search response shapes and return internal id or None."""
            try:
                body = resp.json()
            except Exception:
                return None
            # Common TB shapes:
            # 1) {"data": [{"id": {"id":"..."}, ...}], ...}
            # 2) {"id": {"id":"..."}, "name": "...", ...}  (single object)
            # 3) [] or list of devices
            if isinstance(body, dict):
                if body.get("data") and isinstance(body.get("data"), list) and len(body.get("data"))>0:
                    try:
                        return body["data"][0]["id"]["id"]
                    except Exception:
                        return None
                if body.get("id") and isinstance(body.get("id"), dict) and body.get("id").get("id"):
                    return body.get("id").get("id")
            if isinstance(body, list) and len(body) > 0:
                try:
                    if isinstance(body[0], dict) and body[0].get("id") and isinstance(body[0].get("id"), dict):
                        return body[0]["id"]["id"]
                except Exception:
                    return None
            return None

        while attempt < max_attempts:
            attempt += 1
            try:
                resp = requests.get(url_search, headers=headers, timeout=6)
                if resp.status_code == 200:
                    found_id = _extract_device_id_from_search(resp)
                    if found_id:
                        tb_device_id = found_id
                        last_was_conflict = False
                        break
                    else:
                        # Debug: log empty or unexpected search response for diagnosis
                        try:
                            print(f"Busca retornou vazio/inedito para {self.device_id}: status={resp.status_code} body={resp.text[:800]}")
                        except Exception:
                            pass

                # not found -> try create
                payload = {
                    "name": self.device_id,
                    "type": self.device_type.name if hasattr(self.device_type, "name") else "default"
                }
                url_create = f"{THINGSBOARD_API_URL}/device"
                resp = requests.post(url_create, headers=headers, data=json.dumps(payload), timeout=6)
                if resp.status_code in (200, 201):
                    # creation succeeded, extract id robustly
                    try:
                        created = resp.json()
                        if isinstance(created, dict) and created.get("id") and isinstance(created.get("id"), dict):
                            tb_device_id = created["id"]["id"]
                        else:
                            # fallback: re-run a search to obtain id
                            time.sleep(0.5)
                            resp2 = requests.get(url_search, headers=headers, timeout=6)
                            tb_device_id = _extract_device_id_from_search(resp2)
                        print(f"Device {self.device_id} criado no ThingsBoard.")
                        break
                    except Exception:
                        pass
                elif resp.status_code == 409 or (resp.status_code == 400 and resp.text and 'Device with such name already exists' in resp.text):
                    # Name conflict: try search again to recover the existing device id
                    resp2 = requests.get(url_search, headers=headers, timeout=6)
                    found_id = None
                    if resp2.status_code == 200:
                        found_id = _extract_device_id_from_search(resp2)
                    if found_id:
                        tb_device_id = found_id
                        print(f"Device {self.device_id} aparentemente existe no ThingsBoard (recuperado via busca).")
                        last_was_conflict = True
                        break
                    else:
                        print(f"Device {self.device_id} conflitou (409/400) mas não foi encontrado via busca; tentativa {attempt}/{max_attempts}")
                        last_was_conflict = True
                else:
                    print(f"Erro ao criar device no ThingsBoard: {resp.status_code} - {resp.text[:200]}; tentativa {attempt}/{max_attempts}")
                    last_was_conflict = False
            except requests.exceptions.RequestException as e:
                # If ThingsBoard is unreachable (connection refused/timeout), do NOT clear local token.
                if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
                    print(f"ThingsBoard inacessível na tentativa {attempt}: {e}. Mantendo thingsboard_id/token locais e abortando tentativa agora; será tentado depois.")
                    return
                print(f"Erro HTTP na tentativa {attempt} ao consultar/criar device no ThingsBoard: {e}")
                last_was_conflict = False

            # Reconcilia: limpa mapping local e tenta novamente após backoff+jitter
            if tb_device_id is None:
                # Only clear local mapping when the failure was NOT a name-conflict.
                if not last_was_conflict and (self.thingsboard_id or self.token):
                    print(f"Reconciliação: limpando thingsboard_id/token locais para {self.device_id} e tentando novamente.")
                    self.thingsboard_id = None
                    self.token = ''
                    try:
                        super().save(update_fields=["thingsboard_id", "token"])
                    except Exception:
                        pass
                # exponential backoff with jitter
                sleep_sec = min(2 ** attempt, 10) + random.uniform(0, 0.5)
                time.sleep(sleep_sec)

        if tb_device_id is None:
            print(f"Falha ao garantir device {self.device_id} no ThingsBoard após {max_attempts} tentativas.")
            return

        # Salva o thingsboard_id no modelo se mudou
        if tb_device_id and self.thingsboard_id != tb_device_id:
            self.thingsboard_id = tb_device_id
            try:
                super().save(update_fields=["thingsboard_id"])
            except Exception:
                pass

        # Sempre tenta buscar e salvar o token
        try:
            url_token = f"{THINGSBOARD_API_URL}/device/{tb_device_id}/credentials"
            resp = requests.get(url_token, headers=headers, timeout=5)
            if resp.status_code != 200:
                # credentials endpoint did not return 200. Try to recover existing device by name and fetch credentials.
                print(f"Credenciais indisponiveis (status {resp.status_code}) para {self.device_id}; tentando recuperar por nome...")
                try:
                    resp2 = requests.get(url_search, headers=headers, timeout=5)
                    if resp2.status_code == 200 and resp2.json().get("data"):
                        tb_device_id = resp2.json()["data"][0]["id"]["id"]
                        # try credentials again for recovered id
                        url_token = f"{THINGSBOARD_API_URL}/device/{tb_device_id}/credentials"
                        resp_token = requests.get(url_token, headers=headers, timeout=5)
                        if resp_token.status_code == 200 and resp_token.json().get("credentialsId"):
                            resp = resp_token
                        else:
                            # If credentials still not available, consider deleting remote device if allowed
                            allow_delete = getattr(settings, "ALLOW_THINGSBOARD_DELETE", False)
                            if allow_delete:
                                try:
                                    # delete remote device
                                    del_url = f"{THINGSBOARD_API_URL}/device/{tb_device_id}"
                                    del_resp = requests.delete(del_url, headers=headers, timeout=5)
                                    if del_resp.status_code in (200, 204):
                                        print(f"Device {self.device_id} removido no ThingsBoard por reconciliação (ALLOW_THINGSBOARD_DELETE=True). Tentando recriar.")
                                        payload = {"name": self.device_id, "type": self.device_type.name if hasattr(self.device_type, "name") else "default"}
                                        resp3 = requests.post(f"{THINGSBOARD_API_URL}/device", headers=headers, data=json.dumps(payload), timeout=5)
                                        if resp3.status_code in (200, 201):
                                            tb_device_id = resp3.json()["id"]["id"]
                                            # update url_token
                                            url_token = f"{THINGSBOARD_API_URL}/device/{tb_device_id}/credentials"
                                            resp = requests.get(url_token, headers=headers, timeout=5)
                                    else:
                                        print(f"Falha ao deletar device remoto {self.device_id}: {del_resp.status_code} - {del_resp.text}")
                                except requests.exceptions.RequestException as e:
                                    print(f"Erro ao tentar deletar device remoto {self.device_id}: {e}")
                            else:
                                print(f"ALLOW_THINGSBOARD_DELETE=False e credenciais ausentes para {self.device_id}; não será possível recriar automaticamente.")
                    else:
                        # device still not found by name; try creating normally
                        payload = {"name": self.device_id, "type": self.device_type.name if hasattr(self.device_type, "name") else "default"}
                        resp3 = requests.post(f"{THINGSBOARD_API_URL}/device", headers=headers, data=json.dumps(payload), timeout=5)
                        if resp3.status_code in (200, 201):
                            tb_device_id = resp3.json()["id"]["id"]
                            url_token = f"{THINGSBOARD_API_URL}/device/{tb_device_id}/credentials"
                            resp = requests.get(url_token, headers=headers, timeout=5)
                except requests.exceptions.RequestException as e:
                    print(f"Erro adicional ao tentar reconciliar device {self.device_id}: {e}")
                if not tb_device_id:
                    print(f"Nao foi possivel reconciliar device {self.device_id} para obter token.")
                    return

            resp.raise_for_status()
            device_token = resp.json().get("credentialsId")
            if device_token:
                if self.token != device_token:
                    self.token = device_token
                    try:
                        super().save(update_fields=["token"])
                    except Exception:
                        pass
                print(f"Token do device {self.device_id} salvo no modelo.")
            else:
                print(f"Não foi possivel recuperar o token do device {self.device_id}.")
        except requests.exceptions.RequestException as e:
            # For connection-level errors, keep existing token locally and try later
            if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
                print(f"ThingsBoard inacessível ao recuperar token para {self.device_id}: {e}. Mantendo token local e tentando mais tarde.")
                return
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