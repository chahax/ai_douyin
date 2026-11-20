"""Typed native endpoints; direct v2 validation, never repaired v1 reports."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator, ValidationError
from scripts import creative_isolated_event_entailment_v1 as base

VERSION = "creative_isolated_event_entailment/v2"
EVENTS_VERSION, ENTAILMENT_VERSION, LEDGER_VERSION = (VERSION + s for s in ("/observable_events", "/claim_comparison", "/compiled_ledger"))
digest = base.digest
FORM = "required_content_form"
EVENT_RULE = base.EVENT_RULE.replace(
    "事件ID由本地按Eref#events数组索引派生，不另填ID。temporal_relations只列原文/故事时间有据的已发生先后，before_event/after_event使用上述派生ID，",
    "temporal_relations只列原文/故事时间有据的已发生先后；before_event/after_event是{step_ref,event_index}对象。step_ref选actual_steps已给E，event_index为该原生steps[step_ref].events中从0开始的整数索引；不合成#ID，")
EVENT_RULE = EVENT_RULE.replace("content_medium", FORM).replace(
    "指要求/承诺内容的书面或口头形式，不是开口说话的声道；", "仅指命题明确要求/承诺/告知的内容形式；speech本身的发声不等于内容要求oral，未指定形式填unspecified，非speech填null；")
COMPARE_RULE = base.COMPARE_RULE.replace("content_medium", FORM).replace("未规定medium/deadline用null", "未规定内容形式填unspecified，未规定deadline用null")
COMPARE_RULE += "required_content_form仅在命题明确要求/承诺/告知内容形式时填written/oral；普通问话或inform未指定形式=unspecified，不按发声渠道填写。"


def _rename_schema(value):
    if isinstance(value, dict): return {(FORM if k == "content_medium" else k): _rename_schema(v) for k, v in value.items()}
    if isinstance(value, list): return [_rename_schema(v) for v in value]
    return FORM if value == "content_medium" else value


def _form_schema(schema):
    result = _rename_schema(schema)
    # Direct native union, not a converted review. Unknown remains expressible.
    for row in (result.get("$defs", {}).get("event"), result.get("$defs", {}).get("slots")):
        if row is not None:
            row["allOf"].append({"if": {"properties": {"kind": {"const": "speech"}}}, "then": {"properties": {
                FORM: {"enum": ["written", "oral", "unspecified", "unknown"]}}}, "else": {"properties": {FORM: {"type": "null"}}}})
    return result


def _schema(payload, descriptor, events):
    result = _form_schema(base._event_schema(payload, descriptor) if events else base._comparison_schema(payload, descriptor))
    result["properties"]["schema"] = {"const": EVENTS_VERSION if events else ENTAILMENT_VERSION}
    if events:
        endpoint = base._obj({"step_ref": {"enum": list(payload["actual_steps"])}, "event_index": {"type": "integer", "minimum": 0}})
        relation = result["properties"]["temporal_relations"]["items"]["properties"]
        relation["before_event"] = deepcopy(endpoint); relation["after_event"] = deepcopy(endpoint)
    return result


def _request(inputs, profile, raw, views, payload, events, descriptor):
    result = base._request(inputs, profile, raw, views, payload, _schema(payload, descriptor, events),
        EVENT_RULE if events else COMPARE_RULE, "actual_events" if events else "event_entailment", descriptor)
    result["manifest"]["schema"] = VERSION + "/manifest"
    result["manifest"].update(native_protocol_version=VERSION, native_temporal_endpoints="typed step_ref/event_index; compiled #IDs are not model output")
    result["request"]["input_provenance"]["isolated_event_entailment_version"] = VERSION
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result.update(wire=expected_wire_request(result["request"]), request_sha256=digest(result["request"]))
    return result


def prepare_events(inputs, profile, raw, views):
    compiled = base._source(inputs, raw, views); script = compiled["derived_script"]
    payload = {"schema": VERSION + "/events_context", "actors": base._actors(views["goal"]),
        "scene_locators": [{"id": c["id"], "scene_id": c["scene_id"], "story_time": c["story_time"]} for c in script["scene_contexts"]],
        "actual_steps": base._steps(script)}
    result = _request(inputs, profile, raw, views, payload, True, compiled["source_descriptor"])
    result["manifest"]["withheld_context"] += ["goal", "setup", "premise", "beat_event_trigger", "ensemble"]
    result["views"]["actual_steps"] = deepcopy(payload["actual_steps"])
    return result


def _invalid(exc, phase):
    result = base._invalid(exc, phase); result["isolated_event_entailment_version"] = VERSION
    return result


def _unknown(event):
    return any(event[k] == "unknown" for k in ("speech_force", FORM, "occurrence", "content_phase"))


def _endpoint(endpoint, steps):
    ref, index = endpoint["step_ref"], endpoint["event_index"]
    if type(index) is not int or index < 0 or ref not in steps or index >= len(steps[ref]["events"]):
        raise ValueError("typed temporal endpoint must select an existing native event by exact nonnegative integer index")
    return f"{ref}#{index}"


def validate_events(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"]): raise ValueError("v2 extractor source/request identity differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        events, uncertainties, steps = {}, [], v["actual_steps"]
        for ref, row in native["steps"].items():
            step = steps[ref]; spoken = []
            if row["disposition"] == "unknown": uncertainties.append({"step_ref": ref, "reason": row["reason"]})
            for index, event in enumerate(row["events"]):
                base._check_slots(event)
                if not event["source_quote"].strip() or event["source_quote"] not in step["text"]: raise ValueError("v2 event quote differs from its exact own E.text")
                if event["kind"] == "speech": spoken.append(event)
                event_id = f"{ref}#{index}"
                events[event_id] = {"step_ref": ref, "beat_id": step["beat_id"], "step_index": step["step_index"], **deepcopy(event)}
                if _unknown(event): uncertainties.append({"event_ref": event_id, "reason": "native extraction unknown slot"})
            if step["kind"] == "dialogue":
                if row["disposition"] != "unknown" and not any(e["actor_id"] == step["speaker"] and e["occurrence"] == "occurred" for e in spoken): raise ValueError("dialogue requires its actual speaker's occurred speech")
                if any(e["actor_id"] != step["speaker"] for e in spoken): raise ValueError("dialogue speaker substitution")
        relations = []
        for row in native["temporal_relations"]:
            for proof in row["evidence"]:
                if not proof["quote"].strip() or proof["quote"] not in steps[proof["step_ref"]]["text"]: raise ValueError("temporal quote differs from its actual E.text")
            relations.append({**deepcopy(row), "before_event": _endpoint(row["before_event"], native["steps"]),
                "after_event": _endpoint(row["after_event"], native["steps"])})
        base._closure(events, relations)
        ledger = {"schema_version": LEDGER_VERSION, "native_events_sha256": digest(native), "native_script_sha256": prepared["source_descriptor"]["native_script_sha256"],
            "events": events, "source_steps": deepcopy(steps), "temporal_relations": relations,
            "native_temporal_relations_sha256": digest(native["temporal_relations"]),
            "step_coverage": {ref: row["disposition"] for ref, row in native["steps"].items()},
            "temporal_ids_are_deterministic_compilation_not_native_fields": True,
            "extraction_is_fallible_model_interpretation": True, "document_order_is_completed_time": False}
        return {"valid": True, "accepted": not uncertainties, "ledger_usable": not uncertainties,
            "status": "halt_observable_events_unknown" if uncertainties else "observable_ledger_usable_not_content_approval",
            "findings": [], "uncertainties": uncertainties, "compiled_ledger": ledger, "compiled_ledger_sha256": digest(ledger),
            "native_report_sha256": digest(native), "source_descriptor": deepcopy(prepared["source_descriptor"]),
            "context_sha256": prepared["context_sha256"], "isolated_event_entailment_version": VERSION, "semantic_meaning_programmatically_verified": False}
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc, "actual_events")


def prepare_entailment(inputs, profile, raw, views, events_native, events_prepared):
    if events_prepared != prepare_events(inputs, profile, raw, views): raise ValueError("v2 comparison extractor source differs")
    decision = validate_events(events_native, events_prepared)
    if not decision["valid"] or not decision["ledger_usable"]: raise ValueError("v2 comparison requires a usable native v2 ledger")
    compiled = base._source(inputs, raw, views); fields = base._fields(views["goal"], compiled["derived_script"])
    payload = {"schema": VERSION + "/comparison_context", "actors": base._actors(views["goal"]), "source_fields": fields,
        "compiled_event_ledger": decision["compiled_ledger"]}
    result = _request(inputs, profile, raw, views, payload, False, compiled["source_descriptor"])
    result["views"].update(source_fields=deepcopy(fields), events_native=deepcopy(events_native), events_prepared=deepcopy(events_prepared))
    return result


def validate_entailment(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], v["events_native"], v["events_prepared"]): raise ValueError("v2 comparison source/request identity differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        ledger = json.loads(prepared["request"]["messages"][1]["content"])["compiled_event_ledger"]
        events = ledger["events"]; reach = base._closure(events, ledger["temporal_relations"])
        findings, computed, uncertainties = [], [], []
        for ref, row in native["fields"].items():
            if "".join(s["source_text"] for s in row["source_segments"]) != v["source_fields"][ref]["text"]: raise ValueError("v2 source segments omit or alter F.text: " + ref)
            for index, segment in enumerate(row["source_segments"]):
                loc = {"field_ref": ref, "segment_index": index}
                if segment["role"] == "unknown" or segment["verdict"] == "unknown" or segment["temporal_requirement"] == "unknown": uncertainties.append({**loc, "reason": segment["reason"]})
                if segment["verdict"] == "not_entailed": findings.append({**loc, "finding": deepcopy(segment), "target": native["revision_target"]})
                expected = segment["expected"]
                if expected is None: continue
                base._check_slots(expected)
                if _unknown(expected): uncertainties.append({**loc, "reason": "native expected atom unknown slot"})
                if segment["verdict"] != "entailed": continue
                required = ["kind", "occurrence"] + [k for k in ("actor_id", "speech_force") if expected[k] is not None]
                if expected[FORM] not in (None, "unspecified"): required.append(FORM)
                if not any(all(events[r][k] == expected[k] for k in required) and (expected["deadline"] is None or events[r]["deadline"] is not None) for r in segment["event_refs"]):
                    computed.append({**loc, "code": "TYPED_EVENT_SLOTS_NOT_SUPPORTED", "expected_slots": {k: expected[k] for k in required},
                        "deadline_presence_required": expected["deadline"] is not None, "actual_event_refs": deepcopy(segment["event_refs"]), "native_verdict": segment["verdict"], "target": "script"})
                if segment["temporal_requirement"] == "before" and not all(b in reach[a] for a in segment["prior_event_refs"] for b in segment["event_refs"]): uncertainties.append({**loc, "reason": "no evidenced completed-before path; no document-order inference"})
        if bool(findings) != (native["revision_target"] != "none"): raise ValueError("native target must match definite failed atoms")
        target = native["revision_target"] if native["revision_target"] != "none" else "script" if computed else "none"
        return {"valid": True, "accepted": not findings and not computed and not uncertainties,
            "status": "halt_event_entailment_unknown" if uncertainties else "needs_new_goal_plan" if target == "plan" else "needs_whole_revision" if findings or computed else "event_entailment_passed",
            "findings": findings + computed, "computed_slot_findings": computed, "uncertainties": uncertainties, "revision_target": target,
            "native_revision_target": native["revision_target"], "requires_new_goal_plan": target == "plan", "native_report_sha256": digest(native),
            "compiled_ledger_sha256": digest(ledger), "source_descriptor": deepcopy(prepared["source_descriptor"]), "context_sha256": prepared["context_sha256"],
            "isolated_event_entailment_version": VERSION, "native_verdict_values_rewritten": False, "semantic_meaning_programmatically_verified": False, "human_quality_approved": False}
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc, "event_entailment")


def build_review_packet(events_native, events_prepared, comparison_native, comparison_prepared):
    ed, decision = validate_events(events_native, events_prepared), validate_entailment(comparison_native, comparison_prepared)
    if not ed["ledger_usable"] or not decision["valid"]: raise ValueError("v2 packet requires contract-valid same-source reports")
    if comparison_prepared["views"]["events_native"] != events_native or comparison_prepared["views"]["events_prepared"] != events_prepared: raise ValueError("v2 packet extraction identity differs")
    used = {r["field_ref"] for r in decision["findings"]}
    return {"schema": VERSION + "/review_packet", "native_observable_events_report": deepcopy(events_native), "native_claim_comparison_report": deepcopy(comparison_native),
        "verified_compiled_event_ledger": deepcopy(ed["compiled_ledger"]), "used_source_fields": {ref: {k: value for k, value in row.items() if k != "text"} for ref, row in comparison_prepared["views"]["source_fields"].items() if ref in used},
        "functional_decision": {k: deepcopy(decision[k]) for k in ("status", "revision_target", "native_revision_target", "computed_slot_findings", "uncertainties", "native_report_sha256", "compiled_ledger_sha256")},
        "source_descriptor": deepcopy(comparison_prepared["source_descriptor"]), "native_reports_rewritten": False}


def build_repair_feedback(events_native, events_prepared, comparison_native, comparison_prepared):
    decision = validate_entailment(comparison_native, comparison_prepared)
    if not decision["valid"] or decision["accepted"] or decision["uncertainties"] or decision["requires_new_goal_plan"]: raise ValueError("v2 repair requires definite valid script failure")
    result = build_review_packet(events_native, events_prepared, comparison_native, comparison_prepared); result["schema"] = VERSION + "/repair_feedback"
    return result


_closure = base._closure
