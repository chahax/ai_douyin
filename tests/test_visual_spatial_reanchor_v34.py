"""Current-source staging is separate from old B and supplies attached bodies."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory import visual_spatial_reanchor_v34 as v
from src.content_factory import visual_spatial_scene_v24 as s


def test_four_starts_match_current_source_not_old_B_sitting():
    p=v.plan_from_spec();states=[x['start_state'] for x in p['shots']]
    assert [x['actors']['su_mo']['pose'] for x in states]==['lying','lying','lying','standing']
    assert [x['actors']['su_mo']['eyes'] for x in states]==['closed','closed','open','open']
    assert [x['props']['bread_bag']['holder'] for x in states]==['ye_xijue','ye_xijue','ye_xijue','su_mo']
    assert all(x['end_state']==y['start_state'] for x,y in zip(p['shots'],p['shots'][1:]))
    assert len([o for o in p['objects'] if o['kind']=='bed'])==1


def test_every_new_start_binds_exact_v33_source_current_spans_and_ten_quotes():
    p=v.plan_from_spec();spec=json.loads(v.SPEC.read_text(encoding='utf-8'));assert sum(len(x['dialogue_verbatim']) for x in p['shots'])==10
    for source,shot in zip(spec['shots'],p['shots']):
        assert shot['source_prompt']==source['source']
        assert shot['source_current_state']['span_ids']==source['source_state_span_ids']
        assert all(x['kind']=='context' for x in shot['source_current_state']['spans'])


def test_canonical_room_authority_and_difference_are_explicit():
    p=v.plan_from_spec();d=p['visual_design']
    assert d['primary_canonical_room']['sha256']=='b97231a01cbaff83a000f12be5f22b140fe88e334ed63eb7184f2ba25157eee9'
    assert d['secondary_canonical_room']['sha256']=='d7a918205051c25248f39b6e83f927643a177e0467032fa891a3fe8c9ab93eb9'
    assert d['ceiling_lamp']=={'shape':'square','observed_in_primary':True,'count':1}
    assert d['new_decorations']==[] and 'doorway' in d['known_reference_difference']


def test_v34_script_has_connected_neck_shoulders_limbs_and_skin(tmp_path):
    script=s.blender_script(tmp_path/'plan.json',tmp_path/'out',s.SKIN_MATERIALS,v.POLICY)
    compile(script,'canonical_v34','exec')
    assert "B('neck'" in script and "L('sleeve'" in script and "B('hand'" in script
    assert "'canonical_ceiling_lamp'" in script and "cube('pillow'" not in script
    assert "'human_black_hair_v34'" in script and "scene.cycles.device='CPU'" in script
    assert "'stage_policy':'canonical_room_body/v34'" in script


def test_default_legacy_skin_script_is_still_frozen_exact():
    r=s.PROJECT/'data/video_generation/spatial_minute_experiments_20261107_v1/spatial_r3';out=r/'blender_skin_proxy_v25'
    assert s.blender_script(r/'SPATIAL_PLAN.json',out,s.SKIN_MATERIALS)==(out/'render_spatial.py').read_text(encoding='utf-8')


def test_missing_current_state_binding_rejected(tmp_path):
    spec=json.loads(v.SPEC.read_text(encoding='utf-8'));spec['shots'][2]['source_state_span_ids']=[];p=tmp_path/'spec.json';p.write_text(json.dumps(spec),encoding='utf-8')
    with pytest.raises(s.SpatialError,match='state_spans'):v.plan_from_spec(p)


def test_changed_source_file_binding_rejected(tmp_path):
    spec=json.loads(v.SPEC.read_text(encoding='utf-8'));spec['shots'][0]['source']['sha256']='0'*64;p=tmp_path/'spec.json';p.write_text(json.dumps(spec),encoding='utf-8')
    with pytest.raises(s.SpatialError,match='source_file_changed'):v.plan_from_spec(p)


def test_new_plan_prepare_freezes_current_states_without_root_approval(tmp_path):
    out=tmp_path/'new_spatial';a=v.prepare(out);b=v.prepare(out);assert a==b
    h=json.loads((out/'HANDOFF.json').read_text(encoding='utf-8'));assert h['production_approved'] is False
    receipt=json.loads((out/'SOURCE_CURRENT_STATE_DESIGN.json').read_text(encoding='utf-8'));assert receipt['source_binding_review_written'] is False


def test_unknown_stage_policy_rejected(tmp_path):
    with pytest.raises(s.SpatialError,match='unknown_spatial_stage'):s.blender_script(tmp_path/'plan.json',tmp_path/'out',s.SKIN_MATERIALS,'guess_room')


def test_all_required_head_boxes_fit_with_margin_without_moving_source_bodies():
    p=v.plan_from_spec()
    for shot in p['shots']:
        assert v.heads_fit(p['cameras'][shot['camera_id']],shot['start_state'],p['actors'])
    assert p['shots'][0]['framing_fit']['changed'] is True
    assert p['shots'][0]['start_state']['actors']['ye_nan']['position']==[2.8,2.95,0]


def test_old_high_camera_r1_does_not_pass_full_head_frame_check():
    p=v.plan_from_spec();camera={'position':[2.9,1.6,2.72],'target':[1.95,2.65,.95],'vertical_fov_deg':75,'near':.05}
    assert not v.heads_fit(camera,p['shots'][0]['start_state'],p['actors'])
