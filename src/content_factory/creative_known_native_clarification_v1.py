"""Pure known-complete author clarification; no old verdict is rewritten.

Receipt JSON/tool/usage coherence is checked here. External raw SDK bytes,
settled cumulative spend, fresh source admission and unique dispatch claims
remain the session's responsibilities. This module never opens files/providers.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from . import creative_goal_context_workflow_v24 as workflow

VERSION = "creative_known_native_clarification/v1"
FEEDBACK_SCHEMA = VERSION + "/request_feedback"
digest = workflow.digest
CORE_KEYS = ("source_packet", "verified_legal_context", "reference_fulltext", "expression_standards",
    "production_preferences", "user_goal_contract", "origin_catalog")
CONFIRMED = {"verified_text_ambiguity_not_legal_effect_verdict", "verified_cross_field_inconsistency"}
HYPOTHESIS = "inference_requiring_same_source_semantic_review"
OBSERVATION_CLASSES = {
    "document_purpose_and_timeline": "verified_text_ambiguity_not_legal_effect_verdict",
    "strategy_actor_perspective": "verified_cross_field_inconsistency",
    "concession_cause": HYPOTHESIS,
}
RULE = (
    "这是对完整、用量已知旧规划的作者澄清，旧规划结构有效并不等于已采用。读取完整previous_complete_document，提交完整原生新计划，"
    "不得本地回填、拼接或手改旧稿。current_author_clarification_refs指向已定位的文字含混或跨字段主体问题；"
    "plot_review_hypothesis_refs只是待同源剧情审查核实的观察，不伪装成已确认错误。"
    "完整historical_source_audit保留历史来源不确定，不是当前全量法律错误清单，也没有转为通过。"
    "澄清文书各次用途、提议/同意/签署/生效的表达和时序；同日签署某种安排与明日上班不自动矛盾，"
    "一处签名也不能由本地推成双方已签或解除生效，具体相容安排由完整新稿表达。"
    "策略前后应属于声明的行动主体，对手反应另有其位置与因果；不固定台词、动作、句数、文件名称或替代结局。"
    "原始来源、法律条件、用户已确认方向和参考全文保持，不能迁就新稿改来源；新稿仍须scope2/source2/commitment/drama四份真实同源审查，"
    "再生成完整正文和双分全文审查。旧语义不确定、观察或本地校验不构成新稿法律、创作或人工质量通过。"
)


class ClarificationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ClarificationError(message)


def _sha(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _strict_object(text):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate original JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ClarificationError("nonfinite original JSON constant")
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ClarificationError("complete original JSON object required") from exc
    _require(type(value) is dict, "complete original JSON object required")
    digest(value)
    return value


def _payload(request):
    messages = request.get("messages", [])
    _require(type(messages) is list and len(messages) == 2 and all(type(item) is dict for item in messages)
        and messages[0].get("role") == "system"
        and messages[1].get("role") == "user", "original two-message planning/audit request required")
    return _strict_object(messages[1].get("content"))


def _known_receipt(receipt, *, stage, role):
    _require(type(receipt) is dict and receipt.get("status") == "contract_valid"
        and receipt.get("automatic_retry") is False and not receipt.get("cached_response_read_only"),
        "known complete contract-valid native receipt required; do not fake structural rejection")
    request, meta, payload = receipt.get("request", {}), receipt.get("response_metadata", {}), receipt.get("response_payload", {})
    _require(all(type(item) is dict for item in (request, meta, payload)), "original request/metadata/response objects required")
    _require(request.get("stage") == stage and request.get("role") == role
        and type(request.get("model")) is str and request["model"].strip()
        and receipt.get("request_sha256") == digest(request), "original stage/request identity mismatch")
    _require(type(meta.get("http_status_code")) is int and 200 <= meta["http_status_code"] < 300
        and meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop", "tool_calls")
        and meta.get("output_mode") == "tool_call" and not meta.get("response_fault_code")
        and meta.get("role") == role and meta.get("requested_model") == meta.get("response_model") == request.get("model")
        and payload.get("model") == request["model"] and meta.get("provider") == ("minimax" if role == "writer" else "deepseek")
        and _sha(meta.get("raw_body_sha256")) and type(receipt.get("completed_at")) is str and receipt["completed_at"].strip()
        and type(receipt.get("ordinal")) is int and receipt["ordinal"] > 0,
        "unknown/incomplete/protocol result cannot become author clarification")
    usage = payload.get("usage", {})
    _require(type(usage) is dict, "original typed usage object required")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        _require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int
            and usage[key] == meta[key], "known original typed usage required")
    _require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage totals differ")
    choices = payload.get("choices", [])
    _require(type(choices) is list and len(choices) == 1 and type(choices[0]) is dict and choices[0].get("index") == 0
        and choices[0].get("finish_reason") == meta["finish_reason"], "one complete original response choice required")
    message = choices[0].get("message", {})
    _require(type(message) is dict, "original native assistant message required")
    calls = message.get("tool_calls", [])
    _require(message.get("role") == "assistant" and type(calls) is list and len(calls) == 1 and type(calls[0]) is dict
        and calls[0].get("type") == "function" and type(calls[0].get("function")) is dict
        and calls[0]["function"].get("name") == "submit_creative_json",
        "original target tool result required")
    native = _strict_object(calls[0]["function"].get("arguments"))
    _require(native and digest(receipt.get("output")) == digest(native) and _sha(receipt.get("source_binding_sha256")),
        "native output or bound original source differs")
    return {"ordinal": receipt.get("ordinal"), "receipt_canonical_sha256": digest(receipt),
        "request_sha256": digest(request), "native_output_sha256": digest(native),
        "source_binding_sha256": receipt["source_binding_sha256"], "stage": stage, "role": role,
        "model": request["model"], "status": "contract_valid", "raw_response_body_sha256": meta["raw_body_sha256"],
        "usage": {key: meta[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}}


def _resolve(native, path):
    _require(type(path) is str and path and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|0|[1-9][0-9]*", key)
        for key in path.split(".")), "canonical original field path required")
    value = native
    try:
        for key in path.split("."):
            value = value[int(key)] if type(value) is list else value[key]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ClarificationError("observation path absent from original native: " + path) from exc
    return value


def _observation_refs(observations, native):
    _require(type(observations) is dict and observations.get("schema") == "creative_native_goal_content_risks/root_review/v1"
        and observations.get("native_goal_sha256") == digest(native)
        and observations.get("original_native_modified") is False and observations.get("structural_contract_valid") is True
        and observations.get("is_full_screenplay") is False and observations.get("semantic_quality_passed") is False,
        "bound original author observations, not a quality approval, required")
    risks = observations.get("risks")
    _require(type(risks) is list and risks, "complete author observation list required")
    confirmed, hypotheses, seen = [], [], set()
    for index, row in enumerate(risks):
        _require(type(row) is dict and type(row.get("id")) is str and row["id"] and row["id"] not in seen,
            "unique original observation identity required")
        seen.add(row["id"]); kind = row.get("classification")
        _require(OBSERVATION_CLASSES.get(row["id"]) == kind,
            "unmapped observation or changed confirmed/hypothesis ownership must stop")
        _require(type(row.get("observed_issue")) is str and row["observed_issue"].strip(), "original observation issue required")
        if kind == HYPOTHESIS:
            _require(type(row.get("qualification")) is str and row["qualification"].strip(), "plot hypothesis must retain qualification")
        else:
            _require(type(row.get("reusable_check")) is str and row["reusable_check"].strip(), "reusable clarification purpose required")
        evidence = row.get("evidence"); paths = set()
        _require(type(evidence) is list and evidence, "each observation needs exact original evidence")
        for item in evidence:
            _require(type(item) is dict and set(item) in ({"path", "quote"}, {"path", "value"}), "exact path/quote or path/value evidence required")
            _require(type(item["path"]) is str, "canonical original field path required")
            _require(item["path"] not in paths, "duplicate observation field evidence")
            paths.add(item["path"]); value = _resolve(native, item["path"])
            expected = item["quote"] if "quote" in item else item["value"]
            _require(digest(value) == digest(expected) and ("quote" not in item or type(value) is str),
                "observation differs from its complete native field")
        ref = {"observation_id": row["id"], "classification": kind, "pointer": "/root_observations/risks/" + str(index)}
        (hypotheses if kind == HYPOTHESIS else confirmed).append(ref)
    _require(seen == set(OBSERVATION_CLASSES), "complete supported observation set required; do not silently omit hypotheses")
    return confirmed, hypotheses


def _clean_context(clean, native):
    _require(type(clean) is dict and "previous_complete_document" not in clean and "revision_diagnostics" not in clean,
        "clean original functional inputs required")
    core = workflow._fixed_legal_context(clean)
    workflow.validate_goal_document(native, inputs=clean)
    source_payload, _ = workflow.prior._source_context(workflow.project_inputs(clean), native)
    return core, source_payload


def _decision_summary(report, native, source_payload):
    authority = {key: deepcopy(source_payload[key]) for key in ("verified_legal_context", "origin_catalog")}
    decision = workflow.source_audit.validate_source(report, native, authority, context_sha256=digest(source_payload))
    _require(decision["valid"] and not decision["accepted"] and not decision["findings"] and decision["uncertainties"],
        "this clarification route retains original source uncertainty, not a passed or legal-failure verdict")
    return decision, {"schema": decision["schema"], "valid": decision["valid"], "accepted": decision["accepted"],
        "findings_count": len(decision["findings"]), "uncertainties_count": len(decision["uncertainties"]),
        "original_decision_sha256": digest(decision)}


def validate_revision_inputs(inputs):
    """Check the constructed frame before ownership projection, not raw SDK files."""
    _require(type(inputs) is dict and type(inputs.get("previous_complete_document")) is dict,
        "complete prior native planning document required")
    frame = inputs.get("revision_diagnostics"); native = inputs["previous_complete_document"]
    fields = {"schema", "rule", "original_inputs_sha256", "prior_native_goal_sha256", "receipt_bindings",
        "root_observations", "root_observations_sha256", "current_author_clarification_refs", "plot_review_hypothesis_refs",
        "historical_source_audit", "historical_source_decision", "historical_feedback_applicability"}
    _require(type(frame) is dict and set(frame) == fields and frame.get("schema") == FEEDBACK_SCHEMA
        and frame.get("rule") == RULE, "exact known-native clarification frame required")
    clean = {key: deepcopy(value) for key, value in inputs.items() if key not in ("previous_complete_document", "revision_diagnostics")}
    _require(frame["original_inputs_sha256"] == digest(clean) and frame["prior_native_goal_sha256"] == digest(native),
        "original functional inputs or complete prior native changed")
    core, source_payload = _clean_context(clean, native)
    confirmed, hypotheses = _observation_refs(frame["root_observations"], native)
    _require(frame["root_observations_sha256"] == digest(frame["root_observations"])
        and frame["current_author_clarification_refs"] == confirmed and frame["plot_review_hypothesis_refs"] == hypotheses,
        "confirmed author issues and plot hypotheses must remain separate")
    _, summary = _decision_summary(frame["historical_source_audit"], native, source_payload)
    _require(frame["historical_source_decision"] == summary and frame["historical_feedback_applicability"] ==
        "historical_uncertainty_retained_not_current_legal_error_checklist_or_pass", "historical source uncertainty/verdict changed")
    bindings = frame["receipt_bindings"]
    _require(type(bindings) is dict and set(bindings) == {"goal", "source"}, "both original receipt bindings required")
    for key, stage, role, document in (("goal", "goal_plan", "writer", native), ("source", "goal_audit", "director", frame["historical_source_audit"])):
        proof = bindings[key]
        _require(type(proof) is dict, "complete original receipt binding required")
        usage = proof.get("usage", {})
        _require(type(usage) is dict, "original typed usage binding required")
        _require(proof.get("stage") == stage and proof.get("role") == role and proof.get("status") == "contract_valid"
            and proof.get("native_output_sha256") == digest(document)
            and all(_sha(proof.get(field)) for field in ("receipt_canonical_sha256", "request_sha256", "source_binding_sha256", "raw_response_body_sha256")),
            "original complete native receipt binding mismatch")
        _require(all(type(usage.get(field)) is int and usage[field] >= 0 for field in ("prompt_tokens", "completion_tokens", "total_tokens"))
            and usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"], "known original receipt usage binding required")
    _require(bindings["goal"]["source_binding_sha256"] == bindings["source"]["source_binding_sha256"], "original planning/source lineage differs")
    _require(type(bindings["goal"].get("ordinal")) is int and type(bindings["source"].get("ordinal")) is int
        and 0 < bindings["goal"]["ordinal"] < bindings["source"]["ordinal"], "original source review must follow its native goal")
    return {"schema": VERSION + "/manifest", "valid": True, "original_inputs_sha256": digest(clean),
        "revision_inputs_sha256": digest(inputs), "native_goal_sha256": digest(native),
        "historical_source_native_sha256": digest(frame["historical_source_audit"]),
        "historical_source_decision": summary, "root_observations_sha256": digest(frame["root_observations"]),
        "confirmed_observation_ids": [row["observation_id"] for row in confirmed],
        "plot_hypothesis_ids": [row["observation_id"] for row in hypotheses],
        "source_core_sha256": {key: digest(core[key]) for key in CORE_KEYS}, "receipt_bindings": deepcopy(bindings),
        "feedback_sha256": digest(frame), "original_native_modified": False, "historical_audit_modified": False,
        "historical_U_marked_legal_failure_or_pass": False, "raw_sdk_files_verified_here": False,
        "settled_cumulative_spend_verified_here": False, "source_freshness_verified_here": False,
        "requires_four_new_same_goal_native_audits": True, "provider_calls": 0, "new_claims": 0,
        "creative_quality_passed": False, "human_approved": False}


def build_revision_inputs(current_inputs, native_goal_receipt, native_source_audit_receipt, root_observations):
    goal_proof = _known_receipt(native_goal_receipt, stage="goal_plan", role="writer")
    source_proof = _known_receipt(native_source_audit_receipt, stage="goal_audit", role="director")
    native = native_goal_receipt["output"]; core, source_payload = _clean_context(current_inputs, native)
    original_payload = _payload(native_goal_receipt["request"])
    _require(all(key in original_payload and digest(original_payload[key]) == digest(core[key]) for key in CORE_KEYS),
        "original source/law/reference/user/preferences changed")
    _require(digest(_payload(native_source_audit_receipt["request"])) == digest(source_payload),
        "source audit no longer binds this complete goal/context")
    report = native_source_audit_receipt["output"]
    decision, summary = _decision_summary(report, native, source_payload)
    _require(digest(native_source_audit_receipt.get("validation")) == digest(decision),
        "original source decision differs from its native report")
    confirmed, hypotheses = _observation_refs(root_observations, native)
    result = {**deepcopy(current_inputs), "previous_complete_document": deepcopy(native), "revision_diagnostics": {
        "schema": FEEDBACK_SCHEMA, "rule": RULE, "original_inputs_sha256": digest(current_inputs),
        "prior_native_goal_sha256": digest(native), "receipt_bindings": {"goal": goal_proof, "source": source_proof},
        "root_observations": deepcopy(root_observations), "root_observations_sha256": digest(root_observations),
        "current_author_clarification_refs": confirmed, "plot_review_hypothesis_refs": hypotheses,
        "historical_source_audit": deepcopy(report), "historical_source_decision": summary,
        "historical_feedback_applicability": "historical_uncertainty_retained_not_current_legal_error_checklist_or_pass"}}
    return {"inputs": result, "manifest": validate_revision_inputs(result)}
