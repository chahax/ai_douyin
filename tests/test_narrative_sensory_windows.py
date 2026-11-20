from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.scenes import play_beat

def run(windows,audio=None,transfers=None):
    state={'locations':{'father':'kitchen','child':'hall'},'props':{'bowl':'father'}}
    beat={k:[] for k in ('moves','transfers','prop_uses','gestures','unpacks','packs','transforms','requires_information')}
    beat.update(id='B',audio=audio or [{'kind':'dialogue','speaker':'father','text':'出去玩吧。'}],
                shot_subjects=['father','child'],transfers=transfers or [])
    errors=[]
    trace=play_beat(state,beat,'hall','S','/B',lambda p,c,m:errors.append(c),sensory_windows=windows)
    return state,trace,errors

def window(end=0,visible=True,audible=True):
    return {'place':'kitchen','through_audio_index':end,'visible':visible,'audible':audible}

def test_open_door_does_not_move_people_and_records_actual_hearing():
    state,trace,errors=run([window()])
    assert not errors and state['locations']['father']=='kitchen'
    assert trace[0]['present']==['child']
    assert trace[0]['audible_people']==['child','father']
    assert state['information']['child'][0]['text']=='出去玩吧。'

def test_closed_door_blocks_later_remote_speech():
    _,_,errors=run([window()],audio=[{'kind':'dialogue','speaker':'father','text':'第一句'},
                                    {'kind':'dialogue','speaker':'father','text':'关门后'}])
    assert errors==['absent_speaker']

def test_remote_listener_does_not_learn_dialogue_after_window_closes():
    state,_,errors=run([window()],audio=[{'kind':'dialogue','speaker':'child','text':'开门时'},
                                        {'kind':'dialogue','speaker':'child','text':'关门后秘密'}])
    assert not errors
    assert [e['text'] for e in state['information']['father']]==['开门时']

def test_inner_voice_is_not_broadcast_through_open_door():
    state,_,errors=run([window()],audio=[{'kind':'inner','speaker':'father','text':'只是想法'}])
    assert not errors
    assert 'child' not in state['information']

def test_visibility_does_not_grant_hearing():
    _,_,errors=run([window(audible=False)])
    assert errors==['absent_speaker']

def test_hearing_does_not_grant_visibility():
    _,_,errors=run([window(visible=False)])
    assert errors==['shot_subject_not_visible']

def test_sensory_access_never_authorizes_remote_prop_transfer():
    _,_,errors=run([window()],transfers=[{'prop':'bowl','origin':'father','destination':'child'}])
    assert 'prop_transfer_remote' in errors

def test_no_window_preserves_previous_strict_behavior():
    _,_,errors=run([])
    assert 'absent_speaker' in errors and 'shot_subject_not_visible' in errors

@pytest.mark.parametrize('end',[True,-2,1])
def test_invalid_time_boundary(end):
    _,_,errors=run([window(end)])
    assert errors==['invalid_sensory_window']
