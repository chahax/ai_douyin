"""Native planning first, closed report-revision lineage, offline only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_goal_context_text_production_v23 as runner
from scripts import record_supermarket_native_plan_rebuild_v1 as authorizer
from tests import supermarket_rebuild_service_helper_v1 as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v3 import synthetic_source, add_legal_usage
from src.content_factory import creative_goal_legal_usage_source_audit_v3 as legal

INHERITED={"calls_started":608,"reported_tokens":12451231,"calls_with_known_usage":606,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
ACTUAL_ROOT=runner.PREFLIGHT_PARENT

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("v23 tests cannot contact providers")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)


def replay(tmp_path,monkeypatch,scenario,modes=None):
    monkeypatch.setattr(service,"runner",runner)
    monkeypatch.setattr(service,"INHERITED",deepcopy(INHERITED))
    monkeypatch.setattr(service,"synthetic_source",synthetic_source)
    monkeypatch.setattr(service,"legal_audit",legal)
    monkeypatch.setattr(service,"add_usage",lambda document,goal,ref,*,relation,status=None:add_legal_usage(document,goal,ref,relation=relation))
    original_clients=runner.clients
    monkeypatch.setattr(runner,"clients",SimpleNamespace(TOOL_NAME=original_clients.TOOL_NAME,
        expected_wire_request=lambda request:runner.strict_clients.expected_wire_request(request,source_strict=runner.is_strict_source(request))))
    runtime,root,sends=service.replay(tmp_path,monkeypatch,scenario,modes)
    inputs,profile,goal=runner.read(root/"INPUTS.json"),runner.read(runner.PROFILE),runner.read(root/"INHERITED_NATIVE_GOAL.json")
    diagnostic={"native_goal_sha256":runner.digest(goal),"complete_rebuild_questions":{
        "schema":"synthetic_pending_native_rebuild_questions/v1","native_goal_sha256":runner.digest(goal),
        "instruction":"Complete native rebuild retaining original human goals, no local adoption"},
        "exact_schema_errors":[{"path":["source_observations",152,"usages",0,"context_evidence",0,"source_ref"],
            "validator":"enum","actual_value":"G106"}],"old_report_admitted_decision_created":False}
    runner.write(root/"INHERITED_DIAGNOSTICS.json",diagnostic)
    first=runner.prepare_first_goal_request(inputs,profile,goal,diagnostic)
    runner.write(root/"FIRST_GOAL_REQUEST_PREVIEW.json",first)
    return runtime,root,sends,diagnostic,first


def test_first_whole_plan27_then_current_goal_three_audits_and_body_double_review(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,first=replay(tmp_path,monkeypatch,causal_scenario)
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(row) for row in sends]==["goal_plan","source","commitment","drama","opening_setup","complete_script","semantic","physical"]
    assert sends[0]==first["request"] and sends[0]["role"]=="writer"
    assert result["cumulative_goal_candidates_used"]==27 and result["native_goal_ordinal"]==609
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    assert sends[1]["structured_schema"]["properties"]["goal_sha256"]["const"]==runner.digest(runner.read(root/"goals/native_01.json"))
    assert runner.read(root/"goals/native_01.json")!=runner.read(root/"INHERITED_NATIVE_GOAL.json")
    assert not result["human_quality_approved"] and not result["media_authorized"]
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool"])
def test_first_planner_interface_unknown_or_incomplete_stops_without_source_or_replacement(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("goal_plan",1):mode})
    result=runner.run()
    assert result["status"]=="halt_goal_interface_or_unknown",result
    assert [service.phase(row) for row in sends]==["goal_plan"]
    assert not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("phase,mode",[("source","legal_unknown"),("source","legal_fail"),("commitment","unknown"),("drama","goal_unknown")])
def test_known_valid_current_plan_audit_failure_or_uncertainty_revises_complete_plan28(tmp_path,monkeypatch,causal_scenario,phase,mode):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{(phase,1):mode})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert result["cumulative_goal_candidates_used"]==28
    planned=[row for row in sends if service.phase(row)=="goal_plan"]
    assert len(planned)==2
    payload=json.loads(planned[1]["messages"][1]["content"])
    native=runner.read(root/f"goals/{phase}_native_audit_01.json")
    assert payload["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"][f"native_{phase}_audit"]==native
    assert payload["revision_diagnostics"]["historical_G_references_are_not_current_native_facts"]
    assert payload["previous_complete_document"]==runner.read(root/"goals/native_01.json")
    assert runtime.summary()["stage_calls"]["goal_audit"]<=6
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["missing_scan","mixed_authority","legacy_schema"])
def test_current_source_contract_failure_stops_no_source_report_repair(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_contract_requires_pipeline_diagnosis"
    assert [service.phase(row) for row in sends]==["goal_plan","source"]
    assert sum(service.phase(row)=="source" for row in sends)==1
    service.assert_no_reentry(runtime,root,sends)


def test_only_two_whole_native_plans_and_six_audits_before_no_body(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("drama",1):"goal_unknown",("drama",2):"goal_unknown"})
    result=runner.run()
    assert result["status"]=="halt_goal_content_capacity_exhausted"
    assert result["cumulative_goal_candidates_used"]==28
    assert runtime.summary()["stage_calls"]["goal_audit"]==6
    assert sum(service.phase(row)=="goal_plan" for row in sends)==2
    assert not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_exact_old604_cannot_be_sent_to_source_again_after_planner_returns_it(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,
        {("goal_plan",1):"unchanged_original",("goal_plan",2):"unchanged_original"})
    result=runner.run()
    assert result["status"]=="halt_goal_content_capacity_exhausted"
    assert [service.phase(row) for row in sends]==["goal_plan","goal_plan"]
    assert result["cumulative_goal_candidates_used"]==28
    assert not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_true_parent608_guard_and_full604_R01_QA_first_request_without_report_template():
    summary=runner.prior_guard();binding,prepared=authorizer.build_binding()
    inputs=runner.read(ACTUAL_ROOT/"INPUTS.json");seed=runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    assert payload["previous_complete_document"]==seed and payload["reference_fulltext"]==inputs["reference_fulltext"]
    assert payload["revision_diagnostics"]["complete_rebuild_questions"]==runner.read(runner.REVIEW_QUESTIONS)
    assert len(payload["revision_diagnostics"]["exact_schema_errors"])==2
    assert "previous_complete_source_report" not in json.dumps(payload["revision_diagnostics"])
    assert "known_complete_source_report_revision" not in payload
    assert not payload["revision_diagnostics"]["old_report_admitted_decision_created"]
    assert prepared["request"]["stage"]=="goal_plan" and prepared["request"]["role"]=="writer"
    assert prepared["request"]["parameters"]["max_completion_tokens"]==16000
    assert len(prepared["request"]["messages"][1]["content"])<100000
    assert (summary["effective_calls_started"],summary["effective_reported_tokens"],summary["effective_calls_with_known_usage"])==(608,12451231,606)
    runner.verify_authorization_request_binding(binding,runner.build_revision_diagnostics(seed),prepared,binding["seed_native_identity"])
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


def test_known_full_planner_contract_rejection_consumes27_then_complete_new28(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("goal_plan",1):"contract_fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(row) for row in sends[:3]]==["goal_plan","goal_plan","source"]
    assert result["cumulative_goal_candidates_used"]==28
    assert runner.read(root/"goals/native_01.json")==json.loads(sends[1]["messages"][1]["content"])["previous_complete_document"]
    service.assert_no_reentry(runtime,root,sends)


def test_actual_first_minimax_sdk_wire_preserves_R01_goal_QA_and_matches_future_lineage(tmp_path,monkeypatch):
    import httpx
    from tests import test_creative_m31_flash_role_clients_v1 as sdk
    from src.content_factory import creative_flat_lineage_verifier_v4 as lineage
    binding,prepared=authorizer.build_binding();request,sent=prepared["request"],[]
    monkeypatch.setattr(runner.clients,"role_config",lambda role:SimpleNamespace(
        model=runner.clients.WRITER_MODEL,api_key=sdk.KEY,base_url="https://api.minimax.cn/v1"))
    client,evidence,_=sdk.setup(tmp_path,request,
        lambda outgoing:sent.append(outgoing.read()) or httpx.Response(200,content=sdk.reply()))
    sdk.call(client,request,evidence)
    assert len(sent)==1
    actual=json.loads(sent[0])
    assert actual==runner.clients.expected_wire_request(request)
    assert actual["max_completion_tokens"]==16000 and actual["reasoning_effort"]=="medium"
    payload=json.loads(actual["messages"][1]["content"])
    assert payload["reference_fulltext"]==runner.read(ACTUAL_ROOT/"INPUTS.json")["reference_fulltext"]
    assert payload["previous_complete_document"]==runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")
    assert payload["revision_diagnostics"]["complete_rebuild_questions"]==runner.read(runner.REVIEW_QUESTIONS)
    assert lineage._outbound(lineage.VerificationCycle(),runner.PROJECT,evidence.root,request,evidence.identity_sha256)==actual
    proof=runner.read(evidence.root/"M31_WIRE_PREFLIGHT.json")
    assert proof["SDK_max_retries"]==0 and proof["HTTP_follow_redirects"] is False
