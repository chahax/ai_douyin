"""Reusable coordinator with injected immutable runtime dispatch and storage.

The coordinator has no network/media client. A production caller must supply
frozen source verification, persist-before-dispatch storage and an evidenced
ContinuationRuntime dispatcher. Offline callers supply explicitly fake service
receipts. Historical limits are consulted before any director invocation.
"""
from copy import deepcopy
import base64
import hashlib
import json
from jsonschema import ValidationError

from scripts import run_creative_shared_full_production_v1 as schemas
from . import creative_complete_production_pipeline_v4 as pipeline
from . import creative_production_revision_loop_v3 as loop
from . import creative_shared_media_contract_v3 as media
from . import creative_video_trial_contract_v1 as source
from . import creative_provider_preflight_v1 as capability
from . import creative_reference_compiler_v4 as references

VERSION = "creative_complete_production_coordinator/v4"
MODEL_ROLE_POLICY = {"writer": "MiniMax-M3", "director": "deepseek-flash"}


def production_context_digest(brief, reference_fulltext, preferences):
    """Frozen input identity only, never a claim that 513 reviewed preferences."""
    return source.digest({"brief": brief, "reference_fulltext": reference_fulltext,
        "production_preferences": preferences})


class DispatchGateError(ValueError):
    def __init__(self, code, diagnostic=None):
        self.code = code
        self.diagnostic = deepcopy(diagnostic)
        super().__init__(code)


