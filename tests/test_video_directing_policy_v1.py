"""Pure generic directing examples plus bound legacy/current regression inputs."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess

import pytest

from src.content_factory import video_directing_policy_v1 as p
from src.content_factory import h3_asset_flow_v2 as flow

ROOT=Path(__file__).resolve().parents[1]
CURRENT=ROOT/'data/video_generation/h3_contact_repair_s04_20261114_v1'
LEGACY=ROOT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'


def beat(actors,start=0,end=3,framing='medium',cut=False):
    return dict(start=start,end=end,framing=framing,cut=cut,
        actors={c:dict(pose='原文姿态',visible_parts=['face','torso','hands']) for c in actors},source_span_ids=[])


def entry(cast,camera,audio=None):
    return dict(full_clip_actor_ids=cast,canonical_characters={c:{} for c in cast},
        character_names={'a':'甲','b':'乙','c':'丙','n':'旁白'},camera_beats=camera,audio=audio or [],
        duration=camera[-1]['end'],place_id='current_room',postproduction_subtitles=False)


def contact_pair(performer='b',owner='c',part='forearm'):
    return dict(contact_id='care',performer_actor_id=performer,owner_actor_id=owner,body_part=part)


def contacts_for(camera,contact):
    return [dict(beat_index=i,contacts=[deepcopy(contact)],visible_contact_ids=[],released_after_beat=[]) for i,_ in enumerate(camera)]


def plan(source,manifest=None,contacts=None):
    return p.build_directing_plan(manifest or {},source,p.DEFAULT_POLICY,contact_rows=contacts)


@pytest.fixture
def actual():
    nr=next((CURRENT/'visual_h3_v3').iterdir())
    return flow.read(nr/'INPUT_MANIFEST.json'),flow.read(nr/'shots/S04/workflow_api.json')


@pytest.fixture
def policy(tmp_path):
    file=tmp_path/'generic_policy.json';file.write_text(json.dumps(p.DEFAULT_POLICY,ensure_ascii=False),encoding='utf-8')
    return flow.bind(file)


def test_generic_single_adult_scene_and_narration_keep_source_modes():
    source=entry(['a'],[beat(['a'])],[dict(start=.2,end=2.5,speaker='n',mode='voiceover',quote_index=0)])
    result=plan(source);text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert result['beats'][0]['composition']=='medium' and result['beats'][0]['sound'][0]['mode']=='voiceover'
    assert '画外声' in text and '童声' not in text and 'standing' not in text
    assert result['beats'][0]['contact_knowledge']=='unknown_no_structured_contact_plan'


def test_generic_offscreen_contact_single_medium_uses_clean_compact_upper_body():
    source=entry(['a','b','c'],[beat(['a'])])
    result=plan(source,contacts=contacts_for(source['camera_beats'],contact_pair()))
    current=result['beats'][0];text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert current['composition']=='compact_upper_body' and current['offscreen_actor_ids']==['b','c']
    assert '完整可辨的头肩和上身' in text and '乙、丙的身体整体处于本镜取景范围之外' in text
    assert 'solo_medium_foreground_fragment_risk' in current['risks']


def test_generic_visible_handshake_keeps_identifiable_pair_not_all_cast():
    source=entry(['a','b','c'],[beat(['a','b'])])
    result=plan(source,contacts=contacts_for(source['camera_beats'],contact_pair('a','b','hand')))
    text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert result['beats'][0]['composition']=='recognizable_contact_group'
    assert result['beats'][0]['visible_actor_ids']==['a','b'] and '甲、乙各自可辨认的头肩' in text
    assert '丙的身体整体' in text and result['all_cast_in_every_shot_required'] is False


def test_generic_group_wide_remains_group_and_free_camera():
    source=entry(['a','b','c'],[beat(['a','b','c'],framing='wide')])
    result=plan(source);text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert result['beats'][0]['composition']=='wide' and result['free_camera'] is True
    assert '自由切换' in text and '正对镜头' not in text


def test_generic_reasonable_hand_insert_is_allowed_with_explicit_owner():
    source=entry(['a'],[beat(['a'],framing='hands_close')])
    result=plan(source);current=result['beats'][0];text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert current['composition']=='owned_detail_insert' and current['body_ownership'][0]['owner_actor_id']=='a'
    assert '局部特写' in text and '甲的双手' in text


def test_hand_insert_during_onscreen_speech_keeps_face_instead_of_changing_audio_mode():
    audio=[dict(start=0,end=3,speaker='a',mode='onscreen',quote_index=0)]
    source=entry(['a'],[beat(['a'],framing='hands_close')],audio)
    result=plan(source);text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert result['beats'][0]['composition']=='face_and_owned_detail'
    assert '发声面部' in text and result['beats'][0]['sound'][0]['mode']=='onscreen'
    assert source['audio']==audio


def test_unstructured_care_prose_and_portrait_pose_are_not_inferred_as_state():
    source=entry(['a','b'],[beat(['a'])]);source['source_spans']=[dict(text='甲替乙护理。')]
    result=plan(source,manifest=dict(portraits={'a':dict(posture='standing')}))
    current=result['beats'][0]
    assert current['contact_knowledge']=='unknown_no_structured_contact_plan' and current['visible_contacts']==[]
    assert current['actor_state_source']=='source_camera_audio_only_no_pose_inference'
    assert current['prop_knowledge']=='unknown_source_actions_only'


def test_scene_change_uses_current_scene_without_inventing_a_route():
    source=entry(['a'],[beat(['a'])]);source['place_id']='new_room'
    result=plan(source,manifest=dict(previous_scene_state=dict(place_id='old_room')))
    current=result['beats'][0];text=p.render_plan(result,source,p.DEFAULT_POLICY)[0]['text']
    assert current['spatial']['explicit_scene_change'] is True and '当前场景的布局与人物起点' in text
    assert source['place_id']=='new_room' and '路线' not in text


@pytest.mark.parametrize('marker',[dict(guide_kind='generated_scene'),dict(segment_selection=dict(mode='scene_cut'))])
def test_explicit_scene_start_with_string_previous_state_and_legacy_location(marker):
    source=entry(['a'],[beat(['a'])]);source.pop('place_id')
    manifest=dict(marker,previous_scene_state='前场的已核说明，不解析自由文本',script_fields=dict(location=dict(place_id='new_room')))
    current=plan(source,manifest)['beats'][0]
    assert current['spatial']==dict(current_place_id='new_room',previous_place_id=None,explicit_scene_change=True,
        scene_change_evidence='bound_scene_start_or_scene_cut')


def test_contact_endpoint_not_in_camera_is_machine_error_not_a_partial_limb_excuse():
    source=entry(['a','b'],[beat(['a'])])
    with pytest.raises(p.DirectingPolicyError,match='both_planned_endpoints'):
        plan(source,contacts=contacts_for(source['camera_beats'],contact_pair('a','b')))


@pytest.mark.parametrize('extra',[dict(person_name='某个人'),dict(book='某本书'),dict(asset_path='D:/asset.png')])
def test_generic_policy_rejects_story_identity_and_asset_fields(extra):
    with pytest.raises(p.DirectingPolicyError,match='exact_keys'):p.validate_policy(dict(p.DEFAULT_POLICY,**extra))


def test_policy_schema_rules_and_budget_are_one_contract():
    changed=deepcopy(p.DEFAULT_POLICY);changed['rules'].remove('asset_identity_and_props')
    with pytest.raises(p.DirectingPolicyError,match='all_generic'):p.validate_policy(changed)
    changed=deepcopy(p.DEFAULT_POLICY);changed['max_static_chars']=80
    with pytest.raises(p.DirectingPolicyError,match='exceeds_policy_budget'):p.validate_policy(changed)
    assert len(p.STATIC)<=p.DEFAULT_POLICY['max_static_chars']


def test_actual_54s_mechanism_policy_is_applied_in_the_correct_shot_and_only_prompt_changes(actual,policy,monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('directing policy cannot execute media/model'))
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('directing policy cannot access network'))
    manifest,graph=actual;before_m=deepcopy(manifest);before_g=deepcopy(graph)
    result=p.apply(manifest,graph,policy);receipt=result['manifest']['directing_policy'];current=receipt['plan']['beats'][2]
    assert manifest==before_m and graph==before_g
    assert current['start']==8 and current['end']==14.2 and current['composition']=='compact_upper_body'
    assert set(current['offscreen_actor_ids'])=={'ye_yaner','ye_xijue','ye_nan'}
    assert 'offscreen_people_fully_outside_no_orphan_leg_or_torso' in current['visual_qa_checks']
    rendered=receipt['rendered_beats'][2]['text'];text=result['graph']['condition']['inputs']['prompt']
    lines=text.splitlines();at=next(i for i,line in enumerate(lines) if line.startswith('8—14.2秒，') and '入镜' in line)
    assert lines[at+1]==rendered and '完整可辨的头肩和上身' in rendered
    assert '叶嫣儿的身体整体' in rendered or '叶南、叶西决、叶嫣儿的身体整体' in rendered
    restored=deepcopy(result['graph']);restored['condition']['inputs']['prompt']=graph['condition']['inputs']['prompt']
    assert p.digest(restored)==p.digest(graph)
    restored_m=deepcopy(result['manifest']);restored_m.pop('directing_policy')
    for key in ('compiled_prompt','compiled_prompt_utf8_sha256','graph_sha256'):restored_m[key]=manifest[key]
    assert p.digest(restored_m)==p.digest(manifest)
    assert flow.core.QUOTE.findall(text)==flow.core.QUOTE.findall(manifest['compiled_prompt'])
    assert all(row['status']=='requires_actual_pixel_review' for row in receipt['checklist'])
    assert receipt['model_quality_passed'] is False and receipt['actual_pixels_checked'] is False


def test_legacy_adult_narration_pregraph_and_real_source_work_without_actor_state(policy):
    value=flow.read(LEGACY/'segments/S01/LIBRARY_INPUT.json')
    original=value['compiled_prompt'];graph=dict(condition=dict(inputs=dict(prompt=original)))
    manifest=dict(source_case=value['source_case'],compiled_prompt=original,compiled_prompt_utf8_sha256=flow.core.sha(original),
        graph_sha256=p.digest(graph),required_actor_assets=['su_mo'],guide=dict(review={}))
    result=p.apply(manifest,graph,policy);receipt=result['manifest']['directing_policy']
    assert all(b['actor_state_source']=='source_camera_audio_only_no_pose_inference' for b in receipt['plan']['beats'])
    assert any(a['mode']=='voiceover' for b in receipt['plan']['beats'] for a in b['sound'])
    assert flow.core.QUOTE.findall(result['rendered_text'])==flow.core.QUOTE.findall(original)
    assert '童声' not in '\n'.join(r['text'] for r in receipt['rendered_beats'])


def test_actual_legacy_s02_generated_room_activates_current_scene_rule_with_unknown_previous_place(policy):
    value=flow.read(LEGACY/'segments/S02/LIBRARY_INPUT.json');original=value['compiled_prompt']
    graph=dict(condition=dict(inputs=dict(prompt=original)))
    manifest=dict(source_case=value['source_case'],compiled_prompt=original,compiled_prompt_utf8_sha256=flow.core.sha(original),
        graph_sha256=p.digest(graph),guide_kind=value['guide_kind'],segment_selection=value['segment_selection'],
        script_fields=value['script_fields'],previous_scene_state='保留前场说明，地点ID未结构化',guide=dict(review={}))
    result=p.apply(manifest,graph,policy);receipt=result['manifest']['directing_policy'];first=receipt['plan']['beats'][0]
    assert first['spatial']['explicit_scene_change'] is True and first['spatial']['previous_place_id'] is None
    assert first['spatial']['current_place_id']=='children_room'
    assert '本场取景建立当前场景的布局与人物起点' in receipt['rendered_beats'][0]['text']
    assert not any(b['spatial']['explicit_scene_change'] for b in receipt['plan']['beats'][1:])
    assert any(a['mode']=='voiceover' for b in receipt['plan']['beats'] for a in b['sound'])
    assert flow.core.QUOTE.findall(result['rendered_text'])==flow.core.QUOTE.findall(original)


def test_parent_legacy_camera_header_formats_are_anchored_not_appended_at_end():
    original='开场说明\n0—5秒，以中景呈现，画面人物为甲。\n原动作\n5—9秒，切到头肩近景呈现，画面人物为甲。\n原动作'
    result=p._insert(original,[dict(start=0,end=5,text='第一镜导演说明'),dict(start=5,end=9,text='第二镜导演说明')])
    assert '画面人物为甲。\n第一镜导演说明\n原动作' in result
    assert '画面人物为甲。\n第二镜导演说明\n原动作' in result


def test_policy_binding_and_verified_graph_cannot_be_silently_repaired(actual,policy):
    manifest,graph=actual;original_graph=deepcopy(graph)
    graph['condition']['inputs']['width']=100
    with pytest.raises(p.DirectingPolicyError,match='verified_graph'):p.apply(manifest,graph,policy)
    Path(policy['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(p.DirectingPolicyError,match='bound_input_changed'):p.apply(manifest,original_graph,policy)


def test_contact_and_state_receipts_must_replay_before_directing(actual,policy):
    manifest,graph=actual;manifest['contact_continuity']['resolution']['active_contacts_by_beat'][2]['contacts'][0]['owner_actor_id']='ye_dong'
    with pytest.raises(p.DirectingPolicyError,match='replay_same_bound_resolution'):p.apply(manifest,graph,policy)


def test_repeat_apply_and_missing_camera_anchor_are_explicit_errors(actual,policy):
    first=p.apply(*actual,policy)
    with pytest.raises(p.DirectingPolicyError,match='already_applied'):p.apply(first['manifest'],first['graph'],policy)
    with pytest.raises(p.DirectingPolicyError,match='camera_prompt_anchor'):p._insert('只有台词',[dict(start=0,end=3,text='导演说明')])
