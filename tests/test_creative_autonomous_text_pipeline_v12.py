"""Focused source-time sidecar regression; no semantic or creative gold mocks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v12 as contract
from tests.test_creative_autonomous_text_pipeline_v11 import (
    read, codes, resume_workspace_v11, resume_workspace_v10, resume_workspace_v9,
    resume_workspace_v8, resume_workspace_v7, pipeline_workspace_v6, pipeline_workspace_v5,
    pipeline_workspace_v3, pipeline_workspace_v2, MockV11, extract_for, adjudication_for,
    unsupported_claim, add_claim, wire_checks, review_v2, audit_v5,
)
from tests.test_creative_autonomous_text_pipeline_v10 import subset

PROJECT = Path(__file__).resolve().parents[1]
ROOT11 = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_11"


def temporal_for(plan, brief):
    """Test classification, explicitly not a production semantic decision."""
    facts = {row["id"]: row["text"] for row in brief["facts"]}
    return {"brief_sha256": contract._digest(brief), "plan_sha256": contract._digest(plan),
        "obligations": [{"obligation_id": row["id"], "fact_id": row["fact_id"],
            "temporal_mode": "invariant" if row["id"] == "SO11" or row["mode"] == "state" else
                "absence" if row["mode"] == "absence" else "one_off",
            "source_quote": facts[row["fact_id"]],
            "explanation": "仅供离线分类属性测试；持续约束不当一次发生，真实服务须独立从来源判断。"}
            for row in plan["source_obligations"]]}


def actual_469():
    brief = read(ROOT11 / "INPUT.json")["brief"]
    plan = read(ROOT11 / "SCENE_PLAN.json")
    script = read(ROOT11 / "versions/04/FULL_SCRIPT.json")
    review = read(ROOT11 / "call_466_whole_review_04.json")["output"]
    audit = read(ROOT11 / "call_467_literal_audit_04.json")["output"]
    extract = read(ROOT11 / "call_468_factual_scope_extract_04.json")["output"]
    verdict = read(ROOT11 / "call_469_finding_adjudication_04.json")["output"]
    scope = read(ROOT11 / "SOURCE_FACT_SCOPE.json")
    return brief, script, plan, review, audit, extract, verdict, scope


@pytest.mark.parametrize("change", ["missing_id", "duplicate_id", "wrong_plan", "wrong_brief", "fake_quote", "wrong_fact"])
def test_source_time_sidecar_requires_all_original_ids_hashes_and_true_source_fragments(change):
    brief, _, plan, *_ = actual_469()
    temporal = temporal_for(plan, brief)
    if change == "missing_id": temporal["obligations"].pop()
    elif change == "duplicate_id": temporal["obligations"][-1] = deepcopy(temporal["obligations"][0])
    elif change == "wrong_plan": temporal["plan_sha256"] = "0" * 64
    elif change == "wrong_brief": temporal["brief_sha256"] = "0" * 64
    elif change == "fake_quote": temporal["obligations"][0]["source_quote"] = "原文没有的后续承诺"
    else: temporal["obligations"][0]["fact_id"] = "F4"
    with pytest.raises(ValueError):
        contract.validate_temporal_scope(temporal, plan, brief)


def test_actual_negative_invariant_removes_only_false_so9_so11_order_and_preserves_four_business_failures():
    brief, script, plan, review, audit, extract, verdict, scope = actual_469()
    originals = deepcopy((script, plan, audit, extract, verdict))
    old = contract.prior.combine_adjudicated_decisions(review, audit, extract, verdict, script, brief, plan, scope)
    assert "SOURCE_ORDER_SO9_BEFORE_SO11" in codes(old)
    temporal = temporal_for(plan, brief)
    result = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal)
    assert "SOURCE_ORDER_SO9_BEFORE_SO11" not in codes(result)
    assert {"FACT_SCOPE_C-EDT-01", "FACT_SCOPE_C-FUU-01", "FACT_SCOPE_C-BP-01", "FACT_SCOPE_C-BP-02"}.issubset(codes(result))
    assert result["status"] == "needs_whole_revision"
    report = result["derived_temporal_order_evidence"]
    assert {r["code"] for r in report["inapplicable_strict_order_findings"]} == {"SOURCE_ORDER_SO9_BEFORE_SO11"}
    assert (script, plan, audit, extract, verdict) == originals


@pytest.mark.parametrize("obligation,refs,required_code", [
    ("SO8", ["E0009"], "SOURCE_ORDER_SO7_BEFORE_SO8"),
    ("SO7", ["E0003"], "SOURCE_ORDER_SO6_BEFORE_SO7"),
])
def test_two_oneoff_refusals_and_private_request_retain_strict_source_order(obligation, refs, required_code):
    brief, script, plan, review, audit, extract, verdict, scope = actual_469()
    proof = next(r for r in audit["obligation_evidence"] if r["obligation_id"] == obligation)
    proof["occurrence_refs"] = refs
    proof.pop("occurrence_spans", None)
    result = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal_for(plan, brief))
    assert required_code in codes(result) and result["status"] == "needs_whole_revision"


def test_invariant_does_not_remove_explicit_native_fact_failure_or_initial_state_failure():
    brief, script, plan, review, audit, extract, verdict, scope = actual_469()
    fact = next(r for r in audit["fact_checks"] if r["fact_id"] == "F4")
    fact.update(status="fail", observed_fact="模拟实际拿笔签字，与持续未签的来源相反。", required_revision="由生成模型整稿修复持续约束，不本地拼接动作。")
    next(r for r in audit["initial_state_checks"] if r["entity_id"] == "application").update(
        status="fail", observed_state="模拟起态不符。", required_revision="完整稿从源起态推进。")
    result = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal_for(plan, brief))
    assert {"FACT_F4", "INITIAL_PROP_application"}.issubset(codes(result))


def test_valid_unknown_source_time_stops_even_if_other_known_problems_exist():
    brief, script, plan, review, audit, extract, verdict, scope = actual_469()
    temporal = temporal_for(plan, brief)
    temporal["obligations"][0]["temporal_mode"] = "unknown"
    assert contract.validate_temporal_scope(temporal, plan, brief)["availability_unknown"]
    result = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal)
    assert result["status"] == "halt_source_uncertain" and result["source_temporal_uncertainties"]


def test_actual_language_exemption_cannot_borrow_source_story_to_invent_clear_actor():
    brief, script, plan, review, audit, extract, verdict, scope = actual_469()
    before = deepcopy((extract, verdict))
    result = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal_for(plan, brief))
    assert "LANGUAGE_SOURCE_DEPENDENT_D-01" in codes(result)
    assert result["status"] == "needs_whole_revision" and (extract, verdict) == before


def test_text_only_language_context_exemption_is_protocol_valid_without_source_story():
    brief, script, _, _, _, extract, verdict, scope = actual_469()
    extract = subset(extract, "D-01")
    verdict["extract_sha256"] = contract._digest(extract)
    verdict["findings"] = [r for r in verdict["findings"] if r["finding_id"] == "D-01"]
    verdict["findings"][0].update(source_evidence=[], source_attribute_quote="",
        explanation="仅检验纯正文上下文裁决可接受；此处模拟判断不是当前原句可读性的质量金标。")
    assert contract.decide_adjudication(verdict, extract, script, brief, scope)["status"] == "text_ready_for_director"


def test_writer_targets_do_not_transmit_diagnostic_quotes_or_false_exemption_explanations():
    from scripts.run_autonomous_text_pipeline_v12 import compile_writer_targets
    brief, script, plan, review, audit, extract, verdict, scope = actual_469()
    decision = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal_for(plan, brief))
    targets = compile_writer_targets(decision["revision_requirements"], extract)
    encoded = json.dumps(targets, ensure_ascii=False)
    assert targets["sensitive_finding_ids"] and all(r.get("attribute_type") for r in targets["sensitive_finding_ids"])
    assert "剩下的我跟公司那边再慢慢说" not in encoded
    assert "今天找我来办这件事的是我" not in encoded
    assert "原裁决解释" not in encoded and "evidence_refs" not in encoded
    assert "business_completion" in encoded and "future_business_action" in encoded


@pytest.fixture
def resume_workspace_v12(resume_workspace_v11):
    from scripts import run_autonomous_text_pipeline_v12 as runner
    _, root, parent, brief, script, plan, _, _ = resume_workspace_v11
    ledger, manifest = read(parent / "CALL_LEDGER.json"), read(root / "RESUME_RECEIPTS.json")
    raw = {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"}
    raw["title"] = "模拟完整第4稿，仍有未来承诺"
    script = contract.compile_script(raw, brief)
    source = read(manifest["receipts"]["scope_source"]["path"])["output"]
    scope = contract.compile_source_fact_scope(source, brief)
    extract = extract_for(script, brief, scope)
    add_claim(extract, "follow_up_undertaking", unsupported_claim("future04", "E0001",
        "签了我明天去送表", "明天去送表", "future_business_action", "hr"))
    verdict = adjudication_for(extract, script, brief, scope)
    outputs = [raw, wire_checks(review_v2(script, brief)), wire_checks(audit_v5(script, brief, plan)), extract, verdict]
    labels = ["whole_draft_04", "whole_review_04", "literal_audit_04", "factual_scope_extract_04", "finding_adjudication_04"]
    keys = ["draft", "review", "audit", "extract", "adjudication"]
    tokens = [9285, 13067, 14774, 16408, 13634]
    for ordinal, key, label, output, usage in zip(range(465, 470), keys, labels, outputs, tokens):
        receipt = {"ordinal": ordinal, "label": label, "status": "contract_valid", "output": output,
            "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": usage}}
        path = parent / f"call_{ordinal}_{label}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger["calls"].append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": sha})
        manifest["receipts"][key] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": ordinal}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    setup = read(root / "SETUP.json")
    setup.update(max_full_drafts=5, inherited_full_draft_versions=4, max_automatic_content_revisions=1, minimum_new_whole_drafts=1)
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    yield runner, root, parent, brief, script, plan


class MockV12(MockV11):
    def __init__(self, *args, semantic_source_unknown=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.semantic_source_unknown = semantic_source_unknown

    def call(self, role, messages, **kwargs):
        fields = kwargs["structured_schema"]["properties"]
        if "obligations" in fields:
            from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
            from src.content_factory.creative_workflow_roles import RoleResult
            payload = json.loads(messages[-1]["content"])
            self.requests.append({"role": role, "payload": deepcopy(payload)})
            if len(self.requests) == self.unknown_at:
                raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
            output = temporal_for(self.plan, self.brief)
            if self.semantic_source_unknown: output["obligations"][0]["temporal_mode"] = "unknown"
            return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True,
                "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v12_source_mock", "total_tokens": 100}, response_payload={"mock": True})
        result = super().call(role, messages, **kwargs)
        if role == "writer":
            from src.content_factory.creative_workflow_roles import RoleResult
            value = json.loads(result.text)
            value["title"] = "模型完整第5稿"
            for i, beat in enumerate(value["beats"]): beat["id"] = "COMPLETE_FIFTH_" + str(i)
            result = RoleResult(text=json.dumps(value, ensure_ascii=False), metadata=result.metadata,
                response_payload=result.response_payload)
        return result


def test_six_requests_one_source_then_complete_fifth_and_four_reviews_preserve_history_and_clean_writer_input(resume_workspace_v12):
    runner, root, parent, brief, script, plan = resume_workspace_v12
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV12(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 5, result
    assert [r["role"] for r in service.requests] == ["director", "writer", "director", "director", "director", "director"]
    source_input = service.requests[0]["payload"]
    assert not {"full_current_script", "original_detection", "adjudication", "expected_fail_codes"}.intersection(source_input)
    rewrite = service.requests[1]["payload"]
    assert set(rewrite["creative_scene_plan"]) == {"title", "dramatic_question", "audience_arc", "character_goals", "beats", "ending"}
    assert not {"scene_plan", "source_obligations", "source_order", "previous_complete_script", "revision_requirements"}.intersection(rewrite)
    assert rewrite["previous_complete_script_sha256"] == contract._digest(script) and rewrite["reference_fulltext"]
    assert rewrite["executable_revision_targets"]["sensitive_finding_ids"][0]["attribute_type"] == "future_business_action"
    assert "签了我明天去送表" not in json.dumps(rewrite, ensure_ascii=False)
    assert result["spend"]["effective_calls_started"] == 475
    assert result["spend"]["effective_reported_tokens"] == 7252712
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert all(b["id"].startswith("COMPLETE_FIFTH_") for b in read(root / "DELIVERABLE/RAW_MODEL_SCRIPT.json")["beats"])
    assert read(root / "DELIVERABLE/HANDOFF.json")["manual_assistant_gate_calls"] == 0
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 6


@pytest.mark.parametrize("unknown_at", [1, 2, 5])
def test_unknown_source_writer_or_extract_stops_before_later_dispatch_and_restart_reuses_identity(unknown_at, resume_workspace_v12):
    runner, root, _, brief, script, plan = resume_workspace_v12
    service = MockV12(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at, result
    assert result["spend"]["effective_calls_started"] == 469 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 7252112 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == unknown_at


def test_semantic_source_time_unknown_stops_without_any_writer(resume_workspace_v12):
    runner, root, _, brief, script, plan = resume_workspace_v12
    service = MockV12(brief, script, plan, semantic_source_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_source_uncertain" and len(service.requests) == 1, result
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 1
