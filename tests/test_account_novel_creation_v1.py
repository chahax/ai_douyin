"""Offline integration through the real novel workflow and provider boundary."""
import hashlib
import json

import pytest

from src.content_factory.account_novel_creation_v1 import (
    prepare_account_novel_run, preview_account_novel_run,
    execute_account_novel_run, inspect_account_novel_run,
)
from src.content_factory.account_novel_selection_v1 import discover_books
from src.content_factory.account_novel_workflow_v1 import AccountNovelWorkflow
from src.content_factory.creative_workflow_roles import RoleResult
from tests import test_account_novel_selection_v1 as selection_fixtures
from tests.test_account_novel_selection_v1 import book, NOW
from tests.test_creative_workflow import SOURCE, FakeClients, _answers

profile = selection_fixtures.profile
opportunity = selection_fixtures.opportunity


@pytest.fixture
def prepared(tmp_path, profile, opportunity):
    folder = book(tmp_path / "books", body="小说名称：校园恋爱\n作品简介：未来章节绝密保镖台词\n详情页：https://example.test/book/1\n第1章 初遇\n" + SOURCE)
    run = tmp_path / "run"
    options = {"now": NOW, "duration_seconds": [10, 30], "task_registry": tmp_path / "registry"}
    candidates = discover_books(tmp_path / "books")
    result = prepare_account_novel_run(profile, opportunity, candidates, run, **options)
    assert result["status"] == "prepared"
    return run, folder, candidates, options


def real_runner(clients):
    def run(*, run_dir, bundle, workflow_kwargs):
        return AccountNovelWorkflow(run_dir, clients=clients, **workflow_kwargs).run(bundle)
    return run


def test_prepare_preview_freeze_exact_chapter_body_and_never_send_synopsis(prepared):
    run, folder, _, _ = prepared
    preview = preview_account_novel_run(run, now=NOW)
    payload = preview["material_payload"]
    assert SOURCE in payload["story_source"]
    assert "未来章节绝密保镖台词" not in json.dumps(payload, ensure_ascii=False)
    assert payload["story_source"].startswith("第1章")
    assert preview["workflow_kwargs"]["max_revisions"] == 2
    assert preview["workflow_kwargs"]["retry_unconfirmed_transport"] is False
    assert not (run / "creative").exists()
    assert len(list((run.parent / "registry").glob("*.json"))) == 1


def test_real_workflow_complete_outputs_and_precise_role_payload(prepared):
    run, _, _, _ = prepared
    clients = FakeClients(_answers())
    result = execute_account_novel_run(run, now=NOW, runner=real_runner(clients))
    assert result["status"] == "machine_text_complete"
    assert result["creative_status"] == "media_handoff_pending_capability"
    assert result["creative_state"]["assistant_review_required"] is True
    assert [role for role, _ in clients.calls] == ["writer", "writer", "writer", "writer", "director"]
    assert SOURCE in clients.calls[0][1][-1]["content"]
    assert all("未来章节绝密保镖台词" not in json.dumps(messages, ensure_ascii=False)
               for _, messages in clients.calls)
    assert result["automatic_media_submit"] is False
    assert result["artifacts"]["SCREENPLAY.md"]["bytes"] > 0
    calls = len(clients.calls)
    assert execute_account_novel_run(run, now=NOW, runner=real_runner(clients))["status"] == "machine_text_complete"
    assert len(clients.calls) == calls


def test_prepare_duplicate_inherits_budget_and_rejects_changed_budget(prepared, profile, opportunity):
    run, _, candidates, options = prepared
    prepare_account_novel_run(profile, opportunity, candidates, run, **options)
    with pytest.raises(RuntimeError, match="预算"):
        prepare_account_novel_run(profile, opportunity, candidates, run, **options, max_calls=21)
    with pytest.raises(ValueError, match="两轮"):
        prepare_account_novel_run(profile, opportunity, candidates, run, **options, max_revisions=3)


@pytest.mark.parametrize("filename", ["material.txt", "meta.json", "text_authorization.json"])
def test_original_identity_changes_block_preview(prepared, filename):
    run, folder, _, _ = prepared
    with (folder / filename).open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="改变"):
        preview_account_novel_run(run, now=NOW)


