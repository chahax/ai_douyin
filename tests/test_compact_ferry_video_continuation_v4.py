"""Eight S03 continuation delta checks only; all providers are offline fakes."""
import base64
from copy import deepcopy
import json
import runpy
from types import SimpleNamespace
import pytest
from src.content_factory import compact_ferry_video_continuation_v4 as trial


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    helpers = runpy.run_path(str(trial.ROOT / "tests/test_compact_ferry_video_trial_v2.py"))
    second_trial = trial.parent_trial
    old = second_trial.parent_trial
    parent_base = tmp_path / "parent"
    parent_base.mkdir()
    parent, counter, config = helpers["prepared_inputs"].__wrapped__(parent_base, monkeypatch)
    source = old.SOURCE_ROOT
    data = old.core._read(source / "SEGMENTS.json")
    data["segments"][0].update(start_state="桌前", end_state="票已推到女儿面前")
    second = dict(id="S02", duration_seconds=7, service_duration_seconds=7,
                  start_state="票已推到女儿面前", end_state="女儿防备松开")
    data["segments"].append(second)
    third = dict(id="S03", duration_seconds=6, service_duration_seconds=6,
                 start_state=second["end_state"], end_state="女儿听懂父亲的解释")
    data["segments"].append(third)
    helpers["write"](source / "SEGMENTS.json", data)
    prompt = "7秒，女儿问你买的，父亲回答早上买的，并解释怕漏算热水钱。"
    (source / "S02.PROMPT.txt").write_text(prompt, encoding="utf-8")
    third_prompt = "6秒，女儿问你怎么算，父亲解释路上的费用；反应与对白并行。"
    (source / "S03.PROMPT.txt").write_text(third_prompt, encoding="utf-8")
    previews = old.core._read(source / "SDK_REQUEST_PREVIEWS.json")
    previews["source"] = old.core._binding(source / "SEGMENTS.json")
    previews["requests"].append(dict(segment_id="S02",
        prompt_file=old.core._binding(source / "S02.PROMPT.txt"), payload=second_trial._source_text_payload(prompt)))
    previews["requests"].append(dict(segment_id="S03",
        prompt_file=old.core._binding(source / "S03.PROMPT.txt"), payload=trial._source_text_payload(third_prompt)))
    helpers["write"](source / "SDK_REQUEST_PREVIEWS.json", previews)
    validation = old.core._read(source / "PREVIEW_VALIDATION.json")
    validation["bound_files"] = [old.core._binding(source / name) for name in
        ("FULL_SCREENPLAY.md", "SEGMENTS.json", "TIMING_REFERENCE_PROFILE.json", "SDK_REQUEST_PREVIEWS.json")]
    helpers["write"](source / "PREVIEW_VALIDATION.json", validation)
    helpers["make_inputs"](parent)
    monkeypatch.setattr(old, "_metadata", lambda path: {"technical_container_only": True})
    monkeypatch.setattr(old, "last_frame_integrity", lambda path: {"native_file_bytes_only": True})
    old.prepare(parent)
    client = helpers["Client"](config, status="succeeded")
    old.submit(parent, client=client)
    old.query(parent, client=client)
    receipt = old.core._read(parent / "receipt.json")
    monkeypatch.setattr(second_trial, "SOURCE_ROOT", source)
    monkeypatch.setattr(second_trial, "REGISTRY", old.REGISTRY)
    monkeypatch.setattr(second_trial, "PARENT_RUN", parent)
    monkeypatch.setattr(second_trial, "PARENT_TASK_ID", receipt["task_id"])
    monkeypatch.setattr(second_trial, "_config", lambda **kwargs: config)
    side = dict(schema="user_continuation_acceptance/v1", user_statement="继续",
        decision_source="explicit_user_continuation_instruction", parent_segment_id="S01",
        parent_task_id=receipt["task_id"], accepted_for_continuation=True, authorized_next_segment="S02",
        max_new_submissions=1, source_binding=trial.SOURCE_BINDING,
        parent_receipt=old.core._binding(parent / "receipt.json"), parent_video=receipt["video"],
        parent_native_tail=receipt["native_tail"], native_tail_source="provider_returned_original_last_frame_url",
        source_S01_end_state=data["segments"][0]["end_state"], source_S02_start_state=second["start_state"],
        quality_metrics=dict(visual=None, audio=None, lip_sync=None, pacing=None), automated_media_inspection=False)
    helpers["write"](parent / "receipt.continuation_user_decision.json", side)
    run = tmp_path / "S02"
    helpers["write"](run / "SECOND_SEGMENT.json", dict(source_binding=trial.SOURCE_BINDING,
        authored_by="primary_assistant", segment=second,
        selection_status="assistant_editorial_timing_v2_candidate_not_new_model_acceptance"))
    helpers["write"](run / "AUTHORIZATION.json", dict(source_binding=trial.SOURCE_BINDING, **second_trial.AUTHORIZATION))
    (run / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    monkeypatch.setattr(second_trial, "_metadata", lambda path: {"technical_container_only": True})
    monkeypatch.setattr(second_trial, "last_frame_integrity", lambda path: {"native_file_bytes_only": True})
    second_trial.prepare(run)
    second_client = helpers["Client"](config, status="succeeded")
    second_trial.submit(run, client=second_client)
    second_trial.query(run, client=second_client)
    parent = run
    receipt = old.core._read(parent / "receipt.json")
    monkeypatch.setattr(trial, "SOURCE_ROOT", source)
    monkeypatch.setattr(trial, "REGISTRY", old.REGISTRY)
    monkeypatch.setattr(trial, "PARENT_RUN", parent)
    monkeypatch.setattr(trial, "PARENT_TASK_ID", receipt["task_id"])
    monkeypatch.setattr(trial, "_config", lambda **kwargs: config)
    side = dict(schema="user_continuation_acceptance/v1", user_statement="继续",
        decision_source="explicit_user_continuation_instruction", parent_segment_id="S02",
        parent_task_id=receipt["task_id"], accepted_for_continuation=True, authorized_next_segment="S03",
        max_new_submissions=1, source_binding=trial.SOURCE_BINDING,
        parent_receipt=old.core._binding(parent / "receipt.json"), parent_video=receipt["video"],
        parent_native_tail=receipt["native_tail"], native_tail_source="provider_returned_original_last_frame_url",
        source_S02_end_state=second["end_state"], source_S03_start_state=third["start_state"],
        quality_metrics=dict(visual=None, audio=None, lip_sync=None, pacing=None), automated_media_inspection=False)
    helpers["write"](parent / "receipt.continuation_user_decision.json", side)
    run = tmp_path / "S03"
    helpers["write"](run / "THIRD_SEGMENT.json", dict(source_binding=trial.SOURCE_BINDING,
        authored_by="primary_assistant", segment=third,
        selection_status="assistant_editorial_timing_v2_candidate_not_new_model_acceptance"))
    helpers["write"](run / "AUTHORIZATION.json", dict(source_binding=trial.SOURCE_BINDING, **trial.AUTHORIZATION))
    (run / "PROMPT.txt").write_text(third_prompt, encoding="utf-8")
    return run, parent, counter, config, helpers



def test_six_seconds_first_frame_is_unedited_s02_bytes(inputs):
    run, parent, counter, config, _ = inputs
    before = (parent / "receipt.json").read_bytes(), counter.read_bytes()
    result = trial.prepare(run)
    payload = trial.core._read(run / "REQUEST.json")
    assert payload["duration"] == 6 and payload["resolution"] == "720p"
    assert payload["content"][1]["role"] == "first_frame"
    assert base64.b64decode(payload["content"][1]["image_url"]["url"].split(",", 1)[1]) == (parent / "S02.native-tail.jpg").read_bytes()
    text_only = deepcopy(payload)
    text_only["content"].pop()
    assert text_only == trial._source_text_payload((run / "PROMPT.txt").read_text(encoding="utf-8"))
    assert result["failures"] == 2 and not result["continuation_authorized"]
    assert ((parent / "receipt.json").read_bytes(), counter.read_bytes()) == before


def test_absolute_source_binding_keys_and_s02_parent_pass(inputs):
    run, parent, counter, config, helpers = inputs
    receipt = trial.core._read(parent / "receipt.json")
    path = (trial.SOURCE_ROOT / "SEGMENTS.json").resolve()
    assert receipt["source_bindings"][str(path)] == trial.core._binding(path)
    assert "SEGMENTS.json" not in receipt["source_bindings"]
    assert trial.prepare(run)["status"] == "prepared_not_submitted"


def test_wrong_continuation_target_stops_before_request(inputs):
    run, parent, counter, config, helpers = inputs
    path = parent / "receipt.continuation_user_decision.json"
    side = trial.core._read(path)
    side["authorized_next_segment"] = "S04"
    helpers["write"](path, side)
    with pytest.raises(ValueError): trial.prepare(run)
    assert not (run / "REQUEST.json").exists()


def test_s02_tail_changed_after_prepare_blocks_post(inputs):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    (parent / "S02.native-tail.jpg").write_bytes(b"modified")
    client = helpers["Client"](config)
    with pytest.raises(ValueError): trial.submit(run, client=client)
    assert client.posts == []


def test_once_claim_and_unknown_post_prevent_resubmission(inputs):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    other = run.with_name("S03_other")
    other.mkdir()
    for name in ("THIRD_SEGMENT.json", "AUTHORIZATION.json", "PROMPT.txt"):
        (other / name).write_bytes((run / name).read_bytes())
    trial.prepare(other)
    client = helpers["Client"](config, post_error=TimeoutError("unknown POST"))
    with pytest.raises(TimeoutError): trial.submit(run, client=client)
    with pytest.raises(ValueError): trial.submit(run, client=client)
    with pytest.raises(ValueError): trial.submit(other, client=client)
    assert len(client.posts) == 1 and client.gets == []
    assert trial.inspect(run)["status"] == "submit_outcome_unknown"


def test_new_same_source_unsettled_claim_blocks_post(inputs):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    helpers["legacy_claim"](trial.REGISTRY, "running")
    client = helpers["Client"](config)
    with pytest.raises(ValueError): trial.submit(run, client=client)
    assert client.posts == []


def test_success_s03_is_user_pending_without_s04_and_keeps_sources(inputs, monkeypatch):
    run, parent, counter, config, helpers = inputs
    before = (parent / "receipt.json").read_bytes(), counter.read_bytes()
    trial.prepare(run)
    client = helpers["Client"](config, status="succeeded")
    monkeypatch.setattr(trial, "_metadata", lambda path: {"technical_container_only": True})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {"native_file_bytes_only": True})
    trial.submit(run, client=client)
    result = trial.query(run, client=client)
    receipt = trial.core._read(run / "receipt.json")
    assert result["status"] == "succeeded_awaiting_human_review"
    assert receipt["segment_id"] == "S03" and receipt["parent_segment_id"] == "S02"
    assert receipt["human_approved"] is False and receipt["continuation_authorized"] is False
    assert all(receipt[key] is False for key in ("content_inspection_performed", "audio_or_asr_review_performed", "posthoc_frame_extraction"))
    for directory in (run, parent):
        for name in ("PROMPT.txt", "AUTHORIZATION.json"):
            path = directory / name
            assert receipt["source_bindings"][str(path)] == trial.core._binding(path)
    assert ((parent / "receipt.json").read_bytes(), counter.read_bytes()) == before
    assert len(client.posts) == 1


def test_metadata_six_second_audio_portrait_packet_contract(monkeypatch):
    duration = [6.104]
    seen = []
    def probe(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(format=dict(duration=str(duration[0])),
            streams=[dict(codec_type="video", width=720, height=1280, nb_read_packets="144"),
                     dict(codec_type="audio", nb_read_packets="220")])))
    monkeypatch.setattr(trial.subprocess, "run", probe)
    assert trial._metadata("offline.mp4")["streams"]
    for bad in (4.9, 7.1):
        duration[0] = bad
        with pytest.raises(ValueError): trial._metadata("offline.mp4")
    assert all("-count_packets" in cmd and "-show_frames" not in cmd for cmd in seen)
