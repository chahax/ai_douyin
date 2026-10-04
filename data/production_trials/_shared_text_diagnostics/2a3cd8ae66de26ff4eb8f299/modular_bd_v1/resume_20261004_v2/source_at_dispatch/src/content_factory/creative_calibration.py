"""Bind actual assistant editorial review to a completed first text draft."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from itertools import takewhile
from pathlib import Path
from typing import Any

from .creative_workflow_contract import PROMPTS, WRITER_TOOL_SCHEMAS


CATEGORIES = ("campus_novel", "other_genre_novel", "video_original")
OUTCOMES = ("passed", "major_issues")
_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_FILES = (
    "src/content_factory/creative_workflow.py",
    "src/content_factory/creative_workflow_contract.py",
    "src/content_factory/creative_workflow_inputs.py",
    "src/content_factory/creative_workflow_roles.py",
    "src/content_factory/creative_calibration.py",
    "src/content_factory/creative_brief.py",
    "src/content_factory/reusable_production.py",
)


def revision_artifact(run_dir: Path, kind: str, round_index: int) -> Path:
    """Keep the first published names stable and give later rounds immutable files."""
    if kind not in (
        "FEEDBACK",
        "REVISION_DRAFT",
        "REVISION_REVIEW",
    ) or round_index not in (1, 2):
        raise ValueError("助手返修产物类型或轮次无效")
    suffix = "" if round_index == 1 else "__02"
    return Path(run_dir) / f"ASSISTANT_{kind}{suffix}.json"


def _revision_index(state: dict[str, Any]) -> int:
    index = state.get("assistant_revision_round_index", 1)
    if type(index) is not int or index not in (1, 2):
        raise ValueError("助手返修轮次无效")
    return index


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"记录不是 JSON 对象: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(text.encode("utf-8"))


def current_workflow_profile_sha256() -> str:
    """Fingerprint model routing, prompts, schemas and quality-control code."""
    model_config = _load(_ROOT / "config" / "creative_agent_models.json")
    files = {
        relative: _digest((_ROOT / relative).read_bytes())
        for relative in _PROFILE_FILES
    }
    return _canonical_hash(
        {
            "model_roles": model_config.get("roles", {}),
            "prompt_sha256": {
                name: _digest(text.encode("utf-8"))
                for name, text in sorted(PROMPTS.items())
            },
            "writer_tool_schema_sha256": {
                name: _canonical_hash(schema)
                for name, schema in sorted(WRITER_TOOL_SCHEMAS.items())
            },
            "quality_control_files": files,
        }
    )


def material_input_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    """Describe input form without binding a particular story's content."""
    files = manifest.get("files", {})
    return {
        "source_driver": manifest.get("source_driver"),
        "story_source_suffix": (
            Path(files["story_source"]["path"]).suffix.lower()
            if isinstance(files.get("story_source"), dict)
            else None
        ),
        "story_video_suffix": (
            Path(files["story_video"]["path"]).suffix.lower()
            if isinstance(files.get("story_video"), dict)
            else None
        ),
        "story_analysis_suffix": (
            Path(files["story_analysis"]["path"]).suffix.lower()
            if isinstance(files.get("story_analysis"), dict)
            else None
        ),
        "metadata_present": "metadata" in files,
        "metadata_suffix": (
            Path(files["metadata"]["path"]).suffix.lower()
            if isinstance(files.get("metadata"), dict)
            else None
        ),
        "reference_formats": sorted(
            {
                str(row.get("format"))
                for row in manifest.get("reference_adaptation", [])
                if isinstance(row, dict) and row.get("format")
            }
        ),
    }


def material_input_profile_sha256(manifest: dict[str, Any]) -> str:
    return _canonical_hash(material_input_profile(manifest))


