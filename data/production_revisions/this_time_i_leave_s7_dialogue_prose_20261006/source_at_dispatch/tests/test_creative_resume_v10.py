import json,pytest,httpx,openai
from copy import deepcopy
from jsonschema import Draft202012Validator
from scripts import run_creative_resume_v10 as runner
from scripts import creative_evidenced_role_clients_v1 as client
from scripts import creative_local_event_performance_v2 as split
from src.content_factory.creative_workflow_roles import RoleConfig


def prior_input(ordinal,label):
    root=runner.source.ROOT.parent/'resume_20261005_v9'
    row=runner.control.read(root/f'call_{ordinal:03}_{label}.json')
    bodies=[json.loads(m['content']) for m in row['request']['messages'] if m['role']=='user']
    inp=next(b['read_only_complete_context_and_direction'] for b in bodies if 'read_only_complete_context_and_direction' in b)
    return row,inp


def test_actual_failed_receipts_rejected_by_transmitted_typed_schema():
    for n,label in [(122,'plan_s6_d6_p007_r1'),(123,'plan_s6_d6_p007_r2')]:
        row,inp=prior_input(n,label)
        schema=split.plan_schema(inp)
        Draft202012Validator.check_schema(schema)
        errors=list(Draft202012Validator(schema).iter_errors(row['document_output']))
        assert errors  # 122 reaction bound to gaze; 123 face.target was actor ID.
    row,inp=prior_input(119,'plan_s6_d6_p006_r6')
    Draft202012Validator(split.plan_schema(inp)).validate(row['document_output'])
    bad=deepcopy(row['document_output']);bad['actions'][0]['events'][0]['subject']='C01'
    with pytest.raises(Exception):Draft202012Validator(split.plan_schema(inp)).validate(bad)


def test_actual_sdk_typed_plan_spend_and_single_dispatch(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path/'v10');monkeypatch.setattr(runner,'SHARED_LOCK',tmp_path/'lock')
    native=openai.OpenAI;calls=[]
    def ev(intent,op=None,ids=None):return {'intent':intent,'subject':'C02','operation':op,'satisfies':ids or []}
    def op(kind,target,value):return {'kind':kind,'actor':'C02','target':target,'value':value}
    doc={'actions':[{'source_step_ref':'raw_linear_script.beats.6.steps.0','events':[
        ev('转回桌前',op('face','','朝向E02桌前')),
        ev('看第一批注',op('gaze','','surface:E02:P05第一处红批')),
        ev('原握笔写第一处'),ev('看第二行',op('gaze','','surface:E02:P05第二行')),
        ev('第二行停住反应',None,['B07-R01']),
        ev('滑结算单对齐',op('slide','P06','surface:E02:P05旁对齐')),
        ev('比对结算',op('gaze','','surface:E02:P06')),
        ev('看回第二行',op('gaze','','surface:E02:P05第二行')),
        ev('原握笔点第二行'),ev('划掉重写'),ev('写完一笔停住'),
        ev('再对结算',op('gaze','','surface:E02:P06')),ev('继续比对修改')]}]}
    def handler(req):
        payload=json.loads(req.content);calls.append(payload)
        schema=json.loads(payload['messages'][-1]['content'])['inner_document_schema']
        Draft202012Validator(schema).validate(doc)
        assert schema['properties']['actions']['prefixItems'][0]['properties']['events']['items']['allOf']
        return httpx.Response(200,json={'id':'offline-v10','model':'MiniMax-M3','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'t','type':'function','function':{'name':'submit_creative_json','arguments':json.dumps({'payload_json':json.dumps(doc,ensure_ascii=False)})}}]}}]})
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:native(**kw,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)))
    monkeypatch.setattr(client,'role_config',lambda role:RoleConfig('minimax','MiniMax-M3','https://api.minimaxi.com/v1','dummy-v10-key'))
    runner.prepare();r=runner.plan(6,7)
    assert r['status']=='contract_valid' and r['validation']['not_actual_performance'] and len(calls)==1
    assert runner.plan(6,7)==r and len(calls)==1
    report=runner.summary()
    assert report['effective_calls_started']==124 and report['effective_reported_tokens']==1673120 and report['unknown_token_reservations']==64010
    with pytest.raises(Exception):runner.local(6,7)
    assert len(calls)==1


def test_complete_performance_preserves_all_model_authored_events():
    row,inp=prior_input(119,'plan_s6_d6_p006_r6');plan=row['document_output']
    perf={'dialogue_performance':'本镜无对白','performances':[{'slot':s['slot'],'seconds':1.5,'performance':s['intent']} for s in split.slots(plan)]}
    projected=split.performance_as_compact(perf,plan,inp)
    assert [[g['operation'] for g in a['groups']] for a in projected['actions']]==[[e['operation'] for e in a['events']] for a in plan['actions']]
    assert plan==row['document_output']
    bad=deepcopy(perf);bad['performances'].pop()
    with pytest.raises(Exception):split.performance_as_compact(bad,plan,inp)
