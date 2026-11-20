from copy import deepcopy
from src.content_factory.novel_adaptation.scenes import play_beat


def sample():
    state={'locations':{'father':'kitchen','child':'kitchen'},'props':{}}
    beat={k:[] for k in ('moves','transfers','prop_uses','gestures','unpacks','packs','transforms','requires_information','audio','shot_subjects')}
    beat.update(id='B',gestures=[{'actor':'father','target':'child','verb':'推孩子走出厨房','execution_place':'kitchen'}],
        moves=[{'person':'child','origin':'kitchen','destination':'hall'}],
        action_order=[{'field':'gestures','index':0},{'field':'moves','index':0}])
    return state,beat


def execute(state,beat):
    errors=[]
    play_beat(state,beat,'hall','S','/B',lambda path,code,message:errors.append(code))
    return errors


def test_camera_in_hall_can_show_interaction_inside_kitchen_before_exit():
    state,beat=sample()
    assert execute(state,beat)==[]
    assert state['locations']=={'father':'kitchen','child':'hall'}


def test_explicit_place_does_not_grant_contact_after_child_has_left():
    state,beat=sample();beat['action_order'].reverse()
    assert 'gesture_target_not_visible' in execute(state,beat)


def test_default_place_contract_and_actor_location_stay_strict():
    state,beat=sample();del beat['gestures'][0]['execution_place']
    assert 'gesture_actor_absent' in execute(state,beat)
    state,beat=sample();beat['gestures'][0]['execution_place']='other_room'
    assert 'gesture_actor_absent' in execute(state,beat)
