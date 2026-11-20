"""Only this settled two-call run; no old ancestry/SDK revalidation."""
from copy import deepcopy
import pytest
from scripts import creative_world_scene_invalid_comparison_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_07"


@pytest.fixture
def records():
    config, ledger = bridge.read(ROOT / "SESSION_CONFIG.json"), bridge.read(ROOT / "CALL_LEDGER.json")
    return (bridge.read(config["parent_anchor_path"]), ledger,
        [bridge.read(ROOT / row["receipt"]) for row in ledger["calls"]],
        bridge.read(ROOT / "STATE.json"), bridge.read(ROOT / "USER_SCOPE.json"))


def test_known_valid_facts_and_invalid_json_preserve_cost_and_original_balance(records):
    before = bridge.digest(records)
    assert bridge.validate_records(*records, expected_end=684) == {"calls_started": 684, "reported_tokens": 14882230,
        "calls_with_known_usage": 682, "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert records[2][0]["validation"]["ledger_usable"] is True
    assert records[2][1].get("output") is None and records[2][1].get("validation") is None
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown", "capacity", "prefix_adoption"])
def test_unknown_regrant_and_repaired_prefix_cannot_settle(records, fault):
    values = deepcopy(records)
    if fault == "unknown": values[2][1]["response_metadata"]["total_tokens"] = None
    elif fault == "capacity": values[4]["stage_limits"]["complete_script"] = 3
    else: values[2][1]["output"] = {"illicit_repaired": True}
    with pytest.raises(ValueError): bridge.validate_records(*values, expected_end=684)


def test_pinned682_and_entire_frozen_source_set_required(records):
    freeze = bridge.read(ROOT / "PRODUCTION_FREEZE.json"); parent = records[0]
    bridge.validate_parent_certificate(parent, freeze, expected_parent_sha256=bridge.PARENT_SHA256)
    changed = deepcopy(freeze); changed["files"][next(iter(parent["source_files"]))] = "0" * 64
    with pytest.raises(ValueError, match="identically frozen"):
        bridge.validate_parent_certificate(parent, changed, expected_parent_sha256=bridge.PARENT_SHA256)


def test_original_two_intents_replay_to_protocol_stop_without_sdk():
    original = bridge.session.Session.open(ROOT); ledger = bridge.read(ROOT / "CALL_LEDGER.json")
    with pytest.raises(bridge.session.base.Halt) as stopped: original._replay(ledger, verify_validations=True)
    assert stopped.value.status == "halt_protocol_requires_diagnosis" and stopped.value.details == {"receipt_ordinal": 684}
