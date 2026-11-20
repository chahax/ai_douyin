from copy import deepcopy
import pytest
from test_narrative_props import fixture
from src.content_factory.novel_adaptation.projection_rebind import rebind
from src.content_factory.novel_adaptation.contracts import digest


def test_narrow_prose_rebind_marks_affected_evidence_for_review():
    c,p,plan,props=fixture();new=deepcopy(c);new['scenes'][0]['segments'][0]['action']='甲从正确的盆中取出白菜。'
    before=deepcopy((c,p,plan,props))
    presence,projection,receipt=rebind(c,new,p,plan,props,['/scenes/0/segments/0/action'])
    assert presence['candidate_sha256']==projection['candidate_sha256']==digest(new)
    assert receipt['affected_segment_ids']==['B'] and receipt['prior_acceptance_inherited'] is False
    assert projection['segments']==props['segments']
    assert (c,p,plan,props)==before


def test_single_obligation_edit_invalidates_acceptance_without_changing_events():
    c,p,plan,props=fixture()
    c['scenes'][0]['segments'][0]['continuity_obligations']=['人物离开过道','其他义务']
    p['candidate_sha256']=props['candidate_sha256']=digest(c)
    new=deepcopy(c)
    new['scenes'][0]['segments'][0]['continuity_obligations'][0]='人物仍在过道拐角'
    presence,projection,receipt=rebind(c,new,p,plan,props,['/scenes/0/segments/0/continuity_obligations/0'])
    assert projection['segments']==props['segments']
    assert receipt['affected_segment_ids']==['B']
    assert receipt['semantic_acceptance'] is False
    assert presence['candidate_sha256']==digest(new)
    new['scenes'][0]['segments'][0]['continuity_obligations'][1]='额外未批准变化'
    with pytest.raises(ValueError,match='unapproved'):
        rebind(c,new,p,plan,props,['/scenes/0/segments/0/continuity_obligations/0'])


def test_visual_detail_change_requires_revalidation_even_when_events_replay():
    c,p,plan,props=fixture()
    c['scenes'][0]['segments'][0]['visual_additions']=['吃肉喝汤']
    p['candidate_sha256']=props['candidate_sha256']=digest(c)
    new=deepcopy(c);new['scenes'][0]['segments'][0]['visual_additions'][0]='吃碗里的肉'
    _,projection,receipt=rebind(c,new,p,plan,props,['/scenes/0/segments/0/visual_additions/0'])
    assert projection['segments']==props['segments']
    assert receipt['semantic_acceptance'] is False and receipt['affected_segment_ids']==['B']


def test_timing_and_audio_text_can_rebind_but_never_speaker_or_track_shape():
    c,p,plan,props=fixture()
    b=c['scenes'][0]['segments'][0];b['seconds']=8;b['audio']=[{'kind':'inner','speaker':'a','text':'旧内心'}]
    p['candidate_sha256']=props['candidate_sha256']=digest(c)
    new=deepcopy(c);nb=new['scenes'][0]['segments'][0];nb['seconds']=5;nb['audio'][0]['text']='新内心'
    paths=['/scenes/0/segments/0/seconds','/scenes/0/segments/0/audio/0/text']
    _,_,receipt=rebind(c,new,p,plan,props,paths)
    assert receipt['affected_segment_ids']==['B'] and not receipt['prior_acceptance_inherited']
    nb['audio'][0]['speaker']='other'
    with pytest.raises(ValueError):rebind(c,new,p,plan,props,paths)


@pytest.mark.parametrize('case',['audio','cast','unapproved','stale','empty'])
def test_new_candidate_cannot_silently_inherit_old_projection(case):
    c,p,plan,props=fixture();new=deepcopy(c);path='/scenes/0/segments/0/action'
    if case=='audio':new['scenes'][0]['segments'][0]['audio']=[{'speaker':'a','text':'新对白'}]
    elif case=='cast':new['scenes'][0]['segments'][0]['visible_people']=[]
    elif case=='unapproved':new['scenes'][0]['segments'][0]['camera']='新镜头'
    elif case=='stale':p['candidate_sha256']='old'
    with pytest.raises(ValueError):rebind(c,new,p,plan,props,[path])
