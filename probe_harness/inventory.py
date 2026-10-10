"""Inventario cerrado del sondeo E0–E8 y agenda E7.

Materializa literalmente las tablas aprobadas. No se elige nada en ejecución:
los conteos, valores, hipótesis, preparaciones, resets y orden son fijos. ``C(id)``
se representa como el prefijo de un mensaje al que el solver adjunta el control.
"""

from __future__ import annotations

import json
from typing import Optional

from .models import (
    AUTH_INVALID,
    AUTH_MISSING,
    AUTH_VALID,
    KIND_AUXILIARY,
    KIND_E7,
    KIND_EXPLORATION,
    ProbeSequence,
    RequestSpec,
)
from .settings import DEFAULT_SEED

JSON_CT = "application/json"
TEXT_CT = "text/plain"

MODULUS = 2 ** 32
LCG_MULTIPLIER = 1664525
LCG_INCREMENT = 1013904223

# Longitudes exactas de las veinte secuencias E8 (suma 150).
E8_LENGTHS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 8, 8, 8, 8, 8, 8, 8, 8, 9)


def json_body(message: str) -> str:
    return json.dumps({"m": message}, ensure_ascii=False, separators=(",", ":"))


def _spec(
    case_id: str,
    method: str,
    path: str,
    hypothesis: str,
    axis: str,
    *,
    kind: str = KIND_EXPLORATION,
    auth_mode: str = AUTH_VALID,
    body_raw: Optional[str] = None,
    content_type: Optional[str] = None,
    control_prefix: Optional[str] = None,
    sequence: Optional[str] = None,
) -> RequestSpec:
    return RequestSpec(
        case_id=case_id,
        method=method,
        path=path,
        hypothesis=hypothesis,
        axis=axis,
        kind=kind,
        auth_mode=auth_mode,
        body_raw=body_raw,
        content_type=content_type,
        control_prefix=control_prefix,
        sequence=sequence or axis,
    )


def _aux(case_id: str, axis: str, sequence: str, hypothesis: str, **kwargs) -> RequestSpec:
    return _spec(
        case_id,
        "POST",
        kwargs.pop("path", "/msg"),
        hypothesis,
        axis,
        kind=KIND_AUXILIARY,
        sequence=sequence,
        **kwargs,
    )


def _reset(case_id: str, axis: str, sequence: str) -> RequestSpec:
    return _spec(
        case_id,
        "POST",
        "/__reset",
        f"{case_id}: preparación de {sequence}",
        axis,
        kind=KIND_AUXILIARY,
        sequence=sequence,
    )


# --- E0 -------------------------------------------------------------------


def _e0_sequence() -> ProbeSequence:
    prep = (_reset("AUX-E0-RESET", "E0", "E0"),)
    blocks = (
        ("PING", "PING", "sweep de control de la base PING;64"),
        ("ALTA", "ALTA;Lucia", "sweep de control de la base ALTA;Lucia;82"),
        ("CONSULTA", "CONSULTA;AC-0009", "sweep de control de la base CONSULTA;AC-0009;87"),
    )
    steps = []
    for tag, base, label in blocks:
        for n in range(100):
            case_id = f"E0-{tag}-{n:02d}"
            message = f"{base};{n:02d}"
            steps.append(
                _spec(
                    case_id,
                    "POST",
                    "/msg",
                    f"{case_id}: {label}",
                    "E0",
                    body_raw=json_body(message),
                    content_type=JSON_CT,
                    sequence="E0",
                )
            )
    return ProbeSequence("E0", "E0", prep, tuple(steps))


# --- E1 -------------------------------------------------------------------


