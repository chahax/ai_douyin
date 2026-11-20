from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.scenes import play_beat


def run(state,before,after,participants=None):
    beat={k:[] for k in ('moves','transfers','prop_uses','unpacks','packs','transforms','requires_information','audio','shot_subjects')}
    beat.update(id='B',gestures=[{'actor':'a','verb':'有据姿态变化','target':'room',
         'posture_change':{'before':before,'after':after,'participants':participants or ['a','b']}}])
    errors=[];play_beat(state,beat,'room','S','/B',lambda *x:errors.append(x))
    return errors


def test_standing_sitting_and_one_person_rising_preserve_other_postures():
    s={'locations':{'a':'room','b':'room'},'props':{}}
    assert not run(s,'unknown','standing')
    assert not run(s,'standing','seated')
    assert not run(s,'seated','standing',['a'])
    assert s['postures']=={'a':'standing','b':'seated'}


@pytest.mark.parametrize('case',['already_standing','remote','unknown_reset','mixed_group'])
def test_missing_sit_repeated_rise_or_remote_transition_cannot_pass(case):
    s={'locations':{'a':'room','b':'room'},'props':{},'postures':{'a':'standing','b':'standing'}}
    before='seated'
    if case=='remote':s['locations']['b']='elsewhere';before='standing'
    elif case=='unknown_reset':before='unknown'
    elif case=='mixed_group':s['postures']['a']='seated'
    previous=deepcopy(s['postures']);assert run(s,before,'seated' if case=='remote' else 'standing')
    assert s['postures']==previous
