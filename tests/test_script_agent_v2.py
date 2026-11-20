import json
from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.novel_adaptation import agent_revision_v2 as n,agent_capacity_v2 as cap,agent_transport_v2 as t,prose_patch,contracts as c
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from scripts import run_script_agent_v2 as runner

SOURCE={'chapters':[{'chapter':1,'role':'target','paragraphs':[{'id':'P1','text':'孩子自己盛饭。'}]}]}
TEXT='背景：父亲盛饭。正文：父亲盛饭。结尾。'


def issue(severity='blocking'):
    return dict(id='I1',subject='盛饭',kind='continuity',severity=severity,claim='主体有误',source_ids=['P1'],reason='原文孩子自己盛饭',
        scopes=[dict(quote='背景：父亲盛饭。',boundary='恢复孩子自己盛饭'),dict(quote='正文：父亲盛饭。',boundary='恢复孩子自己盛饭')])


def verdict(decision='supported',severity='blocking'):
    return dict(decisions=[dict(id='I1',decision=decision,severity=severity,reason='已对照原文')],summary='核验完成')


def test_multi_range_atomic_and_unchanged_tail():
    a=n.adjudicate(SOURCE,TEXT,dict(issues=[issue()],summary='需修'),verdict())
    p=n.multi_span_plan(TEXT,a)
    assert [x['issue_id'] for x in p['slots']]==['I1','I1']
    assert prose_patch.apply(TEXT,p,dict(edit_0='背景：孩子自己盛饭。',edit_1='正文：孩子自己盛饭。')).endswith('结尾。')
    with pytest.raises(c.ContractError):prose_patch.apply(TEXT,p,dict(edit_0='只改一处'))
    with pytest.raises(ValueError,match='stale'):n.multi_span_plan(TEXT+'变更',a)


@pytest.mark.parametrize('severity',['production','style'])
def test_nonblocking_does_not_trigger_rewrite(severity):
    a=n.adjudicate(SOURCE,TEXT,dict(issues=[issue(severity)],summary='制作建议'),verdict(severity=severity))
    assert not a['accepted'] and not a['unresolved_blocking']


def test_rejected_and_unresolved_evidence():
    report=dict(issues=[issue()],summary='需核验')
    assert not n.adjudicate(SOURCE,TEXT,report,verdict('rejected'))['accepted']
    assert n.adjudicate(SOURCE,TEXT,report,verdict('unresolved'))['unresolved_blocking']
    bad=deepcopy(report);bad['issues'][0]['source_ids']=['missing']
    assert n.validate_report(SOURCE,TEXT,bad)['address_diagnostics']['I1']==['invalid_source_ref']
    with pytest.raises(ValueError,match='not_patchable'):n.adjudicate(SOURCE,TEXT,bad,verdict())
    with pytest.raises(ValueError,match='coverage'):n.adjudicate(SOURCE,TEXT,report,dict(decisions=[],summary='遗漏'))


def test_inexact_production_quote_records_diagnostic_but_never_applies_patch():
    x=issue('production');x['scopes'][0]['quote']='不存在的标点差异句。'
    report=dict(issues=[x],summary='道具建议')
    a=n.adjudicate(SOURCE,TEXT,report,verdict(severity='production'))
    assert a['binding']['address_diagnostics']['I1']==['nonunique_issue_range']
    assert not a['accepted']
    with pytest.raises(ValueError,match='no_blocking_patch'):n.multi_span_plan(TEXT,a)
    with pytest.raises(ValueError,match='not_patchable'):n.adjudicate(SOURCE,TEXT,report,verdict(severity='blocking'))


def test_overlap_rejected_and_record_binding():
    x=issue();x['scopes'].append(dict(quote='父亲盛饭。正文',boundary='重叠'))
    a=n.adjudicate(SOURCE,TEXT,dict(issues=[x],summary='需修'),verdict())
    with pytest.raises(ValueError,match='overlap'):n.multi_span_plan(TEXT,a)
    registry=[];n.record_issues(registry,a,0)
    check=dict(results=[dict(id='I1',result='unresolved',reason='只换措辞')],regressions=[],summary='仍错')
    assert not n.apply_check(registry,a,check,'new_digest')
    assert registry[0]['status']=='unresolved'


