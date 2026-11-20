"""Independent known-native continuation; only SDK MockTransport can respond."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import creative_fresh_source_session_v2 as flow
from tests.test_creative_fresh_source_session_v1 import offline,setup_session,prepare,causal_scenario,prior_scenario


def setup_revision(tmp_path,monkeypatch,scenario,*,fault=None,wf=None):
    old,inputs,seen,builders,counter,reads=setup_session(tmp_path,monkeypatch,scenario,fault=fault)
    parent=tmp_path/"parent";parent.mkdir()
    native=deepcopy(scenario[2]);native["whole_plan"]["title"]="完整父稿；不得本地改写"
    receipt={"ordinal":621,"label":"whole_plan_01","status":"contract_rejected","request":{"model":old.profile["writer"]["model"]},
        "output":native,"failure":{"category":"validation","response_received":True,"code":"GOAL_NATIVE_PLANNING_INVALID"},
        "validation_error":{"code":"GOAL_NATIVE_PLANNING_INVALID","detail":{"findings":[{"code":"PARENT_EXACT_ERROR","path":"/beats/0/claim_refs"}]}},
        "response_metadata":{"http_status_code":200,"response_body_complete":True,"finish_reason":"tool_calls","total_tokens":25732,
            "output_mode":"tool_call","requested_model":old.profile["writer"]["model"],"response_model":old.profile["writer"]["model"]}}
    flow.write(parent/"call_621_whole_plan_01.json",receipt)
    flow.write(parent/"INPUTS.json",inputs);flow.write(parent/"STATE.json",{"status":"halt_contract_requires_pipeline_diagnosis","stage":"whole_plan","receipt_ordinal":621})
    flow.write(parent/"CALL_LEDGER.json",{"calls":[{"label":"whole_plan_01","receipt":"call_621_whole_plan_01.json","ordinal":621}]})
    flow.write(parent/"SESSION_CONFIG.json",{"anchor_path":old.config.anchor_path})
    inherited={**deepcopy(flow.shared.spend.INHERITED),"calls_started":621,"reported_tokens":12967256,"calls_with_known_usage":619}
    identity={"root":str(parent),"terminal_state_sha256":flow.sha(parent/"STATE.json"),"native_ledger_sha256":flow.sha(parent/"CALL_LEDGER.json"),"production_freeze_sha256":"0"*64,"end_ordinal":621}
    anchor={"schema":"creative_session_spend_anchor/v1","root":str(parent),"inherited":inherited,"whole_goal_candidates_used":1,
        "latest_native_goal_receipt":{"ordinal":621,"native_goal_sha256":flow.digest(native),"diagnostics_sha256":flow.digest(flow.shared.Session._diagnosis(receipt))},
        "parent_identity":identity,"parent_identity_sha256":flow.digest(identity)}
    path=tmp_path/"PARENT_ANCHOR.json";flow.write(path,anchor)
    def verify(value,*,expected_anchor_sha256):
        if flow.digest(value)!=expected_anchor_sha256:raise ValueError("anchor changed")
        return {"verified":True,"inherited":inherited}
    adapter=wf or SimpleNamespace(**{key:getattr(flow.shared.workflow,key) for key in dir(flow.shared.workflow) if not key.startswith("__")})
    if not hasattr(adapter,"ownership_evidence"):adapter.ownership_evidence=lambda value:{"original_contract_sha256":flow.digest(value["user_goal_contract"]),"offline_fixture_only":True}
    adapter.__file__=flow.shared.workflow.__file__
    config=flow.SessionConfig(**{**old.config.__dict__,"root":str(tmp_path/"revision"),"anchor_path":str(path),"anchor_sha256":flow.digest(anchor),"profile_path":str(flow.DEFAULT_PROFILE)})
    session=flow.Session(config,workflow_adapter=adapter,input_builder=old.input_builder,source_gate=old.source_gate,
        anchor_verifier=verify,client_factory_builder=old.client_factory_builder)
    monkeypatch.setattr(session,"claim",tmp_path/"V2_CLAIM.json");monkeypatch.setattr(session,"successor",tmp_path/"V2_SUCCESSOR.json")
    monkeypatch.setattr(session,"_parent_claim",lambda anchor:tmp_path/"PARENT_SUCCESSOR.json")
    return session,inputs,seen,builders,counter,reads,receipt


def test_native621_complete_original_and_diagnostics_enter_preview_once_no_claim(tmp_path,monkeypatch,causal_scenario):
    session,inputs,seen,builders,_,_,parent=setup_revision(tmp_path,monkeypatch,causal_scenario)
    before=json.dumps(parent,ensure_ascii=False);preview=session.preview();payload=json.loads(preview["first_request"]["request"]["messages"][1]["content"])
    assert payload["previous_complete_document"]==parent["output"]
    assert payload["revision_diagnostics"]==session._diagnosis(parent)
    assert payload["reference_fulltext"]==inputs["reference_fulltext"]
    assert preview["whole_plans_used"]==1 and preview["whole_plans_remaining"]==2
    assert preview["stage_limits"]=={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}
    assert json.dumps(parent,ensure_ascii=False)==before and not session.root.exists() and not session.claim.exists() and not seen and not builders


def test_known_plan_rejection_then_full_new_plan_and_all_three_audits_use_v2_workflow(tmp_path,monkeypatch,causal_scenario):
    session,inputs,seen,_,_,_,parent=setup_revision(tmp_path,monkeypatch,causal_scenario)
    original=session.wf.validate_goal_document;attempts=[]
    def validate(value,**kwargs):
        attempts.append(flow.digest(value))
        if len(attempts)==1:
            error=ValueError("EXACT_NEW_PLAN_ERROR");error.code="EXACT_NEW_PLAN_ERROR";raise error
        return original(value,**kwargs)
    monkeypatch.setattr(session.wf,"validate_goal_document",validate)
    prepare(session);result=session.run()
    assert result["status"]=="text_ready_for_director",result
    assert [phase for phase,_ in seen]==["plan","plan","source","commitment","drama","setup","complete_script","semantic","physical"]
    assert result["spend"]["effective_calls_started"]==630 and result["spend"]["effective_reported_tokens"]==12968156
    assert result["schema"]==flow.VERSION+"/state" and result["flow_version"]==flow.VERSION
    requests=[body for phase,body in seen if phase=="plan"]
    old=json.loads(requests[0]["messages"][1]["content"]);revised=json.loads(requests[1]["messages"][1]["content"])
    assert old["previous_complete_document"]==parent["output"]
    assert revised["previous_complete_document"]!=parent["output"] and "EXACT_NEW_PLAN_ERROR" in json.dumps(revised["revision_diagnostics"])
    assert flow.read(session.root/"TEXT_HANDOFF.json")["execution_requirement_evidence"]["manual_native_content_patch"] is False


def test_identical_new_plan_after_source_failure_cannot_redispatch_same_cached_audit(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario)
    original=session.wf.validate_goal_source_audit;attempts=[]
    def validate(value,*args,**kwargs):
        result=original(value,*args,**kwargs);attempts.append(True)
        if len(attempts)==1:result.update(accepted=False,findings=[{"code":"SEMANTIC_CASE_CONDITION_FAILED","message":"full new plan required"}])
        return result
    monkeypatch.setattr(session.wf,"validate_goal_source_audit",validate)
    prepare(session);result=session.run()
    assert result["status"]=="halt_cached_stage_no_new_progress",result
    assert [phase for phase,_ in seen]==["plan","source","plan"]
    assert len([row for row in flow.read(session.root/"CALL_LEDGER.json")["calls"] if row["label"].startswith("whole_plan_")])==2


@pytest.mark.parametrize("fault",["transport","usage_unknown","truncated","missing_tool"])
def test_unknown_or_protocol_plan_never_spends_remaining_plan_slot(tmp_path,monkeypatch,causal_scenario,fault):
    session,_,seen,_,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario,fault={"plan":fault})
    prepare(session);result=session.run()
    assert result["status"] in ("halt_interface_or_unknown","halt_protocol_requires_diagnosis"),result
    assert [phase for phase,_ in seen]==["plan"] and result["spend"]["effective_calls_started"]==622
    assert not (session.root/"TEXT_HANDOFF.json").exists()


def test_two_new_known_content_failures_exhaust_total_three_not_reset(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario,fault={"plan":"type"})
    prepare(session);result=session.run()
    assert result["status"]=="halt_whole_plan_lineage_capacity_exhausted",result
    assert [phase for phase,_ in seen]==["plan","plan"] and result["spend"]["effective_calls_started"]==623
    with pytest.raises(FileExistsError):session.run()


def test_same_parent_changed_anchor_identity_cannot_claim_second_child(tmp_path,monkeypatch,causal_scenario):
    first,_,seen,builders,counter,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario);prepare(first);before=counter.read()
    changed=deepcopy(flow.read(first.config.anchor_path));changed["new_verifier_version"]="different-canonical-anchor"
    assert flow.Session._parent_claim(first,changed)==flow.Session._parent_claim(first,flow.read(first.config.anchor_path))
    other=tmp_path/"OTHER_ANCHOR.json";flow.write(other,changed)
    second=flow.Session(replace(first.config,root=str(tmp_path/"other_child"),grant_id="other_child",anchor_path=str(other),
        anchor_sha256=flow.digest(changed),authorization_path=str(tmp_path/"OTHER_AUTH.json")),workflow_adapter=first.wf,
        input_builder=first.input_builder,source_gate=first.source_gate,anchor_verifier=first.anchor_verifier,client_factory_builder=first.client_factory_builder)
    monkeypatch.setattr(second,"claim",tmp_path/"SECOND_CLAIM.json");monkeypatch.setattr(second,"successor",tmp_path/"SECOND_ANCHOR_CLAIM.json")
    monkeypatch.setattr(second,"_parent_claim",first._parent_claim)
    with pytest.raises(FileExistsError,match="parent session"):second.prepare()
    assert not second.root.exists() and not second.claim.exists() and not second.successor.exists() and not seen and not builders and counter.read()==before


def test_current_round_stops_inside_locked_dispatch_after_dag_claim(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,counter,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario);prepare(session)
    claim=flow.shared.tasks.TaskStore.claim
    def stop(*args,**kwargs):
        value=claim(*args,**kwargs);proof=tmp_path/"STOP.json";flow.write(proof,{"stop":True});counter.stop("ten_reviews_completed",proof);return value
    monkeypatch.setattr(flow.shared.tasks.TaskStore,"claim",stop)
    with pytest.raises(ValueError,match="execution stopped"):session.run()
    assert not seen and not flow.read(session.root/"CALL_LEDGER.json")["calls"]
    assert flow.read(session.root/"STATE.json")["status"]=="halt_execution_exception_requires_reconciliation"


def test_current_source_expiry_blocks_dispatch_and_preserves_pending_spend_terminal(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario);prepare(session)
    def expired(*a,**k):raise ValueError("opportunity_outside_validity")
    monkeypatch.setattr(session,"source_gate",expired)
    with pytest.raises(ValueError,match="opportunity_outside_validity"):session.run()
    state=flow.read(session.root/"STATE.json")
    assert state["schema"]==flow.VERSION+"/state" and state["spend_verification_pending"] and state["spend"] is None and not seen


def test_incomplete_source_auditor_contract_stops_without_rewriting_good_plan(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario)
    def reject(*a,**k):raise ValueError("AUDITOR_FIXED_COVERAGE_MISSING")
    monkeypatch.setattr(session.wf,"validate_goal_source_audit",reject)
    prepare(session);result=session.run()
    assert result["status"]=="halt_goal_audit_contract_requires_diagnosis"
    assert [phase for phase,_ in seen]==["plan","source"]
    assert (session.root/"goal/version_02/source_native.json").exists()
    assert "AUDITOR_FIXED_COVERAGE_MISSING" in json.dumps(flow.read(session.root/"goal/version_02/source_contract_diagnostics.json"))


def test_body_wrong_contract_version_rejected_before_provider(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,builders,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario);prepare(session)
    with pytest.raises(ValueError,match="stage/request contract mismatch"):
        session._admit("complete_script_01",{"stage":"complete_script","structured_schema":{"properties":{"schema":{"const":"wrong-body-version"}}}},flow.read(session.root/"CALL_LEDGER.json"))
    assert not seen and not builders


def test_actual_workflow24_projection_keeps_original_input_and_failed_native_in_preview(tmp_path,monkeypatch,causal_scenario):
    from src.content_factory import creative_goal_context_workflow_v24 as adapter
    from tests.test_creative_goal_context_workflow_v24 import contract
    session,inputs,seen,builders,_,_,parent=setup_revision(tmp_path,monkeypatch,causal_scenario)
    inputs["user_goal_contract"]=contract();flow.write(Path(session._anchor()[0]["root"])/"INPUTS.json",inputs)
    session.input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline_only":True},"source_files":[]}
    session.wf=adapter;preview=session.preview();payload=json.loads(preview["first_request"]["request"]["messages"][1]["content"])
    assert preview["inputs"]["user_goal_contract"]==inputs["user_goal_contract"]
    assert payload["previous_complete_document"]==parent["output"]
    assert "UC_AUTONOMOUS_NATIVE" not in {row["id"] for row in payload["user_goal_contract"]["constraints"]}
    assert "UC_AUTONOMOUS_NATIVE" in {row["id"] for row in payload["user_goal_contract"]["execution_requirements"]}
    assert preview["first_request"]["manifest"]["workflow_version"]==adapter.VERSION
    assert hasattr(adapter,"validate_opening_setup_document") and adapter.windows.VERSION
    assert not seen and not builders and not session.root.exists()


def test_parent_already_text_ready_cannot_regrant_body_or_setup_capacity(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,builders,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario)
    parent=Path(flow.read(session.config.anchor_path)["root"])
    flow.write(parent/"STATE.json",{"status":"text_ready_for_director","stage":"complete_script","receipt_ordinal":625})
    with pytest.raises(ValueError,match="only a terminated known-complete rejected whole_plan"):session.preview()
    assert not session.root.exists() and not session.claim.exists() and not seen and not builders


def test_valid_semantic_source_failure_submits_complete_new_plan_and_rebuilds_all_audits(tmp_path,monkeypatch,causal_scenario):
    """Stage-control test, separate from the real-SDK happy path above."""
    from tests.test_creative_fresh_source_session_v1 import synthetic_source,synthetic_commitment
    session,inputs,seen,builders,_,_,_=setup_revision(tmp_path,monkeypatch,causal_scenario)
    goal=deepcopy(causal_scenario[2]);catalog=session.wf.fixed_legal_claim_catalog(inputs)
    for row in goal["claims"]:
        if row["kind"]=="verified_legal":
            ref=next(ref for ref in row["origin_ids"] if ref in catalog);row.update(origin_ids=[ref],text=catalog[ref]["text"])
    calls=[];plans=[]
    def native_model(runtime,label,prepared,validator):
        request=prepared["request"];schema=request["structured_schema"];calls.append((label,deepcopy(prepared)))
        if label.startswith("whole_plan_"):
            value=deepcopy(goal);value["whole_plan"]["premise"]+=" Synthetic complete revision "+label;plans.append(deepcopy(value))
        elif label.startswith("source_"):
            value=synthetic_source(plans[-1],prepared["source_authority_context"],schema["properties"]["audit_context_sha256"]["const"])
            if len(plans)==1:next(iter(value["claim_checks"].values())).update(status="fail",required_revision="Complete native plan must address case condition")
        elif label.startswith("commitment_"):
            value=synthetic_commitment(plans[-1])
            for key in ("schema","goal_sha256","audit_context_sha256"):value[key]=schema["properties"][key]["const"]
            for row in value["commitment_checks"].values():
                for usage in row["actual_usages"].values():usage.update(requirement_scope="local_event",comparison_refs=[])
        else:
            value=deepcopy(causal_scenario[4]["native_drama_audit"]);value.pop("commitment_checks",None)
            for key in ("schema","goal_sha256","audit_context_sha256"):value[key]=schema["properties"][key]["const"]
            value["closed_scope_findings"]=[];value["scope_observations"]={ref:{"audible_speakers":[],"operated_props":[]} for ref in schema["properties"]["scope_observations"]["properties"]}
        return {"ordinal":621+len(calls),"status":"contract_valid","request":request,"output":value,"validation":validator(value),
            "response_metadata":{"http_status_code":200,"response_body_complete":True,"finish_reason":"tool_calls","output_mode":"tool_call",
                "total_tokens":100,"requested_model":request["model"],"response_model":request["model"]}}
    prepare(session);monkeypatch.setattr(session,"invoke",native_model)
    monkeypatch.setattr(flow.driver,"opening",lambda *args:{"offline_unit_setup":True})
    monkeypatch.setattr(flow.driver,"body",lambda *args:{"status":"unit_goal_audits_completed"})
    result=session._flow(object(),inputs)
    assert result["status"]=="unit_goal_audits_completed"
    assert [label for label,_ in calls]==["whole_plan_02","source_audit_02","whole_plan_03","source_audit_03","commitment_audit_03","drama_audit_03"]
    revised=json.loads(calls[2][1]["request"]["messages"][1]["content"])
    assert revised["previous_complete_document"]==plans[0] and plans[1]!=plans[0]
    for label,prepared in calls[3:]:assert prepared["request"]["structured_schema"]["properties"]["goal_sha256"]["const"]==flow.digest(plans[1])
    assert not seen and not builders


def test_actual_workflow24_body_request_passes_real_admission_with_exact_beat_schema(tmp_path,monkeypatch,causal_scenario):
    from src.content_factory import creative_goal_context_workflow_v24 as adapter
    from tests.test_creative_goal_context_workflow_v24 import case,bundle
    session,_,seen,builders,_,_,parent_receipt=setup_revision(tmp_path,monkeypatch,causal_scenario)
    inputs,goal,opening,ids,native=case(causal_scenario)
    flow.write(Path(session._anchor()[0]["root"])/"INPUTS.json",inputs)
    session.input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline_only":True},"source_files":[]};session.wf=adapter
    prepare(session)
    planned={**deepcopy(parent_receipt),"status":"contract_valid","output":goal}
    setup={**deepcopy(parent_receipt),"status":"contract_valid","output":opening}
    flow.write(session.root/"MOCK_NATIVE_PLAN.json",planned);flow.write(session.root/"MOCK_NATIVE_SETUP.json",setup)
    ledger={"calls":[{"label":"whole_plan_02","receipt":"MOCK_NATIVE_PLAN.json"},{"label":"opening_setup_01","receipt":"MOCK_NATIVE_SETUP.json"}]}
    prepared=adapter.prepare_script_request(inputs,session.profile,goal,bundle(inputs,goal),opening_setup=opening,**adapter.origin_ids(inputs))
    assert session._admit("complete_script_01",prepared["request"],ledger) is True
    changed=deepcopy(prepared["request"]);changed["structured_schema"]["properties"]["beats"]["maxItems"]+=1
    with pytest.raises(ValueError,match="exact current native body schema"):session._admit("complete_script_01",changed,ledger)
    assert not seen and not builders