def _e1_requests() -> list:
    rows = [
        ("E1-01", "GET", "/health", AUTH_VALID, None, None, "salud conocida con auth válida"),
        ("E1-02", "POST", "/health", AUTH_VALID, None, None, "método alternativo de salud"),
        ("E1-03", "GET", "/__reset", AUTH_VALID, None, None, "método alternativo de reset"),
        ("E1-04", "POST", "/__reset", AUTH_VALID, None, None, "reset conocido"),
        ("E1-05", "GET", "/msg", AUTH_VALID, None, None, "método alternativo de msg"),
        ("E1-06", "POST", "/msg", AUTH_VALID, json_body("PING;64"), JSON_CT, "msg conocido sin estado"),
        ("E1-07", "PUT", "/msg", AUTH_VALID, json_body("PING;64"), JSON_CT, "método PUT de msg"),
        ("E1-08", "GET", "/missing", AUTH_VALID, None, None, "ruta inexistente GET"),
        ("E1-09", "POST", "/missing", AUTH_VALID, json_body("PING;64"), JSON_CT, "ruta inexistente POST"),
        ("E1-10", "DELETE", "/missing", AUTH_VALID, None, None, "ruta inexistente DELETE"),
        ("E1-11", "OPTIONS", "/msg", AUTH_VALID, None, None, "opciones de msg"),
        ("E1-12", "HEAD", "/health", AUTH_VALID, None, None, "cabecera de salud"),
        ("E1-13", "GET", "/health", AUTH_MISSING, None, None, None),
        ("E1-14", "POST", "/__reset", AUTH_MISSING, None, None, None),
        ("E1-15", "POST", "/msg", AUTH_MISSING, json_body("PING;64"), JSON_CT, None),
        ("E1-16", "GET", "/missing", AUTH_MISSING, None, None, None),
        ("E1-17", "POST", "/missing", AUTH_MISSING, "texto", TEXT_CT, None),
        ("E1-18", "GET", "/health", AUTH_INVALID, None, None, None),
        ("E1-19", "POST", "/__reset", AUTH_INVALID, None, None, None),
        ("E1-20", "POST", "/msg", AUTH_INVALID, json_body("PING;64"), JSON_CT, None),
        ("E1-21", "GET", "/missing", AUTH_INVALID, None, None, None),
        ("E1-22", "POST", "/missing", AUTH_INVALID, "texto", TEXT_CT, None),
        ("E1-23", "POST", "/msg/", AUTH_VALID, json_body("PING;64"), JSON_CT, "slash final de msg"),
        ("E1-24", "GET", "/health/", AUTH_VALID, None, None, "slash final de salud"),
        ("E1-25", "POST", "/__reset/", AUTH_VALID, None, None, "slash final de reset"),
        ("E1-26", "GET", "//health", AUTH_VALID, None, None, "doble slash"),
        ("E1-27", "POST", "/MSG", AUTH_VALID, json_body("PING;64"), JSON_CT, "ruta con mayúsculas"),
        ("E1-28", "PATCH", "/msg", AUTH_VALID, json_body("PING;64"), JSON_CT, "método PATCH"),
        ("E1-29", "POST", "/", AUTH_VALID, "{}", JSON_CT, "raíz POST"),
        ("E1-30", "GET", "/", AUTH_VALID, None, None, "raíz GET"),
    ]
    requests = []
    for case_id, method, path, auth, body, ctype, label in rows:
        if label is None:
            suffix = "sin auth" if auth == AUTH_MISSING else "auth inválida"
            label = f"{method} {path} {suffix}"
        requests.append(
            _spec(
                case_id,
                method,
                path,
                f"{case_id}: {label}",
                "E1",
                auth_mode=auth,
                body_raw=body,
                content_type=ctype,
                sequence="E1",
            )
        )
    return requests


# --- E2 -------------------------------------------------------------------


