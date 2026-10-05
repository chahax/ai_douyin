import json
import pytest,httpx,openai
from scripts import run_creative_resume_v7 as runner
from scripts import creative_evidenced_role_clients_v1 as client
from src.content_factory.creative_workflow_roles import RoleConfig

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path/'v7');monkeypatch.setattr(runner,'SHARED_LOCK',tmp_path/'test.lock')
    native=openai.OpenAI;calls=[]
    def handler(req):
        calls.append(json.loads(req.content));doc={'dialogue_performance':'无对白；方澄站姿、林屿坐姿保持。','actions':[{'source_step_ref':'raw_linear_script.beats.0.steps.0','groups':[{'seconds':2.5,'subject':'C01','performance':'站姿与电影票、已挂的挎包同框建立。','operations':[],'satisfies':[]}]},{'source_step_ref':'raw_linear_script.beats.0.steps.1','groups':[{'seconds':2,'subject':'C02','performance':'右手沿桌面轻推明细单到两人之间侧，咖啡杯与结算单不动。','operations':[['slide','C02','P05','surface:E02:两人之间側']],'satisfies':[]}]}]}
        body={'id':'offline-v7','model':'MiniMax-M3','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'t','type':'function','function':{'name':'submit_creative_json','arguments':json.dumps({'payload_json':json.dumps(doc,ensure_ascii=False)})}}]}}]}
        return httpx.Response(200,json=body)
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:native(**kw,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)))
    monkeypatch.setattr(client,'role_config',lambda role:RoleConfig('minimax','MiniMax-M3','https://api.minimaxi.com/v1','dummy-v7-key'))
    runner.prepare();return calls

def test_compact_actual_sdk_body_compiles_without_patch_or_model_metadata(prepared):
    r=runner.local(6,1);assert r['status']=='contract_valid' and len(prepared)==1
    raw=r['document_output'];derived=r['validation']['derived_local']
    assert set(raw)=={'dialogue_performance','actions'} and derived['duration_seconds']==4.5
    assert derived['step_units'][1]['groups'][0]['operations']==[{'kind':'slide','actor':'C02','target':'P05','value':'surface:E02:两人之间側'}]
    assert runner.local(6,1)==r and len(prepared)==1
    report=runner.summary();assert report['effective_calls_started']==82 and report['effective_reported_tokens']==910112 and report['unknown_token_reservations']==64010
    verify=runner.control.read(runner.ROOT/'request_previews/local_s6_d6_p001_r1_INPUT_VERIFICATION.json');assert verify['full_reference_pack_in_actual_messages'] and verify['raw_s6_script_unchanged']

def test_compact_order_and_four_column_operation_cannot_be_repaired(prepared):
    ctx,d=runner.direction_source(6);inp=runner.physical.build_local_input(ctx,d,[])
    old=runner.control.read(runner.previous.ROOT/'call_081_local_s6_d6_p001_r2.json');doc=json.loads(json.loads(old['response_text'])['payload_json'])
    with pytest.raises(Exception):runner.local_contract.derive_local(doc,inp)
    from scripts import creative_compact_local_contract_v1 as c
    schema=c.build_schema(inp);op=schema['properties']['actions']['items']['properties']['groups']['items']['properties']['operations']['items']
    from jsonschema import Draft202012Validator
    assert list(Draft202012Validator(op).iter_errors(['gaze','C02','P05','P05']))
    assert list(Draft202012Validator(op).iter_errors(['slide','C02','P05','surface:E02:x','extra']))
    assert not prepared
