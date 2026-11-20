"""Independent strict-source-first replay and original605 consumption checks."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest
from scripts import run_goal_context_text_production_v20 as runner
from tests import test_goal_context_text_production_v18_independent_audit as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v2 import synthetic_source, add_legal_usage
from src.content_factory import creative_goal_legal_usage_source_audit_v2 as legal
from src.content_factory import creative_flat_lineage_verifier_v3 as lineage

INHERITED = {"calls_started":605,"reported_tokens":12148396,"calls_with_known_usage":603,
             "pending_ordinals":[70,160],"unknown_token_reservations":93117}
ACTUAL_ROOT = runner.PREFLIGHT_PARENT
ACTUAL_SOURCE = runner.read(ACTUAL_ROOT/"call_605_goal_source_audit_01.json")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a,**k):
        raise AssertionError("independent replay must not contact a provider")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)


def replay(tmp_path,monkeypatch,scenario,modes=None):
    monkeypatch.setattr(service,"runner",runner)
    monkeypatch.setattr(service,"INHERITED",deepcopy(INHERITED))
    monkeypatch.setattr(service,"synthetic_source",synthetic_source)
    monkeypatch.setattr(service,"legal_audit",legal)
    monkeypatch.setattr(service,"add_usage",lambda document,goal,ref,*,relation,status:
        add_legal_usage(document,goal,ref,relation=relation))
    original_clients=runner.clients
    monkeypatch.setattr(runner,"clients",SimpleNamespace(TOOL_NAME=original_clients.TOOL_NAME,
        expected_wire_request=lambda request:runner.strict_clients.expected_wire_request(
            request,source_strict=runner.is_strict_source(request))))
    runtime,root,sends=service.replay(tmp_path,monkeypatch,scenario,modes)
    first=runner.prepare_source_audit(runner.read(root/"INPUTS.json"),runner.read(runner.PROFILE),
                                      runner.read(root/"INHERITED_NATIVE_GOAL.json"))
    runner.write(root/"FIRST_SOURCE_REQUEST_PREVIEW.json",first,True)
    return runtime,root,sends


def test_initial_complete_source_not_new_planning_reaches_full_body_and_bound_reviews(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario)
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(r) for r in sends[:3]]==["source","commitment","drama"]
    assert not any(service.phase(r)=="goal_plan" for r in sends)
    assert result["cumulative_goal_candidates_used"]==26 and result["native_goal_ordinal"]==604
    assert runtime.summary()["stage_calls"]=={"goal_plan":1,"goal_audit":3,"complete_script":1,"full_review":2}
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    handoff=runner.read(root/"TEXT_HANDOFF.json")
    assert handoff["native_goal"]==runner.read(root/"INHERITED_NATIVE_GOAL.json")
    assert not handoff["production_dispatch_eligible"] and not handoff["media_authorized"]
    assert not result["human_quality_approved"]
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool",
                                  "missing_scan","mixed_authority","legacy_schema","legal_unknown","legal_fail"])
def test_strict_diagnostic_failure_stops_once_without_new_plan_or_body(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    assert result["status"]!="text_ready_for_director"
    assert [service.phase(r) for r in sends]==["source"]
    assert result["cumulative_goal_candidates_used"]==26
    assert not (root/"TEXT_HANDOFF.json").exists() and not (root/"scripts").exists()
    assert runtime.summary()["historical_pending_ordinals"]==[70,160]
    service.assert_no_reentry(runtime,root,sends)


def test_native_drama_failure_revises_whole_goal_and_keeps_all_audits_and_consumption(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("drama",1):"goal_fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(r) for r in sends[:5]]==["source","commitment","drama","goal_plan","source"]
    assert result["cumulative_goal_candidates_used"]==27
    context=json.loads(sends[3]["messages"][1]["content"])
    assert context["previous_complete_document"]==runner.read(root/"goals/native_00.json")
    assert len(context["revision_diagnostics"]["complete_same_source_goal_audits"])==3
    assert runtime.summary()["unknown_token_reservations"]==93117
    assert result["parent_unused_capacity_stays_in_closed_run"]


def test_six_audit_ceiling_stops_before_seventh_dispatch(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,
        {("drama",1):"goal_fail",("drama",2):"goal_fail"})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_capacity_exhausted"
    assert runtime.summary()["stage_calls"]["goal_audit"]==6
    assert sum(service.phase(r)=="goal_plan" for r in sends)==2
    assert result["cumulative_goal_candidates_used"]==28
    assert not (root/"scripts").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_exact605_is_consumption_only_not_json_repair_or_native_admission():
    before=json.dumps(ACTUAL_SOURCE,sort_keys=True,ensure_ascii=False)
    assert lineage._verified_invalid_json_failure(ACTUAL_SOURCE)
    assert json.dumps(ACTUAL_SOURCE,sort_keys=True,ensure_ascii=False)==before
    assert "output" not in ACTUAL_SOURCE and "validation" not in ACTUAL_SOURCE


@pytest.mark.parametrize("fault",["ordinal","status","finish","usage","body","text","model","adopted","retry"])
def test_known605_exception_rejects_identity_or_outcome_drift(fault):
    value=deepcopy(ACTUAL_SOURCE)
    if fault=="ordinal":value["ordinal"]=606
    elif fault=="status":value["status"]="contract_valid"
    elif fault=="finish":value["response_metadata"]["finish_reason"]="length"
    elif fault=="usage":value["response_metadata"]["total_tokens"]=None
    elif fault=="body":value["response_metadata"]["response_body_complete"]=False
    elif fault=="text":value["response_text"]=value["response_text"][:-1]
    elif fault=="model":value["request"]["model"]="other-model"
    elif fault=="adopted":value["output"]={"accepted":True}
    elif fault=="retry":value["automatic_retry"]=True
    assert not lineage._verified_invalid_json_failure(value)


def test_actual_first_preview_has_strict_beta_wire_and_retains_entire604():
    inputs=runner.read(ACTUAL_ROOT/"INPUTS.json");goal=runner.read(ACTUAL_ROOT/"goals/native_01.json")
    first=runner.prepare_source_audit(inputs,runner.read(runner.PROFILE),goal)
    assert runner.is_strict_source(first["request"])
    assert first["wire"]["tools"][0]["function"]["strict"] is True
    body=json.loads(first["request"]["messages"][1]["content"])
    assert body["native_goal_evidence_view"]["native_goal_sha256"]==runner.digest(goal)
    assert first["source_schema_compilation_manifest"]["base_url"]=="https://api.deepseek.com/beta"
    assert first["strict_wire_measurement"]["utf8_bytes"]==484136
    assert first["strict_wire_measurement"]["utf8_bytes"]<600000
    assert first["strict_wire_measurement"]["logical_payload_budget_does_not_certify_full_wire"]
    assert len(json.dumps(first["request"]["input_provenance"]))<5000


def test_actual_unclaimed_authorization_declares_first_source_and_protocol_selector():
    from scripts import record_deepseek_strict_source_continuation_v1 as authorizer
    binding,prepared=authorizer.build_binding()
    assert binding["first_action_is_source_audit"] and binding["source_only_strict_protocol"]
    assert binding["actual_prepared_preview_sha256"]==runner.digest(prepared)
    assert binding["seed_native_identity"]["ordinal"]==604
    assert binding["parent_unused_capacity_stays_in_closed_run"] and not binding["old_ledger_reset"]