def test_node_context_is_explicit_and_independent_review_has_no_history():
    with pytest.raises(ValueError,match='not_allowed'):n.context('review',SOURCE,[],TEXT,relevant_history=['old'])
    registry=[dict(subject='盛饭',source_ids=['P1'],status='rejected'),dict(subject='汽车',source_ids=['P9'],status='resolved')]
    history=n.relevant_history(registry,[issue()]);assert len(history)==1
    payload=n.context('repair',SOURCE,[],TEXT,relevant_history=history,slots=[],confirmed_issues=[issue()])
    assert payload['relevant_history'][0]['status']=='rejected'
    assert set(n.context('review',SOURCE,[],TEXT))=={'source','production_choices','candidate'}


def test_capability_units_limits_and_provider_metadata():
    profile=cap.profiles()['director']
    r=cap.capacity_report([dict(role='user',content='中文输入'*100)],{},profile,65536)
    assert not r['exact'] and r['estimated_input_tokens']!=r['serialized_bytes']
    assert r['decision']=='fits_estimate'
    with pytest.raises(ValueError):cap.validate_profile(profile,'deepseek-flash','high',393217)
    with pytest.raises(ValueError):cap.validate_profile(profile,'other','high',65536)
    with pytest.raises(ValueError):cap.official_metadata(profile,dict(data=[]))
    merged=cap.official_metadata(profile,dict(data=[dict(id='deepseek-flash',context_window=999999,max_output_tokens=88888)]))
    assert merged['max_output_tokens']==88888 and merged['context_window']==999999
    assert cap.deadline_seconds(131072)>cap.deadline_seconds(65536)


def base_plan():
    p=cap.profiles()
    return dict(routes={k:{z:v[z] for z in ['provider','model','base_url']} for k,v in p.items()},
        capabilities=p,budgets=dict(writer=[131072,262144],director=[65536,131072]),
        inference=dict(writer_effort='xhigh',director_effort='high',director_thinking='enabled'),
        endpoint_overrides={'writer':'https://api.minimax.cn/v1'},max_calls=10)


def fake_native(run,role,model,value,finish='stop'):
    num=read(run/'STATE.json')['calls_started'];folder=run/f'native_{num:03}';folder.mkdir()
    text=json.dumps(value,ensure_ascii=False)
    usage=dict(prompt_tokens=10,completion_tokens=20,total_tokens=30)
    native=dict(id=str(num),model=model,usage=usage,choices=[dict(index=0,finish_reason=finish,message=dict(content=text,tool_calls=[]))])
    freeze(folder/'RESPONSE.json',native)
    (folder/'CHUNKS.jsonl').write_text(json.dumps(dict(id=str(num),model=model,usage=usage,choices=[dict(index=0,finish_reason=finish,delta=dict(content=text))])),encoding='utf-8')
    return native


def test_length_expands_only_same_node_preserves_payload(tmp_path):
    state=dict(pending=None,calls_started=0,reported_tokens=0,trial_ended=False);seen=[]
    class Fake:
        def __init__(self,run,plan):self.run,self.plan=run,plan
        def call(self,role,messages,schema):
            seen.append((self.plan['inference']['director_max_tokens'],messages))
            return fake_native(self.run,role,'deepseek-flash',dict(text='ok'),'length' if len(seen)==1 else 'stop')
    tr=t.Transport(tmp_path,base_plan(),state,Fake)
    assert tr.call('audit','director','audit',{'candidate':'fixed'},c.obj(text=c.TEXT))=={'text':'ok'}
    assert [x[0] for x in seen]==[65536,131072] and seen[0][1]==seen[1][1]
    assert state['reported_tokens']==60 and state['pending'] is None
    assert read(tmp_path/'CALL_002.json')['recovery_of']==1
    with pytest.raises(ValueError,match='completed'):tr.call('audit','director','audit',{},c.obj(text=c.TEXT))


