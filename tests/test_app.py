"""Pruebas de integración HTTP del servicio."""

from __future__ import annotations

import socket

import pytest

from replacement.app import create_app
from replacement.control import control_for
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
    if message.startswith("TRANSFER;"):
        assert response.status_code == 503
        assert response.get_data(as_text=True) == "aún no disponible"
    elif message.startswith("PING;"):
        assert response.status_code == 200
    else:
        assert response.status_code in (200, 201, 400, 404)


def _message(command: str) -> str:
    return f"{command};{control_for(command)}"


def test_account_deposit_query_annul_flow(client):
    alta = client.post("/msg", headers=AUTH, json={"m": _message("ALTA;Lucia")})
    assert (alta.status_code, alta.get_json()) == (201, {"cuentaId": "AC-0001"})
    deposito = client.post("/msg", headers=AUTH, json={"m": _message("DEPOSITO;AC-0001;500000")})
    assert (deposito.status_code, deposito.get_json()) == (200, {"status": "recieved", "operacionId": "OP-0001"})
    consulta = client.post("/msg", headers=AUTH, json={"m": _message("CONSULTA;AC-0001")})
    assert consulta.get_json() == {"cuenta_id": "AC-0001", "saldo": "5000.00"}
    anula = client.post("/msg", headers=AUTH, json={"m": _message("ANULA;OP-0001")})
    assert anula.get_json() == {"ok": True, "anulada": "OP-0001"}
    consulta = client.post("/msg", headers=AUTH, json={"m": _message("CONSULTA;AC-0001")})
    assert consulta.get_json() == {"cuenta_id": "AC-0001", "saldo": "0.00"}


def test_transfer_has_no_effect_or_operation_id(client):
    alta = client.post("/msg", headers=AUTH, json={"m": _message("ALTA;Lucia")})
    assert alta.status_code == 201
    transfer = client.post("/msg", headers=AUTH, json={"m": _message("TRANSFER;AC-0001;AC-0001;100000")})
    assert (transfer.status_code, transfer.get_data(as_text=True)) == (503, "aún no disponible")
    deposito = client.post("/msg", headers=AUTH, json={"m": _message("DEPOSITO;AC-0001;1")})
    assert deposito.get_json()["operacionId"] == "OP-0001"


def test_rejected_twenty_digit_deposit_has_no_effect_or_operation_id(client):
    client.post("/msg", headers=AUTH, json={"m": _message("ALTA;Lucia")})
    rejected = client.post(
        "/msg", headers=AUTH,
        json={"m": _message("DEPOSITO;AC-0001;99999999999999999999")},
    )
    assert (rejected.status_code, rejected.get_json()) == (
        400, {"error": "E303", "mensaje": "monto inválido"}
    )
    balance = client.post("/msg", headers=AUTH, json={"m": _message("CONSULTA;AC-0001")})
    assert balance.get_json() == {"cuenta_id": "AC-0001", "saldo": "0.00"}
    accepted = client.post("/msg", headers=AUTH, json={"m": _message("DEPOSITO;AC-0001;1000000000")})
    assert (accepted.status_code, accepted.get_json()) == (
        200, {"status": "recieved", "operacionId": "OP-0001"}
    )


def test_rejected_twenty_digit_deposit_for_missing_account_returns_e303(client):
    response = client.post(
        "/msg", headers=AUTH,
        json={"m": _message("DEPOSITO;AC-9999;99999999999999999999")},
    )
    assert (response.status_code, response.get_json()) == (
        400, {"error": "E303", "mensaje": "monto inválido"}
    )


def test_reset_clears_state_and_counters(client):
    client.post("/msg", headers=AUTH, json={"m": _message("ALTA;Lucia")})
    client.post("/__reset", headers=AUTH)
    response = client.post("/msg", headers=AUTH, json={"m": _message("ALTA;Mateo")})
    assert response.get_json() == {"cuentaId": "AC-0001"}


def test_msg_invalid_numeric_control_returns_e202(client):
    response = client.post("/msg", headers=AUTH, json={"m": "ALTA;Lucia;83"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E202", "mensaje": "control inválido"}


def test_msg_malformed_control_returns_e201(client):
    response = client.post("/msg", headers=AUTH, json={"m": "DEPOSITO;AC-0002;700;5X"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E201", "mensaje": "control mal formado"}


@pytest.mark.parametrize("message", ["PING;64", "ping;64", "Ping;64"])
def test_ping_with_control_returns_pong(client, message):
    response = client.post("/msg", headers=AUTH, json={"m": message})
    assert response.status_code == 200
    assert response.get_json() == {"pong": True}


@pytest.mark.parametrize("control", ["abc", "123", "１２"])
def test_ping_malformed_control_returns_e201(client, control):
    response = client.post("/msg", headers=AUTH, json={"m": f"PING;{control}"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E201", "mensaje": "control mal formado"}


def test_ping_extra_arity_returns_e302(client):
    response = client.post("/msg", headers=AUTH, json={"m": "PING;extra;00"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "E302", "mensaje": "aridad inválida"}


def test_ping_empty_control_returns_e104(client):
    response = client.post("/msg", headers=AUTH, json={"m": "PING;"})
    assert (response.status_code, response.get_json()) == (
        400, {"error": "E104", "mensaje": "segmento vacío"}
    )


def test_ping_single_field_returns_e103(client):
    response = client.post("/msg", headers=AUTH, json={"m": "PING"})
    assert (response.status_code, response.get_json()) == (
        400, {"error": "E103", "mensaje": "falta control"}
    )


def test_rejected_ping_does_not_mutate_balance_or_operation_sequence(client):
    alta = client.post("/msg", headers=AUTH, json={"m": _message("ALTA;Lucia")})
    assert alta.get_json() == {"cuentaId": "AC-0001"}
    first_deposit = client.post(
        "/msg", headers=AUTH, json={"m": _message("DEPOSITO;AC-0001;1")}
    )
    assert first_deposit.get_json() == {"status": "recieved", "operacionId": "OP-0001"}

    rejected = client.post("/msg", headers=AUTH, json={"m": "PING"})
    assert (rejected.status_code, rejected.get_json()) == (
        400, {"error": "E103", "mensaje": "falta control"}
    )
    balance = client.post("/msg", headers=AUTH, json={"m": _message("CONSULTA;AC-0001")})
    assert balance.get_json() == {"cuenta_id": "AC-0001", "saldo": "0.01"}
    second_deposit = client.post(
        "/msg", headers=AUTH, json={"m": _message("DEPOSITO;AC-0001;1")}
    )
    assert second_deposit.get_json() == {"status": "recieved", "operacionId": "OP-0002"}


def test_three_digit_control_is_malformed(client):
    response = client.post("/msg", headers=AUTH, json={"m": "ALTA;Lucia;082"})
    assert response.get_json() == {"error": "E201", "mensaje": "control mal formado"}


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
def test_msg_without_string_body_uses_reference_error(client, payload):
    response = client.post("/msg", headers=AUTH, data=payload, content_type="application/json")
    if payload in ("no es json", ""):
        assert (response.status_code, response.get_json()) == (
            400, {"error": "E100", "mensaje": "JSON inválido"}
        )
    else:
        assert (response.status_code, response.get_json()) == (
            400, {"error": "E102", "mensaje": "falta mensaje"}
        )


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
    response = client.post("/msg", headers=AUTH, data="{}", content_type="application/json")
    assert (response.status_code, response.get_json()) == (
        400, {"error": "E102", "mensaje": "falta mensaje"}
    )


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
