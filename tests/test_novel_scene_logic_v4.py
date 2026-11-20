"""Paired state-boundary fixtures, not natural-language quality evaluation."""
from copy import deepcopy

import pytest

from src.content_factory.novel_scene_logic_v4 import analyze_scene_ledger, check_scene_ledger


def fact(value, predicate="posture", subject="person-a", **qualifiers):
    return {"subject_id": subject, "predicate": predicate, "value": value,
            "certainty": "explicit", "evidence_refs": ["draft:scene1:event"],
            "qualifiers": {"scope": "physical", **qualifiers}}


def ledger(left=None, right=None):
    left = fact("standing") if left is None else left
    right = fact("sitting") if right is None else right
    return {"header": {"source_binding": "source-sha", "draft_binding": "draft-sha"}, "events": [
        {"event_id": "e1", "timeline_id": "present", "narrative_layer": "performance",
         "relation": "new_event", "referent_event_id": None, "interpretation_status": "explicit",
         "entities": ["person-a"], "before": [], "after": [left], "context": {"scene_id": "s1"}},
        {"event_id": "e2", "timeline_id": "present", "narrative_layer": "performance",
         "relation": "new_event", "referent_event_id": None, "interpretation_status": "explicit",
         "entities": ["person-a"], "before": [right], "after": [],
         "context": {"scene_id": "s1", "continuity_from_event_id": "e1"}},
    ]}


@pytest.mark.parametrize("previous,current", [
    (fact(True, "presence"), fact(False, "presence")),
    (fact("standing"), fact("sitting")),
    (fact("room-a", "location", spatial_mode="absolute", reference_frame_id="floor-a"),
     fact("room-b", "location", spatial_mode="absolute", reference_frame_id="floor-a")),
    (fact("person-a", "holder", "ring", holding_mode="exclusive"),
     fact("person-b", "holder", "ring", holding_mode="exclusive")),
])
def test_explicit_independent_continuous_state_change_is_candidate_not_verdict(previous, current):
    result = analyze_scene_ledger(ledger(previous, current))
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["status"] == "candidate" and candidate["requires_verification"] is True
    assert candidate["severity_certainty"] == "unknown"
    assert "verdict" not in result and "blocking" not in candidate
    assert candidate["event_ids"] == ["e1", "e2"]
    assert result["source_binding"] == "source-sha"
    same = ledger(previous, deepcopy(previous))
    assert analyze_scene_ledger(same)["candidates"] == []


@pytest.mark.parametrize("relation", ["same_event", "continuation", "unknown"])
def test_lift_then_drag_restatement_and_continuation_are_not_a_second_action(relation):
    data = ledger()
    data["events"][1].update(relation=relation, referent_event_id="e1")
    data["events"][0]["context"]["description"] = "父亲揪领往上拽"
    data["events"][1]["context"]["description"] = "将他拖起；可能是同一事件展开"
    result = analyze_scene_ledger(data)
    assert result["candidates"] == []
    assert result["retained_ambiguities"][-1]["reason"] == "same_continuing_or_unknown_event"


@pytest.mark.parametrize("layer", ["summary", "background", "closing_summary"])
def test_summary_and_background_are_not_physical_repetitions(layer):
    data = ledger()
    data["events"][1]["narrative_layer"] = layer
    assert analyze_scene_ledger(data)["candidates"] == []


def test_previous_summary_is_not_used_as_certain_performance_state():
    data = ledger()
    data["events"][0]["narrative_layer"] = "summary"
    assert analyze_scene_ledger(data)["candidates"] == []


def test_no_implicit_temporal_continuity_across_a_cut():
    data = ledger()
    data["events"][1]["context"].pop("continuity_from_event_id")
    assert analyze_scene_ledger(data)["candidates"] == []


def test_memory_and_present_are_separate_and_two_explicit_past_events_can_be_checked():
    data = ledger()
    data["events"][0]["timeline_id"] = "childhood"
    assert analyze_scene_ledger(data)["candidates"] == []
    data["events"][1]["timeline_id"] = "childhood"
    assert len(analyze_scene_ledger(data)["candidates"]) == 1


@pytest.mark.parametrize("where", ["event", "fact"])
def test_phone_speaker_is_not_silently_put_in_the_room(where):
    data = ledger(fact(True, "presence"), fact(False, "presence"))
    if where == "event":
        data["events"][1]["context"]["channel"] = "phone"
    else:
        data["events"][1]["before"][0]["qualifiers"]["scope"] = "phone"
    assert analyze_scene_ledger(data)["candidates"] == []


