"""Narrow accounting tests using original read-only diagnostic records.

No parent verifier, model client, production claim, or deep ancestry is used.
"""
from copy import deepcopy

import pytest

from scripts import creative_world_scene_array_probe_spend_anchor_v1 as bridge


@pytest.fixture
def records():
    root = bridge.ROOT
    read = bridge.session.read
    config = read(root / "SESSION_CONFIG.json")
    parent = read(config["parent_anchor_path"])
    ledger = read(root / "CALL_LEDGER.json")
    receipts = [read(root / row["receipt"]) for row in ledger["calls"]]
    state, summary = read(root / "STATE.json"), read(root / "SUMMARY.json")
    cases = bridge.session.importlib.import_module("scripts.creative_world_scene_array_probe_cases_v1").build_cases(read(config["profile_path"]))
    return parent, ledger, receipts, state, summary, cases


def test_known_four_diagnostics_preserve_six_spent_creative_bodies(records):
    before = bridge.digest(records)
    assert bridge.validate_accounting(*records) == bridge.EXPECTED
    assert bridge.digest(records) == before
    assert [r["ordinal"] for r in records[0]["rejected_body_receipts"]] == list(range(651, 657))
    assert len(records[2]) == 4


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "duplicate_response", "body_regrant", "summary_tamper"])
def test_unsettled_tampered_or_regranted_records_cannot_settle(records, fault):
    parent, ledger, receipts, state, summary, cases = deepcopy(records)
    if fault == "unknown_usage":
        receipts[0]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated":
        receipts[0]["response_metadata"]["finish_reason"] = "length"
        receipts[0]["response_payload"]["choices"][0]["finish_reason"] = "length"
    elif fault == "duplicate_response":
        receipts[1]["response_metadata"]["response_id"] = receipts[0]["response_metadata"]["response_id"]
    elif fault == "body_regrant":
        parent["remaining_complete_scripts"] = 4
    else:
        summary["completed_known_cases"][0]["validation"]["valid"] = True
        state["summary_sha256"] = bridge.digest(summary)
    with pytest.raises((ValueError, bridge.session.base.Halt)):
        bridge.validate_accounting(parent, ledger, receipts, state, summary, cases)


def test_verify_rejects_resigned_anchor_tamper_before_reading_ancestors(monkeypatch):
    anchor = {"schema": bridge.VERSION, "inherited": bridge.EXPECTED}
    monkeypatch.setattr(bridge, "build_anchor", lambda: anchor)
    altered = deepcopy(anchor); altered["inherited"]["reported_tokens"] -= 1
    with pytest.raises(ValueError, match="original660 evidence changed"):
        bridge.verify_anchor(altered, expected_anchor_sha256=bridge.digest(altered))


def test_findings_comparison_preserves_exact_multiset_not_order_or_counts(records):
    original = records[2][0]["validation"]
    reordered = deepcopy(original); reordered["findings"].reverse()
    assert bridge._validation_identity(original) == bridge._validation_identity(reordered)
    changed = deepcopy(original); changed["findings"][0]["actual"] = "changed original value"
    assert bridge._validation_identity(original) != bridge._validation_identity(changed)
    repeated = deepcopy(original); repeated["findings"].append(deepcopy(repeated["findings"][0]))
    assert bridge._validation_identity(original) != bridge._validation_identity(repeated)
