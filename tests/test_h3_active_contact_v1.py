"""CPU-only actual-S04 contact regressions and generic source-bound boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess

import pytest

from src.content_factory import h3_active_contact_v1 as c
from src.content_factory import h3_asset_flow_v2 as flow

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/video_generation/h3_contact_repair_s04_20261114_v1'
OLD=ROOT/'data/video_generation/h3_asset_state_revision_minute_20261114_v1'


@pytest.fixture
def actual():
    spec=flow.read(RUN/'inputs/INPUT_SPEC.json')
    entry=flow._bound(flow.bind(OLD/'state_plans/S04_SOURCE_CASE_DERIVED_V2.json'))['shots'][0]
    return dict(schema=c.CASE,entry=entry,state_plan=flow._bound(spec['state_plan']),guide=spec['guide']),flow._bound(spec['contact_plan'])


def codes(result):return {n['code'] for n in result['notices']}


def test_real_s04_repair_closes_care_target_without_changing_other_shots_or_dialogue(actual):
    case,plan=actual;prior=deepcopy(case)
    result=c.resolve(case,plan)
    assert result['status']=='ready' and case==prior
    assert [r['beat_index'] for r in result['changes']]==[1]
    beat=result['entry']['camera_beats'][1]
    assert list(beat['actors'])==['ye_yaner','ye_dong','ye_xijue'] and beat['framing']=='medium'
    assert beat['actors']['ye_xijue']==dict(pose='叶西决坐在床边',visible_parts=['torso','hands'],instance_id='ye_xijue:primary')
    assert result['focus_actor_ids_by_beat'][1]['actor_ids']==['ye_yaner']
    assert result['state_plan']==case['state_plan'] and result['entry']['audio']==case['entry']['audio']
    for index in (0,2,3):assert result['entry']['camera_beats'][index]==case['entry']['camera_beats'][index]


def test_gaze_to_blue_never_changes_the_carried_care_owner(actual):
    case,plan=actual
    assert case['state_plan']['beats'][1]['deltas'][0]['changes']['gaze']=='ye_dong'
    result=c.resolve(case,plan)
    assert result['status']=='ready'
    assert all(row['contacts'][0]['owner_actor_id']=='ye_xijue' for row in result['active_contacts_by_beat'])


def test_blue_only_shot_does_not_pull_the_offscreen_contact_pair_into_frame(actual):
    result=c.resolve(*actual)
    assert set(result['entry']['camera_beats'][2]['actors'])=={'ye_dong'}
    assert result['active_contacts_by_beat'][2]['visible_contact_ids']==[]
    text=c.render_contacts(result,actual[0]['entry']['character_names'])[2]['text']
    assert '画外' in text and '叶西决' in text


def test_repaired_source_is_idempotent_and_keeps_primary_instances(actual):
    case,plan=actual;first=c.resolve(case,plan);case['entry']=first['entry']
    second=c.resolve(case,plan)
    assert second['status']=='ready' and second['changes']==[]
    assert second['entry']['camera_beats'][1]['actors']['ye_xijue']['instance_id']=='ye_xijue:primary'


def test_missing_owner_pose_is_material_notice_not_portrait_guess(actual):
    case,plan=actual;plan['actor_pose_spans']={}
    result=c.resolve(case,plan)
    assert result['status']=='needs_material' and 'missing_contact_endpoint_requires_exact_source_pose' in codes(result)


def test_wrong_visible_owner_instance_is_rejected(actual):
    case,plan=actual
    case['entry']['camera_beats'][1]['actors']['ye_xijue']=dict(pose='叶西决坐在床边',visible_parts=['torso','hands'],instance_id='ye_dong:primary')
    result=c.resolve(case,plan)
    assert result['status']!='ready'
    assert 'contact_requires_valid_actor_state_carry' in codes(result) or 'camera_contact_instance_mismatch' in codes(result)


def test_unobserved_owner_swap_cannot_be_authorized_by_gaze(actual):
    case,plan=actual;contact=plan['initial_contacts'][0]
    contact['owner_actor_id']='ye_dong';contact['owner_instance_id']='ye_dong:primary'
    result=c.resolve(case,plan)
    assert 'contact_must_match_initial_guide_observation' in codes(result)


def test_release_without_source_authority_is_not_ready(actual):
    case,plan=actual;plan['events']=[dict(beat_index=1,phase='after_beat',release_id='unbacked_release')]
    assert 'release_event_requires_bound_action_at_camera_boundary' in codes(c.resolve(case,plan))


def test_dongs_own_relax_action_cannot_release_girls_contact(actual):
    case,plan=actual
    plan['source_releases']=[dict(release_id='wrong_actor',contact_id=plan['initial_contacts'][0]['contact_id'],
        performer_actor_id='ye_dong',owner_actor_id='ye_xijue',body_part='forearm',source_span_ids=['s012'],action_text='松开')]
    plan['events']=[dict(beat_index=2,phase='after_beat',release_id='wrong_actor')]
    assert 'release_requires_same_contact_and_explicit_source_action' in codes(c.resolve(case,plan))


def test_forging_girl_as_actor_does_not_reuse_dongs_source_release(actual):
    case,plan=actual
    plan['source_releases']=[dict(release_id='wrong_source',contact_id=plan['initial_contacts'][0]['contact_id'],
        performer_actor_id='ye_yaner',owner_actor_id='ye_xijue',body_part='forearm',source_span_ids=['s012'],action_text='松开')]
    plan['events']=[dict(beat_index=2,phase='after_beat',release_id='wrong_source')]
    assert 'release_requires_same_contact_and_explicit_source_action' in codes(c.resolve(case,plan))


def add_explicit_release(case,plan):
    # Synthetic source-authority unit case; never written into the real novel.
    case['entry']['source_spans'].append(dict(id='synthetic_release',kind='action',text='女孩放开了弟弟的前臂。'))
    case['entry']['camera_beats'][0]['source_span_ids'].append('synthetic_release')
    case['state_plan']['source_actions'].append(dict(source_span_id='synthetic_release',actor_id='ye_yaner',allowed_changes=[],
        body_parts=['forearm'],target_actor_ids=['ye_xijue'],contact_effect='release',contact_id=plan['initial_contacts'][0]['contact_id']))
    plan['source_releases']=[dict(release_id='release_care',contact_id=plan['initial_contacts'][0]['contact_id'],
        performer_actor_id='ye_yaner',owner_actor_id='ye_xijue',body_part='forearm',source_span_ids=['synthetic_release'],action_text='放开')]
    plan['events']=[dict(beat_index=0,phase='after_beat',release_id='release_care')]


def test_explicit_same_contact_release_stops_carry_after_that_shot(actual):
    case,plan=actual;add_explicit_release(case,plan)
    result=c.resolve(case,plan)
    assert result['status']=='ready' and result['active_contacts_by_beat'][0]['released_after_beat']
    assert all(not row['contacts'] for row in result['active_contacts_by_beat'][1:])
    assert 'ye_xijue' not in result['entry']['camera_beats'][1]['actors']


def remove_tool_via_source_delta(case):
    case['entry']['source_spans'].append(dict(id='synthetic_tool',kind='action',text='女孩收起了棉签。'))
    case['state_plan']['source_actions'].append(dict(source_span_id='synthetic_tool',actor_id='ye_yaner',allowed_changes=['held_items'],body_parts=[]))
    case['state_plan']['beats'][0]['deltas'].append(dict(actor_id='ye_yaner',source_span_ids=['synthetic_tool'],changes={'held_items':[]}))


def test_tool_loss_does_not_silently_release_or_continue_contact(actual):
    case,plan=actual;remove_tool_via_source_delta(case)
    assert 'active_contact_tool_lost_without_source_release' in codes(c.resolve(case,plan))


def test_source_release_allows_tool_change_at_the_same_boundary(actual):
    case,plan=actual;add_explicit_release(case,plan);remove_tool_via_source_delta(case)
    assert c.resolve(case,plan)['status']=='ready'


def test_render_is_human_readable_and_rejects_tampered_resolution(actual):
    result=c.resolve(*actual);rendered=c.render_contacts(result,actual[0]['entry']['character_names'])
    assert len(rendered)==4 and all('ye_' not in row['text'] and ':primary' not in row['text'] for row in rendered)
    assert '叶嫣儿持棉签，轻扶叶西决同一身体的前臂' in rendered[1]['text']
    result['active_contacts_by_beat'][1]['contacts'][0]['owner_actor_id']='ye_dong'
    with pytest.raises(ValueError,match='unchanged_contact_resolution'):c.render_contacts(result,actual[0]['entry']['character_names'])


def test_complete_actual_core_compile_passes_source_pose_and_preserves_all_nine_assets(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('CPU input compile cannot execute media/model'))
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('CPU input compile cannot access network'))
    spec=flow.read(RUN/'inputs/INPUT_SPEC.json');result=flow.compile_spec(spec)
    assert 'manifest' in result and result['manifest']['status']=='offline_draft_valid'
    refs=result['manifest']['references'];old=flow.read(OLD/'segments/S04/offline_v2/INPUT_MANIFEST.json')['references']
    assert [r['image'] for r in refs]==[r['image'] for r in old] and len(refs)==9
    assert result['manifest']['angle_selection']['side_priority'][:2]==['ye_dong','ye_nan']
    assert '叶嫣儿、叶东、叶西决' in result['graph']['condition']['inputs']['prompt']
    # The separately tested Root contact wrapper must perform insertion; no
    # base-flow test pretends that sidecar metadata already altered its prompt.
    assert '本镜持续接触：' not in result['graph']['condition']['inputs']['prompt']


def test_complete_core_compile_rejects_non_source_pose_even_when_state_module_passes(tmp_path):
    spec=flow.read(RUN/'inputs/INPUT_SPEC.json');source=flow._bound(spec['source_case'])
    source['shots'][0]['camera_beats'][1]['actors']['ye_xijue']['pose']='这是无据新增的同一人物备注'
    file=tmp_path/'invalid_source_pose.json';file.write_text(json.dumps(source,ensure_ascii=False),encoding='utf-8');spec['source_case']=flow.bind(file)
    result=flow.compile_spec(spec)
    assert 'manifest' not in result and 'visible_actor_parts_and_source_exact_pose_required' in str(result)
