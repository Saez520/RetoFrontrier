"""Inventario cerrado E0–E8: conteos, tablas, seed y slots de control."""

import json
import unittest

from probe_harness.inventory import E0_CONTROL_BASES, E8_LENGTHS, Inventory


def message_of(spec):
    if spec.control_prefix is not None:
        return spec.control_prefix
    if spec.body_raw is None:
        return None
    try:
        return json.loads(spec.body_raw)["m"]
    except (ValueError, KeyError, TypeError):
        return spec.body_raw


class InventoryCountsTest(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory()

    def test_total_and_distribution(self):
        self.assertEqual(self.inv.exploration_count(), 680)
        self.assertEqual(
            self.inv.axis_counts(),
            {"E0": 300, "E1": 30, "E2": 35, "E3": 35, "E4": 50, "E5": 40, "E6": 40, "E8": 150},
        )

    def test_global_order(self):
        axes = [seq.axis for seq in self.inv.sequences()]
        self.assertEqual(axes[0], "E0")
        self.assertEqual(axes[-1], "E8")
        first_seen = []
        for axis in axes:
            if not first_seen or first_seen[-1] != axis:
                first_seen.append(axis)
        self.assertEqual(first_seen, ["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E8"])

    def test_e0_single_reset_and_blocks(self):
        seq = self.inv.e0_sequence()
        self.assertEqual(len(seq.prep), 1)
        self.assertEqual(seq.prep[0].case_id, "AUX-E0-RESET")
        self.assertEqual(seq.prep[0].path, "/__reset")
        steps = seq.steps
        self.assertEqual(len(steps), 300)
        self.assertEqual([s.case_id for s in steps[:2]], ["E0-PING-00", "E0-PING-01"])
        self.assertEqual(message_of(steps[0]), "PING;00")
        self.assertEqual(message_of(steps[99]), "PING;99")
        self.assertEqual(message_of(steps[100]), "ALTA;Lucia;00")
        self.assertEqual(message_of(steps[199]), "ALTA;Lucia;99")
        self.assertEqual(message_of(steps[200]), "CONSULTA;AC-0009;00")
        self.assertEqual(message_of(steps[299]), "CONSULTA;AC-0009;99")

    def test_e0_control_bases_exclude_ping(self):
        self.assertEqual(E0_CONTROL_BASES, ("ALTA;Lucia", "CONSULTA;AC-0009"))
        self.assertNotIn("PING", E0_CONTROL_BASES)

    def test_e1_table_boundaries(self):
        reqs = self.inv.e1_requests()
        self.assertEqual(len(reqs), 30)
        self.assertEqual(reqs[0].case_id, "E1-01")
        self.assertEqual((reqs[0].method, reqs[0].path), ("GET", "/health"))
        self.assertEqual(reqs[11].path, "/health")
        self.assertEqual(reqs[12].auth_mode, "missing")
        self.assertEqual(reqs[17].auth_mode, "invalid")
        self.assertEqual(reqs[16].content_type, "text/plain")
        self.assertEqual(reqs[28].path, "/")
        self.assertEqual(reqs[28].body_raw, "{}")

    def test_e2_and_e3_counts(self):
        self.assertEqual(len(self.inv.e2_requests()), 35)
        self.assertEqual(len(self.inv.e3_requests()), 35)
        self.assertIsNone(self.inv.e2_requests()[0].body_raw)
        self.assertEqual(message_of(self.inv.e3_requests()[7]), "PING\t64")

    def test_e6_terminations(self):
        reqs = self.inv.e6_requests()
        self.assertEqual(len(reqs), 40)
        self.assertEqual(message_of(reqs[0]), "BLAH;X")
        self.assertEqual(message_of(reqs[1]), "BLAH;00")
        self.assertEqual(message_of(reqs[2]), "BLAH;")
        self.assertEqual(message_of(reqs[3]), "BLAH;999")

    def test_e4_families_and_resets(self):
        seqs = self.inv.e4_sequences()
        self.assertEqual(len(seqs), 7)
        self.assertEqual(sum(len(s.steps) for s in seqs), 50)
        self.assertEqual(seqs[0].prep[0].case_id, "AUX-E4-PING-RESET")
        self.assertEqual(seqs[6].prep[0].case_id, "AUX-E4-SALDOS-RESET")
        self.assertTrue(all(s.steps[0].uses_control() for s in seqs))

    def test_e5_sequences_and_resets(self):
        seqs = self.inv.e5_sequences()
        self.assertEqual(len(seqs), 10)
        self.assertEqual(sum(len(s.steps) for s in seqs), 40)
        self.assertEqual(seqs[0].prep[0].case_id, "AUX-E5-01-RESET")
        self.assertEqual(len(seqs[8].prep), 5)  # reset + cuatro auxiliares
        self.assertEqual(len(seqs[9].prep), 4)


class E8Test(unittest.TestCase):
    def test_lengths_sum(self):
        self.assertEqual(sum(E8_LENGTHS), 150)
        self.assertEqual(len(E8_LENGTHS), 20)
        self.assertTrue(all(2 <= n <= 12 for n in E8_LENGTHS))

    def test_seed_reproducible(self):
        a = Inventory(seed=20261010)
        b = Inventory(seed=20261010)
        self.assertEqual(
            [message_of(s) for seq in a.e8_sequences() for s in seq.steps],
            [message_of(s) for seq in b.e8_sequences() for s in seq.steps],
        )
        self.assertEqual(
            [s.case_id for seq in a.e8_sequences() for s in seq.steps],
            [s.case_id for seq in b.e8_sequences() for s in seq.steps],
        )

    def test_e8_prep_has_reset_and_three_aux(self):
        seq = Inventory().e8_sequences()[0]
        self.assertEqual(
            [s.case_id for s in seq.prep],
            ["AUX-E8-01-RESET", "AUX-E8-01-ALTA-A", "AUX-E8-01-ALTA-B", "AUX-E8-01-DEPOSITO"],
        )

    def test_e8_does_not_replay_example_sequence(self):
        import pathlib

        examples_path = pathlib.Path(__file__).resolve().parents[1] / "docs/material/ejemplos.jsonl"
        example_messages = set()
        for line in examples_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                example_messages.add(json.loads(line)["request"]["m"])
        inv = Inventory()
        produced = [
            message_of(s) for seq in inv.e8_sequences() for s in seq.steps
        ]
        self.assertTrue(example_messages.isdisjoint(set(produced)))


class ControlSlotsTest(unittest.TestCase):
    def test_order_and_uniqueness(self):
        inv = Inventory()
        slots = inv.control_slots()
        ids = [case_id for case_id, _ in slots]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 316)
        self.assertEqual(ids[0], "E4-01")
        self.assertEqual(ids[-1], "E8-20-09")
        self.assertEqual(inv.control_slots(), slots)

    def test_slots_match_control_requests(self):
        inv = Inventory()
        slot_ids = {case_id for case_id, _ in inv.control_slots()}
        from_requests = {
            spec.case_id
            for seq in inv.sequences()
            for spec in seq.all_requests()
            if spec.uses_control()
        }
        self.assertEqual(slot_ids, from_requests)


if __name__ == "__main__":
    unittest.main()
