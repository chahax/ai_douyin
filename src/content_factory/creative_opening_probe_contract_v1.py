"""An isolated source-bound opening trial; no whole-direction approval.

Compilation preserves native current direction and performance separately.
The model-facing video prompt uses only the current performance and exact
source speech. Independent current-segment review is a separate required gate.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_video_trial_contract_v1 as base

VERSION = "creative_opening_probe_contract/v1"
TRIAL_ROUTE = "isolated_opening_probe"
RULE = base.OPENING_PERFORMANCE_RULE + (
    "本次是独立首段试拍，不需要把未通过的整片计划当导演依据。"
    "current_direction只说明当下新增信息、观察、刺激反应与切镜理由，不能预演后段催签、读原因或质疑。"
    "performance只填写当前首段表演，完整原对白由程序取源；整片规划和整片表演仍未通过。"
    "当前方案仍须独立审查，生成后由用户人工审核。")


def opening_probe_schema(script, refs):
    base.opening_source(script, refs)
    direction = base._obj({key: deepcopy(base._TEXT) for key in
        ("information_change", "observation", "stimulus_reaction", "cut_reason")})
    return base._obj({"script_sha256": {"const": base.digest(script)},
        "source_refs": {"const": deepcopy(refs)}, "current_direction": direction,
        "performance": base.opening_performance_schema(script, refs)})


def compile_opening_probe(raw, script, refs):
    base._validate(opening_probe_schema(script, refs), raw)
    base._no_dialogue_copy(raw["current_direction"], script)
    performance = base.compile_opening_performance(raw["performance"], script, refs, user_trial_acceptance=True)
    return {"schema": VERSION, "script_sha256": base.digest(script), "source_refs": deepcopy(refs),
        "native": deepcopy(raw), "native_sha256": base.digest(raw),
        "current_direction": deepcopy(raw["current_direction"]), "performance_compiled": performance,
        "trial_route": TRIAL_ROUTE, "whole_direction_accepted": False, "wholeperformance": False,
        "machine_quality": False, "machine_script_quality": False, "whole_film_performance_complete": False,
        "whole_film_complete": False, "user_trial_acceptance": True,
        "source_text_unchanged": True, "all_native_values_preserved": True,
        "requires_independent_current_review": True, "independent_current_review_complete": False,
        "requires_independent_current_review_criteria_count": 6,
        "actual_media_quality_passed": False, "after_generation_content_status": "awaiting_human_review",
        "requires_human_approved_service_tail_for_next_segment": True}


def render_prompt(compiled, script, actor_names=None):
    if compiled.get("schema") != VERSION or compiled.get("script_sha256") != base.digest(script):
        raise ValueError("isolated opening probe belongs to a different selected source")
    exact = compile_opening_probe(compiled["native"], script, compiled["source_refs"])
    if exact != compiled:
        raise ValueError("isolated opening probe native, direction or performance compilation changed")
    # Current-direction prose is evidence for the independent review, never
    # spoken narration or another instruction channel in the actual video.
    return base.render_opening_prompt(compiled["performance_compiled"], script, actor_names=actor_names)
