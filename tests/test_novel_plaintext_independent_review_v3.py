"""Independent offline checks of prose/review dispatch and recovery boundaries."""
from copy import deepcopy
import json

import pytest

from src.content_factory import novel_plaintext_pipeline_v3 as pipeline
from src.content_factory.creative_workflow_roles import RoleResult


def _review(verdict="pass"):
    checks = [{"dimension": key, "checked": True,
               "assessment": f"离线假审查已覆盖{key}，不证明真实质量。", "issues": []}
              for key in pipeline.contracts.REVIEW_DIMENSIONS]
    if verdict == "revise":
        checks[0]["issues"] = [{"severity": "major", "location": "末场",
                                "evidence": "母亲突然到了场内。", "suggestion": "保留缺席事实，重新提交完整稿。"}]
    return {"verdict": verdict, "whole_text_reviewed": True, "summary": "离线假审核结果", "checks": checks}


class Clients:
    def __init__(self, *, revise=False, fault=None, malformed_review=False):
        self.calls, self.revise, self.fault, self.malformed_review = [], revise, fault, malformed_review
        self.writer_count = 0
        self.review_count = 0

    def call(self, role, messages, **parameters):
        assert parameters["structured_schema"] is None
        payload = json.loads(messages[-1]["content"])
        self.calls.append({"role": role, "payload": payload, "parameters": deepcopy(parameters)})
        if role == "writer":
            self.writer_count += 1
            text = ('# 原生稿\r\n背景：她在房间。\r\n\r\n角色：她和经理。\r\n'
                    f'主线与规划：第{self.writer_count}份完整稿。\r\n'
                    '场一：她看着门口，经理说："先坐。"\r\n结尾：她合上确认单。')
        else:
            self.review_count += 1
            text = ("审核报告缺少JSON" if self.malformed_review else
                    json.dumps(_review("revise" if self.revise and self.review_count == 1 else "pass"), ensure_ascii=False))
        model = "MiniMax-M3" if role == "writer" else "deepseek-flash"
        usage = {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20}
        metadata = {"role": role, "provider": "minimax" if role == "writer" else "deepseek",
                    "requested_model": model, "response_model": model,
                    "response_id": f"independent-{len(self.calls)}", "finish_reason": "stop", **usage}
        native = {"id": metadata["response_id"], "model": model, "usage": deepcopy(usage),
                  "choices": [{"finish_reason": "stop", "message": {"content": text, "tool_calls": []}}]}
        if self.fault == "length":
            metadata["finish_reason"] = native["choices"][0]["finish_reason"] = "length"
        elif self.fault == "usage_unknown":
            metadata.pop("total_tokens")
        return RoleResult(text, metadata, native)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    registry = tmp_path / "canonical"
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", registry)
    source = tmp_path / "source.txt"
    source.write_bytes("独立离线测试正文：她原本在房间里。\n\n经理进门说：‘请坐。’母亲未在场。".encode("utf-8"))
    run = tmp_path / "run"
    view = pipeline.prepare(run, source_path=source, title="独立离线语义测试", book_id="offline-independent-book")
    assert view["status"] == "prepared"
    assert registry.is_dir()
    return run, source


def test_native_prose_and_full_review_revision_are_bound_without_format_rewrite(prepared):
    run, _ = prepared
    clients = Clients(revise=True)
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director" and result["human_approved"] is False
    assert [call["role"] for call in clients.calls] == ["writer", "director", "writer", "director"]
    source = pipeline.core._read(run / "SOURCE.json")
    drafts = [path.read_bytes().decode("utf-8") for path in sorted(run.glob("DRAFT_*.md"))]
    assert "\r\n" in drafts[0]
    assert clients.calls[1]["payload"]["source"] == source
    assert clients.calls[1]["payload"]["screenplay"] == drafts[0]
    assert clients.calls[2]["payload"]["previous_draft"] == drafts[0]
    assert clients.calls[2]["payload"]["review"] == _review("revise")
    assert clients.calls[3]["payload"]["source"] == source
    assert clients.calls[3]["payload"]["screenplay"] == drafts[1]
    assert (run / "SCREENPLAY.md").read_bytes() == drafts[1].encode("utf-8")
    assert pipeline.execute(run, clients=clients)["status"] == "text_ready_for_director"
    assert len(clients.calls) == 4


@pytest.mark.parametrize("fault", ["length", "usage_unknown"])
def test_received_fault_retains_original_receipt_and_never_redispatches(prepared, fault):
    run, _ = prepared
    clients = Clients(fault=fault)
    with pytest.raises(RuntimeError):
        pipeline.execute(run, clients=clients)
    receipt = (run / "RESPONSE_001.json").read_bytes()
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "needs_attention" and result["calls_started"] == 1
    assert result["pending_call"] == 1
    assert len(clients.calls) == 1
    assert not list(run.glob("DRAFT_*.md"))
    assert (run / "RESPONSE_001.json").read_bytes() == receipt
    assert result["reported_tokens"] == (20 if fault == "length" else None)


def test_received_writer_cache_recovers_stage_checkpoint_without_second_writer(prepared, monkeypatch):
    run, _ = prepared
    clients = Clients()
    original_save = pipeline.core._save_state
    failed = False
    def fail_once(directory, state):
        nonlocal failed
        if not failed and state.get("stage") == "review_full" and "writer_full" in state.get("active", {}):
            failed = True
            raise OSError("independent checkpoint publication fault")
        return original_save(directory, state)
    monkeypatch.setattr(pipeline.core, "_save_state", fail_once)
    with pytest.raises(OSError):
        pipeline.execute(run, clients=clients)
    assert [call["role"] for call in clients.calls] == ["writer"]
    assert (run / "RESPONSE_001.json").is_file()
    monkeypatch.setattr(pipeline.core, "_save_state", original_save)
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert [call["role"] for call in clients.calls] == ["writer", "director"]
    assert result["reported_tokens"] == 40 and result["calls_started"] == 2


def test_unreadable_review_is_technical_stop_and_does_not_spend_writer_revisions(prepared):
    run, _ = prepared
    clients = Clients(malformed_review=True)
    with pytest.raises(RuntimeError, match="格式不可读"):
        pipeline.execute(run, clients=clients)
    state = pipeline.core._read(run / "state.json")
    assert state["revisions_used"] == 0
    assert state["status"] == "needs_attention"
    assert not (run / "SCREENPLAY.md").exists()
    assert pipeline.execute(run, clients=clients)["status"] == "needs_attention"
    assert [call["role"] for call in clients.calls] == ["writer", "director"]
