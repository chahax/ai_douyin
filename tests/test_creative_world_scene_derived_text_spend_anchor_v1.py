"""Pure accounting controls over immutable original v7 receipts; no SDK/ancestry."""
from copy import deepcopy
import pytest
from scripts import creative_world_scene_derived_text_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_03"


@pytest.fixture
def records():
    config = bridge.read(ROOT / "SESSION_CONFIG.json"); ledger = bridge.read(ROOT / "CALL_LEDGER.json")
    return (bridge.read(config["parent_anchor_path"]), ledger, [bridge.read(ROOT / row["receipt"]) for row in ledger["calls"]],
        bridge.read(ROOT / "STATE.json"), bridge.read(ROOT / "USER_SCOPE.json"))


def test_known_structural_body_does_not_adopt_invalid_all_pass_review(records):
    before = bridge.digest(records); result = bridge.validate_records(*records, expected_end=679)
    assert result == {"calls_started": 679, "reported_tokens": 14759836, "calls_with_known_usage": 677,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert records[2][2]["validation"]["valid"] is True
    assert records[2][-1]["validation"]["valid"] is False
    assert records[2][-1]["output"]["revision_target"] == "none"
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "review_pass", "reuse_capacity"])
def test_unknown_false_admission_and_capacity_reset_refused(records, fault):
    parent, ledger, receipts, state, scope = deepcopy(records)
    if fault == "unknown_usage": receipts[-1]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[-1]["response_metadata"]["finish_reason"] = "length"
        receipts[-1]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "review_pass":
        receipts[-1]["validation"].update(valid=True, accepted=True)
    else: scope["stage_limits"]["complete_script"] = 6
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, expected_end=679)


def test_registry_v8_routes_only_original_deep_verifier_and_preserves_false_gate(tmp_path, monkeypatch):
    from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
    from tests.test_creative_world_scene_production_probe_v1 import parent_fixture
    proof = parent_fixture(tmp_path); root = bridge.session.base._inside(proof["root"])
    bridge.session.write(root / "STATE.json", {"schema": registry.V8_STATE, "status": "text_ready_for_director"})
    calls = []
    monkeypatch.setattr(registry, "_verify_v8", lambda path: (calls.append(str(path)) or deepcopy(proof)))
    def wrong(*args): raise AssertionError("other version/ready flag is not v8 proof")
    for version in (5, 6, 7): monkeypatch.setattr(registry, f"_verify_v{version}", wrong)
    monkeypatch.setattr(registry.legacy, "verify_text_handoff", wrong)
    checked = registry.verify_text_handoff(root)
    assert calls == [str(root)] and checked["verifier_entry"]["native_state_schema"] == registry.V8_STATE
    proof["accepted"] = False
    with pytest.raises(ValueError, match="complete native proof"): registry.verify_text_handoff(root)
