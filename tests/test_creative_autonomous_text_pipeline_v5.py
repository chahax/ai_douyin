"""Focused typed-initial-state and source/evidence-role regressions.

No provider/media call; mock pass judgments are routing input, not quality gold.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v5 as contract
from tests.test_creative_autonomous_text_pipeline_v2 import review_v2
from tests.test_creative_autonomous_text_pipeline_v3 import (
    source_case, plan_v3, pipeline_workspace_v2, pipeline_workspace_v3, codes,
)
from tests.test_creative_autonomous_text_pipeline_v4 import audit_v4


def plan_v5(script, brief):
    plan = plan_v3(script, brief)
    facts = {r["id"]: r["text"] for r in brief["facts"]}
    for edge in plan["source_order"]:
        edge.update(fact_id=brief["facts"][0]["id"], source_quote=brief["facts"][0]["text"])
    plan["initial_conditions"] = []
    for kind, table in [("character", "character_states"), ("prop", "prop_states")]:
        for row in brief["initial_state"][table]:
            item = {"entity_type": kind, "entity_id": row["id"], "source_quote": row["expected_state"],
                    "relation": "unspecified", "anchor_type": "unspecified", "anchor_id": "", "orientation": "unspecified"}
            if row["id"] == "application":
                item.update(relation="on_surface", anchor_type="character", anchor_id=brief["characters"][-1]["id"], orientation="face_up")
            plan["initial_conditions"].append(item)
    return plan


def source_audit_v5(plan, brief):
    facts = {r["id"]: r["text"] for r in brief["facts"]}
    common = {"status": "pass", "explanation": "源检查路由夹具，不代表真实语义判定。", "required_revision": ""}
    return {"brief_sha256": contract._digest(brief), "plan_sha256": contract._digest(plan),
            "fact_coverage_checks": [{**common, "fact_id": fact, "source_quote": text,
                "obligation_ids": [r["id"] for r in plan["source_obligations"] if r["fact_id"] == fact]} for fact, text in facts.items()],
            "source_obligation_checks": [{**common, "obligation_id": r["id"], "source_quote": facts[r["fact_id"]]} for r in plan["source_obligations"]],
            "initial_condition_checks": [{**common, "entity_type": r["entity_type"], "entity_id": r["entity_id"], "source_quote": r["source_quote"]} for r in plan["initial_conditions"]],
            "source_order_checks": [{**common, **edge} for edge in plan["source_order"]]}


def audit_v5(script, brief, plan):
    value = audit_v4(script, brief, plan)
    value["plan_sha256"] = contract._digest(plan)
    for proof in value["obligation_evidence"]:
        proof["occurrence_refs"] = proof.pop("actual_refs")
        proof["support_refs"] = []
    value["actual_initial_conditions"] = []
    for row in plan["initial_conditions"]:
        item = {k: deepcopy(v) for k, v in row.items() if k != "source_quote"}
        item.update(status="known", observed_state="当前动作发生前的来源声明状态；路由夹具。", evidence_refs=["E0001"])
        value["actual_initial_conditions"].append(item)
    return value


def case_v5():
    brief, raw, script, _, review, _ = source_case()
    plan = plan_v5(script, brief)
    return brief, raw, script, plan, review, audit_v5(script, brief, plan)


def proof(audit, id_):
    return next(r for r in audit["obligation_evidence"] if r["obligation_id"] == id_)


@pytest.mark.parametrize("change", ["orientation", "container"])
def test_initial_physical_mismatch_cannot_be_hidden_by_legacy_all_pass(change):
    brief, _, script, plan, review, audit = case_v5()
    row = next(r for r in audit["actual_initial_conditions"] if r["entity_id"] == "application")
    if change == "orientation":
        row["orientation"] = "face_down"
    else:
        row.update(relation="inside_container", anchor_type="prop", anchor_id="folder")
    assert all(r["status"] == "pass" for r in audit["initial_state_checks"])
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision" and "INITIAL_PROP_application" in codes(result)


def test_initial_physical_unknown_does_not_become_pass_from_legacy_row():
    brief, _, script, plan, review, audit = case_v5()
    next(r for r in audit["actual_initial_conditions"] if r["entity_id"] == "application")["status"] = "unknown"
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "halt_review_uncertain"


def test_trigger_and_listener_outcome_support_do_not_become_action_actor_or_order():
    brief, _, script, plan, review, audit = case_v5()
    proof(audit, "collect")["support_refs"] = ["E0005", "E0003"]
    proof(audit, "refusal")["support_refs"] = ["E0004", "E0006"]
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "text_ready_for_director"


def test_only_support_without_occurrence_does_not_fill_missing_event():
    brief, _, script, plan, review, audit = case_v5()
    proof(audit, "refusal").update(occurrence_refs=[], support_refs=["E0003", "E0004"])
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision" and "SOURCE_EVENT_refusal" in codes(result)


def test_same_request_may_share_occurrence_and_support_without_extra_event():
    brief, _, script, plan, review, audit = case_v5()
    request = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "notice"))
    request.update(id="same_request_purpose", allowed_speech_functions=["request"])
    plan["source_obligations"].append(request)
    audit = audit_v5(script, brief, plan)
    proof(audit, "same_request_purpose").update(occurrence_refs=["E0001"], support_refs=["E0003"])
    audit["literal_events"][0]["speech_functions"] = ["statement", "request"]
    assert contract.combine_decisions(review, audit, script, brief, plan)["status"] == "text_ready_for_director"


def test_required_two_refusals_cannot_share_one_occurrence_even_with_support():
    brief, _, script, plan, _, _ = case_v5()
    row = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "refusal"))
    row["id"] = "refusal_after_change"
    plan["source_obligations"].append(row)
    plan["source_order"].append({"before_id": "refusal", "after_id": "refusal_after_change", "fact_id": brief["facts"][0]["id"], "source_quote": brief["facts"][0]["text"]})
    audit = audit_v5(script, brief, plan)
    proof(audit, "refusal_after_change").update(occurrence_refs=["E0005"], support_refs=["E0006"])
    result = contract.decide_audit(audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert "SOURCE_ORDER_refusal_BEFORE_refusal_after_change" in codes(result)


def test_real_441_legacy_pass_cannot_override_explicit_before_state_atoms():
    receipt = Path(__file__).resolve().parents[1] / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_04/call_441_literal_gate_regression_probe.json"
    source = json.loads(receipt.read_text(encoding="utf-8"))
    native = next(r for r in source["output"]["initial_state_checks"] if r["entity_id"] == "application")
    assert native["status"] == "pass" and "面朝下" in native["observed_state"] and "文件夹内" in native["observed_state"]
    brief, _, script, plan, review, audit = case_v5()
    legacy = next(r for r in audit["initial_state_checks"] if r["entity_id"] == "application")
    legacy.update(status=native["status"], observed_state=native["observed_state"])
    actual = next(r for r in audit["actual_initial_conditions"] if r["entity_id"] == "application")
    actual.update(relation="inside_container", anchor_type="prop", anchor_id="folder", orientation="face_down", observed_state=native["observed_state"])
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision" and "INITIAL_PROP_application" in codes(result)


def compound_clause_case():
    brief, raw, _, _, _, _ = case_v5()
    raw["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开，麻烦你签一下。"
    script = contract.compile_script(raw, brief)
    plan = plan_v5(script, brief)
    request = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "notice"))
    request.update(id="request_after_notice", allowed_speech_functions=["request"])
    plan["source_obligations"].append(request)
    plan["source_order"].append({"before_id": "notice", "after_id": "request_after_notice", "fact_id": brief["facts"][0]["id"], "source_quote": brief["facts"][0]["text"]})
    audit = audit_v5(script, brief, plan)
    audit["literal_events"][0]["speech_functions"] = ["statement", "request"]
    proof(audit, "notice")["occurrence_spans"] = [{"ref_id": "E0001", "quote": "公司让我通知你，这次要你离开"}]
    proof(audit, "request_after_notice").update(occurrence_refs=["E0001"], occurrence_spans=[{"ref_id": "E0001", "quote": "麻烦你签一下"}])
    return brief, raw, script, plan, audit


@pytest.mark.parametrize("overlap", [False, True])
def test_same_dialogue_nonoverlapping_clauses_allow_order_but_overlap_does_not(overlap):
    brief, _, script, plan, audit = compound_clause_case()
    if overlap:
        proof(audit, "notice")["occurrence_spans"][0]["quote"] = script["beats"][0]["steps"][0]["text"]
    result = contract.decide_audit(audit, script, brief, plan)
    if overlap:
        assert result["status"] == "needs_whole_revision" and "SOURCE_ORDER_notice_BEFORE_request_after_notice" in codes(result)
    else:
        assert result["status"] == "text_ready_for_director"


def test_occurrence_span_with_repeated_original_substring_is_uncertain_not_guessed():
    brief, raw, _, plan, _ = compound_clause_case()
    raw["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开，麻烦你签一下。麻烦你签一下。"
    script = contract.compile_script(raw, brief)
    audit = audit_v5(script, brief, plan)
    audit["literal_events"][0]["speech_functions"] = ["statement", "request"]
    proof(audit, "request_after_notice").update(occurrence_refs=["E0001"], occurrence_spans=[{"ref_id": "E0001", "quote": "麻烦你签一下"}])
    with pytest.raises(ValueError):
        contract.validate_audit(audit, script, brief, plan)


@pytest.mark.parametrize("table", ["fact_coverage_checks", "source_obligation_checks", "initial_condition_checks", "source_order_checks"])
def test_source_audit_requires_every_frozen_table_row(table):
    brief, _, _, plan, _, _ = case_v5()
    audit = source_audit_v5(plan, brief)
    audit[table].pop()
    with pytest.raises(ValueError):
        contract.validate_source_audit(audit, plan, brief)


@pytest.mark.parametrize("status,expected", [("fail", "needs_whole_plan_revision"), ("unknown", "halt_source_uncertain")])
def test_source_order_review_controls_plan_revision_or_halt(status, expected):
    brief, _, _, plan, _, _ = case_v5()
    audit = source_audit_v5(plan, brief)
    audit["source_order_checks"][0].update(status=status, explanation="来源仅有同一请求，不支持强加两次严格先后。", required_revision="生成模型重新提交完整源计划，不能新增源要求。")
    assert contract.decide_source_audit(audit, plan, brief)["status"] == expected


@pytest.mark.parametrize("target", ["plan_initial", "audit_order_quote", "audit_plan_sha"])
def test_source_binding_cannot_be_rewritten_or_fabricated(target):
    brief, _, _, plan, _, _ = case_v5()
    audit = source_audit_v5(plan, brief)
    if target == "plan_initial":
        plan["initial_conditions"][0]["source_quote"] = "不存在于来源的引用"
        with pytest.raises(ValueError):
            contract.validate_plan(plan, brief)
    else:
        if target == "audit_order_quote":
            audit["source_order_checks"][0]["source_quote"] = "另一个来源说法"
        else:
            audit["plan_sha256"] = "0" * 64
        with pytest.raises(ValueError):
            contract.validate_source_audit(audit, plan, brief)


@pytest.fixture
def pipeline_workspace_v5(pipeline_workspace_v3):
    from scripts import run_autonomous_text_pipeline_v5 as runner
    _, root, parent, brief, raw, script = pipeline_workspace_v3
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    ledger["starting_spend"].update(calls_started=441, reported_tokens=6871952, calls_with_known_usage=439)
    auth = {"schema": "authorized_creative_continuation/v3", "starting_spend": ledger["starting_spend"], "max_total_tokens": None, "old_budget_reset": False}
    (parent / "AUTHORIZATION.json").write_text(json.dumps(auth), encoding="utf-8")
    ledger["authorization_sha256"] = hashlib.sha256((parent / "AUTHORIZATION.json").read_bytes()).hexdigest()
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    yield runner, root, parent, brief, raw, script


class MockV5:
    def __init__(self, brief, raw, *, first_source_fail=True, source_unknown=False, unknown_at=None, usage_unknown_at=None):
        self.brief, self.raw = deepcopy(brief), deepcopy(raw)
        self.first_source_fail, self.source_unknown = first_source_fail, source_unknown
        self.unknown_at, self.usage_unknown_at = unknown_at, usage_unknown_at
        self.requests = []
        self.plans = self.source_audits = 0

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "payload": deepcopy(payload), "schema": deepcopy(kwargs["structured_schema"])})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "fact_coverage_checks" in properties:
            self.source_audits += 1
            output = source_audit_v5(payload["full_source_plan"], self.brief)
            if self.first_source_fail and self.source_audits == 1:
                output["source_order_checks"][0].update(status="fail", explanation="首次计划加入来源不要求的严格关系。", required_revision="整份新计划只保留来源支持的关系。")
            if self.source_unknown:
                output["source_order_checks"][0]["status"] = "unknown"
        elif "literal_events" in properties:
            plan = self.requests[next(i for i, r in enumerate(self.requests) if "full_source_plan" in r["payload"] and i > 1)]["payload"]["full_source_plan"] if self.first_source_fail else next(r["payload"]["full_source_plan"] for r in self.requests if "full_source_plan" in r["payload"])
            output = audit_v5(payload["full_current_script"], self.brief, plan)
        elif "dialogue_readings" in properties:
            output = review_v2(payload["full_current_script"], self.brief)
        elif "scene_plan" in payload:
            output = deepcopy(self.raw)
        else:
            self.plans += 1
            output = plan_v5(contract.compile_script(self.raw, self.brief), self.brief)
            if self.plans > 1:
                output["title"] = "完整新源计划"
                for i, beat in enumerate(output["beats"]):
                    beat["id"] = "SOURCE_NEW_" + str(i)
        metadata = {"finish_reason": "tool_calls", "output_mode": "tool_call", "total_tokens": 100,
                    "response_id": "v5_mock_" + str(ordinal), "response_body_complete": True}
        if ordinal == self.usage_unknown_at:
            metadata.pop("total_tokens")
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=metadata, response_payload={"mock": True})


def test_source_audit_fail_runs_complete_new_plan_then_body_and_both_checks_without_manual_gate(pipeline_workspace_v5):
    runner, root, parent, brief, raw, script = pipeline_workspace_v5
    parent_before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV5(brief, raw)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and len(service.requests) == 7
    assert service.plans == service.source_audits == 2
    first = json.loads((root / "plan_versions" / "01" / "SOURCE_DECISION.json").read_text(encoding="utf-8"))
    assert first["status"] == "needs_whole_plan_revision"
    assert service.requests[2]["payload"]["previous_complete_plan"] == service.requests[1]["payload"]["full_source_plan"]
    assert service.requests[2]["payload"]["plan_revision_requirement"] == first
    second = service.requests[3]["payload"]["full_source_plan"]
    assert all(b["id"].startswith("SOURCE_NEW_") for b in second["beats"])
    assert service.requests[4]["payload"]["scene_plan"] == second
    assert json.loads((root / "SCENE_PLAN.json").read_text(encoding="utf-8")) == second
    assert json.loads((root / "DELIVERABLE" / "FULL_SCRIPT.json").read_text(encoding="utf-8")) == script
    assert (root / "DELIVERABLE" / "SOURCE_CONTRACT_AUDIT.json").exists()
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert result["spend"]["effective_calls_started"] == 448 and result["spend"]["effective_reported_tokens"] == 6872652
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert (parent / "CALL_LEDGER.json").read_bytes() == parent_before
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == result["status"] and len(service.requests) == 7


@pytest.mark.parametrize("unknown_at", [2, 5])
def test_source_or_literal_unknown_outcome_stops_and_resume_does_not_redispatch(unknown_at, pipeline_workspace_v5):
    runner, root, _, brief, raw, _ = pipeline_workspace_v5
    service = MockV5(brief, raw, first_source_fail=False, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == result["status"] and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 441 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 6871952 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117 and result["spend"]["old_budget_reset"] is False
    assert not (root / "DELIVERABLE").exists()


@pytest.mark.parametrize("kind", ["quality_unknown", "usage_unknown"])
def test_source_audit_unknown_does_not_dispatch_new_plan_or_body(kind, pipeline_workspace_v5):
    runner, root, _, brief, raw, _ = pipeline_workspace_v5
    service = MockV5(brief, raw, first_source_fail=False, source_unknown=kind == "quality_unknown", usage_unknown_at=2 if kind == "usage_unknown" else None)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == ("halt_source_uncertain" if kind == "quality_unknown" else "halt_usage_unknown")
    assert len(service.requests) == 2 and not (root / "DELIVERABLE").exists()


def test_all_five_contract_dependencies_are_explicitly_frozen(pipeline_workspace_v5):
    runner, root, _, _, _, _ = pipeline_workspace_v5
    runner.Pipeline(root).prepare()
    ledger = json.loads((root / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    for version in [1, 2, 3, 4, 5]:
        assert f"src/content_factory/creative_autonomous_text_contract_v{version}.py" in ledger["source_manifest"]
