"""Offline first-sample submission and artifact recovery isolation checks."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from scripts import run_legal_current_production_v2_20261010 as runner


class OfflineClient:
    def __init__(self):
        self.config = SimpleNamespace(model=runner.MODEL, provider="ark_api")
        self.created = 0
        self.queried = []
        self.downloads = []
        self.task_status = "running"
        self.tail = True
        self.video_error = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def build_task_payload(self, prompt, **parameters):
        return {"model": self.config.model, "content": [{"type": "text", "text": prompt}],
                "duration": parameters["duration"], "generate_audio": parameters["generate_audio"]}

    def create_task(self, payload):
        self.created += 1
        return {"id": "offline-current-task"}

    def get_task(self, task_id):
        self.queried.append(task_id)
        content = {"video_url": "https://example.invalid/video.mp4"}
        if self.tail:
            content["last_frame_url"] = "https://example.invalid/tail.png"
        return {"id": task_id, "status": self.task_status, "content": content}

    def download_video(self, task, path):
        self.downloads.append(("video", task["id"]))
        if self.video_error:
            raise self.video_error
        path.write_bytes(b"opaque-offline-video-not-decoded")
        return path

    def download_last_frame(self, task, path):
        self.downloads.append(("tail", task["id"]))
        if not self.tail:
            pytest.fail("missing service tail must not initiate a tail download")
        path.write_bytes(b"opaque-service-tail-not-decoded")
        return path


def metadata(seconds=12):
    # Real Ark 480p output is codec-aligned; the prior saved film is 496 x 864.
    return {"format": {"duration": str(seconds)}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 496, "height": 864},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "32000", "channels": 2},
    ]}


@pytest.fixture
def offline(tmp_path, monkeypatch):
    out = tmp_path / "candidate"
    frame = tmp_path / "native.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\nopaque-native-fixture")
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    plan = {"schema": "current_legal_seedance_opening/v1", "logical_task_id": runner.LOGICAL,
            "segment_id": runner.SID, "shot_id": "SH01", "script_content_sha256": runner.SCOPE["script_sha256"],
            "sources": {"source": {"path": str(source), "sha256": runner.sha(source)}},
            "authorization": deepcopy(runner.SCOPE), "provider": "ark_api", "model": runner.MODEL,
            "resolution": "480p", "ratio": "9:16", "duration_seconds": 12,
            "generate_audio": True, "return_last_frame": True, "image_role": "reference_image",
            "reference_image": {"path": str(frame), "sha256": runner.sha(frame)},
            "prompt": "offline current opening", "source_refs": ["B1.S01", "B1.S02"],
            "budget_reset": False, "later_segments_authorized": False}
    client = OfflineClient()
    monkeypatch.setattr(runner, "OUT", out)
    monkeypatch.setattr(runner, "SeedanceConfig", SimpleNamespace(from_env=lambda *a, **kw: client.config))
    monkeypatch.setattr(runner, "SeedanceClient", lambda config: client)
    # This suite isolates execution; source/production validation has separate tests.
    monkeypatch.setattr(runner, "media_plan", lambda configured_client: deepcopy(plan))
    monkeypatch.setattr(runner, "reserve_media_attempt", lambda *a: None)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: json.dumps(metadata()))
    runner.media("media_prepare")
    return out, client, plan


def save_record(out, plan, **changes):
    record = {"status": "submitted", "technical_status": "running", "content_status": "not_available",
              "task_id": "offline-current-task", "plan_snapshot": plan, "new_submissions": 1,
              "automatic_retry": False}
    record.update(changes)
    runner.control.write(out / "receipt.json", record)
    return record


def test_query_without_task_id_never_creates(offline):
    out, client, plan = offline
    save_record(out, plan, task_id=None, status="submit_outcome_unknown", technical_status="unknown")
    with pytest.raises(ValueError, match="no task ID"):
        runner.media("media_query")
    assert client.created == 0 and client.queried == []


def test_running_and_download_failure_queries_keep_original_id(offline):
    out, client, plan = offline
    save_record(out, plan)
    runner.media("media_query")
    runner.media("media_query")
    client.task_status = "succeeded"
    client.video_error = RuntimeError("offline interrupted file download")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="interrupted"):
            runner.media("media_query")
    record = runner.read(out / "receipt.json")
    assert client.created == 0
    assert client.queried == ["offline-current-task"] * 4
    assert record["task_id"] == "offline-current-task"
    assert record["technical_status"] != "succeeded"
    assert record["status"] == "artifact_save_pending"
    assert record["provider_task_status"] == "succeeded"
    assert record["failure_stage"] == "video_download"


def test_repeat_submit_existing_submitted_receipt_is_blocked(offline):
    out, client, plan = offline
    runner.media("media_submit")
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        runner.media("media_submit")
    assert client.created == 1
    assert runner.read(out / "receipt.json")["task_id"] == "offline-current-task"


def test_preexisting_identical_submitting_receipt_is_never_replayed(offline, monkeypatch):
    out, client, plan = offline
    monkeypatch.setattr(runner.control, "now", lambda: "fixed-offline-timestamp")
    request = runner.read(out / "REQUEST.preview.json")
    record = {"schema": "current_legal_seedance_opening_receipt/v1", "status": "submitting",
              "technical_status": "running", "content_status": "not_available",
              "logical_task_id": runner.LOGICAL, "segment_id": runner.SID, "shot_id": plan["shot_id"],
              "provider": "ark_api", "model": runner.MODEL, "plan": str(out / "PLAN.json"),
              "plan_sha256": runner.sha(out / "PLAN.json"), "plan_snapshot": plan,
              "source_bindings": plan["sources"], "request_sha256": runner.digest(request),
              "created_at": "fixed-offline-timestamp", "new_submissions": 1, "automatic_retry": False}
    runner.control.write(out / "receipt.json", record, True)
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        runner.media("media_submit")
    assert client.created == 0
    assert runner.read(out / "receipt.json") == record


@pytest.mark.parametrize("tail", [True, False])
def test_saved_video_stays_for_human_and_never_redispatches(offline, tail):
    out, client, plan = offline
    save_record(out, plan)
    client.task_status = "succeeded"
    client.tail = tail
    runner.media("media_query")
    record = runner.read(out / "receipt.json")
    assert record["technical_status"] == "succeeded"
    assert record["content_status"] == "awaiting_human_review"
    assert record["human_decision"] is None
    assert record["next_segment_dispatch_allowed"] is False
    assert record["assistant_content_inspected"] is False
    assert runner.sha(record["video_path"]) == record["video_sha256"]
    if tail:
        assert record["last_frame_source"] == "generation_service_original"
    else:
        assert record.get("last_frame") is None
        assert "not_returned" in record["tail_status"]
        assert "continuation" in record["tail_status"]
    runner.media("media_query")
    assert client.created == 0 and client.queried == ["offline-current-task"]


def test_complete_native_audio_video_accepts_codec_aligned_metadata():
    runner.validate_saved_metadata(metadata(), {"duration_seconds": 12, "generate_audio": True,
                                               "resolution": "480p", "ratio": "9:16"})


@pytest.mark.parametrize("problem", ["missing_audio", "too_short", "landscape"])
def test_missing_audio_or_incomplete_duration_is_rejected(problem):
    probe = metadata()
    if problem == "missing_audio":
        probe["streams"] = probe["streams"][:1]
    elif problem == "too_short":
        probe["format"]["duration"] = "1.0"
    else:
        probe["streams"][0].update(width=864, height=496)
    with pytest.raises(ValueError):
        runner.validate_saved_metadata(probe, {"duration_seconds": 12, "generate_audio": True,
                                              "resolution": "480p", "ratio": "9:16"})


def test_invalid_metadata_does_not_mark_success_or_dispatch_again(offline, monkeypatch):
    out, client, plan = offline
    save_record(out, plan)
    client.task_status = "succeeded"
    probe = metadata()
    probe["streams"] = probe["streams"][:1]
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: json.dumps(probe))
    with pytest.raises(ValueError):
        runner.media("media_query")
    record = runner.read(out / "receipt.json")
    assert record["technical_status"] != "succeeded"
    assert record["content_status"] != "awaiting_human_review"
    assert record["task_id"] == "offline-current-task"
    assert client.created == 0


def test_same_story_budget_history_and_pending_segment_survive_directory_change(offline, monkeypatch, tmp_path):
    from src.content_factory import creative_legal_short_seedance_execution_v1 as execution
    out, client, plan = offline
    budget_root = tmp_path / "same_story_budget"
    budget_root.mkdir()
    historical_receipt = tmp_path / "historical_receipt.json"
    runner.control.write(historical_receipt, {"technical_status": "failed", "content_status": "not_available"})
    runner.control.write(budget_root / "historical.reservation.json", {
        "schema": "creative_media_reservation/v1", "receipt": str(historical_receipt),
        "segment_id": "HISTORICAL_SOURCE", "logical_task_id": runner.LOGICAL,
    })
    runner.control.write(budget_root / "budget.json", {
        "schema": "creative_media_budget/v1", "failure_limit": 10,
        "scope": "current_script", "budget_reset_supported": False,
    })
    monkeypatch.setattr(execution, "media_reservation_root", lambda current: budget_root)
    monkeypatch.setattr(runner, "reserve_media_attempt", execution.reserve_media_attempt)
    runner.media("media_submit")
    first_receipt = runner.read(out / "receipt.json")
    assert first_receipt["logical_task_id"] == runner.LOGICAL
    budget = runner.read(budget_root / "budget.json")
    assert budget["confirmed_failed_current_script"] == 1
    assert budget["failure_limit"] == 10 and budget["budget_reset_supported"] is False
    assert historical_receipt.read_text(encoding="utf-8")
    monkeypatch.setattr(runner, "OUT", tmp_path / "different_candidate_directory")
    runner.media("media_prepare")
    with pytest.raises(ValueError, match="unresolved"):
        runner.media("media_submit")
    assert client.created == 1
    assert runner.read(out / "receipt.json") == first_receipt
    assert runner.read(runner.OUT / "receipt.json")["status"] == "blocked_before_submit"
    assert runner.read(budget_root / "budget.json")["confirmed_failed_current_script"] == 1
