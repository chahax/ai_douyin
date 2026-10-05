"""Shared media-review state for newly generated video candidates.

Technical completion and content approval are deliberately independent. A
provider response and a durably saved file can only move ``technical_status``
to ``succeeded``. Video content remains pending until an explicit user review
is bound to the exact source file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, MutableMapping


USER_MANUAL_REVIEW_POLICY_VERSION = "user_manual_review_only/v1"
AWAITING_HUMAN_REVIEW = "awaiting_human_review"


def mark_saved_candidate(
    record: MutableMapping[str, Any],
    *,
    status: str = "succeeded_awaiting_human_review",
) -> MutableMapping[str, Any]:
    """Mark a saved candidate without making a content-quality decision."""

    record.update(
        status=status,
        technical_status="succeeded",
        review_policy_version=USER_MANUAL_REVIEW_POLICY_VERSION,
        content_status=AWAITING_HUMAN_REVIEW,
        user_decision_source=None,
    )
    return record


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _candidate_identity(record: dict[str, Any], receipt_path: Path) -> dict[str, Any]:
    """Canonical identity fields that an approval is allowed to cover."""
    video = Path(
        record.get("video_path")
        or record.get("local_video")
        or record.get("video", "")
    ).resolve()
    tail_value = record.get("last_frame") or record.get("raw_tail")
    tail = Path(tail_value).resolve() if tail_value else None
    identity_fields = (
        "provider", "provider_name", "model", "segment_id", "shot", "shot_id",
        "task_id", "submit_id", "campaign_attempt_id", "generation_attempt_id",
        "candidate_id", "logical_task_id", "plan_sha256", "request_sha256",
        "lineage_sha256", "source_bindings",
    )
    return {
        "source_receipt": str(Path(receipt_path).resolve()),
        "identifiers": {
            key: record.get(key)
            for key in identity_fields
            if record.get(key) is not None
        },
        "video_path": str(video),
        "video_sha256": record.get("video_sha256"),
        "raw_tail_path": str(tail) if tail else None,
        "raw_tail_sha256": record.get("last_frame_sha256") or record.get("raw_tail_sha256"),
    }


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _record_user_media_decision(
    receipt_path: Path,
    decision: str,
    user_statement: str,
) -> dict[str, Any]:
    """Bind an explicit user decision to unchanged provider output bytes.

    This function never inspects media content. It verifies only file presence,
    hashes and receipt lineage before recording the user's own decision.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    user_statement = user_statement.strip()
    if not user_statement:
        raise ValueError("an explicit user statement is required")
    receipt_path = Path(receipt_path).resolve()
    record = _read(receipt_path)
    if (record.get("technical_status") != "succeeded"
            or record.get("content_status") not in {
                AWAITING_HUMAN_REVIEW, "approved", "rejected",
            }):
        raise ValueError("candidate is not a saved video awaiting user review")
    video = Path(
        record.get("video_path")
        or record.get("local_video")
        or record.get("video", "")
    ).resolve()
    expected_video_hash = record.get("video_sha256")
    if (not video.is_file() or not expected_video_hash
            or _file_sha256(video) != expected_video_hash):
        raise ValueError("candidate video is missing or changed")
    tail_value = record.get("last_frame")
    expected_tail_hash = record.get("last_frame_sha256")
    tail = Path(tail_value).resolve() if tail_value else None
    if tail is not None and (
        not tail.is_file() or not expected_tail_hash
        or _file_sha256(tail) != expected_tail_hash
    ):
        raise ValueError("provider original tail is missing or changed")
    technical_receipt_sha256 = (
        record.get("technical_receipt_sha256") or _file_sha256(receipt_path)
    )
    validate_source_bindings(record)
    candidate_identity = _candidate_identity(record, receipt_path)
    candidate_identity_sha256 = hashlib.sha256(
        json.dumps(candidate_identity, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema": "media_user_review/v1",
        "decision": decision,
        "decision_source": "explicit_user_statement",
        "user_statement": user_statement,
        "source_receipt": str(receipt_path),
        "source_receipt_sha256": technical_receipt_sha256,
        "candidate_identity": candidate_identity,
        "candidate_identity_sha256": candidate_identity_sha256,
        "original_video": str(video),
        "original_video_sha256": expected_video_hash,
        "raw_tail": str(tail) if tail else None,
        "raw_tail_sha256": expected_tail_hash,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "automated_visual_or_voice_verdict": False,
    }
    review_path = receipt_path.with_name(
        receipt_path.stem + ".human_review.json"
    )
    if review_path.exists():
        existing = _read(review_path)
        stable_keys = (
            "schema", "decision", "decision_source", "user_statement",
            "source_receipt", "source_receipt_sha256", "original_video",
            "candidate_identity", "candidate_identity_sha256",
            "original_video_sha256", "raw_tail", "raw_tail_sha256",
            "automated_visual_or_voice_verdict",
        )
        if any(existing.get(key) != payload.get(key) for key in stable_keys):
            raise RuntimeError("a different user decision is already bound")
        payload = existing
    else:
        _write_atomic(review_path, payload)
    record["content_status"] = decision
    record["technical_receipt_sha256"] = technical_receipt_sha256
    record["approved_candidate_identity_sha256"] = candidate_identity_sha256
    record["user_decision_source"] = str(review_path)
    record["user_decision_sha256"] = _file_sha256(review_path)
    _write_atomic(receipt_path, record)
    return payload


def validate_user_approved_candidate(review_path: Path) -> dict[str, Any]:
    """Return an approved raw-tail binding or fail closed."""
    review_path = Path(review_path).resolve()
    review = _read(review_path)
    if (review.get("schema") != "media_user_review/v1"
            or review.get("decision") != "approved"
            or review.get("decision_source") != "explicit_user_statement"
            or review.get("automated_visual_or_voice_verdict") is not False):
        raise ValueError("continuation requires an explicit approved user review")
    source_receipt = Path(review.get("source_receipt", "")).resolve()
    if not source_receipt.is_file():
        raise ValueError("approved source receipt changed")
    record = _read(source_receipt)
    validate_source_bindings(record)
    current_candidate_identity = _candidate_identity(record, source_receipt)
    current_candidate_identity_sha256 = hashlib.sha256(
        json.dumps(current_candidate_identity, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (record.get("technical_receipt_sha256") != review.get("source_receipt_sha256")
            or record.get("content_status") != "approved"
            or record.get("user_decision_source") != str(review_path)
            or record.get("user_decision_sha256") != _file_sha256(review_path)
            or record.get("approved_candidate_identity_sha256")
            != review.get("candidate_identity_sha256")
            or current_candidate_identity != review.get("candidate_identity")
            or current_candidate_identity_sha256 != review.get("candidate_identity_sha256")):
        raise ValueError("approved decision is not current on the source receipt")
    video = Path(review.get("original_video", "")).resolve()
    if (not video.is_file()
            or _file_sha256(video) != review.get("original_video_sha256")):
        raise ValueError("approved original video changed")
    return review


def validate_approved_tail(review_path: Path, *, expected_tail_path: Path | None = None) -> dict[str, str]:
    review = validate_user_approved_candidate(review_path)
    tail = Path(review.get("raw_tail") or "").resolve()
    if (not tail.is_file()
            or _file_sha256(tail) != review.get("raw_tail_sha256")):
        raise ValueError("approved provider raw tail changed")
    if expected_tail_path is not None and tail != Path(expected_tail_path).resolve():
        raise ValueError("continuation first frame is not the approved raw tail")
    return {"path": str(tail), "sha256": review["raw_tail_sha256"]}


def validate_source_bindings(record):
    """Legacy media stays byte-bound; new media additionally binds its source chain."""
    for binding in record.get('source_bindings', {}).values():
        path = Path(binding['path'])
        if not path.is_file() or _file_sha256(path) != binding['sha256']:
            raise ValueError('media source lineage changed')
    if record.get('request_sha256'):
        from .creative_stage_contracts import digest
        if digest(record.get('request')) != record['request_sha256']:
            raise ValueError('stored media request changed')
    plan = record.get('plan')
    if plan and record.get('plan_sha256'):
        if not Path(plan).is_file() or _file_sha256(Path(plan)) != record['plan_sha256']:
            raise ValueError('submitted media plan changed')
        if record.get('plan_snapshot') is not None and _read(Path(plan)) != record['plan_snapshot']:
            raise ValueError('stored media plan snapshot changed')


def record_user_media_decision(receipt_path: Path, decision: str, user_statement: str) -> dict[str, Any]:
    """Serialize explicit decisions; conflicting writers cannot replace a review."""
    receipt_path = Path(receipt_path).resolve()
    lock = receipt_path.with_name(receipt_path.name + '.human_review.lock')
    with lock.open('x', encoding='utf-8') as stream:
        stream.write('exclusive human decision writer')
    try:
        return _record_user_media_decision(receipt_path, decision, user_statement)
    finally:
        lock.unlink()
