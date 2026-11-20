"""Endpoint-only arithmetic regression; no service or media dispatch."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_director_endpoint_contract_v4 as endpoint
from src.content_factory import creative_complete_production_pipeline_v2 as ranges
from tests.test_creative_complete_production_pipeline_v2 import actual_inputs, v2_fixture


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "data/production_revisions/shared_full_production_20261012/probe_v4"


def endpoint_fixture():
    script, manifest, initial, direction, performances = v2_fixture()
    edges = {row["range_id"]: row for row in ranges.candidate_graph(script, manifest)["ranges"]}
    native = {key: deepcopy(value) for key, value in direction["native"].items() if key != "segments"}
    native["segments"] = [{**{key: deepcopy(value) for key, value in row.items() if key != "range_id"},
        "end_source_ref": edges[row["range_id"]]["end_source_ref"]}
        for row in direction["native"]["segments"]]
    return script, manifest, initial, native, direction, performances


def generic_native(segments):
    return {"availability": "known", "whole_observation": "桌边两人当面交涉",
        "emotional_progression": "接收要求到作出选择", "visual_style": "写实职场",
        "segments": [{"information_change": "接收当前新增信息", "observation": "当前人物反应",
            "emotional_turn": "当前情绪推进", "cut_reason": "留出下一回应",
            "end_source_ref": end, "budget_tier": tier} for end, tier in segments]}


def test_schema_only_exposes_endpoint_tier_and_existing_creative_fields():
    script, manifest, _, raw, *_ = endpoint_fixture()
    schema = endpoint.whole_direction_schema(script, manifest)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    fields = schema["properties"]["segments"]["items"]["properties"]
    assert set(fields) == {"end_source_ref", "budget_tier", "information_change", "observation",
        "emotional_turn", "cut_reason"}
    assert not {"start_source_ref", "start_index", "source_refs", "range_id", "target_seconds",
        "reaction_reserve_seconds", "script_sha256"} & fields.keys()


def test_preview_uses_endpoint_rule_full_source_and_existing_transport_without_old_range_rule():
    script, manifest, initial, raw, *_ = endpoint_fixture()
    latest_failure = {"ordinal": 517, "complete_native_direction": {"known_failed": "完整原文"},
        "diagnosis": "来源缺漏和重复"}
    inputs = endpoint.build_director_input(script, manifest, initial, "完整教学参考正文", {"style": "写实"}, [latest_failure])
    request = endpoint.build_director_request(inputs, script, manifest)
    assert request["model"] == "MiniMax-M3"
    assert request["parameters"] == {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 10000}
    assert request["messages"][0]["content"] == endpoint.DIRECTOR_RULE
    assert "从candidate_graph的ranges选择range_id" not in request["messages"][0]["content"]
    actual = json.loads(request["messages"][1]["content"])
    assert actual == inputs
    assert actual["full_current_script"] == script and actual["shared_manifest"] == manifest
    assert actual["known_complete_failure_diagnostics"] == [latest_failure]
    assert actual["reference_fulltext"] == "完整教学参考正文"
    assert "candidate_graph" not in actual and "endpoint_graph" in actual
    assert request["inner_document_schema"] == endpoint.whole_direction_schema(script, manifest)
    assert set(request["structured_schema"]["properties"]) == {"payload_json"}
    assert request["preview_only"] and not request["dispatched"] and not request["calls_authorized"]
    Draft202012Validator(request["inner_document_schema"]).validate(raw)
    changed = deepcopy(inputs)
    changed["endpoint_graph"]["endpoint_options"].pop()
    with pytest.raises(ValueError):
        endpoint.build_director_request(changed, script, manifest)


def test_program_derives_unique_contiguous_ranges_and_delegates_exact_v2_projection():
    script, manifest, _, raw, v2, _ = endpoint_fixture()
    original = deepcopy(raw)
    compiled = endpoint.compile_direction(raw, script, manifest)
    assert compiled["v2_direction_projection"] == v2
    assert compiled["native"] == raw == original
    assert compiled["native_sha256"] == endpoint.digest(raw)
    assert compiled["endpoint_mapping_sha256"] == endpoint.digest(compiled["endpoint_mapping"])
    assert compiled["v2_projection_sha256"] == endpoint.digest(v2)
    assert [row["range_id"] for row in compiled["endpoint_mapping"]] == ["R0001_0002", "R0003_0003"]
    refs = [ref for row in compiled["segments"] for ref in row["source_refs"]]
    assert refs == ["B1.S01", "B1.S02", "B1.S03"] and len(set(refs)) == len(refs)
    assert compiled["all_native_creative_values_preserved"]
    assert compiled["model_narrative_cut_choice_preserved"]
    assert not compiled["fresh_service_response_verified"]
    assert not compiled["production_adopted"] and not compiled["legacy_failed_response_adopted"]
    assert not compiled["calls_authorized"] and not compiled["actual_media_quality_passed"]


@pytest.mark.parametrize("endpoints", [("B1.S02", "B1.S02"), ("B1.S03", "B1.S02")])
def test_repeated_or_reversed_endpoints_fail_without_modifying_native(endpoints):
    script, manifest, _, raw, *_ = endpoint_fixture()
    for row, end in zip(raw["segments"], endpoints):
        row["end_source_ref"] = end
    before = deepcopy(raw)
    with pytest.raises(endpoint.EndpointContractError) as exc:
        endpoint.compile_direction(raw, script, manifest)
    assert exc.value.code == "ENDPOINT_ORDER_INVALID"
    assert raw == before == exc.value.diagnostic["native"]


def test_missing_tail_is_rejected_instead_of_appended():
    script, manifest, _, raw, *_ = endpoint_fixture()
    raw["segments"].pop()
    before = deepcopy(raw)
    with pytest.raises(endpoint.EndpointContractError) as exc:
        endpoint.compile_direction(raw, script, manifest)
    assert exc.value.code == "ENDPOINT_TAIL_MISSING"
    assert exc.value.diagnostic["missing_source_refs"] == ["B1.S03"]
    assert raw == before


@pytest.mark.parametrize("field,value", [("range_id", "R0001_0002"), ("start_source_ref", "B1.S01"),
    ("target_seconds", 15), ("reaction_reserve_seconds", .3), ("source_refs", ["B1.S01"])])
def test_model_cannot_override_derived_fields(field, value):
    script, manifest, _, raw, *_ = endpoint_fixture()
    raw["segments"][0][field] = value
    before = deepcopy(raw)
    with pytest.raises(ValueError):
        endpoint.compile_direction(raw, script, manifest)
    assert raw == before


def test_actual_unavailable_range_is_not_shortened_or_split_by_compiler():
    script, manifest = actual_inputs()
    raw = generic_native([("B2.S02", "minimum"), ("B6.S05", "minimum")])
    before = deepcopy(raw)
    report = endpoint.audit_endpoint_choices(raw, script, manifest)
    assert report["whole_source_coverage_complete"]
    assert report["segments"][0]["minimum_required_seconds_for_requested_tier"] > 15
    with pytest.raises(endpoint.EndpointContractError) as exc:
        endpoint.compile_direction(raw, script, manifest)
    assert exc.value.code == "ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE"
    assert raw == before and not exc.value.diagnostic["rejected_response_adopted"]


def test_actual_known_tier_is_rejected_if_unavailable_for_derived_range():
    script, manifest = actual_inputs()
    graph = ranges.candidate_graph(script, manifest)
    singles = [row for row in graph["ranges"] if len(row["source_refs"]) == 1]
    raw = generic_native([(row["end_source_ref"], "minimum") for row in singles])
    raw["segments"][0]["budget_tier"] = "action"
    report = endpoint.audit_endpoint_choices(raw, script, manifest)
    assert report["segments"][0]["range_exists_in_actual_graph"]
    assert not report["segments"][0]["budget_available"]
    with pytest.raises(endpoint.EndpointContractError) as exc:
        endpoint.compile_direction(raw, script, manifest)
    assert exc.value.code == "ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE"


def test_actual_numeric_minimum_is_dynamic_nine_segments_one_hundred_seconds():
    script, manifest = actual_inputs()
    graph = ranges.candidate_graph(script, manifest)
    bounds = endpoint.numeric_plan_bounds(graph)
    assert len(graph["ranges"]) == 71
    assert bounds["minimum_complete_segment_count"] == 9
    assert bounds["minimum_complete_plan_seconds"] == 100
    assert bounds["numeric_lower_bound_only"] and not bounds["narrative_cuts_selected"]
    schema = endpoint.whole_direction_schema(script, manifest)
    assert schema["properties"]["segments"]["minItems"] == 9
    small_script, small_manifest, *_ = endpoint_fixture()
    assert endpoint.whole_direction_schema(small_script, small_manifest)["properties"]["segments"]["minItems"] == 1
    assert not bounds["semantic_action_feasibility_proven"]


def test_request_graph_preserves_all_real_edges_budgets_without_a_chosen_plan():
    script, manifest = actual_inputs()
    graph = ranges.candidate_graph(script, manifest)
    compact = endpoint.endpoint_request_graph(script, manifest)
    assert len(compact["endpoint_options"]) == len(graph["ranges"])
    assert compact["candidate_graph_sha256"] == endpoint.digest(graph)
    for option, edge in zip(compact["endpoint_options"], graph["ranges"]):
        assert option[:4] == [edge["start_source_ref"], edge["end_source_ref"],
            edge["normal_dialogue_seconds"], edge["minimum_nonadjacent_action_seconds"]]
        assert option[4] == [[budget["budget_tier"], budget["target_seconds"], budget["reaction_reserve_seconds"]]
            for budget in edge["budget_options"]]
    assert "selected_segments" not in compact
    assert endpoint.validate_endpoint_request_graph(compact, script, manifest)["all_edges_and_budgets_preserved"]
    for defect in ("edge", "budget", "count"):
        changed = deepcopy(compact)
        if defect == "edge": changed["endpoint_options"].pop()
        elif defect == "budget": changed["endpoint_options"][0][4][0][1] += 1
        else: changed["numeric_plan_bounds"]["minimum_complete_segment_count"] = 6
        with pytest.raises(ValueError, match="endpoint request graph changed"):
            endpoint.validate_endpoint_request_graph(changed, script, manifest)


def test_endpoint_request_uses_compatible_rule_native_schema_and_full_reference():
    import json
    from src.content_factory import creative_complete_production_pipeline_v3 as old_phase
    script, manifest, initial, *_ = endpoint_fixture()
    reference = {"R01": "完整参考机制原文，不照搬情节。"}
    inputs = endpoint.build_director_input(script, manifest, initial, reference, {})
    wire = endpoint.build_director_request(inputs, script, manifest)
    assert wire["model"] == "MiniMax-M3" and wire["role"] == "writer"
    assert wire["parameters"] == {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 10000}
    assert wire["preview_only"] and not wire["dispatched"] and not wire["calls_authorized"]
    assert wire["inner_document_schema"] == endpoint.whole_direction_schema(script, manifest)
    systems = [message["content"] for message in wire["messages"] if message["role"] == "system"]
    assert systems[0].startswith(endpoint.DIRECTOR_RULE)
    assert not systems[0].startswith(old_phase.DIRECTOR_RULE)
    users = [message for message in wire["messages"] if message["role"] == "user"]
    assert json.loads(users[0]["content"]) == inputs
    assert json.loads(users[0]["content"])["reference_fulltext"] == reference


def test_endpoint_request_cannot_use_changed_full_source_or_unfrozen_initial_state():
    script, manifest, initial, *_ = endpoint_fixture()
    inputs = endpoint.build_director_input(script, manifest, initial, "参考全文", {})
    changed = deepcopy(inputs)
    changed["full_current_script"]["title"] = "另一个来源"
    with pytest.raises(ValueError, match="differs from the current source"):
        endpoint.build_director_request(changed, script, manifest)
    changed = deepcopy(initial)
    changed["actors"][0]["emotion"] = "临时改写情绪"
    with pytest.raises(ValueError, match="differs from the frozen source"):
        endpoint.build_director_input(script, manifest, changed, "参考全文", {})


def test_valid_ranges_can_still_exceed_whole_film_cap_without_automatic_recut():
    script, manifest = actual_inputs()
    graph = ranges.candidate_graph(script, manifest)
    singles = [row for row in graph["ranges"] if len(row["source_refs"]) == 1]
    raw = generic_native([(row["end_source_ref"], max(row["budget_options"], key=lambda b: b["target_seconds"])["budget_tier"])
        for row in singles])
    before = deepcopy(raw)
    report = endpoint.audit_endpoint_choices(raw, script, manifest)
    assert report["total_target_seconds"] == 204
    assert report["whole_source_coverage_complete"] and report["all_ranges_and_budgets_numeric_valid"]
    with pytest.raises(endpoint.EndpointContractError) as exc:
        endpoint.compile_direction(raw, script, manifest)
    assert exc.value.code == "ENDPOINT_FILM_BUDGET_EXCEEDED"
    assert raw == before


@pytest.mark.parametrize("defect", ["mapping", "native", "projection", "source"])
def test_saved_endpoint_mapping_and_original_document_are_exactly_bound(defect):
    script, manifest, _, raw, *_ = endpoint_fixture()
    compiled = endpoint.compile_direction(raw, script, manifest)
    assert endpoint.verify_compiled_direction(compiled, script, manifest)["status"] == "endpoint_numeric_contract_valid"
    changed = deepcopy(compiled)
    if defect == "mapping": changed["endpoint_mapping"][0]["source_refs"].pop()
    elif defect == "native": changed["native"]["segments"][0]["cut_reason"] = "另一次切镜选择"
    elif defect == "projection": changed["v2_direction_projection"]["segments"][0]["target_seconds"] = 15
    else: changed["script_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        endpoint.verify_compiled_direction(changed, script, manifest)


def test_actual_517_format_projection_is_only_a_diagnostic_and_still_fails_timing():
    script, manifest = actual_inputs()
    receipt_path = PROBE / "call_517_whole_direction_v3_3.json"
    ledger_path = PROBE / "CALL_LEDGER.json"
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (receipt_path, ledger_path)}
    receipt = json.loads(receipt_path.read_text(encoding="utf8"))
    native_517 = json.loads(receipt["output"]["payload_json"])
    frozen_native = deepcopy(native_517)
    with pytest.raises(ValueError):
        endpoint.compile_direction(native_517, script, manifest)
    # This constructed object is intentionally NOT saved as a new service
    # response. Its only use is proving that an old range-format conversion
    # neither repairs the model's cuts nor passes the new timing contract.
    edges = {row["range_id"]: row for row in ranges.candidate_graph(script, manifest)["ranges"]}
    constructed = {key: deepcopy(value) for key, value in native_517.items() if key != "segments"}
    constructed["segments"] = [{**{key: deepcopy(value) for key, value in row.items() if key != "range_id"},
        "end_source_ref": edges[row["range_id"]]["end_source_ref"]} for row in native_517["segments"]]
    report = endpoint.audit_endpoint_choices(constructed, script, manifest)
    assert report["whole_source_coverage_complete"] and not report["repeated_source_refs"]
    assert len(report["segments"]) == 6 < report["numeric_plan_bounds"]["minimum_complete_segment_count"]
    too_long = [row for row in report["segments"] if row["minimum_required_seconds_for_requested_tier"] > 15]
    assert too_long
    assert not report["fresh_service_response_verified"] and not report["production_adopted"]
    assert not report["rejected_response_adopted"] and not report["calls_authorized"]
    with pytest.raises(endpoint.EndpointContractError) as exc:
        endpoint.compile_direction(constructed, script, manifest)
    assert exc.value.code == "ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE"
    assert native_517 == frozen_native
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
