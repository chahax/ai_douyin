"""Narrow accounting controls; original fixture reads do not replay ancestors."""
from copy import deepcopy
import pytest

from scripts import creative_world_scene_isolated_contract_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_05"


@pytest.fixture
def records():
    config = bridge.read(ROOT / "SESSION_CONFIG.json")
    ledger = bridge.read(ROOT / "CALL_LEDGER.json")
    return (bridge.read(config["parent_anchor_path"]), ledger,
        [bridge.read(ROOT / row["receipt"]) for row in ledger["calls"]],
        bridge.read(ROOT / "STATE.json"), bridge.read(ROOT / "USER_SCOPE.json"))


def test_known_contract_rejection_consumes_review_without_adopting_ledger(records):
    before = bridge.digest(records)
    assert bridge.validate_records(*records, expected_end=681) == {
        "calls_started": 681, "reported_tokens": 14819450, "calls_with_known_usage": 679,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert records[2][0]["validation"]["ledger_usable"] is False
    assert records[3]["status"] == "halt_review_contract"
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "adopt_invalid", "regrant_body"])
def test_unknown_rewrite_and_regrant_refused(records, fault):
    parent, ledger, receipts, state, scope = deepcopy(records)
    if fault == "unknown_usage": receipts[0]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[0]["response_metadata"]["finish_reason"] = "length"
        receipts[0]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "adopt_invalid": receipts[0]["validation"]["ledger_usable"] = True
    else: scope["stage_limits"]["complete_script"] = 3
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, expected_end=681)


def test_registered_parent_schema_digest_and_entire_source_set_are_required(records):
    parent = records[0]
    freeze = bridge.read(ROOT / "PRODUCTION_FREEZE.json")
    bridge.validate_parent_certificate(parent, freeze, expected_parent_sha256=bridge.REGISTERED_PARENT_SHA256)
    changed = deepcopy(freeze)
    changed["files"][next(iter(parent["source_files"]))] = "0" * 64
    with pytest.raises(ValueError, match="identically frozen"):
        bridge.validate_parent_certificate(parent, changed, expected_parent_sha256=bridge.REGISTERED_PARENT_SHA256)
    changed_parent = deepcopy(parent); changed_parent["schema"] = "other/v1"
    with pytest.raises(ValueError, match="certificate/schema/verifier"):
        bridge.validate_parent_certificate(changed_parent, freeze, expected_parent_sha256=bridge.digest(changed_parent))


def test_fixed_v10_calls_deep_native_verifier_not_ready_flag(tmp_path, monkeypatch):
    from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
    from tests.test_creative_world_scene_production_probe_v1 import parent_fixture
    proof = parent_fixture(tmp_path)
    root = bridge.session.base._inside(proof["root"])
    bridge.session.write(root / "STATE.json", {"schema": registry.V10_STATE, "status": "text_ready_for_director"})
    calls = []
    monkeypatch.setattr(registry, "_verify_v10", lambda path: (calls.append(str(path)) or deepcopy(proof)))
    def wrong(*args): raise AssertionError("wrong native verifier")
    for version in (5, 6, 7, 8, 9): monkeypatch.setattr(registry, f"_verify_v{version}", wrong)
    monkeypatch.setattr(registry.legacy, "verify_text_handoff", wrong)
    assert registry.verify_text_handoff(root)["verifier_entry"]["native_state_schema"] == registry.V10_STATE
    assert calls == [str(root)]
    proof["accepted"] = False
    with pytest.raises(ValueError, match="complete native proof"): registry.verify_text_handoff(root)
