"""Narrow pure tests; no parent verifier, client or shared production mutation."""
from copy import deepcopy

import pytest

from scripts import creative_world_scene_known_text_spend_anchor_v1 as bridge

ROOT = bridge.v4.base.PROJECT / "data/production_trials/world_scene_live_20261015/round_04"


@pytest.fixture
def records():
    read = bridge.v4.read
    config = read(ROOT / "SESSION_CONFIG.json"); parent = read(config["parent_anchor_path"])
    ledger = read(ROOT / "CALL_LEDGER.json")
    return parent, ledger, [read(ROOT / row["receipt"]) for row in ledger["calls"]], read(ROOT / "STATE.json"), read(ROOT / "USER_SCOPE.json")


def test_two_known_rejected_bodies_preserve_four_diagnostics_and_all_native_results(records):
    before = bridge.digest(records)
    assert bridge.validate_records(*records, expected_end=662) == {
        "calls_started": 662, "reported_tokens": 14131876, "calls_with_known_usage": 660,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    goal = bridge.v4.read(records[0]["native_goal_receipt"]["path"])["output"]
    for receipt in records[2]:
        recomputed = bridge.v4.contract.diagnose(receipt["output"], goal)
        original = receipt["validation_error"]["detail"]
        assert bridge.parent_bridge._validation_identity(recomputed) == bridge.parent_bridge._validation_identity(original)
    assert bridge.digest(records) == before
    assert len(records[0]["rejected_body_receipts"]) == 6
    assert len(records[0]["registered_diagnostic_receipts"]) == 4


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "scope_regrant", "unsupported_protocol"])
def test_unknown_unregistered_or_regranted_scope_cannot_settle(records, fault):
    parent, ledger, receipts, state, scope = deepcopy(records)
    if fault == "unknown_usage":
        receipts[0]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[0]["response_metadata"]["finish_reason"] = "length"
        receipts[0]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "scope_regrant":
        parent["remaining_complete_scripts"] = 1
    else:
        state["schema"] = "unregistered/arbitrary_module/state"
    with pytest.raises((ValueError, bridge.v4.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, expected_end=662)
