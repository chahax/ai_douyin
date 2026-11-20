from copy import deepcopy
import pytest
from test_novel_adaptation_scenes import PLAN,SCENE,ENT,SOURCE
from src.content_factory.novel_adaptation.scenes import advance,initial_state
from src.content_factory.novel_adaptation import contracts as c


def setup_case():
    plan=deepcopy(PLAN);plan['props']+=[{'id':'pot','owner':'other'},{'id':'rice','owner':'other'}]
    plan['containers']={'rice':'pot'}
    state=initial_state(plan,ENT);state['locations']['a']='other'
    scene=deepcopy(SCENE);b=scene['beats'][0];b['transfers']=[]
    b['moves']=[{'person':'a','origin':'other','destination':'room','carry_from_origin':['pot'],'action':'携锅入场'}]
    return plan,state,scene


def test_arrival_carries_only_explicit_local_objects_and_container_contents():
    plan,state,scene=setup_case();effects=[]
    end=advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state,effects=effects)
    assert end['locations']['a']=='room' and end['props']['pot']==end['props']['rice']=='a'
    assert state['props']['pot']=='other' and {e['prop'] for e in effects}=={'pot','rice'}


@pytest.mark.parametrize('case',['remote_prop','wrong_person','contained_item','fixture'])
def test_arrival_rejects_missing_transport_preconditions(case):
    plan,state,scene=setup_case()
    if case=='remote_prop':state['props']['pot']=state['props']['rice']='room'
    elif case=='wrong_person':state['locations']['a']='room'
    elif case=='contained_item':scene['beats'][0]['moves'][0]['carry_from_origin']=['rice']
    else:state['fixtures']={'pot':['other','room']}
    with pytest.raises(c.ContractError):advance(scene,plan['scenes'][0],plan,ENT,['f'],SOURCE,state)
