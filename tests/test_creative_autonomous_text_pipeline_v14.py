"""Unattended new whole plan and body routing; mock judgments are not quality gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v13 as contract
from src.content_factory import creative_scene_plan_gate_v1 as gate
from tests.test_creative_autonomous_text_pipeline_v12 import (
    read, codes, temporal_for, resume_workspace_v12, resume_workspace_v11, resume_workspace_v10,
    resume_workspace_v9, resume_workspace_v8, resume_workspace_v7, pipeline_workspace_v6,
    pipeline_workspace_v5, pipeline_workspace_v3, pipeline_workspace_v2, extract_for,
    adjudication_for, unsupported_claim, add_claim, wire_checks, review_v2, audit_v5,
)
from tests.test_creative_autonomous_text_pipeline_v5 import source_audit_v5


def gate_for(plan, brief, *, failed_blind=False, unknown=False):
    catalog = gate.creative_evidence_catalog(plan)
    beats = [ref for ref, row in catalog.items() if row["kind"] == "beat"]
    creative = next(ref for ref, row in catalog.items() if row["kind"] == "scene_intent")
    common = {"status": "pass", "explanation": "模拟完整规划验收路由，并非独立语义质量金标。", "evidence_refs": [creative], "required_revision": ""}
    value = {"plan_sha256": contract._digest(plan), "brief_sha256": contract._digest(brief),
        "catalog_sha256": contract._digest(catalog),
        "source_obligation_checks": [{**deepcopy(common), "obligation_id": row["id"], "evidence_refs": [beats[0]],
            "coverage_type": {"event": "explicit_event", "state": "state_preserved", "absence": "absent_as_required"}[row["mode"]]}
            for row in plan["source_obligations"]],
        "fact_checks": [{**deepcopy(common), "fact_id": row["id"]} for row in brief["facts"]],
        "initial_state_checks": [{**deepcopy(common), "entity_type": kind, "entity_id": row["id"]}
            for kind, key in [("character", "character_states"), ("prop", "prop_states")] for row in brief["initial_state"][key]],
        "source_order_checks": [{**deepcopy(common), "before_id": row["before_id"], "after_id": row["after_id"],
            "evidence_refs": beats[:2], "before_evidence_refs": beats[:1], "after_evidence_refs": beats[1:2],
            "planned_relation": "explicit_before"} for row in plan["source_order"]],
        "beat_checks": [{"beat_id": row["id"], "checks": {key: {**deepcopy(common),
            "evidence_refs": [next(ref for ref, entry in catalog.items() if entry.get("beat_id") == row["id"])],
            "source_fact_ids": [brief["facts"][0]["id"]]} for key in gate.BEAT_CHECKS}} for row in plan["beats"]],
        "ending_checks": [{**deepcopy(common), "field": field, "source_fact_ids": [brief["facts"][0]["id"]],
            "evidence_refs": [next(ref for ref, row in catalog.items() if row["kind"] == "ending" and row["field"] == field)]}
            for field in gate.ENDING_FIELDS]}
    if failed_blind:
        next(row for row in value["ending_checks"] if row["field"] == "open_problem").update(status="fail",
            explanation="模拟盲审发现已宣布的公司决定被结尾恢复未知；仅测回归阻断分支。",
            required_revision="完整新计划保留已说明决定，只让争议处理尚未解决。")
    if unknown: value["fact_checks"][0].update(status="unknown", explanation="来源与实际创作字段尚不确定。")
    return value


@pytest.fixture
def resume_workspace_v14(resume_workspace_v12):
    from scripts import run_autonomous_text_pipeline_v14 as runner
    _, root, parent, brief, script, plan = resume_workspace_v12
    ledger, manifest = read(parent / "CALL_LEDGER.json"), read(root / "RESUME_RECEIPTS.json")
    scope = contract.compile_source_fact_scope(read(manifest["receipts"]["scope_source"]["path"])["output"], brief)
    raw = {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"}
    raw["title"] = "模拟未交接的完整第5稿"
    script = contract.compile_script(raw, brief)
    extract = extract_for(script, brief, scope)
    outputs = [temporal_for(plan, brief), raw, wire_checks(review_v2(script, brief)), wire_checks(audit_v5(script, brief, plan)), extract]
    labels = ["source_temporal_scope", "whole_draft_05", "whole_review_05", "literal_audit_05", "factual_scope_extract_05"]
    keys = ["temporal", "draft", "review", "audit", "extract"]
    tokens = [7976, 9289, 14182, 15512, 19849]
    for ordinal, key, label, output, usage in zip(range(470, 475), keys, labels, outputs, tokens):
        receipt = {"ordinal": ordinal, "label": label, "status": "contract_valid", "output": output,
            "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": usage}}
        if ordinal == 474:
            receipt.update(status="contract_rejected", failure={"category": "validation", "code": "source alignment must cite its own original category allowance value", "response_received": True})
        path = parent / f"call_{ordinal}_{label}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger["calls"].append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": sha})
        manifest["receipts"][key] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": ordinal}
    manifest["receipts"].pop("adjudication")
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    setup = read(root / "SETUP.json")
    setup.update(max_full_plans=2, max_full_drafts=7, inherited_full_draft_versions=5,
        max_automatic_content_revisions=2, minimum_new_whole_drafts=1)
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    yield runner, root, parent, brief, script, plan


class MockV14:
    def __init__(self, brief, script, plan, *, unknown_at=None, source_unknown=False, scene_unknown=False,
                 repair=False, always_bad=False, mixed_plan_failure=False, plans_always_fail=False):
        self.brief, self.script, self.plan = deepcopy(brief), deepcopy(script), deepcopy(plan)
        self.requests, self.gates, self.drafts = [], 0, 0
        self.unknown_at, self.source_unknown, self.scene_unknown = unknown_at, source_unknown, scene_unknown
        self.repair, self.always_bad = repair, always_bad
        self.mixed_plan_failure, self.plans_always_fail, self.plans = mixed_plan_failure, plans_always_fail, 0

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        fields = kwargs["structured_schema"]["properties"]
        payload = json.loads(messages[-1]["content"])
        self.requests.append({"role": role, "payload": deepcopy(payload)})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "catalog_sha256" in fields:
            self.gates += 1
            output = gate_for(payload["full_scene_plan"], self.brief,
                failed_blind=self.gates == 1 or self.plans_always_fail or self.mixed_plan_failure and self.gates == 2,
                unknown=self.scene_unknown and self.gates > 1 or self.mixed_plan_failure and self.gates == 2)
        elif "source_obligations" in fields:
            self.plans += 1
            output = deepcopy(self.plan)
            output["title"] = "模型完整新场景行动计划" + str(self.plans)
            for row in output["initial_conditions"]: row.pop("source_quote", None)
            for row in output["source_order"]: row.pop("source_quote", None)
            self.plan = contract.compile_plan(output, self.brief)
        elif "source_obligation_checks" in fields:
            output = source_audit_v5(self.plan, self.brief)
            for table in ["fact_coverage_checks", "source_obligation_checks", "initial_condition_checks", "source_order_checks"]:
                for row in output[table]: row.pop("source_quote", None)
            if self.source_unknown: output["fact_coverage_checks"][0]["status"] = "unknown"
        elif "obligations" in fields:
            output = temporal_for(self.plan, self.brief)
        elif "extract_sha256" in fields:
            output = adjudication_for(payload["original_detection"], payload["full_current_script"], self.brief, payload["source_fact_scope"])
            for row in output["findings"]: row["explanation"] = "MOCK_OLD_ADJUDICATION_EXPLANATION_NEVER_WRITER_INPUT"
        elif "category_extracts" in fields:
            output = extract_for(payload["full_current_script"], self.brief, payload["source_fact_scope"])
            if self.always_bad or self.repair and self.drafts == 1:
                add_claim(output, "follow_up_undertaking", unsupported_claim("future06", "E0001",
                    "签了我明天去送表", "明天去送表", "future_business_action", "hr"))
        elif "literal_events" in fields:
            output = wire_checks(audit_v5(payload["full_current_script"], self.brief, self.plan))
        elif "dialogue_readings" in fields:
            output = wire_checks(review_v2(payload["full_current_script"], self.brief))
        else:
            self.drafts += 1
            output = {k: deepcopy(v) for k, v in self.script.items() if k != "selected_candidate_id"}
            output["title"] = "模型完整第" + str(5 + self.drafts) + "稿"
            if not self.always_bad and not (self.repair and self.drafts == 1):
                output["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开。"
            for i, beat in enumerate(output["beats"]): beat["id"] = "COMPLETE_NATIVE_" + str(5 + self.drafts) + "_" + str(i)
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True,
            "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v14_mock_" + str(ordinal), "total_tokens": 100}, response_payload={"mock": True})


def test_new_whole_plan_is_reviewed_before_whole_sixth_and_restart_dispatches_nothing(resume_workspace_v14):
    runner, root, parent, brief, script, plan = resume_workspace_v14
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV14(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 6, result
    assert len(service.requests) == 10 and service.drafts == 1
    assert "expected_fail" not in json.dumps(service.requests[0]["payload"], ensure_ascii=False)
    assert "previous_complete_plan" in service.requests[1]["payload"] and service.requests[1]["payload"]["reference_fulltext"]
    assert service.requests[2]["payload"]["full_source_plan"] == service.plan
    assert service.requests[3]["payload"]["full_scene_plan"] == service.plan
    assert "creative_scene_plan" in service.requests[5]["payload"] and service.requests[5]["payload"]["reference_fulltext"]
    assert result["spend"]["effective_calls_started"] == 484 and result["spend"]["effective_reported_tokens"] == 7319920
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    handoff = read(root / "DELIVERABLE/HANDOFF.json")
    assert handoff["creative_plan_accepted_before_writer"] and handoff["complete_new_plan_from_model"]
    assert handoff["manual_assistant_gate_calls"] == 0 and not handoff["human_quality_approved"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 10


def test_seventh_whole_repair_keeps_current_negative_evidence_without_old_adjudication_reason(resume_workspace_v14):
    runner, root, _, brief, script, plan = resume_workspace_v14
    service = MockV14(brief, script, plan, repair=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 7, result
    assert len(service.requests) == 15 and service.drafts == 2
    payload = service.requests[10]["payload"]
    target = payload["executable_revision_targets"]
    encoded = json.dumps(target, ensure_ascii=False)
    assert "签了我明天去送表" in encoded and "MOCK_OLD_ADJUDICATION_EXPLANATION_NEVER_WRITER_INPUT" not in encoded
    assert target["negative_evidence_not_script_template"][0]["must_change"] is True
    assert "previous_complete_script" not in payload
    assert result["spend"]["effective_calls_started"] == 489 and not result["spend"]["old_budget_reset"]


@pytest.mark.parametrize("unknown_at", [1, 2, 6, 9])
def test_blind_plan_writer_or_extract_unknown_stops_and_restart_reuses_original_identity(unknown_at, resume_workspace_v14):
    runner, root, _, brief, script, plan = resume_workspace_v14
    service = MockV14(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at, result
    assert result["spend"]["effective_calls_started"] == 474 + unknown_at
    assert result["spend"]["unknown_token_reservations"] > 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == unknown_at


@pytest.mark.parametrize("which", ["source", "creative"])
def test_source_or_actual_creative_plan_gate_unknown_stops_before_any_body(which, resume_workspace_v14):
    runner, root, _, brief, script, plan = resume_workspace_v14
    service = MockV14(brief, script, plan, source_unknown=which == "source", scene_unknown=which == "creative")
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_source_uncertain" and service.drafts == 0, result
    assert len(service.requests) == (3 if which == "source" else 4)
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == (3 if which == "source" else 4)


def test_two_new_whole_bodies_are_limit_no_eighth_or_history_reset(resume_workspace_v14):
    runner, root, _, brief, script, plan = resume_workspace_v14
    service = MockV14(brief, script, plan, always_bad=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "creative_stalled" and result["full_draft_versions"] == 7, result
    assert len(service.requests) == 15 and service.drafts == 2
    assert result["spend"]["effective_calls_started"] == 489 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 15


def test_scene_plan_event_state_mode_mismatch_is_content_revision_not_wire_rejection():
    project = Path(__file__).resolve().parents[1]
    prior = project / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_12"
    plan, brief = read(prior / "SCENE_PLAN.json"), read(prior / "INPUT.json")["brief"]
    value = gate_for(plan, brief)
    row = next(r for r in value["source_obligation_checks"] if r["obligation_id"] == "SO11")
    row["coverage_type"] = "state_preserved"
    original = deepcopy(value)
    assert gate.validate_scene_plan_gate(value, plan, brief)["complete"]
    result = gate.decide_scene_plan_gate(value, plan, brief)
    assert result["status"] == "needs_whole_plan_revision"
    assert "CREATIVE_SOURCE_MODE_SO11" in {r["code"] for r in result["revision_requirements"]}
    assert value == original


def test_creative_plan_mixed_fail_unknown_produces_second_complete_plan_then_body(resume_workspace_v14):
    runner, root, _, brief, script, plan = resume_workspace_v14
    service = MockV14(brief, script, plan, mixed_plan_failure=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 6, result
    assert service.plans == 2 and service.drafts == 1 and len(service.requests) == 13
    decision = read(root / "plan_versions/01/SCENE_GATE_DECISION.json")
    assert decision["status"] == "needs_whole_plan_revision" and decision["revision_requirements"] and decision["uncertainties"]
    second = service.requests[4]["payload"]
    assert second["previous_complete_plan"]["title"].endswith("1")
    assert "creative_plan_decision" in second["plan_revision_requirement"]


def test_failed_second_full_plan_stops_before_script_and_restart_does_not_reset_plans(resume_workspace_v14):
    runner, root, _, brief, script, plan = resume_workspace_v14
    service = MockV14(brief, script, plan, plans_always_fail=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "plan_stalled" and result["full_plan_versions"] == 2, result
    assert service.plans == 2 and service.drafts == 0 and len(service.requests) == 7
    assert result["spend"]["effective_calls_started"] == 481 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 7
