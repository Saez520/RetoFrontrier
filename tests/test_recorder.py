"""Recorder durable, journal de reanudación y recuperación de pendientes."""

import json
import os
import tempfile
import unittest
from unittest import mock

from probe_harness import models
from probe_harness.recorder import ExperimentRecorder, PersistenceError, RunStateStore


def make_spec(case_id="E1-01", **overrides):
    data = dict(
        case_id=case_id,
        method="POST",
        path="/msg",
        hypothesis=f"{case_id}: prueba",
        axis="E1",
        body_raw='{"m":"PING;64"}',
        content_type="application/json",
        sequence="E1",
    )
    data.update(overrides)
    return models.RequestSpec(**data)


def make_result(case_id="E1-01", **overrides):
    data = dict(
        case_id=case_id,
        attempt_id="a1",
        status=200,
        x_req="1",
        response_text='{"pong":true}',
    )
    data.update(overrides)
    return models.AttemptResult(**data)


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "experimentos.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_monotonic_ids_and_fsync(self):
        recorder = ExperimentRecorder(self.log)
        with mock.patch("probe_harness.recorder.os.fsync") as fsync:
            r1 = recorder.record(
                make_spec("E1-01"),
                make_result("E1-01", attempt_id="a1"),
                body_text='{"m":"PING;64"}',
                observed_at="2026-10-10T00:00:00Z",
                seq="E1",
            )
            r2 = recorder.record(
                make_spec("E1-02"),
                make_result("E1-02", attempt_id="a2"),
                body_text='{"m":"PING;64"}',
                observed_at="2026-10-10T00:00:01Z",
                seq="E1",
            )
        self.assertEqual((r1["id"], r2["id"]), (1, 2))
        self.assertEqual(fsync.call_count, 2)
        with open(self.log, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(lines), 2)

    def test_json_and_text_fidelity_and_null_conclusion(self):
        recorder = ExperimentRecorder(self.log)
        recorder.record(
            make_spec("E1-01"),
            make_result("E1-01", response_text='{"a":[1,2]}'),
            body_text='{"m":"PING;64"}',
            observed_at="t",
            seq="E1",
        )
        recorder.record(
            make_spec("E3-01", body_raw="PING", content_type="text/plain"),
            make_result("E3-01", attempt_id="b", response_text="error \n"),
            body_text="PING",
            observed_at="t",
            seq="E3",
        )
        lines = recorder.read_all()
        self.assertEqual(lines[0]["response"], {"a": [1, 2]})
        self.assertEqual(lines[0]["conclusion"], None)
        self.assertEqual(lines[1]["response_raw"], "error \n")
        self.assertEqual(lines[1]["response"], "error \n")

    def test_absent_response_is_explicit(self):
        recorder = ExperimentRecorder(self.log)
        record = recorder.record(
            make_spec("E1-08", method="GET", path="/missing", body_raw=None, content_type=None),
            make_result("E1-08", status=None, x_req=None, response_text=None, error="timeout"),
            body_text=None,
            observed_at="t",
            seq="E1",
        )
        self.assertIsNone(record["status"])
        self.assertIsNone(record["x_req"])
        self.assertIsNone(record["response"])
        self.assertIsNone(record["response_raw"])
        self.assertIsNone(record["request"])

    def test_no_token_in_evidence(self):
        recorder = ExperimentRecorder(self.log)
        recorder.record(
            make_spec("E1-01"),
            make_result("E1-01"),
            body_text='{"m":"PING;64"}',
            observed_at="t",
            seq="E1",
        )
        blob = json.dumps(recorder.read_all(), ensure_ascii=False)
        self.assertNotIn("Bearer", blob)
        self.assertNotIn("Authorization", blob)

    def test_ids_continue_after_existing_log(self):
        recorder = ExperimentRecorder(self.log)
        recorder.record(make_spec("E1-01"), make_result(), body_text="{}", observed_at="t", seq="E1")
        reopened = ExperimentRecorder(self.log)
        self.assertEqual(reopened.next_id, 2)

    def test_recover_pending_records_unknown(self):
        recorder = ExperimentRecorder(self.log)
        pending = {
            "attempt_id": "zz",
            "case_id": "E5-01-02",
            "seq": "E5-01",
            "hipotesis": "h",
            "request": {"m": "X"},
            "axis": "E5",
            "metodo": "POST",
            "ruta": "/msg",
            "tipo_contenido": "application/json",
            "auth": "valid",
            "request_raw": '{"m":"X"}',
            "retry_index": 0,
            "attempt_of": None,
        }
        record = recorder.recover_pending(pending, observed_at="t")
        self.assertEqual(record["case_id"], "E5-01-02")
        self.assertIsNone(record["status"])
        self.assertEqual(record["nota"], "resultado_desconocido")
        self.assertEqual(len(recorder.read_all()), 1)

    def test_case_ids_done(self):
        recorder = ExperimentRecorder(self.log)
        recorder.record(make_spec("E1-01"), make_result(), body_text="{}", observed_at="t", seq="E1")
        self.assertEqual(recorder.case_ids_done(), {"E1-01"})


class RunStateStoreTest(unittest.TestCase):
    def test_atomic_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            store = RunStateStore(path)
            self.assertEqual(store.load(), {})
            store.save({"call_count": 3, "started_at": "x"})
            self.assertEqual(store.load()["call_count"], 3)

    def test_pending_attempt_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            store = RunStateStore(path)
            state = models.RunState(pending_attempt={"case_id": "E0-PING-01"}).to_dict()
            store.save(state)
            self.assertEqual(store.load()["pending_attempt"]["case_id"], "E0-PING-01")

    def test_missing_empty_and_whitespace_state_load_as_empty(self):
        # El preflight crea el journal vacío antes de la primera corrida; un
        # archivo vacío no es estado ilegible.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            store = RunStateStore(path)
            self.assertEqual(store.load(), {})
            with open(path, "w", encoding="utf-8"):
                pass
            self.assertEqual(store.load(), {})
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("   \n\t")
            self.assertEqual(store.load(), {})

    def test_corrupt_state_still_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            store = RunStateStore(path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ no es json")
            with self.assertRaises(PersistenceError):
                store.load()


if __name__ == "__main__":
    unittest.main()
