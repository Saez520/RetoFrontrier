"""CLI: validación temprana, ausencia de flags de controles y códigos de parada."""

import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from probe_harness import cli
from probe_harness.recorder import RunStateStore
from probe_harness.settings import ConfigError

CUTOFF = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)
BEFORE = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now):
        self._now = now

    def monotonic(self):
        return 0.0

    def now_utc(self):
        return self._now


class HelpTest(unittest.TestCase):
    def test_no_human_control_flags(self):
        text = cli.build_parser().format_help()
        self.assertNotIn("controls-path", text)
        self.assertNotIn("write-controls-template", text)
        for flag in ("--log-path", "--state-path", "--seed", "--base-url"):
            self.assertIn(flag, text)


class ConfigTest(unittest.TestCase):
    def test_missing_token_exits_without_leak(self):
        with mock.patch.object(cli, "load_token", side_effect=ConfigError("ORACLE_TOKEN requerido")):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = cli.main([])
        self.assertEqual(code, cli.EXIT_CONFIG)
        self.assertIn("ORACLE_TOKEN requerido", buffer.getvalue())

    def test_preflight_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, "blocker")
            with open(blocker, "w", encoding="utf-8") as fh:
                fh.write("x")
            log_path = os.path.join(blocker, "nested", "log.jsonl")
            with mock.patch.object(cli, "load_token", return_value="tok"), mock.patch.object(
                cli, "SystemClock", lambda: FakeClock(BEFORE)
            ):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    code = cli.main(["--log-path", log_path, "--state-path", os.path.join(tmp, "s.json")])
        self.assertEqual(code, cli.EXIT_PERSISTENCE)
        self.assertIn("persistence_preflight_failure", buffer.getvalue())

    def test_preflight_created_empty_state_is_loadable(self):
        # El preflight crea el archivo de estado vacío antes de la primera
        # corrida; el journal debe interpretarlo como estado inexistente.
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "log.jsonl"
            state_path = Path(tmp) / "state.json"
            cli._preflight(log_path, state_path)
            self.assertTrue(state_path.exists())
            self.assertEqual(RunStateStore(state_path).load(), {})

    def test_cutoff_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "load_token", return_value="tok"), mock.patch.object(
                cli, "SystemClock", lambda: FakeClock(CUTOFF)
            ):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    code = cli.main(
                        [
                            "--log-path",
                            os.path.join(tmp, "log.jsonl"),
                            "--state-path",
                            os.path.join(tmp, "s.json"),
                        ]
                    )
        self.assertEqual(code, cli.EXIT_CUTOFF)


class WiringTest(unittest.TestCase):
    def test_fake_run_wires_runner_without_leaking_token(self):
        captured = {}

        class StubRunner:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self):
                return {"stop_reason": "completed"}

        secret = "supersecret-token"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "load_token", return_value=secret), mock.patch.object(
                cli, "SystemClock", lambda: FakeClock(BEFORE)
            ), mock.patch.object(cli, "ProbeRunner", StubRunner):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(
                        [
                            "--log-path",
                            os.path.join(tmp, "log.jsonl"),
                            "--state-path",
                            os.path.join(tmp, "s.json"),
                        ]
                    )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("state_store", captured)
        self.assertIn("inventory", captured)
        self.assertNotIn(secret, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
