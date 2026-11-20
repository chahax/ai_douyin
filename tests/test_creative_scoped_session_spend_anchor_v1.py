"""Read-only Session3 accounting; ancestors are explicit offline stubs only."""
from copy import deepcopy
from dataclasses import replace
import gc
from pathlib import Path
import sqlite3

import pytest

from scripts import creative_scoped_session_spend_anchor_v1 as bridge
from src.content_factory.creative_counted_execution_v1 import CountedExecution
from tests.test_creative_scoped_source_session_v3 import setup_session, prepare, offline, causal_scenario, prior_scenario

REAL = Path(__file__).resolve().parents[1]
READY = REAL / "data/qa/scoped_session_v3_tmp_20261015_v3/test_nine_real_sdk_calls_four_0/run"
PROTOCOL = REAL / "data/qa/scoped_session_v3_tmp_20261015_v4/test_known_protocol_unknown_an1/run"


def records_at(root):
    ledger = bridge.read(root / "CALL_LEDGER.json")
    return [ledger, [bridge.read(root / row["receipt"]) for row in ledger["calls"]],
        *[bridge.read(root / (name + ".json")) for name in ("STATE", "PRODUCTION_FREEZE", "USER_SCOPE", "AUTHORIZATION")],
        deepcopy(ledger["starting_spend"])]


def fixture(tmp_path, monkeypatch, scenario, *, mode="type"):
    session, inputs, goal, audits, seen, counter = setup_session(tmp_path, monkeypatch, scenario, fault={"plan": mode})
    parent = bridge.read(session.config.anchor_path); parent["inherited_whole_goal_candidates_used"] = 35
    bridge.native.io.write(session.config.anchor_path, parent)
    session.config = replace(session.config, anchor_sha256=bridge.digest(parent))
    prepare(session); result = session.run(); gc.collect()
    monkeypatch.setattr(bridge, "PROJECT", tmp_path)
    def verify(value, *, expected_anchor_sha256, ancestors=()):
        assert bridge.digest(value) == expected_anchor_sha256 == bridge.digest(parent)
        return {"verified": True, "inherited": deepcopy(parent["inherited"])}
    monkeypatch.setattr(bridge, "verify_parent", verify)
    def deny(*a, **kw): raise AssertionError("settled bridge must not call live counted admission")
    monkeypatch.setattr(CountedExecution, "assert_dispatch_allowed", deny)
    return session.root, parent, result, seen


