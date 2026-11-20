"""Pure known-v6 receipt accounting controls; no SDK or ancestor replay."""
from copy import deepcopy
import pytest
from scripts import creative_world_scene_continued_text_spend_anchor_v1 as bridge

ROOT = bridge.session.base.PROJECT / "data/production_trials/world_scene_live_20261016/round_02"


@pytest.fixture
def records():
    config = bridge.read(ROOT / "SESSION_CONFIG.json"); ledger = bridge.read(ROOT / "CALL_LEDGER.json")
    return (bridge.read(config["parent_anchor_path"]), ledger, [bridge.read(ROOT / row["receipt"]) for row in ledger["calls"]],
        bridge.read(ROOT / "STATE.json"), bridge.read(ROOT / "USER_SCOPE.json"))


def test_known_source_and_three_rejections_keep_spend_and_data_distinct(records):
    before = bridge.digest(records); result = bridge.validate_records(*records, expected_end=675)
    assert result == {"calls_started": 675, "reported_tokens": 14587163, "calls_with_known_usage": 673,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert records[2][0]["validation"]["accepted"] is True and all(r["status"] == "contract_rejected" for r in records[2][1:])
    assert bridge.digest(records) == before


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "body_pass", "reuse_capacity"])
def test_unsettled_or_false_body_admission_or_reset_is_rejected(records, fault):
    parent, ledger, receipts, state, scope = deepcopy(records)
    if fault == "unknown_usage": receipts[-1]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[-1]["response_metadata"]["finish_reason"] = "length"
        receipts[-1]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "body_pass": receipts[-1]["status"] = "contract_valid"
    else: scope["stage_limits"]["complete_script"] = 6
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_records(parent, ledger, receipts, state, scope, expected_end=675)
