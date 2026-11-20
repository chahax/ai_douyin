"""Thin isolated comparison and writer-only feedback projection over WF4."""
from copy import deepcopy

from scripts import creative_world_scene_replanned_workflow_v4 as prior
from scripts import creative_isolated_event_entailment_v1 as isolated

VERSION = "creative_world_scene_replanned_workflow/v5"


class ReviewWorkflow(prior.ReviewWorkflow):
    prepare_observable_events_request = staticmethod(isolated.prepare_events)
    validate_observable_events = staticmethod(isolated.validate_events)
    prepare_event_entailment_request = staticmethod(isolated.prepare_entailment)
    validate_event_entailment = staticmethod(isolated.validate_entailment)
    build_event_entailment_review_packet = staticmethod(isolated.build_review_packet)
    build_event_entailment_repair_feedback = staticmethod(isolated.build_repair_feedback)

    def prepare_script_request(self, inputs, profile, goal, audit, **kwargs):
        diagnostics = inputs.get("revision_diagnostics")
        packet = diagnostics.get("native_enacted_review") if type(diagnostics) is dict else None
        if type(packet) is not dict or packet.get("schema") != isolated.VERSION + "/repair_feedback":
            return super().prepare_script_request(inputs, profile, goal, audit, **kwargs)
        clean = {k: deepcopy(v) for k, v in inputs.items() if k not in ("previous_complete_document", "revision_diagnostics")}
        views = self.base.compile_native_views(goal, kwargs["opening_setup"], **self.origin_ids(clean))
        raw = inputs["previous_complete_document"]
        ep = isolated.prepare_events(clean, profile, raw, views)
        events = packet["native_observable_events_report"]
        cp = isolated.prepare_entailment(clean, profile, raw, views, events, ep)
        comparison = packet["native_claim_comparison_report"]
        # Regenerate the precise admitted packet. No external passed flag or
        # metadata-only ledger is trusted as a new creative authority.
        expected = isolated.build_repair_feedback(events, ep, comparison, cp)
        allowed_extra = {"coordinator_packet_schema", "packet_is_model_native"}
        if {k: v for k, v in packet.items() if k not in allowed_extra} != expected:
            raise ValueError("writer feedback packet is not its exact same-source verified comparison/ledger")
        if diagnostics.get("complete_same_source_enacted_review") != isolated.validate_entailment(comparison, cp):
            raise ValueError("writer functional decision differs from native comparison and local slot checks")
        used = set()
        for field in comparison["fields"].values():
            for segment in field["source_segments"]:
                used.update(segment["event_refs"]); used.update(segment["prior_event_refs"])
        ledger = packet["verified_compiled_event_ledger"]
        reach = isolated._closure(ledger["events"], ledger["temporal_relations"])
        for field in comparison["fields"].values():
            for segment in field["source_segments"]:
                if segment["temporal_requirement"] == "before":
                    for a in segment["prior_event_refs"]:
                        for b in segment["event_refs"]:
                            used.update(ref for ref in ledger["events"] if ref in reach[a] and b in reach[ref])
        step_refs = {ledger["events"][ref]["step_ref"] for ref in used}
        relations = [deepcopy(row) for row in ledger["temporal_relations"]
            if row["before_event"] in used and row["after_event"] in used]
        for row in relations: step_refs.update(p["step_ref"] for p in row["evidence"])
        subset = {"schema": isolated.VERSION + "/writer_event_reference_closure",
            "events": {ref: deepcopy(row) for ref, row in ledger["events"].items() if ref in used},
            "source_steps": {ref: deepcopy(row) for ref, row in ledger["source_steps"].items() if ref in step_refs},
            "temporal_relations": relations, "omitted_events_are_not_missing_extraction": True,
            "is_fallible_interpretation_not_authority": True}
        functional = packet["functional_decision"]
        projected = {"schema": VERSION + "/writer_feedback_projection",
            "native_claim_comparison_report": deepcopy(comparison), "verified_event_reference_closure": subset,
            "used_source_fields": deepcopy(packet["used_source_fields"]),
            "functional_decision": {k: deepcopy(v) for k, v in functional.items() if k != "computed_slot_findings"},
            "computed_slot_finding_paths": [{k: deepcopy(row[k]) for k in ("field_ref", "segment_index", "code", "target")}
                for row in functional["computed_slot_findings"]],
            "source_descriptor": deepcopy(packet["source_descriptor"]),
            "original_review_packet_sha256": isolated.digest(packet), "native_observable_events_report_sha256": isolated.digest(events),
            "complete_compiled_event_ledger_sha256": isolated.digest(ledger),
            "omitted_manifest": {"native_observable_events_report": "complete native preserved in local packet/receipt; typed referenced event closure below",
                "verified_compiled_event_ledger": "complete ledger preserved locally; every outbound comparison event reference is included",
                "complete_derived_decision": "preserved locally; duplicate atom bodies are in native comparison once"}}
        current = deepcopy(inputs)
        decision = diagnostics["complete_same_source_enacted_review"]
        current["revision_diagnostics"] = {"complete_same_source_enacted_review": {
            k: deepcopy(decision[k]) for k in ("valid", "accepted", "status", "revision_target", "native_revision_target",
                "requires_new_goal_plan", "uncertainties", "native_report_sha256", "compiled_ledger_sha256")},
            "native_enacted_review": projected}
        result = super().prepare_script_request(current, profile, goal, audit, **kwargs)
        result["manifest"].update(isolated_writer_feedback_projection={
            "schema": VERSION + "/writer_feedback_projection_manifest", "original_packet_sha256": isolated.digest(packet),
            "outbound_projection_sha256": isolated.digest(projected), "referenced_event_ids": sorted(used),
            "native_comparison_preserved_exact": True, "complete_original_draft_preserved_exact": True,
            "complete_native_events_and_ledger_preserved_locally": True, "original_inputs_sha256": isolated.digest(inputs),
            "outbound_inputs_sha256": isolated.digest(current), "no_creative_text_truncated": True})
        return self.base._mark(result, current)
