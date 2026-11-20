from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.scenes import initial_state,advance
from test_novel_adaptation_scenes import PLAN,SCENE,ENT,SOURCE


def fixture():
    plan=deepcopy(PLAN);plan['props'].append({'id':'door','owner':'other','stationary':True,'visible_from':['room','other']})
    scene=deepcopy(SCENE);b=scene['beats'][0];b['transfers']=[]
    b['gestures']=[{'actor':'a','verb':'look_at','target':'door'}];b['shot_subjects']=['door']
    return plan,scene


def test_boundary_visible_does_not_reveal_room_interior_people_or_props():
    plan,scene=fixture();state=initial_state(plan,ENT)
    assert advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)['props']['door']=='other'
    for target in ('other','bread1','b'):
        bad=deepcopy(scene);bad['beats'][0]['gestures'][0]['target']=target
        hidden=deepcopy(state);hidden['props']['bread1']='other';hidden['locations']['b']='other'
        bad['beats'][0]['present']=['a']
        with pytest.raises(c.ContractError,match='gesture_target_not_visible'):
            advance(bad,plan['scenes'][0],plan,ENT,['f'],SOURCE,hidden)


def test_stationary_boundary_cannot_be_handed_to_actor():
    plan,scene=fixture();scene['beats'][0]['transfers']=[{'prop':'door','origin':'other','destination':'a','action':'take'}]
    with pytest.raises(c.ContractError,match='stationary_fixture_transfer'):
        advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,initial_state(plan,ENT))


def test_portable_prop_cannot_gain_cross_room_visibility():
    plan,_=fixture();plan['props'][-1]['stationary']=False
    with pytest.raises(ValueError,match='visibility_requires_stationary_fixture'):initial_state(plan,ENT)
