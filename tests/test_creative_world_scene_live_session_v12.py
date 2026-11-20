"""Synthetic SDK calibration/content-repair control flow; never semantic proof."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_live_session_v12 as m

ROOT=Path(__file__).resolve().parents[1]
SCENARIO=ROOT/"data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"
TEMPLATE=ROOT/"data/production_trials/world_scene_live_20261015/round_02/call_653_complete_script_03.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError("real network forbidden")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(m.base.clients,"role_config",lambda role:SimpleNamespace(
        model=m.base.clients.WRITER_MODEL if role=="writer" else m.base.clients.REVIEW_MODEL,
        base_url="https://api.minimax.cn/v1" if role=="writer" else "https://api.deepseek.com/v1",api_key="offline-only"))
    monkeypatch.setattr(m.strict_clients().core,"role_config",m.base.clients.role_config)


def setup_session(tmp_path,monkeypatch,*,unknown=False,miss=False):
    scenario=m.read(SCENARIO);inputs,docs=scenario["inputs"],scenario["documents"]
    monkeypatch.setattr(m.base,"PROJECT",tmp_path)
    for name,value in (("CODE",{"offline":True}),("SOURCE",{"offline":True}),("PROFILE",scenario["profile"]),
            ("PREFS",inputs["production_preferences"]),("GOALS",inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1",{"offline":True}),("USER_COUNT_UNIT_CONFIRMATION_v1",{"offline":True})):
        m.write(tmp_path/(name+".json"),value,True)
    original=tmp_path/"original_creation";original.mkdir();parent=tmp_path/"v11_invalid_comparison";parent.mkdir()
    for directory in (original,parent):
        m.write(directory/"INPUTS.json",inputs,True);m.write(directory/"SESSION_CONFIG.json",{"profile_path":str(tmp_path/"PROFILE.json")},True)
    template=m.read(TEMPLATE)
    def ref(ordinal,label,output,*,request=None,validation=None):
        receipt=deepcopy(template);receipt.update(ordinal=ordinal,label=label,output=deepcopy(output),status="contract_valid")
        receipt.pop("failure",None);receipt.pop("validation_error",None)
        if request is not None:
            receipt.update(request=deepcopy(request),request_sha256=m.digest(request),stage=request["stage"])
            receipt["response_metadata"].update(requested_model=request["model"],response_model=request["model"])
        if validation is not None:receipt["validation"]=deepcopy(validation)
        path=parent/(label+".json");m.write(path,receipt,True)
        return {"path":str(path),"file_sha256":m.sha(path),"ordinal":ordinal,"label":label,
            "request_sha256":receipt["request_sha256"],"native_sha256":m.digest(output),"status":"contract_valid"}
    from scripts.creative_world_scene_replanned_workflow_v2 import ReviewWorkflow as SourceWorkflow
    from tests.test_creative_world_scene_source_state_audit_v4 import synthetic_report
    wf=SourceWorkflow(m.base.workflow,None);goal=docs["whole_plan_01"]["output"];setup=docs["opening_setup_01"]["output"]
    prepared=wf.prepare_source_state_audit_request(inputs,scenario["profile"],goal,setup);report=synthetic_report(prepared)
    decision=wf.validate_source_state_audit(report,prepared);assert decision["valid"] and decision["accepted"]
    source_ref=ref(672,"accepted_source",report,request=prepared["request"],validation=decision)
    intent=parent/"SOURCE_INTENT.json";m.write(intent,{"prepared":prepared},True)
    embedded={"path":source_ref["path"],"file_sha256":source_ref["file_sha256"],"json_pointer":"/validation","native_sha256":m.digest(decision)}
    anchor={"schema":"OFFLINE injected settled684 proof","root":str(parent),"creative_source_root":str(original),
        "parent_identity":{"root":str(parent),"end_ordinal":684},
        "source_files":{str(original/name):m.sha(original/name) for name in ("INPUTS.json","SESSION_CONFIG.json")},
        "inherited":{"calls_started":684,"reported_tokens":14882230,"calls_with_known_usage":682,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "current_text_scope_accounting":{"limits":m.PARENT_LIMITS,"consumed":m.PARENT_USED,"remaining":m.PARENT_REMAINING,
            "calls_used":2,"calls_remaining":6,"body_used":0,"body_limit":2},
        "current_native_goal_receipt":ref(665,"whole_plan_01",goal),
        "current_native_goal_audit_receipts":{kind:ref(666+i,kind+"_audit_01",docs[kind+"_audit_01"]["output"]) for i,kind in enumerate(m.base.workflow.AUDITS)},
        "current_native_opening_setup_receipt":ref(670,"opening_setup_01_01",setup),"accepted_source_state_audit_receipt":source_ref,
        "accepted_source_state_decision_ref":embedded,"accepted_source_state_prepared_ref":{"path":str(intent),"file_sha256":m.sha(intent),
            "json_pointer":"/prepared","native_sha256":m.digest(prepared),"context_sha256":prepared["context_sha256"]}}
    from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native
    anchor["current_valid_body_receipt"]=ref(678,"complete_script_14",synthetic_native(docs["complete_script_01"]["output"]))
    m.write(parent/"USER_SCOPE.json",{"schema":"OFFLINE original C8 scope","stage_limits":m.PARENT_LIMITS,"total_new_calls_limit":9},True)
    anchor.update(current_body_versions_unused=[15,16],unused_capacity_is_original_grant_balance_only=True,
        creative_body_capacity_regranted=False,continuation_of_original_grant="offline-original-v8-grant",calibration_missed=True)
    anchor["latest_calibration_receipt"]=ref(680,"old_calibration",{"marker":"OFFLINE_680_DO_NOT_SEND_AS_TEMPLATE"},validation={"valid":True,"accepted":True})
    old_intent=parent/"OLD_CALIBRATION_INTENT.json";m.write(old_intent,{"prepared":{"offline":True}},True)
    anchor["latest_calibration_decision_ref"]={"path":anchor["latest_calibration_receipt"]["path"],"file_sha256":anchor["latest_calibration_receipt"]["file_sha256"],"json_pointer":"/validation","native_sha256":m.digest({"valid":True,"accepted":True})}
    anchor["latest_calibration_prepared_ref"]={"path":str(old_intent),"file_sha256":m.sha(old_intent),"json_pointer":"/prepared","native_sha256":m.digest({"offline":True})}
    anchor["latest_observable_events_receipt"]=ref(682,"old_extractor_rejected",{"marker":"OFFLINE_682_MUST_NOT_NORMALIZE"},validation={"valid":False,"accepted":False,"ledger_usable":False})
    old_events_intent=parent/"OLD_EVENTS_INTENT.json";m.write(old_events_intent,{"prepared":{"offline":True}},True)
    anchor["latest_observable_events_decision_ref"]={"path":anchor["latest_observable_events_receipt"]["path"],"file_sha256":anchor["latest_observable_events_receipt"]["file_sha256"],"json_pointer":"/validation","native_sha256":m.digest({"valid":False,"accepted":False,"ledger_usable":False})}
    anchor["latest_observable_events_prepared_ref"]={"path":str(old_events_intent),"file_sha256":m.sha(old_events_intent),"json_pointer":"/prepared","native_sha256":m.digest({"offline":True})}
    for key,path in (("inputs",parent/"INPUTS.json"),("profile",tmp_path/"PROFILE.json")):
        anchor.update({"current_"+key+"_path":str(path),"current_"+key+"_file_sha256":m.sha(path),"current_"+key+"_sha256":m.digest(m.read(path))})
    m.write(tmp_path/"PARENT.json",anchor,True)
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json");counter.begin_round("round28","OFFLINE isolated ledger and entailment balance continuation")
    sent=[];holder={}
    def builder(request):
        def respond(outgoing):
            label=holder["session"].pending_intent["label"];sent.append({"label":label,"url":str(outgoing.url),"wire":json.loads(outgoing.read())})
            if unknown:raise httpx.ReadTimeout("OFFLINE unknown; no retry",request=outgoing)
            prepared=m.read(holder["session"].pending_intent["path"])["prepared"]
            if label.startswith("source_claims"):
                from tests.test_creative_isolated_source_claims_v1 import synthetic_claims
                output=synthetic_claims(prepared)
            elif label.startswith("claims_comparison"):
                from tests.test_creative_isolated_source_claims_v1 import synthetic_comparison
                output=synthetic_comparison(prepared,status="pass" if miss or "calibration" not in label else "fail")
            elif label.startswith("observable_events"):
                from tests.test_creative_isolated_event_entailment_v3 import synthetic_events
                output=synthetic_events(prepared)
            elif label.startswith("complete_script"):
                output=synthetic_native(docs["complete_script_01"]["output"])
                # A distinct synthetic native avoids replaying the calibration
                # request. This is request-identity testing, not story quality.
                output["title"] += "（OFFLINE 新整稿身份）"
            else:
                output=deepcopy(docs[label.rsplit("_",1)[0]+"_01"]["output"])
                # Binding a synthetic report to the actual new request does not
                # claim that a model assessed these contents.
                for key,rule in request["structured_schema"]["properties"].items():
                    if key in output and "const" in rule:output[key]=deepcopy(rule["const"])
                for row in output.get("world_scene_checks",{}).values():row["counterevidence"]=[]
            body={"id":"offline-"+label,"model":request["model"],"choices":[{"index":0,
                "message":{"role":"assistant","content":None,"tool_calls":[{"id":"tool-"+label,"type":"function",
                    "function":{"name":m.base.clients.TOOL_NAME,"arguments":json.dumps(output,ensure_ascii=False)}}]},"finish_reason":"tool_calls"}],
                "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
            return httpx.Response(200,content=json.dumps(body,ensure_ascii=False).encode())
        transport=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(respond),verify=False,**kwargs)
        if m.strict_stage(request):
            return m.strict_clients().make_client_factory(request,strict_claims=True,http_client_factory=transport)
        return m.base.clients.make_client_factory(request,http_client_factory=transport)
    cfg=m.Config(str(tmp_path/"run"),"offline-v12-frozen-source-claims",str(tmp_path/"PARENT.json"),m.digest(anchor),str(tmp_path/"source"),
        str(tmp_path/"PREFS.json"),str(tmp_path/"GOALS.json"),str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round28")
    session=m.Session(cfg,parent_verifier=lambda a,**k:{"verified":True,"inherited":a["inherited"],"source_files":a["source_files"]},
        input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline":True},"source_files":[str(tmp_path/"SOURCE.json")]},
        source_gate=lambda *a,**k:{"valid":True,"current_source_freshness_verified":True},client_factory_builder=builder)
    holder["session"]=session;monkeypatch.setattr(session,"code_files",lambda:[tmp_path/"CODE.json"])
    # Build a fresh synthetic inherited683 before this QA scope freezes. No
    # actual683 files are changed, normalized, or used as model fixture output.
    from scripts.creative_world_scene_replanned_workflow_v7 import ReviewWorkflow as FactsWorkflow
    from tests.test_creative_isolated_event_entailment_v3 import synthetic_events
    legacy=FactsWorkflow(m.base.workflow,None)
    material=m.prior.Session.source_material(session,legacy)
    ep=legacy.prepare_observable_events_request(inputs,scenario["profile"],material["calibration_native_script"],material["calibration_views"])
    en=synthetic_events(ep);ed=legacy.validate_observable_events(en,ep)
    assert ed["valid"] and ed["ledger_usable"] and not ed["uncertainties"]
    accepted=ref(683,"accepted_observable_events",en,request=ep["request"],validation=ed)
    ep_path=parent/"ACCEPTED_EVENTS_INTENT.json";m.write(ep_path,{"prepared":ep},True)
    anchor.update(accepted_observable_events_receipt=accepted,
        accepted_observable_events_prepared_ref={"path":str(ep_path),"file_sha256":m.sha(ep_path),"json_pointer":"/prepared","native_sha256":m.digest(ep)},
        accepted_observable_events_decision_ref={"path":accepted["path"],"file_sha256":accepted["file_sha256"],"json_pointer":"/validation","native_sha256":m.digest(ed)})
    for suffix in ("receipt","prepared_ref","decision_ref"):
        anchor["prior_observable_events_"+suffix]=deepcopy(anchor["latest_observable_events_"+suffix])
        anchor["latest_observable_events_"+suffix]=deepcopy(anchor["accepted_observable_events_"+suffix])
    m.write(tmp_path/"PARENT.json",anchor)
    session.config=type(cfg)(**{**cfg.__dict__,"parent_anchor_sha256":m.digest(anchor)})
    preview=session.preview();m.write(cfg.authorization_path,session.authorization_template(preview),True);session.prepare()
    return session,sent


def test_six_sdk_boundary_reuses683_strict_claims_writer_and_exact_replay(tmp_path,monkeypatch):
    session,sent=setup_session(tmp_path,monkeypatch);captured={}
    class CaptureSemantic(m.Driver):
        def invoke(self,label,prepared,validator):
            if label=="full_review_semantic_15":
                captured.update(label=label,prepared=deepcopy(prepared))
                raise m.base.Halt("offline_semantic_prepared_not_dispatched")
            return super().invoke(label,prepared,validator)
    session.driver_type=CaptureSemantic
    state=session.run()
    assert state["status"]=="offline_semantic_prepared_not_dispatched",state
    expected=["source_claims_calibration_14","claims_comparison_calibration_14","complete_script_15",
        "observable_events_15","source_claims_15","claims_comparison_15"]
    assert [r["label"] for r in sent]==expected
    ledger=m.read(session.root/"CALL_LEDGER.json")
    assert state["spend"]["stage_limits"]==m.LIMITS and state["spend"]["effective_calls_started"]==690
    assert state["deferred_original_body_versions"]==[16] and state["supplemental_review_calls"]==3
    replay=session._replay(ledger,captured["label"],verify_validations=True)
    assert replay==captured["prepared"]
    reader=m.base.evidence.Reader()
    receipts=[m.strict_clients().verify_original_receipt(session.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    m.base.evidence._tasks(reader,session.root,ledger,receipts,session.config.grant_id)
    for event,receipt in zip(sent,receipts):
        strict=event["label"].startswith(("source_claims","claims_comparison"))
        assert event["wire"]["tools"][0]["function"].get("strict",False) is strict
        if strict:
            assert event["url"]=="https://api.deepseek.com/beta/chat/completions"
            assert receipt["request"]["parameters"]["max_completion_tokens"]==16000
            assert receipt["response_metadata"]["selector_policy_version"]==m.strict_clients().VERSION
        if event["label"].startswith("source_claims"):
            payload=json.loads(receipt["request"]["messages"][1]["content"])
            assert set(payload)=={"actors","source_fields","source_units","source_unit_order"}
            assert "actual_ledger" not in payload and "expected_fail" not in payload
    authored=m.read(session.root/"call_intents/complete_script_15.json")["prepared"]
    payload=json.loads(authored["request"]["messages"][1]["content"])
    projected=payload["revision_diagnostics"]["native_enacted_review"]
    assert projected["native_source_claims_report"]==receipts[0]["output"]
    assert projected["native_claim_comparison_report"]==receipts[1]["output"]
    assert authored["manifest"]["isolated_writer_feedback_projection"]["complete_original_draft_preserved_exact"] is True
    assert captured["prepared"]["request"]["stage"]=="full_review"
    assert not(session.root/"TEXT_HANDOFF.json").exists()
    assert not any(r["label"] in ("observable_events_calibration_14","complete_script_16") for r in ledger["calls"])
    freeze=m.read(session.root/"PRODUCTION_FREEZE.json")
    assert freeze["stage_limits"]==m.LIMITS and freeze["total_new_calls_limit"]==8
    badrow={**ledger["calls"][0],"receipt_sha256":"0"*64}
    with pytest.raises(ValueError,match="original frozen file changed"):m.strict_clients().verify_original_receipt(session.root,badrow,ledger["source_manifest"],reader=m.base.evidence.Reader())
    with pytest.raises(FileExistsError):session.run()


def test_budget_and_deferred_body_preserve_original_capacity():
    driver=object.__new__(m.Driver);driver.calls=[{"label":"source_claims_calibration_14"},{"label":"claims_comparison_calibration_14"}]
    driver.preflight("complete_script_15")
    driver.calls.append({"label":"claims_comparison_synthetic"})
    with pytest.raises(m.base.Halt) as caught:driver.preflight("complete_script_15")
    assert caught.value.status=="halt_review_capacity_for_complete_chain" and caught.value.details["required_reviews"]==5
    with pytest.raises(m.base.Halt) as caught:driver.preflight("complete_script_16")
    assert caught.value.status=="halt_selected_original_body_capacity"
    assert caught.value.details["deferred_original_body_versions"]==[16]
    scope=m.scope_metadata()
    assert scope["original_body_capacity_total"]==2 and scope["selected_original_body_versions"]==[15]
    assert scope["original_review_capacity_remaining"]+scope["supplemental_review_calls"]==7
    assert scope["creative_body_capacity_regranted"] is False


def test_unknown_claims_stops_before_comparison_or_writer_without_dispatch():
    driver=object.__new__(m.Driver);driver.inputs={};driver.profile={};seen=[]
    driver.session=SimpleNamespace(accepted_observable_material=lambda *a:({}, {}, {"valid":True}))
    driver.wf=SimpleNamespace(prepare_source_claims_request=lambda *a:{"request":{"stage":"full_review"}},
        validate_source_claims=lambda *a:None)
    def invoke(label,prepared,validator):
        seen.append(label)
        return {},{"valid":True,"accepted":False,"claims_usable":False,"findings":[],"uncertainties":[{"reason":"OFFLINE unknown"}]},{}
    driver.invoke=invoke
    with pytest.raises(Exception) as caught:driver._focused({}, {}, "enacted_causality_calibration_14")
    assert caught.value.status=="halt_review_unknown"
    assert seen==["source_claims_calibration_14"]
