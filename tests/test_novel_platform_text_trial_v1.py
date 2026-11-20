import hashlib
import json

import pytest

from scripts import run_novel_platform_text_trial_v1 as trial
from src.content_factory.creative_workflow_roles import RoleResult
from tests.test_creative_workflow import SOURCE, FakeClients, _answers


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def prepared(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    body = "第1章 初遇\n" + SOURCE
    (source_dir / "01.txt").write_bytes(body.encode("utf-8"))
    material = "小说名称：测试小说\n作品简介：后续章节绝密台词\n详情页：https://fanqienovel.com/page/1\n\n" + body
    (source_dir / "material.txt").write_bytes(material.encode("utf-8"))
    write(source_dir / "meta.json", {"book_id": "1", "book_name": "测试小说", "abstract": "后续章节绝密台词"})
    source = {"book_id": "1", "book_name": "测试小说", "book_url": "https://fanqienovel.com/page/1",
              "material_path": str(source_dir / "material.txt"), "chapters": [{"file": str(source_dir / "01.txt"), "title": "第1章 初遇"}]}
    acquisition = tmp_path / "ACQUISITION.json"
    write(acquisition, {"status": "source_saved", "source": source, "verified_detail_book_id": "1",
                        "saved_at_utc": "2026-10-16T14:30:00+00:00", "model_calls": 0})
    authorization = tmp_path / "AUTHORIZATION.json"
    write(authorization, {"schema": "novel_platform_trial_authorization/v1", "date": "2026-10-16",
                         "source_mode": "fanqie_platform_direct_selection", "scope": ["完整剧本创作与必要文本审查"]})
    run = tmp_path / "run"
    result = trial.prepare(acquisition, run, authorization=authorization, task_registry=tmp_path / "registry",
                           duration_seconds=[10, 30])
    assert result["status"] == "prepared"
    return run, acquisition, authorization, source_dir


class NativeClients(FakeClients):
    def call(self, role, messages, **kwargs):
        result = super().call(role, messages, **kwargs)
        return RoleResult(result.text, result.metadata, {"native": "actual_fake_envelope", "ordinal": len(self.calls)})


def test_prepare_and_preview_no_account_or_opportunity_and_no_synopsis(prepared):
    run, _, _, _ = prepared
    info = trial.preview(run)
    assert info["binding"]["budget"] == trial.BUDGET
    payload = info["material_payload"]
    assert "后续章节绝密台词" not in json.dumps(payload, ensure_ascii=False)
    assert payload["story_source"].startswith("第1章")
    assert "account" not in info["binding"] and "opportunity" not in info["binding"]
    assert not (run / "creative").exists()


def test_real_workflow_runs_and_native_envelopes_accounting_and_idempotent(prepared):
    run, _, _, _ = prepared
    clients = NativeClients(_answers())
    result = trial.execute(run, clients=clients)
    assert result["status"] == "machine_text_complete"
    assert result["creative_state"]["reported_tokens"] == 5
    assert result["human_approved"] is False and result["automatic_media_submit"] is False
    assert len(clients.calls) == 5
    responses = sorted((run / "creative").glob("NATIVE_RESPONSE_*.json"))
    assert len(responses) == 5
    assert all(json.loads(path.read_text(encoding="utf-8"))["response_payload"]["native"] == "actual_fake_envelope" for path in responses)
    assert trial.execute(run, clients=clients)["status"] == "machine_text_complete"
    assert len(clients.calls) == 5


@pytest.mark.parametrize("tokens,reason", [(None, "stop"), (2, "length"), (3, None)])
def test_unknown_usage_or_completion_preserves_native_envelope_and_never_retries(prepared, tokens, reason):
    run, _, _, _ = prepared
    class Unknown(NativeClients):
        def call(self, *args, **kwargs):
            result = super().call(*args, **kwargs)
            return RoleResult(result.text, {**result.metadata, "total_tokens": tokens, "finish_reason": reason}, result.response_payload)
    clients = Unknown(_answers())
    with pytest.raises(Exception):
        trial.execute(run, clients=clients)
    receipt = json.loads((run / "creative/NATIVE_RESPONSE_001.json").read_text(encoding="utf-8"))
    assert receipt["response_payload"]["native"] == "actual_fake_envelope"
    with pytest.raises(Exception):
        trial.execute(run, clients=clients)
    assert len(clients.calls) == 1


@pytest.mark.parametrize("source_name", ["material.txt", "meta.json", "01.txt"])
def test_original_source_changes_stop_before_provider(prepared, source_name):
    run, _, _, folder = prepared
    with (folder / source_name).open("ab") as stream:
        stream.write(b" ")
    clients = NativeClients(_answers())
    with pytest.raises(ValueError):
        trial.execute(run, clients=clients)
    assert clients.calls == []


def test_mutation_after_first_response_blocks_next_provider(prepared):
    run, _, authorization, _ = prepared
    class Change(NativeClients):
        def call(self, *args, **kwargs):
            result = super().call(*args, **kwargs)
            with authorization.open("ab") as stream:
                stream.write(b" ")
            return result
    clients = Change(_answers())
    with pytest.raises(ValueError):
        trial.execute(run, clients=clients)
    assert len(clients.calls) == 1
    blocked = json.loads((run / "creative/director_brief.json").read_text(encoding="utf-8"))
    assert blocked["provider_dispatch_started"] is False


def test_duplicate_directory_cannot_reclaim_same_source_and_intent(prepared, tmp_path):
    _, acquisition, authorization, _ = prepared
    with pytest.raises(RuntimeError, match="逻辑任务"):
        trial.prepare(acquisition, tmp_path / "another", authorization=authorization,
                       task_registry=tmp_path / "registry", duration_seconds=[10, 30])


def test_empty_artifact_never_promotes_machine_completion(prepared):
    run, _, _, _ = prepared
    trial.execute(run, clients=NativeClients(_answers()))
    (run / "creative/SCREENPLAY.json").write_bytes(b"")
    assert trial.inspect(run)["status"] == "incomplete_artifacts"


def test_body_identity_matches_selected_span(prepared):
    run, _, _, _ = prepared
    binding, _ = trial.verify(run)
    assert hashlib.sha256((run / "frozen/story_source.txt").read_bytes()).hexdigest() == binding["source_span"]["sha256"]