def test_shared_holding_does_not_require_exclusive_single_owner():
    data = ledger(fact(["a", "b"], "holder", "ring", holding_mode="shared"),
                  fact(["b", "a"], "holder", "ring", holding_mode="shared"))
    assert analyze_scene_ledger(data)["candidates"] == []
    data["events"][1]["before"][0] = fact("a", "holder", "ring", holding_mode="exclusive")
    assert analyze_scene_ledger(data)["candidates"] == []


def test_relative_space_and_different_coordinate_frames_remain_unassessed():
    left = fact("left-of-father", "location", spatial_mode="relative", reference_frame_id="camera-a")
    right = fact("right-of-father", "location", spatial_mode="relative", reference_frame_id="camera-a")
    result = analyze_scene_ledger(ledger(left, right))
    assert result["candidates"] == []
    assert "relative_or_unknown_space" in {item["reason"] for item in result["retained_ambiguities"]}
    left["qualifiers"]["spatial_mode"] = right["qualifiers"]["spatial_mode"] = "absolute"
    right["qualifiers"]["reference_frame_id"] = "camera-b"
    assert analyze_scene_ledger(ledger(left, right))["candidates"] == []


@pytest.mark.parametrize("certainty", ["inferred", "ambiguous", "unknown"])
def test_unproven_fact_or_event_does_not_become_confirmed_major(certainty):
    data = ledger()
    data["events"][1]["before"][0]["certainty"] = certainty
    assert analyze_scene_ledger(data)["candidates"] == []
    data = ledger()
    data["events"][1]["interpretation_status"] = certainty
    assert analyze_scene_ledger(data)["candidates"] == []


@pytest.mark.parametrize("change", ["evidence", "scope", "subject", "posture", "presence"])
def test_unsupported_or_unlocated_fact_is_retained_without_semantic_guess(change):
    data = ledger()
    target = data["events"][1]["before"][0]
    if change == "evidence":
        target["evidence_refs"] = []
    elif change == "scope":
        target["qualifiers"].pop("scope")
    elif change == "subject":
        target["subject_id"] = "unknown"
    elif change == "posture":
        target["value"] = "比他更小，像要站起来"
    else:
        target.update(predicate="presence", value="false")
    result = analyze_scene_ledger(data)
    assert result["candidates"] == [] and result["retained_ambiguities"]


def test_no_prose_extraction_or_similarity_infers_a_conflict():
    data = ledger()
    for event in data["events"]:
        event["before"] = event["after"] = []
    data["events"][0]["context"]["description"] = "他站在大厅。"
    data["events"][1]["context"]["description"] = "他突然已经坐在另一个房间。"
    assert analyze_scene_ledger(data)["candidates"] == []


def test_a_state_change_within_one_event_is_an_action_not_boundary_conflict():
    data = ledger()
    data["events"] = data["events"][:1]
    data["events"][0]["before"] = [fact("sitting")]
    data["events"][0]["after"] = [fact("standing")]
    assert analyze_scene_ledger(data)["candidates"] == []


def test_a_shown_transfer_changes_the_next_expected_state():
    data = ledger(fact("a", "holder", "key", holding_mode="exclusive"),
                  fact("b", "holder", "key", holding_mode="exclusive"))
    transfer = deepcopy(data["events"][1])
    transfer.update(event_id="transfer", before=[fact("a", "holder", "key", holding_mode="exclusive")],
                    after=[fact("b", "holder", "key", holding_mode="exclusive")])
    data["events"].insert(1, transfer)
    data["events"][-1]["context"]["continuity_from_event_id"] = "transfer"
    assert analyze_scene_ledger(data)["candidates"] == []


def test_stale_predecessor_cannot_skip_an_intervening_performance():
    data = ledger()
    middle = deepcopy(data["events"][0])
    middle.update(event_id="middle", before=[], after=[])
    data["events"].insert(1, middle)
    assert analyze_scene_ledger(data)["candidates"] == []


@pytest.mark.parametrize("target", ["missing", "e2", "future"])
def test_invalid_forward_or_self_continuity_is_retained(target):
    data = ledger()
    data["events"][1]["context"]["continuity_from_event_id"] = target
    assert analyze_scene_ledger(data)["candidates"] == []


