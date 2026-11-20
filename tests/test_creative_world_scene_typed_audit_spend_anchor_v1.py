"""Narrow pure outcome/accounting controls; no SDK, claims or ancestor replay."""
from copy import deepcopy

import pytest

from scripts import creative_world_scene_typed_audit_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_source_state_audit_20261016/round_02"


@pytest.fixture
def records():
    read = bridge.session.read
    config = read(ROOT / "SESSION_CONFIG.json"); ledger = read(ROOT / "CALL_LEDGER.json")
    return (read(config["parent_anchor_path"]), ledger, [read(ROOT / row["receipt"]) for row in ledger["calls"]],
        read(ROOT / "STATE.json"), read(ROOT / "USER_SCOPE.json"), read(ROOT / "SUMMARY.json"),
        read(ROOT / "SOURCE_STATE_AUDIT_DECISION.json"))


def test_known_actual_contract_refusal_is_cost_only_and_original_data_unchanged(records):
    before = bridge.digest(records)
    actual = bridge.validate_records(*records, expected_end=664)
    assert actual == {"inherited": {"calls_started": 664, "reported_tokens": 14206125,
        "calls_with_known_usage": 662, "pending_ordinals": [70, 160], "unknown_token_reservations": 93117},
        "diagnostic_outcome": "contract_rejected"}
    assert bridge.digest(records) == before


@pytest.mark.parametrize("status,valid,accepted,findings,uncertainties,outcome,terminal", [
    ("contract_rejected", False, False, ["OFFLINE contract fault"], [], "contract_rejected", "halt_source_state_audit_contract"),
    ("fail", True, False, ["OFFLINE content fault"], [], "content_failure", "diagnostic_completed_known_content_failure"),
    ("unknown", True, False, [], ["OFFLINE unresolved extraction"], "uncertain", "halt_source_state_audit_uncertain"),
    ("pass", True, True, [], [], "accepted_diagnostic_only", "diagnostic_completed_not_creative"),
])
def test_four_synthetic_diagnostic_outcomes_are_distinct_not_text_admission(status, valid, accepted, findings, uncertainties, outcome, terminal):
    # Synthetic decision routing only; no actual rejected native is converted.
    decision = {"valid": valid, "accepted": accepted, "status": "source_state_" + status,
        "findings": findings, "contract_findings": findings if not valid else [], "uncertainties": uncertainties, "typed_replay": []}
    assert bridge.diagnostic_outcome(decision) == (outcome, terminal)
    if uncertainties:
        decision["accepted"] = True
        with pytest.raises(ValueError): bridge.diagnostic_outcome(decision)


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated"])
def test_unsettled_transport_or_usage_cannot_be_settled(records, fault):
    parent, ledger, receipts, state, scope, summary, decision = deepcopy(records)
    if fault == "unknown_usage":
        receipts[0]["response_metadata"]["total_tokens"] = None
    else:
        receipts[0]["response_metadata"]["finish_reason"] = "length"
        receipts[0]["response_payload"]["choices"][0]["finish_reason"] = "length"
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, summary, decision, expected_end=664)
