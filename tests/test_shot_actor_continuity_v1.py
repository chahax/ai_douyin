"""Pure CPU state/angle regressions, including the actual S04 frozen input."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import urllib.request

import pytest

from src.content_factory import shot_actor_continuity_v1 as flow

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/video_generation/h3_oral_revision_next_minute_20261113_v1'


def real_s04_case():
    entry=json.loads((RUN/'segments/S04/SOURCE_CASE.json').read_text(encoding='utf-8'))['shots'][0]
    previous=json.loads((RUN/'segments/S04/LIBRARY_INPUT.json').read_text(encoding='utf-8'))
    actors=entry['full_clip_actor_ids'];initial={}
    positions=dict(ye_dong='rear_right_of_younger_brother',ye_nan='left_bed_edge',ye_xijue='center_bed_edge',ye_yaner='low_front_right')
    postures=dict(ye_dong='unknown',ye_nan='seated',ye_xijue='seated',ye_yaner='kneeling')
    for cid in actors:
        initial[cid]=dict(instance_id=cid+':primary',position=positions[cid],posture=postures[cid],gaze='source_previous_gaze',
            held_items=['cotton_swab'] if cid=='ye_yaner' else [],body_ownership={'body':cid+':primary'})
    plan=dict(schema=flow.STATE_PLAN,initial=initial,
        initial_basis=dict(guide_image=previous['first_image'],guide_review_sha256=previous['guide_review']['sha256']),
        source_actions=[dict(source_span_id='s010',actor_id='ye_nan',allowed_changes=['gaze'],body_parts=['right_hand']),
            dict(source_span_id='s011',actor_id='ye_yaner',allowed_changes=['gaze'],body_parts=[]),
            dict(source_span_id='s012',actor_id='ye_dong',allowed_changes=['gaze'],body_parts=['right_wrist','right_hand'])],
        beats=[dict(beat_index=0,deltas=[dict(actor_id='ye_nan',source_span_ids=['s010'],changes={'gaze':'ye_dong'})],body_actions=[]),
            dict(beat_index=1,deltas=[dict(actor_id='ye_yaner',source_span_ids=['s011'],changes={'gaze':'ye_dong'})],body_actions=[]),
            dict(beat_index=2,deltas=[dict(actor_id='ye_dong',source_span_ids=['s012'],changes={'gaze':'own_right_wrist'})],body_actions=[
                dict(performer_actor_id='ye_dong',owner_actor_id='ye_dong',body_part='right_wrist',relation='self',action='inspect',source_span_ids=['s012']),
                dict(performer_actor_id='ye_dong',owner_actor_id='ye_dong',body_part='right_hand',relation='self',action='relax',source_span_ids=['s012'])]),
            dict(beat_index=3,deltas=[],body_actions=[],asserted_states={'ye_dong':{'instance_id':'ye_dong:primary','posture':'unknown'}})])
    return dict(schema=flow.CASE,actors=actors,camera_beats=entry['camera_beats'],audio=entry['audio'],source_spans=entry['source_spans'],
        state_plan=plan,available_views={c:['front','left_oblique'] for c in actors},room_views=['front','side'],
        guide=dict(actual=True,image=previous['first_image'],native_result=previous['predecessor_result']),
        max_references=9,previous_selection=previous['segment_selection']['actor_views']),entry['character_names']


def codes(result):return [n['code'] for n in result['notices']]


def test_actual_s04_recomputes_frozen_active_pair_and_prioritizes_dong():
    case,_=real_s04_case();before=deepcopy(case);result=flow.evaluate(case)
    assert result['status']=='ready' and case==before
    selected=result['angle_selection']
    assert selected['side_priority'][0]=='ye_dong' and selected['actor_views']['ye_dong']==['front','left_oblique']
    assert selected['side_priority'][1]=='ye_yaner' and selected['previous_selection_recomputed'] is True
    assert set(selected['required_front_actor_ids'])==set(case['actors'])
    assert all(v[0]=='front' for v in selected['actor_views'].values())
    assert selected['reference_budget']==dict(capacity=9,fronts=4,rooms=2,guide=1,sides=2,used=9)
    assert selected['room_views']==['front','side'] and selected['guide']==case['guide']


def test_cut_and_return_to_medium_keep_unknown_and_one_instance_without_portrait_inference():
    case,_=real_s04_case();case['guide']['portrait_posture']='standing'
    result=flow.evaluate(case);state=result['state_plan_result']
    assert result['status']=='ready' and state['initial_basis']==case['state_plan']['initial_basis']
    for beat in state['beats']:
        assert beat['before']['ye_dong']['posture']==beat['after']['ye_dong']['posture']=='unknown'
        assert beat['after']['ye_dong']['instance_id']=='ye_dong:primary'
    assert state['beats'][-1]['visible_instance_map']['ye_dong']=='ye_dong:primary'
    assert set(result['camera_beats'][1]['actors'])=={'ye_yaner'}
    assert result['free_camera'] and result['all_actors_in_every_frame_required'] is False


def test_unbound_seated_standing_jump_is_rejected_at_cut():
    case,_=real_s04_case();case['state_plan']['beats'][2]['asserted_states']={'ye_dong':{'posture':'seated'}}
    result=flow.evaluate(case)
    assert result['status']=='needs_state_repair' and 'asserted_state_does_not_follow_carried_entity' in codes(result)


def test_wrist_action_cannot_authorize_a_posture_reset():
    case,_=real_s04_case();case['state_plan']['beats'][2]['deltas'][0]['changes']['posture']='seated'
    result=flow.evaluate(case)
    assert 'source_action_does_not_authorize_changed_field' in codes(result)


def test_explicit_source_bound_posture_transition_is_allowed():
    case,_=real_s04_case();case['state_plan']['initial']['ye_dong']['posture']='seated'
    case['source_spans'].append(dict(id='stand_action',kind='action',text='叶东站起身。'))
    case['state_plan']['source_actions'].append(dict(source_span_id='stand_action',actor_id='ye_dong',allowed_changes=['posture'],
        change_values={'posture':['standing']},body_parts=[]))
    case['state_plan']['beats'][0]['deltas'].append(dict(actor_id='ye_dong',source_span_ids=['stand_action'],changes={'posture':'standing'}))
    case['state_plan']['beats'][3]['asserted_states']['ye_dong']['posture']='standing'
    result=flow.evaluate(case)
    assert result['status']=='ready' and result['state_plan_result']['final']['ye_dong']['posture']=='standing'


def test_self_wrist_cannot_point_at_another_actor_body():
    case,_=real_s04_case();case['state_plan']['beats'][2]['body_actions'][0]['owner_actor_id']='ye_nan'
    result=flow.evaluate(case)
    assert 'self_body_action_owner_mismatch' in codes(result)


def test_same_cid_cannot_hide_a_second_instance_in_camera_or_body_action():
    case,_=real_s04_case();case['camera_beats'][2]['actors']['ye_dong']['instance_id']='ye_dong:second'
    assert 'camera_actor_instance_must_match_carried_entity' in codes(flow.evaluate(case))
    case,_=real_s04_case();case['state_plan']['beats'][2]['body_actions'][0]['owner_instance_id']='ye_dong:second'
    assert 'body_action_instance_must_match_carried_entity' in codes(flow.evaluate(case))


def test_other_relation_cannot_disguise_a_self_body_action():
    case,_=real_s04_case();case['state_plan']['beats'][2]['body_actions'][0]['relation']='other'
    assert 'other_body_action_owner_mismatch' in codes(flow.evaluate(case))


def test_source_bound_other_body_care_is_valid_and_shares_the_shot():
    case,_=real_s04_case();case['source_spans'].append(dict(id='care',kind='action',text='叶嫣儿给叶西决擦手腕。'))
    case['state_plan']['source_actions'].append(dict(source_span_id='care',actor_id='ye_yaner',allowed_changes=[],body_parts=['right_wrist'],target_actor_ids=['ye_xijue']))
    case['state_plan']['beats'][1]['body_actions']=[dict(performer_actor_id='ye_yaner',owner_actor_id='ye_xijue',body_part='right_wrist',relation='other',action='care',source_span_ids=['care'])]
    result=flow.evaluate(case)
    assert result['status']=='ready' and result['camera_beats'][1]['framing']=='medium'
    assert set(result['camera_beats'][1]['actors'])=={'ye_yaner','ye_xijue'}
    assert 'face' in result['camera_beats'][1]['actors']['ye_yaner']['visible_parts']


def test_listener_reaction_merges_body_owner_without_forcing_whole_cast():
    case,_=real_s04_case();case['state_plan']['beats'][1]['body_actions']=deepcopy(case['state_plan']['beats'][2]['body_actions'])
    result=flow.evaluate(case)
    assert result['status']=='ready' and set(result['camera_beats'][1]['actors'])=={'ye_yaner','ye_dong'}
    assert result['camera_beats'][1]['framing']=='medium'
    metrics={r['actor_id']:r for r in result['angle_selection']['ranking']}
    assert metrics['ye_dong']['hand_action_complexity']==2  # same continuing action, not counted twice


@pytest.mark.parametrize('change',['extra_actor','extra_instance','duplicate_initial_instance'])
def test_new_entity_and_instance_resets_are_rejected(change):
    case,_=real_s04_case()
    if change=='extra_actor':case['camera_beats'][3]['actors']['blue_copy']={'pose':'copy','visible_parts':['face']}
    elif change=='extra_instance':case['state_plan']['beats'][3]['asserted_states']['ye_dong']['instance_id']='ye_dong:second'
    else:case['state_plan']['initial']['ye_dong']['instance_id']=case['state_plan']['initial']['ye_nan']['instance_id']
    assert flow.evaluate(case)['status']!='ready'


def test_missing_priority_side_is_notice_not_silent_lower_actor_substitution():
    case,_=real_s04_case();case['available_views']['ye_dong']=['front']
    result=flow.evaluate(case)
    assert result['status']=='needs_material' and any(n['code']=='priority_actor_side_view_missing' and n['actor_id']=='ye_dong' for n in result['notices'])


def test_existing_side_variant_is_chosen_with_explicit_reason():
    case,_=real_s04_case();case['available_views']['ye_dong']=['front','right_oblique']
    result=flow.evaluate(case);selection=result['angle_selection']
    assert result['status']=='ready' and selection['actor_views']['ye_dong']==['front','right_oblique']
    assert selection['side_allocations'][0]['reason'] and selection['side_allocations'][0]['available_side_variants']==['right_oblique']


def test_required_front_room_guide_budget_is_not_truncated():
    case,_=real_s04_case();case['max_references']=6
    result=flow.evaluate(case)
    assert result['status']=='needs_material' and 'required_fronts_rooms_guide_exceed_reference_budget' in codes(result)
    case,_=real_s04_case();case['available_views']['ye_xijue']=['left_oblique']
    assert 'required_actor_front_missing' in codes(flow.evaluate(case))
    case,_=real_s04_case();case['guide']['actual']=False
    assert 'actual_guide_reference_required' in codes(flow.evaluate(case))


def test_score_tie_has_stable_actor_id_rule_not_input_order():
    result=flow.select_angles(['b','a'],[dict(start=0,end=2,framing='medium',actors={'a':{},'b':{}})],
        [dict(mode='onscreen',speaker='a',start=0,end=1),dict(mode='onscreen',speaker='b',start=1,end=2)],
        {'a':['front','left_oblique'],'b':['front','left_oblique']},['front','side'],dict(actual=True,image={'path':'guide.png','sha256':'0'*64}),max_references=6)
    assert result['angle_selection']['side_priority']==['a','b'] and result['angle_selection']['actor_views']['a']==['front','left_oblique']
    assert result['angle_selection']['actor_views']['b']==['front']


def test_per_beat_state_render_materializes_carry_and_self_body_owner():
    case,names=real_s04_case();result=flow.evaluate(case);beats=flow.render_state_beats(result,names)
    assert [b['beat_index'] for b in beats]==[0,1,2,3]
    assert all('承接状态' in b['text'] and '镜后状态' in b['text'] for b in beats)
    assert '自己这具身体的右手腕' in beats[2]['text'] and 'ye_dong:primary' in beats[-1]['text']
    assert '姿态尚未确认' in beats[-1]['text'] and '自己这具身体的右手腕' in flow.render_state_instructions(result,names)


@pytest.mark.parametrize('start,end,speaker',[(-1,1,'ye_nan'),(0,16,'ye_nan'),(0,1,'unknown_new_child')])
def test_audio_bounds_and_required_actor_identity_are_checked(start,end,speaker):
    case,_=real_s04_case();case['audio'][0].update(start=start,end=end,speaker=speaker)
    assert flow.evaluate(case)['status']=='needs_material'


def test_module_has_no_network_model_process_or_production_side_effect(monkeypatch):
    case,_=real_s04_case()
    def forbidden(*args,**kwargs):pytest.fail('pure CPU continuity must not access network or launch a model')
    monkeypatch.setattr(socket,'create_connection',forbidden);monkeypatch.setattr(urllib.request,'urlopen',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
    result=flow.evaluate(case)
    assert result['status']=='ready' and result['model_calls']==result['media_calls']==0 and result['production_ready'] is False