def test_complete_nine_call_machine_text_keeps_all_four_audits_body_and_fullreview_costs():
    rows = records_at(READY); result = bridge.validate_records(*rows)
    assert result["inherited"] == {"calls_started": 635, "reported_tokens": 13080843, "calls_with_known_usage": 633,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert result["stage_calls"] == {"goal_plan": 2, "goal_audit": 4, "complete_script": 1, "full_review": 2}


def test_known_missing_tool_cost_is_settled_but_remains_protocol_failure_not_native_adoption():
    rows = records_at(PROTOCOL); result = bridge.validate_records(*rows)
    assert rows[1][0]["status"] == "interface_rejected"
    assert result["inherited"]["calls_started"] == 627 and result["inherited"]["reported_tokens"] == 13080043


@pytest.mark.parametrize("fault", [None, "script", "setup", "full_review"])
def test_machine_handoff_binds_original_goal_setup_body_and_both_native_reviews(monkeypatch, fault):
    ledger, receipts, state, *_ = records_at(READY); reader = bridge.native.Reader()
    original = reader.json
    def projected(path):
        value = original(path)
        if Path(path) == READY / "TEXT_HANDOFF.json":
            if fault == "script": value["native_script"]["title"] += " edited"
            elif fault == "setup": value["native_opening_setup"]["goal_sha256"] = "0" * 64
            elif fault == "full_review": value["native_full_review_bundle"]["native_physical_review"]["context_sha256"] = "0" * 64
        return value
    monkeypatch.setattr(reader, "json", projected)
    if fault is None:
        assert bridge.verify_machine_handoff(reader, READY, ledger["calls"], receipts, state) == bridge.sha_file(READY / "TEXT_HANDOFF.json")
    else:
        with pytest.raises(ValueError): bridge.verify_machine_handoff(reader, READY, ledger["calls"], receipts, state)


@pytest.mark.parametrize("fault", ["prepared", "unknown_status", "unknown_usage", "bool_usage", "truncated", "partial_body",
    "duplicate", "ordinal", "old_plan", "stage_capacity", "reset", "pending_removed", "false_director", "summary_cost", "pending_spend", "protocol_relabel"])
def test_nonterminal_unknown_reset_duplicate_and_capacity_changes_rejected(fault):
    ledger, receipts, state, freeze, scope, auth, inherited = records_at(READY)
    if fault == "prepared": state["status"] = "prepared"
    elif fault == "unknown_status": receipts[-1]["status"] = "outcome_unknown"
    elif fault == "unknown_usage": receipts[-1]["response_metadata"]["total_tokens"] = None
    elif fault == "bool_usage": receipts[-1]["response_metadata"]["prompt_tokens"] = True
    elif fault == "truncated": receipts[-1]["response_metadata"]["finish_reason"] = "length"
    elif fault == "partial_body": receipts[-1]["response_metadata"]["response_body_complete"] = False
    elif fault == "duplicate": receipts[-1]["response_metadata"]["response_id"] = receipts[0]["response_metadata"]["response_id"]
    elif fault == "ordinal": ledger["calls"][-1]["ordinal"] += 1
    elif fault == "old_plan": ledger["calls"][0]["label"] = receipts[0]["label"] = "whole_plan_03"
    elif fault == "stage_capacity": scope["stage_limits"]["goal_audit"] = 5
    elif fault == "reset": ledger["starting_spend"]["reported_tokens"] = 0
    elif fault == "pending_removed": inherited["pending_ordinals"] = []
    elif fault == "false_director": state["old_director_capacity"] = {"used": 0, "limit": 7, "remaining": 7}
    elif fault == "summary_cost": state["spend"]["effective_reported_tokens"] -= 1
    elif fault == "pending_spend": state["spend_verification_pending"] = True
    else: state["status"] = "halt_protocol_requires_diagnosis"; state["text_ready_for_director"] = False
    with pytest.raises(ValueError): bridge.validate_records(ledger, receipts, state, freeze, scope, auth, inherited)


def test_full_sdk_sql_freeze_two_claims_and_readonly_original_run_are_reverified(tmp_path, monkeypatch, causal_scenario):
    root, parent, state, seen = fixture(tmp_path, monkeypatch, causal_scenario)
    before = {str(p): bridge.sha_file(p) for p in tmp_path.rglob("*") if p.is_file()}
    value = bridge.build_anchor(root)
    verified = bridge.verify_anchor(value, expected_anchor_sha256=bridge.digest(value))
    assert verified["inherited"]["calls_started"] == 627 and verified["inherited"]["reported_tokens"] == 13080043
    assert value["whole_goal_candidates_used"] == 4 and value["inherited_whole_goal_candidates_used"] == 36
    assert value["scope_probe_calls_used"] == 2 and value["remaining_scope_probe_calls"] == 0
    assert value["latest_native_goal_receipt"]["ordinal"] == 627 and value["new_plan_native_contract_status"] == "contract_rejected"
    assert value["stage_calls"] == {"goal_plan": 1, "goal_audit": 0, "complete_script": 0, "full_review": 0}
    assert not value["authorizes_new_dispatch"] and not value["creates_successor_claim"] and not value["current_source_freshness_verified"]
    assert not value["text_ready_for_director"] and not value["creative_quality_passed"] and len(seen) == 1
    assert before == {str(p): bridge.sha_file(p) for p in tmp_path.rglob("*") if p.is_file()}


def test_complete_missing_tool_sdk_sql_cost_keeps_old_native_goal_pointer(tmp_path, monkeypatch, causal_scenario):
    root, parent, state, seen = fixture(tmp_path, monkeypatch, causal_scenario, mode="missing_tool")
    value = bridge.build_anchor(root)
    assert value["inherited"]["calls_started"] == 627 and value["whole_goal_candidates_used"] == 4
    assert value["latest_native_goal_receipt"] == parent["latest_native_goal_receipt"]
    assert not value["new_plan_native_tool_available"] and value["new_plan_native_contract_status"] == "interface_rejected"
    assert value["terminal_status"] == "halt_protocol_requires_diagnosis" and len(seen) == 1


@pytest.mark.parametrize("fault", ["snapshot", "raw", "run", "parent_claim", "pending_task", "unknown_session"])
def test_original_file_raw_sql_and_identity_tampering_blocks_anchor(tmp_path, monkeypatch, causal_scenario, fault):
    root, parent, state, seen = fixture(tmp_path, monkeypatch, causal_scenario)
    freeze = bridge.read(root / "PRODUCTION_FREEZE.json")
    if fault == "snapshot":
        source = Path(next(iter(freeze["files"])))
        target = root / "source_at_dispatch" / source.relative_to(tmp_path); target.write_bytes(target.read_bytes() + b" ")
    elif fault == "raw":
        target = root / "call_evidence/call_627/response_body.raw"; target.write_bytes(target.read_bytes() + b" ")
    elif fault == "run": bridge.native.io.write(root / "RUN_CLAIM.json", {"schema": "pretend/v1", "automatic_restart": False})
    elif fault == "parent_claim":
        target = Path(freeze["parent_successor_claim"]["path"]); body = bridge.read(target); body["root"] = str(tmp_path / "other")
        bridge.native.io.write(target, body)
    elif fault == "pending_task":
        with sqlite3.connect(root / "TASKS.sqlite3") as conn:
            conn.execute("UPDATE attempts SET status='claimed',result=NULL,result_sha=NULL")
    else:
        freeze["schema"] = "creative_fresh_source_session/v2/freeze"; bridge.native.io.write(root / "PRODUCTION_FREEZE.json", freeze)
    with pytest.raises(ValueError): bridge.build_anchor(root)


def test_canonical_identity_cannot_hide_changed_anchor_or_accounting(monkeypatch):
    value = {"schema": bridge.VERSION, "root": "offline", "inherited": {"calls_started": 627}}
    monkeypatch.setattr(bridge, "build_anchor", lambda *a, **kw: deepcopy(value))
    changed = deepcopy(value); changed["inherited"]["calls_started"] = 626
    with pytest.raises(ValueError): bridge.verify_anchor(changed, expected_anchor_sha256=bridge.digest(value))
    with pytest.raises(ValueError): bridge.verify_anchor(changed, expected_anchor_sha256=bridge.digest(changed))
