import json
from types import SimpleNamespace
from pathlib import Path
import pytest
import httpx
import openai
from src.content_factory import serial_story_transport_v6 as t
from scripts import serial_native_worker_v6 as w, run_integrated_effort_trial as runner


CFG=SimpleNamespace(provider='minimax',base_url='https://api.minimaxi.com/v1',api_key='offline-test-key')
CN='https://api.minimax.cn/v1'


def test_endpoint_default_and_restricted_override():
    assert t.selected_endpoint('writer',CFG)==CFG.base_url
    assert t.selected_endpoint('writer',CFG,CN)==CN
    for url in ['https://example.com/v1','https://api.minimax.cn.evil.test/v1','http://api.minimax.cn/v1']:
        with pytest.raises(ValueError):t.selected_endpoint('writer',CFG,url)
    with pytest.raises(ValueError):t.selected_endpoint('director',CFG,CN)


def test_prepared_new_round_changes_only_endpoint_not_source_or_prompts(tmp_path):
    prior=Path('data/corpus_production_trials/20261031_integrated_effort_comparison')
    before=(prior/'STATE.json').read_bytes();run=tmp_path/'cn'
    runner.prepare(run,prior,CN,'用这个再试一轮')
    plan=runner.read(run/'PLAN.json')
    assert plan['max_calls']==345 and plan['baseline_calls']==337
    assert plan['routes']['writer']['base_url']==plan['endpoint_override']==CN
    assert runner.read(run/'INPUT.json')==runner.read(prior/'INPUT.json')
    for f in ['WRITER_PROMPT.txt','REVIEW_PROMPT.txt']:
        assert (run/f).read_bytes()==(prior/f).read_bytes()
    assert (prior/'STATE.json').read_bytes()==before
    assert CFG.base_url=='https://api.minimaxi.com/v1'


def test_parent_and_worker_send_cn_using_mock_http_preserve_reasoning(tmp_path,monkeypatch):
    real_openai=openai.OpenAI;captured=[]
    chunks=[{'id':'offline-fixture','object':'chat.completion.chunk','created':1,'model':'MiniMax-M3.1-Flash',
             'choices':[{'index':0,'delta':{'reasoning_content':'fixture reasoning'},'finish_reason':None}]},
            {'id':'offline-fixture','object':'chat.completion.chunk','created':1,'model':'MiniMax-M3.1-Flash',
             'choices':[{'index':0,'delta':{'content':'fixture answer'},'finish_reason':'stop'}],
             'usage':{'prompt_tokens':1,'completion_tokens':2,'total_tokens':3,'completion_tokens_details':{'reasoning_tokens':1}}}]
    def handle(req):
        captured.append((str(req.url),json.loads(req.content)))
        data=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n'
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=data)
    def client(**kw):
        return real_openai(**kw,http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(openai,'OpenAI',client)
    monkeypatch.setattr(t,'role_config',lambda role:CFG)
    monkeypatch.setattr(w,'role_config',lambda role:CFG)
    class Child:
        def __init__(self,command):self.command=command;self.returncode=None
        def wait(self,timeout):w.run(Path(self.command[-1]));self.returncode=0
    monkeypatch.setattr(t.subprocess,'Popen',Child)
    (tmp_path/'STATE.json').write_text(json.dumps({'calls_started':1}),encoding='utf-8')
    plan={'endpoint_override':CN,'routes':{'writer':{'model':'MiniMax-M3.1-Flash','base_url':CN}},
          'inference':{'writer_effort':'xhigh','writer_max_tokens':32768,'wall_seconds':900}}
    result=t.NativeClient(tmp_path,plan).call('writer',[{'role':'user','content':'offline fixture'}],{'type':'object'})
    assert captured[0][0]==CN+'/chat/completions'
    assert captured[0][1]['reasoning_effort']=='xhigh'
    assert captured[0][1]['thinking']=={'type':'adaptive'}
    assert result['choices'][0]['message']['reasoning_content']=='fixture reasoning'
    assert 'offline-test-key' not in (tmp_path/'native_001/REQUEST.json').read_text('utf-8')
    spec=runner.read(tmp_path/'native_001/REQUEST.json');spec['base_url']='https://example.com'
    (tmp_path/'native_001/REQUEST.json').write_text(json.dumps(spec),encoding='utf-8')
    with pytest.raises(ValueError,match='route_changed'):w.run(tmp_path/'native_001')
    assert len(captured)==1
