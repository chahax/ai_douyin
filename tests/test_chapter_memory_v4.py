from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.platform_adapter.fanqie_book_corpus import atomic
from src.content_factory.novel_adaptation import chapter_memory_v4 as m
from scripts import run_chapter_memory_v4 as runner

CORPUS={'chapters':[{'index':1,'text':'甲向乙说：“明天去学校。”\n\n乙点头。'},
    {'index':2,'text':'他答应了。\n\n甲仍在家里。'},
    {'index':3,'text':'第二天，甲出门。'},
    {'index':4,'text':'后来甲成为老师。'}]}


def delta(chapter):
    ref=f'CH{chapter}-P001'
    return dict(facts=[dict(kind='event_state',statement='当前章事实',temporal='current',certainty='explicit',source_ids=[ref])],
        opening_bridge=dict(statement='承接前章说话或起始场面',source_ids=[ref],referents=[]),
        closing_state=dict(statement='仍在当前地点',source_ids=[ref]))


def memory_until(chapter):
    result=[]
    for i in range(1,chapter+1):result=m.append(result,CORPUS,i,delta(i),dict(passed=True,issues=[]))
    return result


def test_source_prefix_keeps_complete_chapters_and_excludes_future():
    p=m.packet(CORPUS,2)
    assert [ch['chapter'] for ch in p['chapters']]==[1,2]
    assert [ch['role'] for ch in p['chapters']]==['context_only','target']
    assert '\n\n'.join(x['text'] for x in p['chapters'][0]['paragraphs'])==CORPUS['chapters'][0]['text']
    with pytest.raises(ValueError):m.packet({'chapters':CORPUS['chapters'][1:]},3)


def test_append_keeps_history_exact_and_binds_parent_and_source():
    first=memory_until(1);original=deepcopy(first)
    second=m.append(first,CORPUS,2,delta(2),dict(passed=True,issues=[]))
    assert first==original and second[:1]==first
    assert second[1]['previous_memory_digest']==digest(first)
    bad=deepcopy(second);bad[0]['analysis']['facts'][0]['statement']='被后章重写'
    with pytest.raises(ValueError,match='analysis_changed'):m.validate_memory(bad,CORPUS,3)
    changed=deepcopy(CORPUS);changed['chapters'][0]['text']='原文发生变化'
    with pytest.raises(ValueError,match='source_changed'):m.validate_memory(second,changed,3)


def test_future_reference_and_unapproved_analysis_cannot_become_memory():
    d=delta(1);d['facts'][0]['source_ids']=['CH4-P001']
    with pytest.raises(m.c.ContractError):m.append([],CORPUS,1,d,dict(passed=True,issues=[]))
    with pytest.raises(ValueError,match='not_approved'):m.append([],CORPUS,1,delta(1),dict(passed=False,issues=[]))
    with pytest.raises(ValueError,match='not_contiguous'):m.append([],CORPUS,2,delta(2),dict(passed=True,issues=[]))


def test_author_receives_growing_analysis_and_original_tail_not_screenplay():
    for chapter in range(1,4):
        packet=m.author_context(memory_until(chapter),CORPUS,chapter)
        assert len(packet['prior_analyses'])==chapter-1
        assert packet['current_analysis']==delta(chapter)
        assert bool(packet['previous_chapter_tail'])==(chapter>1)
        assert 'screenplay' not in str(packet)
    assert m.author_context(memory_until(2),CORPUS,2)['previous_chapter_tail'][-1]['text']=='乙点头。'


