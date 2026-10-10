"""Orquestador serial del sondeo.

Integra inventario, solver, cliente y recorder. Ejecuta E0 primero, invoca al
solver una única vez, corre los ejes independientes y agenda E7 entre
secuencias. Nunca pausa ni solicita entrada humana y nunca reinicia el
presupuesto.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .binding import IdentifierBinding
from .control_solver import control_for, solve
from .models import (
    KIND_EXPLORATION,
    KIND_RETRY,
    RunState,
    SequenceState,
    SolverResult,
    StopReason,
    parse_semantic,
)
from .oracle_client import AttemptMeta, OracleClient, StopRequested
from .recorder import ExperimentRecorder, PersistenceError, RunStateStore
from .settings import (
    ASSUMED_PRIOR_CONSUMPTION,
    CUTOFF_AT,
    E7_SPECIAL_LOCAL,
    LOCAL_UTC_OFFSET_HOURS,
)

TERMINAL_SEQUENCE_STATUSES = {
    "complete",
    "incomplete",
    "uncertain",
    "aborted_control_rejected",
}
DEPENDENT_AXES = {"E4", "E5", "E8"}


class _Hooks:
    """Persiste el journal antes del envío y la evidencia después."""

    def __init__(self, runner: "ProbeRunner", seq_id: str, note=None):
        self.runner = runner
        self.seq_id = seq_id
        self.note = note

    def before_send(self, meta: AttemptMeta) -> None:
        r = self.runner
        r.state.pending_attempt = {
            "attempt_id": meta.attempt_id,
            "case_id": meta.spec.case_id,
            "seq": meta.seq,
            "hipotesis": meta.spec.hypothesis,
            "request": parse_semantic(meta.spec.content_type, meta.body_text),
            "axis": meta.spec.axis,
            "metodo": meta.spec.method,
            "ruta": meta.spec.path,
            "tipo_contenido": meta.spec.content_type,
            "auth": meta.spec.auth_mode,
            "request_raw": meta.body_text,
            "retry_index": meta.retry_index,
            "attempt_of": meta.attempt_of,
        }
        r._save_state()

    def after_send(self, result, meta: AttemptMeta) -> None:
        r = self.runner
        r.recorder.record(
            meta.spec,
            result,
            body_text=meta.body_text,
            observed_at=r.clock.now_utc().isoformat(),
            seq=meta.seq,
            attempt_of=meta.attempt_of,
            retry_index=meta.retry_index,
            note=self.note,
        )
        r.state.pending_attempt = None
        r._save_state()


class ProbeRunner:
    def __init__(
        self,
        *,
        client: OracleClient,
        recorder: ExperimentRecorder,
        inventory,
        examples: list,
        state_store: RunStateStore,
        clock=None,
        cutoff: datetime = CUTOFF_AT,
        progress: Optional[Callable[[str], None]] = None,
    ):
        self.client = client
        self.recorder = recorder
        self.inventory = inventory
        self.examples = examples
        self.state_store = state_store
        self.clock = clock or client.clock
        self.cutoff = cutoff
        self._progress_fn = progress
        self.state = RunState()
        self.solver_result: Optional[SolverResult] = None
        self._done_case_ids: set = set()
        self._e7_times: list = []
        self._control_rejected = False
        self._bindings: dict = {}
        self.summary: dict = {}

    # -- utilidades ------------------------------------------------------

    def _progress(self, message: str) -> None:
        if self._progress_fn is not None:
            self._progress_fn(message)
        else:
            print(f"[probe] {message}", file=sys.stderr, flush=True)

    @property
    def _stopped(self) -> bool:
        return self.state.stop_reason is not None

    def _save_state(self) -> None:
        self.state.next_id = self.recorder.next_id
        self.state.call_count = self.client.calls_made
        self.state_store.save(self.state.to_dict())

    def _stop(self, reason: StopReason, note: str = "") -> None:
        if self.state.stop_reason is None:
            self.state.stop_reason = reason.value
            try:
                self._save_state()
            except PersistenceError:
                # Persistir el motivo es best-effort: la detención ya está
                # decidida y el resumen final no debe perderse por el guardado.
                pass
        self._progress(f"detención: {reason.value} {note}".strip())

    def _mark(self, sequence_id: str, status: str, note: Optional[str] = None) -> None:
        state = SequenceState(sequence_id, status, note=note)
        self.state.sequences[sequence_id] = state.to_dict()
        self._save_state()

    # -- arranque y reanudación ------------------------------------------

    def _restore(self) -> None:
        self.state = RunState.from_dict(self.state_store.load())
        if not self.state.started_at:
            self.state.started_at = self.clock.now_utc().isoformat()
        self.client.calls_made = self.state.call_count
        pending = self.state.pending_attempt
        if pending:
            self.recorder.recover_pending(
                pending, observed_at=self.clock.now_utc().isoformat()
            )
            self.state.pending_attempt = None
            self._save_state()
            self._progress("intento huérfano registrado como resultado desconocido")

    def _schedule_e7(self) -> list:
        started = datetime.fromisoformat(self.state.started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        times = []
        cursor = started + timedelta(hours=1)
        while cursor < self.cutoff:
            times.append(cursor)
            cursor += timedelta(hours=1)
        special = datetime(
            2026,
            10,
            10,
            E7_SPECIAL_LOCAL[0],
            E7_SPECIAL_LOCAL[1],
            tzinfo=timezone(timedelta(hours=LOCAL_UTC_OFFSET_HOURS)),
        ).astimezone(timezone.utc)
        if started < special < self.cutoff:
            times.append(special)
        return sorted(set(times))

    # -- envío -----------------------------------------------------------

    def _body_for(self, spec, seq_id: str):
        """Resuelve el cuerpo y la nota de binding de una solicitud.

        Los tokens de identificadores se sustituyen por los IDs reales ligados
        en la secuencia y el control se computa sobre el mensaje final. Devuelve
        ``(body, note)`` donde la nota describe tokens no ligados (o ``None``).
        """

        if not spec.uses_control():
            return spec.resolved_body(), None
        controls = self.solver_result.controls if self.solver_result else None
        if not controls:
            raise PersistenceError(f"sin vector de controles para {spec.case_id}")
        prefix = spec.control_prefix
        note = None
        binding = self._bindings.get(seq_id)
        if binding is not None:
            prefix, note = binding.substitute(prefix)
        control = control_for(prefix)
        body = json.dumps(
            {"m": f"{prefix};{control}"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return body, note

    def _observe_binding(self, body: Optional[str], result, seq_id: str) -> None:
        binding = self._bindings.get(seq_id)
        if binding is None or body is None:
            return
        try:
            message = json.loads(body).get("m")
        except (ValueError, AttributeError):
            return
        response = parse_semantic(None, result.response_text)
        binding.observe(message, response)

    def _send(self, spec, seq_id: str):
        body, note = self._body_for(spec, seq_id)
        results = self.client.send(
            spec, body, seq=seq_id, hooks=_Hooks(self, seq_id, note)
        )
        result = results[-1]
        self._observe_binding(body, result, seq_id)
        return result

    @staticmethod
    def _is_control_rejected(spec, result) -> bool:
        if not spec.uses_control():
            return False
        response = parse_semantic(None, result.response_text)
        return isinstance(response, dict) and response.get("error") == "E202"

    @staticmethod
    def _confirmed(result) -> bool:
        if not result.has_response() or result.infra:
            return False
        response = parse_semantic(None, result.response_text)
        if isinstance(response, dict) and response.get("error") is not None:
            return False
        return True

    def _on_control_rejected(self, seq_id: str) -> None:
        self._control_rejected = True
        self._mark(seq_id, "aborted_control_rejected", "control_candidate_rejected")
        self._progress(f"{seq_id}: control_candidate_rejected (E202)")

    # -- secuencias ------------------------------------------------------

    def _run_sequence(self, seq, dedup: bool = True) -> None:
        sequence_id = seq.sequence_id
        existing = self.state.sequences.get(sequence_id, {}).get("status")
        if existing in TERMINAL_SEQUENCE_STATUSES:
            self._progress(f"{sequence_id}: omitida (estado {existing})")
            return
        # El binding de identificadores es propio de la secuencia y arranca
        # limpio en su reset.
        self._bindings[sequence_id] = IdentifierBinding()
        # Una secuencia reiniciada explícitamente (estado ``pending``) se
        # re-ejecuta completa, sin saltar slots ya vistos: su binding debe
        # reconstruirse desde sus propias preparaciones (ALTA/DEPOSITO/TRANSFER).
        use_dedup = dedup and existing != "pending"
        if seq.axis in DEPENDENT_AXES:
            if self._control_rejected:
                self._mark(sequence_id, "aborted_control_rejected", "control rechazado")
                return
            if not (self.solver_result and self.solver_result.is_accepted()):
                cause = self.solver_result.status if self.solver_result else "sin_solver"
                self._mark(sequence_id, "pending_control_solver", cause)
                return

        for spec in seq.prep:
            if self._stopped:
                self._mark(sequence_id, "incomplete", "detenido")
                return
            if use_dedup and spec.case_id in self._done_case_ids:
                continue
            try:
                result = self._send(spec, sequence_id)
            except StopRequested as exc:
                self._stop(exc.reason, spec.case_id)
                self._mark(sequence_id, "incomplete", exc.reason.value)
                return
            if self._is_control_rejected(spec, result):
                self._on_control_rejected(sequence_id)
                return
            if not self._confirmed(result):
                self._mark(sequence_id, "incomplete", "preparación no confirmada")
                self._progress(f"{sequence_id}: preparación no confirmada")
                return

        uncertain = False
        for spec in seq.steps:
            if self._stopped:
                break
            if use_dedup and spec.case_id in self._done_case_ids:
                continue
            try:
                result = self._send(spec, sequence_id)
            except StopRequested as exc:
                self._stop(exc.reason, spec.case_id)
                self._mark(sequence_id, "incomplete", exc.reason.value)
                return
            if self._is_control_rejected(spec, result):
                self._on_control_rejected(sequence_id)
                return
            if not result.has_response() or result.infra:
                uncertain = True
                stateful = seq.axis in DEPENDENT_AXES or seq.axis == "E0"
                if stateful:
                    self._mark(sequence_id, "uncertain", "paso sin resultado")
                    self._progress(f"{sequence_id}: incierta en {spec.case_id}")
                    return
        self._mark(sequence_id, "uncertain" if uncertain else "complete")

    # -- solver ----------------------------------------------------------

    def _solve_once(self) -> None:
        # Solo se reutiliza un resultado persistido ya aceptado. Un estado con
        # otro veredicto (p. ej. ``ambiguous_e0`` por una versión anterior del
        # solver) se vuelve a resolver para no arrastrar la ambigüedad.
        if (
            self.state.solver_result
            and self.state.solver_result.get("status") == "accepted"
        ):
            self.solver_result = SolverResult.from_dict(self.state.solver_result)
            self._progress(f"solver (persistido): {self.solver_result.status}")
            return
        # Un sweep de E0 acepta el resultado de la exploración y también el de
        # un reintento de infraestructura: si el control válido llegó en el
        # reintento, debe contar para el solver.
        records = [
            r
            for r in self.recorder.read_all()
            if r.get("axis") == "E0"
            and r.get("kind") in (KIND_EXPLORATION, KIND_RETRY)
        ]
        result = solve(records, self.examples, self.inventory.control_slots())
        self.solver_result = result
        self.state.solver_result = result.to_dict()
        self._save_state()
        self._progress(f"solver: {result.status}")

    # -- agenda E7 -------------------------------------------------------

    def _maybe_run_e7(self) -> None:
        if self._stopped:
            return
        now = self.clock.now_utc()
        for scheduled in self._e7_times:
            key = scheduled.isoformat()
            if key in self.state.e7_done:
                continue
            if scheduled <= now:
                run_tag = scheduled.strftime("%m%dT%H%M")
                seq = self.inventory.build_e7_replay(self.examples, run_tag)
                self._run_sequence(seq, dedup=False)
                self.state.e7_done.append(key)
                self._save_state()
                if self._stopped:
                    return

    # -- ciclo principal -------------------------------------------------

    def run(self) -> dict:
        try:
            self._restore()
            self._done_case_ids = self.recorder.case_ids_done()
            self._e7_times = self._schedule_e7()
            self._progress(
                f"inicio: {self.inventory.exploration_count()} posiciones previstas"
            )
            self._run_sequence(self.inventory.e0_sequence())
            self._solve_once()
            for seq in self.inventory.sequences()[1:]:
                if self._stopped:
                    break
                self._maybe_run_e7()
                if self._stopped:
                    break
                self._run_sequence(seq)
            if not self._stopped:
                self._maybe_run_e7()
        except PersistenceError as exc:
            self._stop(StopReason.PERSISTENCE_FAILURE, str(exc))
        self._finish()
        return self.summary

    def _finish(self) -> None:
        records = self.recorder.read_all()
        planned = {
            spec.case_id
            for seq in self.inventory.sequences()
            for spec in seq.steps
        }
        planned_aux = {
            spec.case_id
            for seq in self.inventory.sequences()
            for spec in seq.prep
        }
        done = self.recorder.case_ids_done()
        axis_counts = self.inventory.axis_counts()
        axes = {}
        for axis, planned_count in axis_counts.items():
            axis_planned = {
                spec.case_id
                for seq in self.inventory.sequences()
                if seq.axis == axis
                for spec in seq.steps
            }
            executed = len(axis_planned & done)
            axes[axis] = {
                "prevista": planned_count,
                "ejecutada": executed,
                "pendiente": planned_count - executed,
            }
        statuses = [s.get("status") for s in self.state.sequences.values()]
        solver = self.solver_result.to_dict() if self.solver_result else None
        if solver:
            solver = {
                "status": solver["status"],
                "candidato": solver["provenance"],
                "huella": solver["vector_fingerprint"],
                "e0": solver["e0_values"],
            }
        self.summary = {
            "stop_reason": self.state.stop_reason or StopReason.COMPLETED.value,
            "exploracion": {
                "prevista": len(planned),
                "ejecutada": len(planned & done),
                "pendiente": len(planned - done),
            },
            "ejes": axes,
            "auxiliares": {
                "previstos": len(planned_aux),
                "ejecutados": len(planned_aux & done),
            },
            "reintentos": sum(1 for r in records if r.get("retry_index", 0) > 0),
            "infraestructura": sum(1 for r in records if r.get("infra")),
            "recuperados": sum(1 for r in records if r.get("nota") == "resultado_desconocido"),
            "solver": solver,
            "secuencias": {
                "completas": statuses.count("complete"),
                "incompletas": statuses.count("incomplete"),
                "inciertas": statuses.count("uncertain"),
                "abortadas_control": statuses.count("aborted_control_rejected"),
                "pendientes_control": statuses.count("pending_control_solver"),
            },
            "E7": {
                "previstas": len(self._e7_times),
                "efectivas": len(self.state.e7_done),
                "pendientes": len(self._e7_times) - len(self.state.e7_done),
            },
            "consumo": {
                "asumido_previo": ASSUMED_PRIOR_CONSUMPTION,
                "verificado": False,
                "llamadas_intentadas": self.state.call_count,
            },
        }
        try:
            self._save_state()
        except PersistenceError:
            pass
        self._progress("resumen: " + json.dumps(self.summary, ensure_ascii=False))
