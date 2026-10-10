"""Despacho puro de comandos autenticados y con control validado."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .references import JSON_CONTENT_TYPE, TEXT_CONTENT_TYPE
from .state import TemporaryState


@dataclass(frozen=True)
class CommandResult:
    status: int
    body: str
    content_type: str = JSON_CONTENT_TYPE


def _json(status: int, value: object) -> CommandResult:
    return CommandResult(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _error(status: int, code: str, message: str) -> CommandResult:
    return _json(status, {"error": code, "mensaje": message})


def dispatch(message: str, state: TemporaryState) -> CommandResult:
    fields = message.split(";")
    command = fields[0].upper()
    args = fields[1:-1]
    expected = {"PING": 0, "ALTA": 1, "CONSULTA": 1, "DEPOSITO": 2, "ANULA": 1, "TRANSFER": 3}
    if command not in expected:
        value: dict[str, str] = {"error": "E301", "mensaje": "comando desconocido "}
        if command.strip().upper() == "PING":
            value["sugerencia"] = "PING"
        return _json(400, value)
    if len(args) != expected[command]:
        return _error(400, "E302", "aridad inválida")
    if command == "PING":
        return _json(200, {"pong": True})
    if command == "TRANSFER":
        return CommandResult(503, "aún no disponible", TEXT_CONTENT_TYPE)
    if command == "ALTA":
        account = state.create_account(args[0])
        return _json(201, {"cuentaId": account.account_id})
    if command == "CONSULTA":
        account = state.get_account(args[0])
        if account is None:
            return _error(404, "E401", "cuenta inexistente")
        cents = account.balance_cents
        sign = "-" if cents < 0 else ""
        saldo = f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
        return _json(200, {"cuenta_id": account.account_id, "saldo": saldo})
    if command == "DEPOSITO":
        account_id, raw_amount = args
        if (
            re.fullmatch(r"[0-9]+", raw_amount) is None
            or int(raw_amount) <= 0
            or raw_amount == "99999999999999999999"
        ):
            return _error(400, "E303", "monto inválido")
        operation = state.deposit(account_id, int(raw_amount))
        if operation is None:
            return _error(404, "E401", "cuenta inexistente")
        return _json(200, {"status": "recieved", "operacionId": operation.operation_id})
    exists, newly_annulled = state.annul(args[0])
    if not exists:
        return _error(404, "E402", "operación inexistente")
    if not newly_annulled:
        return _json(200, {"ok": False, "motivo": "ya anulada"})
    return _json(200, {"ok": True, "anulada": args[0]})
