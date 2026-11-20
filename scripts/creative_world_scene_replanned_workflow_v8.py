"""Frozen source expectations, original A3 facts, and default full7 reviews."""
from copy import deepcopy
from scripts import creative_world_scene_replanned_workflow_v4 as prior
from scripts import creative_isolated_source_claims_v1 as claims

VERSION = "creative_world_scene_replanned_workflow/v8"


class ReviewWorkflow(prior.ReviewWorkflow):
    prepare_observable_events_request = staticmethod(claims.facts.prepare_events)
    validate_observable_events = staticmethod(claims.facts.validate_events)
    prepare_source_claims_request = staticmethod(claims.prepare_claims)
    validate_source_claims = staticmethod(claims.validate_claims)
    prepare_claims_comparison_request = staticmethod(claims.prepare_comparison)
    validate_claims_comparison = staticmethod(claims.validate_comparison)
    build_event_entailment_review_packet = staticmethod(claims.build_review_packet)
    build_event_entailment_repair_feedback = staticmethod(claims.build_repair_feedback)

    def prepare_script_request(self, inputs, profile, goal, audit, **kwargs):
        diagnostics = inputs.get("revision_diagnostics")
        packet = diagnostics.get("native_enacted_review") if type(diagnostics) is dict else None
        if type(packet) is not dict or packet.get("schema") != claims.VERSION + "/repair_feedback":
            return super().prepare_script_request(inputs, profile, goal, audit, **kwargs)
        clean = {k: deepcopy(v) for k, v in inputs.items() if k not in ("previous_complete_document", "revision_diagnostics")}
        views = self.base.compile_native_views(goal, kwargs["opening_setup"], **self.origin_ids(clean))
        raw = inputs["previous_complete_document"]
        sp = claims.prepare_claims(clean, profile, raw, views)
        ep = claims.facts.prepare_events(clean, profile, raw, views)
        sn, en, cn = (packet[k] for k in ("native_source_claims_report", "native_observable_events_report", "native_claim_comparison_report"))
        cp = claims.prepare_comparison(clean, profile, raw, views, sn, sp, en, ep)
        expected = claims.build_repair_feedback(sn, sp, en, ep, cn, cp)
        if {k: v for k, v in packet.items() if k not in ("coordinator_packet_schema", "packet_is_model_native")} != expected:
            raise ValueError("writer requires exactly reconstructed frozen claims, actual facts and failed comparison")
        decision = claims.validate_comparison(cn, cp)
        if diagnostics.get("complete_same_source_enacted_review") != decision: raise ValueError("writer functional decision differs")
        ledger = packet["verified_compiled_event_ledger"]
        used = set()
        for row in cn["checks"]:
            for key in ("support", "counterevidence", "response_refs"):
                used.update(claims._refs(row[key], ledger))
        reach = claims.facts._closure(ledger["events"], ledger["temporal_relations"])
        for row in cn["checks"]:
            if row["ordering"] != "completed_before": continue
            for a in claims._refs(row["support"], ledger):
                for b in claims._refs(row["response_refs"], ledger):
                    used.update(r for r in ledger["events"] if r in reach[a] and b in reach[r])
        relations = [deepcopy(row) for row in ledger["temporal_relations"] if row["before_event"] in used and row["after_event"] in used]
        steps = {ledger["events"][ref]["step_ref"] for ref in used}
        for row in relations: steps.update(p["step_ref"] for p in row["evidence"])
        for row in cn["checks"]: steps.update(p["step_ref"] for p in row["temporal_evidence"])
        subset = {"events": {ref: deepcopy(value) for ref, value in ledger["events"].items() if ref in used},
            "source_steps": {ref: deepcopy(value) for ref, value in ledger["source_steps"].items() if ref in steps},
            "temporal_relations": relations, "extraction_is_fallible_model_interpretation": True,
            "omitted_events_are_not_missing_extraction": True}
        # Index-only compiler metadata avoids repeating each field path for all
        # of its units. Raw part text and every raw verdict remain complete.
        directory = {"unit_order": list(sp["views"]["source_units"]),
            "fields": {ref: {k: deepcopy(value) for k, value in field.items() if k != "text"} for ref, field in sp["views"]["source_fields"].items()},
            "unit_ranges": [{k: row[k] for k in ("field_ref", "start", "end")} for row in sp["views"]["source_units"].values()],
            "claim_id_rule": "unit_order[index]#raw parts index; metadata only, not model-native"}
        functional = {k: deepcopy(decision[k]) for k in ("valid", "accepted", "status", "revision_target", "native_revision_target",
            "requires_new_goal_plan", "findings", "computed_slot_findings", "uncertainties", "native_report_sha256", "compiled_claims_sha256", "compiled_ledger_sha256")}
        projected_functional = {k: deepcopy(v) for k, v in functional.items() if k not in ("findings", "computed_slot_findings")}
        projected_functional["finding_paths"] = [{k: deepcopy(row[k]) for k in ("claim_ref", "code", "target") if k in row} for row in decision["findings"]]
        provenance = {kind: {**{k: env[k] for k in ("native_report_sha256", "actual_request_sha256", "actual_context_sha256") if k in env},
            "complete_local_source_envelope_sha256": claims.digest(env)} for kind, env in packet["local_source_envelopes"].items()}
        # A3 calls its original native-payload hash native_payload_sha256.
        provenance["events"]["native_report_sha256"] = claims.digest(en)
        projected = {"schema": VERSION + "/writer_feedback_projection", "native_source_claims_report": deepcopy(sn),
            "native_claim_comparison_report": deepcopy(cn), "source_unit_directory": directory,
            "verified_event_reference_closure": subset, "functional_decision": projected_functional,
            "source_descriptor": deepcopy(packet["source_descriptor"]), "review_provenance": provenance,
            "original_packet_sha256": claims.digest(packet), "native_observable_events_report_sha256": claims.digest(en),
            "complete_compiled_event_ledger_sha256": claims.digest(ledger),
            "omitted_manifest": {"native_observable_events_report": "complete original raw preserved locally; all comparison references supplied in verified closure",
                "verified_compiled_event_ledger": "complete compiled ledger preserved locally; referenced event/step/temporal closure supplied",
                "verified_compiled_source_claims": "deterministic compilation preserved locally; complete raw source claims and exact source locator directory supplied",
                "full_derived_findings": "full decision preserved locally; exact claim finding paths supplied; native row bodies already in complete comparison once",
                "complete_local_source_envelopes": "full envelopes preserved locally; original hashes/request/context and envelope digests supplied; common source descriptor appears once"}}
        current = deepcopy(inputs)
        current["revision_diagnostics"] = {"complete_same_source_enacted_review": {k: deepcopy(v) for k, v in functional.items() if k not in ("findings", "computed_slot_findings")},
            "native_enacted_review": projected}
        result = super().prepare_script_request(current, profile, goal, audit, **kwargs)
        result["manifest"].update(isolated_writer_feedback_projection={"schema": VERSION + "/manifest", "native_protocol_version": claims.VERSION,
            "packet_sha256": claims.digest(packet), "outbound_projection_sha256": claims.digest(projected), "event_refs": sorted(used),
            "native_claims_preserved_exact": True, "native_comparison_preserved_exact": True,
            "complete_original_draft_preserved_exact": True, "no_creative_text_truncated": True})
        return self.base._mark(result, current)
