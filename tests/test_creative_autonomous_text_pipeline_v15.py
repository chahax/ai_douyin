"""Focused actual-receipt acceptance and independent ending-gate routing.

Mock semantic findings are branch fixtures, not replacement production judgments.
Frozen v14 receipts, source and ledger are only read.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v13 as contract
from src.content_factory import creative_scene_plan_gate_v2 as scene_gate
from src.content_factory import creative_plan_ending_scope_v1 as ending_gate
from tests.test_creative_autonomous_text_pipeline_v14 import (
    MockV14, gate_for, resume_workspace_v14, resume_workspace_v12,
    resume_workspace_v11, resume_workspace_v10, resume_workspace_v9,
    resume_workspace_v8, resume_workspace_v7, pipeline_workspace_v6,
    pipeline_workspace_v5, pipeline_workspace_v3, pipeline_workspace_v2,
)
import hashlib


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def actual_case_v15():
    project = Path(__file__).resolve().parents[1]
    root = project / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_14"
    brief = read(root / "INPUT.json")["brief"]
    item = read(root / "RESUME_RECEIPTS.json")["receipts"]["plan"]
    plan = contract.compile_plan(read(item["path"])["output"], brief)
    receipt = read(root / "call_475_scene_gate_regression.json")
    return root, brief, plan, receipt


def ending_for(plan, brief, *, fail=False, unknown=False):
    value = {"plan_sha256": contract._digest(plan), "brief_sha256": contract._digest(brief),
        "creative_plan_sha256": contract._digest(ending_gate.creative_projection(plan)),
        "ending_fields": []}
    for field in ending_gate.FIELDS:
        value["ending_fields"].append({"field": field, "findings": [{"id": "mock_" + field,
            "quote": plan["ending"][field], "proposition": "模拟原生结尾命题判定，仅验证路由。",
            "proposition_mode": "asserted", "knowledge_type": "known_result",
            "source_relation": "compatible", "source_refs": [],
            "explanation": "模拟明确的来源相容判断，不是质量金标。", "required_revision": ""}]})
    if fail:
        finding = value["ending_fields"][-1]["findings"][0]
        fact = brief["facts"][0]
        fragment = "小林的离开决定是哪一方提出"
        finding.update(quote=fragment if fragment in plan["ending"]["open_problem"] else plan["ending"]["open_problem"], proposition="结尾把已确定的公司决定施事恢复为未知。",
            proposition_mode="questioned", knowledge_type="unknown_fact", source_relation="contradicted",
            source_refs=[{"fact_id": fact["id"], "quote": fact["text"]}],
            explanation="本路由输入显式报告的结尾知识状态矛盾，不能由另一门allpass覆盖。",
            required_revision="生成完整新计划，保持已知公司决定，只保留未解决的争议。")
    if unknown:
        value["ending_fields"][0]["findings"][0].update(source_relation="unknown",
            explanation="模拟独立结尾判断未知，不能放行。")
    return value


def test_actual_475_wire_revalidation_preserves_all_original_semantic_passes():
    _, brief, plan, receipt = actual_case_v15()
    native = deepcopy(receipt["output"])
    assert receipt["status"] == "contract_rejected" and receipt["failure"]["code"] == "MODULE_SCHEMA_INVALID"
    assert scene_gate.validate_scene_plan_gate(native, plan, brief)["complete"]
    decision = scene_gate.decide_scene_plan_gate(native, plan, brief)
    assert decision["status"] == "scene_plan_ready" and not decision["revision_requirements"]
    assert all(row["status"] == "pass" for row in native["ending_checks"])
    assert native == receipt["output"]
    # Revalidation changes neither the old receipt status nor its semantics.
    assert not decision["human_quality_approved"] and not decision["creative_quality_passed"]


@pytest.mark.parametrize("change", ["ref", "plan_sha", "brief_sha", "catalog_sha"])
def test_scene_v2_real_reference_and_cross_source_hashes_remain_strict(change):
    _, brief, plan, receipt = actual_case_v15()
    native = deepcopy(receipt["output"])
    if change == "ref": native["initial_state_checks"][0]["evidence_refs"] = ["P9999"]
    else: native[{"plan_sha": "plan_sha256", "brief_sha": "brief_sha256", "catalog_sha": "catalog_sha256"}[change]] = "0" * 64
    with pytest.raises(ValueError):
        scene_gate.validate_scene_plan_gate(native, plan, brief)


def test_actual_old_scene_allpass_cannot_replace_explicit_independent_ending_failure():
    _, brief, plan, receipt = actual_case_v15()
    assert scene_gate.decide_scene_plan_gate(receipt["output"], plan, brief)["status"] == "scene_plan_ready"
    native = ending_for(plan, brief, fail=True)
    before = deepcopy(native)
    decision = ending_gate.decide(native, plan, brief)
    assert decision["status"] == "needs_whole_plan_revision"
    assert decision["revision_requirements"][0]["code"] == "ENDING_SCOPE_mock_open_problem"
    assert native == before and not decision["other_scene_gate_replaced"]


@pytest.mark.parametrize("change", ["invented_ending_quote", "cross_fact_quote", "cross_creative_hash", "missing_field"])
def test_ending_evidence_and_complete_same_source_coverage(change):
    _, brief, plan, _ = actual_case_v15()
    value = ending_for(plan, brief, fail=True)
    finding = value["ending_fields"][-1]["findings"][0]
    if change == "invented_ending_quote": finding["quote"] = "未出现在结尾中的句子"
    elif change == "cross_fact_quote": finding["source_refs"][0]["quote"] = brief["facts"][-1]["text"]
    elif change == "cross_creative_hash": value["creative_plan_sha256"] = "0" * 64
    else: value["ending_fields"].pop()
    with pytest.raises(ValueError):
        ending_gate.validate(value, plan, brief)


def test_ending_mixed_fail_and_unknown_keeps_uncertainty_but_requires_full_plan_revision():
    _, brief, plan, _ = actual_case_v15()
    native = ending_for(plan, brief, fail=True, unknown=True)
    decision = ending_gate.decide(native, plan, brief)
    assert decision["status"] == "needs_whole_plan_revision"
    assert decision["revision_requirements"] and decision["uncertainties"]
    assert native["ending_fields"][0]["findings"][0]["source_relation"] == "unknown"


def test_ending_only_unknown_halts_without_semantic_approval():
    _, brief, plan, _ = actual_case_v15()
    decision = ending_gate.decide(ending_for(plan, brief, unknown=True), plan, brief)
    assert decision["status"] == "halt_source_uncertain" and not decision["revision_requirements"]
    assert decision["uncertainties"] and not decision["human_quality_approved"]


@pytest.fixture
def resume_workspace_v15(resume_workspace_v14):
    from scripts import run_autonomous_text_pipeline_v15 as runner
    _, root, parent, brief, script, plan = resume_workspace_v14
    ledger, manifest = read(parent / "CALL_LEDGER.json"), read(root / "RESUME_RECEIPTS.json")
    receipt = {"ordinal": 475, "label": "scene_gate_regression", "status": "contract_rejected",
        "output": gate_for(plan, brief), "failure": {"category": "state_contract", "code": "MODULE_SCHEMA_INVALID", "response_received": True},
        "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": 34618}}
    path = parent / "call_475_scene_gate_regression.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ledger["calls"].append({"ordinal": 475, "receipt": path.name, "receipt_sha256": sha})
    manifest["receipts"]["scene_probe"] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": 475}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield runner, root, parent, brief, script, plan


class MockV15(MockV14):
    def __init__(self, brief, script, plan, *, ending_unknown=False, **kwargs):
        super().__init__(brief, script, plan, **kwargs)
        self.gates = 1  # Original 475 is imported, never dispatched again.
        self.endings, self.ending_unknown = 0, ending_unknown

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        fields = kwargs["structured_schema"]["properties"]
        if "ending_fields" not in fields:
            return super().call(role, messages, **kwargs)
        payload = json.loads(messages[-1]["content"])
        self.requests.append({"role": role, "payload": deepcopy(payload)})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        self.endings += 1
        value = ending_for(self.plan, self.brief, fail=self.endings == 1,
                           unknown=self.ending_unknown and self.endings > 1)
        return RoleResult(text=json.dumps(value, ensure_ascii=False), metadata={"response_body_complete": True,
            "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v15_mock_ending_" + str(ordinal),
            "total_tokens": 100}, response_payload={"mock": True})


def test_imported_475_is_not_redispatched_independent_ending_then_new_plan_and_sixth(resume_workspace_v15):
    runner, root, parent, brief, script, plan = resume_workspace_v15
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV15(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 6, json.dumps(result)
    assert len(service.requests) == 11 and service.drafts == 1
    first = service.requests[0]["payload"]
    assert "creative_scene_plan" in first and "source_obligations" not in first["creative_scene_plan"]
    assert "expected_fail" not in json.dumps(first)
    assert read(root / "ENDING_SCOPE_REGRESSION.json")["known_ending_conflict_detected"]
    assert read(root / "DELIVERABLE/ENDING_SCOPE_DECISION.json")["status"] == "ending_scope_ready"
    assert result["spend"]["effective_calls_started"] == 486
    assert result["spend"]["effective_reported_tokens"] == 7354638
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 11


@pytest.mark.parametrize("which", ["scene", "ending"])
def test_either_independent_plan_gate_only_unknown_prevents_any_new_body(which, resume_workspace_v15):
    runner, root, _, brief, script, plan = resume_workspace_v15
    service = MockV15(brief, script, plan, scene_unknown=which == "scene", ending_unknown=which == "ending")
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_source_uncertain" and service.drafts == 0, json.dumps(result)
    assert len(service.requests) == 5
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 5


@pytest.mark.parametrize("unknown_at", [1, 5])
def test_ending_request_result_unknown_stops_and_restart_reuses_same_identity(unknown_at, resume_workspace_v15):
    runner, root, _, brief, script, plan = resume_workspace_v15
    service = MockV15(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at, json.dumps(result)
    assert service.drafts == 0 and result["spend"]["unknown_token_reservations"] > 93117
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == unknown_at


def test_two_new_complete_bodies_keep_five_old_versions_and_stop_without_eighth(resume_workspace_v15):
    runner, root, _, brief, script, plan = resume_workspace_v15
    service = MockV15(brief, script, plan, always_bad=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "creative_stalled" and result["full_draft_versions"] == 7, json.dumps(result)
    assert len(service.requests) == 16 and service.drafts == 2
    assert result["spend"]["effective_calls_started"] == 491
    assert result["spend"]["effective_reported_tokens"] == 7355138
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 16
