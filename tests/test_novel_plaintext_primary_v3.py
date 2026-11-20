"""Primary review of native-text generation; all service results are fixtures."""
from copy import deepcopy
import json

import pytest

from src.content_factory import novel_plaintext_contracts_v3 as contracts
from src.content_factory import novel_plaintext_pipeline_v3 as pipeline
from src.content_factory.creative_workflow_roles import RoleResult


BODY = ("# 门口的信\r\n\r\n背景：小林站在门口，母亲带来父亲的地址。\r\n"
        "角色：小林想找到父亲，母亲希望把线索交给他。\r\n"
        "主线与高潮：递信带来线索，小林从等待转为出发。\r\n"
        "改编规划：保留递信后出发的因果，间接引述改成自然对白。\r\n"
        "完整剧本：白天，门口。母亲将信递出，小林目光落在信封上。\r\n"
        "母亲：‘这是你爸留下的地址。’\r\n"
        "小林接信，低头读完，抬眼看母亲。母亲停住手，等他的回答。\r\n"
        "小林：‘我现在就去找他。’\r\n"
        "小林将信收进衣袋，转向门外。母亲侧身让路，目送他走出门。\r\n"
        "段尾：小林带着地址出发。\r\n")


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", tmp_path / "registry")
    source = tmp_path / "source.txt"
    source.write_bytes("小林站在门口。母亲把信递给小林，说父亲留下了地址。小林接信后决定出发。".encode("utf-8"))
    run = tmp_path / "run"
    pipeline.prepare(run, source_path=source, title="主审离线小说")
    return run, source


def review(*, revise=False):
    checks = [{"dimension": dimension, "checked": True,
               "assessment": "已检查当前完整稿中的对应内容。", "issues": []}
              for dimension in contracts.REVIEW_DIMENSIONS]
    if revise:
        checks[1]["issues"] = [{"severity": "major", "location": "完整剧本结尾",
                                "evidence": "小林将信收进衣袋", "suggestion": "明确交代出发选择的因果。"}]
    return {"verdict": "revise" if revise else "pass", "whole_text_reviewed": True,
            "summary": "离线语义审查夹具，不代表实际创作质量。", "checks": checks}


class OfflineClients:
    def __init__(self, *, revisions=0, contradiction=False, mutate=None):
        self.calls = []
        self.revisions = revisions
        self.contradiction = contradiction
        self.mutate = mutate

    def call(self, role, messages, **parameters):
        payload = json.loads(messages[-1]["content"])
        self.calls.append({"role": role, "payload": deepcopy(payload), "parameters": deepcopy(parameters)})
        if role == "writer":
            text = BODY
        else:
            value = review(revise=self.revisions > 0 or self.contradiction)
            if self.revisions:
                self.revisions -= 1
            if self.contradiction:
                value["verdict"] = "pass"
            text = "```JSON\r\n" + json.dumps(value, ensure_ascii=False) + "\r\n```"
        model = "MiniMax-M3" if role == "writer" else "deepseek-flash"
        identity = "offline-primary-" + str(len(self.calls))
        usage = {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}
        metadata = {"role": role, "provider": "minimax" if role == "writer" else "deepseek",
                    "requested_model": model, "response_model": model, "response_id": identity,
                    "finish_reason": "stop", "output_mode": "content", **usage}
        native = {"id": identity, "model": model, "usage": usage,
                  "choices": [{"finish_reason": "stop", "message": {"content": text, "tool_calls": []}}]}
        if self.mutate:
            self.mutate(role, metadata, native)
        return RoleResult(text, metadata, native)


def test_native_crlf_and_quote_layout_reach_same_text_review_without_tools(prepared):
    run, source = prepared
    clients = OfflineClients()
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert len(clients.calls) == 2
    assert all(call["parameters"]["structured_schema"] is None for call in clients.calls)
    assert clients.calls[-1]["payload"]["screenplay"] == BODY
    assert clients.calls[-1]["payload"]["source"]["text"] == source.read_bytes().decode("utf-8")
    assert (run / "SCREENPLAY.md").read_bytes() == BODY.encode("utf-8")
    assert not result["human_approved"]
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 2


def test_semantic_feedback_reaches_one_full_replacement_not_a_format_retry(prepared):
    run, _ = prepared
    clients = OfflineClients(revisions=1)
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert [row["role"] for row in clients.calls] == ["writer", "director", "writer", "director"]
    replacement = clients.calls[2]["payload"]
    assert replacement["previous_draft"] == BODY
    assert replacement["review"]["verdict"] == "revise"
    assert "source_refs" not in replacement
    assert result["state"]["revisions_used"] == 1


def test_complete_review_cannot_pass_with_major_content_errors(prepared):
    run, _ = prepared
    clients = OfflineClients(contradiction=True)
    with pytest.raises(RuntimeError):
        pipeline.execute(run, clients=clients)
    assert not (run / "OUTPUT_MANIFEST.json").exists()
    assert len(clients.calls) == 2
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 2


@pytest.mark.parametrize("fault", ["length", "usage"])
def test_truncation_and_unknown_usage_still_preserve_result_and_stop(prepared, fault):
    run, _ = prepared
    def mutate(_role, metadata, native):
        if fault == "length":
            metadata["finish_reason"] = native["choices"][0]["finish_reason"] = "length"
        else:
            metadata.pop("total_tokens")
    clients = OfflineClients(mutate=mutate)
    with pytest.raises(RuntimeError):
        pipeline.execute(run, clients=clients)
    assert (run / "RESPONSE_001.json").exists()
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 1


def test_saved_unadopted_native_response_is_not_dispatched_again(prepared, monkeypatch):
    run, _ = prepared
    actual = pipeline._adopt_response
    class ProcessDeath(BaseException):
        pass
    def interrupt(*_args, **_kwargs):
        raise ProcessDeath()
    clients = OfflineClients()
    monkeypatch.setattr(pipeline, "_adopt_response", interrupt)
    with pytest.raises(ProcessDeath):
        pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 1
    monkeypatch.setattr(pipeline, "_adopt_response", actual)
    assert pipeline.execute(run, clients=clients)["status"] == "text_ready_for_director"
    assert len(clients.calls) == 2


def test_changed_source_before_review_cannot_be_accepted(prepared):
    run, source = prepared
    def mutate(role, _metadata, _native):
        if role == "writer":
            source.write_bytes("更换小说正文".encode("utf-8"))
    clients = OfflineClients(mutate=mutate)
    with pytest.raises(ValueError):
        pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 1
    assert not (run / "OUTPUT_MANIFEST.json").exists()
