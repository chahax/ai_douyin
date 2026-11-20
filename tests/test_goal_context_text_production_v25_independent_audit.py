"""Native planning first, closed report-revision lineage, offline only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_goal_context_text_production_v25 as runner
from scripts import record_supermarket_native_setup_continuation_v1 as authorizer
from tests import supermarket_native_setup_service_helper_v1 as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v4 import synthetic_source, add_legal_usage
from src.content_factory import creative_goal_legal_usage_source_audit_v4 as legal

INHERITED={"calls_started":615,"reported_tokens":12732559,"calls_with_known_usage":613,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
ACTUAL_ROOT=runner.PREFLIGHT_PARENT

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("v25 tests cannot contact providers")
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
    source_prepared=runner.prepare_source_audit(inputs,profile,goal)
    report=synthetic_source(goal,source_prepared["source_authority_context"],source_prepared["source_context_sha256"])
    decision=runner.workflow.validate_goal_source_audit(report,goal,context_sha256=source_prepared["source_context_sha256"],authority_context=source_prepared["source_authority_context"])
    qa={"schema":"creative_native_semantic_and_setup_repair_diagnostics/v1",
        "current_goal_native_sha256":runner.digest(goal),"source_audit_native_sha256":runner.digest(report),
        "source_audit_ordinal":611,"parent_terminal_state_sha256":"a"*64,
        "original_accepted_source_decision_preserved":True,"independent_semantic_counterexamples":[],
        "complete_native_reports_required_in_revision":True,"local_native_goal_modified":False,
        "report_locally_converted":False,"human_adopted":False,"creative_quality_passed":False}
    diagnostic={"native_goal_sha256":runner.digest(goal),"complete_semantic_and_setup_repair_qa":qa,
        "complete_same_source_goal_audits":[decision],
        "complete_native_same_source_goal_audit_reports":{"native_source_audit":report},"source_file_sha256":{}}
    monkeypatch.setattr(runner,"REVIEW_QUESTIONS",root/"REVIEW_QUESTIONS.json")
    monkeypatch.setattr(runner,"FIRST_DIAGNOSTICS",root/"FIRST_DIAGNOSTICS.json")
    runner.write(runner.REVIEW_QUESTIONS,qa)
    monkeypatch.setattr(runner,"build_revision_diagnostics",lambda seed:deepcopy(diagnostic))
    runner.write(root/"INHERITED_DIAGNOSTICS.json",diagnostic)
    first=runner.prepare_first_goal_request(inputs,profile,goal,diagnostic)
    runner.write(root/"FIRST_NATIVE_PLAN_REQUEST_PREVIEW.json",first)
    return runtime,root,sends,diagnostic,first


def test_first_whole_plan28_then_current_goal_three_audits_and_body_double_review(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,first=replay(tmp_path,monkeypatch,causal_scenario)
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(row) for row in sends]==["goal_plan","source","commitment","drama","opening_setup","complete_script","semantic","physical"]
    assert sends[0]==first["request"] and sends[0]["role"]=="writer"
    assert result["cumulative_goal_candidates_used"]==28 and result["native_goal_ordinal"]==616
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
def test_known_valid_current_plan_audit_failure_or_uncertainty_revises_complete_plan29(tmp_path,monkeypatch,causal_scenario,phase,mode):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{(phase,1):mode})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert result["cumulative_goal_candidates_used"]==29
    planned=[row for row in sends if service.phase(row)=="goal_plan"]
    assert len(planned)==2
    payload=json.loads(planned[1]["messages"][1]["content"])
    native=runner.read(root/f"goals/{phase}_native_audit_01.json")
    assert payload["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"][f"native_{phase}_audit"]==native
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
    assert result["cumulative_goal_candidates_used"]==29
    assert runtime.summary()["stage_calls"]["goal_audit"]==6
    assert sum(service.phase(row)=="goal_plan" for row in sends)==2
    assert not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_exact_old609_cannot_be_reaudited_when_planner_returns_unchanged_seed(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("goal_plan",1):"unchanged_original"})
    result=runner.run()
    assert result["status"]=="halt_unchanged_native_goal_requires_pipeline_diagnosis"
    assert [service.phase(row) for row in sends]==["goal_plan"]
    assert result["cumulative_goal_candidates_used"]==28
    assert not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_true_parent615_guard_full609_native611_R01_and_bound_semantic_counterexample_preview():
    summary=runner.prior_guard();binding,prepared=authorizer.build_binding()
    inputs=runner.read(ACTUAL_ROOT/"INPUTS.json");seed=runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    diagnostic=runner.build_revision_diagnostics(seed)
    assert payload["previous_complete_document"]==seed and payload["reference_fulltext"]==inputs["reference_fulltext"]
    supplied=payload["revision_diagnostics"]
    assert supplied["complete_native_same_source_goal_audit_reports"]["native_source_audit"]==runner.read(ACTUAL_ROOT/"call_611_goal_source_audit_00.json")["output"]
    assert supplied["semantic_counterexample_review"]["independent_semantic_counterexamples"]==runner.read(runner.REVIEW_QUESTIONS)["independent_semantic_counterexamples"]
    assert len(prepared["manifest"]["revision_feedback_projection"]["source4_compiled_tables_externalized"])==2
    assert "opening_setup_failures" not in json.dumps(supplied)
    assert "known_complete_source_report_revision" not in payload
    assert supplied["original611_not_inherited_as_new_goal_approval"]
    assert prepared["request"]["stage"]=="goal_plan" and prepared["request"]["role"]=="writer"
    assert prepared["request"]["parameters"]["max_completion_tokens"]==16000
    assert len(prepared["request"]["messages"][1]["content"])<100000
    assert (summary["effective_calls_started"],summary["effective_reported_tokens"],summary["effective_calls_with_known_usage"])==(615,12732559,613)
    runner.verify_authorization_request_binding(binding,diagnostic,prepared,binding["seed_native_identity"])
    for key in ("first_action_is_native_plan_rebuild","source_only_strict_protocol","known_native_goal_audit_content_uncertainty_allows_bounded_plan_revision","new_format_or_report_recovery_claimed"):
        drift=deepcopy(binding);drift[key]=not binding[key]
        with pytest.raises(ValueError):runner.verify_authorization_request_binding(drift,diagnostic,prepared,binding["seed_native_identity"])
    assert binding["parent_whole_plan_unused_capacity"]==2 and binding["new_cumulative_goal_candidates_maximum"]==29
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


def test_known_full_planner_contract_rejection_consumes27_then_complete_new28(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("goal_plan",1):"contract_fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(row) for row in sends[:3]]==["goal_plan","goal_plan","source"]
    assert result["cumulative_goal_candidates_used"]==29
    assert runner.read(root/"goals/native_01.json")==json.loads(sends[1]["messages"][1]["content"])["previous_complete_document"]
    service.assert_no_reentry(runtime,root,sends)


def test_actual_first_minimax_sdk_wire_preserves_R01_goal_QA_and_matches_future_lineage(tmp_path,monkeypatch):
    import httpx
    from tests import test_creative_m31_flash_role_clients_v1 as sdk
    from src.content_factory import creative_flat_lineage_verifier_v5 as lineage
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
    assert payload["revision_diagnostics"]["semantic_counterexample_review"]["independent_semantic_counterexamples"]==runner.read(runner.REVIEW_QUESTIONS)["independent_semantic_counterexamples"]
    assert lineage._outbound(lineage.VerificationCycle(),runner.PROJECT,evidence.root,request,evidence.identity_sha256)==actual
    proof=runner.read(evidence.root/"M31_WIRE_PREFLIGHT.json")
    assert proof["SDK_max_retries"]==0 and proof["HTTP_follow_redirects"] is False


def test_known_new_setup4_contract_failure_has_one_complete_revision_without_old_type_conversion(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("opening_setup",1):"null_orientation"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    setup_requests=[row for row in sends if service.phase(row)=="opening_setup"]
    assert len(setup_requests)==2 and result["opening_setup_calls"]==2
    invalid=runner.read(root/"setups/native_01.json")
    second=json.loads(setup_requests[1]["messages"][1]["content"])
    assert second["previous_opening_setup"]==invalid
    assert second["opening_setup_diagnostics"]["validation_error"]["code"]=="OPENING_SETUP_SCHEMA_INVALID"
    assert setup_requests[0]["input_provenance"]["opening_setup_contract_version"]=="creative_opening_setup/v4"
    assert result["cumulative_goal_candidates_used"]==28
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool"])
def test_new_setup4_interface_unknown_stops_after_one_native_call(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("opening_setup",1):mode})
    result=runner.run()
    assert result["status"]=="halt_opening_setup_interface_or_unknown",result
    assert sum(service.phase(row)=="opening_setup" for row in sends)==1
    assert all(service.phase(row)!="complete_script" for row in sends)
    service.assert_no_reentry(runtime,root,sends)


def test_new_setup4_two_rejections_close_local_capacity_without_body_or_third_setup(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("opening_setup",1):"null_orientation",("opening_setup",2):"null_orientation"})
    result=runner.run()
    assert result["status"]=="halt_opening_setup_content_capacity_exhausted"
    assert sum(service.phase(row)=="opening_setup" for row in sends)==2
    assert all(service.phase(row)!="complete_script" for row in sends)
    assert result["parent_whole_plan_unused_capacity"]==2
    service.assert_no_reentry(runtime,root,sends)


def test_three_complete_bodies_and_six_same_source_full_audits_are_bounded(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("physical",1):"fail",("physical",2):"fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert runtime.summary()["stage_calls"]["complete_script"]==3
    assert runtime.summary()["stage_calls"]["full_review"]==6
    assert result["cumulative_goal_candidates_used"]==28
    service.assert_no_reentry(runtime,root,sends)


def test_new_setup4_actual_sdk_wire_is_verified_by_unchanged_flat5(tmp_path,monkeypatch,causal_scenario):
    import httpx
    from tests import test_creative_m31_flash_role_clients_v1 as sdk
    from src.content_factory import creative_flat_lineage_verifier_v5 as lineage
    inputs,_,goal,*_=causal_scenario
    prepared=runner.workflow.prepare_opening_setup_request(inputs,runner.read(runner.PROFILE),goal)
    request,sent=prepared["request"],[]
    assert request["input_provenance"]["opening_setup_contract_version"]=="creative_opening_setup/v4"
    assert request["structured_schema"]["properties"]["schema"]["const"]=="creative_opening_setup/v4"
    monkeypatch.setattr(runner.clients,"role_config",lambda role:SimpleNamespace(
        model=runner.clients.WRITER_MODEL,api_key=sdk.KEY,base_url="https://api.minimax.cn/v1"))
    client,evidence,_=sdk.setup(tmp_path,request,
        lambda outgoing:sent.append(outgoing.read()) or httpx.Response(200,content=sdk.reply()))
    sdk.call(client,request,evidence)
    assert len(sent)==1
    actual=json.loads(sent[0])
    assert actual==runner.clients.expected_wire_request(request)
    assert lineage._outbound(lineage.VerificationCycle(),runner.PROJECT,evidence.root,request,evidence.identity_sha256)==actual
    proof=runner.read(evidence.root/"M31_WIRE_PREFLIGHT.json")
    assert proof["SDK_max_retries"]==0 and proof["HTTP_follow_redirects"] is False


def test_real_registered_parent615_prepare_reads_original_seed_and_creates_only_isolated_root(tmp_path,monkeypatch):
    """Exercise the actual prepare function against the real closed parent."""
    actual_root,actual_claim=runner.ROOT,runner.CLAIM
    parent=runner.PREFLIGHT_PARENT
    assert not (parent/"goals/native_01.json").exists()
    original_seed=runner.read(parent/"INHERITED_NATIVE_GOAL.json")
    assert runner.read(parent/"goals/native_00.json")==original_seed
    assert not actual_root.exists() and not actual_claim.exists()
    frozen=runner.read(parent/"PRODUCTION_FREEZE.json")["files"]
    assert len(frozen)==1719
    assert {path:runner.sha_file(path) for path in frozen}==frozen
    protected=[runner.APPROVAL,runner.REQUEST_PREVIEW,runner.FIRST_DIAGNOSTICS,runner.REVIEW_QUESTIONS,
        parent/"CALL_LEDGER.json",parent/"STATE.json",parent/"TASKS.sqlite3"]
    before={str(path):runner.sha_file(path) for path in protected}
    saved_approval=runner.read(runner.APPROVAL)
    saved_preview=runner.read(runner.REQUEST_PREVIEW)
    # Source snapshot paths must remain within the real project. Default pytest
    # temp roots may be outside it, so allocate only the isolated output there.
    isolated=tmp_path
    if not isolated.resolve().is_relative_to(runner.PROJECT.resolve()):
        import uuid
        isolated=runner.PROJECT/"data/qa/creative_supermarket_native_setup_20261014"/"isolated_prepare_tests"/uuid.uuid4().hex
    root=isolated/"round24_isolated"
    monkeypatch.setattr(runner,"ROOT",root)
    monkeypatch.setattr(runner,"CLAIM",isolated/"claim/CLAIM.json")
    monkeypatch.setattr(runner,"CERTIFICATE",root/"CERTIFIED_PARENT_LINEAGE.json")
    original_runtime=runner.get_runtime
    def isolated_runtime():
        runtime=original_runtime()
        runtime.shared_lock=isolated/"DISPATCH.lock"
        return runtime
    monkeypatch.setattr(runner,"get_runtime",isolated_runtime)
    def forbid_provider(*args,**kwargs):raise AssertionError("real isolated prepare cannot dispatch a provider")
    monkeypatch.setattr(runner.strict_clients,"make_client_factory",forbid_provider)
    result=runner.prepare()
    assert result["new_calls"]==0
    assert (result["effective_calls_started"],result["effective_reported_tokens"],result["effective_calls_with_known_usage"])==(615,12732559,613)
    assert result["historical_pending_ordinals"]==[70,160] and result["unknown_token_reservations"]==93117
    assert result["stage_limits"]=={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}
    assert all(value==0 for value in result["stage_calls"].values())
    assert runner.read(root/"INHERITED_NATIVE_GOAL.json")==original_seed
    assert runner.read(root/"FIRST_NATIVE_PLAN_REQUEST_PREVIEW.json")==saved_preview["prepared"]
    assert runner.read(root/"CALL_LEDGER.json")["calls"]==[]
    assert not (root/"RUN_CLAIM.json").exists()
    scope=runner.read(root/"USER_SCOPE.json")
    assert scope["inherited_goal_candidates_used"]==27 and scope["local_goal_candidates_limit"]==2
    assert scope["cumulative_goal_candidates_this_run_maximum"]==29
    assert scope["parent_whole_plan_unused_capacity"]==2 and scope["parent_unused_capacity_stays_in_closed_run"]
    assert scope["local_opening_setup_limit"]==2 and scope["first_action_is_native_plan_rebuild"]
    freeze=runner.read(root/"PRODUCTION_FREEZE.json")
    assert freeze["continuation_authorization_sha256"]==before[str(runner.APPROVAL)]
    assert {path:runner.sha_file(path) for path in freeze["files"]}==freeze["files"]
    isolated_runtime().inherited_guard()
    assert runner.read(runner.APPROVAL)==saved_approval
    assert {str(path):runner.sha_file(path) for path in protected}==before
    assert {path:runner.sha_file(path) for path in frozen}==frozen
    assert not actual_root.exists() and not actual_claim.exists()
