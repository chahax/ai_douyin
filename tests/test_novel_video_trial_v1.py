from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.content_factory import novel_video_trial_v1 as trial


@pytest.fixture
def setup_trial(tmp_path, monkeypatch):
    original = Path("data/novel_agent_production/20261018_original_trial_v7/run")
    source = tmp_path / "source"
    source.mkdir()
    for name in ("BINDING.json", "PRODUCTION_HANDOFF.json", "SCREENPLAY.md", "OUTPUT_MANIFEST.json"):
        (source / name).write_bytes((original / name).read_bytes())
    monkeypatch.setattr(trial, "REGISTRY", tmp_path / "registry")
    monkeypatch.setattr(trial.runtime, "inspect", lambda run: {"status": "text_ready_for_production", "blockers": []})
    config = trial.seedance.SeedanceConfig("fake", base_url=trial.seedance.ARK_BASE_URL,
                                         model=trial.seedance.ARK_MINI_MODEL, provider="ark_api")
    monkeypatch.setattr(trial, "_config", lambda **kw: config)
    return tmp_path / "run", source, config


class Client:
    def __init__(self, config, *, fail=False, status="running"):
        self.config, self.fail, self.status = config, fail, status
        self.posts, self.gets = [], []

    def create_task(self, payload):
        self.posts.append(payload)
        if self.fail:
            raise TimeoutError("transport outcome unknown")
        return {"id": "original-task"}

    def get_task(self, task_id):
        self.gets.append(task_id)
        return {"id": task_id, "status": self.status,
                "content": {"video_url": "https://example.test/video", "last_frame_url": "https://example.test/tail"}}

    def download_video(self, task, path):
        Path(path).write_bytes(b"fake-video-container")

    def download_last_frame(self, task, path):
        Path(path).write_bytes(b"fake-provider-original-tail")


def test_prepare_is_source_bound_without_post(setup_trial):
    run, source, _ = setup_trial
    result = trial.prepare(run, source_run=source)
    assert result["status"] == "prepared_not_submitted"
    assert not result["claim_exists"]
    prompt = (run / "PROMPT.txt").read_text(encoding="utf-8")
    recipe = trial.core._read(run / "RECIPE.json")
    assert recipe["selected_performance"]["dialogue"] in prompt
    assert recipe["performance_indices"] == [0]
    assert "我没问你这个" not in prompt
    assert "纸票尚未出现" in prompt and "11—15秒" in prompt
    request = trial.core._read(run / "REQUEST.json")
    assert request["duration"] == 15 and request["resolution"] == "720p" and request["ratio"] == "9:16"
    assert len(request["content"]) == 1 and request["generate_audio"] and request["return_last_frame"]


def test_cross_directory_preparations_share_single_admission(setup_trial):
    run, source, config = setup_trial
    second = run.with_name("another")
    trial.prepare(run, source_run=source)
    trial.prepare(second, source_run=source)
    client = Client(config)
    assert trial.submit(run, client=client)["task_id"] == "original-task"
    with pytest.raises(ValueError, match="claim"):
        trial.submit(second, client=client)
    with pytest.raises(ValueError, match="一次"):
        trial.submit(run, client=client)
    assert len(client.posts) == 1


def test_unknown_post_result_stays_permanently_claimed(setup_trial):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    client = Client(config, fail=True)
    with pytest.raises(TimeoutError):
        trial.submit(run, client=client)
    assert trial.inspect(run)["status"] == "submit_outcome_unknown"
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    with pytest.raises(FileNotFoundError):
        trial.query(run, client=client)
    assert len(client.posts) == 1 and client.gets == []


def test_changed_prompt_stops_before_post(setup_trial):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    (run / "PROMPT.txt").write_text("different story", encoding="utf-8")
    client = Client(config)
    with pytest.raises(ValueError, match="冻结文件变化"):
        trial.submit(run, client=client)
    assert client.posts == []


def test_known_native_rejection_records_failure_without_retry(setup_trial):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    client = Client(config)
    def reject(payload):
        client.posts.append(payload)
        raise trial.seedance.SeedanceAPIError("rejected", status_code=400, error_code="InvalidParameter")
    client.create_task = reject
    with pytest.raises(trial.seedance.SeedanceAPIError):
        trial.submit(run, client=client)
    result = trial.inspect(run)
    assert result["status"] == "request_rejected" and result["failure_counter"]["failures_used"] == 1
    assert trial.core._read(run / "SUBMIT_ERROR.json")["http_status"] == 400
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    assert len(client.posts) == 1


