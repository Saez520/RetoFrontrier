"""Fábricas de prueba: sin lectura de ``.env`` ni tráfico de red."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def test_token() -> str:
    return "token-de-prueba"


@pytest.fixture
def other_token() -> str:
    return "otro-token"


@pytest.fixture
def write_jsonl(tmp_path):
    def _write(lines, name="experimentos.jsonl"):
        path = tmp_path / name
        with path.open("w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return path

    return _write


@pytest.fixture
def write_manifest(tmp_path):
    def _write(cases, name="reference_cases.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def reference_data():
    """Evidencia y selectores sintéticos para la suite.

    Son fixtures de prueba, no observaciones del servicio original.
    """
    evidence = [
        {"id": 1, "status": 200, "response": {"status": "listo"}},
        {"id": 2, "status": 401, "response": {"error": "E100", "mensaje": "falta credencial"}},
        {"id": 3, "status": 403, "response": {"error": "E101", "mensaje": "credencial distinta"}},
        {"id": 4, "status": 200, "response": {"reiniciado": True}},
        {"id": 5, "status": 401, "response": {"error": "E100", "mensaje": "falta credencial"}},
        {"id": 6, "status": 403, "response": {"error": "E101", "mensaje": "credencial distinta"}},
        {"id": 7, "status": 401, "response": {"error": "E100", "mensaje": "falta credencial"}},
        {"id": 8, "status": 403, "response": {"error": "E101", "mensaje": "credencial distinta"}},
        {"id": 9, "status": 404, "response": {"error": "E404", "mensaje": "ruta no existe"}},
        {"id": 10, "status": 401, "response": {"error": "E100", "mensaje": "falta credencial"}},
        {"id": 11, "status": 403, "response": {"error": "E101", "mensaje": "credencial distinta"}},
    ]
    cases = [
        {"method": "GET", "path": "/health", "auth": "valid", "evidence_id": 1},
        {"method": "GET", "path": "/health", "auth": "missing", "evidence_id": 2},
        {"method": "GET", "path": "/health", "auth": "invalid", "evidence_id": 3},
        {"method": "POST", "path": "/__reset", "auth": "valid", "evidence_id": 4},
        {"method": "POST", "path": "/__reset", "auth": "missing", "evidence_id": 5},
        {"method": "POST", "path": "/__reset", "auth": "invalid", "evidence_id": 6},
        {"method": "POST", "path": "/msg", "auth": "missing", "evidence_id": 7},
        {"method": "POST", "path": "/msg", "auth": "invalid", "evidence_id": 8},
        {"fallback": True, "auth": "valid", "evidence_id": 9},
        {"fallback": True, "auth": "missing", "evidence_id": 10},
        {"fallback": True, "auth": "invalid", "evidence_id": 11},
    ]
    return {"evidence": evidence, "cases": cases}