def test_three_chapter_agent_wiring_uses_cumulative_memory_only_in_writer(tmp_path,monkeypatch):
    p=tmp_path/'prior';p.mkdir()
    real=Path('data/corpus_production_trials/20261101_autonomous_v3_full_production_quotes')
    for name,value in [('PLAN',read(real/'PLAN.json')),('SOURCE',CORPUS),('STATE',dict(trial_ended=True,pending=None,calls_started=395,reported_tokens=10))]:freeze(p/(name+'.json'),value)
    run=tmp_path/'trial';runner.prepare(run,p,3);captured=[]
    class Fake:
        def __init__(self,run,plan,state):self.run,self.plan,self.state=run,plan,state
        def save(self):atomic(self.run/'STATE.json',self.state)
        def call(self,node,role,prompt,payload,schema):
            captured.append((node,deepcopy(payload)))
            chapter=max(x['chapter'] for x in payload['source']['chapters'])
            if node=='analyze':value=delta(chapter)
            elif node=='analysis_review':value=dict(passed=True,issues=[])
            elif node=='generate':value=dict(text=f'第{chapter}章原生稿，不能作为后章原文。')
            elif node.endswith('_review'):value=dict(issues=[],summary='通过')
            else:raise AssertionError(node)
            self.state['calls_started']+=1;self.state['reported_tokens']+=1
            self.state['nodes'][node]=dict(status='complete',call=self.state['calls_started'])
            freeze(self.run/(node+'.json'),value);self.save();return value
    monkeypatch.setattr(runner.transport,'Transport',Fake)
    runner.execute(run)
    state=read(run/'STATE.json')
    assert state['status']=='trial_complete' and len(state['chapters'])==3 and state['calls_started']==407
    authors=[p for n,p in captured if n=='generate'];analyses=[p for n,p in captured if n=='analyze']
    assert [len(p['chapter_memory']['prior_analyses']) for p in authors]==[0,1,2]
    assert [len(p['previous_memory']) for p in analyses]==[0,1,2]
    assert all('chapter_memory' not in p for n,p in captured if n.endswith('_review') and n!='analysis_review')
    assert all('原生稿' not in str(p) for p in analyses)
    assert [len(p['source']['chapters']) for p in authors]==[1,2,3]
    assert all(read(run/f'chapter_{i:03}_script/PLAN.json')['max_calls']==455 for i in range(1,4))
    assert not state['semantic_accepted']


def test_unknown_analysis_stops_without_replaying_or_entering_script(tmp_path,monkeypatch):
    p=tmp_path/'prior';p.mkdir();real=Path('data/corpus_production_trials/20261101_autonomous_v3_full_production_quotes')
    for name,value in [('PLAN',read(real/'PLAN.json')),('SOURCE',CORPUS),('STATE',dict(trial_ended=True,pending=None,calls_started=395,reported_tokens=10))]:freeze(p/(name+'.json'),value)
    run=tmp_path/'trial';runner.prepare(run,p,3)
    class Unknown:
        def __init__(self,run,plan,state):self.run,self.state=run,state
        def save(self):atomic(self.run/'STATE.json',self.state)
        def call(self,*args):
            self.state.update(calls_started=396,pending=396,status='outcome_unknown');self.save();raise RuntimeError('stream_unknown')
    monkeypatch.setattr(runner.transport,'Transport',Unknown)
    runner.execute(run)
    assert read(run/'STATE.json')['pending']==396
    assert not (run/'chapter_001_script').exists() and not (run/'chapter_002_analysis').exists()
    with pytest.raises(ValueError,match='not_fresh'):runner.execute(run)


