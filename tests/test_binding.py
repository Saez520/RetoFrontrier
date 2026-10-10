"""Binding de identificadores (B2): sustitución antes de calcular el control.

Las pruebas usan un doble de cliente: no hay tráfico de red.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from probe_harness.binding import IdentifierBinding
from probe_harness.control_solver import control_for
from probe_harness.models import ControlProvenance, RequestSpec, SolverResult
from probe_harness.oracle_client import OracleClient, TransportResponse
from probe_harness.recorder import ExperimentRecorder, RunStateStore
from probe_harness.runner import ProbeRunner

CUTOFF = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)
START = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def monotonic(self):
        return 0.0

    def now_utc(self):
        return START


class RecorderTransport:
    """Doble de transporte que despacha por cuerpo y guarda lo enviado."""

    def __init__(self, handler):
        self.handler = handler
        self.bodies = []

    def __call__(self, method, url, headers, body, timeout):
        self.bodies.append(body)
        return self.handler(body)


def json_body(message: str) -> bytes:
    return json.dumps({"m": message}, separators=(",", ":")).encode("utf-8")


def _spec(case_id: str, prefix: str, *, axis="E4", kind="exploration") -> RequestSpec:
    return RequestSpec(
        case_id=case_id,
        method="POST",
        path="/msg",
        hypothesis=case_id,
        axis=axis,
        kind=kind,
        control_prefix=prefix,
        content_type="application/json",
    )


def accepted_solver() -> SolverResult:
    return SolverResult(
        status="accepted",
        provenance=ControlProvenance("letters_a1z26_omit_other", "iso7064_mod97_10", 0, 0),
        fit_count=2,
        holdout_count=0,
        e0_values={},
        vector_fingerprint="fp",
        controls={"placeholder": 0},
    )


class BindingUnitTest(unittest.TestCase):
    def test_alta_binds_name_to_cuenta_id(self):
        binding = IdentifierBinding()
        binding.observe("ALTA;E4-A;25", {"cuentaId": "AC-0001"})
        resolved, note = binding.substitute("CONSULTA;E4-A")
        self.assertEqual(resolved, "CONSULTA;AC-0001")
        self.assertIsNone(note)

    def test_operacion_index_maps_to_kth_observed(self):
        binding = IdentifierBinding()
        binding.observe("DEPOSITO;AC-0001;1000;90", {"operacionId": "OP-0007"})
        binding.observe("TRANSFER;AC-0001;AC-0002;100;12", {"operacionId": "OP-0008"})
        resolved, note = binding.substitute("ANULA;OP-0002")
        self.assertEqual(resolved, "ANULA;OP-0008")
        self.assertIsNone(note)

    def test_unbound_token_stays_literal_with_note(self):
        binding = IdentifierBinding()
        resolved, note = binding.substitute("CONSULTA;E4-A")
        self.assertEqual(resolved, "CONSULTA;E4-A")
        self.assertEqual(note, "token no ligado: E4-A")

    def test_alta_creation_name_is_not_flagged(self):
        binding = IdentifierBinding()
        resolved, note = binding.substitute("ALTA;E4-A")
        self.assertEqual(resolved, "ALTA;E4-A")
        self.assertIsNone(note)

    def test_reset_clears_binding(self):
        binding = IdentifierBinding()
        binding.observe("ALTA;E4-A;25", {"cuentaId": "AC-0001"})
        binding.reset()
        resolved, note = binding.substitute("CONSULTA;E4-A")
        self.assertEqual(resolved, "CONSULTA;E4-A")
        self.assertIsNotNone(note)

    def test_boundary_avoids_partial_name_match(self):
        binding = IdentifierBinding()
        binding.observe("ALTA;E4-A;25", {"cuentaId": "AC-0001"})
        resolved, _ = binding.substitute("CONSULTA;E4-AB")
        self.assertEqual(resolved, "CONSULTA;E4-AB")


class RunnerBindingTest(unittest.TestCase):
    """La prep ALTA liga el nombre; el paso posterior sale con el ID y f."""

    def _runner(self, tmp, handler):
        transport = RecorderTransport(handler)
        client = OracleClient(
            transport,
            FakeClock(),
            sleeper=lambda _s: None,
            base_url="https://x.test",
            token="t",
            cutoff=CUTOFF,
        )
        recorder = ExperimentRecorder(os.path.join(tmp, "log.jsonl"))
        state_store = RunStateStore(os.path.join(tmp, "state.json"))
        runner = ProbeRunner(
            client=client,
            recorder=recorder,
            inventory=None,
            examples=[],
            state_store=state_store,
            clock=FakeClock(),
            progress=lambda _m: None,
        )
        runner.solver_result = accepted_solver()
        runner._bindings["SEQ"] = IdentifierBinding()
        return runner, transport

    def test_name_bound_then_substituted_before_control(self):
        def handler(body):
            if body == json_body(f"ALTA;E4-A;{control_for('ALTA;E4-A')}"):
                return TransportResponse(201, {}, b'{"cuentaId":"AC-0001"}')
            return TransportResponse(200, {}, b'{"ok":true}')

        with tempfile.TemporaryDirectory() as tmp:
            runner, transport = self._runner(tmp, handler)
            runner._send(_spec("PREP", "ALTA;E4-A", kind="auxiliary"), "SEQ")
            runner._send(_spec("STEP", "DEPOSITO;E4-A;100"), "SEQ")

            final_prefix = f"DEPOSITO;AC-0001;100;{control_for('DEPOSITO;AC-0001;100')}"
            self.assertEqual(transport.bodies[-1], json_body(final_prefix))

    def test_operation_index_bound_from_sequence(self):
        def handler(body):
            if body == json_body(f"DEPOSITO;AC-0001;1000;{control_for('DEPOSITO;AC-0001;1000')}"):
                return TransportResponse(200, {}, b'{"status":"recieved","operacionId":"OP-0007"}')
            return TransportResponse(200, {}, b'{"ok":true}')

        with tempfile.TemporaryDirectory() as tmp:
            runner, transport = self._runner(tmp, handler)
            runner._send(_spec("PREP", "DEPOSITO;AC-0001;1000", kind="auxiliary"), "SEQ")
            runner._send(_spec("STEP", "ANULA;OP-0001"), "SEQ")

            final_prefix = f"ANULA;OP-0007;{control_for('ANULA;OP-0007')}"
            self.assertEqual(transport.bodies[-1], json_body(final_prefix))

    def test_unbound_token_is_recorded_with_note(self):
        def handler(body):
            return TransportResponse(200, {}, b'{"ok":true}')

        with tempfile.TemporaryDirectory() as tmp:
            runner, transport = self._runner(tmp, handler)
            runner._send(_spec("STEP", "CONSULTA;E4-A"), "SEQ")
            record = runner.recorder.read_all()[-1]
            self.assertEqual(record["request"], {"m": f"CONSULTA;E4-A;{control_for('CONSULTA;E4-A')}"})
            self.assertEqual(record["nota"], "token no ligado: E4-A")


if __name__ == "__main__":
    unittest.main()
