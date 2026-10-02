from copy import deepcopy
import json
from types import SimpleNamespace as NS
import pytest
from src.content_factory.creative_response_contract import response_failure, receipt_failure, validation_failure
from src.content_factory.creative_workflow_roles import CreativeRoleClients, RoleConfig, RoleResult, RoleResponseError
from tests.test_creative_plan_patch_integration import setup
from tests.test_creative_action_plan_v2 import sample
from src.content_factory.creative_action_plan_v2 import schedule_action_plan


@pytest.mark.parametrize("mode,text", [("content_after_missing_tool_call", "分析"), ("content", '{"valid":true}')])
def test_body_fallback_is_never_a_structured_result(mode, text):
    f = response_failure({"output_mode":mode,"finish_reason":"stop"},text,require_tool=True)
    assert f["code"] == "REQUIRED_TOOL_MISSING" and f["automatic_retry"] is False


def test_truncation_precedes_missing_tool_even_with_a_complete_json_prefix():
    f=response_failure({"finish_reason":"length","output_mode":"content_after_missing_tool_call"},'{}',require_tool=True)
    assert f["code"]=="RESPONSE_TRUNCATED"


@pytest.mark.parametrize("status",["pending_response","call_failed_or_uncertain"])
def test_no_id_does_not_prove_provider_did_not_receive_request(status):
    f=receipt_failure({"status":status,"error":"APIConnectionError; request_id=unknown"})
    assert f["code"]=="OUTCOME_UNKNOWN" and f["next_action"]=="reconcile_original_request"


@pytest.mark.parametrize("reason,mode,text,code",[
    ("stop","content_after_missing_tool_call",'{"beats":[]}',"REQUIRED_TOOL_MISSING"),
    ("length","tool_call",'{}',"RESPONSE_TRUNCATED"),
    ("length","content_after_missing_tool_call","长分析","RESPONSE_TRUNCATED"),
])
def test_fresh_and_cached_stage_stop_without_second_dispatch(tmp_path,reason,mode,text,code):
    p,s,m=sample()
    w,_=setup(tmp_path,[])
    class Client:
        calls=0
        def call(self,*args,**kw):
            self.calls+=1
            return RoleResult(text,{"finish_reason":reason,"output_mode":mode,"total_tokens":101,"response_id":"fixture-paid"})
    client=Client();w.clients=client
    payload={"state_plan_version":p["schema"],"script":s,"static_visual_manifest":m,"plan_thinking_mode":"disabled"}
    before=deepcopy(payload)
    for _ in range(3):
        with pytest.raises(Exception,match=code):
            w._stage("director_state_plan__00","director",payload,lambda v:schedule_action_plan(v,s,m))
    record=json.loads((tmp_path/"director_state_plan__00.json").read_text(encoding="utf-8"))
    assert record["failure"]["code"]==code and record["response_text"]==text
    assert client.calls==1 and w.state["calls_started"]==1
    assert w.state["contract_repairs_used"]==w.state["format_repairs_used"]==0
    assert w._reported_tokens()==101 and payload==before
    assert not list(tmp_path.glob("*attempt*"))


def test_unknown_request_is_not_repeated_even_with_old_retry_flag(tmp_path):
    p,s,m=sample();w,_=setup(tmp_path,[]);w.retry_unconfirmed_transport=True
    class Unknown:
        calls=0
        def call(self,*a,**k):
            self.calls+=1
            raise RuntimeError("APIConnectionError; request_id=unknown")
    client=Unknown();w.clients=client
    payload={"state_plan_version":p["schema"],"script":s,"static_visual_manifest":m}
    with pytest.raises(RuntimeError,match="APIConnectionError"):
        w._stage("director_state_plan__00","director",payload,lambda v:None)
    for _ in range(2):
        with pytest.raises(Exception,match="OUTCOME_UNKNOWN"):
            w._stage("director_state_plan__00","director",payload,lambda v:None)
    assert client.calls==w.state["calls_started"]==1
    assert w.state["max_calls"]==5 and w.state["max_total_tokens"]==250000


@pytest.mark.parametrize("response_id",["","fixture-response"])
def test_rejected_provider_envelope_saved_and_usage_counted_once(tmp_path,monkeypatch,response_id):
    import openai
    import src.content_factory.creative_workflow_roles as roles
    response=NS(id=response_id,model="MiniMax-M3",usage=NS(total_tokens=91),
        choices=[NS(finish_reason="stop",message=NS(content="长分析",tool_calls=[]))])
    count=[]
    def create(**kwargs): count.append(kwargs);return response
    monkeypatch.setattr(roles,"role_config",lambda _:RoleConfig("minimax","MiniMax-M3","https://fixture.invalid","fixture"))
    monkeypatch.setattr(openai,"OpenAI",lambda **kw:NS(chat=NS(completions=NS(create=create))))
    p,s,m=sample();w,_=setup(tmp_path,[]);w.clients=CreativeRoleClients()
    payload={"state_plan_version":p["schema"],"script":s,"static_visual_manifest":m}
    with pytest.raises(RoleResponseError):
        w._stage("director_state_plan__00","director",payload,lambda v:None)
    r=json.loads((tmp_path/"director_state_plan__00.json").read_text(encoding="utf-8"))
    assert r["response_payload"]["choices"][0]["message"]["content"]=="长分析"
    assert r["failure"]["code"]=="REQUIRED_TOOL_MISSING"
    with pytest.raises(Exception,match="REQUIRED_TOOL_MISSING"):
        w._stage("director_state_plan__00","director",payload,lambda v:None)
    assert len(count)==1 and w._reported_tokens()==w.state["reported_tokens"]==91


