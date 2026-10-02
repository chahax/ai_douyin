from copy import deepcopy
from pathlib import Path
import json
import pytest
from src.content_factory.creative_state_plan_guidance import VERSION
from src.content_factory.creative_state_plan_v3 import RULES
from src.content_factory.creative_state_plan_v6 import build_state_plan_prompt,build_state_plan_repair
from src.content_factory.creative_segmented_director import bind_segmented_director
from src.content_factory.creative_workflow_contract import CreativeContractError


def test_old_v3_prompt_unchanged_new_guidance_covers_complete_hold_and_shape():
    old={'state_plan_version':'whole_film_state_plan_v3'}
    assert build_state_plan_prompt(old)==RULES
    context={**old,'state_plan_guidance_version':VERSION,'script':{'beats':[{'id':'B1'},{'id':'B2'}]}}
    prompt=build_state_plan_prompt(context)
    assert 'event.end起算' in prompt and '不能把抬眼' in prompt
    assert '独立event' in prompt and '数量=2' in prompt and '末拍=B2' in prompt
    assert '根层item' in prompt
    repair,payload=build_state_plan_repair('wrong',context,{'schema':'bad'})
    assert prompt in repair and payload['original_request']==context
    assert build_state_plan_prompt(old)==RULES


def test_guidance_is_explicit_in_new_binding_not_retroactive():
    old=bind_segmented_director(state_plan=True,state_plan_version='whole_film_state_plan_v3')
    current=bind_segmented_director(state_plan=True,state_plan_version='whole_film_state_plan_v3',state_plan_guidance_version=VERSION)
    assert 'state_plan_guidance_version' not in old
    assert current['state_plan_guidance_version']==VERSION
    assert current['prompt']!=old['prompt']
    with pytest.raises(CreativeContractError):
        bind_segmented_director(state_plan=True,state_plan_version='whole_film_state_plan_v3',state_plan_guidance_version='unknown')


def test_actual_first_round_prompt_can_be_rebuilt_unchanged():
    path=Path('data/production_trials/say_no_v3_two_production_cycles_20260928/round_01/director_state_plan__00.json')
    if not path.exists(): pytest.skip('local real receipt absent')
    record=json.loads(path.read_text(encoding='utf-8'))
    messages=record['request']['messages'];context=json.loads(messages[-1]['content'])
    assert 'state_plan_guidance_version' not in context
    assert build_state_plan_prompt(context)==RULES
    assert RULES in messages[0]['content']


def test_new_structure_preflight_reports_real_round_two_errors_together():
    from src.content_factory.creative_state_plan_guidance import validate_guided_structure,STRUCTURE_VERSION
    root=Path('data/production_trials/say_no_v3_two_production_cycles_20260928/round_02')
    path=root/'director_state_plan__00.json'
    if not path.exists(): pytest.skip('local receipt unavailable')
    before=path.read_bytes();record=json.loads(before)
    context=json.loads(record['request']['messages'][-1]['content'])
    value=json.loads(record['response_text'])
    assert context['state_plan_guidance_version']==VERSION
    validate_guided_structure(value,context)  # Historical guidance has no new gate.
    context['state_plan_guidance_version']=STRUCTURE_VERSION
    with pytest.raises(CreativeContractError,match='结构预检') as caught:
        validate_guided_structure(value,context)
    errors=json.loads(str(caught.value).split(': ',1)[1])
    expected=['beats.'+str(bi)+'.events.'+str(ei)+'.operations' for bi,b in enumerate(value['beats'])
              for ei,event in enumerate(b['events']) if not isinstance(event['operations'],list)]
    assert len(expected)>=2
    assert set(expected)<=set(row['path'] for row in errors)
    assert all(row['validator']=='type' for row in errors if row['path'] in expected)
    assert 'performance' not in str(caught.value)
    assert path.read_bytes()==before


def test_structure_preflight_accepts_valid_sample_without_mutation():
    from tests.test_creative_state_plan_v3 import sample
    from src.content_factory.creative_state_plan_guidance import validate_guided_structure,STRUCTURE_VERSION
    value,script,manifest=sample();before=deepcopy(value)
    context={'state_plan_version':value['schema'],'state_plan_guidance_version':STRUCTURE_VERSION,
             'script':script,'static_visual_manifest':manifest}
    validate_guided_structure(value,context)
    assert value==before
