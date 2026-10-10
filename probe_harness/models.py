"""Contratos inmutables y tipos compartidos del probe-harness.

Ningún tipo de este módulo conoce ejes, CLI ni transporte. Solo describe el
contrato de datos que comparten el cliente, el recorder y el orquestador.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# Modalidades de autenticación (nunca se registra el valor de la credencial).
AUTH_VALID = "valid"
AUTH_MISSING = "missing"
AUTH_INVALID = "invalid"

# Clases de registro de evidencia.
KIND_EXPLORATION = "exploration"
KIND_AUXILIARY = "auxiliary"
KIND_RETRY = "retry"
KIND_E7 = "e7"
KIND_RECOVERY = "recovery"


class StopReason(str, Enum):
    """Motivo de detención de la cola de envíos."""

    NONE = "none"
    COMPLETED = "completed"
    BUDGET = "budget"
    CUTOFF = "cutoff"
    PERSISTENCE_FAILURE = "persistence_failure"


@dataclass(frozen=True)
class RequestSpec:
    """Descripción completa y reproducible de una solicitud a enviar.

    ``body_raw`` es el texto exacto del cuerpo (``None`` = cuerpo ausente) y
    ``content_type`` su tipo (``None`` = ausente). Cuando ``control_prefix`` está
    presente, el cuerpo se materializa como JSON ``{"m": "<prefijo>;<control>"}``
    con el control resuelto por el solver; ``body_raw`` queda en ``None``.
    """

    case_id: str
    method: str
    path: str
    hypothesis: str
    axis: str
    kind: str = KIND_EXPLORATION
    auth_mode: str = AUTH_VALID
    body_raw: Optional[str] = None
    content_type: Optional[str] = None
    control_prefix: Optional[str] = None
    sequence: Optional[str] = None

    def uses_control(self) -> bool:
        return self.control_prefix is not None

    def resolved_body(self, control: Optional[int] = None) -> Optional[str]:
        if self.control_prefix is not None:
            if control is None:
                raise ValueError(
                    f"control requerido para {self.case_id!r} (usa C(id))"
                )
            payload = {"m": f"{self.control_prefix};{control}"}
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return self.body_raw


@dataclass(frozen=True)
class AttemptResult:
    """Resultado observable de un único intento de transporte."""

    case_id: str
    attempt_id: str
    status: Optional[int]
    x_req: Optional[str]
    response_text: Optional[str]
    infra: bool = False
    infra_header: Optional[str] = None
    error: Optional[str] = None
    auth_mode: str = AUTH_VALID

    def has_response(self) -> bool:
        return self.status is not None


@dataclass(frozen=True)
class ExperimentRecord:
    """Una línea de evidencia de ``experimentos.jsonl``."""

    id: int
    attempt_id: str
    case_id: str
    seq: str
    x_req: Optional[str]
    hipotesis: str
    request: Any
    status: Optional[int]
    response: Any
    conclusion: Optional[str]
    observed_at: str
    axis: str
    kind: str
    attempt_of: Optional[str]
    retry_index: int
    infra: bool
    metodo: str
    ruta: str
    tipo_contenido: Optional[str]
    auth: str
    request_raw: Optional[str]
    response_raw: Optional[str]
    infra_header: Optional[str]
    nota: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "attempt_id": self.attempt_id,
            "case_id": self.case_id,
            "seq": self.seq,
            "x_req": self.x_req,
            "hipotesis": self.hipotesis,
            "request": self.request,
            "status": self.status,
            "response": self.response,
            "conclusion": self.conclusion,
            "observed_at": self.observed_at,
            "axis": self.axis,
            "kind": self.kind,
            "attempt_of": self.attempt_of,
            "retry_index": self.retry_index,
            "infra": self.infra,
            "metodo": self.metodo,
            "ruta": self.ruta,
            "tipo_contenido": self.tipo_contenido,
            "auth": self.auth,
            "request_raw": self.request_raw,
            "response_raw": self.response_raw,
            "infra_header": self.infra_header,
            "nota": self.nota,
        }


@dataclass
class SequenceState:
    """Estado de una secuencia con estado (E4/E5/E8) o de seguimiento."""

    sequence_id: str
    status: str = "pending"
    steps_done: int = 0
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "status": self.status,
            "steps_done": self.steps_done,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SequenceState":
        return cls(
            sequence_id=data["sequence_id"],
            status=data.get("status", "pending"),
            steps_done=data.get("steps_done", 0),
            note=data.get("note"),
        )


@dataclass
class RunState:
    """Journal de ejecución reanudable; nunca contiene credenciales."""

    started_at: Optional[str] = None
    next_id: int = 1
    call_count: int = 0
    pending_attempt: Optional[dict] = None
    solver_result: Optional[dict] = None
    e7_done: list = field(default_factory=list)
    sequences: dict = field(default_factory=dict)
    stop_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "next_id": self.next_id,
            "call_count": self.call_count,
            "pending_attempt": self.pending_attempt,
            "solver_result": self.solver_result,
            "e7_done": list(self.e7_done),
            "sequences": dict(self.sequences),
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "RunState":
        if not data:
            return cls()
        return cls(
            started_at=data.get("started_at"),
            next_id=data.get("next_id", 1),
            call_count=data.get("call_count", 0),
            pending_attempt=data.get("pending_attempt"),
            solver_result=data.get("solver_result"),
            e7_done=list(data.get("e7_done", [])),
            sequences=dict(data.get("sequences", {})),
            stop_reason=data.get("stop_reason"),
        )


@dataclass(frozen=True)
class ControlProvenance:
    """Procedencia determinista del candidato adoptado por el solver."""

    canonicalizer: str
    metric: str
    a: int
    b: int

    def to_dict(self) -> dict:
        return {
            "canonicalizer": self.canonicalizer,
            "metric": self.metric,
            "a": self.a,
            "b": self.b,
        }


@dataclass(frozen=True)
class SolverResult:
    """Resultado inmutable del solver de control autónomo."""

    status: str  # accepted | no_candidate | ambiguous_e0 | ambiguous_candidate
    provenance: Optional[ControlProvenance]
    fit_count: int
    holdout_count: int
    e0_values: dict
    vector_fingerprint: Optional[str]
    controls: Optional[dict] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "fit_count": self.fit_count,
            "holdout_count": self.holdout_count,
            "e0_values": dict(self.e0_values),
            "vector_fingerprint": self.vector_fingerprint,
            "controls": dict(self.controls) if self.controls else None,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SolverResult":
        prov = data.get("provenance")
        return cls(
            status=data["status"],
            provenance=ControlProvenance(**prov) if prov else None,
            fit_count=data.get("fit_count", 0),
            holdout_count=data.get("holdout_count", 0),
            e0_values=dict(data.get("e0_values", {})),
            vector_fingerprint=data.get("vector_fingerprint"),
            controls=dict(data["controls"]) if data.get("controls") else None,
            reason=data.get("reason"),
        )

    def is_accepted(self) -> bool:
        return self.status == "accepted"


@dataclass(frozen=True)
class ProbeSequence:
    """Secuencia de sondeo: preparación auxiliar y posiciones de exploración."""

    sequence_id: str
    axis: str
    prep: tuple
    steps: tuple

    def all_requests(self) -> tuple:
        return tuple(self.prep) + tuple(self.steps)


def parse_semantic(content_type: Optional[str], text: Optional[str]) -> Any:
    """Valor semántico de un cuerpo: JSON parseado o texto exacto.

    Conserva el texto original sin normalizar cuando no es JSON.
    """

    if text is None:
        return None
    if text == "":
        return ""
    head = text.lstrip()[:1]
    is_json_type = bool(content_type) and "json" in content_type.lower()
    looks_like_json = head in "{[\\\"" or text.strip() in ("null", "true", "false")
    if is_json_type or looks_like_json:
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text
    return text


def desired_kind(base_kind: str, retry_index: int) -> str:
    """Clase de registro: un reintento deja de ser la clase original."""

    if retry_index > 0:
        return KIND_RETRY
    return base_kind