def _e2_requests() -> list:
    rows = [
        ("E2-01", None, None, "cuerpo ausente"),
        ("E2-02", "", TEXT_CT, "cuerpo vacío"),
        ("E2-03", "PING;64", TEXT_CT, "texto no JSON conocido"),
        ("E2-04", "{", JSON_CT, "JSON truncado"),
        ("E2-05", '"PING;64"', JSON_CT, "JSON escalar string"),
        ("E2-06", "[]", JSON_CT, "JSON array raíz"),
        ("E2-07", "null", JSON_CT, "JSON null raíz"),
        ("E2-08", '{"m":', JSON_CT, "objeto JSON truncado"),
        ("E2-09", "{}", JSON_CT, "m ausente"),
        ("E2-10", '{"m":null}', JSON_CT, "m null"),
        ("E2-11", '{"m":0}', JSON_CT, "m número"),
        ("E2-12", '{"m":true}', JSON_CT, "m booleano"),
        ("E2-13", '{"m":[]}', JSON_CT, "m array"),
        ("E2-14", '{"m":{}}', JSON_CT, "m objeto"),
        ("E2-15", '{"m":["PING;64"]}', JSON_CT, "m array textual"),
        ("E2-16", '{"m":"PING;64","x":0}', JSON_CT, "claves adicionales 1"),
        ("E2-17", '{"m":"PING;64","x":null}', JSON_CT, "claves adicionales 2"),
        ("E2-18", '{"m":"PING;64","x":{}}', JSON_CT, "claves adicionales 3"),
        ("E2-19", '{"m":"PING;64","m2":"PING;64"}', JSON_CT, "claves adicionales 4"),
        ("E2-20", '{"m":"PING;64","extra":[1,2]}', JSON_CT, "claves adicionales 5"),
    ]
    strings = (
        "",
        " ",
        "\t",
        "\n",
        ";",
        "PING",
        "PING;",
        ";64",
        " ping;64",
        "PING;64 ",
        "PING;;64",
        "A",
        "A" * 255,
        "A" * 256,
        "A" * 1024,
    )
    for index, value in enumerate(strings, start=1):
        rows.append((f"E2-{20 + index:02d}", json_body(value), JSON_CT, f"string borde {index}"))

    requests = []
    for case_id, body, ctype, label in rows:
        requests.append(
            _spec(
                case_id,
                "POST",
                "/msg",
                f"{case_id}: {label}",
                "E2",
                body_raw=body,
                content_type=ctype,
                sequence="E2",
            )
        )
    return requests


# --- E3 -------------------------------------------------------------------


def _e3_requests() -> list:
    messages = [
        "PING",
        "PING;",
        "PING;;64",
        "PING|64",
        "PING,64",
        "PING:64",
        "PING 64",
        "PING\t64",  # separador tabulador
    ]
    rows = [(f"E3-{i:02d}", m, f"separador {i}") for i, m in enumerate(messages, start=1)]
    arity = [
        "PING;64;X",
        "PING;64;",
        "ALTA;82",
        "ALTA;Lucia;82;X",
        "ALTA;;82",
        "ALTA;Lucia;Gomez;82",
        "CONSULTA;14",
        "CONSULTA;AC-0009;87;X",
        "DEPOSITO;AC-0009;100;86",
        "DEPOSITO;AC-0009;100;86;X",
        "TRANSFER;AC-0009;AC-0008;1;86",
        "ANULA;OP-0001;66;X",
    ]
    for i, m in enumerate(arity, start=1):
        rows.append((f"E3-{8 + i:02d}", m, f"aridad {i}"))
    bases = ("PING", "ALTA;Lucia", "CONSULTA;AC-0009")
    suffixes = ("", "X", "5X", "00", "01")
    idx = 21
    for b, base in enumerate(bases, start=1):
        for s, suffix in enumerate(suffixes, start=1):
            rows.append(
                (f"E3-{idx:02d}", f"{base};{suffix}", f"control malformado/inválido: base {b}, sufijo {s}")
            )
            idx += 1

    requests = []
    for case_id, message, label in rows:
        requests.append(
            _spec(
                case_id,
                "POST",
                "/msg",
                f"{case_id}: {label}",
                "E3",
                body_raw=json_body(message),
                content_type=JSON_CT,
                sequence="E3",
            )
        )
    return requests


# --- E4 -------------------------------------------------------------------

