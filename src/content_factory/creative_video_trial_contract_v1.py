"""Reusable text preparation for a source-bound opening video trial.

Whole direction owns source coverage and segmentation; opening performance
owns acting and timing only for the current prefix. Compilation owns exact
dialogue. Speech duration is a planning assumption, never measured audio or
script/media quality approval. No provider or media operation lives here.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re

from jsonschema import Draft202012Validator

VERSION = "creative_video_trial_contract/v1"
NORMAL_SPOKEN_CHARACTERS_PER_SECOND = 3.3
MAX_SEGMENT_SECONDS = 15.0
_TEXT = {"type": "string", "minLength": 1}

WHOLE_DIRECTION_RULE = (
    "整片导演只安排观察对象、情绪变化、每镜新增信息与切镜理由，按全文原顺序把全部来源各归属一个镜段。"
    "每段4至15秒，完整对白按3.3发音字/秒估算并预留接收时间；不得拆句、删字、改台词或加速压时。"
    "动作可与当下谈话自然重叠，具体起态与表演留给当前段合同。若完整原句超过时限，明确unknown，不代写缩句。"
    "不把测试采用、接口成功或时长估算解释为创作质量通过。")
OPENING_PERFORMANCE_RULE = (
    "只安排给定首段来源的连贯表演、双方行动目的、机位和自然普通话，不复写任何对白。"
    "给当前动作实际估计时长；需要自然重叠时只绑定相邻当前对白，不能借后段动作或对白。"
    "聆听表情可在对方说话时自然发生，末尾留接收窗口，不把每个表情做成独立停顿。"
    "参考图仅重建人物、服装与环境身份，首段起态由本稿建立，不能当作旧视频尾帧续段。"
    "时长未知或完整原句无法在正常速度下容纳时如实unknown，不缩放速度或修改原文。")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _obj(fields):
    return {"type": "object", "additionalProperties": False,
            "properties": fields, "required": list(fields)}


def _array(items, minimum=0, maximum=None):
    result = {"type": "array", "items": items, "minItems": minimum}
    if maximum is not None: result["maxItems"] = maximum
    return result


def catalog(script):
    """Stable B#.S## positional IDs; preserve every original value."""
    if not isinstance(script, dict) or not isinstance(script.get("beats"), list) or not script["beats"]:
        raise ValueError("selected complete script must contain nonempty beats")
    result = {}
    for bi, beat in enumerate(script["beats"], 1):
        if not isinstance(beat, dict) or not isinstance(beat.get("steps"), list) or not beat["steps"]:
            raise ValueError("every beat must contain nonempty steps")
        for si, step in enumerate(beat["steps"], 1):
            if (not isinstance(step, dict) or step.get("kind") not in ("action", "dialogue")
                    or not isinstance(step.get("speaker"), str) or not isinstance(step.get("text"), str)
                    or not step["text"].strip() or (step["kind"] == "dialogue" and not step["speaker"].strip())):
                raise ValueError("source step needs kind, speaker and unchanged nonempty text")
            ref = f"B{bi}.S{si:02d}"
            result[ref] = {"kind": step["kind"], "speaker": step["speaker"], "text": step["text"],
                "beat_id": beat.get("id", f"B{bi}"), "path": f"script.beats.{bi - 1}.steps.{si - 1}"}
    return result


def spoken_characters(source):
    return len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", source["text"]))


def spoken_seconds(source):
    return spoken_characters(source) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND if source["kind"] == "dialogue" else 0.0


def _validate(schema, value):
    error = next(iter(Draft202012Validator(schema).iter_errors(value)), None)
    if error is not None:
        raise ValueError("video trial wire invalid: " + error.message)


def _strings(value):
    if isinstance(value, str): yield value
    elif isinstance(value, list):
        for item in value: yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values(): yield from _strings(item)


