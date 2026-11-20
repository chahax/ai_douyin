from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import containers as co,contracts as c
from src.content_factory.novel_adaptation.scenes import initial_state,advance,production_scene
from src.content_factory.novel_adaptation.events import validate_requirements
from src.content_factory.novel_adaptation.handoff import export_handoff,continue_state
from src.content_factory.novel_adaptation.blocking import blocking_schema
from test_novel_adaptation_scenes import SOURCE,ENT,PLAN,SCENE


def fixture():
    plan=deepcopy(PLAN)
    plan['props'] += [{'id':'bag','owner':'a'},{'id':'box','owner':'a'}]
    plan['containers']={'bread1':'bag','bag':'box'}
    scene=deepcopy(SCENE);scene['beats'][0]['transfers'][0]['prop']='box'
    return plan,scene


def test_nested_contents_follow_one_transfer_and_required_events():
    plan,scene=fixture();previous=initial_state(plan,ENT)
    end=advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,previous)
    assert set(end['props'].values())=={'b'} and set(previous['props'].values())=={'a'}
    event={'id':'e','scene_id':'s1','kind':'transfer','prop':'bread1','origin':'a','destination':'b'}
    assert validate_requirements({'scenes':[scene],'design':plan},{'events':[event]})
    view=production_scene(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,previous)
    assert view['end_state']==end and len(view['beats'][0]['transfers'])==1
    scene['beats'][0]['transfers']=[]
    with pytest.raises(c.ContractError):validate_requirements({'scenes':[scene],'design':plan},{'events':[event]})


def test_separate_child_transfer_is_not_silent_removal():
    plan,scene=fixture();scene['beats'][0]['transfers'][0]['prop']='bread1'
    with pytest.raises(c.ContractError,match='contained_prop_requires_removal_action'):
        advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,initial_state(plan,ENT))


def test_model_transfer_schema_only_allows_root_container():
    plan,scene=fixture()
    schema=blocking_schema(plan,ENT,['f'],SOURCE,initial_state(plan,ENT),['CH1-P001'])
    variants=schema['properties']['beats']['items']['properties']['blocking']['items']['oneOf']
    transfer=next(v for v in variants if v['properties']['kind']['enum']==['transfer'])
    assert transfer['properties']['prop']['enum']==['box']


@pytest.mark.parametrize('parents,owners',[
    ({'a':'a'},{'a':'x'}),({'a':'b','b':'a'},{'a':'x','b':'x'}),
    ({'a':'b'},{'a':'x','b':'y'}),({'a':'missing'},{'a':'x'})])
def test_bad_containment_rejected(parents,owners):
    with pytest.raises(ValueError):co.validate(parents,owners)


def test_cross_episode_cannot_erase_containment():
    plan,scene=fixture();end=advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,initial_state(plan,ENT))
    candidate={'design':plan,'end_state':end}
    review={'verdict':'accepted','candidate_sha256':c.digest(candidate),'source_sha256':c.digest(SOURCE)}
    h=export_handoff(candidate,ENT,SOURCE,review,book_id='b',episode_id='E1',timeline_id='now')
    for p in plan['props']:p['owner']='b'
    kwargs=dict(book_id='b',episode_id='E2',timeline_id='now')
    assert continue_state(h,c.digest(h),plan,ENT,**kwargs)['containers']==end['containers']
    del plan['containers']
    with pytest.raises(ValueError,match='opening_container_reset'):continue_state(h,c.digest(h),plan,ENT,**kwargs)


def test_relation_refinement_requires_bound_review_preserves_old_state():
    h={'state':{'props':{'food':'a','bag':'a'}}};old=deepcopy(h)
    proposals=[{'child':'food','container':'bag','source_ids':['CH1-P001']}]
    review={'verdict':'accepted','handoff_sha256':c.digest(h),'source_sha256':c.digest(SOURCE),'proposals_sha256':c.digest(proposals)}
    result=co.refine_containment(h,proposals,SOURCE,review)
    assert h==old and result['state']['props']==h['state']['props']
    proposals[0]['container']='food'
    with pytest.raises(ValueError,match='unreviewed'):co.refine_containment(h,proposals,SOURCE,review)
