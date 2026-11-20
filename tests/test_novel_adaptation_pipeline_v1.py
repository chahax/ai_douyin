"""Offline failure/recovery evidence; never instantiate real service clients."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from src.content_factory import novel_adaptation_pipeline_v1 as pipeline
from src.content_factory.creative_workflow_roles import RoleResult

_spec = importlib.util.spec_from_file_location("adaptation_contract_fixtures", Path(__file__).with_name("test_novel_adaptation_contracts_v1.py"))
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(pipeline, "ROOT", project)
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", project / "registry")


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "chapter.txt"
    source.write_bytes(_fixtures.example_context()["source"]["text"].encode("utf-8"))
    run = tmp_path / "run"
    assert pipeline.prepare(run, source_path=source, title="离线小说", book_id="fake-book")["status"] == "prepared"
    return run, source


class FakeClients:
    def __init__(self, mutate=None, review_failure=None):
        self.calls = []
        self.mutate = mutate
        self.review_failure = review_failure
        self.reviews = 0

    def call(self, role, messages, **parameters):
        payload = json.loads(messages[-1]["content"])
        stage = "review" if role == "director" else next(
            key for key, schema in pipeline.contracts.SCHEMAS.items() if schema == parameters["structured_schema"])
        value = _fixtures.example_review() if stage == "review" else deepcopy(_fixtures.example_context()[stage])
        self.calls.append({"role": role, "stage": stage, "payload": deepcopy(payload), "parameters": deepcopy(parameters)})
        if stage == "review":
            self.reviews += 1
            if self.review_failure and self.reviews == 1:
                target = self.review_failure
                value["issues"] = [{"severity": "major", "location": target,
                    "evidence": "找到父亲" if target == "analysis" else "这是你爸留下的地址。",
                    "impact": "离线故障：主线依据不足", "proposal": "按原文完整返修", "responsible_stage": target}]
        if self.mutate:
            value = self.mutate(stage, value, len(self.calls))
        return self.envelope(role, value, len(self.calls))

    @staticmethod
    def envelope(role, value, ordinal):
        protocol = pipeline._protocol()[role]
        text = json.dumps(value, ensure_ascii=False)
        reason = "tool_calls" if role == "writer" else "stop"
        usage = {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20}
        metadata = {"role": role, "provider": protocol["provider"], "requested_model": protocol["model"],
                    "response_model": protocol["model"], "response_id": f"fake-{ordinal}",
                    "finish_reason": reason, "output_mode": "tool_call" if role == "writer" else "content", **usage}
        message = {"content": None if role == "writer" else text, "tool_calls": []}
        if role == "writer":
            message["tool_calls"] = [{"id": "tool-fake", "type": "function", "function": {
                "name": "submit_creative_json", "arguments": text}}]
        native = {"id": metadata["response_id"], "model": metadata["response_model"], "usage": usage,
                  "choices": [{"finish_reason": reason, "message": message}]}
        return RoleResult(text, metadata, native)


def test_full_route_and_completed_reentry_never_dispatches_twice(prepared):
    run, _ = prepared
    clients = FakeClients()
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert result["calls_started"] == 4 and result["reported_tokens"] == 80
    assert result["human_approved"] is False and result["automatic_media_submit"] is False
    assert not result["blockers"]
    assert len(result["artifacts"]) == 6
    assert [row["stage"] for row in clients.calls] == ["analysis", "adaptation_plan", "screenplay", "review"]
    assert clients.calls[-1]["payload"]["screenplay"] == pipeline._read(run / "SCREENPLAY.json")
    assert pipeline.execute(run, clients=clients)["status"] == "text_ready_for_director"
    assert len(clients.calls) == 4
    assert (run / "SCREENPLAY.md").read_text(encoding="utf-8") == pipeline.contracts.render_screenplay(pipeline._read(run / "SCREENPLAY.json"))


def test_prepare_preview_are_offline_and_source_identity_is_program_owned(prepared, monkeypatch):
    run, _ = prepared
    monkeypatch.setattr(pipeline, "CreativeRoleClients", lambda: pytest.fail("offline inspection constructed client"))
    view = pipeline.preview(run)
    assert view["source"]["full_source_sha256"] == view["source"]["excerpt_sha256"]
    assert view["source"]["binding_id"]
    assert view["calls_started"] == 0


@pytest.mark.parametrize("target,sequence", [
    ("screenplay", ["analysis", "adaptation_plan", "screenplay", "review", "screenplay", "review"]),
    ("analysis", ["analysis", "adaptation_plan", "screenplay", "review", "analysis", "adaptation_plan", "screenplay", "review"]),
])
def test_semantic_review_repair_goes_to_responsible_stage(prepared, target, sequence):
    run, _ = prepared
    clients = FakeClients(review_failure=target)
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director" and result["revisions_used"] == 1
    assert [row["stage"] for row in clients.calls] == sequence
    repair = next(row for row in clients.calls if row["payload"].get("previous_value") is not None)
    assert repair["stage"] == target
    assert repair["payload"]["issues"] and "previous_native_response" not in repair["payload"]
    assert "previous_draft" not in repair["payload"]


def test_aggregated_content_failures_have_global_two_repair_limit(prepared):
    run, _ = prepared
    def invalid(stage, value, _):
        if stage == "screenplay":
            value["duration_seconds"] = 100
            value["scenes"][0]["events"][1]["character_states"].pop()
        return value
    clients = FakeClients(mutate=invalid)
    result = pipeline.execute(run, clients=clients)
    assert result["status"] == "content_revision_exhausted" and result["revisions_used"] == 2
    assert [row["stage"] for row in clients.calls].count("screenplay") == 3
    issues = clients.calls[-1]["payload"]["issues"]
    assert {"DURATION_SUM", "PRESENT_STATE_COVERAGE"} <= {row["code"] for row in issues}
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 5


@pytest.mark.parametrize("fault", ["length", "usage_missing", "usage_sum", "native_mismatch", "model", "missing_tool", "bad_usage_type", "bad_message_type", "bad_tools_type"])
def test_response_faults_preserve_native_evidence_and_never_retry(prepared, fault):
    run, _ = prepared
    class Fault(FakeClients):
        def call(self, *args, **kwargs):
            result = super().call(*args, **kwargs)
            meta, native = deepcopy(result.metadata), deepcopy(result.response_payload)
            if fault == "length":
                meta["finish_reason"] = native["choices"][0]["finish_reason"] = "length"
            elif fault == "usage_missing":
                meta.pop("prompt_tokens")
            elif fault == "usage_sum":
                meta["total_tokens"] = native["usage"]["total_tokens"] = 99
            elif fault == "native_mismatch":
                native["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{}"
            elif fault == "model":
                meta["response_model"] = native["model"] = "other-model"
            elif fault == "missing_tool":
                native["choices"][0]["message"]["tool_calls"] = []
            elif fault == "bad_usage_type":
                native["usage"] = [1]
            elif fault == "bad_message_type":
                native["choices"][0]["message"] = [1]
            else:
                native["choices"][0]["message"]["tool_calls"] = [3]
            return RoleResult(result.text, meta, native)
    clients = Fault()
    with pytest.raises(RuntimeError):
        pipeline.execute(run, clients=clients)
    response = pipeline._read(run / "RESPONSE_001.json")
    assert response["status"] == "response_rejected" and "response_payload" in response
    assert pipeline.inspect(run)["dispatch_blocked"]
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 1


def test_source_tamper_blocks_before_first_call(prepared):
    run, source = prepared
    source.write_bytes(b"changed")
    clients = FakeClients()
    with pytest.raises(ValueError):
        pipeline.execute(run, clients=clients)
    assert not clients.calls


def test_state_flip_cannot_create_false_completion(prepared):
    run, _ = prepared
    state = pipeline._read(run / "state.json")
    state["status"] = "text_ready_for_director"
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert pipeline.inspect(run)["status"] == "incomplete_artifacts"
    clients = FakeClients()
    with pytest.raises(ValueError):
        pipeline.execute(run, clients=clients)
    assert not clients.calls


@pytest.mark.parametrize("filename", ["SCREENPLAY.md", "SCREENPLAY.json", "FULL_TEXT_REVIEW.json", "OUTPUT_MANIFEST.json", "DIRECTOR_HANDOFF.json"])
def test_completion_inspection_revalidates_every_deliverable(prepared, filename):
    run, _ = prepared
    clients = FakeClients()
    assert pipeline.execute(run, clients=clients)["status"] == "text_ready_for_director"
    with (run / filename).open("ab") as stream:
        stream.write(b" ")
    assert pipeline.inspect(run)["status"] == "incomplete_artifacts"
    pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 4


def test_unique_story_registry_survives_changed_registry_option(prepared, tmp_path):
    _, source = prepared
    with pytest.raises(RuntimeError, match="同故事"):
        pipeline.prepare(tmp_path / "second", source_path=source, title="different", registry_dir=tmp_path / "new_registry")


def test_existing_execution_lock_does_not_unlock_another_owner(prepared):
    run, _ = prepared
    pipeline._write(run / ".execution.lock", {"owner": "other"})
    clients = FakeClients()
    with pytest.raises(FileExistsError):
        pipeline.execute(run, clients=clients)
    assert pipeline._read(run / ".execution.lock")["owner"] == "other" and not clients.calls


def test_saved_complete_response_is_consumed_after_validation_interruption(prepared, monkeypatch):
    run, _ = prepared
    real = pipeline.contracts.validate_stage
    class SimulatedProcessDeath(BaseException):
        pass
    def die(*_args, **_kwargs):
        raise SimulatedProcessDeath()
    monkeypatch.setattr(pipeline.contracts, "validate_stage", die)
    clients = FakeClients()
    with pytest.raises(SimulatedProcessDeath):
        pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 1 and pipeline._read(run / "state.json")["pending_call"] is None
    monkeypatch.setattr(pipeline.contracts, "validate_stage", real)
    assert pipeline.execute(run, clients=clients)["status"] == "text_ready_for_director"
    assert len(clients.calls) == 4


def test_partial_deliverables_resume_without_recreating_review(prepared, monkeypatch):
    run, _ = prepared
    real = pipeline._ensure
    class SimulatedProcessDeath(BaseException):
        pass
    def fail(path, value):
        if Path(path).name == "SCREENPLAY.json":
            raise SimulatedProcessDeath()
        return real(path, value)
    monkeypatch.setattr(pipeline, "_ensure", fail)
    clients = FakeClients()
    with pytest.raises(SimulatedProcessDeath):
        pipeline.execute(run, clients=clients)
    assert len(clients.calls) == 4 and (run / "ANALYSIS.json").exists()
    monkeypatch.setattr(pipeline, "_ensure", real)
    assert pipeline.execute(run, clients=clients)["status"] == "text_ready_for_director"
    assert len(clients.calls) == 4


def test_pending_request_stops_even_without_response(prepared, monkeypatch):
    run, _ = prepared
    class ProcessDeath(BaseException):
        pass
    class Dies(FakeClients):
        def call(self, *args, **kwargs):
            self.calls.append("pending")
            raise ProcessDeath()
    clients = Dies()
    with pytest.raises(ProcessDeath):
        pipeline.execute(run, clients=clients)
    assert pipeline.execute(run, clients=clients)["dispatch_blocked"]
    assert clients.calls == ["pending"]


def test_legacy_checkpoint_blocks_without_parent_or_book_id(tmp_path):
    trial = pipeline.ROOT / "data/novel_platform_trials/prior"
    trial.mkdir(parents=True)
    source = trial / "chapter.txt"
    source.write_bytes(_fixtures.example_context()["source"]["text"].encode("utf-8"))
    pipeline._write(trial / "FINAL_TRIAL_CHECKPOINT.json", {
        "book_id": "old", "book_name": "old", "status": "stopped_response_truncated", "calls_started": 11,
        "known_reported_tokens": 180079, "new_writer_requests_allowed_without_new_scope": False})
    run = tmp_path / "legacy_preview"
    result = pipeline.prepare(run, source_path=source)
    assert result["status"] == "legacy_dispatch_blocked"
    assert result["state"]["legacy_reported_tokens"] == 180079
    clients = FakeClients()
    assert pipeline.execute(run, clients=clients)["status"] == "legacy_dispatch_blocked"
    assert not clients.calls


def test_copied_selected_excerpt_cannot_escape_legacy_stop(tmp_path):
    trial = pipeline.ROOT / "data/novel_platform_trials/prior"
    trial.mkdir(parents=True)
    selected = "小说选段中的真实人物与事件不能改目录重领。" * 30
    pipeline._write(trial / "FINAL_TRIAL_CHECKPOINT.json", {
        "book_id": "old", "calls_started": 11, "known_reported_tokens": 180079,
        "new_writer_requests_allowed_without_new_scope": False})
    pipeline._write(trial / "text_run/creative/SELECTED_SOURCE.json", {"text": selected})
    copied = tmp_path / "renamed.txt"
    copied.write_bytes(selected[20:-20].encode("utf-8"))
    result = pipeline.prepare(tmp_path / "renamed_run", source_path=copied, title="换标题")
    assert result["status"] == "legacy_dispatch_blocked"
    clients = FakeClients()
    pipeline.execute(tmp_path / "renamed_run", clients=clients)
    assert not clients.calls


def test_receipt_uses_real_chapters_not_synopsis_and_binds_metadata(tmp_path):
    chapter, metadata, receipt = tmp_path / "c.txt", tmp_path / "meta.json", tmp_path / "receipt.json"
    chapter.write_bytes(_fixtures.example_context()["source"]["text"].encode("utf-8"))
    pipeline._write(metadata, {"book_id": "fake"})
    row = {"status": "source_saved", "source": {"book_id": "fake", "book_name": "test", "chapters": [
        {"path": str(chapter), "sha256": pipeline._binding(chapter)["sha256"]}], "material_path": "DO_NOT_READ",
        "metadata_path": str(metadata), "metadata_sha256": pipeline._binding(metadata)["sha256"]}}
    pipeline._write(receipt, row)
    with pytest.raises(ValueError, match="book_id"):
        pipeline.prepare(tmp_path / "wrong", acquisition_receipt=receipt, book_id="other")
    run = tmp_path / "receipt_run"
    result = pipeline.prepare(run, acquisition_receipt=receipt, scope={"acquired_chapters": 999, "scope_note": "全书"})
    assert result["status"] == "prepared"
    assert result["source"]["scope"]["acquired_chapters"] == 1
    assert "非整本" in result["source"]["scope"]["scope_note"]
    assert result["source"]["scope"]["adaptation_scope"]["acquired_chapters"] == 999
    metadata.write_text("{}", encoding="utf-8")
    assert pipeline.inspect(run)["status"] == "evidence_invalid"


def test_receipt_project_relative_data_paths_have_one_unambiguous_base(tmp_path):
    chapter = pipeline.ROOT / "data/books/chapter.txt"
    chapter.parent.mkdir(parents=True)
    chapter.write_bytes(_fixtures.example_context()["source"]["text"].encode("utf-8"))
    receipt = tmp_path / "elsewhere/receipt.json"
    pipeline._write(receipt, {"status": "source_saved", "source": {
        "book_id": "relative", "chapters": [{"file": "data/books/chapter.txt"}]}})
    assert pipeline.prepare(tmp_path / "relative_run", acquisition_receipt=receipt)["status"] == "prepared"
    with pytest.raises(ValueError, match="越出"):
        pipeline._receipt_file("data/../../outside.txt", receipt)


@pytest.mark.parametrize("field,value", [("WRITER_AGENT_PROVIDER", "other"),
    ("WRITER_AGENT_BASE_URL", "https://user:secret@example.com/v1"),
    ("DIRECTOR_AGENT_BASE_URL", "https://example.com/v1?token=secret")])
def test_unsafe_provider_configuration_is_not_frozen(prepared, monkeypatch, field, value):
    run, _ = prepared
    monkeypatch.setattr(pipeline.settings, field, value)
    clients = FakeClients()
    with pytest.raises(ValueError):
        pipeline.execute(run, clients=clients)
    assert not clients.calls
    assert "secret" not in (run / "BINDING.json").read_text(encoding="utf-8")
