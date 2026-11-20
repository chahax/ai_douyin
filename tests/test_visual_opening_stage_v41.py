"""First-beat spatial framing, world-state continuity and renderer contracts.

These tests run on CPU and do not dispatch a model or assume a proxy is a
photographic quality pass. Saved legacy plans/scripts stay unchanged.
"""
import ast
from copy import deepcopy
import json

import pytest

from src.content_factory import visual_opening_frame as opening
from src.content_factory import visual_spatial_reanchor_v34 as v
from src.content_factory import visual_spatial_scene_v24 as scene


def source_rows():
    return json.loads(v.SPEC.read_text(encoding='utf-8'))['shots']


def new_plan():
    return v.plan_from_spec(first_frame_policy=v.FIRST_FRAME_POLICY)


def write_source(tmp_path, change):
    spec=json.loads(v.SPEC.read_text(encoding='utf-8'))
    change(spec)
    path=tmp_path/'source.json'
    path.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
    return path


def renderer_state_function():
    # Execute the standalone renderer's actual selection helper without bpy.
    tree=ast.parse(v.OPENING_RENDER)
    assert all(isinstance(node,ast.FunctionDef) for node in tree.body)
    return tree


def test_real_four_shots_follow_first_beat_instead_of_union_cast():
    plan=new_plan()
    expected=[(['ye_nan','ye_xijue'],'medium'),(['su_mo'],'face_close'),
              (['ye_xijue'],'face_close'),(['su_mo'],'face_close')]
    for row,shot,(cast,framing) in zip(source_rows(),plan['shots'],expected):
        selected=shot['opening_frame']
        assert selected['policy']==opening.POLICY
        assert selected['in_frame_actor_ids']==cast
        assert selected['framing']==framing
        assert selected['camera_beat']==row['camera_beats'][0]
        assert selected['camera_beat_sha256']==scene.fingerprint(row['camera_beats'][0])
    assert scene.validate(plan)['valid'] is True


def test_closeup_does_not_remove_offframe_people_from_world():
    plan=new_plan()
    for shot in plan['shots']:
        assert all(actor['visible'] for actor in shot['start_state']['actors'].values())
        selected=opening.render_state(shot,shot['start_state'])
        assert sorted(who for who,a in selected['actors'].items() if a['visible'])==shot['opening_frame']['in_frame_actor_ids']
        assert selected['props']==shot['start_state']['props']
    assert all(a['end_state']==b['start_state'] for a,b in zip(plan['shots'],plan['shots'][1:]))
    assert plan['shots'][-1]['end_state']['actors']['ye_nan']['visible'] is False


def test_world_pose_prop_and_source_data_stay_continuous_without_camera_gaze_override():
    legacy=v.plan_from_spec();plan=new_plan();base=scene.novel_plan()
    for index,(old,new) in enumerate(zip(legacy['shots'],plan['shots'])):
        assert old['source_prompt']==new['source_prompt']
        assert old['dialogue_verbatim']==new['dialogue_verbatim']
        assert old['source_current_state']==new['source_current_state']
        assert old['start_state']['props']==new['start_state']['props']
        for who,actor in new['start_state']['actors'].items():
            oldactor=old['start_state']['actors'][who]
            assert {k:actor[k] for k in ('position','pose','eyes','visible')}=={k:oldactor[k] for k in ('position','pose','eyes','visible')}
            assert 'head_camera_aim_max_deg' not in actor
            # Headings come from original story blocking rather than the old
            # diagnostic camera. S04 uses the original received state.
            source_state=base['shots'][2]['end_state'] if index==3 else base['shots'][0]['start_state']
            assert actor['facing_deg']==source_state['actors'][who]['facing_deg']


def test_every_planned_subject_bound_fits_camera_and_closeups_stay_close():
    plan=new_plan()
    for row,shot in zip(source_rows(),plan['shots']):
        camera=plan['cameras'][shot['camera_id']]
        points=v._opening_points(shot['start_state'],plan['actors'],row['camera_beats'][0])
        assert 35<=camera['vertical_fov_deg']<=60
        for point in points:
            assert all(.07<=n<=.93 for n in scene.project(point,camera)['uv'])
        assert shot['framing_fit']['body_heading_preserved'] is True
        assert shot['framing_fit']['all_clip_identity_coverage_required'] is False


@pytest.mark.parametrize('framing',['hands_close','detail','invalid'])
def test_unimplemented_detail_geometry_is_explicitly_refused(tmp_path,framing):
    source=write_source(tmp_path,lambda spec:spec['shots'][1]['camera_beats'][0].update(framing=framing))
    with pytest.raises(scene.SpatialError,match='explicit_geometry'):
        v.plan_from_spec(source,first_frame_policy=v.FIRST_FRAME_POLICY)


