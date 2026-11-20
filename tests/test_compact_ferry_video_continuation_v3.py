"""Only S02 differences; inherited once/unknown logic also exercised without services."""
import base64
from copy import deepcopy
from pathlib import Path
import runpy

import pytest

from src.content_factory import compact_ferry_video_continuation_v3 as trial


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    helpers = runpy.run_path(str(trial.ROOT / "tests/test_compact_ferry_video_trial_v2.py"))
    old = trial.parent_trial
    parent_base = tmp_path / "parent"
    parent_base.mkdir()
    parent, counter, config = helpers["prepared_inputs"].__wrapped__(parent_base, monkeypatch)
    source = old.SOURCE_ROOT
    data = old.core._read(source / "SEGMENTS.json")
    data["segments"][0].update(start_state="桌前", end_state="票已推到女儿面前")
    second = dict(id="S02", duration_seconds=7, service_duration_seconds=7,
                  start_state="票已推到女儿面前", end_state="女儿防备松开")
    data["segments"].append(second)
    helpers["write"](source / "SEGMENTS.json", data)
    prompt = "7秒，女儿问你买的，父亲回答早上买的，并解释怕漏算热水钱。"
    (source / "S02.PROMPT.txt").write_text(prompt, encoding="utf-8")
    previews = old.core._read(source / "SDK_REQUEST_PREVIEWS.json")
    previews["source"] = old.core._binding(source / "SEGMENTS.json")
    previews["requests"].append(dict(segment_id="S02",
        prompt_file=old.core._binding(source / "S02.PROMPT.txt"), payload=trial._source_text_payload(prompt)))
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
    monkeypatch.setattr(trial, "SOURCE_ROOT", source)
    monkeypatch.setattr(trial, "REGISTRY", old.REGISTRY)
    monkeypatch.setattr(trial, "PARENT_RUN", parent)
    monkeypatch.setattr(trial, "PARENT_TASK_ID", receipt["task_id"])
    monkeypatch.setattr(trial, "_config", lambda **kwargs: config)
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
    helpers["write"](run / "AUTHORIZATION.json", dict(source_binding=trial.SOURCE_BINDING, **trial.AUTHORIZATION))
    (run / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    return run, parent, counter, config, helpers


def test_first_frame_decodes_to_original_parent_bytes_and_original_receipt_stays_pending(inputs):
    run, parent, counter, config, _ = inputs
    receipt_before, counter_before = (parent / "receipt.json").read_bytes(), counter.read_bytes()
    result = trial.prepare(run)
    request = trial.core._read(run / "REQUEST.json")
    content = request["content"]
    assert len(content) == 2 and content[1]["role"] == "first_frame"
    assert content[1]["type"] == "image_url"
    assert base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1]) == (parent / "S01.native-tail.jpg").read_bytes()
    without_frame = deepcopy(request)
    without_frame["content"].pop()
    assert without_frame == trial._source_text_payload((run / "PROMPT.txt").read_text(encoding="utf-8"))
    assert result["status"] == "prepared_not_submitted" and result["failures"] == 2
    assert (parent / "receipt.json").read_bytes() == receipt_before and counter.read_bytes() == counter_before
    assert trial.core._read(parent / "receipt.json")["human_approved"] is False


@pytest.mark.parametrize("change", ["missing", "other_parent_id", "other_tail", "bulk_scope", "fake_quality_score"])
def test_bad_parent_user_sidecar_blocks_prepare(inputs, change):
    run, parent, counter, config, helpers = inputs
    path = parent / "receipt.continuation_user_decision.json"
    if change == "missing":
        path.rename(path.with_suffix(".held"))
    else:
        side = trial.core._read(path)
        if change == "other_parent_id": side["parent_task_id"] = "different-original-id"
        if change == "other_tail": side["parent_native_tail"]["sha256"] = "0" * 64
        if change == "bulk_scope": side["authorized_next_segment"] = "all"
        if change == "fake_quality_score": side["quality_metrics"]["audio"] = True
        helpers["write"](path, side)
    with pytest.raises((ValueError, FileNotFoundError)):
        trial.prepare(run)
    assert not (run / "REQUEST.json").exists()


@pytest.mark.parametrize("target", ["S01.native-tail.jpg", "receipt.continuation_user_decision.json", "../source/FULL_SCREENPLAY.md"])
def test_changed_parent_evidence_after_prepare_blocks_post(inputs, target):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    path = trial.SOURCE_ROOT / "FULL_SCREENPLAY.md" if target.startswith("../") else parent / target
    path.write_bytes(path.read_bytes() + b" ")
    client = helpers["Client"](config)
    with pytest.raises(ValueError): trial.submit(run, client=client)
    assert client.posts == []


def test_only_one_post_across_directories_and_unknown_result_keeps_idless_claim(inputs):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    other = run.with_name("S02_other_directory")
    other.mkdir()
    for name in ("SECOND_SEGMENT.json", "AUTHORIZATION.json", "PROMPT.txt"):
        (other / name).write_bytes((run / name).read_bytes())
    trial.prepare(other)
    client = helpers["Client"](config, post_error=TimeoutError("unknown POST"))
    with pytest.raises(TimeoutError): trial.submit(run, client=client)
    with pytest.raises(ValueError): trial.submit(run, client=client)
    with pytest.raises(ValueError): trial.submit(other, client=client)
    assert trial.inspect(run)["status"] == "submit_outcome_unknown"
    assert len(client.posts) == 1 and client.gets == []


def test_unsettled_same_story_parent_cannot_continue(inputs):
    run, parent, counter, config, helpers = inputs
    state = trial.core._read(parent / "state.json")
    state["status"] = "running"
    helpers["write"](parent / "state.json", state)
    with pytest.raises(ValueError): trial.prepare(run)


def test_succeeded_s02_preserves_parent_and_awaits_user_without_s03_authorization(inputs, monkeypatch):
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
    assert receipt["segment_id"] == "S02" and receipt["parent_segment_id"] == "S01"
    assert receipt["human_approved"] is False and receipt["continuation_authorized"] is False
    assert all(receipt[key] is False for key in ("content_inspection_performed", "audio_or_asr_review_performed", "posthoc_frame_extraction"))
    assert len(client.posts) == 1 and client.gets == ["compact-original-task"]
    assert (parent / "receipt.json").read_bytes() == before[0] and counter.read_bytes() == before[1]


def test_parent_and_child_same_named_sources_are_all_preserved_in_receipt(inputs, monkeypatch):
    run, parent, counter, config, helpers = inputs
    trial.prepare(run)
    monkeypatch.setattr(trial, "_metadata", lambda path: {"technical_container_only": True})
    monkeypatch.setattr(trial, "last_frame_integrity", lambda path: {"native_file_bytes_only": True})
    client = helpers["Client"](config, status="succeeded")
    trial.submit(run, client=client)
    trial.query(run, client=client)
    receipt = trial.core._read(run / "receipt.json")
    sources = receipt["source_bindings"]
    for directory in (run, parent):
        for name in ("PROMPT.txt", "AUTHORIZATION.json"):
            path = directory / name
            assert sources[str(path)] == trial.core._binding(path)
    assert len(sources) == len(set(row["path"] for row in trial.core._read(run / "PLAN.json")["source_files"]))
