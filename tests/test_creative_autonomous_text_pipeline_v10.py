"""Immutable detector finding adjudication and unattended revision routing."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v10 as contract
from tests.test_creative_autonomous_text_pipeline_v2 import review_v2
from tests.test_creative_autonomous_text_pipeline_v5 import audit_v5
from tests.test_creative_autonomous_text_pipeline_v7 import (
    wire_checks, resume_workspace_v7, pipeline_workspace_v6, pipeline_workspace_v5,
    pipeline_workspace_v3, pipeline_workspace_v2,
)
from tests.test_creative_autonomous_text_pipeline_v8 import resume_workspace_v8
from tests.test_creative_autonomous_text_pipeline_v9 import (
    resume_workspace_v9, actual_case, extract_for, add_claim, unsupported_claim, read, codes,
)


PROJECT = Path(__file__).resolve().parents[1]
ROOT09 = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_09"
ROOT06 = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_06"


def actual_461():
    brief, _, plan, _, _, scope = actual_case()
    script = contract.compile_script(read(ROOT06 / "call_448_whole_draft_01.json")["output"], brief)
    extract = read(ROOT09 / "call_461_sensitive_gate_regression_probe.json")["output"]
    return brief, script, plan, scope, extract


def finding_rows(extract):
    for category in extract["category_extracts"]:
        for row in category["claims"]:
            yield "claim", row
    for row in extract["dialogue_findings"]:
        yield "language", row
    for row in extract["unknown_items"]:
        yield "unknown", row


def adjudication_for(extract, script, brief, scope):
    rows = []
    for kind, row in finding_rows(extract):
        rows.append({"finding_id": row["id"], "disposition": "unknown" if kind == "unknown" else "confirmed_violation",
            "basis_kind": "uncertain" if kind == "unknown" else "language_error" if kind == "language" else "sensitive_attribute_violation",
            "source_evidence": [], "source_attribute_type": "unknown" if kind == "unknown" else "none",
            "source_attribute_quote": "", "explanation": "离线裁决路由夹具，明确判断不是审美或语义金标。"})
    return {"extract_sha256": contract._digest(extract), "script_sha256": contract._digest(script),
        "brief_sha256": contract._digest(brief), "scope_sha256": contract._digest(scope), "findings": rows}


def subset(extract, id_):
    result = deepcopy(extract)
    for table in result["category_extracts"]:
        table["claims"] = [row for row in table["claims"] if row["id"] == id_]
    for key in ["dialogue_findings", "unknown_items"]:
        result[key] = [row for row in result[key] if row["id"] == id_]
    for row in result["step_coverage"]:
        for key in ["claim_ids", "dialogue_finding_ids", "unknown_ids"]:
            row[key] = [value for value in row[key] if value == id_]
    return result


def context_verdict(verdict, brief, fact_id="F3", quote="小林回应请求仍不签"):
    verdict.update(disposition="context_or_source_supported", basis_kind="non_business_context",
        source_evidence=[{"fact_id": fact_id, "quote": quote}], source_attribute_type="context",
        context_type="employee_refusal", source_attribute_quote="", explanation="判断仅关于当前人物已给的拒签行为，不能授权新业务承诺。")


def test_actual_461_all_native_findings_including_action_language_are_accepted_unchanged():
    brief, script, _, scope, extract = actual_461()
    before = deepcopy(extract)
    assert contract.evidence_catalog(script)["E0032"]["kind"] == "action"
    assert next(r for r in extract["dialogue_findings"] if r["id"] == "D-03")["quote"] == "只剩周姐那一侧的文件夹也不在桌面。"
    assert contract.validate_fact_scope_extract(extract, script, brief, scope)["all_performed_prose_language_checked"]
    verdict = adjudication_for(extract, script, brief, scope)
    decision = contract.decide_adjudication(verdict, extract, script, brief, scope)
    assert decision["status"] == "needs_whole_revision" and "LANGUAGE_FOCUSED_D-03" in codes(decision)
    assert extract == before


@pytest.mark.parametrize("change", ["missing_id", "duplicate_id", "wrong_extract_sha", "wrong_script_sha", "fake_source_quote"])
def test_adjudication_all_ids_exact_hashes_and_true_source_quotes_are_required(change):
    brief, script, _, scope, extract = actual_461()
    value = adjudication_for(extract, script, brief, scope)
    if change == "missing_id": value["findings"].pop()
    elif change == "duplicate_id": value["findings"][-1]["finding_id"] = value["findings"][0]["finding_id"]
    elif change == "wrong_extract_sha": value["extract_sha256"] = "0" * 64
    elif change == "wrong_script_sha": value["script_sha256"] = "0" * 64
    else: value["findings"][0]["source_evidence"] = [{"fact_id": "F3", "quote": "源中没有这句承诺"}]
    with pytest.raises(ValueError):
        contract.validate_adjudication(value, extract, script, brief, scope)


@pytest.mark.parametrize("id_,fact_id,quote", [
    ("C-FUU-03", "F3", "小林回应请求仍不签"),
    ("C-LR-02", "F4", "小林不拿笔签字"),
])
def test_actual_personal_refusal_can_be_context_supported_without_new_business_fact(id_, fact_id, quote):
    brief, script, _, scope, full = actual_461()
    extract = subset(full, id_)
    value = adjudication_for(extract, script, brief, scope)
    context_verdict(value["findings"][0], brief, fact_id, quote)
    assert contract.decide_adjudication(value, extract, script, brief, scope)["status"] == "text_ready_for_director"
    assert read(ROOT09 / "call_461_sensitive_gate_regression_probe.json")["output"] == full


def test_actual_deadline_cannot_borrow_generic_refusal_context():
    brief, script, _, scope, full = actual_461()
    id_ = "C-EDT-01"
    extract = subset(full, id_)
    value = adjudication_for(extract, script, brief, scope)
    context_verdict(value["findings"][0], brief)
    decision = contract.decide_adjudication(value, extract, script, brief, scope)
    assert decision["status"] == "needs_whole_revision" and "FACT_SCOPE_" + id_ in codes(decision)


@pytest.mark.parametrize("id_", ["C-FUU-02", "C-BP-01"])
def test_source_supported_business_promise_and_completion_need_same_concrete_attribute_not_context(id_):
    brief, script, _, scope, full = actual_461()
    extract = subset(full, id_)
    value = adjudication_for(extract, script, brief, scope)
    context_verdict(value["findings"][0], brief)
    # Independent adjudication may reclassify detector mistakes as context.
    # If it instead asserts source support, context is not the same business atom.
    value["findings"][0]["basis_kind"] = "source_supported"
    decision = contract.decide_adjudication(value, extract, script, brief, scope)
    assert decision["status"] == "needs_whole_revision" and "FACT_SCOPE_" + id_ in codes(decision)


@pytest.mark.parametrize("change", ["missing_context_type", "no_source_evidence"])
def test_context_adjudication_has_explicit_classification_and_real_source_evidence(change):
    brief, script, _, scope, full = actual_461()
    extract = subset(full, "C-FUU-03")
    value = adjudication_for(extract, script, brief, scope)
    context_verdict(value["findings"][0], brief)
    if change == "missing_context_type": value["findings"][0].pop("context_type")
    else: value["findings"][0]["source_evidence"] = []
    with pytest.raises(ValueError):
        contract.validate_adjudication(value, extract, script, brief, scope)


def test_absolute_prohibition_cannot_be_used_as_positive_source_support():
    brief, script, _, scope, full = actual_461()
    extract = subset(full, "C-FUU-03")
    value = adjudication_for(extract, script, brief, scope)
    fact = next(r for r in brief["facts"] if r["id"] == "F6")
    context_verdict(value["findings"][0], brief, "F6", fact["text"])
    assert contract.decide_adjudication(value, extract, script, brief, scope)["status"] == "needs_whole_revision"


def test_confirmed_violation_plus_unknown_repairs_whole_script_first_but_only_unknown_halts():
    brief, script, _, scope, extract = actual_461()
    verdict = adjudication_for(extract, script, brief, scope)
    result = contract.decide_adjudication(verdict, extract, script, brief, scope)
    assert result["revision_requirements"] and result["uncertainties"] and result["status"] == "needs_whole_revision"
    unknown = subset(extract, "U-01")
    verdict = adjudication_for(unknown, script, brief, scope)
    result = contract.decide_adjudication(verdict, unknown, script, brief, scope)
    assert not result["revision_requirements"] and result["uncertainties"] and result["status"] == "halt_review_uncertain"


def test_new_payment_amount_cannot_be_reclassified_as_generic_refusal_context():
    brief, script, _, scope, _ = actual_461()
    raw = {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"}
    raw["beats"][0]["steps"][1]["text"] = "公司通知你1000元。"
    script = contract.compile_script(raw, brief)
    extract = extract_for(script, brief, scope)
    add_claim(extract, "wage_or_payment", unsupported_claim("payment", "E0002", "公司通知你1000元。", "1000", "payment_amount", "company"))
    value = adjudication_for(extract, script, brief, scope)
    context_verdict(value["findings"][0], brief)
    assert "FACT_SCOPE_payment" in codes(contract.decide_adjudication(value, extract, script, brief, scope))


@pytest.fixture
def resume_workspace_v10(resume_workspace_v9):
    from scripts import run_autonomous_text_pipeline_v10 as runner
    _, root, parent, brief, script, plan = resume_workspace_v9
    ledger = read(parent / "CALL_LEDGER.json")
    manifest = read(root / "RESUME_RECEIPTS.json")
    old_draft_path = next(parent.glob("call_448_*.json"))
    old_draft = read(old_draft_path)
    old_draft["output"]["beats"][0]["steps"][0]["text"] = "公司让你这个月底走，签了我明天去送表，今天就能办完。这个我签字。"
    old_draft["output"]["beats"][0]["steps"][1]["text"] = "只剩文件夹也不在桌面。"
    baseline = contract.compile_script(old_draft["output"], brief)
    old_draft_path.write_text(json.dumps(old_draft, ensure_ascii=False), encoding="utf-8")
    old_sha = hashlib.sha256(old_draft_path.read_bytes()).hexdigest()
    next(r for r in ledger["calls"] if r["ordinal"] == 448)["receipt_sha256"] = old_sha
    scope = contract.compile_source_fact_scope(read(manifest["receipts"]["scope_source"]["path"])["output"], brief)
    extract = extract_for(baseline, brief, scope)
    claims = [
        ("employment_departure_timing", unsupported_claim("C-EDT-01", "E0001", "这个月底走", "这个月底", "departure_time", "hr")),
        ("follow_up_undertaking", unsupported_claim("C-FUU-02", "E0001", "签了我明天去送表", "明天去送表", "business_promise", "hr")),
        ("business_procedure", unsupported_claim("C-BP-01", "E0001", "今天就能办完", "今天就能办完", "business_completion", "hr")),
        ("follow_up_undertaking", unsupported_claim("C-FUU-03", "E0005", "这不是我的意思，我不签。", "我不签", "future_business_action", "worker")),
    ]
    for category, row in claims: add_claim(extract, category, row)
    for id_, ref, quote in [("D-01", "E0001", "这个我签字。"), ("D-03", "E0002", "只剩文件夹也不在桌面。")]:
        extract["dialogue_findings"].append({"id": id_, "source_ref": ref, "quote": quote,
            "issue_type": "meaning_conflict", "explanation": "模拟语言异常，仅验证原始finding保留及分支。"})
        next(r for r in extract["step_coverage"] if r["source_ref"] == ref)["dialogue_finding_ids"].append(id_)
    native = {"ordinal": 461, "label": "sensitive_gate_regression_probe", "status": "contract_rejected", "output": extract,
        "failure": {"category": "validation", "code": "dialogue finding must cite an actual spoken step", "response_received": True},
        "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": 19996}}
    path = parent / "call_461_sensitive_gate_regression_probe.json"
    path.write_text(json.dumps(native, ensure_ascii=False), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ledger["calls"].append({"ordinal": 461, "receipt": path.name, "receipt_sha256": sha})
    manifest["receipts"]["sensitive_probe"] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": 461}
    manifest["receipts"]["sensitive_probe_draft"] = {"path": str(old_draft_path.resolve()), "sha256": old_sha, "original_ordinal": 448}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield runner, root, parent, brief, script, plan, native


class MockV10:
    def __init__(self, brief, script, plan, *, unknown_at=None, semantic_unknown=False, always_bad=False):
        self.brief, self.script, self.plan = deepcopy(brief), deepcopy(script), deepcopy(plan)
        self.requests, self.extracts = [], 0
        self.unknown_at, self.semantic_unknown, self.always_bad = unknown_at, semantic_unknown, always_bad

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "payload": deepcopy(payload)})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "extract_sha256" in properties:
            script, scope, extract = payload["full_current_script"], payload["source_fact_scope"], payload["original_detection"]
            output = adjudication_for(extract, script, self.brief, scope)
            for row in output["findings"]:
                if row["finding_id"] == "C-FUU-03":
                    fact = self.brief["facts"][0]
                    context_verdict(row, self.brief, fact["id"], fact["text"])
                elif self.semantic_unknown and ordinal > 1:
                    row.update(disposition="unknown", basis_kind="uncertain", source_attribute_type="unknown")
        elif "category_extracts" in properties:
            self.extracts += 1
            script, scope = payload["full_current_script"], payload["source_fact_scope"]
            output = extract_for(script, self.brief, scope)
            if self.extracts == 1 or self.always_bad:
                add_claim(output, "employment_departure_timing", unsupported_claim("date", "E0001", "这个月底走", "这个月底", "departure_time", "hr"))
                output["unknown_items"].append({"id": "unknown", "source_ref": "E0001", "quote": "这个月底走",
                    "topic": "检测另保留不确定性", "explanation": "明确date违规与该未知同时存在，必须先整稿修。"})
                output["step_coverage"][0]["unknown_ids"].append("unknown")
        elif "literal_events" in properties:
            output = wire_checks(audit_v5(payload["full_current_script"], self.brief, self.plan))
        elif "dialogue_readings" in properties:
            output = wire_checks(review_v2(payload["full_current_script"], self.brief))
        else:
            output = {k: deepcopy(v) for k, v in self.script.items() if k != "selected_candidate_id"}
            output["title"] = "模型完整第4稿"
            if not self.always_bad: output["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开。"
            for i, beat in enumerate(output["beats"]): beat["id"] = "COMPLETE_FOURTH_" + str(i)
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True,
            "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v10_mock_" + str(ordinal),
            "total_tokens": 100}, response_payload={"mock": True})


def test_bound_original_461_is_adjudicated_not_repaid_then_one_whole_fourth_draft_is_fully_reviewed(resume_workspace_v10):
    runner, root, parent, brief, script, plan, native = resume_workspace_v10
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV10(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 4, result
    assert len(service.requests) == 8 and sum(r["role"] == "writer" for r in service.requests) == 1
    assert service.requests[0]["payload"]["original_detection"] == native["output"]
    assert "previous_complete_script" not in service.requests[3]["payload"]
    assert service.requests[3]["payload"]["reference_fulltext"]
    assert not service.requests[3]["payload"].get("regression_expectations")
    assert result["spend"]["effective_calls_started"] == 469
    assert result["spend"]["effective_reported_tokens"] == 7133753
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert read(root / "SENSITIVE_GATE_REGRESSION.json")["native_detector_changed"] is False
    assert read(root / "DELIVERABLE/HANDOFF.json")["manual_assistant_gate_calls"] == 0
    assert all(b["id"].startswith("COMPLETE_FOURTH_") for b in read(root / "DELIVERABLE/RAW_MODEL_SCRIPT.json")["beats"])
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 8


@pytest.mark.parametrize("unknown_at", [1, 3, 4])
def test_probe_current_adjudicator_or_writer_unknown_stops_and_restart_does_not_redispatch(unknown_at, resume_workspace_v10):
    runner, root, _, brief, script, plan, _ = resume_workspace_v10
    service = MockV10(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 461 + unknown_at
    assert result["spend"]["unknown_token_reservations"] > 93117
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == unknown_at


def test_only_semantic_unknown_current_adjudication_stops_before_writer(resume_workspace_v10):
    runner, root, _, brief, script, plan, _ = resume_workspace_v10
    service = MockV10(brief, script, plan, semantic_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_review_uncertain" and len(service.requests) == 3
    assert not any(r["role"] == "writer" for r in service.requests)


def test_failed_fourth_full_draft_is_last_authorized_version_without_reset_or_fifth(resume_workspace_v10):
    runner, root, _, brief, script, plan, _ = resume_workspace_v10
    service = MockV10(brief, script, plan, always_bad=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "creative_stalled" and result["full_draft_versions"] == 4
    assert len(service.requests) == 8 and sum(r["role"] == "writer" for r in service.requests) == 1
    assert result["spend"]["effective_calls_started"] == 469
    assert result["spend"]["effective_reported_tokens"] == 7133753
    assert not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 8
