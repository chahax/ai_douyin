"""Pure necessary timing conditions for an unchanged complete native script.

The frozen source policy consumes dialogue in catalogue order. Actions can
overlap adjacent speech in later performance planning; they cannot subtract
from the sum of the sequential dialogue. These estimates are not measured
speech, scheduled performance, creative approval, or permission to dispatch.
"""
from __future__ import annotations

from copy import deepcopy
import math

from . import creative_known_draft_continuation_v2 as windows

VERSION = "creative_fresh_script_feasibility/v3"
digest = windows.digest
source = windows.fresh.source


class ScriptFeasibilityConfigError(ValueError):
    def __init__(self, detail):
        self.code = "SCRIPT_FEASIBILITY_CONFIG_INVALID"
        self.detail = deepcopy(detail)
        super().__init__(self.code)


class ScriptFeasibilityError(ValueError):
    def __init__(self, detail):
        self.code = "SCRIPT_FEASIBILITY_BLOCKED"
        self.detail = deepcopy(detail)
        super().__init__(self.code)


def _positive_finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def build_policy(production_preferences):
    """Read the explicit whole-film limit; never infer or change its value."""
    if type(production_preferences) is not dict:
        raise ScriptFeasibilityConfigError({"field":"production_preferences", "reason":"object required"})
    limit = production_preferences.get("whole_film_max_seconds")
    if not _positive_finite(limit):
        raise ScriptFeasibilityConfigError({"field":"production_preferences.whole_film_max_seconds",
            "reason":"explicit finite positive number required; bool, missing and unknown are invalid"})
    for key, expected in (("normal_spoken_characters_per_second", windows.SPEAKING_RATE),
                          ("native_segment_max_seconds", windows.MAX_SEGMENT_SECONDS),
                          ("receiver_reserve_seconds", windows.RECEIVER_RESERVE_SECONDS)):
        if key in production_preferences and (not _positive_finite(production_preferences[key])
                or production_preferences[key] != expected):
            raise ScriptFeasibilityConfigError({"field":"production_preferences." + key,
                "reason":"configuration conflicts with the inherited fixed normal timing policy"})
    if "no_speed_fitting" in production_preferences and production_preferences["no_speed_fitting"] is not True:
        raise ScriptFeasibilityConfigError({"field":"production_preferences.no_speed_fitting",
            "reason":"speed fitting cannot weaken necessary timing conditions"})
    return {"schema":VERSION + "/policy", "whole_film_max_seconds":limit,
        "speaking_rate":windows.SPEAKING_RATE, "max_segment_seconds":windows.MAX_SEGMENT_SECONDS,
        "receiver_reserve_seconds":windows.RECEIVER_RESERVE_SECONDS,
        "maximum_spoken_characters_per_dialogue":windows.MAX_SPOKEN_CHARACTERS,
        "counting_rule":"creative_video_trial_contract_v1.spoken_characters",
        "timing_contract_source":"creative_fresh_legal_text_pipeline_v1.validate_script: spoken_seconds + .3 <= 15",
        "timing_diagnostic_source":"creative_known_draft_continuation_v2.dialogue_window_diagnostics",
        "whole_limit_source":"explicit production_preferences.whole_film_max_seconds",
        "scope":"necessary dialogue-only lower bounds; reaction/action scheduling and actual speech remain unknown",
        "dialogue_order":"source_catalogue_order_sequential_complete_speech",
        "action_overlap_subtracts_from_speech_floor":False,
        "whole_floor_includes_reaction_or_action_time":False}


