import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
import httpx
import openai
from src.content_factory.novel_adaptation import integrated_revision as n, prose_patch, contracts as c
from src.content_factory import serial_story_transport_v6 as t
from scripts import run_integrated_revision_trial as runner, serial_native_worker_v6 as worker

PRIOR=Path('data/corpus_production_trials/20261031_integrated_cn_endpoint')
PACKET={'chapters':[{'paragraphs':[{'id':'P1','text':'孩子自己盛饭。'}]}]}


def review(quote):
    return {'issues':[{'category':'continuity','severity':'must_fix','quote':quote,'source_ids':['P1'],
                       'reason':'新增重复动作','repair_constraint':'删除无据重复动作'}],'summary':'需修'}


def decision(text,value):
    return {'candidate_digest':c.digest(text),'review_digest':c.digest(value),
            'decisions':[{'index':0,'decision':'accept','reason':'原文只明确自盛，新增动作删除'}]}


def test_deletion_patch_preserves_unselected_prose_and_binding():
    text='开头。孩子自己盛饭。苏墨又给所有孩子盛满。结尾。';v=review('苏墨又给所有孩子盛满。')
    diag=n.diagnose(PACKET,text,v);plan=n.span_plan(text,v,diag,decision(text,v))
    assert not diag['issues'][0]['semantic_accepted']
    assert prose_patch.apply(text,plan,{'edit_0':''})=='开头。孩子自己盛饭。结尾。'
    with pytest.raises(ValueError):prose_patch.apply(text+'改过',plan,{'edit_0':''})
    with pytest.raises(c.ContractError):prose_patch.apply(text,plan,{'edit_0':'','edit_1':'改其他'})


@pytest.mark.parametrize('text,quote,ref',[('重复重复','重复','P1'),('原句','伪造','P1'),('原句','原句','不存在')])
def test_invalid_evidence_cannot_enter_patch(text,quote,ref):
    v=review(quote);v['issues'][0]['source_ids']=[ref];d=n.diagnose(PACKET,text,v)
    with pytest.raises(ValueError,match='invalid_issue_selected'):n.span_plan(text,v,d,decision(text,v))


def test_unresolved_or_stale_review_not_resolved_by_automatic_edit():
    v=review('原句');v['issues'][0]['severity']='unresolved';d=n.diagnose(PACKET,'原句',v)
    with pytest.raises(ValueError,match='cannot_resolve'):n.span_plan('原句',v,d,decision('原句',v))
    v['issues'][0]['severity']='must_fix'
    with pytest.raises(ValueError,match='binding'):n.span_plan('原句',v,d,decision('原句',v))


def test_role_specific_parameters_and_invalid_deepseek_effort(tmp_path):
    runner.prepare(tmp_path/'r',PRIOR);p=runner.read(tmp_path/'r/PLAN.json')
    assert p['max_calls']==348 and p['baseline_calls']==345
    assert p['endpoint_overrides']=={'writer':'https://api.minimax.cn/v1'} and 'endpoint_override' not in p
    args=t.request_args(p,'director',[],{})
    assert args['reasoning_effort']=='high' and args['extra_body']['thinking']['type']=='enabled'
    assert args['max_tokens']==32768 and 'max_completion_tokens' not in args and 'tools' not in args
    p['inference']['director_effort']='xhigh'
    with pytest.raises(ValueError):t.request_args(p,'director',[],{})


