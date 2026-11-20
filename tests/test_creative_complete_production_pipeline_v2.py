"""Offline arithmetic graph regression; no creative decision or media approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_complete_production_pipeline_v2 as c
from src.content_factory import creative_shared_production_contract_v1 as shared
from src.content_factory import creative_video_trial_contract_v1 as source
from tests.test_creative_complete_production_pipeline_v1 import complete_fixture


ROOT = Path(__file__).resolve().parents[1]
ACTUAL = ROOT / "data/production_revisions/shared_full_production_20261012/run_01"


def v2_fixture():
    script, manifest, initial, v1_direction, v1_performances = complete_fixture()
    native = {key: deepcopy(value) for key, value in v1_direction["native"].items() if key != "segments"}
    native["segments"] = [{**{key: deepcopy(value) for key, value in old.items()
        if key not in ("end_source_ref", "target_seconds", "reaction_reserve_seconds")},
        "range_id": rid, "budget_tier": "minimum"}
        for old, rid in zip(v1_direction["native"]["segments"], ("R0001_0002", "R0003_0003"))]
    direction = c.compile_direction(native, script, manifest)
    completed = []
    previous = deepcopy(initial)
    performances = []
    for segment, old in zip(direction["segments"], v1_performances):
        compiled = c.compile_performance(old["native"], script, manifest, segment, previous, completed)
        performances.append(compiled)
        completed.extend(segment["source_refs"])
        previous = deepcopy(compiled["planned_ending_state"])
    return script, manifest, initial, direction, performances


def actual_inputs():
    return json.loads((ACTUAL / "ADOPTED_SOURCE.json").read_text(encoding="utf8"))["script"], json.loads((ACTUAL / "SHARED_MANIFEST.json").read_text(encoding="utf8"))


def test_graph_all_ranges_are_contiguous_numeric_choices_and_not_auto_director():
    script, manifest, *_ = complete_fixture()
    graph = c.candidate_graph(script, manifest)
    ordered = graph["source_refs"]
    assert graph["range_selection_is_model_owned"]
    assert graph["targets_and_reserves_are_program_derived"]
    assert not graph["semantic_action_feasibility_proven"]
    for edge in graph["ranges"]:
        assert edge["source_refs"] == ordered[edge["start_index"]:edge["end_index_exclusive"]]
        for budget in edge["budget_options"]:
            assert 4 <= budget["target_seconds"] <= 15
            assert edge["source_lower_bound_seconds"] + budget["reaction_reserve_seconds"] <= budget["target_seconds"]
    assert "chosen_segments" not in graph
    assert len({edge["range_id"] for edge in graph["ranges"]}) == len(graph["ranges"])


def test_compact_request_graph_preserves_every_numeric_edge_budget_and_source_without_cut_choice():
    script, manifest = actual_inputs()
    rich = c.candidate_graph(script, manifest)
    compact = c.model_candidate_graph(script, manifest)
    assert compact == c.compact_request_graph(script, manifest)
    assert compact["rich_graph_sha256"] == c.digest(rich)
    assert compact["source_refs"] == rich["source_refs"]
    assert len(compact["ranges"]) == len(rich["ranges"]) == 71
    for row, edge in zip(compact["ranges"], rich["ranges"]):
        assert row[:5] == [edge["range_id"], edge["start_index"], edge["end_index_exclusive"],
            edge["normal_dialogue_seconds"], edge["minimum_nonadjacent_action_seconds"]]
        assert row[5] == [[budget["budget_tier"], budget["target_seconds"], budget["reaction_reserve_seconds"]] for budget in edge["budget_options"]]
        assert row[6] == edge["minimum_remaining_target_seconds"]
    result = c.validate_compact_request_graph(compact, script, manifest)
    assert result["every_edge_and_budget_preserved"]
    assert not result["automatic_narrative_cut_selected"]
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(rich, ensure_ascii=False)) / 3
    for defect in ("drop_edge", "budget", "source", "hash"):
        wrong = deepcopy(compact)
        if defect == "drop_edge": wrong["ranges"].pop()
        elif defect == "budget": wrong["ranges"][0][5][0][1] += 1
        elif defect == "source": wrong["source_refs"].reverse()
        else: wrong["rich_graph_sha256"] = "f" * 64
        with pytest.raises(ValueError, match="compact candidate projection changed"):
            c.validate_compact_request_graph(wrong, script, manifest)


def test_model_selects_range_and_tier_but_cannot_supply_or_override_arithmetic():
    script, manifest, _, direction, _ = v2_fixture()
    schema = c.whole_direction_schema(script, manifest)
    Draft202012Validator.check_schema(schema)
    fields = schema["properties"]["segments"]["items"]["properties"]
    assert "range_id" in fields and "budget_tier" in fields
    for constant in ("script_sha256", "target_seconds", "reaction_reserve_seconds", "end_source_ref", "source_refs"):
        assert constant not in fields
    assert direction["native"] != direction["v1_direction_projection"]["native"]
    assert not direction["legacy_failed_response_adopted"]
    native = deepcopy(direction["native"])
    native["segments"][0]["target_seconds"] = 15
    with pytest.raises(ValueError): c.compile_direction(native, script, manifest)


@pytest.mark.parametrize("defect", ["repeat", "skip", "missing_tail", "wrong_tier"])
def test_arithmetic_choices_do_not_allow_source_path_overlap_omission_or_wrong_tier(defect):
    script, manifest, _, direction, _ = v2_fixture()
    raw = deepcopy(direction["native"])
    if defect == "repeat": raw["segments"][1]["range_id"] = raw["segments"][0]["range_id"]
    elif defect == "skip": raw["segments"][0]["range_id"] = "R0002_0002"
    elif defect == "missing_tail": raw["segments"].pop()
    else: raw["segments"][0]["budget_tier"] = "made_up"
    before = deepcopy(raw)
    with pytest.raises(ValueError): c.compile_direction(raw, script, manifest)
    assert raw == before


def test_v1_local_state_and_render_contract_continue_to_apply_to_the_full_v2_plan():
    script, manifest, initial, direction, performances = v2_fixture()
    result = c.compile_complete(direction, performances, script, manifest, initial)
    assert result["schema"] == c.VERSION + "/complete"
    assert result["whole_source_coverage_complete"]
    assert result["whole_film_performance_complete"]
    assert result["direction"]["native"] == direction["native"]
    assert result["action_timing_lower_bound_replaced_by_local_estimates"]
    assert result["source_state_semantic_review_complete"] is False
    assert not result["actual_media_quality_passed"]
    assert c.render_prompt(performances[0], script, manifest).count("请看这张纸。") == 1
    assert "我先看一下。" not in c.render_prompt(performances[0], script, manifest)
    changed = deepcopy(direction)
    changed["v1_direction_projection"]["segments"][0]["reaction_reserve_seconds"] = 0
    with pytest.raises(ValueError): c.compile_complete(changed, performances, script, manifest, initial)


def test_actual_514_515_516_each_failed_first_five_ranges_without_mutating_native_evidence():
    script, _ = actual_inputs()
    for ordinal in (514, 515, 516):
        path = next(ACTUAL.glob(f"call_{ordinal}_*.json"))
        before = path.read_bytes()
        receipt = json.loads(before)
        native = json.loads(receipt["output"]["payload_json"])
        original = deepcopy(native)
        report = c.rejected_direction_timing_report(native, script)
        assert report["arithmetic_failed_segment_indexes"] == [1, 2, 3, 4, 5]
        assert report["segments"][0]["normal_dialogue_seconds"] == pytest.approx(62 / 3.3, abs=1e-6)
        assert report["segments"][1]["normal_dialogue_seconds"] == pytest.approx(75 / 3.3, abs=1e-6)
        assert report["total_original_spoken_characters"] == 309
        assert report["total_normal_dialogue_seconds"] == pytest.approx(309 / 3.3, abs=1e-6)
        assert not report["rejected_response_adopted"]
        assert native == original and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()


def test_actual_script_has_numeric_path_but_no_impossible_old_beat_ranges():
    script, manifest = actual_inputs()
    graph = c.candidate_graph(script, manifest)
    assert graph["minimum_complete_plan_seconds"] <= 180
    old_beat_ranges = {(a, b) for a, b in (("B1.S01", "B1.S03"), ("B2.S01", "B2.S04"),
        ("B3.S01", "B3.S03"), ("B4.S01", "B4.S04"), ("B5.S01", "B5.S04"))}
    assert not any((edge["start_source_ref"], edge["end_source_ref"]) in old_beat_ranges for edge in graph["ranges"])
    first_sentence = next(row for row in graph["ranges"] if row["source_refs"] == ["B1.S01"])
    natural = next(row for row in first_sentence["budget_options"] if row["budget_tier"] == "natural")
    assert natural["target_seconds"] == 15
    assert first_sentence["normal_dialogue_seconds"] == pytest.approx(40 / 3.3, abs=1e-6)


def test_real_range_forbids_a_known_but_numerically_unavailable_action_tier():
    script, manifest = actual_inputs()
    graph = c.candidate_graph(script, manifest)
    edge = next(row for row in graph["ranges"] if row["source_refs"] == ["B1.S01"])
    assert "natural" in {row["budget_tier"] for row in edge["budget_options"]}
    assert "minimum" in {row["budget_tier"] for row in edge["budget_options"]}
    assert "action" not in {row["budget_tier"] for row in edge["budget_options"]}
    raw = {"availability": "known", "whole_observation": "桌边两人当面交涉", "emotional_progression": "接收要求到作出选择",
        "visual_style": "写实职场", "segments": [{"information_change": "接收当前公司要求", "observation": "当前听者反应",
            "emotional_turn": "注意力转向当前矛盾", "cut_reason": "留出下一回应", "range_id": edge["range_id"], "budget_tier": "action"}]}
    schema = c.whole_direction_schema(script, manifest)
    with pytest.raises(Exception): Draft202012Validator(schema).validate(raw)
    with pytest.raises(ValueError): c.compile_direction(raw, script, manifest)


def test_each_segment_within_fifteen_seconds_can_still_exceed_full_film_without_recut():
    script, manifest = actual_inputs()
    graph = c.candidate_graph(script, manifest)
    singles = [row for row in graph["ranges"] if len(row["source_refs"]) == 1]
    selected = [(edge, max(edge["budget_options"], key=lambda row: row["target_seconds"])) for edge in singles]
    assert all(budget["target_seconds"] <= 15 for _, budget in selected)
    assert sum(budget["target_seconds"] for _, budget in selected) == 204 > 180
    raw = {"availability": "known", "whole_observation": "桌边两人当面交涉", "emotional_progression": "接收要求到作出选择",
        "visual_style": "写实职场", "segments": [{"information_change": "接收当前新增信息", "observation": "当前人物反应",
            "emotional_turn": "当前情绪推进", "cut_reason": "留出下一回应", "range_id": edge["range_id"], "budget_tier": budget["budget_tier"]}
            for edge, budget in selected]}
    Draft202012Validator(c.whole_direction_schema(script, manifest)).validate(raw)
    original = deepcopy(raw)
    with pytest.raises(ValueError, match="whole budget has no possible completion"):
        c.compile_direction(raw, script, manifest)
    assert raw == original


def test_single_unfit_original_sentence_is_a_source_failure_not_silent_truncation():
    script, manifest, *_ = complete_fixture()
    bad = deepcopy(script)
    bad["beats"][0]["steps"][1]["text"] = "字" * 60
    pending_policy = deepcopy(manifest["provider_policy"])
    context = json.loads(next(row for row in manifest["provenance_catalog"] if row["source_id"] == "frozen_source_context")["text"])
    original = deepcopy(bad)
    bad_manifest = shared.build_pending_manifest(bad, context, pending_policy,
        [deepcopy(row) for row in manifest["provenance_catalog"] if row["source_id"] != "frozen_source_context"])
    with pytest.raises(ValueError, match="no complete unchanged-source timing path"):
        c.candidate_graph(bad, bad_manifest)
    assert bad == original


def test_graph_adjacent_overlap_is_an_unverified_lower_bound_and_not_an_action_duration():
    script, manifest, *_ = complete_fixture()
    graph = c.candidate_graph(script, manifest)
    edge = next(row for row in graph["ranges"] if row["source_refs"] == ["B1.S01", "B1.S02"])
    assert edge["adjacent_action_overlap_lower_bound_assumptions"][0]["source_ref"] == "B1.S01"
    assert edge["action_overlap_semantics_verified"] is False
    action_only = next(row for row in graph["ranges"] if row["source_refs"] == ["B1.S01"])
    assert action_only["minimum_nonadjacent_action_seconds"] == .25
    assert action_only["minimum_nonadjacent_action_seconds_is_not_actual_duration"]
