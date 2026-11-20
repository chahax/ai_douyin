from copy import deepcopy
import json
import shutil

import pytest

from src.content_factory import novel_scene_text_v2 as scene
from src.content_factory.account_novel_creation_v1 import _digest, _provider_protocol, _write
from src.content_factory.creative_workflow import _hash
from src.content_factory.creative_workflow_inputs import file_binding
from src.content_factory.creative_workflow_roles import RoleResult

SOURCE = "眼睛挣扎着睁开。宁慕云靠树站着，宁苍木瞪着他。宁慕云说：“放开我！”宁苍木后退半步。" + "原文背景与婚礼现场。" * 25


@pytest.fixture
def prepared(tmp_path):
    parent = tmp_path / "parent"
    (parent / "creative").mkdir(parents=True)
    (parent / "frozen").mkdir()
    whole = "片外原文不能传入。" + SOURCE
    (parent / "frozen/story_source.txt").write_bytes(whole.encode("utf-8"))
    selected = {"candidate_id": "C01", "start_character": whole.index(SOURCE), "end_character": len(whole),
                "source_sha256": _hash(whole), "excerpt_sha256": _hash(SOURCE), "text": SOURCE}
    _write(parent / "creative/SELECTED_SOURCE.json", selected)
    for ordinal in range(1, 10):
        tokens = 94902 if ordinal == 9 else 1
        _write(parent / f"creative/NATIVE_RESPONSE_{ordinal:03}.json", {"call_ordinal": ordinal,
            "status": "response_received", "response_metadata": {"total_tokens": tokens, "finish_reason": "stop"},
            "response_payload": {"usage": {"total_tokens": tokens}, "choices": [{"finish_reason": "stop"}]}})
    _write(parent / "creative/state.json", {"status": "needs_attention", "logical_task_id": "story1", "calls_started": 9,
        "reported_tokens": 94910, "max_calls": 20, "max_total_tokens": 500000, "max_revisions": 2,
        "max_contract_repairs": 8, "contract_repairs_used": 4, "format_repairs_used": 1, "revision_rounds": 0})
    bound = {"logical_task_id": "story1", "task_registry": str(tmp_path / "old_registry"),
             "provider_protocol": _provider_protocol(), "files": {"body": file_binding(parent / "frozen/story_source.txt")}}
    _write(parent / "BINDING.json", bound)
    _write(parent / "BINDING_ANCHOR.json", {"sha256": _digest(bound)})
    run = tmp_path / "run"
    assert scene.prepare(parent, run, continuation_registry=tmp_path / "continuations")["status"] == "prepared"
    return run, parent


def script(binding):
    present = [{"character": "宁慕云", "action": "靠树站着", "expression": "警觉", "gaze": "看宁苍木"},
               {"character": "宁苍木", "action": "站着", "expression": "恼怒", "gaze": "瞪着宁慕云"}]
    events = [
        {"id": "E01", "kind": "action", "actor": "宁慕云", "text": "宁慕云靠树站着", "source_quote": "宁慕云靠树站着"},
        {"id": "E02", "kind": "dialogue", "actor": "宁慕云", "text": "放开我！", "source_quote": "宁慕云说：“放开我！”"},
        {"id": "E03", "kind": "reaction", "actor": "宁苍木", "text": "宁苍木后退半步", "source_quote": "宁苍木后退半步"},
    ]
    for event in events:
        event.update(duration_seconds=4, performers=deepcopy(present), other_present_state="其余在场者保持当前位置与视线")
    world = {"era": "原文未交代", "daily_context": "婚礼现场", "space_and_prior_events": "宁慕云靠树站着", "relationships": "原文未交代"}
    location, time, timeline, start, end = "树边", "原文未交代具体时刻", "婚礼现场当前", "宁慕云靠树站着", "宁苍木后退半步"
    markdown = "# 完整剧本\n世界框架：" + "；".join(world.values()) + f"\nS01 {timeline} {time} {location}\n段首：{start}\n"
    markdown += "宁慕云摆脱控制；宁苍木目标原文未交代。\n" + "\n".join("；".join(row.values()) for row in present) + "\n"
    markdown += "\n".join(event["actor"] + "：" + event["text"] + "；" + event["other_present_state"] for event in events)
    markdown += "\n段尾：" + end + "\n" + "在场者的动作、神情与视线在事件之间连续保留，完整表演的刺激与反应依次推进。" * 4
    return {"schema": scene.SCRIPT_SCHEMA, "title": "树边", "candidate_id": binding["candidate_id"], "source_sha256": binding["source_sha256"],
            "duration_seconds": 12, "world": world,
            "characters": [{"name": "宁慕云", "situation": "靠树站着", "goal": "摆脱控制", "source_quote": "放开我！"},
                           {"name": "宁苍木", "situation": "瞪着宁慕云", "goal": "原文未交代", "source_quote": "宁苍木瞪着他"}],
            "scenes": [{"id": "S01", "timeline": timeline, "location": location, "time": time,
                        "present": present, "start_state": start, "end_state": end, "events": events}], "screenplay_markdown": markdown}


