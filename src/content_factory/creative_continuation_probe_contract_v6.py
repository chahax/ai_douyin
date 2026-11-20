"""Reject unverified screen coordinates in every model-authored prose field.

Camera ownership remains with the approved original frame. This lexical guard
blocks explicit coordinate/shot declarations, not all semantic contradictions;
the ten independent review criteria and human media review remain required.
"""
from __future__ import annotations

from copy import deepcopy
import re

from . import creative_continuation_probe_contract_v3 as prose
from . import creative_continuation_probe_contract_v5 as prior
from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v6"
TRIAL_ROUTE = prior.TRIAL_ROUTE
CAMERA_POLICY = prior.CAMERA_POLICY
CAMERA_INSTRUCTION = prior.CAMERA_INSTRUCTION
SPATIAL_DECLARATION_PATTERN = (
    r"(?:画\s*[左右]"
    r"|(?:画面|镜头|构图)\s*(?:的|中|内)?\s*(?:偏|靠|最)?\s*[左右](?:侧|边|方|端|半)?"
    r"|[上下左右]\s*半(?:边|幅)?\s*(?:画面|镜头|构图)"
    r"|(?:画面|镜头|构图)\s*(?:的)?\s*[上下]\s*半(?:边|幅)?"
    r"|中近景|近景|特写|中景|远景|全景|俯拍|仰拍|反打|过肩(?:镜头|机位|构图)"
    r"|(?:切换|重设|另设|重新设置|重新安排)\s*(?:机位|构图|视轴))")
SPATIAL_SAFE_PATTERN = r"^(?![\s\S]*" + SPATIAL_DECLARATION_PATTERN + r")[\s\S]*$"
_SPATIAL = re.compile(SPATIAL_DECLARATION_PATTERN)
RULE = prior.RULE + (
    "所有自由方向、连贯演法、人物目的与接收、语气与听者行为、终态文字都不得补写未经来源确认的屏幕方位或另设景别机位。"
    "不写画右、画左、画面左侧右侧、上下半画面、中近景、特写、俯仰拍、反打等坐标或机位重构；只沿原帧。"
    "人物的右手食指、纸笔在周姐一侧是动作或人物相对关系，不当作屏幕坐标删除。"
    "命中公开空间文字规则时完整原生保留并拒收，不删词或改写；规则未命中不证明空间语义或实际视频连续性正确。")


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


def _v5_context(context):
    projected = deepcopy(context)
    projected["schema"] = prior.VERSION + "/scene_continuity_context"
    return projected


def continuation_source(script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    source = prior.continuation_source(script, completed_refs, refs, _v5_context(context))
    source.update(scene_continuity_context=deepcopy(context), scene_continuity_context_sha256=base.digest(context))
    return source


def _free_text_schemas(schema):
    yield from schema["properties"]["current_direction"]["properties"].values()
    performance = schema["properties"]["performance"]["properties"]
    for key in ("continuous_performance", "ending_state"):
        yield performance[key]
    goal = performance["actor_goals"]["items"]["properties"]
    yield goal["immediate_objective"]
    yield goal["source_reception"]["properties"]["response"]
    for row in performance["dialogue_delivery"].get("prefixItems", []):
        for key in ("speech_tone", "listener_behavior"):
            yield row["properties"][key]


def continuation_probe_schema(script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    schema = deepcopy(prior.continuation_probe_schema(script, completed_refs, refs, _v5_context(context)))
    for field in _free_text_schemas(schema):
        field["pattern"] = SPATIAL_SAFE_PATTERN
        field["description"] = field.get("description", "") + "不另声明屏幕左右/半画面、景别或机位；沿批准原帧。人物右手或道具在人一侧不受此词法规则禁止。"
    return schema


def _validate_spatial_prose(raw):
    for path, text in prose._free_text_fields(raw):
        if path == "performance.camera":
            continue  # An immutable protocol enum, not free camera prose.
        match = _SPATIAL.search(text)
        if match:
            raise ValueError("unverified spatial declaration at " + path + ": " + match.group(0))


def compile_continuation_probe(raw, script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    v5_context = _v5_context(context)
    # First validate types and closed keys. Then locate the spatial finding;
    # the same expression is public in the new response schema.
    base._validate(prior.continuation_probe_schema(script, completed_refs, refs, v5_context), raw)
    _validate_spatial_prose(raw)
    base._validate(continuation_probe_schema(script, completed_refs, refs, context), raw)
    compiled = prior.compile_continuation_probe(raw, script, completed_refs, refs, v5_context)
    compiled.update(schema=VERSION, scene_continuity_context=deepcopy(context),
        scene_continuity_context_sha256=base.digest(context), spatial_prose_guard_validated=True,
        spatial_prose_guard_is_semantic_proof=False)
    compiled["performance_compiled"]["schema"] = VERSION + "/performance"
    return compiled


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("spatial-guard continuation belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"],
        compiled["source_refs"], compiled["scene_continuity_context"])
    if compiled != exact:
        raise ValueError("spatial-guard continuation native, context, projection or timing compilation changed")
    projection = prior.compile_continuation_probe(compiled["native"], script, compiled["completed_refs"],
        compiled["source_refs"], _v5_context(compiled["scene_continuity_context"]))
    return prior.render_prompt(projection, script, actor_names=actor_names)
