"""Offline protocol candidate: bind constant identities outside model output.

The native document contains creative fields and local source references only.
Fixed source identities, camera policy and language are derived from frozen
inputs in a separate projection. No legacy response is converted or adopted.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_continuation_probe_contract_v6 as prior
from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v7"
TRIAL_ROUTE = prior.TRIAL_ROUTE
CAMERA_POLICY = prior.CAMERA_POLICY
CAMERA_INSTRUCTION = prior.CAMERA_INSTRUCTION
RULE = prior.RULE.replace(
    "本版本camera只能填retain_approved_frame，不自由编写机位或猜测左右、距离、座位。",
    "本版本不填写camera；机位协议由冻结上下文确定，不自由编写机位或猜测左右、距离、座位。") + (
    "本次原生响应只有current_direction与performance。不要生成顶层或performance内的script_sha256、source_refs，"
    "不要生成camera或spoken_language；这些常量由程序按冻结输入确定性编译。"
    "保留availability、所有自然创意文字与局部必需的来源引用：source_reception.stimuli、dialogue_delivery、action_timings仍按当前合同完整填写。"
    "不转换旧失败响应，不补写或修改创意文字；本协议候选仅离线验证，不授予生产调用。")


def build_scene_continuity_context(script, scene_and_character_context, approved_tail_metadata):
    context = prior.build_scene_continuity_context(script, scene_and_character_context, approved_tail_metadata)
    context["schema"] = VERSION + "/scene_continuity_context"
    return context


def _context(context, script):
    if not isinstance(context, dict):
        raise ValueError("scene continuity context required")
    exact = build_scene_continuity_context(script, context.get("source_scene_and_character_context"),
        context.get("approved_first_frame"))
    if context != exact:
        raise ValueError("scene continuity context changed or belongs to a different source")
    return exact


def _v6_context(context):
    projected = deepcopy(context)
    projected["schema"] = prior.VERSION + "/scene_continuity_context"
    return projected


def continuation_source(script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    source = prior.continuation_source(script, completed_refs, refs, _v6_context(context))
    source.update(scene_continuity_context=deepcopy(context), scene_continuity_context_sha256=base.digest(context),
        fixed_response_metadata_generated_by_model=False)
    return source


def continuation_probe_schema(script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    schema = deepcopy(prior.continuation_probe_schema(script, completed_refs, refs, _v6_context(context)))
    for key in ("script_sha256", "source_refs"):
        del schema["properties"][key]
        schema["required"].remove(key)
    performance = schema["properties"]["performance"]
    for key in ("script_sha256", "source_refs", "camera", "spoken_language"):
        del performance["properties"][key]
        performance["required"].remove(key)
    return schema


def _derived_metadata(script, refs):
    return {"script_sha256": base.digest(script), "source_refs": deepcopy(refs),
        "camera": CAMERA_POLICY, "spoken_language": "zh-CN"}


def _projection(raw, metadata):
    projected = deepcopy(raw)
    for key in ("script_sha256", "source_refs"):
        projected[key] = deepcopy(metadata[key])
    projected["performance"].update(deepcopy(metadata))
    return projected


def compile_continuation_probe(raw, script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    base._validate(continuation_probe_schema(script, completed_refs, refs, context), raw)
    metadata = _derived_metadata(script, refs)
    projected = _projection(raw, metadata)
    v6_compiled = prior.compile_continuation_probe(projected, script, completed_refs, refs, _v6_context(context))
    performance = deepcopy(v6_compiled["performance_compiled"])
    performance.update(schema=VERSION + "/performance", native=deepcopy(raw["performance"]),
        native_sha256=base.digest(raw["performance"]))
    return {**deepcopy(v6_compiled), "schema": VERSION, "native": deepcopy(raw),
        "native_sha256": base.digest(raw), "performance_compiled": performance,
        "scene_continuity_context": deepcopy(context), "scene_continuity_context_sha256": base.digest(context),
        "derived_metadata": metadata, "derived_metadata_sha256": base.digest(metadata),
        "v6_projection_native": deepcopy(projected), "v6_projection_sha256": base.digest(projected),
        "v6_projection_compiled": v6_compiled,
        "fixed_response_metadata_generated_by_model": False, "creative_fields_rewritten": False,
        "legacy_failed_response_adopted": False, "deployment_scope": "offline_only",
        "production_calls_authorized_by_contract": False}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("derived-metadata continuation belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"],
        compiled["source_refs"], compiled["scene_continuity_context"])
    if exact != compiled:
        raise ValueError("derived-metadata native, source, context, projection or timing compilation changed")
    return prior.render_prompt(compiled["v6_projection_compiled"], script, actor_names=actor_names)
