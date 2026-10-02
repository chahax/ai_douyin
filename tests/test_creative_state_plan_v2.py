from copy import deepcopy
import pytest
from src.content_factory.creative_state_plan_v6 import validate_state_plan,compile_state_plan,build_state_plan_prompt,build_state_plan_repair,build_state_plan_schema,RULES
from src.content_factory.creative_segmented_director import bind_segmented_director
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_state_plan_v6 import sample as old_sample


def sample():
    p,s,m=old_sample();p['schema']='whole_film_state_plan_v2'
    p['beats'][0]['events']=[{'start':0,'end':2,'phase':'before','performance':'自然完成操作',
        'operations':[{'kind':'take','actor':'C02','target':'P01','value':'右手'}]}]
    p['beats'][1]['events']=[{'start':0,'end':2,'phase':'after','performance':'自然坐稳',
        'operations':[{'kind':'sit','actor':'C02','target':'E02','value':'椅上'}]}]
    return p,s,m


def test_v2_compiles_from_actions_and_preserves_raw():
    p,s,m=sample();raw=deepcopy(p);result=compile_state_plan(p,s,m)
    assert p==raw
    assert '拿起P01' in result['shots'][0]['visible_performance']
    assert result['shots'][0]['end_state']==result['shots'][1]['start_state']
    assert 'sitting' in result['shots'][1]['end_state']


@pytest.mark.parametrize('mutation,error',[(lambda p:p['initial_state']['C02'].update(posture='sitting'),'sit要求'),
    (lambda p:p['initial_state']['P01'].update(holder='C02'),'take要求'),
    (lambda p:p['beats'][0]['events'][0]['operations'][0].update(kind='place'),'place要求')])
def test_physical_preconditions(mutation,error):
    p,s,m=sample();mutation(p)
    with pytest.raises(CreativeContractError,match=error): validate_state_plan(p,s,m)


def test_noop_gaze_does_not_pay_to_repair():
    p,s,m=sample();p['beats'][0]['events'][0]['operations'].append({'kind':'gaze','actor':'C01','target':'','value':'C02'})
    validate_state_plan(p,s,m)
    assert '维持gaze' in compile_state_plan(p,s,m)['shots'][0]['visible_performance']


def test_independent_simultaneous_performers_allowed():
    p,s,m=sample();p['beats'][0]['events'].append({'start':1,'end':2,'phase':'before','performance':'注意对方',
        'operations':[{'kind':'gaze','actor':'C01','target':'','value':'P01'}]})
    validate_state_plan(p,s,m)


def test_overlapping_prop_dependency_rejected():
    p,s,m=sample();p['beats'][0]['events'].append({'start':1,'end':2,'phase':'before','performance':'放下',
        'operations':[{'kind':'place','actor':'C02','target':'P01','value':'桌面'}]})
    with pytest.raises(CreativeContractError): validate_state_plan(p,s,m)


def test_after_cannot_start_while_dialogue_speaking():
    p,s,m=sample();p['beats'][0]['events'][0].update(start=3,end=5,phase='after')
    with pytest.raises(CreativeContractError,match='after动作'): validate_state_plan(p,s,m)


def test_before_cannot_finish_after_speech_starts():
    p,s,m=sample();p['beats'][0]['events'][0].update(end=3)
    with pytest.raises(CreativeContractError,match='before动作'): validate_state_plan(p,s,m)


def test_v1_prompt_remains_exact_and_v2_is_explicit():
    assert build_state_plan_prompt({})==RULES
    binding=bind_segmented_director(state_plan=True,state_plan_version='whole_film_state_plan_v2')
    assert binding['state_plan_version']=='whole_film_state_plan_v2'
    assert 'operations' in binding['prompt']
    instruction,payload=build_state_plan_repair('error',binding,{})
    assert 'whole_film_state_plan_v2' in instruction


def test_schema_agrees_with_fixture():
    import jsonschema
    p,s,m=sample();schema=build_state_plan_schema({'script':s,'static_visual_manifest':m})
    jsonschema.validate(p,schema)
