"""Current continuation entry guards; synthetic bytes, no provider requests."""
from copy import deepcopy
import json
import socket
from types import SimpleNamespace

import pytest

from scripts import run_selected_script_continuation_v1 as trial
from src.content_factory import media_review_policy as policy


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("continuation guard tests cannot access providers")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def approved_previous(monkeypatch, tmp_path):
    media = tmp_path / "previous"
    media.mkdir()
    video, tail = media / "synthetic.mp4", media / "synthetic.png"
    video.write_bytes(b"offline-container-placeholder")
    tail.write_bytes(b"offline-tail-placeholder")
    rp = media / "receipt.json"
    record = {"technical_status": "succeeded", "content_status": "awaiting_human_review",
        "segment_id": trial.previous.SID, "logical_task_id": trial.LOGICAL,
        "provider": "ark_api", "model": trial.MODEL, "task_id": "offline-approved-previous",
        "request": {"offline_fixture": True}, "request_sha256": trial.control.digest({"offline_fixture": True}),
        "plan_sha256": "offline-plan-hash", "source_bindings": {},
        "plan_snapshot": {"script_content_sha256": trial.SOURCE_SHA, "source_refs": trial.COMPLETED},
        "video_path": str(video), "video_sha256": trial.control.sha_file(video),
        "last_frame": str(tail), "last_frame_sha256": trial.control.sha_file(tail),
        "last_frame_source": "generation_service_original"}
    write(rp, record)
    policy._record_user_media_decision(rp, "approved", "[OFFLINE FIXTURE] simulated explicit approval")
    monkeypatch.setattr(trial, "PREVIOUS_MEDIA", media)
    return SimpleNamespace(media=media, receipt=rp, review=media / "receipt.human_review.json", tail=tail)


@pytest.fixture
def plan(approved_previous):
    return {"schema": "selected_source_continuation_plan/v1", "logical_task_id": trial.LOGICAL,
        "segment_id": trial.SID, "source_run": None, "script_content_sha256": trial.SOURCE_SHA,
        "completed_source_refs": trial.COMPLETED, "source_refs": trial.REFS,
        "provider": "ark_api", "model": trial.MODEL, "resolution": "480p", "ratio": "9:16",
        "duration_seconds": 8, "generate_audio": True, "return_last_frame": True,
        "image_role": "first_frame", "first_frame": trial.approved_frame(), "sources": {},
        "authorization": {"script_sha256": trial.SOURCE_SHA, "source_refs": trial.REFS,
            "previous_segment_id": trial.previous.SID, "segment_id": trial.SID,
            "completed_source_refs": trial.COMPLETED, "max_new_video_submissions": 1,
            "batch_authorized": False, "automatic_retry": False, "publishing_authorized": False,
            "budget_reset": False, "source_script_edited": False, "machine_script_quality_passed": False,
            "whole_film_direction_accepted": False, "subsequent_continuation_requires_human_approval": True},
        "prompt": "offline current prompt", "new_submissions": 1, "automatic_retry": False,
        "budget_reset": False, "future_continuation_requires_current_human_approval": True,
        "machine_script_quality_passed": False, "whole_film_direction_accepted": False}


def test_approved_native_tail_and_one_current_scope(plan):
    assert trial.validate_plan(plan) == plan
    assert plan["image_role"] == "first_frame" and plan["source_run"] is None
    assert plan["logical_task_id"] == trial.previous.LOGICAL


@pytest.mark.parametrize("mode", ["no_review", "unapproved", "changed_tail", "nonadjacent"])
def test_previous_approval_and_tail_scope_fail_closed(approved_previous, mode):
    if mode == "no_review":
        approved_previous.review.unlink()
    elif mode == "unapproved":
        r = trial.control.read(approved_previous.receipt)
        r["content_status"] = "awaiting_human_review"
        write(approved_previous.receipt, r)
    elif mode == "changed_tail":
        approved_previous.tail.write_bytes(b"changed after approval")
    else:
        r = trial.control.read(approved_previous.receipt)
        r["plan_snapshot"]["source_refs"] = ["B1.S01"]
        write(approved_previous.receipt, r)
    with pytest.raises((ValueError, FileNotFoundError)):
        trial.approved_frame()


def test_actual_current_range_is_adjacent_without_replaying_previous():
    x = trial.control.read(trial.PARENT / "INPUT.json")
    script = x["full_current_script"]
    trial.contract.continuation_probe_schema(script, trial.COMPLETED, trial.REFS)
    with pytest.raises(ValueError, match="adjacent"):
        trial.contract.continuation_probe_schema(script, trial.COMPLETED, ["B1.S04"])
    with pytest.raises(ValueError, match="adjacent"):
        trial.contract.continuation_probe_schema(script, trial.COMPLETED, ["B1.S02", "B1.S03"])


