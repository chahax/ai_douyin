from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.pacing import validate_pacing
from src.content_factory.novel_adaptation.presentation import display_names
from src.content_factory.novel_adaptation import contracts as c
from test_novel_adaptation_scenes import PLAN,ENT,SCENE


def test_long_silent_reaction_rejected_but_brief_and_action_allowed():
    s=deepcopy(SCENE);b=s['beats'][0];b.update(audio=[],transfers=[],gestures=[{'verb':'nod_to'}])
    policy={'max_scene_seconds':30,'max_silent_reaction_seconds':2.5}
    with pytest.raises(c.ContractError,match='silent_reaction'):validate_pacing(s,policy)
    b['end']=2
    assert validate_pacing(s,policy)['status']=='configured_checks_passed'
    b['end']=4;b['gestures']=[{'verb':'open_bag'}]
    assert validate_pacing(s,policy)['status']=='configured_checks_passed'
    assert validate_pacing(s,None)['status']=='not_requested'


def test_upper_duration_is_not_a_required_target():
    assert validate_pacing(SCENE,{'max_scene_seconds':30})['status']=='configured_checks_passed'
    with pytest.raises(c.ContractError,match='duration_above'):validate_pacing(SCENE,{'max_scene_seconds':3})


def test_names_strip_notes_without_changing_identity_or_ambiguous_labels():
    e=deepcopy(ENT);p=deepcopy(PLAN);old=deepcopy(e)
    e['entities'][0]['display_name']='甲（主角）'
    e['entities'][1]['display_name']='土豆（袋内物说明）'
    before=deepcopy(e)
    names=display_names(p,e)
    assert names['a']=='甲' and names['b']=='土豆' and e==before
    e['entities'][1]['display_name']='甲（过去的原主）'
    names=display_names(p,e)
    assert names['a']=='甲（主角）' and names['b']=='甲（过去的原主）'
