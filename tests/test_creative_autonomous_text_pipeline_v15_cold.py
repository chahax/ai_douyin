"""Independent v15 cold entry routing, using only simulated native results."""
from copy import deepcopy
import hashlib
import json

import pytest

from tests.test_creative_autonomous_text_pipeline_v14_cold import (
    cold_workspace_v14, pipeline_workspace_v2, MockColdV14, read,
)
from tests.test_creative_autonomous_text_pipeline_v15 import ending_for


@pytest.fixture
def cold_workspace_v15(cold_workspace_v14):
    from scripts import run_autonomous_text_pipeline_v15 as runner
    _, root, parent, brief, script, plan = cold_workspace_v14
    ledger = read(parent / "CALL_LEDGER.json")
    ledger["starting_spend"].update(calls_started=475, reported_tokens=7353538, calls_with_known_usage=473)
    auth = read(parent / "AUTHORIZATION.json")
    auth["starting_spend"] = deepcopy(ledger["starting_spend"])
    (parent / "AUTHORIZATION.json").write_text(json.dumps(auth), encoding="utf-8")
    ledger["authorization_sha256"] = hashlib.sha256((parent / "AUTHORIZATION.json").read_bytes()).hexdigest()
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    yield runner, root, parent, brief, script, plan


class MockColdV15(MockColdV14):
    def __init__(self, brief, script, plan, *, ending_unknown=False, fail_plans=0):
        super().__init__(brief, script, plan)
        self.ending_unknown, self.fail_plans, self.endings = ending_unknown, fail_plans, 0

    def call(self, role, messages, **kwargs):
        from src.content_factory.creative_workflow_roles import RoleResult
        if "ending_fields" not in kwargs["structured_schema"]["properties"]:
            return super().call(role, messages, **kwargs)
        self.requests.append({"role": role, "payload": json.loads(messages[-1]["content"])})
        self.endings += 1
        value = ending_for(self.plan, self.brief, fail=self.endings <= self.fail_plans, unknown=self.ending_unknown)
        return RoleResult(text=json.dumps(value, ensure_ascii=False), metadata={"response_body_complete": True,
            "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v15_cold_ending_" + str(self.endings),
            "total_tokens": 100}, response_payload={"mock": True})


def test_cold_both_independent_plan_gates_full_body_four_reviews_and_same_source_handoff(cold_workspace_v15):
    runner, root, parent, brief, script, plan = cold_workspace_v15
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockColdV15(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 1, json.dumps(result)
    labels = [row["label"] for row in read(root / "CALL_LEDGER.json")["calls"]]
    assert labels == ["scene_plan_01", "source_contract_audit_01", "scene_plan_gate_01", "ending_scope_01",
                      "factual_scope_source", "source_temporal_scope", "whole_draft_01", "whole_review_01",
                      "literal_audit_01", "factual_scope_extract_01", "finding_adjudication_01"]
    assert len(service.requests) == 11 and service.plans == service.drafts == service.endings == 1
    ending_payload = service.requests[3]["payload"]
    assert "source_obligations" not in ending_payload["creative_scene_plan"]
    assert "test_expectations" not in ending_payload
    assert read(root / "DELIVERABLE/CREATIVE_PLAN_DECISION.json")["status"] == "scene_plan_ready"
    assert read(root / "DELIVERABLE/ENDING_SCOPE_DECISION.json")["status"] == "ending_scope_ready"
    handoff = read(root / "DELIVERABLE/HANDOFF.json")
    assert handoff["manual_assistant_gate_calls"] == 0 and not handoff["human_quality_approved"]
    assert result["spend"]["effective_calls_started"] == 486
    assert result["spend"]["effective_reported_tokens"] == 7354638
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 11


def test_cold_ending_only_unknown_stops_before_scope_and_writer_without_redispatch(cold_workspace_v15):
    runner, root, _, brief, script, plan = cold_workspace_v15
    service = MockColdV15(brief, script, plan, ending_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_source_uncertain" and service.drafts == 0, json.dumps(result)
    assert len(service.requests) == 4
    assert result["spend"]["effective_calls_started"] == 479
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 4


@pytest.mark.parametrize("fail_plans, expected_status, requests", [(1, "text_ready_for_director", 15), (2, "plan_stalled", 8)])
def test_cold_whole_plan_regeneration_is_bounded_at_two_native_plans(fail_plans, expected_status, requests, cold_workspace_v15):
    runner, root, _, brief, script, plan = cold_workspace_v15
    service = MockColdV15(brief, script, plan, fail_plans=fail_plans)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == expected_status and service.plans == 2, json.dumps(result)
    assert len(service.requests) == requests
    assert service.drafts == (1 if expected_status == "text_ready_for_director" else 0)
    second = service.requests[4]["payload"]
    assert second["previous_complete_plan"]["title"].endswith("1")
    assert second["plan_revision_requirement"]["full_native_plan_required"]
    assert second["plan_revision_requirement"]["prior_passing_explanations_not_writer_input"]
    assert result["spend"]["effective_calls_started"] == 475 + requests
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == expected_status
    assert len(service.requests) == requests