def _no_dialogue_copy(value, script):
    """Native instruction prose never serves as a second dialogue channel."""
    for source in catalog(script).values():
        if source["kind"] != "dialogue": continue
        original = source["text"]
        trimmed = original.rstrip("。！？!?，,；;\n ")
        for cue in _strings(value):
            if original in cue or (len(trimmed) >= 6 and trimmed in cue):
                raise ValueError("instruction prose copied current or future source dialogue")


def _finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("video timing must be known finite seconds")
    return float(value)


def whole_direction_schema(script):
    sources = catalog(script)
    segment = _obj({"source_refs": {**_array({"enum": list(sources)}, 1, len(sources)), "uniqueItems": True},
        "information_change": deepcopy(_TEXT), "observation": deepcopy(_TEXT),
        "emotional_turn": deepcopy(_TEXT), "cut_reason": deepcopy(_TEXT),
        "target_seconds": {"type": "integer", "minimum": 4, "maximum": 15},
        "reaction_reserve_seconds": {"type": "number", "minimum": 0.3, "maximum": 3}})
    segment["properties"]["target_seconds"]["description"] = "完整原对白按3.3发音字/秒，另加reaction_reserve_seconds，不能拆句或快读。动作具体耗时留待本段表演。"
    return _obj({"script_sha256": {"const": digest(script)}, "availability": {"enum": ["known", "unknown"]},
        "whole_observation": deepcopy(_TEXT), "emotional_progression": deepcopy(_TEXT), "visual_style": deepcopy(_TEXT),
        "segments": _array(segment, 1, len(sources))})


def compile_whole_direction(raw, script):
    _validate(whole_direction_schema(script), raw)
    if raw["availability"] != "known": raise ValueError("whole direction availability unknown")
    _no_dialogue_copy(raw, script)
    sources = catalog(script)
    if [ref for segment in raw["segments"] for ref in segment["source_refs"]] != list(sources):
        raise ValueError("whole direction must own every source exactly once in original order")
    segments = []
    for index, segment in enumerate(raw["segments"], 1):
        seconds = sum(spoken_seconds(sources[ref]) for ref in segment["source_refs"])
        reserve = _finite(segment["reaction_reserve_seconds"])
        if seconds + reserve > segment["target_seconds"] + 1e-6:
            raise ValueError("whole source dialogue exceeds segment at normal speed; no splitting or acceleration")
        segments.append({**deepcopy(segment), "segment_id": f"M{index:03d}",
            "normal_dialogue_seconds": round(seconds, 6), "action_timing_resolved": False})
    return {"schema": VERSION + "/whole_direction", "script_sha256": digest(script),
        "native_sha256": digest(raw), "native": deepcopy(raw), "segments": segments,
        "whole_source_coverage_complete": True, "normal_spoken_characters_per_second": NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "timing_is_estimate": True, "measured_audio": False, "fit_scaled": False,
        "machine_script_quality": False, "actual_media_quality_passed": False}


def _opening_sources(script, refs):
    sources = catalog(script)
    if not isinstance(refs, list) or not refs or refs != list(sources)[:len(refs)]:
        raise ValueError("opening must own a complete contiguous source prefix in original order")
    return {ref: deepcopy(sources[ref]) for ref in refs}


def opening_source(script, refs):
    """Request projection: no later action or dialogue text."""
    current = _opening_sources(script, refs)
    actors = list(dict.fromkeys(q["speaker"] for q in catalog(script).values() if q["kind"] == "dialogue"))
    return {"script_sha256": digest(script), "source_refs": deepcopy(refs), "current_sources": current,
        "actor_ids": actors, "normal_spoken_characters_per_second": NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "reference_mode": "reference_image_identity_environment_reconstruction", "resume_from_old_video": False}


