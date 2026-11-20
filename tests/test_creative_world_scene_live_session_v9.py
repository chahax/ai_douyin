"""Synthetic SDK calibration/content-repair control flow; never semantic proof."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_live_session_v9 as m

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
    original=tmp_path/"original_creation";original.mkdir();parent=tmp_path/"v8_calibration_miss";parent.mkdir()
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
    anchor={"schema":"OFFLINE injected settled680 proof","root":str(parent),"creative_source_root":str(original),
        "parent_identity":{"root":str(parent),"end_ordinal":680},
        "source_files":{str(original/name):m.sha(original/name) for name in ("INPUTS.json","SESSION_CONFIG.json")},
        "inherited":{"calls_started":680,"reported_tokens":14804812,"calls_with_known_usage":678,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "current_text_scope_accounting":{"limits":m.PARENT_LIMITS,"consumed":m.PARENT_USED,"remaining":m.PARENT_REMAINING,
            "calls_used":1,"calls_remaining":10,"body_used":0,"body_limit":2},
        "current_native_goal_receipt":ref(665,"whole_plan_01",goal),
        "current_native_goal_audit_receipts":{kind:ref(666+i,kind+"_audit_01",docs[kind+"_audit_01"]["output"]) for i,kind in enumerate(m.base.workflow.AUDITS)},
        "current_native_opening_setup_receipt":ref(670,"opening_setup_01_01",setup),"accepted_source_state_audit_receipt":source_ref,
        "accepted_source_state_decision_ref":embedded,"accepted_source_state_prepared_ref":{"path":str(intent),"file_sha256":m.sha(intent),
            "json_pointer":"/prepared","native_sha256":m.digest(prepared),"context_sha256":prepared["context_sha256"]}}
    from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native
    anchor["current_valid_body_receipt"]=ref(678,"complete_script_14",synthetic_native(docs["complete_script_01"]["output"]))
    m.write(parent/"USER_SCOPE.json",{"schema":"OFFLINE original C8 scope","stage_limits":m.PARENT_LIMITS,"total_new_calls_limit":11},True)
    anchor.update(current_body_versions_unused=[15,16],unused_capacity_is_original_grant_balance_only=True,
        creative_body_capacity_regranted=False,continuation_of_original_grant="offline-original-v8-grant",calibration_missed=True)
    anchor["latest_calibration_receipt"]=ref(680,"old_calibration",{"marker":"OFFLINE_680_DO_NOT_SEND_AS_TEMPLATE"},validation={"valid":True,"accepted":True})
    old_intent=parent/"OLD_CALIBRATION_INTENT.json";m.write(old_intent,{"prepared":{"offline":True}},True)
    anchor["latest_calibration_decision_ref"]={"path":anchor["latest_calibration_receipt"]["path"],"file_sha256":anchor["latest_calibration_receipt"]["file_sha256"],"json_pointer":"/validation","native_sha256":m.digest({"valid":True,"accepted":True})}
    anchor["latest_calibration_prepared_ref"]={"path":str(old_intent),"file_sha256":m.sha(old_intent),"json_pointer":"/prepared","native_sha256":m.digest({"offline":True})}
    for key,path in (("inputs",parent/"INPUTS.json"),("profile",tmp_path/"PROFILE.json")):
        anchor.update({"current_"+key+"_path":str(path),"current_"+key+"_file_sha256":m.sha(path),"current_"+key+"_sha256":m.digest(m.read(path))})
    m.write(tmp_path/"PARENT.json",anchor,True)
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json");counter.begin_round("round25","OFFLINE isolated ledger and entailment balance continuation")
    sent=[];holder={}
    def builder(request):
        def respond(outgoing):
            label=holder["session"].pending_intent["label"];sent.append({"label":label,"wire":json.loads(outgoing.read())})
            if unknown:raise httpx.ReadTimeout("OFFLINE unknown; no retry",request=outgoing)
            if label.startswith(("observable_events","event_entailment")):
                from tests.test_creative_isolated_event_entailment_v1 import synthetic_events,synthetic_comparison
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
    cfg=m.Config(str(tmp_path/"run"),"offline-v9-entailment",str(tmp_path/"PARENT.json"),m.digest(anchor),str(tmp_path/"source"),
        str(tmp_path/"PREFS.json"),str(tmp_path/"GOALS.json"),str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round25")
    session=m.Session(cfg,parent_verifier=lambda a,**k:{"verified":True,"inherited":a["inherited"],"source_files":a["source_files"]},
        input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline":True},"source_files":[str(tmp_path/"SOURCE.json")]},
        source_gate=lambda *a,**k:{"valid":True,"current_source_freshness_verified":True},client_factory_builder=builder)
    holder["session"]=session;monkeypatch.setattr(session,"code_files",lambda:[tmp_path/"CODE.json"])
    preview=session.preview();m.write(cfg.authorization_path,session.authorization_template(preview),True);session.prepare()
    return session,sent


def test_sdk_isolated_calibration_fail_then_whole_body_four_reviews_and_deep_handoff(tmp_path,monkeypatch):
    session,sent=setup_session(tmp_path,monkeypatch);result=session.run()
    assert result["status"]=="text_ready_for_director",result
    assert [row["label"] for row in sent]==["observable_events_calibration_14","event_entailment_calibration_14","complete_script_15",
        "observable_events_15","event_entailment_15","full_review_semantic_15","full_review_physical_15"]
    assert result["spend"]["stage_limits"]==m.LIMITS and result["spend"]["effective_calls_started"]==687
    first=m.read(session.root/"call_intents/observable_events_calibration_14.json")["prepared"]["request"]
    assert "calibration_expected_admission" not in json.dumps(first,ensure_ascii=False)
    assert "OFFLINE_680_DO_NOT_SEND_AS_TEMPLATE" not in json.dumps(first,ensure_ascii=False)
    monkeypatch.setattr(m.Session,"open",classmethod(lambda cls,root,**k:session));proof=m.verify_text_handoff(session.root)
    raw,derived,compiled=(m.read(proof["paths"][key]) for key in ("raw_script","derived_script","compiled_script"))
    assert len({m.digest(raw),m.digest(derived),m.digest(compiled)})==3
    assert proof["identity"]["native_script_sha256"]==proof["source_descriptor"]["native_script_sha256"]==m.digest(raw)
    assert proof["identity"]["derived_script_sha256"]==m.digest(derived)
    assert m.read(proof["paths"]["calibration"])["known_counterexample_rejected"] is True
    packet=m.read(proof["paths"]["enacted_review"])
    assert packet["packet_is_model_native"] is False
    assert packet["verified_compiled_event_ledger"]==m.read(proof["paths"]["compiled_observable_ledger"])
    assert packet["native_observable_events_report"]==m.read(proof["paths"]["observable_events_report"])
    assert packet["native_claim_comparison_report"]==m.read(proof["paths"]["event_entailment_report"])
    body_intent=m.read(session.root/"call_intents/complete_script_15.json")["prepared"]["request"]
    feedback=json.loads(body_intent["messages"][1]["content"])["revision_diagnostics"]["native_enacted_review"]
    assert feedback["used_source_fields"] and all("text" not in row for row in feedback["used_source_fields"].values())
    assert m.read(session.root/"TEXT_HANDOFF.json")["decision"]["review_admission_version"]=="creative_world_scene_review_admission/v1"
    assert result["spend"]["stage_calls"]["full_review"]==6 and not proof["authorizes_media_dispatch"]
    with pytest.raises(FileExistsError):session.run()


def test_calibration_false_pass_stops_after_two_reviews_no_body(tmp_path,monkeypatch):
    session,sent=setup_session(tmp_path,monkeypatch,miss=True);result=session.run()
    assert result["status"]=="halt_calibration_missed",result
    assert [row["label"] for row in sent]==["observable_events_calibration_14","event_entailment_calibration_14"]
    assert not(session.root/"TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError):session.run()


def test_unknown_isolated_extraction_one_send_no_comparison_body_handoff(tmp_path,monkeypatch):
    session,sent=setup_session(tmp_path,monkeypatch,unknown=True);result=session.run()
    assert result["status"]=="halt_interface_or_unknown" and [row["label"] for row in sent]==["observable_events_calibration_14"],result
    assert result["spend"]["new_unknown_token_reservations"]>0 and not(session.root/"TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError):session.run()


def test_light_review_budget_preflight_preserves_unused_body():
    driver=object.__new__(m.Driver)
    driver.calls=[{"label":f"event_entailment_synthetic_{i}"} for i in range(4)]
    driver.reserve_complete_chain("complete_script_15")
    driver.calls.append({"label":"event_entailment_synthetic_4"})
    with pytest.raises(m.base.Halt) as caught:driver.reserve_complete_chain("complete_script_15")
    assert caught.value.status=="halt_review_capacity_for_complete_chain"
    assert caught.value.details["remaining_reviews"]==3 and caught.value.details["unused_body_versions"]==[15,16]
