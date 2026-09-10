"""Source-bound corrections from direct frame review, separate from raw model output.

This validates provenance and scope, not whether a reviewer's interpretation is
true. The corrected observations still require model synthesis and independent
semantic review before a script can use the resulting expression analysis.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

from .artifacts import parse_model_json, read_json, sha256

REVIEW_SCHEMA = "source_visual_observation_review/v1"
_HASH = re.compile(r"[0-9a-f]{64}")


def _bound_file(value: dict, *, label: str, allowed_keys: set[str] | None = None) -> tuple[Path, str]:
    if not isinstance(value, dict) or set(value) != (allowed_keys or {"path", "sha256"}):
        raise ValueError(f"{label} needs an exact path/SHA binding")
    if not isinstance(value.get("path"), str) or not Path(value["path"]).is_absolute():
        raise ValueError(f"{label} needs an absolute artifact path")
    digest = value.get("sha256")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ValueError(f"{label} has an invalid SHA256")
    path = Path(value["path"]).resolve()
    if not path.is_file() or sha256(path) != digest:
        raise ValueError(f"{label} artifact SHA256 changed or file is missing")
    return path, digest


def _observations(batches: list[dict]) -> dict[str, str]:
    rows = {}
    for batch in batches:
        if not isinstance(batch, dict) or not isinstance(batch.get("observations"), list):
            raise ValueError("review requires actual visual observation batches")
        for item in batch["observations"]:
            if not isinstance(item, dict):
                raise ValueError("invalid visual observation")
            frame_id, event = item.get("frame_id"), item.get("event")
            if not isinstance(frame_id, str) or not isinstance(event, str) or not event.strip() or frame_id in rows:
                raise ValueError("raw visual observations need unique IDs and nonempty text")
            rows[frame_id] = event.strip()
    return rows


def apply_reviewed_observations(frame_manifest: dict, visual_batches: list[dict],
                                observation_review: str | Path | dict) -> dict:
    """Return ``evidence`` and immutable ``review`` binding without mutating batches.

    Initial opt-in accepts a review path. Persist ``result['review']`` in the
    generated Qwen artifact and pass it on subsequent validation; its SHA binds
    the exact reviewed corrections. Corrections change visual text only.
    """
    if isinstance(observation_review, (str, Path)):
        review_path = Path(observation_review).resolve()
        review_hash = sha256(review_path)
    else:
        review_path, review_hash = _bound_file(observation_review, label="observation review")
    review = read_json(review_path)
    required = {"schema", "source_video_sha256", "frame_manifest", "original_artifacts",
                "corrections", "scope_limitations"}
    if set(review) != required or review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("invalid source visual observation review schema or fields")
    manifest_path, manifest_hash = _bound_file(review["frame_manifest"], label="review frame manifest")
    if read_json(manifest_path) != frame_manifest or frame_manifest.get("schema") != "local_video_frame_manifest/v2":
        raise ValueError("review is bound to a different frame manifest")
    source_hash = review["source_video_sha256"]
    if (not isinstance(source_hash, str) or not _HASH.fullmatch(source_hash) or
            frame_manifest.get("source_video_sha256") != source_hash or
            sha256(frame_manifest["source_video_path"]) != source_hash):
        raise ValueError("review source video SHA256 differs from the actual source")
    frames = frame_manifest.get("frames") or []
    by_id = {frame["id"]: frame for frame in frames}
    raw = _observations(visual_batches)
    if not frames or len(by_id) != len(frames) or set(raw) != set(by_id):
        raise ValueError("review raw observations must cover exactly the source frame IDs")
    for frame in frames:
        second = frame.get("time_seconds")
        if (isinstance(second, bool) or not isinstance(second, (int, float)) or not math.isfinite(second)
                or not 0 <= second <= float(frame_manifest["duration_seconds"]) + .2):
            raise ValueError("review frame timestamp is invalid")
        if sha256(frame["path"]) != frame["sha256"]:
            raise ValueError("review sampled frame SHA256 changed")

    original_artifacts = review["original_artifacts"]
    if not isinstance(original_artifacts, list) or not original_artifacts:
        raise ValueError("review requires original Qwen artifacts")
    anchored = {}
    seen_artifacts = set()
    for binding in original_artifacts:
        path, digest = _bound_file(binding, label="original visual", allowed_keys={"kind", "path", "sha256"})
        if (str(path), digest) in seen_artifacts:
            raise ValueError("duplicate original visual artifact")
        seen_artifacts.add((str(path), digest))
        payload = read_json(path)
        kind = binding["kind"]
        if kind == "qwen_analysis":
            if (payload.get("schema") != "local_qwen_frame_analysis/v2" or
                    payload.get("source_video_sha256") != source_hash or
                    payload.get("frame_manifest_sha256") != manifest_hash):
                raise ValueError("original Qwen analysis is bound to different source frames")
            rows = _observations(payload.get("batches") or [])
            if set(rows) != set(by_id):
                raise ValueError("original Qwen analysis has incomplete frame observations")
        elif kind == "qwen_visual_response":
            rows = _observations([parse_model_json(payload.get("answer") or "")])
            inputs = payload.get("input") or []
            input_frames = []
            for index, content in enumerate(inputs):
                if not isinstance(content, dict) or content.get("type") != "image":
                    continue
                preceding = inputs[index - 1] if index else {}
                matches = [frame for frame in frames if
                           str(Path(content.get("image") or "").resolve()) == str(Path(frame["path"]).resolve())
                           and preceding == {"type": "text", "text": f"{frame['id']}，{frame['time_seconds']:.3f}秒"}]
                if len(matches) != 1:
                    raise ValueError("original Qwen response image/time binding differs from reviewed frames")
                input_frames.append(matches[0]["id"])
            if len(input_frames) != len(set(input_frames)) or set(input_frames) != set(rows):
                raise ValueError("original Qwen response does not bind its observed input frames")
        else:
            raise ValueError("unsupported original visual artifact kind")
        for frame_id, event in rows.items():
            if frame_id not in raw or raw[frame_id] != event:
                raise ValueError("review raw batches differ from the original Qwen observation")
            if frame_id in anchored and anchored[frame_id] != event:
                raise ValueError("original visual artifacts disagree")
            anchored[frame_id] = event
    if set(anchored) != set(raw):
        raise ValueError("original visual artifacts must bind every raw frame observation")

    limitations = review["scope_limitations"]
    if not isinstance(limitations, list) or not limitations or not all(isinstance(text, str) and text.strip() for text in limitations):
        raise ValueError("review must state the limitations of direct frame inspection")
    corrections = review["corrections"]
    if not isinstance(corrections, list) or not corrections:
        raise ValueError("observation review must contain explicit visual corrections")
    revised = dict(raw)
    corrected_ids = set()
    correction_fields = {"frame_id", "frame_sha256", "time_seconds", "original_text", "corrected_text",
                         "review_reason", "reviewer", "reviewed_at"}
    for correction in corrections:
        if not isinstance(correction, dict) or set(correction) != correction_fields:
            raise ValueError("review correction fields permit visual text changes only")
        frame_id = correction["frame_id"]
        if frame_id not in by_id or frame_id not in anchored or frame_id in corrected_ids:
            raise ValueError("review correction frame must have one original visual artifact binding")
        frame = by_id[frame_id]
        if (correction["frame_sha256"] != frame["sha256"] or
                isinstance(correction["time_seconds"], bool) or correction["time_seconds"] != frame["time_seconds"]):
            raise ValueError("review correction cannot change frame bytes or timestamps")
        if correction["original_text"] != raw[frame_id]:
            raise ValueError("review original_text differs from actual Qwen observation")
        for key in ("corrected_text", "review_reason", "reviewer", "reviewed_at"):
            if not isinstance(correction[key], str) or not correction[key].strip():
                raise ValueError(f"review correction needs {key}")
        if correction["corrected_text"] == correction["original_text"]:
            raise ValueError("review correction must state an actual observation change")
        try:
            reviewed_at = datetime.fromisoformat(correction["reviewed_at"])
        except ValueError as exc:
            raise ValueError("reviewed_at must be an explicit timezone-aware timestamp") from exc
        if reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be an explicit timezone-aware timestamp")
        revised[frame_id] = correction["corrected_text"]
        corrected_ids.add(frame_id)
    return {
        "evidence": [{"id": frame["id"], "channel": "visual", "start_seconds": frame["time_seconds"],
                      "end_seconds": frame["time_seconds"], "text": revised[frame["id"]]} for frame in frames],
        # The exact review file retains reviewer/reason/original/correction/scope
        # details. Keep this binding minimal for strict reload validation.
        "review": {"path": str(review_path), "sha256": review_hash},
    }
