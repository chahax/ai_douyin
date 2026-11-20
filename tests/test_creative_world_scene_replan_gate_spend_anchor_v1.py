"""Pure known-accounting controls; no SDK, ancestor verification or writes."""
from copy import deepcopy
import pytest
from scripts import creative_world_scene_replan_gate_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_01"


@pytest.fixture
def records():
    read = bridge.read; config = read(ROOT / "SESSION_CONFIG.json"); ledger = read(ROOT / "CALL_LEDGER.json")
    return (read(config["parent_anchor_path"]), ledger, [read(ROOT / row["receipt"]) for row in ledger["calls"]],
        read(ROOT / "STATE.json"), read(ROOT / "USER_SCOPE.json"))


def test_known_seven_calls_preserve_contract_refusal_and_original_unused_bodies(records):
    before = bridge.digest(records)
    inherited = bridge.validate_records(*records, expected_end=671)
    assert inherited == {"calls_started": 671, "reported_tokens": 14447219, "calls_with_known_usage": 669,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert records[3]["decision"]["valid"] is False and records[3]["decision"]["computed_state_findings"]
    assert records[3]["spend"]["stage_calls"]["complete_script"] == 0
    assert bridge.digest(records) == before


def test_ancestor_current_scope_never_overwrites_actual_seven_call_accounting(records):
    parent = records[0]
    current = {"limits": deepcopy(bridge.session.LIMITS), "consumed": deepcopy(bridge.COUNTS),
        "remaining": {k: bridge.session.LIMITS[k] - bridge.COUNTS[k] for k in bridge.COUNTS},
        "calls_used": 7, "calls_remaining": 26, "body_used": 0, "body_limit": 3,
        "body_versions_available": [9, 10, 11]}
    result = bridge._inherit_original_lineage({"current_text_scope_accounting": deepcopy(current), "remaining_complete_scripts": 3}, parent)
    assert result["current_text_scope_accounting"] == current
    assert result["prior_text_scope_accounting"] == parent["current_text_scope_accounting"]
    assert result["native_goal_receipt"] == parent["native_goal_receipt"]
    assert result["remaining_complete_scripts"] == 3


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "fake_accepted", "reset_history"])
def test_unknown_and_false_admission_or_reset_cannot_settle(records, fault):
    parent, ledger, receipts, state, scope = deepcopy(records)
    if fault == "unknown_usage": receipts[-1]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[-1]["response_metadata"]["finish_reason"] = "length"
        receipts[-1]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "fake_accepted": receipts[-1]["validation"]["accepted"] = True
    else: parent["rejected_body_receipts"] = []
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, expected_end=671)
