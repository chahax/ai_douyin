import copy
import json
from pathlib import Path

import pytest

from src.content_factory.emotional_focus import validate_emotional_focus
from scripts.run_reference_director import validate


def fixture():
    story = {'characters':{'B':{}}, 'beats':[{'id':'B02','duration':10}, {'id':'B04','duration':4}],
             'emotional_focus':{'beat_id':'B02','actor':'B','pre_line_seconds':1.2,
                                'post_line_seconds':2,'resolution_max_seconds':4}}
    previous = {'story':story, 'visual':{'shots':[
        {'beat_id':'B02','start':0,'end':10,'subject':'B','size':'close'}]}}
    performance = {'beats':[{'id':'B02','lines':[
        {'speaker':'B','start':1.5,'end':4.2}, {'speaker':'B','start':4.8,'end':7.2}]}]}
    return previous, performance


def test_reaction_has_time_and_visible_face():
    previous, value = fixture()
    validate_emotional_focus('performance',value,previous)


@pytest.mark.parametrize('index,key,value', [(0,'start',0.5), (1,'end',9)])
def test_dialogue_cannot_consume_reaction_window(index,key,value):
    previous, performance = fixture()
    performance['beats'][0]['lines'][index][key] = value
    with pytest.raises(ValueError,match='reaction time'):
        validate_emotional_focus('performance',performance,previous)


def test_cutting_to_father_while_daughter_waits_fails():
    previous, value = fixture()
    previous['visual']['shots'][0]['end'] = 7.2
    previous['visual']['shots'].append({'beat_id':'B02','start':7.2,'end':10,'subject':'A','size':'close'})
    with pytest.raises(ValueError,match='coverage'):
        validate_emotional_focus('performance',value,previous)


def test_extended_ending_cannot_steal_focus_budget():
    previous, _ = fixture()
    previous['story']['beats'][-1]['duration'] = 8
    with pytest.raises(ValueError,match='Resolution'):
        validate_emotional_focus('story',previous['story'],{})


def test_legacy_replay_not_retroactively_marked_or_modified():
    value = {'beats':[]}
    before = copy.deepcopy(value)
    validate_emotional_focus('story',value,{})
    assert value == before


def test_story_supports_short_resolution_and_long_focus():
    story = {'title':'玄关一步','initial':'女儿门外父亲门内','ending':'进入后仍有距离',
        'characters':{k:{'name':k,'want':'接纳','fear':'拒绝'} for k in ('A','B')},
        'beats':[{'id':f'B{i:02}','duration':duration,'event':'可见事件','change':'关系改变','dialogue':[]}
                 for i,duration in enumerate([7,10,6,4],1)],
        'emotional_focus':fixture()[0]['story']['emotional_focus']}
    validate('story',story,{})