_E4_FAMILIES = (
    (
        "PING",
        (),
        ("PING", "ping", "Ping", "PING;0", "PING;X", " PING"),
    ),
    (
        "ALTA",
        (),
        (
            "ALTA;CmdAlice",
            "alta;CmdAlice",
            "Alta;CmdAlice",
            "ALTA;",
            "ALTA;CmdAlice;extra",
            "ALTA;Cmd Alice",
            "ALTA;Cmd-001",
            "ALTA;cmdalice",
        ),
    ),
    (
        "CONSULTA",
        (("AUX-E4-CONSULTA-ALTA", "ALTA;E4-A"),),
        (
            "CONSULTA;E4-A",
            "consulta;E4-A",
            "Consulta;E4-A",
            "CONSULTA;AC-0000",
            "CONSULTA;AC-9999",
            "CONSULTA;",
            "CONSULTA;E4-A;extra",
            "CONSULTA; E4-A",
        ),
    ),
    (
        "DEPOSITO",
        (("AUX-E4-DEPOSITO-ALTA", "ALTA;E4-A"),),
        (
            "DEPOSITO;E4-A;0",
            "DEPOSITO;E4-A;1",
            "DEPOSITO;E4-A;250000",
            "DEPOSITO;E4-A;-1",
            "DEPOSITO;E4-A;NaN",
            "DEPOSITO;E4-A;",
            "DEPOSITO;AC-9999;1",
            "deposito;E4-A;1",
        ),
    ),
    (
        "TRANSFER",
        (
            ("AUX-E4-TRANSFER-ALTA-A", "ALTA;E4-A"),
            ("AUX-E4-TRANSFER-ALTA-B", "ALTA;E4-B"),
            ("AUX-E4-TRANSFER-DEPOSITO", "DEPOSITO;E4-A;500000"),
        ),
        (
            "TRANSFER;E4-A;E4-B;0",
            "TRANSFER;E4-A;E4-B;1",
            "TRANSFER;E4-A;E4-B;100000",
            "TRANSFER;E4-A;E4-B;120000",
            "TRANSFER;E4-A;E4-B;-1",
            "TRANSFER;E4-A;E4-B;NaN",
            "TRANSFER;E4-A;AC-9999;1",
            "transfer;E4-A;E4-B;1",
        ),
    ),
    (
        "ANULA",
        (
            ("AUX-E4-ANULA-ALTA-A", "ALTA;E4-A"),
            ("AUX-E4-ANULA-ALTA-B", "ALTA;E4-B"),
            ("AUX-E4-ANULA-DEPOSITO", "DEPOSITO;E4-A;500000"),
            ("AUX-E4-ANULA-TRANSFER", "TRANSFER;E4-A;E4-B;1000"),
        ),
        (
            "ANULA;OP-0002",
            "ANULA;OP-0002",
            "ANULA;OP-9999",
            "anula;OP-0002",
            "ANULA;",
            "ANULA;OP-0002;extra",
        ),
    ),
    (
        "SALDOS",
        (),
        (
            "SALDOS;E4-A",
            "saldos;E4-A",
            "SALDOS",
            "SALDOS;",
            "SALDOS;E4-A;extra",
            "SALDOS;AC-9999",
        ),
    ),
)


def _e4_sequences() -> list:
    sequences = []
    counter = 1
    for family, extra_prep, prefixes in _E4_FAMILIES:
        prep = [_reset(f"AUX-E4-{family}-RESET", "E4", family)]
        for aux_id, prefix in extra_prep:
            prep.append(
                _aux(
                    aux_id,
                    "E4",
                    family,
                    f"{aux_id}: preparación de {family}",
                    control_prefix=prefix,
                    content_type=JSON_CT,
                )
            )
        steps = []
        for prefix in prefixes:
            case_id = f"E4-{counter:02d}"
            steps.append(
                _spec(
                    case_id,
                    "POST",
                    "/msg",
                    f"{case_id}: variante literal del comando {family}: {prefix}",
                    "E4",
                    control_prefix=prefix,
                    content_type=JSON_CT,
                    sequence=family,
                )
            )
            counter += 1
        sequences.append(ProbeSequence(family, "E4", tuple(prep), tuple(steps)))
    return sequences