class Clients:
    def __init__(self, failures=0, tokens=1, finish="stop"):
        self.calls, self.failures, self.tokens, self.finish = [], failures, tokens, finish

    def call(self, role, messages, **kwargs):
        self.calls.append((role, deepcopy(messages), deepcopy(kwargs)))
        payload = json.loads(messages[-1]["content"])
        if role == "writer":
            value = script({"candidate_id": payload["candidate_id"], "source_sha256": payload["actual_source_sha256"]})
            value["title"] += str(len(self.calls))
        else:
            failed = self.failures > 0
            self.failures -= 1
            value = {"schema": scene.REVIEW_SCHEMA, "script_sha256": payload["actual_script_sha256"],
                "source_sha256": payload["actual_source_sha256"], "candidate_id": payload["candidate_id"],
                "whole_text_reviewed": True, "summary": "全文审查已完成",
                "issues": [{"severity": "major", "location": "E01", "evidence": "宁慕云靠树站着", "impact": "表演反应不充分", "proposal": "整稿修订"}] if failed else []}
        reason = "tool_calls" if role == "writer" and self.finish == "stop" else self.finish
        model = "MiniMax-M3" if role == "writer" else "deepseek-flash"
        metadata = {"total_tokens": self.tokens, "finish_reason": reason, "output_mode": "tool_call" if role == "writer" else "content", "response_model": model}
        native = {"id": "fake" + str(len(self.calls)), "model": model, "usage": {"total_tokens": self.tokens}, "choices": [{"finish_reason": reason}]}
        return RoleResult(json.dumps(value, ensure_ascii=False), metadata, native)


def test_prepare_inherits_exact_parent_budget_and_only_selected_story_context(prepared):
    run, _ = prepared
    view = scene.preview(run)
    assert view["remaining_calls"] == 11 and view["remaining_known_tokens"] == 405090
    assert view["source"]["text"] == SOURCE
    assert view["state"]["contract_repairs_used"] + view["state"]["format_repairs_used"] == 5
    clients = Clients()
    result = scene.execute(run, clients=clients)
    assert result["status"] == "machine_text_complete"
    assert result["state"]["calls_started"] == 11 and result["state"]["reported_tokens"] == 94912
    assert result["state"]["revision_rounds"] == 1
    assert all("片外原文不能传入" not in messages[-1]["content"] for _, messages, _ in clients.calls)
    assert json.loads((run / "CALL_010.json").read_text(encoding="utf-8"))["response_payload"]["id"] == "fake1"
    assert scene.execute(run, clients=clients)["status"] == "machine_text_complete"
    assert len(clients.calls) == 2


@pytest.mark.parametrize("failures,status", [(1, "machine_text_complete"), (2, "content_revision_exhausted")])
def test_full_review_failure_generates_one_complete_replacement_with_same_source(prepared, failures, status):
    run, _ = prepared
    clients = Clients(failures=failures)
    result = scene.execute(run, clients=clients)
    assert result["status"] == status and len(clients.calls) == 4
    assert result["state"]["revision_rounds"] == 2 and result["state"]["calls_started"] == 13
    assert result["state"]["reported_tokens"] == 94914
    second = json.loads(clients.calls[2][1][-1]["content"])
    assert second["previous_script"]["scenes"][0]["events"] and second["issues"]
    assert second["selected_source"]["text"] == SOURCE
    scene.execute(run, clients=clients)
    assert len(clients.calls) == 4


@pytest.mark.parametrize("tokens,finish", [(None, "stop"), (1, "length"), (1, None)])
def test_unknown_or_truncated_response_never_redispatched(prepared, tokens, finish):
    run, _ = prepared
    clients = Clients(tokens=tokens, finish=finish)
    with pytest.raises(RuntimeError):
        scene.execute(run, clients=clients)
    with pytest.raises(RuntimeError):
        scene.execute(run, clients=clients)
    assert len(clients.calls) == 1
    assert (run / "CALL_010.json").exists()