def test_conflicting_extracted_facts_are_uncertain_and_not_silently_last_wins():
    data = ledger()
    data["events"][0]["after"].append(fact("sitting"))
    result = analyze_scene_ledger(data)
    assert result["candidates"] == []
    assert result["status"] == "needs_attention"
    assert result["errors"] == ["INTERNALLY_CONFLICTING_FACT_SET"]
    assert any(item["reason"] == "internally_conflicting_fact_set" for item in result["retained_ambiguities"])


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("predicate,values,qualifiers", [
    ("posture", ("standing", "sitting"), {}),
    ("presence", (True, False), {}),
    ("holder", ("person-a", "person-b"), {"holding_mode": "exclusive"}),
    ("location", ("room-a", "room-b"), {"spatial_mode": "absolute", "reference_frame_id": "building-a"}),
])
def test_single_event_internal_conflict_is_auxiliary_technical_stop(phase, predicate, values, qualifiers):
    data = ledger()
    data["events"] = data["events"][:1]
    data["events"][0][phase] = [fact(value, predicate, **qualifiers) for value in values]
    result = analyze_scene_ledger(data)
    assert result["status"] == "needs_attention" and result["errors"] == ["INTERNALLY_CONFLICTING_FACT_SET"]
    assert result["candidates"] == [] and "verdict" not in result
    # This says the extractor's required state ledger is unreliable, not that
    # the author must rewrite a manuscript to repair the auxiliary format.
    assert "writer_revision" not in result


def test_different_frames_at_same_phase_are_uncertain_not_internal_contradiction():
    data = ledger()
    data["events"][0]["before"] = [
        fact("left", "location", spatial_mode="absolute", reference_frame_id="camera-a"),
        fact("right", "location", spatial_mode="absolute", reference_frame_id="camera-b"),
    ]
    result = analyze_scene_ledger(data)
    assert result["status"] == "analysis_complete" and result["errors"] == []
    assert any(item["reason"] == "different_spatial_frames" for item in result["retained_ambiguities"])


@pytest.mark.parametrize("ambiguity", ["fact", "event", "channel"])
def test_uncertain_or_remote_alternative_states_are_not_turned_into_technical_stop(ambiguity):
    data = ledger()
    data["events"] = data["events"][:1]
    data["events"][0]["before"] = [fact("standing"), fact("sitting")]
    if ambiguity == "fact":
        data["events"][0]["before"][1]["certainty"] = "ambiguous"
    elif ambiguity == "event":
        data["events"][0]["interpretation_status"] = "ambiguous"
    else:
        data["events"][0]["context"]["channel"] = "phone"
    result = analyze_scene_ledger(data)
    assert result["status"] == "analysis_complete" and result["errors"] == []


def test_identical_duplicate_facts_collapse_and_evidence_is_preserved():
    data = ledger()
    duplicate = fact("standing")
    duplicate["evidence_refs"] = ["draft:second-location"]
    data["events"][0]["after"].append(duplicate)
    result = analyze_scene_ledger(data)
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["evidence_refs"] == ["draft:scene1:event", "draft:second-location"]


def test_identity_binding_changes_candidate_identity_and_input_is_immutable():
    data = ledger()
    saved = deepcopy(data)
    first = analyze_scene_ledger(data)
    assert data == saved and first == check_scene_ledger(data)
    data["header"]["draft_binding"] = "new-draft"
    second = analyze_scene_ledger(data)
    assert first["candidates"][0]["candidate_id"] != second["candidates"][0]["candidate_id"]


@pytest.mark.parametrize("data", [None, {}, {"events": "prose"}, {"events": [None]},
                                  {"events": [{"event_id": "unknown"}]},
                                  {"events": [{"event_id": "same"}, {"event_id": "same"}]}])
def test_invalid_input_cannot_be_reported_as_a_release_pass(data):
    result = analyze_scene_ledger(data)
    assert result["status"] == "needs_attention" and result["errors"]
    assert result["candidates"] == [] and "verdict" not in result


def test_empty_ledger_is_only_empty_analysis_not_content_pass():
    result = analyze_scene_ledger({"events": []})
    assert result["status"] == "analysis_complete" and result["requires_semantic_verification"]
    assert "verdict" not in result and result["candidates"] == []
