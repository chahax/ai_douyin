"""Source-bound domain payloads; A2 envelopes are private deterministic checks.

No service payload is repaired or relabelled as an A2 model-native report.
Only machine metadata is added to the canonical checking envelope.
"""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator, ValidationError
from scripts import creative_isolated_event_entailment_v2 as prior

VERSION = "creative_isolated_event_entailment/v3"
EVENTS_VERSION, ENTAILMENT_VERSION, LEDGER_VERSION = (VERSION + s for s in ("/observable_events_payload", "/claim_comparison_payload", "/compiled_ledger"))
digest, FORM, _closure = prior.digest, prior.FORM, prior._closure


def _domain(events): return ("steps", "temporal_relations") if events else ("fields", "revision_target")


def _native_schema(checking_schema, events):
    schema = deepcopy(checking_schema)
    schema["properties"] = {key: schema["properties"][key] for key in _domain(events)}
    schema["required"] = list(_domain(events))
    return schema


def _canonical(native, checking_prepared, events):
    """Add only headers derived from a locally rebuilt checking request."""
    headers = {key: deepcopy(rule["const"]) for key, rule in checking_prepared["request"]["structured_schema"]["properties"].items() if "const" in rule}
    report = {**headers, **deepcopy(native)}
    if {key: report[key] for key in _domain(events)} != native: raise ValueError("canonical checking compilation changed native domain")
    return report


def _prepare(checking, payload, events):
    result = deepcopy(checking); descriptor = result["source_descriptor"]
    schema = _native_schema(prior._schema(payload, descriptor, events), events)
    context = digest(payload); request = result["request"]
    request["structured_schema"] = schema
    request["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    request["messages"][0]["content"] += "原生响应仅提交" + "/".join(_domain(events)) + "；版本、来源、上下文与摘要由本地信封绑定，不输出机器元信息。"
    request["input_provenance"].update(isolated_event_entailment_version=VERSION, context_sha256=context, native_domain_payload_only=True)
    result["manifest"].update(schema=VERSION + "/manifest", native_protocol_version=VERSION,
        context_sha256=context, canonical_checking_context_sha256=checking["context_sha256"],
        canonical_checking_request_sha256=checking["request_sha256"],
        local_envelope_is_model_native=False, native_domain_fields=list(_domain(events)),
        payload_identity=prior.base.workflow.base.workflow.contexts._measure(payload))
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result.update(context_sha256=context, wire=expected_wire_request(request), request_sha256=digest(request))
    return result


def prepare_events(inputs, profile, raw, views):
    checking = prior.prepare_events(inputs, profile, raw, views)
    payload = json.loads(checking["request"]["messages"][1]["content"])
    payload["schema"] = VERSION + "/events_context"
    return _prepare(checking, payload, True)


def _checking_events(prepared):
    v = prepared["views"]
    return prior.prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"])


def _envelope(native, prepared, checking, canonical, events):
    return {"schema": VERSION + "/local_source_envelope", "native_protocol_version": VERSION,
        "native_payload_sha256": digest(native), "actual_request_sha256": prepared["request_sha256"],
        "actual_context_sha256": prepared["context_sha256"], "source_descriptor": deepcopy(prepared["source_descriptor"]),
        "canonical_checking_protocol": prior.VERSION, "canonical_checking_report_sha256": digest(canonical),
        "canonical_checking_context_sha256": checking["context_sha256"], "canonical_checking_request_sha256": checking["request_sha256"],
        "canonical_checking_headers": {key: deepcopy(value) for key, value in canonical.items() if key not in _domain(events)},
        "domain_fields": list(_domain(events)), "domain_values_preserved_exact": True,
        "canonical_checking_report_is_model_native": False, "native_payload_rewritten": False}


def _invalid(exc, phase):
    result = prior._invalid(exc, phase); result["isolated_event_entailment_version"] = VERSION
    return result


def _lift(result, native, prepared, checking, canonical, events, actual_ledger=None):
    lifted = deepcopy(result)
    lifted.update(isolated_event_entailment_version=VERSION, native_report_sha256=digest(native),
        context_sha256=prepared["context_sha256"], local_source_envelope=_envelope(native, prepared, checking, canonical, events))
    if "compiled_ledger" in lifted:
        original = deepcopy(lifted["compiled_ledger"]); ledger = lifted["compiled_ledger"]
        ledger.update(schema_version=LEDGER_VERSION, native_events_sha256=digest(native))
        for key in ("events", "source_steps", "temporal_relations", "step_coverage"):
            if ledger[key] != original[key]: raise ValueError("source-bound lift changed extracted domain")
        lifted.update(canonical_checking_compiled_ledger_sha256=digest(original), compiled_ledger_sha256=digest(ledger))
    elif actual_ledger is not None:
        lifted["canonical_checking_compiled_ledger_sha256"] = lifted.get("compiled_ledger_sha256")
        lifted["compiled_ledger_sha256"] = digest(actual_ledger)
    return lifted


def validate_events(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"]): raise ValueError("source-bound event request/authority differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        checking = _checking_events(prepared); canonical = _canonical(native, checking, True)
        return _lift(prior.validate_events(canonical, checking), native, prepared, checking, canonical, True)
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc, "actual_events")


def _checking_comparison(inputs, profile, raw, views, events_native):
    ep = prior.prepare_events(inputs, profile, raw, views)
    return prior.prepare_entailment(inputs, profile, raw, views, _canonical(events_native, ep, True), ep)


def prepare_entailment(inputs, profile, raw, views, events_native, events_prepared):
    if events_prepared != prepare_events(inputs, profile, raw, views): raise ValueError("source-bound comparison extractor request differs")
    decision = validate_events(events_native, events_prepared)
    if not decision["valid"] or not decision["ledger_usable"]: raise ValueError("usable source-bound native ledger required")
    checking = _checking_comparison(inputs, profile, raw, views, events_native)
    payload = json.loads(checking["request"]["messages"][1]["content"])
    payload.update(schema=VERSION + "/comparison_context", compiled_event_ledger=deepcopy(decision["compiled_ledger"]))
    result = _prepare(checking, payload, False)
    result["views"].update(events_native=deepcopy(events_native), events_prepared=deepcopy(events_prepared))
    return result


def validate_entailment(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], v["events_native"], v["events_prepared"]): raise ValueError("source-bound comparison request/authority differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        checking = _checking_comparison(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], v["events_native"])
        canonical = _canonical(native, checking, False)
        ledger = json.loads(prepared["request"]["messages"][1]["content"])["compiled_event_ledger"]
        return _lift(prior.validate_entailment(canonical, checking), native, prepared, checking, canonical, False, ledger)
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc, "event_entailment")


