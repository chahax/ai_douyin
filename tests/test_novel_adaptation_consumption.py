from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import lifecycle as lc


def fixture():
    state={'locations':{'child':'room'},'props':{'food':'room','bowl':'room'},'containers':{'food':'bowl'}}
    recipe={'id':'eat','kind':'consumption','inputs':['food'],'outputs':[],
            'retained_inputs':[],'source_ids':['CH1-P001'],'input_containers':{'food':'bowl'}}
    plan={'allow_consumption_recipes':True,'recipes':[recipe]}
    return state,plan


def test_consumption_removes_food_preserves_bowl_and_creates_nothing():
    state,plan=fixture();lc.initialize(plan,state)
    lc.apply(state,{'actor':'child','recipe':'eat','destination':'room'},'transform','room')
    assert not lc.exists(state,'food') and lc.exists(state,'bowl')
    assert set(state['props'])=={'food','bowl'} and state['containers']=={}
    before=deepcopy(state)
    with pytest.raises(ValueError,match='already_applied'):
        lc.apply(state,{'actor':'child','recipe':'eat','destination':'room'},'transform','room')
    assert state==before


@pytest.mark.parametrize('case',['no_optin','outputs','retained','ordinary_empty'])
def test_consumption_cannot_weaken_old_transformation_contract(case):
    state,plan=fixture();recipe=plan['recipes'][0]
    if case=='no_optin':plan.pop('allow_consumption_recipes')
    elif case=='outputs':recipe['outputs']=['bowl']
    elif case=='retained':recipe['retained_inputs']=['food']
    elif case=='ordinary_empty':recipe.pop('kind')
    with pytest.raises(ValueError):lc.initialize(plan,state)


def test_remote_consumption_rejected_atomically():
    state,plan=fixture();state['locations']['child']='elsewhere';lc.initialize(plan,state)
    before=deepcopy(state)
    with pytest.raises(ValueError,match='actor_absent'):
        lc.apply(state,{'actor':'child','recipe':'eat','destination':'room'},'transform','room')
    assert state==before


def test_explicit_group_consumption_requires_all_participants_present():
    state,plan=fixture();state['locations']['sibling']='room';lc.initialize(plan,state)
    row={'actor':'child','participants':['child','sibling'],'recipe':'eat','destination':'room'}
    before=deepcopy(state);state['locations']['sibling']='outside';outside=deepcopy(state)
    with pytest.raises(ValueError,match='participants_absent'):lc.apply(state,row,'transform','room')
    assert state==outside
    state=before;lc.apply(state,row,'transform','room')
    assert state['prop_status']['food']=='consumed'
