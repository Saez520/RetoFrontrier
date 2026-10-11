"""Comparación del baseline V1 frente al log append-only."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from probe_harness.v2_diff import EXIT_OK, run_compare


class CompareTest(unittest.TestCase):
    def test_combined_log_uses_only_v1_ids_as_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "experimentos.jsonl"
            rows = [
                {"id": 1, "case_id": "V1-RESET", "metodo": "POST", "ruta": "/__reset", "status": 200},
                {"id": 924, "case_id": "V1-LAST", "metodo": "POST", "ruta": "/msg", "status": 200},
                # Estos son registros append-only V2; nunca baseline.
                {"id": 925, "case_id": "V2-REPLAY-0001", "status": 200},
                {"id": 926, "case_id": "V2-CONF-0001", "status": 201},
            ]
            log_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_compare(SimpleNamespace(baseline=str(log_path), log_path=str(log_path)))

        self.assertEqual(result, EXIT_OK)
        report = json.loads(output.getvalue())
        self.assertEqual(report["baseline_total"], 2)
        self.assertEqual(report["compared"], 1)
        self.assertEqual(report["missing_replay"], [924])


if __name__ == "__main__":
    unittest.main()