def test_unknown_does_not_retry(tmp_path):
    state=dict(pending=None,calls_started=0,reported_tokens=0,trial_ended=False)
    class Bad:
        def __init__(self,*args):pass
        def call(self,*args):raise RuntimeError('lost receipt')
    tr=t.Transport(tmp_path,base_plan(),state,Bad)
    with pytest.raises(RuntimeError):tr.call('audit','director','x',{},c.obj(text=c.TEXT))
    assert state['calls_started']==1 and state['pending']==1
    with pytest.raises(RuntimeError,match='unknown'):tr.call('other','director','x',{},c.obj(text=c.TEXT))


def test_exhausted_known_length_cannot_reset_retry_budget(tmp_path):
    state=dict(pending=None,calls_started=0,reported_tokens=0,trial_ended=False)
    class Length:
        def __init__(self,run,plan):self.run=run
        def call(self,role,messages,schema):return fake_native(self.run,role,'deepseek-flash',{},'length')
    tr=t.Transport(tmp_path,base_plan(),state,Length)
    with pytest.raises(RuntimeError,match='recovery_exhausted'):tr.call('audit','director','x',{},c.obj(text=c.TEXT))
    assert state['pending'] is None and state['calls_started']==2 and state['trial_ended']
    with pytest.raises(ValueError,match='already_dispatched'):tr.call('audit','director','x',{},c.obj(text=c.TEXT))


def test_known_invalid_schema_is_not_retried_as_length(tmp_path):
    state=dict(pending=None,calls_started=0,reported_tokens=0,trial_ended=False)
    class Invalid:
        def __init__(self,run,plan):self.run=run
        def call(self,role,messages,schema):return fake_native(self.run,role,'deepseek-flash',{'other':'wrong'})
    tr=t.Transport(tmp_path,base_plan(),state,Invalid)
    with pytest.raises(c.ContractError):tr.call('audit','director','x',{},c.obj(text=c.TEXT))
    assert state['pending'] is None and state['calls_started']==1 and state['status']=='known_invalid_output'


@pytest.mark.parametrize('retry',[False,True,'production'])
def test_full_orchestration_with_multi_patch_and_independent_final(tmp_path,monkeypatch,retry):
    prior=tmp_path/'prior';prior.mkdir()
    source=dict(chapters=[dict(index=1,text='孩子自己盛饭。')])
    for name,value in [('SOURCE',source),('INPUT',SOURCE),('PRODUCTION_CHOICES',[]),
       ('STATE',dict(pending=None,trial_ended=True,calls_started=0,reported_tokens=0)),('CANDIDATE_BINDING',dict(candidate_digest=digest(TEXT)))]:freeze(prior/(name+'.json'),value)
    (prior/'SCREENPLAY.md').write_text(TEXT,encoding='utf-8')
    run=tmp_path/'run';runner.prepare(run,prior,'recover-review')
    seen=[]
    class FakeTransport:
        def __init__(self,run,plan,state):self.run,self.plan,self.state=run,plan,state
        def save(self):t.atomic(self.run/'STATE.json',self.state)
        def call(self,node,role,prompt,payload,schema):
            seen.append((node,payload));self.state['calls_started']+=1
            if node=='round_0_review':return dict(issues=[issue()],summary='需修')
            if node=='round_1_verify' and retry=='production':
                v=verdict(severity='production');v['decisions'][0]['id']='I2';return v
            if node.endswith('_verify'):return verdict()
            if node=='round_0_patch' and retry is True:return dict(edit_0='背景：父亲盛饭。',edit_1='正文：父亲盛饭。')
            if node.endswith('_patch'):return dict(edit_0='背景：孩子自己盛饭。',edit_1='正文：孩子自己盛饭。')
            if node=='round_0_check' and retry is True:return dict(results=[dict(id='I1',result='unresolved',reason='两处未改')],regressions=[issue()],summary='继续处理原问题')
            if node=='round_0_check' and retry=='production':
                x=issue('production');x.update(id='I2',subject='结尾布景',scopes=[dict(quote='结尾。',boundary='制作前明确')])
                return dict(results=[dict(id='I1',result='resolved',reason='两处恢复')],regressions=[x],summary='新制作观察不可丢弃')
            if node.endswith('_check'):return dict(results=[dict(id='I1',result='resolved',reason='两处均恢复')],regressions=[],summary='完成')
            if node in ['round_1_review','round_2_review']:return dict(issues=[],summary='未发现阻断项')
            raise AssertionError(node)
    monkeypatch.setattr(runner.transport,'Transport',FakeTransport)
    runner.execute(run)
    state=read(run/'STATE.json')
    assert state['status']=='ready_for_primary_review' and not state['video_released']
    assert read(run/'ISSUE_REGISTRY.json')[-1]['status']==('open' if retry=='production' else 'resolved')
    if retry is True:
        assert read(run/'ISSUE_REGISTRY.json')[0]['status']=='unresolved'
        assert (run/'round_1_CARRIED_REVIEW.json').exists()
    if retry=='production':
        assert state['production_todos'][0]['id']=='I2'
        assert sum(node.endswith('_patch') for node,_ in seen)==1
    assert set(seen[-1][1])=={'source','production_choices','candidate'}
    assert '父亲盛饭' not in (run/'SCREENPLAY.md').read_text(encoding='utf-8')
    assert (prior/'SCREENPLAY.md').read_text(encoding='utf-8')==TEXT