def test_stages_preserve_candidate_and_deepseek_is_independent(tmp_path,monkeypatch):
    r=tmp_path/'r';runner.prepare(r,PRIOR);original=(r/'ORIGINAL.md').read_text('utf-8');calls=[]
    packet=runner.read(r/'INPUT.json');quote='桌上摆着海鲜粥和煎的饼。苏墨给六个孩子盛好粥。'
    value=review(quote);value['issues'][0]['source_ids']=['CH20-P024']
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.plan,self.state=run,plan,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,role,deepcopy(payload)));self.state['calls_started']+=1
            result=value if name=='review' else {'edit_0':'桌上摆着海鲜粥和煎的饼。'} if name=='patch' else {'text':'模拟报告，不表示内容通过'}
            (self.run/(name+'.json')).write_text(json.dumps(result),encoding='utf-8')
            return result
    monkeypatch.setattr(runner,'DirectLedger',Fake);monkeypatch.setattr(runner,'Ledger',Fake)
    monkeypatch.setattr(runner,'NativeClient',lambda *a:None)
    monkeypatch.setattr(runner,'audit_folder',lambda f:{'completion_evidence':'known'})
    runner.execute(r,'review')
    with pytest.raises(ValueError,match='stage_not_ready'):runner.execute(r,'review')
    dec=r/'dec.json';dec.write_text(json.dumps(decision(original,value)),encoding='utf-8')
    runner.execute(r,'repair',dec);runner.execute(r,'final')
    assert [x[1] for x in calls]==['writer','writer','director']
    assert calls[2][0].startswith('FINAL_CONTENT')
    assert set(calls[2][2])=={'source','production_choices','candidate'}
    assert calls[2][2]['source']==packet and calls[2][2]['candidate']==(r/'SCREENPLAY.md').read_text('utf-8')
    assert (r/'ORIGINAL.md').read_text('utf-8')==original
    assert not runner.read(r/'FINAL_REVIEW_BINDING.json')['semantic_accepted']
    assert runner.read(r/'STATE.json')['calls_started']==348


def test_unknown_review_stops_later_stages(tmp_path,monkeypatch):
    r=tmp_path/'r';runner.prepare(r,PRIOR)
    class Unknown:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,*a):self.state.update(pending=346,calls_started=346);raise RuntimeError('unknown')
    monkeypatch.setattr(runner,'DirectLedger',Unknown);monkeypatch.setattr(runner,'NativeClient',lambda *a:None)
    runner.execute(r,'review');assert runner.read(r/'STATE.json')['status']=='outcome_unknown'
    with pytest.raises(ValueError):runner.execute(r,'repair')
    assert not (r/'SCREENPLAY.md').exists()


def test_real_worker_sdk_routes_deepseek_without_minimax_override(tmp_path,monkeypatch):
    r=tmp_path/'r';runner.prepare(r,PRIOR);plan=runner.read(r/'PLAN.json');capture=[]
    cfg=SimpleNamespace(provider='deepseek',base_url='https://api.deepseek.com/v1',api_key='offline-deepseek-key')
    real=openai.OpenAI
    def handler(req):
        capture.append((str(req.url),json.loads(req.content)))
        chunk={'id':'fixture','model':'deepseek-flash','object':'chat.completion.chunk','created':1,
               'choices':[{'index':0,'delta':{'content':'{"text":"ok"}'},'finish_reason':'stop'}],
               'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}}
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content='data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:real(**kw,http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    monkeypatch.setattr(t,'role_config',lambda role:cfg);monkeypatch.setattr(worker,'role_config',lambda role:cfg)
    class Child:
        def __init__(self,cmd):self.cmd=cmd;self.returncode=None
        def wait(self,timeout):worker.run(Path(self.cmd[-1]));self.returncode=0
    monkeypatch.setattr(t.subprocess,'Popen',Child)
    t.NativeClient(r,plan).call('director',[{'role':'user','content':'offline JSON test'}],c.obj(text=c.TEXT))
    url,args=capture[0];assert url=='https://api.deepseek.com/v1/chat/completions'
    assert args['thinking']=={'type':'enabled'} and args['reasoning_effort']=='high'
    assert args['max_tokens']==32768 and 'reasoning_split' not in args
    request=(r/'native_345/REQUEST.json').read_text('utf-8')
    assert 'endpoint_override' not in request and 'offline-deepseek-key' not in request