@pytest.mark.parametrize("filename", ["story_source.txt", "model_metadata.json", "account.json", "authorization.json"])
def test_frozen_identity_changes_block_preview(prepared, filename):
    run, _, _, _ = prepared
    with (run / "frozen" / filename).open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="改变"):
        preview_account_novel_run(run, now=NOW)


def test_duplicate_new_directory_cannot_reclaim_same_intent(prepared, profile, opportunity, tmp_path):
    _, _, candidates, options = prepared
    with pytest.raises(RuntimeError, match="逻辑任务"):
        prepare_account_novel_run(profile, opportunity, candidates, tmp_path / "other", **options)


def test_no_materials_can_resume_preparation_in_same_directory(tmp_path, profile, opportunity):
    run = tmp_path / "run"
    options = {"now": NOW, "task_registry": tmp_path / "registry"}
    assert prepare_account_novel_run(profile, opportunity, [], run, **options)["status"] == "needs_materials"
    book(tmp_path / "books", body=SOURCE)
    result = prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run, **options)
    assert result["status"] == "prepared"
    assert (run / "PREPARATION_HISTORY/attempt_001/SELECTION.json").exists()


def test_short_source_failed_preparation_can_resume_and_preserves_evidence(tmp_path, profile, opportunity):
    run = tmp_path / "run"
    options = {"now": NOW, "task_registry": tmp_path / "registry"}
    folder = book(tmp_path / "books", body="很短")
    with pytest.raises(ValueError, match="200"):
        prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run, **options)
    (folder / "material.txt").write_text(SOURCE, encoding="utf-8")
    auth_path = folder / "text_authorization.json"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    auth["source_sha256"] = hashlib.sha256((folder / "material.txt").read_bytes()).hexdigest()
    auth_path.write_text(json.dumps(auth, ensure_ascii=False), encoding="utf-8")
    assert prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run, **options)["status"] == "prepared"
    assert "200" in (run / "PREPARATION_HISTORY/attempt_001/STATUS.json").read_text(encoding="utf-8")


def test_persisted_lock_blocks_dispatch(prepared):
    run, _, _, _ = prepared
    (run / ".account_novel_execution.lock").write_text("{}", encoding="utf-8")
    clients = FakeClients([])
    with pytest.raises(RuntimeError, match="执行锁"):
        execute_account_novel_run(run, now=NOW, runner=real_runner(clients))
    assert clients.calls == []


def test_returned_success_without_saved_work_is_rejected(prepared):
    run, _, _, _ = prepared
    with pytest.raises(RuntimeError, match="持久保存"):
        execute_account_novel_run(run, now=NOW, runner=lambda **_: {"status": "media_handoff_pending_capability"})
    assert inspect_account_novel_run(run)["status"] == "needs_attention"


@pytest.mark.parametrize("tokens", [None, -1, True, 1.5])
def test_unknown_usage_saved_stops_and_resume_never_redispatches(prepared, tokens):
    run, _, _, _ = prepared
    class UnknownUsage(FakeClients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            return RoleResult(result.text, {**result.metadata, "total_tokens": tokens})
    clients = UnknownUsage(_answers())
    with pytest.raises(Exception, match="用量未知"):
        execute_account_novel_run(run, now=NOW, runner=real_runner(clients))
    receipt = json.loads((run / "creative/writer_analysis.json").read_text(encoding="utf-8"))
    assert receipt["response_text"]
    assert receipt["failure"]["code"] == "USAGE_UNKNOWN"
    assert inspect_account_novel_run(run)["creative_state"]["reported_tokens"] is None
    assert len(clients.calls) == 1
    with pytest.raises(Exception):
        execute_account_novel_run(run, now=NOW, runner=real_runner(clients))
    assert len(clients.calls) == 1


def test_tampered_complete_artifact_not_claimed_complete(prepared):
    run, _, _, _ = prepared
    execute_account_novel_run(run, now=NOW, runner=real_runner(FakeClients(_answers())))
    (run / "creative/SCREENPLAY.json").write_text("{}", encoding="utf-8")
    assert inspect_account_novel_run(run)["status"] == "incomplete_artifacts"


def test_validator_runs_under_lock_before_any_dispatch(prepared):
    run, _, _, _ = prepared
    calls = []
    def validator():
        assert (run / ".account_novel_execution.lock").exists()
        calls.append(1)
        raise ValueError("账号已停用")
    with pytest.raises(ValueError, match="停用"):
        execute_account_novel_run(run, now=NOW, validator=validator)
    assert calls == [1]
    assert not (run / "creative").exists()


@pytest.mark.parametrize("key,value", [("max_calls", 100), ("task_registry", "other")])
def test_binding_modification_rejected_by_independent_anchor(prepared, key, value):
    run, _, _, _ = prepared
    path = run / "BINDING.json"
    binding = json.loads(path.read_text(encoding="utf-8"))
    if key == "max_calls":
        binding["budget"][key] = value
    else:
        binding[key] = value
    path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ValueError, match="冻结绑定"):
        preview_account_novel_run(run, now=NOW)


