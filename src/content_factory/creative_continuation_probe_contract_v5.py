"""Closed source cast and frame-owned camera for a continuation probe.

The context binds source identities and original-frame metadata, not inferred
pixel positions. The runner verifies frame provenance and human approval; this
contract neither reads media nor marks a video as approved.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_continuation_probe_contract_v1 as timing
from . import creative_continuation_probe_contract_v3 as prose
from . import creative_continuation_probe_contract_v4 as prior
from . import creative_video_trial_contract_v1 as base

VERSION = "creative_continuation_probe_contract/v5"
TRIAL_ROUTE = prior.TRIAL_ROUTE
CAMERA_POLICY = "retain_approved_frame"
CAMERA_INSTRUCTION = "沿用已批准服务原始尾帧的机位、视轴和构图；既有座位与空间关系以该原帧为唯一布局依据，不另猜左右位置或改排座位。"
RULE = prior.RULE.replace("独立8项审查", "独立10项审查") + (
    "本版本camera只能填retain_approved_frame，不自由编写机位或猜测左右、距离、座位。"
    "scene_continuity_context由冻结源角色场景和已批准原帧元数据确定，不由模型生成或修改。"
    "只保留闭合演员表中的人物，延续同一场景、原帧既有座位与遮挡出画关系，不新增入场人物、旁观者或分身，不强迫两人同时居中。"
    "除本段原动作要求的自然表演外，不重新布置人物、道具或场景；十项独立审查须另核closed_cast_spatial_continuity与camera_authority。")


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be a nonempty source identity")
    return value


def _tail_schema():
    text = deepcopy(base._TEXT)
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return base._obj({"path": text, "sha256": sha, "role": {"const": "first_frame"},
        "source": {"const": "generation_service_original"}, "source_task_id": text,
        "source_segment_id": text, "source_video_sha256": sha, "human_review_path": text})


def build_scene_continuity_context(script, scene_and_character_context, approved_tail_metadata):
    catalog = base.catalog(script)
    actors = list(dict.fromkeys(row["speaker"] for row in catalog.values() if row["kind"] == "dialogue"))
    if not isinstance(scene_and_character_context, dict):
        raise ValueError("scene and character context must come from frozen source")
    characters = scene_and_character_context.get("characters")
    scenes = scene_and_character_context.get("scenes")
    initial = scene_and_character_context.get("initial_state")
    if not isinstance(characters, list) or not characters or not isinstance(scenes, list) or not scenes or not isinstance(initial, dict):
        raise ValueError("frozen source must declare characters, scenes and initial scene")
    ids = [_nonempty(row.get("id"), "character id") if isinstance(row, dict) else None for row in characters]
    if None in ids or len(ids) != len(set(ids)) or set(ids) != set(actors):
        raise ValueError("closed source cast must exactly match complete script speakers")
    scene_ids = [_nonempty(row.get("id"), "scene id") if isinstance(row, dict) else None for row in scenes]
    scene_id = _nonempty(initial.get("scene_id"), "source initial scene id")
    if None in scene_ids or len(scene_ids) != len(set(scene_ids)) or scene_id not in scene_ids:
        raise ValueError("continuation scene must be a declared frozen source scene")
    base._validate(_tail_schema(), approved_tail_metadata)
    return {"schema": VERSION + "/scene_continuity_context", "script_sha256": base.digest(script),
        "source_scene_and_character_context": deepcopy(scene_and_character_context),
        "source_scene_and_character_context_sha256": base.digest(scene_and_character_context),
        "actor_ids": actors, "actor_count": len(actors), "scene_id": scene_id,
        "closed_cast": True, "additional_people_allowed": False, "retain_existing_seats": True,
        "preserve_frame_occlusion_and_out_of_frame": True, "force_all_actors_in_frame": False,
        "approved_first_frame": deepcopy(approved_tail_metadata),
        "approved_first_frame_metadata_sha256": base.digest(approved_tail_metadata),
        "camera_policy": CAMERA_POLICY, "spatial_layout_authority": "generation_service_original_first_frame",
        "pixel_layout_inferred": False, "approval_verification_is_runner_owned": True}


def _context(context, script):
    if not isinstance(context, dict):
        raise ValueError("scene continuity context required")
    exact = build_scene_continuity_context(script, context.get("source_scene_and_character_context"),
        context.get("approved_first_frame"))
    if context != exact:
        raise ValueError("scene continuity context changed or belongs to a different source")
    return exact


def continuation_source(script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    return {**prior.continuation_source(script, completed_refs, refs),
        "scene_continuity_context": deepcopy(context), "scene_continuity_context_sha256": base.digest(context)}


def continuation_probe_schema(script, completed_refs, refs, scene_continuity_context):
    _context(scene_continuity_context, script)
    schema = deepcopy(prior.continuation_probe_schema(script, completed_refs, refs))
    schema["properties"]["performance"]["properties"]["camera"] = {"const": CAMERA_POLICY,
        "description": "只沿用批准原帧；空间布局、左右、座位与机位不得由模型另写。"}
    return schema


def _projection(raw):
    projected = prior._projection(raw)
    # Camera is a protocol selection, not model-authored creative prose.
    projected["performance"]["camera"] = CAMERA_INSTRUCTION
    return projected


def compile_continuation_probe(raw, script, completed_refs, refs, scene_continuity_context):
    context = _context(scene_continuity_context, script)
    base._validate(continuation_probe_schema(script, completed_refs, refs, context), raw)
    prose._validate_prose(raw, script)
    projected = _projection(raw)
    v1_compiled = timing.compile_continuation_probe(projected, script, completed_refs, refs)
    source = prior.continuation_source(script, completed_refs, refs)
    performance = deepcopy(v1_compiled["performance_compiled"])
    performance.update(schema=VERSION + "/performance", native=deepcopy(raw["performance"]),
        native_sha256=base.digest(raw["performance"]))
    return {**deepcopy(v1_compiled), "schema": VERSION, "native": deepcopy(raw),
        "native_sha256": base.digest(raw), "performance_compiled": performance,
        "completed_stimulus_sources": deepcopy(source["completed_stimulus_sources"]),
        "current_stimulus_sources": deepcopy(source["current_sources"]),
        "completed_sources_are_context_only": True, "only_current_source_refs_are_performed": True,
        "v1_projection_native": deepcopy(projected), "v1_projection_sha256": base.digest(projected),
        "v1_projection_compiled": v1_compiled, "requires_independent_current_review_criteria_count": 10,
        "stimulus_source_channel_compatibility_validated": True,
        "stimulus_phase_channel_compatibility_validated": True, "stimulus_prose_semantics_verified": False,
        "source_references_are_spoken_content": False, "deterministic_projection_only": True,
        "scene_continuity_context": deepcopy(context), "scene_continuity_context_sha256": base.digest(context),
        "camera_authority": "approved_service_original_tail", "actual_spatial_continuity_verified": False}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("frame-owned continuation belongs to a different selected source")
    exact = compile_continuation_probe(compiled["native"], script, compiled["completed_refs"],
        compiled["source_refs"], compiled["scene_continuity_context"])
    if compiled != exact:
        raise ValueError("frame-owned continuation native, context, projection or timing compilation changed")
    prompt = timing.render_prompt(compiled["v1_projection_compiled"], script, actor_names=actor_names)
    context = compiled["scene_continuity_context"]
    names = {} if actor_names is None else actor_names
    labels = [names.get(actor, actor) for actor in context["actor_ids"]]
    lines = prompt.split("\n")
    lines[1:1] = ["来源编号、phase及渠道是因果审查元数据，不朗读。已完成刺激不重演；只表演当前原动作与原对白。",
        "本场闭合演员表：" + "、".join(labels) + "，共" + str(context["actor_count"]) + "人；只保留这些人物，不新增入场者、旁观者、额外人物或分身。",
        "延续同一场景与原帧既有座位、人物和道具关系；绝对布局以输入原帧为准，不猜左右或另排座位。保留原帧已有的遮挡和出画，不强制所有人同时居中。",
        "当前情境与新增信息（不复演过去）：" + compiled["current_direction"]["information_change"]]
    return "\n".join(lines)
