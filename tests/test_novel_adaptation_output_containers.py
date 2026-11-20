from copy import deepcopy
import pytest
from test_novel_adaptation_lifecycle import fixture
from test_novel_adaptation_scenes import ENT,SOURCE,SCENE
from src.content_factory.novel_adaptation import lifecycle as lc
from src.content_factory.novel_adaptation.scenes import initial_state,advance


def setup_case():
    plan,_=fixture();plan['props'].append({'id':'pot','owner':'room'})
    plan['recipes'][0]['output_containers']={'meal':'pot'}
    state=initial_state(plan,ENT)
    lc.apply(state,{'actor':'a','prop':'bread1','container':'bag','destination':'a'},'unpack','room')
    return plan,state


def test_finished_food_is_contained_and_follows_carried_pot():
    plan,state=setup_case()
    lc.apply(state,{'actor':'a','recipe':'cook','destination':'room'},'transform','room')
    assert state['containers']['meal']=='pot'
    scene=deepcopy(SCENE);b=scene['beats'][0]
    b['transfers']=[{'prop':'pot','origin':'room','destination':'a','action':'拿起锅'}]
    end=advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)
    assert end['props']['meal']==end['props']['pot']=='a'
    assert end['containers']['meal']=='pot'


@pytest.mark.parametrize('case',['remote','wrong_owner','absent'])
def test_unavailable_output_vessel_fails_atomically(case):
    _,state=setup_case()
    if case=='remote':state['props']['pot']='other'
    elif case=='wrong_owner':state['props']['pot']='b'
    else:state['prop_status']['pot']='planned'
    before=deepcopy(state)
    with pytest.raises(ValueError,match='output_vessel_unavailable'):
        lc.apply(state,{'actor':'a','recipe':'cook','destination':'room'},'transform','room')
    assert state==before


@pytest.mark.parametrize('mapping',[{'meal':'meal'},{'meal':'bread1'},{'meal':'missing'},{'bread1':'pot'}])
def test_bad_output_container_design_rejected(mapping):
    plan,_=setup_case();plan['recipes'][0]['output_containers']=mapping
    with pytest.raises(ValueError):initial_state(plan,ENT)