def test_invalid_full_native_text_evidence_is_not_admitted(setup_trial, monkeypatch):
    run, source, _ = setup_trial
    monkeypatch.setattr(trial.runtime, "inspect", lambda run: {"status": "incomplete_artifacts", "blockers": ["native altered"]})
    with pytest.raises(ValueError, match="完整核验"):
        trial.prepare(run, source_run=source)


def test_query_only_original_id_and_saved_candidate_pending_user(setup_trial, monkeypatch):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    client = Client(config, status="succeeded")
    trial.submit(run, client=client)
    monkeypatch.setattr(trial, "_metadata", lambda path: {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {"format": "jpeg", "complete": True})
    result = trial.query(run, client=client)
    assert result["content_status"] == "awaiting_human_review" and not result["human_approved"]
    receipt = trial.core._read(run / "receipt.json")
    trial.media_review_policy.validate_source_bindings(receipt)
    assert receipt["native_tail_source"] == "provider_returned_original_last_frame_url"
    assert not receipt["posthoc_frame_extraction"] and not receipt["audio_or_asr_review_performed"]
    trial.query(run, client=client)
    assert len(client.posts) == 1 and client.gets == ["original-task"]
    review = trial.media_review_policy.record_user_media_decision(run / "receipt.json", "approved", "test-only explicit mock approval")
    assert trial.media_review_policy.validate_approved_tail(Path(trial.core._read(run / "receipt.json")["user_decision_source"]))["sha256"] == receipt["last_frame_sha256"]


def test_saved_native_submit_result_recovers_id_without_new_post(setup_trial, monkeypatch):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    client = Client(config)
    save = trial._save
    failed = []
    def crash_once(path, value):
        if value.get("status") == "submitted" and not failed:
            failed.append(True)
            raise OSError("simulated checkpoint rename failure")
        save(path, value)
    monkeypatch.setattr(trial, "_save", crash_once)
    with pytest.raises(OSError):
        trial.submit(run, client=client)
    assert trial.core._read(run / "state.json")["task_id"] is None
    assert trial.query(run, client=client)["task_id"] == "original-task"
    assert len(client.posts) == 1 and client.gets == ["original-task"]


def test_actual_verified_handoff_compiles_without_external_calls():
    source = Path("data/novel_agent_production/20261018_original_trial_v7/run")
    handoff = trial._source(source)
    recipe, prompt = trial.compile_prompt(handoff)
    assert recipe["selected_performance"] == handoff["director"]["segments"][0]["performance"][0]
    assert handoff["director"]["segments"][0]["performance"][0]["dialogue"] in prompt


def test_changed_query_id_is_rejected(setup_trial):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    client = Client(config)
    trial.submit(run, client=client)
    state = trial.core._read(run / "state.json")
    state["task_id"] = "another-task"
    trial._save(run / "state.json", state)
    with pytest.raises(ValueError, match="原始任务ID"):
        trial.query(run, client=client)
    assert client.gets == []


def test_failed_queries_do_not_reset_or_duplicate_story_failures(setup_trial):
    run, source, config = setup_trial
    trial.prepare(run, source_run=source)
    client = Client(config, status="failed")
    trial.submit(run, client=client)
    trial.query(run, client=client)
    result = trial.query(run, client=client)
    assert result["failure_counter"]["failures_used"] == 1
    assert result["failure_counter"]["failed_task_ids"] == ["original-task"]
    assert len(client.posts) == 1


@pytest.mark.parametrize("width,height,audio,good", [(720, 1280, True, True), (1280, 720, True, False), (720, 1280, False, False)])
def test_metadata_requires_portrait_native_audio(monkeypatch, width, height, audio, good):
    streams = [{"codec_type": "video", "width": width, "height": height, "nb_read_packets": "450"}]
    if audio:
        streams.append({"codec_type": "audio", "nb_read_packets": "700"})
    monkeypatch.setattr(trial.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0,
        stdout=json.dumps({"format": {"duration": "15"}, "streams": streams})))
    if good:
        assert trial._metadata("candidate.mp4")["streams"][0]["width"] == 720
    else:
        with pytest.raises(ValueError, match="720"):
            trial._metadata("candidate.mp4")
