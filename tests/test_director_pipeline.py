import copy
import pytest
from src.content_factory.director_pipeline import replay,compile_cards,validate_outline,validate_photography,DURATIONS,fit_speech_windows


def outline():
    return {'characters':{'A':{'name':'甲','identity':'客人','appearance':'蓝衣','voice':'女中音'},'B':{'name':'乙','identity':'店员','appearance':'灰衣','voice':'男中音'}},
            'scene':'室内','props':{'P1':{'name':'杯子','location':'table'}},
            'locations':['table','A.left','A.right','B.left','B.right'],'state':{'door':'closed'},
            'events':[{'id':'S01','duration':7,'new_information':'检查杯子','emotion_trigger':'察觉杯温','emotional_change':'从担心到放松'}]}


def script():
    return {'shots':[{'id':'S01','actions':[{'start':0,'end':7,'actor':'A','description':'甲右手拿起杯子',
        'transfers':[{'prop':'P1','from':'table','to':'A.right'}],'updates':[]}],
        'lines':[{'speaker':'A','start':0.5,'end':2,'text':'这杯子有点烫'}],'emotion':{'A':'缩眉后放松','B':'关注客人'}}]}


def test_state_is_derived_and_input_unchanged():
    o=outline();before=copy.deepcopy(o);trace=replay(o,script())
    assert trace[0]['before']['props']['P1']=='table'
    assert trace[0]['after']['props']['P1']=='A.right'
    assert o==before


def test_impossible_transfer_rejected():
    s=script();s['shots'][0]['actions'][0]['transfers'][0]['from']='B.right'
    with pytest.raises(ValueError,match='origin'):replay(outline(),s)


def test_busy_hand_rejected():
    o=outline();o['props']['P2']={'name':'纸','location':'A.right'}
    with pytest.raises(ValueError,match='multiple'):replay(o,script())


def test_unspoken_timeline_cannot_overlap():
    s=script();s['shots'][0]['lines'].append({'speaker':'B','start':1,'end':3,'text':'你先把它放下'})
    with pytest.raises(ValueError,match='overlap'):replay(outline(),s)


def test_dialogue_rendered_once_and_audio_derived():
    p={'master':{'framing':'full_body_two_shot','angle':'same_side_oblique','light_source':'door_daylight'},'shots':[{'id':'S01','focus':'关心'}]}
    c=compile_cards(outline(),script(),p)[0]
    assert c['story_lock'].count('这杯子有点烫')==1
    assert '这杯子有点烫' not in c['audio']
    assert '0.5—2秒 甲' in c['audio']
    assert '秒，甲：' in c['beats']


def test_photography_cannot_override_each_segments_framing():
    p={'master':{'framing':'full_body_two_shot','angle':'same_side_oblique','light_source':'door_daylight'},'shots':[{'id':'S01','focus':'关心','composition':'突然特写'}]}
    with pytest.raises(ValueError,match='Only editorial'):validate_photography(outline(),p)


def test_photography_cannot_invent_light_source():
    p={'master':{'framing':'full_body_two_shot','angle':'same_side_oblique','light_source':'ceiling_and_door_daylight'},'shots':[{'id':'S01','focus':'关心'}]}
    with pytest.raises(ValueError,match='invent'):validate_photography(outline(),p)


def test_no_props_requires_no_hand_location_inventory():
    o=outline();o.update(title='测试',props={},locations=[],state={'A.position':'左','B.position':'右'})
    for c in o['characters'].values():c.update(want='表达',vulnerability='怕误会')
    o['events']=[{'id':f'S{i+1:02}','duration':d,'action':'交流','new_information':'回应','emotion_trigger':'听到','emotional_change':'释然','causal_link':'继续'} for i,d in enumerate(DURATIONS)]
    assert validate_outline(o,{})['props']=={}


def test_different_people_can_react_simultaneously():
    s=script();s['shots'][0]['actions'].append({'start':1,'end':6,'actor':'B','description':'乙看向甲','transfers':[],'updates':[]})
    assert replay(outline(),s)[0]['after']['props']['P1']=='A.right'


def test_authored_action_list_order_does_not_change_time_semantics():
    s=script();s['shots'][0]['actions'].insert(0,{'start':3,'end':6,'actor':'B','description':'乙看向甲','transfers':[],'updates':[]})
    assert replay(outline(),s)[0]['after']['props']['P1']=='A.right'


def test_same_person_cannot_have_conflicting_action_tracks():
    s=script();s['shots'][0]['actions'].append({'start':1,'end':6,'actor':'A','description':'甲又拿杯','transfers':[],'updates':[]})
    with pytest.raises(ValueError,match='Same actor'):replay(outline(),s)


def test_short_answer_not_forced_to_unnaturally_fast_speed():
    s=script();s['shots'][0]['lines']=[{'speaker':'A','start':0.3,'end':0.9,'text':'嗯。'}]
    assert replay(outline(),s)


def test_still_pose_between_actions_is_not_a_missing_action():
    s=script();s['shots'][0]['actions'][0]['end']=1
    assert replay(outline(),s)[0]['after']['props']['P1']=='A.right'


def test_speech_fit_preserves_words_and_retimes_reactions():
    s=script();s['shots'][0]['actions'][0].update(transfers=[],end=7)
    s['shots'][0]['lines']=[{'speaker':'A','start':0.2,'end':2.2,'text':'今晚朋友聚餐我替你答应了'},
                           {'speaker':'B','start':4.4,'end':6.8,'text':'不去是不想被安排跟友情是两码事'}]
    before=copy.deepcopy(s);fitted,report=fit_speech_windows(outline(),s)
    assert s==before and report['changes']
    assert [l['text'] for l in fitted['shots'][0]['lines']]==[l['text'] for l in s['shots'][0]['lines']]
    assert fitted['shots'][0]['lines'][1]['start']<4.4
    replay(outline(),fitted)
