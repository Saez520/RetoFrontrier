"""Solver de control autónomo y cerrado.

Extrae los controles aceptados de E0, arma los conjuntos de ajuste y hold-out,
recorre el catálogo finito de canonicalizadores, métricas y familias afines, y
solo adopta una función cuya predicción supera ajuste y hold-out y produce un
único vector de controles. No ejecuta solicitudes, no lee credenciales y no
solicita valores humanos.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .models import ControlProvenance, RequestSpec, SolverResult

# Líneas de ``ejemplos.jsonl`` (1-based) que integran el ajuste y el hold-out.
FIT_LINES = (4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 16, 18, 19)
HOLDOUT_LINES = (1, 3, 15)

E0_EXCLUDED_ERRORS = ("E201", "E202")


# --- canonicalizadores ----------------------------------------------------


def _canon_raw(data: bytes) -> bytes:
    return data


def _canon_command_upper(data: bytes) -> bytes:
    idx = data.find(b";")
    head = data if idx == -1 else data[:idx]
    tail = b"" if idx == -1 else data[idx:]
    head = bytes(c - 32 if 0x61 <= c <= 0x7A else c for c in head)
    return head + tail


def _canon_ascii_upper(data: bytes) -> bytes:
    return bytes(c - 32 if 0x61 <= c <= 0x7A else c for c in data)


def _canon_strip_semicolons(data: bytes) -> bytes:
    return data.replace(b";", b"")


CANONICALIZERS = (
    ("raw", _canon_raw),
    ("command_upper", _canon_command_upper),
    ("ascii_upper", _canon_ascii_upper),
    ("strip_semicolons", _canon_strip_semicolons),
)


# --- métricas -------------------------------------------------------------


def _crc8_msb(poly: int, init: int, xorout: int, data: bytes) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc ^ xorout


def _crc8_maxim(data: bytes) -> int:
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
    return crc & 0xFF


def _xor_bytes(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def _sha1(data: bytes) -> bytes:
    return hashlib.sha1(data).digest()


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


CATALOG_METRICS = (
    ("sum", lambda b: sum(b) % 100),
    ("sum256", lambda b: (sum(b) % 256) % 100),
    ("xor", lambda b: _xor_bytes(b) % 100),
    ("crc8_atm", lambda b: _crc8_msb(0x07, 0x00, 0x00, b) % 100),
    ("crc8_sae_j1850", lambda b: _crc8_msb(0x1D, 0xFF, 0xFF, b) % 100),
    ("crc8_maxim", lambda b: _crc8_maxim(b) % 100),
    ("crc32", lambda b: zlib.crc32(b) % 100),
    ("adler32", lambda b: zlib.adler32(b) % 100),
    ("md5_first", lambda b: _md5(b)[0] % 100),
    ("md5_last", lambda b: _md5(b)[-1] % 100),
    ("sha1_first", lambda b: _sha1(b)[0] % 100),
    ("sha1_last", lambda b: _sha1(b)[-1] % 100),
    ("sha256_first", lambda b: _sha256(b)[0] % 100),
    ("sha256_last", lambda b: _sha256(b)[-1] % 100),
)


# --- carga de ejemplos ----------------------------------------------------


def load_examples(path: str | Path) -> list:
    examples = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            examples.append(json.loads(line))
    return examples


def _split_message(message: str) -> tuple:
    base, _, control = message.rpartition(";")
    return base, control


def example_pairs(examples: list) -> dict:
    """Devuelve ``{n: (base, control)}`` para las líneas con control parseable."""

    pairs = {}
    for index, example in enumerate(examples, start=1):
        request = example.get("request")
        if not isinstance(request, dict) or "m" not in request:
            continue
        base, control = _split_message(str(request["m"]))
        try:
            pairs[index] = (base, int(control))
        except ValueError:
            continue
    return pairs


# --- extracción de E0 -----------------------------------------------------


def _is_accepted(record) -> bool:
    if record.get("infra"):
        return False
    if record.get("status") is None:
        return False
    response = record.get("response")
    if isinstance(response, dict) and response.get("error") in E0_EXCLUDED_ERRORS:
        return False
    return True


def extract_e0_values(e0_records: list) -> dict:
    """Agrupa por base los controles aceptados medidos en E0."""

    grouped: dict = {}
    for record in e0_records:
        request = record.get("request")
        if not isinstance(request, dict) or "m" not in request:
            continue
        base, control = _split_message(str(request["m"]))
        try:
            value = int(control)
        except ValueError:
            continue
        grouped.setdefault(base, set())
        if _is_accepted(record):
            grouped[base].add(value)
    return grouped


# --- solver ---------------------------------------------------------------


def _vector_fingerprint(vector: list) -> str:
    payload = ",".join(f"{case_id}:{value}" for case_id, value in vector)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def solve(
    e0_records: list,
    examples: list,
    slots: list,
    *,
    metrics=CATALOG_METRICS,
    canonicalizers=CANONICALIZERS,
) -> SolverResult:
    """Deriva el vector de controles o reporta la causa exacta de no derivación."""

    pairs = example_pairs(examples)
    expected = {}
    for line in HOLDOUT_LINES:
        if line in pairs:
            base, control = pairs[line]
            expected[base] = control
    fit = [pairs[line] for line in FIT_LINES if line in pairs]
    holdout = [pairs[line] for line in HOLDOUT_LINES if line in pairs]

    grouped = extract_e0_values(e0_records)
    e0_values = {}
    for base, expect in expected.items():
        accepted = grouped.get(base, set())
        if len(accepted) != 1:
            return SolverResult(
                status="ambiguous_e0",
                provenance=None,
                fit_count=len(fit),
                holdout_count=len(holdout),
                e0_values={},
                vector_fingerprint=None,
                controls=None,
                reason=f"{base}: {len(accepted)} controles aceptados en E0",
            )
        (value,) = tuple(accepted)
        if value != expect:
            return SolverResult(
                status="ambiguous_e0",
                provenance=None,
                fit_count=len(fit),
                holdout_count=len(holdout),
                e0_values={base: value},
                vector_fingerprint=None,
                controls=None,
                reason=f"{base}: E0={value} difiere del ejemplo {expect}",
            )
        e0_values[base] = value

    all_bases = {base for base, _ in fit}
    all_bases.update(base for base, _ in holdout)
    all_bases.update(prefix for _, prefix in slots)

    vectors = []
    provenance = None
    for canon_name, canon in canonicalizers:
        canon_cache = {base: canon(base.encode("utf-8")) for base in all_bases}
        encoded = {base: canon_cache[base] for base in all_bases}
        for metric_name, metric in metrics:
            fit_values = [metric(encoded[base]) for base, _ in fit]
            if not fit:
                continue
            for a in range(100):
                avs = [(a * v) % 100 for v in fit_values]
                b = (fit[0][1] - avs[0]) % 100
                if not all((avs[i] + b) % 100 == fit[i][1] for i in range(1, len(fit))):
                    continue
                if not all(
                    (a * metric(encoded[base]) + b) % 100 == control
                    for base, control in holdout
                ):
                    continue
                vector = [
                    (case_id, (a * metric(encoded[prefix]) + b) % 100)
                    for case_id, prefix in slots
                ]
                vectors.append(vector)
                if provenance is None:
                    provenance = ControlProvenance(canon_name, metric_name, a, b)

    if not vectors:
        return SolverResult(
            status="no_candidate",
            provenance=None,
            fit_count=len(fit),
            holdout_count=len(holdout),
            e0_values=e0_values,
            vector_fingerprint=None,
            controls=None,
            reason="ningún candidato supera ajuste y hold-out",
        )

    fingerprints = {_vector_fingerprint(vec) for vec in vectors}
    if len(fingerprints) > 1:
        return SolverResult(
            status="ambiguous_candidate",
            provenance=None,
            fit_count=len(fit),
            holdout_count=len(holdout),
            e0_values=e0_values,
            vector_fingerprint=None,
            controls=None,
            reason=f"{len(vectors)} candidatos con vectores distintos",
        )

    chosen = vectors[0]
    return SolverResult(
        status="accepted",
        provenance=provenance,
        fit_count=len(fit),
        holdout_count=len(holdout),
        e0_values=e0_values,
        vector_fingerprint=_vector_fingerprint(chosen),
        controls={case_id: value for case_id, value in chosen},
        reason=None,
    )


def apply_control_vector(spec: RequestSpec, controls: dict) -> Optional[str]:
    """Adaptador sin I/O: materializa el cuerpo con el control resuelto por id."""

    if not spec.uses_control():
        return spec.resolved_body()
    if spec.case_id not in controls:
        raise KeyError(f"sin control para {spec.case_id!r}")
    return spec.resolved_body(controls[spec.case_id])
