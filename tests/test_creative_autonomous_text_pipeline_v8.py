"""Focused source-bound claim extraction routing; mock judgments are not gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v8 as contract
from tests.test_creative_autonomous_text_pipeline_v2 import review_v2
from tests.test_creative_autonomous_text_pipeline_v5 import case_v5, audit_v5, plan_v5
from tests.test_creative_autonomous_text_pipeline_v7 import (
    wire_checks, resume_workspace_v7, pipeline_workspace_v6, pipeline_workspace_v5,
    pipeline_workspace_v3, pipeline_workspace_v2,
)


def scope_for(brief):
    allowed = [{"id": "allow_" + fact["id"], "category": "company_decision" if i == 0 else "document_fact",
        "source_fact_ids": [fact["id"]], "source_quotes": [{"fact_id": fact["id"], "quote": fact["text"]}],
        "actor_id": "", "value": fact["text"]} for i, fact in enumerate(brief["facts"])]
    return {"brief_sha256": contract._digest(brief), "restrictions": [],
            "allowed_claims": allowed, "unknown_items": [],
            "source_fact_coverage": [{"fact_id": fact["id"], "restriction_ids": [], "allowed_claim_ids": ["allow_" + fact["id"]],
                "non_business": False, "availability": "known", "explanation": "源提取路由夹具：原文事实已列许可，语义不是质量金标。"} for fact in brief["facts"]]}


def extract_for(script, brief, scope):
    return {"script_sha256": contract._digest(script), "brief_sha256": contract._digest(brief),
            "scope_sha256": contract._digest(scope), "claims": [], "dialogue_findings": [], "unknown_items": [],
            "step_coverage": [{"source_ref": ref, "claim_ids": [], "dialogue_finding_ids": [], "unknown_ids": []} for ref in contract.evidence_catalog(script)]}


def add_extract_row(value, table, key, row):
    value[table].append(row)
    next(c for c in value["step_coverage"] if c["source_ref"] == row["source_ref"])[key].append(row["id"])


def scope_case():
    brief, raw, _, _, _, _ = case_v5()
    raw["beats"][0]["steps"][0]["text"] = "公司让你这个月底离开，签了我明天去送表。"
    script = contract.compile_script(raw, brief)
    plan = plan_v5(script, brief)
    scope = contract.compile_source_fact_scope(scope_for(brief), brief)
    return brief, script, plan, wire_checks(review_v2(script, brief)), wire_checks(audit_v5(script, brief, plan)), scope


@pytest.mark.parametrize("category,modality,quote,value", [
    ("employment_departure_timing", "assertion", "公司让你这个月底离开", "这个月底离开"),
    ("follow_up_undertaking", "conditional_undertaking", "签了我明天去送表", "明天去送表"),
])
def test_unprovided_relative_departure_and_conditional_undertaking_override_whole_pass(category, modality, quote, value):
    brief, script, plan, review, audit, scope = scope_case()
    assert contract.combine_decisions(review, audit, script, brief, plan)["status"] == "text_ready_for_director"
    extract = extract_for(script, brief, scope)
    add_extract_row(extract, "claims", "claim_ids", {"id": "extra", "source_ref": "E0001", "quote": quote,
        "category": category, "actor_id": "hr", "value": value, "modality": modality, "source_fact_ids": []})
    decision = contract.combine_scope_decisions(review, audit, extract, script, brief, plan, scope)
    assert decision["status"] == "needs_whole_revision" and "FACT_SCOPE_extra" in {r["code"] for r in decision["revision_requirements"]}


def test_explicit_language_finding_cannot_be_softened_by_function_summary_pass():
    brief, script, plan, review, audit, scope = scope_case()
    extract = extract_for(script, brief, scope)
    add_extract_row(extract, "dialogue_findings", "dialogue_finding_ids", {"id": "language", "source_ref": "E0001",
        "quote": script["beats"][0]["steps"][0]["text"], "issue_type": "meaning_conflict",
        "explanation": "夹具明确的语言发现不能被旧摘要目的清楚所覆盖；不建立禁词表。"})
    assert contract.combine_scope_decisions(review, audit, extract, script, brief, plan, scope)["status"] == "needs_whole_revision"


@pytest.mark.parametrize("change", ["invented_quote", "missing_step", "wrong_scope"])
def test_extract_quote_coverage_and_scope_binding_cannot_be_fabricated(change):
    brief, script, _, _, _, scope = scope_case()
    extract = extract_for(script, brief, scope)
    if change == "missing_step":
        extract["step_coverage"].pop()
        missing_source = scope_for(brief)
        missing_source["source_fact_coverage"].pop()
        with pytest.raises(ValueError):
            contract.validate_source_fact_scope(missing_source, brief)
    elif change == "wrong_scope":
        extract["scope_sha256"] = "0" * 64
    else:
        add_extract_row(extract, "claims", "claim_ids", {"id": "extra", "source_ref": "E0001", "quote": "正文没有这个句子",
            "category": "employment_departure_timing", "actor_id": "hr", "value": "月底", "modality": "assertion", "source_fact_ids": []})
    with pytest.raises(ValueError):
        contract.validate_fact_scope_extract(extract, script, brief, scope)


def test_scene_time_and_performance_detail_do_not_become_new_business_facts():
    brief, script, _, _, _, scope = scope_case()
    extract = extract_for(script, brief, scope)
    add_extract_row(extract, "claims", "claim_ids", {"id": "context", "source_ref": "E0002",
        "quote": contract.evidence_catalog(script)["E0002"]["quote"], "category": "performance_action", "actor_id": "hr",
        "value": "普通同场道具表演", "modality": "other", "source_fact_ids": []})
    assert contract.decide_fact_scope_extract(extract, script, brief, scope)["status"] == "text_ready_for_director"


def test_partial_occurrence_windows_default_to_whole_step_without_rewriting_native_judgments():
    brief, script, plan, _, audit, _ = scope_case()
    before = deepcopy(audit)
    row = next(r for r in audit["obligation_evidence"] if r["obligation_id"] == "refusal")
    row["occurrence_spans"] = []
    before = deepcopy(audit)
    compiled = contract.compile_audit(audit, script, brief, plan)
    assert audit == before and next(r for r in compiled["obligation_evidence"] if r["obligation_id"] == "refusal")["occurrence_spans"] == [{"ref_id": "E0005", "quote": contract.evidence_catalog(script)["E0005"]["quote"]}]
    for native, resolved in zip(audit["obligation_evidence"], compiled["obligation_evidence"]):
        assert all(native[k] == resolved[k] for k in native if k != "occurrence_spans")


@pytest.fixture
def resume_workspace_v8(resume_workspace_v7):
    from scripts import run_autonomous_text_pipeline_v8 as runner
    _, root, parent, brief, _, plan, _ = resume_workspace_v7
    manifest = json.loads((root / "RESUME_RECEIPTS.json").read_text(encoding="utf-8"))
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    def save_existing(key, change):
        path = Path(manifest["receipts"][key]["path"])
        receipt = json.loads(path.read_text(encoding="utf-8"))
        change(receipt)
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["receipts"][key]["sha256"] = sha
        next(row for row in ledger["calls"] if row["ordinal"] == receipt["ordinal"])["receipt_sha256"] = sha
        return receipt
    draft = save_existing("draft", lambda r: r["output"]["beats"][0]["steps"][0].update(text="公司让我通知你，这次要你离开，这个月底走。"))
    script = contract.compile_script(draft["output"], brief)
    save_existing("review", lambda r: r["output"].update(script_sha256=contract._digest(script)))
    audit = wire_checks(audit_v5(script, brief, plan))
    next(r for r in audit["obligation_evidence"] if r["obligation_id"] == "refusal")["occurrence_spans"] = []
    native = {"ordinal": 450, "label": "literal_audit_01", "status": "contract_rejected", "output": audit,
        "failure": {"category": "validation", "code": "occurrence_spans must cover every occurrence_ref exactly once", "response_received": True},
        "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": 18065}}
    path = parent / "call_450_literal_audit_01.json"
    path.write_text(json.dumps(native, ensure_ascii=False), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ledger["calls"].append({"ordinal": 450, "receipt": path.name, "receipt_sha256": sha})
    manifest["receipts"]["audit"] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": 450}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield runner, root, parent, brief, script, plan, audit


class MockV8:
    def __init__(self, brief, script, plan, *, unknown_at=None, semantic_unknown=False, source_unknown=False):
        self.brief, self.script, self.plan = deepcopy(brief), deepcopy(script), deepcopy(plan)
        self.requests, self.extracts = [], 0
        self.unknown_at, self.semantic_unknown = unknown_at, semantic_unknown
        self.source_unknown = source_unknown

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "payload": deepcopy(payload)})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "restrictions" in properties:
            output = scope_for(self.brief)
            if self.source_unknown:
                output["source_fact_coverage"][0]["availability"] = "unknown"
        elif "step_coverage" in properties:
            self.extracts += 1
            script, scope = payload["full_current_script"], payload["source_fact_scope"]
            output = extract_for(script, self.brief, scope)
            if self.semantic_unknown:
                add_extract_row(output, "unknown_items", "unknown_ids", {"id": "unclear", "source_ref": "E0001", "quote": contract.evidence_catalog(script)["E0001"]["quote"], "topic": "是否新增业务主张", "explanation": "无法判定，不能猜成通过。"})
            elif self.extracts == 1:
                add_extract_row(output, "claims", "claim_ids", {"id": "date", "source_ref": "E0001", "quote": "这个月底走", "category": "employment_departure_timing", "actor_id": "hr", "value": "这个月底走", "modality": "assertion", "source_fact_ids": []})
        elif "literal_events" in properties:
            output = wire_checks(audit_v5(payload["full_current_script"], self.brief, self.plan))
        elif "dialogue_readings" in properties:
            output = wire_checks(review_v2(payload["full_current_script"], self.brief))
        else:
            output = {k: deepcopy(v) for k, v in self.script.items() if k != "selected_candidate_id"}
            output["title"] = "生成模型完整第二稿"
            output["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开。"
            for i, beat in enumerate(output["beats"]):
                beat["id"] = "COMPLETE_NEW_" + str(i)
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True, "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v8_mock_" + str(ordinal), "total_tokens": 100}, response_payload={"mock": True})


def test_scope_fail_runs_complete_second_draft_and_three_checks_without_manual_scope_or_reset(resume_workspace_v8):
    runner, root, parent, brief, script, plan, native_audit = resume_workspace_v8
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV8(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and len(service.requests) == 6, result
    assert service.requests[0]["payload"] == {"brief": brief}
    assert service.requests[2]["payload"]["previous_complete_script"] == script
    assert all(b["id"].startswith("COMPLETE_NEW_") for b in json.loads((root / "DELIVERABLE/FULL_SCRIPT.json").read_text(encoding="utf-8"))["beats"])
    assert json.loads((root / "versions/01/ORIGINAL_NATIVE_AUDIT.json").read_text(encoding="utf-8")) == native_audit
    assert result["spend"]["effective_calls_started"] == 456 and result["spend"]["effective_reported_tokens"] == 6977657
    assert result["spend"]["unknown_token_reservations"] == 93117 and result["spend"]["old_budget_reset"] is False
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"] and len(service.requests) == 6


@pytest.mark.parametrize("unknown_at", [1, 2])
def test_unknown_scope_service_stops_without_redispatch_or_reset(unknown_at, resume_workspace_v8):
    runner, root, _, brief, script, plan, _ = resume_workspace_v8
    service = MockV8(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 450 + unknown_at and result["spend"]["unknown_token_reservations"] > 93117
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"] and len(service.requests) == unknown_at


def test_unknown_claim_semantics_stops_before_new_full_draft(resume_workspace_v8):
    runner, root, _, brief, script, plan, _ = resume_workspace_v8
    service = MockV8(brief, script, plan, semantic_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_review_uncertain" and len(service.requests) == 2


def test_source_availability_unknown_is_semantic_halt_not_protocol_failure(resume_workspace_v8):
    runner, root, _, brief, script, plan, _ = resume_workspace_v8
    service = MockV8(brief, script, plan, source_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_source_uncertain" and len(service.requests) == 1
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"] and len(service.requests) == 1
