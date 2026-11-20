from pathlib import Path
import json
import tempfile
import unittest

from src.content_factory.creative_counted_execution_v1 import CountedExecution


class CountedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proof = self.root / "evidence.txt"
        self.proof.write_text("offline fixture only", encoding="utf-8")
        self.execution = CountedExecution(self.root / "session")
        self.execution.initialize(self.proof)

    def finish(self, number):
        key = f"round_{number}"
        self.execution.begin_round(key, f"substantive offline fixture {number}")
        self.execution.assert_dispatch_allowed(key)
        return self.execution.complete_round(key, action="fixture", conclusion="fixture result",
                                             evidence_paths=[self.proof])

    def test_reinitialize_preserves_counts(self):
        self.finish(1)
        self.assertEqual(len(self.execution.initialize(self.proof)["rounds"]), 1)

    def test_rebind_rejected(self):
        other = self.root / "other.txt"
        other.write_text("different", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.execution.initialize(other)

    def test_unit_confirmation_is_bound_without_reset(self):
        self.finish(1)
        state = self.execution.read()
        confirmation = self.root / "confirmation.json"
        confirmation.write_text(json.dumps({"unit": state["unit"],
            "authorization_sha256": state["authorization"]["sha256"]}), encoding="utf-8")
        saved = self.execution.confirm_unit(confirmation)
        self.assertTrue(saved["unit_confirmed"])
        self.assertEqual(len(saved["rounds"]), 1)
        confirmation.write_text(json.dumps({"unit": "provider_call",
            "authorization_sha256": state["authorization"]["sha256"]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.execution.confirm_unit(confirmation)

    def test_no_dispatch_without_active_round(self):
        with self.assertRaises(ValueError):
            self.execution.assert_dispatch_allowed("round_1")

    def test_completion_is_idempotent(self):
        self.finish(1)
        state = self.execution.complete_round("round_1", action="fixture", conclusion="fixture result",
                                               evidence_paths=[self.proof])
        self.assertEqual(len(state["rounds"]), 1)

    def test_evidence_cannot_be_replaced(self):
        self.finish(1)
        self.proof.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.execution.complete_round("round_1", action="fixture", conclusion="fixture result",
                                          evidence_paths=[self.proof])

    def test_review_gate_blocks_next_round_and_dispatch(self):
        for number in range(1, 11):
            self.finish(number)
        with self.assertRaises(ValueError):
            self.execution.begin_round("round_11", "new work")
        with self.assertRaises(ValueError):
            self.execution.assert_dispatch_allowed("round_10")
        self.execution.record_review(1, self.proof)
        self.execution.begin_round("round_11", "new work")

    def test_tenth_review_seals_session(self):
        for number in range(1, 101):
            self.finish(number)
            if number % 10 == 0:
                self.execution.record_review(number // 10, self.proof)
        resumed = CountedExecution(self.execution.root)
        self.assertEqual(resumed.read()["stop_reason"], "ten_reviews_completed")
        self.assertEqual(len(resumed.initialize(self.proof)["rounds"]), 100)
        with self.assertRaises(ValueError):
            resumed.begin_round("round_101", "forbidden")

    def test_explicit_stop_blocks_new_dispatch(self):
        self.execution.begin_round("round_1", "actual work")
        self.execution.stop("unknown_result_requires_reconciliation", self.proof)
        with self.assertRaises(ValueError):
            self.execution.assert_dispatch_allowed("round_1")

    def test_limit_changes_are_rejected(self):
        self.execution.begin_round("round_1", "actual work")
        state = self.execution.read()
        state["maximum_rounds"] = 1000
        self.execution._save(state)
        with self.assertRaises(ValueError):
            self.execution.assert_dispatch_allowed("round_1")


if __name__ == "__main__":
    unittest.main()
