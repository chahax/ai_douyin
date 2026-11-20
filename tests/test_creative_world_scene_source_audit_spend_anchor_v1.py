"""Pure actual-record accounting controls; no ancestor replay or SDK calls."""
from copy import deepcopy

import pytest

from scripts import creative_world_scene_source_audit_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_source_state_audit_20261016/round_01"


@pytest.fixture
def records():
    read = bridge.session.read
    config = read(ROOT / "SESSION_CONFIG.json"); ledger = read(ROOT / "CALL_LEDGER.json")
    return (read(config["parent_anchor_path"]), ledger, [read(ROOT / row["receipt"]) for row in ledger["calls"]],
        read(ROOT / "STATE.json"), read(ROOT / "USER_SCOPE.json"), read(ROOT / "SUMMARY.json"),
        read(ROOT / "SOURCE_STATE_AUDIT_DECISION.json"))


def test_known_native_pass_but_contract_rejected_settles_without_semantic_admission(records):
    before = bridge.digest(records)
    assert records[2][0]["output"]["overall_status"] == "pass"
    assert bridge.validate_records(*records, expected_end=663) == {
        "calls_started": 663, "reported_tokens": 14163272, "calls_with_known_usage": 661,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    original = bridge.session.Session.open(ROOT)
    prepared = original._request(bridge.session.read(ROOT / "INPUTS.json"))
    assert prepared["request"] == records[2][0]["request"]
    recomputed = original.audit.validate(records[2][0]["output"], prepared)
    assert bridge._decision_identity(recomputed) == bridge._decision_identity(records[-1])
    assert recomputed["valid"] is recomputed["accepted"] is False
    assert len(recomputed["findings"]) == 80
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "native_pass_promoted", "old_body_reset"])
def test_unknown_or_forged_admission_cannot_settle(records, fault):
    parent, ledger, receipts, state, scope, summary, decision = deepcopy(records)
    if fault == "unknown_usage":
        receipts[0]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[0]["response_metadata"]["finish_reason"] = "length"
        receipts[0]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "native_pass_promoted":
        decision["valid"] = decision["accepted"] = True
        receipts[0]["validation"] = deepcopy(decision)
        summary["derived_decision_sha256"] = bridge.digest(decision)
        state["summary_sha256"] = bridge.digest(summary)
    else:
        parent["cumulative_body_attempts_used"] = 0
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, summary, decision, expected_end=663)
