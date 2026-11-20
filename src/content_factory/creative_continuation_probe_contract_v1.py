"""Source-bound continuation preparation, independent of opening-prefix logic.

The runner owns evidence that the previous service tail was approved. This
pure contract owns adjacent source scope, unchanged dialogue and estimated
timing; neither compilation nor an API success approves any media content.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v1"
TRIAL_ROUTE = "isolated_continuation_probe"
RULE = (
    "只安排紧接已完成来源的本段连续范围，不复演前段，不预演未来来源。"
    "first_frame必须由运行器核验为上一段经用户批准的服务原始尾帧，连续承接人物、服装工牌、空间位置与道具状态；不能重新构造人物或工牌。"
    "完整对白由程序取源，按3.3发音字/秒估算正常普通话，不复写台词、不拆句、不删字、不快读压时。"
    "当前动作可与相邻当前对白自然重叠，边说边听，末尾留0.3至3秒反应；每次请求4至15秒。"
    "current_direction仅供独立当前段审查，不作为旁白或第二份视频表演指令。"
    "整片规划仍未通过，本段生成后仍为awaiting_human_review，尾帧批准不由此合同推定。")


def _current_sources(script, completed_refs, refs):
    sources = base.catalog(script)
    ordered = list(sources)
    if (not isinstance(completed_refs, list) or not completed_refs
            or len(completed_refs) >= len(ordered)
            or completed_refs != ordered[:len(completed_refs)]):
        raise ValueError("completed sources must be a nonempty original prefix with a next source")
    if (not isinstance(refs, list) or not refs
            or refs != ordered[len(completed_refs):len(completed_refs) + len(refs)]):
        raise ValueError("continuation must own the immediately adjacent contiguous source range")
    return {ref: deepcopy(sources[ref]) for ref in refs}


def continuation_source(script, completed_refs, refs):
    """Request projection: prior and future text are not part of this segment."""
    current = _current_sources(script, completed_refs, refs)
    actors = list(dict.fromkeys(q["speaker"] for q in base.catalog(script).values() if q["kind"] == "dialogue"))
    return {"script_sha256": base.digest(script), "completed_refs": deepcopy(completed_refs),
        "source_refs": deepcopy(refs), "current_sources": current, "actor_ids": actors,
        "normal_spoken_characters_per_second": base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "reference_mode": "first_frame_approved_service_tail_continuation",
        "requires_approved_service_tail_before_media": True, "service_tail_approval_verified": False}


def _performance_schema(script, completed_refs, refs):
    current = _current_sources(script, completed_refs, refs)
    actors = continuation_source(script, completed_refs, refs)["actor_ids"]
    actions = [ref for ref, row in current.items() if row["kind"] == "action"]
    dialogues = [ref for ref, row in current.items() if row["kind"] == "dialogue"]
    goal = base._obj({"actor_id": {"enum": actors} if actors else False,
        "immediate_objective": deepcopy(base._TEXT), "reception_of_current_stimulus": deepcopy(base._TEXT)})
    goals = base._array(goal, len(actors), len(actors))
    if actors:
        goals["allOf"] = [{"contains": {
        "type": "object", "properties": {"actor_id": {"const": actor}}, "required": ["actor_id"]},
        "minContains": 1, "maxContains": 1} for actor in actors]
    timings = []
    for action_ref in actions:
        adjacent = [ref for ref in dialogues if abs(refs.index(action_ref) - refs.index(ref)) == 1]
        action = base._obj({"source_ref": {"const": action_ref},
            "duration_seconds": {"type": "number", "minimum": 0.25, "maximum": 15},
            "overlap_with": {"enum": [""] + adjacent},
            "overlap_offset_seconds": {"type": "number", "minimum": 0, "maximum": 15}})
        action["properties"]["overlap_with"]["description"] = "只可重叠相邻当前对白；填空时offset必须为0，不能绑定前段或未来对白。"
        action["allOf"] = [{"if": {"properties": {"overlap_with": {"const": ""}}},
            "then": {"properties": {"overlap_offset_seconds": {"const": 0}}}}]
        timings.append(action)
    timing_schema = {"type": "array", "items": False,
        "minItems": len(actions), "maxItems": len(actions)}
    if timings:
        timing_schema["prefixItems"] = timings
    return base._obj({"script_sha256": {"const": base.digest(script)}, "source_refs": {"const": deepcopy(refs)},
        "availability": {"enum": ["known", "unknown"]}, "continuous_performance": deepcopy(base._TEXT),
        "actor_goals": goals, "camera": deepcopy(base._TEXT), "spoken_language": {"const": "zh-CN"},
        "delivery": deepcopy(base._TEXT), "action_timings": timing_schema,
        "post_reaction_seconds": {"type": "number", "minimum": 0.3, "maximum": 3},
        "ending_state": deepcopy(base._TEXT)})


def continuation_probe_schema(script, completed_refs, refs):
    _current_sources(script, completed_refs, refs)
    direction = base._obj({key: deepcopy(base._TEXT) for key in
        ("information_change", "observation", "stimulus_reaction", "cut_reason")})
    return base._obj({"script_sha256": {"const": base.digest(script)}, "source_refs": {"const": deepcopy(refs)},
        "current_direction": direction, "performance": _performance_schema(script, completed_refs, refs)})


def _compile_performance(raw, script, completed_refs, refs):
    # An independent range validator is essential: the frozen opening compiler
    # intentionally rejects any non-prefix and is never called here.
    base._validate(_performance_schema(script, completed_refs, refs), raw)
    if raw["availability"] != "known":
        raise ValueError("continuation performance availability unknown")
    base._no_dialogue_copy(raw, script)
    current = _current_sources(script, completed_refs, refs)
    actions = {row["source_ref"]: row for row in raw["action_timings"]}
    groups = {ref: [ref] for ref in refs}
    for action_ref, timing in actions.items():
        base._finite(timing["duration_seconds"])
        base._finite(timing["overlap_offset_seconds"])
        if timing["overlap_with"]:
            groups[timing["overlap_with"]].append(action_ref)
            del groups[action_ref]
    schedule, elapsed = [], 0.0
    for _, members in sorted(groups.items(), key=lambda item: min(refs.index(ref) for ref in item[1])):
        duration = 0.0
        for ref in sorted(members, key=refs.index):
            source = current[ref]
            overlap = actions[ref]["overlap_with"] if source["kind"] == "action" else ""
            offset = base._finite(actions[ref]["overlap_offset_seconds"]) if overlap else 0.0
            seconds = base._finite(actions[ref]["duration_seconds"]) if source["kind"] == "action" else base.spoken_seconds(source)
            schedule.append({"source_ref": ref, "kind": source["kind"], "speaker": source["speaker"],
                "original_text": source["text"], "start_seconds": round(elapsed + offset, 6),
                "end_seconds": round(elapsed + offset + seconds, 6), "duration_seconds": round(seconds, 6),
                "overlap_with": overlap})
            duration = max(duration, offset + seconds)
        elapsed += duration
    total = elapsed + base._finite(raw["post_reaction_seconds"])
    if total > base.MAX_SEGMENT_SECONDS + 1e-6:
        raise ValueError("complete continuation exceeds fifteen seconds at normal speed; no truncation or fit scaling")
    schedule.sort(key=lambda row: refs.index(row["source_ref"]))
    return {"schema": VERSION + "/performance", "script_sha256": base.digest(script),
        "source_refs": deepcopy(refs), "native": deepcopy(raw), "native_sha256": base.digest(raw),
        "schedule": schedule, "source_seconds": round(elapsed, 6), "total_seconds": round(total, 6),
        "duration_seconds": max(4, math.ceil(round(total, 6))),
        "normal_spoken_characters_per_second": base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "timing_is_estimate": True, "measured_audio": False, "fit_scaled": False}


def compile_continuation_probe(raw, script, completed_refs, refs):
    base._validate(continuation_probe_schema(script, completed_refs, refs), raw)
    base._no_dialogue_copy(raw["current_direction"], script)
    performance = _compile_performance(raw["performance"], script, completed_refs, refs)
    return {"schema": VERSION, "script_sha256": base.digest(script), "completed_refs": deepcopy(completed_refs),
        "source_refs": deepcopy(refs), "native": deepcopy(raw), "native_sha256": base.digest(raw),
        "current_direction": deepcopy(raw["current_direction"]), "performance_compiled": performance,
        "trial_route": TRIAL_ROUTE, "whole_direction_accepted": False, "whole_film_performance_complete": False,
        "whole_film_complete": False, "machine_quality": False, "machine_script_quality": False,
        "user_trial_acceptance": True, "source_text_unchanged": True, "all_native_values_preserved": True,
        "reference_mode": "first_frame_approved_service_tail_continuation", "resume_from_previous_segment": True,
        "requires_approved_service_tail_before_media": True, "service_tail_approval_verified": False,
        "requires_independent_current_review": True, "independent_current_review_complete": False,
        "requires_independent_current_review_criteria_count": 6, "actual_media_quality_passed": False,
        "after_generation_content_status": "awaiting_human_review",
        "requires_human_approved_service_tail_for_next_segment": True}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("continuation probe belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"], compiled["source_refs"])
    if exact != compiled:
        raise ValueError("continuation native, source range or timing compilation changed")
    names = {} if actor_names is None else actor_names
    actors = continuation_source(script, compiled["completed_refs"], compiled["source_refs"])["actor_ids"]
    if not isinstance(names, dict) or any(key not in actors or not isinstance(value, str) or not value.strip() for key, value in names.items()):
        raise ValueError("actor display names must map actual source speaker IDs")
    base._no_dialogue_copy(names, script)
    performance = compiled["performance_compiled"]
    raw = performance["native"]
    lines = [f"{performance['duration_seconds']}秒，9:16竖屏，写实剧情当前续段。",
        "输入图片作为first_frame，须是上一段经用户批准的生成服务原始尾帧。连续承接人物、服装和工牌、空间、坐站位置以及纸笔文件夹状态；不重新造人或工牌，不重演前段动作。",
        "自然中文普通话，正常谈话速度，边说边听、边做当下动作。表演指令不朗读。只说下列当前原对白各一次，不加前段或后段对白、旁白、字幕或配乐。",
        "连贯表演：" + raw["continuous_performance"], "观察与机位：" + raw["camera"], "说话方式：" + raw["delivery"]]
    for goal in raw["actor_goals"]:
        label = names.get(goal["actor_id"], goal["actor_id"])
        lines.append(label + "当下行动目的：" + goal["immediate_objective"] + "；对当前刺激的接收：" + goal["reception_of_current_stimulus"])
    current = _current_sources(script, compiled["completed_refs"], compiled["source_refs"])
    dialogue_slots = []
    for row in performance["schedule"]:
        source = current[row["source_ref"]]
        if source["kind"] == "dialogue":
            dialogue_slots.append(source["text"])
            lines.append(names.get(source["speaker"], source["speaker"]) + "原对白（" + row["source_ref"] + "）：「" + source["text"] + "」")
        else:
            overlap = "；自然与" + row["overlap_with"] + "谈话重叠" if row["overlap_with"] else ""
            lines.append("当前原动作（" + row["source_ref"] + "）：" + source["text"] + overlap)
    lines.append(f"末句说完留约{raw['post_reaction_seconds']:g}秒接收窗口，保持：" + raw["ending_state"])
    expected = Counter(row["text"] for row in current.values() if row["kind"] == "dialogue")
    if Counter(dialogue_slots) != expected:
        raise ValueError("dialogue slots must contain current original speech exactly once")
    prompt = "\n".join(lines)
    for text in {row["text"] for row in base.catalog(script).values() if row["kind"] == "dialogue" and len(row["text"]) >= 4}:
        if prompt.count(text) != expected[text]:
            raise ValueError("current dialogue uniqueness or prior/future dialogue isolation failed")
    return prompt
