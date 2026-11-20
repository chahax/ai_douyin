"""Real-corpus property regressions; excerpt positives are not whole-film gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v9 as contract
from tests.test_creative_autonomous_text_pipeline_v2 import review_v2
from tests.test_creative_autonomous_text_pipeline_v5 import case_v5, audit_v5, plan_v5
from tests.test_creative_autonomous_text_pipeline_v7 import (
    wire_checks, resume_workspace_v7, pipeline_workspace_v6, pipeline_workspace_v5,
    pipeline_workspace_v3, pipeline_workspace_v2,
)
from tests.test_creative_autonomous_text_pipeline_v8 import scope_for, resume_workspace_v8


PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_08"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def actual_case():
    brief = read(ACTUAL / "INPUT.json")["brief"]
    script = read(ACTUAL / "versions/03/FULL_SCRIPT.json")
    plan = read(ACTUAL / "SCENE_PLAN.json")
    audit = read(ACTUAL / "call_459_literal_audit_03.json")["output"]
    review = read(ACTUAL / "call_458_whole_review_03.json")["output"]
    scope = read(ACTUAL / "SOURCE_FACT_SCOPE.json")
    return brief, script, plan, audit, review, scope


def codes(decision):
    return {r["code"] for r in decision["revision_requirements"]}


def test_actual_459_request_anchor_is_not_invalidated_by_statement_context():
    brief, script, plan, audit, _, _ = actual_case()
    native = deepcopy(audit)
    row = next(r for r in audit["obligation_evidence"] if r["obligation_id"] == "SO7")
    assert row["occurrence_refs"] == ["E0019", "E0021"]
    decision = contract.decide_audit(audit, script, brief, plan)
    assert "SOURCE_EVENT_SO7" not in codes(decision)
    assert audit == native
    derived = contract.derive_event_evidence(audit, script, brief, plan)
    report = next(r for r in derived["obligations"] if r["obligation_id"] == "SO7")
    assert report["matching_occurrence_refs"] == ["E0021"]
    assert report["unusable_context_refs"] == ["E0019"]
    assert "E0019" in report["support_refs"]


def test_actual_447_initial_state_and_missing_first_refusal_still_fail():
    brief, _, plan, _, _, _ = actual_case()
    fixture = read(ACTUAL / "AUDIT_REGRESSION_FIXTURE.json")
    receipt = read(PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_06/call_447_literal_gate_regression_probe.json")
    script = fixture["full_script"]
    native = deepcopy(receipt["output"])
    audit = contract.project_legacy_audit(native, script, brief, plan)
    decision = contract.decide_audit(audit, script, brief, plan)
    assert decision["status"] == "needs_whole_revision"
    assert "INITIAL_PROP_application" in codes(decision)
    assert any(c.startswith(("SOURCE_EVENT_", "SOURCE_ORDER_")) for c in codes(decision))
    assert native == receipt["output"]


def test_matching_occurrences_cannot_fabricate_two_strictly_ordered_refusals():
    brief, _, script, plan, _, _ = case_v5()
    extra = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "refusal"))
    extra["id"] = "second_refusal"
    plan["source_obligations"].append(extra)
    plan["source_order"].append({"before_id": "refusal", "after_id": "second_refusal", "fact_id": brief["facts"][0]["id"], "source_quote": brief["facts"][0]["text"]})
    audit = wire_checks(audit_v5(script, brief, plan))
    next(r for r in audit["obligation_evidence"] if r["obligation_id"] == "second_refusal")["occurrence_refs"] = ["E0005"]
    assert "SOURCE_ORDER_refusal_BEFORE_second_refusal" in codes(contract.decide_audit(audit, script, brief, plan))


def extract_for(script, brief, scope):
    projected = contract.project_sensitive_scope(scope, brief)
    return {"script_sha256": contract._digest(script), "brief_sha256": contract._digest(brief),
        "scope_sha256": contract._digest(scope),
        "category_extracts": [{"category": category, "claims": []} for category in projected["protected_categories"]],
        "dialogue_findings": [], "unknown_items": [],
        "step_coverage": [{"source_ref": ref, "claim_ids": [], "dialogue_finding_ids": [], "unknown_ids": []}
                          for ref in contract.evidence_catalog(script)]}


def add_claim(extract, category, row):
    next(r for r in extract["category_extracts"] if r["category"] == category)["claims"].append(row)
    next(r for r in extract["step_coverage"] if r["source_ref"] == row["source_ref"])["claim_ids"].append(row["id"])


def unsupported_claim(id_, ref, quote, value, type_, actor):
    return {"id": id_, "source_ref": ref, "quote": quote, "actor_id": actor,
        "attribute_type": type_, "attribute_value": value, "modality": "assertion",
        "source_alignment": {"status": "unsupported", "allowance_id": "", "source_attribute_quote": "",
            "source_attribute_type": "none", "explanation": "冻结源没有这一具体业务属性；测试只验证此明确判断的路由。"}}


def restricted_scope(brief):
    source = scope_for(brief)
    fact = brief["facts"][0]
    for category in ["employment_departure_timing", "follow_up_undertaking", "procedural_action"]:
        id_ = "restriction_" + category
        source["restrictions"].append({"id": id_, "category": category, "source_fact_ids": [fact["id"]],
            "source_quotes": [{"fact_id": fact["id"], "quote": fact["text"]}], "mode": "forbid_new"})
        source["source_fact_coverage"][0]["restriction_ids"].append(id_)
    return source


def test_actual_sourced_refusal_paper_and_exhale_are_not_prose_exact_whitelist_attributes():
    brief, script, _, _, _, scope = actual_case()
    before = deepcopy(scope)
    projected = contract.project_sensitive_scope(scope, brief)
    assert scope == before and projected["scope_sha256"] == contract._digest(scope)
    assert not {"company_decision", "employee_intention", "document_fact", "performance_action", "procedural_action"}.intersection(projected["protected_categories"])
    # These actual valid source properties are positive only for this sparse gate.
    catalog = contract.evidence_catalog(script)
    assert "公司这边的意思已经定了" in catalog["E0002"]["quote"]
    assert "这张我不签" in catalog["E0017"]["quote"]
    assert "纸和笔一起取回" in catalog["E0029"]["quote"]
    assert "呼出一口气" in catalog["E0032"]["quote"]
    assert contract.decide_fact_scope_extract(extract_for(script, brief, scope), script, brief, scope)["status"] == "text_ready_for_director"


def test_actual_broad_source_ban_protects_unclassified_payment_and_all_business_attributes():
    brief, script, _, _, _, scope = actual_case()
    projected = contract.project_sensitive_scope(scope, brief)
    assert set(projected["protected_categories"]) == set(contract.ATTRIBUTE_TYPES)
    source = deepcopy(scope)
    extract = extract_for(script, brief, scope)
    # The model may submit category tables in a different order, once each.
    extract["category_extracts"].reverse()
    assert contract.validate_fact_scope_extract(extract, script, brief, scope)["complete"] is True
    assert source == scope


@pytest.mark.parametrize("ref,quote,value,category,type_", [
    ("E0013", "手续一签就了了", "一签就了了", "business_procedure", "business_completion"),
    ("E0021", "剩下的我跟公司那边再慢慢说", "我跟公司那边再慢慢说", "follow_up_undertaking", "future_business_action"),
])
def test_actual_457_embedded_sensitive_properties_are_not_hidden_by_outer_request(ref, quote, value, category, type_):
    brief, script, _, _, _, scope = actual_case()
    extract = extract_for(script, brief, scope)
    add_claim(extract, category, unsupported_claim("sensitive", ref, quote, value, type_, "zhou"))
    decision = contract.decide_fact_scope_extract(extract, script, brief, scope)
    assert decision["status"] == "needs_whole_revision" and "FACT_SCOPE_sensitive" in codes(decision)


def test_actual_453_relative_departure_attribute_cannot_hide_in_company_decision():
    brief, _, _, _, _, scope = actual_case()
    script = read(ACTUAL / "versions/02/FULL_SCRIPT.json")
    extract = extract_for(script, brief, scope)
    add_claim(extract, "employment_departure_timing", unsupported_claim("deadline", "E0002", "让你从这个月底走", "这个月底", "departure_time", "company"))
    assert "FACT_SCOPE_deadline" in codes(contract.decide_fact_scope_extract(extract, script, brief, scope))


def test_source_personal_plea_does_not_authorize_future_business_undertaking():
    brief, script, _, _, _, scope = actual_case()
    extract = extract_for(script, brief, scope)
    row = unsupported_claim("promise", "E0021", "剩下的我跟公司那边再慢慢说", "我跟公司那边再慢慢说", "future_business_action", "zhou")
    allowance = next(r for r in scope["allowed_claims"] if r["id"] == "A6")
    row["source_alignment"].update(status="supported", allowance_id="A6", source_attribute_quote=allowance["value"], source_attribute_type="context")
    add_claim(extract, "follow_up_undertaking", row)
    assert "FACT_SCOPE_promise" in codes(contract.decide_fact_scope_extract(extract, script, brief, scope))


@pytest.mark.parametrize("change", ["missing_category", "missing_step", "invented_attribute", "fake_source_quote", "unknown"])
def test_sensitive_coverage_evidence_and_unknown_remain_strict(change):
    brief, script, _, _, _, scope = actual_case()
    extract = extract_for(script, brief, scope)
    row = unsupported_claim("promise", "E0021", "剩下的我跟公司那边再慢慢说", "我跟公司那边再慢慢说", "future_business_action", "zhou")
    if change == "missing_category": extract["category_extracts"].pop()
    elif change == "missing_step": extract["step_coverage"].pop()
    elif change == "invented_attribute":
        row["attribute_value"] = "原文没有的未来动作"
        add_claim(extract, "follow_up_undertaking", row)
    elif change == "fake_source_quote":
        row["source_alignment"].update(status="supported", allowance_id="A6", source_attribute_quote="不存在的源许可", source_attribute_type="future_business_action")
        add_claim(extract, "follow_up_undertaking", row)
    else:
        row["source_alignment"].update(status="unknown", source_attribute_type="unknown")
        add_claim(extract, "follow_up_undertaking", row)
        assert contract.decide_fact_scope_extract(extract, script, brief, scope)["status"] == "halt_review_uncertain"
        return
    with pytest.raises(ValueError):
        contract.validate_fact_scope_extract(extract, script, brief, scope)


def test_one_utterance_can_expose_two_independent_protected_attributes():
    brief, raw, _, _, _, _ = case_v5()
    raw["beats"][0]["steps"][0]["text"] = "公司让你这个月底走，签了我明天去送表。"
    script = contract.compile_script(raw, brief)
    scope = contract.compile_source_fact_scope(restricted_scope(brief), brief)
    extract = extract_for(script, brief, scope)
    add_claim(extract, "employment_departure_timing", unsupported_claim("date", "E0001", "公司让你这个月底走", "这个月底", "departure_time", "company"))
    add_claim(extract, "follow_up_undertaking", unsupported_claim("promise", "E0001", "签了我明天去送表", "明天去送表", "future_business_action", "hr"))
    assert {"FACT_SCOPE_date", "FACT_SCOPE_promise"}.issubset(codes(contract.decide_fact_scope_extract(extract, script, brief, scope)))


@pytest.mark.parametrize("category,type_,source_value,actual_value", [
    ("employment_departure_timing", "departure_time", "11日", "1日"),
    ("wage_or_payment", "payment_amount", "1000", "100"),
])
def test_literal_business_value_is_equal_not_substring(category, type_, source_value, actual_value):
    brief, raw, _, _, _, _ = case_v5()
    fact = brief["facts"][0]
    fact["text"] = "公司明确安排" + source_value + "。"
    brief["facts"].append({"id": "business_limits", "text": "不增加其他日期或金额。"})
    raw["beats"][0]["steps"][0]["text"] = "公司明确安排" + actual_value + "。"
    script = contract.compile_script(raw, brief)
    source = scope_for(brief)
    source["allowed_claims"] = [r for r in source["allowed_claims"] if r["id"] != "allow_business_limits"]
    source["restrictions"].append({"id": "restriction_literal", "category": category, "source_fact_ids": ["business_limits"],
        "source_quotes": [{"fact_id": "business_limits", "quote": "不增加其他日期或金额。"}], "mode": "forbid_new"})
    source["source_fact_coverage"][-1].update(allowed_claim_ids=[], restriction_ids=["restriction_literal"])
    source["allowed_claims"].append({"id": "literal", "category": category, "actor_id": "company", "value": source_value,
        "source_fact_ids": [fact["id"]], "source_quotes": [{"fact_id": fact["id"], "quote": fact["text"]}]})
    source["source_fact_coverage"][0]["allowed_claim_ids"].append("literal")
    scope = contract.compile_source_fact_scope(source, brief)
    extract = extract_for(script, brief, scope)
    row = unsupported_claim("literal", "E0001", raw["beats"][0]["steps"][0]["text"], actual_value, type_, "company")
    row["source_alignment"].update(status="supported", allowance_id="literal", source_attribute_quote=source_value, source_attribute_type=type_)
    add_claim(extract, category, row)
    assert "FACT_SCOPE_literal" in codes(contract.decide_fact_scope_extract(extract, script, brief, scope))


@pytest.fixture
def resume_workspace_v9(resume_workspace_v8):
    from scripts import run_autonomous_text_pipeline_v9 as runner
    _, root, parent, brief, script, plan, _ = resume_workspace_v8
    ledger = read(parent / "CALL_LEDGER.json")
    manifest = read(root / "RESUME_RECEIPTS.json")
    tokens = [5074, 12631, 14930, 14524, 17427, 12529, 15002, 14356, 17329, 12098]
    outputs = {451: restricted_scope(brief), 457: {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"},
               458: wire_checks(review_v2(script, brief)), 459: wire_checks(audit_v5(script, brief, plan))}
    labels = {451: "factual_scope_source", 457: "whole_draft_03", 458: "whole_review_03", 459: "literal_audit_03"}
    keys = {451: "scope_source", 457: "draft", 458: "review", 459: "audit"}
    for ordinal in range(451, 461):
        receipt = {"ordinal": ordinal, "label": labels.get(ordinal, "completed_native_fixture"), "status": "contract_valid",
            "output": outputs.get(ordinal, {"routing_fixture": True}),
            "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": tokens[ordinal - 451]}}
        path = parent / f"call_{ordinal}_{receipt['label']}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger["calls"].append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": sha})
        if ordinal in keys:
            manifest["receipts"][keys[ordinal]] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": ordinal}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    setup = read(root / "SETUP.json")
    setup.update(max_full_drafts=4, inherited_full_draft_versions=3, max_automatic_content_revisions=1,
                 revision_context_policy="reconstruct_from_frozen_sources")
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    yield runner, root, parent, brief, script, plan


class MockV9:
    def __init__(self, brief, script, plan, *, unknown_at=None, always_bad=False):
        self.brief, self.script, self.plan = deepcopy(brief), deepcopy(script), deepcopy(plan)
        self.requests, self.extracts = [], 0
        self.unknown_at, self.always_bad = unknown_at, always_bad

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "payload": deepcopy(payload)})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "category_extracts" in properties:
            self.extracts += 1
            script, scope = payload["full_current_script"], payload["source_fact_scope"]
            output = extract_for(script, self.brief, scope)
            if self.extracts == 1 or self.always_bad:
                add_claim(output, "employment_departure_timing", unsupported_claim("date", "E0001", "这个月底走", "这个月底", "departure_time", "hr"))
        elif "literal_events" in properties:
            output = wire_checks(audit_v5(payload["full_current_script"], self.brief, self.plan))
        elif "dialogue_readings" in properties:
            output = wire_checks(review_v2(payload["full_current_script"], self.brief))
        else:
            output = {k: deepcopy(v) for k, v in self.script.items() if k != "selected_candidate_id"}
            output["title"] = "新模型完整第4稿"
            if not self.always_bad:
                output["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开。"
            for i, beat in enumerate(output["beats"]):
                beat["id"] = "COMPLETE_FOURTH_" + str(i)
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True,
            "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v9_mock_" + str(ordinal),
            "total_tokens": 100}, response_payload={"mock": True})


def test_inherited_three_native_drafts_allow_only_one_complete_new_draft_and_no_respend(resume_workspace_v9):
    runner, root, parent, brief, script, plan = resume_workspace_v9
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV9(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director", result
    assert result["full_draft_versions"] == 4 and len(service.requests) == 5
    rewrite = service.requests[1]["payload"]
    assert "previous_complete_script" not in rewrite
    assert rewrite["previous_complete_script_sha256"] == contract._digest(script)
    assert rewrite["brief"] == brief and rewrite["reference_fulltext"]
    assert [r["role"] for r in service.requests] == ["director", "writer", "director", "director", "director"]
    native = read(root / "DELIVERABLE/RAW_MODEL_SCRIPT.json")
    assert all(b["id"].startswith("COMPLETE_FOURTH_") for b in native["beats"])
    assert result["spend"]["effective_calls_started"] == 465
    assert result["spend"]["effective_reported_tokens"] == 7113457
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert result["spend"]["old_budget_reset"] is False
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert not list(root.rglob("*human_decision*")) and not list(root.rglob("*assistant_decision*"))
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 5


@pytest.mark.parametrize("unknown_at", [1, 2])
def test_new_scope_or_writer_unknown_stops_without_dispatching_or_clearing_history(unknown_at, resume_workspace_v9):
    runner, root, _, brief, script, plan = resume_workspace_v9
    service = MockV9(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 460 + unknown_at
    assert result["spend"]["unknown_token_reservations"] > 93117
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == unknown_at


def test_one_new_complete_draft_limit_does_not_reset_after_failed_fourth(resume_workspace_v9):
    runner, root, _, brief, script, plan = resume_workspace_v9
    service = MockV9(brief, script, plan, always_bad=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "creative_stalled" and result["full_draft_versions"] == 4
    assert len(service.requests) == 5 and sum(r["role"] == "writer" for r in service.requests) == 1
    assert result["spend"]["effective_calls_started"] == 465
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 5