def build_review_packet(events_native, events_prepared, comparison_native, comparison_prepared):
    ed, decision = validate_events(events_native, events_prepared), validate_entailment(comparison_native, comparison_prepared)
    if not ed["ledger_usable"] or not decision["valid"]: raise ValueError("source-bound packet requires valid same-source reports")
    if comparison_prepared["views"]["events_native"] != events_native or comparison_prepared["views"]["events_prepared"] != events_prepared: raise ValueError("source-bound packet extractor identity differs")
    used = {row["field_ref"] for row in decision["findings"]}
    return {"schema": VERSION + "/review_packet", "native_observable_events_report": deepcopy(events_native), "native_claim_comparison_report": deepcopy(comparison_native),
        "verified_compiled_event_ledger": deepcopy(ed["compiled_ledger"]),
        "used_source_fields": {ref: {k: value for k, value in row.items() if k != "text"} for ref, row in comparison_prepared["views"]["source_fields"].items() if ref in used},
        "functional_decision": {k: deepcopy(decision[k]) for k in ("status", "revision_target", "native_revision_target", "computed_slot_findings", "uncertainties", "native_report_sha256", "compiled_ledger_sha256")},
        "local_source_envelopes": {"events": ed["local_source_envelope"], "comparison": decision["local_source_envelope"]},
        "source_descriptor": deepcopy(comparison_prepared["source_descriptor"]), "native_reports_rewritten": False}


def build_repair_feedback(events_native, events_prepared, comparison_native, comparison_prepared):
    decision = validate_entailment(comparison_native, comparison_prepared)
    if not decision["valid"] or decision["accepted"] or decision["uncertainties"] or decision["requires_new_goal_plan"]: raise ValueError("source-bound repair requires definite valid script failure")
    result = build_review_packet(events_native, events_prepared, comparison_native, comparison_prepared)
    result["schema"] = VERSION + "/repair_feedback"
    return result
