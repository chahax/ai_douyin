from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.content_factory import compact_ferry_video_trial_v2 as trial


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    source, registry, run = tmp_path / "source", tmp_path / "registry", tmp_path / "run"
    source.mkdir()
    monkeypatch.setattr(trial, "SOURCE_ROOT", source)
    monkeypatch.setattr(trial, "REGISTRY", registry)
    counter = registry / ("story_" + trial.SOURCE_BINDING + ".json")
    write(counter, dict(schema="novel_video_trial/v1", source_binding=trial.SOURCE_BINDING,
        failure_limit=10, failures_used=2, failed_task_ids=["old-provider-failure", "old-user-rejected"]))
    config = trial.seedance.SeedanceConfig("offline", base_url=trial.seedance.ARK_BASE_URL,
        model=trial.seedance.ARK_MINI_MODEL, provider="ark_api")
    monkeypatch.setattr(trial, "_config", lambda **kwargs: config)
    (source / "FULL_SCREENPLAY.md").write_text("完整新标准助手编辑候选，尚非模型通过稿", encoding="utf-8")
    segment = dict(id="S01", duration_seconds=7, service_duration_seconds=7)
    write(source / "SEGMENTS.json", dict(schema="assistant_editorial_full_screenplay_segments/v4",
        source_binding=trial.SOURCE_BINDING, segments=[segment],
        primary_review_status="editorial_reviewed_not_model_accepted", new_minimax_generation=False,
        new_deepseek_acceptance=False))
    prompt = "7秒，女儿说房间找好了，父亲取票并回答票买好了。"
    (source / "S01.PROMPT.txt").write_text(prompt, encoding="utf-8")
    profile = trial.timing.profile()
    write(source / "TIMING_REFERENCE_PROFILE.json", profile)
    write(source / "SDK_REQUEST_PREVIEWS.json", dict(source=trial.core._binding(source / "SEGMENTS.json"),
        profile_sha256=profile["sha256"], model_acceptance=False, requests=[dict(segment_id="S01",
        prompt_file=trial.core._binding(source / "S01.PROMPT.txt"), payload=trial._payload(prompt))]))
    write(source / "PREVIEW_VALIDATION.json", dict(profile_sha256=profile["sha256"],
        sdk_previews_match_selected_duration_and_ordered_actions=True,
        production_handoff_ready=False, human_content_approved=False,
        bound_files=[trial.core._binding(source / name) for name in
        ("FULL_SCREENPLAY.md", "SEGMENTS.json", "TIMING_REFERENCE_PROFILE.json", "SDK_REQUEST_PREVIEWS.json")]))
    make_inputs(run)
    return run, counter, config


def make_inputs(run):
    first = trial.core._read(trial.SOURCE_ROOT / "SEGMENTS.json")["segments"][0]
    write(run / "FIRST_SEGMENT.json", dict(source_binding=trial.SOURCE_BINDING,
        authored_by="primary_assistant", segment=first,
        selection_status="assistant_editorial_timing_v2_candidate_not_new_model_acceptance"))
    write(run / "AUTHORIZATION.json", dict(source_binding=trial.SOURCE_BINDING, **trial.AUTHORIZATION))
    (run / "PROMPT.txt").write_text((trial.SOURCE_ROOT / "S01.PROMPT.txt").read_text(encoding="utf-8"), encoding="utf-8")


class Client:
    def __init__(self, config, *, status="running", post_error=None):
        self.config, self.status, self.post_error = config, status, post_error
        self.posts, self.gets, self.downloads = [], [], []
        self.fail_get_once = False
        self.fail_tail_once = False

    def create_task(self, payload):
        self.posts.append(payload)
        if self.post_error:
            raise self.post_error
        return {"id": "compact-original-task"}

    def get_task(self, task_id):
        self.gets.append(task_id)
        if self.fail_get_once:
            self.fail_get_once = False
            raise TimeoutError("GET only failed")
        return dict(id=task_id, status=self.status, usage={"total_tokens": 42},
            content=dict(video_url="https://example.test/video", last_frame_url="https://example.test/tail"))

    def download_video(self, task, path):
        self.downloads.append("video")
        Path(path).write_bytes(b"offline-video-container")

    def download_last_frame(self, task, path):
        self.downloads.append("tail")
        if self.fail_tail_once:
            self.fail_tail_once = False
            raise TimeoutError("download interrupted")
        Path(path).write_bytes(b"offline-provider-original-tail")


