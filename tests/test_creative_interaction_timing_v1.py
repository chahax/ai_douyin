from copy import deepcopy

import pytest

from src.content_factory.creative_interaction_timing_v1 import (
    InteractionTimingError, compile_interactions,
)


def event(event_id, source_ref, kind, actor, start, end, *, requires=None, **extra):
    return {"event_id": event_id, "source_ref": source_ref, "kind": kind,
            "actor": actor, "start_seconds": start, "end_seconds": end,
            "requires": [] if requires is None else requires, "interaction_id": "I01",
            **extra}


def dependency(event_id, milestone):
    return {"event_id": event_id, "milestone": milestone}


def concurrent_example():
    # Original source steps and permissions are explicit; no existing script
    # is projected, reordered, or treated as implicitly permitting overlap.
    events = [
        event("notice", "B1.S02", "speech", "周姐", 0, 4, text="公司决定请你今天办离职手续"),
        event("push", "B1.S03", "action", "周姐", 1, 3,
              requires=[dependency("notice", "start")], prop_ids=["paper", "pen"]),
        event("listen", "B1.R01", "reaction", "小林", 1.5, 4.5,
              requires=[dependency("notice", "start")]),
        event("read", "B2.S01", "reaction", "小林", 4.5, 5.5,
              requires=[dependency("push", "end")]),
    ]
    permissions = [["B1.S02", "B1.S03"], ["B1.S02", "B1.R01"], ["B1.S03", "B1.R01"]]
    return events, permissions


def test_explicit_parallel_speech_action_listener_uses_latest_end_not_sum():
    events, permissions = concurrent_example()
    original = deepcopy(events)
    result = compile_interactions(events, declared_allowed_overlap=permissions)
    assert result["total_duration_seconds"] == 5.5
    assert result["summed_event_duration_seconds"] == 10
    assert len(result["allowed_actual_overlaps"]) == 3
    assert result["events"] == original == events
    assert result["timestamps_scaled"] is False
    assert result["schedule_reordered"] is False
    assert result["actual_media_speech_rate"] is None
    assert result["creative_quality_passed"] is False
    result["events"][0]["end_seconds"] = 100
    assert events == original


def test_reading_personal_reason_cannot_precede_paper_arrival():
    events, permissions = concurrent_example()
    events[-1]["start_seconds"] = 2.5
    with pytest.raises(InteractionTimingError, match="STIMULUS_NOT_REACHED"):
        compile_interactions(events, declared_allowed_overlap=permissions)


def test_same_actor_cannot_speak_two_lines_even_with_permission():
    events = [
        event("first", "B1.S02", "speech", "周姐", 0, 4, text="公司决定请你今天办离职手续"),
        event("second", "B1.S05", "speech", "周姐", 2, 4, text="你先看看再说"),
    ]
    with pytest.raises(InteractionTimingError, match="ACTOR_SPEECH_OVERLAP"):
        compile_interactions(events, declared_allowed_overlap=[["B1.S02", "B1.S05"]])


def test_same_prop_two_actions_cannot_overlap_even_with_permission():
    events = [
        event("push", "B1.S03", "action", "周姐", 0, 2, prop_ids=["paper"]),
        event("retrieve", "B4.S03", "action", "小林", 1, 3, prop_ids=["paper"]),
    ]
    with pytest.raises(InteractionTimingError, match="PROP_ACTION_OVERLAP"):
        compile_interactions(events, declared_allowed_overlap=[["B1.S03", "B4.S03"]])


def test_adjacent_source_steps_do_not_imply_overlap_permission():
    events, permissions = concurrent_example()
    with pytest.raises(InteractionTimingError, match="OVERLAP_NOT_DECLARED"):
        compile_interactions(events, declared_allowed_overlap=permissions[1:])


def test_explicit_end_dependency_blocks_early_speech_despite_overlap_permission():
    events = [
        event("first", "B1.S02", "speech", "周姐", 0, 4, text="公司决定请你今天办离职手续"),
        event("reply", "B1.S04", "speech", "小林", 3, 5, text="公司把我辞了"),
    ]
    events[1]["requires"] = [dependency("first", "end")]
    with pytest.raises(InteractionTimingError, match="STIMULUS_NOT_REACHED"):
        compile_interactions(events, declared_allowed_overlap=[["B1.S02", "B1.S04"]])


def test_planned_overlong_speech_does_not_scale_to_fifteen_seconds():
    events = [event("line", "B1.S02", "speech", "周姐", 0, 16,
                    text="你" * 48)]
    original = deepcopy(events)
    with pytest.raises(InteractionTimingError, match="DURATION_LIMIT_EXCEEDED"):
        compile_interactions(events, declared_allowed_overlap=[], duration_limit_seconds=15)
    assert events == original


def test_fast_speech_is_rejected_without_changing_submitted_duration():
    events = [event("line", "B1.S02", "speech", "周姐", 0, 2, text="你" * 12)]
    original = deepcopy(events)
    with pytest.raises(InteractionTimingError, match="PLANNED_SPEECH_TOO_FAST"):
        compile_interactions(events, declared_allowed_overlap=[])
    assert events == original


def test_slow_speech_warning_does_not_shorten_duration():
    events = [event("line", "B1.S02", "speech", "周姐", 0, 6, text="你" * 12)]
    result = compile_interactions(events, declared_allowed_overlap=[])
    assert result["total_duration_seconds"] == 6
    assert result["warnings"][0]["code"] == "PLANNED_SPEECH_BELOW_RANGE"


