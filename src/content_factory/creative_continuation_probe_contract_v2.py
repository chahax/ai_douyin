"""Continuation stimuli metadata, preserving all native performance prose.

Channels describe an explicit claim for independent review. Source/channel
compatibility cannot prove that free-form reception prose has the same meaning.
The frozen v1 contract still owns scope, normal-speed timing and rendering.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_continuation_probe_contract_v1 as prior
from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v2"
TRIAL_ROUTE = prior.TRIAL_ROUTE
RULE = prior.RULE + (
    "每名角色的current_stimuli至少列一项本段来源和spoken或visible渠道。"
    "spoken只能引用本段另一名角色实际说出的原对白，自己的对白不能当作所听刺激；visible只能引用本段原动作。"
    "接收演法必须与列出的渠道一致：纸面可见字不能编成另一角色已说出的词。"
    "这些元数据只证明所引用来源和渠道形式相容，自由文字的因果与本段信息是否完成仍须独立8项审查，"
    "包括stimulus_source_channel和current_source_action_completed。")


def continuation_source(script, completed_refs, refs):
    return prior.continuation_source(script, completed_refs, refs)


def continuation_probe_schema(script, completed_refs, refs):
    schema = deepcopy(prior.continuation_probe_schema(script, completed_refs, refs))
    current = prior._current_sources(script, completed_refs, refs)
    actors = continuation_source(script, completed_refs, refs)["actor_ids"]
    goal = schema["properties"]["performance"]["properties"]["actor_goals"]["items"]
    stimulus = base._obj({"source_ref": {"enum": deepcopy(refs)}, "channel": {"enum": ["spoken", "visible"]}})
    goal["properties"]["current_stimuli"] = {**base._array(stimulus, 1, len(refs)), "uniqueItems": True,
        "description": "本段听觉/视觉刺激，至少一项。spoken须另一speaker的当前对白；visible须当前动作。所述反应语义由独立审查核对。"}
    goal["required"].append("current_stimuli")
    actor_rules = []
    for actor in actors:
        permitted = []
        for ref, source in current.items():
            if source["kind"] == "action":
                permitted.append(base._obj({"source_ref": {"const": ref}, "channel": {"const": "visible"}}))
            elif source["speaker"] != actor:
                permitted.append(base._obj({"source_ref": {"const": ref}, "channel": {"const": "spoken"}}))
        actor_rules.append({"if": {"properties": {"actor_id": {"const": actor}}, "required": ["actor_id"]},
            "then": {"properties": {"current_stimuli": {"items": {"oneOf": permitted} if permitted else False}}}})
    if actor_rules:
        goal["allOf"] = actor_rules
    return schema


def _timing_projection(raw):
    """Only remove validated stimuli metadata; never rewrite creative prose."""
    projected = deepcopy(raw)
    for goal in projected["performance"]["actor_goals"]:
        del goal["current_stimuli"]
    return projected


def compile_continuation_probe(raw, script, completed_refs, refs):
    base._validate(continuation_probe_schema(script, completed_refs, refs), raw)
    projected = _timing_projection(raw)
    v1_compiled = prior.compile_continuation_probe(projected, script, completed_refs, refs)
    performance = deepcopy(v1_compiled["performance_compiled"])
    performance.update(schema=VERSION + "/performance", native=deepcopy(raw["performance"]),
        native_sha256=base.digest(raw["performance"]))
    return {**deepcopy(v1_compiled), "schema": VERSION, "native": deepcopy(raw), "native_sha256": base.digest(raw),
        "performance_compiled": performance, "v1_timing_projection_sha256": base.digest(projected),
        "v1_timing_projection_compiled": v1_compiled,
        "requires_independent_current_review_criteria_count": 8,
        "stimulus_source_channel_compatibility_validated": True, "stimulus_prose_semantics_verified": False}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("continuation stimuli compilation belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"], compiled["source_refs"])
    if exact != compiled:
        raise ValueError("continuation stimuli native, metadata, projection or timing compilation changed")
    # Stimulus paths are evidence for review, not speech or a second prose
    # channel. The exact validated v1 projection preserves every creative field.
    return prior.render_prompt(compiled["v1_timing_projection_compiled"], script, actor_names=actor_names)
