"""Actual orchestration with fake native envelopes, never paid requests."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v5 as pipe
from src.content_factory.creative_workflow_roles import RoleResult
from src.content_factory import novel_logic_contracts_v4 as contracts


def fact(value="standing"):
    return {"subject_id": "hero", "predicate": "posture", "value": value,
            "certainty": "explicit", "evidence_refs": ["S01: opening"], "qualifiers": {"scope": "physical"}}


def event():
    return {"event_id": "E01", "timeline_id": "present", "narrative_layer": "performance",
            "entities": ["hero"], "relation": "new_event", "referent_event_id": None,
            "before": [fact()], "after": [fact()], "interpretation_status": "explicit",
            "context": {"scene_id": "S01", "location": "room", "description": "Hero answers at the table."}}


def issue():
    return {"issue_id": "I1", "root_cause_id": "invented-backstory", "dimensions": ["causality"],
            "event_ids": ["E01"], "evidence": ["Invented knowing the hidden letter."],
            "reasonable_explanations": [], "counterevidence": [], "impact": "Changes the motive.",
            "severity": "major", "severity_certainty": "confirmed", "finding_status": "confirmed", "blocking": True}


def review(verdict="pass", *, disposition="confirmed", required=None):
    issues = [issue()] if verdict == "revise" and required is None else []
    return {"scene_ledger": {"events": [event()]},
            "full_review": {"native_verdict": verdict, "whole_text_reviewed": True,
                "source_complete": True, "draft_complete": True, "issues": issues,
                "checks": [{"dimension": name, "checked": True, "assessment": "Complete same-draft check.",
                            "issue_ids": [row["issue_id"] for row in issues if name in row["dimensions"]]}
                           for name in contracts.REVIEW_DIMENSIONS]},
            "adjudication": {"new_issues": [], "dispositions": [
                {"issue_id": row["issue_id"], "disposition": disposition,
                 "basis": ["Compared the complete source and current draft."], "new_issue_ids": [],
                 "blocking": disposition == "confirmed"} for row in (issues if required is None else required)]}}


def plan():
    return {"world_framework": "A present-day room; hero chooses to answer the family.",
        "selected_scope": "Only the acquired chapter, stopping at its actual ending.",
        "segments": [{"segment_id": "S01", "timeline_id": "present", "location": "room",
            "environment": "Table beside the door.", "present_characters": ["hero"],
            "start_state": [fact()], "end_state": [fact()], "performance": [{"event_id": "E01",
                "actor_id": "hero", "action": "Looks up and answers.", "expression": "Firm",
                "gaze": "Toward the door", "dialogue": "I will decide.", "reaction": "Waits for an answer.",
                "reaction_window": "After the line"}], "emotion_focus": "Taking control",
            "next_cause": "The chapter ends on his choice.", "estimated_duration_seconds": 8,
            "duration_basis": "One short line and its readable reaction."}],
        "event_coverage": [{"event_id": "E01", "segment_ids": ["S01"], "relation": "new_event"}],
        "asset_requirements": [{"asset_type": "character", "search_tags": ["hero"],
            "status": "pending", "candidate_id": None, "candidate_version": None}]}


def director_review(verdict="pass"):
    return {"verdict": verdict, "whole_text_reviewed": True, "summary": "All director segments reviewed.",
        "checks": [{"dimension": name, "checked": True, "assessment": "Full director text assessed.",
                    "issues": [{"severity": "major", "location": "S01", "evidence": "Reaction is missing.",
                                "suggestion": "Give the actor a readable reaction."}]
                              if verdict == "revise" and name == "emotion_windows" else []}
                   for name in contracts.REVIEW_DIMENSIONS]}


def result(value, role="writer", *, finish="stop", unknown=False, tokens=100):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    model = "MiniMax-M3" if role == "writer" else "deepseek-flash"
    meta = {"role": role, "provider": "minimax" if role == "writer" else "deepseek",
            "requested_model": model, "response_model": model, "response_id": "response-" + str(id(value)),
            "finish_reason": finish, "output_mode": "content", "prompt_tokens": tokens // 2,
            "completion_tokens": tokens - tokens // 2, "total_tokens": tokens}
    usage = {key: meta[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    if unknown:
        meta.pop("total_tokens")
        usage.pop("total_tokens")
    payload = {"id": meta["response_id"], "model": model, "usage": usage,
               "choices": [{"finish_reason": finish, "message": {"content": text, "tool_calls": [],
                              "reasoning_content": None}}]}
    return RoleResult(text, meta, payload)


class FakeClients:
    def __init__(self, values):
        self.values, self.calls = list(values), []

    def call(self, role, messages, **parameters):
        self.calls.append({"role": role, "messages": deepcopy(messages), "parameters": deepcopy(parameters)})
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", tmp_path / "canonical")
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    path = tmp_path / "chapter.txt"
    path.write_text("第1章\n房间里，他在桌前抬头答话：我要自己决定。", encoding="utf-8")
    return path


@pytest.fixture
def prepared(source, tmp_path):
    run = tmp_path / "run"
    pipe.prepare(run, source_path=source, title="测试小说", book_id="test-book")
    return run


def success_values():
    return [result("背景、角色、主线高潮、改编规划。\r\n完整稿：他抬头答话。结尾。"),
            result(review(), "director"), result(plan()), result(director_review(), "director")]


def test_full_flow_uses_real_native_contracts_and_no_media(prepared):
    clients = FakeClients(success_values())
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "text_ready_for_production"
    assert view["calls_started"] == 4 and view["known_reported_tokens"] == 400
    assert [row["role"] for row in clients.calls] == ["writer", "director", "writer", "director"]
    assert all(row["parameters"]["structured_schema"] is None for row in clients.calls)
    assert view["human_approved"] is False and view["automatic_media_submit"] is False
    assert view["media_generated"] is False
    assert len(list(prepared.glob("CLAIM_*.json"))) == 4
    assert len(list(prepared.glob("CALL_LEDGER_*.json"))) == 4
    assert (prepared / "SCREENPLAY.md").read_bytes() == success_values()[0].text.encode("utf-8")
    assert pipe.execute(prepared, clients=FakeClients([]))["calls_started"] == 4


def test_one_stage_pause_resumes_without_repeat(prepared):
    clients = FakeClients(success_values())
    first = pipe.execute(prepared, clients=clients, max_steps=1)
    assert first["stage"] == "review_full" and first["calls_started"] == 1
    second = pipe.execute(prepared, clients=clients, max_steps=1)
    assert second["stage"] == "director_full" and second["calls_started"] == 2
    assert pipe.execute(prepared, clients=clients)["status"] == "text_ready_for_production"
    assert len(clients.calls) == 4


def test_confirmed_major_rewrites_whole_draft_not_director(prepared):
    values = [result("完整初稿"), result(review("revise"), "director"), *success_values()]
    clients = FakeClients(values)
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "text_ready_for_production" and view["state"]["revisions_used"] == 1
    payload = json.loads(clients.calls[2]["messages"][-1]["content"])
    assert payload["previous_draft"] == "完整初稿"
    assert payload["review"]["review"]["review"]["native_verdict"] == "revise"
    assert (prepared / "DRAFT_001.md").read_text(encoding="utf-8") == "完整初稿"


def test_native_revise_all_rejected_requires_native_same_draft_pass(prepared):
    clients = FakeClients([result("完整稿"), result(review("revise", disposition="rejected"), "director"),
        result(review(required=[issue()], disposition="rejected"), "director"),
        result(plan()), result(director_review(), "director")])
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "text_ready_for_production"
    assert view["state"]["revisions_used"] == 0 and view["state"]["clarifications_used"] == 1
    payload = json.loads(clients.calls[2]["messages"][-1]["content"])
    assert payload["screenplay"] == "完整稿" and payload["required_issues"] == [issue()]
    assert json.loads((prepared / "REVIEW_002.json").read_text(encoding="utf-8"))["native_verdict"] == "revise"


def test_writer_revision_limit_counts_actual_dispatches(prepared):
    clients = FakeClients([item for _ in range(3) for item in
                          (result("完整但失败的稿"), result(review("revise"), "director"))])
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "content_revision_exhausted"
    assert view["calls_started"] == 6 and view["state"]["revisions_used"] == 2
    assert not (prepared / "SCREENPLAY.md").exists()


def test_director_revision_does_not_rewrite_approved_writer(prepared):
    clients = FakeClients(success_values()[:3] + [result(director_review("revise"), "director"),
        result(plan()), result(director_review(), "director")])
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "text_ready_for_production" and view["state"]["director_revisions_used"] == 1
    assert view["state"]["revisions_used"] == 0 and len(list(prepared.glob("DRAFT_*.md"))) == 1
    payload = json.loads(clients.calls[4]["messages"][-1]["content"])
    assert payload["previous_director"] and payload["revision_feedback"]["native_verdict"] == "revise"


@pytest.mark.parametrize("finish,unknown", [("length", False), ("stop", True)])
def test_unknown_or_truncated_receipt_preserved_and_stops(prepared, finish, unknown):
    with pytest.raises(RuntimeError):
        pipe.execute(prepared, clients=FakeClients([result("部分正文", finish=finish, unknown=unknown)]))
    view = pipe.inspect(prepared)
    assert view["status"] == "needs_attention" and view["pending_call"] == 1
    assert view["reported_tokens"] == (None if unknown else 100)
    assert (prepared / "RESPONSE_001.json").exists()
    assert pipe.execute(prepared, clients=FakeClients([]))["calls_started"] == 1


def test_native_response_saved_before_checkpoint_recovers_without_redispatch(prepared, monkeypatch):
    original = pipe._adopt_response
    monkeypatch.setattr(pipe, "_adopt_response", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    first = FakeClients(success_values()[:1])
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(prepared, clients=first)
    monkeypatch.setattr(pipe, "_adopt_response", original)
    remaining = FakeClients(success_values()[1:])
    view = pipe.execute(prepared, clients=remaining)
    assert view["status"] == "text_ready_for_production" and view["known_reported_tokens"] == 400
    assert [row["role"] for row in remaining.calls] == ["director", "writer", "director"]


def test_inflight_unknown_never_redispatches(prepared):
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(prepared, clients=FakeClients([KeyboardInterrupt()]))
    clients = FakeClients([])
    with pytest.raises(RuntimeError, match="未知"):
        pipe.execute(prepared, clients=clients)
    assert clients.calls == [] and pipe.inspect(prepared)["pending_call"] == 1


def test_invalid_sidecar_does_not_trigger_writer_repair(prepared):
    with pytest.raises(ValueError):
        pipe.execute(prepared, clients=FakeClients([result("完整稿"), result("not JSON", "director")]))
    view = pipe.inspect(prepared)
    assert view["status"] == "needs_attention" and view["calls_started"] == 2
    assert view["state"]["revisions_used"] == 0


def test_same_source_cannot_claim_again_with_different_registry(source, tmp_path):
    pipe.prepare(tmp_path / "first", source_path=source, title="one", book_id="known")
    with pytest.raises(RuntimeError, match="不能"):
        pipe.prepare(tmp_path / "new", source_path=source, title="renamed", book_id="changed",
                     registry_dir=tmp_path / "different")


def test_legacy_registry_alias_blocks_v5(source, tmp_path):
    canonical = Path(pipe.CANONICAL_REGISTRY)
    canonical.mkdir()
    old = canonical / ("book_" + pipe.core._digest("known") + ".json")
    pipe.core._write(old, {"schema": "novel_plaintext_pipeline/v3", "run_dir": "old", "remaining": 0})
    before = old.read_bytes()
    with pytest.raises(RuntimeError, match="不能"):
        pipe.prepare(tmp_path / "new", source_path=source, book_id="known")
    assert old.read_bytes() == before


@pytest.mark.parametrize("change", ["source", "response", "scene_ledger", "handoff"])
def test_tampered_original_or_derived_evidence_fails_closed(prepared, change):
    pipe.execute(prepared, clients=FakeClients(success_values()))
    binding = pipe.core._read(prepared / "BINDING.json")
    path = {"source": Path(binding["source_evidence"][0]["path"]), "response": prepared / "RESPONSE_002.json",
            "scene_ledger": prepared / "SCENE_LEDGER_002.json", "handoff": prepared / "PRODUCTION_HANDOFF.json"}[change]
    path.write_bytes(path.read_bytes() + b" ")
    assert pipe.inspect(prepared)["status"] == "incomplete_artifacts"


def test_known_final_pass_delivered_at_zero_call_capacity(source, tmp_path):
    run = tmp_path / "run"
    pipe.prepare(run, source_path=source, max_calls=4)
    view = pipe.execute(run, clients=FakeClients(success_values()))
    assert view["status"] == "text_ready_for_production" and pipe.preview(run)["remaining_calls"] == 0


def test_unsupported_max_steps_is_rejected_before_dispatch(prepared):
    for value in (0, -1, True, "1"):
        with pytest.raises(ValueError):
            pipe.execute(prepared, clients=FakeClients([]), max_steps=value)


def test_native_pass_new_scene_candidate_requires_actual_full_clarification(prepared):
    first = review()
    second_event = event()
    second_event.update(event_id="E02", before=[fact("sitting")])
    second_event["context"]["continuity_from_event_id"] = "E01"
    first["scene_ledger"]["events"].append(second_event)
    pipe.execute(prepared, clients=FakeClients([result("他在桌边答话，动作没有清楚交代。")]), max_steps=1)
    view = pipe.execute(prepared, clients=FakeClients([result(first, "director")]), max_steps=1)
    assert view["stage"] == "clarify_full" and view["state"]["revisions_used"] == 0
    saved = pipe.core._read(prepared / "GATE_002.json")
    candidates = saved["scene_candidate_issues"]
    assert len(candidates) == 1 and candidates[0]["severity_certainty"] == "unknown"
    next_review = review(required=candidates, disposition="rejected")
    next_review["scene_ledger"] = deepcopy(first["scene_ledger"])
    client = FakeClients([result(next_review, "director")])
    view = pipe.execute(prepared, clients=client, max_steps=1)
    assert view["stage"] == "director_full" and view["state"]["clarifications_used"] == 1
    payload = json.loads(client.calls[0]["messages"][-1]["content"])
    assert payload["required_issues"] == candidates
    assert payload["screenplay"] == "他在桌边答话，动作没有清楚交代。"


def test_clarification_limit_cannot_be_reset_by_execute_restart(prepared):
    first = review("revise", disposition="rejected")
    second = review(required=[issue()], disposition="rejected")
    second["full_review"]["native_verdict"] = "revise"
    clients = FakeClients([result("完整稿"), result(first, "director"), result(second, "director")])
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "needs_attention" and view["calls_started"] == 3
    assert view["state"]["clarifications_used"] == 1
    assert pipe.execute(prepared, clients=FakeClients([]))["calls_started"] == 3


def test_director_known_content_contract_gets_one_full_local_layer_revision(prepared):
    invalid = plan()
    invalid["segments"][0]["performance"][0]["event_id"] = "E99"
    invalid["event_coverage"][0]["event_id"] = "E99"
    clients = FakeClients(success_values()[:2] + [result(invalid), result(plan()),
        result(director_review(), "director")])
    view = pipe.execute(prepared, clients=clients)
    assert view["status"] == "text_ready_for_production"
    assert view["calls_started"] == 5 and view["state"]["director_revisions_used"] == 1
    payload = json.loads(clients.calls[3]["messages"][-1]["content"])
    assert payload["previous_director"] == invalid
    assert payload["revision_feedback"]["content_contract_errors"]
    assert len(list(prepared.glob("DRAFT_*.md"))) == 1


def test_final_director_request_capacity_does_not_grant_more_calls(source, tmp_path):
    run = tmp_path / "run"
    pipe.prepare(run, source_path=source, max_calls=3)
    client = FakeClients(success_values()[:3])
    with pytest.raises(RuntimeError, match="预算耗尽"):
        pipe.execute(run, clients=client)
    assert pipe.inspect(run)["calls_started"] == 3 and len(client.calls) == 3
    assert not (run / "PRODUCTION_HANDOFF.json").exists()


def test_content_revision_saved_native_response_recovers_exact_request_once(prepared, monkeypatch):
    pipe.execute(prepared, clients=FakeClients([result("初稿"), result(review("revise"), "director")]), max_steps=2)
    original = pipe._adopt_response
    monkeypatch.setattr(pipe, "_adopt_response", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(prepared, clients=FakeClients([result("返修完整稿")]))
    monkeypatch.setattr(pipe, "_adopt_response", original)
    client = FakeClients(success_values()[1:])
    view = pipe.execute(prepared, clients=client)
    assert view["status"] == "text_ready_for_production" and view["calls_started"] == 6
    assert view["state"]["revisions_used"] == 1
    assert [call["role"] for call in client.calls] == ["director", "writer", "director"]


def test_explicit_target_and_catalog_candidate_are_frozen_and_consumed(source, tmp_path):
    image = tmp_path / "hero.png"
    image.write_bytes(b"local-asset-identity-only")
    catalog = tmp_path / "CATALOG.json"
    catalog.write_text(json.dumps({"assets": [{"asset_id": "hero", "version": "v1", "name": "hero",
        "kind": "character", "details": {"tags": ["hero"]}, "image": {"path": "hero.png",
        "expected_sha256": pipe.core._binding(image)["sha256"]}}]}), encoding="utf-8")
    run = tmp_path / "run"
    pipe.prepare(run, source_path=source, brief={"target_duration_seconds": 180}, catalog_path=catalog)
    clients = FakeClients(success_values())
    view = pipe.execute(run, clients=clients)
    assert view["status"] == "text_ready_for_production"
    payload = json.loads(clients.calls[2]["messages"][-1]["content"])
    candidate = payload["catalog_candidates"][0]
    assert candidate["candidate_id"] == "hero" and "path" not in candidate
    assert payload["target_duration_seconds"] == 180
    candidate_output = pipe.core._read(run / "ASSET_CANDIDATES.json")["candidates"][0]
    assert candidate_output["integrity"] == "ok" and candidate_output["current_casting_status"] == "unbound"
    image.write_bytes(b"changed asset")
    assert pipe.inspect(run)["status"] == "incomplete_artifacts"


def test_native_receipt_and_snapshot_saved_projection_failure_recovers_without_call(prepared, monkeypatch):
    original = pipe._save_state
    failed = False

    def fail_projection(run, state):
        nonlocal failed
        if not failed and (run / "RESPONSE_001.json").exists() and state.get("pending_call") is None:
            failed = True
            number = len(list(run.glob("STATE_*.json"))) + 1
            pipe.core._write(run / f"STATE_{number:05}.json", state)
            raise OSError("Injected failure after immutable checkpoint publication")
        return original(run, state)

    monkeypatch.setattr(pipe, "_save_state", fail_projection)
    with pytest.raises(OSError):
        pipe.execute(prepared, clients=FakeClients(success_values()[:1]))
    assert pipe.inspect(prepared)["status"] == "evidence_invalid"
    assert pipe.inspect(prepared)["projection_recovery_available"] is True
    monkeypatch.setattr(pipe, "_save_state", original)
    repaired = pipe.recover_projection(prepared)
    assert repaired["status"] == "running" and repaired["calls_started"] == 1
    assert repaired["projection_recovery_available"] is False
    client = FakeClients(success_values()[1:])
    view = pipe.execute(prepared, clients=client)
    assert view["status"] == "text_ready_for_production" and view["calls_started"] == 4
    assert [call["role"] for call in client.calls] == ["director", "writer", "director"]


def test_unverified_orphan_snapshot_does_not_recover_or_dispatch(prepared):
    state = pipe.core._read(prepared / "state.json")
    state["calls_started"] = 1
    number = len(list(prepared.glob("STATE_*.json"))) + 1
    pipe.core._write(prepared / f"STATE_{number:05}.json", state)
    assert pipe.inspect(prepared)["projection_recovery_available"] is False
    client = FakeClients([])
    with pytest.raises(ValueError, match="检查点不符"):
        pipe.execute(prepared, clients=client)
    assert not client.calls
