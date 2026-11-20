"""Whole-planning scope repair and known492 inheritance; strictly offline."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import run_selected_script_video_trial_v2 as trial

_spec = importlib.util.spec_from_file_location(
    "_selected_trial_v1_offline_helpers", Path(__file__).with_name("test_video_trial_entry_guard_v1.py"))
old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("scope repair tests cannot access any provider")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def parent():
    ledger = trial.control.read(trial.KNOWN_PARENT / "CALL_LEDGER.json")
    receipt = trial.control.read(trial.KNOWN_PARENT / ledger["calls"][0]["receipt"])
    return SimpleNamespace(ledger=ledger, receipt=receipt)


@pytest.fixture
def full_input(parent):
    x = trial.control.read(trial.KNOWN_PARENT / "INPUT.json")
    x["prior_complete_direction_failure"] = {
        "ordinal": 492, "status": parent.receipt["status"],
        "native_output": deepcopy(parent.receipt["output"]),
        "failure": deepcopy(parent.receipt["failure"]),
        "repair_requirement": "完整新计划须覆盖25来源，不拼旧段。",
    }
    return x


def assert_whole_scope(whole, x):
    assert all(key not in whole for key in (
        "current_scope", "source_acceptance_scope", "original_automatic_decision_retained"))
    assert whole["full_current_script"] == x["full_current_script"]
    assert whole["reference_fulltext"] == x["reference_fulltext"]
    assert len(whole["full_source_catalog"]) == 25
    assert list(whole["full_source_catalog"]) == list(trial.contract.catalog(x["full_current_script"]))
    assert whole["first_refs"] == trial.REFS
    assert whole["prior_complete_direction_failure"]["ordinal"] == 492
    assert whole["prior_complete_direction_failure"]["native_output"] == x["prior_complete_direction_failure"]["native_output"]


def test_whole_plan_inputs_are_distinct_from_current_media_boundary(full_input):
    before = deepcopy(full_input)
    whole, acting = trial.stage_inputs(full_input)
    assert full_input == before
    assert_whole_scope(whole, full_input)
    assert acting["current_scope"] == full_input["current_scope"]
    assert "original_automatic_decision_retained" not in acting
    assert "source_acceptance_scope" not in acting
    whole["full_current_script"]["title"] = "offline mutation"
    assert full_input == before


def test_actual_whole_dispatch_messages_keep_all25_and_reference(monkeypatch, tmp_path, full_input):
    (tmp_path / "INPUT.json").write_text(json.dumps(full_input, ensure_ascii=False), encoding="utf-8")
    calls = []
    class Runtime:
        models = {"writer": {"model": "MiniMax-M3"}}
        def dispatch(self, label, request, validator):
            calls.append((label, deepcopy(request)))
            return {"status": "contract_rejected", "failure": {"category": "validation"}}
    monkeypatch.setattr(trial, "ROOT", tmp_path)
    monkeypatch.setattr(trial, "prepare", lambda: None)
    monkeypatch.setattr(trial, "runtime", Runtime)
    result = trial.text()
    assert result["stage"] == "whole_direction" and result["status"] == "contract_rejected"
    assert len(calls) == 1
    label, request = calls[0]
    assert label == "whole_direction" and request["model"] == "MiniMax-M3"
    whole = json.loads(request["messages"][1]["content"])
    assert_whole_scope(whole, full_input)
    assert len(request["structured_schema"]["properties"]["source_assignments"]["prefixItems"]) == 25
    assert trial.control.read(tmp_path / "WHOLE_DIRECTION_INPUT.json") == whole


def test_actual_known492_rejection_is_carried_as_spend_without_reset(parent):
    before = deepcopy(parent.ledger)
    inherited, receipts = trial.inherited_known_parent(parent.ledger, trial.KNOWN_PARENT)
    assert parent.ledger == before
    assert len(receipts) == 1 and receipts[0] == parent.receipt
    assert receipts[0]["ordinal"] == 492 and receipts[0]["status"] == "contract_rejected"
    assert receipts[0]["response_metadata"]["total_tokens"] == 16506
    assert inherited["calls_started"] == 492
    assert inherited["reported_tokens"] == 7595568
    assert inherited["calls_with_known_usage"] == 490
    assert inherited["unknown_token_reservations"] == 93117
    assert inherited["pending_ordinals"] == [70, 160]
    assert inherited["parent_ledger_sha256"] == trial.control.sha_file(trial.KNOWN_PARENT / "CALL_LEDGER.json")


@pytest.mark.parametrize("where,key,value", [
    ("response_metadata", "total_tokens", None),
    ("response_metadata", "total_tokens", True),
    ("response_metadata", "total_tokens", -1),
    ("response_metadata", "response_body_complete", False),
    ("response_metadata", "response_body_complete", None),
    ("response_metadata", "finish_reason", "length"),
    ("response_metadata", "finish_reason", None),
    (None, "status", "outcome_unknown"),
    (None, "output", None),
    ("failure", "category", "response_protocol"),
])
def test_unknown_incomplete_or_usage_unknown_parent_stops(parent, tmp_path, where, key, value):
    ledger = deepcopy(parent.ledger)
    receipt = deepcopy(parent.receipt)
    (receipt[where] if where else receipt)[key] = value
    rp = tmp_path / "original492.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    ledger["source_manifest"] = {}
    ledger["calls"][0].update(receipt=rp.name, receipt_sha256=trial.control.sha_file(rp))
    for name in ("AUTHORIZATION.json", "ANCHOR.json"):
        (tmp_path / name).write_bytes((trial.KNOWN_PARENT / name).read_bytes())
    (tmp_path / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown|incomplete|known complete"):
        trial.inherited_known_parent(ledger, tmp_path)


@pytest.fixture
def fake_media(monkeypatch, tmp_path):
    monkeypatch.setattr(old, "trial", trial)
    selection = old.selection.__wrapped__()
    return old.fake_media.__wrapped__(monkeypatch, tmp_path, selection)


@pytest.mark.parametrize("missing_id", [False, True])
def test_v2_unknown_submission_does_not_redispatch(fake_media, missing_id):
    old.test_unknown_create_is_never_dispatched_twice(fake_media, missing_id)


def test_v2_original_id_queries_keep_same_budget_and_human_review(fake_media):
    assert fake_media.plan["logical_task_id"] == "legal_trend_text_trial_20261008_adopted_r8"
    assert fake_media.plan["source_run"] is None
    old.test_original_id_query_saves_only_pending_human_review(fake_media)


@pytest.mark.parametrize("section,key,value", [
    ("authorization", "batch_authorized", True),
    ("authorization", "max_new_video_submissions", 2),
    ("authorization", "automatic_retry", True),
    ("authorization", "budget_reset", True),
    (None, "logical_task_id", "changed-story-reset"),
    (None, "source_run", "new-source-run-cannot-reset"),
])
def test_v2_trial_remains_one_segment_without_budget_migration(fake_media, section, key, value):
    plan = deepcopy(fake_media.plan)
    (plan[section] if section else plan)[key] = value
    with pytest.raises(ValueError):
        trial.validate_media_plan(plan)
    assert fake_media.client.submissions == len(fake_media.reservations) == 0