def diagnose_script(raw, brief, production_preferences, *, expected_preferences_sha256=None):
    """Report every dialogue window and the whole speech-only lower bound.

    Unknown whole-film configuration blocks calculation. Supplying an expected
    preferences digest binds the calculation to the caller's frozen context.
    No result of this function edits or approves the source document.
    """
    policy = build_policy(production_preferences)
    preferences_sha = digest(production_preferences)
    if expected_preferences_sha256 is not None and (
            not windows.prior._sha(expected_preferences_sha256) or expected_preferences_sha256 != preferences_sha):
        raise ScriptFeasibilityConfigError({"field":"production_preferences", "reason":"frozen preferences SHA changed"})
    script = windows.fresh.contract.compile_script(raw, brief)
    catalogue = source.catalog(script)
    if {row["speaker"] for row in catalogue.values() if row["kind"] == "dialogue"} != set(brief["constraints"]["allowed_character_ids"]):
        raise ValueError("full script must cover exact declared on-screen dialogue cast")
    window_report = windows.dialogue_window_diagnostics(raw, brief)
    dialogue_rows = []
    for ref, row in catalogue.items():
        if row["kind"] != "dialogue":
            continue
        count, speech = source.spoken_characters(row), source.spoken_seconds(row)
        minimum = speech + policy["receiver_reserve_seconds"]
        dialogue_rows.append({"source_ref":ref, "field_path":row["path"] + ".text",
            "text":row["text"], "speaker_id":row["speaker"], "spoken_character_count":count,
            "estimated_speech_seconds":speech, "receiver_reserve_seconds":policy["receiver_reserve_seconds"],
            "estimated_minimum_seconds":minimum, "max_segment_seconds":policy["max_segment_seconds"],
            "exceeds_segment_window":minimum > policy["max_segment_seconds"],
            "excess_seconds":max(0, minimum - policy["max_segment_seconds"])})
    total_count = sum(row["spoken_character_count"] for row in dialogue_rows)
    whole_minimum = total_count / policy["speaking_rate"]
    whole_limit = policy["whole_film_max_seconds"]
    whole = {"dialogue_count":len(dialogue_rows), "spoken_character_count":total_count,
        "estimated_speech_only_seconds":whole_minimum, "whole_film_max_seconds":whole_limit,
        "exceeds_whole_speech_floor":whole_minimum > whole_limit,
        "excess_seconds":max(0, whole_minimum - whole_limit),
        "remaining_before_reaction_and_action_seconds":whole_limit - whole_minimum,
        "reaction_and_action_duration_known":False, "production_feasible":None,
        "source_refs":[row["source_ref"] for row in dialogue_rows]}
    issues = []
    if window_report["violations"]:
        issues.append({"code":"SCRIPT_DIALOGUE_WINDOW_EXCEEDED", "target":"complete_native_script",
            "evidence":deepcopy(window_report["violations"]),
            "required_revision":"完整新稿同时修复全部超长言语单元与整片总量；冻结事实/人物行事功能保留，不提速、不手改正文。"})
    if whole["exceeds_whole_speech_floor"]:
        issues.append({"code":"WHOLE_FILM_SPEECH_MINIMUM_EXCEEDED", "target":"complete_native_script",
            "evidence":deepcopy(whole),
            "required_revision":"完整新稿自然减少全片顺次对白总量并留出后续表演时间；仅拆句或并行动作不能消除对白总量缺口。"})
    return {"schema":VERSION + "/diagnostic", "raw_script_sha256":digest(raw),
        "script_sha256":digest(script), "brief_sha256":digest(brief),
        "production_preferences_sha256":preferences_sha, "policy_sha256":digest(policy), "policy":policy,
        "status":"necessary_conditions_blocked" if issues else "necessary_conditions_satisfied_only",
        "dialogue_rows":dialogue_rows, "dialogue_window_diagnostics":window_report, "whole_speech_floor":whole,
        "issues":issues, "estimated_not_measured":True, "production_feasible":None,
        "creative_quality_passed":False, "human_quality_approved":False, "media_authorized":False,
        "dispatch_performed":False, "source_prose_changed":False}


def validate_script(raw, brief, production_preferences, *, expected_preferences_sha256=None):
    report = diagnose_script(raw, brief, production_preferences,
        expected_preferences_sha256=expected_preferences_sha256)
    if report["issues"]:
        raise ScriptFeasibilityError(report)
    return report


def make_validator(brief, production_preferences):
    """Capture immutable inputs for a future injected dispatcher validator."""
    bound_brief, bound_preferences = deepcopy(brief), deepcopy(production_preferences)
    build_policy(bound_preferences)
    expected_sha = digest(bound_preferences)
    def validator(raw):
        return validate_script(raw, bound_brief, bound_preferences, expected_preferences_sha256=expected_sha)
    return validator
