"""Independent cold entry routing; no paid calls, no creative semantic gold."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import creative_autonomous_text_contract_v13 as contract
from tests.test_creative_autonomous_text_pipeline_v2 import pipeline_workspace_v2
from tests.test_creative_autonomous_text_pipeline_v5 import case_v5, plan_v5
from tests.test_creative_autonomous_text_pipeline_v9 import restricted_scope
from tests.test_creative_autonomous_text_pipeline_v14 import (
    MockV14, read, unsupported_claim, add_claim, audit_v5, wire_checks,
)


@pytest.fixture
def cold_workspace_v14(pipeline_workspace_v2):
    from scripts import run_autonomous_text_pipeline_v14 as runner
    _, root, parent, _, _, _ = pipeline_workspace_v2
    brief, raw, _, plan, _, _ = case_v5()
    brief["selected_candidate_id"] = "FRESH_COLD_V14_CANDIDATE"
    script = contract.compile_script(raw, brief)
    x = read(root / "INPUT.json")
    x["brief"] = brief
    (root / "INPUT.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
    setup = read(root / "SETUP.json")
    setup.update(max_full_drafts=3, max_full_plans=2, max_automatic_content_revisions=2,
                 minimum_new_whole_drafts=0, regression_probe_file=None)
    assert "resume_receipts_file" not in setup
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    ledger = read(parent / "CALL_LEDGER.json")
    ledger["starting_spend"].update(calls_started=474, reported_tokens=7318920,
                                    calls_with_known_usage=472)
    authorization = read(parent / "AUTHORIZATION.json")
    authorization["starting_spend"] = deepcopy(ledger["starting_spend"])
    (parent / "AUTHORIZATION.json").write_text(json.dumps(authorization), encoding="utf-8")
    ledger["authorization_sha256"] = hashlib.sha256((parent / "AUTHORIZATION.json").read_bytes()).hexdigest()
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    yield runner, root, parent, brief, script, plan


class MockColdV14(MockV14):
    def __init__(self, brief, script, plan, *, fail_drafts=0, unknown_at=None):
        super().__init__(brief, script, plan, unknown_at=unknown_at)
        # Cold entry does not dispatch the old-plan blind probe.
        self.gates = 1
        self.fail_drafts = fail_drafts

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        fields = kwargs["structured_schema"]["properties"]
        if "restrictions" in fields:
            self.requests.append({"role": role, "payload": json.loads(messages[-1]["content"])})
            ordinal = len(self.requests)
            if ordinal == self.unknown_at:
                raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
            return RoleResult(text=json.dumps(restricted_scope(self.brief), ensure_ascii=False),
                metadata={"response_body_complete": True, "finish_reason": "tool_calls", "output_mode": "tool_call",
                          "response_id": "v14_cold_scope_" + str(ordinal), "total_tokens": 100}, response_payload={"mock": True})
        if "literal_events" in fields:
            payload = json.loads(messages[-1]["content"])
            self.requests.append({"role": role, "payload": deepcopy(payload)})
            ordinal = len(self.requests)
            if ordinal == self.unknown_at:
                raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
            # The old helper maps its fixture topic ID to an action actor. Use
            # that fixture label only inside generation; the returned audit
            # remains bound to the actual fresh script and native plan SHA.
            helper_brief = deepcopy(self.brief)
            helper_brief["selected_candidate_id"] = "fixture_legal"
            output = wire_checks(audit_v5(payload["full_current_script"], helper_brief, self.plan))
            return RoleResult(text=json.dumps(output, ensure_ascii=False),
                metadata={"response_body_complete": True, "finish_reason": "tool_calls", "output_mode": "tool_call",
                          "response_id": "v14_cold_audit_" + str(ordinal), "total_tokens": 100}, response_payload={"mock": True})
        native = super().call(role, messages, **kwargs)
        value = json.loads(native.text)
        if "premise" in fields:
            value["title"] = "冷启动模型完整第" + str(self.drafts) + "稿"
            for i, beat in enumerate(value["beats"]):
                beat["id"] = "FRESH_COLD_NATIVE_" + str(self.drafts) + "_" + str(i)
            if self.drafts <= self.fail_drafts:
                value["beats"][0]["steps"][0]["text"] = "公司让你离开，签了我明天去送表。"
        elif "category_extracts" in fields and self.drafts <= self.fail_drafts:
            add_claim(value, "follow_up_undertaking", unsupported_claim(
                "future_cold_" + str(self.drafts), "E0001", "签了我明天去送表", "明天去送表", "future_business_action", "hr"))
        return RoleResult(text=json.dumps(value, ensure_ascii=False), metadata=native.metadata,
                          response_payload=native.response_payload)


def test_cold_model_source_scope_scene_gate_full_four_reviews_and_handoff(cold_workspace_v14):
    runner, root, parent, brief, script, plan = cold_workspace_v14
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockColdV14(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 1, json.dumps(result)
    assert len(service.requests) == 10 and service.drafts == 1
    assert list(service.requests[3]["payload"]) == ["brief"]
    labels = [row["label"] for row in read(root / "CALL_LEDGER.json")["calls"]]
    assert labels == ["scene_plan_01", "source_contract_audit_01", "scene_plan_gate_01", "factual_scope_source",
                      "source_temporal_scope", "whole_draft_01", "whole_review_01", "literal_audit_01",
                      "factual_scope_extract_01", "finding_adjudication_01"]
    assert (root / "DELIVERABLE/CREATIVE_PLAN_GATE.json").exists()
    assert (root / "DELIVERABLE/CREATIVE_PLAN_DECISION.json").exists()
    body = read(root / "DELIVERABLE/FULL_SCRIPT.json")
    assert body["selected_candidate_id"] == "FRESH_COLD_V14_CANDIDATE"
    assert all(row["id"].startswith("FRESH_COLD_NATIVE_1_") for row in body["beats"])
    handoff = read(root / "DELIVERABLE/HANDOFF.json")
    assert handoff["source_scope_model_generated"] and handoff["manual_assistant_gate_calls"] == 0
    assert not handoff["human_quality_approved"] and not handoff["creative_quality_proven"]
    assert result["spend"]["effective_calls_started"] == 484
    assert result["spend"]["effective_reported_tokens"] == 7319920
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 10


@pytest.mark.parametrize("fail_drafts, expected_status", [(2, "text_ready_for_director"), (3, "creative_stalled")])
def test_cold_three_whole_drafts_bound_two_automatic_revisions_without_reset(fail_drafts, expected_status, cold_workspace_v14):
    runner, root, _, brief, script, plan = cold_workspace_v14
    service = MockColdV14(brief, script, plan, fail_drafts=fail_drafts)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == expected_status and result["full_draft_versions"] == 3, json.dumps(result)
    assert len(service.requests) == 20 and service.drafts == 3
    third_writer = service.requests[15]["payload"]
    assert third_writer["executable_revision_targets"]["negative_evidence_not_script_template"]
    assert "previous_complete_script" not in third_writer
    assert result["spend"]["effective_calls_started"] == 494
    assert result["spend"]["effective_reported_tokens"] == 7320920
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == expected_status
    assert len(service.requests) == 20


def test_cold_first_scope_request_unknown_halts_before_writer_and_restart_does_not_redispatch(cold_workspace_v14):
    runner, root, _, brief, script, plan = cold_workspace_v14
    service = MockColdV14(brief, script, plan, unknown_at=4)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == 4 and service.drafts == 0, result
    assert result["spend"]["effective_calls_started"] == 478
    assert result["spend"]["unknown_token_reservations"] > 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 4