def style_class_for_brief(brief: dict[str, Any]) -> str:
    selected_id = brief.get("selected_style_id")
    selected = next(
        (
            row
            for row in brief.get("style_options", [])
            if isinstance(row, dict) and row.get("id") == selected_id
        ),
        {},
    )
    medium = str(selected.get("medium", "")).lower()
    positive_medium = re.sub(
        r"(?:非|不是|不采用|避免|拒绝)[^，。；;、]{0,8}(?:cg|三维|3d)",
        "",
        medium,
    )
    if any(
        marker in positive_medium
        for marker in (
            "二维",
            "2d",
            "手绘",
            "水墨",
            "插画",
            "工笔",
            "淡彩",
            "绢本",
        )
    ):
        return "2d_illustrated_animation"
    if any(
        marker in positive_medium for marker in ("三维", "3d", "cg", "黏土", "定格")
    ):
        return "3d_or_stop_motion_animation"
    if "实拍" in positive_medium:
        return "live_action"
    if any(marker in positive_medium for marker in ("写实", "电影感", "现实主义")):
        return "cinematic_realism"
    return "other:" + _digest(positive_medium.encode("utf-8"))[:12]


def _valid_handoff(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    status = state.get("status")
    if status != "media_handoff_pending_capability" and not (
        status
        in ("needs_revision", "reviewed_revision_media_handoff_pending_capability")
        and state.get("assistant_review_outcome") == "major_issues"
        and isinstance(state.get("assistant_review_sha256"), str)
    ):
        raise ValueError("运行尚未完成文本交接")
    handoff = _load(run_dir / "MEDIA_HANDOFF.json")
    if _canonical_hash(handoff) != state.get("handoff_sha256"):
        raise ValueError("媒体交接包版本不符")
    for filename, key in (
        ("SCREENPLAY.json", "script_sha256"),
        ("STORYBOARD.json", "shots_sha256"),
        ("EXECUTION_DRAFT.json", "execution_draft_sha256"),
        ("MEDIA_CAPABILITY_AUDIT.json", "capability_audit_sha256"),
        ("EDITORIAL_REVIEW_PACKET.json", "review_packet_sha256"),
    ):
        if _canonical_hash(_load(run_dir / filename)) != handoff.get(key):
            raise ValueError(f"{filename} 与交接包版本不符")
    capability = _load(run_dir / "MEDIA_CAPABILITY_AUDIT.json")
    if (
        capability.get("automatic_submit") is not False
        or handoff.get("media_provider") != capability.get("provider")
        or handoff.get("media_model") != capability.get("model")
    ):
        raise ValueError("媒体执行能力审计与所选执行器不一致")
    if handoff.get("automatic_submit") is not False:
        raise ValueError("文本复核不能放行媒体自动提交")
    return handoff


def validated_assistant_review(
    run_dir: Path, state: dict[str, Any]
) -> dict[str, Any] | None:
    """Verify that an actual review still names this immutable text handoff."""
    path = Path(run_dir) / "CALIBRATION_REVIEW.json"
    if not path.exists():
        return None
    review = _load(path)
    _valid_handoff(Path(run_dir), state)
    evidence_path = Path(review["evidence_path"])
    if review.get("handoff_sha256") != state.get("handoff_sha256") or _digest(
        evidence_path.read_bytes()
    ) != review.get("evidence_sha256"):
        raise ValueError("助手复核证据或媒体交接版本不符")
    bound_hash = state.get("assistant_review_sha256")
    if bound_hash is not None and bound_hash != _canonical_hash(review):
        raise ValueError("任务状态绑定的助手复核版本不符")
    if state.get("assistant_review_outcome") not in (None, review.get("outcome")):
        raise ValueError("任务状态与助手复核结论不一致")
    return review


def _synchronize_review_state_locked(run_dir: Path) -> dict[str, Any]:
    """Promote a version-bound review outcome to the main task state, idempotently."""
    run_dir = Path(run_dir)
    path = run_dir / "state.json"
    state = _load(path)
    review = validated_assistant_review(run_dir, state)
    if review is None or review.get("outcome") not in OUTCOMES:
        raise ValueError("没有可同步的有效助手复核")
    desired = (
        "needs_revision"
        if review["outcome"] == "major_issues"
        else "media_handoff_pending_capability"
    )
    state.update(
        status=desired,
        assistant_review_outcome=review["outcome"],
        assistant_review_sha256=_canonical_hash(review),
    )
    from .creative_state_store import commit_state_locked

    commit_state_locked(run_dir, state)
    return state


def _record_review_locked(
    run_dir: Path, *, category: str, outcome: str, evidence_file: Path
) -> dict[str, Any]:
    if category not in CATEGORIES or outcome not in OUTCOMES:
        raise ValueError("样本类型或复核结论无效")
    run_dir = Path(run_dir)
    state = _load(run_dir / "state.json")
    if state["status"] != "media_handoff_pending_capability":
        raise ValueError("没有完整文本产物，不能登记首稿复核")
    if state["source_driver"] not in (
        {"reference_video", "original"} if category == "video_original" else {"novel"}
    ):
        raise ValueError("样本类型与业务驱动不一致")
    handoff = _valid_handoff(run_dir, state)
    script_path, shots_path = run_dir / "SCREENPLAY.json", run_dir / "STORYBOARD.json"
    script = _load(script_path)
    if _canonical_hash(script) != handoff["script_sha256"]:
        raise ValueError("剧本版本与交接包不符")
    if _canonical_hash(_load(shots_path)) != handoff["shots_sha256"]:
        raise ValueError("分镜版本与交接包不符")
    draft = _load(run_dir / "EXECUTION_DRAFT.json")
    if (
        _canonical_hash(draft) != handoff["execution_draft_sha256"]
        or draft.get("automatic_submit") is not False
    ):
        raise ValueError("执行预稿版本与交接包不符")
    packet = _load(run_dir / "EDITORIAL_REVIEW_PACKET.json")
    if _canonical_hash(packet) != handoff["review_packet_sha256"]:
        raise ValueError("集中复核包版本与交接包不符")
    materials = _load(run_dir / "materials.json")
    brief_record = _load(run_dir / "director_brief.json")
    brief = brief_record.get("output")
    if not isinstance(brief, dict):
        raise ValueError("导演方向回执缺少有效输出")
    analysis = _load(run_dir / "writer_analysis.json")
    rejected_candidates = analysis.get("output", {}).get("rejected_candidates", [])
    format_reconciliations = analysis.get("output", {}).get(
        "format_reconciliations", []
    )
    evidence_file = Path(evidence_file).resolve(strict=True)
    evidence = evidence_file.read_text(encoding="utf-8").strip()
    if len(evidence) < 120:
        raise ValueError("复核证据过短；需实际列明人物、动机和情绪高光")
    path = run_dir / "CALIBRATION_REVIEW.json"
    if path.exists():
        raise ValueError("已有绑定复核记录，不覆盖历史结论")
    current_profile = current_workflow_profile_sha256()
    task_profile = state.get("workflow_profile_sha256")
    profile_unchanged_since_generation = (
        isinstance(task_profile, str) and task_profile == current_profile
    )
    review = {
        "schema": "creative_assistant_review/v1",
        "reviewer": "assistant",
        "category": category,
        "outcome": outcome,
        "first_draft_no_major": (
            outcome == "passed"
            and state["revision_rounds"] == 0
            and not rejected_candidates
            and not script.get("duration_reconciliation")
            and profile_unchanged_since_generation
        ),
        "operationally_clean": (
            state.get("contract_repairs_used", 0) == 0
            and state.get("format_repairs_used", 0) == 0
            and not format_reconciliations
            and not state.get("local_format_reconciliations")
        ),
        "technical_repairs_before_complete_draft": {
            "contract_repairs": state.get("contract_repairs_used", 0),
            "format_repairs": state.get("format_repairs_used", 0),
            "analysis_format_reconciliations": len(format_reconciliations),
            "local_format_reconciliations": list(
                state.get("local_format_reconciliations", [])
            ),
        },
        "rejected_candidates": len(rejected_candidates),
        "format_reconciliations": len(format_reconciliations),
        "duration_reconciliation": script.get("duration_reconciliation"),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "material_sha256": state["material_sha256"],
        "handoff_sha256": state["handoff_sha256"],
        "evidence_path": str(evidence_file),
        "evidence_sha256": _digest(evidence_file.read_bytes()),
        "human_spot_check": "not_performed",
        "video_review": "not_performed",
        "workflow_profile_sha256": task_profile or "legacy_unbound",
        "review_runtime_profile_sha256": current_profile,
        "profile_unchanged_since_generation": profile_unchanged_since_generation,
        "input_profile": material_input_profile(materials),
        "input_profile_sha256": material_input_profile_sha256(materials),
        "style_class": style_class_for_brief(brief),
    }
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    _synchronize_review_state_locked(run_dir)
    return review


def _record_revision_review_locked(
    run_dir: Path,
    *,
    outcome: str,
    evidence_file: Path,
) -> dict[str, Any]:
    """Bind an actual reread to the separately stored assistant revision draft."""
    if outcome not in OUTCOMES:
        raise ValueError("复核结论无效")
    run_dir = Path(run_dir)
    state_path = run_dir / "state.json"
    state = _load(state_path)
    round_index = _revision_index(state)
    path = revision_artifact(run_dir, "REVISION_REVIEW", round_index)
    if path.exists():
        raise ValueError("已有返修复核记录，不覆盖历史结论")
    revision_status = state.get("assistant_revision_status")
    if (
        state.get("status") != "needs_revision"
        or revision_status not in ("assistant_recheck_pending", "needs_revision")
        or (outcome == "passed" and revision_status != "assistant_recheck_pending")
    ):
        raise ValueError("没有待助手复看的返修稿")
    first_review = validated_assistant_review(run_dir, state)
    if first_review is None or first_review.get("outcome") != "major_issues":
        raise ValueError("原始助手问题单未绑定")
    draft = _load(revision_artifact(run_dir, "REVISION_DRAFT", round_index))
    if (
        _canonical_hash(draft) != state.get("assistant_revision_draft_sha256")
        or draft.get("status") != revision_status
        or draft.get("parent_handoff_sha256") != state.get("handoff_sha256")
        or draft.get("automatic_submit") is not False
    ):
        raise ValueError("返修稿与受审版本不符")
    if revision_status == "needs_revision" and not draft.get("unresolved_model_issues"):
        raise ValueError("模型主要问题未随返修稿留档")
    for name, key in (
        ("script", "script_sha256"),
        ("shots", "shots_sha256"),
        ("check", "check_sha256"),
    ):
        if _canonical_hash(draft[name]) != draft[key]:
            raise ValueError(f"返修稿的 {name} 内容与哈希不符")
    for name, key in (("analysis", "analysis_sha256"), ("brief", "brief_sha256")):
        if name in draft and _canonical_hash(draft[name]) != draft.get(key):
            raise ValueError(f"返修稿的 {name} 内容与哈希不符")
    if "selected_source" in draft and _canonical_hash(
        draft["selected_source"]
    ) != draft.get("selected_source_sha256"):
        raise ValueError("返修稿的 selected_source 内容与哈希不符")
    if round_index == 2:
        previous = validated_revision_review(run_dir, state, round_index=1)
        if (
            previous is None
            or previous["outcome"] != "major_issues"
            or draft.get("parent_revision_review_sha256") != _canonical_hash(previous)
        ):
            raise ValueError("第二轮返修缺少第一轮未通过的有效证据")
    evidence_file = Path(evidence_file).resolve(strict=True)
    if len(evidence_file.read_text(encoding="utf-8").strip()) < 120:
        raise ValueError("返修复核证据过短")
    review = {
        "schema": "creative_assistant_revision_review/v1",
        "reviewer": "assistant",
        "outcome": outcome,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "first_review_sha256": _canonical_hash(first_review),
        "round_index": round_index,
        "draft_sha256": _canonical_hash(draft),
        "evidence_path": str(evidence_file),
        "evidence_sha256": _digest(evidence_file.read_bytes()),
        "human_spot_check": "not_performed",
        "video_review": "not_performed",
    }
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    state["assistant_revision_status"] = (
        "needs_revision"
        if outcome == "major_issues"
        else "review_passed_pending_handoff"
    )
    state["assistant_revision_review_sha256"] = _canonical_hash(review)
    hashes = dict(state.get("assistant_revision_review_hashes", {}))
    hashes[f"{round_index:02}"] = _canonical_hash(review)
    state["assistant_revision_review_hashes"] = hashes
    state["assistant_revision_round_index"] = round_index
    from .creative_state_store import commit_state_locked

    commit_state_locked(run_dir, state)
    return review


def validated_revision_review(
    run_dir: Path,
    state: dict[str, Any],
    *,
    round_index: int | None = None,
) -> dict[str, Any] | None:
    current_index = _revision_index(state)
    index = current_index if round_index is None else round_index
    path = revision_artifact(run_dir, "REVISION_REVIEW", index)
    if not path.exists():
        return None
    review = _load(path)
    first = validated_assistant_review(run_dir, state)
    draft = _load(revision_artifact(run_dir, "REVISION_DRAFT", index))
    feedback = _load(revision_artifact(run_dir, "FEEDBACK", index))
    expected_hash = state.get("assistant_revision_review_hashes", {}).get(f"{index:02}")
    if expected_hash is None and index == current_index:
        expected_hash = state.get("assistant_revision_review_sha256")
    if (
        first is None
        or review.get("first_review_sha256") != _canonical_hash(first)
        or review.get("round_index", 1) != index
        or review.get("draft_sha256") != _canonical_hash(draft)
        or draft.get("feedback_sha256") != _canonical_hash(feedback)
        or draft.get("automatic_submit") is not False
        or _digest(Path(review["evidence_path"]).read_bytes())
        != review.get("evidence_sha256")
        or review.get("outcome") not in OUTCOMES
        or expected_hash != _canonical_hash(review)
    ):
        raise ValueError("返修稿助手复核与当前任务版本不符")
    for name, key in (
        ("analysis", "analysis_sha256"),
        ("brief", "brief_sha256"),
        ("selected_source", "selected_source_sha256"),
        ("script", "script_sha256"),
        ("shots", "shots_sha256"),
        ("check", "check_sha256"),
    ):
        if name in draft and _canonical_hash(draft[name]) != draft.get(key):
            raise ValueError(f"返修稿的 {name} 内容与哈希不符")
    if index == 2:
        previous = validated_revision_review(run_dir, state, round_index=1)
        if (
            previous is None
            or previous["outcome"] != "major_issues"
            or feedback.get("parent_revision_review_sha256")
            != _canonical_hash(previous)
            or draft.get("parent_revision_review_sha256") != _canonical_hash(previous)
        ):
            raise ValueError("第二轮返修与第一轮复核版本不符")
    return review


def calibration_status(runs_root: Path) -> dict[str, Any]:
    current_profile = current_workflow_profile_sha256()
    attempts = []
    for state_path in Path(runs_root).glob("*/state.json"):
        created_at = datetime.fromtimestamp(
            state_path.stat().st_mtime, timezone.utc
        ).isoformat()
        try:
            state = _load(state_path)
            if state.get("schema") != "creative_workflow_state/v1":
                continue
            created_at = state["created_at"]
            review = None
            review_path = state_path.parent / "CALIBRATION_REVIEW.json"
            if review_path.exists():
                review = validated_assistant_review(state_path.parent, state)
            attempts.append(
                {
                    "created_at": created_at,
                    "run_dir": str(state_path.parent),
                    "review": review,
                    "status": state.get("status"),
                }
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            # A damaged creative task is still a failed attempt in the sequence.
            attempts.append(
                {
                    "created_at": created_at,
                    "run_dir": str(state_path.parent),
                    "review": None,
                    "status": "invalid_state",
                }
            )
    attempts.sort(key=lambda row: (str(row["created_at"]), row["run_dir"]))
    valid_reviews = [row["review"] for row in attempts if row["review"] is not None]

    def clean(row: dict[str, Any]) -> bool:
        review = row["review"]
        return bool(
            review
            and review.get("first_draft_no_major") is True
            and review.get("workflow_profile_sha256") == current_profile
            and isinstance(review.get("input_profile_sha256"), str)
            and isinstance(review.get("style_class"), str)
        )

    milestone = None
    for index in range(2, len(attempts)):
        triple = attempts[index - 2 : index + 1]
        if (
            all(clean(row) for row in triple)
            and {row["review"]["category"] for row in triple} == set(CATEGORIES)
            and len({row["review"]["material_sha256"] for row in triple}) == 3
        ):
            milestone = {
                "at": attempts[index]["created_at"],
                "run_dirs": [row["run_dir"] for row in triple],
                "index": index,
            }
    last_three = attempts[-3:]
    # The first routine task without extra review does not erase an achieved
    # calibration. A later recorded major issue does reopen targeted review.
    reopened = bool(
        milestone
        and any(
            row["review"] and row["review"].get("outcome") == "major_issues"
            for row in attempts[milestone["index"] + 1 :]
        )
    )
    milestone_reviews = (
        [
            attempts[index]["review"]
            for index in range(milestone["index"] - 2, milestone["index"] + 1)
        ]
        if milestone
        else []
    )
    return {
        "attempted_tasks": len(attempts),
        "reviewed_tasks": len(valid_reviews),
        "consecutive_first_draft_passes": len(
            list(takewhile(clean, reversed(attempts)))
        ),
        "categories_in_last_three": [
            row["review"].get("category") if row["review"] else None
            for row in last_three
        ],
        "stop_per_draft_assistant_review": milestone is not None and not reopened,
        "calibration_milestone": (
            {key: value for key, value in milestone.items() if key != "index"}
            if milestone
            else None
        ),
        "targeted_review_reopened": reopened,
        "current_workflow_profile_sha256": current_profile,
        "profile_mismatch_reviews": sum(
            1
            for review in valid_reviews
            if review.get("first_draft_no_major") is True
            and review.get("workflow_profile_sha256") != current_profile
        ),
        "calibrated_input_profile_sha256": sorted(
            {review["input_profile_sha256"] for review in milestone_reviews}
        ),
        "calibrated_style_classes": sorted(
            {review["style_class"] for review in milestone_reviews}
        ),
        "video_flow_passes": 0,
    }


def synchronize_review_state(run_dir: Path) -> dict[str, Any]:
    from .creative_state_store import state_lock

    with state_lock(run_dir):
        return _synchronize_review_state_locked(run_dir)


def record_review(
    run_dir: Path, *, category: str, outcome: str, evidence_file: Path
) -> dict[str, Any]:
    from .creative_state_store import state_lock

    with state_lock(run_dir):
        return _record_review_locked(
            run_dir, category=category, outcome=outcome, evidence_file=evidence_file
        )


def record_revision_review(
    run_dir: Path, *, outcome: str, evidence_file: Path
) -> dict[str, Any]:
    from .creative_state_store import state_lock

    with state_lock(run_dir):
        return _record_revision_review_locked(
            run_dir, outcome=outcome, evidence_file=evidence_file
        )
