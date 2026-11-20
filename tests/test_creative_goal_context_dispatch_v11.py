"""Source-specific allowance and exact protocol gate, entirely offline."""
from copy import deepcopy
import socket

import pytest

from scripts import creative_goal_context_dispatch_v11 as adapter
from scripts import run_goal_context_text_production_v27 as runner
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("runtime gate tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    from datetime import datetime, timezone
    from scripts import preview_goal_context_workflow_v2 as preview
    packet=runner.read(preview.SOURCE_ROOT/"source/SOURCE_PACKET.json")
    sample=datetime.fromisoformat(packet["prepared_at"].replace("Z","+00:00"))
    class FixtureClock:
        @staticmethod
        def now(tz=None):return sample.astimezone(tz or timezone.utc)
    monkeypatch.setattr(preview,"datetime",FixtureClock)


def gate(profile):
    runtime = object.__new__(adapter.GoalContextRuntime)
    runtime.profile = deepcopy(profile)
    runtime.models = runner.models(profile)
    return runtime


def test_only_compact_source_gets_24000_other_review_and_writer_keep_original(causal_scenario):
    inputs, _, goal, *_ = causal_scenario
    from tests.test_creative_goal_context_workflow_v22 import synthetic_fixed_goal
    goal=synthetic_fixed_goal(inputs,goal)
    profile = runner.read(runner.PROFILE)
    runtime = gate(profile)
    source = runner.prepare_source_audit(inputs, profile, goal)["request"]
    before = deepcopy((source, profile))
    runtime._request_gate(source)
    assert (source, profile) == before
    for kind in ("commitment", "drama"):
        request = getattr(runner.workflow, f"prepare_goal_{kind}_audit_request")(inputs, profile, goal)["request"]
        assert request["parameters"]["max_completion_tokens"] == 16000
        runtime._request_gate(request)
    writer = runner.workflow.prepare_goal_request(inputs, profile)["request"]
    assert writer["parameters"]["max_completion_tokens"] == 16000
    with pytest.raises(RuntimeError,match="no whole-plan generation"):
        runtime._request_gate(writer)
    opening=runner.workflow.prepare_opening_setup_request(inputs,profile,goal)["request"]
    runtime._request_gate(opening)
    ordinary = deepcopy(source)
    ordinary["stage"] = "full_review"
    ordinary["structured_schema"] = {"type": "object", "properties": {}}
    ordinary["parameters"]["max_completion_tokens"] = 32000
    runtime._request_gate(ordinary)
    assert runtime.profile == profile


@pytest.mark.parametrize("fault", ["missing_binding", "changed_binding", "disabled", "endpoint",
    "strict_false", "schema_policy", "ordinary_strict", "source_cap", "request_cap", "role",
    "stage", "model", "sdk_retry", "sdk_bool", "redirects", "wire_cap"])
def test_compact_contract_cannot_fallback_to_ordinary_or_drift(causal_scenario, fault):
    inputs, _, goal, *_ = causal_scenario
    from tests.test_creative_goal_context_workflow_v22 import synthetic_fixed_goal
    goal=synthetic_fixed_goal(inputs,goal)
    profile = runner.read(runner.PROFILE)
    request = runner.prepare_source_audit(inputs, profile, goal)["request"]
    runtime = gate(profile)
    if fault == "missing_binding": request["input_provenance"].pop("source_protocol_binding")
    elif fault == "changed_binding": request["input_provenance"]["source_protocol_binding"]["function_strict"] = False
    elif fault == "disabled": runtime.profile["source_strict"]["enabled"] = False
    elif fault == "endpoint": runtime.profile["source_strict"]["base_url"] = "https://api.deepseek.com/v1"
    elif fault == "strict_false": runtime.profile["source_strict"]["function_strict"] = False
    elif fault == "schema_policy": runtime.profile["source_strict"]["schema_version"] = "creative_goal_legal_usage_source_audit/v4"
    elif fault == "ordinary_strict": runtime.profile["source_strict"]["other_deepseek_stages_strict"] = True
    elif fault == "source_cap": runtime.profile["source_strict"]["max_completion_tokens"] = 16000
    elif fault == "request_cap": request["parameters"]["max_completion_tokens"] = 16000
    elif fault == "role": request["role"] = "writer"
    elif fault == "stage": request["stage"] = "full_review"
    elif fault == "model": request["model"] = "deepseek-reasoner"
    elif fault == "sdk_retry": runtime.profile["source_strict"]["sdk_max_retries"] = 1
    elif fault == "sdk_bool": runtime.profile["source_strict"]["sdk_max_retries"] = False
    elif fault == "redirects": runtime.profile["source_strict"]["http_follow_redirects"] = True
    elif fault == "wire_cap": runtime.profile["source_strict"]["max_wire_utf8_bytes"] = 600001
    before = deepcopy((request, runtime.profile))
    with pytest.raises(RuntimeError): runtime._request_gate(request)
    assert (request, runtime.profile) == before


def test_old_length_predicate_and_original_task_classification_implementation_unchanged():
    import inspect
    from src.content_factory import creative_flat_lineage_verifier_v5 as old
    from src.content_factory import creative_flat_lineage_verifier_v6 as new
    assert inspect.getsource(old._verified_length_failure) == inspect.getsource(new._verified_length_failure)
    assert inspect.getsource(old._task_history) == inspect.getsource(new._task_history)


@pytest.mark.parametrize("stage",["goal_plan","goal_audit"])
def test_new_one_plan_and_three_audits_ceiling_cannot_take_old_unused_stage_capacity(stage):
    limits=deepcopy(adapter.LIMIT_CEILINGS);limits[stage]+=1
    with pytest.raises(ValueError,match="independent ceilings"):
        adapter.GoalContextRuntime(None,None,None,None,None,stage_limits=limits)