def test_prepare_lock_blocks_concurrent_preparation(tmp_path, profile, opportunity):
    run = tmp_path / "run"
    prepare_account_novel_run(profile, opportunity, [], run, now=NOW)
    (run / ".account_novel_prepare.lock").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="准备锁"):
        prepare_account_novel_run(profile, opportunity, [], run, now=NOW)


def test_default_duration_and_audience_follow_account(tmp_path, profile, opportunity):
    profile.target_audiences = ["校园读者"]
    profile.domain_config.update(min_video_seconds=50, default_video_seconds=80, max_video_seconds=120)
    book(tmp_path / "books", body=SOURCE)
    run = tmp_path / "run"
    prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run,
                              now=NOW, task_registry=tmp_path / "registry")
    preview = preview_account_novel_run(run, now=NOW)
    assert preview["binding"]["duration_seconds"] == [50, 120]
    brief = json.loads((run / "creative_brief.json").read_text(encoding="utf-8"))
    assert "校园读者" in brief["audience"]
    assert brief["duration_policy"] == "strict_range"


def test_original_authorization_changed_midrun_stops_before_next_provider_call(prepared, monkeypatch):
    run, folder, _, _ = prepared
    class Mutate(FakeClients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            with (folder / "text_authorization.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            return result
    clients = Mutate(_answers())
    import src.content_factory.creative_workflow as base
    monkeypatch.setattr(base, "CreativeRoleClients", lambda: clients)
    with pytest.raises(ValueError, match="改变"):
        execute_account_novel_run(run, now=NOW)
    assert len(clients.calls) == 1
    blocked = json.loads((run / "creative/director_brief.json").read_text(encoding="utf-8"))
    assert blocked["status"] == "blocked_before_dispatch"
    assert blocked["provider_dispatch_started"] is False


def test_runtime_endpoint_change_blocks_preview_without_credentials_in_binding(prepared, monkeypatch):
    from src.shared.config import settings
    run, _, _, _ = prepared
    preview = preview_account_novel_run(run, now=NOW)
    assert "api_key" not in json.dumps(preview["binding"]["provider_protocol"]).lower()
    monkeypatch.setattr(settings, "WRITER_AGENT_BASE_URL", "https://changed.example.test/v1")
    with pytest.raises(ValueError, match="模型服务"):
        preview_account_novel_run(run, now=NOW)


@pytest.mark.parametrize("url", ["https://user:secret@example.test/v1", "https://example.test/v1?api_key=secret"])
def test_prepare_never_persists_credential_bearing_endpoint(tmp_path, profile, opportunity, monkeypatch, url):
    from src.shared.config import settings
    monkeypatch.setattr(settings, "WRITER_AGENT_BASE_URL", url)
    book(tmp_path / "books", body=SOURCE)
    run = tmp_path / "run"
    with pytest.raises(ValueError, match="URL"):
        prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run,
                                  now=NOW, task_registry=tmp_path / "registry")
    assert not (run / "BINDING.json").exists()
    assert "secret" not in (run / "STATUS.json").read_text(encoding="utf-8")