class CompleteProductionCoordinator:
    def __init__(self, *, invoke, persist_state, verify_frozen_source, opening_context_builder,
                 models, maximum_local_content_revisions=2, preflight_text_request=None,
                 capability_registry=None, director_request_enricher=None):
        self.invoke = invoke
        self.persist_state = persist_state
        self.verify_frozen_source = verify_frozen_source
        self.opening_context_builder = opening_context_builder
        self.models = deepcopy(models)
        self.preflight_text_request = preflight_text_request or capability.preflight_text_request
        self.capability_registry = deepcopy(capability_registry)
        self.director_request_enricher = director_request_enricher
        if type(maximum_local_content_revisions) is not int or not 0 <= maximum_local_content_revisions <= 2:
            raise ValueError("local content revision limit may not exceed the existing authorization")
        self.maximum_local_content_revisions = maximum_local_content_revisions

    def _preflight(self, request):
        self.verify_frozen_source()
        try:
            report = self.preflight_text_request(request, self.capability_registry)
        except capability.ProviderPreflightError as exc:
            raise DispatchGateError("TEXT_PROVIDER_CAPABILITY_PREFLIGHT_FAILED",
                {"code": exc.code, "detail": getattr(exc, "detail", None)}) from exc
        if (report.get("status") != "capability_preflight_passed" or report.get("blocked") is not False
            or report.get("request_sha256") != source.digest(request)):
            raise DispatchGateError("TEXT_PROVIDER_PREFLIGHT_IDENTITY_INVALID")
        return report

    def _enrich_director(self, request):
        if self.director_request_enricher is None:
            return request, {"status": "no_selected_visual_material", "images_in_actual_request": 0,
                "pixel_identity_verified": False, "calls_authorized": False}
        try:
            enriched = self.director_request_enricher(deepcopy(request))
        except references.ReferenceCompilerError as exc:
            raise DispatchGateError("DIRECTOR_REFERENCE_BINDING_INVALID",
                {"code": exc.code, "detail": exc.detail, "dispatch_started": False}) from exc
        except Exception as exc:
            raise DispatchGateError("DIRECTOR_REFERENCE_ENRICHER_FAILED",
                {"exception_type": type(exc).__name__, "dispatch_started": False,
                 "automatic_retry": False}) from exc
        if not isinstance(enriched, dict) or not isinstance(enriched.get("request"), dict):
            raise DispatchGateError("DIRECTOR_REFERENCE_ENRICHER_RESULT_INVALID")
        actual = enriched["request"]
        if (not isinstance(actual.get("messages"), list)
            or any(not isinstance(message, dict) for message in actual["messages"])):
            raise DispatchGateError("DIRECTOR_REFERENCE_ENRICHER_RESULT_INVALID")
        # B appends a separate user image message. The original source JSON,
        # transport/schema/model and every existing message remain exact.
        base, after = deepcopy(request), deepcopy(actual)
        base_messages, actual_messages = base.pop("messages"), after.pop("messages")
        if (base != after or actual_messages[:len(base_messages)] != base_messages
            or len(actual_messages) <= len(base_messages)
            or any(message.get("role") != "user" or not isinstance(message.get("content"), list)
                for message in actual_messages[len(base_messages):])):
            raise DispatchGateError("DIRECTOR_VISUAL_ENRICHMENT_CHANGED_SOURCE_REQUEST")
        proof = deepcopy(enriched.get("proof", enriched.get("coverage", {})))
        if not isinstance(proof, dict):
            raise DispatchGateError("DIRECTOR_VISUAL_PROOF_OR_IMAGE_PAYLOAD_MISSING")
        if any(not isinstance(part, dict) for message in actual_messages[len(base_messages):]
            for part in message["content"]):
            raise DispatchGateError("DIRECTOR_VISUAL_COVERAGE_MAPPING_INVALID")
        images = [part for message in actual_messages[len(base_messages):]
            for part in message["content"] if part.get("type") == "image_url"]
        if (not images or proof.get("schema") != "creative_reference_compiler/v4/director_visual_coverage"
            or proof.get("original_messages_sha256") != source.digest(base_messages)
            or proof.get("actual_messages_sha256") != source.digest(actual_messages)
            or proof.get("original_messages_preserved") is not True
            or len(actual_messages) != len(base_messages) + 1
            or proof.get("multimodal_message_index") != len(base_messages)):
            raise DispatchGateError("DIRECTOR_VISUAL_PROOF_OR_IMAGE_PAYLOAD_MISSING")
        parts, rows = actual_messages[-1]["content"], proof.get("ordered_images", [])
        mapping = proof.get("entity_asset_mapping", [])
        if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            or len(rows) != len(images) or len(parts) != len(images) + 1
            or parts[0].get("type") != "text" or not isinstance(parts[0].get("text"), str)
            or not isinstance(mapping, list) or not mapping or any(not isinstance(row, dict) for row in mapping)
            or proof.get("mapping_sha256") != source.digest(mapping)):
            raise DispatchGateError("DIRECTOR_VISUAL_COVERAGE_MAPPING_INVALID")
        try:
            if json.loads(parts[0]["text"].split("\n")[-1]) != mapping:
                raise ValueError("actual map text differs from covered map")
            for index, (part, row) in enumerate(zip(parts[1:], rows), 1):
                if (part.get("type") != "image_url" or row.get("content_index") != index
                    or row.get("reference_number") != index or row.get("reference_label") != "image" + str(index)):
                    raise ValueError("actual image position differs from covered numbering")
                url = part["image_url"]["url"]
                if not url.startswith("data:image/") or ";base64," not in url:
                    raise ValueError("B director adapter requires original independent image bytes")
                data = base64.b64decode(url.split(";base64,", 1)[1], validate=True)
                if not data or hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise ValueError("actual image bytes differ from original mapped hash")
            by_id = {row["asset_id"]: row for row in rows}
            if len(by_id) != len(rows):
                raise ValueError("covered image identities repeat")
            for row in mapping:
                actual_row = by_id[row["asset_id"]]
                if any(row.get(key) != actual_row[key] for key in
                    ("content_index", "reference_number", "reference_label")):
                    raise ValueError("subject mapping points at a different actual image")
            actual_input = json.loads(base_messages[1]["content"])
            expected_entities = {("actor", row["id"]) for row in actual_input["shared_manifest"]["actors"]}
            expected_entities |= {("scene", row["id"]) for row in actual_input["shared_manifest"]["scenes"]}
            required_entities = {(row["entity_type"], row["entity_id"]) for row in proof["required_visual_entities"]}
            mapped_entities = {(row["entity_type"], row["entity_id"]) for row in mapping}
            if not expected_entities.issubset(required_entities) or not required_entities.issubset(mapped_entities):
                raise ValueError("whole director required actors/scenes have no actual image mapping")
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
            raise DispatchGateError("DIRECTOR_VISUAL_COVERAGE_MAPPING_INVALID") from exc
        return actual, proof

    @staticmethod
    def _visual_cache_binding(proof):
        material = {key: deepcopy(proof.get(key)) for key in
            ("status", "ordered_images", "entity_asset_mapping", "required_visual_entities",
             "voice_identity_guaranteed", "provider_input_acceptance")}
        return {"schema": VERSION + "/director_visual_cache_binding",
            "selected_material_sha256": source.digest(material),
            "entity_asset_mapping": deepcopy(proof.get("entity_asset_mapping", [])),
            "voice_identity_bound": False, "pixel_identity_verified": False}

    @staticmethod
    def _latest_revision_diagnostics(diagnostics, feedback):
        """Retain stop metadata; send one latest native content correction.

        Complete earlier responses stay in persisted events and receipts.
        Re-sending every full rejected draft is not needed for a complete
        replacement and makes the next prompt grow after each revision.
        """
        summaries = [deepcopy(row) for row in diagnostics
            if isinstance(row, dict) and "previous_stop_summary" in row]
        return [*summaries, deepcopy(feedback)]

    @staticmethod
    def _terminal_prompt_context(terminal, state):
        """Keep full stop history on disk; model sees bounded source feedback."""
        capacity = loop.candidate_capacity(state)
        if capacity["unresolved_claims"] or capacity.get("unresolved_result_ids"):
            raise DispatchGateError("ORIGINAL_DIRECTOR_RESULT_UNRESOLVED")
        failed_route = terminal.get("failure_route") or {}
        summary = {"previous_stop_summary": {
            "reason": terminal["reason"], "terminal_sha256": source.digest(terminal),
            "failure_code": failed_route.get("failure_code"),
            "original_result_id": failed_route.get("original_result_id"),
            "capacity_after_explicit_grant": capacity},
            "complete_stop_preserved_in_history": True, "adopted": False}
        # Every result remains in the immutable journal. Never send its old
        # request/messages/full inputs as part of a stop diagnostic.
        evidence_rows = [event["evidence"] for event in terminal.get("events", [])
            if isinstance(event.get("evidence"), dict)]
        if any(row.get("known_complete") is not True for row in evidence_rows):
            raise DispatchGateError("ORIGINAL_STOP_RESULT_NOT_COMPLETE")
        candidates = [event["result"] for event in state["director_events"]
            if isinstance(event.get("result"), dict)]
        original_id = failed_route.get("original_result_id")
        evidence = next((row for row in reversed(evidence_rows + candidates)
            if row.get("result_id") == original_id), None)
        latest_direction = next((row["native_document"] for row in reversed(candidates)
            if row.get("known_complete") is True), None)
        if evidence is None or evidence.get("known_complete") is not True or latest_direction is None:
            return summary, None
        code = failed_route.get("failure_code")
        diagnostic = None
        if code == loop.WINDOW_FAILURE:
            diagnostic = next((event["diagnostic"] for event in reversed(terminal.get("events", []))
                if event.get("stage") == "local_window_diagnostic"), None)
        elif code == loop.DIRECTOR_FAILURE:
            prior_feedback = failed_route.get("revision_input", {})
            diagnostic = prior_feedback.get("diagnostic")
        elif code == loop.REVIEW_FAILURE:
            diagnostic = failed_route.get("revision_input", {}).get("diagnostic")
        # The original route was blocked at the exhausted cap. Re-evaluate
        # exactly its known native result under the already explicit grant;
        # this only builds feedback and adds no request/candidate/authorization.
        route = loop.route_failure(state, code, evidence, latest_direction,
            failed_native_performance=evidence["native_document"] if code == loop.WINDOW_FAILURE else None,
            diagnostic=diagnostic)
        feedback = route.get("revision_input") if route.get("action") == "whole_direction_revision" else None
        return summary, deepcopy(feedback)

    def _call(self, label, request, validate, state, preflight=None):
        expected_request = deepcopy(request)
        report = self._preflight(expected_request) if preflight is None else deepcopy(preflight)
        if report.get("request_sha256") != source.digest(expected_request):
            raise DispatchGateError("TEXT_PROVIDER_PREFLIGHT_IDENTITY_INVALID")
        self.verify_frozen_source()
        identity = source.digest({"label": label, "request_sha256": source.digest(expected_request),
            "source_binding_sha256": state["source_binding_sha256"]})
        journal = state.setdefault("stage_dispatch_events", [])
        if any(event.get("dispatch_identity") == identity for event in journal):
            raise DispatchGateError("EXISTING_STAGE_REQUEST_MUST_RECONCILE_OR_REUSE")
        journal.append({"event": "claim", "dispatch_identity": identity, "label": label,
            "stage": expected_request["stage"], "request_sha256": source.digest(expected_request),
            "preflight": report, "automatic_retry": False})
        state["coordinator_status"] = "running"
        self.persist_state(deepcopy(state))
        try:
            receipt = self.invoke(label, deepcopy(expected_request), validate)
        except Exception as exc:
            # The outcome may be unknown. Preserve the durable claim and never
            # manufacture a result or re-invoke this stage after restart.
            journal.append({"event": "dispatch_exception", "dispatch_identity": identity,
                "exception_type": type(exc).__name__, "outcome_unknown": True})
            self.persist_state(deepcopy(state))
            raise DispatchGateError("STAGE_DISPATCH_OUTCOME_UNKNOWN") from exc
        evidence = loop.normalize_receipt(receipt, expected_request)
        if not loop._compatible_evidence(state, evidence):
            evidence["known_complete"] = False
            evidence["errors"] = list(dict.fromkeys([*evidence["errors"], "SOURCE_IDENTITY_CHANGED"]))
        journal.append({"event": "result", "dispatch_identity": identity,
            "receipt_sha256": source.digest(receipt), "evidence": deepcopy(evidence)})
        self.persist_state(deepcopy(state))
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
        self._active_state, self._active_events = deepcopy(state), []
        try:
            return self._run(script=script, manifest=manifest, initial=initial,
                reference_fulltext=reference_fulltext, preferences=preferences, brief=brief,
                source_review_binding=source_review_binding, state=state,
                cached_performances=cached_performances, scope=scope)
        except DispatchGateError as exc:
            if exc.diagnostic is not None:
                self._active_events.append({"stage": "dispatch_gate", "diagnostic": exc.diagnostic})
            return self._stop(exc.code, self._active_state, self._active_events)
        except (ValueError, ValidationError) as exc:
            self._active_events.append({"stage": "deterministic_gate", "exception_type": type(exc).__name__,
                "validation_error": str(exc), "automatic_retry": False})
            return self._stop("COMPLETE_PRODUCTION_GATE_INVALID", self._active_state, self._active_events)

    def _run(self, *, script, manifest, initial, reference_fulltext, preferences, brief,
            source_review_binding, state, cached_performances=(), scope=None):
        """Rebuild native direction, changed locals and full review within bounds.

        No old whole review is reused, even when every local input is unchanged.
        A failed local estimate returns to the whole director with its original
        native schedule. Unchanged local input must include rules/model/schema.
        """
        self.verify_frozen_source()
        state = deepcopy(state)
        events, diagnostics, cache = [], [], deepcopy(list(cached_performances))
        self._active_state, self._active_events = state, events
        if not isinstance(reference_fulltext, str) or not reference_fulltext.strip():
            return self._stop("COMPLETE_REFERENCE_FULLTEXT_REQUIRED", state, events)
        compatible_cache = []
        for original in cache:
            cached_evidence = loop.normalize_receipt(original.get("receipt", original))
            if loop._compatible_evidence(state, cached_evidence):
                compatible_cache.append(original)
            else:
                events.append({"stage": "cache_scope_rejected", "original_result_id": cached_evidence["result_id"],
                    "reason": "SOURCE_IDENTITY_CHANGED", "native_reused": False})
        cache = compatible_cache
        material = {"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial}
        if state.get("stable_scope_material") is not None and state["stable_scope_material"] != material:
            return self._stop("COMPLETE_CREATIVE_SOURCE_SCOPE_CHANGED", state, events)
        if state.get("stable_scope_sha256") != source.digest(state.get("stable_scope_material")):
            return self._stop("COMPLETE_CREATIVE_SOURCE_SCOPE_IDENTITY_INVALID", state, events)
        if (not isinstance(source_review_binding, dict)
            or type(source_review_binding.get("writer_ordinal")) is not int
            or type(source_review_binding.get("review_ordinal")) is not int
            or source_review_binding["writer_ordinal"] >= source_review_binding["review_ordinal"]
            or source_review_binding.get("script_sha256") != source.digest(script)
            or source_review_binding.get("machine_text_review_passed") is not True):
            return self._stop("COMPLETE_SOURCE_NATIVE_REVIEW_BINDING_REQUIRED", state, events)
        context_identity = production_context_digest(brief, reference_fulltext, preferences)
        if source_review_binding.get("production_context_sha256") != context_identity:
            return self._stop("COMPLETE_FROZEN_PRODUCTION_CONTEXT_BINDING_REQUIRED", state, events)
        if any(self.models.get(role) != model for role, model in MODEL_ROLE_POLICY.items()):
            return self._stop("MODEL_ROLE_ASSIGNMENT_DIFFERS_FROM_FROZEN_POLICY", state, events)
        if state.get("coordinator_status") in ("running", "completed"):
            return self._stop("EXISTING_EXECUTION_RECONCILE_OR_REUSE_SAVED_HANDOFF", state, events)
        terminal = state.get("coordinator_terminal")
        resumed_feedback = None
        if terminal:
            if terminal["reason"] != "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED" or not loop.candidate_capacity(state)["remaining"]:
                return self._stop(terminal["reason"], state, terminal["events"], terminal.get("failure_route"))
            # An explicit extra-candidate grant can reopen a known bounded stop.
            # Full evidence stays in history. Its request/receipt/event graph
            # is deliberately absent from the next model prompt.
            stop_summary, resumed_feedback = self._terminal_prompt_context(terminal, state)
            diagnostics.append(stop_summary)
            if resumed_feedback is not None:
                diagnostics.append(resumed_feedback)
            state["coordinator_terminal_history"] = state.get("coordinator_terminal_history", []) + [deepcopy(terminal)]
            state.pop("coordinator_terminal", None)
        pending_stage_claims = set()
        for event in state.get("stage_dispatch_events", []):
            if event.get("event") == "claim":
                pending_stage_claims.add(event["dispatch_identity"])
            elif event.get("event") == "result":
                pending_stage_claims.discard(event["dispatch_identity"])
        if pending_stage_claims:
            events.append({"stage": "unresolved_dispatch_claims", "dispatch_identities": sorted(pending_stage_claims),
                "query_original_identity_only": True})
            return self._stop("ORIGINAL_STAGE_DISPATCH_UNRESOLVED", state, events)
        failures = [event["result"] for event in state["director_events"] if
            event.get("result", {}).get("known_complete") and
            event["result"].get("status") == "contract_rejected"]
        if failures and resumed_feedback is None:
            # All original events/spend remain in state. The model receives the
            # last complete failure only, avoiding duplicate full old drafts.
            diagnostics.append(pipeline.known_failure_diagnostic(failures[-1], script))
        while True:
            capacity = loop.candidate_capacity(state)
            if capacity["unresolved_claims"] or capacity.get("unresolved_result_ids"):
                return self._stop("ORIGINAL_DIRECTOR_RESULT_UNRESOLVED", state, events)
            if not capacity["remaining"]:
                return self._stop("INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED", state, events)
            inputs = pipeline.build_director_input(script, manifest, initial, reference_fulltext, preferences, diagnostics)
            inputs["brief"] = deepcopy(brief)
            inputs["production_context_binding"] = {"production_context_sha256": context_identity,
                "binding_kind": "external_frozen_input_identity", "prior_semantic_review_claim": False}
            request = pipeline.build_request("whole_direction", inputs,
                pipeline.whole_direction_schema(script, manifest), self.models["writer"])
            request, director_visual_proof = self._enrich_director(request)
            preflight = self._preflight(request)
            identity = source.digest(request)
            state = loop.claim_director_request(state, identity)
            self._active_state = state
            state["coordinator_status"] = "running"
            self.persist_state(deepcopy(state))  # must be durable before invoke
            label = "whole_direction_v4_" + str(capacity["attempts_including_claims"])
            validate = lambda native: pipeline.compile_direction(native, script, manifest)
            receipt, evidence = self._call(label, request, validate, state, preflight)
            state = loop.register_director_result(state, evidence, identity)
            self._active_state = state
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
                diagnostics = self._latest_revision_diagnostics(diagnostics, route["revision_input"])
                continue
            if evidence["status"] != "contract_valid":
                return self._stop("DIRECTOR_RUNTIME_ACCEPTANCE_MISMATCH", state, events)
            performances, prefix, current_state = [], [], deepcopy(initial)
            director_route = None
            for segment in direction["segments"]:
                perf_input = pipeline.build_performance_input(script, manifest, segment, current_state, prefix,
                    reference_fulltext, preferences)
                perf_input["director_visual_binding"] = self._visual_cache_binding(director_visual_proof)
                perf_input["production_context_sha256"] = context_identity
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
                        local_label = "performance_v4_d" + str(capacity["attempts_including_claims"]) + "_" + segment["segment_id"] + "_r" + str(revision)
                        local_receipt, local_evidence = self._call(local_label, actual_request, validate_local, state)
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
                diagnostics = self._latest_revision_diagnostics(diagnostics, director_route["revision_input"])
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
                "whole_direction_native": deepcopy(native),
                "whole_direction_original_service_identity": {key: deepcopy(evidence[key]) for key in
                    ("result_id", "request_sha256", "native_sha256", "receipt_sha256", "reported_tokens")},
                "director_actual_request_sha256": source.digest(request),
                "director_visual_request_proof": deepcopy(director_visual_proof),
                "director_original_text_input": deepcopy(evidence["actual_input"]),
                "director_raw_visual_payload_not_copied_to_text_review": True,
                "all_planned_video_prompts": prompts, "opening_actual_video_prompt": opening_prompt,
                "opening_shared_projection": opening_context, "opening_actual_provider_request": actual_preview["request"],
                "opening_actual_request_proof": actual_preview["proof"], "reference_fulltext": reference_fulltext,
                "source_full_review_binding": deepcopy(source_review_binding), "scope": deepcopy(scope),
                "voice_binding": "unbound", "pixel_identity_verified": False}
            review_schema = schemas.review_schema(schemas.PRODUCTION_CHECKS, list(source.catalog(script)))
            review_request = pipeline.build_request("whole_production_review", review_input, review_schema, self.models["director"])
            def validate_review(value):
                return schemas.validate_review(value, review_schema)
            review_receipt, review_evidence = self._call("whole_production_review_v4_d" + str(capacity["attempts_including_claims"]),
                review_request, validate_review, state)
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
                diagnostics = self._latest_revision_diagnostics(diagnostics, route["revision_input"])
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
                "whole_direction_native": deepcopy(native),
                "whole_direction_original_service_identity": deepcopy(review_input["whole_direction_original_service_identity"]),
                "director_visual_request_proof": deepcopy(director_visual_proof),
                "director_original_request": deepcopy(request),
                "complete_compilation": complete, "planned_prompts": prompts, "opening_actual_preview": actual_preview,
                "opening_shared_context": opening_context, "opening_actual_prompt": opening_prompt,
                "reviewed_request_identity_proof": reviewed_request_proof,
                "production_review_ordinal": review_receipt["ordinal"], "review_limitations": review_evidence["native_document"]["review_limitations"],
                "complete_text_handoff_ready": True, "media_dispatch_allowed": False,
                "actual_media_quality_passed": False, "human_creative_quality_passed": False,
                "budget_reset": False, "automatic_retry": False}