# --- E5 -------------------------------------------------------------------

_E5_PATTERNS = {
    1: ("ALTA;{A}", "ALTA;{B}", "CONSULTA;{A}", "CONSULTA;{B}"),
    2: ("ALTA;{A}", "DEPOSITO;{A};1", "CONSULTA;{A}", "CONSULTA;{A}"),
    3: ("ALTA;{A}", "ALTA;{B}", "DEPOSITO;{A};100", "TRANSFER;{A};{B};1"),
    4: ("ALTA;{A}", "ALTA;{B}", "DEPOSITO;{A};500000", "TRANSFER;{A};{B};120000"),
    5: ("ALTA;{A}", "ALTA;{B}", "TRANSFER;{A};{B};1", "CONSULTA;{B}"),
    6: ("ALTA;{A}", "DEPOSITO;{A};100", "DEPOSITO;{A};200", "CONSULTA;{A}"),
    7: ("ALTA;{A}", "ALTA;{B}", "DEPOSITO;{A};250000", "TRANSFER;{A};{B};100000"),
    8: ("ALTA;{A}", "ALTA;{B}", "DEPOSITO;{A};250000", "TRANSFER;{A};{B};99999"),
    9: ("ANULA;OP-0002", "ANULA;OP-0002", "CONSULTA;{A}", "CONSULTA;{B}"),
    10: ("TRANSFER;{A};{B};100", "TRANSFER;{A};{B};200", "ANULA;OP-0003", "CONSULTA;{B}"),
}

_E5_EXTRA_PREP = {
    9: (
        ("AUX-E5-09-01", "ALTA;E5-09-A"),
        ("AUX-E5-09-02", "ALTA;E5-09-B"),
        ("AUX-E5-09-03", "DEPOSITO;E5-09-A;1000"),
        ("AUX-E5-09-04", "TRANSFER;E5-09-A;E5-09-B;100"),
    ),
    10: (
        ("AUX-E5-10-01", "ALTA;E5-10-A"),
        ("AUX-E5-10-02", "ALTA;E5-10-B"),
        ("AUX-E5-10-03", "DEPOSITO;E5-10-A;1000"),
    ),
}

_EFFECTS = {
    "ALTA": "creación/IDs",
    "CONSULTA": "consulta",
    "DEPOSITO": "depósito",
    "TRANSFER": "transferencia",
    "ANULA": "anulación",
    "SALDOS": "comando alternativo",
}


def _effect(message: str) -> str:
    return _EFFECTS.get(message.split(";")[0].upper(), "paso")


def _e5_sequences() -> list:
    sequences = []
    for ss in range(1, 11):
        seq_id = f"{ss:02d}"
        prep = [_reset(f"AUX-E5-{seq_id}-RESET", "E5", f"E5-{seq_id}")]
        for aux_id, prefix in _E5_EXTRA_PREP.get(ss, ()):
            prep.append(
                _aux(
                    aux_id,
                    "E5",
                    f"E5-{seq_id}",
                    f"{aux_id}: preparación de E5-{seq_id}",
                    control_prefix=prefix,
                    content_type=JSON_CT,
                )
            )
        steps = []
        for pp, pattern in enumerate(_E5_PATTERNS[ss], start=1):
            message = pattern.replace("{A}", f"E5-{seq_id}-A").replace("{B}", f"E5-{seq_id}-B")
            case_id = f"E5-{seq_id}-{pp:02d}"
            steps.append(
                _spec(
                    case_id,
                    "POST",
                    "/msg",
                    f"secuencia {seq_id}, paso {pp:02d}: {_effect(message)}",
                    "E5",
                    control_prefix=message,
                    content_type=JSON_CT,
                    sequence=f"E5-{seq_id}",
                )
            )
        sequences.append(ProbeSequence(f"E5-{seq_id}", "E5", tuple(prep), tuple(steps)))
    return sequences


