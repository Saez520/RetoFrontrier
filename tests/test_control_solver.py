"""Solver de control: función exacta ISO 7064 MOD 97-10, E0 y contrato público."""

import unittest

from probe_harness.control_solver import (
    apply_control_vector,
    control_for,
    extract_e0_values,
    is_control_valid,
    solve,
)
from probe_harness.inventory import E0_CONTROL_BASES
from probe_harness.models import RequestSpec

# Pares reales del catálogo de ejemplos (base, control aceptado) más las dos
# bases de borde confirmadas contra el oráculo (r=0 → f=98; r=1 → f=97).
KNOWN_PAIRS = (
    ("ALTA;Lucia", 82),
    ("ALTA;Mateo", 3),
    ("CONSULTA;AC-0001", 14),
    ("CONSULTA;AC-0002", 11),
    ("CONSULTA;AC-0009", 87),
    ("DEPOSITO;AC-0001;250000", 86),
    ("DEPOSITO;AC-0002;700", 35),
    ("TRANSFER;AC-0001;AC-0002;40000", 86),
    ("TRANSFER;AC-0001;AC-0002;120000", 55),
    ("TRANSFER;AC-0001;AC-0002;100000", 12),
    ("TRANSFER;AC-0002;AC-0001;50000", 23),
    ("ANULA;OP-0003", 66),
    ("CONSULTA;AC-9964", 98),
    ("CONSULTA;AC-9932", 97),
)


def build_accepting_e0(values: dict) -> list:
    """Sweep E0 sintético: por base, solo el valor dado es aceptado."""

    records = []
    for base, accepted in values.items():
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


class ExactFunctionTest(unittest.TestCase):
    def test_known_pairs(self):
        for base, expected in KNOWN_PAIRS:
            self.assertEqual(control_for(base), expected, base)

    def test_acceptance_matches_canonical_control(self):
        for base, expected in KNOWN_PAIRS:
            self.assertTrue(is_control_valid(base, expected), base)

    def test_acceptance_rejects_wrong_numeric(self):
        self.assertFalse(is_control_valid("ALTA;Lucia", 83))
        self.assertFalse(is_control_valid("CONSULTA;AC-0009", 5))

    def test_letters_case_insensitive_and_other_chars_omitted(self):
        self.assertEqual(
            control_for("CONSULTA;AC-0001"), control_for("consuLta;ac-0001")
        )
        # El separador ``;`` se omite: la misma secuencia de letras da igual S.
        self.assertEqual(control_for("ALTA;Lucia"), control_for("ALTALucia"))


class BorderTest(unittest.TestCase):
    """Bordes confirmados en T0b: la aceptación es igualdad, no congruencia.

    ``f`` no se reduce mod 97: r=0 da f=98 y r=1 da f=97. El gemelo mod-97
    (1 y 0) es rechazado por el oráculo con E202.
    """

    R0_BASE = "CONSULTA;AC-9964"
    R1_BASE = "CONSULTA;AC-9932"

    def test_r0_control_is_98_and_one_is_rejected(self):
        self.assertEqual(control_for(self.R0_BASE), 98)
        self.assertTrue(is_control_valid(self.R0_BASE, 98))
        self.assertFalse(is_control_valid(self.R0_BASE, 1))

    def test_r1_control_is_97_and_zero_is_rejected(self):
        self.assertEqual(control_for(self.R1_BASE), 97)
        self.assertTrue(is_control_valid(self.R1_BASE, 97))
        self.assertFalse(is_control_valid(self.R1_BASE, 0))


class ImportOrderTest(unittest.TestCase):
    """La función exacta y las bases de E0 conviven sin ciclos de importación."""

    def test_both_modules_are_importable_and_consistent(self):
        import probe_harness.control_solver as control_solver
        import probe_harness.inventory as inventory

        self.assertEqual(control_solver.control_for("ALTA;Lucia"), 82)
        self.assertEqual(
            tuple(inventory.E0_CONTROL_BASES), ("ALTA;Lucia", "CONSULTA;AC-0009")
        )
        self.assertNotIn("PING", inventory.E0_CONTROL_BASES)


class SolveAcceptedTest(unittest.TestCase):
    def setUp(self):
        self.records = build_accepting_e0({"ALTA;Lucia": 82, "CONSULTA;AC-0009": 87})
        self.slots = [
            ("E4-01", "PING"),
            ("E5-01-01", "ALTA;E5-01-A"),
            ("E8-01-01", "CONSULTA;E8-A-01"),
        ]

    def test_accepted_and_controls_computed_with_f(self):
        result = solve(self.records, None, self.slots)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.e0_values, {"ALTA;Lucia": 82, "CONSULTA;AC-0009": 87})
        self.assertEqual(result.controls["E4-01"], control_for("PING"))
        self.assertEqual(result.controls["E5-01-01"], control_for("ALTA;E5-01-A"))
        self.assertEqual(result.controls["E8-01-01"], control_for("CONSULTA;E8-A-01"))
        self.assertTrue(result.vector_fingerprint)

    def test_ping_sweep_does_not_make_e0_ambiguous(self):
        # PING acepta los 100 controles; al no ser base de validación, no
        # contamina el veredicto.
        records = build_accepting_e0(
            {"ALTA;Lucia": 82, "CONSULTA;AC-0009": 87}
        )
        ping_accepts = [
            {
                "case_id": f"E0-PING-{n:02d}",
                "request": {"m": f"PING;{n:02d}"},
                "status": 200,
                "response": {},
                "infra": False,
            }
            for n in range(100)
        ]
        result = solve(records + ping_accepts, None, self.slots)
        self.assertEqual(result.status, "accepted")
        self.assertNotIn("PING", result.e0_values)

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


class SolveAmbiguityTest(unittest.TestCase):
    def test_base_with_two_accepts_is_ambiguous(self):
        records = build_accepting_e0({"ALTA;Lucia": 82, "CONSULTA;AC-0009": 87})
        records.append(
            {
                "case_id": "E0-ALTA-90",
                "request": {"m": "ALTA;Lucia;90"},
                "status": 200,
                "response": {},
                "infra": False,
            }
        )
        result = solve(records, None, [("E4-01", "PING")])
        self.assertEqual(result.status, "ambiguous_e0")
        self.assertIsNone(result.controls)

    def test_base_without_accepts_is_ambiguous(self):
        records = [
            {**r, "status": 400, "response": {"error": "E202"}}
            if r["request"]["m"].startswith("ALTA;Lucia;")
            else r
            for r in build_accepting_e0({"ALTA;Lucia": 82, "CONSULTA;AC-0009": 87})
        ]
        result = solve(records, None, [("E4-01", "PING")])
        self.assertEqual(result.status, "ambiguous_e0")

    def test_measured_value_mismatch_is_ambiguous(self):
        records = build_accepting_e0({"ALTA;Lucia": 83, "CONSULTA;AC-0009": 87})
        result = solve(records, None, [("E4-01", "PING")])
        self.assertEqual(result.status, "ambiguous_e0")
        self.assertEqual(result.e0_values, {"ALTA;Lucia": 83})


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
