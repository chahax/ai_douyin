import pytest
from src.content_factory.novel_adaptation import faithful_video_contract as f
from src.content_factory.novel_adaptation import contracts as c

def test_complete_source_is_separated_without_rewriting():
    source={'chapters':[{'index':19,'text':'前情。'},{'index':20,'text':'完整目标一。\n完整目标二。'}]}
    packet=f.source_packet(source,[19],[20])
    assert packet['target_complete_chapters'][0]==source['chapters'][1]
    with pytest.raises(ValueError):f.source_packet(source,[20],[20])

def test_machine_pass_cannot_release_and_changed_candidate_invalidates():
    draft={'screenplay':'他想：会不会迟到？'}
    reviews=[f.bind_review(draft,{'decision':'pass'})]
    with pytest.raises(ValueError):f.release(draft,reviews,{})
    primary={'candidate_sha256':c.digest(draft),'decision':'accepted'}
    assert f.release(draft,reviews,primary)['accepted']
    with pytest.raises(ValueError,match='stale'):f.release({'screenplay':'他已经迟到'},reviews,primary)
    with pytest.raises(ValueError,match='unresolved'):f.release(draft,reviews,{**primary,'unresolved_plot_issues':['条件变事实']})

def test_second_round_requires_cause_and_change_not_new_chapter():
    first={'id':'round1','source_sha256':'same','pending':None,'version':'v1'}
    with pytest.raises(ValueError):f.next_iteration(first,{},'v2')
    plan=f.next_iteration(first,{'cause':'前情混入目标事件','change':'显式区分事件来源范围'},'v2')
    assert plan['same_source_sha256']=='same'
    with pytest.raises(ValueError,match='unknown'):f.next_iteration({**first,'pending':290},{'cause':'x','change':'y'},'v2')

def test_each_stage_shares_fidelity_boundary():
    for stage in f.STAGES:
        assert f.prompt(stage).startswith(f.COMMON)
    assert '不先按15秒' in f.prompt('screenplay')
def test_second_iteration_source_isolation():
    from src.content_factory.novel_adaptation import faithful_video_contract as f
    packet={'context_only':[{'index':1,'text':'前情甲\n\n前情乙'}], 'target_complete_chapters':[{'index':2,'text':'目标开篇\n\n目标末尾'}]}
    results={'understanding':'错误地把目标开篇归为前情','scene_plan':'候选计划','screenplay':'完整稿'}
    inputs=f.stage_inputs(packet,results,'scene_plan',2)
    assert 'analysis_unverified' not in inputs
    assert inputs['source_index'][1]['paragraphs']==[{'id':'CH2-P001','text':'目标开篇'},{'id':'CH2-P002','text':'目标末尾'}]
    writer=f.stage_inputs(packet,results,'screenplay',2)
    assert 'analysis_unverified' not in writer
    assert writer['target_complete_chapters']==packet['target_complete_chapters']
    assert f.stage_inputs(packet,results,'fidelity_review',2)['complete_candidate']=='完整稿'
