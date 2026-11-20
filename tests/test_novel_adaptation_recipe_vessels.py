from copy import deepcopy
import pytest
from test_novel_adaptation_lifecycle import fixture
from test_novel_adaptation_scenes import ENT
from src.content_factory.novel_adaptation.scenes import initial_state
from src.content_factory.novel_adaptation import lifecycle as lc


def setup_case():
    plan,_=fixture()
    plan['props'].append({'id':'pot','owner':'room'})
    plan['recipes'][0]['input_containers']={'bread1':'pot'}
    return plan,initial_state(plan,ENT)


def test_only_explicit_vessel_allows_contained_input_and_consumption_detaches_it():
    _,state=setup_case()
    row={'actor':'a','recipe':'cook','destination':'room'}
    before=deepcopy(state)
    with pytest.raises(ValueError,match='recipe_input_wrong_vessel'):lc.apply(state,row,'transform','room')
    assert state==before
    lc.apply(state,{'actor':'a','prop':'bread1','container':'bag','destination':'a'},'unpack','room')
    lc.apply(state,{'actor':'a','prop':'bread1','container':'pot'},'pack','room')
    lc.apply(state,row,'transform','room')
    assert state['prop_status']['bread1']=='consumed' and lc.exists(state,'meal')
    assert lc.exists(state,'pot') and 'bread1' not in state['containers']


def test_missing_placement_cannot_be_replaced_by_visible_input():
    _,state=setup_case()
    lc.apply(state,{'actor':'a','prop':'bread1','container':'bag','destination':'a'},'unpack','room')
    with pytest.raises(ValueError,match='recipe_input_wrong_vessel'):
        lc.apply(state,{'actor':'a','recipe':'cook','destination':'room'},'transform','room')


@pytest.mark.parametrize('mapping',[{'bread1':'missing'},{'bread1':'meal'},{'bread1':'bread1'},{'bag':'pot'}])
def test_invalid_vessel_contract_is_rejected(mapping):
    plan,_=setup_case();plan['recipes'][0]['input_containers']=mapping
    with pytest.raises(ValueError):initial_state(plan,ENT)
