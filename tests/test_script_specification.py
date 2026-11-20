from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import script_specification as spec, autonomous_revision_v3 as n

SOURCE={'chapters':[{'chapter':1,'role':'target','paragraphs':[{'id':'CH1-P001','text':'他停顿后开口。'}]}]}
TEXT='他停顿了一下，然后开口。'

def inputs(kind='continuity',severity='production'):
    issue=dict(id='I1',subject='停顿措辞',kind=kind,severity=severity,claim='措辞可更简洁',
        source_ids=['CH1-P001'],reason='含义清楚，只有轻微重复',scopes=[dict(quote=TEXT,boundary='可选')])
    verdict=dict(id='I1',decision='supported',severity='style',action='keep',source_ids=['CH1-P001'],
        reason='停顿后开口的顺序不变，没有位置或主体变化，不妨碍表演。',scopes=[])
    return dict(issues=[issue],summary='微小问题'),dict(decisions=[verdict],summary='保留')

def test_minor_opt_in_does_not_weaken_legacy_default():
    report,v=inputs()
    with pytest.raises(ValueError,match='cannot_be_downgraded'):n.adjudicate(SOURCE,TEXT,report,v)
    a=n.adjudicate(SOURCE,TEXT,report,v,allow_minor=True)
    assert not a['accepted'] and a['rows'][0]['action']=='keep'

@pytest.mark.parametrize('kind,severity',[('facts','production'),('scope','style'),('continuity','blocking')])
def test_core_errors_cannot_be_relabelled_to_keep(kind,severity):
    report,v=inputs(kind,severity)
    with pytest.raises(ValueError,match='cannot_be_downgraded'):n.adjudicate(SOURCE,TEXT,report,v,allow_minor=True)

def test_frozen_spec_tamper_rejected_and_default_prompt_unchanged():
    original=n.WRITE;cfg=spec.config()
    assert spec.prompt('write',original,None)==original
    cfg['text']+='改动'
    with pytest.raises(ValueError,match='specification_changed'):spec.prompt('write',original,cfg)

def test_new_trial_freezes_spec_and_inherits_it_to_analysis(tmp_path):
    from scripts import run_chapter_memory_v4 as runner
    from src.content_factory.corpus_screenplay_v1 import read
    prior=__import__('pathlib').Path('data/corpus_production_trials/20261101_chapter_memory_v4_first_three_final')
    run=tmp_path/'spec_trial'
    runner.prepare(run,prior,specification=True,request_text='更新规范，再跑前三章')
    plan=read(run/'PLAN.json')
    assert plan['baseline_calls']==432 and plan['max_calls']==492
    assert plan['start_chapter']==1 and read(run/'MEMORY_000.json')==[]
    assert (run/'SPECIFICATION.md').read_text(encoding='utf-8')==plan['specification']['text']
    assert read(run/'AUTHORIZATION.json')['user']=='更新规范，再跑前三章'
    assert 'script_specification.py' in str(plan['implementation_pin'])

def test_kept_minor_child_closes_its_previous_open_record():
    from scripts.run_autonomous_revision_v3 import close_parents
    rows=[dict(record_id='old',status='open'),dict(record_id='new',status='kept_style',parents=['old'])]
    close_parents(rows,rows[1],'kept_style','candidate')
    assert n.completion_gate('完整剧本',rows,True)['passed']

def test_check_filters_only_known_kept_surplus_without_changing_real_results():
    a=dict(accepted=[dict(id='fix')],rows=[dict(id='fix',action='repair_source'),dict(id='minor',action='keep')])
    raw=dict(results=[dict(id='fix',result='unresolved',reason='仍有问题'),dict(id='minor',result='resolved',reason='已保留')],regressions=[],summary='真实回执')
    value,receipt=spec.normalize_check(raw,a)
    assert value['results']==raw['results'][:1] and receipt['ignored_kept_ids']==['minor']
    assert len(raw['results'])==2
    for bad in [dict(raw,results=raw['results'][1:]),dict(raw,results=raw['results']+[raw['results'][0]]),
                dict(raw,results=raw['results']+[dict(id='unknown',result='resolved')])]:
        with pytest.raises(ValueError,match='check_coverage'):spec.normalize_check(bad,a)
    bad=deepcopy(raw);bad['results'][1]['result']='unresolved'
    with pytest.raises(ValueError,match='kept_issue_reported_unresolved'):spec.normalize_check(bad,a)

def test_real_441_check_resume_preserves_usage_candidate_and_remaining_patch(tmp_path):
    from pathlib import Path
    from scripts import run_autonomous_revision_v3 as runner
    from src.content_factory.corpus_screenplay_v1 import read
    prior=Path('data/corpus_production_trials/20261101_spec_first_three/chapter_001_script')
    original_state=read(prior/'STATE.json');run=tmp_path/'continued'
    runner.prepare(run,prior,resume_check='cycle_0_check')
    plan=read(run/'PLAN.json')
    assert plan['baseline_calls']==441 and plan['max_calls']==492 and plan['max_repair_rounds']==1
    assert (run/'ORIGINAL.md').read_text(encoding='utf-8')==(prior/'SCREENPLAY.md').read_text(encoding='utf-8')
    assert read(run/'IMPORTED_CHECK.json')['receipt']['ignored_kept_ids']==['future-roles-omitted']
    assert all(x['status'] in ('resolved','kept_style','rejected') for x in read(run/'PREVIOUS_REGISTRY.json'))
    assert read(prior/'STATE.json')==original_state

def test_rejected_analysis_is_source_pointer_not_approved_facts(tmp_path):
    from pathlib import Path
    from scripts import run_chapter_memory_v4 as runner
    from src.content_factory.novel_adaptation import chapter_memory_v4 as m
    from src.content_factory.corpus_screenplay_v1 import read
    prior=Path('data/corpus_production_trials/20261101_spec_first_three_check')
    run=tmp_path/'source_only'
    runner.prepare(run,prior,source_only_after_rejection=True)
    plan=read(run/'PLAN.json');corpus=read(run/'SOURCE.json');memory=read(run/'MEMORY_001.json')
    assert plan['start_chapter']==2 and plan['max_calls']==492 and plan['baseline_calls']==452
    combined=m.append_source_only(memory,corpus,2,plan['resumed_analysis'])
    m.validate_memory(combined,corpus,3)
    assert 'analysis' not in combined[-1] and 'audit' not in combined[-1]
    assert combined[-1]['semantic_guarantee'] is False and combined[:1]==memory
    assert m.author_context(combined,corpus,2)['current_analysis'] is None
    bad=deepcopy(combined);bad[-1]['analysis']={'facts':['虚构事实']}
    with pytest.raises(ValueError,match='invalid_source_only_record'):m.validate_memory(bad,corpus,3)
