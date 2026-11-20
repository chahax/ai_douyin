"""Explicit writer projection; protocol is a code-supplied pure module only."""
from copy import deepcopy


def prepare(owner, prepare_base, protocol, version, inputs, profile, goal, audit, **kwargs):
    diagnostics = inputs.get("revision_diagnostics")
    packet = diagnostics.get("native_enacted_review") if type(diagnostics) is dict else None
    if type(packet) is not dict or packet.get("schema") != protocol.VERSION + "/repair_feedback":
        return prepare_base(inputs, profile, goal, audit, **kwargs)
    clean = {k: deepcopy(v) for k, v in inputs.items() if k not in ("previous_complete_document", "revision_diagnostics")}
    views = owner.base.compile_native_views(goal, kwargs["opening_setup"], **owner.origin_ids(clean))
    ep = protocol.prepare_events(clean, profile, inputs["previous_complete_document"], views)
    events = packet["native_observable_events_report"]
    cp = protocol.prepare_entailment(clean, profile, inputs["previous_complete_document"], views, events, ep)
    comparison = packet["native_claim_comparison_report"]
    expected = protocol.build_repair_feedback(events, ep, comparison, cp)
    if {k: v for k, v in packet.items() if k not in ("coordinator_packet_schema", "packet_is_model_native")} != expected:
        raise ValueError("writer packet differs from exact same-source native reports and verified ledger")
    decision = protocol.validate_entailment(comparison, cp)
    if diagnostics.get("complete_same_source_enacted_review") != decision:
        raise ValueError("writer decision differs from source-bound native comparison")
    ledger = packet["verified_compiled_event_ledger"]
    used = {r for field in comparison["fields"].values() for s in field["source_segments"] for r in s["event_refs"] + s["prior_event_refs"]}
    reach = protocol._closure(ledger["events"], ledger["temporal_relations"])
    for field in comparison["fields"].values():
        for s in field["source_segments"]:
            if s["temporal_requirement"] == "before":
                for a in s["prior_event_refs"]:
                    for b in s["event_refs"]:
                        used.update(r for r in ledger["events"] if r in reach[a] and b in reach[r])
    relations = [deepcopy(r) for r in ledger["temporal_relations"] if r["before_event"] in used and r["after_event"] in used]
    step_refs = {ledger["events"][r]["step_ref"] for r in used}
    for row in relations: step_refs.update(p["step_ref"] for p in row["evidence"])
    subset = {"schema": protocol.VERSION + "/writer_event_reference_closure",
        "events": {r: deepcopy(v) for r, v in ledger["events"].items() if r in used},
        "source_steps": {r: deepcopy(v) for r, v in ledger["source_steps"].items() if r in step_refs},
        "temporal_relations": relations, "omitted_events_are_not_missing_extraction": True,
        "is_fallible_interpretation_not_authority": True}
    functional = packet["functional_decision"]
    projected = {"schema": version + "/writer_feedback_projection", "native_claim_comparison_report": deepcopy(comparison),
        "verified_event_reference_closure": subset, "used_source_fields": deepcopy(packet["used_source_fields"]),
        "functional_decision": {k: deepcopy(v) for k, v in functional.items() if k != "computed_slot_findings"},
        "computed_slot_finding_paths": [{k: deepcopy(row[k]) for k in ("field_ref", "segment_index", "code", "target")} for row in functional["computed_slot_findings"]],
        "source_descriptor": deepcopy(packet["source_descriptor"]), "original_review_packet_sha256": protocol.digest(packet),
        "native_observable_events_report_sha256": protocol.digest(events), "complete_compiled_event_ledger_sha256": protocol.digest(ledger),
        "omitted_manifest": {"native_observable_events_report": "complete raw payload preserved in local packet/receipt; referenced event closure supplied",
            "verified_compiled_event_ledger": "complete ledger preserved locally; all outbound comparison references included",
            "complete_derived_decision": "preserved locally; duplicate atom bodies are in native comparison once"}}
    if "local_source_envelopes" in packet: projected["local_source_envelopes"] = deepcopy(packet["local_source_envelopes"])
    current = deepcopy(inputs)
    current["revision_diagnostics"] = {"complete_same_source_enacted_review": {k: deepcopy(decision[k]) for k in (
        "valid", "accepted", "status", "revision_target", "native_revision_target", "requires_new_goal_plan", "uncertainties", "native_report_sha256", "compiled_ledger_sha256")},
        "native_enacted_review": projected}
    result = prepare_base(current, profile, goal, audit, **kwargs)
    result["manifest"].update(isolated_writer_feedback_projection={"schema": version + "/writer_feedback_projection_manifest",
        "original_packet_sha256": protocol.digest(packet), "outbound_projection_sha256": protocol.digest(projected),
        "referenced_event_ids": sorted(used), "native_comparison_preserved_exact": True, "complete_original_draft_preserved_exact": True,
        "complete_native_events_and_ledger_preserved_locally": True, "original_inputs_sha256": protocol.digest(inputs),
        "outbound_inputs_sha256": protocol.digest(current), "no_creative_text_truncated": True,
        "protocol_injected_by_fixed_code": protocol.VERSION})
    return owner.base._mark(result, current)
