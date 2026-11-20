"""Selected-script trial boundaries: real frozen provenance, offline fake media."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import run_selected_script_video_trial_v1 as trial
from src.content_factory.media_review_policy import validate_source_bindings


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("video trial guard tests must remain offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def selection():
    script = trial.control.read(trial.PARENT / "versions/07/FULL_SCRIPT.json")
    decision = trial.control.read(trial.PARENT / "versions/07/AUTOMATIC_DECISION.json")
    receipt = trial.control.read(trial.ASSET / "receipt.json")
    review = trial.control.read(trial.ASSET / "receipt.human_review.json")
    scope = {
        "schema": "selected_native_script_single_video_trial/v1",
        "script_sha256": trial.control.digest(script), "script_ordinal": 487,
        "source_decision_sha256": trial.control.digest(decision),
        "user_statements": ["开始视频流程。", "刚刚这个版本感觉ok了你评价没通过？"],
        "source_validation_findings_retained": True,
        "human_trial_acceptance_recorded": True, "machine_script_quality_passed": False,
        "max_new_video_submissions": 1, "batch_authorized": False,
        "automatic_retry": False, "publishing_authorized": False,
        "budget_reset": False, "source_script_edited": False,
        "first_source_refs": deepcopy(trial.REFS), "reference_image_only": True,
        "later_tail_continuation_requires_human_approval": True,
    }
    return SimpleNamespace(script=script, decision=decision, receipt=receipt,
                           review=review, scope=scope)


def validate_selection(f):
    return trial.validate_trial_sources(f.scope, f.script, f.decision, f.receipt, f.review)


def test_human_trial_acceptance_preserves_actual_machine_failure(selection):
    before = deepcopy(selection.__dict__)
    result = validate_selection(selection)
    assert selection.__dict__ == before
    assert selection.decision["status"] == "needs_whole_revision"
    assert selection.decision["revision_requirements"]
    assert result["machine_script_quality_passed"] is False
    assert result["user_accepted_for_trial"] is True
    assert result["old_source_decision_unchanged"] is True
    assert selection.receipt["task_id"] == "cgt-20261008213008-7k6gh"
    assert selection.review["decision_source"] == "explicit_user_statement"
    assert selection.review["automated_visual_or_voice_verdict"] is False


@pytest.mark.parametrize("target", ["script", "decision"])
def test_selected_source_or_original_decision_change_is_rejected(selection, target):
    if target == "script":
        selection.script["beats"][0]["steps"][1]["text"] += "离线修改。"
    else:
        selection.decision["revision_requirements"] = []
    with pytest.raises(ValueError, match="changed"):
        validate_selection(selection)


@pytest.mark.parametrize("field,value", [
    ("max_new_video_submissions", 2), ("max_new_video_submissions", True),
    ("batch_authorized", True), ("automatic_retry", True),
    ("publishing_authorized", True), ("budget_reset", True),
    ("machine_script_quality_passed", True), ("source_script_edited", True),
])
def test_selection_does_not_inherit_batch_repeat_or_quality_approval(selection, field, value):
    selection.scope[field] = value
    with pytest.raises(ValueError, match="one selected native trial scope"):
        validate_selection(selection)


@pytest.mark.parametrize("target,field,value", [
    ("receipt", "content_status", "awaiting_human_review"),
    ("receipt", "last_frame_source", "locally_extracted"),
    ("receipt", "technical_status", "unknown"),
    ("review", "decision", "rejected"),
])
def test_unapproved_or_nonoriginal_asset_cannot_be_reused(selection, target, field, value):
    getattr(selection, target)[field] = value
    with pytest.raises(ValueError, match="approved original"):
        validate_selection(selection)


@pytest.mark.parametrize("field,value", [
    ("raw_tail_sha256", "other-approved-reference"),
    ("original_video_sha256", "other-approved-video"),
    ("decision_source", "model_verdict"),
    ("automated_visual_or_voice_verdict", True),
])
def test_approval_metadata_must_bind_same_native_asset(selection, field, value):
    selection.review[field] = value
    with pytest.raises(ValueError):
        validate_selection(selection)


def test_retained_original_findings_flag_must_be_actual_boolean(selection):
    selection.scope["source_validation_findings_retained"] = "true"
    with pytest.raises(ValueError):
        validate_selection(selection)


def test_approval_candidate_task_identity_cannot_be_swapped(selection):
    selection.review["candidate_identity"]["identifiers"]["task_id"] = "other-approved-task"
    with pytest.raises(ValueError):
        validate_selection(selection)


def test_original_failure_decision_must_refer_to_selected_body(selection):
    selection.decision["script_sha256"] = "different-complete-body"
    selection.scope["source_decision_sha256"] = trial.control.digest(selection.decision)
    with pytest.raises(ValueError):
        validate_selection(selection)


@pytest.fixture
def fake_media(monkeypatch, tmp_path, selection):
    out = tmp_path / "video"
    root = tmp_path / "text"
    root.mkdir()
    source = root / "source.json"
    source.write_text(json.dumps(selection.script, ensure_ascii=False), encoding="utf-8")
    image = root / "same-original-reference.png"
    image.write_bytes(Path(selection.receipt["last_frame"]).read_bytes())
    plan = {
        "schema": "selected_script_video_trial_plan/v1", "logical_task_id": trial.LOGICAL,
        "segment_id": trial.SID, "source_run": None, "source_refs": deepcopy(trial.REFS),
        "script_content_sha256": trial.control.digest(selection.script),
        "provider": "ark_api", "model": trial.MODEL, "resolution": "480p", "ratio": "9:16",
        "duration_seconds": 14, "generate_audio": True, "return_last_frame": True,
        "image_role": "reference_image",
        "reference_image": {"path": str(image), "sha256": trial.control.sha_file(image),
                            "source": "generation_service_original"},
        "sources": {"source": {"path": str(source), "sha256": trial.control.sha_file(source)}},
        "authorization": deepcopy(selection.scope), "prompt": "离线模拟当前首样提示词。",
        "machine_script_quality_passed": False, "content_status_at_prepare": "not_available",
        "human_trial_acceptance_recorded": True, "new_submissions": 1,
        "automatic_retry": False, "future_continuation_requires_current_human_approval": True,
        "budget_reset": False,
    }

    class Client:
        config = SimpleNamespace(model=trial.MODEL, provider="ark_api")
        submissions = 0
        create_error = None
        create_response = {"id": "offline-selected-original-id"}
        final = {"status": "running"}

        def __init__(self):
            self.queried_ids = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def build_task_payload(self, prompt, **kwargs):
            assert kwargs["task_type"] == "reference"
            assert kwargs["references"][0].role == "reference_image"
            return {"model": trial.MODEL, "duration": kwargs["duration"],
                    "resolution": kwargs["resolution"], "ratio": kwargs["ratio"],
                    "generate_audio": kwargs["generate_audio"], "return_last_frame": True,
                    "content": [{"type": "text", "text": prompt},
                                kwargs["references"][0].to_content()]}

        def create_task(self, request):
            self.submissions += 1
            if self.create_error:
                raise self.create_error
            return deepcopy(self.create_response)

        def get_task(self, task_id):
            self.queried_ids.append(task_id)
            return deepcopy(self.final)

        def download_video(self, task, path):
            Path(path).write_bytes(b"offline-saved-video")
            return Path(path)

        def download_last_frame(self, task, path):
            Path(path).write_bytes(b"offline-service-original-tail")
            return Path(path)

    client = Client()
    reservations = []
    monkeypatch.setattr(trial, "ROOT", root)
    monkeypatch.setattr(trial, "OUT", out)
    monkeypatch.setattr(trial, "SeedanceClient", lambda config: client)
    monkeypatch.setattr(trial, "SeedanceConfig", SimpleNamespace(from_env=lambda *a, **k: object()))
    monkeypatch.setattr(trial, "make_media_plan", lambda: deepcopy(plan))
    monkeypatch.setattr(trial, "reserve_media_attempt", lambda *args: reservations.append(args))
    probe = {"streams": [{"codec_type": "video", "width": 496, "height": 864},
                          {"codec_type": "audio"}], "format": {"duration": "14.08"}}
    def metadata_only(command, **kwargs):
        assert command[:7] == ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json"]
        return json.dumps(probe)
    monkeypatch.setattr(trial.subprocess, "check_output", metadata_only)
    return SimpleNamespace(out=out, root=root, plan=plan, client=client,
                           source=source, image=image, reservations=reservations)


def test_current_native_reference_request_and_single_trial_guard(fake_media):
    f = fake_media
    before = deepcopy(f.plan)
    assert trial.validate_media_plan(f.plan) == before
    assert f.plan == before
    trial.media("media_prepare")
    request = trial.control.read(f.out / "REQUEST.preview.json")
    assert request["content"][1]["role"] == "reference_image"
    assert request["duration"] == 14 and request["return_last_frame"] is True
    assert f.client.submissions == len(f.reservations) == 0


@pytest.mark.parametrize("field", ["source", "reference"])
def test_changed_bound_source_or_reference_bytes_block_media(fake_media, field):
    path = fake_media.source if field == "source" else fake_media.image
    path.write_bytes(path.read_bytes() + b"changed-offline")
    with pytest.raises(ValueError, match="changed"):
        trial.validate_media_plan(fake_media.plan)
    assert fake_media.client.submissions == 0


@pytest.mark.parametrize("section,field,value", [
    ("authorization", "max_new_video_submissions", 2),
    ("authorization", "max_new_video_submissions", True),
    ("authorization", "batch_authorized", True),
    ("authorization", "automatic_retry", True),
    ("authorization", "budget_reset", True),
    (None, "image_role", "first_frame"),
    (None, "source_run", "new-directory-cannot-reset-history"),
    (None, "new_submissions", 2),
    (None, "future_continuation_requires_current_human_approval", False),
    (None, "script_content_sha256", "different-selected-script"),
    (None, "duration_seconds", 16),
    (None, "duration_seconds", True),
])
def test_media_plan_cannot_expand_or_reset_single_trial(fake_media, section, field, value):
    plan = deepcopy(fake_media.plan)
    target = plan[section] if section else plan
    target[field] = value
    with pytest.raises(ValueError):
        trial.validate_media_plan(plan)


@pytest.mark.parametrize("missing_id", [False, True])
def test_unknown_create_is_never_dispatched_twice(fake_media, missing_id):
    f = fake_media
    trial.media("media_prepare")
    if missing_id:
        f.client.create_response = {}
    else:
        f.client.create_error = RuntimeError("offline result unknown")
    with pytest.raises((RuntimeError, ValueError), match="unknown"):
        trial.media("media_submit")
    receipt = trial.control.read(f.out / "receipt.json")
    assert receipt["technical_status"] == "unknown"
    assert receipt["status"] == "submit_outcome_unknown"
    with pytest.raises(ValueError, match="existing submission"):
        trial.media("media_submit")
    with pytest.raises(ValueError, match="original ID missing"):
        trial.media("media_query")
    assert f.client.submissions == len(f.reservations) == 1


def test_original_id_query_saves_only_pending_human_review(fake_media):
    f = fake_media
    trial.media("media_prepare")
    trial.media("media_submit")
    f.client.final = {"status": "succeeded", "content": {"last_frame_url": "offline-original"}}
    trial.media("media_query")
    receipt = trial.control.read(f.out / "receipt.json")
    assert f.client.submissions == len(f.reservations) == 1
    assert f.client.queried_ids == ["offline-selected-original-id"] * 2
    assert receipt["technical_status"] == "succeeded"
    assert receipt["content_status"] == "awaiting_human_review"
    assert receipt["human_decision"] is None
    assert receipt["next_segment_dispatch_allowed"] is False
    assert receipt["assistant_content_inspected"] is False
    assert receipt["tail_status"] == "saved_unapproved"
    assert receipt["request"] == trial.control.read(f.out / "REQUEST.preview.json")
    assert receipt["source_bindings"] == f.plan["sources"]
    assert receipt["plan"] == str(f.out / "PLAN.json")
    validate_source_bindings(receipt)
    f.source.write_bytes(f.source.read_bytes() + b"modified-after-save")
    with pytest.raises(ValueError, match="lineage changed"):
        validate_source_bindings(receipt)
    with pytest.raises(ValueError, match="existing submission"):
        trial.media("media_submit")
    assert f.client.submissions == 1
    assert not (f.out / ".execution.lock").exists()
