"""Source-bound emotion checkpoints before physical scheduling. No remote calls."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json

VERSION = "story_emotion_checkpoint/v1"
CRITERIA = ("pressure", "choice", "consequence", "release")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def validate_emotional_brief(brief):
    if not isinstance(brief, dict):
        raise ValueError("emotional brief must be an object")
    for key in ("audience_goal", *CRITERIA):
        if not isinstance(brief.get(key), str) or not brief[key].strip():
            raise ValueError(f"emotional brief missing {key}")
    limits = brief.get("creative_limits")
    if not isinstance(limits, list) or not limits or any(
        not isinstance(x, str) or not x.strip() for x in limits
    ):
        raise ValueError("creative_limits must preserve the story direction")


def build_emotion_revision_input(previous_script, brief, reference_pack, feedback):
    """Prepare complete writer context; no manual patch or dispatch."""
    validate_emotional_brief(brief)
    if not previous_script.get("beats"):
        raise ValueError("complete previous script required")
    if not reference_pack or not feedback:
        raise ValueError("full reference pack and original feedback required")
    prompt = (
        "提交完整新剧本，不返回补丁，不拼接新旧拍。先兑现观众情绪目标、压力、选择、"
        "后果和释放，再设计可见事件；时长和拍数浮动。压力须发生在正文中，不能只写"
        "背景；不靠堆道具操作延长紧张感。借鉴参考的表达机制，不照搬剧情。"
        "遵守creative_limits；不要默认增加反派、第三人、报复或补偿话术。"
        "本阶段不排手部操作、坐标或逐秒表演，后续导演和局部表演负责这些。"
        "输出完整title、premise、selected_candidate_id、beats；每拍保留id、event、"
        "trigger、steps，每项steps为action或dialogue，包含完整text；dialogue另含speaker。"
        "新版整体采用后全文复审。"
    )
    context = {"emotional_brief": deepcopy(brief), "previous_script": deepcopy(previous_script),
               "reference_pack": deepcopy(reference_pack), "feedback": deepcopy(feedback)}
    return {"schema": "complete_emotion_revision_input/v1", "creator": "MiniMax",
            "reviewer": "DeepSeek", "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            "bindings": {k + "_sha256": digest(v) for k, v in context.items()},
            "automatic_retry": False, "submitted": False}


def validate_emotion_review(review, script, brief):
    """Check exact evidence; a model review cannot assert human approval."""
    validate_emotional_brief(brief)
    if (review.get("schema") != VERSION or review.get("script_sha256") != digest(script)
            or review.get("brief_sha256") != digest(brief)):
        raise ValueError("emotion review source binding changed")
    rows = review.get("criteria")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("emotion criteria must be an array of objects")
    if [r.get("criterion") for r in rows] != list(CRITERIA):
        raise ValueError("emotion review must cover four criteria once in order")
    for row in rows:
        if row.get("finding") not in {"satisfied", "needs_revision", "uncertain"}:
            raise ValueError("invalid emotion finding")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("emotion finding needs a reason")
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or (not refs and row["finding"] != "uncertain"):
            raise ValueError("emotion finding needs source evidence")
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError("emotion evidence must be an object")
            parts = ref.get("path", "").split(".")
            if parts[0] != "script":
                raise ValueError("emotion evidence must refer to the actual script")
            value = script
            try:
                for part in parts[1:]:
                    value = value[int(part)] if isinstance(value, list) else value[part]
            except (KeyError, IndexError, ValueError, TypeError):
                raise ValueError("emotion evidence path missing") from None
            if not isinstance(value, str) or ref.get("quote") != value:
                raise ValueError("emotion evidence must quote the exact string leaf")
    if review.get("creative_quality_passed") is not False:
        raise ValueError("model review cannot assert creative quality approval")
    return ("needs_complete_revision" if any(r["finding"] == "needs_revision" for r in rows)
            else "needs_content_confirmation")


def story_media_blockers(script, brief, full_review, confirmation=None,
                         *, revision_feedback_unresolved=False):
    """A clean text review does not erase human feedback or approve creativity."""
    validate_emotional_brief(brief)
    blockers = []
    if full_review.get("issues") != [] or full_review.get("story_preserved") is not True:
        blockers.append("full_text_review_incomplete_or_failed")
    if revision_feedback_unresolved:
        blockers.append("human_revision_feedback_unresolved")
    if not confirmation:
        blockers.append("story_content_confirmation_missing")
    elif (confirmation.get("decision") != "approved"
          or not isinstance(confirmation.get("user_statement"), str)
          or not confirmation["user_statement"].strip()
          or confirmation.get("script_sha256") != digest(script)
          or confirmation.get("brief_sha256") != digest(brief)
          or confirmation.get("full_review_sha256") != digest(full_review)):
        blockers.append("story_content_confirmation_mismatched")
    return blockers

