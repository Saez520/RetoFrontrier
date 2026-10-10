"""Solver de control basado en la función exacta derivada.

La función de control es ISO 7064 MOD 97-10 sobre ``S(base)``: cada letra se
mapea a su posición 1..26 (sin distinguir mayúsculas), cada dígito se conserva y
cualquier otro carácter se omite. El control canónico es
``f(base) = 98 - (N*100 % 97)`` (rango 2..98, sin reducción final mod 97) y la
aceptación es por igualdad exacta ``int(control) == f(base)``.

La congruencia ``(N*100 + control) % 97 == 1`` no describe al original: en los
bordes ``N*100 % 97 == 0`` (f=98) y ``== 1`` (f=97) aceptaría 1 y 0, que el
servicio rechaza con ``E202``.

El solver no ejecuta solicitudes, no lee credenciales y no solicita valores
humanos: valida la derivación contra las bases medidas en E0 y materializa los
controles de cada slot con ``f(prefijo)``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from .inventory import E0_CONTROL_BASES
from .models import ControlProvenance, RequestSpec, SolverResult

E0_EXCLUDED_ERRORS = ("E201", "E202")

# Bases del catálogo de pruebas que usan el control derivado (12 pares).
ISO7064_MODULUS = 97


# --- función exacta -------------------------------------------------------


def _encode_base(base: str) -> str:
    """``S(base)``: letra→1..26 (case-insensitive), dígito→dígito, resto omitido."""

    parts = []
    for char in base:
        if "0" <= char <= "9":
            parts.append(char)
        elif "A" <= char <= "Z":
            parts.append(str(ord(char) - ord("A") + 1))
        elif "a" <= char <= "z":
            parts.append(str(ord(char) - ord("a") + 1))
    return "".join(parts)


def _base_number(base: str) -> int:
    encoded = _encode_base(base)
    return int(encoded) if encoded else 0


def control_for(base: str) -> int:
    """Control canónico ``f(base) = 98 - (N*100 % 97)`` (rango 2..98)."""

    number = _base_number(base)
    return 98 - (number * 100 % ISO7064_MODULUS)


def is_control_valid(base: str, control: int) -> bool:
    """Aceptación por igualdad exacta: ``control == f(base)``."""

    return control == control_for(base)


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
    examples: Optional[list] = None,
    slots: Optional[list] = None,
    *,
    validation_bases: tuple = E0_CONTROL_BASES,
) -> SolverResult:
    """Deriva el vector de controles o reporta la causa exacta de no derivación.

    ``examples`` se acepta por compatibilidad de contrato y no interviene: la
    función de control es fija y no se ajusta a partir del catálogo.
    """

    if slots is None:
        slots = []

    grouped = extract_e0_values(e0_records)
    e0_values = {}
    for base in validation_bases:
        measured = grouped.get(base, set())
        if len(measured) != 1:
            return SolverResult(
                status="ambiguous_e0",
                provenance=None,
                fit_count=len(validation_bases),
                holdout_count=0,
                e0_values={},
                vector_fingerprint=None,
                controls=None,
                reason=f"{base}: {len(measured)} controles aceptados en E0",
            )
        (value,) = tuple(measured)
        expected = control_for(base)
        if value != expected:
            return SolverResult(
                status="ambiguous_e0",
                provenance=None,
                fit_count=len(validation_bases),
                holdout_count=0,
                e0_values={base: value},
                vector_fingerprint=None,
                controls=None,
                reason=f"{base}: E0={value} difiere de f={expected}",
            )
        e0_values[base] = value

    controls = {case_id: control_for(prefix) for case_id, prefix in slots}
    vector = sorted(controls.items())
    return SolverResult(
        status="accepted",
        provenance=ControlProvenance(
            canonicalizer="letters_a1z26_omit_other",
            metric="iso7064_mod97_10",
            a=0,
            b=0,
        ),
        fit_count=len(validation_bases),
        holdout_count=0,
        e0_values=e0_values,
        vector_fingerprint=_vector_fingerprint(vector),
        controls=controls,
        reason=None,
    )


def apply_control_vector(spec: RequestSpec, controls: dict) -> Optional[str]:
    """Adaptador sin I/O: materializa el cuerpo con el control resuelto por id."""

    if not spec.uses_control():
        return spec.resolved_body()
    if spec.case_id not in controls:
        raise KeyError(f"sin control para {spec.case_id!r}")
    return spec.resolved_body(controls[spec.case_id])
