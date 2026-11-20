"""Off-camera character speech stays distinct from narration and visible casting."""
import json
import pytest
from src.content_factory import visual_shot_binding_v3 as binding
from src.content_factory import visual_h3_handoff_v3 as handoff


def packet(mode='offscreen_dialogue'):
    return dict(book_id='novel',source={'path':'fixed.md','sha256':'a'*64},
        characters=[dict(id='su_mo',design_version='one'),dict(id='child',design_version='two')],
        places=[dict(id='room',design_version='room1')],shots=[dict(id='F1',scene_id='scene',
            place_id='room',visible_cast=['su_mo'],character_views={'su_mo':'front'},
            visual_prompt='苏墨躺在床上，闭着眼睛，眉头紧皱。',
            audio=[dict(speaker='child',mode=mode,text='二哥，今天没偷到钱，怎么办呀？')])])


def test_offscreen_child_is_not_imported_into_visible_reference_slots():
    p=packet();calls=[]
    def lookup(req):
        calls.append(req)
        return dict(**req,book_id='novel',asset_id=req['entity_id'],version=1,status='reviewed',sha256='b'*64)
    result=binding.compile_bindings(p,lookup)['shots'][0]
    assert [x['entity_id'] for x in calls]==['su_mo','room']
    assert result['audio']==p['shots'][0]['audio']
    text=handoff.prompt_for(result,dict(requested_seconds=12,native_seconds=12))
    assert 'offscreen_dialogue为指定角色在画外说话' in text
    payload=json.loads(text.split('\n',1)[1])
    assert payload['audio']==p['shots'][0]['audio']
    assert payload['visible_cast']==['su_mo']
    assert 'child' not in payload['visible_cast']


def test_onscreen_voice_only_child_still_rejected():
    with pytest.raises(ValueError,match='onscreen_speaker_not_visible'):
        binding.requirements(packet('onscreen'))


def test_typo_mode_is_not_silently_coerced():
    with pytest.raises(ValueError,match='unknown_audio_mode'):
        binding.requirements(packet('offscreen_typo'))


def test_source_chinese_role_label_reaches_h3_beside_stable_id():
    shot=packet()['shots'][0]
    shot['audio'][0].update(source_speaker='叶西决',source_channel='画外对白')
    text=handoff.prompt_for(shot,dict(requested_seconds=12,native_seconds=12))
    assert json.loads(text.split('\n',1)[1])['audio']==shot['audio']


@pytest.mark.parametrize('mode',['onscreen','inner_voice','voiceover'])
def test_existing_audio_modes_keep_old_prompt_contract(mode):
    shot=packet(mode)['shots'][0]
    shot['audio'][0]['speaker']='su_mo'
    text=handoff.prompt_for(shot,dict(requested_seconds=12,native_seconds=12))
    assert 'offscreen_dialogue为指定角色' not in text
    assert json.loads(text.split('\n',1)[1])['audio']==shot['audio']
