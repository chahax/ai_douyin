"""Continue a reconciled, complete missing-tool plan without a clean restart.

The dispatcher, additive freeze and ledger stay caller-owned. Raw plain content
is a format-revision input only; this module never adopts it as a tool result.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from . import creative_fresh_legal_text_pipeline_v1 as prior
from .creative_workflow_roles import _response_model_matches

VERSION = "creative_known_plan_continuation/v1"
_SHA = re.compile(r"[0-9a-f]{64}")
digest = prior.digest


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _object_bytes(raw):
    _require(type(raw) is bytes, "original bytes required")
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate original field")
            value[key] = item
        return value
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite original field")))
    _require(type(value) is dict, "original JSON object required")
    return value


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def compile_missing_tool_seed(receipt, *, receipt_bytes, evidence_directory,
                              expected_receipt_sha256, expected_source_binding_sha256,
                              expected_wire, verifier=None):
    """Validate both original SDK bodies, then derive a separate raw-text seed."""
    _require(_sha(expected_receipt_sha256) and _sha(expected_source_binding_sha256), "independent receipt/source SHA required")
    _require(hashlib.sha256(receipt_bytes).hexdigest() == expected_receipt_sha256
        and _object_bytes(receipt_bytes) == receipt, "original receipt bytes changed")
    request = receipt.get("request")
    _require(type(request) is dict and receipt.get("request_sha256") == digest(request), "original request changed")
    _require(receipt.get("source_binding_sha256") == expected_source_binding_sha256
        and request.get("input_provenance", {}).get("source_binding_sha256") == expected_source_binding_sha256,
        "original source binding changed")
    _require(prior._known_complete(receipt, request, expected_source_binding_sha256), "unknown, incomplete or truncated original result")
    failure, meta = receipt.get("failure", {}), receipt["response_metadata"]
    _require(receipt.get("status") == "interface_rejected" and "output" not in receipt and "document_output" not in receipt,
        "only original unadopted interface rejection is eligible")
    _require(failure.get("code") == "REQUIRED_TOOL_MISSING" and failure.get("category") == "interface"
        and failure.get("response_received") is True and failure.get("provider_outcome_known") is True
        and failure.get("cause_code", "REQUIRED_TOOL_MISSING") == "REQUIRED_TOOL_MISSING"
        and meta.get("response_fault_code") == "REQUIRED_TOOL_MISSING" and meta.get("finish_reason") == "stop",
        "only complete known missing-tool content is eligible")
    role, model = request.get("role"), request.get("model")
    _require(role in prior.MODEL_POLICY and model == prior.MODEL_POLICY[role]
        and meta.get("role") == role and meta.get("requested_model") == model
        and meta.get("provider") == ("minimax" if role == "writer" else "deepseek"),
        "original role/model/provider changed")
    directory = Path(evidence_directory).resolve()
    identity = _object_bytes((directory / "IDENTITY.json").read_bytes())
    actual_identity = {"ordinal": receipt["ordinal"], "label": receipt["label"],
        "request_sha256": receipt["request_sha256"], "source_binding_sha256": expected_source_binding_sha256,
        "role": request["role"], "model": request["model"]}
    identity_sha = digest(actual_identity)
    _require(identity.get("identity") == actual_identity and identity.get("identity_sha256") == identity_sha
        and receipt.get("call_evidence", {}).get("identity_sha256") == identity_sha, "original call identity changed")
    bodies = {}
    for prefix in ("REQUEST", "RESPONSE"):
        manifest = _object_bytes((directory / (prefix + "_BODY_MANIFEST.json")).read_bytes())
        name = prefix.lower() + "_body.raw"
        _require(manifest.get("body_file") == name, "original body filename changed")
        raw = (directory / name).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        _require(manifest.get("identity_sha256") == identity_sha and manifest.get("body_complete") is True
            and manifest.get("raw_bytes_preserved") is True and manifest.get("credential_redacted") is False
            and type(manifest.get("bytes")) is int and manifest["bytes"] == len(raw)
            and manifest.get("original_sha256") == manifest.get("stored_sha256") == sha,
            "original " + prefix.lower() + " body/manifest changed")
        bodies[prefix] = (manifest, _object_bytes(raw), sha)
    request_manifest, wire, request_body_sha = bodies["REQUEST"]
    _require(type(expected_wire) is dict and wire == expected_wire, "actual SDK request differs from expected wire")
    response_manifest, body, body_sha = bodies["RESPONSE"]
    _require(body_sha == meta.get("raw_body_sha256") and body == receipt.get("response_payload")
        and type(response_manifest.get("http_metadata", {}).get("http_status_code")) is int
        and response_manifest["http_metadata"]["http_status_code"] == meta["http_status_code"],
        "original raw response differs from receipt")
    _require(type(body.get("usage", {}).get("total_tokens")) is int
        and body["usage"]["total_tokens"] == meta["total_tokens"], "original usage changed")
    base = body.get("base_resp")
    if role == "writer" or base is not None:
        _require(type(base) is dict and type(base.get("status_code")) is int and base["status_code"] == 0
            and type(meta.get("provider_status_code")) is int and meta["provider_status_code"] == 0,
            "original provider outcome changed")
    else:
        _require("provider_status_code" not in meta, "absent provider status contradicts metadata")
    _require(type(body.get("model")) is str and meta.get("response_model") == body["model"]
        and _response_model_matches(role, model, body["model"]), "original response model changed")
    choices = body.get("choices")
    _require(type(choices) is list and len(choices) == 1 and type(choices[0]) is dict
        and choices[0].get("finish_reason") == "stop", "unique complete original choice required")
    message = choices[0].get("message")
    _require(type(message) is dict and message.get("tool_calls") in (None, [])
        and message.get("function_call") is None, "unexpected or ambiguous original tool output")
    text = message.get("content")
    _require(type(text) is str and bool(text.strip()), "nonempty original plain content required")
    _require(receipt.get("response_text") in (None, text), "receipt plain-text projection contradicts raw body")
    if verifier is not None:
        _require(callable(verifier), "runtime verifier must be callable")
        _require(verifier(deepcopy(receipt), deepcopy(request)) is not False, "runtime original evidence verification failed")
    seed = {"schema": VERSION + "/format_seed", "source_binding_sha256": expected_source_binding_sha256,
        "original_ordinal": receipt["ordinal"], "original_label": receipt["label"],
        "original_request_sha256": receipt["request_sha256"], "original_receipt_sha256": expected_receipt_sha256,
        "original_receipt_document_sha256": digest(receipt), "original_identity_sha256": identity_sha,
        "original_request_body_sha256": request_body_sha, "original_response_body_sha256": body_sha,
        "original_reported_tokens": meta["total_tokens"], "original_response_text": text,
        "original_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "original_status_retained": "interface_rejected", "plain_content_adopted_as_tool": False,
        "maximum_new_format_requests": 1, "automatic_transport_retry": False, "budget_reset": False}
    seed["seed_sha256"] = digest(seed)
    return seed


def validate_missing_tool_seed(seed, receipt, source_binding_sha256):
    _require(type(seed) is dict and seed.get("schema") == VERSION + "/format_seed", "verified format seed required")
    value = deepcopy(seed)
    sha = value.pop("seed_sha256", None)
    _require(_sha(sha) and sha == digest(value), "format seed changed")
    _require(seed.get("source_binding_sha256") == source_binding_sha256
        and seed.get("original_ordinal") == receipt.get("ordinal") and seed.get("original_label") == receipt.get("label")
        and seed.get("original_request_sha256") == receipt.get("request_sha256")
        and seed.get("original_receipt_document_sha256") == digest(receipt)
        and seed.get("original_identity_sha256") == receipt.get("call_evidence", {}).get("identity_sha256")
        and seed.get("original_response_body_sha256") == receipt.get("response_metadata", {}).get("raw_body_sha256"),
        "format seed does not bind the original receipt")
    _require(prior._known_complete(receipt, receipt["request"], source_binding_sha256)
        and receipt.get("failure", {}).get("code") == "REQUIRED_TOOL_MISSING", "original result no longer eligible")
    content = receipt["response_payload"]["choices"][0]["message"]["content"]
    _require(type(content) is str and content.strip() and seed.get("original_response_text") == content
        and seed.get("original_text_sha256") == hashlib.sha256(content.encode("utf-8")).hexdigest()
        and seed.get("original_reported_tokens") == receipt["response_metadata"]["total_tokens"]
        and seed.get("plain_content_adopted_as_tool") is False and seed.get("maximum_new_format_requests") == 1
        and seed.get("automatic_transport_retry") is False and seed.get("budget_reset") is False,
        "format seed content or permission changed")
    return {"format_seed_valid": True, "seed_sha256": sha}


class KnownPlanContinuation(prior.FreshLegalTextPipeline):
    def __init__(self, *, invoke, persist_state, payload_projector, operator_binding,
                 format_recovery_authorization, resume_guard=None, format_seed_factory=None):
        super().__init__(invoke=invoke, persist_state=persist_state,
            format_recovery_authorization=format_recovery_authorization)
        _require(callable(payload_projector), "pure compact payload projector required")
        _require(type(operator_binding) is dict and _sha(operator_binding.get("operator_freeze_sha256"))
            and _sha(operator_binding.get("projection_sha256")), "additive operator freeze/projection SHA required")
        self.payload_projector = payload_projector
        self.operator_binding = deepcopy(operator_binding)
        self.resume_guard = resume_guard
        self.format_seed_factory = format_seed_factory

    def _project(self, payload):
        before = deepcopy(payload)
        after = self.payload_projector(deepcopy(payload))
        _require(type(after) is dict and set(after) == set(before), "projection changed payload field set")
        _require({k: v for k, v in after.items() if k != "source_packet"}
            == {k: v for k, v in before.items() if k != "source_packet"},
            "projection changed native creative documents or complete reference/context")
        return after

    def _request(self, phase, rule, payload, schema, cap):
        projected = self._project(payload)
        request = super()._request(phase, rule, projected, schema, cap)
        request["input_provenance"].update(additive_operator_scope=deepcopy(self.operator_binding),
            continuation_operator_version=VERSION, projected_payload_sha256=digest(projected))
        return request

    def _call_once(self, phase, label, request, validator):
        if self.resume_guard is not None:
            try:
                self.resume_guard()
            except Exception as exc:
                self._save("halt_additive_preflight_failed", failure={"type": type(exc).__name__, "redispatch_allowed": False})
                return None
        return super()._call_once(phase, label, request, validator)

    def _recover(self, phase, label, request, validator, receipt, seed):
        validate_missing_tool_seed(seed, receipt, self.state["source_binding_sha256"])
        auth = self.format_authorization
        _require(type(auth) is dict and auth.get("authorized") is True
            and auth.get("source_binding_sha256") == self.state["source_binding_sha256"]
            and type(auth.get("evidence_ref")) is str and bool(auth["evidence_ref"])
            and _sha(auth.get("evidence_sha256")), "current source format authorization required")
        _require(phase not in self.state["format_recovery_claims"], "phase format recovery already consumed")
        recovery = deepcopy(request)
        payload = _object_bytes(recovery["messages"][1]["content"].encode("utf-8"))
        provenance = recovery["input_provenance"]
        if provenance.get("continuation_operator_version") == VERSION:
            _require(provenance.get("additive_operator_scope") == self.operator_binding
                and provenance.get("projected_payload_sha256") == digest(payload), "projected request changed")
            projected = payload
        else:
            projected = self._project(payload)
        recovery["messages"][1]["content"] = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        recovery["input_provenance"].update(additive_operator_scope=deepcopy(self.operator_binding),
            continuation_operator_version=VERSION, projected_payload_sha256=digest(projected),
            single_format_recovery_of=receipt["ordinal"], verified_format_seed_sha256=seed["seed_sha256"])
        recovery["messages"].append({"role": "user", "content": json.dumps({
            "format_recovery_original_response": seed["original_response_text"],
            "original_request_sha256": receipt["request_sha256"], "original_ordinal": receipt["ordinal"],
            "requirement": "完整原生结果已返回但未用指定工具提交。重新提交本阶段全部完整合同；不返回补丁，不称原结果已验收。"}, ensure_ascii=False)})
        self.state["format_recovery_claims"][phase] = {"original_ordinal": receipt["ordinal"],
            "original_receipt_sha256": digest(receipt), "request_sha256": digest(recovery),
            "verified_format_seed_sha256": seed["seed_sha256"], "authorization": deepcopy(auth)}
        self._save("format_recovery_claimed")
        result = self._call_once(phase, label + "_format_recovery", recovery, validator)
        if result is None:
            return None
        if result.get("status") != "contract_valid":
            self._save("halt_format_recovery_failed", original_ordinal=result["ordinal"], redispatch_allowed=False)
            return None
        return result

    def _call(self, phase, label, request, validator):
        result = self._call_once(phase, label, request, validator)
        if result is None or result.get("failure", {}).get("code") != "REQUIRED_TOOL_MISSING":
            return result
        if phase in self.state["format_recovery_claims"] or self.format_seed_factory is None:
            self._save("halt_required_tool_missing", original_ordinal=result["ordinal"], redispatch_allowed=False)
            return None
        try:
            seed = self.format_seed_factory(deepcopy(result))
            return self._recover(phase, label, request, validator, result, seed)
        except Exception as exc:
            self._save("halt_format_seed_invalid", original_ordinal=result["ordinal"],
                failure={"type": type(exc).__name__, "redispatch_allowed": False})
            return None

    def run_from_known_plan(self, *, resume_state, format_seed, packet, legal_context,
                            reference_fulltext, expression_standards, production_preferences,
                            provider_evidence, source_binding_sha256, now=None):
        _require(not self._used, "one continuation object cannot execute twice")
        self._used = True
        _require(_sha(source_binding_sha256), "exact frozen source binding SHA required")
        current = now or datetime.now(timezone.utc).isoformat()
        if packet.get("schema") == prior.graph_bridge.VERSION:
            prior.graph_bridge.validate_packet(packet, now=current)
        else:
            _require(not prior.trend_bridge.validate_packet(packet, now=current)["blockers"], "frozen source packet blocked")
        _require(packet["inputs"]["source"]["account_profile"]["domain_strategy_id"] == "legal_services",
            "same legal account source required")
        _require(legal_context.get("schema") == "verified_legal_story_context/v1" and legal_context.get("sources")
            and legal_context.get("facts") and legal_context.get("creative_boundaries"), "verified legal context required")
        state = deepcopy(resume_state)
        _require(state.get("status") == "halt_required_tool_missing" and state.get("source_binding_sha256") == source_binding_sha256,
            "exact known missing-tool stop required")
        _require(state.get("limits") == self.limits and type(state.get("versions")) is dict
            and all(type(state["versions"].get(k)) is int and 0 <= state["versions"][k] <= self.limits[k] for k in self.limits)
            and state["versions"]["theme"] >= 1 and state["versions"]["plan"] >= 1 and state["versions"]["draft"] == 0,
            "original native counters/limits changed")
        _require(type(state.get("format_recovery_claims")) is dict and "plan" not in state["format_recovery_claims"],
            "original plan format recovery consumed")
        receipts = state.get("receipts")
        _require(type(receipts) is list and receipts, "all original receipts required")
        _require(len({r["ordinal"] for r in receipts}) == len(receipts)
            and len({r["label"] for r in receipts}) == len(receipts)
            and [r["ordinal"] for r in receipts] == list(range(receipts[0]["ordinal"], receipts[0]["ordinal"] + len(receipts)))
            and all(prior._known_complete(r, r["request"], source_binding_sha256) for r in receipts),
            "original receipt prefix unknown, duplicated or changed")
        original = receipts[-1]
        _require(original["request"]["input_provenance"]["phase"] == "plan"
            and state.get("original_ordinal") == original["ordinal"], "wrong stopped phase or ordinal")
        validate_missing_tool_seed(format_seed, original, source_binding_sha256)
        result_events = [e for e in state.get("events", []) if e.get("event") == "result"]
        _require([e.get("receipt_ordinal") for e in result_events] == [r["ordinal"] for r in receipts]
            and all(e.get("receipt_sha256") == digest(r) for e, r in zip(result_events, receipts)),
            "original result event prefix changed")
        claims = [e for e in state["events"] if e.get("event") == "claim"]
        _require(len(claims) == len(receipts) and all(e.get("label") == r["label"]
            and e.get("request_sha256") == r["request_sha256"] for e, r in zip(claims, receipts)),
            "unresolved or changed original claim exists")
        _require(original["label"] == f"fresh_plan_{state['versions']['plan']:02}"
            and len([r for r in receipts if re.fullmatch(r"fresh_theme_[0-9]{2}", r["label"])]) == state["versions"]["theme"]
            and len([r for r in receipts if re.fullmatch(r"fresh_plan_[0-9]{2}", r["label"])]) == state["versions"]["plan"],
            "original native version history differs")
        theme, brief = state["native_theme"], state["brief"]
        accepted_themes = [r for r in receipts if r["status"] == "contract_valid" and r["request"]["input_provenance"]["phase"] == "theme"]
        _require(accepted_themes and accepted_themes[-1].get("document_output", accepted_themes[-1].get("output")) == theme,
            "accepted native theme changed")
        prior.validate_theme(theme, packet, production_preferences.get("max_characters", 4))
        _require(prior.compile_brief(theme, packet, legal_context, production_preferences, source_binding_sha256) == brief,
            "frozen brief or source context changed")
        _require(reference_fulltext == packet["inputs"]["reference_fulltext"]
            and reference_fulltext and expression_standards == packet["inputs"]["expression_standards"]
            and expression_standards.get("criteria"), "complete actual reference/standards changed")
        _require(type(production_preferences.get("max_characters", 4)) is int
            and 1 <= production_preferences.get("max_characters", 4) <= 4, "max closed on-screen actors must be 1..4")
        prior.validate_provider_evidence(provider_evidence)
        self.reference, self.receipts, self.state = deepcopy(reference_fulltext), deepcopy(receipts), state
        self._original_receipt_count = len(receipts)
        self.state["continuation"] = {"operator_version": VERSION, "operator_binding": deepcopy(self.operator_binding),
            "original_stop_state_sha256": digest(resume_state), "original_receipt_prefix_sha256": digest(receipts),
            "original_native_versions": deepcopy(state["versions"]), "original_format_seed_sha256": format_seed["seed_sha256"],
            "old_budget_reset": False}
        context = {"source_packet": deepcopy(packet), "verified_legal_context": deepcopy(legal_context),
            "reference_fulltext": self.reference, "expression_standards": deepcopy(expression_standards),
            "production_preferences": deepcopy(production_preferences), "automatic_creative_choice_not_user_approval": True}
        plan_validator = lambda value: prior.contract.validate_plan(value, brief)
        recovered = self._recover("plan", original["label"], original["request"], plan_validator, original, format_seed)
        native_plan = self._output(recovered, plan_validator)
        if native_plan is None:
            return self._finish_state()
        plan = prior.contract.compile_plan(native_plan, brief)
        self.state.update(native_plan=native_plan, compiled_plan=plan)
        self._save("plan_ready")
        return self._after_theme(context, theme, brief, plan, legal_context, reference_fulltext,
            production_preferences, provider_evidence)

    def _finish_state(self):
        count = getattr(self, "_original_receipt_count", len(self.receipts))
        self.state["continuation_new_model_calls"] = len(self.receipts) - count
        self.state["continuation_known_reported_tokens"] = sum(r["response_metadata"]["total_tokens"]
            for r in self.receipts[count:] if type(r.get("response_metadata", {}).get("total_tokens")) is int
            and r["response_metadata"]["total_tokens"] >= 0)
        return super()._finish_state()

    def _after_theme(self, context, theme, brief, plan, legal_context, reference_fulltext,
                     production_preferences, provider_evidence):
        previous_plan, plan_targets, previous_script, script_targets = None, None, None, None
        while self.state["versions"]["draft"] < self.limits["draft"]:
            if plan is None:
                def builder(previous, targets):
                    payload = {**deepcopy(context), "brief": deepcopy(brief)}
                    payload.update(previous_complete_document=previous if previous is not None else previous_plan,
                        revision_requirements=targets if targets is not None else plan_targets)
                    return self._request("plan", prior.PLAN_RULE, payload, prior.contract.build_plan_schema(brief), 7000)
                native_plan, _ = self._native_loop("plan", builder, lambda value: prior.contract.validate_plan(value, brief))
                if native_plan is None:
                    return self._finish_state()
                plan = prior.contract.compile_plan(native_plan, brief)
                self.state.update(native_plan=native_plan, compiled_plan=plan)
                self._save("plan_ready")
            self.state["versions"]["draft"] += 1
            version = self.state["versions"]["draft"]
            payload = {**deepcopy(context), "brief": deepcopy(brief), "creative_scene_plan": deepcopy(plan)}
            if previous_script is not None:
                payload.update(previous_complete_document=deepcopy(previous_script), revision_requirements=deepcopy(script_targets))
            validator = lambda value: prior.validate_script(value, brief)
            receipt = self._call("draft", f"fresh_draft_{version:02}",
                self._request("draft", prior.AUTHOR_RULE, payload, prior.contract.build_script_schema(brief), 6500), validator)
            native = self._output(receipt, validator)
            if native is None:
                if receipt is None or self.state["status"].startswith("halt_"):
                    return self._finish_state()
                if self._complete_rejection(receipt):
                    previous_script = deepcopy(receipt.get("document_output", receipt.get("output")))
                    script_targets = [{"target": "script", "failure": deepcopy(receipt["failure"]),
                        "validation_error": deepcopy(receipt.get("validation_error"))}]
                    self._save("automatic_complete_draft_revision", revision_requirements=script_targets)
                    continue
                self._save("halt_" + str(receipt.get("status")), original_ordinal=receipt.get("ordinal"))
                return self._finish_state()
            script = prior.contract.compile_script(native, brief)
            self.state.update(native_script=native, script=script)
            self._save("draft_ready_waiting_full_review")
            payload = {**deepcopy(context), "brief": deepcopy(brief), "full_scene_plan": deepcopy(plan),
                "full_current_script": deepcopy(script), "evidence_catalog": prior.contract.evidence_catalog(script),
                "legal_fact_catalog": prior.legal_catalog(legal_context), "quality_criteria": deepcopy(prior.CRITERIA)}
            validator = lambda value: prior.validate_review(value, script, brief, plan, legal_context)
            review_receipt = self._call("review", f"fresh_full_review_{version:02}",
                self._request("review", prior.REVIEW_RULE, payload, prior.review_schema(script, brief, plan, legal_context), 12000), validator)
            review = self._output(review_receipt, validator)
            if review is None:
                if review_receipt is not None and not self.state["status"].startswith("halt_"):
                    self._save("halt_review_contract_rejected", original_ordinal=review_receipt.get("ordinal"), redispatch_allowed=False)
                return self._finish_state()
            decision = prior.decide_review(review, script, brief, plan, legal_context)
            self.state.update(full_review=review, automatic_decision=decision)
            self._save("full_review_passed_building_handoff" if decision["status"] == "text_ready_for_director" else decision["status"])
            if decision["status"].startswith("halt_"):
                return self._finish_state()
            if decision["status"] == "text_ready_for_director":
                package = prior.build_production_package(theme, brief, script, provider_evidence)
                binding = {"writer_ordinal": receipt["ordinal"], "review_ordinal": review_receipt["ordinal"],
                    "writer_receipt_sha256": digest(receipt), "review_receipt_sha256": digest(review_receipt),
                    "script_sha256": digest(script), "machine_text_review_passed": True,
                    "production_context_sha256": prior.coordinator.production_context_digest(brief, reference_fulltext, production_preferences),
                    "human_quality_approved": False, "review_kind": VERSION + "/integrated_full_review"}
                self.state.update(status="text_ready_for_director", source_review_binding=binding,
                    manifest=package["shared_manifest"], initial=package["planned_initial_state"],
                    shared_dynamic_initial=package["shared_dynamic_initial"], production_package=package,
                    sourcepackage={"brief": brief, "casting": {r["id"]: r["profile"] for r in theme["characters"]},
                        "scene_appearance": {r["id"]: r["appearance"] for r in theme["scenes"]},
                        "prop_appearance": {r["id"]: r["appearance"] for r in theme["initial_state"]["prop_states"]},
                        "reference_fulltext": reference_fulltext, "production_preferences": deepcopy(production_preferences)})
                return self._finish_state()
            previous_script, script_targets = deepcopy(script), deepcopy(decision["revision_requirements"])
            if any(r["target"] == "plan" for r in script_targets):
                previous_plan = deepcopy(self.state["native_plan"])
                plan_targets = [deepcopy(r) for r in script_targets if r["target"] == "plan"]
                plan = None
            self._save("automatic_complete_draft_revision", revision_requirements=script_targets)
        self._save("creative_stalled", version_limit_exhausted=True)
        return self._finish_state()
