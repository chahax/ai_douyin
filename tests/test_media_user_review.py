from __future__ import annotations

import hashlib
import json

import pytest

from scripts.run_creative_seedance_segment import validate as validate_segment
from src.content_factory.media_review_policy import (
    record_user_media_decision,
    validate_approved_tail,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(tmp_path, name="receipt"):
    video = tmp_path / f"{name}.mp4"
    tail = tmp_path / f"{name}.last.png"
    video.write_bytes(b"provider-video")
    tail.write_bytes(b"provider-tail")
    receipt = tmp_path / f"{name}.json"
    receipt.write_text(json.dumps({
        "schema": "creative_seedance_segment_receipt/v1",
        "status": "succeeded_awaiting_human_review",
        "technical_status": "succeeded",
        "content_status": "awaiting_human_review",
        "provider": "ark_api",
        "segment_id": name,
        "task_id": f"task-{name}",
        "video_path": str(video),
        "video_sha256": _sha(video),
        "last_frame": str(tail),
        "last_frame_sha256": _sha(tail),
    }), encoding="utf-8")
    return receipt, video, tail


def test_explicit_user_approval_binds_original_video_and_raw_tail(tmp_path):
    receipt, video, tail = _candidate(tmp_path)

    review = record_user_media_decision(
        receipt, "approved", "我已人工看过这一段，同意继续下一段。",
    )
    repeated = record_user_media_decision(
        receipt, "approved", "我已人工看过这一段，同意继续下一段。",
    )
    binding = validate_approved_tail(
        receipt.with_name("receipt.human_review.json"),
        expected_tail_path=tail,
    )

    assert repeated == review
    assert review["decision"] == "approved"
    assert review["original_video_sha256"] == _sha(video)
    assert binding == {"path": str(tail.resolve()), "sha256": _sha(tail)}
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert saved["content_status"] == "approved"
    assert saved["technical_status"] == "succeeded"


def test_rejection_or_changed_tail_cannot_unlock_continuation(tmp_path):
    rejected_receipt, _video, rejected_tail = _candidate(tmp_path, "rejected")
    record_user_media_decision(
        rejected_receipt, "rejected", "我人工看过，人物动作不对。",
    )
    with pytest.raises(ValueError, match="approved user review"):
        validate_approved_tail(
            rejected_receipt.with_name("rejected.human_review.json"),
        )


@pytest.mark.parametrize("changed_field", ["video_identity", "task_id"])
def test_candidate_receipt_identity_change_invalidates_prior_approval(tmp_path, changed_field):
    receipt, _video, tail = _candidate(tmp_path, f"tamper-{changed_field}")
    review_path = receipt.with_name(receipt.stem + ".human_review.json")
    record_user_media_decision(
        receipt, "approved", "我已人工审核当前这条候选并批准续段。",
    )
    record = json.loads(receipt.read_text(encoding="utf-8"))
    if changed_field == "video_identity":
        replacement = tmp_path / "replacement.mp4"
        replacement.write_bytes(b"another-candidate-video")
        record["video_path"] = str(replacement)
        record["video_sha256"] = _sha(replacement)
    else:
        record["task_id"] = "different-provider-task"
    receipt.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="approved decision is not current"):
        validate_approved_tail(review_path, expected_tail_path=tail)

    approved_receipt, _video, approved_tail = _candidate(tmp_path, "changed")
    record_user_media_decision(
        approved_receipt, "approved", "我人工看过，可以继续。",
    )
    approved_tail.write_bytes(b"changed")
    with pytest.raises(ValueError, match="raw tail changed"):
        validate_approved_tail(
            approved_receipt.with_name("changed.human_review.json"),
        )


def test_raw_tail_segment_plan_requires_bound_user_approval(tmp_path):
    receipt, _video, tail = _candidate(tmp_path)
    record_user_media_decision(
        receipt, "approved", "我已人工看过，同意使用原尾帧续段。",
    )
    review = receipt.with_name("receipt.human_review.json")
    plan = {
        "schema": "creative_seedance_segment_plan/v1",
        "opening_frame_source": "preceding_approved_raw_tail",
        "first_frame": {"path": str(tail), "sha256": _sha(tail)},
        "predecessor_review": {"path": str(review), "sha256": _sha(review)},
        "sources": {},
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    _path, validated, frame = validate_segment(path)

    assert validated == plan
    assert frame == tail.resolve()
