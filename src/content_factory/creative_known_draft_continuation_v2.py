"""One unsubmitted native draft slot after a proven local duplicate rejection.

The caller verifies the frozen SQL/SDK/ledger proof on every dispatch. This
module retains the stopped history and never treats transport uncertainty as
an unused slot. Model prose is returned in full and is never split or patched.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re

from jsonschema import Draft202012Validator

from . import creative_known_plan_continuation_v1 as prior

fresh = prior.prior
VERSION = "creative_known_draft_continuation/v2"
digest = prior.digest
MAX_SEGMENT_SECONDS = 15
RECEIVER_RESERVE_SECONDS = .3
SPEAKING_RATE = fresh.source.NORMAL_SPOKEN_CHARACTERS_PER_SECOND
MAX_SPOKEN_CHARACTERS = math.floor((MAX_SEGMENT_SECONDS - RECEIVER_RESERVE_SECONDS) * SPEAKING_RATE)
_SPOKEN_CLASS = r"\u4e00-\u9fffA-Za-z0-9"
DIALOGUE_PATTERN = rf"^(?:[^{_SPOKEN_CLASS}]*[{_SPOKEN_CLASS}]){{0,{MAX_SPOKEN_CHARACTERS}}}[^{_SPOKEN_CLASS}]*$"
AUTHOR_RULE = fresh.AUTHOR_RULE + (
    "本请求是已证实未派发的第三份完整稿槽，原计划和简报不改。工具Schema将原15秒下界公开："
    "只对白按原估算函数统计汉字、英文字母和数字，标点不计；3.3字/秒加0.3秒最低接收保留，最多48发音字符。"
    "读取dialogue_window_diagnostics全部失败原句与来源位置，自然重构本稿言语行动；不机械定句数、不靠加速，"
    "动作不套该字数限制。导演仍安排机位、切镜和镜段组合，局部表演安排并行动作和反应。"
    "提交完整原生新稿，不复制原失败全文，不拆补旧正文。"
)


class ScriptDialogueWindowError(ValueError):
    def __init__(self, detail):
        self.code = "SCRIPT_DIALOGUE_WINDOW_EXCEEDED"
        self.detail = deepcopy(detail)
        super().__init__(self.code)


class KnownLocalDispatchError(ValueError):
    """Caller-owned proof that a specific claim failed before dispatch.

    Construct only after checking the SQL transaction and runtime ledger. An
    ordinary TaskStoreError, including an error after dispatch, stays unknown.
    """
    def __init__(self, *, request_sha256, evidence_sha256, detail):
        prior._require(prior._sha(request_sha256) and prior._sha(evidence_sha256)
            and type(detail) is dict and detail.get("code") == "DUPLICATE_DISPATCH"
            and type(detail.get("sql_attempt_count")) is int and detail["sql_attempt_count"] == 0
            and detail.get("provider_dispatch_started") is False and detail.get("runtime_boundary_verified") is True
            and type(detail.get("graph_id")) is str and bool(detail["graph_id"]),
            "specific known-local predispatch proof required")
        self.code, self.detail = "DUPLICATE_DISPATCH", deepcopy(detail)
        self.request_sha256, self.evidence_sha256 = request_sha256, evidence_sha256
        super().__init__(self.code)


def build_script_schema(brief):
    schema = deepcopy(fresh.contract.build_script_schema(brief))
    step = schema["properties"]["beats"]["items"]["properties"]["steps"]["items"]
    step.setdefault("allOf", []).append({
        "if": {"properties": {"kind": {"const": "dialogue"}}, "required": ["kind"]},
        "then": {"properties": {"text": {"pattern": DIALOGUE_PATTERN,
            "description": "原下界：仅汉字/英文字母/数字计发音字符，最多48；标点不计，action不适用。"}}},
    })
    return schema


def dialogue_window_diagnostics(raw, brief):
    script = fresh.contract.compile_script(raw, brief)
    violations = []
    for ref, row in fresh.source.catalog(script).items():
        count, speech = fresh.source.spoken_characters(row), fresh.source.spoken_seconds(row)
        if row["kind"] == "dialogue" and speech + RECEIVER_RESERVE_SECONDS > MAX_SEGMENT_SECONDS:
            violations.append({"source_ref": ref, "field_path": row["path"] + ".text",
                "text": row["text"], "speaker_id": row["speaker"], "spoken_character_count": count,
                "speaking_rate": SPEAKING_RATE, "estimated_speech_seconds": speech,
                "receiver_reserve_seconds": RECEIVER_RESERVE_SECONDS,
                "estimated_minimum_seconds": speech + RECEIVER_RESERVE_SECONDS,
                "max_segment_seconds": MAX_SEGMENT_SECONDS, "maximum_spoken_characters": MAX_SPOKEN_CHARACTERS,
                "required_revision": "生成完整原生新稿，自然重构该言语单元；保持冻结事实与行事功能，不提速、不手改旧稿。"})
    return {"schema": VERSION + "/dialogue_window_diagnostics", "script_sha256": digest(script),
        "brief_sha256": digest(brief), "estimated_not_measured": True,
        "speaking_rate": SPEAKING_RATE, "receiver_reserve_seconds": RECEIVER_RESERVE_SECONDS,
        "max_segment_seconds": MAX_SEGMENT_SECONDS, "maximum_spoken_characters": MAX_SPOKEN_CHARACTERS,
        "violations": violations}


def validate_script(raw, brief):
    script = fresh.contract.compile_script(raw, brief)
    entries = fresh.source.catalog(script)
    if {r["speaker"] for r in entries.values() if r["kind"] == "dialogue"} != set(brief["constraints"]["allowed_character_ids"]):
        raise ValueError("full script must cover exact declared on-screen dialogue cast")
    diagnostics = dialogue_window_diagnostics(raw, brief)
    if diagnostics["violations"]:
        raise ScriptDialogueWindowError(diagnostics)
    Draft202012Validator(build_script_schema(brief)).validate(raw)
    return {"complete_native_script": True, "script_sha256": digest(script),
        "dialogue_window_diagnostics": diagnostics, "creative_quality_passed": False}


def validate_local_failure_proof(proof, stop_state, result527, source_binding_sha256):
    require = prior._require
    require(type(proof) is dict and proof.get("schema") == "known_local_draft_failure_proof/v1",
        "frozen known-local failure proof required")
    require(proof.get("code") == "DUPLICATE_DISPATCH" and proof.get("provider_dispatch_started") is False
        and proof.get("runtime_boundary_verified") is True and proof.get("graph_status") == "prepared"
        and type(proof.get("sql_attempt_count")) is int and proof["sql_attempt_count"] == 0,
        "only proven duplicate rejection before provider dispatch is eligible")
    require(proof.get("source_binding_sha256") == source_binding_sha256
        and proof.get("stop_state_sha256") == digest(stop_state)
        and proof.get("result527_sha256") == digest(result527)
        and prior._sha(proof.get("ledger_sha256")) and prior._sha(proof.get("taskstore_evidence_sha256")),
        "local failure proof binding changed")
    receipts = stop_state.get("receipts", [])
    require(proof.get("ledger_receipt_ordinals") == [r["ordinal"] for r in receipts]
        and len(receipts) == 7 and receipts[-1] == result527, "original seven-receipt ledger prefix changed")
    claims = [row for row in stop_state.get("events", []) if row.get("event") == "claim"]
    require(claims and claims[-1].get("label") == proof.get("failed_label") == "fresh_draft_03"
        and claims[-1].get("request_sha256") == proof.get("request_sha256") == digest(result527["request"]),
        "unsubmitted third draft request identity changed")
    require(type(proof.get("graph_id")) is str and bool(proof["graph_id"]), "known local graph identity required")
    return {"known_local_failure": True, "proof_sha256": digest(proof), "provider_dispatch_started": False}


class KnownDraftContinuation(prior.KnownPlanContinuation):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        prior._require(callable(self.resume_guard), "actual frozen local proof guard required")
        prior._require(prior._sha(self.operator_binding.get("local_failure_proof_sha256")),
            "additive operator must bind frozen local failure proof SHA")

    def _call_once(self, phase, label, request, validator):
        original_invoke = self.invoke
        known_local = []
        def captured(*args, **kwargs):
            try:
                return original_invoke(*args, **kwargs)
            except KnownLocalDispatchError as exc:
                if exc.request_sha256 == digest(request):
                    known_local.append(exc)
                raise
        self.invoke = captured
        try:
            result = super()._call_once(phase, label, request, validator)
        finally:
            self.invoke = original_invoke
        if known_local:
            exc = known_local[0]
            self._save("halt_known_local_before_dispatch", failed_label=label,
                failure={"type":type(exc).__name__,"code":exc.code,"detail":deepcopy(exc.detail),
                    "request_sha256":exc.request_sha256,"evidence_sha256":exc.evidence_sha256,
                    "provider_dispatch_started":False,"redispatch_allowed":False})
        return result

    def run_from_known_local_draft(self, *, stop_state, result527, local_failure_proof,
                                  packet, legal_context, reference_fulltext, expression_standards,
                                  production_preferences, provider_evidence, source_binding_sha256, now=None):
        require = prior._require
        require(not self._used, "one continuation object cannot execute twice")
        self._used = True
        require(prior._sha(source_binding_sha256), "exact frozen source binding SHA required")
        current = now or datetime.now(timezone.utc).isoformat()
        if packet.get("schema") == fresh.graph_bridge.VERSION:
            fresh.graph_bridge.validate_packet(packet, now=current)
        else:
            require(not fresh.trend_bridge.validate_packet(packet, now=current)["blockers"], "frozen source packet blocked")
        require(packet["inputs"]["source"]["account_profile"]["domain_strategy_id"] == "legal_services", "same legal source required")
        require(reference_fulltext and reference_fulltext == packet["inputs"]["reference_fulltext"]
            and expression_standards == packet["inputs"]["expression_standards"] and expression_standards.get("criteria"),
            "frozen full reference/standards changed")
        require(legal_context.get("schema") == "verified_legal_story_context/v1" and legal_context.get("sources")
            and legal_context.get("facts") and legal_context.get("creative_boundaries"), "verified legal context required")
        require(type(production_preferences.get("max_characters", 4)) is int
            and 1 <= production_preferences.get("max_characters", 4) <= 4, "closed actor capacity required")
        state = deepcopy(stop_state)
        require(state.get("status") == "halt_execution_unknown" and state.get("failure", {}).get("type") == "TaskStoreError"
            and state.get("source_binding_sha256") == source_binding_sha256 and state.get("limits") == self.limits
            and state.get("versions") == {"theme": 2, "plan": 2, "draft": 3}, "exact stopped third native slot required")
        validation = validate_local_failure_proof(local_failure_proof, state, result527, source_binding_sha256)
        require(self.operator_binding["local_failure_proof_sha256"] == validation["proof_sha256"], "operator/proof differs")
        receipts, events = state["receipts"], state["events"]
        require(all(fresh._known_complete(r, r["request"], source_binding_sha256) for r in receipts)
            and len({r["label"] for r in receipts}) == len(receipts)
            and [r["ordinal"] for r in receipts] == list(range(receipts[0]["ordinal"], receipts[0]["ordinal"] + len(receipts))),
            "original result/usage prefix unknown or duplicated")
        results, claims = [e for e in events if e.get("event") == "result"], [e for e in events if e.get("event") == "claim"]
        require(len(results) == len(receipts) and len(claims) == len(receipts) + 1
            and [e.get("receipt_ordinal") for e in results] == [r["ordinal"] for r in receipts]
            and all(e.get("receipt_sha256") == digest(r) for e, r in zip(results, receipts))
            and all(e.get("label") == r["label"] and e.get("request_sha256") == digest(r["request"])
                for e, r in zip(claims[:-1], receipts)), "only reconciled old final local claim may be pending")
        require(type(state.get("format_recovery_claims")) is dict and "plan" in state["format_recovery_claims"]
            and "draft" not in state["format_recovery_claims"], "original phase format allowance changed")
        require(result527.get("status") == "contract_rejected" and result527.get("failure", {}).get("category") in ("validation", "state_contract")
            and result527["request"]["input_provenance"]["phase"] == "draft"
            and result527.get("failure", {}).get("code") == "complete utterance cannot fit 15 seconds at normal speed",
            "last original draft must be a known complete dialogue-window rejection")
        native = result527.get("document_output", result527.get("output"))
        require(native == receipts[-2].get("document_output", receipts[-2].get("output")), "known unchanged full draft chain differs")
        theme, brief, plan = state["native_theme"], state["brief"], state["compiled_plan"]
        accepted_themes = [r for r in receipts if r["status"] == "contract_valid" and r["request"]["input_provenance"]["phase"] == "theme"]
        accepted_plans = [r for r in receipts if r["status"] == "contract_valid" and r["request"]["input_provenance"]["phase"] == "plan"]
        require(accepted_themes and accepted_themes[-1].get("document_output", accepted_themes[-1].get("output")) == theme
            and accepted_plans and accepted_plans[-1].get("document_output", accepted_plans[-1].get("output")) == state["native_plan"],
            "accepted original native theme/plan changed")
        require(fresh.compile_brief(theme, packet, legal_context, production_preferences, source_binding_sha256) == brief
            and fresh.contract.compile_plan(state["native_plan"], brief) == plan, "frozen brief/compiled plan changed")
        fresh.validate_provider_evidence(provider_evidence)
        diagnostics = dialogue_window_diagnostics(native, brief)
        require(bool(diagnostics["violations"]), "original full draft has no verified window defect")
        self.state, self.receipts, self.reference = state, deepcopy(receipts), deepcopy(reference_fulltext)
        self._original_receipt_count = len(receipts)
        self.state["local_draft_continuation"] = {"operator_version": VERSION,
            "operator_binding": deepcopy(self.operator_binding), "original_stop_state_sha256": digest(stop_state),
            "local_failure_proof_sha256": digest(local_failure_proof), "original_native_versions": deepcopy(state["versions"]),
            "unsubmitted_native_slot": 3, "old_budget_reset": False}
        context = {"source_packet": deepcopy(packet), "verified_legal_context": deepcopy(legal_context),
            "reference_fulltext": self.reference, "expression_standards": deepcopy(expression_standards),
            "production_preferences": deepcopy(production_preferences), "automatic_creative_choice_not_user_approval": True}
        payload = {**deepcopy(context), "brief": deepcopy(brief), "creative_scene_plan": deepcopy(plan),
            "previous_complete_document": deepcopy(native), "dialogue_window_diagnostics": diagnostics,
            "revision_requirements": [{"target": "script", "code": "SCRIPT_DIALOGUE_WINDOW_EXCEEDED", "detail": diagnostics}]}
        request = self._request("draft", AUTHOR_RULE, payload, build_script_schema(brief), 6500)
        require(digest(request) != local_failure_proof["request_sha256"], "new request has no substantive contract/diagnostic change")
        self._save("known_local_draft_slot_ready", dialogue_window_diagnostics=diagnostics)
        receipt = self._call("draft", "fresh_draft_03_known_local_revision", request, lambda v: validate_script(v, brief))
        raw = self._output(receipt, lambda v: validate_script(v, brief))
        if raw is None:
            if receipt is not None and not self.state["status"].startswith("halt_"):
                self._save("draft_stalled", original_ordinal=receipt.get("ordinal"), version_limit_exhausted=True,
                    redispatch_allowed=False)
            return self._finish_state()
        script = fresh.contract.compile_script(raw, brief)
        self.state.update(native_script=raw, script=script)
        self._save("draft_ready_waiting_full_review")
        review_payload = {**deepcopy(context), "brief": deepcopy(brief), "full_scene_plan": deepcopy(plan),
            "full_current_script": deepcopy(script), "evidence_catalog": fresh.contract.evidence_catalog(script),
            "legal_fact_catalog": fresh.legal_catalog(legal_context), "quality_criteria": deepcopy(fresh.CRITERIA)}
        validator = lambda value: fresh.validate_review(value, script, brief, plan, legal_context)
        review_receipt = self._call("review", "fresh_full_review_03_known_local_revision",
            self._request("review", fresh.REVIEW_RULE, review_payload, fresh.review_schema(script, brief, plan, legal_context), 12000), validator)
        review = self._output(review_receipt, validator)
        if review is None:
            if review_receipt is not None and not self.state["status"].startswith("halt_"):
                self._save("halt_review_contract_rejected", original_ordinal=review_receipt.get("ordinal"), redispatch_allowed=False)
            return self._finish_state()
        decision = fresh.decide_review(review, script, brief, plan, legal_context)
        self.state.update(full_review=review, automatic_decision=decision)
        if decision["status"] != "text_ready_for_director":
            self._save(decision["status"] if decision["status"].startswith("halt_") else "creative_stalled",
                version_limit_exhausted=True, redispatch_allowed=False)
            return self._finish_state()
        package = fresh.build_production_package(theme, brief, script, provider_evidence)
        binding = {"writer_ordinal": receipt["ordinal"], "review_ordinal": review_receipt["ordinal"],
            "writer_receipt_sha256": digest(receipt), "review_receipt_sha256": digest(review_receipt),
            "script_sha256": digest(script), "machine_text_review_passed": True,
            "production_context_sha256": fresh.coordinator.production_context_digest(brief, reference_fulltext, production_preferences),
            "human_quality_approved": False, "review_kind": VERSION + "/integrated_full_review"}
        self.state.update(status="text_ready_for_director", source_review_binding=binding, manifest=package["shared_manifest"],
            initial=package["planned_initial_state"], shared_dynamic_initial=package["shared_dynamic_initial"], production_package=package,
            sourcepackage={"brief": brief, "casting": {r["id"]: r["profile"] for r in theme["characters"]},
                "scene_appearance": {r["id"]: r["appearance"] for r in theme["scenes"]},
                "prop_appearance": {r["id"]: r["appearance"] for r in theme["initial_state"]["prop_states"]},
                "reference_fulltext": reference_fulltext, "production_preferences": deepcopy(production_preferences)})
        return self._finish_state()
