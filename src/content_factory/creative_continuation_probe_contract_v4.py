"""Bind completed causes without adding them to the current performance.

Past source references are context for the independent acting review. The
frozen v1 compiler still schedules and renders current sources only. Native
creative prose is preserved; its causal meaning is not proved by references.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_continuation_probe_contract_v1 as timing
from . import creative_continuation_probe_contract_v3 as prior
from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v4"
TRIAL_ROUTE = timing.TRIAL_ROUTE
RULE = timing.RULE + (
    "每名角色在source_reception.stimuli至少列一项有phase的刺激：current只引用本段来源，completed只引用已经完成的原序前缀。"
    "spoken只能引用另一speaker实际说出的原对白，visible只能引用原动作，phase必须与来源所属范围一致，绝不引用未来。"
    "completed来源只解释已经发生的起因，不是本段表演、朗读或重复动作的来源；本段仍只表演当前source_refs。"
    "source_reception.response只写短自然反应；dialogue_delivery每句当前原对白恰一行，原对白只由源文注入一次。"
    "所有自由演法文字都不得复抄完整原对白。来源编号、phase及渠道不是朗读内容。"
    "继承姿态、过去起因与当前反应的因果、机位及当前信息完成仍须独立8项审查，形式相容不等于语义正确。")


def continuation_source(script, completed_refs, refs):
    source = timing.continuation_source(script, completed_refs, refs)
    catalog = base.catalog(script)
    return {**source,
        "completed_stimulus_sources": {ref: deepcopy(catalog[ref]) for ref in completed_refs},
        "completed_sources_are_context_only": True,
        "only_current_source_refs_are_performed": True}


def continuation_probe_schema(script, completed_refs, refs):
    source = continuation_source(script, completed_refs, refs)
    schema = deepcopy(prior.continuation_probe_schema(script, completed_refs, refs))
    goal = schema["properties"]["performance"]["properties"]["actor_goals"]["items"]
    source_rows = [("completed", ref, row) for ref, row in source["completed_stimulus_sources"].items()]
    source_rows += [("current", ref, row) for ref, row in source["current_sources"].items()]
    stimulus = base._obj({"phase": {"enum": ["current", "completed"]},
        "source_ref": {"enum": deepcopy(completed_refs + refs)},
        "channel": {"enum": ["spoken", "visible"]}})
    goal["properties"]["source_reception"]["properties"]["stimuli"] = {
        **base._array(stimulus, 1, len(source_rows)), "uniqueItems": True,
        "description": "completed是过去因果上下文，不追加本段演出；current是本段。spoken须另一speaker对白，visible须原动作；不得引用未来或把phase填错。"}
    actor_rules = []
    for actor in source["actor_ids"]:
        permitted = []
        for phase, ref, row in source_rows:
            if row["kind"] == "action":
                channel = "visible"
            elif row["speaker"] != actor:
                channel = "spoken"
            else:
                continue
            permitted.append(base._obj({"phase": {"const": phase},
                "source_ref": {"const": ref}, "channel": {"const": channel}}))
        actor_rules.append({"if": {"properties": {"actor_id": {"const": actor}}, "required": ["actor_id"]},
            "then": {"properties": {"source_reception": {"properties": {
                "stimuli": {"items": {"oneOf": permitted} if permitted else False}}}}}})
    goal["allOf"] = actor_rules
    return schema


def _projection(raw):
    projected = prior._projection(raw)
    for goal in projected["performance"]["actor_goals"]:
        # Validated phase/channel evidence is retained in the full native v4
        # record. It is not a speech, action or v2 current-stimulus substitute.
        del goal["current_stimuli"]
    return projected


def compile_continuation_probe(raw, script, completed_refs, refs):
    base._validate(continuation_probe_schema(script, completed_refs, refs), raw)
    prior._validate_prose(raw, script)
    projected = _projection(raw)
    v1_compiled = timing.compile_continuation_probe(projected, script, completed_refs, refs)
    performance = deepcopy(v1_compiled["performance_compiled"])
    performance.update(schema=VERSION + "/performance", native=deepcopy(raw["performance"]),
        native_sha256=base.digest(raw["performance"]))
    source = continuation_source(script, completed_refs, refs)
    return {**deepcopy(v1_compiled), "schema": VERSION, "native": deepcopy(raw),
        "native_sha256": base.digest(raw), "performance_compiled": performance,
        "completed_stimulus_sources": deepcopy(source["completed_stimulus_sources"]),
        "current_stimulus_sources": deepcopy(source["current_sources"]),
        "completed_sources_are_context_only": True, "only_current_source_refs_are_performed": True,
        "v1_projection_native": deepcopy(projected), "v1_projection_sha256": base.digest(projected),
        "v1_projection_compiled": v1_compiled,
        "requires_independent_current_review_criteria_count": 8,
        "stimulus_source_channel_compatibility_validated": True,
        "stimulus_phase_channel_compatibility_validated": True,
        "stimulus_prose_semantics_verified": False,
        "source_references_are_spoken_content": False, "deterministic_projection_only": True}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("continuation phased-stimulus compilation belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"], compiled["source_refs"])
    if exact != compiled:
        raise ValueError("continuation phased-stimulus native, projection or timing compilation changed")
    prompt = timing.render_prompt(compiled["v1_projection_compiled"], script, actor_names=actor_names)
    lines = prompt.split("\n")
    lines.insert(1, "来源编号、phase及渠道是因果审查元数据，不朗读。已完成的刺激不重演；只表演当前原动作，只说当前原对白。")
    return "\n".join(lines)
