"""Configuración del servicio leída desde el entorno.

La credencial del equipo se lee exclusivamente de ``TEAM_TOKEN`` y nunca se
escribe en archivos, respuestas ni diagnósticos. ``REFERENCE_RESPONSES_PATH``
apunta al JSONL de respuestas de referencia, de solo lectura.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_REFERENCES_PATH = "experimentos.jsonl"


@dataclass(frozen=True)
class Settings:
    """Configuración inmutable y su estado de disponibilidad."""

    token: str
    references_path: str
    ready: bool
    reason: str


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Carga la configuración y determina si está lista.

    Un token vacío, una ruta inexistente o un archivo no legible producen una
    configuración no lista con una razón apta para el operador y sin secretos.
    """
    env: Mapping[str, str] = os.environ if environ is None else environ

    token = (env.get("TEAM_TOKEN") or "").strip()
    references_path = (env.get("REFERENCE_RESPONSES_PATH") or "").strip() or DEFAULT_REFERENCES_PATH

    if not token:
        return Settings(
            token="",
            references_path=references_path,
            ready=False,
            reason="falta la credencial del equipo",
        )
    if not os.path.isfile(references_path):
        return Settings(
            token=token,
            references_path=references_path,
            ready=False,
            reason=f"no se encontró el archivo de respuestas de referencia: {references_path}",
        )
    if not os.access(references_path, os.R_OK):
        return Settings(
            token=token,
            references_path=references_path,
            ready=False,
            reason=f"el archivo de respuestas de referencia no es legible: {references_path}",
        )
    return Settings(token=token, references_path=references_path, ready=True, reason="")
