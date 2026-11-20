"""Primary-agent adversarial checks; every provider result is an offline fixture."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import novel_adaptation_contracts_v1 as contracts
from src.content_factory import novel_adaptation_pipeline_v1 as pipeline
from src.content_factory.creative_workflow_roles import RoleResult
from test_novel_adaptation_contracts_v1 import example_context, example_review


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", tmp_path / "canonical")
    source = tmp_path / "fictional_source.txt"
    source.write_bytes(example_context()["source"]["text"].encode("utf-8"))
    run = tmp_path / "run"
    pipeline.prepare(run, source_path=source, title="主审离线夹具", scope="仅夹具片段")
    return run, source


class OfflineClients:
    def __init__(self, *, response_fault=None, first_review_stage=None):
        self.calls = []
        self.response_fault = response_fault
        self.first_review_stage = first_review_stage
        self.reviews = 0

    def call(self, role, messages, **parameters):
        payload = json.loads(messages[-1]["content"])
        stage = "review" if role == "director" else next(
            name for name, schema in contracts.SCHEMAS.items()
            if schema == parameters["structured_schema"])
        self.calls.append({"stage": stage, "payload": deepcopy(payload)})
        if stage == "review":
            value = example_review()
            self.reviews += 1
            if self.first_review_stage and self.reviews == 1:
                value["issues"] = [{"severity": "major", "location": "E4", "evidence": "我现在就去找他。",
                                    "impact": "离线故障注入", "proposal": "回到责任阶段重新完整生成",
                                    "responsible_stage": self.first_review_stage}]
        else:
            value = deepcopy(example_context()[stage])
        text = json.dumps(value, ensure_ascii=False)
        finish = "tool_calls" if role == "writer" else "stop"
        model = "MiniMax-M3" if role == "writer" else "deepseek-flash"
        response_id = f"offline-primary-{len(self.calls)}"
        metadata = {"role": role, "provider": "minimax" if role == "writer" else "deepseek",
                    "requested_model": model, "response_model": model, "response_id": response_id,
                    "prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10,
                    "finish_reason": finish, "output_mode": "tool_call" if role == "writer" else "content"}
        message = {"content": text if role == "director" else None, "tool_calls": []}
        if role == "writer":
            message["tool_calls"] = [{"id": "offline-tool", "type": "function",
                                      "function": {"name": "submit_creative_json", "arguments": text}}]
        native = {"id": response_id, "model": model,
                  "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
                  "choices": [{"finish_reason": finish, "message": message}]}
        if self.response_fault:
            text, metadata, native = self.response_fault(text, metadata, native)
        return RoleResult(text, metadata, native)


def test_primary_full_route_preserves_rewritten_dialogue_and_same_full_review(case):
    run, source = case
    clients = OfflineClients()
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert [row["stage"] for row in clients.calls] == [*contracts.STAGES, "review"]
    review = clients.calls[-1]["payload"]
    assert review["source"]["text"] == source.read_text(encoding="utf-8")
    assert review["screenplay"] == example_context()["screenplay"]
    assert "这是你爸留下的地址。" not in review["source"]["text"]
    assert "这是你爸留下的地址。" in (run / "SCREENPLAY.md").read_text(encoding="utf-8")
    assert not result["human_approved"]
    assert not result["automatic_media_submit"]
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 4


@pytest.mark.parametrize("stage,expected", [
    ("analysis", ["analysis", "adaptation_plan", "screenplay", "review"]),
    ("adaptation_plan", ["adaptation_plan", "screenplay", "review"]),
    ("screenplay", ["screenplay", "review"]),
])
def test_primary_review_routes_to_actual_responsible_stage(case, stage, expected):
    run, _ = case
    clients = OfflineClients(first_review_stage=stage)
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert [row["stage"] for row in clients.calls][4:] == expected
    assert result["revisions_used"] == 1
    repaired = clients.calls[4]["payload"]
    assert repaired["issues"]
    assert sum(key in repaired for key in ("previous_value", "previous_draft")) == 1
    assert "previous_native_response" not in repaired


def truncate(text, meta, native):
    meta["finish_reason"] = native["choices"][0]["finish_reason"] = "length"
    return text, meta, native


def mismatch_text(text, meta, native):
    return text + " ", meta, native


def malformed_usage(text, meta, native):
    native["usage"] = ["not-an-object"]
    return text, meta, native


def malformed_message(text, meta, native):
    native["choices"][0]["message"] = ["not-an-object"]
    return text, meta, native


def missing_usage(text, meta, native):
    meta.pop("total_tokens")
    native["usage"].pop("total_tokens")
    return text, meta, native


@pytest.mark.parametrize("fault", [truncate, mismatch_text, malformed_usage, malformed_message, missing_usage])
def test_primary_bad_envelope_always_saves_native_and_never_replays(case, fault):
    run, _ = case
    clients = OfflineClients(response_fault=fault)
    try:
        pipeline.execute(run, clients=clients)
    except (ValueError, RuntimeError):
        pass
    responses = list(run.glob("RESPONSE_*.json"))
    assert len(responses) == 1, "已收到的原生响应必须保存，校验失败不能丢失证据"
    saved = json.loads(responses[0].read_text(encoding="utf-8"))
    assert saved["response_payload"] is not None
    try:
        pipeline.execute(run, clients=clients)
    except (ValueError, RuntimeError):
        pass
    assert len(clients.calls) == 1
    assert not (run / "OUTPUT_MANIFEST.json").exists()


def test_primary_changed_source_and_delivered_copy_cannot_dispatch_or_stay_complete(case):
    run, source = case
    clients = OfflineClients()
    pipeline.execute(run, clients=clients)
    with (run / "SCREENPLAY.md").open("a", encoding="utf-8") as handle:
        handle.write("伪造交付内容")
    assert pipeline.inspect(run)["status"] == "incomplete_artifacts"
    source.write_text("更换来源", encoding="utf-8")
    with pytest.raises((RuntimeError, ValueError)):
        pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 4


def test_primary_global_registry_rejects_alternative_directory_and_mirror(case, tmp_path):
    _, source = case
    with pytest.raises(RuntimeError, match="同故事"):
        pipeline.prepare(tmp_path / "elsewhere", source_path=source, title="改个标题",
                         scope="同一文本", registry_dir=tmp_path / "different_registry")


def test_primary_acquired_book_id_cannot_be_overridden_to_escape_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", tmp_path / "canonical")
    chapter = tmp_path / "chapter.txt"
    chapter.write_text(example_context()["source"]["text"], encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "source_saved", "source": {
        "book_id": "original-id", "book_name": "测试来源", "chapters": [{"file": str(chapter)}]}}), encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline.prepare(tmp_path / "run", acquisition_receipt=receipt, book_id="other-id")


def test_primary_current_failed_trial_is_preview_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", tmp_path / "canonical")
    root = Path(__file__).resolve().parents[1]
    receipt = root / "data/novel_platform_trials/20261016_v1/ACQUISITION_RESULT_v4.json"
    run = tmp_path / "historical_preview"
    pipeline.prepare(run, acquisition_receipt=receipt)
    result = pipeline.preview(run)
    assert result["status"] == "legacy_dispatch_blocked"
    assert result["dispatch_blocked"]
    assert result["state"]["legacy_calls_started"] == 11
    assert result["state"]["legacy_reported_tokens"] == 180079
    clients = OfflineClients()
    pipeline.execute(run, clients=clients)
    assert not clients.calls
    assert not list(run.glob("REQUEST_*.json"))
