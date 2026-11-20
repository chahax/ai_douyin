"""Verify original model lineage before the frozen whole-flow media adapter.

This adds proof and source hashes to the media plan only. It does not edit any
creative value, transport response, video prompt, request or old frozen source.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_creative_shared_full_production_v1 as production

VERSION = "shared_verified_media/v2"
OPERATIONS = ("media_prepare", "media_submit", "media_query")


def _ordinal(value):
    if type(value) is not int or value < 1:
        raise ValueError("original positive ordinal required")
    return value


def _known_receipt(runtime, ledger, ordinal, role):
    rows = [row for row in ledger["calls"] if row["ordinal"] == _ordinal(ordinal)]
    if len(rows) != 1:
        raise ValueError("original stage ordinal missing or duplicated")
    receipt = runtime.effective_receipt(rows[0])
    meta = receipt.get("response_metadata", {})
    if (receipt.get("ordinal") != ordinal or receipt.get("status") != "contract_valid"
        or receipt.get("request", {}).get("role") != role
        or meta.get("response_body_complete") is not True
        or meta.get("finish_reason") not in ("tool_calls", "stop")
        or type(meta.get("total_tokens")) is not int or meta["total_tokens"] < 0):
        raise ValueError("original stage must be valid, complete and have known usage")
    if receipt["request_sha256"] != production.control.digest(receipt["request"]):
        raise ValueError("original request binding changed")
    value = production.document(receipt)
    if role != "writer" and production.control.strict_json(receipt["response_text"]) != value:
        raise ValueError("review value differs from the original response text")
    return receipt, value


def _review_input(receipt):
    users = [m["content"] for m in receipt["request"]["messages"] if m.get("role") == "user"]
    if len(users) != 1:
        raise ValueError("review must bind one exact native user input")
    return production.control.strict_json(users[0])


def _writer_input(receipt, schema):
    request = receipt["request"]
    users = [m["content"] for m in request["messages"] if m.get("role") == "user"]
    expected_transport = {"transport": production.transport.VERSION,
        "tool_name": production.transport.TOOL_NAME, "inner_document_schema": schema}
    if (len(users) != 2 or request.get("output_transport") != production.transport.VERSION
        or request.get("inner_document_schema") != schema
        or production.control.strict_json(users[1]) != expected_transport):
        raise ValueError("original writer input or transport schema differs from the selected stage")
    return production.control.strict_json(users[0])


def _selected_stage(runtime, ledger, label, expected_input, schema):
    """Exactly one selected native, following only bounded known content failures."""
    rows = []
    for row in ledger["calls"]:
        name = row.get("label", "")
        match = re.fullmatch(re.escape(label) + r"_r(\d+)", name)
        if match:
            rows.append((int(match[1]), row))
        elif name.startswith(label + "_r"):
            raise ValueError("invalid original content revision label")
    rows.sort(key=lambda item: item[0])
    if (not rows or [index for index, _ in rows] != list(range(len(rows)))
        or len(rows) > production.MAX_CONTENT_REVISIONS + 1):
        raise ValueError("selected original stage missing or content revision range invalid")
    failures, selected, previous_ordinal = [], None, 0
    for index, row in rows:
        receipt = runtime.effective_receipt(row)
        if (receipt.get("label") != row["label"] or receipt.get("ordinal") != _ordinal(row["ordinal"])
            or receipt["ordinal"] <= previous_ordinal
            or receipt.get("request_sha256") != production.control.digest(receipt.get("request"))
            or receipt.get("request", {}).get("role") != "writer"):
            raise ValueError("original stage label, ordinal or request binding changed")
        previous_ordinal = receipt["ordinal"]
        expected = deepcopy(expected_input)
        if failures:
            expected["previous_complete_rejected_versions"] = deepcopy(failures)
        if _writer_input(receipt, schema) != expected:
            raise ValueError("original stage did not receive the exact source, direction and state prefix")
        if receipt.get("status") == "contract_valid":
            if selected is not None or index != rows[-1][0]:
                raise ValueError("multiple adopted native stages or revisions after a valid stage")
            selected = _known_receipt(runtime, ledger, row["ordinal"], "writer")
        else:
            native = production.known_complete_rejected_native(receipt)
            if native is None:
                raise ValueError("unresolved transport or incomplete failure cannot precede an adopted stage")
            failures.append({"ordinal": receipt["ordinal"], "complete_rejected_native": native,
                "validation_error": receipt.get("validation_error"), "adopted": False,
                "reported_tokens": receipt["response_metadata"]["total_tokens"]})
    if selected is None:
        raise ValueError("no uniquely adopted valid original stage")
    return selected


def _passed_review(value, checks, script):
    schema = production.review_schema(checks, list(production.source.catalog(script)))
    result = production.validate_review(value, schema)
    if result["needs_revision"] or result["has_explicit_fail"] or result["has_unknown"]:
        raise ValueError("failed or unknown original review cannot authorize media")


def verify_bindings():
    """Read original receipts, then compare all derived production inputs exactly."""
    rt = production.runtime()
    ledger = production.control.read(rt.ledger)
    rt.check(ledger)
    for row in ledger["calls"]:
        receipt = rt.effective_receipt(row)
        m = receipt.get("response_metadata", {})
        if (receipt.get("status") not in ("contract_valid", "contract_rejected", "interface_rejected")
            or m.get("response_body_complete") is not True
            or m.get("finish_reason") not in ("tool_calls", "stop")
            or type(m.get("total_tokens")) is not int or m["total_tokens"] < 0):
            raise ValueError("unknown or incomplete current-run outcome blocks media")
    root = production.ROOT
    adopted = production.control.read(root / "ADOPTED_SOURCE.json")
    handoff = production.control.read(root / "VIDEO_HANDOFF.json")
    script, manifest = adopted["script"], production.control.read(root / "SHARED_MANIFEST.json")
    complete = production.control.read(root / "COMPLETE_PRODUCTION_COMPILED.json")
    direction = production.control.read(root / "WHOLE_DIRECTION.json")
    finals = production.control.read(root / "FINAL_PROMPTS.json")
    projection = production.control.read(root / "BOOTSTRAP_CONTEXT.json")
    x = production.control.read(root / "INPUT.json")
    scope = production.control.read(root / "USER_SCOPE.json")
    if (adopted.get("script_sha256") != production.control.digest(script)
        or adopted.get("machine_text_review_passed") is not True
        or adopted.get("actual_media_quality_passed") is not False
        or handoff.get("script_sha256") != production.control.digest(script)
        or handoff.get("global_manifest_sha256") != production.control.digest(manifest)
        or handoff.get("complete_compilation_sha256") != production.control.digest(complete)
        or handoff.get("text_full_review_passed") is not True):
        raise ValueError("derived source or handoff identity changed")
    if (handoff["source_writer_ordinal"] != adopted["writer_ordinal"]
        or handoff["source_review_ordinal"] != adopted["review_ordinal"]):
        raise ValueError("handoff source lineage differs from the adopted source")
    writer, native = _known_receipt(rt, ledger, adopted["writer_ordinal"], "writer")
    if native != script:
        raise ValueError("adopted script differs from original model native output")
    source_review, reviewed = _known_receipt(rt, ledger, adopted["review_ordinal"], "director")
    source_input = _review_input(source_review)
    if (source_input.get("full_script") != script
        or source_input.get("script_sha256") != production.control.digest(script)
        or source_input.get("brief") != x["brief"]
        or source_input.get("source_catalog") != production.source.catalog(script)
        or source_input.get("reference_fulltext") != x["reference_fulltext"]
        or source_input.get("casting") != x["casting"]):
        raise ValueError("source review did not receive this exact source and frozen context")
    _passed_review(reviewed, production.SCRIPT_CHECKS, script)
    context = {key: deepcopy(x["brief"][key]) for key in ("characters", "scenes", "initial_state")}
    initial = production.pipeline.build_initial_state(context, manifest)
    if (complete["initial_state"] != initial
        or production.control.read(root / "PLANNED_INITIAL_STATE.json") != initial):
        raise ValueError("production initial state differs from the frozen source")
    direction_input = {"full_current_script": script, "source_catalog": production.source.catalog(script),
        "shared_manifest": manifest, "planned_initial_state": initial,
        "reference_fulltext": x["reference_fulltext"], "production_preferences": x["production_preferences"]}
    direction_receipt, direction_native = _selected_stage(rt, ledger, "whole_direction", direction_input,
        production.pipeline.whole_direction_schema(script, manifest))
    exact_direction = production.pipeline.compile_direction(direction_native, script, manifest)
    if direction != exact_direction or complete["direction"] != exact_direction:
        raise ValueError("adopted direction differs from original model native output")
    if not writer["ordinal"] < source_review["ordinal"] < direction_receipt["ordinal"]:
        raise ValueError("source and direction original stage order changed")
    original_stages = [writer, source_review, direction_receipt]
    performances, state, completed = [], initial, []
    for segment, adopted_performance in zip(direction["segments"], complete["performances"]):
        refs = segment["source_refs"]
        perf_input = {"current_direction": segment,
            "current_sources": {ref: production.source.catalog(script)[ref] for ref in refs},
            "completed_stimulus_catalog": {ref: production.source.catalog(script)[ref] for ref in completed},
            "shared_manifest": manifest, "planned_initial_state": state, "completed_source_refs": completed,
            "reference_fulltext": x["reference_fulltext"], "production_preferences": x["production_preferences"],
            "actual_future_tail_not_created": True, "planned_state_is_not_pixel_approval": True}
        receipt, native_performance = _selected_stage(rt, ledger, "performance_" + segment["segment_id"].lower(),
            perf_input, production.pipeline.performance_schema(script, manifest, segment, state, completed))
        compiled = production.pipeline.compile_performance(native_performance, script, manifest, segment, state, completed)
        if (compiled != adopted_performance
            or production.control.read(root / "performances" / (segment["segment_id"] + ".json")) != compiled):
            raise ValueError("adopted performance differs from original model native output")
        if receipt["ordinal"] <= original_stages[-1]["ordinal"]:
            raise ValueError("performance original stage order changed")
        original_stages.append(receipt)
        performances.append(compiled)
        state = compiled["planned_ending_state"]
        completed = completed + refs
    rebuilt = production.pipeline.compile_complete(exact_direction, performances, script, manifest, initial)
    if rebuilt != complete:
        raise ValueError("complete source or planned state chain changed")
    planned = [production.pipeline.render_prompt(p, script, manifest) for p in complete["performances"]]
    dynamic = production.bootstrap_dynamic_state(manifest, x)
    actual_projection = production.shared.compile_segment_context(manifest, script, dynamic,
        complete["performances"][0]["source_refs"], bootstrap=True)
    actual_prompt = production.pipeline.render_prompt(complete["performances"][0], script, manifest, actual_projection)
    if (projection != actual_projection or finals["all_planned_prompts"] != planned
        or finals["opening_actual_prompt"] != actual_prompt):
        raise ValueError("actual shared projection or video prompts changed")
    whole_review, whole_value = _known_receipt(rt, ledger, handoff["production_review_ordinal"], "director")
    if whole_review["ordinal"] <= original_stages[-1]["ordinal"]:
        raise ValueError("whole production review did not follow all original production stages")
    original_stages.append(whole_review)
    whole_input = _review_input(whole_review)
    expected = {"brief": x["brief"], "full_current_script": script, "source_catalog": production.source.catalog(script),
        "shared_manifest": manifest, "whole_direction": direction, "complete_compilation": complete,
        "all_local_performances": complete["performances"], "all_planned_video_prompts": planned,
        "opening_actual_video_prompt": actual_prompt, "opening_shared_projection": actual_projection,
        "reference_fulltext": x["reference_fulltext"], "scope": scope}
    if any(whole_input.get(key) != value for key, value in expected.items()):
        raise ValueError("whole production review did not receive the exact current production inputs")
    _passed_review(whole_value, production.PRODUCTION_CHECKS, script)
    if handoff.get("review_limitations") != whole_value["review_limitations"]:
        raise ValueError("original review limitations changed")
    return {"schema": VERSION, "script_sha256": production.control.digest(script),
        "global_manifest_sha256": production.control.digest(manifest), "complete_compilation_sha256": production.control.digest(complete),
        "actual_prompt_sha256": production.control.digest(actual_prompt), "ledger_sha256": production.control.sha_file(rt.ledger),
        "original_receipt_bindings": [{"ordinal": r["ordinal"], "request_sha256": r["request_sha256"],
            "original_effective_receipt_sha256": production.control.digest(r)} for r in original_stages],
        "source_native_unchanged": True, "all_actual_review_inputs_equal": True,
        "all_adopted_direction_and_performance_natives_equal": True,
        "media_quality_verified": False, "human_approved": False, "video_request_modified": False}


def media(operation):
    if operation not in OPERATIONS:
        raise ValueError("explicit verified media operation required")
    proof = verify_bindings()
    artifact = production.ROOT / "VERIFIED_MEDIA_BINDING_V2.json"
    production.control.write(artifact, proof, True)
    original_make_plan = production.make_plan
    def verified_make_plan():
        current = verify_bindings()
        if current != proof:
            raise ValueError("original production binding changed before media dispatch")
        plan = deepcopy(original_make_plan())
        for path in (Path(__file__).resolve(), artifact):
            plan["sources"][str(path)] = {"path": str(path), "sha256": production.control.sha_file(path)}
        plan["verified_media_binding"] = deepcopy(proof)
        return plan
    production.make_plan = verified_make_plan
    try:
        return production.media(operation)
    finally:
        production.make_plan = original_make_plan


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=OPERATIONS)
    print(json.dumps(media(parser.parse_args().operation), ensure_ascii=False), flush=True)
