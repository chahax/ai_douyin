"""Whole-source direction, local acting and deterministic production planning.

This pure contract does not create media, approve pixels, authorize calls or
invent future tail-frame approval. Planned states remain planned declarations;
source quotation checks authenticate references, not their semantic sufficiency.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import re
import json

from . import creative_video_trial_contract_v1 as source
from . import creative_shared_production_contract_v1 as shared
from .creative_continuation_probe_contract_v6 import SPATIAL_DECLARATION_PATTERN

VERSION = "creative_complete_production_pipeline/v1"
MAX_FILM_SECONDS = 180
ACTOR_STATE_FIELDS = ("location", "posture", "gaze", "emotion", "knowledge")
PROP_STATE_FIELDS = ("holder", "anchor", "facing")
_TEXT = {"type": "string", "minLength": 1}
_NULL_TEXT = {"type": ["string", "null"], "minLength": 1}
_SPATIAL = re.compile(SPATIAL_DECLARATION_PATTERN)
RULE = (
    "整片导演按原文连续来源确定切点，覆盖全部来源一次，不拆句、改对白、补尾声或固定段数。"
    "逐段表演接收完整共用人物/场景规格和上一段计划终态，不能生成或改写性别、外貌、服装、所有权、声线、素材主体对应。"
    "只安排当前来源的连贯表演；完整原对白由程序注入。对白按3.3发音字/秒估计，不靠快读压时。"
    "当下动作仅可与相邻当前对白自然重叠，双方边说边听，预留末句反应，不把每个细微表情做成独立动作。"
    "提交完整ending_state，位置/姿态/视线/情绪/已知信息及道具持有/承托/朝向逐项承接；"
    "所有变化在state_changes列具体path、本段source_ref和原文quote，不变字段不用造变化；不能借未来事件解释当前变化。"
    "未知状态用null原样承接，不靠姓名或未查看的画面猜测。引用准确不证明状态变化语义合理，仍需同源全文审查。"
    "计划阶段不填写未来服务尾帧批准；视频续段必须运行器核验当前用户批准的服务原始尾帧和共用演员主体映射。"
    "不另写画面左右、景别或重设机位，保留人物相对位置与原动作；完整影片不超过180秒，单段4至15秒。")


def digest(value):
    return source.digest(value)


def _obj(fields):
    return source._obj(fields)


def _array(item, minimum=0, maximum=None):
    return source._array(item, minimum, maximum)


def _identity(manifest, script):
    return shared.validate_shared_manifest(manifest, script)


def _actors(manifest):
    return [row["id"] for row in manifest["actors"]]


def _props(manifest):
    return [row["id"] for row in manifest["props"]]


def _state_schema(manifest):
    actors = _actors(manifest)
    actor = _obj({"id": {"enum": actors}, **{key: deepcopy(_NULL_TEXT) for key in ACTOR_STATE_FIELDS}})
    prop = _obj({"id": {"enum": _props(manifest)} if _props(manifest) else False,
        "holder": {"enum": [*actors, None]}, "anchor": deepcopy(_NULL_TEXT), "facing": deepcopy(_NULL_TEXT)})
    return _obj({"scene_id": {"enum": [row["id"] for row in manifest["scenes"]]},
        "actors": _array(actor, len(actors), len(actors)),
        "props": _array(prop, len(_props(manifest)), len(_props(manifest)))})


def _validate_state(state, manifest):
    source._validate(_state_schema(manifest), state)
    for key, expected in (("actors", _actors(manifest)), ("props", _props(manifest))):
        ids = [row["id"] for row in state[key]]
        if len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise ValueError("planned state must cover the same closed actor and prop identities")


def build_initial_state(source_context, manifest):
    """Only project explicit frozen declarations; unspecified fields stay null.

    Legacy `state` prose is retained once as posture, not parsed into guessed
    location/gaze/emotion/knowledge. Those become explicit unresolved fields.
    `description` prose is retained as a prop anchor without inferring ownership.
    """
    if digest(source_context) != manifest["source_context_sha256"]:
        raise ValueError("initial state source context differs from the frozen shared provenance")
    initial = source_context["initial_state"]
    actor_bank = {row["id"]: row for row in initial.get("character_states", initial.get("actors", []))}
    prop_bank = {row["id"]: row for row in initial.get("prop_states", initial.get("props", []))}
    if set(actor_bank) != set(_actors(manifest)) or set(prop_bank) != set(_props(manifest)):
        raise ValueError("frozen initial state must declare exactly the shared actors and props")
    result = {"scene_id": initial["scene_id"], "actors": [], "props": []}
    for actor_id in _actors(manifest):
        row = actor_bank[actor_id]
        values = {key: deepcopy(row.get(key)) for key in ACTOR_STATE_FIELDS}
        if values["posture"] is None:
            values["posture"] = deepcopy(row.get("state", row.get("expected_state")))
        result["actors"].append({"id": actor_id, **values})
    for prop_id in _props(manifest):
        row = prop_bank[prop_id]
        result["props"].append({"id": prop_id, "holder": deepcopy(row.get("holder", row.get("holder_character_id"))),
            "anchor": deepcopy(row.get("anchor", row.get("state", row.get("expected_state", row.get("description"))))),
            "facing": deepcopy(row.get("facing", row.get("orientation")))})
    _validate_state(result, manifest)
    return result


def _frozen_initial(manifest):
    declared = next(row for row in manifest["provenance_catalog"] if row["source_id"] == "frozen_source_context")
    return build_initial_state(json.loads(declared["text"]), manifest)


def _range(script, completed_refs, refs):
    bank = source.catalog(script)
    ordered = list(bank)
    if not isinstance(completed_refs, list) or completed_refs != ordered[:len(completed_refs)]:
        raise ValueError("completed sources must be an original prefix, including an empty first prefix")
    if not isinstance(refs, list) or not refs or refs != ordered[len(completed_refs):len(completed_refs) + len(refs)]:
        raise ValueError("segment must immediately follow the completed prefix")
    return {ref: deepcopy(bank[ref]) for ref in refs}


def whole_direction_schema(script, manifest):
    _identity(manifest, script)
    old = source.whole_direction_schema(script)
    segment = {key: deepcopy(value) for key, value in old["properties"]["segments"]["items"]["properties"].items()
        if key != "source_refs"}
    segment["end_source_ref"] = {"enum": list(source.catalog(script)),
        "description": "本段最后完整来源；从首段起严格推进，最后一段到全文最后来源。程序展开连续范围。"}
    fields = {key: deepcopy(value) for key, value in old["properties"].items() if key not in ("script_sha256", "segments")}
    fields["segments"] = _array(_obj(segment), 1, len(source.catalog(script)))
    return _obj(fields)


def compile_direction(raw, script, manifest):
    source._validate(whole_direction_schema(script, manifest), raw)
    if raw["availability"] != "known":
        raise ValueError("whole direction availability unknown")
    shared.assert_creative_does_not_override(raw)
    source._no_dialogue_copy(raw, script)
    ordered = list(source.catalog(script))
    cursor = 0
    segments = []
    for row in raw["segments"]:
        end = ordered.index(row["end_source_ref"]) + 1
        if end <= cursor:
            raise ValueError("whole direction cut endpoint must strictly advance")
        segments.append({**{key: deepcopy(value) for key, value in row.items() if key != "end_source_ref"},
            "source_refs": ordered[cursor:end]})
        cursor = end
    if cursor != len(ordered):
        raise ValueError("whole direction must reach the final source, without a missing tail")
    projected = {key: deepcopy(value) for key, value in raw.items() if key != "segments"}
    projected.update(script_sha256=digest(script), segments=segments)
    compiled = source.compile_whole_direction(projected, script)
    total = sum(row["target_seconds"] for row in segments)
    if total > MAX_FILM_SECONDS:
        raise ValueError("whole direction exceeds the complete film 180 second boundary")
    return {"schema": VERSION + "/direction", "script_sha256": digest(script), "global_manifest_sha256": digest(manifest),
        "native": deepcopy(raw), "native_sha256": digest(raw), "segments": deepcopy(compiled["segments"]),
        "total_target_seconds": total, "whole_source_coverage_complete": True,
        "fixed_response_metadata_generated_by_model": False, "creative_fields_rewritten": False,
        "planning_scope": "whole_film", "timing_is_estimate": True,
        "machine_script_quality": False, "actual_media_quality_passed": False}


def _state_paths(manifest):
    return ["scene_id"] + [f"actors.{aid}.{key}" for aid in _actors(manifest) for key in ACTOR_STATE_FIELDS] + [
        f"props.{pid}.{key}" for pid in _props(manifest) for key in PROP_STATE_FIELDS]


def _state_value(state, path):
    if path == "scene_id":
        return state["scene_id"]
    collection, entity_id, field = path.split(".")
    return next(row[field] for row in state[collection] if row["id"] == entity_id)


def _segment(segment, script, completed_refs):
    fields = ("information_change", "observation", "emotional_turn", "cut_reason", "target_seconds", "reaction_reserve_seconds", "source_refs")
    if not isinstance(segment, dict) or any(key not in segment for key in fields):
        raise ValueError("compiled whole direction segment required")
    _range(script, completed_refs, segment["source_refs"])
    source._validate(source.whole_direction_schema(script)["properties"]["segments"]["items"],
        {key: deepcopy(segment[key]) for key in fields})
    return segment


def performance_schema(script, manifest, segment, planned_initial_state, completed_refs):
    _identity(manifest, script)
    _segment(segment, script, completed_refs)
    _validate_state(planned_initial_state, manifest)
    current = _range(script, completed_refs, segment["source_refs"])
    refs = list(current)
    actors = _actors(manifest)
    actions = [ref for ref, row in current.items() if row["kind"] == "action"]
    dialogues = [ref for ref, row in current.items() if row["kind"] == "dialogue"]
    stimuli = _obj({"phase": {"enum": ["completed", "current"]},
        "source_ref": {"enum": completed_refs + refs}, "channel": {"enum": ["spoken", "visible"]}})
    goal = _obj({"actor_id": {"enum": actors}, "immediate_objective": deepcopy(_TEXT),
        "source_reception": _obj({"stimuli": _array(stimuli), "response": deepcopy(_TEXT)})})
    delivery_rows = [_obj({"source_ref": {"const": ref}, "speech_tone": deepcopy(_TEXT), "listener_behavior": deepcopy(_TEXT)}) for ref in dialogues]
    action_rows = []
    for ref in actions:
        adjacent = [candidate for candidate in dialogues if abs(refs.index(ref) - refs.index(candidate)) == 1]
        timing = _obj({"source_ref": {"const": ref}, "duration_seconds": {"type": "number", "minimum": .25, "maximum": 15},
            "overlap_with": {"enum": ["", *adjacent]}, "overlap_offset_seconds": {"type": "number", "minimum": 0, "maximum": 15}})
        timing["allOf"] = [{"if": {"properties": {"overlap_with": {"const": ""}}},
            "then": {"properties": {"overlap_offset_seconds": {"const": 0}}}}]
        action_rows.append(timing)
    def fixed_rows(rows):
        result = {"type": "array", "items": False, "minItems": len(rows), "maxItems": len(rows)}
        if rows:
            result["prefixItems"] = rows
        return result
    return _obj({"availability": {"enum": ["known", "unknown"]}, "continuous_performance": deepcopy(_TEXT),
        "actor_goals": _array(goal, len(actors), len(actors)), "dialogue_delivery": fixed_rows(delivery_rows),
        "action_timings": fixed_rows(action_rows), "post_reaction_seconds": {"type": "number", "minimum": .3, "maximum": 3},
        "ending_state": _state_schema(manifest), "state_changes": _array(_obj({
            "path": {"enum": _state_paths(manifest)}, "source_ref": {"enum": refs}, "quote": deepcopy(_TEXT)}))})


def _prose_only(raw):
    result = deepcopy(raw)
    # Evidence quotations may legitimately reproduce source words. They never
    # become instructions or an extra spoken channel in the actual video prompt.
    result.pop("state_changes", None)
    return result


def _state_changes(raw, script, manifest, initial, refs):
    _validate_state(raw["ending_state"], manifest)
    changed = {path for path in _state_paths(manifest) if _state_value(initial, path) != _state_value(raw["ending_state"], path)}
    rows = raw["state_changes"]
    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)) or set(paths) != changed:
        raise ValueError("state changes need exactly one current source evidence for each changed field, and none for unchanged fields")
    bank = source.catalog(script)
    for row in rows:
        if row["source_ref"] not in refs or row["quote"] not in bank[row["source_ref"]]["text"]:
            raise ValueError("planned state evidence must quote an actual current source")
    if initial["scene_id"] != raw["ending_state"]["scene_id"]:
        evidence = next(row for row in rows if row["path"] == "scene_id")
        permitted = any(row["source_ref"] == evidence["source_ref"] and row["from_scene_id"] == initial["scene_id"] and
            row["to_scene_id"] == raw["ending_state"]["scene_id"] for row in manifest["scene_transition_permissions"])
        if not permitted:
            raise ValueError("planned scene change requires a frozen source-event transition permission")


def _compile_schedule(raw, current):
    refs = list(current)
    actions = {row["source_ref"]: row for row in raw["action_timings"]}
    groups = {ref: [ref] for ref in refs}
    for ref, row in actions.items():
        source._finite(row["duration_seconds"])
        source._finite(row["overlap_offset_seconds"])
        if row["overlap_with"]:
            groups[row["overlap_with"]].append(ref)
            del groups[ref]
    elapsed = 0.0
    schedule = []
    for _, members in sorted(groups.items(), key=lambda pair: min(refs.index(ref) for ref in pair[1])):
        group_seconds = 0.0
        for ref in sorted(members, key=refs.index):
            row = current[ref]
            overlap = actions[ref]["overlap_with"] if row["kind"] == "action" else ""
            offset = source._finite(actions[ref]["overlap_offset_seconds"]) if overlap else 0.0
            seconds = source._finite(actions[ref]["duration_seconds"]) if row["kind"] == "action" else source.spoken_seconds(row)
            schedule.append({"source_ref": ref, "kind": row["kind"], "speaker": row["speaker"], "original_text": row["text"],
                "start_seconds": round(elapsed + offset, 6), "end_seconds": round(elapsed + offset + seconds, 6),
                "duration_seconds": round(seconds, 6), "overlap_with": overlap})
            group_seconds = max(group_seconds, offset + seconds)
        elapsed += group_seconds
    total = elapsed + source._finite(raw["post_reaction_seconds"])
    schedule.sort(key=lambda row: refs.index(row["source_ref"]))
    return schedule, elapsed, total


def compile_performance(raw, script, manifest, segment, planned_initial_state, completed_refs):
    source._validate(performance_schema(script, manifest, segment, planned_initial_state, completed_refs), raw)
    if raw["availability"] != "known":
        raise ValueError("local performance availability unknown")
    if not completed_refs and planned_initial_state != _frozen_initial(manifest):
        raise ValueError("first planned state must exactly preserve the frozen initial source")
    shared.assert_creative_does_not_override(raw)
    prose = _prose_only(raw)
    source._no_dialogue_copy(prose, script)
    for text in source._strings(prose):
        if _SPATIAL.search(text):
            raise ValueError("local performance must not invent screen coordinates or reset a camera")
    current = _range(script, completed_refs, segment["source_refs"])
    goals = raw["actor_goals"]
    ids = [row["actor_id"] for row in goals]
    if len(ids) != len(set(ids)) or set(ids) != set(_actors(manifest)):
        raise ValueError("local actor goals must cover the closed cast exactly once")
    bank = source.catalog(script)
    for goal in goals:
        seen = set()
        for stimulus in goal["source_reception"]["stimuli"]:
            ref = stimulus["source_ref"]
            expected_phase = "current" if ref in current else "completed"
            expected_channel = "spoken" if bank[ref]["kind"] == "dialogue" else "visible"
            if stimulus["phase"] != expected_phase or stimulus["channel"] != expected_channel:
                raise ValueError("reception phase and channel must match completed/current source and kind")
            if expected_channel == "spoken" and bank[ref]["speaker"] == goal["actor_id"]:
                raise ValueError("own speech is not received external spoken stimulus")
            key = (expected_phase, ref, expected_channel)
            if key in seen:
                raise ValueError("duplicate reception stimulus")
            seen.add(key)
    _state_changes(raw, script, manifest, planned_initial_state, list(current))
    schedule, elapsed, total = _compile_schedule(raw, current)
    if raw["post_reaction_seconds"] + 1e-6 < segment["reaction_reserve_seconds"]:
        raise ValueError("local performance cannot consume the director's reserved reaction window")
    if total > 15 + 1e-6 or total > segment["target_seconds"] + 1e-6:
        raise ValueError("complete local performance exceeds its planned window at normal speech speed")
    return {"schema": VERSION + "/performance", "script_sha256": digest(script), "global_manifest_sha256": digest(manifest),
        "segment": deepcopy(segment), "segment_id": segment.get("segment_id"), "source_refs": list(current),
        "completed_refs": deepcopy(completed_refs), "native": deepcopy(raw), "native_sha256": digest(raw),
        "planned_initial_state": deepcopy(planned_initial_state), "planned_ending_state": deepcopy(raw["ending_state"]),
        "planned_initial_state_sha256": digest(planned_initial_state), "planned_ending_state_sha256": digest(raw["ending_state"]),
        "schedule": schedule, "source_seconds": round(elapsed, 6), "total_seconds": round(total, 6),
        "duration_seconds": max(4, math.ceil(round(total, 6))), "post_reaction_seconds": raw["post_reaction_seconds"],
        "normal_spoken_characters_per_second": source.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "timing_is_estimate": True, "measured_audio": False, "fit_scaled": False,
        "planning_scope": "whole_film_segment", "state_change_quotes_authentic": True,
        "state_change_semantic_support_reviewed": False, "source_text_unchanged": True,
        "service_tail_approval_verified": False, "actual_media_quality_passed": False,
        "after_generation_content_status": "awaiting_human_review"}


def compile_complete(direction, performances, script, manifest, initial_state):
    exact_direction = compile_direction(direction["native"], script, manifest)
    if direction != exact_direction:
        raise ValueError("whole direction changed after source-bound compilation")
    _validate_state(initial_state, manifest)
    if initial_state != _frozen_initial(manifest):
        raise ValueError("whole-film initial state must exactly preserve the frozen source")
    if len(performances) != len(direction["segments"]):
        raise ValueError("complete handoff requires every directed segment performance")
    completed = []
    previous = deepcopy(initial_state)
    for segment, performance in zip(direction["segments"], performances):
        exact = compile_performance(performance["native"], script, manifest, segment, previous, completed)
        if exact != performance:
            raise ValueError("performance source, global identity, timing or planned state chain changed")
        completed.extend(segment["source_refs"])
        previous = deepcopy(exact["planned_ending_state"])
    if completed != list(source.catalog(script)):
        raise ValueError("complete handoff must cover the full original source exactly once")
    total = sum(row["duration_seconds"] for row in performances)
    if total > MAX_FILM_SECONDS:
        raise ValueError("complete compiled film exceeds 180 seconds")
    return {"schema": VERSION + "/complete", "script_sha256": digest(script), "global_manifest_sha256": digest(manifest),
        "direction": deepcopy(direction), "performances": deepcopy(performances), "initial_state": deepcopy(initial_state),
        "final_planned_state": previous, "source_refs": completed, "total_duration_seconds": total,
        "whole_source_coverage_complete": True, "whole_film_performance_complete": True, "planned_state_chain_complete": True,
        "planning_scope": "whole_film", "source_text_unchanged": True, "source_state_semantic_review_complete": False,
        "requires_independent_full_production_text_review": True, "machine_script_quality": False,
        "actual_media_quality_passed": False, "human_approved": False, "calls_authorized": False,
        "future_tail_approval_invented": False, "video_continuation_requires_actual_approved_service_tail": True}


def _state_lines(state, manifest, label):
    names = {row["id"]: row["name"] for row in manifest["actors"]}
    lines = [label + "（计划声明，实际连续性以本次输入与人工审核为准）："]
    actor_labels = {"location": "位置", "posture": "姿态", "gaze": "观察/朝向", "emotion": "情绪", "knowledge": "已接收信息"}
    for actor in state["actors"]:
        text = "；".join(actor_labels[key] + "：" + (actor[key] if actor[key] is not None else "未明示，不能猜测") for key in ACTOR_STATE_FIELDS)
        lines.append(names[actor["id"]] + "：" + text)
    for prop in state["props"]:
        holder = names.get(prop["holder"], prop["holder"]) if prop["holder"] is not None else "无人持有/未声明持有人；不可据此判定所有权"
        lines.append(f"道具 {prop['id']}：持有={holder}；承托={prop['anchor'] or '未明示'}；朝向={prop['facing'] or '未明示'}。")
    return lines


def render_prompt(compiled_segment, script, manifest, shared_context=None):
    """Render current speech once; future speech never enters the video prompt.

    `shared_context` must be the separately compiled actual bootstrap/approved
    reference context. Without it this is an offline planning preview only.
    """
    exact = compile_performance(compiled_segment["native"], script, manifest, compiled_segment["segment"],
        compiled_segment["planned_initial_state"], compiled_segment["completed_refs"])
    if exact != compiled_segment:
        raise ValueError("performance/source/global manifest/state compilation changed before rendering")
    names = {row["id"]: row["name"] for row in manifest["actors"]}
    source._no_dialogue_copy(names, script)
    native = compiled_segment["native"]
    opening = not compiled_segment["completed_refs"]
    lines = [f"{compiled_segment['duration_seconds']}秒，9:16竖屏，写实剧情{'首段' if opening else '续段'}。"]
    if shared_context is None:
        lines.append("离线全片计划预览，尚未绑定本段实际图像素材或用户尾帧批准，不可直接视为可派发请求。")
        lines.append("共用演员档案：" + "、".join(f"{row['id']}={row['name']}" for row in manifest["actors"]))
        for row in manifest["actors"]:
            fields = "；".join(f"{key}={row['profile'][key]['value'] if row['profile'][key]['status'] == 'known' else '未知'}" for key in shared.PROFILE_FIELDS)
            lines.append(row["name"] + "固定规格：" + fields)
    else:
        if shared_context.get("global_manifest_sha256") != digest(manifest) or shared_context.get("script_sha256") != digest(script) or shared_context.get("source_refs") != compiled_segment["source_refs"]:
            raise ValueError("actual shared request context must bind this same source and fixed manifest")
        if shared.text_sha256(shared_context["prompt_fragment"]) != shared_context["prompt_fragment_sha256"]:
            raise ValueError("shared prompt fragment changed")
        dynamic = shared_context["projection"]["dynamic_state"]
        if dynamic["completed_source_refs"] != compiled_segment["completed_refs"] or dynamic["scene_id"] != compiled_segment["planned_initial_state"]["scene_id"]:
            raise ValueError("actual shared dynamic source prefix or scene differs from this segment plan")
        exact_shared = shared.compile_segment_context(manifest, script, dynamic,
            compiled_segment["source_refs"], shared_context["projection"]["scene_transition"],
            shared_context["media_binding"], shared_context["casting_bootstrap"])
        if exact_shared != shared_context:
            raise ValueError("actual shared projection or reference approval declarations changed")
        if opening and shared_context["media_binding"]["role"] == "first_frame":
            raise ValueError("new whole-film first segment must not pretend to continue an old tail")
        if not opening and shared_context["media_binding"]["role"] != "first_frame":
            raise ValueError("later segment requires the actual approved original service tail")
        lines.append(shared_context["prompt_fragment"])
    lines.extend(["自然中文普通话，正常谈话速度。边说边听，动作与当下谈话自然重叠，不把细微表情拆成机械停顿。",
        "表演文字不朗读；仅说下列当前原对白各一次，不说前段或后段对白，不添加旁白、字幕、配乐或其他人物。",
        "空间布局与人物相对位置连续，不能凭姓名推断画面左右或改变固定身份。",
        "连贯表演：" + native["continuous_performance"]])
    lines.extend(_state_lines(compiled_segment["planned_initial_state"], manifest, "本段计划起态"))
    for goal in native["actor_goals"]:
        lines.append(names[goal["actor_id"]] + "当下行动目的：" + goal["immediate_objective"] + "；接收与回应：" + goal["source_reception"]["response"])
    delivery = {row["source_ref"]: row for row in native["dialogue_delivery"]}
    slots = []
    for row in compiled_segment["schedule"]:
        if row["kind"] == "dialogue":
            slots.append(row["original_text"])
            cue = delivery[row["source_ref"]]
            lines.append(names[row["speaker"]] + "原对白（" + row["source_ref"] + "）：「" + row["original_text"] + "」；语气：" + cue["speech_tone"] + "；听者：" + cue["listener_behavior"])
        else:
            overlap = "；自然与" + row["overlap_with"] + "谈话重叠" if row["overlap_with"] else ""
            lines.append("当前原动作（" + row["source_ref"] + "）：" + row["original_text"] + overlap)
    lines.append(f"末句结束后留约{native['post_reaction_seconds']:g}秒接收窗口。")
    lines.extend(_state_lines(native["ending_state"], manifest, "本段计划终态"))
    current = _range(script, compiled_segment["completed_refs"], compiled_segment["source_refs"])
    expected = Counter(row["text"] for row in current.values() if row["kind"] == "dialogue")
    if Counter(slots) != expected:
        raise ValueError("video prompt speech slots must preserve each current original dialogue once")
    prompt = "\n".join(lines)
    for text in {row["text"] for row in source.catalog(script).values() if row["kind"] == "dialogue" and len(row["text"]) >= 4}:
        if prompt.count(text) != expected[text]:
            raise ValueError("current original dialogue uniqueness or future/prior speech isolation failed")
    return prompt
