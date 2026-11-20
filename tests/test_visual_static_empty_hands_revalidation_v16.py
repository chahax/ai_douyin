"""Only source-state-backed exact empty-hand wording bypasses exclusion lexing."""
from copy import deepcopy
import json
import pytest

from src.content_factory import visual_static_start_planner_v13 as base


def candidate(*,states=True,text=None):
    value=dict(visible_cast=['adult','child'],depicted_moment='start',static_start_prompt=text or
        'An adult man lies on the existing bed with open eyes. He holds no item: both empty hands rest on his own abdomen. A child stands beside him and alone holds the same bagged white bread in both hands.')
    if states:value['opening_states']=[dict(character_id='adult',posture='lying_supine',eyes='open',held_items=''),
        dict(character_id='child',posture='standing',eyes='open',held_items='same bagged white bread')]
    return value


def check(value):
    return base._check(value,dict(visible_cast=['adult','child']),dict(characters=[dict(id='adult',age_band='adult'),dict(id='child',age_band='child')]),
        dict(positive_only=True,max_words=250,word_target_only=True))


def test_structured_empty_hand_fact_is_allowed_without_rewriting_native_candidate():
    value=candidate();before=deepcopy(value);encoded=json.dumps(value,ensure_ascii=False).encode('utf-8')
    check(value)
    assert value==before and json.dumps(value,ensure_ascii=False).encode('utf-8')==encoded
    assert 'holds no item' in value['static_start_prompt']


@pytest.mark.parametrize('mutate',[
    lambda value:value.pop('opening_states'),
    lambda value:value['opening_states'][0].update(held_items='the bread'),
    lambda value:value['opening_states'][0].update(character_id='unseen_person'),
    lambda value:value.update(opening_states=None),
])
def test_same_words_without_current_visible_empty_hand_state_are_still_rejected(mutate):
    value=candidate();mutate(value)
    with pytest.raises(base.StaticBlocked,match='exclusion_list'):check(value)


@pytest.mark.parametrize('extra',[
    ' No additional people are present.', ' No other props appear.', ' The room is without a table.',
    ' Exclude any other person.', ' The scene is not a flashback.',
])
def test_real_exclusion_list_remains_rejected_even_with_empty_state(extra):
    value=candidate();value['static_start_prompt']+=extra
    with pytest.raises(base.StaticBlocked,match='exclusion_list'):check(value)


@pytest.mark.parametrize('phrase',['holding no items','holds no object','has no item'])
def test_allowance_does_not_expand_to_other_negative_constructions(phrase):
    value=candidate();value['static_start_prompt']=value['static_start_prompt'].replace('holds no item',phrase)
    with pytest.raises(base.StaticBlocked,match='exclusion_list'):check(value)
