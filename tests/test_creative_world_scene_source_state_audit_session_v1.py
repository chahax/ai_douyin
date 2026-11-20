"""One SDK diagnostic only; all service output/parent proofs are synthetic."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_source_state_audit_session_v1 as m

ROOT=Path(__file__).resolve().parents[1]
SCENARIO=ROOT/"data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"
TEMPLATE=ROOT/"data/production_trials/world_scene_live_20261015/round_02/call_653_complete_script_03.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("real network forbidden")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(m.base.clients,"role_config",lambda role:SimpleNamespace(model=m.base.clients.REVIEW_MODEL,
        base_url="https://api.deepseek.com/v1",api_key="offline-only"))


def setup_session(tmp_path,monkeypatch,*,unknown=False):
    scenario=m.read(SCENARIO);inputs=scenario["inputs"];docs=scenario["documents"]
    monkeypatch.setattr(m.base,"PROJECT",tmp_path)
    profile=deepcopy(scenario["profile"]);profile["stage_parameters"]["goal_audit"]["max_completion_tokens"]=32000
    for name,value in (("CODE",{"offline":True}),("SOURCE",{"offline":True}),("ORIGINAL_PROFILE",scenario["profile"]),
            ("PROFILE",profile),("PREFS",inputs["production_preferences"]),("GOALS",inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1",{"offline":True}),("USER_COUNT_UNIT_CONFIRMATION_v1",{"offline":True})):
        m.write(tmp_path/(name+".json"),value,True)
    source=tmp_path/"historical662";source.mkdir()
    m.write(source/"INPUTS.json",inputs,True)
    m.write(source/"SESSION_CONFIG.json",{"profile_path":str(tmp_path/"ORIGINAL_PROFILE.json")},True)
    template=m.read(TEMPLATE)
    def ref(ordinal,label,output):
        receipt=deepcopy(template);receipt.update(ordinal=ordinal,label=label,output=deepcopy(output),status="contract_valid")
        path=source/(label+".json");m.write(path,receipt,True)
        return {"path":str(path),"file_sha256":m.sha(path),"ordinal":ordinal,"label":label,
            "request_sha256":receipt["request_sha256"],"native_sha256":m.digest(output),"status":"contract_valid"}
    anchor={"schema":"offline-injected662-source-proof","root":str(source),"creative_source_root":str(source),
        "parent_identity":{"root":str(source),"end_ordinal":662},
        "source_files":{str(source/name):m.sha(source/name) for name in ("INPUTS.json","SESSION_CONFIG.json")},
        "inherited":{"calls_started":662,"reported_tokens":14131876,"calls_with_known_usage":660,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "native_goal_receipt":ref(645,"whole_plan_02",docs["whole_plan_01"]["output"]),
        "native_opening_setup_receipt":ref(650,"opening_setup_01",docs["opening_setup_01"]["output"])}
    m.write(tmp_path/"PARENT.json",anchor,True)
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round19","OFFLINE necessary source audit")
    sent=[];outputs=[];holder={}
    def builder(request):
        def respond(outgoing):
            sent.append(json.loads(outgoing.read()))
            if unknown:raise httpx.ReadTimeout("OFFLINE unknown; no retry",request=outgoing)
            from tests.test_creative_world_scene_source_state_audit_v1 import synthetic_report
            output=synthetic_report(holder["s"]._request(m.read(holder["s"].root/"INPUTS.json")),overall_status="fail")
            outputs.append(deepcopy(output))
            body={"id":"offline-source-diagnostic","model":request["model"],"choices":[{"index":0,
                "message":{"role":"assistant","content":None,"tool_calls":[{"id":"offline-tool","type":"function",
                    "function":{"name":m.base.clients.TOOL_NAME,"arguments":json.dumps(output,ensure_ascii=False)}}]},"finish_reason":"tool_calls"}],
                "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
            return httpx.Response(200,content=json.dumps(body,ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request,http_client_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(respond),verify=False,**kw))
    cfg=m.Config(str(tmp_path/"run"),"offline-one-source-audit",str(tmp_path/"PARENT.json"),m.digest(anchor),str(tmp_path/"source"),
        str(tmp_path/"PREFS.json"),str(tmp_path/"GOALS.json"),str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round19")
    s=m.Session(cfg,parent_verifier=lambda a,**k:{"verified":True,"inherited":a["inherited"],"source_files":a["source_files"]},
        input_builder=lambda *a,**k:{"inputs":deepcopy(inputs),"evidence":{"offline":True},"source_files":[str(tmp_path/"SOURCE.json")]},
        source_gate=lambda *a,**k:{"valid":True,"current_source_freshness_verified":True},client_factory_builder=builder)
    holder["s"]=s;monkeypatch.setattr(s,"code_files",lambda:[tmp_path/"CODE.json"])
    preview=s.preview();m.write(cfg.authorization_path,s.authorization_template(preview),True);s.prepare()
    return s,sent,outputs,scenario


def test_known_complete_semantic_failure_keeps_original_sdk_sql_and_stops(tmp_path,monkeypatch):
    s,sent,outputs,scenario=setup_session(tmp_path,monkeypatch)
    result=s.run();assert result["status"]=="diagnostic_completed_known_content_failure",result
    assert len(sent)==len(outputs)==1 and not result["text_ready_for_director"]
    assert m.read(s.root/"NATIVE_SOURCE_STATE_AUDIT.json")==outputs[0]
    decision=m.read(s.root/"SOURCE_STATE_AUDIT_DECISION.json")
    assert decision["valid"] and not decision["accepted"] and decision["findings"] and decision["contract_findings"]==[]
    assert result["spend"]["stage_limits"]==m.LIMITS and result["spend"]["effective_calls_started"]==663
    assert result["spend"]["effective_reported_tokens"]==14131976 and result["spend"]["historical_pending_ordinals"]==[70,160]
    ledger=m.read(s.root/"CALL_LEDGER.json");reader=m.base.evidence.Reader()
    receipts=[m.base.evidence.verify_original_receipt(s.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    m.base.evidence._tasks(reader,s.root,ledger,receipts,s.config.grant_id)
    assert receipts[0]["status"]=="contract_valid" and receipts[0]["validation"]["accepted"] is False
    payload=json.loads(receipts[0]["request"]["messages"][1]["content"])
    assert "original_inputs" not in payload
    assert payload["authority_inputs"]==s._request(scenario["inputs"])["views"]["authority_inputs"]
    assert payload["native_goal_document"]==scenario["documents"]["whole_plan_01"]["output"]
    assert payload["native_opening_setup_document"]==scenario["documents"]["opening_setup_01"]["output"]
    assert receipts[0]["request"]["parameters"]["max_completion_tokens"]==32000
    assert not(s.root/"TEXT_HANDOFF.json").exists()
    with sqlite3.connect(s.root/"TASKS.sqlite3") as db:assert db.execute("select count(*) from attempts").fetchone()[0]==1
    with pytest.raises(FileExistsError):s.run()


def test_unknown_only_one_send_no_native_adoption_or_repeated_run(tmp_path,monkeypatch):
    s,sent,outputs,_=setup_session(tmp_path,monkeypatch,unknown=True)
    result=s.run();assert result["status"]=="halt_interface_or_unknown" and len(sent)==1,result
    assert outputs==[] and result["spend"]["new_unknown_token_reservations"]>0
    assert not(s.root/"NATIVE_SOURCE_STATE_AUDIT.json").exists() and not(s.root/"TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError):s.run()