def test_prepare_compiles_seven_seconds_text_only_and_keeps_old_counter(prepared_inputs):
    run, counter, config = prepared_inputs
    original = counter.read_bytes()
    result = trial.prepare(run)
    assert result["status"] == "prepared_not_submitted" and result["failures"] == 2
    payload = trial.core._read(run / "REQUEST.json")
    assert payload["duration"] == 7 and payload["resolution"] == "720p" and payload["ratio"] == "9:16"
    assert payload["generate_audio"] and payload["return_last_frame"]
    assert payload["content"] == [{"type": "text", "text": (run / "PROMPT.txt").read_text(encoding="utf-8")}]
    assert "assistant_editorial_timing_v2_candidate_not_new_model_acceptance" in result["text_status"]
    assert counter.read_bytes() == original and not result["claim_exists"]


def test_duplicate_posts_blocked_across_directories(prepared_inputs):
    run, counter, config = prepared_inputs
    other = run.with_name("other")
    make_inputs(other)
    trial.prepare(run)
    trial.prepare(other)
    client = Client(config)
    trial.submit(run, client=client)
    with pytest.raises(ValueError, match="一次POST"):
        trial.submit(run, client=client)
    with pytest.raises(ValueError, match="claim"):
        trial.submit(other, client=client)
    assert len(client.posts) == 1 and client.gets == []


def test_unknown_post_retains_claim_and_stops_without_fake_failure(prepared_inputs):
    run, counter, config = prepared_inputs
    original = counter.read_bytes()
    trial.prepare(run)
    client = Client(config, post_error=TimeoutError("unknown POST"))
    with pytest.raises(TimeoutError):
        trial.submit(run, client=client)
    assert trial.inspect(run)["status"] == "submit_outcome_unknown"
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    with pytest.raises(FileNotFoundError):
        trial.query(run, client=client)
    error = trial.core._read(run / "SUBMIT_ERROR.json")
    assert error["usage"] is None and error["usage_known"] is False
    assert trial.inspect(run)["failures"] == 2 and counter.read_bytes() == original
    assert len(client.posts) == 1 and client.gets == []


@pytest.mark.parametrize("name", ["PROMPT.txt", "AUTHORIZATION.json", "FIRST_SEGMENT.json", "REQUEST.json"])
def test_changed_run_binding_prevents_post(prepared_inputs, name):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    path = run / name
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    client = Client(config)
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    assert client.posts == []


@pytest.mark.parametrize("name", ["FULL_SCREENPLAY.md", "SEGMENTS.json", "TIMING_REFERENCE_PROFILE.json", "PREVIEW_VALIDATION.json", "SDK_REQUEST_PREVIEWS.json"])
def test_changed_full_source_prevents_post(prepared_inputs, name):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    path = trial.SOURCE_ROOT / name
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    client = Client(config)
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    assert client.posts == []


def test_changed_historical_counter_blocks_and_is_not_rewritten(prepared_inputs):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    value = trial.core._read(counter)
    value["failures_used"] = 0
    write(counter, value)
    changed = counter.read_bytes()
    client = Client(config)
    with pytest.raises(ValueError, match="冻结文件变化"):
        trial.submit(run, client=client)
    assert counter.read_bytes() == changed and client.posts == []


def test_incomplete_authorization_is_rejected(prepared_inputs):
    run, counter, config = prepared_inputs
    auth = dict(source_binding=trial.SOURCE_BINDING, **trial.AUTHORIZATION)
    auth["max_new_submissions"] = True
    write(run / "AUTHORIZATION.json", auth)
    with pytest.raises(ValueError, match="授权"):
        trial.prepare(run)


def test_http_rejection_is_counted_once_in_new_ledger(prepared_inputs):
    run, counter, config = prepared_inputs
    original = counter.read_bytes()
    trial.prepare(run)
    client = Client(config, post_error=trial.seedance.SeedanceAPIError("rejected", status_code=400, error_code="InvalidParameter"))
    with pytest.raises(trial.seedance.SeedanceAPIError):
        trial.submit(run, client=client)
    assert trial.inspect(run)["status"] == "request_rejected"
    assert trial.inspect(run)["failures"] == 3
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    assert len(client.posts) == 1 and counter.read_bytes() == original


