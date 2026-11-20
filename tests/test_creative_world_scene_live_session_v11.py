"""Synthetic SDK calibration/content-repair control flow; never semantic proof."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_live_session_v11 as m

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


def setup_session(tmp_path,monkeypatch,*,unknown=False,miss=False):
    scenario=m.read(SCENARIO);inputs,docs=scenario["inputs"],scenario["documents"]
    monkeypatch.setattr(m.base,"PROJECT",tmp_path)
    for name,value in (("CODE",{"offline":True}),("SOURCE",{"offline":True}),("PROFILE",scenario["profile"]),
            ("PREFS",inputs["production_preferences"]),("GOALS",inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1",{"offline":True}),("USER_COUNT_UNIT_CONFIRMATION_v1",{"offline":True})):
        m.write(tmp_path/(name+".json"),value,True)
    original=tmp_path/"original_creation";original.mkdir();parent=tmp_path/"v10_source_metadata_contract_failure";parent.mkdir()
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
    anchor={"schema":"OFFLINE injected settled682 proof","root":str(parent),"creative_source_root":str(original),
        "parent_identity":{"root":str(parent),"end_ordinal":682},
        "source_files":{str(original/name):m.sha(original/name) for name in ("INPUTS.json","SESSION_CONFIG.json")},
        "inherited":{"calls_started":682,"reported_tokens":14835413,"calls_with_known_usage":680,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "current_text_scope_accounting":{"limits":m.PARENT_LIMITS,"consumed":m.PARENT_USED,"remaining":m.LIMITS,
            "calls_used":1,"calls_remaining":8,"body_used":0,"body_limit":2},
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
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json");counter.begin_round("round27","OFFLINE isolated ledger and entailment balance continuation")
    sent=[];holder={}
    def builder(request):
        def respond(outgoing):
            label=holder["session"].pending_intent["label"];sent.append({"label":label,"wire":json.loads(outgoing.read())})
            if unknown:raise httpx.ReadTimeout("OFFLINE unknown; no retry",request=outgoing)
            if label.startswith(("observable_events","event_entailment")):
                from tests.test_creative_isolated_event_entailment_v3 import synthetic_events,synthetic_comparison
                prepared=m.read(holder["session"].pending_intent["path"])["prepared"]
                if label.startswith("observable_events"):output=synthetic_events(prepared)
                else:output=synthetic_comparison(prepared,status="pass" if miss or "calibration" not in label else "fail")
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
        return m.base.clients.make_client_factory(request,http_client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(respond),verify=False,**kwargs))
    cfg=m.Config(str(tmp_path/"run"),"offline-v11-source-bound-payload",str(tmp_path/"PARENT.json"),m.digest(anchor),str(tmp_path/"source"),
        str(tmp_path/"PREFS.json"),str(tmp_path/"GOALS.json"),str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round27")
    session=m.Session(cfg,parent_verifier=lambda a,**k:{"verified":True,"inherited":a["inherited"],"source_files":a["source_files"]},
        input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline":True},"source_files":[str(tmp_path/"SOURCE.json")]},
        source_gate=lambda *a,**k:{"valid":True,"current_source_freshness_verified":True},client_factory_builder=builder)
    holder["session"]=session;monkeypatch.setattr(session,"code_files",lambda:[tmp_path/"CODE.json"])
    preview=session.preview();m.write(cfg.authorization_path,session.authorization_template(preview),True);session.prepare()
    return session,sent





def test_two_sdk_native_payloads_writer_request_and_exact_prefix_replay(tmp_path,monkeypatch):
    session,sent=setup_session(tmp_path,monkeypatch)
    captured={}
    class CaptureWriter(m.Driver):
        def invoke(self,label,prepared,validator):
            if label.startswith("complete_script_"):
                self.reserve_complete_chain(label)
                captured.update(label=label,prepared=deepcopy(prepared))
                raise m.base.Halt("offline_writer_prepared_not_dispatched")
            return super().invoke(label,prepared,validator)
    session.driver_type=CaptureWriter
    state=session.run()
    assert state["status"]=="offline_writer_prepared_not_dispatched",state
    assert [r["label"] for r in sent]==["observable_events_calibration_14","event_entailment_calibration_14"]
    assert captured["label"]=="complete_script_15"
    ledger=m.read(session.root/"CALL_LEDGER.json")
    assert state["spend"]["stage_limits"]==m.LIMITS and state["spend"]["effective_calls_started"]==684
    replay=session._replay(ledger,"complete_script_15",verify_validations=True)
    assert replay==captured["prepared"]
    reader=m.base.evidence.Reader()
    receipts=[m.base.evidence.verify_original_receipt(session.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    m.base.evidence._tasks(reader,session.root,ledger,receipts,session.config.grant_id)
    assert set(receipts[0]["output"])=={"steps","temporal_relations"}
    assert set(receipts[1]["output"])=={"fields","revision_target"}
    assert all(r["validation"]["native_report_sha256"]==m.digest(r["output"]) for r in receipts)
    for receipt in receipts:
        envelope=receipt["validation"]["local_source_envelope"]
        assert envelope["native_payload_sha256"]==m.digest(receipt["output"])
        assert envelope["actual_request_sha256"]==receipt["request_sha256"]
        assert envelope["domain_values_preserved_exact"] is True
        checking={**envelope["canonical_checking_headers"],**receipt["output"]}
        assert m.digest(checking)==envelope["canonical_checking_report_sha256"]
        assert envelope["canonical_checking_report_sha256"]!=envelope["native_payload_sha256"]
    first=m.read(session.root/"call_intents/observable_events_calibration_14.json")["prepared"]
    assert "OFFLINE_682_MUST_NOT_NORMALIZE" not in json.dumps(first["request"],ensure_ascii=False)
    assert "OFFLINE_680_DO_NOT_SEND_AS_TEMPLATE" not in json.dumps(first["request"],ensure_ascii=False)
    packet=json.loads(captured["prepared"]["request"]["messages"][1]["content"])["revision_diagnostics"]["native_enacted_review"]
    assert packet["native_claim_comparison_report"]==receipts[1]["output"]
    assert not(session.root/"TEXT_HANDOFF.json").exists()
    assert not any(r["label"].startswith("complete_script_") for r in ledger["calls"])
    assert m.read(session.root/"PRODUCTION_FREEZE.json")["total_new_calls_limit"]==8
    with pytest.raises(FileExistsError):session.run()


def test_six_review_remainder_reserves_complete_chain():
    driver=object.__new__(m.Driver);driver.calls=[{"label":"observable_events_calibration_14"},{"label":"event_entailment_calibration_14"}]
    driver.reserve_complete_chain("complete_script_15")
    driver.calls.append({"label":"event_entailment_synthetic"})
    with pytest.raises(m.base.Halt) as caught:driver.reserve_complete_chain("complete_script_15")
    assert caught.value.status=="halt_review_capacity_for_complete_chain"
    assert caught.value.details["remaining_reviews"]==3 and caught.value.details["unused_body_versions"]==[15,16]
    assert m.POLICY.limits=={"goal_plan":0,"goal_audit":0,"complete_script":2,"full_review":6}
