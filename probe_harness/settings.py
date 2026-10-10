"""Configuración fija del probe-harness y lectura segura de ``.env``.

Los límites de ritmo, presupuesto y cierre son constantes de política: la
configuración de ejecución no puede ampliarlos ni desactivarlos. El único valor
que sale de ``.env`` es el token del equipo, que nunca se reproduce.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Base del servicio original. Solo puede sobrescribirse por argumento explícito
# de pruebas locales (``--base-url``).
ORACLE_BASE_URL = "https://caja-negra-production-c64f.up.railway.app"

# Política de envío, inmutable durante la ejecución.
MAX_CALLS = 1000
CALLS_PER_SECOND = 8
MIN_INTERVAL_SECONDS = 1.0 / CALLS_PER_SECOND  # 125 ms
RETRY_WAITS = (1.0, 5.0)  # hasta dos reintentos ante infraestructura

# Corte absoluto: 2026-10-11 01:00 UTC == 2026-10-10 20:00 (UTC-05).
CUTOFF_AT = datetime(2026, 10, 11, 1, 0, 0, tzinfo=timezone.utc)

# Semilla por defecto del generador combinatorio E8.
DEFAULT_SEED = 20261010

# Estado inicial asumido del consumo del token, pendiente de verificación factual.
ASSUMED_PRIOR_CONSUMPTION = 0

# Reintento de seguimiento E7: cada hora desde el arranque más 19:50 UTC-05.
E7_SPECIAL_LOCAL = (19, 50)
LOCAL_UTC_OFFSET_HOURS = -5

# Contexto de red.
REQUEST_TIMEOUT_SECONDS = 5.0
TOKEN_ENV_VAR = "ORACLE_TOKEN"
DEFAULT_LOG_PATH = "experimentos.jsonl"
DEFAULT_STATE_PATH = ".probe-state.json"
EXAMPLES_PATH = "docs/material/ejemplos.jsonl"

INVALID_TOKEN_LITERAL = "Bearer probe-invalid-token"


class ConfigError(Exception):
    """Error de configuración que impide iniciar la ejecución."""


def redact(value: Optional[str]) -> str:
    """Representación segura de un valor sensible."""

    return "[REDACTED]" if value else ""


def _parse_dotenv_text(text: str) -> dict:
    values: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def read_dotenv(path: str | os.PathLike = ".env") -> dict:
    """Lectura mínima de ``.env``; no modifica el archivo.

    Solo devuelve las claves declaradas; no imprime ni expone valores.
    """

    p = Path(path)
    if not p.exists():
        return {}
    try:
        return _parse_dotenv_text(p.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - defensivo
        raise ConfigError(f"no se pudo leer {p.name}") from exc



def load_token(env: Optional[dict] = None, dotenv_path: str | os.PathLike = ".env") -> str:
    """Obtiene ``ORACLE_TOKEN`` del entorno o de ``.env``.

    Falla con un mensaje que no reproduce el secreto cuando el valor falta o
    está vacío.
    """

    source = os.environ if env is None else env
    token = source.get(TOKEN_ENV_VAR)
    if token is None and env is None:
        token = read_dotenv(dotenv_path).get(TOKEN_ENV_VAR)
    if token is None or token.strip() == "":
        raise ConfigError(f"{TOKEN_ENV_VAR} requerido")
    return token


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