def test_missing_subject_or_unpresent_world_subject_is_not_guessed(tmp_path):
    source=write_source(tmp_path,lambda spec:spec['shots'][1]['camera_beats'][0].update(actors={}))
    with pytest.raises(scene.SpatialError,match='first_camera_beat_subjects'):
        v.plan_from_spec(source,first_frame_policy=v.FIRST_FRAME_POLICY)
    source=source_rows()[1]
    plan=new_plan();state=deepcopy(plan['shots'][1]['start_state']);state['actors']['su_mo']['visible']=False
    with pytest.raises(scene.SpatialError,match='not_present'):
        v._opening_camera(source,state,plan['actors'],plan['cameras']['anchor_S02'],plan['room']['size'])


def test_first_camera_is_data_driven_not_selected_by_segment_or_character_name():
    plan=new_plan();row=deepcopy(source_rows()[1]);state=deepcopy(plan['shots'][1]['start_state']);actors=deepcopy(plan['actors'])
    before=v._opening_camera(row,state,actors,plan['cameras']['anchor_S02'],plan['room']['size'])
    row['camera_beats'][0]['actors']['new_actor']=row['camera_beats'][0]['actors'].pop('su_mo')
    state['actors']['new_actor']=state['actors'].pop('su_mo')
    next(actor for actor in actors if actor['id']=='su_mo')['id']='new_actor'
    after=v._opening_camera(row,state,actors,plan['cameras']['anchor_S02'],plan['room']['size'])
    assert before[0]==after[0]
    assert after[1]['in_frame_actor_ids']==['new_actor']


def test_standalone_render_selection_matches_stills_and_preserves_world():
    plan=new_plan();scope={'plan':plan,'json':json}
    exec(compile(renderer_state_function(),'opening_renderer','exec'),scope)
    renderer=scope['opening_render_state']
    for shot in plan['shots']:
        original=deepcopy(shot['start_state'])
        expected=opening.render_state(shot,shot['start_state'])
        actual=renderer(shot['id']+'_start',shot['start_state'])
        selected=shot['opening_frame'];holder=original['props']['bread_bag']['holder']
        bread_visible=holder in selected['in_frame_actor_ids'] and 'hands' in selected['camera_beat']['actors'][holder]['visible_parts']
        expected['_opening_bread_visible']=bread_visible
        assert actual==expected
        assert shot['start_state']==original
        assert renderer(shot['id']+'_end',shot['end_state']) is shot['end_state']
    assert renderer('room_front',None) is None


def test_optin_renderer_does_not_float_offframe_held_props(tmp_path):
    script=scene.blender_script(tmp_path/'plan.json',tmp_path/'out',scene.SKIN_MATERIALS,opening.POLICY)
    compile(script,'first_beat_blender','exec')
    assert "if state.get('_opening_bread_visible',True):" in script
    assert "state=opening_render_state(name,state)" in script
    assert "'world_in_scene_actor_ids'" in script
    assert "'rendered_prop_ids'" in script
    assert "'visible_actor_ids'" in script


def test_legacy_generated_script_remains_actual_frozen_bytes():
    old=v.RUN/'blender_canonical_v34'
    generated=scene.blender_script(v.RUN/'SPATIAL_PLAN.json',old,scene.SKIN_MATERIALS,v.POLICY)
    assert generated==(old/'render_spatial.py').read_text(encoding='utf-8')
    assert 'opening_render_state' not in generated
    plan=v.plan_from_spec()
    assert 'first_frame_policy' not in plan
    assert all('opening_frame' not in shot for shot in plan['shots'])


def test_prepare_freezes_policy_and_can_be_resumed_without_mutating_inputs(tmp_path):
    run=tmp_path/'new_opening_stage'
    a=v.prepare(run,first_frame_policy=opening.POLICY)
    b=v.prepare(run,first_frame_policy=opening.POLICY)
    assert a==b
    saved=json.loads((run/'SPATIAL_PLAN.json').read_text(encoding='utf-8'))
    assert saved['first_frame_policy']==opening.POLICY
    assert saved['shots'][1]['opening_frame']['in_frame_actor_ids']==['su_mo']
    assert json.loads((run/'SOURCE_CURRENT_STATE_DESIGN.json').read_text(encoding='utf-8'))['production_approved'] is False


def test_unknown_policy_never_silently_falls_back():
    with pytest.raises(scene.SpatialError,match='unsupported_first_frame_policy'):
        v.plan_from_spec(first_frame_policy='unknown')
