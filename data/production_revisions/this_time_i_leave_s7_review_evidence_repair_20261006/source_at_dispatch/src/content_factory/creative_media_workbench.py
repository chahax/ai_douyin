"""Source-bound media workbench. No frame extraction or content verdicts."""

from pathlib import Path
import hashlib
from .creative_stage_contracts import digest, persist, read
from .media_review_policy import (
    record_user_media_decision,
    validate_source_bindings,
    validate_approved_tail,
    validate_user_approved_candidate,
)


def file_binding(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def register_preview(run_dir, plan_path, *, source_paths, text_gate):
    root = Path(run_dir).resolve()
    state = read(root / "state.json")
    from .creative_stage_debug import pending_must_fix_feedback

    if pending_must_fix_feedback(state) or any(
        v in ("invalidated", "needs_revision")
        for v in state.get("debug_stage_validity", {}).values()
    ):
        raise ValueError(
            "unresolved text feedback blocks current media request preview"
        )
    if text_gate != "text_review_gate_satisfied":
        raise ValueError("text review gate is pending")
    plan = read(plan_path)
    binding = {
        "schema": "creative_media_request_chain/v1",
        "source_run": str(root),
        "plan": file_binding(plan_path),
        "sources": {k: file_binding(p) for k, p in source_paths.items()},
        "request": plan,
        "text_gate": text_gate,
        "automatic_submit": False,
    }
    key = digest(binding)
    persist(
        root / ".creative_debug/media/previews" / (key + ".json"),
        binding,
        immutable=True,
    )
    persist(root / ".creative_debug/media/current_preview.json", {"chain_sha256": key})
    return binding


def register_candidate(run_dir, receipt_path, *, expected_plan_sha256=None):
    root = Path(run_dir).resolve()
    record = read(receipt_path)
    if record.get("technical_status") != "succeeded":
        raise ValueError("only durably saved candidates can enter human review")
    video = file_binding(record["video_path"])
    if video["sha256"] != record.get("video_sha256"):
        raise ValueError("candidate video changed")
    validate_source_bindings(record)
    if expected_plan_sha256 and record.get("plan_sha256") != expected_plan_sha256:
        raise ValueError("candidate differs from request preview")
    segment = record.get("segment_id") or record.get("shot_id") or "final"
    row = {
        "schema": "creative_media_candidate_binding/v1",
        "segment_id": segment,
        "candidate_receipt": str(Path(receipt_path).resolve()),
        "video": video,
        "plan_sha256": record.get("plan_sha256"),
        "source_bindings": record.get("source_bindings", {}),
        "task_id": record.get("task_id"),
        "candidate_id": digest(
            {
                "receipt": str(Path(receipt_path).resolve()),
                "video": video,
                "plan": record.get("plan_sha256"),
            }
        ),
    }
    persist(
        root / ".creative_debug/media/candidates" / (row["candidate_id"] + ".json"),
        row,
        immutable=True,
    )
    index_path = root / ".creative_debug/media/index.json"
    index = (
        read(index_path)
        if index_path.exists()
        else {"schema": "creative_media_index/v1", "current": {}, "history": []}
    )
    if row["candidate_id"] not in index["history"]:
        index["history"].append(row["candidate_id"])
    index["current"][segment] = row["candidate_id"]
    persist(index_path, index)
    return row


def inspect_media(run_dir):
    root = Path(run_dir) / ".creative_debug/media"
    index = (
        read(root / "index.json")
        if (root / "index.json").exists()
        else {"current": {}, "history": []}
    )
    rows = []
    for segment, key in index["current"].items():
        binding = read(root / "candidates" / (key + ".json"))
        record = read(binding["candidate_receipt"])
        stale = None
        try:
            validate_source_bindings(record)
            if (
                file_binding(record["video_path"])["sha256"]
                != binding["video"]["sha256"]
            ):
                raise ValueError("candidate video changed")
        except (OSError, ValueError) as exc:
            stale = str(exc)
        rows.append(
            {
                **binding,
                "content_status": record.get("content_status"),
                "stale_reason": stale,
            }
        )
    return {"current": rows, "history": index["history"]}


def media_feedback(
    run_dir,
    candidate_id,
    decision,
    statement,
    *,
    video_sha256,
    time_range=None,
    responsible_stage=None,
    stage_output_sha256=None,
    evidence=None,
):
    import re

    if not re.fullmatch("[0-9a-f]{64}", candidate_id):
        raise ValueError("invalid candidate ID")
    root = Path(run_dir).resolve()
    index = read(root / ".creative_debug/media/index.json")
    binding = read(root / ".creative_debug/media/candidates" / (candidate_id + ".json"))
    if (
        index["current"].get(binding["segment_id"]) != candidate_id
        or binding["video"]["sha256"] != video_sha256
    ):
        raise ValueError(
            "displayed candidate is historical or changed; refresh before feedback"
        )
    if time_range is not None:
        import math

        if (
            len(time_range) != 2
            or any(
                isinstance(x, bool) or not isinstance(x, (int, float))
                for x in time_range
            )
            or not all(math.isfinite(x) for x in time_range)
            or not 0 <= time_range[0] <= time_range[1]
        ):
            raise ValueError("invalid media feedback time range")
    if responsible_stage:
        from .creative_stage_debug import CreativeStageCommandService

        selected = next(
            (
                x
                for x in CreativeStageCommandService(root).inspect()["stages"]
                if x["stage_id"] == responsible_stage
            ),
            None,
        )
        if (
            not evidence
            or selected is None
            or selected["output_sha256"] != stage_output_sha256
        ):
            raise ValueError(
                "responsibility routing needs current stage hash and explicit evidence"
            )
    receipt_path = Path(binding["candidate_receipt"])
    source = read(receipt_path)
    prior_review = source.get("user_decision_source")
    decision_statement = (
        read(prior_review)["user_statement"]
        if prior_review and source.get("content_status") == decision
        else statement
    )
    review = record_user_media_decision(receipt_path, decision, decision_statement)
    feedback = {
        "schema": "creative_media_feedback/v1",
        "candidate_id": candidate_id,
        "video_sha256": video_sha256,
        "segment_id": binding["segment_id"],
        "time_range_seconds": time_range,
        "source_bindings": binding["source_bindings"],
        "user_review_sha256": digest(review),
        "decision": decision,
        "message": statement,
        "responsible_stage": responsible_stage,
        "stage_output_sha256": stage_output_sha256,
        "evidence": evidence or [],
        "next_action": "continue_after_human_approval"
        if decision == "approved"
        else "revise_responsible_stage"
        if responsible_stage
        else "needs_responsibility_evidence",
        "automatic_regeneration": False,
    }
    if decision == "rejected" and responsible_stage:
        feedback["stage_feedback"] = CreativeStageCommandService(root).feedback(
            responsible_stage,
            statement,
            expected_output_sha256=stage_output_sha256,
            evidence=[
                {
                    "media_candidate_id": candidate_id,
                    "time_range_seconds": time_range,
                    "video_sha256": video_sha256,
                    "responsibility_evidence": evidence,
                }
            ],
        )
    persist(
        root / ".creative_debug/media/feedback" / (digest(feedback) + ".json"),
        feedback,
        immutable=True,
    )
    return feedback


def approved_chain(segment_ids, reviews):
    if len(segment_ids) != len(set(segment_ids)) or len(reviews) != len(segment_ids):
        raise ValueError("assembly requires an explicit unique complete segment order")
    chain = []
    for segment, review_path in zip(segment_ids, reviews):
        review = validate_user_approved_candidate(review_path)
        if review["candidate_identity"]["identifiers"].get("segment_id") != segment:
            raise ValueError("approved segment order differs from assembly plan")
        source = read(review["source_receipt"])
        declared_order = source.get("plan_snapshot", {}).get("segment_order")
        if declared_order and declared_order != segment_ids:
            raise ValueError(
                "assembly order differs from the reviewed source-version plan"
            )
        chain.append(
            {
                "segment_id": segment,
                "review": file_binding(review_path),
                "video": file_binding(review["original_video"]),
            }
        )
    return {
        "schema": "creative_approved_assembly_chain/v1",
        "segments": chain,
        "next_action": "existing_assembler_then_full_film_human_review",
        "content_status": "awaiting_human_review",
    }


def approved_predecessor(segment_ids, next_segment, review_path):
    position = segment_ids.index(next_segment)
    review = validate_user_approved_candidate(review_path)
    if (
        position < 1
        or review["candidate_identity"]["identifiers"].get("segment_id")
        != segment_ids[position - 1]
    ):
        raise ValueError(
            "continuation requires the immediately preceding approved segment"
        )
    return validate_approved_tail(review_path)


def prepare_segment(
    run_dir,
    compiled_plan,
    segment_id,
    output,
    *,
    first_frame=None,
    first_frame_review=None,
    predecessor_review=None,
    seed=20261002,
):
    root = Path(run_dir).resolve()
    preview_root = root / ".creative_debug/media"
    key = read(preview_root / "current_preview.json")["chain_sha256"]
    preview = read(preview_root / "previews" / (key + ".json"))
    if file_binding(compiled_plan) != preview["plan"]:
        raise ValueError("compiled request differs from the current verified preview")
    for source in preview["sources"].values():
        if file_binding(source["path"]) != source:
            raise ValueError("preview source changed")
    state = read(root / "state.json")
    from .creative_stage_debug import pending_must_fix_feedback

    if pending_must_fix_feedback(state) or any(
        v in ("invalidated", "needs_revision")
        for v in state.get("debug_stage_validity", {}).values()
    ):
        raise ValueError("text feedback blocks preparing a media execution plan")
    compiled = read(compiled_plan)
    segments = compiled["segments"]
    order = [row["segment_id"] for row in segments]
    selected = next((row for row in segments if row["segment_id"] == segment_id), None)
    if (
        selected is None
        or not selected.get("payload_template")
        or selected["shot_id"] in compiled["blocked_shots"]
    ):
        raise ValueError("segment is not supported by the verified media adapter")
    if order.index(segment_id) > 0:
        if not predecessor_review:
            raise ValueError("preceding segment requires explicit human approval")
        predecessor = validate_user_approved_candidate(predecessor_review)
        prior = read(predecessor["source_receipt"])
        if prior.get("source_bindings", {}).get("compiled_plan") != preview["plan"]:
            raise ValueError(
                "preceding approval belongs to another source-version chain"
            )
        if (
            predecessor["candidate_identity"]["identifiers"].get("segment_id")
            != order[order.index(segment_id) - 1]
        ):
            raise ValueError(
                "cut or continuation needs the immediately preceding approval"
            )
        if selected["continuity_mode"] == "raw_tail_continuation":
            first_frame = approved_predecessor(order, segment_id, predecessor_review)[
                "path"
            ]
            frame_review = {"predecessor_review": file_binding(predecessor_review)}
            frame_source = "preceding_approved_raw_tail"
        else:
            if not first_frame or not first_frame_review:
                raise ValueError(
                    "planned cut needs a separately reviewed new-camera opening"
                )
            frame_review = {
                "predecessor_review": file_binding(predecessor_review),
                "first_frame_review": file_binding(first_frame_review),
            }
            frame_source = "reviewed_new_camera_opening_frame"
    else:
        if not first_frame or not first_frame_review:
            raise ValueError("opening needs a reviewed local first frame")
        frame_review = {"first_frame_review": file_binding(first_frame_review)}
        frame_source = "reviewed_opening_frame"
    template = selected["payload_template"]
    value = {
        "schema": "creative_seedance_segment_plan/v1",
        "source_run": str(root),
        "segment_id": segment_id,
        "shot_id": selected["shot_id"],
        "segment_order": order,
        "logical_task_id": state.get("logical_task_id"),
        "provider": compiled["provider"],
        "model": compiled["model"],
        "duration_seconds": selected["duration_seconds"],
        "ratio": compiled["ratio"],
        "resolution": compiled["resolution"],
        "seed": seed,
        "prompt": next(x["text"] for x in template["content"] if x["type"] == "text"),
        "payload_template": template,
        "payload_template_sha256": digest(template),
        "cut_adapter_version": "native_audio_concat_human_review/v1",
        "request_chain_sha256": key,
        "sources": {**preview["sources"], "compiled_plan": preview["plan"]},
        "first_frame": file_binding(first_frame),
        "opening_frame_source": frame_source,
        **frame_review,
    }
    from .creative_segment_execution import validate

    persist(output, value, immutable=True)
    validate(output)
    return value


def assemble_approved(chain_path, output_dir, *, runner=None):
    """Reuse the native audio concat recipe, then stop for full-film human review."""
    import subprocess

    runner = runner or subprocess.run
    chain = read(chain_path)
    verified = approved_chain(
        [r["segment_id"] for r in chain["segments"]],
        [r["review"]["path"] for r in chain["segments"]],
    )
    if chain != verified:
        raise ValueError("approved assembly inputs changed")
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = out / "receipt.json"
    with receipt.open("x", encoding="utf-8") as stream:
        __import__("json").dump(
            {
                "schema": "creative_assembly_receipt/v1",
                "technical_status": "running",
                "content_status": "not_available",
                "chain": file_binding(chain_path),
            },
            stream,
        )
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n"]
    filters = []
    concat = ""
    sources = {"assembly_chain": file_binding(chain_path)}
    for i, row in enumerate(chain["segments"]):
        args += ["-i", row["video"]["path"]]
        filters += [
            f"[{i}:v]setpts=PTS-STARTPTS,fps=30,setsar=1[v{i}]",
            f"[{i}:a]asetpts=PTS-STARTPTS,aresample=48000[a{i}]",
        ]
        concat += f"[v{i}][a{i}]"
        sources[row["segment_id"] + "_video"] = row["video"]
        sources[row["segment_id"] + "_review"] = row["review"]
        reviewed = read(row["review"]["path"])
        record = read(reviewed["source_receipt"])
        sources.update(
            {
                row["segment_id"] + "_" + k: v
                for k, v in record.get("source_bindings", {}).items()
            }
        )
    filters += [concat + f"concat=n={len(chain['segments'])}:v=1:a=1[v][a]"]
    video = out / "full_film_candidate.mp4"
    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(video),
    ]
    try:
        runner(args, check=True, capture_output=True)
        if not video.is_file() or video.stat().st_size == 0:
            raise ValueError("assembled candidate is missing or empty")
        from .media_review_policy import mark_saved_candidate

        result = {
            "schema": "creative_assembly_receipt/v1",
            "segment_id": "final",
            "video_path": str(video),
            "video_sha256": file_binding(video)["sha256"],
            "source_bindings": sources,
            "audio_note": "source native audio retained; no content approval",
            "assembly_chain": chain,
        }
        mark_saved_candidate(result)
        persist(receipt, result)
        return result
    except Exception as exc:
        persist(
            receipt,
            {
                "schema": "creative_assembly_receipt/v1",
                "technical_status": "failed",
                "content_status": "not_available",
                "error": str(exc),
                "chain": file_binding(chain_path),
            },
        )
        raise