@pytest.mark.parametrize("key,value", [
    ("source_receipt", "offline-different-receipt.json"),
    ("original_video_sha256", "0" * 64),
    ("raw_tail_sha256", "0" * 64),
])
def test_review_must_belong_to_current_original_receipt(approved_previous, key, value):
    review = trial.control.read(approved_previous.review)
    review[key] = value
    write(approved_previous.review, review)
    with pytest.raises(ValueError, match="another original candidate"):
        trial.approved_frame()


@pytest.mark.parametrize("section,key,value", [
    (None, "new_submissions", True),
    (None, "duration_seconds", True),
    (None, "source_run", "reset-budget-directory"),
    (None, "budget_reset", True),
    (None, "image_role", "reference_image"),
    (None, "machine_script_quality_passed", 0),
    (None, "whole_film_direction_accepted", True),
    (None, "source_refs", ["B1.S04"]),
    ("authorization", "max_new_video_submissions", True),
    ("authorization", "batch_authorized", True),
    ("authorization", "automatic_retry", True),
    ("authorization", "budget_reset", True),
    ("authorization", "subsequent_continuation_requires_human_approval", 1),
    ("authorization", "previous_segment_id", "different-previous-segment"),
    ("authorization", "segment_id", "different-current-segment"),
])
def test_typed_scope_and_same_budget_are_required(plan, section, key, value):
    changed = deepcopy(plan)
    (changed[section] if section else changed)[key] = value
    with pytest.raises(ValueError):
        trial.validate_plan(changed)


def test_frame_metadata_cannot_be_swapped(plan):
    changed = deepcopy(plan)
    changed["first_frame"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="tail changed"):
        trial.validate_plan(changed)


def test_missing_current_review_cannot_produce_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(trial, "ROOT", tmp_path)
    write(tmp_path / "INPUT.json", {})
    write(tmp_path / "VIDEO_TEXT_HANDOFF.json", {})
    write(tmp_path / "CALL_LEDGER.json", {})
    monkeypatch.setattr(trial, "runtime", lambda: SimpleNamespace(
        ledger=tmp_path / "CALL_LEDGER.json", check=lambda ledger: None))
    def missing(label):
        assert label == "production_text_review"
        raise ValueError("missing current review")
    monkeypatch.setattr(trial, "accepted", missing)
    with pytest.raises(ValueError, match="missing current review"):
        trial.make_plan()


def test_real498_spend_is_carried_without_parent_writes():
    p = trial.PARENT / "CALL_LEDGER.json"
    before = p.read_bytes()
    inherited, receipts = trial.previous.inherited_known_parent(trial.control.read(p), trial.PARENT)
    assert [r["ordinal"] for r in receipts] == [498]
    assert receipts[0]["status"] == "contract_valid"
    assert inherited["calls_started"] == 498
    assert inherited["reported_tokens"] == 7659223 + receipts[0]["response_metadata"]["total_tokens"]
    assert inherited["unknown_token_reservations"] == 93117
    assert inherited["pending_ordinals"] == [70, 160]
    assert p.read_bytes() == before


def test_unknown_submission_and_missing_id_never_create_again(monkeypatch, tmp_path, plan):
    out = tmp_path / "current"
    out.mkdir()
    calls, reservations = [], []
    class Client:
        config = SimpleNamespace(model=trial.MODEL)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def build_task_payload(self, prompt, **kwargs):
            return {"prompt": prompt, "duration": kwargs["duration"], "offline_fixture": True}
        def create_task(self, request):
            calls.append(deepcopy(request))
            raise RuntimeError("offline unknown transport result")
        def get_task(self, task_id):
            raise AssertionError("no original id is available")
    monkeypatch.setattr(trial, "OUT", out)
    monkeypatch.setattr(trial, "SeedanceConfig", SimpleNamespace(from_env=lambda *a, **k: None))
    monkeypatch.setattr(trial, "SeedanceClient", lambda cfg: Client())
    monkeypatch.setattr(trial, "make_plan", lambda: deepcopy(plan))
    monkeypatch.setattr(trial, "reserve_media_attempt", lambda *args: reservations.append(args))
    request = trial.build_request(Client(), plan)
    write(out / "PLAN.json", plan)
    write(out / "REQUEST.preview.json", request)
    with pytest.raises(RuntimeError, match="unknown"):
        trial.media("media_submit")
    saved = trial.control.read(out / "receipt.json")
    assert saved["status"] == "submit_outcome_unknown" and saved["technical_status"] == "unknown"
    with pytest.raises(ValueError, match="never resubmit"):
        trial.media("media_submit")
    with pytest.raises(ValueError, match="missing original ID"):
        trial.media("media_query")
    assert len(calls) == len(reservations) == 1

