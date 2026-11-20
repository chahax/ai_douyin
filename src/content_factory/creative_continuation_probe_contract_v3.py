"""Separate source references, reception prose and per-dialogue delivery.

Original speech is injected only by the frozen source renderer. A deterministic
v2 projection preserves every native creative string verbatim; it is not a
content repair. Acting meaning and continuity still need independent review.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_continuation_probe_contract_v1 as timing
from . import creative_continuation_probe_contract_v2 as prior
from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v3"
TRIAL_ROUTE = prior.TRIAL_ROUTE
RULE = timing.RULE + (
    "本版本以source_reception.stimuli填写刺激来源，以source_reception.response只写短自然反应；"
    "不再填写reception_of_current_stimulus或current_stimuli。"
    "每名角色的stimuli至少一项；spoken仅引用另一speaker的当前原对白，visible仅引用当前原动作，不能把自己的话或纸面可见字当作另一角色说出的刺激。"
    "dialogue_delivery每句当前原对白恰一行，只用source_ref引用，speech_tone写语气，listener_behavior写听者同步行为，不能复抄完整原对白。"
    "连续演法、人物目的、反应、语气、听者行为、机位、终态及当前方向都不能成为复写台词的通道。"
    "来源编号和spoken/visible是审查元数据，不能朗读。原对白由程序只从源文插入一次。"
    "继承姿态、是否无因抬眼复位等自由文字语义仍须独立8项审查，不以引用形式通过推定表演正确。")


def continuation_source(script, completed_refs, refs):
    return prior.continuation_source(script, completed_refs, refs)


def continuation_probe_schema(script, completed_refs, refs):
    schema = deepcopy(prior.continuation_probe_schema(script, completed_refs, refs))
    performance = schema["properties"]["performance"]
    goal = performance["properties"]["actor_goals"]["items"]
    stimuli = goal["properties"].pop("current_stimuli")
    goal["properties"].pop("reception_of_current_stimulus")
    goal["required"] = [key for key in goal["required"] if key not in ("current_stimuli", "reception_of_current_stimulus")]
    response = {**deepcopy(base._TEXT), "maxLength": 180,
        "description": "只写当前刺激引起的短自然反应，不复抄对白，不先演未来反应。"}
    goal["properties"]["source_reception"] = base._obj({"stimuli": stimuli, "response": response})
    goal["required"].append("source_reception")
    for rule in goal.get("allOf", []):
        items = rule["then"]["properties"].pop("current_stimuli")["items"]
        rule["then"]["properties"]["source_reception"] = {"properties": {"stimuli": {"items": items}}}
    performance["properties"].pop("delivery")
    performance["required"].remove("delivery")
    current = continuation_source(script, completed_refs, refs)["current_sources"]
    dialogue_refs = [ref for ref, row in current.items() if row["kind"] == "dialogue"]
    rows = [base._obj({"source_ref": {"const": ref},
        "speech_tone": {**deepcopy(base._TEXT), "maxLength": 120, "description": "只写说话语气，不复写本句台词。"},
        "listener_behavior": {**deepcopy(base._TEXT), "maxLength": 180, "description": "只写此句期间的听者自然行为，不复写对白或新增未来行为。"}})
        for ref in dialogue_refs]
    delivery = {"type": "array", "items": False, "minItems": len(rows), "maxItems": len(rows)}
    if rows:
        delivery["prefixItems"] = rows
    performance["properties"]["dialogue_delivery"] = delivery
    performance["required"].append("dialogue_delivery")
    return schema


def _free_text_fields(raw):
    for key, value in raw["current_direction"].items():
        yield "current_direction." + key, value
    performance = raw["performance"]
    for key in ("continuous_performance", "camera", "ending_state"):
        yield "performance." + key, performance[key]
    for index, goal in enumerate(performance["actor_goals"]):
        prefix = f"performance.actor_goals[{index}]"
        yield prefix + ".immediate_objective", goal["immediate_objective"]
        yield prefix + ".source_reception.response", goal["source_reception"]["response"]
    for index, row in enumerate(performance["dialogue_delivery"]):
        for key in ("speech_tone", "listener_behavior"):
            yield f"performance.dialogue_delivery[{index}].{key}", row[key]


def _validate_prose(raw, script):
    for path, text in _free_text_fields(raw):
        try:
            base._no_dialogue_copy(text, script)
        except ValueError as exc:
            raise ValueError(str(exc) + " at " + path) from exc


def _projection(raw):
    """Create old renderer fields from references without changing any prose."""
    projected = deepcopy(raw)
    performance = projected["performance"]
    for goal in performance["actor_goals"]:
        reception = goal.pop("source_reception")
        goal["current_stimuli"] = reception["stimuli"]
        goal["reception_of_current_stimulus"] = reception["response"]
    rows = performance.pop("dialogue_delivery")
    performance["delivery"] = "\n".join(
        "对白来源(" + row["source_ref"] + ")的语气：" + row["speech_tone"]
        + "；听者同步行为：" + row["listener_behavior"] for row in rows) if rows else "本段没有原对白，不新增对白。"
    return projected


def compile_continuation_probe(raw, script, completed_refs, refs):
    base._validate(continuation_probe_schema(script, completed_refs, refs), raw)
    _validate_prose(raw, script)
    projected = _projection(raw)
    v2_compiled = prior.compile_continuation_probe(projected, script, completed_refs, refs)
    performance = deepcopy(v2_compiled["performance_compiled"])
    performance.update(schema=VERSION + "/performance", native=deepcopy(raw["performance"]),
        native_sha256=base.digest(raw["performance"]))
    return {**deepcopy(v2_compiled), "schema": VERSION, "native": deepcopy(raw), "native_sha256": base.digest(raw),
        "performance_compiled": performance, "v2_projection_native": deepcopy(projected),
        "v2_projection_sha256": base.digest(projected), "v2_projection_compiled": v2_compiled,
        "source_references_are_spoken_content": False, "deterministic_projection_only": True}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("continuation source-reception compilation belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"], compiled["source_refs"])
    if exact != compiled:
        raise ValueError("continuation source-reception native, projection or timing compilation changed")
    prompt = prior.render_prompt(compiled["v2_projection_compiled"], script, actor_names=actor_names)
    lines = prompt.split("\n")
    lines.insert(1, "来源编号、刺激渠道及演法说明均为拍摄与审查指令，不朗读；仅朗读当前原对白。")
    return "\n".join(lines)
