"""Configuración fija, lectura segura de ``.env`` y contratos inmutables."""

import json
import os
import tempfile
import unittest
from datetime import timezone

from probe_harness import models, settings
from probe_harness.settings import ConfigError, load_token, read_dotenv


class SettingsTest(unittest.TestCase):
    def test_policy_constants_are_fixed(self):
        self.assertEqual(settings.MAX_CALLS, 1000)
        self.assertEqual(settings.CALLS_PER_SECOND, 8)
        self.assertAlmostEqual(settings.MIN_INTERVAL_SECONDS, 0.125)
        self.assertEqual(settings.CUTOFF_AT.year, 2026)
        self.assertEqual(settings.CUTOFF_AT.tzinfo, timezone.utc)
        self.assertEqual(settings.CUTOFF_AT.hour, 1)

    def test_load_token_from_env(self):
        self.assertEqual(load_token(env={"ORACLE_TOKEN": "token-de-prueba"}), "token-de-prueba")

    def test_missing_token_raises_without_value(self):
        with self.assertRaises(ConfigError) as ctx:
            load_token(env={})
        self.assertIn("ORACLE_TOKEN requerido", str(ctx.exception))

    def test_empty_token_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_token(env={"ORACLE_TOKEN": "   "})

    def test_read_dotenv_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('# comentario\nORACLE_TOKEN="token-x"\nOTRA=1\n')
            values = read_dotenv(path)
            self.assertEqual(values["ORACLE_TOKEN"], "token-x")
            self.assertEqual(values["OTRA"], "1")

    def test_token_never_leaks_in_config_error(self):
        with self.assertRaises(ConfigError) as ctx:
            load_token(env={})
        self.assertNotIn("Bearer", str(ctx.exception))
        self.assertEqual(settings.redact("secreto"), "[REDACTED]")
        self.assertEqual(settings.redact(None), "")


class ModelsTest(unittest.TestCase):
    def test_request_spec_resolves_control_body(self):
        spec = models.RequestSpec(
            case_id="E4-01",
            method="POST",
            path="/msg",
            hypothesis="h",
            axis="E4",
            control_prefix="PING",
            content_type="application/json",
        )
        self.assertTrue(spec.uses_control())
        self.assertEqual(spec.resolved_body(7), '{"m":"PING;7"}')

    def test_request_spec_requires_control_when_slot(self):
        spec = models.RequestSpec(
            case_id="E4-01",
            method="POST",
            path="/msg",
            hypothesis="h",
            axis="E4",
            control_prefix="PING",
        )
        with self.assertRaises(ValueError):
            spec.resolved_body()

    def test_request_spec_raw_body_passthrough(self):
        spec = models.RequestSpec(
            case_id="E2-03",
            method="POST",
            path="/msg",
            hypothesis="h",
            axis="E2",
            body_raw="PING;64",
            content_type="text/plain",
        )
        self.assertEqual(spec.resolved_body(), "PING;64")

    def test_parse_semantic_json_and_text(self):
        self.assertEqual(models.parse_semantic("application/json", '{"a":1}'), {"a": 1})
        self.assertEqual(models.parse_semantic("text/plain", "PING;64"), "PING;64")
        self.assertIsNone(models.parse_semantic(None, None))
        self.assertEqual(models.parse_semantic(None, ""), "")

    def test_solver_result_roundtrip(self):
        result = models.SolverResult(
            status="accepted",
            provenance=models.ControlProvenance("raw", "sum", 1, 2),
            fit_count=13,
            holdout_count=3,
            e0_values={"PING": 64},
            vector_fingerprint="abc",
            controls={"E4-01": 7},
        )
        clone = models.SolverResult.from_dict(result.to_dict())
        self.assertEqual(clone, result)
        self.assertTrue(clone.is_accepted())

    def test_stop_reason_is_closed_set(self):
        self.assertEqual(
            {r.value for r in models.StopReason},
            {"none", "completed", "budget", "cutoff", "persistence_failure"},
        )


if __name__ == "__main__":
    unittest.main()
