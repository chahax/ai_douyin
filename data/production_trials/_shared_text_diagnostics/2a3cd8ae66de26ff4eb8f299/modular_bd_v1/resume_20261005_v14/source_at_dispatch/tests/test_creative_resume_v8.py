import json
import pytest,httpx,openai
from scripts import run_creative_resume_v8 as runner
from scripts import creative_evidenced_role_clients_v1 as client
from src.content_factory.creative_workflow_roles import RoleConfig

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path/'v8');monkeypatch.setattr(runner,'SHARED_LOCK',tmp_path/'test.lock')
    native=openai.OpenAI;calls=[]
    def handler(req):
        calls.append(json.loads(req.content));doc={'dialogue_performance':'无对白；方澄站姿、林屿坐姿保持。','actions':[{'source_step_ref':'raw_linear_script.beats.0.steps.0','groups':[{'seconds':2.5,'subject':'C01','performance':'站姿与电影票、已挂的挎包同框建立。','operation':None,'satisfies':[]}]},{'source_step_ref':'raw_linear_script.beats.0.steps.1','groups':[{'seconds':2,'subject':'C02','performance':'右手沿桌面轻推明细单到两人之间侧，咖啡杯与结算单不动。','operation':{'kind':'slide','actor':'C02','target':'P05','value':'surface:E02:两人之间側'},'satisfies':[]}]}]}
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
    report=runner.summary();assert report['effective_calls_started']==94 and report['effective_reported_tokens']==1131234 and report['unknown_token_reservations']==64010
    verify=runner.control.read(runner.ROOT/'request_previews/local_s6_d6_p001_r1_INPUT_VERIFICATION.json');assert verify['full_reference_pack_in_actual_messages'] and verify['raw_s6_script_unchanged']

def test_one_operation_schema_rejects_tuple_array_multi_operation_and_bad_target(prepared):
    ctx,d=runner.direction_source(6);inp=runner.physical.build_local_input(ctx,d,[])
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    schema=runner.local_contract.build_schema(inp)
    gs=schema['properties']['actions']['items']['properties']['groups']['items']
    base={'seconds':1,'subject':'C02','performance':'轻推纸张','operation':{'kind':'slide','actor':'C02','target':'P05','value':'surface:E02:两人之间'},'satisfies':[]}
    assert not list(Draft202012Validator(gs).iter_errors(base))
    for bad in ([base['operation'],base['operation']],['slide','C02','P05','surface:E02:x'],{'kind':'slide','actor':'C02','target':'P05','value':'surface:E02:x','action_ref':'x'}):
        group={**base,'operation':bad}
        assert list(Draft202012Validator(gs).iter_errors(group))
    doc={'dialogue_performance':'本镜无对白','actions':[{'source_step_ref':'raw_linear_script.beats.0.steps.0','groups':[{**base,'subject':'C01','operation':None}]},{'source_step_ref':'raw_linear_script.beats.0.steps.1','groups':[deepcopy(base)]}]}
    doc['actions'][1]['groups'][0]['operation']={'kind':'gaze','actor':'C02','target':'P05','value':'P05'}
    with pytest.raises(Exception):runner.local_contract.derive_local(doc,inp)
    assert not prepared


def test_verified_parent_cache_still_rejects_changed_frozen_bytes(tmp_path,monkeypatch):
    p=tmp_path/'frozen.json';p.write_text('old')
    checks=[]
    monkeypatch.setattr(runner,'ROOT',tmp_path/'current')
    monkeypatch.setattr(runner,'_PARENT_CACHE',None)
    monkeypatch.setattr(runner,'_parent_fingerprint',lambda:{str(p):runner.control.sha_file(p)})
    monkeypatch.setattr(runner,'_parent_binding_uncached',lambda:checks.append(1) or ({},{},{}))
    assert runner.parent_binding()==({},{},{})
    assert runner.parent_binding()==({},{},{}) and checks==[1]
    p.write_text('changed')
    with pytest.raises(RuntimeError,match='frozen parent files changed'):runner.parent_binding()
