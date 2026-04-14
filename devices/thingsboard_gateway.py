from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests
from django.core.cache import cache


JWT_CACHE_PREFIX = "tb_gateway_jwt_"
JWT_CACHE_TIMEOUT_SECONDS = 2 * 60 * 60


@dataclass
class GatewayConnection:
    base_url: str
    mqtt_host: str
    mqtt_port: int
    mqtt_keep_alive: int


def _normalize_base_url(base_url: str) -> str:
    value = (base_url or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    return value.rstrip("/")


def _get_gateway_model():
    from devices.models import GatewayIOT

    return GatewayIOT


def get_active_gateway(required: bool = True):
    GatewayIOT = _get_gateway_model()
    gateway = GatewayIOT.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
    if required and not gateway:
        raise RuntimeError("Nenhum GatewayIOT ativo encontrado.")
    return gateway


def get_gateway_connection(gateway=None, required: bool = True) -> Optional[GatewayConnection]:
    gateway = gateway or get_active_gateway(required=required)
    if not gateway:
        return None

    base_url = _normalize_base_url(gateway.base_url)
    parsed = urlparse(base_url)
    mqtt_host = parsed.hostname or ""

    return GatewayConnection(
        base_url=base_url,
        mqtt_host=mqtt_host,
        mqtt_port=gateway.mqtt_port,
        mqtt_keep_alive=gateway.mqtt_keep_alive,
    )


def _jwt_cache_key(gateway_id: int) -> str:
    return f"{JWT_CACHE_PREFIX}{gateway_id}"


def get_management_headers(gateway=None, force_refresh: bool = False) -> dict:
    gateway = gateway or get_active_gateway(required=True)

    if gateway.auth_method == gateway.AUTH_METHOD_API_KEY:
        return {
            "Content-Type": "application/json",
            "X-Authorization": f"ApiKey {gateway.api_key}",
        }

    if gateway.auth_method != gateway.AUTH_METHOD_USER_PASSWORD:
        raise RuntimeError(f"Metodo de autenticacao nao suportado: {gateway.auth_method}")

    cache_key = _jwt_cache_key(gateway.id)
    jwt_token = None if force_refresh else cache.get(cache_key)

    if not jwt_token:
        connection = get_gateway_connection(gateway)
        response = requests.post(
            f"{connection.base_url}/api/auth/login",
            json={"username": gateway.username, "password": gateway.password},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        jwt_token = response.json().get("token")
        if not jwt_token:
            raise RuntimeError("ThingsBoard nao retornou token JWT no login.")
        cache.set(cache_key, jwt_token, timeout=JWT_CACHE_TIMEOUT_SECONDS)

    return {
        "Content-Type": "application/json",
        "X-Authorization": f"Bearer {jwt_token}",
    }


def clear_gateway_auth_cache(gateway=None):
    gateway = gateway or get_active_gateway(required=False)
    if not gateway:
        return
    cache.delete(_jwt_cache_key(gateway.id))


def test_gateway_connection(gateway=None) -> tuple[bool, str]:
    gateway = gateway or get_active_gateway(required=True)
    try:
        connection = get_gateway_connection(gateway)
        headers = get_management_headers(gateway=gateway, force_refresh=True)
        response = requests.get(
            f"{connection.base_url}/api/auth/user",
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            return True, "ok"
        return False, f"status_{response.status_code}"
    except Exception as exc:
        return False, str(exc)
