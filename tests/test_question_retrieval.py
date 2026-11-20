import pytest
from src.content_factory.novel_adaptation.question_retrieval import BookIndex,validate_selection,validate_links
from src.content_factory.novel_adaptation import contracts as c

def source():return {'chapters':[
 {'index':1,'text':'叶东安慰弟弟。\n他也才11岁。\n如果迟到就挨打。'},
 {'index':2,'text':'叶东准备出门。\n六个孩子坐车。'},
 {'index':9,'text':'叶东长大后担任队长。'}]}

def test_global_hits_keep_source_context_and_do_not_leak_future():
    ix=BookIndex(source());r=ix.search(['叶东','队长','11岁'],'CH2-P001')
    assert any(x['id']=='CH9-P001' for x in r['later_hits_for_review_only'])
    assert 'CH1-P002' in r['eligible_context_ids']
    assert 'CH1-P001' in r['eligible_context_ids']
    assert all(ix.order[k]<ix.order['CH2-P001'] for k in r['eligible_context_ids'])
    assert ix.catalog['CH1-P003']['text']=='如果迟到就挨打。'

def test_supported_requires_evidence_and_future_not_selectable():
    ix=BookIndex(source());search={'q':ix.search(['叶东'],'CH2-P001')};questions=[{'id':'q'}]
    for selection in [{'q':{'evidence_ids':['CH9-P001'],'status':'supported'}}, {'q':{'evidence_ids':[],'status':'supported'}}]:
        with pytest.raises(ValueError):validate_selection(questions,search,selection)
    assert validate_selection(questions,search,{'q':{'evidence_ids':[],'status':'unknown'}})

def test_no_hit_is_unknown_not_invented_fact():
    ix=BookIndex(source());r=ix.search(['xyzqwerty'],'CH2-P001')
    assert r['eligible_context_ids']==[] and not r['exhaustive_recall_claimed']

def test_link_must_exist_in_current_candidate():
    good={'screenplay':'叶东准备出门。','source_links':[{'source_id':'CH2-P001','screenplay_quote':'准备出门'}]}
    assert validate_links(good,['CH2-P001'])==good
    bad={**good,'screenplay':'叶东已经回家'}
    with pytest.raises(ValueError):validate_links(bad,['CH2-P001'])

def test_schema_matches_shared_candidate_pool_and_unknown_is_retained():
    searches={'q1':{'eligible_context_ids':['CH1-P001']},'q2':{'eligible_context_ids':['CH1-P002']}}
    questions=[{'id':'q1'},{'id':'q2'}]
    result={'q1':{'evidence_ids':['CH1-P002'],'status':'supported'},'q2':{'evidence_ids':['CH1-P001'],'status':'unknown'}}
    assert validate_selection(questions,searches,result)==result

def test_visible_target_evidence_allowed_but_later_chapters_still_rejected():
    searches={'q':{'eligible_context_ids':['CH1-P001']}};questions=[{'id':'q'}]
    result={'q':{'evidence_ids':['CH2-P001'],'status':'supported'}}
    assert validate_selection(questions,searches,result,['CH2-P001'])==result
    with pytest.raises(ValueError):validate_selection(questions,searches,{'q':{'evidence_ids':['CH9-P001'],'status':'supported'}},['CH2-P001'])


def test_known_failed_writer_is_preserved_not_reissued(tmp_path):
    import importlib.util,json
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('handoff_runner',Path('scripts/run_revision_handoff_trial.py'))
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    prior=Path('data/corpus_production_trials/20261029_questioned_holdout_three_v3')
    if not prior.exists():pytest.skip('native replay fixture unavailable')
    run=tmp_path/'continuation'
    runner.prepare_questioned(run,prior)
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    assert read(run/'STATE.json')['calls_started']==279
    assert read(run/'PLAN.json')['max_calls']==285
    assert read(run/'B_CANDIDATE.json')==read(prior/'WRITE_B_DIRECT_DECODED.json')
    assert not read(run/'B_METRICS.json')['source_link_format_valid']
    assert not read(run/'COMPLETED_B.json')['semantic_acceptance']
    assert read(run/'A_CANDIDATE.json')==read(prior/'A_CANDIDATE.json')
    assert read(run/'EVALUATION_FROZEN.json')==read(prior/'EVALUATION_FROZEN.json')
