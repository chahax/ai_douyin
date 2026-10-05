from pathlib import Path
import json
import pytest,httpx,openai
from jsonschema import Draft202012Validator
from scripts import run_creative_resume_v6 as runner
from scripts import creative_evidenced_role_clients_v1 as client
from src.content_factory.creative_workflow_roles import RoleConfig

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path/'v6');monkeypatch.setattr(runner,'SHARED_LOCK',tmp_path/'test.lock')
    captured=[];native=openai.OpenAI
    old=runner.control.read(runner.previous.ROOT/'call_079_local_s6_d6_p001_r2.json')
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'offline-v6','model':'MiniMax-M3','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'t','type':'function','function':{'name':'submit_creative_json','arguments':old['response_text']}}]}}]})
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:native(**kw,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)))
    monkeypatch.setattr(client,'role_config',lambda role:RoleConfig('minimax','MiniMax-M3','https://api.minimaxi.com/v1','dummy-v6-key'))
    runner.prepare();return captured

def test_exact_original_invalid_response_rejected_by_transmitted_schema(prepared):
    ctx,d=runner.direction_source(6);inp=runner.physical.build_local_input(ctx,d,[]);schema=runner.physical.build_local_schema(inp)
    old=runner.control.read(runner.previous.ROOT/'call_079_local_s6_d6_p001_r2.json')
    assert not list(Draft202012Validator(old['request']['inner_document_schema']).iter_errors(old['document_output']))
    assert list(Draft202012Validator(schema).iter_errors(old['document_output']))
    assert schema=={**runner.physical.base._local_schema(ctx,d,inp['shot_id'],runner.control.digest(inp)),'description':runner.physical.base.RULES}
    assert not prepared

def test_real_sdk_actual_messages_preserve_conditions_and_ledger(prepared):
    result=runner.local(6,1);assert len(prepared)==1 and result['status']=='contract_rejected'
    body=prepared[0];actual=json.loads(body['messages'][-1]['content'])['inner_document_schema']
    group=actual['properties']['step_units']['items']['properties']['groups']['items']
    assert group['allOf'] and group['properties']['operations']['items']['allOf']
    assert result['failure']['code']=='JSON_DOCUMENT_INNER_SCHEMA_REJECTED'
    assert runner.local(6,1)==result and len(prepared)==1
    spend=runner.summary();assert spend['effective_calls_started']==80 and spend['effective_reported_tokens']==872512 and spend['unknown_token_reservations']==64010