def opening_performance_schema(script, refs):
    current = _opening_sources(script, refs)
    actors = opening_source(script, refs)["actor_ids"]
    action_refs = [ref for ref, row in current.items() if row["kind"] == "action"]
    dialogue_refs = [ref for ref, row in current.items() if row["kind"] == "dialogue"]
    goal = _obj({"actor_id": {"enum": actors} if actors else False,
        "immediate_objective": deepcopy(_TEXT), "reception_of_current_stimulus": deepcopy(_TEXT)})
    goals = {**_array(goal, len(actors), len(actors)), "allOf": [{"contains": {
        "type": "object", "properties": {"actor_id": {"const": actor}}, "required": ["actor_id"]},
        "minContains": 1, "maxContains": 1} for actor in actors]}
    action = _obj({"source_ref": {"enum": action_refs} if action_refs else False,
        "duration_seconds": {"type": "number", "minimum": 0.25, "maximum": 15},
        "overlap_with": {"enum": [""] + dialogue_refs},
        "overlap_offset_seconds": {"type": "number", "minimum": 0, "maximum": 15}})
    action["properties"]["overlap_with"]["description"] = "可选相邻当前对白来源；不跨镜，不用未来对白。没有重叠时填空，offset=0。"
    return _obj({"script_sha256": {"const": digest(script)}, "source_refs": {"const": deepcopy(refs)},
        "availability": {"enum": ["known", "unknown"]}, "continuous_performance": deepcopy(_TEXT),
        "actor_goals": goals, "camera": deepcopy(_TEXT), "spoken_language": {"const": "zh-CN"},
        "delivery": deepcopy(_TEXT), "action_timings": _array(action, len(action_refs), len(action_refs)),
        "post_reaction_seconds": {"type": "number", "minimum": 0.3, "maximum": 3},
        "ending_state": deepcopy(_TEXT)})


def compile_opening_performance(raw, script, refs, *, user_trial_acceptance=False):
    _validate(opening_performance_schema(script, refs), raw)
    if raw["availability"] != "known": raise ValueError("opening performance availability unknown")
    if not isinstance(user_trial_acceptance, bool): raise ValueError("trial acceptance must be an explicit boolean")
    _no_dialogue_copy(raw, script)
    current = _opening_sources(script, refs)
    action_refs = [ref for ref, row in current.items() if row["kind"] == "action"]
    if [q["source_ref"] for q in raw["action_timings"]] != action_refs:
        raise ValueError("all current actions need one known timing in original order")
    actions = {q["source_ref"]: q for q in raw["action_timings"]}
    groups = {ref: [ref] for ref in refs}
    for action_ref, timing in actions.items():
        _finite(timing["duration_seconds"]); offset = _finite(timing["overlap_offset_seconds"])
        target = timing["overlap_with"]
        if target:
            if abs(refs.index(action_ref) - refs.index(target)) != 1:
                raise ValueError("natural overlap may only join an adjacent current action and dialogue")
            groups[target].append(action_ref); del groups[action_ref]
        elif offset != 0:
            raise ValueError("nonoverlapping action cannot have an overlap offset")
    schedule, elapsed = [], 0.0
    for anchor, members in sorted(groups.items(), key=lambda q: min(refs.index(ref) for ref in q[1])):
        duration = 0.0
        for ref in sorted(members, key=refs.index):
            source = current[ref]
            offset = actions[ref]["overlap_offset_seconds"] if source["kind"] == "action" and actions[ref]["overlap_with"] else 0.0
            seconds = _finite(actions[ref]["duration_seconds"]) if source["kind"] == "action" else spoken_seconds(source)
            schedule.append({"source_ref": ref, "kind": source["kind"], "speaker": source["speaker"], "original_text": source["text"],
                "start_seconds": round(elapsed + offset, 6), "end_seconds": round(elapsed + offset + seconds, 6),
                "duration_seconds": round(seconds, 6), "overlap_with": actions[ref]["overlap_with"] if source["kind"] == "action" else ""})
            duration = max(duration, offset + seconds)
        elapsed += duration
    reserve = _finite(raw["post_reaction_seconds"])
    total = elapsed + reserve
    if total > MAX_SEGMENT_SECONDS + 1e-6:
        raise ValueError("complete opening exceeds fifteen seconds at normal speed; no truncation or fit scaling")
    schedule.sort(key=lambda q: refs.index(q["source_ref"]))
    return {"schema": VERSION + "/opening", "script_sha256": digest(script), "source_refs": deepcopy(refs),
        "native_sha256": digest(raw), "native": deepcopy(raw), "schedule": schedule,
        "source_seconds": round(elapsed, 6), "total_seconds": round(total, 6),
        "duration_seconds": max(4, math.ceil(round(total, 6))), "normal_spoken_characters_per_second": NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "timing_is_estimate": True, "measured_audio": False, "fit_scaled": False,
        "source_text_unchanged": True, "complete_current_segment": True, "whole_film_complete": False,
        "reference_mode": "reference_image_identity_environment_reconstruction", "resume_from_old_video": False,
        "machine_script_quality": False, "user_trial_acceptance": user_trial_acceptance,
        "actual_media_quality_passed": False, "after_generation_content_status": "awaiting_human_review",
        "requires_human_approved_service_tail_for_next_segment": True}