def test_schema_type_error_uses_bounded_repair_not_interface_retry(tmp_path):
    from src.content_factory.creative_plan_patch import plan_digest
    p,s,m=sample();p["beats"][0]["groups"][0]["duration_seconds"]="1"
    patch={"source_sha256":plan_digest(p),"patches":[{"path":"beats.0.groups.0.duration_seconds","value":1}]}
    w,c=setup(tmp_path,[p,patch])
    payload={"state_plan_version":p["schema"],"script":s,"static_visual_manifest":m}
    out=w._stage("director_state_plan__00","director",payload,lambda v:schedule_action_plan(v,s,m))
    assert out["beats"][0]["groups"][0]["duration_seconds"]==1
    assert w.state["calls_started"]==2 and w.state["contract_repairs_used"]==1
    fault=json.loads(next(tmp_path.glob("*__validation_fault_*")).read_text(encoding="utf-8"))
    assert fault["failure"]["code"]=="PLAN_SCHEMA_INVALID"
    assert fault["failure"]["next_action"]=="bounded_schema_repair_then_full_validation"
    assert w._stage("director_state_plan__00","director",payload,lambda v:schedule_action_plan(v,s,m))==out
    assert len(c.calls)==2


@pytest.mark.parametrize("kind",["missing","truncated","unknown"])
def test_contract_repair_failure_does_not_repeat_on_resume(tmp_path,kind):
    from src.content_factory.creative_plan_patch import plan_digest
    p,s,m=sample();p["beats"][0]["groups"][0]["duration_seconds"]="1"
    w,_=setup(tmp_path,[])
    class BadRepair:
        calls=0
        def call(self,*a,**kw):
            self.calls+=1
            if kind=="unknown":raise RuntimeError("APIConnectionError; request_id=unknown")
            return RoleResult("{}",{"output_mode":"content_after_missing_tool_call","finish_reason":"length" if kind=="truncated" else "stop","total_tokens":13})
    c=BadRepair();w.clients=c
    payload={"state_plan_version":p["schema"],"script":s,"static_visual_manifest":m}
    for _ in range(2):
        with pytest.raises(Exception):
            w._validate_or_repair("director_state_plan__00","director",payload,p,lambda v:schedule_action_plan(v,s,m))
    assert c.calls==w.state["calls_started"]==1 and w.state["contract_repairs_used"]==1
    r=json.loads((tmp_path/"director_state_plan__00__contract_repair.json").read_text(encoding="utf-8"))
    assert r["failure"]["code"]=={"missing":"REQUIRED_TOOL_MISSING","truncated":"RESPONSE_TRUNCATED","unknown":"OUTCOME_UNKNOWN"}[kind]


def test_successful_schema_repair_replay_does_not_choose_a_second_filename(tmp_path):
    from src.content_factory.creative_plan_patch import plan_digest
    p,s,m=sample();p["beats"][0]["groups"][0]["duration_seconds"]="1"
    patch={"source_sha256":plan_digest(p),"patches":[{"path":"beats.0.groups.0.duration_seconds","value":1}]}
    w,c=setup(tmp_path,[patch])
    payload={"state_plan_version":p["schema"],"script":s,"static_visual_manifest":m}
    validate=lambda v:schedule_action_plan(v,s,m)
    first=w._validate_or_repair("director_state_plan__00","director",payload,p,validate)
    assert w._validate_or_repair("director_state_plan__00","director",payload,p,validate)==first
    assert len(c.calls)==w.state["calls_started"]==1 and w.state["contract_repairs_used"]==1


def test_successful_tool_result_exposes_safe_envelope_without_headers(monkeypatch):
    import openai
    import src.content_factory.creative_workflow_roles as roles
    response=NS(id="fixture-safe",model="MiniMax-M3",usage=NS(prompt_tokens=5,completion_tokens=6,total_tokens=11),
        choices=[NS(finish_reason="tool_calls",message=NS(content="safe content",reasoning_content="safe reasoning",
            tool_calls=[NS(id="tool-fixture",type="function",function=NS(name="submit_creative_json",arguments='{"ok":true}'))]))])
    sent=[]
    def create(**kwargs):sent.append(kwargs);return response
    monkeypatch.setattr(roles,"role_config",lambda _:RoleConfig("minimax","MiniMax-M3","https://fixture.invalid","secret-fixture-key"))
    monkeypatch.setattr(openai,"OpenAI",lambda **kwargs:NS(chat=NS(completions=NS(create=create))))
    result=CreativeRoleClients().call("writer",[{"role":"user","content":"fixture"}],thinking="disabled",structured_schema={"type":"object"})
    assert result.text=='{"ok":true}'
    assert result.response_payload["choices"][0]["message"]["reasoning_content"]=="safe reasoning"
    assert result.response_payload["choices"][0]["message"]["content"]=="safe content"
    assert result.response_payload["usage"]["total_tokens"]==11
    assert "secret-fixture-key" not in json.dumps(result.response_payload)
    assert "headers" not in result.response_payload
    assert sent[0]["extra_body"]=={"thinking":{"type":"disabled"}}
    assert sent[0]["tool_choice"]=={"type":"function","function":{"name":"submit_creative_json"}}