def test_full_scope_uses_complete_numbered_chapters(tmp_path):
    prior=tmp_path/'p';prior.mkdir()
    freeze(prior/'STATE.json',dict(pending=None,trial_ended=True,calls_started=0,reported_tokens=0))
    freeze(prior/'SOURCE.json',dict(chapters=[dict(index=i,text=f'第{i}章完整。\n\n第二段。') for i in [1,2,3]]))
    runner.prepare(tmp_path/'r',prior,'full',[1],[2,3])
    packet=read(tmp_path/'r/INPUT.json')
    assert [(x['chapter'],x['role'],len(x['paragraphs'])) for x in packet['chapters']]==[(1,'context_only',2),(2,'target',2),(3,'target',2)]
    assert read(tmp_path/'r/PRODUCTION_CHOICES.json')==[]


def test_known_review_adoption_no_deepseek_replay_and_tamper_rejected(tmp_path,monkeypatch):
    prior=Path('data/corpus_production_trials/20261101_script_agent_v2_observations')
    text=(prior/'SCREENPLAY.md').read_text(encoding='utf-8')
    handoff=dict(candidate_digest=digest(text),known_review_node='round_2_review',report=read(prior/'round_2_review.json'))
    p=tmp_path/'handoff.json';freeze(p,handoff)
    r=tmp_path/'run';runner.prepare(r,prior,'recover-review',observations=p)
    assert read(r/'PLAN.json')['imported_independent_review']
    seen=[]
    class Fake:
        def __init__(self,run,plan,state):self.run,self.state=run,state
        def save(self):t.atomic(self.run/'STATE.json',self.state)
        def call(self,node,role,prompt,payload,schema):
            seen.append(role);self.state['calls_started']+=1
            return dict(decisions=[dict(id=x['id'],decision='rejected',severity='style',reason='offline mock only') for x in handoff['report']['issues']],summary='offline')
    monkeypatch.setattr(runner.transport,'Transport',Fake);runner.execute(r)
    assert seen==['writer']
    assert read(r/'STATE.json')['final_review_binding']['independent']
    handoff['report']['summary']='changed report';p.write_text(json.dumps(handoff),encoding='utf-8')
    with pytest.raises(ValueError,match='imported_review_changed'):runner.prepare(tmp_path/'bad',prior,'recover-review',observations=p)


def test_continuation_keeps_previous_observations_but_excludes_other_target():
    prior=Path('data/corpus_production_trials/20261101_script_agent_v2_known_review')
    packet=read(prior/'INPUT.json');history=runner.history_for_scope(prior,packet)
    # I6 was absent from the last independent audit, but its dining-room staging
    # observation remains in the earlier same-target ledger and must survive.
    assert any(x['subject']=='第六场孩子调度' and x['status']=='open' for x in history)
    assert any(x['id']=='R2' and x['status']=='resolved' for x in history)
    other=deepcopy(packet)
    for chapter in other['chapters']:
        if chapter['role']=='target':chapter['chapter']+=10
    assert runner.history_for_scope(prior,other)==[]
