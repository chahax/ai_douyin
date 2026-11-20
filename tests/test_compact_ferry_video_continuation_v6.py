"""Four S05 delta checks; the full S01–S04 parent chain uses offline fakes only."""
import base64
from copy import deepcopy
import json
import runpy
from types import SimpleNamespace

import pytest

from src.content_factory import compact_ferry_video_continuation_v6 as trial


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    helpers = runpy.run_path(str(trial.ROOT / "tests/test_compact_ferry_video_trial_v2.py"))
    fourth = trial.parent_trial
    third = fourth.parent_trial
    second = third.parent_trial
    first = second.parent_trial
    parent_base = tmp_path / "parent"
    parent_base.mkdir()
    run, counter, config = helpers["prepared_inputs"].__wrapped__(parent_base, monkeypatch)
    source = first.SOURCE_ROOT
    data = first.core._read(source / "SEGMENTS.json")
    data["segments"][0].update(start_state="桌前", end_state="票已推到女儿面前")
    modules = [first, second, third, fourth, trial]
    durations = [7, 7, 6, 11, 10]
    states = ["票已推到女儿面前", "女儿防备松开", "女儿听懂父亲的解释", "父亲确认女儿想清楚了", "女儿准备收票"]
    selected_names = ["FIRST_SEGMENT.json", "SECOND_SEGMENT.json", "THIRD_SEGMENT.json", "FOURTH_SEGMENT.json", "FIFTH_SEGMENT.json"]
    prompts = [(source / "S01.PROMPT.txt").read_text(encoding="utf-8"),
               "7秒，女儿问票是谁买的，父亲回答早上买的。",
               "6秒，女儿问你不拦我，父亲解释舍不得是自己的事。",
               "11秒，女儿说明工作与住处，父亲确认她已经想清楚；反应与对白并行。",
               "10秒，父亲让女儿收好票，女儿问是否同行，父亲指向渡船；对白动作并行。"]
    for index in range(1, 5):
        data["segments"].append(dict(id=f"S0{index + 1}", duration_seconds=durations[index],
            service_duration_seconds=durations[index], start_state=states[index - 1], end_state=states[index]))
        (source / f"S0{index + 1}.PROMPT.txt").write_text(prompts[index], encoding="utf-8")
    helpers["write"](source / "SEGMENTS.json", data)
    previews = first.core._read(source / "SDK_REQUEST_PREVIEWS.json")
    previews["source"] = first.core._binding(source / "SEGMENTS.json")
    for index in range(1, 5):
        previews["requests"].append(dict(segment_id=f"S0{index + 1}",
            prompt_file=first.core._binding(source / f"S0{index + 1}.PROMPT.txt"),
            payload=modules[index]._source_text_payload(prompts[index])))
    helpers["write"](source / "SDK_REQUEST_PREVIEWS.json", previews)
    validation = first.core._read(source / "PREVIEW_VALIDATION.json")
    validation["bound_files"] = [first.core._binding(source / name) for name in
        ("FULL_SCREENPLAY.md", "SEGMENTS.json", "TIMING_REFERENCE_PROFILE.json", "SDK_REQUEST_PREVIEWS.json")]
    helpers["write"](source / "PREVIEW_VALIDATION.json", validation)
    helpers["make_inputs"](run)
    parent = None
    for index, module in enumerate(modules):
        if index:
            receipt = first.core._read(parent / "receipt.json")
            monkeypatch.setattr(module, "SOURCE_ROOT", source)
            monkeypatch.setattr(module, "REGISTRY", first.REGISTRY)
            monkeypatch.setattr(module, "PARENT_RUN", parent)
            monkeypatch.setattr(module, "PARENT_TASK_ID", receipt["task_id"])
            monkeypatch.setattr(module, "_config", lambda **kwargs: config)
            parent_id, child_id = f"S0{index}", f"S0{index + 1}"
            side = dict(schema="user_continuation_acceptance/v1", user_statement=module.AUTHORIZATION["user_statement"],
                decision_source="explicit_user_continuation_instruction", parent_segment_id=parent_id,
                parent_task_id=receipt["task_id"], accepted_for_continuation=True, authorized_next_segment=child_id,
                max_new_submissions=1, source_binding=trial.SOURCE_BINDING,
                parent_receipt=first.core._binding(parent / "receipt.json"), parent_video=receipt["video"],
                parent_native_tail=receipt["native_tail"], native_tail_source="provider_returned_original_last_frame_url",
                quality_metrics=dict(visual=None, audio=None, lip_sync=None, pacing=None),
                automated_media_inspection=False)
            side[f"source_{parent_id}_end_state"] = data["segments"][index - 1]["end_state"]
            side[f"source_{child_id}_start_state"] = data["segments"][index]["start_state"]
            helpers["write"](parent / "receipt.continuation_user_decision.json", side)
            run = tmp_path / child_id
            helpers["write"](run / selected_names[index], dict(source_binding=trial.SOURCE_BINDING,
                authored_by="primary_assistant", segment=data["segments"][index],
                selection_status="assistant_editorial_timing_v2_candidate_not_new_model_acceptance"))
            helpers["write"](run / "AUTHORIZATION.json", dict(source_binding=trial.SOURCE_BINDING, **module.AUTHORIZATION))
            (run / "PROMPT.txt").write_text(prompts[index], encoding="utf-8")
        if module is trial:
            return run, parent, counter, config, helpers
        monkeypatch.setattr(module, "_metadata", lambda path: {"technical_container_only": True})
        monkeypatch.setattr(module, "last_frame_integrity", lambda path: {"native_file_bytes_only": True})
        module.prepare(run)
        client = helpers["Client"](config, status="succeeded")
        module.submit(run, client=client)
        module.query(run, client=client)
        parent = run


