"""Actual SDK MockTransport; injected synthetic parent, no real provider/claim."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator

from scripts import creative_world_scene_live_session_v4 as m

ROOT=Path(__file__).resolve().parents[1]
SCENARIO=ROOT/"data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"
TEMPLATE=ROOT/"data/production_trials/world_scene_live_20261015/round_02/call_653_complete_script_03.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("real network forbidden")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(m.base.clients,"role_config",lambda role:SimpleNamespace(model=m.base.clients.WRITER_MODEL if role=="writer" else m.base.clients.REVIEW_MODEL,
        base_url="https://api.minimax.cn/v1" if role=="writer" else "https://api.deepseek.com/v1",api_key="offline-only"))


def setup_session(tmp_path,monkeypatch,*,fault=None):
    scenario=m.read(SCENARIO);inputs=scenario["inputs"];docs=scenario["documents"]
    monkeypatch.setattr(m.base,"PROJECT",tmp_path)
    for name,value in (("CODE",{"offline":True}),("SOURCE",{"offline":True}),("PROFILE",scenario["profile"]),
            ("PREFS",inputs["production_preferences"]),("GOALS",inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1",{"offline":True}),("USER_COUNT_UNIT_CONFIRMATION_v1",{"offline":True})):
        m.write(tmp_path/(name+".json"),value,True)
    creative=tmp_path/"creative656";creative.mkdir();toy=tmp_path/"toy660";toy.mkdir()
    m.write(creative/"INPUTS.json",inputs,True);m.write(creative/"SESSION_CONFIG.json",{"profile_path":str(tmp_path/"PROFILE.json")},True)
    m.write(toy/"INPUTS.json",{"toy_only_not_story":True},True)
    template=m.read(TEMPLATE)
    def ref(ordinal,label,output):
        r=deepcopy(template);r.update(ordinal=ordinal,label=label,output=deepcopy(output),status="contract_valid")
        p=creative/(label+".json");m.write(p,r,True)
        return {"path":str(p),"file_sha256":m.sha(p),"ordinal":ordinal,"label":label,"request_sha256":r["request_sha256"],
            "native_sha256":m.digest(output),"status":"contract_valid"}
    anchor={"schema":"offline-injected660","root":str(toy),"parent_identity":{"root":str(toy),"end_ordinal":660},
        "creative_source_root":str(creative),"source_files":{str(creative/n):m.sha(creative/n) for n in ("INPUTS.json","SESSION_CONFIG.json")},
        "inherited":{"calls_started":660,"reported_tokens":14073608,"calls_with_known_usage":658,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "native_goal_receipt":ref(645,"whole_plan_02",docs["whole_plan_01"]["output"]),
        "native_goal_audit_receipts":{kind:ref(646+i,kind+"_audit_02",docs[kind+"_audit_01"]["output"]) for i,kind in enumerate(m.base.workflow.AUDITS)},
        "native_opening_setup_receipt":ref(650,"opening_setup_01",docs["opening_setup_01"]["output"])}
    m.write(tmp_path/"PARENT.json",anchor,True)
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json");counter.begin_round("round18","OFFLINE direct fullbody")
    sent=[];holder={}
    def builder(request):
        def respond(outgoing):
            label=holder["s"].pending_intent["label"];sent.append({"label":label,"wire":json.loads(outgoing.read())})
            if fault=="transport":raise httpx.ReadTimeout("OFFLINE unknown",request=outgoing)
            if label.startswith("complete_script"):
                output=deepcopy(docs["complete_script_01"]["output"])
                if fault=="always_bad" or fault=="repair" and label=="complete_script_07":output["beats"][0]["steps"]={"item":output["beats"][0]["steps"]}
            else:output=deepcopy(docs[label.rsplit("_",1)[0]+"_01"]["output"])
            message={"role":"assistant","content":None,"tool_calls":[{"id":"offline-"+label,"type":"function",
                "function":{"name":m.base.clients.TOOL_NAME,"arguments":json.dumps(output,ensure_ascii=False)}}]}
            body={"id":"offline-"+label,"model":request["model"],"choices":[{"index":0,"message":message,"finish_reason":"tool_calls"}],
                "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
            return httpx.Response(200,content=json.dumps(body,ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request,http_client_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(respond),verify=False,**kw))
    cfg=m.Config(str(tmp_path/"run"),"offline-direct-two",str(tmp_path/"PARENT.json"),m.digest(anchor),str(tmp_path/"source"),
        str(tmp_path/"PREFS.json"),str(tmp_path/"GOALS.json"),str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round18",
        review_admission_module="src.content_factory.creative_full_review_protocol_v6")
    s=m.Session(cfg,parent_verifier=lambda a,**k:{"verified":True,"inherited":a["inherited"],"source_files":a["source_files"]},
        input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline":True},"source_files":[str(tmp_path/"SOURCE.json")]},
        source_gate=lambda *a,**k:{"valid":True,"current_source_freshness_verified":True},client_factory_builder=builder,
        review_adapter=m.base.workflow.full_reviews())
    holder["s"]=s;monkeypatch.setattr(s,"code_files",lambda:[tmp_path/"CODE.json"])
    preview=s.preview();m.write(cfg.authorization_path,s.authorization_template(preview),True);s.prepare()
    return s,sent,scenario


@pytest.mark.parametrize("fault",[None,"repair"])
def test_sdk_clean_direct_first_complete_repair_and_deep_handoff(tmp_path,monkeypatch,fault):
    s,sent,scenario=setup_session(tmp_path,monkeypatch,fault=fault)
    result=s.run();assert result["status"]=="text_ready_for_director",result
    labels=[r["label"] for r in sent]
    assert labels==(["complete_script_07","complete_script_08","full_review_semantic_08","full_review_physical_08"] if fault else
        ["complete_script_07","full_review_semantic_07","full_review_physical_07"])
    ledger=m.read(s.root/"CALL_LEDGER.json");first=m.read(s.root/ledger["calls"][0]["receipt"])
    payload=json.loads(first["request"]["messages"][1]["content"])
    assert "previous_complete_document" not in payload and "revision_diagnostics" not in payload
    assert payload["native_goal_document"]==scenario["documents"]["whole_plan_01"]["output"]
    assert result["spend"]["stage_limits"]==m.LIMITS and result["spend"]["effective_calls_started"]==660+len(sent)
    assert m.base.workflow.contexts._reference_occurrences(payload,scenario["inputs"]["reference_fulltext"])==1
    if fault:
        second=m.read(s.root/ledger["calls"][1]["receipt"]);body=json.loads(second["request"]["messages"][1]["content"])
        assert body["previous_complete_document"]==first["output"] and body["revision_diagnostics"]["findings"]
    monkeypatch.setattr(m.Session,"open",classmethod(lambda cls,root,**k:s))
    verified=m.verify_text_handoff(s.root);assert verified["valid"] and not verified["authorizes_media_dispatch"]
    assert verified["identity"]["native_script_sha256"]!=verified["identity"]["compiled_script_sha256"]
    with sqlite3.connect(s.root/"TASKS.sqlite3") as db:assert db.execute("select count(*) from attempts").fetchone()[0]==len(sent)
    with pytest.raises(FileExistsError):s.run()


@pytest.mark.parametrize("fault",["always_bad","transport"])
def test_two_body_capacity_or_unknown_stops_without_third_request(tmp_path,monkeypatch,fault):
    s,sent,_=setup_session(tmp_path,monkeypatch,fault=fault);result=s.run()
    assert result["status"]==("halt_live_script_capacity" if fault=="always_bad" else "halt_interface_or_unknown"),result
    assert [r["label"] for r in sent]==(["complete_script_07","complete_script_08"] if fault=="always_bad" else ["complete_script_07"])
    assert not(s.root/"TEXT_HANDOFF.json").exists()


def test_direct_wire_type_pass_cannot_replace_canonical_local_index_gate():
    scenario=m.read(SCENARIO);docs=scenario["documents"];g=docs["whole_plan_01"]["output"]
    wf=m.ReviewWorkflow(m.base.workflow,None);reports=[docs[k+"_audit_01"]["output"] for k in m.base.workflow.AUDITS]
    p=wf.prepare_script_request(scenario["inputs"],scenario["profile"],g,m.base.workflow.build_goal_audit_bundle(*reports),
        opening_setup=docs["opening_setup_01"]["output"],**wf.origin_ids(scenario["inputs"]))
    bad=deepcopy(docs["complete_script_01"]["output"]);actor=next(iter(bad["beats"][1]["ensemble"]))
    bad["beats"][1]["ensemble"][actor][0]["action_step_indexes"]=[999]
    assert not list(Draft202012Validator(p["request"]["structured_schema"]).iter_errors(bad))
    with pytest.raises(m.contract.ScriptContractError):wf.validate_script_document(bad,p["views"],scenario["inputs"]["production_preferences"])