def test_known_plan_classification_is_reused_unchanged_without_budget_reset(tmp_path):
    import json
    prior=Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three/chapter_001_analysis')
    run=tmp_path/'continued';runner.prepare(run,prior,3,reuse_analysis=True)
    imported=read(run/'IMPORTED_ANALYSIS.json')
    raw=json.loads(read(prior/'RESPONSE_396.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    assert imported['value']==raw and not imported['semantic_approved']
    assert read(run/'PLAN.json')['max_calls']==455
    assert read(run/'STATE.json')['calls_started']==396


def test_resolution_does_not_drop_real_error_or_additional_findings():
    source=m.packet(CORPUS,1)
    audit=dict(passed=False,issues=[dict(path='facts[0]',reason='计划误当已发生',source_ids=['CH1-P001'])])
    resolution=dict(decisions={'i0':dict(blocks_memory=True,reason='明天是计划',source_ids=['CH1-P001'])},additional_issues=[])
    assert not m.resolved_audit(source,audit,resolution)['passed']
    resolution['decisions']['i0']['blocks_memory']=False
    assert m.resolved_audit(source,audit,resolution)['passed']
    resolution['additional_issues']=audit['issues']
    assert not m.resolved_audit(source,audit,resolution)['passed']
    resolution['decisions']={}
    with pytest.raises(m.c.ContractError):m.resolved_audit(source,audit,resolution)


def test_rejected_analysis_reuse_keeps_original_and_call_window(tmp_path):
    prior=Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three_continued/chapter_001_analysis')
    run=tmp_path/'resume';runner.prepare(run,prior,3,reuse_reviewed_analysis=True)
    imported=read(run/'IMPORTED_ANALYSIS.json')
    assert imported['value']==read(prior/'analysis_repair.json')
    assert imported['review']==read(prior/'analysis_recheck.json')
    assert read(run/'PLAN.json')['max_calls']==455
    assert read(run/'STATE.json')['calls_started']==399


def test_second_chapter_known_json_failure_resumes_without_repeating_first(tmp_path):
    prior=Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three_gate')
    run=tmp_path/'resume';runner.prepare(run,prior,3,resume_failed_analysis=True)
    p=read(run/'PLAN.json');s=read(run/'STATE.json')
    assert p['start_chapter']==2 and p['max_calls']==455 and s['calls_started']==412
    assert read(run/'MEMORY_001.json')==read(prior/'MEMORY_001.json')
    assert s['chapters']==read(prior/'STATE.json')['chapters']


def test_invalid_json_retry_is_one_new_node_and_keeps_failure(tmp_path,monkeypatch):
    import json
    class Bad:
        def __init__(self,run,plan,state):self.run,self.state=run,state
        def save(self):atomic(self.run/'STATE.json',self.state)
        def call(self,node,*args):
            self.state['nodes'][node]={'status':'known_invalid_output'}
            self.state['calls_started']+=1;self.state.update(status='known_invalid_output',trial_ended=True,pending=None)
            self.save();raise json.JSONDecodeError('incomplete','{"opening_bridge":',18)
    monkeypatch.setattr(runner.transport,'Transport',Bad)
    r=tmp_path/'analysis'
    with pytest.raises(json.JSONDecodeError):runner.analyze(r,{},dict(calls_started=0,reported_tokens=0),CORPUS,[],1)
    s=read(r/'STATE.json')
    assert s['calls_started']==2 and set(s['nodes'])=={'analyze','analyze_format_retry'}
    assert (r/'FORMAT_RETRY_RECEIPT.json').exists()


def test_review_envelope_resume_preserves_open_issues_and_remaining_script_round(tmp_path):
    from scripts import run_autonomous_revision_v3 as v3
    prior=Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three_json/chapter_002_script')
    child=tmp_path/'child';v3.prepare(child,prior,resume_review='cycle_1_review')
    assert read(child/'PLAN.json')['max_repair_rounds']==1
    assert read(child/'PLAN.json')['max_calls']==455
    assert len(read(child/'OPEN_ISSUES.json'))==4
    assert read(child/'OPEN_LINKS.json')['I5']
    report=read(child/'IMPORTED_REVIEW.json')
    assert 'type' not in report['report'] and report['normalization']['method']=='remove_only_json_mode_marker'
    root=tmp_path/'root';runner.prepare(root,prior.parent,3,resume_script_review='cycle_1_review')
    assert read(root/'PLAN.json')['initial_memory_chapter']==2
    assert read(root/'STATE.json')['calls_started']==420
    assert len(read(root/'STATE.json')['chapters'])==1


def test_json_mode_metadata_normalization_cannot_hide_task_schema_errors():
    from src.content_factory.novel_adaptation.agent_transport_v2 import normalize_response_envelope
    schema=m.c.obj(text=m.c.TEXT)
    original={'type':'json_object','text':'原样正文'}
    fixed,receipt=normalize_response_envelope(original,schema)
    assert fixed=={'text':'原样正文'} and original['type']=='json_object' and receipt
    for invalid in [{'type':'json_object','text':3},{'type':'other','text':'正文'},{'type':'json_object','text':'正文','extra':1}]:
        assert normalize_response_envelope(invalid,schema)==(invalid,None)


def test_failed_script_is_not_canon_when_evaluation_advances_source_memory(tmp_path):
    prior=Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three_envelope')
    run=tmp_path/'next';runner.prepare(run,prior,3,advance_known_failed_script=True)
    assert read(run/'PLAN.json')['start_chapter']==3 and read(run/'PLAN.json')['max_calls']==455
    assert read(run/'MEMORY_002.json')==read(prior/'MEMORY_002.json')
    assert read(run/'STATE.json')['chapters'][-1]['script_status']=='known_invalid_output'


def test_scopes_inside_source_ids_are_only_relocated_not_rewritten():
    import json
    from src.content_factory.novel_adaptation import autonomous_revision_v3 as n
    p=Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three_envelope/chapter_002_script')
    raw=json.loads(read(p/'RESPONSE_421.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    report=json.loads(read(p/'CALL_421.json')['messages'][1]['content'])['review']
    fixed,receipt=n.repair_unique_misplaced_scopes(report,raw)
    assert fixed['decisions']['I4']['source_ids']==raw['decisions']['I4']['source_ids'][:2]
    assert fixed['decisions']['I4']['scopes']==raw['decisions']['I4']['source_ids'][2]['item']
    assert receipt['values_unchanged']
