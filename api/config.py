"""Configuración por variables de entorno (nada sensible en el código)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _int(n, d):
    try:
        return int(os.environ.get(n, d))
    except ValueError:
        return d


@dataclass(frozen=True)
class Config:
    # Acceso: contraseña para la interfaz y claves para integraciones (separadas por coma).
    clave: str = field(default_factory=lambda: os.environ.get("PACKSIM_CLAVE", ""))
    api_keys: tuple = field(default_factory=lambda: tuple(k.strip() for k in os.environ.get("PACKSIM_API_KEYS", "").split(",") if k.strip()))
    # Firma de las cookies de sesión. Si falta, se genera una al arrancar (las sesiones no sobreviven a un reinicio).
    secreto: str = field(default_factory=lambda: os.environ.get("PACKSIM_SECRETO") or secrets.token_hex(32))
    sesion_horas: int = field(default_factory=lambda: _int("PACKSIM_SESION_HORAS", 12))
    # Límites
    tamano_max_mb: int = field(default_factory=lambda: _int("PACKSIM_TAMANO_MAX_MB", 50))
    tiempo_max_s: int = field(default_factory=lambda: _int("PACKSIM_TIEMPO_MAX_S", 120))
    tiempo_max_fisica_s: int = field(default_factory=lambda: _int("PACKSIM_TIEMPO_MAX_FISICA_S", 240))
    memoria_max_mb: int = field(default_factory=lambda: _int("PACKSIM_MEMORIA_MAX_MB", 2048))
    trabajos_paralelos: int = field(default_factory=lambda: _int("PACKSIM_TRABAJOS_PARALELOS", 2))
    trabajos_max_en_memoria: int = field(default_factory=lambda: _int("PACKSIM_TRABAJOS_MAX", 200))
    vencimiento_s: int = field(default_factory=lambda: _int("PACKSIM_VENCIMIENTO_S", 3600))
    limite_por_hora: int = field(default_factory=lambda: _int("PACKSIM_LIMITE_POR_HORA", 120))
    # HTTPS detrás del proxy de Railway → cookies "Secure"
    cookies_seguras: bool = field(default_factory=lambda: os.environ.get("PACKSIM_COOKIES_SEGURAS", "1") != "0")

    @property
    def abierta(self) -> bool:
        """Sin contraseña ni claves: modo desarrollo (solo para correr local)."""
        return not self.clave and not self.api_keys
