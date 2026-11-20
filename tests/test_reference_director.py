import copy
import pytest
from scripts.run_reference_director import validate, stage_prompt, PROMPT


def fixture():
    emotion = {'beats':[{'id':'B01','duration':6,'dialogue':[{'speaker':'A','text':'那话是我说错了。'}]}]}
    visual = {'space':{'entrance_count':1,'layout':'外走廊内玄关','door_hinge':'左','door_opening':'向内','axis':'父女连线','opening_positions':{'A':'内','B':'外'}},
              'shots':[{'id':'V01','beat_id':'B01','start':0,'end':2,'size':'wide','subject':'both','camera_side':'同侧','composition':'门内外','visible_evidence':'距离','cut_reason':'建立','continuity_anchor':'门框'},
                       {'id':'V02','beat_id':'B01','start':2,'end':6,'size':'close','subject':'A','camera_side':'同侧','composition':'父亲脸','visible_evidence':'认错后抬眼','cut_reason':'反应','continuity_anchor':'门框'}]}
    performance = {'beats':[{'id':'B01','actions':[{'actor':'A','start':2,'end':5,'trigger':'听到追问','description':'抬眼','body_before':'站定','body_after':'站定','face_change':'紧咬下唇到松开','gaze_target':'女儿','intensity':3,'readable_in_shot':'V02'}],
                            'lines':[{'speaker':'A','text':'那话是我说错了。','start':2,'end':5}], 'end_positions':{'A':'内','B':'外'}}]}
    return {'emotion':emotion,'visual':visual},performance


def test_reaction_closeup_is_allowed_with_establishing_shot():
    previous,_ = fixture()
    validate('visual',previous['visual'],previous)


def test_missing_spatial_time_coverage_rejected():
    previous,_ = fixture()
    previous['visual']['shots'][1]['start']=3
    with pytest.raises(ValueError,match='gap/overlap'):
        validate('visual',previous['visual'],previous)


def test_later_stage_cannot_reverse_dialogue_responsibility():
    previous,value = fixture()
    value['beats'][0]['lines'][0]['text']='不是你说的吗？'
    with pytest.raises(ValueError,match='Dialogue changed'):
        validate('performance',value,previous)


def test_action_cannot_cite_shot_before_it_happens():
    previous,value = fixture()
    value['beats'][0]['actions'][0]['readable_in_shot']='V01'
    with pytest.raises(ValueError,match='invisible'):
        validate('performance',value,previous)


def test_same_person_cannot_have_overlapping_action_tracks():
    previous,value = fixture()
    value['beats'][0]['actions'].append(copy.deepcopy(value['beats'][0]['actions'][0]))
    with pytest.raises(ValueError,match='overlap'):
        validate('performance',value,previous)


def test_model_sees_only_current_stage_output_contract():
    for stage in ('emotion','visual','performance'):
        prompt = stage_prompt(stage)
        assert 'stage='+stage+'：' in prompt
        for other in {'emotion','visual','performance'}-{stage}:
            assert 'stage='+other+'：' not in prompt


def test_each_director_stage_receives_shared_creative_constraints():
    shared = PROMPT.read_text(encoding='utf-8').split('stage=emotion：', 1)[0].strip()
    for stage in ('emotion', 'visual', 'performance'):
        prompt = stage_prompt(stage)
        assert shared in prompt
        assert prompt.index(shared) < prompt.index('stage='+stage+'：')