# --- E6 -------------------------------------------------------------------

_E6_ROOTS = (
    ("BLAH", "comando desconocido"),
    ("PING;extra", "aridad de PING"),
    ("ALTA", "aridad de ALTA"),
    ("ALTA;Lucia;Gomez", "aridad de ALTA extendida"),
    ("CONSULTA", "aridad de CONSULTA"),
    ("CONSULTA;AC-9999;extra", "aridad/cuenta inexistente"),
    ("DEPOSITO;AC-9999;NaN", "cuenta/cantidad mal formada"),
    ("TRANSFER;AC-9999;AC-9998;NaN", "cuentas/cantidad mal formada"),
    ("ANULA;OP-9999;extra", "aridad/operación inexistente"),
    ("SALDOS;AC-9999", "comando desconocido/argumento"),
)

_E6_TERMINATIONS = ("X", "00", "", "999")


def _e6_requests() -> list:
    requests = []
    counter = 1
    for root, cause in _E6_ROOTS:
        for term in _E6_TERMINATIONS:
            case_id = f"E6-{counter:02d}"
            message = f"{root};{term}"
            requests.append(
                _spec(
                    case_id,
                    "POST",
                    "/msg",
                    f"{case_id}: prioridad entre {cause} y control {term}",
                    "E6",
                    body_raw=json_body(message),
                    content_type=JSON_CT,
                    sequence="E6",
                )
            )
            counter += 1
    return requests


# --- E8 -------------------------------------------------------------------


def _e8_prefix(t: int, seq_id: str, monto: int) -> tuple:
    if t == 0:
        return f"CONSULTA;E8-A-{seq_id}", "consulta de origen"
    if t == 1:
        return f"CONSULTA;E8-B-{seq_id}", "consulta de destino"
    if t == 2:
        return f"DEPOSITO;E8-A-{seq_id};{monto}", "depósito secuencial"
    if t == 3:
        return (
            f"TRANSFER;E8-A-{seq_id};E8-B-{seq_id};{monto}",
            "transferencia origen a destino",
        )
    if t == 4:
        return (
            f"TRANSFER;E8-B-{seq_id};E8-A-{seq_id};{monto}",
            "transferencia destino a origen",
        )
    if t == 5:
        return "ANULA;OP-0001", "anulación de operación inicial"
    if t == 6:
        return "ANULA;OP-0002", "anulación de segunda operación"
    return f"SALDOS;E8-A-{seq_id}", "comando alternativo en secuencia"


