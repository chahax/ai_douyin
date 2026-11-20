"""Offline endpoint-only director contract over the unchanged v2 timing graph.

The model chooses narrative endpoints and budget tiers. The compiler derives
the only contiguous start/range, then delegates arithmetic to frozen v2. This
module does not recover old model responses, authenticate a new response,
dispatch requests, approve acting, or choose narrative cuts.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json

from scripts import creative_json_document_transport_v1 as transport
from . import creative_complete_production_pipeline_v1 as local
from . import creative_complete_production_pipeline_v2 as ranges
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_director_endpoint_contract/v4"
digest = source.digest
DIRECTOR_RULE = (
    "你负责整片导演，根据完整正文的情绪与因果安排每段新增信息、观察对象、情绪转折和切镜理由。"
    "每段只选择end_source_ref与budget_tier，并填写本阶段原创作字段；不声明起点、range_id、来源数组或秒数。"
    "第一段起点是全文首来源，后续起点由上一段终点的下一个来源唯一确定。终点严格向后推进，最后到全文末来源。"
    "endpoint_graph的endpoint_columns和budget_columns说明候选列；用当前推导起点与所选终点核对真实可用档位。"
    "numeric_plan_bounds给出数学最少段数与时长下界，不是固定审美段数或表演通过；叙事拍不等于API视频段。"
    "保留全部原句原动作，不删对白、不拆原句、不加剧情；人物、场景与道具沿用shared_manifest。"
    "单段4至15秒、整片不超过180秒，预算和反应余量由程序派生，不靠加速或压扁表演满足预算。"
    "minimum、natural、reaction、action仅是预算档位，邻接动作的重叠只是数学假设；复杂动作仍待局部表演和全文审查。"
    "本阶段不填写局部动作排时、人物终态或状态变化；不要猜画面左右、换座或重建续段机位。"
    "每段创作意图必须对应本段实际连续来源，不能用未来事件解释当前段。"
    "失败诊断只作依据；返修须提交完整原生新计划，不能只转换旧格式、提交补丁或拼接旧稿。"
)


class EndpointContractError(ValueError):
    """Known numeric contract failure, without changing the native document."""

    def __init__(self, code, message, diagnostic):
        super().__init__(message)
        self.code = code
        self.diagnostic = deepcopy(diagnostic)


def numeric_plan_bounds(graph):
    """Count/cost DP; retain no chosen edge or narrative plan.

    For each segment count keep its cheapest complete suffix. Filtering by the
    film cap yields the exact minimum feasible count under this *numeric lower
    bound* graph, not an acting or semantic feasibility claim.
    """
    count = len(graph["source_refs"])
    outgoing = {index: [] for index in range(count)}
    for edge in graph["ranges"]:
        outgoing[edge["start_index"]].append(edge)
    costs = {count: {0: 0}}
    for index in range(count - 1, -1, -1):
        current = {}
        for edge in outgoing[index]:
            cost = min(budget["target_seconds"] for budget in edge["budget_options"])
            for suffix_count, suffix_cost in costs.get(edge["end_index_exclusive"], {}).items():
                segment_count = suffix_count + 1
                total = cost + suffix_cost
                current[segment_count] = min(current.get(segment_count, total), total)
        costs[index] = current
    feasible = {number: cost for number, cost in costs[0].items()
        if cost <= graph["maximum_film_seconds"]}
    if not feasible:
        raise ValueError("no numeric complete endpoint plan fits the film boundary")
    return {"minimum_complete_segment_count": min(feasible),
        "minimum_complete_plan_seconds": min(feasible.values()),
        "maximum_film_seconds": graph["maximum_film_seconds"],
        "numeric_lower_bound_only": True, "narrative_cuts_selected": False,
        "semantic_action_feasibility_proven": False}


def endpoint_request_graph(script, manifest):
    """Preserve every real graph edge/budget without asking for a start or ID."""
    graph = ranges.candidate_graph(script, manifest)
    return {"schema": VERSION + "/endpoint_request_graph",
        "script_sha256": digest(script), "global_manifest_sha256": digest(manifest),
        "candidate_graph_sha256": digest(graph), "source_refs": deepcopy(graph["source_refs"]),
        "endpoint_columns": ["derived_start_source_ref", "end_source_ref",
            "normal_dialogue_seconds", "action_lower_bound_seconds", "budgets",
            "minimum_remaining_target_seconds"],
        "budget_columns": ["budget_tier", "target_seconds", "reaction_reserve_seconds"],
        "endpoint_options": [[edge["start_source_ref"], edge["end_source_ref"],
            edge["normal_dialogue_seconds"], edge["minimum_nonadjacent_action_seconds"],
            [[budget["budget_tier"], budget["target_seconds"], budget["reaction_reserve_seconds"]]
                for budget in edge["budget_options"]], edge["minimum_remaining_target_seconds"]]
            for edge in graph["ranges"]],
        "numeric_plan_bounds": numeric_plan_bounds(graph),
        "start_is_previous_endpoint_plus_one": True,
        "model_selects_endpoints_and_budget_tiers": True,
        "normal_spoken_characters_per_second": graph["normal_spoken_characters_per_second"],
        "semantic_action_feasibility_proven": False, "actual_media_quality_passed": False,
        "calls_authorized": False}


def validate_endpoint_request_graph(document, script, manifest):
    expected = endpoint_request_graph(script, manifest)
    if document != expected:
        raise ValueError("endpoint request graph changed source, edge, budget or numeric bounds")
    return {"status": "endpoint_request_graph_valid", "request_graph_sha256": digest(document),
        "candidate_graph_sha256": expected["candidate_graph_sha256"],
        "all_edges_and_budgets_preserved": True, "narrative_cuts_selected": False,
        "calls_authorized": False}


def _document_schema(script, manifest, minimum_segments):
    # Reuse the existing creative fields, never maintain a competing creative
    # contract or permit model-declared timing/range metadata.
    old = ranges.whole_direction_schema(script, manifest)
    creative = {key: deepcopy(value)
        for key, value in old["properties"]["segments"]["items"]["properties"].items()
        if key not in ("range_id", "budget_tier")}
    creative.update(end_source_ref={"enum": list(source.catalog(script))},
        budget_tier={"enum": list(ranges.BUDGET_TIERS)})
    fields = {key: deepcopy(value) for key, value in old["properties"].items() if key != "segments"}
    fields["segments"] = source._array(source._obj(creative), minimum_segments, len(source.catalog(script)))
    return source._obj(fields)


def whole_direction_schema(script, manifest):
    graph = ranges.candidate_graph(script, manifest)
    minimum = numeric_plan_bounds(graph)["minimum_complete_segment_count"]
    return _document_schema(script, manifest, minimum)


def build_director_input(script, manifest, initial, reference_fulltext, preferences, diagnostics=()):
    local._validate_state(initial, manifest)
    if initial != local._frozen_initial(manifest):
        raise ValueError("endpoint director initial state differs from the frozen source")
    return {"full_current_script": deepcopy(script), "source_catalog": source.catalog(script),
        "shared_manifest": deepcopy(manifest), "planned_initial_state": deepcopy(initial),
        "reference_fulltext": reference_fulltext, "production_preferences": deepcopy(preferences),
        "endpoint_graph": endpoint_request_graph(script, manifest),
        "known_complete_failure_diagnostics": deepcopy(list(diagnostics))}


def build_director_request(inputs, script, manifest, model="MiniMax-M3"):
    """Request preview only; transport and model settings match the prior test.

    It deliberately does not call v3.build_request, whose system instruction
    requests range IDs and is incompatible with this endpoint schema.
    """
    validate_endpoint_request_graph(inputs["endpoint_graph"], script, manifest)
    if inputs["full_current_script"] != script or inputs["shared_manifest"] != manifest:
        raise ValueError("endpoint request input differs from the current source")
    if inputs["source_catalog"] != source.catalog(script) or inputs["planned_initial_state"] != local._frozen_initial(manifest):
        raise ValueError("endpoint request catalog or initial state differs from the frozen source")
    schema = whole_direction_schema(script, manifest)
    messages = [{"role": "system", "content": DIRECTOR_RULE},
        {"role": "user", "content": json.dumps(inputs, ensure_ascii=False, allow_nan=False)}]
    return {"role": "writer", "model": model, "operator_version": VERSION, "stage": "whole_direction",
        "parameters": {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 10000},
        "messages": transport.build_messages(messages, schema),
        "structured_schema": transport.build_envelope_schema(), "output_transport": transport.VERSION,
        "inner_document_schema": schema, "preview_only": True, "dispatched": False,
        "calls_authorized": False}


def audit_endpoint_choices(raw, script, manifest):
    """Read-only math for diagnostics, including rejected/too-short plans.

    A diagnostic may examine a locally constructed document. It never attests
    that the service submitted it or adopts it as a fresh response.
    """
    source._validate(_document_schema(script, manifest, 1), raw)
    graph = ranges.candidate_graph(script, manifest)
    bank = source.catalog(script)
    ordered = graph["source_refs"]
    indexes = {ref: index for index, ref in enumerate(ordered)}
    edges = {(edge["start_index"], edge["end_index_exclusive"]): edge for edge in graph["ranges"]}
    cursor = 0
    rows = []
    spent = 0
    all_numeric_valid = True
    for index, native in enumerate(raw["segments"], 1):
        end = indexes[native["end_source_ref"]] + 1
        advances = end > cursor
        refs = ordered[cursor:end] if advances else []
        edge = edges.get((cursor, end)) if advances else None
        budgets = edge["budget_options"] if edge else []
        budget = next((value for value in budgets if value["budget_tier"] == native["budget_tier"]), None)
        floor = ranges._range_floor(bank, refs)
        available = edge is not None and budget is not None
        if available:
            spent += budget["target_seconds"]
        else:
            all_numeric_valid = False
        rows.append({"segment_id": f"M{index:03d}", "derived_start_index": cursor,
            "end_index_exclusive": end, "end_source_ref": native["end_source_ref"],
            "source_refs": deepcopy(refs), "endpoint_strictly_advances": advances,
            "range_id": edge["range_id"] if edge else None,
            "range_exists_in_actual_graph": edge is not None,
            "budget_tier": native["budget_tier"], "budget_available": budget is not None,
            "budget": deepcopy(budget), "source_numeric_lower_bound": floor,
            "minimum_required_seconds_for_requested_tier": round(floor["source_lower_bound_seconds"]
                + ranges.BUDGET_TIERS[native["budget_tier"]]["reaction_reserve_seconds"]
                + ranges.BUDGET_TIERS[native["budget_tier"]]["additional_action_headroom_seconds"], 6),
            "provider_maximum_segment_seconds": source.MAX_SEGMENT_SECONDS,
            "whole_budget_has_numeric_completion": bool(available and all_numeric_valid
                and spent + edge["minimum_remaining_target_seconds"] <= ranges.MAX_FILM_SECONDS)})
        if advances:
            cursor = end
    actual_refs = [ref for row in rows for ref in row["source_refs"]]
    counts = Counter(actual_refs)
    bounds = numeric_plan_bounds(graph)
    return {"schema": VERSION + "/endpoint_audit", "native": deepcopy(raw),
        "native_sha256": digest(raw), "script_sha256": digest(script),
        "global_manifest_sha256": digest(manifest), "candidate_graph_sha256": digest(graph),
        "numeric_plan_bounds": bounds, "segments": rows,
        "segment_count_meets_numeric_minimum": len(rows) >= bounds["minimum_complete_segment_count"],
        "all_endpoints_strictly_advance": all(row["endpoint_strictly_advances"] for row in rows),
        "whole_source_coverage_complete": actual_refs == ordered,
        "missing_source_refs": [ref for ref in ordered if counts[ref] == 0],
        "repeated_source_refs": [ref for ref in ordered if counts[ref] > 1],
        "all_ranges_and_budgets_numeric_valid": all_numeric_valid,
        "total_target_seconds": spent if all_numeric_valid else None,
        "native_response_preserved": True, "fresh_service_response_verified": False,
        "rejected_response_adopted": False, "production_adopted": False,
        "semantic_action_feasibility_proven": False, "actual_media_quality_passed": False,
        "calls_authorized": False}


def compile_direction(raw, script, manifest):
    report = audit_endpoint_choices(raw, script, manifest)
    if not report["all_endpoints_strictly_advance"]:
        raise EndpointContractError("ENDPOINT_ORDER_INVALID", "director endpoints must strictly advance", report)
    if not report["whole_source_coverage_complete"]:
        raise EndpointContractError("ENDPOINT_TAIL_MISSING", "director endpoints must reach the complete original tail", report)
    if not report["all_ranges_and_budgets_numeric_valid"]:
        raise EndpointContractError("ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE",
            "derived contiguous range or chosen budget is unavailable in the actual timing graph", report)
    if not report["segment_count_meets_numeric_minimum"]:
        raise EndpointContractError("ENDPOINT_COUNT_BELOW_NUMERIC_MINIMUM",
            "director has fewer segments than the actual graph's numeric minimum", report)
    if any(not row["whole_budget_has_numeric_completion"] for row in report["segments"]):
        raise EndpointContractError("ENDPOINT_FILM_BUDGET_EXCEEDED",
            "whole endpoint budget exceeds the complete film 180 second boundary", report)
    source._validate(whole_direction_schema(script, manifest), raw)
    projected = {key: deepcopy(value) for key, value in raw.items() if key != "segments"}
    projected["segments"] = [{**{key: deepcopy(value) for key, value in native.items()
        if key != "end_source_ref"}, "range_id": row["range_id"]}
        for native, row in zip(raw["segments"], report["segments"])]
    compiled = ranges.compile_direction(projected, script, manifest)
    mapping = [{key: deepcopy(row[key]) for key in ("segment_id", "derived_start_index",
        "end_index_exclusive", "end_source_ref", "source_refs", "range_id", "budget_tier", "budget")}
        for row in report["segments"]]
    return {"schema": VERSION + "/direction", "script_sha256": digest(script),
        "global_manifest_sha256": digest(manifest), "native": deepcopy(raw), "native_sha256": digest(raw),
        "candidate_graph_sha256": report["candidate_graph_sha256"],
        "endpoint_mapping": mapping, "endpoint_mapping_sha256": digest(mapping),
        "v2_direction_projection": compiled, "v2_projection_sha256": digest(compiled),
        "segments": deepcopy(compiled["segments"]), "total_target_seconds": compiled["total_target_seconds"],
        "numeric_plan_bounds": deepcopy(report["numeric_plan_bounds"]),
        "whole_source_coverage_complete": True, "all_native_creative_values_preserved": True,
        "start_and_range_are_program_derived": True, "model_narrative_cut_choice_preserved": True,
        "native_response_preserved": True, "fresh_service_response_verified": False,
        "legacy_failed_response_adopted": False, "production_adopted": False,
        "semantic_action_feasibility_proven": False, "actual_media_quality_passed": False,
        "calls_authorized": False}


def verify_compiled_direction(compiled, script, manifest):
    expected = compile_direction(compiled["native"], script, manifest)
    if compiled != expected:
        raise ValueError("endpoint native, mapping, graph or v2 projection changed")
    return {"status": "endpoint_numeric_contract_valid", "native_sha256": expected["native_sha256"],
        "endpoint_mapping_sha256": expected["endpoint_mapping_sha256"],
        "v2_projection_sha256": expected["v2_projection_sha256"],
        "fresh_service_response_verified": False, "production_adopted": False,
        "semantic_action_feasibility_proven": False, "calls_authorized": False}
