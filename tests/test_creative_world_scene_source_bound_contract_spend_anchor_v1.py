"""Minimal source identity, known accounting, capacity and unknown controls."""
from copy import deepcopy
import pytest
from scripts import creative_world_scene_source_bound_contract_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_06"


@pytest.fixture
def records():
    config, ledger = bridge.read(ROOT / "SESSION_CONFIG.json"), bridge.read(ROOT / "CALL_LEDGER.json")
    return (bridge.read(config["parent_anchor_path"]), ledger,
        [bridge.read(ROOT / row["receipt"]) for row in ledger["calls"]],
        bridge.read(ROOT / "STATE.json"), bridge.read(ROOT / "USER_SCOPE.json"))


def test_known_missing_schema_stays_invalid_but_cost_is_complete(records):
    before = bridge.digest(records)
    assert bridge.validate_records(*records, expected_end=682) == {"calls_started": 682, "reported_tokens": 14835413,
        "calls_with_known_usage": 680, "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert "schema" not in records[2][0]["output"] and records[2][0]["validation"]["ledger_usable"] is False
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown", "capacity"])
def test_unknown_and_regranted_body_refused(records, fault):
    values = deepcopy(records)
    if fault == "unknown": values[2][0]["response_metadata"]["total_tokens"] = None
    else: values[4]["stage_limits"]["complete_script"] = 3
    with pytest.raises((ValueError, bridge.session.base.Halt)): bridge.validate_records(*values, expected_end=682)


def test_pinned681_full_source_set_and_canonical_identity_required(records):
    parent = records[0]; freeze = bridge.read(ROOT / "PRODUCTION_FREEZE.json")
    bridge.validate_parent_certificate(parent, freeze, expected_parent_sha256=bridge.PARENT_SHA256)
    changed = deepcopy(freeze); changed["files"][next(iter(parent["source_files"]))] = "0" * 64
    with pytest.raises(ValueError, match="identically frozen"):
        bridge.validate_parent_certificate(parent, changed, expected_parent_sha256=bridge.PARENT_SHA256)
    changed_parent = deepcopy(parent); changed_parent["schema"] = "other/v1"
    with pytest.raises(ValueError, match="certificate/schema/verifier"):
        bridge.validate_parent_certificate(changed_parent, freeze, expected_parent_sha256=bridge.digest(changed_parent))


def test_fixed_v11_deep_native_route_and_no_ready_flag(tmp_path, monkeypatch):
    from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
    from tests.test_creative_world_scene_production_probe_v1 import parent_fixture
    proof = parent_fixture(tmp_path); root = bridge.session.base._inside(proof["root"])
    bridge.session.write(root / "STATE.json", {"schema": registry.V11_STATE, "status": "text_ready_for_director"})
    calls = []
    monkeypatch.setattr(registry, "_verify_v11", lambda path: (calls.append(str(path)) or deepcopy(proof)))
    def deny(*args): raise AssertionError("wrong native route")
    for version in range(5, 11): monkeypatch.setattr(registry, f"_verify_v{version}", deny)
    monkeypatch.setattr(registry.legacy, "verify_text_handoff", deny)
    assert registry.verify_text_handoff(root)["verifier_entry"]["native_state_schema"] == registry.V11_STATE
    assert calls == [str(root)]
    proof["accepted"] = False
    with pytest.raises(ValueError, match="complete native proof"): registry.verify_text_handoff(root)
