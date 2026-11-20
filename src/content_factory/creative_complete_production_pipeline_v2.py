"""Director choices over precomputed source ranges and timing budget tiers.

The program supplies arithmetic; the model still chooses narrative boundaries
and observation. Candidate timing is a lower-bound planning estimate, not proof
that complex actions, acting or generated audio fit. Frozen v1 is unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import math

from . import creative_complete_production_pipeline_v1 as prior
from . import creative_video_trial_contract_v1 as source
from . import creative_shared_production_contract_v1 as shared

VERSION = "creative_complete_production_pipeline/v2"
MAX_FILM_SECONDS = prior.MAX_FILM_SECONDS
ACTION_MINIMUM_SECONDS = .25
BUDGET_TIERS = {
    "minimum": {"reaction_reserve_seconds": .3, "additional_action_headroom_seconds": 0.0},
    "natural": {"reaction_reserve_seconds": .7, "additional_action_headroom_seconds": 1.5},
    "reaction": {"reaction_reserve_seconds": 1.5, "additional_action_headroom_seconds": 1.0},
    "action": {"reaction_reserve_seconds": .7, "additional_action_headroom_seconds": 3.5},
}
RULE = prior.RULE + (
    "整片导演的当前协议不填写target_seconds或reaction_reserve_seconds，也不自己计算秒数。"
    "只从程序candidate_graph选择range_id和budget_tier；每range公开完整来源范围、对白字数/秒数及可选预算。"
    "按源顺序把range连成完整路径：首range从全文第一个来源开始，下一个range紧接上一range末来源，最后到全文末来源。"
    "全部原文来源一次覆盖，不能把一个叙事beat强塞一个15秒视频段。"
    "minimum只是最低下界，natural给必要动作余量，reaction给接收反应余量，action给动作余量；档位不是表演质量等级。"
    "程序只枚举可选连续范围，不替导演选切点；目标秒数和反应窗口从选定预算派生，不回填模型原文。"
    "动作0.25秒为合同下界，邻接动作的可重叠只是下界假设；明确说完后动作、复杂动作时长仍须下游逐段安排和全文审查。"
    "若实际表演不适合所选预算，提交完整计划返修而不是加速、删对白或自动改变切点。")

build_initial_state = prior.build_initial_state
performance_schema = prior.performance_schema
compile_performance = prior.compile_performance
render_prompt = prior.render_prompt
digest = source.digest


def _range_floor(bank, refs):
    """Safe numeric lower bound, without interpreting action semantics.

    Adjacent actions may share current speech under the existing local timing
    contract, so their minimum is conservatively hidden. This does not authorize
    that overlap or establish that it respects the source's temporal meaning.
    """
    speech = sum(source.spoken_seconds(bank[ref]) for ref in refs)
    visible_overlap_candidates = []
    separate_actions = []
    for i, ref in enumerate(refs):
        if bank[ref]["kind"] != "action":
            continue
        neighbors = [refs[j] for j in (i - 1, i + 1) if 0 <= j < len(refs) and bank[refs[j]]["kind"] == "dialogue"]
        if neighbors:
            visible_overlap_candidates.append({"source_ref": ref, "adjacent_current_dialogue_refs": neighbors})
        else:
            separate_actions.append(ref)
    mandatory_action = len(separate_actions) * ACTION_MINIMUM_SECONDS
    return {"spoken_characters": sum(source.spoken_characters(bank[ref]) for ref in refs if bank[ref]["kind"] == "dialogue"),
        "normal_dialogue_seconds": round(speech, 6), "nonadjacent_action_source_refs": separate_actions,
        "minimum_nonadjacent_action_seconds": round(mandatory_action, 6),
        "adjacent_action_overlap_lower_bound_assumptions": visible_overlap_candidates,
        "source_lower_bound_seconds": round(speech + mandatory_action, 6),
        "minimum_nonadjacent_action_seconds_is_not_actual_duration": True,
        "action_overlap_semantics_verified": False}


def candidate_graph(script, manifest):
    shared.validate_shared_manifest(manifest, script)
    bank = source.catalog(script)
    ordered = list(bank)
    ranges = []
    for start in range(len(ordered)):
        for end in range(start + 1, len(ordered) + 1):
            refs = ordered[start:end]
            floor = _range_floor(bank, refs)
            budgets = []
            for tier, config in BUDGET_TIERS.items():
                required = floor["source_lower_bound_seconds"] + config["reaction_reserve_seconds"] + config["additional_action_headroom_seconds"]
                target = max(4, math.ceil(round(required, 6)))
                if target <= source.MAX_SEGMENT_SECONDS:
                    budgets.append({"budget_tier": tier, **deepcopy(config), "target_seconds": target,
                        "source_and_reserve_lower_bound_seconds": round(floor["source_lower_bound_seconds"] + config["reaction_reserve_seconds"], 6),
                        "unused_lower_bound_seconds": round(target - floor["source_lower_bound_seconds"] - config["reaction_reserve_seconds"], 6)})
            if budgets:
                ranges.append({"range_id": f"R{start + 1:04d}_{end:04d}", "start_source_ref": refs[0], "end_source_ref": refs[-1],
                    "source_refs": refs, "start_index": start, "end_index_exclusive": end, **floor, "budget_options": budgets})
    outgoing = {i: [] for i in range(len(ordered))}
    for row in ranges:
        outgoing[row["start_index"]].append(row)
    suffix = {len(ordered): 0}
    for i in range(len(ordered) - 1, -1, -1):
        costs = [budget["target_seconds"] + suffix[row["end_index_exclusive"]]
            for row in outgoing[i] if row["end_index_exclusive"] in suffix for budget in row["budget_options"]]
        if costs:
            suffix[i] = min(costs)
    if 0 not in suffix or suffix[0] > MAX_FILM_SECONDS:
        raise ValueError("no complete unchanged-source timing path fits normal speech and the film boundary")
    # Keep every graph edge that can reach the full source. No semantic or
    # aesthetic endpoint is selected or removed by this arithmetic pass.
    ranges = [row for row in ranges if row["end_index_exclusive"] in suffix]
    for row in ranges:
        row["minimum_remaining_target_seconds"] = suffix[row["end_index_exclusive"]]
    return {"schema": VERSION + "/candidate_graph", "script_sha256": digest(script), "global_manifest_sha256": digest(manifest),
        "source_refs": ordered, "ranges": ranges, "budget_tiers": deepcopy(BUDGET_TIERS),
        "minimum_complete_plan_seconds": suffix[0], "maximum_film_seconds": MAX_FILM_SECONDS,
        "normal_spoken_characters_per_second": source.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "range_selection_is_model_owned": True, "targets_and_reserves_are_program_derived": True,
        "action_timing_is_lower_bound_only": True, "semantic_action_feasibility_proven": False,
        "actual_media_quality_passed": False, "calls_authorized": False}


def compact_request_graph(script, manifest):
    """Deterministic decision-only projection; full arithmetic stays in audit.

    Indices address `source_refs` once; each budget is [tier,target,reserve].
    No edge, tier, cost, endpoint or cut choice is generated by this projection.
    """
    graph = candidate_graph(script, manifest)
    return {"schema": VERSION + "/compact_candidate_graph", "rich_graph_sha256": digest(graph),
        "source_refs": deepcopy(graph["source_refs"]),
        "range_columns": ["range_id", "start_index", "end_index_exclusive", "dialogue_seconds", "action_lower_bound_seconds", "budgets", "minimum_remaining_target_seconds"],
        "budget_columns": ["budget_tier", "target_seconds", "reaction_reserve_seconds"],
        "ranges": [[row["range_id"], row["start_index"], row["end_index_exclusive"], row["normal_dialogue_seconds"],
            row["minimum_nonadjacent_action_seconds"],
            [[budget["budget_tier"], budget["target_seconds"], budget["reaction_reserve_seconds"]] for budget in row["budget_options"]],
            row["minimum_remaining_target_seconds"]] for row in graph["ranges"]],
        "budget_tiers": deepcopy(BUDGET_TIERS), "minimum_complete_plan_seconds": graph["minimum_complete_plan_seconds"],
        "maximum_film_seconds": MAX_FILM_SECONDS, "normal_spoken_characters_per_second": source.NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
        "indices": "zero_based_start_inclusive_end_exclusive", "action_timing_lower_bound_is_not_feasibility_proof": True}


model_candidate_graph = compact_request_graph


def validate_compact_request_graph(compact, script, manifest):
    exact = compact_request_graph(script, manifest)
    if compact != exact:
        raise ValueError("compact candidate projection changed an edge, budget, source identity or arithmetic")
    return {"status": "compact_candidate_graph_valid", "rich_graph_sha256": compact["rich_graph_sha256"],
        "compact_graph_sha256": digest(compact), "every_edge_and_budget_preserved": True,
        "automatic_narrative_cut_selected": False, "calls_authorized": False}


def whole_direction_schema(script, manifest):
    graph = candidate_graph(script, manifest)
    old = prior.whole_direction_schema(script, manifest)
    creative = {key: deepcopy(value) for key, value in old["properties"]["segments"]["items"]["properties"].items()
        if key not in ("target_seconds", "reaction_reserve_seconds", "end_source_ref")}
    creative.update(range_id={"enum": [row["range_id"] for row in graph["ranges"]]},
        budget_tier={"enum": list(BUDGET_TIERS)})
    segment = source._obj(creative)
    segment["allOf"] = [{"if": {"properties": {"range_id": {"const": row["range_id"]}}},
        "then": {"properties": {"budget_tier": {"enum": [budget["budget_tier"] for budget in row["budget_options"]]}}}}
        for row in graph["ranges"]]
    fields = {key: deepcopy(value) for key, value in old["properties"].items() if key != "segments"}
    fields["segments"] = source._array(segment, 1, len(graph["source_refs"]))
    return source._obj(fields)


def compile_direction(raw, script, manifest):
    source._validate(whole_direction_schema(script, manifest), raw)
    graph = candidate_graph(script, manifest)
    edges = {row["range_id"]: row for row in graph["ranges"]}
    projected = {key: deepcopy(value) for key, value in raw.items() if key != "segments"}
    projected["segments"] = []
    choices = []
    cursor = 0
    total = 0
    for i, native in enumerate(raw["segments"], 1):
        edge = edges[native["range_id"]]
        if edge["start_index"] != cursor:
            raise ValueError(f"source path discontinuity in segment {i}: range {edge['range_id']} starts at {edge['start_source_ref']}, expected source index {cursor}")
        budget = next(row for row in edge["budget_options"] if row["budget_tier"] == native["budget_tier"])
        total += budget["target_seconds"]
        if total + edge["minimum_remaining_target_seconds"] > MAX_FILM_SECONDS:
            raise ValueError(f"whole budget has no possible completion after segment {i}: spent={total}, minimum_remaining={edge['minimum_remaining_target_seconds']}, maximum={MAX_FILM_SECONDS}")
        projected["segments"].append({**{key: deepcopy(value) for key, value in native.items() if key not in ("range_id", "budget_tier")},
            "end_source_ref": edge["end_source_ref"], "target_seconds": budget["target_seconds"],
            "reaction_reserve_seconds": budget["reaction_reserve_seconds"]})
        choices.append({"segment_id": f"M{i:03d}", "range_id": edge["range_id"], "budget_tier": native["budget_tier"],
            "source_refs": deepcopy(edge["source_refs"]), "numeric_lower_bound": deepcopy({k: edge[k] for k in (
                "normal_dialogue_seconds", "minimum_nonadjacent_action_seconds", "source_lower_bound_seconds")}), "budget": deepcopy(budget)})
        cursor = edge["end_index_exclusive"]
    if cursor != len(graph["source_refs"]):
        raise ValueError("source path stops before the full original script tail")
    legacy_projection = prior.compile_direction(projected, script, manifest)
    return {"schema": VERSION + "/direction", "script_sha256": digest(script), "global_manifest_sha256": digest(manifest),
        "native": deepcopy(raw), "native_sha256": digest(raw), "candidate_graph_sha256": digest(graph),
        "v1_direction_projection": legacy_projection, "segments": deepcopy(legacy_projection["segments"]),
        "timing_choices": choices, "total_target_seconds": total, "whole_source_coverage_complete": True,
        "program_arithmetic_derived": True, "model_narrative_cut_choice_preserved": True,
        "all_native_creative_values_preserved": True, "legacy_failed_response_adopted": False,
        "timing_is_estimate": True, "semantic_action_feasibility_proven": False,
        "machine_script_quality": False, "actual_media_quality_passed": False, "calls_authorized": False}


def compile_complete(direction, performances, script, manifest, initial_state):
    exact = compile_direction(direction["native"], script, manifest)
    if exact != direction:
        raise ValueError("v2 director native, fixed manifest, candidate graph or numeric projection changed")
    result = prior.compile_complete(direction["v1_direction_projection"], performances, script, manifest, initial_state)
    result.update(schema=VERSION + "/complete", direction=deepcopy(direction),
        candidate_graph_sha256=direction["candidate_graph_sha256"], program_arithmetic_derived=True,
        action_timing_lower_bound_replaced_by_local_estimates=True,
        source_state_semantic_review_complete=False, actual_media_quality_passed=False)
    return result


def rejected_direction_timing_report(raw, script):
    """Read-only diagnostics for old complete native responses; never adopt them."""
    bank = source.catalog(script)
    ordered = list(bank)
    cursor = 0
    rows = []
    for i, native in enumerate(raw["segments"], 1):
        end = ordered.index(native["end_source_ref"]) + 1
        refs = ordered[cursor:end]
        if end <= cursor:
            raise ValueError("cannot audit a reversed or repeated source range as a complete segment")
        speech = sum(source.spoken_seconds(bank[ref]) for ref in refs)
        required = speech + native["reaction_reserve_seconds"]
        rows.append({"segment_index": i, "source_refs": refs, "end_source_ref": native["end_source_ref"],
            "spoken_characters": sum(source.spoken_characters(bank[ref]) for ref in refs if bank[ref]["kind"] == "dialogue"),
            "normal_dialogue_seconds": round(speech, 6), "reaction_reserve_seconds": native["reaction_reserve_seconds"],
            "required_spoken_and_reaction_seconds": round(required, 6), "native_target_seconds": native["target_seconds"],
            "required_minus_native_target_seconds": round(required - native["target_seconds"], 6),
            "fits_native_target": required <= native["target_seconds"] + 1e-6,
            "fits_provider_fifteen_second_cap": required <= 15 + 1e-6,
            "actual_action_duration_checked": False, "action_numeric_lower_bound": _range_floor(bank, refs)})
        cursor = end
    return {"schema": VERSION + "/rejected_native_timing_audit", "script_sha256": digest(script),
        "native_sha256": digest(raw), "source_refs": ordered, "whole_source_coverage_complete": cursor == len(ordered),
        "segments": rows, "arithmetic_failed_segment_indexes": [row["segment_index"] for row in rows if not row["fits_native_target"]],
        "total_original_spoken_characters": sum(source.spoken_characters(row) for row in bank.values() if row["kind"] == "dialogue"),
        "total_normal_dialogue_seconds": round(sum(source.spoken_seconds(row) for row in bank.values()), 6),
        "native_response_preserved": True, "rejected_response_adopted": False,
        "media_quality_checked": False, "calls_authorized": False}
