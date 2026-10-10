"""Catálogo de respuestas de referencia y su trazabilidad por evidencia.

El catálogo lee el JSONL de evidencia en modo solo lectura, indexa cada línea
por ``id`` y resuelve, para cada combinación de método, ruta y modalidad de
autenticación, la respuesta registrada. Un manifiesto sin secretos
(``reference_cases.json``) selecciona qué líneas de evidencia usar.

Objetos y listas se emiten como JSON UTF-8 compacto; los textos se emiten como
texto UTF-8 literal, sin correcciones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .settings import Settings

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"

AUTH_MODES = ("valid", "missing", "invalid")
FALLBACK = "fallback"
DEFAULT_MANIFEST_PATH = "reference_cases.json"

# Selectores mínimos exigidos por el contrato de esta fase.
REQUIRED_SELECTORS: tuple[tuple[str, str, str], ...] = (
    ("GET", "/health", "valid"),
    ("GET", "/health", "missing"),
    ("GET", "/health", "invalid"),
    ("POST", "/__reset", "valid"),
    ("POST", "/__reset", "missing"),
    ("POST", "/__reset", "invalid"),
    ("POST", "/msg", "missing"),
    ("POST", "/msg", "invalid"),
    (FALLBACK, FALLBACK, "valid"),
    (FALLBACK, FALLBACK, "missing"),
    (FALLBACK, FALLBACK, "invalid"),
)


@dataclass(frozen=True)
class ReferenceResponse:
    """Respuesta lista para emitir: status, cuerpo y tipo de contenido."""

    status: int
    body: bytes
    content_type: str


def build_reference_response(status: int, response: Any) -> ReferenceResponse:
    """Construye una respuesta desde el valor ``response`` de una línea.

    ``dict``/``list`` se serializan como JSON UTF-8 compacto conservando el
    orden de las listas; ``str`` se emite como texto UTF-8 literal.
    """
    if isinstance(response, str):
        return ReferenceResponse(status=status, body=response.encode("utf-8"), content_type=TEXT_CONTENT_TYPE)
    body = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return ReferenceResponse(status=status, body=body, content_type=JSON_CONTENT_TYPE)


@dataclass(frozen=True)
class Catalog:
    """Conjunto resuelto de respuestas de referencia."""

    ready: bool
    reason: str
    _exact: Mapping[tuple[str, str, str], ReferenceResponse] = field(default_factory=dict)
    _fallback: Mapping[str, ReferenceResponse] = field(default_factory=dict)
    used_evidence_ids: tuple[int, ...] = ()

    def resolve(self, method: str, path: str, auth: str) -> ReferenceResponse | None:
        """Resuelve una respuesta; el selector exacto gana al fallback."""
        if not self.ready:
            return None
        exact = self._exact.get((method.upper(), path, auth))
        if exact is not None:
            return exact
        return self._fallback.get(auth)


def unavailable_catalog(reason: str) -> Catalog:
    """Catálogo no listo con razón apta para el operador."""
    return Catalog(ready=False, reason=reason)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_evidence_line(raw: str) -> tuple[int, int, Any]:
    """Valida una línea de evidencia y devuelve ``(id, status, response)``."""
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("la línea de evidencia no es un objeto JSON")

    evidence_id = obj.get("id")
    if not _is_int(evidence_id) or evidence_id <= 0:
        raise ValueError("la línea de evidencia no tiene un id entero positivo")

    status = obj.get("status")
    if not _is_int(status) or not 100 <= status <= 599:
        raise ValueError("la línea de evidencia no tiene un status HTTP entero")

    if "response" not in obj:
        raise ValueError("la línea de evidencia no tiene response")
    response = obj["response"]
    if not isinstance(response, (dict, list, str)):
        raise ValueError("el response de la evidencia no es objeto, lista o texto")

    return evidence_id, status, response


def _load_index(evidence_path: str) -> tuple[dict[int, ReferenceResponse] | None, str]:
    try:
        text = Path(evidence_path).read_text(encoding="utf-8")
    except OSError:
        return None, f"no se pudo leer el archivo de respuestas de referencia: {evidence_path}"

    index: dict[int, ReferenceResponse] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            evidence_id, status, response = _parse_evidence_line(raw)
        except (json.JSONDecodeError, ValueError):
            return None, f"la evidencia contiene una línea inválida (línea {lineno})"
        if evidence_id in index:
            return None, f"la evidencia repite el id {evidence_id}"
        index[evidence_id] = build_reference_response(status, response)
    return index, ""


def _load_manifest(manifest_path: str) -> tuple[list[Any] | None, str]:
    try:
        text = Path(manifest_path).read_text(encoding="utf-8")
    except OSError:
        return None, f"no se pudo leer el manifiesto de referencias: {manifest_path}"
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        return None, "el manifiesto de referencias no es JSON válido"
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        return None, "el manifiesto de referencias no tiene una lista 'cases'"
    return manifest["cases"], ""


def _parse_cases(
    cases: list[Any], index: Mapping[int, ReferenceResponse]
) -> tuple[dict[tuple[str, str, str], ReferenceResponse] | None, dict[str, ReferenceResponse] | None, tuple[int, ...], str]:
    exact: dict[tuple[str, str, str], ReferenceResponse] = {}
    fallback: dict[str, ReferenceResponse] = {}
    used: list[int] = []
    seen: set[tuple[Any, ...]] = set()

    for position, case in enumerate(cases):
        if not isinstance(case, dict):
            return None, None, (), f"el caso {position} del manifiesto no es un objeto"

        auth = case.get("auth")
        if auth not in AUTH_MODES:
            return None, None, (), f"el caso {position} no declara una modalidad de autenticación válida"

        evidence_id = case.get("evidence_id")
        if not _is_int(evidence_id) or evidence_id <= 0:
            return None, None, (), f"el caso {position} no declara un evidence_id positivo"

        method = case.get("method")
        path = case.get("path")
        is_fallback = case.get("fallback") is True

        if is_fallback:
            if method is not None or path is not None:
                return None, None, (), f"el caso {position} marca fallback y además declara método o ruta"
            key: tuple[Any, ...] = (FALLBACK, auth)
        else:
            if not isinstance(method, str) or not isinstance(path, str):
                return None, None, (), f"el caso {position} no declara método y ruta"
            key = (method.upper(), path, auth)

        if key in seen:
            return None, None, (), f"el manifiesto repite el selector del caso {position}"
        seen.add(key)

        if evidence_id not in index:
            return None, None, (), f"el evidence_id {evidence_id} no existe en la evidencia"
        used.append(evidence_id)

        if is_fallback:
            fallback[auth] = index[evidence_id]
        else:
            # ``key`` ya está normalizado con method en mayúsculas.
            exact[key] = index[evidence_id]  # type: ignore[index]

    return exact, fallback, tuple(used), ""


def _missing_required(
    exact: Mapping[tuple[str, str, str], ReferenceResponse],
    fallback: Mapping[str, ReferenceResponse],
) -> str:
    for method, path, auth in REQUIRED_SELECTORS:
        if method == FALLBACK:
            if auth not in fallback:
                return f"falta el selector de reserva para la modalidad {auth}"
        elif (method, path, auth) not in exact:
            return f"falta el selector {method} {path} ({auth})"
    return ""


def load_catalog(settings: Settings, manifest_path: str = DEFAULT_MANIFEST_PATH) -> Catalog:
    """Carga el catálogo de referencias y calcula su disponibilidad.

    El servicio queda no listo si el JSONL no es legible, una línea es
    inválida, el manifiesto no resuelve sus selectores requeridos o falta una
    respuesta seleccionada.
    """
    cases, reason = _load_manifest(manifest_path)
    if cases is None:
        return unavailable_catalog(reason)

    index, reason = _load_index(settings.references_path)
    if index is None:
        return unavailable_catalog(reason)

    exact, fallback, used, reason = _parse_cases(cases, index)
    if exact is None or fallback is None:
        return unavailable_catalog(reason)

    missing = _missing_required(exact, fallback)
    if missing:
        return unavailable_catalog(missing)

    return Catalog(ready=True, reason="", _exact=exact, _fallback=fallback, used_evidence_ids=used)