def test_ten_seconds_exact_s04_tail_and_bad_authorization_blocks(inputs):
    run, parent, counter, config, helpers = inputs
    before = (parent / "receipt.json").read_bytes(), counter.read_bytes()
    path = parent / "receipt.continuation_user_decision.json"
    side = trial.core._read(path)
    bad = deepcopy(side)
    bad["authorized_next_segment"] = "S06"
    helpers["write"](path, bad)
    with pytest.raises(ValueError):
        trial.prepare(run)
    assert not (run / "REQUEST.json").exists()
    helpers["write"](path, side)
    assert trial.prepare(run)["status"] == "prepared_not_submitted"
    payload = trial.core._read(run / "REQUEST.json")
    assert payload["duration"] == 10 and payload["resolution"] == "720p"
    assert payload["content"][1]["role"] == "first_frame"
    assert base64.b64decode(payload["content"][1]["image_url"]["url"].split(",", 1)[1]) == (parent / "S04.native-tail.jpg").read_bytes()
    text_only = deepcopy(payload)
    text_only["content"].pop()
    assert text_only == trial._source_text_payload((run / "PROMPT.txt").read_text(encoding="utf-8"))
    path = (trial.SOURCE_ROOT / "SEGMENTS.json").resolve()
    assert trial.core._read(parent / "receipt.json")["source_bindings"][str(path)] == trial.core._binding(path)
    assert ((parent / "receipt.json").read_bytes(), counter.read_bytes()) == before


def test_s05_once_claim_retains_unknown_result_across_directories(inputs):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    other = run.with_name("S05_other")
    other.mkdir()
    for name in ("FIFTH_SEGMENT.json", "AUTHORIZATION.json", "PROMPT.txt"):
        (other / name).write_bytes((run / name).read_bytes())
    trial.prepare(other)
    client = helpers["Client"](config, post_error=TimeoutError("unknown POST"))
    with pytest.raises(TimeoutError):
        trial.submit(run, client=client)
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    with pytest.raises(ValueError):
        trial.submit(other, client=client)
    assert len(client.posts) == 1 and client.gets == []
    assert trial.inspect(run)["status"] == "submit_outcome_unknown"


def test_s05_success_awaits_user_without_s06_and_keeps_parent(inputs, monkeypatch):
    run, parent, counter, config, helpers = inputs
    before = (parent / "receipt.json").read_bytes(), counter.read_bytes()
    trial.prepare(run)
    monkeypatch.setattr(trial, "_metadata", lambda path: {"technical_container_only": True})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {"native_file_bytes_only": True})
    client = helpers["Client"](config, status="succeeded")
    trial.submit(run, client=client)
    result = trial.query(run, client=client)
    receipt = trial.core._read(run / "receipt.json")
    assert result["status"] == "succeeded_awaiting_human_review"
    assert receipt["segment_id"] == "S05" and receipt["parent_segment_id"] == "S04"
    assert receipt["human_approved"] is False and receipt["continuation_authorized"] is False
    assert all(receipt[key] is False for key in ("content_inspection_performed", "audio_or_asr_review_performed", "posthoc_frame_extraction"))
    for directory in (run, parent):
        for name in ("PROMPT.txt", "AUTHORIZATION.json"):
            path = directory / name
            assert receipt["source_bindings"][str(path)] == trial.core._binding(path)
    assert ((parent / "receipt.json").read_bytes(), counter.read_bytes()) == before
    assert len(client.posts) == 1


def test_metadata_ten_second_audio_portrait_packet_contract(monkeypatch):
    duration = [10.104]
    seen = []
    def probe(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(format=dict(duration=str(duration[0])),
            streams=[dict(codec_type="video", width=720, height=1280, nb_read_packets="240"),
                     dict(codec_type="audio", nb_read_packets="320")])))
    monkeypatch.setattr(trial.subprocess, "run", probe)
    for good in (9, 10.104, 11):
        duration[0] = good
        assert trial._metadata("offline.mp4")["streams"]
    for bad in (8.99, 11.01):
        duration[0] = bad
        with pytest.raises(ValueError, match="9–11秒"):
            trial._metadata("offline.mp4")
    assert all("-count_packets" in cmd and "-show_frames" not in cmd for cmd in seen)
