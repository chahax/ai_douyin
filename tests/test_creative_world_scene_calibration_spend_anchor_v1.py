"""Pure original known-calibration controls; no SDK/ancestry/restart."""
from copy import deepcopy
import pytest
from scripts import creative_world_scene_calibration_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_04"


@pytest.fixture
def records():
    config = bridge.read(ROOT / "SESSION_CONFIG.json"); ledger = bridge.read(ROOT / "CALL_LEDGER.json")
    return (bridge.read(config["parent_anchor_path"]), ledger, [bridge.read(ROOT / row["receipt"]) for row in ledger["calls"]],
        bridge.read(ROOT / "STATE.json"), bridge.read(ROOT / "USER_SCOPE.json"))


def test_known_model_pass_and_local_calibration_miss_stay_distinct(records):
    before = bridge.digest(records); result = bridge.validate_records(*records, expected_end=680)
    assert result == {"calls_started": 680, "reported_tokens": 14804812, "calls_with_known_usage": 678,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert records[2][0]["validation"]["valid"] and records[2][0]["validation"]["accepted"]
    assert records[3]["status"] == "halt_calibration_missed" and not records[3]["text_ready_for_director"]
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "rewrite_opinion", "regrant_body"])
def test_unknown_opinion_rewrite_and_capacity_reset_refused(records, fault):
    parent, ledger, receipts, state, scope = deepcopy(records)
    if fault == "unknown_usage": receipts[0]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[0]["response_metadata"]["finish_reason"] = "length"
        receipts[0]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "rewrite_opinion": receipts[0]["validation"]["accepted"] = False
    else: scope["stage_limits"]["complete_script"] = 3
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, expected_end=680)


def test_fixed_v9_route_calls_native_verifier_and_never_uses_ready_flag(tmp_path, monkeypatch):
    from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
    from tests.test_creative_world_scene_production_probe_v1 import parent_fixture
    proof = parent_fixture(tmp_path); root = bridge.session.base._inside(proof["root"])
    bridge.session.write(root / "STATE.json", {"schema": registry.V9_STATE, "status": "text_ready_for_director"})
    calls = []
    monkeypatch.setattr(registry, "_verify_v9", lambda path: (calls.append(str(path)) or deepcopy(proof)))
    def wrong(*args): raise AssertionError("wrong version; ready flag is not native proof")
    for version in (5, 6, 7, 8): monkeypatch.setattr(registry, f"_verify_v{version}", wrong)
    monkeypatch.setattr(registry.legacy, "verify_text_handoff", wrong)
    checked = registry.verify_text_handoff(root)
    assert calls == [str(root)] and checked["verifier_entry"]["native_state_schema"] == registry.V9_STATE
    proof["accepted"] = False
    with pytest.raises(ValueError, match="complete native proof"): registry.verify_text_handoff(root)
