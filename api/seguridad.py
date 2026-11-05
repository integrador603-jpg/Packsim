"""Acceso por contraseña (cookie firmada) o API key, y límite de frecuencia por IP."""
from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

COOKIE = "packsim_sesion"


def _firmar(secreto: str, datos: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(secreto.encode(), datos.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def crear_token(secreto: str, horas: int) -> str:
    vence = str(int(time.time()) + horas * 3600)
    return f"{vence}.{_firmar(secreto, vence)}"


def token_valido(secreto: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    vence, firma = token.split(".", 1)
    if not vence.isdigit() or int(vence) < time.time():
        return False
    return hmac.compare_digest(firma, _firmar(secreto, vence))


def clave_correcta(esperada: str, recibida: str) -> bool:
    return bool(esperada) and hmac.compare_digest(esperada.encode(), (recibida or "").encode())


def exigir_acceso(request: Request):
    cfg = request.app.state.cfg
    if cfg.abierta:
        return
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and any(hmac.compare_digest(auth[7:].strip().encode(), k.encode()) for k in cfg.api_keys):
        return
    if token_valido(cfg.secreto, request.cookies.get(COOKIE)):
        return
    raise HTTPException(status_code=401, detail="Iniciá sesión para usar el simulador.")


class LimiteFrecuencia:
    """Ventana deslizante de 1 hora por IP (en memoria)."""

    def __init__(self, por_hora: int):
        self.por_hora = por_hora
        self._h: dict[str, deque] = {}
        self._lock = threading.Lock()

    def permitir(self, ip: str) -> bool:
        ahora = time.time()
        with self._lock:
            q = self._h.setdefault(ip, deque())
            while q and ahora - q[0] > 3600:
                q.popleft()
            if len(q) >= self.por_hora:
                return False
            q.append(ahora)
            return True


def ip_cliente(request: Request) -> str:
    # Railway y la mayoría de los proxies agregan X-Forwarded-For; se usa la primera IP.
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?")
