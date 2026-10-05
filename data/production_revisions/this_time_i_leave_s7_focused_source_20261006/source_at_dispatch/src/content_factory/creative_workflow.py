"""Versioned two-role text workflow. Media submission is deliberately separate."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .creative_workflow_contract import (
    CreativeContractError,
    PROMPTS,
    WRITER_TOOL_SCHEMAS,
    creative_focus_beat_range,
    creative_focus_duration_range,
    _canonical_source_quote,
    _dialogue_text,
    _speech_units,
    _source_direct_quote_spans,
    compile_beat_screenplay,
    parse_json_object,
    validate_analysis,
    validate_candidate_embedded_dialogue_order,
    validate_candidate_duration,
    validate_creative_focus_action_constraints,
    validate_creative_focus_beat_count,
    validate_creative_focus_duration,
    validate_director_brief,
    validate_director_shots_or_story_issues,
    validate_reference_summary,
    validate_beat_plan,
    validate_script,
    validate_shots,
    validate_summary,
    validate_writer_check,
    is_narration_speaker,
)
from .creative_review_gate import (
    VERSION as REVIEW_POLICY_VERSION, SCRIPT_REVIEW_PROMPT,
    SUPPORTED_VERSIONS as REVIEW_POLICY_VERSIONS, review_prompt, review_rules,
    validate_review, make_packet, template as review_decision_template,
    confirmed_issues, digest as review_digest,
)

PROMPTS["script_review"] = SCRIPT_REVIEW_PROMPT

from .creative_workflow_inputs import MaterialBundle, verify_manifest
from .creative_workflow_roles import (
    CreativeRoleClients, RoleResult, role_context_capability,
)
from .creative_media_capability import audit_creative_executor
from .creative_seedance_segments import (
    build_seedance_segment_plan, validate_seedance_segment_plan,
)
from .creative_calibration import (
    calibration_status, material_input_profile_sha256, revision_artifact,
    style_class_for_brief, validated_assistant_review, validated_revision_review,
)
from .creative_stage_debug import (
    CreativeStageBreakpointReached,
)


_BEAT_REFERENCE_PATTERN = r"(?<![A-Za-z0-9_])B\d+[A-Za-z]?(?![A-Za-z0-9_])"
_SHOT_REFERENCE_PATTERN = r"(?<![A-Za-z0-9_])SH\d+[A-Za-z]?(?![A-Za-z0-9_])"


def _beat_references(text: str) -> list[str]:
    """Find stable beat ids even when Chinese text touches either side."""
    return re.findall(_BEAT_REFERENCE_PATTERN, text)


def _shot_references(text: str) -> list[str]:
    """Find stable shot ids without relying on Unicode word boundaries."""
    return re.findall(_SHOT_REFERENCE_PATTERN, text)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_versioned_current(path: Path, value: Any) -> None:
    """Advance a canonical current receipt while retaining immutable history."""
    if path.exists():
        previous = _read(path)
        if previous == value:
            return
        archive = path.with_name(f"{path.stem}__history_{_hash(previous)}{path.suffix}")
        if archive.exists() and _read(archive) != previous:
            raise RuntimeError(f"历史回执哈希冲突: {archive.name}")
        if not archive.exists():
            _write(archive, previous)
    _write(path, value)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_effective_analysis(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "EFFECTIVE_ANALYSIS.json"
    if path.is_file():
        value = _read(path)
        if not isinstance(value, dict):
            raise RuntimeError("有效编剧分析产物格式无效")
        return value
    return _read(Path(run_dir) / "writer_analysis.json")["output"]


def _expand_direct_speech_bounds(source: str, start: int, end: int) -> tuple[int, int]:
    """Keep an excerpt anchor inside direct speech bound to its full quote marks."""
    expanded_start, expanded_end = start, end
    for opening, closing in (("「", "」"), ("『", "』"), ("“", "”")):
        last_open = source.rfind(opening, 0, start + 1)
        last_close = source.rfind(closing, 0, start + 1)
        if last_open > last_close:
            expanded_start = min(expanded_start, last_open)
        last_open_before_end = source.rfind(opening, 0, end)
        last_close_before_end = source.rfind(closing, 0, end)
        if last_open_before_end > last_close_before_end:
            next_close = source.find(closing, end)
            if next_close >= 0:
                expanded_end = max(expanded_end, next_close + 1)
    return expanded_start, expanded_end


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _output_artifact(path: Path, purpose: str) -> dict[str, Any]:
    return {
        "path": path.name,
        "purpose": purpose,
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _chunks(text: str, limit: int) -> list[str]:
    """Lossless chunks, preferring paragraph boundaries when available."""
    chunks: list[str] = []
    current = ""
    for paragraph in text.splitlines(keepends=True):
        if current and len(current) + len(paragraph) > limit:
            chunks.append(current)
            current = ""
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current += paragraph
    if current:
        chunks.append(current)
    assert "".join(chunks) == text
    return chunks


def _dialogue_inventory(source: str) -> list[dict[str, str]]:
    """Quote spans plus nearby evidence; inscriptions remain visibly distinguishable."""
    rows: list[dict[str, str]] = []
    for index, match in enumerate(
        re.finditer(r"「(.*?)」|“(.*?)”", source, re.DOTALL), start=1
    ):
        raw_text = match.group(1) or match.group(2)
        cjk_count = sum(
            0x3400 <= ord(character) <= 0x9FFF
            or 0xF900 <= ord(character) <= 0xFAFF
            or 0x3040 <= ord(character) <= 0x30FF
            or 0xAC00 <= ord(character) <= 0xD7AF
            for character in raw_text
        )
        latin_count = sum(character.isascii() and character.isalpha() for character in raw_text)
        text = re.sub(r"\s+", " " if latin_count > cjk_count else "", raw_text).strip()
        if not text:
            continue
        rows.append({
            "id": f"Q{index:02}",
            "text": text,
            "before": "".join(source[max(0, match.start() - 35):match.start()].split()),
            "after": "".join(source[match.end():match.end() + 25].split()),
        })
    return rows


def _dialogue_compression_options(
    plan: dict[str, Any], target_beat_ids: list[str], source: str,
) -> list[dict[str, Any]]:
    """Offer exact source spans so timing repair cannot paraphrase between clauses."""
    normalized_source = _dialogue_text(source)
    target_ids = set(target_beat_ids)
    result: list[dict[str, Any]] = []
    for beat in plan.get("beats", []):
        if not isinstance(beat, dict) or beat.get("id") not in target_ids:
            continue
        for dialogue_index, line in enumerate(beat.get("dialogue", [])):
            if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                continue
            text = line["text"].strip()
            if not text:
                continue
            clauses: list[str] = []
            clause_start = 0
            closing_quotes = "」』”’\"'"
            opening_quotes = "「『“‘\"'"
            for index, character in enumerate(text):
                if character not in "，。！？；：!?;:":
                    continue
                # Keep reporting colons attached to the nested quote they open,
                # and keep immediate closing quote marks attached to the clause.
                if (
                    character in "：:"
                    and index + 1 < len(text)
                    and text[index + 1] in opening_quotes
                ):
                    continue
                clause_end = index + 1
                while clause_end < len(text) and text[clause_end] in closing_quotes:
                    clause_end += 1
                clauses.append(text[clause_start:clause_end])
                clause_start = clause_end
            if clause_start < len(text):
                clauses.append(text[clause_start:])
            clauses = [row for row in clauses if row]
            candidates: list[tuple[int, int, str, int]] = []
            seen: set[str] = set()
            # Atomic clauses first, then short adjacent combinations. This keeps
            # choices spread across the original line without creating a huge prompt.
            for width in range(1, min(3, len(clauses)) + 1):
                for start in range(0, len(clauses) - width + 1):
                    candidate = "".join(clauses[start:start + width]).strip()
                    speech_units = _speech_units(candidate)
                    if (speech_units < 2 or speech_units > 72 or candidate in seen
                            or _dialogue_text(candidate) not in normalized_source):
                        continue
                    seen.add(candidate)
                    candidates.append((start, width, candidate, speech_units))
            result.append({
                "beat_id": beat["id"],
                "dialogue_index": dialogue_index,
                "speaker": line.get("speaker"),
                "original_text": text,
                "options": [
                    {"text": candidate, "speech_units": speech_units}
                    for _, _, candidate, speech_units in candidates[:36]
                ],
            })
    return result


def _source_scope_audit(source: str, script: dict[str, Any], driver: str) -> dict[str, Any]:
    """Surface a large unused source lead-in for editorial judgment, not automatic rejection."""
    result: dict[str, Any] = {
        "schema": "creative_source_scope_audit/v1",
        "script_sha256": _hash(script),
        "selected_source_sha256": _hash(source),
        "applicable": driver == "novel",
        "potential_overwide_start": False,
    }
    if driver != "novel":
        result["reason"] = "视频原创驱动不使用小说选段起点"
        return result
    first_line = next(
        (line.get("text") for beat in script["beats"] for line in beat["dialogue"]),
        None,
    )
    if not isinstance(first_line, str) or not first_line.strip():
        result["reason"] = "剧本无对白，无法从对白位置判断选段起点"
        return result
    compact_source = [(index, char) for index, char in enumerate(source) if not char.isspace()]
    compact_text = "".join(char for _, char in compact_source)
    spoken = "".join(first_line.split())
    compact_offset = compact_text.find(spoken)
    if compact_offset < 0:
        result["reason"] = "首句对白未能在原文中定位；对白契约须单独拦截"
        return result
    raw_offset = compact_source[compact_offset][0]
    preceding = _dialogue_inventory(source[:raw_offset])
    result.update(
        first_spoken_text=first_line,
        first_spoken_source_offset=raw_offset,
        selected_source_characters=len(source),
        preceding_quoted_spans=len(preceding),
        potential_overwide_start=(
            raw_offset >= 500
            and raw_offset >= len(source) * 0.5
            and len(preceding) >= 3
        ),
    )
    result["reason"] = (
        "首句对白位于选段后半，前面有多处引号内容；须核对前段是否含未呈现的独立事件或关键刺激"
        if result["potential_overwide_start"]
        else "未触发大幅跳过选段开头的启发式提示；不能据此证明因果完整"
    )
    return result


def _revise_selected_source_boundary(
    source: str,
    current: dict[str, Any],
    feedback: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    """Create an immutable, bounded novel excerpt revision from exact source anchors."""
    if current.get("source_sha256") != _hash(source):
        raise CreativeContractError("当前锁定选段与小说来源版本不一致")
    if feedback.get("parent_selected_source_sha256") != _hash(current):
        raise CreativeContractError("选段边界返修未绑定当前锁定选段")
    reason = feedback.get("boundary_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise CreativeContractError("选段边界返修缺少具体理由")
    start_quote, start = _canonical_source_quote(
        source, feedback.get("new_start_quote"), "selected_source.new_start_quote",
    )
    end_quote, end_anchor = _canonical_source_quote(
        source, feedback.get("new_end_quote"), "selected_source.new_end_quote",
    )
    end = end_anchor + len(end_quote)
    start, end = _expand_direct_speech_bounds(source, start, end)
    if start >= end or end_anchor < start:
        raise CreativeContractError("选段边界返修的起止顺序倒置")
    old_start = current.get("start_character")
    old_end = current.get("end_character")
    if type(old_start) is not int or type(old_end) is not int or not (0 <= old_start < old_end <= len(source)):
        raise CreativeContractError("当前锁定选段缺少有效字符边界")
    if abs(start - old_start) > 800 or abs(end - old_end) > 800:
        raise CreativeContractError("选段边界每端只能在当前范围前后 800 字内调整")
    if max(start, old_start) >= min(end, old_end):
        raise CreativeContractError("选段边界返修不能切换到不相交的另一事件")
    text = source[start:end]
    if text == current.get("text"):
        raise CreativeContractError("选段边界返修没有改变当前锁定选段")
    revised = {
        "schema": "creative_selected_source_revision/v1",
        "candidate_id": current.get("candidate_id"),
        "start_character": start,
        "end_character": end,
        "source_sha256": _hash(source),
        "excerpt_sha256": _hash(text),
        "text": text,
        "parent_selected_source_sha256": _hash(current),
        "parent_start_character": old_start,
        "parent_end_character": old_end,
        "assistant_feedback_sha256": _hash(feedback),
        "scope_adjustment": {
            "source": "assistant_review",
            "new_start_quote": start_quote,
            "new_end_quote": end_quote,
            "reason": reason.strip(),
        },
    }
    return revised, start_quote, end_quote


_DIRECTOR_SCOPE_WINDOW = 1200


def _is_narrative_start_boundary(source: str, position: int) -> bool:
    """Reject source expansions that start in the middle of prose or a word."""
    if position <= 0:
        return True
    prefix = source[:position]
    if prefix.endswith(("\n\n", "\r\n\r\n")):
        return True
    stripped = prefix.rstrip()
    return not stripped or stripped[-1] in "。！？.!?：:；;"


def _validate_director_brief_for_source(
    value: dict[str, Any], source: str, driver: str, candidate: dict[str, Any],
) -> None:
    """Validate source-scope anchors inside the paid director stage contract."""
    validate_director_brief(value)
    scope = value.get("source_scope") or {}
    lead_quote = scope.get("lead_in_start_quote", "")
    trim_quote = scope.get("trim_start_quote", "")
    extend_quote = scope.get("extend_end_quote", "")
    trim_end_quote = scope.get("trim_end_quote", "")
    if driver != "novel":
        if lead_quote or trim_quote or extend_quote or trim_end_quote:
            raise CreativeContractError("视频原创导演不能声明小说原文边界")
        return
    candidate_start_quote, candidate_start = _canonical_source_quote(
        source, candidate["start_quote"], "candidate.start_quote",
    )
    candidate_end_quote, candidate_end_anchor = _canonical_source_quote(
        source, candidate["end_quote"], "candidate.end_quote",
    )
    candidate_end = candidate_end_anchor + len(candidate_end_quote)
    candidate_start, candidate_end = _expand_direct_speech_bounds(
        source, candidate_start, candidate_end,
    )
    if lead_quote:
        canonical_lead, lead_start = _canonical_source_quote(
            source, lead_quote, "director.source_scope.lead_in_start_quote",
        )
        lead_start, _ = _expand_direct_speech_bounds(
            source, lead_start, lead_start + len(canonical_lead),
        )
        if (lead_start >= candidate_start
                or candidate_start - lead_start > _DIRECTOR_SCOPE_WINDOW):
            raise CreativeContractError(
                f"导演建议的前置原文不在候选起点前 {_DIRECTOR_SCOPE_WINDOW} 字内"
            )
        if not _is_narrative_start_boundary(source, lead_start):
            raise CreativeContractError("导演建议的前置原文起点落在句子或单词中间")
    if trim_quote:
        canonical_trim, trimmed_start = _canonical_source_quote(
            source, trim_quote, "director.source_scope.trim_start_quote",
        )
        trimmed_start, _ = _expand_direct_speech_bounds(
            source, trimmed_start, trimmed_start + len(canonical_trim),
        )
        if (trimmed_start <= candidate_start
                or trimmed_start >= candidate_end - len(candidate_end_quote)):
            raise CreativeContractError("导演建议的收窄起点不在候选原文内部")
    if extend_quote:
        canonical_extend, extended_anchor = _canonical_source_quote(
            source, extend_quote, "director.source_scope.extend_end_quote",
        )
        _, extended_end = _expand_direct_speech_bounds(
            source, extended_anchor, extended_anchor + len(canonical_extend),
        )
        if (extended_anchor < candidate_end
                or extended_end - candidate_end > _DIRECTOR_SCOPE_WINDOW):
            raise CreativeContractError(
                f"导演建议的新终点不在候选终点后 {_DIRECTOR_SCOPE_WINDOW} 字内"
            )
    if trim_end_quote:
        canonical_trim_end, trimmed_end_anchor = _canonical_source_quote(
            source, trim_end_quote, "director.source_scope.trim_end_quote",
        )
        _, trimmed_end = _expand_direct_speech_bounds(
            source, trimmed_end_anchor, trimmed_end_anchor + len(canonical_trim_end),
        )
        if trimmed_end <= candidate_start + len(candidate_start_quote) or trimmed_end >= candidate_end:
            raise CreativeContractError("导演建议的收窄终点不在候选原文内部")
        adjusted_start = candidate_start
        if trim_quote:
            adjusted_quote, adjusted_start = _canonical_source_quote(
                source, trim_quote, "director.source_scope.trim_start_quote",
            )
            adjusted_start, _ = _expand_direct_speech_bounds(
                source, adjusted_start, adjusted_start + len(adjusted_quote),
            )
        if adjusted_start >= trimmed_end:
            raise CreativeContractError("导演调整后的原文起点不能晚于终点")


def _project_noop_director_source_scope(
    value: dict[str, Any], source: str, driver: str, candidate: dict[str, Any],
) -> tuple[dict[str, Any], list[str]] | None:
    """Clear boundary suggestions that resolve to the unchanged candidate edge."""
    if driver != "novel" or not isinstance(value.get("source_scope"), dict):
        return None
    try:
        candidate_start_quote, candidate_start = _canonical_source_quote(
            source, candidate["start_quote"], "candidate.start_quote",
        )
        candidate_end_quote, candidate_end_anchor = _canonical_source_quote(
            source, candidate["end_quote"], "candidate.end_quote",
        )
    except (KeyError, CreativeContractError):
        return None
    candidate_end = candidate_end_anchor + len(candidate_end_quote)
    candidate_start, candidate_end = _expand_direct_speech_bounds(
        source, candidate_start, candidate_end,
    )
    scope = value["source_scope"]
    cleared: list[str] = []
    for field in (
        "lead_in_start_quote", "trim_start_quote", "extend_end_quote", "trim_end_quote",
    ):
        quote = scope.get(field, "")
        if not isinstance(quote, str) or not quote:
            continue
        try:
            canonical, anchor = _canonical_source_quote(
                source, quote, f"director.source_scope.{field}",
            )
        except CreativeContractError:
            continue
        expanded_start, expanded_end = _expand_direct_speech_bounds(
            source, anchor, anchor + len(canonical),
        )
        unchanged = (
            expanded_start == candidate_start
            if field in ("lead_in_start_quote", "trim_start_quote")
            else expanded_end == candidate_end
        )
        if unchanged:
            cleared.append(field)
    if not cleared:
        return None
    projected = deepcopy(value)
    projected_scope = projected["source_scope"]
    for field in cleared:
        projected_scope[field] = ""
    if not any(projected_scope.get(field) for field in (
        "lead_in_start_quote", "trim_start_quote", "extend_end_quote", "trim_end_quote",
    )):
        projected["source_scope"] = {}
    return projected, cleared


_CANDIDATE_LOCKED_KEYS = (
    "id", "title", "start_quote", "end_quote", "duration_seconds",
)
_CANDIDATE_STORY_KEYS = (
    "setup", "conflict", "turn", "peak", "aftermath", "selection_reason",
)
_DIRECTOR_FEEDBACK_DECISIONS = {
    "accepted_candidate_change", "accepted_in_script", "director_only", "declined",
}


def _feedback_requires_candidate_decision(value: Any) -> bool:
    """Conservatively identify preflight feedback about the story candidate."""
    if isinstance(value, dict):
        text = " ".join(str(value.get(key, "")) for key in ("issue", "scope", "proposal"))
    else:
        text = str(value)
    lowered = text.lower()
    markers = (
        "candidate", "setup", "conflict", "turn", "peak", "aftermath",
        "selected_source", "end_quote", "start_quote", "source scope",
        "候选", "选段", "原文边界", "原文终点", "原文起点", "结尾",
        "收束", "高潮", "前因", "转折", "不是原文", "不在原文",
        "位于当前", "位于选段", "越界",
    )
    return any(marker in lowered for marker in markers)


def _validate_director_feedback_response(
    value: dict[str, Any],
    original_candidate: dict[str, Any],
    writer_feedback: list[Any],
    selected_source: dict[str, Any] | None = None,
) -> None:
    """Validate a writer's bound response to every director preflight item."""
    if set(value) != {"candidate_update", "feedback_responses"}:
        raise CreativeContractError("导演前期意见交接只能包含候选更新和逐条回应")
    update = value.get("candidate_update")
    responses = value.get("feedback_responses")
    if not isinstance(update, dict) or set(update) != set(original_candidate):
        raise CreativeContractError("导演前期意见交接的候选字段不完整")
    if any(update.get(key) != original_candidate.get(key) for key in _CANDIDATE_LOCKED_KEYS):
        raise CreativeContractError("导演前期意见交接改变了候选身份、选段或时长")
    for key in _CANDIDATE_STORY_KEYS:
        if not isinstance(update.get(key), str) or not update[key].strip():
            raise CreativeContractError(f"导演前期意见交接的 candidate_update.{key} 不能为空")
    if not isinstance(responses, list) or len(responses) != len(writer_feedback):
        raise CreativeContractError("导演前期意见必须由编剧逐条回应")
    changed = any(update[key] != original_candidate[key] for key in _CANDIDATE_STORY_KEYS)
    accepted_change = False
    for index, (feedback, response) in enumerate(zip(writer_feedback, responses)):
        if (
            not isinstance(response, dict)
            or set(response) != {"feedback_index", "decision", "reason"}
            or response.get("feedback_index") != index
            or response.get("decision") not in _DIRECTOR_FEEDBACK_DECISIONS
            or not isinstance(response.get("reason"), str)
            or not response["reason"].strip()
        ):
            raise CreativeContractError("导演前期意见回应的编号、决定或理由无效")
        if response["decision"] == "accepted_candidate_change":
            accepted_change = True
        if (
            _feedback_requires_candidate_decision(feedback)
            and response["decision"] == "director_only"
        ):
            raise CreativeContractError("候选或原文范围问题不能推给导演摄影阶段")
    if accepted_change and not changed:
        raise CreativeContractError("编剧声称已修改候选，但 candidate_update 没有实际变化")
    if changed and not accepted_change:
        raise CreativeContractError("candidate_update 已变化，但没有意见标为候选修改")
    source_text = (
        str(selected_source.get("text") or "")
        if isinstance(selected_source, dict) else ""
    )
    if source_text:
        validate_candidate_embedded_dialogue_order(update, source_text)
    outside_source_claims = (
        "原文下一行", "紧接原文下一行", "下文原文", "选段后原文", "选段之后原文",
    )
    claimed_text = " ".join(
        [str(update.get(key, "")) for key in _CANDIDATE_STORY_KEYS]
        + [str(row.get("reason", "")) for row in responses if isinstance(row, dict)]
    )
    outside_source_assertion = False
    for marker in outside_source_claims:
        for match in re.finditer(re.escape(marker), claimed_text):
            prefix = claimed_text[max(0, match.start() - 60):match.start()]
            if re.search(
                r"(?:不会|不會|不得|不能|未|没有|沒有|禁止).{0,12}$",
                prefix,
            ):
                continue
            outside_source_assertion = True
            break
        if outside_source_assertion:
            break
    if source_text and outside_source_assertion:
        raise CreativeContractError(
            "编剧用锁定 selected_source 之外的所谓原文下一行支持候选；"
            "只能改为选段内事实或明确的非冲突制作选择"
        )


def _project_director_feedback_candidate_lock(
    output: dict[str, Any], candidate_lock: dict[str, Any],
) -> tuple[
    dict[str, Any], list[str], bool, list[str], list[str], list[int]
] | None:
    """Restore locked fields and reject candidate edits with no accepted change."""
    projected = deepcopy(output)
    relocated = False
    stripped_format_paths: list[str] = []
    downgraded_noop_change_indexes: list[int] = []
    allowed_wrapper_fields = {
        "source_sha256", "source_evidence", "source_evidence_limit",
        "invalid_character_quotes", "invalid_candidate_quotes", "creative_focus",
    }
    if "candidate_update" in projected:
        extras = set(projected) - {"candidate_update", "feedback_responses"}
        if extras and extras <= allowed_wrapper_fields:
            for key in sorted(extras):
                projected.pop(key)
                stripped_format_paths.append(key)
    if set(projected) == {"candidate_update"}:
        update = projected.get("candidate_update")
        if (
            not isinstance(update, dict)
            or set(update) != set(candidate_lock) | {"feedback_responses"}
            or not isinstance(update.get("feedback_responses"), list)
        ):
            return None
        responses = update.pop("feedback_responses")
        projected["feedback_responses"] = responses
        relocated = True
    if set(projected) != {"candidate_update", "feedback_responses"}:
        return None
    update = projected.get("candidate_update")
    if not isinstance(update, dict):
        return None
    for alias, canonical in (("start_Quote", "start_quote"), ("end_Quote", "end_quote")):
        if alias not in update:
            continue
        if canonical in update and update[canonical] != update[alias]:
            return None
        update.setdefault(canonical, update[alias])
        update.pop(alias)
        stripped_format_paths.append(f"candidate_update.{alias}")
    if "director_notes" in update:
        if not isinstance(update["director_notes"], str):
            return None
        update.pop("director_notes")
        stripped_format_paths.append("candidate_update.director_notes")
    if set(update) != set(candidate_lock):
        return None
    responses = projected.get("feedback_responses")
    if isinstance(responses, list):
        for index, response in enumerate(responses):
            if (
                isinstance(response, dict)
                and set(response) == {
                    "feedback_index", "decision", "reason", "field_changes",
                }
            ):
                response.pop("field_changes")
                stripped_format_paths.append(
                    f"feedback_responses[{index}].field_changes"
                )
            if (
                isinstance(response, dict)
                and "rationale_field" in response
                and not str(response.get("rationale_field") or "").strip()
            ):
                response.pop("rationale_field")
                stripped_format_paths.append(
                    f"feedback_responses[{index}].rationale_field"
                )
    restored = [
        key for key in _CANDIDATE_LOCKED_KEYS
        if update.get(key) != candidate_lock.get(key)
    ]
    complete_responses = (
        isinstance(responses, list)
        and all(
            isinstance(response, dict)
            and set(response) == {"feedback_index", "decision", "reason"}
            and response.get("feedback_index") == index
            and response.get("decision") in _DIRECTOR_FEEDBACK_DECISIONS
            and isinstance(response.get("reason"), str)
            and bool(response["reason"].strip())
            for index, response in enumerate(responses)
        )
    )
    has_accepted_change = complete_responses and any(
        response["decision"] == "accepted_candidate_change"
        for response in responses
    )
    story_changed = any(
        update.get(key) != candidate_lock.get(key) for key in _CANDIDATE_STORY_KEYS
    )
    if complete_responses and has_accepted_change and not story_changed:
        for index, response in enumerate(responses):
            if response["decision"] == "accepted_candidate_change":
                response["decision"] = "accepted_in_script"
                downgraded_noop_change_indexes.append(index)
        has_accepted_change = False
    unacknowledged_changes = (
        [
            key for key in _CANDIDATE_STORY_KEYS
            if update.get(key) != candidate_lock.get(key)
        ]
        if complete_responses and not has_accepted_change else []
    )
    if (
        not restored and not relocated and not unacknowledged_changes
        and not stripped_format_paths and not downgraded_noop_change_indexes
    ):
        return None
    for key in restored:
        update[key] = deepcopy(candidate_lock[key])
    for key in unacknowledged_changes:
        update[key] = deepcopy(candidate_lock[key])
    return (
        projected, restored, relocated, unacknowledged_changes,
        stripped_format_paths, downgraded_noop_change_indexes,
    )


def _missing_director_feedback_suffix(
    output: dict[str, Any], writer_feedback: list[Any],
) -> list[int]:
    """Return only an unambiguous missing suffix of valid feedback responses."""
    if set(output) != {"candidate_update", "feedback_responses"}:
        return []
    responses = output.get("feedback_responses")
    if not isinstance(responses, list) or len(responses) >= len(writer_feedback):
        return []
    for index, response in enumerate(responses):
        if (
            not isinstance(response, dict)
            or set(response) != {"feedback_index", "decision", "reason"}
            or response.get("feedback_index") != index
            or response.get("decision") not in _DIRECTOR_FEEDBACK_DECISIONS
            or not isinstance(response.get("reason"), str)
            or not response["reason"].strip()
        ):
            return []
    return list(range(len(responses), len(writer_feedback)))


def _apply_director_feedback_response_patch(
    output: dict[str, Any], patch: dict[str, Any], missing_indexes: list[int],
) -> dict[str, Any]:
    """Append an exact model-authored suffix without changing prior negotiation text."""
    if set(patch) != {"feedback_responses"}:
        raise CreativeContractError("导演意见回应补丁只能包含 feedback_responses")
    rows = patch.get("feedback_responses")
    if not isinstance(rows, list) or len(rows) != len(missing_indexes):
        raise CreativeContractError("导演意见回应补丁数量与缺失编号不一致")
    for expected_index, row in zip(missing_indexes, rows):
        if (
            not isinstance(row, dict)
            or set(row) != {"feedback_index", "decision", "reason"}
            or row.get("feedback_index") != expected_index
            or row.get("decision") not in _DIRECTOR_FEEDBACK_DECISIONS
            or not isinstance(row.get("reason"), str)
            or not row["reason"].strip()
        ):
            raise CreativeContractError("导演意见回应补丁的编号、决定或理由无效")
    corrected = deepcopy(output)
    corrected["feedback_responses"].extend(deepcopy(rows))
    return corrected


def _invalid_director_feedback_response_indexes(
    output: dict[str, Any], writer_feedback: list[Any],
) -> list[int]:
    """Locate invalid rows when the response list is complete and index-bound."""
    if set(output) != {"candidate_update", "feedback_responses"}:
        return []
    responses = output.get("feedback_responses")
    if not isinstance(responses, list) or len(responses) != len(writer_feedback):
        return []
    invalid: list[int] = []
    for index, (feedback, response) in enumerate(zip(writer_feedback, responses)):
        malformed = (
            not isinstance(response, dict)
            or set(response) != {"feedback_index", "decision", "reason"}
            or response.get("feedback_index") != index
            or response.get("decision") not in _DIRECTOR_FEEDBACK_DECISIONS
            or not isinstance(response.get("reason"), str)
            or not response["reason"].strip()
        )
        wrong_layer = (
            isinstance(response, dict)
            and _feedback_requires_candidate_decision(feedback)
            and response.get("decision") == "director_only"
        )
        if malformed or wrong_layer:
            invalid.append(index)
    return invalid


def _replace_director_feedback_responses(
    output: dict[str, Any], patch: dict[str, Any], target_indexes: list[int],
) -> dict[str, Any]:
    """Replace only explicitly invalid feedback rows and preserve all others."""
    if set(patch) != {"feedback_responses"}:
        raise CreativeContractError("导演意见回应替换补丁只能包含 feedback_responses")
    rows = patch.get("feedback_responses")
    if not isinstance(rows, list) or len(rows) != len(target_indexes):
        raise CreativeContractError("导演意见回应替换补丁数量与目标编号不一致")
    corrected = deepcopy(output)
    for expected_index, row in zip(target_indexes, rows):
        if (
            not isinstance(row, dict)
            or set(row) != {"feedback_index", "decision", "reason"}
            or row.get("feedback_index") != expected_index
            or row.get("decision") not in _DIRECTOR_FEEDBACK_DECISIONS
            or not isinstance(row.get("reason"), str)
            or not row["reason"].strip()
        ):
            raise CreativeContractError("导演意见回应替换补丁的编号、决定或理由无效")
        corrected["feedback_responses"][expected_index] = deepcopy(row)
    return corrected


def _project_feedback_patch_echo_metadata(
    patch: dict[str, Any],
) -> tuple[dict[str, Any], list[str]] | None:
    """Drop only boolean request metadata echoed into otherwise complete patch rows."""
    if set(patch) != {"feedback_responses"}:
        return None
    rows = patch.get("feedback_responses")
    if not isinstance(rows, list):
        return None
    required = {"feedback_index", "decision", "reason"}
    projected = deepcopy(patch)
    stripped: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required <= set(row):
            return None
        extras = set(row) - required
        if not extras:
            continue
        if not extras <= {"candidate_decision_required", "rationale_field"}:
            return None
        if (
            "candidate_decision_required" in extras
            and type(row.get("candidate_decision_required")) is not bool
        ):
            return None
        if (
            "rationale_field" in extras
            and str(row.get("rationale_field") or "").strip()
        ):
            return None
        for key in sorted(extras):
            projected["feedback_responses"][index].pop(key)
            stripped.append(f"feedback_responses[{index}].{key}")
    return (projected, stripped) if stripped else None


def _project_mismatched_raw_tail_to_planned_cut(
    output: dict[str, Any],
) -> tuple[dict[str, Any], list[str]] | None:
    """Conservatively require a cut adapter when raw-tail states are not identical."""
    rows = output.get("shots")
    if not isinstance(rows, list):
        return None
    projected = deepcopy(output)
    affected: list[str] = []
    previous_end: Any = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return None
        if (
            index > 0
            and row.get("continuity_mode") == "raw_tail_continuation"
            and row.get("start_state") != previous_end
        ):
            projected["shots"][index]["continuity_mode"] = (
                "planned_cut_requires_adapter"
            )
            affected.append(str(row.get("id") or f"shots[{index}]"))
        previous_end = row.get("end_state")
    return (projected, affected) if affected else None


def _candidate_with_director_scope(
    candidate: dict[str, Any], excerpt_record: dict[str, Any],
) -> dict[str, Any]:
    """Promote an accepted director source-boundary adjustment into the lock."""
    adjustment = excerpt_record.get("scope_adjustment")
    if not isinstance(adjustment, dict):
        return candidate
    adjusted = deepcopy(candidate)
    start_quote = (
        adjustment.get("lead_in_start_quote")
        or adjustment.get("trim_start_quote")
    )
    end_quote = (
        adjustment.get("extend_end_quote")
        or adjustment.get("trim_end_quote")
    )
    if isinstance(start_quote, str) and start_quote:
        adjusted["start_quote"] = start_quote
    if isinstance(end_quote, str) and end_quote:
        adjusted["end_quote"] = end_quote
    return adjusted


def _project_director_feedback_response_order(
    output: dict[str, Any], writer_feedback: list[Any],
) -> dict[str, Any] | None:
    """Sort a complete unique response set without changing any response text."""
    rows = output.get("feedback_responses")
    if not isinstance(rows, list) or len(rows) != len(writer_feedback):
        return None
    if any(not isinstance(row, dict) or type(row.get("feedback_index")) is not int for row in rows):
        return None
    expected = list(range(len(writer_feedback)))
    indexes = [row["feedback_index"] for row in rows]
    if sorted(indexes) != expected or indexes == expected:
        return None
    projected = deepcopy(output)
    projected["feedback_responses"] = sorted(
        projected["feedback_responses"], key=lambda row: row["feedback_index"],
    )
    return projected


def _project_redundant_action_dialogue_quotes(
    value: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Normalize only proven meta-references to dialogue inside action prose.

    Providers sometimes keep quoting a word from locked dialogue while
    describing its delivery. The projection handles only two grammar-safe
    forms: a quoted word after 尾音, and a quoted word before 落下后.
    It refuses every other quotation rather than silently rewriting action.
    """
    projected = deepcopy(value)
    beats: list[tuple[list[Any], dict[str, Any]]] = []
    if isinstance(projected.get("beats"), list):
        beats.extend(
            (["beats", index], row)
            for index, row in enumerate(projected["beats"])
            if isinstance(row, dict)
        )
    if isinstance(projected.get("replace_beats"), list):
        for index, wrapper in enumerate(projected["replace_beats"]):
            if isinstance(wrapper, dict) and isinstance(wrapper.get("beat"), dict):
                beats.append((["replace_beats", index, "beat"], wrapper["beat"]))
    changes: list[dict[str, Any]] = []
    quote_pattern = re.compile(
        r'"([^"\r\n]+)"|“([^”\r\n]+)”|「([^」\r\n]+)」|'
        r"'([^'\r\n]+)'|『([^』\r\n]+)』"
    )

    def compact(raw: str) -> str:
        return "".join(character for character in raw if character.isalnum())

    for beat_path, beat in beats:
        dialogue = beat.get("dialogue")
        if not isinstance(dialogue, list):
            continue
        spoken = [
            compact(str(row.get("text", "")))
            for row in dialogue if isinstance(row, dict)
        ]
        for field in ("before", "during", "after"):
            action = beat.get(field)
            if not isinstance(action, str):
                continue
            rewritten = action
            field_changes: list[dict[str, str]] = []
            matches = list(quote_pattern.finditer(action))
            for match in reversed(matches):
                quote = next(group for group in match.groups() if group is not None)
                normalized = compact(quote)
                if not normalized or not any(normalized in line for line in spoken):
                    continue
                prefix = rewritten[:match.start()]
                suffix = rewritten[match.end():]
                delivery_prefix = re.search(r"(?:尾音|句尾)\s*$", prefix)
                if delivery_prefix:
                    count_suffix = re.match(r"\s*(?:二字|两字|兩字)?", suffix)
                    start = match.start()
                    end = match.end() + (count_suffix.end() if count_suffix else 0)
                    replacement = ""
                else:
                    tail = re.match(
                        r"\s*(?:二字|两字|兩字)?"
                        r"(?:落下|落音|说完|說完|出口)(?:之?后|之?後)?",
                        suffix,
                    )
                    if not tail:
                        return None
                    start = match.start()
                    end = match.end() + tail.end()
                    replacement = "回答落音后"
                original = rewritten[start:end]
                rewritten = rewritten[:start] + replacement + rewritten[end:]
                field_changes.append({"original": original, "replacement": replacement})
            if quote_pattern.search(rewritten):
                remaining = [
                    next(group for group in match.groups() if group is not None)
                    for match in quote_pattern.finditer(rewritten)
                ]
                if any(
                    compact(quote)
                    and any(compact(quote) in line for line in spoken)
                    for quote in remaining
                ):
                    return None
            if rewritten != action:
                beat[field] = rewritten
                changes.append({
                    "path": [*beat_path, field],
                    "original": action,
                    "replacement": rewritten,
                    "rules": list(reversed(field_changes)),
                })
    return (projected, changes) if changes else None


def _project_singleton_dialogue_objects(
    output: dict[str, Any],
) -> tuple[dict[str, Any], list[str]] | None:
    """Wrap exact singleton dialogue objects in arrays without changing content."""
    projected = deepcopy(output)
    paths: list[str] = []

    def project_beats(beats: Any, prefix: str) -> None:
        if not isinstance(beats, list):
            return
        for index, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            dialogue = beat.get("dialogue")
            if (
                isinstance(dialogue, dict)
                and set(dialogue) == {"speaker", "text"}
                and all(isinstance(dialogue[key], str) for key in ("speaker", "text"))
            ):
                beat["dialogue"] = [dialogue]
                paths.append(f"{prefix}[{index}].dialogue")

    project_beats(projected.get("beats"), "beats")
    replacements = projected.get("replace_beats")
    if isinstance(replacements, list):
        for index, replacement in enumerate(replacements):
            if isinstance(replacement, dict) and isinstance(replacement.get("beat"), dict):
                project_beats(
                    [replacement["beat"]], f"replace_beats[{index}].beat",
                )
    if not paths:
        return None
    return projected, paths


def _project_candidate_meta_quote_as_prose(
    value: dict[str, Any], problem: str,
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Unquote a backward citation used only to explain what is not dramatized."""
    if "候选故事声明中的逐字原文对白顺序倒置或重复" not in problem:
        return None
    match = re.search(
        r"→\s*(setup|conflict|turn|peak|aftermath|selection_reason)=([^\n]+)",
        problem,
    )
    if not match:
        return None
    field, cited = match.group(1), _dialogue_text(match.group(2)).strip()
    candidate = value.get("candidate_update")
    if not isinstance(candidate, dict) or not isinstance(candidate.get(field), str):
        return None
    source_text = candidate[field]
    explanatory = any(marker in source_text for marker in (
        "仅作为", "僅作為", "只作为", "只作為", "只作", "原文引语", "原文引語",
    ))
    excluded = any(marker in source_text for marker in (
        "不当作", "不當作", "不写", "不寫", "不展开", "不展開", "并非", "並非",
    ))
    if not explanatory or not excluded:
        return None
    for opening, closing in (("「", "」"), ("“", "”"), ("『", "』")):
        pattern = re.escape(opening) + r"(.*?)" + re.escape(closing)
        for quoted in re.finditer(pattern, source_text):
            inner = quoted.group(1)
            normalized = _dialogue_text(inner).strip()
            if not normalized or not (
                normalized.startswith(cited) or cited.startswith(normalized)
            ):
                continue
            corrected = deepcopy(value)
            corrected["candidate_update"][field] = (
                source_text[:quoted.start()] + inner + source_text[quoted.end():]
            )
            return corrected, {
                "field": field,
                "quoted_text": inner,
                "rule": "removed quote delimiters from an explicit non-dramatized meta explanation",
            }
    return None


def _project_repeated_candidate_evidence_quote_as_prose(
    value: dict[str, Any], problem: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Unquote repeated same-field citations explicitly labelled as evidence."""
    if "候选故事声明中的逐字原文对白顺序倒置或重复" not in problem:
        return None
    match = re.search(
        r"(?:setup|conflict|turn|peak|aftermath)=([^\n]+?)\s*→\s*"
        r"(setup|conflict|turn|peak|aftermath)=([^\n]+)",
        problem,
    )
    if not match:
        return None
    field = match.group(2)
    cited = _dialogue_text(match.group(3)).strip()
    if not cited:
        return None
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        return None
    projected = deepcopy(value)
    changes: list[dict[str, Any]] = []
    quote_patterns = (
        r'"([^"\r\n]+)"', r"'([^'\r\n]+)'", r"「([^」\r\n]+)」",
        r"『([^』\r\n]+)』", r"“([^”\r\n]+)”",
    )
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or not isinstance(candidate.get(field), str):
            continue
        source_text = candidate[field]
        occurrences: list[tuple[int, int, str]] = []
        for pattern in quote_patterns:
            for quoted in re.finditer(pattern, source_text):
                if _dialogue_text(quoted.group(1)).strip() == cited:
                    occurrences.append((quoted.start(), quoted.end(), quoted.group(1)))
        occurrences.sort()
        if len(occurrences) < 2:
            continue
        replacements: list[tuple[int, int, str]] = []
        for start, end, inner in occurrences[1:]:
            prefix = source_text[max(0, start - 36):start]
            if not any(marker in prefix for marker in (
                "原著事实", "原文事实", "原文依据", "来源依据", "依据", "说明",
            )):
                continue
            replacements.append((start, end, inner))
        if not replacements:
            continue
        corrected_text = source_text
        for start, end, inner in reversed(replacements):
            corrected_text = corrected_text[:start] + inner + corrected_text[end:]
        projected["candidates"][index][field] = corrected_text
        changes.append({
            "candidate_index": index,
            "candidate_id": candidate.get("id"),
            "field": field,
            "quoted_text": cited,
            "unquoted_evidence_occurrences": len(replacements),
        })
    return (projected, changes) if changes else None


def _project_redundant_source_quote_wrappers(
    value: dict[str, Any], source: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Remove only a redundant outer quote pair around a unique exact source span."""
    if not isinstance(source, str) or not source:
        return None
    projected = deepcopy(value)
    changes: list[dict[str, Any]] = []
    pairs = {'"': '"', "'": "'", "“": "”", "「": "」", "『": "』"}

    def project(container: dict[str, Any], key: str, path: str) -> None:
        current = container.get(key)
        if not isinstance(current, str) or len(current) < 3 or source.count(current) == 1:
            return
        closing = pairs.get(current[0])
        if closing is None or current[-1] != closing:
            return
        inner = current[1:-1]
        if inner and source.count(inner) == 1:
            container[key] = inner
            changes.append({"path": path, "from": current, "to": inner})

    characters = projected.get("characters")
    if isinstance(characters, list):
        for index, row in enumerate(characters):
            if isinstance(row, dict):
                project(row, "source_quote", f"characters[{index}].source_quote")
    candidates = projected.get("candidates")
    if isinstance(candidates, list):
        for index, row in enumerate(candidates):
            if not isinstance(row, dict):
                continue
            project(row, "start_quote", f"candidates[{index}].start_quote")
            project(row, "end_quote", f"candidates[{index}].end_quote")
    return (projected, changes) if changes else None


def _project_explicit_issue_owner(
    value: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Honor an issue's explicit repair-layer statement when its owner contradicts it."""
    issues = value.get("issues")
    if not isinstance(issues, list):
        return None
    projected = deepcopy(value)
    changes: list[dict[str, Any]] = []
    for index, row in enumerate(issues):
        if not isinstance(row, dict):
            continue
        context = " ".join(str(row.get(key, "")) for key in ("evidence", "proposal"))
        owner = row.get("owner")
        explicit_writer = any(marker in context for marker in (
            "由 writer", "需 writer", "须由 writer", "歸 writer", "归 writer",
            "由编剧", "由編劇", "须由编剧", "須由編劇", "归编剧", "歸編劇",
        ))
        explicit_director = any(marker in context for marker in (
            "属 director", "屬 director", "由 director", "归 director", "歸 director",
            "由导演", "由導演", "归导演", "歸導演", "导演权限", "導演權限",
        ))
        proposal = str(row.get("proposal", ""))
        shot_only_proposal = bool(
            owner == "writer"
            and _shot_references(proposal)
            and not any(marker in proposal for marker in (
                "向 writer 申请", "向writer申请", "向编剧申请", "向編劇申請",
                "修改 beat", "修改beat", "改 beat", "改beat", "合并为单拍",
                "合併為單拍", "节拍数", "節拍數", ".duration_seconds",
            ))
        )
        if "总时长不变" in proposal or "總時長不變" in proposal:
            shot_only_proposal = bool(
                owner == "writer" and _shot_references(proposal)
            )
        target = None
        if (isinstance(owner, str) and owner not in ("writer", "director")
                and ("script" in owner.lower() or "编剧" in owner or "編劇" in owner)):
            target = "writer"
        elif (isinstance(owner, str) and owner not in ("writer", "director")
              and ("director" in owner.lower() or "导演" in owner or "導演" in owner)):
            target = "director"
        elif owner == "director" and explicit_writer:
            target = "writer"
        elif owner == "writer" and explicit_director and not re.search(
            r"(?<![A-Za-z0-9_])B\d+[A-Za-z]?\.duration_seconds"
            r"(?![A-Za-z0-9_])",
            context,
        ):
            target = "director"
        elif shot_only_proposal:
            target = "director"
        if target is not None:
            projected["issues"][index]["owner"] = target
            changes.append({
                "issue_index": index,
                "from": owner,
                "to": target,
                "rule": (
                    "shot-only proposal stays in director layer"
                    if shot_only_proposal and not explicit_director
                    else "issue text explicitly assigned the repair layer"
                ),
            })
    return (projected, changes) if changes else None


def _director_scope_repair_evidence(
    payload: dict[str, Any], output: dict[str, Any], problem: str,
) -> dict[str, Any]:
    """Keep a source-boundary repair small while still exposing exact nearby text."""
    materials = payload.get("materials") or {}
    source = materials.get("story_source", "")
    analysis = payload.get("analysis") or {}
    selected_id = analysis.get("selected_candidate_id")
    candidate = next(
        (row for row in analysis.get("candidates", []) if row.get("id") == selected_id),
        {},
    )
    window = ""
    if isinstance(source, str) and source and candidate:
        try:
            _, start = _canonical_source_quote(
                source, candidate.get("start_quote"), "candidate.start_quote",
            )
            end_quote, end_anchor = _canonical_source_quote(
                source, candidate.get("end_quote"), "candidate.end_quote",
            )
            end = end_anchor + len(end_quote)
            window = source[
                max(0, start - _DIRECTOR_SCOPE_WINDOW):
                min(len(source), end + _DIRECTOR_SCOPE_WINDOW)
            ]
        except CreativeContractError:
            window = (payload.get("selected_source") or {}).get("text", "")
    return {
        "error": problem,
        "draft_sha256": _hash(output),
        "current_source_scope": output.get("source_scope", {}),
        "candidate_lock": candidate,
        "source_window": window,
        "source_window_sha256": _hash(window),
        "rule": (
            "只决定是否需要前移/收窄候选起点或延长候选终点；引文必须从 source_window 逐字复制并唯一定位。"
            "没有可靠调整时全部字段留空。"
        ),
    }


def _project_whole_film_writer_duration_scale(
    payload: dict[str, Any], problem: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Return a full compact beat patch when a global duration repair is numeric only."""
    from .creative_brief import focus_duration_is_flexible
    if focus_duration_is_flexible((payload.get("material_ref") or {}).get("creative_focus", "")):
        return None
    if not problem.startswith("编剧局部返修"):
        return None
    issues = payload.get("issues") or []
    context = " ".join(
        str(issue.get(key, ""))
        for issue in issues if isinstance(issue, dict)
        for key in ("location", "evidence", "impact", "proposal")
    )
    if not (
        any(marker in context for marker in ("全片", "整片", "总时长", "總時長"))
        and any(marker in context for marker in ("duration_seconds", "超出上限", "总时长", "總時長"))
    ):
        return None
    script = payload.get("previous_script") or {}
    beats = script.get("beats") or []
    beat_ids = [row.get("id") for row in beats if isinstance(row, dict)]
    if not beat_ids or payload.get("affected_beat_ids") != beat_ids:
        return None
    analysis = payload.get("analysis") or {}
    selected = analysis.get("selected_candidate_id")
    candidates = analysis.get("candidates") or []
    candidate = next((row for row in candidates if isinstance(row, dict) and row.get("id") == selected), None)
    target = candidate.get("duration_seconds") if isinstance(candidate, dict) else None
    if type(target) not in (int, float) or target <= 0:
        return None
    target = int(target)
    current_values = [int(row.get("duration_seconds", 0)) for row in beats]
    current = sum(current_values)
    if current <= 0 or target < len(beats) or current == target:
        return None
    raw = [value * target / current for value in current_values]
    scaled = [max(1, int(value)) for value in raw]
    delta = target - sum(scaled)
    order = sorted(range(len(beats)), key=lambda index: raw[index] - int(raw[index]), reverse=delta > 0)
    cursor = 0
    while delta and order:
        index = order[cursor % len(order)]
        step = 1 if delta > 0 else -1
        if scaled[index] + step >= 1:
            scaled[index] += step
            delta -= step
        cursor += 1
    if sum(scaled) != target:
        return None
    rows, changes = [], []
    for beat, old, new in zip(beats, current_values, scaled):
        revised = deepcopy(beat)
        revised["duration_seconds"] = new
        rows.append({"beat_id": beat["id"], "beat": revised})
        if old != new:
            changes.append({"beat_id": beat["id"], "from": old, "to": new})
    return ({"replace_beats": rows}, changes) if changes else None


def _project_director_beat_duration_scale(
    output: dict[str, Any], script: dict[str, Any], problem: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Scale a malformed director beat to its locked duration without changing content."""
    if not any(marker in problem for marker in ("对白约", "分镜时长与剧本节拍不符")):
        return None
    shot_ids = set(_shot_references(problem))
    beat_ids = set(_beat_references(problem))
    for shot in output.get("shots", []):
        if isinstance(shot, dict) and shot.get("id") in shot_ids:
            beat_ids.add(shot.get("beat_id"))
    target_by_beat = {
        row.get("id"): row.get("duration_seconds")
        for row in script.get("beats", []) if isinstance(row, dict)
    }
    corrected = deepcopy(output)
    changes: list[dict[str, Any]] = []
    for beat_id in [row.get("id") for row in script.get("beats", []) if isinstance(row, dict)]:
        if beat_id not in beat_ids or type(target_by_beat.get(beat_id)) not in (int, float):
            continue
        indexes = [
            index for index, shot in enumerate(corrected.get("shots", []))
            if isinstance(shot, dict) and shot.get("beat_id") == beat_id
            and type(shot.get("duration_seconds")) in (int, float)
        ]
        target = int(target_by_beat[beat_id])
        current_values = [int(corrected["shots"][index]["duration_seconds"]) for index in indexes]
        current = sum(current_values)
        if not indexes or current <= 0 or target < len(indexes) or current == target:
            continue
        raw = [value * target / current for value in current_values]
        scaled = [max(1, int(value)) for value in raw]
        delta = target - sum(scaled)
        order = sorted(
            range(len(indexes)),
            key=lambda position: raw[position] - int(raw[position]),
            reverse=delta > 0,
        )
        cursor = 0
        while delta != 0 and order:
            position = order[cursor % len(order)]
            step = 1 if delta > 0 else -1
            if scaled[position] + step >= 1:
                scaled[position] += step
                delta -= step
            cursor += 1
        if sum(scaled) != target:
            continue
        for index, old, new in zip(indexes, current_values, scaled):
            if old != new:
                corrected["shots"][index]["duration_seconds"] = new
                changes.append({
                    "shot_id": corrected["shots"][index].get("id"),
                    "beat_id": beat_id, "from": old, "to": new,
                })
    return (corrected, changes) if changes else None


def _format_content_stream(value: str) -> str:
    """Compare prose and key order across a syntax-only JSON repair."""
    value = value.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
    value = re.sub(r"\\[nrt]", "", value)
    return "".join(char for char in value if char.isalnum() or char in "。！？；，、…—?!.%")


def _parse_format_repair(source: str, repaired: str) -> dict[str, Any]:
    try:
        value = parse_json_object(repaired)
    except CreativeContractError:
        value = _escape_embedded_json_quotes(repaired)
        if value is None:
            raise
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    original_body = source
    if not source.lstrip().startswith("{"):
        object_start = source.find("{")
        if object_start < 0:
            raise CreativeContractError("JSON 格式修复找不到原始对象正文")
        original_body = source[object_start:]
    if _format_content_stream(original_body) != _format_content_stream(canonical):
        # A contract-repair model can echo the repair envelope and leave only the
        # embedded ``original`` object syntactically damaged.  A later syntax-only
        # repair is safe to reuse when it contains exactly the same alphanumeric
        # content and key/value order as that embedded object, excluding envelope
        # diagnostics and hashes.  This still rejects any prose or value rewrite.
        original_marker = re.search(r'"original"\s*:', original_body)
        provenance_marker = (
            re.search(r',\s*"source_sha256"\s*:', original_body[original_marker.end():])
            if original_marker else None
        )
        embedded_body = None
        if original_marker and provenance_marker:
            embedded_body = original_body[
                original_marker.end():
                original_marker.end() + provenance_marker.start()
            ]
        if (embedded_body is None
                or _format_content_stream(embedded_body) != _format_content_stream(canonical)):
            raise CreativeContractError("JSON 格式修复改动了正文内容或字段顺序，拒绝复用")
    return value


def _escape_embedded_json_quotes(raw: str) -> dict[str, Any] | None:
    """Recover only quotation marks embedded in JSON strings, without changing text."""
    fixed: list[str] = []
    inside = escaped = changed = False
    for index, char in enumerate(raw):
        if char == '"' and inside and not escaped:
            tail = raw[index + 1:].lstrip()
            if tail and tail[0] not in ",:}]":
                fixed.append('\\"')
                changed = True
                continue
            inside = False
        elif char == '"' and not inside:
            inside = True
        if char == "\\" and inside and not escaped:
            escaped = True
        else:
            escaped = False
        fixed.append(char)
    if not changed or inside:
        return None
    try:
        value = parse_json_object("".join(fixed))
    except CreativeContractError:
        return None
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value if _format_content_stream(raw) == _format_content_stream(canonical) else None


def _execution_draft(script: dict[str, Any], shots: dict[str, Any]) -> dict[str, Any]:
    """Compile checked shot requirements without pretending to know media segment support."""
    beats = {row["id"]: row for row in script["beats"]}
    requirements = []
    for shot in shots["shots"]:
        beat = beats[shot["beat_id"]]
        requirements.append({
            "shot_id": shot["id"],
            "beat_id": beat["id"],
            "beat_event": beat["event"],
            "purpose": shot["purpose"],
            "composition": shot["composition"],
            "camera": shot["camera"],
            "visible_performance": shot["visible_performance"],
            "dialogue_lock": deepcopy(shot["dialogue_lock"]),
            "start_state": shot["start_state"],
            "end_state": shot["end_state"],
            "continuity_mode": shot["continuity_mode"],
            "prompt": shot["prompt"],
            "production_choices": deepcopy(shot["production_choices"]),
        })
    return {
        "schema": "creative_execution_draft/v1",
        "script_sha256": _hash(script),
        "shots_sha256": _hash(shots),
        "shot_requirements": requirements,
        "generation_segments": [],
        "segment_mapping_status": "pending_executor_capability",
        "automatic_submit": False,
    }


def _review_packet(
    analysis: dict[str, Any], brief: dict[str, Any], script: dict[str, Any],
    shots: dict[str, Any], check: dict[str, Any], material_sha256: str,
    *, assistant_review_required: bool, source_scope_audit: dict[str, Any],
) -> dict[str, Any]:
    selected = next(
        row for row in analysis["candidates"]
        if row["id"] == analysis["selected_candidate_id"]
    )
    shot_rows = shots["shots"]
    return {
        "schema": "creative_editorial_review_packet/v1",
        "material_sha256": material_sha256,
        "analysis_sha256": _hash(analysis),
        "brief_sha256": _hash(brief),
        "script_sha256": _hash(script),
        "shots_sha256": _hash(shots),
        "writer_check_sha256": _hash(check),
        "source_scope_audit": deepcopy(source_scope_audit),
        "review_status": ("assistant_review_pending" if assistant_review_required
                          else "routine_assistant_review_waived_after_calibration"),
        "human_spot_check": "not_performed",
        "video_review": "not_performed",
        "selected_candidate": {
            "id": selected["id"], "title": selected["title"],
            "start_quote": selected.get("start_quote", ""),
            "end_quote": selected.get("end_quote", ""),
            "selection_reason": analysis["selection_reason"],
        },
        "characters_and_evidence": deepcopy(analysis["characters"]),
        "director_style": {
            "selected_style_id": brief["selected_style_id"],
            "visual_strategy": brief["visual_strategy"],
            "performance_strategy": brief["performance_strategy"],
        },
        "emotion_windows": [
            {
                "beat_id": beat["id"],
                "event": beat["event"],
                "trigger": beat["trigger"],
                "before": beat["before"],
                "during": beat["during"],
                "after": beat["after"],
                "dialogue": deepcopy(beat["dialogue"]),
                "shots": [
                    {"id": shot["id"], "purpose": shot["purpose"],
                     "composition": shot["composition"],
                     "visible_performance": shot["visible_performance"]}
                    for shot in shot_rows if shot["beat_id"] == beat["id"]
                ],
            }
            for beat in script["beats"]
        ],
        "minor_writer_issues": [
            deepcopy(row) for row in check["issues"] if row["severity"] == "minor"
        ],
    }


def _review_packet_markdown(packet: dict[str, Any]) -> str:
    selected = packet["selected_candidate"]
    review_note = (
        "状态：待助手实际复核；本文件由程序汇集证据，不表示人物、动机或情绪已经通过。"
        if packet["review_status"] == "assistant_review_pending"
        else "状态：前期校准已达标，本稿不要求逐稿助手复核；程序与双角色检查不能冒称独立主观审核通过。"
    )
    lines = [
        "# 剧本与导演稿集中复核包",
        "",
        review_note,
        "",
        f"选段：{selected['title']}（{selected['id']}）",
        f"选择理由：{selected['selection_reason']}",
        f"起点引文：{selected['start_quote'] or '视频原创，无小说引文'}",
        f"终点引文：{selected['end_quote'] or '视频原创，无小说引文'}",
        f"选段起点提示：{packet['source_scope_audit']['reason']}",
        "",
        "## 人物与来源证据",
        "",
    ]
    for row in packet["characters_and_evidence"]:
        lines.append(f"- {row['name']}：目标 {row['want']}；来源 {row.get('source_quote') or '原创故事设定'}")
    lines.extend(["", "## 情绪节拍与镜头", ""])
    for beat in packet["emotion_windows"]:
        lines.extend([
            f"### {beat['beat_id']} {beat['event']}", "",
            f"刺激：{beat['trigger']}",
            f"前：{beat['before']}",
            f"中：{beat['during']}",
            f"后：{beat['after']}",
            "对白：" + ("；".join(f"{row['speaker']}：{row['text']}" for row in beat["dialogue"]) or "无"),
            "镜头：" + ("；".join(
                f"{row['id']} {row['purpose']} / {row['composition']} / {row['visible_performance']}"
                for row in beat["shots"]
            ) or "无"),
            "",
        ])
    return "\n".join(lines)


def _repair_evidence(payload: dict[str, Any], output: dict[str, Any], problem: str) -> dict[str, Any]:
    """Give a repair call relevant raw lines, not a second full-book payload."""
    material = payload.get("story_source") or payload.get("materials") or payload.get("source") or {}
    creative_focus = payload.get("creative_focus", "")
    if isinstance(material, dict):
        source = material.get("story_source", "")
        creative_focus = material.get("creative_focus", creative_focus)
    else:
        source = material
    if not source:
        source = payload.get("source_chunk") or payload.get("reference_chunk") or ""
    if not isinstance(source, str):
        source = ""
    candidates = output.get("candidates", [])
    questionable = []
    invalid_character_quotes = []
    invalid_candidate_quotes = []
    compact_source = "".join(char for char in source if char.isalnum())
    characters = output.get("characters", [])
    if isinstance(characters, list):
        for index, character in enumerate(characters):
            if not isinstance(character, dict):
                continue
            quote = character.get("source_quote")
            if not isinstance(quote, str) or not quote:
                continue
            compact_quote = "".join(char for char in quote if char.isalnum())
            if len(compact_quote) < 8 or compact_source.count(compact_quote) != 1:
                invalid_character_quotes.append({
                    "path": ["characters", index, "source_quote"],
                    "name": character.get("name"), "invalid_quote": quote,
                })
                questionable.extend(
                    fragment.strip() for fragment in re.split(r"…+|\.\.\.+", quote)
                    if sum(char.isalnum() for char in fragment) >= 8
                )
    if isinstance(candidates, list):
        for candidate_index, candidate in enumerate(candidates):
            if isinstance(candidate, dict):
                for key in ("start_quote", "end_quote"):
                    quote = candidate.get(key)
                    if isinstance(quote, str) and quote and source.count(quote) != 1:
                        questionable.append(quote)
                        invalid_candidate_quotes.append({
                            "path": ["candidates", candidate_index, key],
                            "candidate_id": candidate.get("id"),
                            "invalid_quote": quote,
                        })
    lines = source.splitlines()
    scored = []
    for index, line in enumerate(lines):
        if line.strip() and questionable:
            score = max(SequenceMatcher(None, quote, line.strip()).ratio() for quote in questionable)
            if score >= 0.35:
                scored.append((score, index))
    scored.sort(reverse=True)
    seen: set[int] = set()
    excerpts = []
    for _, index in scored[:5]:
        if index in seen:
            continue
        seen.add(index)
        excerpts.append({"line": index + 1, "text": "\n".join(lines[max(0, index - 3):index + 4])})
    structurally_incomplete = not isinstance(characters, list) or not isinstance(candidates, list) or not candidates
    if (not excerpts and (structurally_incomplete or questionable)
            and isinstance(creative_focus, str) and creative_focus):
        chapter = re.search(r"第\s*[0-9一二三四五六七八九十百千两]+\s*章", creative_focus)
        if chapter:
            start = source.find(chapter.group(0))
            if start >= 0:
                following = re.search(
                    r"第\s*[0-9一二三四五六七八九十百千两]+\s*章", source[start + len(chapter.group(0)):],
                )
                end = (
                    start + len(chapter.group(0)) + following.start()
                    if following else min(len(source), start + 12000)
                )
                excerpts.append({"line": "creative_focus_chapter", "text": source[start:end][:12000]})
        if not excerpts:
            focus_parts = [
                part.strip() for part in re.split(r"[，。；：、\s]+", creative_focus)
                if len(part.strip()) >= 4
            ]
            focus_scores = []
            for index, line in enumerate(lines):
                if not line.strip() or not focus_parts:
                    continue
                score = max(SequenceMatcher(None, part, line.strip()).ratio() for part in focus_parts)
                if score >= 0.3:
                    focus_scores.append((score, index))
            for _, index in sorted(focus_scores, reverse=True)[:3]:
                excerpts.append({
                    "line": index + 1,
                    "text": "\n".join(lines[max(0, index - 8):index + 9]),
                })
    selected_source = payload.get("selected_source")
    if not excerpts and isinstance(selected_source, dict) and isinstance(selected_source.get("text"), str):
        excerpts.append({"line": "selected_excerpt", "text": selected_source["text"][:10000]})
    return {
        "error": problem,
        "original": output,
        "source_sha256": _hash(source),
        "source_evidence": excerpts,
        "invalid_character_quotes": invalid_character_quotes,
        "invalid_candidate_quotes": invalid_candidate_quotes,
        "creative_focus": creative_focus,
        "source_evidence_limit": "只可修复证据覆盖的字段；证据不足须报告未解决，不能编造引文",
    }


def _candidate_quote_repair_evidence(
    payload: dict[str, Any], output: dict[str, Any], problem: str,
    invalid_paths: list[list[Any]],
) -> dict[str, Any]:
    """Provide exact nearby source without asking MiniMax to resend the analysis."""
    evidence = _repair_evidence(payload, output, problem)
    candidate_indexes = sorted({path[1] for path in invalid_paths})
    candidates = output.get("candidates", [])
    return {
        "error": problem,
        "draft_sha256": _hash(output),
        "invalid_candidate_quotes": [
            row for row in evidence["invalid_candidate_quotes"]
            if row.get("path") in invalid_paths
        ],
        "candidate_context": [
            {"index": index, "candidate": candidates[index]}
            for index in candidate_indexes
            if isinstance(candidates, list) and 0 <= index < len(candidates)
        ],
        "source_evidence": evidence["source_evidence"],
        "source_sha256": evidence["source_sha256"],
        "rule": "只返回 invalid_candidate_quotes 对应的逐字引文补丁；其他分析字段不可改动",
    }


def _director_repair_evidence(
    payload: dict[str, Any], output: dict[str, Any], problem: str,
) -> dict[str, Any]:
    """Send the failing shot neighborhood and current beat locks, not a full storyboard."""
    script = payload.get("script", {})
    beats = script.get("beats", []) if isinstance(script, dict) else []
    shots = output.get("shots", [])
    beat_locks = {
        beat["id"]: {
            "event": beat.get("event"),
            "duration_seconds": beat.get("duration_seconds"),
            "dialogue": beat.get("dialogue"),
        }
        for beat in beats if isinstance(beat, dict) and isinstance(beat.get("id"), str)
    }
    if not isinstance(shots, list):
        shots = []
    shot_index = [
        {"index": index, "id": shot.get("id"), "beat_id": shot.get("beat_id"),
         "duration_seconds": shot.get("duration_seconds"),
         "event_lock": shot.get("event_lock")}
        for index, shot in enumerate(shots) if isinstance(shot, dict)
    ]
    referenced_shots = set(_shot_references(problem))
    referenced_beats = set(_beat_references(problem))
    mismatched_locks = [
        row for row in shot_index
        if row["beat_id"] in beat_locks
        and row["event_lock"] != beat_locks[row["beat_id"]]["event"]
    ]
    affected = {
        row["index"] for row in shot_index
        if row["id"] in referenced_shots or row["beat_id"] in referenced_beats
    }
    if mismatched_locks and "未绑定编剧定稿事件" in problem:
        affected.update(row["index"] for row in mismatched_locks)
    if not affected:
        affected = {row["index"] for row in shot_index[:2]}
    event_lock_only = "未绑定编剧定稿事件" in problem
    neighborhood = (
        affected if event_lock_only else {
            neighbor for index in affected for neighbor in (index - 1, index, index + 1)
            if 0 <= neighbor < len(shots)
        }
    )
    return {
        "error": problem,
        "original_sha256": _hash(output),
        "beat_locks": beat_locks,
        "shot_index": shot_index,
        "invalid_event_locks": mismatched_locks,
        "affected_shots": [
            {"index": index, "shot": (
                {key: shots[index].get(key) for key in ("id", "beat_id", "event_lock")}
                if event_lock_only else shots[index]
            )}
            for index in sorted(neighborhood) if isinstance(shots[index], dict)
        ],
        "repair_scope": "只按原稿索引提交已有字段补丁；未展示的镜头保持不变",
    }


def _apply_repair_patches(original: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    patches = repair.get("patches")
    if not isinstance(patches, list) or not 1 <= len(patches) <= 3:
        raise CreativeContractError("定向修复必须包含 1-3 个字段补丁")
    corrected = deepcopy(original)
    for patch in patches:
        if not isinstance(patch, dict) or not isinstance(patch.get("path"), list):
            raise CreativeContractError("补丁路径无效")
        path = patch["path"]
        if len(path) < 2 or path[0] not in ("shots", "style"):
            raise CreativeContractError("补丁超出导演稿允许修订范围")
        cursor: Any = corrected
        for part in path[:-1]:
            if isinstance(cursor, list) and type(part) is int and 0 <= part < len(cursor):
                cursor = cursor[part]
            elif isinstance(cursor, dict) and isinstance(part, str) and part in cursor:
                cursor = cursor[part]
            else:
                raise CreativeContractError("补丁指向不存在的字段")
        final = path[-1]
        if not isinstance(cursor, dict) or not isinstance(final, str) or final not in cursor:
            raise CreativeContractError("补丁只能替换已有字段")
        cursor[final] = patch.get("value")
    return corrected


def _apply_writer_action_patches(
    original: dict[str, Any], repair: dict[str, Any], required: list[list[Any]],
) -> dict[str, Any]:
    """Replace only action fields that paraphrase locked dialogue."""
    patches = repair.get("patches")
    if not isinstance(patches, list) or len(patches) != len(required):
        raise CreativeContractError("编剧动作复述修复必须逐项提交全部目标字段")
    if [row.get("path") for row in patches if isinstance(row, dict)] != required:
        raise CreativeContractError("编剧动作复述修复路径与目标清单不一致")
    corrected = deepcopy(original)
    changed = False
    for patch, path in zip(patches, required, strict=True):
        if (not isinstance(patch, dict) or set(patch) != {"path", "value"}
                or len(path) != 3 or path[0] != "beats"
                or type(path[1]) is not int
                or path[2] not in ("before", "during", "after")):
            raise CreativeContractError("编剧动作复述修复只能替换指定动作字段")
        value = patch["value"]
        if not isinstance(value, str) or not value.strip():
            raise CreativeContractError("编剧动作复述修复必须返回非空可见动作")
        current = corrected["beats"][path[1]][path[2]]
        if value != current:
            changed = True
        corrected["beats"][path[1]][path[2]] = value.strip()
    if not changed:
        raise CreativeContractError("编剧动作复述修复没有改变目标字段")
    return corrected


def _issue_beat_ids(
    script: dict[str, Any], issues: list[dict[str, Any]],
    previous_shots: dict[str, Any] | None = None,
) -> list[str]:
    """Resolve issue locations to script beat ids without trusting prose ownership."""
    beat_order = [
        row.get("id") for row in script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]
    affected: set[str] = set()
    shot_to_beat = {
        row.get("id"): row.get("beat_id")
        for row in (previous_shots or {}).get("shots", []) if isinstance(row, dict)
        if isinstance(row.get("id"), str) and isinstance(row.get("beat_id"), str)
    }
    for issue in issues:
        location = str(issue.get("location", ""))
        issue_context = " ".join(
            str(issue.get(key, "")) for key in ("location", "evidence", "impact", "proposal")
        )
        if (
            any(marker in issue_context for marker in ("全片", "整片", "总时长", "總時長"))
            and any(marker in issue_context for marker in (
                "duration_seconds", "总时长", "總時長", "时长范围", "時長範圍",
                "超出上限", "合计", "合計",
            ))
        ):
            affected.update(beat_order)
            continue
        if location in beat_order:
            affected.add(location)
            continue
        if location in shot_to_beat:
            affected.add(shot_to_beat[location])
            continue
        # The structured location is authoritative when it resolves. Proposals
        # often name unaffected beats only to say that they must stay unchanged.
        # Treating those guardrails as targets widens a scoped repair and lets a
        # model rewrite already-approved beats.
        location_beats = set(_beat_references(location))
        location_shots = set(_shot_references(location))
        text = location if location_beats or location_shots else " ".join(
            str(issue.get(key, "")) for key in ("evidence", "proposal")
        )
        affected.update(_beat_references(text))
        for first, last in re.findall(
            r"(?<![A-Za-z0-9_])(B\d+[A-Za-z]?)\s*"
            r"(?:-|—|–|~|～|至|到)\s*(B\d+[A-Za-z]?)(?![A-Za-z0-9_])",
            text,
        ):
            if first in beat_order and last in beat_order:
                start, stop = beat_order.index(first), beat_order.index(last)
                if start <= stop:
                    affected.update(beat_order[start:stop + 1])
        for shot_id in _shot_references(text):
            if shot_id in shot_to_beat:
                affected.add(shot_to_beat[shot_id])
    return [beat_id for beat_id in beat_order if beat_id in affected]


def _dialogue_split_repair_beat_ids(
    script: dict[str, Any], problem: str,
) -> list[str]:
    """Route false in-dialogue timing prose to a compact beat repair."""
    if "语言时间锚点模拟单条长对白内部动作" not in problem:
        return []
    referenced = set(_beat_references(problem))
    return [
        row["id"] for row in script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
        and row["id"] in referenced
    ]


def _proposal_has_concrete_local_beat_fix(proposal: str) -> bool:
    """Recognize a concrete beat edit that takes precedence over a fallback upstream note."""
    return bool(re.search(
        r"(?:拆|合并|合併|移到|移入|重分配|重新分配|调整|調整|改为|改為)"
        r".{0,28}(?:B\d|beat|节拍|節拍|before|during|after|对白|對白)",
        proposal,
        re.I,
    ))


def _story_issues_require_source_boundary(issues: list[dict[str, Any]]) -> bool:
    """Do not spend beat-revision calls on an explicitly locked source boundary."""
    for issue in issues:
        proposal = str(issue.get("proposal", ""))
        context = " ".join(
            str(issue.get(key, "")) for key in ("location", "evidence", "proposal")
        )
        explicit_boundary_change = bool(re.search(
            r"(?:扩展|擴展|延长|延長|收窄|前移|后移|後移|修改|调整|調整)"
            r".{0,24}(?:selected_source|选段|選段|边界|邊界|end_quote|start_quote)",
            proposal,
            re.I,
        ))
        generic_upstream_scope = any(
            marker in proposal
            for marker in ("需上游选段/候选修订", "需上游選段/候選修訂")
        )
        if (
            issue.get("owner") == "writer"
            and issue.get("severity") in ("blocking", "major")
            and "selected_source" in context
            and (explicit_boundary_change or generic_upstream_scope)
            and not _proposal_has_concrete_local_beat_fix(proposal)
        ):
            return True
    return False


def _story_issues_require_candidate_revision(issues: list[dict[str, Any]]) -> bool:
    """Stop local beat repairs when the reviewer explicitly routes to candidate scope."""
    for issue in issues:
        proposal = str(issue.get("proposal", "")).strip()
        explicit_return = proposal.startswith(("退回候选层", "需退回候选层", "須退回候選層"))
        if (
            issue.get("owner") == "writer"
            and issue.get("severity") in ("blocking", "major")
            and not _proposal_has_concrete_local_beat_fix(proposal)
            and (
                explicit_return
                or any(marker in proposal for marker in (
                    "需上游候选", "需上游选段/候选修订", "更换候选",
                    "候选层修订", "修改候选呈现约束",
                    "不能由当前编剧或导演局部补写", "唯一解需要",
                ))
            )
        ):
            return True
    return False


def _audit_review_source_absence_claims(
    issues: list[dict[str, Any]], script: dict[str, Any], selected_source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dismiss only review claims directly contradicted by locked source text.

    This is deliberately narrow: an issue must claim that cited dialogue is
    absent from the selected source, while its exact normalized dialogue is
    quoted in the evidence and present in that source. Subjective context,
    motivation, performance and source-boundary judgments remain untouched.
    """
    source_text = _dialogue_text(selected_source)
    beats = {
        row.get("id"): row for row in script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    absence_markers = (
        "未出现", "未出現", "不在选段", "不在選段", "选段外", "選段外",
        "不属于选段", "不屬於選段", "not in selected_source",
    )
    kept: list[dict[str, Any]] = []
    dismissed: list[dict[str, Any]] = []
    for index, issue in enumerate(issues):
        evidence = str(issue.get("evidence", ""))
        context = _dialogue_text(" ".join(
            str(issue.get(key, "")) for key in ("evidence", "impact", "proposal")
        ))
        if not any(marker in context for marker in absence_markers):
            kept.append(issue)
            continue
        beat_ids = []
        issue_text = " ".join(
            str(issue.get(key, "")) for key in ("location", "evidence", "proposal")
        )
        for beat_id in _beat_references(issue_text):
            if beat_id in beats and beat_id not in beat_ids:
                beat_ids.append(beat_id)
        contradicted_lines = []
        normalized_evidence = _dialogue_text(evidence)
        for beat_id in beat_ids:
            for line in beats[beat_id].get("dialogue", []):
                if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                    continue
                text = _dialogue_text(line["text"])
                if text and text in normalized_evidence and text in source_text:
                    contradicted_lines.append({"beat_id": beat_id, "text": line["text"]})
        if not contradicted_lines:
            kept.append(issue)
            continue
        dismissed.append({
            "issue_index": index,
            "issue_sha256": _hash(issue),
            "reason": "review_claimed_cited_dialogue_absent_but_exact_text_is_in_selected_source",
            "contradicted_dialogue": contradicted_lines,
        })
    return kept, dismissed


def _is_unconfirmed_transport(error: object) -> bool:
    """Recognize no-request-id failures eligible for one explicitly requested retry."""
    text = str(error)
    return (
        "request_id=unknown" in text
        and ("APIConnectionError" in text or "status=529" in text)
    )


def _project_missing_review_suggestions(output, context):
    """An omitted optional-advice list is empty, never a clearance decision."""
    if "suggestions" in output or not isinstance(output.get("issues"), list):
        return None
    focus = output.get("calibration_focus")
    if not isinstance(focus, list) or any(not isinstance(x, str) or not x.strip() for x in focus):
        return None
    corrected = {**deepcopy(output), "suggestions": []}
    try:
        validate_review(corrected, context)
    except CreativeContractError:
        return None
    return corrected


def _project_story_issue_enrichment(original, response, context):
    source, rows = original.get("story_issues"), response.get("story_issues")
    if set(response) != {"story_issues"} or not isinstance(source, list) or not isinstance(rows, list) or len(source) != len(rows):
        raise CreativeContractError("剧情问题补全必须逐项保留全部 story_issues")
    ids = [b.get("id") for b in context.get("script", {}).get("beats", [])]
    result, changes, rejected = [], [], []
    for index, (old, new) in enumerate(zip(source, rows)):
        if not isinstance(old, dict) or not isinstance(new, dict):
            raise CreativeContractError("剧情问题补全必须保留原问题对象")
        merged = deepcopy(old)
        for key in ("id", "rule", "contradiction", "evidence_refs"):
            if key not in old and key in new:
                merged[key] = deepcopy(new[key])
        ignored = [key for key in new if key not in ("id", "rule", "contradiction", "evidence_refs", "location") and new[key] != old.get(key)]
        if ignored:
            changes.append({"index": index, "ignored_rewritten_fields": ignored})
        location = old.get("location")
        if location not in ids:
            match = re.fullmatch(r"B0*(\d+)", str(location))
            choices = [bid for bid in ids if match and re.fullmatch(r"B0*" + str(int(match[1])), str(bid))]
            if len(choices) == 1:
                merged["location"] = choices[0]
        refs = merged.get("evidence_refs")
        # Never weaken preexisting evidence. Newly proposed invalid supplemental
        # references are recorded, not promoted into the review packet.
        if "evidence_refs" not in old and isinstance(refs, list):
            valid_refs = []
            for ref in refs:
                try:
                    target = context
                    for part in ref["path"].split("."):
                        target = target[int(part)] if isinstance(target, list) and part.isdecimal() else target[part]
                    quote = ref["quote"]
                    valid = isinstance(quote, str) and bool(quote) and (
                        isinstance(target, str) and quote in target or type(target) in (int, float) and quote == json.dumps(target))
                except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                    valid = False
                if valid:
                    valid_refs.append(deepcopy(ref))
                else:
                    rejected.append({"index": index, "reference": deepcopy(ref), "reason": "unresolvable_or_nonverbatim_supplemental_reference"})
            merged["evidence_refs"] = valid_refs
        result.append(merged)
    corrected = {"story_issues": result}
    _validate_story_issue_enrichment(original, corrected, context.get("script") or {})
    return corrected, {"ignored_rewrites": changes, "rejected_supplemental_references": rejected,
                       "assistant_review_required": True}


def _validate_story_issue_enrichment(original, corrected, script):
    """Formatting may add audit evidence but cannot dismiss or rewrite complaints."""
    rows = corrected.get("story_issues")
    source = original.get("story_issues")
    if set(corrected) != {"story_issues"} or not isinstance(rows, list) or not isinstance(source, list) or len(rows) != len(source):
        raise CreativeContractError("剧情问题补全必须逐项保留全部 story_issues")
    ids = [b.get("id") for b in script.get("beats", [])]
    for before, after in zip(source, rows):
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise CreativeContractError("剧情问题补全必须保留原问题对象")
        for key, value in before.items():
            if key == "location":
                if after.get(key) == value:
                    continue
                match = re.fullmatch(r"B0*(\d+)", str(value))
                choices = [bid for bid in ids if match and re.fullmatch(r"B0*" + str(int(match[1])), str(bid))]
                if len(choices) == 1 and after.get(key) == choices[0]:
                    continue
            elif after.get(key) == value:
                continue
            raise CreativeContractError("剧情问题补全不得改写、删减原意见；仅允许唯一节拍编号归位")


def _project_writer_revision(
    previous_script: dict[str, Any], proposed_script: dict[str, Any], affected_beat_ids: list[str],
    *, allow_summary_update: bool = False,
) -> dict[str, Any]:
    """Accept revised complete beats only where the issue list granted write scope."""
    if not affected_beat_ids:
        raise CreativeContractError("编剧返修问题没有可定位的节拍")
    proposed = {
        row.get("id"): row for row in proposed_script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if any(beat_id not in proposed for beat_id in affected_beat_ids):
        raise CreativeContractError("编剧返修缺少受影响节拍")
    projected = deepcopy(previous_script)
    projected["beats"] = [
        deepcopy(proposed[row["id"]]) if row.get("id") in affected_beat_ids else deepcopy(row)
        for row in previous_script.get("beats", []) if isinstance(row, dict)
    ]
    projected["duration_seconds"] = sum(
        row.get("duration_seconds", 0) for row in projected["beats"]
    )
    if allow_summary_update:
        premise = proposed_script.get("premise")
        if not isinstance(premise, str) or not premise.strip():
            raise CreativeContractError("授权摘要返修必须提供完整非空 premise")
        projected["premise"] = premise
    projected["screenplay_markdown"] = compile_beat_screenplay(projected)
    return projected


def _writer_revision_schema(ids: list[str]) -> dict:
    schema = deepcopy(WRITER_TOOL_SCHEMAS["writer_revise"])
    rows = schema["properties"]["replace_beats"]
    rows.update(minItems=len(ids), maxItems=len(ids))
    rows["items"]["properties"]["beat_id"] = {"type": "string", "enum": ids}
    return schema


def _validate_production_design(value: dict, shots: dict, catalog: list) -> None:
    from .reusable_production import validate_design
    try:
        validate_design(value, shots, catalog)
    except (ValueError, TypeError, KeyError) as exc:
        raise CreativeContractError(str(exc)) from exc


def _apply_writer_revision_patch(
    previous_script: dict[str, Any], patch: dict[str, Any], affected_beat_ids: list[str],
) -> dict[str, Any]:
    """Merge compact MiniMax beat replacements into the immutable parent script."""
    # Diagnose all missing content, including a misplaced wrapper, without
    # silently copying an unrevised beat from the parent script.
    rows_for_diagnosis = patch.get("replace_beats", [])
    if isinstance(rows_for_diagnosis, list):
        supplied = [r.get("beat_id") for r in rows_for_diagnosis if isinstance(r, dict)]
        misplaced = patch.get("item")
        misplaced_id = misplaced.get("beat_id") if isinstance(misplaced, dict) else None
        missing = [bid for bid in affected_beat_ids if bid not in supplied and bid != misplaced_id]
        if missing:
            raise CreativeContractError(
                f"编剧局部返修必须逐拍提交全部受影响节拍；缺失节拍: {missing}；"
                f"清单外 item 节拍: {misplaced_id}；必须由编剧补全缺失内容，禁止用旧稿冒充返修"
            )
    if set(patch) != {"replace_beats"} or not isinstance(patch["replace_beats"], list):
        raise CreativeContractError("编剧局部返修必须只提交 replace_beats")
    rows = patch["replace_beats"]
    if len(rows) != len(affected_beat_ids) or any(not isinstance(row, dict) for row in rows):
        raise CreativeContractError("编剧局部返修必须逐拍提交全部受影响节拍")
    if [row.get("beat_id") for row in rows] != affected_beat_ids:
        raise CreativeContractError("编剧局部返修节拍顺序与受影响清单不一致")
    replacements: dict[str, dict[str, Any]] = {}
    for row in rows:
        if set(row) != {"beat_id", "beat"} or not isinstance(row["beat"], dict):
            raise CreativeContractError("编剧局部返修每项必须包含 beat_id 和完整 beat")
        if row["beat"].get("id") != row["beat_id"]:
            raise CreativeContractError("编剧局部返修内外节拍 ID 不一致")
        replacements[row["beat_id"]] = deepcopy(row["beat"])
    projected = deepcopy(previous_script)
    projected["beats"] = [
        replacements.get(row.get("id"), deepcopy(row))
        for row in previous_script.get("beats", []) if isinstance(row, dict)
    ]
    if set(replacements) != set(affected_beat_ids):
        raise CreativeContractError("编剧局部返修包含父稿不存在的节拍")
    projected["duration_seconds"] = sum(
        row.get("duration_seconds", 0) for row in projected["beats"]
    )
    projected["screenplay_markdown"] = compile_beat_screenplay(projected)
    return projected


def _project_flat_writer_revision_patch(
    patch: dict[str, Any], affected_beat_ids: list[str],
) -> dict[str, Any] | None:
    """Wrap an exact flat replacement row without changing model-authored beat content."""
    if set(patch) != {"replace_beats"} or not isinstance(patch["replace_beats"], list):
        return None
    rows = patch["replace_beats"]
    flat_keys = {
        "beat_id", "duration_seconds", "event", "trigger", "before", "during",
        "after", "dialogue",
    }
    if (
        len(rows) != len(affected_beat_ids)
        or any(not isinstance(row, dict) or set(row) != flat_keys for row in rows)
        or [row["beat_id"] for row in rows] != affected_beat_ids
    ):
        return None
    return {
        "replace_beats": [
            {
                "beat_id": row["beat_id"],
                "beat": {
                    "id": row["beat_id"],
                    **{
                        key: deepcopy(value) for key, value in row.items()
                        if key != "beat_id"
                    },
                },
            }
            for row in rows
        ]
    }


def _project_interleaved_dialogue_revision_patch(
    patch: dict[str, Any], affected_beat_ids: list[str],
) -> dict[str, Any] | None:
    """Convert a provider's action/dialogue sequence into the fixed beat contract."""
    wrapped = _project_flat_writer_revision_patch(patch, affected_beat_ids)
    if wrapped is None:
        return None
    projected = deepcopy(wrapped)
    changed = False
    for row in projected["replace_beats"]:
        beat = row["beat"]
        sequence = beat.get("during")
        if not isinstance(sequence, list) or not sequence:
            continue
        if any(
            not isinstance(item, dict) or set(item) != {"action", "dialogue"}
            for item in sequence
        ):
            return None
        dialogue_groups: list[list[dict[str, Any]]] = []
        actions_by_gap: list[list[str]] = [[]]
        for item in sequence:
            action = item.get("action")
            dialogue = item.get("dialogue")
            if action is not None:
                if not isinstance(action, str) or not action.strip() or dialogue is not None:
                    return None
                actions_by_gap[-1].append(action.strip())
                continue
            if (
                not isinstance(dialogue, list) or not dialogue
                or any(
                    not isinstance(line, dict) or set(line) != {"speaker", "text"}
                    or not isinstance(line.get("speaker"), str)
                    or not isinstance(line.get("text"), str) or not line["text"]
                    for line in dialogue
                )
            ):
                return None
            dialogue_groups.append(dialogue)
            actions_by_gap.append([])
        if len(dialogue_groups) != 2 or len(actions_by_gap) != 3:
            return None
        inner_dialogue = [line for group in dialogue_groups for line in group]
        outer_dialogue = beat.get("dialogue")
        if (
            not isinstance(outer_dialogue, list)
            or _dialogue_text("".join(str(line.get("text", "")) for line in inner_dialogue))
            != _dialogue_text("".join(
                str(line.get("text", "")) for line in outer_dialogue
                if isinstance(line, dict)
            ))
        ):
            return None
        if actions_by_gap[0]:
            beat["before"] = "；".join([beat["before"], *actions_by_gap[0]])
        beat["during"] = "；".join(actions_by_gap[1]) or "两句对白自然衔接"
        if actions_by_gap[2]:
            beat["after"] = "；".join([*actions_by_gap[2], beat["after"]])
        beat["dialogue"] = inner_dialogue
        changed = True
    return projected if changed else None


def _project_blank_dialogue_separators(
    patch: dict[str, Any], previous_script: dict[str, Any], affected_beat_ids: list[str],
) -> dict[str, Any] | None:
    """Drop whitespace-only fake speakers when the remaining text is unchanged."""
    projected = deepcopy(patch)
    replacements = projected.get("replace_beats")
    if not isinstance(replacements, list):
        return None
    previous = {
        row.get("id"): row for row in previous_script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    changed = False
    for row in replacements:
        if not isinstance(row, dict) or row.get("beat_id") not in affected_beat_ids:
            return None
        beat = row.get("beat")
        if not isinstance(beat, dict) or not isinstance(beat.get("dialogue"), list):
            return None
        lines = beat["dialogue"]
        kept = [
            line for line in lines
            if not (
                isinstance(line, dict)
                and isinstance(line.get("text"), str)
                and not line["text"].strip()
            )
        ]
        if len(kept) == len(lines):
            continue
        parent = previous.get(row["beat_id"])
        if not isinstance(parent, dict) or not kept:
            return None
        parent_text = "".join(
            str(line.get("text", "")) for line in parent.get("dialogue", [])
            if isinstance(line, dict)
        )
        kept_text = "".join(
            str(line.get("text", "")) for line in kept if isinstance(line, dict)
        )
        if _dialogue_text(parent_text) != _dialogue_text(kept_text):
            return None
        beat["dialogue"] = kept
        changed = True
    return projected if changed else None


def _project_missing_locked_dialogue_split_fields(
    previous_script: dict[str, Any], patch: dict[str, Any], affected_beat_ids: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Restore only omitted immutable fields in a compact dialogue-split beat patch."""
    if set(patch) != {"replace_beats"} or not isinstance(patch["replace_beats"], list):
        return None
    previous = {
        row.get("id"): row for row in previous_script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if [row.get("beat_id") for row in patch["replace_beats"]] != affected_beat_ids:
        return None
    locked = ("id", "duration_seconds", "event", "trigger", "before", "after")
    projected = deepcopy(patch)
    restored: list[dict[str, Any]] = []
    for row in projected["replace_beats"]:
        if not isinstance(row, dict) or set(row) != {"beat_id", "beat"}:
            return None
        beat_id = row["beat_id"]
        beat = row["beat"]
        parent = previous.get(beat_id)
        if not isinstance(beat, dict) or not isinstance(parent, dict):
            return None
        if any(key in beat and beat[key] != parent.get(key) for key in locked):
            return None
        for key in locked:
            if key not in beat:
                beat[key] = deepcopy(parent[key])
                restored.append({"beat_id": beat_id, "field": key})
        if "during" not in beat or "dialogue" not in beat:
            return None
    return (projected, restored) if restored else None


def _validate_dialogue_split_revision_scope(
    previous_script: dict[str, Any], patch: dict[str, Any], affected_beat_ids: list[str],
) -> None:
    """A dialogue split may only change the split lines and their middle action."""
    if set(patch) != {"replace_beats"} or not isinstance(patch["replace_beats"], list):
        raise CreativeContractError("长对白拆句返修必须只提交 replace_beats")
    previous = {
        row.get("id"): row for row in previous_script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if [row.get("beat_id") for row in patch["replace_beats"]] != affected_beat_ids:
        raise CreativeContractError("长对白拆句返修节拍范围不符")
    locked = ("id", "duration_seconds", "event", "trigger", "before", "after")
    for row in patch["replace_beats"]:
        beat = row.get("beat") if isinstance(row, dict) else None
        parent = previous.get(row.get("beat_id")) if isinstance(row, dict) else None
        if not isinstance(beat, dict) or not isinstance(parent, dict):
            raise CreativeContractError("长对白拆句返修缺少完整节拍")
        changed_locked = [key for key in locked if beat.get(key) != parent.get(key)]
        if changed_locked:
            raise CreativeContractError(
                "长对白拆句返修改动了锁定字段: " + ", ".join(changed_locked)
            )


def _project_legacy_writer_beat_plan(value: dict[str, Any]) -> dict[str, Any] | None:
    """Project an old beat_id/summary envelope onto the current writer contract."""
    beats = value.get("beats")
    if (
        not isinstance(beats, list) or not beats
        or any(
            not isinstance(row, dict)
            or "id" in row
            or not isinstance(row.get("beat_id"), str)
            or not row["beat_id"].strip()
            for row in beats
        )
    ):
        return None
    ids = [row["beat_id"] for row in beats]
    if len(set(ids)) != len(ids):
        return None
    top_keys = ("title", "premise", "selected_candidate_id", "duration_seconds")
    if any(key not in value for key in top_keys):
        return None
    beat_keys = (
        "duration_seconds", "event", "trigger", "before", "during", "after", "dialogue",
    )
    return {
        **{key: deepcopy(value[key]) for key in top_keys},
        "beats": [
            {
                "id": row["beat_id"],
                **{key: deepcopy(row[key]) for key in beat_keys if key in row},
            }
            for row in beats
        ],
    }


def _writer_revision_result(
    previous_script: dict[str, Any], value: dict[str, Any], affected_beat_ids: list[str],
    *, allow_summary_update: bool = False, revision_mode: str = "scoped",
) -> dict[str, Any]:
    """Adopt complete new drafts; only legacy bindings use scoped projection."""
    if revision_mode == "full_script":
        from .creative_full_script_revision import accept_full_script
        return accept_full_script(previous_script, value)
    if "replace_beats" in value:
        return _apply_writer_revision_patch(previous_script, value, affected_beat_ids)
    return _project_writer_revision(previous_script, value, affected_beat_ids, allow_summary_update=allow_summary_update)


def _validate_writer_revision_result(
    value: dict[str, Any], previous_script: dict[str, Any], affected_beat_ids: list[str],
    candidate: dict[str, Any], selected_excerpt: str, source_driver: str,
    creative_focus: str = "", *, revision_mode: str = "scoped",
) -> None:
    """Validate the complete adopted draft against story and execution contracts."""
    if "replace_beats" not in value:
        validate_script(value, candidate["id"], selected_excerpt, source_driver)
        validate_candidate_duration(value, candidate, creative_focus)
        validate_creative_focus_duration(value, creative_focus)
        validate_creative_focus_beat_count(value, creative_focus)
        validate_creative_focus_action_constraints(value, creative_focus)
    merged = _writer_revision_result(previous_script, value, affected_beat_ids, revision_mode=revision_mode)
    validate_script(merged, candidate["id"], selected_excerpt, source_driver)
    validate_candidate_duration(merged, candidate, creative_focus)
    validate_creative_focus_duration(merged, creative_focus)
    validate_creative_focus_beat_count(merged, creative_focus)
    validate_creative_focus_action_constraints(merged, creative_focus)


def _validate_beat_plan_for_candidate(
    value: dict[str, Any], candidate: dict[str, Any], source: str, driver: str,
    creative_focus: str = "",
) -> None:
    if isinstance(value.get("item"), dict):
        raise CreativeContractError(
            "writer_script 把独立节拍放在 beats 数组之外，正文不完整"
        )
    # Check the explicit authoring shape before duration arithmetic.  A
    # truncated response with only the first few beats otherwise looks like a
    # timing error and gets sent to a patch protocol that cannot add the
    # missing story body.
    validate_creative_focus_beat_count(value, creative_focus)
    validate_beat_plan(value, candidate["id"], source, driver)
    validate_candidate_duration(value, candidate, creative_focus)
    validate_creative_focus_duration(value, creative_focus)
    validate_creative_focus_action_constraints(value, creative_focus)


def _validate_script_for_candidate(
    value: dict[str, Any], candidate: dict[str, Any], source: str, driver: str,
    creative_focus: str = "",
) -> None:
    validate_script(value, candidate["id"], source, driver)
    validate_candidate_duration(value, candidate, creative_focus)
    validate_creative_focus_duration(value, creative_focus)
    validate_creative_focus_beat_count(value, creative_focus)
    validate_creative_focus_action_constraints(value, creative_focus)


def _director_revision_beats(
    previous_script: dict[str, Any], script: dict[str, Any],
    previous_shots: dict[str, Any], issues: list[dict[str, Any]],
    previous_design: dict[str, Any] | None = None,
) -> list[str]:
    """Include every shot or shared asset actually cited by a confirmed issue."""
    beat_order = [
        row.get("id") for row in script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]
    previous_by_id = {
        row.get("id"): row for row in previous_script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    current_by_id = {
        row.get("id"): row for row in script.get("beats", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    affected = {
        beat_id for beat_id in beat_order
        if previous_by_id.get(beat_id) != current_by_id.get(beat_id)
    }
    affected.update(_issue_beat_ids(script, issues, previous_shots))
    shot_rows = previous_shots.get("shots", [])
    shot_to_beat = {row.get("id"): row.get("beat_id") for row in shot_rows if isinstance(row, dict)}
    design = previous_design or {}
    design_rows = design.get("shots", [])
    context = {"shots": previous_shots, "production_design": design}
    for issue in issues:
        for ref in issue.get("evidence_refs", []):
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                continue
            parts = ref["path"].split(".")
            if len(parts) < 4 or not parts[2].isdecimal():
                continue
            try:
                target = context
                for part in parts:
                    target = target[int(part)] if isinstance(target, list) and part.isdecimal() else target[part]
                quote = ref.get("quote")
                valid = isinstance(quote, str) and bool(quote) and (
                    isinstance(target, str) and quote in target or type(target) in (int, float) and quote == json.dumps(target))
                if not valid:
                    continue
                index = int(parts[2])
                if parts[:2] == ["shots", "shots"]:
                    affected.add(shot_rows[index].get("beat_id"))
                elif parts[:2] == ["production_design", "shots"]:
                    affected.add(shot_to_beat.get(design_rows[index].get("shot_id")))
                elif parts[:2] == ["production_design", "assets"]:
                    asset_id = design["assets"][index].get("id")
                    for row in design_rows:
                        if asset_id and asset_id in row.get("asset_ids", []):
                            affected.add(shot_to_beat.get(row.get("shot_id")))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
    return [beat_id for beat_id in beat_order if beat_id in affected]


def _bound_director_revision_beats(path, previous_script, script, previous_shots, issues,
                                   previous_design=None, *, force_all=False):
    """Old stages replay their exact scope; only unsubmitted stages expand references."""
    beat_order = [row["id"] for row in script.get("beats", [])]
    if path.exists():
        messages = _read(path).get("request", {}).get("messages", [])
        payload = json.loads(messages[-1]["content"]) if messages else {}
        ids = payload.get("affected_beat_ids")
        if not isinstance(ids, list) or not ids or any(x not in beat_order for x in ids) or len(ids) != len(set(ids)):
            raise CreativeContractError("既有导演返修回执缺少有效授权节拍，不能自动扩大")
        return list(ids)
    ids = beat_order if force_all else _director_revision_beats(
        previous_script, script, previous_shots, issues, previous_design)
    if ids:
        receipt_path = path.with_name(path.stem + "__scope_binding.json")
        receipt = {"schema": "creative_director_revision_scope/v1", "affected_beat_ids": ids,
            "previous_script_sha256": _hash(previous_script), "script_sha256": _hash(script),
            "previous_shots_sha256": _hash(previous_shots), "previous_design_sha256": _hash(previous_design),
            "confirmed_issues_sha256": _hash(issues), "force_all": force_all}
        if receipt_path.exists() and _read(receipt_path) != receipt:
            raise RuntimeError("已绑定的新导演返修范围不能漂移")
        _write(receipt_path, receipt)
    return ids


def _apply_director_revision_patch(
    previous_shots: dict[str, Any], patch: dict[str, Any], affected_beat_ids: list[str],
) -> dict[str, Any]:
    """Replace complete shot groups for affected beats and preserve all other groups."""
    if set(patch) != {"replace_beats"} or not isinstance(patch["replace_beats"], list):
        raise CreativeContractError("导演局部返修必须只提交 replace_beats")
    rows = patch["replace_beats"]
    if len(rows) != len(affected_beat_ids) or any(not isinstance(row, dict) for row in rows):
        raise CreativeContractError("导演局部返修必须逐拍提交全部受影响镜头")
    if [row.get("beat_id") for row in rows] != affected_beat_ids:
        raise CreativeContractError("导演局部返修节拍顺序与受影响清单不一致")
    replacements: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if set(row) != {"beat_id", "shots"} or not isinstance(row["shots"], list) or not row["shots"]:
            raise CreativeContractError("导演局部返修每拍必须提供完整非空镜头列表")
        if any(not isinstance(shot, dict) or shot.get("beat_id") != row["beat_id"] for shot in row["shots"]):
            raise CreativeContractError("导演局部返修镜头必须绑定所在节拍")
        replacements[row["beat_id"]] = deepcopy(row["shots"])
    merged = {key: deepcopy(value) for key, value in previous_shots.items() if key != "shots"}
    merged_shots: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for shot in previous_shots.get("shots", []):
        if not isinstance(shot, dict):
            continue
        beat_id = shot.get("beat_id")
        if beat_id in replacements:
            if beat_id not in emitted:
                merged_shots.extend(replacements[beat_id])
                emitted.add(beat_id)
        else:
            merged_shots.append(deepcopy(shot))
    if emitted != set(affected_beat_ids):
        raise CreativeContractError("导演局部返修包含原分镜不存在的节拍")
    merged["shots"] = merged_shots
    return merged


def _project_director_beat_event_locks(
    patch: dict[str, Any], script: dict[str, Any], affected_beat_ids: list[str],
) -> tuple[dict[str, Any], list[dict[str, str]]] | None:
    """Restore only the immutable beat event copied into split-shot lock fields."""
    rows = patch.get("replace_beats")
    if not isinstance(rows, list):
        return None
    beat_events = {
        row.get("id"): row.get("event")
        for row in script.get("beats", []) if isinstance(row, dict)
        and row.get("id") in affected_beat_ids and isinstance(row.get("event"), str)
    }
    if set(beat_events) != set(affected_beat_ids):
        return None
    projected = deepcopy(patch)
    changes: list[dict[str, str]] = []
    for row in projected.get("replace_beats", []):
        beat_id = row.get("beat_id") if isinstance(row, dict) else None
        shots = row.get("shots") if isinstance(row, dict) else None
        if beat_id not in beat_events or not isinstance(shots, list):
            return None
        for shot in shots:
            if not isinstance(shot, dict):
                return None
            expected = beat_events[beat_id]
            current = shot.get("event_lock")
            if current != expected:
                changes.append({
                    "shot_id": str(shot.get("id", "")),
                    "beat_id": beat_id,
                    "from": "<missing>" if "event_lock" not in shot else str(current),
                    "to": expected,
                })
                shot["event_lock"] = expected
    return (projected, changes) if changes else None

def _validate_director_revision_result(
    value: dict[str, Any], previous_shots: dict[str, Any], affected_beat_ids: list[str],
    brief: dict[str, Any], script: dict[str, Any], source: str = "",
    creative_focus: str = "",
) -> None:
    """Validate a compact beat patch; accept old full replies for resumable history."""
    if "replace_beats" in value:
        merged = _apply_director_revision_patch(previous_shots, value, affected_beat_ids)
        validate_shots(merged, brief, script, source, creative_focus)
        return
    validate_shots(value, brief, script, source, creative_focus)


def _missing_beat_fields(original: dict[str, Any]) -> list[list[Any]]:
    """Find only absent prose/dialogue cells; never infer their story content."""
    missing: list[list[Any]] = []
    beats = original.get("beats")
    if not isinstance(beats, list):
        return missing
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        for key in ("event", "trigger", "before", "during", "after"):
            if not isinstance(beat.get(key), str) or not beat[key].strip():
                missing.append(["beats", index, key])
        dialogue = beat.get("dialogue")
        if not isinstance(dialogue, list):
            missing.append(["beats", index, "dialogue"])
        else:
            for line_index, line in enumerate(dialogue):
                if isinstance(line, dict):
                    for key in ("speaker", "text"):
                        if not isinstance(line.get(key), str) or not line[key].strip():
                            missing.append(["beats", index, "dialogue", line_index, key])
    return missing


def _apply_missing_beat_patches(
    original: dict[str, Any], repair: dict[str, Any], required: list[list[Any]],
) -> dict[str, Any]:
    patches = repair.get("patches")
    if not isinstance(patches, list) or len(patches) != len(required):
        raise CreativeContractError("编剧定向修复必须逐项补全所有缺失字段")
    if [patch.get("path") for patch in patches if isinstance(patch, dict)] != required:
        raise CreativeContractError("编剧定向修复路径与缺失字段不一致")
    corrected = deepcopy(original)
    for patch, path in zip(patches, required, strict=True):
        value = patch.get("value")
        if path[-1] == "dialogue":
            if (not isinstance(value, list)
                    or any(not isinstance(line, dict)
                           or set(line) != {"speaker", "text"}
                           or any(not isinstance(line[key], str) or not line[key].strip()
                                  for key in ("speaker", "text"))
                           for line in value)):
                raise CreativeContractError("编剧定向修复的 dialogue 必须是完整台词列表")
        elif not isinstance(value, str) or not value.strip():
            raise CreativeContractError("编剧定向修复不能填空字符串")
        cursor: Any = corrected
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = value
    return corrected


def _reuse_projection_bound_legacy_beat_repair(
    run_dir: Path, name: str, output: dict[str, Any], payload: dict[str, Any],
    required: list[list[Any]],
) -> dict[str, Any] | None:
    """Reuse a complete paid repair only through its exact legacy projection chain."""
    if not name.startswith("writer_script") or not required:
        return None
    output_sha256 = _hash(output)
    matches: list[tuple[Path, dict[str, Any]]] = []
    for projection_path in run_dir.glob(
        f"{name}__local_beat_plan_projection_*.json"
    ):
        projection = _read(projection_path)
        if (
            projection.get("schema") == "creative_local_beat_plan_projection/v1"
            and projection.get("output_sha256") == output_sha256
            and isinstance(projection.get("source_sha256"), str)
        ):
            matches.append((projection_path, projection))
    if not matches:
        return None
    source_hashes = {row[1]["source_sha256"] for row in matches}
    if len(source_hashes) != 1:
        raise RuntimeError(f"{name} 旧节拍投影存在相互冲突的来源绑定")
    projection_path, projection = matches[0]
    source_sha256 = projection["source_sha256"]
    repair_paths = [
        run_dir / f"{name}__contract_repair_{source_sha256[:12]}.json",
        run_dir / f"{name}__contract_repair.json",
    ]
    repair_path = next((path for path in repair_paths if path.exists()), None)
    if repair_path is None:
        return None
    repair = _read(repair_path)
    if (
        repair.get("status") != "response_received"
        or repair.get("source_sha256") != source_sha256
        or repair.get("payload_sha256") != _hash(payload)
        or repair.get("response_metadata", {}).get("finish_reason")
        not in (None, "stop", "tool_calls")
        or not isinstance(repair.get("response_text"), str)
    ):
        return None
    raw_response = repair["response_text"]
    format_path: Path | None = None
    try:
        patch = parse_json_object(raw_response)
    except CreativeContractError:
        candidate_format_path = (
            run_dir / f"{repair_path.stem}__response__format_repair.json"
        )
        if not candidate_format_path.exists():
            return None
        format_repair = _read(candidate_format_path)
        if (
            format_repair.get("status") != "response_received"
            or format_repair.get("source_sha256") != _hash(raw_response)
            or format_repair.get("response_metadata", {}).get("finish_reason")
            not in (None, "stop", "tool_calls")
            or not isinstance(format_repair.get("response_text"), str)
        ):
            return None
        try:
            patch = _parse_format_repair(
                raw_response, format_repair["response_text"],
            )
        except CreativeContractError:
            return None
        format_path = candidate_format_path
    try:
        corrected = _apply_missing_beat_patches(output, patch, required)
    except CreativeContractError:
        return None
    receipt_path = run_dir / (
        f"{name}__local_legacy_repair_reuse_{output_sha256[:12]}.json"
    )
    receipt = {
        "schema": "creative_local_legacy_repair_reuse/v1",
        "projection_receipt": projection_path.name,
        "projection_receipt_sha256": _hash(_read(projection_path)),
        "legacy_source_sha256": source_sha256,
        "projected_source_sha256": output_sha256,
        "payload_sha256": _hash(payload),
        "repair_record": repair_path.name,
        "repair_record_sha256": _hash(repair),
        "format_repair_record": format_path.name if format_path else None,
        "format_repair_record_sha256": (
            _hash(_read(format_path)) if format_path else None
        ),
        "required_paths": required,
        "output_sha256": _hash(corrected),
        "rule": "reuse only when projection, paid repair, syntax repair, payload, and exact patch paths all bind",
    }
    if receipt_path.exists() and _read(receipt_path) != receipt:
        raise RuntimeError(f"{name} 旧补丁复用回执与当前绑定不符")
    _write(receipt_path, receipt)
    return corrected


def _missing_analysis_fields(original: dict[str, Any]) -> list[list[Any]]:
    """Find missing causal descriptions without disturbing existing source quotes."""
    characters = original.get("characters")
    candidates = original.get("candidates")
    if not isinstance(characters, list) or not isinstance(candidates, list):
        return []
    missing: list[list[Any]] = []
    for collection, rows, fields in (
        ("characters", characters, ("want",)),
        ("candidates", candidates,
         ("setup", "conflict", "turn", "peak", "aftermath", "selection_reason")),
    ):
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in fields:
                if not isinstance(row.get(field), str) or not row[field].strip():
                    missing.append([collection, index, field])
            if collection == "candidates" and (
                type(row.get("duration_seconds")) is not int or row["duration_seconds"] <= 0
            ):
                missing.append([collection, index, "duration_seconds"])
    return missing


def _invalid_candidate_quote_paths(
    analysis: dict[str, Any], source: str,
) -> list[list[Any]]:
    """Locate every novel candidate boundary that cannot be uniquely anchored."""
    candidates = analysis.get("candidates")
    if not isinstance(candidates, list) or not isinstance(source, str) or not source:
        return []
    invalid: list[list[Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        for field in ("start_quote", "end_quote"):
            try:
                _canonical_source_quote(
                    source, candidate.get(field), f"candidate.{field}",
                )
            except CreativeContractError:
                invalid.append(["candidates", index, field])
    return invalid if len(invalid) <= 6 else []


def _invalid_character_quote_paths(
    analysis: dict[str, Any], source: str,
) -> list[list[Any]]:
    """Locate novel character evidence that is not one exact unique source span."""
    characters = analysis.get("characters")
    if not isinstance(characters, list) or not isinstance(source, str) or not source:
        return []
    invalid: list[list[Any]] = []
    for index, character in enumerate(characters):
        if not isinstance(character, dict):
            continue
        try:
            _canonical_source_quote(
                source, character.get("source_quote"), f"characters[{index}].source_quote",
            )
        except CreativeContractError:
            invalid.append(["characters", index, "source_quote"])
    return invalid if len(invalid) <= 6 else []


def _apply_missing_analysis_patches(
    original: dict[str, Any], repair: dict[str, Any], required: list[list[Any]],
) -> dict[str, Any]:
    patches = repair.get("patches")
    if not isinstance(patches, list) or len(patches) != len(required):
        raise CreativeContractError("编剧分析缺字段补丁必须逐项对应")
    if [patch.get("path") for patch in patches if isinstance(patch, dict)] != required:
        raise CreativeContractError("编剧分析补丁路径与缺失字段不一致")
    corrected = deepcopy(original)
    for patch, path in zip(patches, required, strict=True):
        value = patch.get("value")
        if path[-1] == "duration_seconds":
            if type(value) is not int or value <= 0:
                raise CreativeContractError("候选时长补丁必须是正整数")
        elif not isinstance(value, str) or not value.strip():
            raise CreativeContractError("编剧分析缺字段补丁不能填空字符串")
        corrected[path[0]][path[1]][path[2]] = value
    return corrected


def _apply_candidate_quote_patches(
    original: dict[str, Any], repair: dict[str, Any],
    required: list[list[Any]], source: str,
) -> dict[str, Any]:
    """Apply only exact, unique candidate start/end anchors from the source."""
    if set(repair) != {"patches"} or not isinstance(repair["patches"], list):
        raise CreativeContractError("候选边界修复只能返回 patches")
    patches = repair["patches"]
    if len(patches) != len(required) or not all(isinstance(row, dict) for row in patches):
        raise CreativeContractError("候选边界补丁必须逐项对应")
    if [row.get("path") for row in patches] != required:
        raise CreativeContractError("候选边界补丁路径与无效引文不一致")
    corrected = deepcopy(original)
    for patch, path in zip(patches, required, strict=True):
        if set(patch) != {"path", "value"} or not isinstance(patch["value"], str):
            raise CreativeContractError("候选边界补丁只能提供路径和逐字引文")
        canonical, _ = _canonical_source_quote(
            source, patch["value"], f"candidate.{path[-1]}",
        )
        corrected[path[0]][path[1]][path[2]] = canonical
    return corrected


def _apply_character_quote_patches(
    original: dict[str, Any], repair: dict[str, Any],
    required: list[list[Any]], source: str,
) -> dict[str, Any]:
    """Apply only exact, unique character evidence quotes from the source."""
    if set(repair) != {"patches"} or not isinstance(repair["patches"], list):
        raise CreativeContractError("人物引文修复只能返回 patches")
    patches = repair["patches"]
    if len(patches) != len(required) or not all(isinstance(row, dict) for row in patches):
        raise CreativeContractError("人物引文补丁必须逐项对应")
    if [row.get("path") for row in patches] != required:
        raise CreativeContractError("人物引文补丁路径与无效引文不一致")
    corrected = deepcopy(original)
    for patch, path in zip(patches, required, strict=True):
        if set(patch) != {"path", "value"} or not isinstance(patch["value"], str):
            raise CreativeContractError("人物引文补丁只能提供路径和逐字引文")
        label = f"characters[{path[1]}].source_quote"
        try:
            canonical, _ = _canonical_source_quote(source, patch["value"], label)
        except CreativeContractError:
            original_quote = original[path[0]][path[1]][path[2]]
            canonical = _recover_near_source_quote(
                source, [patch["value"], original_quote], label,
            )
        corrected[path[0]][path[1]][path[2]] = canonical
    return corrected


def _recover_near_source_quote(source: str, candidates: list[str], label: str) -> str:
    """Recover a nearly copied long quote only when one source span is unambiguous."""
    source_chars = [(index, char) for index, char in enumerate(source) if char.isalnum()]
    compact_source = "".join(char for _, char in source_chars)
    ranked: list[tuple[float, int, int]] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        compact = "".join(char for char in candidate if char.isalnum())
        if len(compact) < 12 or len(compact) > len(compact_source):
            continue
        for start in range(len(compact_source) - len(compact) + 1):
            window = compact_source[start:start + len(compact)]
            score = sum(left == right for left, right in zip(compact, window, strict=True)) / len(compact)
            if score >= 0.92:
                ranked.append((score, start, len(compact)))
    if not ranked:
        raise CreativeContractError(f"{label} 无法从来源安全恢复")
    ranked.sort(reverse=True)
    best_score, best_start, length = ranked[0]
    distinct = {
        (start, span_length) for score, start, span_length in ranked
        if score >= best_score - 0.01
    }
    if len(distinct) != 1:
        raise CreativeContractError(f"{label} 的近似来源不唯一，拒绝自动恢复")
    raw_start = source_chars[best_start][0]
    raw_end = source_chars[best_start + length - 1][0] + 1
    recovered = source[raw_start:raw_end]
    canonical, _ = _canonical_source_quote(source, recovered, label)
    return canonical


def _invalid_novel_dialogue_paths(plan: dict[str, Any], source: str) -> list[list[Any]]:
    """Locate absent, out-of-order, or narration-mislabeled novel dialogue."""
    beats = plan.get("beats")
    if not isinstance(beats, list) or not isinstance(source, str) or not source:
        return []
    normalized_source = _dialogue_text(source)
    direct_spans = _source_direct_quote_spans(source)
    cursor = 0
    invalid: list[list[Any]] = []
    for beat_index, beat in enumerate(beats):
        if not isinstance(beat, dict) or not isinstance(beat.get("dialogue"), list):
            return []
        for line_index, line in enumerate(beat["dialogue"]):
            spoken = line.get("text") if isinstance(line, dict) else None
            speaker = line.get("speaker") if isinstance(line, dict) else None
            if (not isinstance(spoken, str) or not spoken.strip()
                    or not isinstance(speaker, str) or not speaker.strip()):
                return []
            normalized = _dialogue_text(spoken)
            position = normalized_source.find(normalized, cursor)
            narration = is_narration_speaker(speaker)
            end = position + len(normalized) if position >= 0 else -1
            if position < 0 or (
                not narration
                and not any(position >= start and end <= stop for start, stop in direct_spans)
            ):
                invalid.append(["beats", beat_index, "dialogue", line_index, "text"])
            else:
                cursor = end
    return invalid if len(invalid) <= 8 else []


def _novel_dialogue_order_repair_beat_ids(
    plan: dict[str, Any], source: str,
) -> list[str]:
    """Find one unambiguous contiguous beat range containing a source-order inversion."""
    beats = plan.get("beats")
    if not isinstance(beats, list) or not isinstance(source, str) or not source:
        return []
    normalized_source = _dialogue_text(source)
    direct_spans = _source_direct_quote_spans(source)
    ordered: list[tuple[int, int, int]] = []
    for beat_index, beat in enumerate(beats):
        if (
            not isinstance(beat, dict)
            or not isinstance(beat.get("id"), str)
            or not isinstance(beat.get("dialogue"), list)
        ):
            return []
        for line_index, line in enumerate(beat["dialogue"]):
            if (
                not isinstance(line, dict)
                or not isinstance(line.get("speaker"), str)
                or not isinstance(line.get("text"), str)
            ):
                return []
            spoken = _dialogue_text(line["text"])
            if not spoken or normalized_source.count(spoken) != 1:
                continue
            position = normalized_source.index(spoken)
            end = position + len(spoken)
            narration = is_narration_speaker(line["speaker"])
            if not narration and not any(
                position >= start and end <= stop for start, stop in direct_spans
            ):
                continue
            ordered.append((beat_index, line_index, position))
    expected_positions = sorted(row[2] for row in ordered)
    mismatched_beat_indexes = [
        row[0] for row, expected_position in zip(ordered, expected_positions)
        if row[2] != expected_position
    ]
    if not mismatched_beat_indexes:
        return []
    start = min(mismatched_beat_indexes)
    end = max(mismatched_beat_indexes)
    return [beats[index]["id"] for index in range(start, end + 1)]


def _project_unique_source_dialogue_punctuation(
    original: dict[str, Any], source: str, required: list[list[Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Restore punctuation from one unique direct quote without changing its words."""
    if not required:
        return None
    inventory = _dialogue_inventory(source)
    normalized_source = _dialogue_text(source)
    required_keys = {tuple(path) for path in required}
    corrected = deepcopy(original)
    changes: list[dict[str, Any]] = []
    cursor = 0
    for beat_index, beat in enumerate(original.get("beats", [])):
        if not isinstance(beat, dict) or not isinstance(beat.get("dialogue"), list):
            return None
        for line_index, line in enumerate(beat["dialogue"]):
            if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                return None
            path = ("beats", beat_index, "dialogue", line_index, "text")
            spoken = line["text"]
            normalized = _dialogue_text(spoken)
            position = normalized_source.find(normalized, cursor)
            if position >= 0:
                cursor = position + len(normalized)
                continue
            if path not in required_keys:
                return None
            compact = "".join(char for char in normalized if char.isalnum())
            if len(compact) < 4:
                continue
            candidates: list[tuple[str, int]] = []
            for item in inventory:
                canonical = item["text"]
                compact_canonical = "".join(
                    char for char in canonical if char.isalnum()
                )
                if compact_canonical == compact:
                    recovered = canonical
                elif compact_canonical.count(compact) == 1:
                    try:
                        recovered, _ = _canonical_source_quote(
                            canonical, spoken, "dialogue punctuation",
                        )
                    except CreativeContractError:
                        continue
                    if "".join(char for char in recovered if char.isalnum()) != compact:
                        continue
                else:
                    continue
                normalized_canonical = _dialogue_text(recovered)
                if normalized_source.count(normalized_canonical) != 1:
                    continue
                canonical_position = normalized_source.index(normalized_canonical)
                if canonical_position >= cursor:
                    candidates.append((recovered, canonical_position))
            candidates = list(dict.fromkeys(candidates))
            if len(candidates) != 1:
                continue
            canonical, position = candidates[0]
            corrected["beats"][beat_index]["dialogue"][line_index]["text"] = canonical
            changes.append({"path": list(path), "from": spoken, "to": canonical})
            cursor = position + len(_dialogue_text(canonical))
    if not changes:
        return None
    if "screenplay_markdown" in corrected:
        corrected["screenplay_markdown"] = compile_beat_screenplay(corrected)
    return corrected, changes


def _project_missing_check_impacts(
    original: dict[str, Any],
) -> tuple[dict[str, Any], list[int]] | None:
    """Keep a malformed issue conservative when only its impact text is missing."""
    issues = original.get("issues")
    if not isinstance(issues, list) or not issues:
        return None
    missing: list[int] = []
    for index, row in enumerate(issues):
        if not isinstance(row, dict):
            return None
        if isinstance(row.get("impact"), str) and row["impact"].strip():
            continue
        if (
            row.get("owner") not in ("writer", "director")
            or row.get("severity") not in ("blocking", "major", "minor")
            or any(
                not isinstance(row.get(key), str) or not row[key].strip()
                for key in ("location", "evidence", "proposal")
            )
        ):
            return None
        missing.append(index)
    if not missing:
        return None
    corrected = deepcopy(original)
    for index in missing:
        corrected["issues"][index]["impact"] = (
            "模型未提供影响说明；该问题在补全影响并重新复核前阻止自动放行。"
        )
    return corrected, missing


def _apply_novel_dialogue_patches(
    original: dict[str, Any], repair: dict[str, Any],
    required: list[list[Any]], source: str,
) -> dict[str, Any]:
    if set(repair) != {"patches"} or not isinstance(repair["patches"], list):
        raise CreativeContractError("小说对白修复只能返回 patches")
    patches = repair["patches"]
    if len(patches) != len(required) or not all(isinstance(row, dict) for row in patches):
        raise CreativeContractError("小说对白补丁必须逐句对应")
    if [row.get("path") for row in patches] != required:
        raise CreativeContractError("小说对白补丁路径与问题台词不一致")
    normalized_source = _dialogue_text(source)
    corrected = deepcopy(original)
    for patch, path in reversed(list(zip(patches, required, strict=True))):
        if set(patch) != {"path", "value"} or not isinstance(patch["value"], str):
            raise CreativeContractError("小说对白补丁只能提供路径和原文台词")
        replacement = patch["value"]
        if replacement and _dialogue_text(replacement) not in normalized_source:
            raise CreativeContractError("小说对白补丁不是所选原文中的连续引文")
        lines = corrected["beats"][path[1]]["dialogue"]
        if replacement:
            lines[path[3]]["text"] = replacement
        else:
            del lines[path[3]]
    if "screenplay_markdown" in corrected:
        corrected["screenplay_markdown"] = compile_beat_screenplay(corrected)
    return corrected


def _apply_writer_timing_patch(
    original: dict[str, Any], repair: dict[str, Any], required_beat_ids: list[str],
) -> dict[str, Any]:
    """Apply a timing-only repair without allowing story or performance rewrites."""
    if set(repair) != {"replace_beats"} or not isinstance(repair["replace_beats"], list):
        raise CreativeContractError("编剧时长修复只能返回 replace_beats")
    rows = repair["replace_beats"]
    if len(rows) != len(required_beat_ids) or not all(isinstance(row, dict) for row in rows):
        raise CreativeContractError("编剧时长修复必须逐拍提交全部目标节拍")
    if [row.get("beat_id") for row in rows] != required_beat_ids:
        raise CreativeContractError("编剧时长修复节拍顺序与目标清单不一致")
    replacements: dict[str, dict[str, Any]] = {}
    for row in rows:
        if set(row) != {"beat_id", "duration_seconds", "dialogue"}:
            raise CreativeContractError("编剧时长修复每拍只能提交时长和对白")
        duration = row["duration_seconds"]
        dialogue = row["dialogue"]
        if type(duration) not in (int, float) or duration <= 0:
            raise CreativeContractError("编剧时长修复的节拍时长必须为正数")
        if not isinstance(dialogue, list) or not all(
            isinstance(line, dict) and set(line) == {"speaker", "text"}
            and isinstance(line["speaker"], str) and line["speaker"].strip()
            and isinstance(line["text"], str) and line["text"].strip()
            for line in dialogue
        ):
            raise CreativeContractError("编剧时长修复的对白必须是说话人与非空原文列表")
        replacements[row["beat_id"]] = {
            "duration_seconds": duration,
            "dialogue": deepcopy(dialogue),
        }
    corrected = deepcopy(original)
    changed = False
    for beat in corrected.get("beats", []):
        replacement = replacements.get(beat.get("id"))
        if replacement is None:
            continue
        for key in ("duration_seconds", "dialogue"):
            if beat.get(key) != replacement[key]:
                changed = True
            beat[key] = replacement[key]
    if not changed:
        raise CreativeContractError("编剧时长修复没有改变时长或对白")
    corrected["duration_seconds"] = sum(row["duration_seconds"] for row in corrected["beats"])
    if "screenplay_markdown" in corrected:
        corrected["screenplay_markdown"] = compile_beat_screenplay(corrected)
    return corrected


def _project_unrequested_analysis_quote_patches(
    repair: dict[str, Any], required: list[list[Any]],
) -> tuple[dict[str, Any], list[list[Any]]] | None:
    """Keep exact requested fixes while rejecting unsolicited character quote edits."""
    if set(repair) != {"patches"} or not isinstance(repair["patches"], list):
        return None
    patches = repair["patches"]
    if len(patches) <= len(required):
        return None
    requested = patches[:len(required)]
    extras = patches[len(required):]
    if not all(isinstance(row, dict) for row in patches):
        return None
    if [row.get("path") for row in requested] != required:
        return None
    ignored_paths = [row.get("path") for row in extras]
    if not all(
        isinstance(path, list) and len(path) == 3
        and path[0] == "characters" and type(path[1]) is int
        and path[2] == "source_quote" and path not in required
        for path in ignored_paths
    ):
        return None
    return {"patches": requested}, ignored_paths


from .creative_original_prompt import VERSION as EVENT_WRITER_VERSION, bind_original_prompt, validate_brief_script, bind_brief_priority, stage_summary_update_allowed
from .creative_original_director import bind_original_director, bind_original_director_revision
from .creative_segmented_director import bind_segmented_director, generate_reviewed_beats
from .creative_review_v3 import VERSION as REVIEW_V3, build_review_prompt, validate_v3_review
from .creative_review_v4 import VERSION as REVIEW_V4, build_review_prompt as build_review_prompt_v4, validate_review_v4
from .creative_review_v5 import VERSION as REVIEW_V5, build_review_prompt as build_review_prompt_v5, validate_review_v5
from .creative_review_v6 import VERSION as REVIEW_V6, build_review_prompt as build_review_prompt_v6, validate_review_v6, build_review_repair, validate_repair_preserves_conclusions
from .creative_static_visual_manifest import build_static_manifest_prompt
from .creative_event_script import EVENT_SCHEMA, compile_event_script

LEGACY_MODEL_PROFILE = "legacy_writer_minimax_director_deepseek"
CREATE_REVIEW_PROFILE = "minimax_create_deepseek_review"
MODEL_PROFILES = (LEGACY_MODEL_PROFILE, CREATE_REVIEW_PROFILE)


class CreativeWorkflow:
    def __init__(
        self,
        run_dir: Path,
        *,
        clients: CreativeRoleClients | None = None,
        max_calls: int = 20,
        max_revisions: int = 2,
        max_contract_repairs: int = 8,
        budget_policy_version: str = "v4_20260923",
        direct_context_chars: int = 42000,
        creative_focus: str = "",
        retry_unconfirmed_transport: bool = False,
        max_total_tokens: int = 500000,
        logical_task_id: str | None = None,
        model_profile: str | None = None,
        writer_prompt_version: str | None = None,
        review_policy_version: str | None = None,
        production_protocol: str | None = None,
        stop_after_stage: str | None = None,
        max_new_stages: int | None = None,
    ) -> None:
        if (max_calls < 5 or max_revisions < 0 or max_contract_repairs < 0
                or direct_context_chars < 1000 or max_total_tokens < 10000):
            raise ValueError("调用、返修或上下文预算无效")
        if budget_policy_version not in (
            "v1_20260922", "v2_20260922", "v3_20260922", "v4_20260923", "v5_20261001",
        ):
            raise ValueError("未知的创作预算版本")
        self.run_dir = Path(run_dir)
        self.clients = clients or CreativeRoleClients()
        self.max_calls = max_calls
        self.max_revisions = max_revisions
        self.max_contract_repairs = max_contract_repairs
        self.budget_policy_version = budget_policy_version
        self.direct_context_chars = direct_context_chars
        self.creative_focus = creative_focus.strip()
        self.retry_unconfirmed_transport = retry_unconfirmed_transport
        self.max_total_tokens = max_total_tokens
        self.logical_task_id = logical_task_id
        self.stop_after_stage = stop_after_stage.strip() if stop_after_stage else None
        if max_new_stages is not None and max_new_stages < 1:
            raise ValueError("单步调试的新阶段数量必须为正数")
        self.max_new_stages = max_new_stages
        self._debug_new_stages = 0
        self._debug_stage_trace = []
        self.state_path = self.run_dir / "state.json"
        self.state: dict[str, Any] = {}
        saved_profile = (_read(self.state_path).get("model_profile", LEGACY_MODEL_PROFILE)
                         if self.state_path.exists() else None)
        self.model_profile = model_profile or saved_profile or LEGACY_MODEL_PROFILE
        if self.model_profile not in MODEL_PROFILES:
            raise ValueError("未知模型分工")
        if saved_profile is not None and self.model_profile != saved_profile:
            raise RuntimeError("恢复任务不能更换已绑定的模型分工")
        saved_writer = (_read(self.state_path).get("writer_prompt_version", "legacy")
                        if self.state_path.exists() else None)
        self.writer_prompt_version = writer_prompt_version or saved_writer or "legacy"
        if self.writer_prompt_version not in ("legacy", EVENT_WRITER_VERSION):
            raise ValueError("未知编剧提示词版本")
        if saved_writer is not None and saved_writer != self.writer_prompt_version:
            raise RuntimeError("恢复任务不能更换编剧提示词版本")
        saved_review = (_read(self.state_path).get("review_policy_version", "legacy")
                        if self.state_path.exists() else None)
        self.review_policy_version = review_policy_version or saved_review or (
            REVIEW_POLICY_VERSION if self.model_profile == CREATE_REVIEW_PROFILE
            and self.writer_prompt_version == EVENT_WRITER_VERSION else "legacy")
        if self.review_policy_version not in ("legacy", *REVIEW_POLICY_VERSIONS):
            raise ValueError("未知审核流程版本")
        if saved_review is not None and saved_review != self.review_policy_version:
            raise RuntimeError("恢复任务不能更换审核流程版本")
        if self.review_policy_version in REVIEW_POLICY_VERSIONS and (
            self.model_profile != CREATE_REVIEW_PROFILE or self.writer_prompt_version != EVENT_WRITER_VERSION
        ):
            raise ValueError("证据审核流程仅适用于原创事件版创作")
        saved_protocol = (_read(self.state_path).get("production_protocol", "legacy")
                          if self.state_path.exists() else None)
        self.production_protocol = production_protocol or saved_protocol or "legacy"
        if self.production_protocol not in ("legacy", "governed_production_v1"):
            raise ValueError("未知生产协议")
        if saved_protocol is not None and saved_protocol != self.production_protocol:
            raise RuntimeError("恢复任务不能更换已绑定生产协议")
        if self.production_protocol == "governed_production_v1" and self.review_policy_version != REVIEW_V6:
            raise ValueError("governed_production_v1仅适用于显式v6原创文本流程")
        self._active_stage_name = ""

    def _finish_debug_stage(self, name, role, output, *, completed_before):
        from .creative_stage_runtime import finish_stage
        return finish_stage(self, name, role, output, completed_before=completed_before)

    def _transport_role(self, logical_role: str) -> str:
        if self.model_profile == CREATE_REVIEW_PROFILE:
            return "director" if self._active_stage_name.startswith(("writer_check", "script_review")) else "writer"
        return logical_role

    def _call_model(self, role: str, messages: list, **kwargs) -> RoleResult:
        from .creative_diagnostic_spend import assert_no_unreconciled_diagnostic_spend
        assert_no_unreconciled_diagnostic_spend(self.run_dir)
        from .creative_state_store import authorize_dispatch
        authorize_dispatch(self, role, messages)
        transport = self._transport_role(role)
        try:
            result = self.clients.call(transport, messages, **kwargs)
        except Exception as exc:
            metadata = getattr(exc, "response_metadata", None)
            if isinstance(metadata, dict):
                metadata = {**metadata, "call_ordinal": self.state.get("calls_started", 0)}
                exc.response_metadata = metadata
                receipt = {"schema": "creative_failed_response_usage/v1",
                           "stage": self._active_stage_name, "call_ordinal": self.state.get("calls_started", 0),
                           "response_metadata": {**metadata, "logical_role": role, "transport_config_role": transport}}
                path = self.run_dir / f"FAILED_RESPONSE_USAGE_{self.state.get('calls_started', 0):03}.json"
                if path.exists() and _read(path) != receipt:
                    raise RuntimeError("失败调用usage回执冲突，拒绝覆盖") from exc
                _write(path, receipt)
            raise
        result = RoleResult(result.text, {**result.metadata, "call_ordinal": self.state.get("calls_started", 0)})
        if self.model_profile == LEGACY_MODEL_PROFILE:
            return result
        return RoleResult(result.text, {**result.metadata, "logical_role": role,
                          "workflow_stage": self._active_stage_name,
                          "model_profile": self.model_profile,
                          "transport_config_role": transport})

    def _split_repair_budget(self) -> bool:
        return self.state.get("budget_policy_version") in (
            "v2_20260922", "v3_20260922", "v4_20260923", "v5_20261001",
        )

    def _repair_budget_used(self) -> int:
        return self.state.get("contract_repairs_used", 0) + self.state.get("format_repairs_used", 0)

    def _save(self) -> None:
        self.state["reported_tokens"] = self._reported_tokens()
        from .creative_state_store import commit_state
        commit_state(self.run_dir, self.state)

    def _stop_for_upstream_source_boundary(
        self,
        *,
        script: dict[str, Any],
        shots: dict[str, Any] | None,
        issues: list[dict[str, Any]],
        excerpt_record: dict[str, Any],
        evidence_name: str,
        evidence: dict[str, Any],
        explanation: str,
    ) -> dict[str, Any]:
        """Stop local repair when a review explicitly requires changing source scope."""
        evidence_hash_key = f"{evidence_name}_sha256"
        unresolved = {
            "schema": "creative_unresolved_draft/v1",
            "status": "needs_revision",
            "reason": "upstream_source_boundary_required",
            "script_sha256": _hash(script),
            evidence_hash_key: _hash(evidence),
            "selected_source_sha256": _hash(excerpt_record),
            "script": script,
            "shots": shots,
            "issues": issues,
            "automatic_media_submit": False,
        }
        if shots is not None:
            unresolved["shots_sha256"] = _hash(shots)
        _write(self.run_dir / "UNRESOLVED_DRAFT.json", unresolved)
        _write(self.run_dir / "UPSTREAM_SOURCE_BOUNDARY_REQUIRED.json", {
            "schema": "creative_upstream_source_boundary_required/v1",
            "status": "needs_revision",
            "selected_source_sha256": _hash(excerpt_record),
            evidence_hash_key: _hash(evidence),
            "issues": issues,
            "automatic_media_submit": False,
        })
        lines = [
            "# 未通过的剧本工作稿", "", explanation, "",
            script["screenplay_markdown"], "", "## 未解决问题", "",
        ]
        for issue in issues:
            lines.extend((
                f"### {issue['location']} · {issue['severity']}", "",
                f"证据：{issue['evidence']}", "",
                f"影响：{issue['impact']}", "",
                f"建议：{issue['proposal']}", "",
            ))
        (self.run_dir / "UNRESOLVED_DRAFT.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )
        self.state["status"] = "needs_revision"
        self.state["unresolved_issues"] = issues
        self.state["upstream_repair_required"] = "selected_source_boundary"
        self._save()
        return self.state

    def _stop_for_upstream_candidate_revision(
        self,
        *,
        script: dict[str, Any],
        shots: dict[str, Any] | None,
        issues: list[dict[str, Any]],
        excerpt_record: dict[str, Any],
        evidence_name: str,
        evidence: dict[str, Any],
        explanation: str,
    ) -> dict[str, Any]:
        """Stop before local repair when the selected candidate cannot be filmed faithfully."""
        evidence_hash_key = f"{evidence_name}_sha256"
        unresolved = {
            "schema": "creative_unresolved_draft/v1",
            "status": "needs_revision",
            "reason": "upstream_candidate_revision_required",
            "script_sha256": _hash(script),
            evidence_hash_key: _hash(evidence),
            "selected_source_sha256": _hash(excerpt_record),
            "script": script,
            "shots": shots,
            "issues": issues,
            "automatic_media_submit": False,
        }
        if shots is not None:
            unresolved["shots_sha256"] = _hash(shots)
        _write(self.run_dir / "UNRESOLVED_DRAFT.json", unresolved)
        _write(self.run_dir / "UPSTREAM_CANDIDATE_REVISION_REQUIRED.json", {
            "schema": "creative_upstream_candidate_revision_required/v1",
            "status": "needs_revision",
            "selected_source_sha256": _hash(excerpt_record),
            evidence_hash_key: _hash(evidence),
            "issues": issues,
            "automatic_media_submit": False,
        })
        lines = [
            "# 未通过的剧本工作稿", "", explanation, "",
            script["screenplay_markdown"], "", "## 未解决问题", "",
        ]
        for issue in issues:
            lines.extend((
                f"### {issue['location']} · {issue['severity']}", "",
                f"证据：{issue['evidence']}", "",
                f"影响：{issue['impact']}", "",
                f"建议：{issue['proposal']}", "",
            ))
        (self.run_dir / "UNRESOLVED_DRAFT.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )
        self.state["status"] = "needs_revision"
        self.state["unresolved_issues"] = issues
        self.state["upstream_repair_required"] = "candidate_revision"
        self._save()
        return self.state

    def _clear_stale_upstream_stop_state(self) -> None:
        """Clear resumable stop flags after current routing no longer requires upstream work."""
        changed = False
        for key in ("upstream_repair_required", "unresolved_issues"):
            if key in self.state:
                self.state.pop(key)
                changed = True
        if changed:
            self._save()

    def _reported_tokens(self) -> int:
        total = 0
        seen_response_ids = set()
        # Recovery moves paid receipts into this task's history. Count those
        # original responses too; archive placement must not reset token spend.
        receipt_paths = list(self.run_dir.glob("*.json"))
        history = self.run_dir / "history"
        if history.is_dir():
            receipt_paths.extend(history.rglob("*.json"))
        root = self.run_dir.resolve()
        for path in receipt_paths:
            if not path.resolve().is_relative_to(root):
                continue
            if path.name in ("state.json", "materials.json", "SCREENPLAY.json",
                             "STORYBOARD.json", "EXECUTION_DRAFT.json",
                             "EDITORIAL_REVIEW_PACKET.json", "SELECTED_SOURCE.json",
                             "MEDIA_HANDOFF.json", "SEEDANCE_SEGMENT_PLAN.json",
                             "CALIBRATION_REVIEW.json"):
                continue
            try:
                record = _read(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            for item in [record, *record.get("prior_attempts", [])]:
                usage = item.get("response_metadata", {})
                amount = usage.get("total_tokens")
                if type(amount) is int and amount >= 0:
                    response_id = usage.get("response_id")
                    ordinal = usage.get("call_ordinal", item.get("call_ordinal"))
                    identity = ("response", response_id) if response_id else (
                        ("call", ordinal) if type(ordinal) is int and ordinal > 0 else None)
                    if identity is not None:
                        if identity in seen_response_ids:
                            continue
                        seen_response_ids.add(identity)
                    total += amount
        return total

    def _write_output_manifest(
        self,
        *,
        handoff: dict[str, Any],
        artifact_purposes: dict[str, str],
        filename: str = "CREATIVE_OUTPUT_MANIFEST.json",
    ) -> dict[str, Any]:
        """Bind the readable package, role handoffs and actual call receipts."""
        if handoff.get("narrative_transfer_sha256"):
            narrative_file = ("ASSISTANT_REVISED_NARRATIVE_TRANSFER.json"
                if "ASSISTANT_REVISED_MEDIA_HANDOFF.json" in artifact_purposes else "NARRATIVE_TRANSFER.json")
            if _hash(_read(self.run_dir / narrative_file)) != handoff["narrative_transfer_sha256"]:
                raise RuntimeError("叙事交接对照与锁定制作稿不一致")
            artifact_purposes = {**artifact_purposes, narrative_file: "实际事件、分镜表演与最终请求的叙事对照"}
        artifacts = []
        for artifact_name, purpose in artifact_purposes.items():
            path = self.run_dir / artifact_name
            if not path.is_file():
                raise RuntimeError(f"输出包缺少 {artifact_name}")
            artifacts.append(_output_artifact(path, purpose))

        stage_handoffs = []
        for stage in self.state.get("stages", []):
            record_path = self.run_dir / f"{stage['name']}.json"
            if not record_path.is_file():
                raise RuntimeError(f"阶段回执缺少 {record_path.name}")
            stage_handoffs.append({
                "stage": stage["name"],
                "role": stage["role"],
                "input_sha256": stage["input_sha256"],
                "output_sha256": stage["output_sha256"],
                "receipt_path": record_path.name,
                "receipt_sha256": _file_sha256(record_path),
                "context_budget": stage.get("context_budget"),
                "usage": stage.get("usage", {}),
            })

        call_receipts = []
        artifact_names = set(artifact_purposes) | {filename, "state.json", "materials.json"}
        for path in sorted(self.run_dir.glob("*.json")):
            if path.name in artifact_names:
                continue
            try:
                value = _read(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            attempts = [value, *value.get("prior_attempts", [])]
            if not any(isinstance(row, dict) and (
                isinstance(row.get("response_metadata"), dict)
                or ("request" in row and isinstance(row.get("role"), str))
            ) for row in attempts):
                continue
            call_receipts.append({
                "path": path.name,
                "sha256": _file_sha256(path),
                "attempts": len(attempts),
            })

        manifest = {
            "schema": "creative_output_manifest/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_driver": self.state["source_driver"],
            "logical_task_id": self.state.get("logical_task_id"),
            "material_sha256": self.state["material_sha256"],
            "handoff_sha256": _hash(handoff),
            "automatic_media_submit": False,
            "artifacts": artifacts,
            "stage_handoffs": stage_handoffs,
            "usage_summary": {
                "calls_started": self.state["calls_started"],
                "reported_total_tokens": self._reported_tokens(),
                "known_cost": None,
                "cost_status": "provider_price_not_bound_to_receipts",
                "call_receipts": call_receipts,
            },
            "unresolved_limits": [
                "media executor capability is not yet verified by a paid submission",
                "first frame, cuts, original tail-frame continuation, audio and lip sync remain pending",
            ],
        }
        _write(self.run_dir / filename, manifest)
        return manifest

    def _validate_output_manifest(
        self,
        *,
        handoff: dict[str, Any],
        filename: str = "CREATIVE_OUTPUT_MANIFEST.json",
        state_hash_key: str = "output_manifest_sha256",
    ) -> dict[str, Any]:
        path = self.run_dir / filename
        if not path.is_file():
            raise RuntimeError("输出包总清单缺失")
        manifest = _read(path)
        if (_hash(manifest) != self.state.get(state_hash_key)
                or manifest.get("schema") != "creative_output_manifest/v1"):
            raise RuntimeError("输出包总清单版本不符")
        if (manifest.get("handoff_sha256") != _hash(handoff)
                or manifest.get("material_sha256") != self.state.get("material_sha256")
                or manifest.get("automatic_media_submit") is not False):
            raise RuntimeError("输出包总清单与本次交接不一致")
        for row in manifest.get("artifacts", []):
            relative = row.get("path")
            if not isinstance(relative, str) or Path(relative).name != relative:
                raise RuntimeError("输出包包含无效文件路径")
            artifact_path = self.run_dir / relative
            if (not artifact_path.is_file()
                    or _file_sha256(artifact_path) != row.get("sha256")
                    or artifact_path.stat().st_size != row.get("size_bytes")):
                raise RuntimeError(f"输出包产物 {relative} 已缺失或被改动")
        expected_stages = [
            (row["name"], row["role"], row["input_sha256"], row["output_sha256"])
            for row in self.state.get("stages", [])
        ]
        actual_stages = [
            (row.get("stage"), row.get("role"), row.get("input_sha256"), row.get("output_sha256"))
            for row in manifest.get("stage_handoffs", [])
        ]
        if actual_stages != expected_stages:
            raise RuntimeError("输出包角色交接链与运行状态不一致")
        for row in manifest.get("stage_handoffs", []):
            receipt_path = self.run_dir / row["receipt_path"]
            if not receipt_path.is_file() or _file_sha256(receipt_path) != row["receipt_sha256"]:
                raise RuntimeError(f"阶段回执 {row['receipt_path']} 已缺失或被改动")
        usage = manifest.get("usage_summary", {})
        if usage.get("calls_started") != self.state.get("calls_started"):
            raise RuntimeError("输出包调用计数与运行状态不一致")
        for row in usage.get("call_receipts", []):
            receipt_path = self.run_dir / row["path"]
            if not receipt_path.is_file() or _file_sha256(receipt_path) != row["sha256"]:
                raise RuntimeError(f"调用回执 {row['path']} 已缺失或被改动")
        return manifest

    def _reserve_tokens(
        self, role: str, messages: list[dict[str, str]], max_tokens: int = 12000,
    ) -> dict[str, Any]:
        """Reserve a conservative budget and return its auditable basis."""
        from .creative_diagnostic_spend import assert_no_unreconciled_diagnostic_spend
        assert_no_unreconciled_diagnostic_spend(self.run_dir)
        capability = role_context_capability(self._transport_role(role))
        serialized_characters = len(_canonical(messages))
        # Treat each serialized Unicode character as one planning token.  This
        # is deliberately conservative for the current Chinese-heavy inputs,
        # but is not presented as a provider tokenizer result.
        estimated_input_tokens = serialized_characters
        estimated_total = estimated_input_tokens + max_tokens
        if estimated_total > capability["planning_context_window_tokens"]:
            raise RuntimeError(
                f"{role} 请求保守估算 {estimated_total} token 超过已核验上下文规划上限，"
                "未发送且未静默截断"
            )
        if self._reported_tokens() + estimated_total > self.max_total_tokens:
            raise RuntimeError("文本 token 预算不足，保存进度且不跳过必需审核")
        return {
            "schema": "creative_context_budget/v1",
            "estimation_method": (
                "serialized_unicode_characters_as_conservative_input_token_estimate; "
                "provider_usage_is_authoritative_after_response"
            ),
            "serialized_input_characters": serialized_characters,
            "estimated_input_tokens": estimated_input_tokens,
            "requested_max_output_tokens": max_tokens,
            "estimated_total_tokens": estimated_total,
            **capability,
        }

    def _accept_response(self, path, record, *, require_tool=False):
        from .creative_response_contract import receipt_failure, CreativeResponseContractError
        failure = receipt_failure(record, require_tool=require_tool)
        if failure:
            record["failure"] = failure
            if failure["code"] == "RESPONSE_TRUNCATED":
                record["status"] = "incomplete_response"
            elif failure["response_received"]:
                record["status"] = "response_rejected"
            _write(path, record)
            self._save()
            raise CreativeResponseContractError(failure)

    def _record_response_exception(self, path, record, exc):
        from .creative_response_contract import exception_failure
        record["failure"] = exception_failure(exc)
        record["status"] = (
            "blocked_before_dispatch" if getattr(exc, "provider_dispatch_started", None) is False
            else "incomplete_response" if record["failure"]["code"] == "RESPONSE_TRUNCATED"
            else "response_rejected" if record["failure"]["response_received"]
            else "call_failed_or_uncertain")
        record["error"] = str(exc)
        if getattr(exc, "provider_dispatch_started", None) is False:
            record["provider_dispatch_started"] = False
        for attr, key in (("response_metadata", "response_metadata"),
                          ("response_text", "response_text"), ("response_payload", "response_payload")):
            value = getattr(exc, attr, None)
            if value is not None:
                record[key] = value
        _write(path, record)
        self._save()

    def _decode(self, name: str, role: str, raw: str) -> dict[str, Any]:
        try:
            return parse_json_object(raw)
        except CreativeContractError:
            pass
        stripped = raw.strip()
        if stripped.startswith("{"):
            try:
                first, first_end = json.JSONDecoder().raw_decode(stripped)
            except json.JSONDecodeError:
                first = None
                first_end = 0
            trailing = stripped[first_end:].strip() if first_end else ""
            if isinstance(first, dict) and trailing:
                if name == "writer_director_feedback" and set(first) == {"candidate_update"}:
                    try:
                        second, second_end = json.JSONDecoder().raw_decode(trailing)
                    except json.JSONDecodeError:
                        second = None
                        second_end = 0
                    if (
                        isinstance(second, dict)
                        and set(second) == {"feedback_responses"}
                        and not trailing[second_end:].strip()
                    ):
                        merged = {**first, **second}
                        receipt_path = self.run_dir / (
                            f"{name}__local_adjacent_objects_merge.json"
                        )
                        receipt = {
                            "schema": "creative_local_adjacent_objects_merge/v1",
                            "source_sha256": _hash(raw),
                            "output_sha256": _hash(merged),
                            "first_keys": list(first),
                            "second_keys": list(second),
                            "rule": (
                                "merged exactly two adjacent writer-director feedback objects "
                                "with disjoint expected top-level keys; values and key order preserved"
                            ),
                        }
                        if receipt_path.exists() and _read(receipt_path) != receipt:
                            raise RuntimeError(f"{name} 相邻对象归位回执与原响应不符")
                        _write(receipt_path, receipt)
                        reconciled = self.state.setdefault("local_format_reconciliations", [])
                        if name not in reconciled:
                            reconciled.append(name)
                            self._save()
                        return merged
                canonical_first = json.dumps(
                    first, ensure_ascii=False, separators=(",", ":"),
                )
                if canonical_first.startswith(trailing):
                    receipt_path = self.run_dir / f"{name}__local_duplicate_prefix.json"
                    receipt = {
                        "schema": "creative_local_duplicate_json_prefix/v1",
                        "source_sha256": _hash(raw),
                        "output_sha256": _hash(first),
                        "complete_object_characters": first_end,
                        "discarded_duplicate_prefix_characters": len(trailing),
                        "rule": (
                            "kept the first complete JSON object; trailing text was an exact "
                            "prefix of its canonical serialization"
                        ),
                    }
                    if receipt_path.exists() and _read(receipt_path) != receipt:
                        raise RuntimeError(f"{name} 重复 JSON 前缀归位回执与原响应不符")
                    _write(receipt_path, receipt)
                    repaired = self.state.setdefault("local_format_reconciliations", [])
                    if name not in repaired:
                        repaired.append(name)
                        self._save()
                    return first
        if name.startswith("writer_revise"):
            try:
                json.loads(stripped)
            except json.JSONDecodeError as exc:
                single_extra_closer = (
                    exc.msg == "Extra data" and exc.pos == len(stripped) - 1
                    and stripped.endswith("}}")
                )
            else:
                single_extra_closer = False
            if single_extra_closer:
                try:
                    locally_fixed = parse_json_object(stripped[:-1])
                except CreativeContractError:
                    pass
                else:
                    if _format_content_stream(stripped) == _format_content_stream(stripped[:-1]):
                        receipt_path = self.run_dir / f"{name}__local_format_repair.json"
                        receipt = {
                            "schema": "creative_local_format_repair/v1",
                            "source_sha256": _hash(raw),
                            "output_sha256": _hash(locally_fixed),
                            "repair": "discard_one_superfluous_final_closing_brace",
                        }
                        if receipt_path.exists() and _read(receipt_path) != receipt:
                            raise RuntimeError(f"{name} 本地格式修复回执与原响应不符")
                        _write(receipt_path, receipt)
                        repaired = self.state.setdefault("local_format_reconciliations", [])
                        if name not in repaired:
                            repaired.append(name)
                            self._save()
                        return locally_fixed
        if raw.lstrip().startswith("<think>") and "</think>" in raw:
            raw = raw.split("</think>", 1)[1].strip()
        local = _escape_embedded_json_quotes(raw)
        if local is not None:
            receipt_path = self.run_dir / f"{name}__local_format_repair.json"
            receipt = {
                "schema": "creative_local_format_repair/v1",
                "source_sha256": _hash(raw),
                "output_sha256": _hash(local),
                "repair": "escape_embedded_json_string_quotes_only",
            }
            if receipt_path.exists() and _read(receipt_path) != receipt:
                raise RuntimeError(f"{name} 本地格式修复回执与原响应不符")
            _write(receipt_path, receipt)
            repaired = self.state.setdefault("local_format_reconciliations", [])
            if name not in repaired:
                repaired.append(name)
                self._save()
            return local
        repair_path = self.run_dir / f"{name}__format_repair.json"
        if repair_path.exists():
            repair = _read(repair_path)
            if repair.get("source_sha256") != _hash(raw):
                raise RuntimeError(f"{name} 格式修复记录状态不明确")
            self._accept_response(repair_path, repair)
            if repair.get("status") != "response_received":
                raise RuntimeError(f"{name} 格式修复记录状态不明确")
            return _parse_format_repair(raw, repair["response_text"])
        if self.state["calls_started"] >= self.max_calls:
            raise CreativeContractError("JSON 格式损坏，修复预算不足")
        if self._split_repair_budget() and self._repair_budget_used() >= self.max_contract_repairs:
            raise CreativeContractError("JSON 格式损坏，共享格式与契约修复预算已满")
        messages = [
            {"role": "system", "content": "你只修复下一段 JSON 的语法，不改写任何事实、文字、顺序或选项。输出一个合法 JSON 对象，不要解释或代码围栏。"},
            {"role": "user", "content": raw},
        ]
        context_budget = self._reserve_tokens(role, messages)
        repair = {"status": "pending_response", "source_sha256": _hash(raw),
                  "role": role, "request_sha256": _hash(messages), "request": messages,
                  "context_budget": context_budget}
        _write(repair_path, repair)
        self.state["calls_started"] += 1
        if self._split_repair_budget():
            self.state["format_repairs_used"] += 1
        self._save()
        try:
            result = self._call_model(role, messages, temperature=0.0,
                                       thinking="disabled")
        except Exception as exc:
            self._record_response_exception(repair_path, repair, exc)
            raise
        repair.update(status="response_received", response_text=result.text,
                      response_metadata=result.metadata)
        _write(repair_path, repair)
        self._accept_response(repair_path, repair)
        return _parse_format_repair(raw, result.text)

    def _validate_or_repair(
        self, name: str, role: str, payload: dict[str, Any],
        output: dict[str, Any], validator: Any, seen_invalid_hashes: set[str] | None = None,
    ) -> dict[str, Any]:
        if name.startswith("director_state_plan") and payload.get("state_plan_version") == "whole_film_action_plan_v2":
            from .creative_action_plan_v2 import reject_unavailable_response, PlanUnavailableError
            try:
                reject_unavailable_response(output, payload)
            except PlanUnavailableError as exc:
                from .creative_governed_runtime import record_plan_stop
                record_plan_stop(self, name, exc)
                raise
        if self.review_policy_version in (REVIEW_V3, REVIEW_V4, REVIEW_V5, REVIEW_V6) and name.startswith(("writer_check", "script_review")):
            from .creative_review_v3 import canonicalize_unique_leaf_refs
            corrected, changes = canonicalize_unique_leaf_refs(output, payload)
            if changes:
                receipt = {"schema": "creative_unique_leaf_reference_projection/v1",
                           "source_sha256": _hash(output), "output_sha256": _hash(corrected),
                           "changes": changes, "automatic_approval": False,
                           "assistant_review_required": True}
                receipt_path = self.run_dir / f"{name}__local_leaf_refs_{_hash(output)[:12]}_{_hash(corrected)[:12]}.json"
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError("证据唯一叶子引用投影回执不一致")
                _write(receipt_path, receipt)
                output = corrected
        if self.review_policy_version in REVIEW_POLICY_VERSIONS and name.startswith(("writer_check", "script_review")):
            corrected_review = _project_missing_review_suggestions(output, payload)
            if corrected_review is not None:
                receipt_path = self.run_dir / f"{name}__local_empty_suggestions_{_hash(output)[:12]}.json"
                receipt = {"schema": "creative_missing_suggestions_projection/v1",
                    "source_sha256": _hash(output), "output_sha256": _hash(corrected_review),
                    "added_field": "suggestions", "value": [], "issues_unchanged": True,
                    "assistant_review_required": True, "automatic_approval": False}
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError("缺省建议列表投影回执不一致")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = corrected_review
        if name.startswith("director_shots__beat_"):
            from .creative_segmented_director import normalize_dialogue_lock_timing
            corrected, changes = normalize_dialogue_lock_timing(output, payload.get("script", {}))
            if changes:
                receipt = {"schema": "creative_dialogue_timing_metadata_projection/v1",
                           "source_sha256": _hash(output), "output_sha256": _hash(corrected),
                           "changes": changes, "dialogue_text_and_speaker_unchanged": True,
                           "automatic_approval": False}
                receipt_path = self.run_dir / f"{name}__local_dialogue_timing_{_hash(output)[:12]}.json"
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError("对白计时字段投影回执不一致")
                _write(receipt_path, receipt)
                output = corrected
        if name.startswith("director_shots"):
            continuity_projection = _project_mismatched_raw_tail_to_planned_cut(output)
            if continuity_projection is not None:
                corrected, affected_shots = continuity_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_continuity_mode_{_hash(output)[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_continuity_mode_projection/v1",
                    "source_sha256": _hash(output),
                    "output_sha256": _hash(corrected),
                    "affected_shot_ids": affected_shots,
                    "rule": (
                        "mismatched raw-tail start/end states require a reviewed cut adapter"
                    ),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError("导演镜头连续模式归位回执与原响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = corrected
        if name == "writer_director_feedback":
            ordered_feedback = _project_director_feedback_response_order(
                output, payload.get("writer_feedback", []),
            )
            if ordered_feedback is not None:
                receipt_path = self.run_dir / (
                    f"{name}__local_response_order_{_hash(output)[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_feedback_response_order/v1",
                    "source_sha256": _hash(output),
                    "output_sha256": _hash(ordered_feedback),
                    "feedback_indexes": [
                        row["feedback_index"]
                        for row in ordered_feedback["feedback_responses"]
                    ],
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError("导演意见回应排序回执与原响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = ordered_feedback
            projected_feedback = _project_director_feedback_candidate_lock(
                output, payload.get("candidate_lock", {}),
            )
            if projected_feedback is not None:
                (
                    corrected, restored_fields, relocated,
                    rejected_unacknowledged_fields, stripped_format_paths,
                    downgraded_noop_change_indexes,
                ) = projected_feedback
                receipt_path = self.run_dir / (
                    f"{name}__local_candidate_lock_{_hash(output)[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_candidate_lock_projection/v1",
                    "source_sha256": _hash(output),
                    "output_sha256": _hash(corrected),
                    "candidate_lock_sha256": _hash(payload["candidate_lock"]),
                    "restored_locked_fields": restored_fields,
                    "restored_candidate_fields_without_change_decision": (
                        rejected_unacknowledged_fields
                    ),
                    "relocated_feedback_responses": relocated,
                    "stripped_format_paths": stripped_format_paths,
                    "downgraded_noop_candidate_change_indexes": (
                        downgraded_noop_change_indexes
                    ),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError("导演前期意见候选锁归位回执与原响应不符")
                _write(receipt_path, receipt)
                repaired = self.state.setdefault("local_format_reconciliations", [])
                if name not in repaired:
                    repaired.append(name)
                    self._save()
                output = corrected
        if name == "writer_analysis":
            quote_wrapper_projection = _project_redundant_source_quote_wrappers(
                output, str(payload.get("story_source") or ""),
            )
            if quote_wrapper_projection is not None:
                corrected, changes = quote_wrapper_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_source_quote_wrappers_{_hash(output)[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_source_quote_wrapper_projection/v1",
                    "source_sha256": _hash(output),
                    "output_sha256": _hash(corrected),
                    "changes": changes,
                    "rule": (
                        "removed only a redundant outer quote pair when the unchanged "
                        "inner text occurs exactly once in story_source"
                    ),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 来源引文外层归位回执与当前响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = corrected
        if name.startswith(("writer_script", "writer_revise")):
            action_quote_projection = _project_redundant_action_dialogue_quotes(output)
            if action_quote_projection is not None:
                projected_output, changes = action_quote_projection
                source_hash = _hash(output)
                receipt_path = self.run_dir / (
                    f"{name}__local_action_dialogue_reference_{source_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_action_dialogue_reference/v1",
                    "source_sha256": source_hash,
                    "output_sha256": _hash(projected_output),
                    "changes": changes,
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(
                        f"{name} 动作对白引用归一化回执与原响应不符"
                    )
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = projected_output
            dialogue_projection = _project_singleton_dialogue_objects(output)
            if dialogue_projection is not None:
                projected_output, affected_paths = dialogue_projection
                source_hash = _hash(output)
                receipt_path = self.run_dir / (
                    f"{name}__local_singleton_dialogue_{source_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_singleton_dialogue_projection/v1",
                    "source_sha256": source_hash,
                    "output_sha256": _hash(projected_output),
                    "affected_paths": affected_paths,
                    "rule": "exact speaker/text object wrapped as a one-item dialogue array",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 单条对白归位回执与当前响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = projected_output
        if name == "director_brief":
            materials = payload.get("materials") or {}
            analysis = payload.get("analysis") or {}
            selected_id = analysis.get("selected_candidate_id")
            candidate = next(
                (
                    row for row in analysis.get("candidates", [])
                    if isinstance(row, dict) and row.get("id") == selected_id
                ),
                {},
            )
            scope_projection = _project_noop_director_source_scope(
                output,
                str(materials.get("story_source") or ""),
                str(materials.get("source_driver") or ""),
                candidate,
            )
            if scope_projection is not None:
                projected_output, cleared_fields = scope_projection
                source_hash = _hash(output)
                receipt_path = self.run_dir / (
                    f"{name}__local_noop_source_scope_{source_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_noop_director_source_scope/v1",
                    "source_sha256": source_hash,
                    "output_sha256": _hash(projected_output),
                    "cleared_fields": cleared_fields,
                    "rule": "boundary suggestion resolved to the unchanged candidate edge",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 零变化边界归位回执与当前响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = projected_output
        legacy_projection = (
            _project_legacy_writer_beat_plan(output)
            if name.startswith("writer_script") else None
        )
        if legacy_projection is not None:
            source_hash = _hash(output)
            receipt_path = self.run_dir / (
                f"{name}__local_beat_plan_projection_{source_hash[:12]}.json"
            )
            receipt = {
                "schema": "creative_local_beat_plan_projection/v1",
                "source_sha256": source_hash,
                "output_sha256": _hash(legacy_projection),
                "beat_ids": [row["id"] for row in legacy_projection["beats"]],
                "discarded_top_level_keys": sorted(
                    set(output) - {
                        "title", "premise", "selected_candidate_id",
                        "duration_seconds", "beats",
                    }
                ),
                "rule": "beat_id renamed to id; legacy summary metadata discarded; story text unchanged",
            }
            if receipt_path.exists() and _read(receipt_path) != receipt:
                raise RuntimeError(f"{name} 旧节拍投影回执与当前响应不符")
            _write(receipt_path, receipt)
            reconciled = self.state.setdefault("local_format_reconciliations", [])
            if name not in reconciled:
                reconciled.append(name)
                self._save()
            output = legacy_projection
        if name.startswith("writer_check"):
            owner_projection = _project_explicit_issue_owner(output)
            if owner_projection is not None:
                projected_output, changes = owner_projection
                source_hash = _hash(output)
                receipt_path = self.run_dir / (
                    f"{name}__local_explicit_owner_{source_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_explicit_issue_owner/v1",
                    "source_sha256": source_hash,
                    "changes": changes,
                    "output_sha256": _hash(projected_output),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 显式 owner 归位回执与当前响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                output = projected_output
        seen_invalid_hashes = set() if seen_invalid_hashes is None else seen_invalid_hashes
        output_hash = _hash(output)
        if output_hash in seen_invalid_hashes:
            raise CreativeContractError(f"{name} 修复结果在已有无效版本之间循环")
        seen_invalid_hashes.add(output_hash)
        try:
            validator(output)
            return output
        except CreativeContractError as exc:
            from .creative_action_plan_v2 import PlanUnavailableError
            if isinstance(exc, PlanUnavailableError):
                from .creative_governed_runtime import record_plan_stop
                record_plan_stop(self, name, exc)
                raise
            problem = str(exc)
            from .creative_response_contract import validation_failure
            failure_path = self.run_dir / f"{name}__validation_fault_{output_hash[:12]}.json"
            _write(failure_path, {"schema": "creative_validation_fault/v1",
                "stage": name, "source_sha256": output_hash,
                "failure": validation_failure(exc), "error": problem,
                "semantic_approval": False})
        if name.startswith(("director_shots", "director_revise")) and problem == "镜头 ID 重复":
            shots = output.get("shots")
            if isinstance(shots, list) and all(isinstance(row, dict) for row in shots):
                corrected = deepcopy(output)
                changes = []
                for index, shot in enumerate(corrected["shots"], start=1):
                    new_id = f"SH{index:02d}"
                    old_id = shot.get("id")
                    if old_id != new_id:
                        changes.append({"index": index - 1, "from": old_id, "to": new_id})
                        shot["id"] = new_id
                if changes:
                    receipt_path = self.run_dir / (
                        f"{name}__local_shot_id_resequence_{output_hash[:12]}.json"
                    )
                    receipt = {
                        "schema": "creative_local_shot_id_resequence/v1",
                        "source_sha256": output_hash,
                        "changes": changes,
                        "output_sha256": _hash(corrected),
                        "rule": "shot objects and order unchanged; ids resequenced by storyboard order",
                    }
                    if receipt_path.exists() and _read(receipt_path) != receipt:
                        raise RuntimeError(f"{name} 镜头编号归位回执与当前响应不符")
                    _write(receipt_path, receipt)
                    reconciled = self.state.setdefault("local_format_reconciliations", [])
                    if name not in reconciled:
                        reconciled.append(name)
                        self._save()
                    return self._validate_or_repair(
                        name, role, payload, corrected, validator,
                        seen_invalid_hashes,
                    )
        if name == "writer_director_feedback":
            meta_quote_projection = _project_candidate_meta_quote_as_prose(output, problem)
            if meta_quote_projection is not None:
                corrected, change = meta_quote_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_meta_quote_prose_{output_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_candidate_meta_quote_prose/v1",
                    "source_sha256": output_hash,
                    "change": change,
                    "output_sha256": _hash(corrected),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 元说明引号归位回执与当前响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                return self._validate_or_repair(
                    name, role, payload, corrected, validator,
                    seen_invalid_hashes,
                )
        if name == "writer_analysis":
            evidence_quote_projection = (
                _project_repeated_candidate_evidence_quote_as_prose(output, problem)
            )
            if evidence_quote_projection is not None:
                corrected, changes = evidence_quote_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_repeated_evidence_quote_{output_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_repeated_evidence_quote_projection/v1",
                    "source_sha256": output_hash,
                    "changes": changes,
                    "output_sha256": _hash(corrected),
                    "rule": (
                        "kept first dramatized quote; removed only delimiters from a later "
                        "same-field occurrence explicitly labelled as source evidence"
                    ),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 重复证据引号归位回执与当前响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                return self._validate_or_repair(
                    name, role, payload, corrected, validator,
                    seen_invalid_hashes,
                )
        if name.startswith("writer_check") and "issue.impact" in problem:
            impact_projection = _project_missing_check_impacts(output)
            if impact_projection is not None:
                impact_corrected, missing_indexes = impact_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_missing_impact_{output_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_missing_check_impact/v1",
                    "source_sha256": output_hash,
                    "missing_issue_indexes": missing_indexes,
                    "output_sha256": _hash(impact_corrected),
                    "rule": "fixed conservative placeholder; issue remains unresolved and cannot enable release",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 缺失影响归位回执与当前响应不符")
                _write(receipt_path, receipt)
                return self._validate_or_repair(
                    name, role, payload, impact_corrected, validator,
                    seen_invalid_hashes,
                )
        if name.startswith("director_revise") and "replace_beats" in output:
            previous_shots = payload.get("previous_shots")
            affected_beat_ids = payload.get("affected_beat_ids")
            if isinstance(previous_shots, dict) and isinstance(affected_beat_ids, list):
                try:
                    projected_director_output = _apply_director_revision_patch(
                        previous_shots, output, affected_beat_ids,
                    )
                except CreativeContractError:
                    projected_director_output = None
                if projected_director_output is not None:
                    receipt_path = self.run_dir / (
                        f"{name}__invalid_projection_{output_hash[:12]}.json"
                    )
                    receipt = {
                        "schema": "creative_director_revision_projection/v1",
                        "source_sha256": output_hash,
                        "affected_beat_ids": affected_beat_ids,
                        "output_sha256": _hash(projected_director_output),
                        "reason": "validate_and_repair_compact_revision_against_full_storyboard",
                    }
                    if receipt_path.exists() and _read(receipt_path) != receipt:
                        raise RuntimeError(f"{name} 紧凑导演返修投影回执与当前响应不符")
                    _write(receipt_path, receipt)
                    output = projected_director_output
                    projected_hash = _hash(output)
                    if projected_hash in seen_invalid_hashes:
                        raise CreativeContractError(f"{name} 修复结果在已有无效版本之间循环")
                    seen_invalid_hashes.add(projected_hash)
        if name.startswith("writer_revise") and self._script_revision_mode() != "full_script" and "replace_beats" in output:
            previous_script = payload.get("previous_script")
            affected_beat_ids = payload.get("affected_beat_ids")
            if isinstance(previous_script, dict) and isinstance(affected_beat_ids, list):
                try:
                    projected_writer_output = _apply_writer_revision_patch(
                        previous_script, output, affected_beat_ids,
                    )
                except CreativeContractError:
                    projected_writer_output = None
                if projected_writer_output is not None:
                    receipt_path = self.run_dir / (
                        f"{name}__invalid_projection_{output_hash[:12]}.json"
                    )
                    receipt = {
                        "schema": ("creative_writer_full_revision_adoption/v1" if self._script_revision_mode() == "full_script" else "creative_writer_revision_projection/v1"),
                        "source_sha256": output_hash,
                        "affected_beat_ids": affected_beat_ids,
                        "output_sha256": _hash(projected_writer_output),
                        "reason": "validate_and_repair_compact_revision_against_full_screenplay",
                    }
                    if receipt_path.exists() and _read(receipt_path) != receipt:
                        raise RuntimeError(f"{name} 紧凑编剧返修投影回执与当前响应不符")
                    _write(receipt_path, receipt)
                    output = projected_writer_output
                    projected_hash = _hash(output)
                    if projected_hash in seen_invalid_hashes:
                        raise CreativeContractError(f"{name} 修复结果在已有无效版本之间循环")
                    seen_invalid_hashes.add(projected_hash)
        if name.startswith("writer_revise") and self._script_revision_mode() != "full_script":
            writer_duration_projection = _project_whole_film_writer_duration_scale(payload, problem)
            if writer_duration_projection is not None:
                duration_corrected, duration_changes = writer_duration_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_whole_film_duration_scale_{_hash(output)[:12]}.json"
                )
                receipt = {
                    "schema": "creative_writer_duration_scale/v1",
                    "source_sha256": _hash(output),
                    "previous_script_sha256": _hash(payload.get("previous_script") or {}),
                    "problem": problem,
                    "changes": duration_changes,
                    "output_sha256": _hash(duration_corrected),
                    "rule": "scale only beat duration_seconds to the locked candidate total; all text and beat order unchanged",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 本地全片时长归位回执与当前响应不符")
                _write(receipt_path, receipt)
                return self._validate_or_repair(
                    name, role, payload, duration_corrected, validator,
                    seen_invalid_hashes,
                )
        if name.startswith(("director_shots", "director_revise")):
            duration_projection = _project_director_beat_duration_scale(
                output, payload.get("script") or {}, problem,
            )
            if duration_projection is not None:
                duration_corrected, duration_changes = duration_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_duration_scale_{_hash(output)[:12]}.json"
                )
                receipt = {
                    "schema": "creative_director_duration_scale/v1",
                    "source_sha256": _hash(output),
                    "script_sha256": _hash(payload.get("script") or {}),
                    "problem": problem,
                    "changes": duration_changes,
                    "output_sha256": _hash(duration_corrected),
                    "rule": "scale only existing shot durations to the locked beat total; all text and shot order unchanged",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 本地镜头时长归位回执与当前响应不符")
                _write(receipt_path, receipt)
                return self._validate_or_repair(
                    name, role, payload, duration_corrected, validator,
                    seen_invalid_hashes,
                )
        expected = {
            "source_sha256": _hash(output),
            "payload_sha256": _hash(payload),
            "error": problem,
            "repair_protocol": "generic_full_object/v1",
        }
        if name.startswith("writer_revise") and self._script_revision_mode() != "full_script" and "缺失节拍:" in problem and payload.get("affected_beat_ids"):
            expected["repair_protocol"] = "writer_revision_missing_beats/v1"
        missing_feedback_indexes = (
            _missing_director_feedback_suffix(
                output, payload.get("writer_feedback", []),
            )
            if name == "writer_director_feedback"
            and "导演前期意见必须由编剧逐条回应" in problem
            and isinstance(payload.get("writer_feedback"), list)
            else []
        )
        if missing_feedback_indexes:
            expected["repair_protocol"] = "writer_director_feedback_response_patch/v1"
        invalid_feedback_indexes = (
            _invalid_director_feedback_response_indexes(
                output, payload.get("writer_feedback", []),
            )
            if name == "writer_director_feedback"
            and any(marker in problem for marker in (
                "导演前期意见回应的编号、决定或理由无效",
                "候选或原文范围问题不能推给导演摄影阶段",
            ))
            and isinstance(payload.get("writer_feedback"), list)
            else []
        )
        if invalid_feedback_indexes:
            expected["repair_protocol"] = "writer_director_feedback_replace_patch/v1"
        is_director_scope_patch = (
            name.startswith("director_brief")
            and any(marker in problem for marker in (
                "source_scope", "原文边界", "原文前移", "收窄原文",
                "前置原文", "收窄起点", "视频原创导演",
            ))
        )
        if is_director_scope_patch:
            expected["repair_protocol"] = "director_source_scope_patch/v1"
        is_missing_shots_repair = (name.startswith("director_shots")
            and self.state.get("source_driver") == "original"
            and output.get("story_issues") == [] and not output.get("shots"))
        is_story_issue_repair = name.startswith("director_shots") and "story_issues" in output and not is_missing_shots_repair
        if is_missing_shots_repair:
            expected["repair_protocol"] = "director_missing_shots/v1"
        if is_story_issue_repair:
            expected["repair_protocol"] = "director_story_issue_enrichment/v1"
        # Check unresolved attempts before choosing a schema-specific filename.
        # A later repair_protocol assignment must not create a second paid request.
        from .creative_response_contract import receipt_failure
        for prior_path in sorted(self.run_dir.glob(f"{name}__contract_repair*.json")):
            prior = _read(prior_path)
            same_source = (prior.get("source_sha256") == expected["source_sha256"]
                           and prior.get("payload_sha256") == expected["payload_sha256"])
            unknown = receipt_failure(prior)
            if same_source or (unknown and unknown["code"] == "OUTCOME_UNKNOWN"):
                self._accept_response(prior_path, prior,
                    require_tool=bool(prior.get("tool_schema_sha256")))
        legacy_path = self.run_dir / f"{name}__contract_repair.json"
        path = legacy_path
        if legacy_path.exists():
            legacy = _read(legacy_path)
            if any(legacy.get(key) != value for key, value in expected.items() if key != "repair_protocol"):
                path = self.run_dir / f"{name}__contract_repair_{expected['source_sha256'][:12]}.json"
        is_director_patch = name.startswith(("director_shots", "director_revise")) and not is_story_issue_repair and not is_missing_shots_repair and payload.get("execution_projection_version") != "reviewed_beat_storyboard_v5"
        is_writer_script_stage = name.startswith(("writer_script", "writer_revise"))
        writer_script_beats = output.get("beats")
        writer_script_beat_range = creative_focus_beat_range(self.creative_focus)
        writer_script_count_outside_lock = (
            name == "writer_script"
            and isinstance(writer_script_beats, list)
            and writer_script_beat_range is not None
            and not (
                writer_script_beat_range[0]
                <= len(writer_script_beats)
                <= writer_script_beat_range[1]
            )
        )
        missing_writer_script_body = (
            name == "writer_script"
            and (
                not isinstance(writer_script_beats, list)
                or writer_script_count_outside_lock
                or isinstance(output.get("item"), dict)
            )
        )
        if missing_writer_script_body:
            expected["repair_protocol"] = "writer_script_full_body/v1"
        dialogue_split_beat_ids = (
            _dialogue_split_repair_beat_ids(output, problem)
            if is_writer_script_stage else []
        )
        if dialogue_split_beat_ids:
            expected["repair_protocol"] = "writer_dialogue_split_beat_patch/v1"
        director_beat_patch_ids: list[str] = []
        if is_director_patch and any(marker in problem for marker in (
            "分镜对白", "对白约", "分镜时长", "未绑定编剧定稿事件",
            "原始尾帧续段状态不连续", "视频执行时长超限",
        )):
            referenced_beats = set(_beat_references(problem))
            referenced_shots = set(_shot_references(problem))
            shot_to_beat = {
                row.get("id"): row.get("beat_id")
                for row in output.get("shots", []) if isinstance(row, dict)
                and isinstance(row.get("id"), str) and isinstance(row.get("beat_id"), str)
            }
            referenced_beats.update(
                shot_to_beat[shot_id] for shot_id in referenced_shots
                if shot_id in shot_to_beat
            )
            script = payload.get("script") or {}
            director_beat_patch_ids = [
                row.get("id") for row in script.get("beats", []) if isinstance(row, dict)
                and isinstance(row.get("id"), str) and row.get("id") in referenced_beats
            ]
        if director_beat_patch_ids:
            expected["repair_protocol"] = "director_beat_contract_patch/v1"
        missing_beat_fields = _missing_beat_fields(output) if is_writer_script_stage else []
        legacy_corrected = _reuse_projection_bound_legacy_beat_repair(
            self.run_dir, name, output, payload, missing_beat_fields,
        )
        if legacy_corrected is not None:
            return self._validate_or_repair(
                name, role, payload, legacy_corrected, validator, seen_invalid_hashes,
            )
        selected_source = payload.get("selected_source")
        selected_text = (
            selected_source.get("text", "") if isinstance(selected_source, dict) else ""
        )
        dialogue_order_beat_ids = (
            _novel_dialogue_order_repair_beat_ids(output, selected_text)
            if is_writer_script_stage
            and (payload.get("materials") or payload.get("material_ref") or {}).get(
                "source_driver"
            ) == "novel"
            and "对白不在所选原文顺序中" in problem
            else []
        )
        if dialogue_order_beat_ids:
            expected["repair_protocol"] = "writer_dialogue_order_beat_patch/v2"
        dialogue_order_rows: list[dict[str, Any]] = []
        if dialogue_order_beat_ids:
            normalized_selected = _dialogue_text(selected_text)
            for beat in output.get("beats", []):
                if not isinstance(beat, dict) or beat.get("id") not in dialogue_order_beat_ids:
                    continue
                for line_index, line in enumerate(beat.get("dialogue", [])):
                    if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                        continue
                    normalized_line = _dialogue_text(line["text"])
                    if normalized_selected.count(normalized_line) != 1:
                        continue
                    dialogue_order_rows.append({
                        "current_beat_id": beat["id"],
                        "current_line_index": line_index,
                        "speaker": line.get("speaker"),
                        "text": line["text"],
                        "source_position": normalized_selected.index(normalized_line),
                    })
        invalid_dialogue_paths = (
            _invalid_novel_dialogue_paths(output, selected_text)
            if is_writer_script_stage
            and (payload.get("materials") or payload.get("material_ref") or {}).get("source_driver") == "novel"
            and any(marker in problem for marker in (
                "对白不在所选原文顺序中", "角色对白不是所选原文中的人物直接引语",
            ))
            and not missing_beat_fields and not dialogue_order_beat_ids else []
        )
        if invalid_dialogue_paths:
            local_dialogue_projection = _project_unique_source_dialogue_punctuation(
                output, selected_text, invalid_dialogue_paths,
            )
            if local_dialogue_projection is not None:
                dialogue_corrected, changes = local_dialogue_projection
                receipt_path = self.run_dir / (
                    f"{name}__local_dialogue_punctuation_{output_hash[:12]}.json"
                )
                receipt = {
                    "schema": "creative_local_dialogue_punctuation/v1",
                    "source_sha256": _hash(output),
                    "selected_source_sha256": _hash(selected_text),
                    "required_paths": invalid_dialogue_paths,
                    "changes": changes,
                    "projected_paths": [row["path"] for row in changes],
                    "unresolved_paths": [
                        path for path in invalid_dialogue_paths
                        if path not in [row["path"] for row in changes]
                    ],
                    "output_sha256": _hash(dialogue_corrected),
                    "rule": (
                        "words unchanged; uniquely recoverable punctuation restored from ordered "
                        "direct quotes; unresolved rows remain for the next bound repair"
                    ),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 原文对白标点归位回执与当前绑定不符")
                _write(receipt_path, receipt)
                return self._validate_or_repair(
                    name, role, payload, dialogue_corrected, validator,
                    seen_invalid_hashes,
                )
        timing_beat_ids: list[str] = []
        if (
            is_writer_script_stage and not missing_writer_script_body
            and not missing_beat_fields and not invalid_dialogue_paths
            and any(marker in problem for marker in (
                "对白约", "全片对白约", "剧本节拍合计", "偏离候选",
                "creative_focus 明确时长范围",
                "duration_seconds 必须为 0-600 秒正数",
            ))
        ):
            problem_ids = set(_beat_references(problem))
            use_all = (
                "全片对白约" in problem or "剧本节拍合计" in problem
                or "偏离候选" in problem or "creative_focus 明确时长范围" in problem
            )
            timing_beat_ids = [
                row.get("id") for row in output.get("beats", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
                and (use_all or row.get("id") in problem_ids)
            ]
        if timing_beat_ids:
            expected["repair_protocol"] = "writer_timing_patch/v4"
        action_restatement_paths: list[list[Any]] = []
        if is_writer_script_stage and "复述已锁定对白" in problem:
            beat_indexes = {
                row.get("id"): index for index, row in enumerate(output.get("beats", []))
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            for beat_id, field in re.findall(
                r"(?<![A-Za-z0-9_])(B\d+[A-Za-z]?)\."
                r"(before|during|after)(?![A-Za-z0-9_])",
                problem,
            ):
                if beat_id in beat_indexes:
                    path_value = ["beats", beat_indexes[beat_id], field]
                    if path_value not in action_restatement_paths:
                        action_restatement_paths.append(path_value)
        if action_restatement_paths:
            expected["repair_protocol"] = "writer_action_restatement_patch/v1"
        missing_analysis_fields = (
            _missing_analysis_fields(output)
            if name == "writer_analysis" and "必须为非空文字" in problem else []
        )
        analysis_source = selected_text or (
            payload.get("materials") or payload
        ).get("story_source", "")
        invalid_candidate_quote_paths = (
            _invalid_candidate_quote_paths(output, analysis_source)
            if name == "writer_analysis"
            and "candidate." in problem and "在来源中必须唯一定位" in problem
            else []
        )
        invalid_candidate_match = re.search(
            r"candidate\.(start_quote|end_quote)", problem,
        )
        if invalid_candidate_quote_paths and invalid_candidate_match:
            invalid_field = invalid_candidate_match.group(1)
            invalid_candidate_quote_paths = [
                path for path in invalid_candidate_quote_paths if path[-1] == invalid_field
            ]
        invalid_character_quote_paths = (
            _invalid_character_quote_paths(output, analysis_source)
            if name == "writer_analysis"
            and "characters[" in problem and ".source_quote" in problem
            and "在来源中必须唯一定位" in problem
            else []
        )
        invalid_character_match = re.search(r"characters\[(\d+)\]\.source_quote", problem)
        if invalid_character_quote_paths and invalid_character_match:
            invalid_index = int(invalid_character_match.group(1))
            invalid_character_quote_paths = [
                path for path in invalid_character_quote_paths if path[1] == invalid_index
            ]
        if invalid_character_quote_paths:
            expected["repair_protocol"] = "writer_character_quote_patch/v2"
        action_patch_mode = False
        if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_action_plan_v1", "whole_film_action_plan_v2"):
            from .creative_plan_patch import can_patch_contract_error
            action_patch_mode = can_patch_contract_error(output, problem)
            expected["repair_protocol"] = "action_plan_local_patch/v1" if action_patch_mode else "action_plan_full_rebuild/v1"
        if path.exists():
            existing_repair = _read(path)
            if any(existing_repair.get(key) != value for key, value in expected.items()):
                protocol_hash = hashlib.sha256(
                    str(expected.get("repair_protocol", "generic")).encode("utf-8")
                ).hexdigest()[:8]
                path = self.run_dir / (
                    f"{name}__contract_repair_{expected['source_sha256'][:12]}_"
                    f"{protocol_hash}.json"
                )
        repair_instruction = (
            "只重做 target_beat_ids 对应的完整编剧节拍，不复制标题、其他节拍或整份剧本。"
            "仅返回合法 JSON：{\"replace_beats\":[{\"beat_id\":\"B04\",\"beat\":完整节拍对象}]}。"
            "beat_id、数量和顺序必须与 target_beat_ids 完全相同；每个 beat 只能含 id、"
            "duration_seconds、event、trigger、before、during、after、dialogue。"
            "replace_beats 的每项必须且只能包含 beat_id 和 beat 两个键，完整节拍必须放在 beat 内，"
            "绝不能把 duration_seconds 等节拍字段平铺到外层。"
            "把 target_beats 中已有的逐字原文对白按 required_target_dialogue_order 调整到正确先后，"
            "不得翻译、改写、删字、拼接、重复或新增对白；允许把一条对白从前拍移到后拍，"
            "每个列出的 text 必须恰好出现一次，且输出中的先后必须按 source_position 递增；"
            "并同步修正 event、trigger、动作和时长，使动作仍按 before→第一句对白→during→"
            "其余对白→after 成立。目标节拍合计时长保持 target_duration_seconds。不要返回说明。"
            if dialogue_order_beat_ids else
            "只补齐 missing_feedback 中列出的导演意见回应，不复制 candidate_update、已有回应或整份交接。"
            "只返回合法 JSON：{\"feedback_responses\":[{\"feedback_index\":4,"
            "\"decision\":\"accepted_in_script\",\"reason\":\"具体处理方式\"}]}。"
            "feedback_index 的数量、顺序和值必须与 missing_feedback 完全一致；decision 只能是 "
            "accepted_candidate_change、accepted_in_script、director_only、declined。"
            "涉及候选、选段或原文边界的问题不能选择 director_only；candidate_update 已锁定，"
            "若无需再改候选应说明将如何在剧本中落实。不要返回其他键。"
            if missing_feedback_indexes else
            "只重做 target_feedback 中列出的无效导演意见回应，不复制 candidate_update、其他回应或整份交接。"
            "只返回合法 JSON：{\"feedback_responses\":[{\"feedback_index\":2,"
            "\"decision\":\"accepted_in_script\",\"reason\":\"具体处理方式\"}]}。"
            "feedback_index 的数量、顺序和值必须与 target_feedback 完全一致；每项只能包含 "
            "feedback_index、decision、reason，不能添加 rationale_field 等键。decision 只能是 "
            "accepted_candidate_change、accepted_in_script、director_only、declined。"
            "candidate_decision_required 为 true 时不能选择 director_only；candidate_update 已锁定，"
            "若无需再改候选应具体说明将在节拍中怎样落实。不要返回其他键。"
            if invalid_feedback_indexes else
            "只修复导演前期稿的原文起点建议，不复制整份导演稿。只返回合法 JSON："
            "{\"source_scope\":{\"lead_in_start_quote\":\"\",\"trim_start_quote\":\"\",\"extend_end_quote\":\"\",\"trim_end_quote\":\"\",\"reason\":\"\"}}。"
            "前移与收窄最多选一个；终点延长可同时使用；引文必须从 source_window 逐字连续复制且能唯一定位。"
            "若没有可靠的边界调整，三个引文和 reason 都留空。不要返回 style_options 或其他字段。"
            if is_director_scope_patch else
            "只重做 target_beat_ids 对应的完整镜头组，不复制 style、其他节拍或整份导演稿。"
            "仅返回合法 JSON：{\"replace_beats\":[{\"beat_id\":\"B01\",\"shots\":[完整镜头对象]}]}。"
            "beat_id、数量和顺序必须与 target_beat_ids 完全相同。每个镜头必须只含现有导演镜头合同字段，"
            "event_lock 逐字等于 script_beat.event，合并后的 dialogue_lock 逐句等于 script_beat.dialogue，"
            "镜头时长合计等于 script_beat.duration_seconds。可以重新拆镜和分配时长，但不能缩写、改写或增加台词；"
            "每个有对白镜头按实际对白最多每秒5字分配时长，不能借无对白镜头抵扣。"
            "首尾状态须接续 boundary_states；新切镜使用 planned_cut_requires_adapter。不要返回说明。"
            if director_beat_patch_ids else
            "重新提交完整的 writer_script JSON，不要回显 error、original 或输入包装。"
            "顶层必须且只能包含 title、premise、selected_candidate_id、duration_seconds、beats。"
            "beats 必须是数组，每拍必须且只能包含 id、duration_seconds、event、trigger、"
            "before、during、after、dialogue；dialogue 每项只有 speaker、text。"
            "严格按 candidate_lock 与 creative_focus 写出完整事件链；小说对白和旁白逐字取自"
            " selected_source，人物直接对白按 source_dialogue_inventory 顺序，间接叙述不能改成"
            "人物台词。总时长等于各拍时长之和。不要返回说明。"
            if missing_writer_script_body else
            "只修复指定导演稿校验错误。返回合法 JSON 对象 {\"patches\":[{\"path\":[\"shots\",序号,\"字段名\"],\"value\":新值}]}。"
            "序号从0开始；只改必须修改的最多3个已有字段，不能改人物事件或其他镜头。不要复制完整原稿。"
            if is_director_patch else
            "只填补 missing_beat_fields 列出的空字段。仅返回 {\"patches\":[{\"path\":[\"beats\",0,\"before\"],\"value\":\"具体可见动作\"}]}。"
            "每个缺失路径按给定顺序补一项；不能改已有字段、不能额外加键、不能复制完整原稿。"
            "路径以 dialogue 结尾时 value 必须是 [{\"speaker\":\"角色名\",\"text\":\"实际台词\"}]，"
            "本拍无对白则 value 为 []；对白子字段路径的 value 是非空文字；其他字段写可见动作或事件。"
            if missing_beat_fields else
            "只修复 invalid_candidate_quotes 指定的小说候选起止引文，不复制完整编剧分析。"
            "仅返回合法 JSON：{\"patches\":[{\"path\":[\"candidates\",0,\"end_quote\"],"
            "\"value\":\"来源中的逐字连续短引文\"}]}。路径、条数和顺序必须逐项对应；"
            "value 必须从 source_evidence 逐字复制并在完整来源中唯一定位。"
            "不能改候选事件、人物、选择或其他字段；证据不足时不要编造近义引文。"
            if invalid_candidate_quote_paths else
            "只修复 invalid_character_quotes 指定的人物来源引文，不复制整份编剧分析。"
            "仅返回合法 JSON：{\"patches\":[{\"path\":[\"characters\",0,\"source_quote\"],"
            "\"value\":\"来源中的逐字连续短引文\"}]}。路径、条数和顺序必须逐项对应；"
            "value 必须从 source_evidence 逐字复制并在完整来源中唯一定位，不能改人称、简繁体、标点或拼接省略。"
            "不能修改人物目标、候选、选择或其他字段。"
            if invalid_character_quote_paths else
            "只修复 invalid_dialogue 指定的小说对白，不复制完整剧本。仅返回合法 JSON 对象"
            " {\"patches\":[{\"path\":[\"beats\",0,\"dialogue\",0,\"text\"],\"value\":\"原文连续短句\"}]}。"
            "路径、条数和顺序必须逐项对应；每个 value 必须逐字等于对应 allowed_source_spans.options 中"
            "某个 text，包括原标点；若没有合适选项或本句不该说，value 写空字符串以删除整句。"
            "不能自行从 selected_source 拼接、删词或改标点；在其他对白之间保持原文先后顺序。"
            "不能拼接跳过的原文、增减标点、改说话人或修改其他字段。"
            if invalid_dialogue_paths else
            "只修复 invalid_action_restatements 指定的动作字段，不复制完整剧本。仅返回合法 JSON："
            "{\"patches\":[{\"path\":[\"beats\",0,\"during\"],\"value\":\"只含可见表情、视线、站位或肢体反应\"}]}。"
            "路径、条数和顺序必须逐项对应；删除动作字段对 dialogue 的复述，但保留该字段原有的可见情绪反应、"
            "动作结果与下一状态。value 不得出现‘说、道、问、答、喊、开口、宣称、念出’等转述台词的表达，"
            "不能改对白、事件、时长或其他字段。"
            if action_restatement_paths else
            "只修复 target_beat_ids 的对白容量与节拍时长，不复制整份剧本。仅返回合法 JSON："
            "{\"replace_beats\":[{\"beat_id\":\"B01\",\"duration_seconds\":10,\"dialogue\":[{\"speaker\":\"角色\",\"text\":\"原文连续整句\"}]}]}。"
            "必须按 target_beat_ids 原顺序逐拍返回且不漏项；每项只能有 beat_id、duration_seconds、dialogue。"
            "保留该拍事件和情绪功能；小说对白的每个 text 必须逐字复制 allowed_source_spans 中某个 options.text，"
            "包括原标点；可以删除整条，或把同一长台词拆成多个按原顺序排列的选项，绝不能自行删词、改写、拼接。"
            "删去中间句后，前后保留句必须各自成为独立 dialogue 项，不能跨过被删内容拼成一个 text；"
            "只能删除完整句或直接采用 options.text，不能在逗号、分号或破折号处自行截断。"
            "原创视频没有 allowed_source_spans 时才可使用原有对白。不能把叙述当人物对白。"
            "把补丁应用回未列出的原拍后，若 required_total_duration_range 非空，全片合计必须落在该闭区间内；"
            "若 required_beat_count_range 非空，应用补丁后的 beats 数量也必须落在该闭区间内；"
            "否则须接近 candidate_duration_seconds。必须先逐项相加自检，不能返回仍超出上限的补丁；"
            "计时单位按中日韩每字1单位、"
            "其他文字每词2单位计算，每拍对白不超过每秒4.5单位、全片不超过每秒3.5单位，"
            "为动作与反应留时。不要修改事件、动作、人物或其他字段。"
            if timing_beat_ids else
            "只补 missing_analysis_fields 指定的缺失人物目标或候选字段。仅返回合法 JSON 对象"
            " {\"patches\":[{\"path\":[\"candidates\",0,\"setup\"],\"value\":\"...\"}]}。"
            "逐项按原顺序返回，不要复制完整原稿，也不要修改既有引文、候选选择、剧情或其他字段。"
            "duration_seconds 用正整数，其余字段用非空文字；依据 original 的已有材料填具体因果，"
            "不得用空泛占位符或编造原文没有的人物行动。"
            if missing_analysis_fields else
            "只修复可读剧本动作段的指定错误。仅返回 {\"beat_scenes\":[{\"beat_id\":\"...\",\"action_segments\":[\"...\"]}]}；"
            "严格按 beat_scene_required_shape 的 ID、顺序和 action_segment_count 填写，不增删节拍。"
            "每个节拍只允许 beat_id、action_segments 两个键；不要添加 dialogue、台词、片尾字段。"
            "对白由程序插入，动作段不得直接写出说话内容。其他已合格动作保持原意。"
            if name == "writer_screenplay" else
            "只输出修正后的编剧分析 JSON 对象，不要回显输入的 error、original、source_sha256、"
            "source_evidence 或 source_evidence_limit。输入的 original 才是待修的稿件，不是输出包装格式。"
            "顶层必须且只能有 summary、characters、candidates、selected_candidate_id、"
            "selection_reason、reference_use 六个键。summary 必须是文字；characters、candidates、"
            "reference_use 必须是列表；没有表达参考时 reference_use 为 []。characters 每项必须且只能有 name、"
            "want、fear、source_quote；candidates 每项必须且只能有 id、title、setup、conflict、turn、"
            "peak、aftermath、start_quote、end_quote、duration_seconds、selection_reason；候选 id 使用 C01"
            " 这类稳定编号，duration_seconds 使用正整数。reference_use 每项必须且只能有 reference_id、"
            "mechanism、not_used。若供应商把本应独立的字段折叠进 summary 或 XML 文字，必须恢复为上述"
            "结构；仅从 creative_focus、source_evidence 和 original 已有内容恢复，证据不足不能补写新事件。"
            "人物 source_quote 和小说候选"
            "起止引文必须从提供的原文逐字复制，不能用省略号拼接。错误指向 characters[i].source_quote"
            " 时，只改该索引人物的引文；参考 invalid_character_quotes 和 source_evidence 中的附近原文。"
            "只改校验错误，不得借修复改写故事。"
            if name == "writer_analysis" else
            "修复下面 JSON 的指定校验错误。只改必须修改的字段；事实、人物归属、候选选择和其他文本保持原样。引文只能从提供的故事来源逐字复制，不能改写。返回完整合法 JSON 对象，不要解释。"
        )
        if dialogue_split_beat_ids:
            repair_instruction = (
                "只重做 target_beat_ids 对应的完整编剧节拍，不复制 error、draft_sha256、"
                "selected_source、其他节拍或整份剧本。仅返回合法 JSON："
                "{\"replace_beats\":[{\"beat_id\":\"B03\",\"beat\":完整节拍对象}]}。"
                "beat_id、数量与顺序必须和 target_beat_ids 完全相同；beat 只能含 id、"
                "duration_seconds、event、trigger、before、during、after、dialogue。"
                "把需要在长对白中间出现的听者反应放到 during：只可在 selected_source 已有标点处"
                "把原 dialogue 拆成同一 speaker 的相邻多条，按顺序拼接后须逐字等于原 dialogue，"
                "不得插入空 text、其他 speaker、删字、改字、改标点或新增对白。只能修改 during 与"
                "dialogue；id、duration_seconds、event、trigger、before、after 必须逐字复制 target_beats。"
                "during 只写可见动作，不得用‘说到某句时’或复述台词模拟内部时序。不要返回说明。"
            )
        repair_payload = (
            {
                "error": problem,
                "draft_sha256": _hash(output),
                "target_beat_ids": dialogue_order_beat_ids,
                "target_beats": [
                    row for row in output.get("beats", [])
                    if isinstance(row, dict) and row.get("id") in dialogue_order_beat_ids
                ],
                "target_duration_seconds": sum(
                    row.get("duration_seconds", 0) for row in output.get("beats", [])
                    if isinstance(row, dict) and row.get("id") in dialogue_order_beat_ids
                ),
                "current_target_dialogue_order": dialogue_order_rows,
                "required_target_dialogue_order": sorted(
                    dialogue_order_rows, key=lambda row: row["source_position"]
                ),
                "selected_source": selected_text,
            }
            if dialogue_order_beat_ids else
            {
                "error": problem,
                "draft_sha256": _hash(output),
                "candidate_lock": payload.get("candidate_lock"),
                "candidate_update": output.get("candidate_update"),
                "existing_feedback_responses": output.get("feedback_responses"),
                "missing_feedback": [
                    {
                        "feedback_index": index,
                        "feedback": payload["writer_feedback"][index],
                        "candidate_decision_required": _feedback_requires_candidate_decision(
                            payload["writer_feedback"][index]
                        ),
                    }
                    for index in missing_feedback_indexes
                ],
                "selected_source": payload.get("selected_source"),
            }
            if missing_feedback_indexes else
            {
                "error": problem,
                "draft_sha256": _hash(output),
                "candidate_update_sha256": _hash(output.get("candidate_update")),
                "target_feedback": [
                    {
                        "feedback_index": index,
                        "feedback": payload["writer_feedback"][index],
                        "invalid_response": output["feedback_responses"][index],
                        "candidate_decision_required": _feedback_requires_candidate_decision(
                            payload["writer_feedback"][index]
                        ),
                    }
                    for index in invalid_feedback_indexes
                ],
                "selected_source": payload.get("selected_source"),
            }
            if invalid_feedback_indexes else
            _director_scope_repair_evidence(payload, output, problem)
            if is_director_scope_patch else
            _candidate_quote_repair_evidence(
                payload, output, problem, invalid_candidate_quote_paths,
            )
            if invalid_candidate_quote_paths else
            _repair_evidence(payload, output, problem)
            if invalid_character_quote_paths else
            _director_repair_evidence(payload, output, problem)
            if director_beat_patch_ids else
            {
                "error": problem,
                "original_partial": output,
                "candidate_lock": payload.get("candidate_lock"),
                "selected_source": payload.get("selected_source"),
                "source_dialogue_inventory": payload.get("source_dialogue_inventory", []),
                "creative_focus": self.creative_focus,
                "source_driver": (
                    payload.get("materials") or payload.get("material_ref") or {}
                ).get("source_driver"),
            }
            if missing_writer_script_body else
            _director_repair_evidence(payload, output, problem)
            if is_director_patch else
            {"error": problem, "draft_sha256": _hash(output),
             "invalid_dialogue": [
                 {"path": path, "speaker": output["beats"][path[1]]["dialogue"][path[3]]["speaker"],
                  "text": output["beats"][path[1]]["dialogue"][path[3]]["text"]}
                 for path in invalid_dialogue_paths
             ],
             "selected_source": selected_text,
             "source_dialogue_inventory": payload.get("source_dialogue_inventory", []),
             "allowed_source_spans": _dialogue_compression_options(
                 output,
                 [output["beats"][path[1]]["id"] for path in invalid_dialogue_paths],
                 selected_text,
             )}
            if invalid_dialogue_paths else _repair_evidence(payload, output, problem)
        )
        if timing_beat_ids:
            candidate = payload.get("candidate_lock") or {}
            repair_payload = {
                "error": problem,
                "draft_sha256": _hash(output),
                "candidate_duration_seconds": (candidate.get("duration_seconds")
                    if not (self.state.get("writer_prompt_binding") or {}).get("creative_brief", {}).get("duration_policy") == "flexible" else None),
                "required_total_duration_range": creative_focus_duration_range(
                    self.creative_focus,
                ),
                "required_beat_count_range": creative_focus_beat_range(
                    self.creative_focus,
                ),
                "target_beat_ids": timing_beat_ids,
                "target_beats": [
                    row for row in output.get("beats", []) if row.get("id") in timing_beat_ids
                ],
                "selected_source": selected_text,
                "source_dialogue_inventory": payload.get("source_dialogue_inventory", []),
                "allowed_source_spans": _dialogue_compression_options(
                    output, timing_beat_ids, selected_text,
                ) if selected_text else [],
                "beat_speech_unit_caps": {
                    row["id"]: int(row["duration_seconds"] * 4.5)
                    for row in output.get("beats", [])
                    if isinstance(row, dict) and row.get("id") in timing_beat_ids
                    and isinstance(row.get("duration_seconds"), (int, float))
                },
                "film_speech_unit_cap": int(sum(
                    row.get("duration_seconds", 0) for row in output.get("beats", [])
                    if isinstance(row, dict)
                    and isinstance(row.get("duration_seconds"), (int, float))
                ) * 3.5),
            }
        if action_restatement_paths:
            repair_payload = {
                "error": problem,
                "draft_sha256": _hash(output),
                "invalid_action_restatements": [
                    {
                        "path": path_value,
                        "beat_id": output["beats"][path_value[1]]["id"],
                        "current_value": output["beats"][path_value[1]][path_value[2]],
                        "event": output["beats"][path_value[1]]["event"],
                        "trigger": output["beats"][path_value[1]]["trigger"],
                        "locked_dialogue": output["beats"][path_value[1]]["dialogue"],
                        "before": output["beats"][path_value[1]]["before"],
                        "after": output["beats"][path_value[1]]["after"],
                    }
                    for path_value in action_restatement_paths
                ],
            }
        if dialogue_split_beat_ids:
            repair_payload = {
                "error": problem,
                "draft_sha256": _hash(output),
                "target_beat_ids": dialogue_split_beat_ids,
                "target_beats": [
                    row for row in output.get("beats", [])
                    if isinstance(row, dict) and row.get("id") in dialogue_split_beat_ids
                ],
                "selected_source": selected_text,
                "required_rule": (
                    "split only at source punctuation; concatenate split texts to the exact "
                    "original dialogue; visible reaction belongs between adjacent lines"
                ),
            }
        if director_beat_patch_ids:
            script_rows = {
                row.get("id"): row for row in (payload.get("script") or {}).get("beats", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            shots = output.get("shots", [])
            target_indexes = [
                index for index, row in enumerate(shots) if isinstance(row, dict)
                and row.get("beat_id") in director_beat_patch_ids
            ]
            if not target_indexes:
                raise CreativeContractError("导演定向修复没有找到受影响节拍的完整镜头")
            first_index = min(target_indexes)
            last_index = max(target_indexes)
            repair_payload = {
                "error": problem,
                "draft_sha256": _hash(output),
                "target_beat_ids": director_beat_patch_ids,
                "script_beats": [script_rows[beat_id] for beat_id in director_beat_patch_ids],
                "current_beat_shots": [
                    row for row in shots if isinstance(row, dict)
                    and row.get("beat_id") in director_beat_patch_ids
                ],
                "style_lock": output.get("style"),
                "boundary_states": {
                    "previous_end_state": (
                        shots[first_index - 1].get("end_state") if first_index > 0 else None
                    ),
                    "next_start_state": (
                        shots[last_index + 1].get("start_state")
                        if last_index + 1 < len(shots) else None
                    ),
                },
            }
        if director_beat_patch_ids and payload.get("executor_constraints"):
            repair_payload["executor_constraints"] = payload["executor_constraints"]
            repair_instruction += (
                "每个镜头都必须满足 executor_constraints 的 duration_min/duration_max，"
                "同时保持该节拍合计时长。超长节拍必须拆成多个有叙事作用的镜头，"
                "短于最小时长的镜头需合并或重新分配；不能仅压短整拍，不能返回 duration_seconds 数值补丁。"
                "对白模式只用画内、画外或画内/画外；无对白时用无对白。"
            )
        if invalid_character_quote_paths:
            repair_payload = {
                "error": problem,
                "draft_sha256": _hash(output),
                "invalid_character_quotes": [
                    row for row in repair_payload.get("invalid_character_quotes", [])
                    if row.get("path") in invalid_character_quote_paths
                ],
                "source_evidence": repair_payload.get("source_evidence", []),
            }
        if missing_beat_fields:
            repair_payload["missing_beat_fields"] = missing_beat_fields
        if missing_analysis_fields:
            repair_payload["missing_analysis_fields"] = missing_analysis_fields
        if invalid_candidate_quote_paths:
            repair_payload["invalid_candidate_quotes"] = [
                row for row in repair_payload.get("invalid_candidate_quotes", [])
                if row.get("path") in invalid_candidate_quote_paths
            ]
        if name == "writer_screenplay":
            repair_payload["beat_scene_required_shape"] = payload["beat_scene_required_shape"]
        repair_structured_schema = WRITER_TOOL_SCHEMAS["writer_script"] if missing_writer_script_body and role == "writer" else None
        if name.startswith("writer_revise") and self._script_revision_mode() != "full_script" and "缺失节拍:" in problem and payload.get("affected_beat_ids"):
            repair_structured_schema = _writer_revision_schema(payload["affected_beat_ids"])
            repair_instruction = (
                "按原返修任务补全缺失节拍，只返回 {replace_beats:[{beat_id,beat}]}。"
                "数量、ID、顺序必须与 original_request.affected_beat_ids 完全一致。"
                "已提供且合格的返修节拍保持原样；错放在 item 的节拍移入列表。"
                "缺失节拍必须根据原任务 issues 和 previous_script 完成实际返修，不得以旧稿直接填缺。"
                "每个 beat 提交完整字段，dialogue 必须为数组，无对白写 []。"
                "保留事件归属、锁定对白及原任务来源约束；禁止返回原样的残缺对象。"
            )
            repair_payload = {"error": problem, "original_request": payload, "invalid_response": output}
        if is_missing_shots_repair:
            shape = {
                "style": {k: "..." for k in ("style_option_id", "visual_medium", "palette", "spatial_layout", "character_lock", "light_source")},
                "shots": [{"id": "SH01", "beat_id": "实际节拍ID", "duration_seconds": 8,
                    **{k: "..." for k in ("purpose", "composition", "camera", "visible_performance", "event_lock", "start_state", "end_state", "cut_reason", "dialogue_mode", "continuity_mode", "prompt")},
                    "dialogue_lock": [{"speaker": "实际说话人", "text": "逐字对白"}], "production_choices": []}],
                "media_assumptions": []}
            repair_instruction = (
                "你负责为已审核原创剧本完成完整分镜。上一响应 story_issues 为空但遗漏分镜，必须补交 expected_shape 的完整对象。"
                "只返回 style/shots/media_assumptions，不返回 story_issues、patches 或新剧本；被驳回的意见不得换措辞重提。"
                "creative_brief 是用户硬约束；script 是唯一演出锁，候选旧实现不得覆盖已修订剧本。"
                "按每拍 before→首句dialogue→during→后续dialogue→after 分配动作、台词及反应时间，不改变因果和说话人。"
                "每拍至少一镜，按原节拍顺序、逐拍合计时长准确。event_lock 逐字复制该拍event，dialogue_lock 按实际对白顺序逐字分配，不增删重复。"
                "说话时长按中文每字一单位、拉丁词每词两单位，每镜每秒最多5单位，另给动作与反应留时。"
                "采用 director_brief.selected_style_id。确定人物人数、身份、服装、布局及唯一道具归属；不添加简报禁止的物品和无叙事作用操作。"
                "首态只写本镜开始已成立状态，镜内动作不能提前完成；尾态记录结果。"
                "continuity_mode 仅 raw_tail_continuation/planned_cut_requires_adapter；原尾帧续段首态逐字等于上一尾态，换机位采用planned_cut_requires_adapter。"
                "dialogue_mode 仅用“画内”、“画外”、“画内/画外”或“无对白”，须符合构图；无对白写“无对白”。"
                "服从 executor_constraints 的每镜时长和能力，必要时拆镜保持每拍总时长。"
                "省略进店点单不等于缺失因果；已有动作顺序内可安排的2秒反应窗口由导演具体排时，不按动作数量判断超时。"
                "不得声称已完成声音、口型或真实视频审核。"
            )
            original_request = deepcopy(payload)
            binding = self.state.get("writer_prompt_binding") or {}
            if binding.get("creative_brief"):
                original_request["creative_brief"] = deepcopy(binding["creative_brief"])
            dismissal_records = []
            for review_key, bound in self.state.get("evidence_review_decisions", {}).items():
                if review_key.startswith("director"):
                    decision_path = self.run_dir / f"{review_key}__assistant_decision.json"
                    if decision_path.exists():
                        decision = _read(decision_path)
                        if review_digest(decision) != bound["decision_sha256"]:
                            raise RuntimeError("已使用的导演驳回回执不能修改")
                        dismissal_records.append({"review_key": review_key, "summary": decision.get("summary"), "decisions": decision.get("decisions")})
            repair_payload = {"error": problem, "original_request": original_request,
                "invalid_response": output, "expected_shape": shape, "assistant_review_decisions": dismissal_records}
        if is_story_issue_repair:
            repair_instruction = (
                "修复导演退回编剧意见的结构。只返回 {story_issues:[完整问题对象]}，不得返回 shots 或 patches。"
                "逐项原样保留原问题的 owner、severity、evidence、impact、proposal 等已存在字段，不能删除、合并或改写意见。"
                "location 只有在唯一对应原稿节拍时才可归位（如 B01 对应 B1）；否则保持原样等待核实。"
                "去掉根层附带的 style/media_assumptions，仅补全缺少的 id、rule、contradiction、evidence_refs。"
                "证据逐字引用 original_request 中真实字段；不得编造证据，不得判断意见已经通过。"
            )
            if self.review_policy_version in REVIEW_POLICY_VERSIONS:
                repair_instruction += review_rules(self.review_policy_version)
            repair_payload = {"error": problem, "original_request": payload, "invalid_response": output}
        if name.startswith("director_shots") and payload.get("execution_projection_version") == "reviewed_beat_storyboard_v5" and not is_story_issue_repair:
            from .creative_segmented_director import build_execution_repair
            repair_instruction, repair_payload = build_execution_repair(problem, payload, output)
            repair_structured_schema = None
        if name == "static_visual_manifest" and payload.get("static_manifest_version") == "static_visual_manifest_v2":
            from .creative_static_visual_manifest import build_static_manifest_repair
            repair_instruction, repair_payload = build_static_manifest_repair(problem, payload, output)
            repair_structured_schema = None
        repair_thinking = "disabled"
        if name.startswith("director_state_plan"):
            from .creative_state_plan_v6 import build_state_plan_repair
            repair_instruction, repair_payload = build_state_plan_repair(problem, payload, output)
            repair_structured_schema = None
            if payload.get("state_plan_version") in ("whole_film_state_plan_v2", "whole_film_state_plan_v3", "whole_film_action_plan_v1", "whole_film_action_plan_v2"):
                from .creative_state_plan_v6 import build_state_plan_schema
                repair_structured_schema = build_state_plan_schema(payload)
                repair_thinking = payload.get("plan_thinking_mode", "adaptive")
                repair_instruction += "\n请调用submit_creative_json工具提交完整目标对象。"
            if action_patch_mode:
                from .creative_plan_patch import build_patch_request, build_patch_schema, repair_paths_for_error
                repair_scope = repair_paths_for_error(output, problem)
                repair_target_schema = repair_structured_schema
                repair_instruction, repair_payload = build_patch_request(
                    repair_target_schema, payload, problem, output, repair_scope)
                repair_structured_schema = build_patch_schema(output, repair_scope, target_schema=repair_target_schema)
                repair_instruction += "\n调用submit_creative_json提交补丁对象，禁止重写整稿。"
        if self.review_policy_version == REVIEW_V6 and name.startswith(("writer_check", "script_review")):
            repair_instruction, repair_payload = build_review_repair(problem, payload, output)
            repair_structured_schema = None
        if path.exists():
            repair = _read(path)
            if any(repair.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"{name} 旧修复记录绑定了不同产物")
            self._accept_response(path, repair, require_tool=repair_structured_schema is not None)
            if repair.get("status") != "response_received":
                raise RuntimeError(f"{name} 上次契约修复调用状态未确认")
        else:
            if self.state["calls_started"] >= self.max_calls:
                raise CreativeContractError(f"{name}: {problem}；修复预算不足")
            if self._split_repair_budget():
                if self._repair_budget_used() >= self.max_contract_repairs:
                    raise CreativeContractError(f"{name}: {problem}；共享格式与契约修复预算已满")
            elif self.state["revision_rounds"] >= self.max_revisions:
                raise CreativeContractError(f"{name}: {problem}；共享实质返修轮数已满")
            messages = [
                {"role": "system", "content": repair_instruction},
                {"role": "user", "content": json.dumps(repair_payload, ensure_ascii=False)},
            ]
            context_budget = self._reserve_tokens(role, messages)
            repair = {"status": "pending_response", **expected, "error": problem,
                      "role": role, "request_sha256": _hash(messages), "request": messages,
                      "context_budget": context_budget}
            if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_state_plan_v2", "whole_film_state_plan_v3", "whole_film_action_plan_v1", "whole_film_action_plan_v2"):
                repair["request_parameters"] = {"thinking": repair_thinking, "temperature": 0.0,
                    "max_completion_tokens": 12000}
                repair["tool_schema_sha256"] = _hash(repair_structured_schema)
            _write(path, repair)
            self.state["calls_started"] += 1
            if self._split_repair_budget():
                self.state["contract_repairs_used"] += 1
            else:
                self.state["revision_rounds"] += 1
            self._save()
            try:
                result = self._call_model(
                    role, messages, temperature=0.0, thinking=repair_thinking,
                    structured_schema=repair_structured_schema,
                )
            except Exception as exc:
                self._record_response_exception(path, repair, exc)
                raise
            repair.update(status="response_received", response_text=result.text,
                          response_metadata=result.metadata)
            _write(path, repair)
        self._accept_response(path, repair, require_tool=repair_structured_schema is not None)
        try:
            corrected = parse_json_object(repair["response_text"])
        except CreativeContractError:
            # A contract repair can itself contain only JSON punctuation damage.
            # Route that exact response through the format-only channel; its
            # content-stream guard prevents a syntax repair from rewriting facts.
            corrected = self._decode(f"{path.stem}__response", role, repair["response_text"])
        if action_patch_mode:
            corrected = self._merge_action_plan_patch(path.stem, output, corrected, allowed_paths=repair_scope, target_schema=repair_target_schema)
        if is_missing_shots_repair:
            if "story_issues" in corrected or "patches" in corrected:
                raise CreativeContractError("空问题分支必须补交完整分镜，不能制造新问题或字段补丁")
            source = payload.get("selected_source") or {}
            validate_shots(corrected, payload.get("director_brief") or payload.get("brief") or {},
                           payload.get("script") or {}, source.get("text", "") if isinstance(source, dict) else "", self.creative_focus)
        if is_story_issue_repair:
            enrichment_response = deepcopy(corrected)
            corrected, projection_notes = _project_story_issue_enrichment(output, corrected, payload)
            projection_path = self.run_dir / f"{path.stem}__local_issue_enrichment_projection.json"
            projection_receipt = {"schema": "creative_story_issue_enrichment_projection/v1",
                "source_sha256": _hash(output), "response_sha256": _hash(enrichment_response),
                "output_sha256": _hash(corrected), **projection_notes}
            if projection_path.exists() and _read(projection_path) != projection_receipt:
                raise RuntimeError("剧情意见补全投影回执不一致")
            _write(projection_path, projection_receipt)
            repair["reconciliation"] = {"protocol": expected["repair_protocol"],
                "preserved_issue_count": len(corrected["story_issues"]),
                "location_changes": [{"index": i, "before": old.get("location"), "after": new.get("location")}
                    for i, (old, new) in enumerate(zip(output["story_issues"], corrected["story_issues"]))
                    if old.get("location") != new.get("location")],
                "removed_root_keys": sorted(set(output) - {"story_issues"})}
            _write(path, repair)
        if missing_feedback_indexes or invalid_feedback_indexes:
            metadata_projection = _project_feedback_patch_echo_metadata(corrected)
            if metadata_projection is not None:
                projected_patch, stripped_paths = metadata_projection
                receipt_path = self.run_dir / (
                    f"{path.stem}__local_feedback_metadata_projection.json"
                )
                receipt = {
                    "schema": "creative_local_feedback_metadata_projection/v1",
                    "source_sha256": _hash(corrected),
                    "output_sha256": _hash(projected_patch),
                    "stripped_format_paths": stripped_paths,
                    "rule": "drop only boolean request metadata echoed into patch rows",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 回应补丁元数据归位回执与模型响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                corrected = projected_patch
        if dialogue_split_beat_ids:
            locked_field_projection_source_sha256 = _hash(corrected)
            locked_field_projection = _project_missing_locked_dialogue_split_fields(
                output, corrected, dialogue_split_beat_ids,
            )
            if locked_field_projection is not None:
                corrected, restored_fields = locked_field_projection
                receipt_path = self.run_dir / (
                    f"{path.stem}__local_locked_field_projection.json"
                )
                receipt = {
                    "schema": "creative_local_locked_field_projection/v1",
                    "source_sha256": locked_field_projection_source_sha256,
                    "output_sha256": _hash(corrected),
                    "restored_fields": restored_fields,
                    "rule": (
                        "restore only omitted immutable parent beat fields; "
                        "never overwrite a returned locked-field value"
                    ),
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 锁定字段归位回执与模型响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
            blank_projection = _project_blank_dialogue_separators(
                corrected, output, dialogue_split_beat_ids,
            )
            if blank_projection is not None:
                receipt_path = self.run_dir / (
                    f"{path.stem}__local_blank_dialogue_projection.json"
                )
                receipt = {
                    "schema": "creative_local_blank_dialogue_projection/v1",
                    "source_sha256": _hash(corrected),
                    "output_sha256": _hash(blank_projection),
                    "affected_beat_ids": dialogue_split_beat_ids,
                    "rule": "remove whitespace-only separator lines when remaining text equals parent",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 空白对白归位回执与模型响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                corrected = blank_projection
            interleaved_projection = _project_interleaved_dialogue_revision_patch(
                corrected, dialogue_split_beat_ids,
            )
            if interleaved_projection is not None:
                receipt_path = self.run_dir / (
                    f"{path.stem}__local_interleaved_dialogue_projection.json"
                )
                receipt = {
                    "schema": "creative_local_interleaved_dialogue_projection/v1",
                    "source_sha256": _hash(corrected),
                    "output_sha256": _hash(interleaved_projection),
                    "affected_beat_ids": dialogue_split_beat_ids,
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 交错对白归位回执与模型响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                corrected = interleaved_projection
            _validate_dialogue_split_revision_scope(
                output, corrected, dialogue_split_beat_ids,
            )
            corrected = _apply_writer_revision_patch(output, corrected, dialogue_split_beat_ids)
        elif dialogue_order_beat_ids:
            flat_projection = _project_flat_writer_revision_patch(
                corrected, dialogue_order_beat_ids,
            )
            if flat_projection is not None:
                receipt_path = self.run_dir / f"{path.stem}__local_flat_beat_projection.json"
                receipt = {
                    "schema": "creative_local_flat_writer_revision_projection/v1",
                    "source_sha256": _hash(corrected),
                    "output_sha256": _hash(flat_projection),
                    "affected_beat_ids": dialogue_order_beat_ids,
                    "rule": "wrap exact flat beat fields; add id from identical beat_id",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 平铺节拍归位回执与模型响应不符")
                _write(receipt_path, receipt)
                reconciled = self.state.setdefault("local_format_reconciliations", [])
                if name not in reconciled:
                    reconciled.append(name)
                    self._save()
                corrected = flat_projection
            corrected = _apply_writer_revision_patch(
                output, corrected, dialogue_order_beat_ids,
            )
        elif missing_feedback_indexes:
            corrected = _apply_director_feedback_response_patch(
                output, corrected, missing_feedback_indexes,
            )
        elif invalid_feedback_indexes:
            corrected = _replace_director_feedback_responses(
                output, corrected, invalid_feedback_indexes,
            )
        elif missing_beat_fields:
            corrected = _apply_missing_beat_patches(output, corrected, missing_beat_fields)
        elif director_beat_patch_ids:
            if "未绑定编剧定稿事件" in problem:
                event_projection = _project_director_beat_event_locks(
                    corrected, payload.get("script") or {}, director_beat_patch_ids,
                )
                if event_projection is not None:
                    projected_patch, changes = event_projection
                    receipt_path = self.run_dir / (
                        f"{path.stem}__local_event_lock_projection.json"
                    )
                    receipt = {
                        "schema": "creative_local_event_lock_projection/v1",
                        "source_sha256": _hash(corrected),
                        "output_sha256": _hash(projected_patch),
                        "affected_beat_ids": director_beat_patch_ids,
                        "changes": changes,
                        "rule": (
                            "copy only immutable script beat.event into existing "
                            "split-shot event_lock fields"
                        ),
                    }
                    if receipt_path.exists() and _read(receipt_path) != receipt:
                        raise RuntimeError(f"{name} 事件锁归位回执与模型响应不符")
                    _write(receipt_path, receipt)
                    reconciled = self.state.setdefault(
                        "local_format_reconciliations", []
                    )
                    if name not in reconciled:
                        reconciled.append(name)
                        self._save()
                    corrected = projected_patch
            corrected = _apply_director_revision_patch(
                output, corrected, director_beat_patch_ids,
            )
        elif invalid_candidate_quote_paths:
            corrected = _apply_candidate_quote_patches(
                output, corrected, invalid_candidate_quote_paths, analysis_source,
            )
        elif invalid_character_quote_paths:
            corrected = _apply_character_quote_patches(
                output, corrected, invalid_character_quote_paths, analysis_source,
            )
        elif invalid_dialogue_paths:
            corrected = _apply_novel_dialogue_patches(
                output, corrected, invalid_dialogue_paths, selected_text,
            )
        elif action_restatement_paths:
            corrected = _apply_writer_action_patches(
                output, corrected, action_restatement_paths,
            )
        elif timing_beat_ids:
            corrected = _apply_writer_timing_patch(output, corrected, timing_beat_ids)
        elif missing_analysis_fields and "patches" in corrected:
            projected = _project_unrequested_analysis_quote_patches(
                corrected, missing_analysis_fields,
            )
            if projected is not None:
                projected_repair, ignored_paths = projected
                receipt_path = self.run_dir / f"{path.stem}__local_patch_projection.json"
                receipt = {
                    "schema": "creative_local_patch_projection/v1",
                    "source_sha256": _hash(corrected),
                    "projected_sha256": _hash(projected_repair),
                    "ignored_paths": ignored_paths,
                    "reason": "unsolicited_character_quote_edits_rejected",
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} 编剧分析补丁归位回执与原响应不符")
                _write(receipt_path, receipt)
                corrected = projected_repair
            corrected = _apply_missing_analysis_patches(
                output, corrected, missing_analysis_fields,
            )
        elif (
            name == "writer_screenplay"
            and "beat_scenes" in corrected
            and set(corrected) <= {"beat_scenes", "error", "report"}
            and set(corrected) != {"beat_scenes"}
        ):
            repair["projection"] = "discard_non_story_metadata_only"
            _write(path, repair)
            corrected = {"beat_scenes": corrected["beat_scenes"]}
        elif "patches" in corrected:
            corrected = _apply_repair_patches(output, corrected)
        elif is_director_scope_patch and set(corrected) == {"source_scope"}:
            corrected = {**deepcopy(output), "source_scope": corrected["source_scope"]}
        elif (
            isinstance(corrected.get("original"), dict)
            and set(corrected) <= set(repair_payload)
        ):
            if _hash(corrected["original"]) == _hash(output):
                raise CreativeContractError(
                    f"{name} 修复只回显原稿与证据，未改变无效产物: {problem}"
                )
            if all(
                corrected[key] == repair_payload[key]
                for key in corrected if key != "original"
            ):
                repair["reconciliation"] = "lift_modified_original_from_unchanged_evidence_wrapper"
                _write(path, repair)
                corrected = corrected["original"]
        elif set(corrected) == {"error", "original"} and isinstance(corrected["original"], dict):
            corrected = corrected["original"]
        if name.startswith("script_review") and isinstance(corrected.get("issues"), list):
            rerouted = [
                {"id": row.get("id"), "owner": row.get("owner")}
                for row in corrected["issues"]
                if isinstance(row, dict) and row.get("owner") != "writer"
            ]
            if rerouted:
                projected = deepcopy(corrected)
                for row in projected["issues"]:
                    if isinstance(row, dict):
                        row["owner"] = "writer"
                receipt_path = self.run_dir / f"{path.stem}__local_owner_route_projection.json"
                receipt = {
                    "schema": "creative_local_owner_route_projection/v1",
                    "source_sha256": _hash(corrected),
                    "projected_sha256": _hash(projected),
                    "changed_issues": rerouted,
                    "reason": "pre_directing_review_has_no_director_artifact_to_repair",
                    "semantic_conclusions_changed": False,
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} owner route projection receipt changed")
                _write(receipt_path, receipt)
                corrected = projected
        if name.startswith("script_review") and isinstance(corrected.get("coverage"), list):
            projected = deepcopy(corrected)
            removed = []
            for beat in projected["coverage"]:
                for check_name, check in beat.get("checks", {}).items():
                    if check.get("status") != "not_applicable":
                        continue
                    refs = check.get("evidence_refs", [])
                    kept = [ref for ref in refs if not (
                        isinstance(ref, dict)
                        and ref.get("path", "").endswith(".dialogue")
                        and ref.get("quote") == "[]"
                    )]
                    if len(kept) != len(refs):
                        removed.append({"beat_id": beat.get("id"), "check": check_name})
                        check["evidence_refs"] = kept
            if removed:
                receipt_path = self.run_dir / f"{path.stem}__local_not_applicable_evidence_projection_{_hash(corrected)[:12]}.json"
                receipt = {
                    "schema": "creative_local_not_applicable_evidence_projection/v1",
                    "source_sha256": _hash(corrected),
                    "projected_sha256": _hash(projected),
                    "removed_array_refs": removed,
                    "semantic_conclusions_changed": False,
                }
                if receipt_path.exists() and _read(receipt_path) != receipt:
                    raise RuntimeError(f"{name} not-applicable evidence projection receipt changed")
                _write(receipt_path, receipt)
                corrected = projected
        if self.review_policy_version == REVIEW_V6 and name.startswith(("writer_check", "script_review")):
            validate_repair_preserves_conclusions(output, corrected)
        try:
            validator(corrected)
        except CreativeContractError as exc:
            if _hash(corrected) == _hash(output):
                raise CreativeContractError(
                    f"{name} 修复未改变无效产物: {exc}"
                ) from None
            return self._validate_or_repair(
                name, role, payload, corrected, validator, seen_invalid_hashes,
            )
        return corrected

    def _merge_action_plan_patch(self, key: str, original: dict, patch: dict, allowed_paths=None, *, target_schema=None) -> dict:
        from .creative_plan_patch import apply_plan_patch
        merged = apply_plan_patch(original, patch, allowed_paths=allowed_paths, target_schema=target_schema)
        receipt = {"schema": "action_plan_patch_merge/v1", "source_sha256": _hash(original),
                   "patch_sha256": _hash(patch), "output_sha256": _hash(merged),
                   "model_patch": patch, "output": merged, "semantic_approval": False}
        if original.get("schema") == "whole_film_action_plan_v2":
            from .creative_plan_patch import patch_recheck_scope
            receipt["dependency_recheck"] = patch_recheck_scope(original, patch, target_schema=target_schema)
        path = self.run_dir / f"{key}__action_patch_merge.json"
        if path.exists() and _read(path) != receipt:
            raise RuntimeError("动作计划补丁合并回执改变，不能覆盖")
        _write(path, receipt)
        return merged

    def _unwrap_director_envelope(self, name: str, output: dict[str, Any]) -> dict[str, Any]:
        """Remove one redundant response envelope without changing any shot content."""
        if not name.startswith("director_") or set(output) != {"director_shots"}:
            return output
        inner = output["director_shots"]
        if not isinstance(inner, dict) or not {"style", "shots"} <= set(inner):
            return output
        path = self.run_dir / f"{name}__local_envelope_reconciliation.json"
        receipt = {
            "schema": "creative_local_envelope_reconciliation/v1",
            "envelope_key": "director_shots",
            "source_sha256": _hash(output),
            "output_sha256": _hash(inner),
        }
        if path.exists() and _read(path) != receipt:
            raise RuntimeError(f"{name} 导演稿外层归位回执与原响应不符")
        _write(path, receipt)
        repaired = self.state.setdefault("local_format_reconciliations", [])
        if name not in repaired:
            repaired.append(name)
            self._save()
        return inner

    def _unwrap_writer_revise_envelope(self, name: str, output: dict[str, Any]) -> dict[str, Any]:
        """Keep a complete revised script when the writer adds only audit metadata."""
        if not name.startswith("writer_revise") or "writer_script" not in output:
            return output
        if set(output) - {
            "writer_script", "unresolved", "revision_notes", "issues_resolved",
            "source_scope", "creative_notes",
        }:
            return output
        if output.get("unresolved", []) != []:
            raise CreativeContractError(f"{name} 返修报告仍有未解决问题，不能归位为合格剧本")
        scope = output.get("source_scope")
        if scope is not None and (
            not isinstance(scope, dict)
            or scope.get("modified") != [] or scope.get("conflicts") != []
        ):
            raise CreativeContractError(f"{name} 返修报告声称改动来源边界或仍有冲突")
        inner = output["writer_script"]
        script_keys = {
            "title", "premise", "selected_candidate_id", "duration_seconds",
            "beats", "screenplay_markdown",
        }
        metadata_keys = {
            "source_sha256", "source_evidence", "invalid_character_quotes",
            "source_evidence_limit", "change_log", "shot_list",
        }
        if not isinstance(inner, dict) or not script_keys <= set(inner):
            return output
        if set(inner) - script_keys - metadata_keys:
            return output
        script = {key: deepcopy(inner[key]) for key in script_keys}
        path = self.run_dir / f"{name}__local_envelope_reconciliation.json"
        receipt = {
            "schema": "creative_local_envelope_reconciliation/v1",
            "envelope_key": "writer_script",
            "source_sha256": _hash(output),
            "output_sha256": _hash(script),
            "excluded_wrapper_keys": sorted(set(output) - {"writer_script"}),
            "excluded_inner_keys": sorted(set(inner) - script_keys),
        }
        if path.exists() and _read(path) != receipt:
            raise RuntimeError(f"{name} 编剧稿外层归位回执与原响应不符")
        _write(path, receipt)
        reconciled = self.state.setdefault("local_format_reconciliations", [])
        if name not in reconciled:
            reconciled.append(name)
            self._save()
        return script

    def _stage(self, name, role, payload, validator):
        from .creative_stage_runtime import execute_stage
        return execute_stage(self, name, role, payload, validator)

    def _regenerate_full_storyboard(self, key, script, brief, analysis, candidate,
                                   selected_source, context_ref, source):
        """Build all shots from the reviewed new script, without old-shot patches."""
        return self._stage(
            f"director_shots__full_revision_{key}", "director",
            {"material_ref": context_ref, "analysis": analysis, "director_brief": brief,
             "candidate_lock": candidate, "selected_source": selected_source, "script": script},
            lambda value: validate_shots(value, brief, script, source, self.creative_focus))

    def _script_revision_mode(self):
        return (self.state.get("script_revision_binding") or {}).get("mode", "scoped")

    def _stage_impl(
        self,
        name: str,
        role: str,
        payload: dict[str, Any],
        validator: Any,
    ) -> dict[str, Any]:
        self._active_stage_name = name
        recovery = self.state.get("stage_recovery_bindings", {}).get(name)
        if recovery:
            if recovery.get("version") != "failed_plan_full_rebuild_v1":
                raise RuntimeError("不支持的失败计划恢复绑定")
            payload = {**payload, "stage_recovery_requirements": recovery["requirements"],
                       "previous_invalid_output": recovery["previous_invalid_output"]}
        if name.startswith("writer_revise") and self._script_revision_mode() == "full_script":
            payload = {**payload, "revision_mode": "full_script"}
        if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_action_plan_v1", "whole_film_action_plan_v2") and payload.get("plan_patch_base"):
            payload = {**payload, "source_sha256": _hash(payload["plan_patch_base"])}
            if payload.get("previous_draft") == payload["plan_patch_base"]:
                payload.pop("previous_draft", None)
        if name.startswith(("writer_check", "script_review")) and self.review_policy_version == REVIEW_V6:
            evidence_interface = self.state.get("review_evidence_interface_version")
            if evidence_interface:
                if evidence_interface not in ("leaf_catalog_v1", "evidence_ids_v1"):
                    raise CreativeContractError("不支持的审核证据接口版本")
                payload = {**payload, "review_evidence_interface_version": evidence_interface}
                hints_version = self.state.get("evidence_id_repair_hints_version")
                if hints_version:
                    if evidence_interface != "evidence_ids_v1" or hints_version != "missing_source_candidates_v1":
                        raise CreativeContractError("不支持的审核证据候选导航版本")
                    payload["evidence_id_repair_hints_version"] = hints_version
        path = self.run_dir / f"{name}.json"
        if path.exists() and _read(path).get("status") == "blocked_before_dispatch":
            blocked = _read(path)
            if blocked.get("provider_dispatch_started") is not False:
                raise RuntimeError("blocked request lacks confirmed non-dispatch evidence")
            archive = path.with_name(name + "__blocked_" + _hash(blocked) + ".json")
            if archive.exists():
                raise RuntimeError("blocked request archive collision")
            path.replace(archive)

        if name.startswith(("director_shots", "director_revise")):
            limits = None
            if path.exists():
                messages = _read(path).get("request", {}).get("messages", [])
                if messages:
                    limits = json.loads(messages[-1]["content"]).get("executor_constraints")
            elif getattr(self, "_reusable_generation", False):
                audit = audit_creative_executor({"shots": []})
                limits = {k: audit[k] for k in ("provider", "model", "duration_min", "duration_max", "evidence")}
                limits["rule"] = "每镜时长须在范围内；长节拍拆成有叙事目的的镜头。切镜仍需实际衔接适配，不得伪称原始尾帧连续。"
            if limits:
                payload = {**payload, "executor_constraints": limits}
                original_validator = validator
                def validate_executable(value):
                    original_validator(value)
                    resolved = value
                    if "replace_beats" in value:
                        resolved = _apply_director_revision_patch(
                            payload["previous_shots"], value, payload["affected_beat_ids"])
                    invalid = [f"{row['id']}={row['duration_seconds']}秒"
                               for row in resolved.get("shots", [])
                               if type(row.get("duration_seconds")) is not int
                               or not limits["duration_min"] <= row["duration_seconds"] <= limits["duration_max"]]
                    if invalid:
                        raise CreativeContractError(
                            f"视频执行时长超限 {limits['duration_min']}—{limits['duration_max']}秒: {invalid}；拆镜时保留对白顺序与情绪窗口")
                validator = validate_executable
        if name.startswith("director_production_design") and not path.exists():
            payload = deepcopy(payload)
            payload["planning_rules"] = {
                "reuse": "required_tags保留真实兼容要求，不为命中素材而删掉服装、光线等约束。指定复用必须与目录一致；未证实或需要改造时列issues或明确新建。未知布局需实际看图，不得猜测。",
                "opening": "逐镜依据storyboard.start_state写t=0单张静态首帧；不复制整段视频prompt，不写随后、说完、转向、递出等镜内事件；不得把镜内事件提前完成。",
                "assets": "asset_ids必须包含本镜所有可见人物（含手、背影、局部）及场景对应ID；纯画外发声不等于入画。固定左右、服装和道具首态与分镜一致。",
                "dialogue": "逐句核对说话人是否入画，画内/画外/混合模式须与构图及生成提示一致。",
                "review": "issues和previous_design为实际返修依据，逐项处理，不以自评分替代审核。",
            }
            if hasattr(self, "_production_revision_context"):
                payload.update(self._production_revision_context)
        elif name.startswith("director_production_design") and path.exists():
            messages = _read(path).get("request", {}).get("messages", [])
            if messages:
                recorded = json.loads(messages[-1]["content"])
                for key in ("planning_rules", "issues", "previous_design"):
                    if key in recorded:
                        payload = {**payload, key: recorded[key]}
        event_binding = self.state.get("writer_prompt_binding")
        original_director_binding = self.state.get("original_director_binding")
        original_directing = bool(event_binding and original_director_binding and name.startswith("director_shots"))
        revision_binding = None
        if event_binding and original_director_binding and name.startswith("director_revise"):
            revision_binding = self.state.get("original_director_revision_bindings", {}).get(name)
            if revision_binding is None and not path.exists():
                revision_binding = bind_original_director_revision(original_director_binding["prompt"])
                self.state.setdefault("original_director_revision_bindings", {})[name] = revision_binding
                self._save()
        if original_directing or revision_binding:
            payload = {**payload, "creative_brief": event_binding["creative_brief"]}
        event_authoring = bool(event_binding and name.startswith(("writer_script", "writer_revise")))
        if event_binding and name.startswith(("writer_script", "writer_revise", "writer_check")):
            payload = {**payload, "creative_brief": event_binding["creative_brief"]}
        priority_binding = self.state.get("original_brief_priority_binding")
        if event_binding and priority_binding and name.startswith(("writer_analysis", "director_brief", "writer_director_feedback")):
            payload = {**payload, "creative_brief": event_binding["creative_brief"]}
        if event_authoring:
            upstream_validator = validator
            def validate_original_event_result(value):
                upstream_validator(value)
                resolved = value
                if name.startswith("writer_revise") and payload.get("affected_beat_ids"):
                    resolved = _writer_revision_result(payload["previous_script"], value, payload["affected_beat_ids"], allow_summary_update=payload.get("allow_summary_update", False), revision_mode=self._script_revision_mode())
                validate_brief_script(resolved, event_binding["creative_brief"])
            validator = validate_original_event_result
        if self.review_policy_version in REVIEW_POLICY_VERSIONS:
            if name.startswith("writer_check"):
                legacy_validator = validator
                def checked_review(value):
                    legacy_validator(value)
                    validate_review(value, payload)
                validator = checked_review
            elif name.startswith("director_shots"):
                shot_validator = validator
                def checked_story(value):
                    shot_validator(value)
                    if value.get("story_issues"):
                        validate_review({"story_preserved": False, "issues": value["story_issues"],
                                         "suggestions": [], "calibration_focus": []}, payload)
                validator = checked_story
        if self.review_policy_version in (REVIEW_V3, REVIEW_V4, REVIEW_V5, REVIEW_V6) and name.startswith(("script_review", "writer_check")):
            base_review_validator = validator
            def check_coverage(value):
                if self.review_policy_version == REVIEW_V6 and payload.get("review_evidence_interface_version") == "evidence_ids_v1":
                    from .creative_review_evidence_ids import expand_review_ids
                    effective, _ = expand_review_ids(value, payload)
                    validate_review_v6(effective, payload)
                    base_review_validator(effective)
                    return
                if self.review_policy_version == REVIEW_V6 and payload.get("review_evidence_interface_version") == "leaf_catalog_v1":
                    # Aggregate reference errors before a base validator stops at its first bad ref.
                    validate_review_v6(value, payload)
                    base_review_validator(value)
                    return
                base_review_validator(value)
                if self.review_policy_version == REVIEW_V6:
                    validate_review_v6(value, payload)
                elif self.review_policy_version == REVIEW_V5:
                    validate_review_v5(value, payload)
                elif self.review_policy_version == REVIEW_V4:
                    validate_review_v4(value, payload)
                else:
                    validate_v3_review(value, payload)
            validator = check_coverage
        input_hash = _hash(payload)
        structured_schema = (
            WRITER_TOOL_SCHEMAS.get(name.split("__", 1)[0]) if role == "writer" else None
        )
        if name.startswith("writer_revise") and self._script_revision_mode() != "full_script" and structured_schema and payload.get("affected_beat_ids"):
            structured_schema = _writer_revision_schema(payload["affected_beat_ids"])
        if name.startswith("director_state_plan"):
            from .creative_state_plan_v6 import build_state_plan_prompt
            prompt = build_state_plan_prompt(payload)
        else:
            prompt = (build_static_manifest_prompt(payload) if name == "static_visual_manifest"
                      else PROMPTS[name.split("__", 1)[0]])
        if name.startswith("script_review"):
            prompt = review_prompt(self.review_policy_version)
        if original_directing:
            prompt = original_director_binding["prompt"]
        elif revision_binding:
            prompt = revision_binding["prompt"]
        if self.model_profile == CREATE_REVIEW_PROFILE:
            if name.startswith("writer_check"):
                prompt = prompt.replace(
                    "你是 MiniMax 编剧，核对 DeepSeek 导演稿",
                    "你是 DeepSeek 独立审查员，核对 MiniMax 创作稿",
                ).replace("你是现有编剧角色的交叉回核，不是独立第三审核模型。",
                          "你只审查和提出可定位问题，不代写或改写创作正文。")
                prompt += ("\n同时审查production_design（如提供）：首帧是否仅为start_state静态投影、"
                           "资产复用是否匹配目录、对白模式与构图是否一致、道具及动作时序是否连续。"
                           "资产与首帧问题归director并定位到镜号；不可凭自评分宣称媒体通过。"
                           "同一说话人的一句对白按标点跨镜且逐字衔接是合法表达，不能仅因跨镜判major。"
                           "画外角色发声或动作说明提及该角色，不等于角色必须入画；须有明确相反构图才判冲突。"
                           "首帧可以定格正在持续的动作，不能仅因正在作画就强改为尚未落笔；"
                           "只检查首态已完成的动作是否被镜内重新执行。没有实际媒体不能断言口型失败。")
            elif not name.startswith("script_review"):
                prompt = prompt.replace("DeepSeek", "MiniMax")
        if event_authoring:
            prompt = event_binding["prompt"]
            prompt += "\ncreative_brief为用户创作要求，优先于导演brief。只返回events事件版完整稿，不返回before/during/after或补丁。"
            if name.startswith("writer_revise"):
                if self._script_revision_mode() != "full_script":
                    prompt += "\n按issues修复affected_beat_ids，其他拍逐字保留原稿；previous_script是旧接口格式，按其真实播放顺序转换成events。"
            structured_schema = deepcopy(EVENT_SCHEMA)
        priority_binding = self.state.get("original_brief_priority_binding")
        if event_binding and priority_binding and name.startswith(("writer_analysis", "director_brief", "writer_director_feedback", "writer_script", "writer_revise")):
            prompt += "\n" + priority_binding["prompt"]
        if event_binding and priority_binding and not original_directing and name.startswith("director_shots") and priority_binding.get("director_execution_prompt"):
            prompt += "\n" + priority_binding["director_execution_prompt"]
        if event_authoring and name.startswith("writer_revise") and self._script_revision_mode() != "full_script":
            previous_beats = payload.get("previous_script", {}).get("beats", [])
            locked_ids = [b["id"] for b in previous_beats]
            prompt += "\n事件返修必须保持现有节拍ID、顺序和总拍数；不得重排编号、合并或拆拍。仅修改affected_beat_ids中的完整事件，其余实际动作/对白及各拍秒数与previous_script一致。每拍dialogue最多两条，不为旧样例凑第三条；如果完整稿概括与正文冲突，以实际正文为准。返回完整事件JSON。"
            structured_schema = deepcopy(structured_schema)
            structured_schema["properties"]["beats"].update(minItems=len(locked_ids), maxItems=len(locked_ids))
            beat_schema = structured_schema["properties"]["beats"]["items"]
            beat_schema["properties"]["id"]["enum"] = locked_ids
            beat_schema["properties"]["events"].update(minItems=1,
                contains={"type":"object","properties":{"kind":{"const":"dialogue"}},"required":["kind"]},
                minContains=0,maxContains=2)
        if event_authoring and name.startswith("writer_revise") and self._script_revision_mode() == "full_script":
            prompt += "\n" + self.state["script_revision_binding"]["prompt"]
            structured_schema["properties"]["beats"]["items"]["properties"]["events"]["minItems"] = 1
        if event_authoring and payload.get("allow_summary_update") is True and self._script_revision_mode() != "full_script":
            prompt += "\n本次授权同步修订根字段 premise，使其准确概括合并后的完整剧本；不得保留已删除动作或道具。title 和 selected_candidate_id 不变，未授权节拍正文逐字保留。"
        if event_binding and name.startswith("writer_check"):
            prompt += "\n必须逐条核对creative_brief的转折、结尾行动主体、禁用物和线索出现时间。只有实际动作/对白算演出，event和trigger是摘要。不要将优点、无矛盾内容或正常省略走路列为问题；每个问题引用原字段实词。"
        if self.review_policy_version in REVIEW_POLICY_VERSIONS:
            if name.startswith("writer_check"):
                prompt += review_rules(self.review_policy_version)
            elif name.startswith("director_shots"):
                prompt += "\n若返回story_issues，每项同样必须符合以下issues证据要求；正常分镜返回格式不变。" + review_rules(self.review_policy_version)
        if self.review_policy_version in (REVIEW_V3, REVIEW_V4, REVIEW_V5, REVIEW_V6) and name.startswith(("script_review", "writer_check")):
            # Replace, never append to the conflicting legacy six-field/scoring contract.
            prompt = (build_review_prompt_v6(payload) if self.review_policy_version == REVIEW_V6
                      else build_review_prompt_v5(payload) if self.review_policy_version == REVIEW_V5
                      else build_review_prompt_v4(payload) if self.review_policy_version == REVIEW_V4
                      else build_review_prompt(payload))
            structured_schema = None
        if name.startswith("director_shots") and payload.get("segment_instructions"):
            prompt += "\n" + payload["segment_instructions"]
        if recovery:
            prompt += "\n本阶段完整重新生成；previous_invalid_output仅用于定位旧错误，不是可继续合并的合格稿。" + recovery["requirements"]
        stage_thinking = "disabled"
        if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_state_plan_v2", "whole_film_state_plan_v3", "whole_film_action_plan_v1", "whole_film_action_plan_v2"):
            from .creative_state_plan_v6 import build_state_plan_schema
            structured_schema = build_state_plan_schema(payload)
            stage_thinking = payload.get("plan_thinking_mode", "adaptive")
        if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_action_plan_v1", "whole_film_action_plan_v2") and payload.get("plan_patch_base"):
            from .creative_plan_patch import build_patch_request, build_patch_schema
            prompt, _ = build_patch_request(structured_schema, payload, payload.get("issues", []), payload["plan_patch_base"])
            prompt += "\n本阶段原计划在plan_patch_base，source_sha256在请求根层；按issues修复。"
            structured_schema = build_patch_schema(payload["plan_patch_base"], target_schema=structured_schema)
        from .creative_narrative_focus import prompt_for_stage
        prompt += prompt_for_stage(self.state.get("narrative_focus_binding"), name)
        if structured_schema is not None:
            prompt += "\n请调用 submit_creative_json 工具提交上述完整 JSON，不要另写正文。"
        prompt_hash = _hash(prompt)
        if payload.get("debug_must_fix_feedback"):
            prompt += (
                "\n本次调用是用户明确登记的必修反馈返修。逐条处理 debug_must_fix_feedback，"
                "修订当前责任阶段产物；不得沿用旧产物，不得把反馈当作建议忽略。"
                "反馈修复通过本阶段原有 validator 后才可继续下游。"
            )
            prompt_hash = _hash(prompt)
        from .creative_stage_contracts import record_input, reconcile_cached_stage
        record_input(self, name, role, payload, prompt_hash, input_hash)
        reconcile_cached_stage(self, name, input_hash, prompt_hash)
        max_tokens = 20000 if role == "director" else 12000
        temperature = 0.2 if event_authoring else (0.1 if name in ("writer_script", "writer_screenplay") else 0.4)
        if self.review_policy_version in REVIEW_POLICY_VERSIONS and name.startswith(("script_review", "writer_check")):
            temperature = 0.2
        if path.exists():
            record = _read(path)
            if record.get("prompt_sha256") not in (None, prompt_hash):
                raise RuntimeError(f"{name} 提示词版本已改变，不能复用旧阶段回执")
            if record.get("status") != "validated":
                self._accept_response(path, record, require_tool=structured_schema is not None)
            if record is not None:
                if record.get("input_sha256") != input_hash or record.get("role") != role:
                    if name.startswith((
                        "director_shots", "director_revise", "writer_check", "writer_revise",
                    )):
                        archive = self.run_dir / f"{name}__stale_parent_01.json"
                        if archive.exists() or path.resolve().parent != self.run_dir.resolve():
                            raise RuntimeError(f"{name} 旧父稿归档路径冲突")
                        record["invalidated_by_input_sha256"] = input_hash
                        _write(path, record)
                        path.replace(archive)
                        record = None
                    else:
                        raise RuntimeError(f"{name} 已有记录与当前父稿不一致，拒绝复用")
            if record is not None:
                if record.get("status") == "response_received":
                    output = self._decode(name, role, record["response_text"])
                    output = self._unwrap_director_envelope(name, output)
                    output = self._unwrap_writer_revise_envelope(name, output)
                    if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_action_plan_v1", "whole_film_action_plan_v2") and payload.get("plan_patch_base"):
                        output = self._merge_action_plan_patch(name, payload["plan_patch_base"], output, target_schema=build_state_plan_schema(payload))
                    if event_authoring:
                        record["event_output"] = deepcopy(output)
                        try:
                            output = compile_event_script(output)
                        except CreativeContractError as event_error:
                            record["event_compilation_error"] = str(event_error)
                            from .creative_event_recovery import repair_event_contract
                            output = repair_event_contract(self, name, role, payload, output, event_error, validator)
                        if name.startswith("writer_revise"):
                            output["screenplay_markdown"] = compile_beat_screenplay(output)
                    output = self._validate_or_repair(name, role, payload, output, validator)
                    record["output"] = output
                    record["output_sha256"] = _hash(output)
                    record["status"] = "validated"
                    _write(path, record)
                    if not any(row["name"] == name
                               and row.get("input_sha256") == input_hash
                               and row.get("output_sha256") == record["output_sha256"]
                               for row in self.state["stages"]):
                        self.state["stages"].append({
                            "name": name, "role": role,
                            "input_sha256": input_hash,
                            "output_sha256": record["output_sha256"],
                            "context_budget": record.get("context_budget"),
                            "usage": record["response_metadata"],
                        })
                        self._save()
                    return output
                if record.get("status") != "validated":
                    raise RuntimeError(f"{name} 上次调用状态未确认，请核对回执后再恢复")
                output = record["output"]
                if _hash(output) != record.get("output_sha256"):
                    raise RuntimeError(f"{name} 已存产物被改动")
                corrected = self._validate_or_repair(name, role, payload, output, validator)
                if _hash(corrected) != record["output_sha256"]:
                    record.setdefault("superseded_outputs", []).append({
                        "output_sha256": record["output_sha256"],
                        "output": output,
                        "reason": "revalidated_against_current_contract",
                    })
                    record["output"] = corrected
                    record["output_sha256"] = _hash(corrected)
                    _write(path, record)
                    previous = next(row for row in reversed(self.state["stages"]) if row["name"] == name)
                    self.state["stages"].append({**previous,
                        "output_sha256": record["output_sha256"], "contract_repaired": True})
                    self._save()
                return corrected
        if self.state["calls_started"] >= self.max_calls:
            raise RuntimeError("模型调用预算已满；保存进度，未跳过检查")
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        from .creative_execution_control import check_dispatch
        check_dispatch(self, name)
        context_budget = self._reserve_tokens(role, messages, max_tokens=max_tokens)
        record = {
            "schema": "creative_stage/v1",
            "status": "pending_response",
            "stage": name,
            "role": role,
            "input_sha256": input_hash,
            "prompt_sha256": prompt_hash,
            "context_budget": context_budget,
            "request": {"messages": messages, "message_sha256": _hash(messages),
                        "tool_schema_sha256": _hash(structured_schema) if structured_schema else None,
                        "parameters": {"max_completion_tokens" if self._transport_role(role) == "writer" else "max_tokens": max_tokens,
                                       "temperature": temperature,
                                       "thinking": stage_thinking}},
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _write(path, record)
        self.state["calls_started"] += 1
        self._save()
        try:
            result: RoleResult = self._call_model(
                role, messages, max_tokens=max_tokens,
                temperature=temperature,
                thinking=stage_thinking,
                structured_schema=structured_schema,
            )
        except Exception as exc:
            self._record_response_exception(path, record, exc)
            raise
        record["response_text"] = result.text
        record["response_metadata"] = result.metadata
        record["status"] = "response_received"
        _write(path, record)
        self._accept_response(path, record, require_tool=structured_schema is not None)
        output = self._decode(name, role, result.text)
        output = self._unwrap_director_envelope(name, output)
        output = self._unwrap_writer_revise_envelope(name, output)
        if name.startswith("director_state_plan") and payload.get("state_plan_version") in ("whole_film_action_plan_v1", "whole_film_action_plan_v2") and payload.get("plan_patch_base"):
            output = self._merge_action_plan_patch(name, payload["plan_patch_base"], output, target_schema=build_state_plan_schema(payload))
        if event_authoring:
            record["event_output"] = deepcopy(output)
            try:
                output = compile_event_script(output)
            except CreativeContractError as event_error:
                record["event_compilation_error"] = str(event_error)
                from .creative_event_recovery import repair_event_contract
                output = repair_event_contract(self, name, role, payload, output, event_error, validator)
            if name.startswith("writer_revise"):
                output["screenplay_markdown"] = compile_beat_screenplay(output)
        output = self._validate_or_repair(name, role, payload, output, validator)
        record["output"] = output
        record["output_sha256"] = _hash(output)
        record["status"] = "validated"
        _write(path, record)
        self.state["stages"].append({
            "name": name,
            "role": role,
            "input_sha256": input_hash,
            "output_sha256": record["output_sha256"],
            "context_budget": context_budget,
            "usage": result.metadata,
        })
        self._save()
        return output

    def _write_context_receipt(
        self, bundle: MaterialBundle, payload: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = deepcopy(self.state["context_strategy"])
        mode = strategy["mode"]
        receipt = {
            "schema": "creative_context_strategy/v1",
            "material_sha256": self.state["material_sha256"],
            "source_driver": bundle.source_driver,
            "strategy": strategy,
            "direct_context_limit_characters": self.direct_context_chars,
            "final_payload_serialized_characters": len(_canonical(payload)),
            "final_payload_sha256": _hash(payload),
            "planning_estimation": (
                "序列化 Unicode 字符数按一字符一 token 作保守输入估算；"
                "这不是供应商 tokenizer 结果，响应 usage 才是实际用量"
            ),
            "role_context_capabilities": {
                **{role: role_context_capability("writer" if self.model_profile == CREATE_REVIEW_PROFILE else role) for role in ("writer", "director")},
                **({"reviewer": role_context_capability("director")} if self.model_profile == CREATE_REVIEW_PROFILE else {}),
            },
            "source_delivery": (
                "full_source_text"
                if mode == "full"
                else "all_source_chunks_summarized_then_selected_raw_excerpt_reloaded"
            ),
            "reference_delivery": (
                "full_reference_text"
                if mode == "full" or not bundle.references
                else "all_reference_chunks_summarized_for_expression_only"
            ),
            "not_sent_verbatim_to_initial_analysis": (
                [] if mode == "full" else [
                    {
                        "material": "story_source",
                        "reason": "完整原文已逐块读取；初始全局分析发送完整分块摘要，选中后重新载入逐字原文",
                    },
                    *([{
                        "material": "reference_pack",
                        "reason": "参考材料已逐块读取；初始分析只发送表达机制摘要",
                    }] if bundle.references and strategy.get("reference_chunks") else []),
                ]
            ),
            "unread_or_unverified": list(bundle.manifest.get("unread_or_unverified", [])),
        }
        path = self.run_dir / "CONTEXT_STRATEGY.json"
        if path.exists() and _read(path) != receipt:
            raise RuntimeError("上下文策略回执与当前材料或阈值不一致")
        _write(path, receipt)
        return receipt

    def _context(self, bundle: MaterialBundle) -> dict[str, Any]:
        payload = bundle.input_payload()
        if self.creative_focus:
            payload["creative_focus"] = self.creative_focus
        if len(_canonical(payload)) <= self.direct_context_chars:
            self.state["context_strategy"] = {
                "mode": "full",
                "direct_context_limit_characters": self.direct_context_chars,
                "initial_payload_serialized_characters": len(_canonical(payload)),
                "source_sha256": _hash(bundle.source_text),
                "reference_sha256": _hash(list(bundle.references)),
                "sent_payload_sha256": _hash(payload),
            }
            self._save()
            self._write_context_receipt(bundle, payload)
            return payload
        source_chunks = (
            _chunks(bundle.source_text, max(1000, self.direct_context_chars // 2))
            if len(bundle.source_text) > self.direct_context_chars // 2 else []
        )
        if len(source_chunks) + 6 > self.max_calls - self.state["calls_started"]:
            raise RuntimeError("分层阅读与必需的双角色检查预算不足")
        self.state["context_strategy"] = {
            "mode": "hierarchical",
            "direct_context_limit_characters": self.direct_context_chars,
            "initial_payload_serialized_characters": len(_canonical(payload)),
            "source_sha256": _hash(bundle.source_text),
            "reference_sha256": _hash(list(bundle.references)),
            "source_chunks": len(source_chunks),
            "source_chunk_sha256": [_hash(chunk) for chunk in source_chunks],
            "reference_chunks": 0,
            "reference_chunk_sha256": [],
        }
        self._save()
        if source_chunks:
            summaries = []
            for index, chunk in enumerate(source_chunks, 1):
                summary = self._stage(
                    f"source_summary__{index:03}", "writer",
                    {"source_chunk": chunk, "chunk_number": index, "chunk_count": len(source_chunks)},
                    lambda value, text=chunk: validate_summary(value, text),
                )
                summaries.append(summary)
            payload["story_source"] = {
                "mode": "hierarchical_complete_summary",
                "source_sha256": _hash(bundle.source_text),
                "summaries": summaries,
                "limitation": "全文由分层摘要覆盖；原文逐字引文将在后续程序用完整来源核验",
            }
        if len(_canonical(payload)) > self.direct_context_chars and bundle.references:
            reference_chunks = []
            for reference in bundle.references:
                for index, chunk in enumerate(_chunks(reference["text"], max(1000, self.direct_context_chars // 2)), 1):
                    reference_chunks.append((reference["id"], index, chunk))
            if len(reference_chunks) + 6 > self.max_calls - self.state["calls_started"]:
                raise RuntimeError("参考分层阅读与必需的双角色检查预算不足")
            self.state["context_strategy"]["reference_chunks"] = len(reference_chunks)
            self.state["context_strategy"]["reference_chunk_sha256"] = [_hash(row[2]) for row in reference_chunks]
            self._save()
            compressed: dict[str, list[Any]] = {}
            for ref_id, index, chunk in reference_chunks:
                summary = self._stage(
                    f"reference_summary__{ref_id}_{index:03}", "writer",
                    {"reference_id": ref_id, "reference_chunk": chunk},
                    validate_reference_summary,
                )
                compressed.setdefault(ref_id, []).append(summary)
            payload["reference_pack"] = [
                {"id": ref_id, "mode": "expression_only_summary", "summaries": rows}
                for ref_id, rows in compressed.items()
            ]
        if len(_canonical(payload)) > self.direct_context_chars:
            raise RuntimeError("分层摘要后仍超出上下文阈值，未截断材料")
        self.state["context_strategy"]["sent_payload_sha256"] = _hash(payload)
        self.state["context_strategy"]["final_payload_serialized_characters"] = len(
            _canonical(payload)
        )
        self._save()
        self._write_context_receipt(bundle, payload)
        return payload

    def _verified_review(self, key: str, review: dict, context: dict) -> list | None:
        """Persist one immutable review packet; only assistant decisions unlock repairs."""
        from .creative_narrative_transfer import enrich_review_context
        context = enrich_review_context(self.state.get("narrative_focus_binding"), key, context)
        from .creative_reference_expression import enrich_reference_context
        context = enrich_reference_context(self.state.get("reference_expression_binding"), key, context)
        from .creative_stage_debug import replayable_resolved_stage_feedback
        repair_context = replayable_resolved_stage_feedback(self.run_dir, self.state, key)
        if repair_context:
            context = {**context, "debug_must_fix_feedback": repair_context}
        from .creative_focused_review_stage import enabled as focused_enabled, verify_expansion
        if focused_enabled(self, key, context):
            verify_expansion(self, key, review, context)
        elif self.state.get("review_evidence_interface_version") == "evidence_ids_v1":
            from .creative_review_evidence_ids import expand_review_ids
            raw_stage = _read(self.run_dir / f"{key}.json")
            effective, expansion = expand_review_ids(raw_stage["output"], context)
            if effective != review or _read(self.run_dir / f"{key}__evidence_ids_expansion.json") != expansion:
                raise RuntimeError("审核证据ID展开稿与原模型产物/当前上下文不一致")
        packet = make_packet(key, review, context)
        packet_path = self.run_dir / f"{key}__review_packet.json"
        if packet_path.exists() and _read(packet_path) != packet:
            raise RuntimeError("审核包父版本已改变")
        _write(packet_path, packet)
        decision_path = self.run_dir / f"{key}__assistant_decision.json"
        if not decision_path.exists():
            _write(self.run_dir / f"{key}__decision_template.json", review_decision_template(packet))
            self.state["status"] = "script_review_pending"
            self.state["pending_evidence_review"] = {"key": key, "packet": packet_path.name,
                "packet_sha256": review_digest(packet), "decision": decision_path.name}
            self._save()
            return None
        decision = _read(decision_path)
        issues = confirmed_issues(packet, decision)
        bound = self.state.setdefault("evidence_review_decisions", {})
        binding = {"packet_sha256": review_digest(packet), "decision_sha256": review_digest(decision)}
        if key in bound and bound[key] != binding:
            raise RuntimeError("已使用的助手核实回执不能修改")
        bound[key] = binding
        _write(self.run_dir / f"{key}__confirmed_issues.json", {
            **binding, "issues": issues, "suggestions": review["suggestions"],
            "automatic_media_submit": False})
        if self.state.get("pending_evidence_review", {}).get("key") == key:
            self.state.pop("pending_evidence_review", None)
        self._save()
        return issues

    def _review_script_before_directing(self, script, *, key, bundle, candidate,
                                        selected_excerpt, excerpt_record, analysis, brief,
                                        context_ref):
        if self.review_policy_version not in REVIEW_POLICY_VERSIONS:
            return script
        for index in range(self.max_revisions + 1):
            name = f"script_review__{key}_{index:02}"
            context = {"creative_brief": self.state["writer_prompt_binding"]["creative_brief"],
                       "script": script, "candidate_lock": candidate,
                       "selected_source": excerpt_record}
            def validate_script_review(value):
                validate_review(value, context)
                if any(i["owner"] != "writer" for i in value["issues"]):
                    raise CreativeContractError("剧本预审问题必须归writer")
            review = self._stage(name, "director", context, validate_script_review)
            issues = self._verified_review(name, review, context)
            if issues is None:
                return None
            if any(i["owner"] != "writer" for i in issues):
                raise CreativeContractError("剧本预审核实问题必须归writer")
            if not issues:
                return script
            round_key = f"{name}_revision"
            committed = self.state.setdefault("revision_committed", [])
            if index >= self.max_revisions or (round_key not in committed
                    and self.state["revision_rounds"] >= self.max_revisions):
                self.state.update(status="needs_revision", unresolved_issues=issues)
                _write(self.run_dir / "SCRIPT_REVIEW_UNRESOLVED.json", {
                    "script": script, "issues": issues, "review": review,
                    "automatic_media_submit": False})
                self._save()
                return None
            stage = f"writer_revise__preflight_{key}_{index + 1:02}"
            # Replay committed cached stages without consuming or reserving a new round.
            if round_key not in committed:
                if self.state["calls_started"] + 2 > self.max_calls:
                    raise RuntimeError("剧本返修和复审预算不足")
                committed.append(round_key)
                self.state["revision_rounds"] += 1
                self._save()
            affected = _issue_beat_ids(script, issues)
            previous = script
            allow_summary_update = stage_summary_update_allowed(
                self.run_dir / f"{stage}.json", eligible=bool(
                    bundle.source_driver == "original" and self.state.get("writer_prompt_binding")))
            revised = self._stage(stage, "writer", {
                **({"allow_summary_update": True} if allow_summary_update else {}),
                "material_ref": context_ref, "selected_source": excerpt_record,
                "analysis": analysis, "brief": brief, "candidate_lock": candidate,
                "previous_script": previous, "affected_beat_ids": affected, "issues": issues},
                lambda value: _validate_writer_revision_result(value, previous, affected,
                    candidate, selected_excerpt, bundle.source_driver, self.creative_focus, revision_mode=self._script_revision_mode()))
            script = _writer_revision_result(previous, revised, affected, allow_summary_update=allow_summary_update, revision_mode=self._script_revision_mode())
        raise RuntimeError("剧本审核轮次耗尽")

    def run(self, *args, **kwargs):
        """One dispatcher owns this task's stage receipts and budgets at a time."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        lock = self.run_dir / '.creative_execution.lock'
        try:
            with lock.open('x', encoding='utf-8') as stream:
                json.dump({'scope': 'creative_text_dispatch', 'automatic_unlock_after_crash': False}, stream)
        except FileExistsError:
            raise RuntimeError('任务执行锁已存在：先核对在途调用和回执，不重复派发') from None
        try:
            return self._run_unlocked(*args, **kwargs)
        finally:
            lock.unlink()

    def _run_unlocked(self, bundle: MaterialBundle) -> dict[str, Any]:
        self._reusable_generation = bool(bundle.metadata.get("creative_brief"))
        if self.writer_prompt_version == EVENT_WRITER_VERSION and (
                bundle.source_driver != "original" or not bundle.metadata.get("creative_brief")
                or self.model_profile != CREATE_REVIEW_PROFILE):
            raise ValueError("事件编剧模块仅用于有简报的MiniMax创作/DeepSeek审查原创任务")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            self.state = _read(self.state_path)
            if self.state.get("model_profile", LEGACY_MODEL_PROFILE) != self.model_profile:
                raise RuntimeError("恢复任务不能更换已绑定的模型分工")
            existing_policy = self.state.get("budget_policy_version", "v1_20260922")
            if existing_policy != self.budget_policy_version:
                raise RuntimeError("恢复任务不能改变创作预算版本")
            if self.state.get("material_sha256") != _hash(bundle.manifest):
                raise RuntimeError("恢复任务的材料版本不一致")
            if self.state.get("creative_focus", "") != self.creative_focus:
                raise RuntimeError("恢复任务的创作焦点不一致")
            if self.logical_task_id is not None and self.state.get("logical_task_id") != self.logical_task_id:
                raise RuntimeError("恢复任务的逻辑任务身份不一致")
            if self.state.get("max_calls") != self.max_calls or self.state.get("max_revisions") != self.max_revisions:
                raise RuntimeError("恢复任务不能悄悄改变预算")
            if self._split_repair_budget() and self.state.get("max_contract_repairs") != self.max_contract_repairs:
                raise RuntimeError("恢复任务不能改变格式与契约修复预算")
            if "max_total_tokens" not in self.state:
                self.state["max_total_tokens"] = self.max_total_tokens
                self._save()
            elif self.state["max_total_tokens"] != self.max_total_tokens:
                raise RuntimeError("恢复任务不能悄悄改变文本 token 预算")
            if self.state.get("status") == "debug_breakpoint":
                breakpoint = self.state.pop("debug_breakpoint", None)
                if breakpoint:
                    history = self.state.setdefault("debug_breakpoint_history", [])
                    if breakpoint not in history:
                        history.append(breakpoint)
                self.state["status"] = "debug_resuming"
                self._save()
        else:
            if any(path.name != '.creative_execution.lock' for path in self.run_dir.iterdir()):
                raise RuntimeError("运行目录已有其他文件")
            calibration = calibration_status(self.run_dir.parent)
            current_input_profile = material_input_profile_sha256(bundle.manifest)
            calibrated_inputs = calibration.get("calibrated_input_profile_sha256")
            unseen_input_profile = bool(
                calibration["stop_per_draft_assistant_review"]
                and isinstance(calibrated_inputs, list)
                and current_input_profile not in calibrated_inputs
            )
            assistant_review_required = (
                not calibration["stop_per_draft_assistant_review"] or unseen_input_profile
            )
            if self.model_profile == CREATE_REVIEW_PROFILE:
                assistant_review_required = True
            from .creative_narrative_focus import bind_narrative_focus
            from .creative_full_script_revision import bind_full_script_revision
            self.state = {
                "narrative_focus_binding": (bind_narrative_focus() if bundle.source_driver == "original" else None),
                "reference_expression_version": ("reference_expression_v1" if bundle.source_driver == "original" and bundle.references else None),
                "script_revision_binding": (bind_full_script_revision() if bundle.source_driver == "original" and self.writer_prompt_version == EVENT_WRITER_VERSION else None),
                "schema": "creative_workflow_state/v1",
                "model_profile": self.model_profile,
                "writer_prompt_version": self.writer_prompt_version,
                "review_policy_version": self.review_policy_version,
                "production_protocol": self.production_protocol,
                **({"review_packet_version": "focused_review_packet_v1"}
                   if self.production_protocol == "governed_production_v1" else {}),
                **({"review_evidence_interface_version": "evidence_ids_v1"} if self.review_policy_version == REVIEW_V6 else {}),
                **({"evidence_id_repair_hints_version": "missing_source_candidates_v1"} if self.review_policy_version == REVIEW_V6 else {}),
                "segmented_director_binding": (bind_segmented_director(authoritative=self.review_policy_version in (REVIEW_V4, REVIEW_V5, REVIEW_V6),
                    static_visual=self.review_policy_version in (REVIEW_V5, REVIEW_V6),
                    state_plan=self.review_policy_version == REVIEW_V6,
                    state_plan_version=("whole_film_action_plan_v2" if self.production_protocol == "governed_production_v1"
                                        else "whole_film_action_plan_v1"), plan_thinking_mode="disabled")
                    if self.review_policy_version in (REVIEW_V3, REVIEW_V4, REVIEW_V5, REVIEW_V6) and bundle.source_driver == "original" else None),
                "original_director_binding": (bind_original_director()
                    if self.writer_prompt_version == EVENT_WRITER_VERSION and bundle.source_driver == "original" else None),
                "original_brief_priority_binding": (bind_brief_priority()
                    if self.writer_prompt_version == EVENT_WRITER_VERSION and bundle.source_driver == "original" else None),
                "writer_prompt_binding": (bind_original_prompt(bundle.metadata["creative_brief"])
                                          if self.writer_prompt_version == EVENT_WRITER_VERSION else None),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "materials_bound",
                "source_driver": bundle.source_driver,
                "creative_focus": self.creative_focus,
                "logical_task_id": self.logical_task_id,
                "material_sha256": _hash(bundle.manifest),
                "calls_started": 0,
                "max_calls": self.max_calls,
                "max_total_tokens": self.max_total_tokens,
                "max_revisions": self.max_revisions,
                "budget_policy_version": self.budget_policy_version,
                "max_contract_repairs": self.max_contract_repairs if self.budget_policy_version != "v1_20260922" else None,
                "contract_repairs_used": 0,
                "format_repairs_used": 0,
                "revision_rounds": 0,
                "revision_committed": [],
                "stages": [],
                "assistant_review_required": assistant_review_required,
                "calibration_milestone_at_start": calibration["calibration_milestone"],
                "workflow_profile_sha256": calibration.get(
                    "current_workflow_profile_sha256"
                ),
                "input_profile_sha256": current_input_profile,
                "calibrated_style_classes_at_start": calibration.get(
                    "calibrated_style_classes"
                ),
                "review_reopen_reasons": (
                    ["unseen_input_profile"] if unseen_input_profile else []
                ),
                "text_pass_sequence": 0,
                "video_pass_sequence": 0,
            }
            if self.production_protocol == "governed_production_v1":
                from .creative_governed_runtime import bind_new_task
                self.state["rule_registry_binding"] = bind_new_task()
            _write(self.run_dir / "materials.json", bundle.manifest)
            self._save()
        from .creative_governed_runtime import verify_rules
        verify_rules(self)
        verify_manifest(bundle.manifest)
        if _read(self.run_dir / "materials.json") != bundle.manifest:
            raise RuntimeError("材料清单与运行目录不一致")
        # Recover accepted commands even when a previously completed task would return early.
        self._save()
        if self.state.get("command_integrity_errors"):
            self.state.update(status="needs_attention", last_error="resolved feedback replay binding changed: feedback command integrity check failed")
            self._save()
            raise RuntimeError("resolved feedback replay binding changed: feedback command integrity check failed")
        if self.state.get("status") == "reviewed_revision_media_handoff_pending_capability":
            review = validated_revision_review(self.run_dir, self.state)
            if review is None or review.get("outcome") != "passed":
                raise RuntimeError("返修交接缺少实际助手通过记录")
            handoff = _read(self.run_dir / "ASSISTANT_REVISED_MEDIA_HANDOFF.json")
            if (_hash(handoff) != self.state.get("revised_handoff_sha256")
                    or handoff.get("automatic_submit") is not False
                    or handoff.get("assistant_revision_review_sha256")
                    != self.state.get("assistant_revision_review_sha256")):
                raise RuntimeError("返修媒体交接包版本不符")
            bound_outputs = [
                ("ASSISTANT_REVISED_ANALYSIS.json", "analysis_sha256"),
                ("ASSISTANT_REVISED_DIRECTOR_BRIEF.json", "brief_sha256"),
                ("ASSISTANT_REVISED_SCREENPLAY.json", "script_sha256"),
                ("ASSISTANT_REVISED_STORYBOARD.json", "shots_sha256"),
                ("ASSISTANT_REVISED_EXECUTION_DRAFT.json", "execution_draft_sha256"),
                ("ASSISTANT_REVISED_MEDIA_CAPABILITY_AUDIT.json", "capability_audit_sha256"),
                ("ASSISTANT_REVISED_EDITORIAL_REVIEW_PACKET.json", "review_packet_sha256"),
            ]
            if "segment_plan_sha256" in handoff:
                bound_outputs.append(
                    ("ASSISTANT_REVISED_SEEDANCE_SEGMENT_PLAN.json", "segment_plan_sha256")
                )
            if "selected_source_sha256" in handoff:
                bound_outputs.append(
                    ("ASSISTANT_REVISED_SELECTED_SOURCE.json", "selected_source_sha256")
                )
            for filename, key in bound_outputs:
                if _hash(_read(self.run_dir / filename)) != handoff[key]:
                    raise RuntimeError(f"返修交接的 {filename} 版本不符")
            current_capability = audit_creative_executor(
                _read(self.run_dir / "ASSISTANT_REVISED_STORYBOARD.json")
            )
            if (current_capability["provider"], current_capability["model"]) != (
                handoff["media_provider"], handoff["media_model"]
            ):
                raise RuntimeError("返修交接的媒体执行器型号已改变")
            if "segment_plan_sha256" in handoff:
                validate_seedance_segment_plan(
                    _read(self.run_dir / "ASSISTANT_REVISED_SEEDANCE_SEGMENT_PLAN.json"),
                    _read(self.run_dir / "ASSISTANT_REVISED_SCREENPLAY.json"),
                    _read(self.run_dir / "ASSISTANT_REVISED_STORYBOARD.json"),
                    _read(self.run_dir / "ASSISTANT_REVISED_MEDIA_CAPABILITY_AUDIT.json"),
                )
            if self.state.get("revised_output_manifest_sha256") is not None:
                self._validate_output_manifest(
                    handoff=handoff,
                    filename="ASSISTANT_REVISED_CREATIVE_OUTPUT_MANIFEST.json",
                    state_hash_key="revised_output_manifest_sha256",
                )
            return self.state
        if self.state.get("status") == "needs_revision" and self.state.get("assistant_review_outcome") == "major_issues":
            review = validated_assistant_review(self.run_dir, self.state)
            if review is None or review.get("outcome") != "major_issues":
                raise RuntimeError("助手问题稿缺少有效绑定复核记录")
            return self.state
        if self.state.get("status") == "media_handoff_pending_capability":
            handoff = _read(self.run_dir / "MEDIA_HANDOFF.json")
            if _hash(handoff) != self.state.get("handoff_sha256") or handoff.get("automatic_submit") is not False:
                raise RuntimeError("媒体交接包被改动")
            script = _read(self.run_dir / "SCREENPLAY.json")
            shots = _read(self.run_dir / "STORYBOARD.json")
            if _hash(script) != handoff["script_sha256"] or _hash(shots) != handoff["shots_sha256"]:
                raise RuntimeError("媒体交接包绑定的文本版本已改变")
            if self.state.get("production_protocol") == "governed_production_v1":
                from .creative_governed_runtime import focused_artifacts
                focused_artifacts(self)
                from .creative_state_plan_binding import bind_reviewed_state_plan
                _, plan_hash = bind_reviewed_state_plan(self, script, shots)
                if plan_hash != handoff.get("state_plan_sha256"):
                    raise RuntimeError("恢复交接的已审动作计划绑定改变")
            draft = _read(self.run_dir / "EXECUTION_DRAFT.json")
            if _hash(draft) != handoff["execution_draft_sha256"] or draft != _execution_draft(script, shots):
                raise RuntimeError("执行预稿与已审核剧本或分镜不一致")
            capability = _read(self.run_dir / "MEDIA_CAPABILITY_AUDIT.json")
            if _hash(capability) != handoff["capability_audit_sha256"]:
                raise RuntimeError("媒体执行能力审计已被改动")
            current_executor = audit_creative_executor(shots)
            if (capability["provider"], capability["model"]) != (
                current_executor["provider"], current_executor["model"]
            ):
                raise RuntimeError("所选媒体执行器或模型已改变，旧能力审计不能复用")
            if "segment_plan_sha256" in handoff:
                segment_plan = _read(self.run_dir / "SEEDANCE_SEGMENT_PLAN.json")
                if _hash(segment_plan) != handoff["segment_plan_sha256"]:
                    raise RuntimeError("Seedance 分段计划已被改动")
                try:
                    validate_seedance_segment_plan(segment_plan, script, shots, capability)
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
            packet = _read(self.run_dir / "EDITORIAL_REVIEW_PACKET.json")
            if _hash(packet) != handoff["review_packet_sha256"]:
                raise RuntimeError("集中复核包版本与媒体交接包不一致")
            if self.state.get("output_manifest_sha256") is not None:
                self._validate_output_manifest(handoff=handoff)
            review = validated_assistant_review(self.run_dir, self.state)
            if review is not None and review.get("outcome") == "major_issues":
                raise RuntimeError("助手已登记主要问题，媒体交接状态尚未同步")
            if "last_error" in self.state:
                self.state.pop("last_error")
                self._save()
            return self.state
        try:
            context = self._context(bundle)
            if self.state.get("reference_expression_version") == "reference_expression_v1":
                from .creative_reference_expression import bind_reference_expression
                binding = bind_reference_expression(context["reference_pack"])
                existing = self.state.get("reference_expression_binding")
                if existing is not None and existing != binding:
                    raise RuntimeError("参考表达绑定已改变，不能覆盖旧任务")
                self.state["reference_expression_binding"] = binding
                self._save()
            analysis = self._stage(
                "writer_analysis", "writer", context,
                lambda value: validate_analysis(value, bundle.source_text, bundle.source_driver),
            )
            candidate = validate_analysis(analysis, bundle.source_text, bundle.source_driver)
            if bundle.source_driver == "novel":
                start = bundle.source_text.index(candidate["start_quote"])
                end = bundle.source_text.index(candidate["end_quote"]) + len(candidate["end_quote"])
                start, end = _expand_direct_speech_bounds(bundle.source_text, start, end)
                selected_excerpt = bundle.source_text[start:end]
                excerpt_record = {
                    "candidate_id": candidate["id"],
                    "start_character": start,
                    "end_character": end,
                    "source_sha256": _hash(bundle.source_text),
                    "excerpt_sha256": _hash(selected_excerpt),
                    "text": selected_excerpt,
                }
            else:
                selected_excerpt = bundle.source_text
                excerpt_record = {"candidate_id": candidate["id"], "story_source": "原创简报驱动" if bundle.source_driver == "original" else "原创视频驱动"}
            brief = self._stage(
                "director_brief", "director", {"materials": context, "analysis": analysis,
                                                   "selected_source": excerpt_record},
                lambda value: _validate_director_brief_for_source(
                    value, bundle.source_text, bundle.source_driver, candidate,
                ),
            )
            style_class = style_class_for_brief(brief)
            self.state["style_class"] = style_class
            calibrated_styles = self.state.get("calibrated_style_classes_at_start")
            if (
                not self.state["assistant_review_required"]
                and isinstance(calibrated_styles, list)
                and style_class not in calibrated_styles
            ):
                self.state["assistant_review_required"] = True
                reasons = self.state.setdefault("review_reopen_reasons", [])
                if "unseen_style_class" not in reasons:
                    reasons.append("unseen_style_class")
            self._save()
            if bundle.source_driver == "novel":
                scope = brief.get("source_scope") or {}
                if not isinstance(scope, dict):
                    raise CreativeContractError("导演原文边界建议必须是对象")
                lead_quote = scope.get("lead_in_start_quote", "")
                trim_quote = scope.get("trim_start_quote", "")
                extend_quote = scope.get("extend_end_quote", "")
                trim_end_quote = scope.get("trim_end_quote", "")
                if lead_quote and trim_quote:
                    raise CreativeContractError("导演不能同时前移和收窄原文起点")
                if extend_quote and trim_end_quote:
                    raise CreativeContractError("导演不能同时延长和收窄原文终点")
                if lead_quote:
                    if not isinstance(lead_quote, str) or not isinstance(scope.get("reason"), str) or not scope["reason"].strip():
                        raise CreativeContractError("导演前移原文起点缺少逐字引文或理由")
                    canonical_quote, lead_start = _canonical_source_quote(
                        bundle.source_text, lead_quote, "director.source_scope.lead_in_start_quote",
                    )
                    lead_start, _ = _expand_direct_speech_bounds(
                        bundle.source_text, lead_start, lead_start + len(canonical_quote),
                    )
                    if (lead_start >= start
                            or start - lead_start > _DIRECTOR_SCOPE_WINDOW):
                        raise CreativeContractError(
                            f"导演建议的前置原文不在候选起点前 "
                            f"{_DIRECTOR_SCOPE_WINDOW} 字内"
                        )
                    if not _is_narrative_start_boundary(bundle.source_text, lead_start):
                        raise CreativeContractError(
                            "导演建议的前置原文起点落在句子或单词中间"
                        )
                    excerpt_record = {
                        **excerpt_record,
                        "candidate_start_character": start,
                        "start_character": lead_start,
                        "excerpt_sha256": _hash(bundle.source_text[lead_start:end]),
                        "text": bundle.source_text[lead_start:end],
                        "scope_adjustment": {
                            "source": "director_brief", "lead_in_start_quote": canonical_quote,
                            "reason": scope["reason"],
                        },
                    }
                    selected_excerpt = excerpt_record["text"]
                elif trim_quote:
                    if not isinstance(trim_quote, str) or not isinstance(scope.get("reason"), str) or not scope["reason"].strip():
                        raise CreativeContractError("导演收窄原文起点缺少逐字引文或理由")
                    canonical_quote, trimmed_start = _canonical_source_quote(
                        bundle.source_text, trim_quote, "director.source_scope.trim_start_quote",
                    )
                    trimmed_start, _ = _expand_direct_speech_bounds(
                        bundle.source_text, trimmed_start, trimmed_start + len(canonical_quote),
                    )
                    if trimmed_start <= start or trimmed_start >= end - len(candidate["end_quote"]):
                        raise CreativeContractError("导演建议的收窄起点不在候选原文内部")
                    excerpt_record = {
                        **excerpt_record,
                        "candidate_start_character": start,
                        "start_character": trimmed_start,
                        "excerpt_sha256": _hash(bundle.source_text[trimmed_start:end]),
                        "text": bundle.source_text[trimmed_start:end],
                        "scope_adjustment": {
                            "source": "director_brief", "trim_start_quote": canonical_quote,
                            "reason": scope["reason"],
                        },
                    }
                    selected_excerpt = excerpt_record["text"]
                if extend_quote:
                    if not isinstance(extend_quote, str) or not isinstance(scope.get("reason"), str) or not scope["reason"].strip():
                        raise CreativeContractError("导演延长原文终点缺少逐字引文或理由")
                    canonical_quote, extended_anchor = _canonical_source_quote(
                        bundle.source_text, extend_quote,
                        "director.source_scope.extend_end_quote",
                    )
                    _, extended_end = _expand_direct_speech_bounds(
                        bundle.source_text, extended_anchor,
                        extended_anchor + len(canonical_quote),
                    )
                    if (extended_anchor < end
                            or extended_end - end > _DIRECTOR_SCOPE_WINDOW):
                        raise CreativeContractError(
                            f"导演建议的新终点不在候选终点后 "
                            f"{_DIRECTOR_SCOPE_WINDOW} 字内"
                        )
                    current_start = excerpt_record["start_character"]
                    adjustment = dict(excerpt_record.get("scope_adjustment", {}))
                    adjustment.update(
                        source="director_brief", extend_end_quote=canonical_quote,
                        reason=scope["reason"],
                    )
                    excerpt_record = {
                        **excerpt_record,
                        "candidate_end_character": end,
                        "end_character": extended_end,
                        "excerpt_sha256": _hash(bundle.source_text[current_start:extended_end]),
                        "text": bundle.source_text[current_start:extended_end],
                        "scope_adjustment": adjustment,
                    }
                    selected_excerpt = excerpt_record["text"]
                elif trim_end_quote:
                    if (not isinstance(trim_end_quote, str)
                            or not isinstance(scope.get("reason"), str)
                            or not scope["reason"].strip()):
                        raise CreativeContractError("导演收窄原文终点缺少逐字引文或理由")
                    canonical_quote, trimmed_end_anchor = _canonical_source_quote(
                        bundle.source_text, trim_end_quote,
                        "director.source_scope.trim_end_quote",
                    )
                    _, trimmed_end = _expand_direct_speech_bounds(
                        bundle.source_text, trimmed_end_anchor,
                        trimmed_end_anchor + len(canonical_quote),
                    )
                    current_start = excerpt_record["start_character"]
                    if trimmed_end <= current_start or trimmed_end >= end:
                        raise CreativeContractError("导演建议的收窄终点不在候选原文内部")
                    adjustment = dict(excerpt_record.get("scope_adjustment", {}))
                    adjustment.update(
                        source="director_brief", trim_end_quote=canonical_quote,
                        reason=scope["reason"],
                    )
                    excerpt_record = {
                        **excerpt_record,
                        "candidate_end_character": end,
                        "end_character": trimmed_end,
                        "excerpt_sha256": _hash(bundle.source_text[current_start:trimmed_end]),
                        "text": bundle.source_text[current_start:trimmed_end],
                        "scope_adjustment": adjustment,
                    }
                    selected_excerpt = excerpt_record["text"]
            if bundle.source_driver == "novel":
                scoped_candidate = _candidate_with_director_scope(candidate, excerpt_record)
                if scoped_candidate != candidate:
                    candidate = scoped_candidate
                    analysis = deepcopy(analysis)
                    analysis["candidates"] = [
                        candidate if row["id"] == candidate["id"] else row
                        for row in analysis["candidates"]
                    ]
                    validate_analysis(analysis, bundle.source_text, bundle.source_driver)
            excerpt_path = self.run_dir / "SELECTED_SOURCE.json"
            if excerpt_path.exists() and _read(excerpt_path) != excerpt_record:
                raise RuntimeError("所选原文区间或候选版本已改变")
            _write(excerpt_path, excerpt_record)
            original_analysis = analysis
            original_candidate = candidate
            writer_feedback = brief.get("writer_feedback") or []
            if not isinstance(writer_feedback, list):
                raise CreativeContractError("导演前期意见必须是数组")
            negotiation_output: dict[str, Any] | None = None
            if writer_feedback:
                negotiation_output = self._stage(
                    "writer_director_feedback", "writer",
                    {
                        "materials": context,
                        "previous_analysis": analysis,
                        "candidate_lock": candidate,
                        "selected_source": excerpt_record,
                        "director_brief_sha256": _hash(brief),
                        "writer_feedback": writer_feedback,
                    },
                    lambda value: _validate_director_feedback_response(
                        value, original_candidate, writer_feedback, excerpt_record,
                    ),
                )
                revised_analysis = deepcopy(analysis)
                revised_analysis["candidates"] = [
                    negotiation_output["candidate_update"]
                    if row["id"] == candidate["id"] else row
                    for row in analysis["candidates"]
                ]
                validate_analysis(
                    revised_analysis, bundle.source_text, bundle.source_driver,
                )
                if (
                    revised_analysis["characters"] != analysis["characters"]
                    or revised_analysis["selected_candidate_id"]
                    != analysis["selected_candidate_id"]
                    or any(
                        revised != old
                        for revised, old in zip(
                            revised_analysis["candidates"], analysis["candidates"]
                        )
                        if old["id"] != candidate["id"]
                    )
                ):
                    raise RuntimeError("导演前期意见交接改动了未授权的分析内容")
                analysis = revised_analysis
                candidate = next(
                    row for row in analysis["candidates"]
                    if row["id"] == analysis["selected_candidate_id"]
                )
            changed_fields = [
                key for key in _CANDIDATE_STORY_KEYS
                if candidate[key] != original_candidate[key]
            ]
            negotiation_receipt = {
                "schema": "creative_director_feedback_candidate_revision/v1",
                "status": (
                    "writer_reconciled_director_feedback"
                    if writer_feedback else "no_writer_feedback"
                ),
                "original_analysis_sha256": _hash(original_analysis),
                "director_brief_sha256": _hash(brief),
                "selected_source_sha256": _hash(excerpt_record),
                "writer_feedback_count": len(writer_feedback),
                "model_output_sha256": (
                    _hash(negotiation_output) if negotiation_output is not None else None
                ),
                "changed_candidate_fields": changed_fields,
                "feedback_responses": (
                    negotiation_output["feedback_responses"]
                    if negotiation_output is not None else []
                ),
                "effective_analysis_sha256": _hash(analysis),
            }
            negotiation_path = self.run_dir / "DIRECTOR_FEEDBACK_CANDIDATE_REVISION.json"
            _write_versioned_current(negotiation_path, negotiation_receipt)
            effective_analysis_path = self.run_dir / "EFFECTIVE_ANALYSIS.json"
            _write_versioned_current(effective_analysis_path, analysis)
            context_ref = {
                "source_driver": bundle.source_driver,
                "title": bundle.title,
                "creative_focus": self.creative_focus,
                "material_sha256": self.state["material_sha256"],
                "source_sha256": _hash(bundle.source_text),
                "reference_sha256": _hash(list(bundle.references)),
            }
            beat_plan = self._stage(
                "writer_script", "writer",
                {"materials": context, "analysis": analysis, "director_brief": brief,
                 "candidate_lock": candidate,
                 "selected_source": excerpt_record,
                 "source_dialogue_inventory": (
                     _dialogue_inventory(selected_excerpt) if bundle.source_driver == "novel" else []
                 )},
                lambda value: _validate_beat_plan_for_candidate(
                    value, candidate, selected_excerpt, bundle.source_driver,
                    self.creative_focus,
                ),
            )
            beat_lock = {key: item for key, item in beat_plan.items() if key != "screenplay_markdown"}
            script = {**beat_lock, "screenplay_markdown": compile_beat_screenplay(beat_lock)}
            _validate_script_for_candidate(
                script, candidate, selected_excerpt, bundle.source_driver,
                self.creative_focus,
            )
            for story_revision in range(self.max_revisions + 1):
                script = self._review_script_before_directing(script,
                    key=f"story_{story_revision:02}", bundle=bundle, candidate=candidate,
                    selected_excerpt=selected_excerpt, excerpt_record=excerpt_record,
                    analysis=analysis, brief=brief, context_ref=context_ref)
                if script is None:
                    return self.state
                if self.state.get("segmented_director_binding"):
                    shots = generate_reviewed_beats(self, script, brief, context_ref)
                    if shots is None:
                        return self.state
                    break
                shot_stage = (
                    "director_shots" if story_revision == 0
                    else f"director_shots__story_{story_revision:02}"
                )
                shot_result = self._stage(
                    shot_stage, "director",
                    {"material_ref": context_ref, "analysis": analysis, "director_brief": brief,
                     "candidate_lock": candidate, "selected_source": excerpt_record,
                     "script": script},
                    lambda value: validate_director_shots_or_story_issues(
                        value, brief, script, selected_excerpt,
                        self.creative_focus,
                    ),
                )
                if "story_issues" not in shot_result:
                    shots = shot_result
                    break
                story_issues = shot_result["story_issues"]
                if self.review_policy_version in REVIEW_POLICY_VERSIONS:
                    story_context = {"material_ref": context_ref, "analysis": analysis,
                        "director_brief": brief, "candidate_lock": candidate,
                        "selected_source": excerpt_record, "script": script}
                    for attempt in range(2):
                        story_check = {"story_preserved": False, "issues": story_issues,
                                       "suggestions": [], "calibration_focus": []}
                        verified = self._verified_review(shot_stage, story_check, story_context)
                        if verified is None:
                            return self.state
                        story_issues = verified
                        if story_issues:
                            break
                        if attempt:
                            raise RuntimeError("导演两次只返回已驳回的问题，没有有效分镜；停止而非修改合格剧本")
                        shot_stage += "__dismissed_retry"
                        story_context = {**story_context, "dismissed_story_issues": shot_result["story_issues"],
                            "instruction": "这些问题已经由助手核实为误报。保留剧本，生成完整分镜，不修改剧本。"}
                        shot_result = self._stage(shot_stage, "director", story_context,
                            lambda value: validate_director_shots_or_story_issues(
                                value, brief, script, selected_excerpt, self.creative_focus))
                        if "story_issues" not in shot_result:
                            break
                        story_issues = shot_result["story_issues"]
                    if "story_issues" not in shot_result:
                        shots = shot_result
                        break
                if _story_issues_require_source_boundary(story_issues):
                    return self._stop_for_upstream_source_boundary(
                        script=script,
                        shots=None,
                        issues=story_issues,
                        excerpt_record=excerpt_record,
                        evidence_name="director_story_issue",
                        evidence=shot_result,
                        explanation=(
                            "导演发现锁定选段边界不足；局部节拍返修不能越界补剧情。"
                        ),
                    )
                if _story_issues_require_candidate_revision(story_issues):
                    return self._stop_for_upstream_candidate_revision(
                        script=script,
                        shots=None,
                        issues=story_issues,
                        excerpt_record=excerpt_record,
                        evidence_name="director_story_issue",
                        evidence=shot_result,
                        explanation=(
                            "导演发现候选的关键刺激或结果无法在当前来源约束下忠实呈现；"
                            "局部节拍返修不能把间接叙述改成新对白。"
                        ),
                    )
                self._clear_stale_upstream_stop_state()
                round_key = f"story_issue_round_{story_revision + 1:02}"
                if story_revision >= self.max_revisions or (
                    round_key not in self.state.setdefault("revision_committed", [])
                    and self.state["revision_rounds"] >= self.max_revisions
                ):
                    unresolved = {
                        "schema": "creative_unresolved_draft/v1",
                        "status": "needs_revision",
                        "script_sha256": _hash(script),
                        "director_story_issue_sha256": _hash(shot_result),
                        "script": script,
                        "shots": None,
                        "issues": story_issues,
                        "automatic_media_submit": False,
                    }
                    _write(self.run_dir / "UNRESOLVED_DRAFT.json", unresolved)
                    lines = ["# 未通过的剧本工作稿", "",
                             "导演在拆镜前发现主要剧情问题；本稿不能进入媒体生成。", "",
                             script["screenplay_markdown"], "", "## 未解决问题", ""]
                    for issue in story_issues:
                        lines.extend((f"### {issue['location']} · {issue['severity']}", "",
                                      f"证据：{issue['evidence']}", "",
                                      f"影响：{issue['impact']}", "",
                                      f"建议：{issue['proposal']}", ""))
                    (self.run_dir / "UNRESOLVED_DRAFT.md").write_text(
                        "\n".join(lines), encoding="utf-8",
                    )
                    self.state["status"] = "needs_revision"
                    self.state["unresolved_issues"] = story_issues
                    self._save()
                    return self.state
                # One writer revision, one director retry and the later writer check are mandatory.
                if round_key not in self.state.get("revision_committed", []) and self.state["calls_started"] + 3 > self.max_calls:
                    raise RuntimeError("编剧返修、导演复审和交叉回核预算不足，未跳过检查")
                if round_key not in self.state["revision_committed"]:
                    self.state["revision_committed"].append(round_key)
                    self.state["revision_rounds"] += 1
                    self._save()
                writer_stage = f"writer_revise__story_{story_revision + 1:02}"
                affected_writer_beats = _issue_beat_ids(script, story_issues)
                proposed_script = self._stage(
                    writer_stage, "writer",
                    {"material_ref": context_ref, "selected_source": excerpt_record,
                     "analysis": analysis, "brief": brief, "candidate_lock": candidate,
                     "previous_script": script, "affected_beat_ids": affected_writer_beats,
                     "issues": story_issues},
                    lambda value: _validate_writer_revision_result(
                        value, script, affected_writer_beats,
                        candidate, selected_excerpt, bundle.source_driver,
                        self.creative_focus,
                        revision_mode=self._script_revision_mode(),
                    ),
                )
                projected_script = _writer_revision_result(
                    script, proposed_script, affected_writer_beats,
                    revision_mode=self._script_revision_mode(),
                )
                proposed_by_id = {
                    row.get("id"): row for row in proposed_script.get("beats", [])
                    if isinstance(row, dict)
                }
                _write(self.run_dir / f"{writer_stage}__affected_projection.json", {
                    "schema": ("creative_writer_full_revision_adoption/v1" if self._script_revision_mode() == "full_script" else "creative_writer_revision_projection/v1"),
                    "affected_beat_ids": affected_writer_beats,
                    "model_output_sha256": _hash(proposed_script),
                    "projected_output_sha256": _hash(projected_script),
                    "ignored_beat_ids": [] if self._script_revision_mode() == "full_script" else [
                        row.get("id") for row in script.get("beats", [])
                        if isinstance(row, dict) and row.get("id") not in affected_writer_beats
                        and "replace_beats" not in proposed_script
                        and proposed_by_id.get(row.get("id")) != row
                    ],
                })
                script = projected_script
            from .creative_state_plan_binding import bind_reviewed_state_plan
            state_plan_context, state_plan_sha256 = bind_reviewed_state_plan(self, script, shots)
            reviewed_design = None
            check = {"issues": []}
            for revision in range(self.max_revisions + 1):
                source_scope_audit = _source_scope_audit(
                    selected_excerpt, script, bundle.source_driver,
                )
                _write(
                    self.run_dir / f"SOURCE_SCOPE_AUDIT__{revision:02}.json",
                    source_scope_audit,
                )
                if source_scope_audit["potential_overwide_start"]:
                    self.state["assistant_review_required"] = True
                    self._save()
                review_extras = {}
                if self.model_profile == CREATE_REVIEW_PROFILE and bundle.metadata.get("creative_brief"):
                    reviewed_design = self._stage(
                        f"director_production_design__review_{revision:02}", "director",
                        {"creative_brief": bundle.metadata["creative_brief"],
                         "asset_catalog": bundle.metadata.get("asset_catalog", []),
                         "script": script, "storyboard": shots,
                         "previous_design": reviewed_design,
                         "issues": check["issues"] if revision else [], **state_plan_context},
                        lambda value: _validate_production_design(value, shots, bundle.metadata.get("asset_catalog", [])),
                    )
                    review_extras = {"production_design": reviewed_design,
                                     "asset_catalog": bundle.metadata.get("asset_catalog", [])}
                check_payload = {"material_ref": context_ref, "selected_source": excerpt_record,
                     "candidate_lock": candidate, "analysis": analysis, "script": script, "shots": shots,
                     "source_scope_audit": source_scope_audit, **review_extras, **state_plan_context}
                if self.state.get("writer_prompt_binding"):
                    check_payload["creative_brief"] = self.state["writer_prompt_binding"]["creative_brief"]
                check = self._stage(f"writer_check__{revision:02}", "writer", check_payload, validate_writer_check)
                effective_check = check
                if self.review_policy_version in REVIEW_POLICY_VERSIONS:
                    verified = self._verified_review(f"writer_check__{revision:02}", check, check_payload)
                    if verified is None:
                        return self.state
                    effective_check = {**check, "issues": verified, "story_preserved": not verified}
                    check = effective_check

                audited_check_issues, dismissed_source_claims = (
                    _audit_review_source_absence_claims(
                        effective_check["issues"], script, selected_excerpt,
                    )
                )
                if dismissed_source_claims:
                    source_claim_audit = {
                        "schema": "creative_review_source_claim_audit/v1",
                        "writer_check_sha256": _hash(check),
                        "script_sha256": _hash(script),
                        "selected_source_sha256": _hash(excerpt_record),
                        "dismissed": dismissed_source_claims,
                        "retained_issue_sha256": [
                            _hash(row) for row in audited_check_issues
                        ],
                        "rule": (
                            "only exact cited dialogue absence claims contradicted by "
                            "the locked selected source are dismissed"
                        ),
                    }
                    _write(
                        self.run_dir / f"writer_check__{revision:02}__source_claim_audit.json",
                        source_claim_audit,
                    )
                issues = [
                    row for row in audited_check_issues
                    if row["severity"] in ("blocking", "major")
                ]
                if state_plan_sha256 and (issues or (reviewed_design and reviewed_design.get("issues"))):
                    # A free-form director patch would bypass the reviewed typed plan.
                    self.state.update(status="needs_revision", unresolved_issues=issues,
                        design_issues=(reviewed_design or {}).get("issues", []),
                        reason="v6联合审核未通过；须修订并重审状态计划或资产设计，禁止旧分镜自由补丁",
                        blocked_state_plan_sha256=state_plan_sha256)
                    self._save()
                    return self.state
                if not issues:
                    break
                if _story_issues_require_source_boundary(issues):
                    return self._stop_for_upstream_source_boundary(
                        script=script,
                        shots=shots,
                        issues=issues,
                        excerpt_record=excerpt_record,
                        evidence_name="writer_check",
                        evidence=check,
                        explanation=(
                            "编剧交叉回核发现锁定选段边界不足；局部剧本或分镜返修"
                            "不能越界补写原文没有的前因。"
                        ),
                    )
                if _story_issues_require_candidate_revision(issues):
                    return self._stop_for_upstream_candidate_revision(
                        script=script,
                        shots=shots,
                        issues=issues,
                        excerpt_record=excerpt_record,
                        evidence_name="writer_check",
                        evidence=check,
                        explanation=(
                            "编剧交叉回核发现当前候选无法在来源与呈现约束内忠实完成；"
                            "局部剧本或分镜返修不能把间接叙述改成新对白。"
                        ),
                    )
                self._clear_stale_upstream_stop_state()
                round_key = f"issue_round_{revision + 1:02}"
                if revision >= self.max_revisions or (
                    round_key not in self.state.setdefault("revision_committed", [])
                    and self.state["revision_rounds"] >= self.max_revisions
                ):
                    unresolved = {
                        "schema": "creative_unresolved_draft/v1",
                        "status": "needs_revision",
                        "script_sha256": _hash(script),
                        "shots_sha256": _hash(shots),
                        "check_sha256": _hash(check),
                        "script": script,
                        "shots": shots,
                        "issues": issues,
                        "automatic_media_submit": False,
                    }
                    _write(self.run_dir / "UNRESOLVED_DRAFT.json", unresolved)
                    lines = ["# 未通过的剧本工作稿", "", "本稿存在未解决的主要问题，不能作为合格剧本或视频生成依据。", "",
                             "## 剧本", "", script["screenplay_markdown"], "", "## 未解决问题", ""]
                    for issue in issues:
                        lines.extend((
                            f"### {issue['location']} · {issue['owner']} · {issue['severity']}", "",
                            f"证据：{issue['evidence']}", "",
                            f"影响：{issue['impact']}", "",
                            f"建议：{issue['proposal']}", "",
                        ))
                    (self.run_dir / "UNRESOLVED_DRAFT.md").write_text("\n".join(lines), encoding="utf-8")
                    self.state["status"] = "needs_revision"
                    self.state["unresolved_issues"] = issues
                    self._save()
                    return self.state
                # Reserve both revision and independent re-check before spending the next call.
                owners = {row["owner"] for row in issues}
                needed = (2 if "writer" in owners else 1) + 1
                if self.model_profile == CREATE_REVIEW_PROFILE and bundle.metadata.get("creative_brief"):
                    needed += 1  # Rebuild the asset plan before the independent review.
                if round_key not in self.state.get("revision_committed", []) and self.state["calls_started"] + needed > self.max_calls:
                    raise RuntimeError("返修和复核预算不足，停在待检查状态")
                if round_key not in self.state["revision_committed"]:
                    self.state["revision_committed"].append(round_key)
                    self.state["revision_rounds"] += 1
                    self._save()
                previous_script = script
                previous_shots = shots
                if "writer" in owners:
                    writer_stage = f"writer_revise__{revision + 1:02}"
                    writer_issues = [row for row in issues if row["owner"] == "writer"]
                    affected_writer_beats = _issue_beat_ids(
                        script, writer_issues, previous_shots,
                    )
                    proposed_script = self._stage(
                        writer_stage, "writer",
                        {"material_ref": context_ref, "selected_source": excerpt_record,
                         "analysis": analysis, "brief": brief, "previous_script": script,
                         "affected_beat_ids": affected_writer_beats, "issues": writer_issues},
                        lambda value: _validate_writer_revision_result(
                            value, previous_script, affected_writer_beats,
                            candidate, selected_excerpt, bundle.source_driver,
                            self.creative_focus,
                            revision_mode=self._script_revision_mode(),
                        ),
                    )
                    script = _writer_revision_result(
                        previous_script, proposed_script, affected_writer_beats,
                        revision_mode=self._script_revision_mode(),
                    )
                    proposed_by_id = {
                        row.get("id"): row for row in proposed_script.get("beats", [])
                        if isinstance(row, dict)
                    }
                    _write(self.run_dir / f"{writer_stage}__affected_projection.json", {
                        "schema": ("creative_writer_full_revision_adoption/v1" if self._script_revision_mode() == "full_script" else "creative_writer_revision_projection/v1"),
                        "affected_beat_ids": affected_writer_beats,
                        "model_output_sha256": _hash(proposed_script),
                        "projected_output_sha256": _hash(script),
                        "ignored_beat_ids": [] if self._script_revision_mode() == "full_script" else [
                            row.get("id") for row in previous_script.get("beats", [])
                            if isinstance(row, dict) and row.get("id") not in affected_writer_beats
                            and "replace_beats" not in proposed_script
                            and proposed_by_id.get(row.get("id")) != row
                        ],
                    })
                if "writer" in owners:
                    script = self._review_script_before_directing(script,
                        key=f"joint_{revision + 1:02}", bundle=bundle, candidate=candidate,
                        selected_excerpt=selected_excerpt, excerpt_record=excerpt_record,
                        analysis=analysis, brief=brief, context_ref=context_ref)
                    if script is None:
                        return self.state
                if "writer" in owners and self._script_revision_mode() == "full_script":
                    shots = self._regenerate_full_storyboard(
                        f"joint_{revision + 1:02}", script, brief, analysis, candidate,
                        excerpt_record, context_ref, selected_excerpt)
                else:
                    affected_beat_ids = _bound_director_revision_beats(
                        self.run_dir / f"director_revise__{revision + 1:02}.json",
                        previous_script, script, previous_shots, issues, reviewed_design,
                    )
                    if not affected_beat_ids:
                        raise CreativeContractError("导演返修问题没有可定位的节拍或镜头")
                    director_revision = self._stage(
                        f"director_revise__{revision + 1:02}", "director",
                        {"material_ref": context_ref, "selected_source": excerpt_record,
                         "brief": brief, "script": script, "previous_shots": previous_shots,
                         "affected_beat_ids": affected_beat_ids, "issues": issues},
                        lambda value: _validate_director_revision_result(
                            value, previous_shots, affected_beat_ids, brief, script,
                            selected_excerpt, self.creative_focus,
                        ),
                    )
                    shots = (
                        _apply_director_revision_patch(previous_shots, director_revision, affected_beat_ids)
                        if "replace_beats" in director_revision else director_revision
                    )
            production_design = reviewed_design
            if bundle.metadata.get("creative_brief") and self.model_profile == LEGACY_MODEL_PROFILE:
                production_design = self._stage(
                    "director_production_design", "director",
                    {"creative_brief": bundle.metadata["creative_brief"], "asset_catalog": bundle.metadata.get("asset_catalog", []), "script": script, "storyboard": shots},
                    lambda value: _validate_production_design(value, shots, bundle.metadata.get("asset_catalog", [])),
                )
            if production_design is not None:
                _write(self.run_dir / "PRODUCTION_DESIGN.json", production_design)
            _write(self.run_dir / "SCREENPLAY.json", script)
            (self.run_dir / "SCREENPLAY.md").write_text(script["screenplay_markdown"], encoding="utf-8")
            _write(self.run_dir / "STORYBOARD.json", shots)
            execution_draft = _execution_draft(script, shots)
            _write(self.run_dir / "EXECUTION_DRAFT.json", execution_draft)
            capability_audit = audit_creative_executor(shots)
            _write(self.run_dir / "MEDIA_CAPABILITY_AUDIT.json", capability_audit)
            segment_plan = build_seedance_segment_plan(script, shots, capability_audit)
            _write(self.run_dir / "SEEDANCE_SEGMENT_PLAN.json", segment_plan)
            review_packet = _review_packet(
                analysis, brief, script, shots, check, self.state["material_sha256"],
                assistant_review_required=self.state.get("assistant_review_required", True),
                source_scope_audit=source_scope_audit,
            )
            _write(self.run_dir / "EDITORIAL_REVIEW_PACKET.json", review_packet)
            (self.run_dir / "EDITORIAL_REVIEW_PACKET.md").write_text(
                _review_packet_markdown(review_packet), encoding="utf-8"
            )
            handoff = {
                "schema": "creative_media_handoff/v1",
                "material_sha256": self.state["material_sha256"],
                "analysis_sha256": _hash(analysis),
                "brief_sha256": _hash(brief),
                "script_sha256": _hash(script),
                "shots_sha256": _hash(shots),
                "execution_draft_sha256": _hash(execution_draft),
                "capability_audit_sha256": _hash(capability_audit),
                "segment_plan_sha256": _hash(segment_plan),
                "media_provider": capability_audit["provider"],
                "media_model": capability_audit["model"],
                "review_packet_sha256": _hash(review_packet),
                "text_status": (
                    "auto_checked_calibration_review_pending"
                    if self.state.get("assistant_review_required", True)
                    else "auto_checked_routine_review_waived_after_calibration"
                ),
                "media_status": "segment_templates_ready_capability_unverified",
                "automatic_submit": False,
                "reason": "Seedance 请求模板已映射；已审首帧、切镜装配、原始尾帧续段和真实声画仍待核验",
            }
            if state_plan_sha256:
                handoff["state_plan_sha256"] = state_plan_sha256
                if state_plan_context.get("scheduled_state_plan"):
                    handoff["scheduled_state_plan_sha256"] = _hash(state_plan_context["scheduled_state_plan"])
                    handoff["scheduling_report_sha256"] = _hash(state_plan_context["scheduling_report"])
            if production_design is not None:
                handoff["production_design_sha256"] = _hash(production_design)
                handoff["reusable_production_status"] = "design_issues_require_revision" if production_design["issues"] else "awaiting_actual_style_and_asset_reviews"
            if self.review_policy_version in REVIEW_POLICY_VERSIONS:
                history = {"policy": self.review_policy_version,
                    "decisions": self.state.get("evidence_review_decisions", {}),
                    "automatic_media_submit": False}
                _write(self.run_dir / "TEXT_REVIEW_HISTORY.json", history)
                handoff["text_review_history_sha256"] = _hash(history)
            from .creative_narrative_transfer import enabled as narrative_enabled, build_transfer
            if narrative_enabled(self.state.get("narrative_focus_binding")):
                transfer = build_transfer(self.state["narrative_focus_binding"],
                    bundle.metadata["creative_brief"], script, shots, segment_plan)
                _write(self.run_dir / "NARRATIVE_TRANSFER.json", transfer)
                handoff["narrative_transfer_sha256"] = _hash(transfer)
            _write(self.run_dir / "MEDIA_HANDOFF.json", handoff)
            self.state["status"] = "media_handoff_pending_capability"
            self.state["text_pass_sequence"] = 1
            self.state["handoff_sha256"] = _hash(handoff)
            from .creative_governed_runtime import focused_artifacts
            governed_artifacts = focused_artifacts(self)
            output_manifest = self._write_output_manifest(
                handoff=handoff,
                artifact_purposes={
                    **governed_artifacts,
                    "materials.json": "材料清单与上下文范围",
                    "CONTEXT_STRATEGY.json": "上下文能力依据、估算、分层与未逐字发送范围",
                    "writer_analysis.json": "整体理解、候选与编剧调用回执",
                    "director_brief.json": "导演方向与前期意见",
                    "DIRECTOR_FEEDBACK_CANDIDATE_REVISION.json": "导演前期意见与编剧逐条回应的版本绑定",
                    "EFFECTIVE_ANALYSIS.json": "吸收导演前期意见后的有效编剧分析",
                    **{path.name: "导演前期意见交接收据历史版本（不可变）"
                       for path in self.run_dir.glob("DIRECTOR_FEEDBACK_CANDIDATE_REVISION__history_*.json")},
                    **{path.name: "有效编剧分析历史版本（不可变）"
                       for path in self.run_dir.glob("EFFECTIVE_ANALYSIS__history_*.json")},
                    "SELECTED_SOURCE.json": "锁定原文选段或原创来源",
                    **({"TEXT_REVIEW_HISTORY.json": "剧本和联合审核的助手核实记录",
                        **{f"{key}__{suffix}.json": "绑定稿件的审核证据与核实记录"
                           for key in self.state.get("evidence_review_decisions", {})
                           for suffix in ("review_packet", "assistant_decision", "confirmed_issues")}}
                       if self.review_policy_version in REVIEW_POLICY_VERSIONS else {}),
                    "SCREENPLAY.json": "结构化完整剧本",
                    "SCREENPLAY.md": "完整可读剧本",
                    "STORYBOARD.json": "导演分镜、表演与连续性",
                    **({"STATE_PLAN.json": "已审核的全片状态计划及模型/审核来源"} if state_plan_sha256 else {}),
                    **({"SCHEDULED_STATE_PLAN.json": "程序排时的执行计划", "SCHEDULING_REPORT.json": "动作和对白时间分配依据"} if state_plan_context.get("scheduled_state_plan") else {}),
                    **({"PRODUCTION_DESIGN.json": "通用资产、镜头意图与实审计划"} if production_design is not None else {}),
                    "EDITORIAL_REVIEW_PACKET.json": "审核与情绪窗口记录",
                    "EDITORIAL_REVIEW_PACKET.md": "可读审核包",
                    "EXECUTION_DRAFT.json": "执行预稿与文本检查等级",
                    "MEDIA_CAPABILITY_AUDIT.json": "媒体执行限制",
                    "SEEDANCE_SEGMENT_PLAN.json": "分段执行与首尾状态计划",
                    "MEDIA_HANDOFF.json": "锁定媒体交接与提交开关",
                },
            )
            self.state["output_manifest_sha256"] = _hash(output_manifest)
            self.state.pop("last_error", None)
            self._save()
            return self.state
        except CreativeStageBreakpointReached:
            return self.state
        except Exception as exc:
            self.state["status"] = "needs_attention"
            self.state["last_error"] = str(exc)
            self._save()
            raise

    def revise_from_assistant(
        self, bundle: MaterialBundle, feedback_path: Path,
    ) -> dict[str, Any]:
        """Spend a remaining shared revision round on a bound assistant issue list.

        The original handoff and first-draft review remain immutable. A revised
        candidate is never promoted until an assistant actually rereads it.
        """
        if (self.state.get("segmented_director_binding") or {}).get("version") == "reviewed_beat_storyboard_v6":
            raise CreativeContractError("v6须通过状态计划返修与重审，禁止旧助手自由分镜返修入口")
        self.run(bundle)
        if self.state.get("status") != "needs_revision":
            raise CreativeContractError("只有助手登记主要问题的稿件可走阶段性返修")
        review = validated_assistant_review(self.run_dir, self.state)
        if review is None or review.get("outcome") != "major_issues":
            raise CreativeContractError("助手返修缺少绑定的主要问题复核")
        feedback = _read(Path(feedback_path))
        if not isinstance(feedback, dict):
            raise CreativeContractError("助手问题单格式无效")
        schema = feedback.get("schema")
        round_index = {"creative_assistant_feedback/v1": 1,
                       "creative_assistant_feedback/v2": 2}.get(schema)
        repair_scope = "script_and_shots"
        if schema == "creative_assistant_feedback/v3":
            round_index = feedback.get("round_index")
            repair_scope = feedback.get("repair_scope")
            if type(round_index) is not int or round_index not in (1, 2):
                raise CreativeContractError("上游返修轮次必须是第一或第二轮")
            if repair_scope not in (
                "analysis_character_motivation", "analysis_candidate_claims",
                "selected_source_boundary",
            ):
                raise CreativeContractError("上游返修范围无效")
        expected_keys = {"schema", "handoff_sha256", "assistant_review_sha256", "issues"}
        if schema == "creative_assistant_feedback/v3":
            expected_keys.update(("round_index", "repair_scope"))
            if repair_scope == "analysis_character_motivation":
                expected_keys.add("target_characters")
            else:
                expected_keys.add("target_candidate_id")
            if repair_scope == "selected_source_boundary":
                expected_keys.update((
                    "parent_selected_source_sha256", "new_start_quote",
                    "new_end_quote", "boundary_reason",
                ))
        if round_index == 2:
            expected_keys.add("parent_revision_review_sha256")
        if round_index is None or set(feedback) != expected_keys:
            raise CreativeContractError("助手问题单格式无效")
        if (feedback["handoff_sha256"] != self.state["handoff_sha256"]
                or feedback["assistant_review_sha256"] != self.state["assistant_review_sha256"]):
            raise CreativeContractError("助手问题单与受审版本不符")
        previous_review = None
        if round_index == 2:
            previous_review = validated_revision_review(self.run_dir, self.state, round_index=1)
            if (previous_review is None or previous_review["outcome"] != "major_issues"
                    or feedback["parent_revision_review_sha256"] != _hash(previous_review)):
                raise CreativeContractError("第二轮问题单未绑定第一轮实际复核")
        issues = feedback["issues"]
        validate_writer_check({"story_preserved": False, "issues": issues,
                               "calibration_focus": []})
        if not issues or any(row["severity"] not in ("blocking", "major") for row in issues):
            raise CreativeContractError("助手返修单只接收阻断或主要问题")
        if repair_scope == "analysis_character_motivation":
            targets = feedback["target_characters"]
            if (not isinstance(targets, list) or not targets
                    or any(not isinstance(name, str) or not name.strip() for name in targets)
                    or len(set(targets)) != len(targets)
                    or any(row["owner"] != "writer" for row in issues)):
                raise CreativeContractError("上游人物动机返修必须点名人物并归编剧处理")
            current_analysis = _load_effective_analysis(self.run_dir)
            known_names = {row["name"] for row in current_analysis["characters"]}
            if any(name not in known_names for name in targets):
                raise CreativeContractError("上游返修点名了旧分析中不存在的人物")
        elif repair_scope in ("analysis_candidate_claims", "selected_source_boundary"):
            target_candidate_id = feedback["target_candidate_id"]
            current_analysis = _load_effective_analysis(self.run_dir)
            if (not isinstance(target_candidate_id, str)
                    or target_candidate_id != current_analysis["selected_candidate_id"]
                    or any(row["owner"] != "writer" for row in issues)):
                raise CreativeContractError("候选或选段返修必须绑定当前已选候选并归编剧处理")
            if repair_scope == "selected_source_boundary":
                if bundle.source_driver != "novel":
                    raise CreativeContractError("视频原创驱动不允许伪造小说选段边界")
                active_excerpt = _read(self.run_dir / "SELECTED_SOURCE.json")
                if round_index == 2:
                    previous_draft_for_scope = _read(
                        revision_artifact(self.run_dir, "REVISION_DRAFT", 1)
                    )
                    active_excerpt = previous_draft_for_scope.get(
                        "selected_source", active_excerpt,
                    )
                _revise_selected_source_boundary(
                    bundle.source_text, active_excerpt, feedback,
                )
        bound_path = revision_artifact(self.run_dir, "FEEDBACK", round_index)
        if bound_path.exists():
            if _read(bound_path) != feedback:
                raise RuntimeError("同一任务的助手返修单已绑定另一版本")
        else:
            _write(bound_path, feedback)
        revised_review = validated_revision_review(
            self.run_dir, self.state, round_index=round_index,
        )
        if revised_review is not None:
            return self.state
        if round_index == 1 and self.state.get("assistant_revision_round_index", 1) == 2:
            raise CreativeContractError("当前任务已进入第二轮助手返修；不能重跑第一轮")

        brief_record = _read(self.run_dir / "director_brief.json")
        analysis, brief = _load_effective_analysis(self.run_dir), brief_record["output"]
        handoff = _read(self.run_dir / "MEDIA_HANDOFF.json")
        if (_hash(analysis) != handoff["analysis_sha256"]
                or _hash(brief) != handoff["brief_sha256"]
                or _hash(feedback) != _hash(_read(bound_path))):
            raise RuntimeError("助手返修上游产物与旧交接版本不符")
        candidate = next(
            row for row in analysis["candidates"]
            if row["id"] == analysis["selected_candidate_id"]
        )
        excerpt = _read(self.run_dir / "SELECTED_SOURCE.json")
        if round_index == 2:
            previous_draft = _read(revision_artifact(self.run_dir, "REVISION_DRAFT", 1))
            if (previous_review is None
                    or previous_review["draft_sha256"] != _hash(previous_draft)):
                raise RuntimeError("第二轮上游返修稿与第一轮复核不符")
            script, shots = previous_draft["script"], previous_draft["shots"]
            analysis = previous_draft.get("analysis", analysis)
            brief = previous_draft.get("brief", brief)
            excerpt = previous_draft.get("selected_source", excerpt)
        else:
            script = _read(self.run_dir / "SCREENPLAY.json")
            shots = _read(self.run_dir / "STORYBOARD.json")
        selected_text = excerpt["text"] if bundle.source_driver == "novel" else bundle.source_text
        candidate = next(
            row for row in analysis["candidates"]
            if row["id"] == analysis["selected_candidate_id"]
        )
        round_key = f"assistant_issue_round_{round_index:02}"
        owners = {row["owner"] for row in issues}
        upstream_repair = repair_scope in (
            "analysis_character_motivation", "analysis_candidate_claims",
            "selected_source_boundary",
        )
        needed = (
            4 if repair_scope == "selected_source_boundary"
            else 5 if upstream_repair
            else (2 if "writer" in owners else 1) + 1
        )
        if "writer" in owners and self._script_revision_mode() == "full_script":
            needed += 1  # Review the complete new script before regenerating all shots.
        if bundle.metadata.get("creative_brief"):
            needed += 1  # Include the production-design model call.
        if round_key not in self.state["revision_committed"]:
            if self.state["revision_rounds"] >= self.max_revisions:
                self.state["assistant_revision_status"] = "budget_exhausted"
                self._save()
                return self.state
            if self.state["calls_started"] + needed > self.max_calls:
                self.state["assistant_revision_status"] = "call_budget_exhausted"
                self._save()
                return self.state
            # Reserve the writer/director round and its independent recheck as
            # one unit, not only the first paid request.
            input_size = len(_canonical({"feedback": feedback, "script": script,
                                         "shots": shots, "analysis": analysis, "brief": brief}))
            if self._reported_tokens() + needed * (input_size + 20000) > self.max_total_tokens:
                self.state["assistant_revision_status"] = "token_budget_exhausted"
                self._save()
                return self.state
            self.state["revision_committed"].append(round_key)
            self.state["revision_rounds"] += 1
            self.state["assistant_revision_round_index"] = round_index
            self.state["assistant_revision_status"] = "in_progress"
            self._save()

        context_ref = {
            "source_driver": bundle.source_driver,
            "title": bundle.title,
            "creative_focus": self.creative_focus,
            "material_sha256": self.state["material_sha256"],
            "source_sha256": _hash(bundle.source_text),
            "reference_sha256": _hash(list(bundle.references)),
        }
        try:
            if repair_scope == "analysis_character_motivation":
                original_characters = {row["name"]: row for row in analysis["characters"]}

                def validate_character_updates(value: dict[str, Any]) -> None:
                    if (set(value) != {"character_updates"}
                            or not isinstance(value["character_updates"], list)
                            or len(value["character_updates"]) != len(targets)
                            or any(not isinstance(row, dict)
                                   or not isinstance(row.get("name"), str)
                                   for row in value["character_updates"])):
                        raise CreativeContractError("人物动机补丁必须恰好覆盖点名人物")
                    if {row["name"] for row in value["character_updates"]} != set(targets):
                        raise CreativeContractError("人物动机补丁必须恰好覆盖点名人物")
                    for row in value["character_updates"]:
                        if (not isinstance(row, dict)
                                or set(row) != {"name", "want", "fear", "source_quote"}
                                or not isinstance(row["source_quote"], str)
                                or any(not isinstance(row[key], str) or not row[key].strip()
                                       for key in ("want", "fear"))):
                            raise CreativeContractError("人物动机补丁字段不完整")
                    if not any(
                        row[key] != original_characters[row["name"]][key]
                        for row in value["character_updates"] for key in ("want", "fear")
                    ):
                        raise CreativeContractError("人物动机返修没有改变无依据的判断")

                updates = self._stage(
                    f"writer_character_motivation_revise__assistant_{round_index:02}", "writer",
                    {"materials": self._context(bundle), "previous_analysis": analysis,
                     "target_characters": targets, "issues": issues,
                     "selected_source": excerpt},
                    validate_character_updates,
                )
                revised_analysis = deepcopy(analysis)
                changes = {row["name"]: row for row in updates["character_updates"]}
                quote_echoes_ignored = [
                    {"name": row["name"],
                     "received_sha256": _hash(row["source_quote"]),
                     "locked_sha256": _hash(original_characters[row["name"]]["source_quote"])}
                    for row in updates["character_updates"]
                    if row["source_quote"] != original_characters[row["name"]]["source_quote"]
                ]
                revised_analysis["characters"] = [
                    {**row, "want": changes[row["name"]]["want"],
                     "fear": changes[row["name"]]["fear"]} if row["name"] in changes else row
                    for row in analysis["characters"]
                ]
                validate_analysis(revised_analysis, bundle.source_text, bundle.source_driver)
                if (revised_analysis["candidates"] != analysis["candidates"]
                        or revised_analysis["selected_candidate_id"] != analysis["selected_candidate_id"]):
                    raise RuntimeError("人物动机返修改变了已锁定候选")
                analysis = revised_analysis
            elif repair_scope == "analysis_candidate_claims":
                original_candidate = next(
                    row for row in analysis["candidates"]
                    if row["id"] == target_candidate_id
                )
                locked_keys = ("id", "title", "start_quote", "end_quote", "duration_seconds")

                def validate_candidate_update(value: dict[str, Any]) -> None:
                    if (set(value) != {"candidate_update"}
                            or not isinstance(value["candidate_update"], dict)):
                        raise CreativeContractError("候选声明返修必须提交唯一 candidate_update")
                    update = value["candidate_update"]
                    if set(update) != set(original_candidate):
                        raise CreativeContractError("候选声明返修字段不完整")
                    if any(update[key] != original_candidate[key] for key in locked_keys):
                        raise CreativeContractError("候选声明返修改变了身份、选段或时长")
                    if not any(
                        update[key] != original_candidate[key]
                        for key in ("setup", "conflict", "turn", "peak", "aftermath",
                                    "selection_reason")
                    ):
                        raise CreativeContractError("候选声明返修没有改变越界承诺")

                update = self._stage(
                    f"writer_candidate_claims_revise__assistant_{round_index:02}", "writer",
                    {"materials": self._context(bundle), "previous_analysis": analysis,
                     "candidate_lock": original_candidate, "selected_source": excerpt,
                     "issues": issues},
                    validate_candidate_update,
                )["candidate_update"]
                revised_analysis = deepcopy(analysis)
                revised_analysis["candidates"] = [
                    update if row["id"] == target_candidate_id else row
                    for row in analysis["candidates"]
                ]
                validate_analysis(revised_analysis, bundle.source_text, bundle.source_driver)
                if (revised_analysis["characters"] != analysis["characters"]
                        or revised_analysis["selected_candidate_id"] != analysis["selected_candidate_id"]):
                    raise RuntimeError("候选声明返修改变了人物或选择结果")
                analysis = revised_analysis
            elif repair_scope == "selected_source_boundary":
                original_analysis = deepcopy(analysis)
                original_candidate = next(
                    row for row in analysis["candidates"]
                    if row["id"] == target_candidate_id
                )
                revised_excerpt, start_quote, end_quote = _revise_selected_source_boundary(
                    bundle.source_text, excerpt, feedback,
                )
                revised_analysis = deepcopy(analysis)
                revised_analysis["candidates"] = [
                    {**row, "start_quote": start_quote, "end_quote": end_quote}
                    if row["id"] == target_candidate_id else row
                    for row in analysis["candidates"]
                ]
                validate_analysis(revised_analysis, bundle.source_text, bundle.source_driver)
                revised_candidate = next(
                    row for row in revised_analysis["candidates"]
                    if row["id"] == target_candidate_id
                )
                for key in (
                    "id", "title", "setup", "conflict", "turn", "peak",
                    "aftermath", "duration_seconds", "selection_reason",
                ):
                    if revised_candidate[key] != original_candidate[key]:
                        raise RuntimeError("选段边界返修改变了候选身份或剧情声明")
                if (revised_analysis["characters"] != original_analysis["characters"]
                        or revised_analysis["selected_candidate_id"]
                        != original_analysis["selected_candidate_id"]):
                    raise RuntimeError("选段边界返修改变了人物或选择结果")
                analysis = revised_analysis
                excerpt = revised_excerpt
                selected_text = excerpt["text"]
            if upstream_repair:
                candidate = next(
                    row for row in analysis["candidates"]
                    if row["id"] == analysis["selected_candidate_id"]
                )
                revised_brief = self._stage(
                    f"director_brief__assistant_{round_index:02}", "director",
                    {"materials": self._context(bundle), "analysis": analysis,
                     "selected_source": excerpt, "previous_brief": brief,
                     "issues": issues,
                     "locked_scope": excerpt.get("scope_adjustment", {})},
                    lambda value: _validate_director_brief_for_source(
                        value, bundle.source_text, bundle.source_driver, candidate,
                    ),
                )
                if (repair_scope == "selected_source_boundary"
                        and revised_brief.get("source_scope") not in (None, {})):
                    raise CreativeContractError("导演复审不能再次改变助手已锁定的选段边界")
                if (repair_scope != "selected_source_boundary"
                        and revised_brief.get("source_scope")
                        not in (None, {}, brief.get("source_scope"))):
                    raise CreativeContractError("导演上游复审试图改变已锁定原文选段")
                brief = revised_brief
                candidate = next(
                    row for row in analysis["candidates"]
                    if row["id"] == analysis["selected_candidate_id"]
                )
            previous_script = script
            previous_shots = shots
            if repair_scope in ("analysis_candidate_claims", "selected_source_boundary"):
                beat_plan = self._stage(
                    f"writer_script__assistant_{round_index:02}", "writer",
                    {"materials": self._context(bundle), "analysis": analysis,
                     "director_brief": brief, "candidate_lock": candidate,
                     "selected_source": excerpt,
                     "source_dialogue_inventory": (
                         _dialogue_inventory(selected_text)
                         if bundle.source_driver == "novel" else []
                     )},
                    lambda value: _validate_beat_plan_for_candidate(
                        value, candidate, selected_text, bundle.source_driver,
                        self.creative_focus,
                    ),
                )
                beat_lock = {key: value for key, value in beat_plan.items()
                             if key != "screenplay_markdown"}
                script = {**beat_lock, "screenplay_markdown": compile_beat_screenplay(beat_lock)}
                _validate_script_for_candidate(
                    script, candidate, selected_text, bundle.source_driver,
                    self.creative_focus,
                )
            elif "writer" in owners:
                writer_stage = f"writer_revise__assistant_{round_index:02}"
                writer_input = {
                    "material_ref": context_ref, "selected_source": excerpt,
                    "analysis": analysis, "brief": brief, "candidate_lock": candidate,
                    "previous_script": previous_script, "issues": issues,
                }
                # Early assistant-revision receipts predate the explicit affected-beat
                # field. Preserve their exact request hash so a valid received compact
                # reply can be revalidated locally without repeating a paid call.
                writer_record_path = self.run_dir / f"{writer_stage}.json"
                legacy_received_request = False
                if writer_record_path.exists():
                    writer_record = _read(writer_record_path)
                    messages = writer_record.get("request", {}).get("messages", [])
                    if messages and isinstance(messages[-1].get("content"), str):
                        try:
                            recorded_input = json.loads(messages[-1]["content"])
                        except json.JSONDecodeError:
                            recorded_input = None
                        legacy_received_request = (
                            isinstance(recorded_input, dict)
                            and "affected_beat_ids" not in recorded_input
                        )
                writer_issues = [row for row in issues if row["owner"] == "writer"]
                affected_writer_beats = (
                    [
                        row.get("id") for row in previous_script.get("beats", [])
                        if isinstance(row, dict) and isinstance(row.get("id"), str)
                    ]
                    if upstream_repair else
                    _issue_beat_ids(
                        previous_script,
                        issues if legacy_received_request else writer_issues,
                        previous_shots,
                    )
                )
                if not legacy_received_request:
                    writer_input["affected_beat_ids"] = affected_writer_beats
                proposed_script = self._stage(
                    writer_stage, "writer",
                    writer_input,
                    lambda value: _validate_writer_revision_result(
                        value, previous_script, affected_writer_beats,
                        candidate, selected_text, bundle.source_driver,
                        self.creative_focus,
                        revision_mode=self._script_revision_mode(),
                    ),
                )
                script = _writer_revision_result(
                    previous_script, proposed_script, affected_writer_beats,
                    revision_mode=self._script_revision_mode(),
                )
                proposed_by_id = {
                    row.get("id"): row for row in proposed_script.get("beats", [])
                    if isinstance(row, dict)
                }
                _write(self.run_dir / f"{writer_stage}__affected_projection.json", {
                    "schema": ("creative_writer_full_revision_adoption/v1" if self._script_revision_mode() == "full_script" else "creative_writer_revision_projection/v1"),
                    "affected_beat_ids": affected_writer_beats,
                    "model_output_sha256": _hash(proposed_script),
                    "projected_output_sha256": _hash(script),
                    "ignored_beat_ids": [] if self._script_revision_mode() == "full_script" else [
                        row.get("id") for row in previous_script.get("beats", [])
                        if isinstance(row, dict) and row.get("id") not in affected_writer_beats
                        and "replace_beats" not in proposed_script
                        and proposed_by_id.get(row.get("id")) != row
                    ],
                })
            prior_design = (previous_draft.get("production_design") if round_index == 2
                            else _read(self.run_dir / "PRODUCTION_DESIGN.json")
                            if (self.run_dir / "PRODUCTION_DESIGN.json").exists() else None)
            if "writer" in owners and self._script_revision_mode() == "full_script":
                script = self._review_script_before_directing(script,
                    key=f"assistant_{round_index:02}", bundle=bundle, candidate=candidate,
                    selected_excerpt=selected_text, excerpt_record=excerpt,
                    analysis=analysis, brief=brief, context_ref=context_ref)
                if script is None:
                    return self.state
                shots = self._regenerate_full_storyboard(
                    f"assistant_{round_index:02}", script, brief, analysis, candidate,
                    excerpt, context_ref, selected_text)
            else:
                affected_director_beats = _bound_director_revision_beats(
                    self.run_dir / f"director_revise__assistant_{round_index:02}.json",
                    previous_script, script, previous_shots, issues, prior_design,
                    force_all=upstream_repair,
                )
                if not affected_director_beats:
                    raise CreativeContractError("助手返修问题没有可定位的节拍或镜头")
                director_revision = self._stage(
                    f"director_revise__assistant_{round_index:02}", "director",
                    {"material_ref": context_ref, "selected_source": excerpt,
                     "brief": brief, "script": script, "previous_shots": previous_shots,
                     "affected_beat_ids": affected_director_beats, "issues": issues},
                    lambda value: _validate_director_revision_result(
                        value, previous_shots, affected_director_beats, brief, script,
                        selected_text, self.creative_focus,
                    ),
                )
                shots = (
                    _apply_director_revision_patch(
                        previous_shots, director_revision, affected_director_beats,
                    )
                    if "replace_beats" in director_revision else director_revision
                )
            scope_audit = _source_scope_audit(selected_text, script, bundle.source_driver)
            revised_design = None
            self._production_revision_context = {
                "issues": issues,
                "previous_design": (previous_draft.get("production_design") if round_index == 2
                                    else _read(self.run_dir / "PRODUCTION_DESIGN.json")
                                    if (self.run_dir / "PRODUCTION_DESIGN.json").exists() else None),
            }
            review_extras = {}
            if self.model_profile == CREATE_REVIEW_PROFILE and bundle.metadata.get("creative_brief"):
                revised_design = self._stage(
                    f"director_production_design__assistant_{round_index:02}", "director",
                    {"creative_brief": bundle.metadata["creative_brief"],
                     "asset_catalog": bundle.metadata.get("asset_catalog", []),
                     "script": script, "storyboard": shots},
                    lambda value: _validate_production_design(value, shots, bundle.metadata.get("asset_catalog", [])),
                )
                review_extras = {"production_design": revised_design,
                                 "asset_catalog": bundle.metadata.get("asset_catalog", [])}
            check = self._stage(
                f"writer_check__assistant_{round_index:02}", "writer",
                {"material_ref": context_ref, "selected_source": excerpt,
                 "candidate_lock": candidate, "analysis": analysis, "script": script,
                 "shots": shots, "source_scope_audit": scope_audit, **review_extras},
                validate_writer_check,
            )
            unresolved = [row for row in check["issues"]
                          if row["severity"] in ("blocking", "major")]
            if self.model_profile == LEGACY_MODEL_PROFILE and bundle.metadata.get("creative_brief") and not unresolved:
                revised_design = self._stage(
                    f"director_production_design__assistant_{round_index:02}", "director",
                    {"creative_brief": bundle.metadata["creative_brief"],
                     "asset_catalog": bundle.metadata.get("asset_catalog", []),
                     "script": script, "storyboard": shots},
                    lambda value: _validate_production_design(value, shots, bundle.metadata.get("asset_catalog", [])),
                )
            draft = {
                "schema": "creative_assistant_revision_draft/v1",
                "status": "assistant_recheck_pending" if not unresolved else "needs_revision",
                "parent_handoff_sha256": self.state["handoff_sha256"],
                "feedback_sha256": _hash(feedback),
                "repair_scope": repair_scope,
                "analysis_sha256": _hash(analysis), "brief_sha256": _hash(brief),
                "analysis": analysis, "brief": brief,
                "script_sha256": _hash(script),
                "shots_sha256": _hash(shots),
                "check_sha256": _hash(check),
                "script": script, "shots": shots, "check": check,
                "unresolved_model_issues": unresolved,
                "automatic_submit": False,
            }
            if revised_design is not None:
                draft["production_design"] = revised_design
                draft["production_design_sha256"] = _hash(revised_design)
            if repair_scope == "selected_source_boundary":
                draft["selected_source_sha256"] = _hash(excerpt)
                draft["selected_source"] = excerpt
            if repair_scope == "analysis_character_motivation":
                draft["source_quote_echoes_ignored"] = quote_echoes_ignored
            if previous_review is not None:
                draft["parent_revision_review_sha256"] = _hash(previous_review)
            draft_path = revision_artifact(self.run_dir, "REVISION_DRAFT", round_index)
            if draft_path.exists() and _read(draft_path) != draft:
                raise RuntimeError("助手返修工作稿与已有版本不符")
            _write(draft_path, draft)
            self.state["assistant_revision_status"] = draft["status"]
            self.state["assistant_revision_draft_sha256"] = _hash(draft)
            self.state.pop("assistant_revision_error", None)
            self._save()
            return self.state
        except Exception as exc:
            self.state["assistant_revision_status"] = "needs_attention"
            self.state["assistant_revision_error"] = str(exc)
            self._save()
            raise

    def promote_reviewed_assistant_revision(self, bundle: MaterialBundle) -> dict[str, Any]:
        """Export a separately reviewed revision without overwriting first-draft evidence."""
        if (self.state.get("segmented_director_binding") or {}).get("version") == "reviewed_beat_storyboard_v6":
            raise CreativeContractError("v6禁止提升未绑定状态计划的旧助手返修稿")
        self.run(bundle)
        if (self.state.get("status") != "needs_revision"
                or self.state.get("assistant_revision_status") != "review_passed_pending_handoff"):
            raise CreativeContractError("返修稿尚无绑定的助手通过结论")
        review = validated_revision_review(self.run_dir, self.state)
        if review is None or review.get("outcome") != "passed":
            raise CreativeContractError("返修稿实际复核未通过")
        draft = _read(revision_artifact(
            self.run_dir, "REVISION_DRAFT", self.state.get("assistant_revision_round_index", 1),
        ))
        if _hash(draft) != self.state["assistant_revision_draft_sha256"]:
            raise RuntimeError("返修工作稿版本不符")
        script, shots, check = draft["script"], draft["shots"], draft["check"]
        if draft["unresolved_model_issues"] or any(
            row["severity"] in ("blocking", "major") for row in check["issues"]
        ):
            raise CreativeContractError("返修稿仍有主要模型问题，不能交接")
        analysis = draft.get("analysis", _load_effective_analysis(self.run_dir))
        brief = draft.get("brief", _read(self.run_dir / "director_brief.json")["output"])
        validate_analysis(analysis, bundle.source_text, bundle.source_driver)
        validate_director_brief(brief)
        candidate = next(row for row in analysis["candidates"]
                         if row["id"] == analysis["selected_candidate_id"])
        excerpt = draft.get("selected_source", _read(self.run_dir / "SELECTED_SOURCE.json"))
        if "selected_source" in draft and _hash(excerpt) != draft.get("selected_source_sha256"):
            raise RuntimeError("返修稿的选段内容与哈希不符")
        selected_text = excerpt["text"] if bundle.source_driver == "novel" else bundle.source_text
        _validate_script_for_candidate(
            script, candidate, selected_text, bundle.source_driver,
            self.creative_focus,
        )
        validate_shots(
            shots, brief, script, selected_text, self.creative_focus,
        )
        validate_writer_check(check)
        scope_audit = _source_scope_audit(selected_text, script, bundle.source_driver)
        execution = _execution_draft(script, shots)
        capability = audit_creative_executor(shots)
        capability_path = self.run_dir / "ASSISTANT_REVISED_MEDIA_CAPABILITY_AUDIT.json"
        if capability_path.exists():
            saved_capability = _read(capability_path)
            capability["audited_at"] = saved_capability.get("audited_at")
            if saved_capability.get("schema") == "creative_media_capability_audit/v1":
                legacy_keys = ("provider", "model", "endpoint_base_url", "duration_min", "duration_max", "shots")
                if any(saved_capability.get(key) != capability.get(key) for key in legacy_keys):
                    raise RuntimeError("返修媒体能力审计与当前执行器不符")
                capability = saved_capability
            else:
                if saved_capability != capability:
                    raise RuntimeError("返修媒体能力审计与当前执行器不符")
                capability = saved_capability
        segment_plan = build_seedance_segment_plan(script, shots, capability)
        packet = _review_packet(
            analysis, brief, script, shots, check, self.state["material_sha256"],
            assistant_review_required=True, source_scope_audit=scope_audit,
        )
        packet["review_status"] = "assistant_review_passed_on_bound_revision"
        packet["assistant_revision_review_sha256"] = self.state["assistant_revision_review_sha256"]
        handoff = {
            "schema": "creative_media_handoff/v1",
            "material_sha256": self.state["material_sha256"],
            "analysis_sha256": _hash(analysis), "brief_sha256": _hash(brief),
            "selected_source_sha256": _hash(excerpt),
            "script_sha256": _hash(script), "shots_sha256": _hash(shots),
            "execution_draft_sha256": _hash(execution),
            "capability_audit_sha256": _hash(capability),
            "segment_plan_sha256": _hash(segment_plan),
            "review_packet_sha256": _hash(packet),
            "assistant_revision_review_sha256": self.state["assistant_revision_review_sha256"],
            "original_handoff_sha256": self.state["handoff_sha256"],
            "media_provider": capability["provider"], "media_model": capability["model"],
            "text_status": "assistant_review_passed_after_revision",
            "media_status": "segment_templates_ready_capability_unverified", "automatic_submit": False,
            "reason": "文本返修已由助手复看；Seedance 请求模板已映射，首尾帧、切镜及实际声画尚未核验",
        }
        outputs = {
            "ASSISTANT_REVISED_ANALYSIS.json": analysis,
            "ASSISTANT_REVISED_DIRECTOR_BRIEF.json": brief,
            "ASSISTANT_REVISED_SELECTED_SOURCE.json": excerpt,
            "ASSISTANT_REVISED_SCREENPLAY.json": script,
            "ASSISTANT_REVISED_STORYBOARD.json": shots,
            "ASSISTANT_REVISED_EXECUTION_DRAFT.json": execution,
            "ASSISTANT_REVISED_MEDIA_CAPABILITY_AUDIT.json": capability,
            "ASSISTANT_REVISED_SEEDANCE_SEGMENT_PLAN.json": segment_plan,
            "ASSISTANT_REVISED_EDITORIAL_REVIEW_PACKET.json": packet,
            "ASSISTANT_REVISED_MEDIA_HANDOFF.json": handoff,
        }
        if bundle.metadata.get("creative_brief"):
            from .reusable_production import validate_design
            design = draft.get("production_design")
            validate_design(design, shots)
            if _hash(design) != draft.get("production_design_sha256"):
                raise RuntimeError("返修资产设计未绑定已审工作稿")
            handoff["production_design_sha256"] = _hash(design)
            outputs["ASSISTANT_REVISED_PRODUCTION_DESIGN.json"] = design
        from .creative_narrative_transfer import enabled as narrative_enabled, build_transfer
        if narrative_enabled(self.state.get("narrative_focus_binding")):
            transfer = build_transfer(self.state["narrative_focus_binding"],
                bundle.metadata["creative_brief"], script, shots, segment_plan)
            outputs["ASSISTANT_REVISED_NARRATIVE_TRANSFER.json"] = transfer
            handoff["narrative_transfer_sha256"] = _hash(transfer)
        for filename, value in outputs.items():
            path = self.run_dir / filename
            if path.exists() and _read(path) != value:
                raise RuntimeError(f"返修交接产物 {filename} 已绑定不同版本")
        screenplay_path = self.run_dir / "ASSISTANT_REVISED_SCREENPLAY.md"
        if screenplay_path.exists() and screenplay_path.read_text(encoding="utf-8") != script["screenplay_markdown"]:
            raise RuntimeError("返修可读剧本已绑定不同版本")
        for filename, value in outputs.items():
            _write(self.run_dir / filename, value)
        screenplay_path.write_text(script["screenplay_markdown"], encoding="utf-8")
        self.state["status"] = "reviewed_revision_media_handoff_pending_capability"
        self.state["assistant_revision_status"] = "passed_media_handoff_pending_capability"
        self.state["revised_handoff_sha256"] = _hash(handoff)
        revised_manifest = self._write_output_manifest(
            handoff=handoff,
            filename="ASSISTANT_REVISED_CREATIVE_OUTPUT_MANIFEST.json",
            artifact_purposes={
                "materials.json": "材料清单与上下文范围",
                "CONTEXT_STRATEGY.json": "上下文能力依据、估算、分层与未逐字发送范围",
                "ASSISTANT_REVISED_ANALYSIS.json": "返修后的整体理解与候选",
                "ASSISTANT_REVISED_DIRECTOR_BRIEF.json": "返修后的导演方向",
                "ASSISTANT_REVISED_SELECTED_SOURCE.json": "返修后锁定来源",
                "ASSISTANT_REVISED_SCREENPLAY.json": "返修后结构化剧本",
                "ASSISTANT_REVISED_SCREENPLAY.md": "返修后可读剧本",
                "ASSISTANT_REVISED_STORYBOARD.json": "返修后导演分镜与连续性",
                **({"ASSISTANT_REVISED_PRODUCTION_DESIGN.json": "返修后的通用资产与镜头计划"}
                   if bundle.metadata.get("creative_brief") else {}),
                "ASSISTANT_REVISED_EDITORIAL_REVIEW_PACKET.json": "返修审核记录",
                "ASSISTANT_REVISED_EXECUTION_DRAFT.json": "返修执行预稿",
                "ASSISTANT_REVISED_MEDIA_CAPABILITY_AUDIT.json": "返修媒体执行限制",
                "ASSISTANT_REVISED_SEEDANCE_SEGMENT_PLAN.json": "返修分段执行计划",
                "ASSISTANT_REVISED_MEDIA_HANDOFF.json": "返修媒体交接与提交开关",
            },
        )
        self.state["revised_output_manifest_sha256"] = _hash(revised_manifest)
        self._save()
        return self.state

