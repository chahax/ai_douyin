"""Diagnostic MockTransport only; real parent proof is separately verified."""
from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_array_probe_session_v1 as m
from scripts import creative_world_scene_array_probe_cases_v1 as cases

ROOT=Path(__file__).resolve().parents[1]
PROFILE=ROOT/"data/qa/creative_world_scene_live_20261015/LIVE_PROFILE_v1.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("real network is forbidden")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(m.base.clients,"role_config",lambda role:SimpleNamespace(model=m.base.clients.WRITER_MODEL,
        base_url="https://api.minimax.cn/v1",api_key="offline-only"))


def setup_session(tmp_path,monkeypatch,*,fault=None):
    monkeypatch.setattr(m.base,"PROJECT",tmp_path)
    for name,value in (("CODE",{"offline":True}),("PARENT_STATE",{"offline":True}),
            ("PROFILE",m.read(PROFILE)),("AUTHORIZATION_AND_CADENCE_v1",{"offline":True}),
            ("USER_COUNT_UNIT_CONFIRMATION_v1",{"offline":True})):
        m.write(tmp_path/(name+".json"),value,True)
    anchor={"schema":"offline-injected-settled656","root":str(tmp_path/"historical656"),
        "parent_identity":{"root":str(tmp_path/"historical656"),"end_ordinal":656},
        "inherited":{"calls_started":656,"reported_tokens":14061496,"calls_with_known_usage":654,
            "pending_ordinals":[70,160],"unknown_token_reservations":93117},
        "cumulative_body_attempts_used":6,"remaining_complete_scripts":0}
    m.write(tmp_path/"PARENT.json",anchor,True)
    counter=m.base.CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round17","OFFLINE preregistered interface comparisons")
    sent=[];holder={}
    def builder(request):
        def respond(outgoing):
            label=holder["session"].pending_intent["label"];sent.append({"label":label,"wire":json.loads(outgoing.read())})
            if fault=="transport":raise httpx.ReadTimeout("OFFLINE unknown; no re-send",request=outgoing)
            output=cases.synthetic_control_output()
            if fault is None and len(sent)==1:output["beats"][0]["steps"]={"item":output["beats"][0]["steps"]}
            if fault=="empty_first" and len(sent)==1:output={}
            message={"role":"assistant","content":None,"tool_calls":[{"id":"offline-"+label,"type":"function",
                "function":{"name":m.base.clients.TOOL_NAME,"arguments":json.dumps(output,ensure_ascii=False)}}]}
            if fault=="missing_tool":message={"role":"assistant","content":json.dumps(output,ensure_ascii=False)}
            body={"id":"offline-"+label,"model":request["model"],"choices":[{"index":0,"message":message,
                "finish_reason":"length" if fault=="truncated" else "stop" if fault=="missing_tool" else "tool_calls"}],
                "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
            return httpx.Response(200,content=json.dumps(body,ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request,
            http_client_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(respond),verify=False,**kw))
    cfg=m.Config(str(tmp_path/"run"),"offline-array-four",str(tmp_path/"PARENT.json"),m.digest(anchor),
        str(tmp_path/"PROFILE.json"),str(tmp_path/"AUTH.json"),str(tmp_path),"round17")
    session=m.Session(cfg,parent_verifier=lambda v,**k:{"verified":True,"inherited":v["inherited"],
        "body_capacity_exhausted":True,"source_files":{str(tmp_path/"PARENT_STATE.json"):m.sha(tmp_path/"PARENT_STATE.json")}},
        client_factory_builder=builder)
    holder["session"]=session;monkeypatch.setattr(session,"code_files",lambda:[tmp_path/"CODE.json"])
    preview=session.preview();m.write(cfg.authorization_path,session.authorization_template(preview),True);session.prepare()
    return session,sent,counter


def test_four_preregistered_sdk_calls_continue_known_rejection_and_preserve_sql_raw(tmp_path,monkeypatch):
    session,sent,_=setup_session(tmp_path,monkeypatch)
    result=session.run();assert result["status"]=="diagnostic_completed_not_creative",result
    assert [x["label"] for x in sent]==["array_probe_"+x for x in m.CASE_IDS]
    assert result["complete_factorial"] and not result["text_ready_for_director"]
    assert not(session.root/"TEXT_HANDOFF.json").exists()
    summary=m.read(session.root/"SUMMARY.json")
    assert [x["validation"]["valid"] for x in summary["completed_known_cases"]]==[False,True,True,True]
    assert result["spend"]["stage_limits"]==m.LIMITS
    assert result["spend"]["effective_calls_started"]==660 and result["spend"]["effective_reported_tokens"]==14061896
    assert result["spend"]["historical_pending_ordinals"]==[70,160]
    ledger=m.read(session.root/"CALL_LEDGER.json");reader=m.base.evidence.Reader()
    receipts=[m.base.evidence.verify_original_receipt(session.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    m.base.evidence._tasks(reader,session.root,ledger,receipts,session.config.grant_id)
    assert [r["status"] for r in receipts]==["contract_rejected","contract_valid","contract_valid","contract_valid"]
    with sqlite3.connect(session.root/"TASKS.sqlite3") as db:assert db.execute("select count(*) from attempts").fetchone()[0]==4
    with pytest.raises(FileExistsError):session.run()


@pytest.mark.parametrize("fault",["transport","truncated","missing_tool"])
def test_unknown_or_protocol_stops_first_case_without_replay(tmp_path,monkeypatch,fault):
    session,sent,_=setup_session(tmp_path,monkeypatch,fault=fault)
    result=session.run();assert result["status"].startswith("halt_") and len(sent)==1,result
    assert result["status"]==("halt_protocol_requires_diagnosis" if fault=="missing_tool" else "halt_interface_or_unknown")
    assert not result["text_ready_for_director"] and not result["complete_factorial"]
    assert not(session.root/"TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError):session.run()


def test_no_fifth_case_or_same_parent_regrant(tmp_path,monkeypatch):
    session,sent,_=setup_session(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match="exhausted"):session._admit("anything",{}, {"calls":[{}]*4})
    second=m.Session(replace(session.config,root=str(tmp_path/"other"),grant_id="other",authorization_path=str(tmp_path/"AUTH2.json")),
        parent_verifier=session.parent_verifier)
    monkeypatch.setattr(second,"code_files",session.code_files)
    m.write(second.config.authorization_path,second.authorization_template(second.preview()),True)
    with pytest.raises(ValueError,match="unique successor"):second.prepare()
    assert not sent


def test_guard_failure_keeps_terminal_evidence_and_does_not_forge_current_spend(tmp_path,monkeypatch):
    session,sent,_=setup_session(tmp_path,monkeypatch)
    m.write(tmp_path/"CODE.json",{"offline":"changed after freeze"})
    result=session.run()
    assert result["status"]=="halt_execution_reconciliation" and not sent
    assert result["spend_verification_pending"] and result["spend"] is None
    assert (session.root/"RUN_CLAIM.json").exists() and (session.root/"EXECUTION_ERROR.json").exists()
    summary=m.read(session.root/"SUMMARY.json")
    assert summary["spend_verification_pending"] and summary["spend"] is None
    assert m.read(session.root/"CALL_LEDGER.json")["calls"]==[]
    with pytest.raises(FileExistsError):session.run()
