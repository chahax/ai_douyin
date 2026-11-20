from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import lifecycle as lc


def fixture():
    state={'locations':{'cook':'room'},'props':{'raw':'room','meal':'room','pot':'room','bowl':'room'},
           'containers':{'raw':'pot'}}
    plan={'planned_props':['meal'],'recipes':[{'id':'cook','inputs':['raw'],'outputs':['meal'],
          'retained_inputs':[],'source_ids':['CH1-P001']}]}
    lc.initialize(plan,state)
    row={'actor':'cook','recipe':'cook','destination':'room',
         'input_containers':{'raw':'pot'},'output_containers':{'meal':'pot'}}
    return state,row


def test_explicit_processing_inside_vessel_preserves_container_and_recipe():
    state,row=fixture();recipe=deepcopy(state['recipes'])
    lc.apply(state,row,'transform','room')
    assert state['containers']=={'meal':'pot'}
    assert state['prop_status']['raw']=='consumed'
    assert state['recipes']==recipe


@pytest.mark.parametrize('case',['wrong_vessel','undeclared','non_input','fixed_conflict','remote_output','consumed_vessel'])
def test_vessel_declaration_does_not_bypass_actual_state(case):
    state,row=fixture()
    if case=='wrong_vessel':row['input_containers']['raw']='bowl'
    elif case=='undeclared':row.pop('input_containers')
    elif case=='non_input':row['input_containers']['meal']='pot'
    elif case=='fixed_conflict':state['recipes']['cook']['input_containers']={'raw':'bowl'}
    elif case=='remote_output':state['props']['bowl']='other';row['output_containers']['meal']='bowl'
    elif case=='consumed_vessel':row['output_containers']['meal']='raw'
    before=deepcopy(state)
    with pytest.raises(ValueError):lc.apply(state,row,'transform','room')
    assert state==before