def render_opening_prompt(compiled, script, *, actor_names=None):
    if compiled.get("schema") != VERSION + "/opening" or compiled.get("script_sha256") != digest(script):
        raise ValueError("opening compilation belongs to a different source")
    exact = compile_opening_performance(compiled["native"], script, compiled["source_refs"],
        user_trial_acceptance=compiled["user_trial_acceptance"])
    if exact != compiled: raise ValueError("opening compilation source, performance or timing changed")
    names = actor_names or {}
    known_actors = opening_source(script, compiled["source_refs"])["actor_ids"]
    if any(key not in known_actors or not isinstance(value, str) or not value.strip() for key, value in names.items()):
        raise ValueError("actor display names must map actual source speaker IDs")
    _no_dialogue_copy(names, script)
    raw = compiled["native"]
    lines = [f"{compiled['duration_seconds']}秒，9:16竖屏，写实剧情首段。",
        "输入图片作为reference_image，仅参考人物脸、服装和环境。重新建立本稿首段的姿态、位置与道具起态；不续接旧视频，不继承参考图片中的旧动作。",
        "自然中文普通话，正常谈话速度，边说边听、边做当下动作。表演指令不朗读。只说下列当前原对白各一次，不加后段对白、旁白、字幕或配乐。",
        "连贯表演：" + raw["continuous_performance"], "观察与机位：" + raw["camera"], "说话方式：" + raw["delivery"]]
    for goal in raw["actor_goals"]:
        label = names.get(goal["actor_id"], goal["actor_id"])
        lines.append(label + "当下行动目的：" + goal["immediate_objective"] + "；对当前刺激的接收：" + goal["reception_of_current_stimulus"])
    current = _opening_sources(script, compiled["source_refs"])
    dialogue_slots = []
    for row in compiled["schedule"]:
        source = current[row["source_ref"]]
        if source["kind"] == "dialogue":
            dialogue_slots.append((row["source_ref"], source["text"]))
            lines.append(names.get(source["speaker"], source["speaker"]) + "原对白（" + row["source_ref"] + "）：「" + source["text"] + "」")
        else:
            overlap = "；自然与" + row["overlap_with"] + "谈话重叠" if row["overlap_with"] else ""
            lines.append("当前原动作（" + row["source_ref"] + "）：" + source["text"] + overlap)
    lines.append(f"末句说完留约{raw['post_reaction_seconds']:g}秒接收窗口，保持：" + raw["ending_state"])
    expected = Counter(q["text"] for q in current.values() if q["kind"] == "dialogue")
    if Counter(text for _, text in dialogue_slots) != expected:
        raise ValueError("dialogue slots must contain current original speech exactly once")
    prompt = "\n".join(lines)
    # Long exact utterances also catch accidental dialogue copied into source
    # actions or instructions. Very short common words rely on bound slots.
    for original in {q["text"] for q in catalog(script).values() if q["kind"] == "dialogue" and len(q["text"]) >= 4}:
        if prompt.count(original) != expected[original]:
            raise ValueError("current dialogue uniqueness or future dialogue isolation failed")
    return prompt
