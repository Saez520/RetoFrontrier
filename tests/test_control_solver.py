"""Solver de control autónomo: éxito, sobreajuste, ambigüedad y E0."""

import unittest

from probe_harness.control_solver import (
    CANONICALIZERS,
    FIT_LINES,
    HOLDOUT_LINES,
    apply_control_vector,
    extract_e0_values,
    solve,
)
from probe_harness.models import RequestSpec

FIT_BASES = [f"FIT{i:02d}" for i in range(1, 14)]
HOLDOUT_BASES = ["PING", "ALFA", "BETA"]


def metric_sum(data: bytes) -> int:
    return sum(data) % 100


def build_examples(fit_controls, holdout_controls):
    slots = [None] * 21
    for line, base, control in zip(FIT_LINES, FIT_BASES, fit_controls):
        slots[line] = {"n": line, "request": {"m": f"{base};{control}"}, "status": 200, "response": {}}
    for line, base, control in zip(HOLDOUT_LINES, HOLDOUT_BASES, holdout_controls):
        slots[line] = {"n": line, "request": {"m": f"{base};{control}"}, "status": 200, "response": {}}
    for line in range(1, 21):
        if slots[line] is None:
            slots[line] = {"n": line, "request": {"m": f"SKIP{line};0"}, "status": 400, "response": {"error": "E301"}}
    return slots[1:]


def build_e0(holdout_values):
    records = []
    for base, accepted in zip(HOLDOUT_BASES, holdout_values):
        for n in range(100):
            ok = n == accepted
            records.append(
                {
                    "case_id": f"E0-X-{n:02d}",
                    "request": {"m": f"{base};{n:02d}"},
                    "status": 200 if ok else 400,
                    "response": {} if ok else {"error": "E202"},
                    "infra": False,
                }
            )
    return records


class SolverAcceptTest(unittest.TestCase):
    def setUp(self):
        self.fit_controls = [metric_sum(base.encode()) for base in FIT_BASES]
        self.holdout_values = [metric_sum(base.encode()) for base in HOLDOUT_BASES]
        self.examples = build_examples(self.fit_controls, self.holdout_values)
        self.records = build_e0(self.holdout_values)
        self.slots = [
            ("E4-01", "PING"),
            ("E5-01-01", "ALTA;E5-01-A"),
            ("E8-01-01", "CONSULTA;E8-A-01"),
        ]
        self.canon = dict(CANONICALIZERS)["raw"]

    def _solve(self, **kwargs):
        return solve(
            self.records,
            self.examples,
            self.slots,
            metrics=[("sum", metric_sum)],
            canonicalizers=[("raw", self.canon)],
            **kwargs,
        )

    def test_accepted_with_unique_vector(self):
        result = self._solve()
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.fit_count, 13)
        self.assertEqual(result.holdout_count, 3)
        self.assertEqual(result.provenance.a, 1)
        self.assertEqual(result.provenance.b, 0)
        self.assertEqual(result.controls["E4-01"], metric_sum(b"PING"))
        self.assertTrue(result.vector_fingerprint)

    def test_serialization_has_no_leading_zero(self):
        spec = RequestSpec(
            case_id="E4-01",
            method="POST",
            path="/msg",
            hypothesis="h",
            axis="E4",
            control_prefix="PING",
        )
        body = apply_control_vector(spec, {"E4-01": 7})
        self.assertEqual(body, '{"m":"PING;7"}')


class SolverOverfitTest(unittest.TestCase):
    def test_holdout_mismatch_is_no_candidate(self):
        fit_controls = [metric_sum(base.encode()) for base in FIT_BASES]
        wrong_holdout = [(metric_sum(base.encode()) + 5) % 100 for base in HOLDOUT_BASES]
        examples = build_examples(fit_controls, wrong_holdout)
        records = build_e0(wrong_holdout)
        result = solve(
            records,
            examples,
            [("E4-01", "PING")],
            metrics=[("sum", metric_sum)],
            canonicalizers=[("raw", dict(CANONICALIZERS)["raw"])],
        )
        self.assertEqual(result.status, "no_candidate")
        self.assertIsNone(result.controls)


class SolverAmbiguityTest(unittest.TestCase):
    def test_two_vectors_is_ambiguous_candidate(self):
        fit_controls = [metric_sum(base.encode()) for base in FIT_BASES]
        holdout_values = [metric_sum(base.encode()) for base in HOLDOUT_BASES]
        examples = build_examples(fit_controls, holdout_values)
        records = build_e0(holdout_values)
        # Ambas canonicalizaciones coinciden en bases mayúsculas, pero difieren
        # en un prefijo con minúsculas.
        slots = [("E4-01", "ping")]
        result = solve(
            records,
            examples,
            slots,
            metrics=[("sum", metric_sum)],
            canonicalizers=[
                ("raw", dict(CANONICALIZERS)["raw"]),
                ("ascii_upper", dict(CANONICALIZERS)["ascii_upper"]),
            ],
        )
        self.assertEqual(result.status, "ambiguous_candidate")
        self.assertIsNone(result.controls)

    def test_ambiguous_e0_multiple_accepts(self):
        records = build_e0([metric_sum(b.encode()) for b in HOLDOUT_BASES])
        # PING acepta además el 5: dos aceptados -> ambiguous_e0.
        records.append(
            {
                "case_id": "E0-PING-05",
                "request": {"m": "PING;05"},
                "status": 200,
                "response": {},
                "infra": False,
            }
        )
        examples = build_examples(
            [metric_sum(base.encode()) for base in FIT_BASES],
            [metric_sum(base.encode()) for base in HOLDOUT_BASES],
        )
        result = solve(
            records,
            examples,
            [("E4-01", "PING")],
            metrics=[("sum", metric_sum)],
            canonicalizers=[("raw", dict(CANONICALIZERS)["raw"])],
        )
        self.assertEqual(result.status, "ambiguous_e0")

    def test_ambiguous_e0_zero_accepts(self):
        # Ningún valor aceptado en el sweep de PING (todos E202).
        records = build_e0([metric_sum(b.encode()) for b in HOLDOUT_BASES])
        records = [
            {**r, "status": 400, "response": {"error": "E202"}}
            if r["request"]["m"].startswith("PING;")
            else r
            for r in records
        ]
        examples = build_examples(
            [metric_sum(base.encode()) for base in FIT_BASES],
            [metric_sum(base.encode()) for base in HOLDOUT_BASES],
        )
        result = solve(
            records,
            examples,
            [("E4-01", "PING")],
            metrics=[("sum", metric_sum)],
            canonicalizers=[("raw", dict(CANONICALIZERS)["raw"])],
        )
        self.assertEqual(result.status, "ambiguous_e0")


class E0ExtractionTest(unittest.TestCase):
    def test_e201_e202_and_infra_excluded(self):
        records = [
            {"request": {"m": "PING;02"}, "status": 200, "response": {}, "infra": False},
            {"request": {"m": "PING;03"}, "status": 400, "response": {"error": "E202"}, "infra": False},
            {"request": {"m": "PING;04"}, "status": 400, "response": {"error": "E201"}, "infra": False},
            {"request": {"m": "PING;05"}, "status": 429, "response": {}, "infra": True},
        ]
        grouped = extract_e0_values(records)
        self.assertEqual(grouped["PING"], {2})


if __name__ == "__main__":
    unittest.main()
