"""Offline integration of native prose, whole review, and durable dispatch."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import novel_plaintext_pipeline_v3 as pipe
from src.content_factory.creative_workflow_roles import RoleResult


def review(verdict="pass", issue=None):
    value = {"verdict": verdict, "whole_text_reviewed": True, "summary": "全文已对照来源检查",
             "checks": [{"dimension": dim, "checked": True, "assessment": "核对原文与完整稿，具体内容一致", "issues": []}
                        for dim in pipe.contracts.REVIEW_DIMENSIONS]}
    if issue:
        value["checks"][0]["issues"] = [{"severity": "major", "location": "第三场结尾", "evidence": issue,
                                         "suggestion": "按已获取原文范围重写完整稿"}]
    return value


def result(text, role="writer", *, finish="stop", tokens=100, unknown_usage=False):
    model = "MiniMax-M3" if role == "writer" else "deepseek-flash"
    meta = {"role": role, "provider": "minimax" if role == "writer" else "deepseek", "requested_model": model,
            "response_model": model, "response_id": "fake-" + role + "-" + str(tokens), "finish_reason": finish,
            "output_mode": "content", "prompt_tokens": tokens // 2, "completion_tokens": tokens - tokens // 2,
            "total_tokens": tokens}
    usage = {key: meta[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    if unknown_usage:
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
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", tmp_path / "registry")
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    source = tmp_path / "source.txt"
    source.write_text("第1章\n婚礼现场。新郎醒来，家人责骂；他认出旧树上的刻字。\n\n今日了断。", encoding="utf-8")
    run = tmp_path / "run"
    pipe.prepare(run, source_path=source, title="测试小说", book_id="fake-book")
    return run, source


def test_plaintext_complete_and_native_crlf_are_unchanged(prepared):
    run, _ = prepared
    prose = "背景与角色\r\n主线与改编计划\r\n第一场：婚礼庭院\r\n新郎抬眼：今天，由我自己决定。\r\n结尾。"
    audit = "  ```JSON  \n" + json.dumps(review(), ensure_ascii=False) + "\n``` \n"
    clients = FakeClients([result(prose), result(audit, "director", tokens=120)])
    view = pipe.execute(run, clients=clients)
    assert view["status"] == "text_ready_for_director"
    assert view["known_reported_tokens"] == 220
    assert (run / "SCREENPLAY.md").read_bytes() == prose.encode("utf-8")
    assert clients.calls[0]["parameters"]["structured_schema"] is None
    assert "output_schema" not in json.loads(clients.calls[0]["messages"][-1]["content"])
    assert json.loads(clients.calls[1]["messages"][-1]["content"])["screenplay"] == prose
    assert view["human_approved"] is False and view["automatic_media_submit"] is False
    again = pipe.execute(run, clients=FakeClients([]))
    assert again["status"] == "text_ready_for_director" and again["calls_started"] == 2


def test_semantic_revision_gets_entire_previous_draft_and_review(prepared):
    run, _ = prepared
    initial = "开头。小说没写的断亲结局。"
    revised = "背景、角色、高潮、改编说明。\n婚礼对峙。\n结尾停在原文悬念。"
    failed = review("revise", "未取得后续章节，却编出断亲结局")
    clients = FakeClients([result(initial), result(json.dumps(failed), "director"),
                           result(revised), result(json.dumps(review()), "director")])
    view = pipe.execute(run, clients=clients)
    assert view["status"] == "text_ready_for_director" and view["calls_started"] == 4
    assert view["state"]["revisions_used"] == 1
    payload = json.loads(clients.calls[2]["messages"][-1]["content"])
    assert payload["previous_draft"] == initial and payload["review"] == failed
    assert (run / "DRAFT_001.md").read_text(encoding="utf-8") == initial
    assert (run / "SCREENPLAY.md").read_text(encoding="utf-8") == revised


def test_incomplete_prose_is_sent_to_semantic_reviewer_and_bounded(prepared):
    run, _ = prepared
    clients = FakeClients([item for _ in range(3) for item in
                           (result("只有开头"), result(json.dumps(review("revise", "正文只有开头，没有完整剧情")), "director"))])
    view = pipe.execute(run, clients=clients)
    assert view["status"] == "content_revision_exhausted"
    assert view["calls_started"] == 6 and view["state"]["revisions_used"] == 2
    assert not (run / "SCREENPLAY.md").exists()
    assert pipe.execute(run, clients=FakeClients([]))["calls_started"] == 6


@pytest.mark.parametrize("finish,unknown_usage", [("length", False), ("stop", True)])
def test_truncated_or_unknown_usage_is_preserved_and_never_retried(prepared, finish, unknown_usage):
    run, _ = prepared
    clients = FakeClients([result("已收到但不能放行的正文", finish=finish, unknown_usage=unknown_usage)])
    with pytest.raises(RuntimeError):
        pipe.execute(run, clients=clients)
    view = pipe.inspect(run)
    assert view["status"] == "needs_attention" and view["pending_call"] == 1
    assert view["known_reported_tokens"] == (0 if unknown_usage else 100)
    assert view["reported_tokens"] == (None if unknown_usage else 100)
    assert (run / "RESPONSE_001.json").exists()
    assert pipe.execute(run, clients=FakeClients([]))["calls_started"] == 1


@pytest.mark.parametrize("audit", ["not JSON", json.dumps({"verdict": "pass"}), json.dumps(review("revise"))])
def test_invalid_review_stops_without_rewriting_creative_content(prepared, audit):
    run, _ = prepared
    clients = FakeClients([result("一份原生稿"), result(audit, "director")])
    with pytest.raises(RuntimeError):
        pipe.execute(run, clients=clients)
    view = pipe.inspect(run)
    assert view["status"] == "needs_attention" and view["calls_started"] == 2
    assert view["state"]["revisions_used"] == 0
    assert not (run / "SCREENPLAY.md").exists()


def test_saved_response_checkpoint_crash_is_adopted_without_redispatch(prepared, monkeypatch):
    run, _ = prepared
    real_adopt = pipe._adopt_response
    calls = FakeClients([result("已收到的完整原生稿")])
    monkeypatch.setattr(pipe, "_adopt_response", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(run, clients=calls)
    monkeypatch.setattr(pipe, "_adopt_response", real_adopt)
    resume = FakeClients([result(json.dumps(review()), "director")])
    view = pipe.execute(run, clients=resume)
    assert view["status"] == "text_ready_for_director" and view["calls_started"] == 2
    assert [call["role"] for call in resume.calls] == ["director"]
    assert view["known_reported_tokens"] == 200


def test_unknown_inflight_crash_is_never_redispatched(prepared):
    run, _ = prepared
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(run, clients=FakeClients([KeyboardInterrupt()]))
    resumed = FakeClients([])
    with pytest.raises(RuntimeError, match="未知"):
        pipe.execute(run, clients=resumed)
    assert not resumed.calls and pipe.inspect(run)["pending_call"] == 1


def test_source_mutation_blocks_actual_dispatch(prepared):
    run, source = prepared
    source.write_text("来源已改变", encoding="utf-8")
    clients = FakeClients([])
    with pytest.raises(ValueError, match="冻结文件"):
        pipe.execute(run, clients=clients)
    assert not clients.calls


def test_call_receipt_mutation_is_detected(prepared):
    run, _ = prepared
    pipe.execute(run, clients=FakeClients([result("完整稿"), result(json.dumps(review()), "director")]))
    path = run / "RESPONSE_001.json"
    path.write_bytes(path.read_bytes() + b" ")
    assert pipe.inspect(run)["status"] == "incomplete_artifacts"
    with pytest.raises(ValueError):
        pipe.execute(run, clients=FakeClients([]))


def test_output_mutation_removes_completed_status(prepared):
    run, _ = prepared
    pipe.execute(run, clients=FakeClients([result("完整稿"), result(json.dumps(review()), "director")]))
    (run / "SCREENPLAY.md").write_text("另一个稿", encoding="utf-8")
    assert pipe.inspect(run)["status"] == "incomplete_artifacts"


def test_same_story_cannot_be_prepared_in_second_registry(prepared, tmp_path):
    _, source = prepared
    with pytest.raises(RuntimeError, match="同故事"):
        pipe.prepare(tmp_path / "new-run", source_path=source, title="改名", registry_dir=tmp_path / "another-registry")


def test_late_legacy_checkpoint_blocks_dispatch(prepared, monkeypatch):
    run, _ = prepared
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [{"reason": "新历史停止"}])
    clients = FakeClients([])
    with pytest.raises(RuntimeError, match="历史停止"):
        pipe.execute(run, clients=clients)
    assert not clients.calls


def test_preparation_preview_inspection_are_zero_model(prepared, monkeypatch):
    run, _ = prepared
    monkeypatch.setattr(pipe.CreativeRoleClients, "call", lambda *args, **kwargs: pytest.fail("不应模型调用"))
    assert pipe.preview(run)["remaining_calls"] == 20
    assert pipe.inspect(run)["calls_started"] == 0


def test_authorization_is_mutually_exclusive_with_source(prepared, tmp_path):
    _, source = prepared
    with pytest.raises(ValueError, match="另一来源"):
        pipe.prepare(tmp_path / "new", source_path=source, authorization=tmp_path / "auth.json")


def test_response_model_mismatch_stops_before_review(prepared):
    run, _ = prepared
    bad = result("正文")
    bad.response_payload["model"] = "another-model"
    with pytest.raises(RuntimeError):
        pipe.execute(run, clients=FakeClients([bad]))
    assert pipe.inspect(run)["calls_started"] == 1


def test_token_budget_admission_does_not_truncate_or_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", tmp_path / "registry")
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    source, run = tmp_path / "source.txt", tmp_path / "run"
    source.write_text("来源正文", encoding="utf-8")
    pipe.prepare(run, source_path=source, max_total_tokens=10)
    clients = FakeClients([])
    with pytest.raises(RuntimeError, match="预算"):
        pipe.execute(run, clients=clients)
    assert not clients.calls and pipe.inspect(run)["calls_started"] == 0


def test_pending_request_bytes_are_frozen(prepared):
    run, _ = prepared
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(run, clients=FakeClients([KeyboardInterrupt()]))
    path = run / "REQUEST_001.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="未决请求冻结"):
        pipe.execute(run, clients=FakeClients([]))


def test_real_authorization_readonly_audit_has_14_response_total():
    path = pipe.core.ROOT / "data/novel_adaptation_production/20261017_plaintext_v3/AUTHORIZATION.json"
    if not path.exists():
        pytest.skip("本地生产历史不在仓库测试副本中")
    auth = pipe.core._read(path)
    before = {row["path"]: Path(row["path"]).read_bytes() for row in auth["history_bindings"]}
    audited = pipe._audit_authorization(path, auth["run_dir"])
    assert audited["legacy_totals"] == {"calls_started": 14, "reported_tokens": 228513}
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())