def test_known_terminal_failure_is_idempotent_and_keeps_legacy_bytes(prepared_inputs):
    run, counter, config = prepared_inputs
    original = counter.read_bytes()
    trial.prepare(run)
    client = Client(config, status="failed")
    trial.submit(run, client=client)
    trial.query(run, client=client)
    result = trial.query(run, client=client)
    events = trial.core._read(trial._paths()[3])
    assert result["failures"] == 3 and events["new_failures"] == 1
    assert len(client.posts) == 1 and client.gets == ["compact-original-task"] * 2
    assert counter.read_bytes() == original


def test_native_submit_response_recovers_checkpoint_using_get_only(prepared_inputs, monkeypatch):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    client = Client(config)
    original_save = trial._save
    failed = []
    def crash_once(path, value):
        if value.get("status") == "submitted" and not failed:
            failed.append(True)
            raise OSError("checkpoint failed after native ID saved")
        return original_save(path, value)
    monkeypatch.setattr(trial, "_save", crash_once)
    with pytest.raises(OSError):
        trial.submit(run, client=client)
    assert trial.core._read(run / "state.json")["task_id"] is None
    result = trial.query(run, client=client)
    assert result["task_id"] == "compact-original-task"
    assert len(client.posts) == 1 and client.gets == ["compact-original-task"]


def test_get_failure_can_query_original_id_again(prepared_inputs):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    client = Client(config)
    trial.submit(run, client=client)
    client.fail_get_once = True
    with pytest.raises(TimeoutError):
        trial.query(run, client=client)
    trial.query(run, client=client)
    assert len(client.posts) == 1 and client.gets == ["compact-original-task"] * 2


def test_changed_task_id_blocks_get(prepared_inputs):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    client = Client(config)
    trial.submit(run, client=client)
    state = trial.core._read(run / "state.json")
    state["task_id"] = "another-task"
    trial._save(run / "state.json", state)
    with pytest.raises(ValueError, match="原始任务ID"):
        trial.query(run, client=client)
    assert client.gets == []


def test_interrupted_download_resumes_same_task_and_awaits_human(prepared_inputs, monkeypatch):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    client = Client(config, status="succeeded")
    trial.submit(run, client=client)
    client.fail_tail_once = True
    monkeypatch.setattr(trial, "_metadata", lambda path: {"packet_check": True})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {"format": "jpeg", "pixel_decoding": False})
    with pytest.raises(TimeoutError):
        trial.query(run, client=client)
    result = trial.query(run, client=client)
    assert result["content_status"] == "awaiting_human_review" and not result["human_approved"]
    assert client.downloads == ["video", "tail", "tail"] and len(client.posts) == 1
    receipt = trial.core._read(run / "receipt.json")
    assert receipt["native_tail_source"] == "provider_returned_original_last_frame_url"
    assert receipt["content_inspection_performed"] is False and receipt["audio_or_asr_review_performed"] is False
    trial.media_review_policy.validate_source_bindings(receipt)
    trial.query(run, client=client)
    assert len(client.gets) == 2


def test_changed_saved_media_is_not_reported_as_valid(prepared_inputs, monkeypatch):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    client = Client(config, status="succeeded")
    trial.submit(run, client=client)
    monkeypatch.setattr(trial, "_metadata", lambda path: {})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {})
    trial.query(run, client=client)
    (run / "S01.mp4").write_bytes(b"changed-video")
    assert trial.inspect(run)["status"] == "evidence_invalid"


@pytest.mark.parametrize("key,value", [("status", "passed"), ("content_status", "passed"),
    ("human_approved", True), ("task_id", "other-task"), ("request_sha256", "changed")])
def test_receipt_status_or_identity_tampering_is_rejected(prepared_inputs, monkeypatch, key, value):
    run, counter, config = prepared_inputs
    trial.prepare(run)
    client = Client(config, status="succeeded")
    trial.submit(run, client=client)
    monkeypatch.setattr(trial, "_metadata", lambda path: {})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {})
    trial.query(run, client=client)
    receipt = trial.core._read(run / "receipt.json")
    receipt[key] = value
    trial._save(run / "receipt.json", receipt)
    assert trial.inspect(run)["status"] == "evidence_invalid"