def test_speech_range_is_explicit_experimental_configuration():
    events = [event("line", "B1.S02", "speech", "周姐", 0, 3, text="你" * 15)]
    result = compile_interactions(events, declared_allowed_overlap=[], planned_speech_range=(3, 5))
    assert result["planned_speech_range"] == [3, 5]
    assert result["speech_estimates"][0]["planned_chinese_characters_per_second"] == 5
    assert result["actual_media_speech_rate"] is None


def test_chinese_punctuation_does_not_count_as_spoken_characters():
    events = [event("line", "B1.S02", "speech", "周姐", 0, 4,
                    text="公司决定，请你今天办离职手续。")]
    result = compile_interactions(events, declared_allowed_overlap=[])
    assert result["speech_estimates"][0]["chinese_character_count"] == 13


def test_non_chinese_speech_estimate_stays_unknown():
    events = [event("line", "B1.S02", "speech", "周姐", 0, 4, text="Hello")]
    result = compile_interactions(events, declared_allowed_overlap=[])
    assert result["speech_estimates"][0]["planned_chinese_characters_per_second"] is None
    assert result["warnings"][0]["code"] == "SPEECH_ESTIMATE_UNAVAILABLE"


@pytest.mark.parametrize("duplicate_field,code", [
    ("event_id", "EVENT_ID_DUPLICATE"), ("source_ref", "SOURCE_REF_DUPLICATE"),
])
def test_duplicate_event_or_source_rejected(duplicate_field, code):
    events = [
        event("one", "B1.S01", "action", "小林", 0, 1),
        event("two", "B1.S02", "action", "周姐", 1, 2),
    ]
    events[1][duplicate_field] = events[0][duplicate_field]
    with pytest.raises(InteractionTimingError, match=code):
        compile_interactions(events, declared_allowed_overlap=[])


def test_permission_must_name_known_sources_not_event_ids():
    events, _ = concurrent_example()
    with pytest.raises(InteractionTimingError, match="OVERLAP_DECLARATION_INVALID"):
        compile_interactions(events, declared_allowed_overlap=[["notice", "push"]])


def test_dependency_cycle_rejected_even_for_equal_start_milestones():
    events = [
        event("one", "B1.S01", "action", "小林", 0, 1,
              requires=[dependency("two", "start")]),
        event("two", "B1.S02", "action", "周姐", 0, 1,
              requires=[dependency("one", "start")]),
    ]
    with pytest.raises(InteractionTimingError, match="DEPENDENCY_CYCLE"):
        compile_interactions(events, declared_allowed_overlap=[["B1.S01", "B1.S02"]])


def test_reaction_without_explicit_stimulus_rejected():
    events = [event("reaction", "B1.R01", "reaction", "小林", 0, 1)]
    with pytest.raises(InteractionTimingError, match="REACTION_STIMULUS_MISSING"):
        compile_interactions(events, declared_allowed_overlap=[])


def test_touching_interval_boundaries_need_no_overlap_permission():
    events = [
        event("one", "B1.S01", "action", "小林", 0, 1, prop_ids=["paper"]),
        event("two", "B1.S03", "action", "周姐", 1, 2,
              prop_ids=["paper"], requires=[dependency("one", "end")]),
    ]
    result = compile_interactions(events, declared_allowed_overlap=[])
    assert result["allowed_actual_overlaps"] == []
    assert result["total_duration_seconds"] == 2


@pytest.mark.parametrize("field,value,code", [
    ("kind", [], "EVENT_KIND_INVALID"),
    ("start_seconds", True, "FIELD_INVALID"),
    ("end_seconds", float("inf"), "FIELD_INVALID"),
    ("end_seconds", 0, "EVENT_INTERVAL_INVALID"),
])
def test_malformed_types_and_nonfinite_intervals_fail_contract(field, value, code):
    events = [event("one", "B1.S01", "action", "小林", 0, 1)]
    events[0][field] = value
    with pytest.raises(InteractionTimingError, match=code):
        compile_interactions(events, declared_allowed_overlap=[])


def test_dependency_milestone_must_be_a_string():
    events = [
        event("one", "B1.S01", "action", "小林", 0, 1),
        event("two", "B1.S03", "action", "周姐", 1, 2,
              requires=[dependency("one", [])]),
    ]
    with pytest.raises(InteractionTimingError, match="DEPENDENCY_INVALID"):
        compile_interactions(events, declared_allowed_overlap=[])


def test_compilation_preserves_input_order_even_if_events_are_not_sorted():
    events, permissions = concurrent_example()
    events.reverse()
    original = deepcopy(events)
    result = compile_interactions(events, declared_allowed_overlap=permissions)
    assert result["events"] == original == events
    assert result["total_duration_seconds"] == 5.5


def test_disjoint_prop_actions_overlap_only_with_explicit_permission():
    events = [
        event("one", "B1.S01", "action", "小林", 0, 2, prop_ids=["badge"]),
        event("two", "B1.S03", "action", "周姐", 1, 3, prop_ids=["paper"]),
    ]
    result = compile_interactions(events, declared_allowed_overlap=[["B1.S01", "B1.S03"]])
    assert result["total_duration_seconds"] == 3
    assert len(result["allowed_actual_overlaps"]) == 1
