"""Test collection policy for unavailable historical review evidence.

Some legacy production tests depend on six large, review-bound artifacts that
were never committed to any Git ref and are absent from this workspace.  Those
tests must not fail as ordinary code regressions, and the artifacts must not be
recreated without their original media and human-review evidence.  Skip only
the exact evidence-dependent tests below.  The skip is conditional, so restoring
the real artifact automatically re-enables the original test.
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

REFERENCE_PLAN = Path(
    "data/fanqie_promotion/scene_plans/reference_404263_full_workflows_v2.json"
)
REFERENCE_CONTINUITY = Path(
    "data/qa/reference_404263_full_workflows_20260825/"
    "full_candidate_edit_recipes_v2_continuity.json"
)
REFERENCE_DETAILED_SEMIREAL = Path(
    "data/qa/reference_404263_detailed_two_style_full_20260826/"
    "semireal/story_project.json"
)
TASK1_V61_PLAN = Path(
    "data/fanqie_promotion/scene_plans/task1_story_v61_reviewed_anchors.json"
)
TASK1_V61_REVIEW_TEMPLATE = Path(
    "data/qa/task1_story_v61_failed_smoke_review_template.json"
)
TASK1_V62_PLAN = Path(
    "data/fanqie_promotion/scene_plans/task1_story_v62_microshot_workflow.json"
)


def _all(*names: str, evidence: tuple[Path, ...]) -> dict[str, tuple[Path, ...]]:
    return {name: evidence for name in names}


HISTORICAL_EVIDENCE_REQUIREMENTS: dict[
    str, dict[str, tuple[Path, ...]]
] = {
    "test_reference_404263_bighead3d_project.py": _all(
        "test_bighead3d_project_preserves_source_timeline_and_review_gate",
        evidence=(REFERENCE_PLAN,),
    ),
    "test_reference_404263_detailed_generation_contracts.py": _all(
        "test_generation_prompts_are_english_and_keep_chinese_audit_fields",
        "test_hard_gate_shots_have_explicit_physical_staging",
        evidence=(REFERENCE_DETAILED_SEMIREAL,),
    ),
    "test_reference_404263_full_workflow.py": _all(
        "test_caption_wrapping_is_balanced_and_never_orphans_punctuation",
        "test_continuity_recipe_covers_every_beat_without_legacy_cut_quota",
        "test_continuity_recipe_does_not_cross_engines_inside_one_action",
        "test_continuity_recipe_has_no_automatic_or_long_anchor_tails",
        "test_controlled_candidate_uses_both_workflow_families",
        "test_controlled_workflow_uses_pose_only_move_and_splits_fragile_actions",
        "test_every_beat_has_auditable_performance_fields_and_existing_anchor",
        "test_full_plan_contract_is_exact_and_non_publishable",
        "test_generation_prompt_does_not_execute_postproduction_cut_list",
        "test_only_motivated_ui_inserts_interrupt_action",
        "test_p07_p08_p14_use_dedicated_non_reused_sources",
        "test_p19_p20_are_adjacent_windows_with_a_continuous_source_contract",
        "test_reviewed_edit_recipes_match_beat_durations_and_cut_counts",
        "test_voice_spec_matches_all_beats_exactly_once",
        evidence=(REFERENCE_PLAN, REFERENCE_CONTINUITY),
    ),
    "test_task1_story_v61_creative_contract.py": _all(
        "test_creative_regressions_fail_closed",
        "test_real_plan_satisfies_exact_creative_contract",
        evidence=(TASK1_V61_PLAN,),
    ),
    "test_task1_story_v61_failed_smoke_runner.py": _all(
        "test_audio_failure_stops_before_runtime_provider",
        "test_default_mode_is_static_and_keeps_publish_gates_closed",
        "test_default_validation_uses_separate_audit_path",
        "test_each_reviewed_runtime_source_change_fails_static_gate_before_tts",
        "test_execute_renders_only_selected_shots_and_keeps_platform_gates_closed",
        "test_prepare_audio_stops_before_video_generation",
        "test_runtime_preflight_failure_stops_before_video",
        "test_single_shot_diagnostic_is_not_review_eligible",
        evidence=(TASK1_V61_PLAN,),
    ),
    "test_task1_story_v61_full_batch_gate.py": _all(
        "test_execute_only_after_gate_and_keeps_publish_closed",
        evidence=(TASK1_V61_PLAN,),
    ),
    "test_task1_story_v61_smoke_review_packet.py": _all(
        "test_prepares_machine_packet_but_never_human_approval",
        "test_refuses_to_overwrite_review_or_packet",
        "test_rejects_candidate_changed_during_frame_extraction",
        "test_rejects_incomplete_render_progress_before_extracting",
        "test_rejects_ineligible_candidate_before_extracting",
        "test_rejects_musetalk_artifact_sha_mismatch",
        "test_rejects_template_with_inherited_approval_field",
        "test_review_link_failure_rolls_back_published_packet",
        "test_sadtalker_packet_binds_rife_source_and_output_evidence",
        evidence=(TASK1_V61_REVIEW_TEMPLATE,),
    ),
    "test_task1_story_v62_microshot_workflow.py": _all(
        "test_composer_supports_every_declared_crop",
        "test_direct_reference_branch_can_never_authorize_publication",
        "test_microshots_are_complete_and_bound_to_new_units",
        "test_original_branch_rebuilds_every_story_beat",
        evidence=(TASK1_V61_PLAN, TASK1_V62_PLAN),
    ),
    "test_task1_story_v63_visual_retention_workflow.py": _all(
        "test_v63_has_complete_40_8_second_microshot_timeline",
        "test_v63_has_three_distinct_visual_phases",
        "test_v63_natural_action_repairs_forbid_overacted_blocking_and_watch_check",
        "test_v63_renderer_partition_is_exact",
        "test_v63_uses_19_unique_original_anchors_and_no_reference_pixels",
        evidence=(TASK1_V62_PLAN,),
    ),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip only tests whose immutable historical evidence is unavailable."""
    for item in items:
        module_rules = HISTORICAL_EVIDENCE_REQUIREMENTS.get(Path(str(item.path)).name)
        if not module_rules:
            continue
        test_name = item.name.split("[", 1)[0]
        required = module_rules.get(test_name)
        if not required:
            continue
        missing = [path for path in required if not (ROOT / path).is_file()]
        if not missing:
            continue
        item.add_marker(pytest.mark.skip(reason=(
            "historical external review evidence unavailable; restore the original "
            "artifact to re-enable: " + ", ".join(path.as_posix() for path in missing)
        )))
