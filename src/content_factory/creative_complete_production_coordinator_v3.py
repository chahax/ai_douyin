"""Reusable coordinator with injected immutable runtime dispatch and storage.

The coordinator has no network/media client. A production caller must supply
frozen source verification, persist-before-dispatch storage and an evidenced
ContinuationRuntime dispatcher. Offline callers supply explicitly fake service
receipts. Historical limits are consulted before any director invocation.
"""
from copy import deepcopy
from jsonschema import ValidationError

from scripts import run_creative_shared_full_production_v1 as schemas
from . import creative_complete_production_pipeline_v3 as pipeline
from . import creative_production_revision_loop_v3 as loop
from . import creative_shared_media_contract_v3 as media
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_complete_production_coordinator/v3"


class CompleteProductionCoordinator:
    def __init__(self, *, invoke, persist_state, verify_frozen_source, opening_context_builder,
                 models, maximum_local_content_revisions=2):
        self.invoke = invoke
        self.persist_state = persist_state
        self.verify_frozen_source = verify_frozen_source
        self.opening_context_builder = opening_context_builder
        self.models = deepcopy(models)
        if type(maximum_local_content_revisions) is not int or not 0 <= maximum_local_content_revisions <= 2:
            raise ValueError("local content revision limit may not exceed the existing authorization")
        self.maximum_local_content_revisions = maximum_local_content_revisions

    def _call(self, label, request, validate):
        self.verify_frozen_source()
        receipt = self.invoke(label, request, validate)
        evidence = loop.normalize_receipt(receipt, request)
        return receipt, evidence

    def _stop(self, reason, state, events, route=None):
        state = deepcopy(state)
        terminal = {"reason": reason, "failure_route": deepcopy(route), "events": deepcopy(events)}
        previous_terminal = state.get("coordinator_terminal")
        if previous_terminal is not None and previous_terminal != terminal:
            state["coordinator_terminal_history"] = state.get("coordinator_terminal_history", []) + [deepcopy(previous_terminal)]
        state["coordinator_status"] = "stopped"
        state["coordinator_terminal"] = terminal
        self.persist_state(deepcopy(state))
        return {"schema": VERSION + "/result", "status": "needs_attention", "reason": reason,
            "loop_state": deepcopy(state), "events": deepcopy(events), "failure_route": deepcopy(route),
            "complete_text_handoff_ready": False, "media_dispatch_allowed": False,
            "actual_media_quality_passed": False, "budget_reset": False, "automatic_retry": False}

    def run(self, *, script, manifest, initial, reference_fulltext, preferences, brief,
            source_review_binding, state, cached_performances=(), scope=None):
        """Rebuild native direction, changed locals and full review within bounds.

        No old whole review is reused, even when every local input is unchanged.
        A failed local estimate returns to the whole director with its original
        native schedule. Unchanged local input must include rules/model/schema.
        """
        self.verify_frozen_source()
        state = deepcopy(state)
        events, diagnostics, cache = [], [], deepcopy(list(cached_performances))
        material = {"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial}
        if state.get("stable_scope_material") is not None and state["stable_scope_material"] != material:
            return self._stop("COMPLETE_CREATIVE_SOURCE_SCOPE_CHANGED", state, events)
        if (type(source_review_binding.get("writer_ordinal")) is not int
            or type(source_review_binding.get("review_ordinal")) is not int
            or source_review_binding["writer_ordinal"] >= source_review_binding["review_ordinal"]
            or source_review_binding.get("script_sha256") != source.digest(script)
            or source_review_binding.get("machine_text_review_passed") is not True):
            return self._stop("COMPLETE_SOURCE_NATIVE_REVIEW_BINDING_REQUIRED", state, events)
        if state.get("coordinator_status") in ("running", "completed"):
            return self._stop("EXISTING_EXECUTION_RECONCILE_OR_REUSE_SAVED_HANDOFF", state, events)
        terminal = state.get("coordinator_terminal")
        if terminal:
            if terminal["reason"] != "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED" or not loop.candidate_capacity(state)["remaining"]:
                return self._stop(terminal["reason"], state, terminal["events"], terminal.get("failure_route"))
            # An explicit extra-candidate grant can reopen a known bounded stop.
            # The terminal evidence is retained and passed to the new director.
            diagnostics.append({"complete_previous_stop": deepcopy(terminal), "adopted": False})
            state["coordinator_terminal_history"] = state.get("coordinator_terminal_history", []) + [deepcopy(terminal)]
            state.pop("coordinator_terminal", None)
        for event in state["director_events"]:
            result = event.get("result", {})
            if result.get("known_complete") and result.get("status") == "contract_rejected":
                item = {"prior_complete_native_direction": deepcopy(result["native_document"]),
                    "original_result_identity": {key: result[key] for key in ("result_id", "request_sha256", "receipt_sha256", "reported_tokens")},
                    "adopted": False}
                if all("end_source_ref" in row for row in result["native_document"].get("segments", [])):
                    item["native_timing_diagnostic"] = pipeline.ranges.rejected_direction_timing_report(result["native_document"], script)
                diagnostics.append(item)
        while True:
            capacity = loop.candidate_capacity(state)
            if capacity["unresolved_claims"] or capacity.get("unresolved_result_ids"):
                return self._stop("ORIGINAL_DIRECTOR_RESULT_UNRESOLVED", state, events)
            if not capacity["remaining"]:
                return self._stop("INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED", state, events)
            inputs = pipeline.build_director_input(script, manifest, initial, reference_fulltext, preferences, diagnostics)
            request = pipeline.build_request("whole_direction", inputs,
                pipeline.whole_direction_schema(script, manifest), self.models["writer"])
            identity = source.digest(request)
            state = loop.claim_director_request(state, identity)
            state["coordinator_status"] = "running"
            self.persist_state(deepcopy(state))  # must be durable before invoke
            label = "whole_direction_v3_" + str(capacity["attempts_including_claims"])
            validate = lambda native: pipeline.compile_direction(native, script, manifest)
            receipt, evidence = self._call(label, request, validate)
            state = loop.register_director_result(state, evidence, identity)
            self.persist_state(deepcopy(state))
            events.append({"stage": "whole_direction", "receipt": deepcopy(receipt), "evidence": evidence})
            if not evidence["known_complete"]:
                return self._stop("DIRECTOR_RESULT_NOT_COMPLETE", state, events)
            native = evidence["native_document"]
            try:
                direction = validate(native)
            except (ValueError, ValidationError) as exc:
                route = loop.route_failure(state, loop.DIRECTOR_FAILURE, evidence, native,
                    diagnostic={"validation_error": str(exc)})
                if route["action"] != "whole_direction_revision":
                    return self._stop(route["reason"], state, events, route)
                diagnostics.append(route["revision_input"])
                continue
            if evidence["status"] != "contract_valid":
                return self._stop("DIRECTOR_RUNTIME_ACCEPTANCE_MISMATCH", state, events)
            performances, prefix, current_state = [], [], deepcopy(initial)
            director_route = None
            for segment in direction["segments"]:
                perf_input = pipeline.build_performance_input(script, manifest, segment, current_state, prefix,
                    reference_fulltext, preferences)
                perf_schema = pipeline.performance_schema(script, manifest, segment, current_state, prefix)
                perf_request = pipeline.build_request("local_performance", perf_input, perf_schema, self.models["writer"])
                validate_local = lambda value: pipeline.compile_performance(value, script, manifest, segment, current_state, prefix)
                reuse = loop.reuse_native_performance(cache, perf_request, validate_local)
                events.append({"stage": "reuse_check", "segment_id": segment["segment_id"], "result": reuse})
                if reuse["status"] == "blocked":
                    return self._stop(reuse["reason"], state, events)
                if reuse["native_reused"]:
                    compiled = reuse["compiled"]
                else:
                    failed_locals = []
                    compiled = None
                    for revision in range(self.maximum_local_content_revisions + 1):
                        actual_input = deepcopy(perf_input)
                        if failed_locals:
                            actual_input["previous_complete_rejected_versions"] = deepcopy(failed_locals)
                        actual_request = pipeline.build_request("local_performance", actual_input, perf_schema, self.models["writer"])
                        local_label = "performance_v3_d" + str(capacity["attempts_including_claims"]) + "_" + segment["segment_id"] + "_r" + str(revision)
                        local_receipt, local_evidence = self._call(local_label, actual_request, validate_local)
                        events.append({"stage": "local_performance", "receipt": local_receipt, "evidence": local_evidence})
                        if not local_evidence["known_complete"]:
                            return self._stop("LOCAL_RESULT_NOT_COMPLETE", state, events)
                        local_native = local_evidence["native_document"]
                        try:
                            compiled = validate_local(local_native)
                        except pipeline.PerformanceWindowExceeded as exc:
                            events.append({"stage": "local_window_diagnostic", "diagnostic": deepcopy(exc.diagnostic)})
                            director_route = loop.route_failure(state, loop.WINDOW_FAILURE, local_evidence, native,
                                failed_native_performance=local_native, diagnostic=exc.diagnostic)
                            if director_route["action"] != "whole_direction_revision":
                                return self._stop(director_route["reason"], state, events, director_route)
                            break
                        except (ValueError, ValidationError) as exc:
                            failed_locals.append({"ordinal": local_receipt.get("ordinal"),
                                "complete_rejected_native": deepcopy(local_native), "validation_error": str(exc),
                                "reported_tokens": local_evidence["reported_tokens"], "adopted": False})
                            compiled = None
                            continue
                        if local_evidence["status"] != "contract_valid":
                            return self._stop("LOCAL_RUNTIME_ACCEPTANCE_MISMATCH", state, events)
                        cache.append({"request": actual_request, "receipt": local_receipt, "compiled": compiled})
                        break
                    if director_route:
                        break
                    if compiled is None:
                        return self._stop("LOCAL_CONTENT_REVISION_ALLOWANCE_EXHAUSTED", state, events)
                performances.append(compiled)
                prefix += segment["source_refs"]
                current_state = deepcopy(compiled["planned_ending_state"])
            if director_route:
                diagnostics.append(director_route["revision_input"])
                events.append({"stage": "whole_direction_revision", "route": director_route,
                    "full_production_review_invalidated": True})
                continue
            complete = pipeline.compile_complete(direction, performances, script, manifest, initial)
            prompts = [pipeline.render_prompt(row, script, manifest) for row in performances]
            opening_context = self.opening_context_builder(performances[0])
            opening_prompt = pipeline.render_prompt(performances[0], script, manifest, opening_context)
            actual_preview = media.compile_request_preview(opening_context, opening_prompt, performances[0]["duration_seconds"])
            review_input = {"brief": deepcopy(brief), "full_current_script": deepcopy(script),
                "source_catalog": source.catalog(script), "shared_manifest": deepcopy(manifest),
                "whole_direction": direction, "complete_compilation": complete, "all_local_performances": performances,
                "all_planned_video_prompts": prompts, "opening_actual_video_prompt": opening_prompt,
                "opening_shared_projection": opening_context, "opening_actual_provider_request": actual_preview["request"],
                "opening_actual_request_proof": actual_preview["proof"], "reference_fulltext": reference_fulltext,
                "source_full_review_binding": deepcopy(source_review_binding), "scope": deepcopy(scope),
                "voice_binding": "unbound", "pixel_identity_verified": False}
            review_schema = schemas.review_schema(schemas.PRODUCTION_CHECKS, list(source.catalog(script)))
            review_request = pipeline.build_request("whole_production_review", review_input, review_schema, self.models["director"])
            def validate_review(value):
                return schemas.validate_review(value, review_schema)
            review_receipt, review_evidence = self._call("whole_production_review_v3_d" + str(capacity["attempts_including_claims"]),
                review_request, validate_review)
            events.append({"stage": "whole_production_review", "receipt": review_receipt, "evidence": review_evidence})
            if not review_evidence["known_complete"] or review_evidence["status"] != "contract_valid":
                return self._stop("FULL_PRODUCTION_REVIEW_NOT_COMPLETE", state, events)
            try:
                verdict = validate_review(review_evidence["native_document"])
            except (ValueError, ValidationError):
                return self._stop("FULL_PRODUCTION_REVIEW_CONTRACT_INVALID", state, events)
            if verdict["has_unknown"]:
                return self._stop("FULL_PRODUCTION_REVIEW_UNKNOWN", state, events)
            if verdict["needs_revision"]:
                route = loop.route_failure(state, loop.REVIEW_FAILURE, review_evidence, native,
                    diagnostic={"complete_compilation_sha256": source.digest(complete)})
                if route["action"] != "whole_direction_revision":
                    return self._stop(route["reason"], state, events, route)
                diagnostics.append(route["revision_input"])
                events.append({"stage": "whole_direction_revision", "route": route,
                    "full_production_review_invalidated": True})
                continue
            reviewed_request_proof = media.verify_reviewed_request(actual_preview["request"], actual_preview, review_receipt,
                expected_reviewed_request_sha256=source.digest(actual_preview["request"]),
                expected_review_receipt_sha256=source.digest(review_receipt),
                expected_review_input=review_input, expected_checks=schemas.PRODUCTION_CHECKS)
            state["coordinator_status"] = "completed"
            state["coordinator_completion"] = {"complete_compilation_sha256": source.digest(complete),
                "production_review_ordinal": review_receipt["ordinal"], "opening_request_sha256": source.digest(actual_preview["request"])}
            self.persist_state(deepcopy(state))
            return {"schema": VERSION + "/result", "status": "complete_text_production_handoff_ready",
                "loop_state": state, "events": events, "direction": direction, "performances": performances,
                "complete_compilation": complete, "planned_prompts": prompts, "opening_actual_preview": actual_preview,
                "opening_shared_context": opening_context, "opening_actual_prompt": opening_prompt,
                "reviewed_request_identity_proof": reviewed_request_proof,
                "production_review_ordinal": review_receipt["ordinal"], "review_limitations": review_evidence["native_document"]["review_limitations"],
                "complete_text_handoff_ready": True, "media_dispatch_allowed": False,
                "actual_media_quality_passed": False, "human_creative_quality_passed": False,
                "budget_reset": False, "automatic_retry": False}