def _e8_sequences(seed: int = DEFAULT_SEED) -> list:
    x = seed
    sequences = []
    for ss, length in enumerate(E8_LENGTHS, start=1):
        seq_id = f"{ss:02d}"
        prep = [
            _reset(f"AUX-E8-{seq_id}-RESET", "E8", f"E8-{seq_id}"),
            _aux(
                f"AUX-E8-{seq_id}-ALTA-A",
                "E8",
                f"E8-{seq_id}",
                f"AUX-E8-{seq_id}-ALTA-A: preparación de E8-{seq_id}",
                control_prefix=f"ALTA;E8-A-{seq_id}",
                content_type=JSON_CT,
            ),
            _aux(
                f"AUX-E8-{seq_id}-ALTA-B",
                "E8",
                f"E8-{seq_id}",
                f"AUX-E8-{seq_id}-ALTA-B: preparación de E8-{seq_id}",
                control_prefix=f"ALTA;E8-B-{seq_id}",
                content_type=JSON_CT,
            ),
            _aux(
                f"AUX-E8-{seq_id}-DEPOSITO",
                "E8",
                f"E8-{seq_id}",
                f"AUX-E8-{seq_id}-DEPOSITO: preparación de E8-{seq_id}",
                control_prefix=f"DEPOSITO;E8-A-{seq_id};500000",
                content_type=JSON_CT,
            ),
        ]
        steps = []
        for pp in range(1, length + 1):
            x = (LCG_MULTIPLIER * x + LCG_INCREMENT) % MODULUS
            t = x % 8
            monto = 1 + 1000 * ((x // 8) % 9)
            prefix, label = _e8_prefix(t, seq_id, monto)
            case_id = f"E8-{seq_id}-{pp:02d}"
            steps.append(
                _spec(
                    case_id,
                    "POST",
                    "/msg",
                    f"{case_id}: {label} tras la preparación de E8-{seq_id}",
                    "E8",
                    control_prefix=prefix,
                    content_type=JSON_CT,
                    sequence=f"E8-{seq_id}",
                )
            )
        sequences.append(ProbeSequence(f"E8-{seq_id}", "E8", tuple(prep), tuple(steps)))
    return sequences


# --- inventario completo --------------------------------------------------


class Inventory:
    """Inventario cerrado y determinista del sondeo."""

    def __init__(self, seed: int = DEFAULT_SEED):
        self.seed = seed
        self._e0 = _e0_sequence()
        self._e1 = tuple(_e1_requests())
        self._e2 = tuple(_e2_requests())
        self._e3 = tuple(_e3_requests())
        self._e4 = tuple(_e4_sequences())
        self._e5 = tuple(_e5_sequences())
        self._e6 = tuple(_e6_requests())
        self._e8 = tuple(_e8_sequences(seed))

    def e0_sequence(self) -> ProbeSequence:
        return self._e0

    def e1_requests(self) -> tuple:
        return self._e1

    def e2_requests(self) -> tuple:
        return self._e2

    def e3_requests(self) -> tuple:
        return self._e3

    def e4_sequences(self) -> tuple:
        return self._e4

    def e5_sequences(self) -> tuple:
        return self._e5

    def e6_requests(self) -> tuple:
        return self._e6

    def e8_sequences(self) -> tuple:
        return self._e8

    def sequences(self) -> tuple:
        """Orden global: E0, E1, E2, E3, E4, E5, E6 y E8."""

        flat = [self._e0]
        for axis_id, requests in (
            ("E1", self._e1),
            ("E2", self._e2),
            ("E3", self._e3),
        ):
            flat.append(ProbeSequence(axis_id, axis_id, (), tuple(requests)))
        flat.extend(self._e4)
        flat.extend(self._e5)
        flat.append(ProbeSequence("E6", "E6", (), tuple(self._e6)))
        flat.extend(self._e8)
        return tuple(flat)

    def exploration_count(self) -> int:
        return sum(len(seq.steps) for seq in self.sequences())

    def axis_counts(self) -> dict:
        counts = {}
        for seq in self.sequences():
            counts[seq.axis] = counts.get(seq.axis, 0) + len(seq.steps)
        return counts

    def control_slots(self) -> list:
        """Pares ``(case_id, prefijo)`` de todo caso que usa ``C(id)``, en orden."""

        slots = []
        for seq in self.sequences():
            for spec in seq.all_requests():
                if spec.uses_control():
                    slots.append((spec.case_id, spec.control_prefix))
        return slots

    def build_e7_replay(self, examples: list, run_tag: str = "") -> ProbeSequence:
        return build_e7_replay(examples, run_tag)


def build_e7_replay(examples: list, run_tag: str = "") -> ProbeSequence:
    """Construye la repetición literal de los veinte mensajes de ejemplo."""

    suffix = f"-{run_tag}" if run_tag else ""
    prep = (_reset(f"AUX-E7-RESET{suffix}", "E7", f"E7{suffix}"),)
    steps = []
    for index, example in enumerate(examples, start=1):
        message = example["request"]["m"]
        case_id = f"E7{suffix}-{index:02d}"
        steps.append(
            _spec(
                case_id,
                "POST",
                "/msg",
                f"{case_id}: repetición literal de ejemplo {index}",
                "E7",
                kind=KIND_E7,
                body_raw=json_body(message),
                content_type=JSON_CT,
                sequence=f"E7{suffix}",
            )
        )
    return ProbeSequence(f"E7{suffix}", "E7", prep, tuple(steps))
