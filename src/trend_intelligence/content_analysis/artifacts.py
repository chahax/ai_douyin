"""Content-addressed evidence helpers shared by local inference and its adapter."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be an object: {path}")
    return value


def write_json(path: str | Path, value: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def parse_model_json(answer: str) -> dict:
    """A prose/truncated answer must not be upgraded into successful analysis."""
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


def transcript_evidence(payload: dict) -> list[dict]:
    """Keep actual sentence/character timestamps; never invent timing from length."""
    evidence: list[dict] = []
    for entry in payload.get("result") or []:
        if not isinstance(entry, dict):
            continue
        sentences = entry.get("sentence_info") or []
        if sentences:
            for sentence in sentences:
                if not isinstance(sentence, dict) or not str(sentence.get("text") or "").strip():
                    continue
                if sentence.get("start") is None or sentence.get("end") is None:
                    continue
                evidence.append({"channel": "asr", "text": str(sentence["text"]),
                                 "start_seconds": float(sentence["start"]) / 1000,
                                 "end_seconds": float(sentence["end"]) / 1000})
        else:
            text = str(entry.get("text") or "").strip()
            timestamps = entry.get("timestamp") or []
            valid = [pair for pair in timestamps if isinstance(pair, list) and len(pair) == 2]
            if text and valid:
                tokens = text.split()
                if len(tokens) != len(valid):
                    tokens = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+", text)
                if len(tokens) != len(valid):
                    # Mixed-language tokenizer alignment is unknown. Retain
                    # the real outer boundaries without inventing word timing.
                    evidence.append({"channel": "asr", "text": text,
                                     "start_seconds": float(valid[0][0]) / 1000,
                                     "end_seconds": float(valid[-1][1]) / 1000})
                    continue
                start = 0
                for index in range(len(tokens)):
                    elapsed = float(valid[index][1]) - float(valid[start][0])
                    pause = float(valid[index + 1][0]) - float(valid[index][1]) if index + 1 < len(tokens) else 0
                    if index + 1 == len(tokens) or pause >= 350 or elapsed >= 4000 or index - start >= 23:
                        words = tokens[start:index + 1]
                        fragment = "".join(words) if all(re.fullmatch(r"[\u3400-\u9fff]", w) for w in words) else " ".join(words)
                        evidence.append({"channel": "asr", "text": fragment,
                                         "start_seconds": float(valid[start][0]) / 1000,
                                         "end_seconds": float(valid[index][1]) / 1000})
                        start = index + 1
    for index, item in enumerate(evidence, 1):
        item["id"] = f"A{index:04d}"
    return evidence


def validate_expression(value: dict, evidence: list[dict], duration: float) -> dict:
    """Require every stated expression finding to cite available media evidence."""
    if value.get("schema") != "video_expression_analysis/v1":
        raise ValueError("missing video_expression_analysis/v1 result")
    known = {item["id"]: item for item in evidence}
    if not known:
        raise ValueError("expression analysis has no media evidence")
    for item in evidence:
        start, end = item.get("start_seconds"), item.get("end_seconds")
        if start is None or end is None or not 0 <= start <= end <= duration + .2:
            raise ValueError("media evidence timestamp outside source video")
    modes = value.get("expression_modes")
    allowed_modes = {"prop_demonstration", "conflict_drama", "direct_explanation", "question_answer",
                     "case_reenactment", "screen_demonstration", "text_cards", "interview", "mixed", "unknown"}
    if (not isinstance(modes, list) or not modes
            or any(not isinstance(item, dict) or set(item) != {"mode", "evidence_ids"}
                   or item.get("mode") not in allowed_modes or not isinstance(item.get("evidence_ids"), list)
                   for item in modes)):
        raise ValueError("expression_modes must be nonempty mode/evidence_ids objects with valid mode names")
    if len({item["mode"] for item in modes}) != len(modes):
        raise ValueError("expression_modes contains duplicate modes")

    def visit(node: Any, path: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]")
        elif isinstance(node, dict):
            meaningful = any(str(node.get(key) or "").strip() for key in ("text", "mode", "goal"))
            refs = node.get("evidence_ids") or []
            if meaningful and (not refs or any(ref not in known for ref in refs)):
                raise ValueError(f"{path}: expression claim lacks valid media evidence references for {node.get('text') or node.get('goal') or node.get('mode')!r}")
            for key, child in node.items():
                if key != "evidence":
                    visit(child, f"{path}.{key}")

    for key in ("core_message", "expression_modes", "visual_expression", "audio_expression", "conflict"):
        if key not in value:
            raise ValueError(f"expression analysis missing {key}")
        visit(value[key], key)
    if not str(value["core_message"].get("text") or "").strip():
        raise ValueError("expression core message is empty")
    if value["conflict"].get("status") not in {"observed", "not_observed", "unknown"}:
        raise ValueError("invalid observed conflict status")
    for key in ("trigger", "opposition", "stakes", "turning_point", "resolution"):
        if key in value["conflict"] and not isinstance(value["conflict"][key], dict):
            raise ValueError(f"conflict.{key} must be a text/evidence_ids object, including when empty")
    # Evidence text/timestamps are owned by the extraction passes, not synthesis.
    return {**value, "evidence": evidence}


def verify_expression_evidence(expression: dict, frame_manifest: dict, transcript_payload: dict,
                               *, visual_batches: list[dict] | None = None,
                               observation_review: str | Path | dict | None = None) -> None:
    """Verify the evidence graph against independent extraction artifacts.

    Synthesis cannot invent frame times, rewrite recognized words, add an ASR
    sentence or cite a real frame ID for a different point in the video.
    """
    frames = frame_manifest.get("frames") or []
    expected_frames = {frame["id"]: frame for frame in frames}
    if len(expected_frames) != len(frames) or not frames:
        raise ValueError("frame manifest needs unique nonempty frame IDs")
    rows = expression.get("evidence") or []
    actual = {item.get("id"): item for item in rows if isinstance(item, dict)}
    if len(actual) != len(rows):
        raise ValueError("expression evidence IDs are not unique")
    visuals = {key: item for key, item in actual.items() if item.get("channel") == "visual"}
    if set(visuals) != set(expected_frames):
        raise ValueError("visual evidence IDs do not match the analyzed frame manifest")
    observed_text = None
    if visual_batches is not None:
        observations = [item for batch in visual_batches for item in batch.get("observations") or []]
        observed_text = {str(item.get("frame_id")): str(item.get("event") or "").strip() for item in observations}
        if len(observed_text) != len(observations) or set(observed_text) != set(expected_frames):
            raise ValueError("Qwen observations do not cover exactly the frame manifest IDs")
    if observation_review is not None:
        if visual_batches is None:
            raise ValueError("reviewed observations require original visual batches")
        from .reviewed_observations import apply_reviewed_observations
        reviewed = apply_reviewed_observations(frame_manifest, visual_batches, observation_review)
        observed_text = {item["id"]: item["text"] for item in reviewed["evidence"]}
    for key, item in visuals.items():
        time = expected_frames[key]["time_seconds"]
        if item.get("start_seconds") != time or item.get("end_seconds") != time:
            raise ValueError(f"visual evidence {key} timestamp differs from the decoded frame")
        if observed_text is not None and item.get("text") != observed_text[key]:
            raise ValueError(f"visual evidence {key} differs from Qwen frame observation")
    expected_asr = {item["id"]: item for item in transcript_evidence(transcript_payload)}
    actual_asr = {key: item for key, item in actual.items() if item.get("channel") == "asr"}
    if set(actual_asr) != set(expected_asr):
        raise ValueError("ASR evidence IDs differ from timestamped transcript evidence")
    for key, item in actual_asr.items():
        if any(item.get(field) != expected_asr[key][field]
               for field in ("channel", "text", "start_seconds", "end_seconds")):
            raise ValueError(f"ASR evidence {key} differs from the actual timestamped transcript")
    if set(actual) != set(visuals) | set(actual_asr):
        raise ValueError("expression contains unsupported media evidence channel")


def require_no_semantic_rejection(qwen_path: str | Path, *, rejection_root: str | Path | None = None) -> None:
    """Block an observed semantic failure permanently for that exact artifact.

    Absence of a review means an automatic candidate, not approval or rejection.
    A rejected artifact must be replaced by a separately generated/corrected
    artifact; changing its nearby review to 'passed' cannot release the old SHA.
    """
    artifact = Path(qwen_path).resolve()
    digest = sha256(artifact)
    root = Path(rejection_root or Path(__file__).resolve().parents[3] /
                "data/video_analysis/semantic_rejections").resolve()
    marker = root / f"{digest}.json"
    if marker.is_file():
        record = read_json(marker)
        if record.get("artifact_sha256") != digest or record.get("decision") != "failed":
            raise ValueError("semantic rejection registry was changed; cannot release this artifact")
        raise ValueError(f"known semantic failure for Qwen artifact {digest[:12]}; regenerate the expression before script generation")
    review_path = artifact.with_name("semantic_review.json")
    if not review_path.is_file():
        return
    review = read_json(review_path)
    if review.get("artifact_sha256") != digest:
        return  # Review belongs to a different candidate; never transfer approval.
    if review.get("decision") != "failed" and not review.get("blocked_for_script_generation"):
        return
    if review.get("schema") != "source_expression_semantic_review/v1":
        raise ValueError("bound semantic rejection has an invalid review schema")
    write_json(marker, {
        "schema": "source_expression_semantic_rejection/v1", "artifact_sha256": digest,
        "artifact_path_at_rejection": str(artifact), "decision": "failed",
        "blocked_for_script_generation": True, "review_path": str(review_path),
        "review_sha256": sha256(review_path), "review": review,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "release_policy": "This exact artifact SHA remains rejected; a new expression artifact and independent review are required.",
    })
    raise ValueError(f"known semantic failure for Qwen artifact {digest[:12]}; regenerate the expression before script generation")
