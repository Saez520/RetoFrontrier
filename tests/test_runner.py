"""Runner: orden, solver único, fallback autónomo, fail-fast, reanudación, E7."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from probe_harness.control_solver import load_examples
from probe_harness.inventory import Inventory
from probe_harness.models import ControlProvenance, SolverResult
from probe_harness.oracle_client import OracleClient, TransportError, TransportResponse
from probe_harness.recorder import ExperimentRecorder, RunStateStore
from probe_harness.runner import ProbeRunner
from probe_harness.settings import EXAMPLES_PATH

CUTOFF = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)
START = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=START):
        self.now = now
        self.mono = 0.0

    def monotonic(self):
        return self.mono

    def now_utc(self):
        return self.now

    def advance(self, seconds):
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


class ScriptedTransport:
    def __init__(self, handler=None):
        self.handler = handler or (lambda method, url, headers, body: TransportResponse(200, {}, b"{}"))
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "body": body})
        return self.handler(method, url, headers, body)


def accepted_result(inv, value=7):
    controls = {case_id: value for case_id, _ in inv.control_slots()}
    return SolverResult(
        status="accepted",
        provenance=ControlProvenance("raw", "sum", 1, 0),
        fit_count=13,
        holdout_count=3,
        e0_values={"PING": 64},
        vector_fingerprint="fp",
        controls=controls,
    ).to_dict()


def no_candidate_result():
    return SolverResult(
        status="no_candidate",
        provenance=None,
        fit_count=13,
        holdout_count=3,
        e0_values={},
        vector_fingerprint=None,
        controls=None,
    ).to_dict()


def synthetic_examples():
    return [{"request": {"m": "PING;64"}} for _ in range(20)]


class RunnerHarness:
    def __init__(self, tmp, solver_result, handler=None, max_calls=1000, now=START, started_at=None, examples=None):
        self.clock = FakeClock(now)
        self.transport = ScriptedTransport(handler)
        self.client = OracleClient(
            self.transport,
            self.clock,
            sleeper=self.clock.advance,
            base_url="https://x.test",
            token="t",
            max_calls=max_calls,
            cutoff=CUTOFF,
        )
        self.log = os.path.join(tmp, "log.jsonl")
        self.state_path = os.path.join(tmp, "state.json")
        self.recorder = ExperimentRecorder(self.log)
        self.state_store = RunStateStore(self.state_path)
        self.inventory = Inventory()
        if solver_result is not None:
            self.state_store.save(
                {
                    "started_at": (started_at or self.clock.now_utc()).isoformat(),
                    "solver_result": solver_result,
                }
            )
        self.runner = ProbeRunner(
            client=self.client,
            recorder=self.recorder,
            inventory=self.inventory,
            examples=examples if examples is not None else synthetic_examples(),
            state_store=self.state_store,
            clock=self.clock,
            progress=lambda message: None,
        )

    def run(self):
        return self.runner.run()


class OrderAndSolverTest(unittest.TestCase):
    def test_e0_first_and_single_solver(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None)
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            calls = {"n": 0}
            original = h.runner._solve_once

            def spy():
                calls["n"] += 1
                return original()

            h.runner._solve_once = spy
            summary = h.run()
            self.assertEqual(calls["n"], 1)
            records = h.recorder.read_all()
            self.assertEqual(records[0]["case_id"], "AUX-E0-RESET")
            self.assertEqual(records[0]["axis"], "E0")
            self.assertEqual(summary["exploracion"]["ejecutada"], 680)
            self.assertEqual(summary["stop_reason"], "completed")

    def test_resume_does_not_repeat_e0(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None)
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            h.run()
            first_len = len(h.recorder.read_all())
            h2 = RunnerHarness(tmp, None)
            h2.run()
            self.assertEqual(len(h2.recorder.read_all()), first_len)


class FallbackTest(unittest.TestCase):
    def test_no_candidate_runs_independent_axes(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = RunnerHarness(tmp, no_candidate_result())
            summary = h.run()
            records = h.recorder.read_all()
            cases = {r["case_id"] for r in records}
            self.assertIn("E1-01", cases)
            self.assertIn("E2-01", cases)
            self.assertIn("E3-01", cases)
            self.assertIn("E6-01", cases)
            self.assertNotIn("E4-01", cases)
            self.assertFalse(any(c.startswith("E8-") for c in cases))
            statuses = h.runner.state.sequences
            self.assertEqual(statuses["PING"]["status"], "pending_control_solver")
            self.assertEqual(statuses["E5-01"]["status"], "pending_control_solver")
            self.assertEqual(statuses["E8-01"]["status"], "pending_control_solver")
            self.assertEqual(summary["solver"]["status"], "no_candidate")


class FailFastTest(unittest.TestCase):
    def test_e202_aborts_dependent_axes(self):
        def handler(method, url, headers, body):
            if body == b'{"m":"PING;7"}':
                return TransportResponse(400, {}, b'{"error":"E202","mensaje":"control inv\xc3\xa1lido"}')
            return TransportResponse(200, {}, b"{}")

        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None, handler=handler)
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            h.run()
            cases = {r["case_id"] for r in h.recorder.read_all()}
            self.assertIn("E4-01", cases)
            self.assertIn("E6-01", cases)
            self.assertNotIn("E4-02", cases)
            self.assertFalse(any(c.startswith("E5-") for c in cases))
            self.assertFalse(any(c.startswith("E8-") for c in cases))
            self.assertEqual(h.runner.state.sequences["PING"]["status"], "aborted_control_rejected")
            self.assertEqual(h.runner.state.sequences["E5-01"]["status"], "aborted_control_rejected")


class UncertainSequenceTest(unittest.TestCase):
    def test_missing_response_stops_dependents(self):
        target = b'{"m":"ALTA;E5-01-B;7"}'

        def handler(method, url, headers, body):
            if body == target:
                raise TransportError("timeout")
            return TransportResponse(200, {}, b"{}")

        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None, handler=handler)
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            h.run()
            cases = {r["case_id"] for r in h.recorder.read_all()}
            self.assertIn("E5-01-01", cases)
            self.assertIn("E5-01-02", cases)
            self.assertNotIn("E5-01-03", cases)
            self.assertNotIn("E5-01-04", cases)
            self.assertEqual(h.runner.state.sequences["E5-01"]["status"], "uncertain")


class BudgetTest(unittest.TestCase):
    def test_budget_stops_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None, max_calls=5)
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            summary = h.run()
            self.assertEqual(summary["stop_reason"], "budget")
            self.assertEqual(h.client.calls_made, 5)
            self.assertEqual(h.runner.state.sequences["E0"]["status"], "incomplete")


class E7Test(unittest.TestCase):
    def test_hourly_replay_between_sequences(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None, now=START + timedelta(hours=1, minutes=30))
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            summary = h.run()
            records = h.recorder.read_all()
            e7 = [r for r in records if r["axis"] == "E7"]
            self.assertTrue(e7)
            self.assertGreaterEqual(summary["E7"]["efectivas"], 1)


class SummaryTest(unittest.TestCase):
    def test_summary_fields_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = Inventory()
            h = RunnerHarness(tmp, None)
            h.state_store.save({"started_at": START.isoformat(), "solver_result": accepted_result(inv)})
            summary = h.run()
            for key in (
                "stop_reason",
                "exploracion",
                "ejes",
                "auxiliares",
                "reintentos",
                "infraestructura",
                "solver",
                "secuencias",
                "E7",
                "consumo",
            ):
                self.assertIn(key, summary)
            self.assertEqual(summary["consumo"]["asumido_previo"], 0)
            self.assertFalse(summary["consumo"]["verificado"])


class FirstRunStateTest(unittest.TestCase):
    """La primera corrida arranca con un state-path inexistente o vacío.

    El preflight crea el journal como archivo vacío antes de la primera
    solicitud; ese estado debe interpretarse como ``{}`` y no abortar la corrida.
    """

    def test_first_run_with_missing_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = RunnerHarness(tmp, None)
            self.assertFalse(os.path.exists(h.state_path))
            summary = h.run()
            records = h.recorder.read_all()
            self.assertEqual(records[0]["case_id"], "AUX-E0-RESET")
            self.assertEqual(summary["stop_reason"], "completed")

    def test_first_run_with_empty_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = RunnerHarness(tmp, None)
            with open(h.state_path, "w", encoding="utf-8"):
                pass
            summary = h.run()
            records = h.recorder.read_all()
            self.assertEqual(records[0]["case_id"], "AUX-E0-RESET")
            self.assertEqual(summary["stop_reason"], "completed")


class SolveRetryPathTest(unittest.TestCase):
    """La ruta real ``_solve_once -> solve`` incluye el resultado de un reintento.

    Si el control válido de una base de E0 llega recién en el reintento de
    infraestructura, el sweep no debe quedar con cero aceptados (``ambiguous_e0``
    espurio): el resultado del reintento también alimenta al solver.
    """

    def _handler(self, attempts):
        def handler(method, url, headers, body):
            message = None
            if body:
                try:
                    message = json.loads(body.decode("utf-8")).get("m")
                except (ValueError, UnicodeDecodeError, AttributeError):
                    message = None
            if message == "PING;64":
                attempts["ping64"] = attempts.get("ping64", 0) + 1
                if attempts["ping64"] == 1:
                    return TransportResponse(
                        503, {"X-Frontier-Infra": "1"}, b'{"error":"down"}'
                    )
                return TransportResponse(200, {}, b'{"pong":true}')
            if message in ("ALTA;Lucia;82", "CONSULTA;AC-0009;87"):
                return TransportResponse(200, {}, b"{}")
            if isinstance(message, str) and ";" in message:
                return TransportResponse(400, {}, b'{"error":"E201"}')
            return TransportResponse(200, {}, b"{}")

        return handler

    def test_retry_success_reaches_solver(self):
        examples = load_examples(EXAMPLES_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            h = RunnerHarness(
                tmp, None, handler=self._handler({}), examples=examples
            )
            summary = h.run()
            kinds = [
                r["kind"]
                for r in h.recorder.read_all()
                if r.get("case_id") == "E0-PING-64"
            ]
        self.assertIn("retry", kinds)
        self.assertNotEqual(summary["solver"]["status"], "ambiguous_e0")
        self.assertEqual(summary["solver"]["e0"]["PING"], 64)


if __name__ == "__main__":
    unittest.main()