"""MockTransport at the SDK boundary; all source/parent admission is synthetic."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_live_session_v1 as live
from src.content_factory.creative_counted_execution_v1 import CountedExecution

REAL = Path(__file__).resolve().parents[1]
SCENARIO = REAL / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_WHOLE_REVISION_v1.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("Only offline SDK MockTransport is authorized by these tests")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(live.clients, "role_config", lambda role: SimpleNamespace(
        model=live.clients.WRITER_MODEL if role == "writer" else live.clients.REVIEW_MODEL,
        base_url="https://api.minimax.cn/v1" if role == "writer" else "https://api.deepseek.com/v1", api_key="offline-not-a-real-key"))


def setup_session(tmp_path, monkeypatch, *, fault=None):
    monkeypatch.setattr(live, "PROJECT", tmp_path)
    scenario = live.read(SCENARIO)
    inputs = scenario["inputs"]
    for name in ("CODE", "SOURCE", "PARENT_STATE", "AUTHORIZATION_AND_CADENCE_v1", "USER_COUNT_UNIT_CONFIRMATION_v1"):
        live.write(tmp_path / (name + ".json"), {"offline_synthetic": name})
    live.write(tmp_path / "PROFILE.json", scenario["profile"])
    live.write(tmp_path / "PREFS.json", inputs["production_preferences"])
    live.write(tmp_path / "GOALS.json", inputs["user_goal_contract"])
    parent_root = tmp_path / "historical640"; parent_root.mkdir()
    anchor = {"schema": "offline-synthetic640-not-original-certification", "root": str(parent_root),
        "parent_identity": {"root": str(parent_root), "end_ordinal": 640},
        "inherited": {"calls_started": 640, "reported_tokens": 13544245, "calls_with_known_usage": 638,
            "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}}
    live.write(tmp_path / "PARENT.json", anchor)
    counter = CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round14", "offline world live-adapter branch validation")
    def parent_verifier(value, *, expected_anchor_sha256):
        assert live.digest(value) == expected_anchor_sha256
        return {"verified": True, "anchor": value, "inherited": value["inherited"],
            "source_files": {str(tmp_path / "PARENT_STATE.json"): live.sha(tmp_path / "PARENT_STATE.json")}}
    fresh = []
    def source_gate(path, *, now):
        fresh.append(now); return {"valid": True, "current_source_freshness_verified": True, "offline": True}
    def builder(*args, **kwargs):
        return {"inputs": deepcopy(inputs), "evidence": {"offline_source_admission": True},
            "source_files": [str(tmp_path / "SOURCE.json")]}
    seen = []; holder = {}
    def client_factory(request):
        def respond(outgoing):
            label = holder["session"].pending_intent["label"]
            seen.append({"label": label, "wire": json.loads(outgoing.read())})
            if fault == "transport": raise httpx.ReadTimeout("offline transport unknown", request=outgoing)
            output = deepcopy(scenario["documents"][label]["output"])
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-tool-" + label,
                "type": "function", "function": {"name": live.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]}
            if fault == "missing_tool": message = {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            body = {"id": "offline-response-" + label, "model": request["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "length" if fault == "truncated" else
                    "stop" if fault == "missing_tool" else "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            if fault == "usage_unknown": body.pop("usage")
            return httpx.Response(200, content=json.dumps(body, ensure_ascii=False).encode())
        return live.clients.make_client_factory(request,
            http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(respond), verify=False, **kw))
    config = live.Config(str(tmp_path / "run"), "offline-world-live", str(tmp_path / "PARENT.json"), live.digest(anchor),
        str(tmp_path / "source_dir"), str(tmp_path / "PREFS.json"), str(tmp_path / "GOALS.json"), str(tmp_path / "PROFILE.json"),
        str(tmp_path / "AUTH.json"), str(tmp_path), "round14", review_admission_module="src.content_factory.creative_full_review_protocol_v6")
    session = live.Session(config, parent_verifier=parent_verifier, input_builder=builder, source_gate=source_gate,
        client_factory_builder=client_factory, review_adapter=live.workflow.full_reviews())
    holder["session"] = session
    # This fixture tests admission logic with a small explicit source set;
    # production code_files still freezes its actual local import closure.
    monkeypatch.setattr(session, "code_files", lambda: [tmp_path / "CODE.json"])
    return session, seen, counter, fresh, scenario


def prepare(session):
    value = session.preview(); live.write(session.config.authorization_path, session.authorization_template(value), True)
    session.prepare(); return value


def test_preview_no_claim_client_or_counter_mutation_and_explicit26_policy(tmp_path, monkeypatch):
    session, seen, counter, _, _ = setup_session(tmp_path, monkeypatch)
    before = counter.path.read_bytes(); value = session.preview()
    assert value["provider_calls"] == 0 and value["inherited"]["calls_started"] == 640
    assert live.LIMITS == {"goal_plan": 5, "goal_audit": 12, "complete_script": 3, "full_review": 6}
    assert not session.root.exists() and not session.claim.exists() and not seen and before == counter.path.read_bytes()
    prepare(session)
    assert session.runtime().stage_limits == live.LIMITS and not seen


def test_actual_sdk_full_native_revision_and_verified_handoff_rejects_forged_sha_and_reports(tmp_path, monkeypatch):
    session, seen, _, fresh, scenario = setup_session(tmp_path, monkeypatch); prepare(session)
    result = session.run()
    assert result["status"] == "text_ready_for_director", result
    labels = [row["label"] for row in seen]
    assert len(seen) == 11 and "full_review_physical_01" not in labels
    assert labels[-3:] == ["complete_script_02", "full_review_semantic_02", "full_review_physical_02"]
    ledger = live.read(session.root / "CALL_LEDGER.json")
    second = live.read(session.root / next(row["receipt"] for row in ledger["calls"] if row["label"] == "complete_script_02"))
    actual = json.loads(second["request"]["messages"][1]["content"])
    assert actual["previous_complete_document"] == scenario["documents"]["complete_script_01"]["output"]
    assert actual["revision_diagnostics"]["native_part_reviews"]["semantic"] == scenario["documents"]["full_review_semantic_01"]["output"]
    assert result["spend"]["effective_calls_started"] == 651 and result["spend"]["effective_reported_tokens"] == 13545345
    assert result["spend"]["historical_pending_ordinals"] == [70, 160] and result["spend"]["unknown_token_reservations"] == 93117
    with sqlite3.connect(session.root / "TASKS.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 11
    monkeypatch.setattr(live.Session, "open", classmethod(lambda cls, root, **kw: session))
    verified = live.verify_text_handoff(session.root)
    assert verified["valid"] and verified["accepted"] and not verified["authorizes_media_dispatch"] and fresh
    assert verified["identity"]["native_script_sha256"] != verified["identity"]["compiled_script_sha256"]
    original_handoff = (session.root / "TEXT_HANDOFF.json").read_bytes()
    original_state = (session.root / "STATE.json").read_bytes()
    handoff = live.read(session.root / "TEXT_HANDOFF.json"); state = live.read(session.root / "STATE.json")
    handoff["run_claim_sha256"] = state["run_claim_sha256"] = "0" * 64
    state["text_handoff_sha256"] = live.digest(handoff)
    live.write(session.root / "TEXT_HANDOFF.json", handoff); live.write(session.root / "STATE.json", state)
    with pytest.raises(ValueError, match="state/handoff"): live.verify_text_handoff(session.root)
    (session.root / "TEXT_HANDOFF.json").write_bytes(original_handoff); (session.root / "STATE.json").write_bytes(original_state)
    handoff = live.read(session.root / "TEXT_HANDOFF.json"); state = live.read(session.root / "STATE.json")
    fullpath = Path(handoff["paths"]["full_review_bundle"]); full = live.read(fullpath)
    full["native_physical_review"]["original_service_result_was_not_this"] = True
    live.write(fullpath, full)
    handoff["artifact_file_sha256"][str(fullpath)] = live.sha(fullpath)
    handoff["native_identity"]["full_review_bundle"] = live.digest(full)
    state["text_handoff_sha256"] = live.digest(handoff)
    live.write(session.root / "TEXT_HANDOFF.json", handoff); live.write(session.root / "STATE.json", state)
    with pytest.raises(ValueError, match="original service result"): live.verify_text_handoff(session.root)
    with pytest.raises(FileExistsError, match="RUN_CLAIM"): session.run()


@pytest.mark.parametrize("fault", ["transport", "truncated", "usage_unknown", "missing_tool"])
def test_unknown_truncation_and_missing_tool_stop_one_call_without_retries(tmp_path, monkeypatch, fault):
    session, seen, _, _, _ = setup_session(tmp_path, monkeypatch, fault=fault); prepare(session)
    result = session.run()
    assert len(seen) == 1 and result["status"].startswith("halt_") and not result["text_ready_for_director"]
    assert not (session.root / "TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError): session.run()


def test_counter_rechecked_after_original_task_claim_before_provider(tmp_path, monkeypatch):
    session, seen, counter, _, _ = setup_session(tmp_path, monkeypatch); prepare(session)
    old = live.policy.tasks.TaskStore.claim
    def stopped(store, *args, **kwargs):
        value = old(store, *args, **kwargs)
        path = tmp_path / "OFFLINE_STOP.json"; live.write(path, {"offline": True})
        counter.complete_round("round14", action="offline stop", conclusion="before SDK", evidence_paths=[path])
        return value
    monkeypatch.setattr(live.policy.tasks.TaskStore, "claim", stopped)
    result = session.run()
    assert result["status"] == "halt_execution_reconciliation" and seen == []
    assert live.read(session.root / "CALL_LEDGER.json")["calls"] == []
    with sqlite3.connect(session.root / "TASKS.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_same_parent_different_grant_root_cannot_regrant_new_scope(tmp_path, monkeypatch):
    session, seen, _, _, _ = setup_session(tmp_path, monkeypatch); prepare(session)
    other = live.Session(replace(session.config, root=str(tmp_path / "other"), grant_id="other",
        authorization_path=str(tmp_path / "AUTH2.json")), parent_verifier=session.parent_verifier,
        input_builder=session.input_builder, source_gate=session.source_gate, review_adapter=session.injected_review_adapter)
    monkeypatch.setattr(other, "code_files", session.code_files)
    live.write(other.config.authorization_path, other.authorization_template(other.preview()), True)
    with pytest.raises(ValueError, match="unique successor"): other.prepare()
    assert not seen


def test_exact_intent_rechecked_after_task_claim_before_provider(tmp_path, monkeypatch):
    session, seen, _, _, _ = setup_session(tmp_path, monkeypatch); prepare(session)
    old = live.policy.tasks.TaskStore.claim
    def changed(store, *args, **kwargs):
        value = old(store, *args, **kwargs)
        intent = Path(session.pending_intent["path"]); altered = live.read(intent)
        altered["prepared"]["request"]["messages"][0]["content"] += " changed after task claim"
        live.write(intent, altered)
        return value
    monkeypatch.setattr(live.policy.tasks.TaskStore, "claim", changed)
    result = session.run()
    assert result["status"] == "halt_execution_reconciliation" and not seen


def test_explicit_new_scope_routes_preserve_old_decision_and_unknown_still_stops():
    old = {"valid": True, "accepted": False, "findings": [{"code": "native_script_failure"}], "uncertainties": [],
        "status": "halt_same_story_prior_allowance_exhausted", "revision_dispatch_blocked": True,
        "new_scope_revision_admitted": True, "underlying_v6_decision": {"accepted": False}}
    before = deepcopy(old)
    assert live.LiveDriver.audit_gate(old, "semantic") is False and old == before
    with pytest.raises(ValueError, match="does not accept"): live._require_accepted(old, "handoff_full")
    plan = {**old, "new_scope_revision_admitted": False, "new_scope_requires_new_goal_plan": True, "requires_new_goal_plan": True}
    assert live.LiveDriver.audit_gate(plan, "semantic") is False
    unknown = {**old, "uncertainties": [{"code": "native_unknown"}]}
    with pytest.raises(live.stages.OfflineStop): live.LiveDriver.audit_gate(unknown, "semantic")


def test_actual_scope_adapter_factory_and_exact_profile_fail_closed(tmp_path, monkeypatch):
    session, seen, _, _, _ = setup_session(tmp_path, monkeypatch); prepare(session)
    session.config = replace(session.config, review_admission_module="scripts.creative_world_scene_review_admission_v1")
    session.injected_review_adapter = None
    scope = live.read(session.root / "USER_SCOPE.json")
    adapter = session._reviews(scope)
    assert adapter.VERSION == "creative_world_scene_review_admission/v1" and seen == []
    bad = deepcopy(scope); bad["inputs_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="inputs identity"): session._reviews(bad)
    profile = live.read(session.config.profile_path); profile["director"]["parameters"]["thinking"] = "enabled"
    live.write(session.config.profile_path, profile)
    with pytest.raises(ValueError, match="exact role/stage"): session._profile_gate()
    assert seen == []


def test_feedback_compilation_preserves_full_native_values_and_exact_functional_failure():
    row = {"table": "world_scene_checks", "item_id": "world", "target": "script",
        "finding": {"status": "fail", "reason": "OFFLINE exact functional problem", "required_revision": "whole native draft"}}
    underlying = {"valid": True, "accepted": False, "status": "halt_same_story_prior_allowance_exhausted",
        "findings": [deepcopy(row), deepcopy(row)], "uncertainties": [], "revision_target": "script"}
    original = {**deepcopy(underlying), "underlying_v6_decision": deepcopy(underlying),
        "review_admission_version": "creative_world_scene_review_admission/v1", "new_scope_revision_admitted": True}
    inputs = {"previous_complete_document": {"OFFLINE": "complete native remains exact"},
        "revision_diagnostics": {"complete_same_source_part_review": original,
            "native_part_reviews": {"semantic": {"OFFLINE": "complete report, including every pass row"}}}}
    before = deepcopy(inputs); result, manifest = live.compile_revision_feedback(inputs)
    projected = result["revision_diagnostics"]["complete_same_source_part_review"]
    assert inputs == before and result["previous_complete_document"] == inputs["previous_complete_document"]
    assert result["revision_diagnostics"]["native_part_reviews"] == inputs["revision_diagnostics"]["native_part_reviews"]
    assert projected["findings"] == [row] and projected["status"] == original["status"] and projected["accepted"] is False
    assert "underlying_v6_decision" not in projected and projected["underlying_v6_decision_sha256"] == live.digest(underlying)
    assert manifest["native_reports_preserved_by_value"] and not manifest["context_budget_increased"]
    unknown = deepcopy(inputs); unknown["revision_diagnostics"]["complete_same_source_part_review"]["review_admission_version"] = "unknown/v99"
    assert live.compile_revision_feedback(unknown) == (unknown, None)


def test_existing_frozen_run_cannot_change_its_counter_key_via_new_config(tmp_path, monkeypatch):
    session, seen, _, _, _ = setup_session(tmp_path, monkeypatch); prepare(session)
    session.config = replace(session.config, round_key="another-active-round")
    with pytest.raises(ValueError, match="original frozen run/round"): session._guard()
    assert seen == []
