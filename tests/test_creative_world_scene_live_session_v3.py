"""Offline SDK transport only. Synthetic parent proof is explicitly injected."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator

from scripts import creative_world_scene_live_session_v3 as m

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "data/qa/creative_world_scene_live_20261015"
OLD = ROOT / "data/production_trials/world_scene_live_20261015/round_02"
SCENARIO = ROOT / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("real network is not authorized")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(m.base.clients, "role_config", lambda role: SimpleNamespace(
        model=m.base.clients.WRITER_MODEL if role == "writer" else m.base.clients.REVIEW_MODEL,
        base_url="https://api.minimax.cn/v1" if role == "writer" else "https://api.deepseek.com/v1", api_key="offline-only"))


def setup_session(tmp_path, monkeypatch, fault=None):
    scenario = m.read(SCENARIO); inputs = scenario["inputs"]
    monkeypatch.setattr(m.base, "PROJECT", tmp_path)
    parent = tmp_path / "historical653"; parent.mkdir()
    for name,value in (("CODE",{"offline":True}),("SOURCE",{"offline":True}),("PROFILE",scenario["profile"]),
            ("PREFS",inputs["production_preferences"]),("GOALS",inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1",{"offline":True}),("USER_COUNT_UNIT_CONFIRMATION_v1",{"offline":True})):
        m.write(tmp_path/(name+".json"),value,True)
    m.write(parent/"INPUTS.json",inputs,True); m.write(parent/"SESSION_CONFIG.json",{"profile_path":str(tmp_path/"PROFILE.json")},True)
    template=m.read(OLD/"call_653_complete_script_03.json")
    def ref(ordinal,label,output,status="contract_valid"):
        receipt=deepcopy(template); receipt.update(ordinal=ordinal,label=label,output=deepcopy(output),status=status)
        path=parent/(label+".json");m.write(path,receipt,True)
        return {"path":str(path),"file_sha256":m.sha(path),"ordinal":ordinal,"label":label,
            "request_sha256":receipt["request_sha256"],"native_sha256":m.digest(output),"status":status}
    docs=scenario["documents"]
    goal_ref=ref(645,"whole_plan_02",docs["whole_plan_01"]["output"])
    audit_refs={kind:ref(646+i,kind+"_audit_02",docs[kind+"_audit_01"]["output"]) for i,kind in enumerate(m.base.workflow.AUDITS)}
    setup_ref=ref(650,"opening_setup_01",docs["opening_setup_01"]["output"])
    bad=deepcopy(docs["complete_script_01"]["output"]);bad["scene_contexts"][0]["previous_context_id"]=""
    rejected=[ref(651+i,f"complete_script_{i+1:02}",bad,"contract_rejected") for i in range(3)]
    anchor={"schema":"offline653-synthetic-proof-is-injected", "root":str(parent),
        "parent_identity":{"root":str(parent),"end_ordinal":653},
        "inherited":{"calls_started":653,"reported_tokens":13948653,"calls_with_known_usage":651,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "consumed_stage_calls":deepcopy(m.OLD_CONSUMED),"consumed_calls":13,"complete_scripts_used":3,"remaining_complete_scripts":0,
        "native_goal_receipt":goal_ref,"native_goal_audit_receipts":audit_refs,"native_opening_setup_receipt":setup_ref,
        "rejected_body_receipts":rejected}
    m.write(tmp_path/"PARENT.json",anchor,True)
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round16","OFFLINE independent body scope")
    seen=[];holder={}
    def client_factory(request):
        def respond(outgoing):
            label=holder["session"].pending_intent["label"];seen.append({"label":label,"wire":json.loads(outgoing.read())})
            if fault=="transport":raise httpx.ReadTimeout("offline unknown",request=outgoing)
            prefix,version=label.rsplit("_",1);source=prefix+f"_{int(version)-3:02}"
            output=deepcopy(docs[source]["output"])
            message={"role":"assistant","content":None,"tool_calls":[{"id":"offline-"+label,"type":"function",
                "function":{"name":m.base.clients.TOOL_NAME,"arguments":json.dumps(output,ensure_ascii=False)}}]}
            body={"id":"offline-"+label,"model":request["model"],"choices":[{"index":0,"message":message,"finish_reason":"tool_calls"}],
                "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
            return httpx.Response(200,content=json.dumps(body,ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request,http_client_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(respond),verify=False,**kw))
    cfg=m.Config(str(tmp_path/"run"),"offline-body04",str(tmp_path/"PARENT.json"),m.digest(anchor),str(tmp_path/"source"),
        str(tmp_path/"PREFS.json"),str(tmp_path/"GOALS.json"),str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round16",
        review_admission_module="src.content_factory.creative_full_review_protocol_v6")
    parent_verifier=lambda value,**k:{"verified":True,"inherited":value["inherited"],"source_files":{},"body_capacity_exhausted":True}
    session=m.Session(cfg,parent_verifier=parent_verifier,
        input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline":True},"source_files":[str(tmp_path/"SOURCE.json")]},
        source_gate=lambda *a,**k:{"valid":True,"current_source_freshness_verified":True},client_factory_builder=client_factory,
        review_adapter=m.base.workflow.full_reviews())
    monkeypatch.setattr(session,"code_files",lambda:[tmp_path/"CODE.json"]);holder["session"]=session
    preview=session.preview();m.write(cfg.authorization_path,session.authorization_template(preview),True);session.prepare()
    return session,seen,counter,scenario


def test_actual653_complete_feedback_once_budget_wire_local_and_no_native_change():
    anchor=m.read(QA/"SETTLED653_SPEND_ANCHOR_v1.json");seed=m.material(anchor)
    inputs=m.read(OLD/"INPUTS.json");profile=m.read(QA/"LIVE_PROFILE_v1.json")
    before=m.sha(OLD/"call_653_complete_script_03.json")
    wf=m.ReviewWorkflow(m.base.workflow,None,seed)
    prepared=wf.prepare_script_request(inputs,profile,seed["goal"],seed["audit_bundle"],opening_setup=seed["setup"],**wf.origin_ids(inputs))
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    assert payload["previous_complete_document"]==seed["rejected"] and payload["revision_diagnostics"]==seed["diagnostic"]
    assert len(payload["revision_diagnostics"]["findings"])==104
    assert prepared["manifest"]["payload_identity"]["characters"]<=140000
    assert prepared["manifest"]["payload_identity"]["utf8_bytes"]<=420000
    assert m.base.workflow.contexts._reference_occurrences(payload,inputs["reference_fulltext"])==1
    local=m.contract.refine_schema(m.base.workflow.world.build_script_schema(seed["goal"]))
    assert local==prepared["request"]["structured_schema"]
    assert list(Draft202012Validator(local).iter_errors(seed["rejected"]))
    with pytest.raises(m.contract.ScriptContractError) as caught:wf.validate_script_document(seed["rejected"],prepared["views"],inputs["production_preferences"])
    assert caught.value.detail["findings"]==seed["diagnostic"]["findings"]
    assert prepared["wire"]==m.base.clients.expected_wire_request(prepared["request"])
    assert m.sha(OLD/"call_653_complete_script_03.json")==before


def test_sdk_body04_two_full_reviews_raw_sql_and_handoff(tmp_path,monkeypatch):
    session,seen,_,scenario=setup_session(tmp_path,monkeypatch)
    result=session.run();assert result["status"]=="text_ready_for_director",result
    assert [x["label"] for x in seen]==["complete_script_04","full_review_semantic_04","full_review_physical_04"]
    assert result["spend"]["stage_limits"]==m.LIMITS and result["spend"]["effective_calls_started"]==656
    assert result["spend"]["effective_reported_tokens"]==13948953
    assert result["spend"]["historical_pending_ordinals"]==[70,160]
    with sqlite3.connect(session.root/"TASKS.sqlite3") as db:assert db.execute("select count(*) from attempts").fetchone()[0]==3
    monkeypatch.setattr(m.Session,"open",classmethod(lambda cls,root,**k:session))
    verified=m.verify_text_handoff(session.root);assert verified["accepted"] and not verified["authorizes_media_dispatch"]
    assert m.read(session.root/"TEXT_HANDOFF.json")["schema"]==m.VERSION+"/text_handoff"
    with pytest.raises(FileExistsError):session.run()
    # Re-certifying a hand-edited compiled artifact cannot turn it into a native.
    hand=m.read(session.root/"TEXT_HANDOFF.json");state=m.read(session.root/"STATE.json")
    rawpath=Path(hand["paths"]["raw_script"]);raw=m.read(rawpath);raw["title"]+=" edited"
    m.write(rawpath,raw);hand["artifact_file_sha256"][str(rawpath)]=m.sha(rawpath);hand["native_identity"]["raw_script"]=m.digest(raw)
    m.write(session.root/"TEXT_HANDOFF.json",hand);state["text_handoff_sha256"]=m.digest(hand);m.write(session.root/"STATE.json",state)
    with pytest.raises(ValueError,match="actual complete valid original"):m.verify_text_handoff(session.root)


def test_unknown_sends_only04_and_stops_without_regrant(tmp_path,monkeypatch):
    session,seen,_,_=setup_session(tmp_path,monkeypatch,fault="transport")
    result=session.run();assert result["status"]=="halt_interface_or_unknown" and len(seen)==1
    assert seen[0]["label"]=="complete_script_04" and not (session.root/"TEXT_HANDOFF.json").exists()
    assert result["spend"]["new_unknown_token_reservations"]>0
    with pytest.raises(FileExistsError):session.run()


def test_new_scope_old_labels_and_same_parent_new_grant_are_rejected(tmp_path,monkeypatch):
    session,seen,_,_=setup_session(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match="scope exhausted/unregistered"):
        session._admit("complete_script_01",{"stage":"complete_script"},{"calls":[]})
    scope=m.read(session.root/"USER_SCOPE.json");assert scope["old_body_calls_used"]==scope["old_body_capacity"]==3
    assert scope["total_new_calls_limit"]==9 and scope["old_scope_calls_used"]==13
    other=m.Session(replace(session.config,root=str(tmp_path/"other"),grant_id="other",authorization_path=str(tmp_path/"AUTH2.json")),
        parent_verifier=session.parent_verifier,input_builder=session.input_builder,source_gate=session.source_gate,review_adapter=session.injected_review_adapter)
    monkeypatch.setattr(other,"code_files",session.code_files)
    m.write(other.config.authorization_path,other.authorization_template(other.preview()),True)
    with pytest.raises(ValueError,match="unique successor"):other.prepare()
    assert not seen