def test_pending_original_request_blocks_new_dispatch(prepared):
    run, _ = prepared
    _write(run / "CALL_010.json", {"ordinal": 10, "status": "pending", "stage_key": "writer_01"})
    clients = Clients()
    with pytest.raises(RuntimeError):
        scene.execute(run, clients=clients)
    assert clients.calls == []


def test_parent_native_receipt_tamper_blocks_new_dispatch(prepared):
    run, parent = prepared
    with (parent / "creative/NATIVE_RESPONSE_009.json").open("ab") as stream:
        stream.write(b" ")
    clients = Clients()
    with pytest.raises(ValueError):
        scene.execute(run, clients=clients)
    assert clients.calls == []


def test_same_task_continuation_cannot_claim_new_directory(prepared, tmp_path):
    _, parent = prepared
    with pytest.raises(RuntimeError):
        scene.prepare(parent, tmp_path / "another", continuation_registry=tmp_path / "continuations")


@pytest.mark.parametrize("mutation", ["world", "reaction", "dialogue", "duration", "present", "markdown"])
def test_full_event_contract_rejects_missing_or_out_of_source_content(prepared, mutation):
    run, _ = prepared
    binding, _, _ = scene.verify(run)
    value = script(binding)
    if mutation == "world":
        value.pop("world")
    elif mutation == "reaction":
        value["scenes"][0]["events"][-1]["kind"] = "action"
    elif mutation == "dialogue":
        value["scenes"][0]["events"][1]["text"] = "片段外的父亲原话"
    elif mutation == "duration":
        value["duration_seconds"] = 99
    elif mutation == "present":
        value["scenes"][0]["present"][0]["character"] = "不存在的人"
    else:
        value["screenplay_markdown"] = "摘要"
    with pytest.raises(Exception):
        scene.validate_script(value, binding, SOURCE)


def test_known_complete_schema_failure_uses_second_full_draft_not_patch(prepared):
    run, _ = prepared
    class InvalidFirst(Clients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            if len(self.calls) == 1:
                value = json.loads(result.text)
                value.pop("world")
                return RoleResult(json.dumps(value, ensure_ascii=False), result.metadata, result.response_payload)
            return result
    clients = InvalidFirst()
    result = scene.execute(run, clients=clients)
    assert result["status"] == "machine_text_complete"
    assert [call[0] for call in clients.calls] == ["writer", "writer", "director"]
    assert result["state"]["revision_rounds"] == 2
    assert result["state"]["contract_repairs_used"] == 4 and result["state"]["format_repairs_used"] == 1
    payload = json.loads(clients.calls[1][1][-1]["content"])
    assert payload["issues"] and payload["previous_native_response"]


def test_complete_json_fence_review_keeps_native_response_and_completes(prepared):
    run, _ = prepared
    class Fenced(Clients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            if role == "director":
                return RoleResult("```json\n" + result.text + "\n```", result.metadata, result.response_payload)
            return result
    assert scene.execute(run, clients=Fenced())["status"] == "machine_text_complete"
    assert json.loads((run / "CALL_011.json").read_text(encoding="utf-8"))["response_text"].startswith("```json")


@pytest.mark.parametrize("field", ["action", "expression", "gaze", "other_present_state"])
def test_readable_markdown_cannot_omit_structured_performance(prepared, field):
    run, _ = prepared
    binding, _, _ = scene.verify(run)
    value = script(binding)
    event = value["scenes"][0]["events"][0]
    if field == "other_present_state":
        event[field] = "这个独立反应没有写进可读正文"
    else:
        event["performers"][0][field] = "这个独立表演没有写进可读正文"
    with pytest.raises(ValueError, match="可读剧本漏掉"):
        scene.validate_script(value, binding, SOURCE)


def test_parent_revision_usage_leaves_only_one_full_draft(prepared, tmp_path):
    _, original = prepared
    parent = tmp_path / "prior_revision_parent"
    shutil.copytree(original, parent, ignore=shutil.ignore_patterns("*.lock"))
    state = scene._read(parent / "creative/state.json")
    state["revision_rounds"] = 1
    _write(parent / "creative/state.json", state)
    binding = scene._read(parent / "BINDING.json")
    binding["files"] = {"body": file_binding(parent / "frozen/story_source.txt")}
    _write(parent / "BINDING.json", binding)
    _write(parent / "BINDING_ANCHOR.json", {"sha256": _digest(binding)})
    run = tmp_path / "one_remaining"
    scene.prepare(parent, run, continuation_registry=tmp_path / "other_registry")
    clients = Clients(failures=2)
    result = scene.execute(run, clients=clients)
    assert result["status"] == "content_revision_exhausted" and len(clients.calls) == 2
    assert result["state"]["revision_rounds"] == 2
