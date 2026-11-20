"""Independent native-service replay and inherited603 identities; no live dispatch."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts import run_goal_context_text_production_v19 as runner
from scripts import record_legal_pragmatics_continuation_v1 as authorizer
from scripts import record_legal_pragmatics_diagnosis_v1 as recorder
from tests import test_goal_context_text_production_v18_independent_audit as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v2 import synthetic_source,add_legal_usage
from src.content_factory import creative_goal_legal_usage_source_audit_v2 as legal

INHERITED={"calls_started":603,"reported_tokens":12073493,"calls_with_known_usage":601,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
ACTUAL_PARENT=runner.PREFLIGHT_PARENT
ACTUAL_SOURCE_INPUTS=runner.read(ACTUAL_PARENT/"INPUTS.json")
PRIOR_GUARD,PREPARE=runner.prior_guard,runner.prepare


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError("v19 independent tests cannot contact providers")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket.socket,"connect_ex",deny)
    monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(runner.previous,"get_runtime",deny)
    monkeypatch.setattr(runner,"prior_guard",deny)


def replay(tmp_path,monkeypatch,scenario,modes=None):
    monkeypatch.setattr(service,"runner",runner)
    monkeypatch.setattr(service,"INHERITED",deepcopy(INHERITED))
    monkeypatch.setattr(service,"synthetic_source",synthetic_source)
    monkeypatch.setattr(service,"legal_audit",legal)
    def add(document,goal,ref,*,relation,status):
        row=add_legal_usage(document,goal,ref,relation=relation)
        if status=="pass" and relation=="contradicts":row["status"]="pass" # deliberate malformed v1/v2 mixture
        return row
    monkeypatch.setattr(service,"add_usage",add)
    return service.replay(tmp_path,monkeypatch,scenario,modes)


def test_source_gate_failure_reaches_complete_new_goal_without_losing_native_relation(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):"legal_fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(r) for r in sends[:4]]==["goal_plan","source","goal_plan","source"]
    rejected=runner.read(root/"goals/source_audit_decision_01.json")
    assert rejected["accepted"] is False and rejected["gate_origin"]=="explicit_native_relation_policy"
    finding=rejected["findings"][0]
    assert finding["gate"]=="fail" and "status" not in finding and "native_usage" in finding
    next_context=json.loads(sends[2]["messages"][1]["content"])
    forwarded=next_context["revision_diagnostics"]["complete_same_source_goal_audits"][0]["findings"][0]
    assert forwarded==finding and forwarded["required_revision"] and forwarded["native_usage"]["basis_relation"]=="contradicts"
    assert next_context["previous_complete_document"]==runner.read(root/"goals/native_01.json")
    assert result["inherited_goal_candidates_used"]==25 and result["cumulative_goal_candidates_used"]==27
    assert result["parent_whole_plan_unused_capacity"]==1 and result["parent_unused_capacity_stays_in_closed_run"] is True
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    assert [r["label"] for r in runner.read(runtime.ledger)["calls"] if r["label"].startswith("goal_plan_")]==["goal_plan_26","goal_plan_27"]
    handoff=runner.read(root/"TEXT_HANDOFF.json")
    assert handoff["native_goal_audit"]["native_source_audit"]["schema"]==legal.VERSION
    assert not handoff["media_authorized"] and not result["human_quality_approved"]
    service.assert_no_reentry(runtime,root,sends)


def test_new_bound_19_calls_keeps_old_unused1_and_director7_without_reset(tmp_path,monkeypatch,causal_scenario):
    modes={("drama",1):"goal_fail",("opening_setup",1):"contract_fail",("physical",1):"fail",("physical",2):"fail"}
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,modes)
    result=runner.run();spend=runtime.summary()
    assert result["status"]=="text_ready_for_director",result
    assert spend["stage_calls"]=={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}
    assert (spend["effective_calls_started"],spend["effective_reported_tokens"],spend["effective_calls_with_known_usage"])==(622,12075393,620)
    assert spend["unknown_token_reservations"]==93117 and spend["historical_pending_ordinals"]==[70,160]
    assert result["cumulative_goal_candidates_used"]==27 and result["opening_setup_calls"]==2
    assert result["parent_whole_plan_unused_capacity"]==1 and result["old_director_capacity"]=={"used":7,"limit":7,"remaining":0}
    assert not spend["old_budget_reset"] and not (root/"goals/native_03.json").exists()
    assert not (root/"scripts/version_04").exists()
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("part,mode",[("goal_plan","transport_unknown"),("goal_plan","usage_unknown"),("goal_plan","truncated"),
    ("goal_plan","missing_tool"),("source","transport_unknown"),("source","usage_unknown"),("source","truncated"),
    ("source","missing_tool"),("commitment","missing_tool"),("semantic","truncated")])
def test_unknown_truncated_or_missing_tool_never_uses_unused_parent_plan_or_restarts(tmp_path,monkeypatch,causal_scenario,part,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{(part,1):mode})
    result=runner.run()
    assert result["status"]!="text_ready_for_director"
    assert sum(service.phase(r)=="goal_plan" for r in sends)==1
    assert result["cumulative_goal_candidates_used"]==26 and result["parent_whole_plan_unused_capacity"]==1
    assert not (root/"TEXT_HANDOFF.json").exists() and not (root/"goals/native_02.json").exists()
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["legal_unknown","masked_legal_fail","missing_scan","mixed_authority","legacy_schema"])
def test_new_source_unknown_or_incomplete_native_contract_stops_before_focused_and_author(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    assert result["status"] in {"halt_goal_audit_uncertain","halt_goal_audit_contract_requires_pipeline_diagnosis"},result
    assert [service.phase(r) for r in sends]==["goal_plan","source"]
    assert not (root/"setups").exists() and not (root/"scripts").exists()
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["unknown","masked_fail","missing_commitments","mixed_context","mixed_goal"])
def test_three_native_audit_gate_cannot_be_bypassed_by_partial_or_conflicting_focused_package(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("commitment",1):mode})
    result=runner.run()
    assert result["status"]!="text_ready_for_director" and result["audit_kind"]=="commitment"
    assert [service.phase(r) for r in sends]==["goal_plan","source","commitment"]
    assert not (root/"scripts").exists()
    service.assert_no_reentry(runtime,root,sends)


def parent_fixture(tmp_path,monkeypatch):
    parent=tmp_path/"closed603";summary=runner.read(ACTUAL_PARENT/"STATE.json")["spend"]
    for name in ("STATE.json","USER_SCOPE.json","CALL_LEDGER.json","call_602_goal_plan_25.json","call_603_goal_source_audit_01.json"):
        runner.write(parent/name,runner.read(ACTUAL_PARENT/name))
    monkeypatch.setattr(runner,"PREFLIGHT_PARENT",parent);monkeypatch.setattr(runner,"PARENT_STATE",parent/"STATE.json")
    runtime=SimpleNamespace(ledger=parent/"CALL_LEDGER.json",summary=Mock(return_value=deepcopy(summary)),inherited_guard=Mock())
    monkeypatch.setattr(runner.previous,"get_runtime",Mock(return_value=runtime))
    monkeypatch.setattr(runner.original,"verify_receipt_evidence",Mock(return_value=parent))
    return parent,summary,runtime


def test_original603_complete_rejection_not_unknown_and_old_unused1_not_reclaimed(tmp_path,monkeypatch):
    parent,summary,runtime=parent_fixture(tmp_path,monkeypatch);before={p:p.read_bytes() for p in parent.glob("*.json")}
    assert PRIOR_GUARD()==summary
    assert runtime.inherited_guard.call_count==1 and runner.original.verify_receipt_evidence.call_count==2
    assert {p:p.read_bytes() for p in before}==before


@pytest.mark.parametrize("fault",["nonterminal","accepted603","usage_unknown","wrong_finish","changed_receipt_sha",
    "missing_call","wrong_stage","used_count","max_count","stage_count","unknown_reset"])
def test_changed_parent603_identity_or_capacity_stops_new_authorization(tmp_path,monkeypatch,fault):
    parent,summary,runtime=parent_fixture(tmp_path,monkeypatch)
    if fault in {"accepted603","usage_unknown","wrong_finish","changed_receipt_sha","wrong_stage"}:
        path=parent/"call_603_goal_source_audit_01.json";value=runner.read(path)
        if fault=="accepted603":value["validation"]={"accepted":True}
        elif fault=="usage_unknown":value["response_metadata"]["total_tokens"]=None
        elif fault=="wrong_finish":value["response_metadata"]["finish_reason"]="length"
        elif fault=="wrong_stage":value["request"]["stage"]="full_review"
        else:value["response_text"]="different"
        runner.write(path,value)
        if fault!="changed_receipt_sha":
            ledger=runner.read(runtime.ledger);ledger["calls"][-1]["receipt_sha256"]=runner.sha_file(path);runner.write(runtime.ledger,ledger)
    elif fault=="missing_call":
        ledger=runner.read(runtime.ledger);ledger["calls"].pop();runner.write(runtime.ledger,ledger)
    elif fault=="max_count":
        scope=runner.read(parent/"USER_SCOPE.json");scope["cumulative_goal_candidates_this_run_maximum"]=25;runner.write(parent/"USER_SCOPE.json",scope)
    else:
        state=runner.read(parent/"STATE.json")
        if fault=="nonterminal":state["status"]="goal_received"
        elif fault=="used_count":state["cumulative_goal_candidates_used"]=26
        elif fault=="stage_count":state["spend"]["stage_calls"]["goal_audit"]=2;runtime.summary.return_value=deepcopy(state["spend"])
        else:state["spend"]["unknown_token_reservations"]=0;runtime.summary.return_value=deepcopy(state["spend"])
        runner.write(parent/"STATE.json",state)
    with pytest.raises(ValueError):PRIOR_GUARD()


@pytest.fixture
def local_binding(tmp_path,monkeypatch):
    project=tmp_path/"binding";parent=project/"parent"
    paths={"PROJECT":project,"PREFLIGHT_PARENT":parent,"ROOT":project/"run","CLAIM":project/"grant/CLAIM.json",
        "APPROVAL":project/"grant/USER_CONTINUATION.json","PROFILE":project/"profile.json","PARENT_STATE":parent/"STATE.json",
        "INPUT_SUPPLEMENT_AUTHORIZATION":project/"old_supplement.json","USER_DIRECTION_CONFIRMATION":project/"confirmation.json",
        "REQUEST_PREVIEW":project/"preview.json"}
    for key,value in paths.items():monkeypatch.setattr(runner,key,value)
    authority=project/"old_authority.json";monkeypatch.setattr(runner.previous,"APPROVAL",authority)
    runner.write(authority,{"human_authorized":True,"user_quote":"minimax随便追加"})
    runner.write(runner.INPUT_SUPPLEMENT_AUTHORIZATION,{"original":"supplement"})
    runner.write(runner.USER_DIRECTION_CONFIRMATION,{"original":"confirmed story direction"})
    runner.write(parent/"INPUTS.json",{"source":"original ten user goals, law, R01"})
    runner.write(parent/"STATE.json",{"spend":{"effective_calls_started":603}})
    seed={"original":"native602"};runner.write(parent/"goals/native_01.json",seed)
    runner.write(parent/"native602.json",{"output":seed})
    runner.write(parent/"CALL_LEDGER.json",{"calls":[{"ordinal":602,"receipt":"native602.json"}]})
    runner.write(runner.PROFILE,{"model":"same"})
    monkeypatch.setattr(runner,"prior_guard",Mock(return_value={"closed":True}))
    monkeypatch.setattr(runner,"verify_inherited_direction_inputs",Mock(return_value={"original":"supplement"}))
    monkeypatch.setattr(runner,"verify_seed_native",Mock(return_value={"ordinal":602,"semantic_approved":False}))
    diag=Mock(return_value={"verified":"603 conflicts","pending":"602 risks"})
    prep=Mock(return_value={"request":{"source":"complete602 revision with latest goals"}})
    monkeypatch.setattr(runner,"build_revision_diagnostics",diag)
    monkeypatch.setattr(runner.workflow,"prepare_goal_request",prep)
    return project,diag,prep


def test_local_authorization_binds25_used26max1unused_and_recovers_only_identical_preview(local_binding):
    project,_,_=local_binding;authorizer.main();approval=runner.APPROVAL.read_bytes();preview=runner.REQUEST_PREVIEW.read_bytes()
    binding=runner.read(runner.APPROVAL)
    assert (binding["parent_goal_candidates_used"],binding["parent_whole_plan_maximum"],binding["parent_whole_plan_unused_capacity"],binding["new_cumulative_goal_candidates_maximum"])==(25,26,1,27)
    assert binding["seed_native_identity"]["ordinal"]==602 and not binding["media_authorized"]
    runner.REQUEST_PREVIEW.unlink();authorizer.main()
    assert runner.APPROVAL.read_bytes()==approval and runner.REQUEST_PREVIEW.read_bytes()==preview
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


@pytest.mark.parametrize("fault",["inputs","profile","diagnosis","actual_request","saved_preview","claim",
    "max_claim","seed_identity","automatic_retry","direction_evidence"])
def test_identity_capacity_and_authorization_drift_reject_before_any_new_claim(local_binding,monkeypatch,fault):
    from scripts import creative_flat_lineage_guard_v2 as lineage
    project,diag,prep=local_binding;authorizer.main()
    if fault=="inputs":runner.write(runner.PREFLIGHT_PARENT/"INPUTS.json",{"source":"changed"})
    elif fault=="profile":runner.write(runner.PROFILE,{"model":"changed"})
    elif fault=="diagnosis":diag.return_value["pending"]="changed"
    elif fault=="actual_request":prep.return_value["request"]["source"]="changed"
    elif fault=="saved_preview":runner.write(runner.REQUEST_PREVIEW,{"prepared":"different"})
    elif fault=="claim":runner.write(runner.CLAIM,{"original":"claim"})
    elif fault=="direction_evidence":runner.write(runner.USER_DIRECTION_CONFIRMATION,{"changed":"confirmation"})
    else:
        binding=runner.read(runner.APPROVAL)
        if fault=="max_claim":binding["new_cumulative_goal_candidates_maximum"]=28
        elif fault=="seed_identity":binding["seed_native_identity"]["ordinal"]=594
        else:binding["automatic_transport_retry"]=True
        runner.write(runner.APPROVAL,binding)
    before={p:p.read_bytes() for p in project.rglob("*.json")}
    monkeypatch.setattr(lineage,"build_lineage_certificate",Mock(return_value={"read_only":"certificate"}))
    monkeypatch.setattr(runner.parent,"source_gate",Mock(return_value={"offline":True}))
    writes=Mock(side_effect=AssertionError("drift must reject before any artifact/claim"));monkeypatch.setattr(runner,"write",writes)
    with pytest.raises((ValueError,RuntimeError)):PREPARE()
    assert writes.call_count==0 and not runner.ROOT.exists()
    assert {p:p.read_bytes() for p in before}==before


def test_actual_diagnosis_retains_complete603_and_four_pending_content_risks_without_adoption():
    native=runner.read(ACTUAL_PARENT/"goals/native_01.json");diag=recorder.build_diagnosis(ACTUAL_PARENT)
    assert len(diag["complete_original603_conflicts"])==20 and diag["parent_unused_goal_candidates"]==1
    assert [r["kind"] for r in diag["pending_content_risks"]]==["proposed_versus_agreed_termination","manager_risk_change_causal_trigger","unqualified_notebook_value_denial","cooler_sequence_and_folder_state_preconditions"]
    assert all(r["status"].startswith("pending_model") for r in diag["pending_content_risks"])
    assert diag["prior_legal_fault_evidence"]["original595_cc6_judgment"]["status"]=="pass"
    assert diag["prior_legal_fault_evidence"]["original596_cc6_status"]=="pass"
    assert not (ACTUAL_PARENT/"goals/source_native_audit_01.json").exists()
    assert runner.verify_seed_native(native)["semantic_approved"] is False


def test_latest_ten_user_rows_are_exactly_inherited_without_new_append_or_claim():
    before=deepcopy(ACTUAL_SOURCE_INPUTS)
    proof=runner.verify_inherited_direction_inputs(ACTUAL_SOURCE_INPUTS)
    assert ACTUAL_SOURCE_INPUTS==before
    assert sum(len(before["user_goal_contract"][key]) for key in ("constraints","audience_goals"))==10
    assert proof["appended_user_ids"]==["UC_CONFIRMED_SUPERMARKET_DIRECTION","UG_INTENSIFIED_EMOTIONAL_EXCHANGE"]


@pytest.mark.parametrize("fault",["lost_direction","duplicate_append","changed_old_goal"])
def test_inherited_human_goal_loss_duplicate_or_mutation_cannot_be_reauthorized(fault):
    value=deepcopy(ACTUAL_SOURCE_INPUTS)
    if fault=="lost_direction":value["user_goal_contract"]["constraints"].pop()
    elif fault=="duplicate_append":value["user_goal_contract"]["audience_goals"].append(deepcopy(value["user_goal_contract"]["audience_goals"][-1]))
    else:value["user_goal_contract"]["constraints"][0]["text"]="changed former user goal"
    with pytest.raises(ValueError):runner.verify_inherited_direction_inputs(value)


@pytest.mark.parametrize("fault",["conflict_count","pending_risk_as_pass","removed_risk","old_law_evidence","source_file","spend"])
def test_changed_qualified_diagnosis_cannot_become_writer_authority(tmp_path,monkeypatch,fault):
    seed=runner.read(ACTUAL_PARENT/"goals/native_01.json");diag=recorder.build_diagnosis(ACTUAL_PARENT)
    if fault=="conflict_count":diag["verified_failures"][0]["conflict_count"]=0
    elif fault=="pending_risk_as_pass":diag["pending_content_risks"][0]["status"]="pass"
    elif fault=="removed_risk":diag["pending_content_risks"].pop()
    elif fault=="old_law_evidence":diag["prior_legal_fault_evidence"]["original595_cc6_judgment"]["status"]="fail"
    elif fault=="source_file":diag["source_file_sha256"].pop(next(iter(diag["source_file_sha256"])))
    else:diag["parent_spend"]["effective_reported_tokens"]=0
    path=tmp_path/"diag.json";runner.write(path,diag);monkeypatch.setattr(runner,"CONTENT_DIAGNOSIS",path)
    with pytest.raises(ValueError):runner.build_revision_diagnostics(seed)


def test_actual602_latest_direction_and_full_R01_reach_initial_request_and_source_gate_feedback():
    seed=runner.read(ACTUAL_PARENT/"goals/native_01.json");diag=runner.build_revision_diagnostics(seed)
    prepared=runner.workflow.prepare_goal_request(runner.revision_planning_inputs(ACTUAL_SOURCE_INPUTS,seed,diag),runner.read(runner.PROFILE))
    body=json.loads(prepared["request"]["messages"][1]["content"])
    assert body["previous_complete_document"]==seed and body["reference_fulltext"]==ACTUAL_SOURCE_INPUTS["reference_fulltext"]
    assert body["user_goal_contract"]["constraints"][-1]["id"]=="UC_CONFIRMED_SUPERMARKET_DIRECTION"
    assert body["user_goal_contract"]["audience_goals"][-1]["id"]=="UG_INTENSIFIED_EMOTIONAL_EXCHANGE"
    assert body["revision_diagnostics"]["verified_pipeline_diagnosis"]["pending_content_risks"]==diag["verified_pipeline_diagnosis"]["pending_content_risks"]
    request=runner.workflow.prepare_goal_source_audit_request(ACTUAL_SOURCE_INPUTS,runner.read(runner.PROFILE),seed)
    report=synthetic_source(seed,request["source_authority_context"],request["source_context_sha256"])
    row=add_legal_usage(report,seed,"G030",relation="contradicts")
    row["required_revision"]="New complete native plan must resolve the notebook framing; this synthetic failure is not a semantic gold label."
    decision=runner.workflow.validate_goal_source_audit(report,seed,context_sha256=request["source_context_sha256"],authority_context=request["source_authority_context"])
    next_request=runner.workflow.prepare_goal_request(runner.revision_planning_inputs(ACTUAL_SOURCE_INPUTS,seed,{"complete_same_source_goal_audits":[decision]}),runner.read(runner.PROFILE))
    second=json.loads(next_request["request"]["messages"][1]["content"])
    finding=second["revision_diagnostics"]["complete_same_source_goal_audits"][0]["findings"][0]
    assert finding["native_usage"]==row and finding["gate"]=="fail" and finding["required_revision"]==row["required_revision"]
    assert next_request["manifest"]["payload_identity"]["characters"]<=next_request["manifest"]["context_policy"]["max_payload_characters"]
    assert next_request["manifest"]["payload_identity"]["utf8_bytes"]<=next_request["manifest"]["context_policy"]["max_payload_utf8_bytes"]
