import json,pytest,httpx,openai
from copy import deepcopy
from scripts import run_creative_resume_v9 as runner
from scripts import creative_evidenced_role_clients_v1 as client
from scripts import creative_local_event_performance_v1 as split
from src.content_factory.creative_workflow_roles import RoleConfig


def test_plan_then_complete_performance_is_lossless_and_no_hidden_take_place():
    ctx,d,ls=runner.physical.make_surface_offline_case(untimed=True)
    inp=runner.physical.build_local_input(ctx,d,[])
    original=ls[0]
    events=[{'intent':g['performance'],'subject':g['hold_subject'] or 'C02','operation':g['operations'][0] if g['operations'] else None,'satisfies':[]} for g in original['step_units'][0]['groups']]
    plan={'actions':[{'source_step_ref':original['step_units'][0]['source_step_ref'],'events':events}]}
    planned=split.plan_as_compact(plan,inp)
    perf={'dialogue_performance':'完整原句自然说出。','performances':[{'slot':s['slot'],'seconds':1,'performance':s['intent']} for s in split.slots(plan)]}
    combined=split.performance_as_compact(perf,plan,inp)
    assert [g['operation'] for g in combined['actions'][0]['groups']]==[e['operation'] for e in events]
    assert plan=={'actions':[{'source_step_ref':original['step_units'][0]['source_step_ref'],'events':events}]}
    bad=deepcopy(perf);bad['performances'].append(bad['performances'][0])
    with pytest.raises(Exception):split.performance_as_compact(bad,plan,inp)


def test_actual_sdk_plan_projection_inherits_spend_and_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path/'v9');monkeypatch.setattr(runner,'SHARED_LOCK',tmp_path/'lock')
    native=openai.OpenAI;calls=[]
    doc={'actions':[{'source_step_ref':'raw_linear_script.beats.2.steps.0','events':[{'intent':'侧身','subject':'C02','operation':{'kind':'face','actor':'C02','target':'','value':'方澄桌角'},'satisfies':[]},*[e for prop in ['P03_Y','P03_P','P03_B'] for e in [{'intent':'抽出该便利贴','subject':'C02','operation':{'kind':'take','actor':'C02','target':prop,'value':'右手'},'satisfies':[]},{'intent':'摊到自己桌前','subject':'C02','operation':{'kind':'place','actor':'C02','target':prop,'value':'surface:E02:桌前'},'satisfies':[]}]],{'intent':'点浅黄','subject':'C02','operation':None,'satisfies':[]}]},{'source_step_ref':'raw_linear_script.beats.2.steps.2','events':[{'intent':'拿笔反转后手持等接','subject':'C02','operation':{'kind':'take','actor':'C02','target':'P07','value':'右手'},'satisfies':[]}]}]}
    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200,json={'id':'offline-v9','model':'MiniMax-M3','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'t','type':'function','function':{'name':'submit_creative_json','arguments':json.dumps({'payload_json':json.dumps(doc,ensure_ascii=False)})}}]}}]})
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:native(**kw,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)))
    monkeypatch.setattr(client,'role_config',lambda role:RoleConfig('minimax','MiniMax-M3','https://api.minimaxi.com/v1','dummy-v9-key'))
    runner.prepare();r=runner.plan(6,3)
    assert r['status']=='contract_valid' and r['validation']['not_actual_performance'] and len(calls)==1
    assert runner.plan(6,3)==r and len(calls)==1
    report=runner.summary();assert report['effective_calls_started']==97 and report['effective_reported_tokens']==1185855 and report['unknown_token_reservations']==64010
    with pytest.raises(Exception):runner.local(6,3)
    assert len(calls)==1


def test_changed_model_event_plan_invalidates_entire_old_performance():
    original={'actions':[{'source_step_ref':'source','events':[]}]}
    rec={'request':{'input_provenance':{'event_plan_sha256':runner.control.digest(original)}}}
    runner.assert_plan_binding(rec,{'output':original})
    with pytest.raises(RuntimeError,match='event plan changed'):
        runner.assert_plan_binding(rec,{'output':{'actions':[]}})