@pytest.mark.parametrize("duration,width,height,audio,packets,good", [
    (7,720,1280,True,True,True), (15,720,1280,True,True,False),
    (10,1280,720,True,True,False), (10,720,1280,False,True,False),
    (10,720,1280,True,False,False),
])
def test_metadata_uses_seven_second_portrait_audio_packet_contract(monkeypatch, duration, width, height, audio, packets, good):
    streams = [dict(codec_type="video", width=width, height=height, nb_read_packets="200" if packets else "0")]
    if audio:
        streams.append(dict(codec_type="audio", nb_read_packets="400"))
    seen = []
    def probe(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(format=dict(duration=str(duration)), streams=streams)))
    monkeypatch.setattr(trial.subprocess, "run", probe)
    if good:
        assert trial._metadata("offline.mp4")["streams"]
    else:
        with pytest.raises(ValueError, match="720"):
            trial._metadata("offline.mp4")
    assert "-count_packets" in seen[0] and "-show_frames" not in seen[0]


def test_prepare_never_constructs_http_transport(prepared_inputs, monkeypatch):
    run, _, _ = prepared_inputs
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP transport must not be constructed for prepare")
    monkeypatch.setattr(trial.seedance.SeedanceClient, "__init__", forbidden)
    assert trial.prepare(run)["status"] == "prepared_not_submitted"


@pytest.mark.parametrize("change", ["different_prompt", "different_segment", "v1_profile"])
def test_fresh_input_mismatch_stops_before_prepare(prepared_inputs, change):
    run, _, _ = prepared_inputs
    if change == "different_prompt":
        (run / "PROMPT.txt").write_text("different story", encoding="utf-8")
    elif change == "different_segment":
        value = trial.core._read(run / "FIRST_SEGMENT.json")
        value["segment"]["duration_seconds"] = 8
        write(run / "FIRST_SEGMENT.json", value)
    else:
        profile = trial.core._read(trial.SOURCE_ROOT / "TIMING_REFERENCE_PROFILE.json")
        profile["version"] = "performance_timing_reference/v1"
        write(trial.SOURCE_ROOT / "TIMING_REFERENCE_PROFILE.json", profile)
    with pytest.raises(ValueError):
        trial.prepare(run)
    assert not (run / "PLAN.json").exists()


def legacy_claim(registry, status="succeeded", *, native_status=None):
    old = registry.parent / "old_run"
    write(old / "PLAN.json", dict(source_binding=trial.SOURCE_BINDING))
    write(old / "REQUEST.json", {"duration": 10})
    write(old / "state.json", dict(task_id="old-native-id", status=status, submissions_started=1))
    write(old / "NATIVE_SUBMIT_RESPONSE.json", {"id": "old-native-id"})
    write(old / "NATIVE_QUERY_001.json", dict(id="old-native-id", status=native_status or status))
    claim = dict(run_dir=str(old.resolve()), plan=trial.core._binding(old / "PLAN.json"),
        request=trial.core._binding(old / "REQUEST.json"), identity=dict(source_binding=trial.SOURCE_BINDING))
    write(old / "SUBMISSION_CLAIM.json", claim)
    write(registry / "old_claim.json", claim)
    return old


@pytest.mark.parametrize("status", ["queued", "running", "submit_outcome_unknown", "unknown"])
def test_same_source_unsettled_claim_stops_new_prepare(prepared_inputs, status):
    run, _, _ = prepared_inputs
    legacy_claim(trial.REGISTRY, status)
    with pytest.raises(ValueError, match="在途或未知"):
        trial.prepare(run)
    assert not (run / "PLAN.json").exists()


def test_known_success_awaiting_human_does_not_block_new_version(prepared_inputs):
    run, _, config = prepared_inputs
    legacy_claim(trial.REGISTRY, "succeeded_awaiting_human_review", native_status="succeeded")
    trial.prepare(run)
    plan = trial.core._read(run / "PLAN.json")
    assert len(plan["prior_terminal_claim_bindings"]) == 7
    client = Client(config)
    trial.submit(run, client=client)
    assert len(client.posts) == 1


def test_new_same_source_unsettled_claim_after_prepare_blocks_post(prepared_inputs):
    run, _, config = prepared_inputs
    trial.prepare(run)
    legacy_claim(trial.REGISTRY, "running")
    client = Client(config)
    with pytest.raises(ValueError, match="在途或未知"):
        trial.submit(run, client=client)
    assert not client.posts
