from copy import deepcopy
import pytest
from tests.test_creative_state_plan_v2 import sample as old_sample
from src.content_factory.creative_state_plan_v6 import validate_state_plan,compile_state_plan,build_state_plan_schema
from src.content_factory.creative_workflow_contract import CreativeContractError


def sample():
    p,s,m=old_sample();p['schema']='whole_film_state_plan_v3'
    p['beats'][0]['events'][0].update(phase='before_first_line',script_slot='before',dialogue_index=-1)
    p['beats'][1]['events'][0].update(phase='no_dialogue',script_slot='after',dialogue_index=-1)
    p['beats'][0]['events'].append({'start':2,'end':4,'phase':'first_line_delivery','script_slot':'dialogue_performance',
        'dialogue_index':0,'performance':'陈禾自然说出对白，呼吸平稳','operations':[]})
    return p,s,m


def test_delivery_overlaps_speech_and_preserves_source_plan():
    import jsonschema
    p,s,m=sample();raw=deepcopy(p)
    jsonschema.validate(p,build_state_plan_schema({'state_plan_version':p['schema'],'script':s,'static_visual_manifest':m}))
    validate_state_plan(p,s,m)
    assert '自然说出对白' in compile_state_plan(p,s,m)['shots'][0]['visible_performance']
    assert p==raw


def test_after_departure_cannot_happen_during_delivery():
    p,s,m=sample();p['beats'][0]['events'][-1].update(script_slot='after',dialogue_index=-1,phase='after_last_line')
    p['beats'][0]['events'][-1]['operations']=[{'kind':'move','actor':'C01','target':'','value':'门口'}]
    with pytest.raises(CreativeContractError,match='不能提前'): validate_state_plan(p,s,m)
    p['beats'][0]['events'][-1].update(script_slot='dialogue_performance',dialogue_index=0,phase='first_line_delivery')
    with pytest.raises(CreativeContractError,match='关键动作'): validate_state_plan(p,s,m)


def test_eight_characters_in_one_second_remains_invalid():
    p,s,m=sample();s['beats'][0]['dialogue'][0]['text']='麻烦你了，明天见啊。'
    p['beats'][0]['dialogue_windows'][0]['end']=3
    p['beats'][0]['events'][-1]['end']=3
    with pytest.raises(CreativeContractError,match='对白'): validate_state_plan(p,s,m)


def test_script_during_is_after_first_line_not_delivery():
    p,s,m=sample();event=p['beats'][0]['events'][-1]
    event.update(script_slot='during',dialogue_index=-1,phase='after_last_line')
    with pytest.raises(CreativeContractError,match='不能提前'): validate_state_plan(p,s,m)
    event.update(start=4,end=6)
    validate_state_plan(p,s,m)


def test_historical_v2_during_rejection_is_unchanged():
    p,s,m=old_sample();p['beats'][0]['events'][0].update(start=2,end=4,phase='during')
    with pytest.raises(CreativeContractError,match='during动作'): validate_state_plan(p,s,m)
