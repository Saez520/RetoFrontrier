"""Pruebas de integración HTTP del servicio."""

from __future__ import annotations

import socket

import pytest

from replacement.app import create_app
from replacement.references import load_catalog, unavailable_catalog
from replacement.settings import Settings

AUTH = {"Authorization": "Bearer token-de-prueba"}
OTHER = {"Authorization": "Bearer otro-token"}


def _settings(evidence_path, *, ready=True, reason="") -> Settings:
    return Settings(token="token-de-prueba", references_path=str(evidence_path), ready=ready, reason=reason)


@pytest.fixture
def client(write_jsonl, write_manifest, reference_data):
    evidence_path = write_jsonl(reference_data["evidence"])
    manifest_path = write_manifest(reference_data["cases"])
    settings = _settings(evidence_path)
    catalog = load_catalog(settings, str(manifest_path))
    assert catalog.ready is True
    app = create_app(settings, catalog)
    return app.test_client()


# --- Rutas conocidas ---------------------------------------------------------


def test_health_valid_returns_reference(client):
    response = client.get("/health", headers=AUTH)
    assert response.status_code == 200
    assert response.get_json() == {"status": "listo"}


def test_reset_valid_is_idempotent_and_ping_stays_special(client):
    first = client.post("/__reset", headers=AUTH)
    second = client.post("/__reset", headers=AUTH)

    assert first.status_code == second.status_code == 200
    assert first.get_json() == {"reiniciado": True}

    response = client.post("/msg", headers=AUTH, json={"m": "PING;64"})
    assert response.status_code == 200
    assert response.get_json() == {"pong": True}


KNOWN_VALID_CONTROLS = (
    "ALTA;Lucia;82",
    "ALTA;Mateo;3",
    "CONSULTA;AC-0001;14",
    "CONSULTA;AC-0002;11",
    "CONSULTA;AC-0009;87",
    "DEPOSITO;AC-0001;250000;86",
    "DEPOSITO;AC-0002;700;35",
    "TRANSFER;AC-0001;AC-0002;40000;86",
    "TRANSFER;AC-0001;AC-0002;120000;55",
    "TRANSFER;AC-0001;AC-0002;100000;12",
    "TRANSFER;AC-0002;AC-0001;50000;23",
    "ANULA;OP-0003;66",
)


@pytest.mark.parametrize("message", KNOWN_VALID_CONTROLS)
def test_msg_valid_control_preserves_stub(client, message):
    response = client.post("/msg", headers=AUTH, json={"m": message})
    assert response.status_code == 503
    assert response.get_data(as_text=True) == "aún no disponible"


def test_msg_invalid_numeric_control_returns_e202(client):
    response = client.post("/msg", headers=AUTH, json={"m": "ALTA;Lucia;83"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E202", "mensaje": "control inválido"}


def test_msg_malformed_control_returns_e201(client):
    response = client.post("/msg", headers=AUTH, json={"m": "DEPOSITO;AC-0002;700;5X"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E201", "mensaje": "control mal formado"}


def test_ping_any_numeric_control_returns_pong(client):
    for control in ("00", "3", "64", "98"):
        response = client.post("/msg", headers=AUTH, json={"m": f"PING;{control}"})
        assert response.status_code == 200
        assert response.get_json() == {"pong": True}


def test_ping_extra_arity_returns_e302(client):
    response = client.post("/msg", headers=AUTH, json={"m": "PING;extra;00"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E302", "mensaje": "aridad inválida"}


def test_ping_single_field_uses_stub(client):
    response = client.post("/msg", headers=AUTH, json={"m": "PING"})
    assert response.status_code == 503
    assert response.get_data(as_text=True) == "aún no disponible"


@pytest.mark.parametrize(
    "payload",
    [
        "no es json",
        "",
        "{}",
        '{"m": 0}',
        '{"m": null}',
    ],
)
def test_msg_without_string_body_uses_stub(client, payload):
    response = client.post("/msg", headers=AUTH, data=payload, content_type="application/json")
    assert response.status_code == 503
    assert response.get_data(as_text=True) == "aún no disponible"


# --- Autenticación -----------------------------------------------------------


def test_msg_missing_uses_reference(client):
    response = client.post("/msg", data="{}", content_type="application/json")
    assert response.status_code == 401
    assert response.get_json() == {"error": "E100", "mensaje": "falta credencial"}


def test_msg_other_token_uses_reference(client):
    response = client.post("/msg", headers=OTHER, data="{}", content_type="application/json")
    assert response.status_code == 403
    assert response.get_json() == {"error": "E101", "mensaje": "credencial distinta"}


def test_malformed_bearer_is_invalid(client):
    response = client.post("/msg", headers={"Authorization": "Token abc"}, data="{}", content_type="application/json")
    assert response.status_code == 403


def test_health_missing_uses_reference(client):
    response = client.get("/health")
    assert response.status_code == 401


# --- Rutas y métodos no cubiertos -------------------------------------------


def test_unknown_route_valid_uses_fallback(client):
    response = client.patch("/ruta/desconocida", headers=AUTH)
    assert response.status_code == 404
    assert response.get_json() == {"error": "E404", "mensaje": "ruta no existe"}


def test_unknown_route_missing_uses_fallback(client):
    response = client.get("/nada")
    assert response.status_code == 401


def test_non_post_msg_uses_fallback(client):
    response = client.put("/msg", headers=AUTH)
    assert response.status_code == 404


def test_no_framework_html_error_pages(client):
    response = client.get("/ruta/inexistente", headers=AUTH)
    assert "text/html" not in response.content_type


# --- Ausencia de conexiones salientes ---------------------------------------


def test_no_outbound_connections(client, monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("se intentó una conexión saliente")

    monkeypatch.setattr(socket.socket, "connect", _fail)
    monkeypatch.setattr(socket, "create_connection", _fail)

    assert client.get("/health", headers=AUTH).status_code == 200
    assert client.post("/msg", headers=AUTH, data="{}", content_type="application/json").status_code == 503


# --- Base no lista -----------------------------------------------------------


def test_settings_not_ready_blocks_health(write_jsonl, reference_data):
    evidence_path = write_jsonl(reference_data["evidence"])
    settings = _settings(evidence_path, ready=False, reason="falta credencial")
    app = create_app(settings, unavailable_catalog("sin catálogo"))

    response = app.test_client().get("/health", headers=AUTH)
    assert response.status_code == 503
    assert "text/html" not in response.content_type
    assert "token-de-prueba" not in response.get_data(as_text=True)


def test_catalog_not_ready_blocks_health(write_jsonl, reference_data, tmp_path):
    evidence_path = write_jsonl(reference_data["evidence"])
    settings = _settings(evidence_path)
    catalog = load_catalog(settings, str(tmp_path / "sin-manifiesto.json"))
    assert catalog.ready is False

    response = create_app(settings, catalog).test_client().get("/health", headers=AUTH)
    assert response.status_code == 503
    assert "token-de-prueba" not in response.get_data(as_text=True)
