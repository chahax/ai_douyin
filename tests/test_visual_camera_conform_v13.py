"""Deterministic lens math, explicit art-plan lineage and real CPU guide/H3 reads."""
from copy import deepcopy
import math
from pathlib import Path
import shutil

from jsonschema import ValidationError
import pytest

from src.content_factory import visual_camera_conform_v13 as c
from src.content_factory import visual_first_frame_static_v13 as s
from src.content_factory import visual_environment_v4 as e
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_h3_handoff_v3 as h
from test_visual_first_frame_static_v13 import fixture


@pytest.mark.parametrize('extent',[1.4,1.9,2.5,2.8])
def test_solves_vertical_target_plane_extent_exactly_without_moving_eye_or_target(extent):
    raw=dict(eye=[0,0,1.5],target=[0,3,1],fov=60);before=deepcopy(raw)
    result=c.conform_camera(raw,extent)
    distance=math.sqrt(3**2+.5**2)
    expected=math.degrees(2*math.atan(extent*(736/1312)/(2*distance)))
    assert result['camera']['fov']==pytest.approx(expected,abs=1e-12)
    assert result['achieved_vertical_extent']==pytest.approx(extent,abs=1e-12)
    assert result['target_distance']==distance and raw==before
    assert result['camera']['eye']==raw['eye'] and result['camera']['target']==raw['target']
    assert result['raw_vertical_extent']>extent and result['novel_measurement_approved'] is False


def test_aspect_ratio_and_actual_three_dimensional_target_distance_are_used():
    raw=dict(eye=[0,0,1],target=[0,3,3],fov=50)
    portrait=c.conform_camera(raw,2,width=736,height=1312)
    landscape=c.conform_camera(raw,2,width=1312,height=736)
    assert portrait['target_distance']==math.sqrt(13) and portrait['camera']['fov']<landscape['camera']['fov']
    for result in (portrait,landscape):
        d=result['target_distance'];a=result['width']/result['height'];fov=result['camera']['fov']
        assert 2*d*math.tan(math.radians(fov/2))/a==pytest.approx(2,abs=1e-12)


@pytest.mark.parametrize('extent',[.1,20,0,-1,True,float('inf'),float('nan'),'1.4'])
def test_unreachable_or_invalid_extent_never_clamps_or_relocates_camera(extent):
    raw=dict(eye=[0,0,1.5],target=[0,3,1.5],fov=60);before=deepcopy(raw)
    with pytest.raises(c.CameraConformError):c.conform_camera(raw,extent)
    assert raw==before


def test_raw_camera_and_dimensions_are_explicit_and_finite():
    raw=dict(eye=[0,0,1],target=[0,3,1],fov=60)
    for candidate in [dict(raw,target=[0,0,1]),dict(raw,eye=[True,0,1]),dict(raw,fov=float('nan')),
                      dict(raw,extra='silently move'),dict(raw,target=[0,3])]:
        with pytest.raises(c.CameraConformError):c.conform_camera(candidate,2)
    with pytest.raises(c.CameraConformError):c.conform_camera(raw,2,width=735)


def test_new_art_plan_changes_only_fov_and_preserves_immutable_source_and_other_shots(tmp_path):
    plan,_,_=fixture(tmp_path);source=Path(plan['config']['first_frame_plan']['path']);before=source.read_bytes();raw=p.read(source)
    second=deepcopy(raw['shots'][0]);second['shot_id']='F2';raw['shots'].append(second);p.write(source,raw);before=source.read_bytes()
    output=tmp_path/'CONFORMED.json';result=c.derive_plan(source,output,{'F1':1.4})
    assert source.read_bytes()==before and p.read(output)==result and c.verify_plan(result)
    assert result['shots'][1]==raw['shots'][1]
    for key in raw['shots'][0]:
        if key!='camera_override':assert result['shots'][0][key]==raw['shots'][0][key]
    assert result['shots'][0]['camera_override']['eye']==raw['shots'][0]['camera_override']['eye']
    assert result['shots'][0]['camera_override']['target']==raw['shots'][0]['camera_override']['target']
    assert 12<=result['shots'][0]['camera_override']['fov']<35
    assert c.derive_plan(source,output,{'F1':1.4})==result # Idempotent read, never rewrites origin.
    with pytest.raises(c.CameraConformError):c.derive_plan(source,source,{'F1':1.4})
    with pytest.raises(c.CameraConformError):c.derive_plan(source,output,{'F1':1.9})


@pytest.mark.parametrize('mutation',[
    lambda value:value['shots'][0]['camera_override']['target'].__setitem__(0,2),
    lambda value:value['shots'][0]['camera_override'].update(fov=30),
    lambda value:value['shots'][0].update(static_start_prompt='An invented new shot.'),
    lambda value:value['camera_conform']['shots']['F1'].update(achieved_vertical_extent=999),
])
def test_verification_recomputes_raw_camera_and_rejects_text_target_or_audit_changes(tmp_path,mutation):
    plan,_,_=fixture(tmp_path);result=c.derive_plan(plan['config']['first_frame_plan']['path'],tmp_path/'DERIVED.json',{'F1':1.4})
    mutation(result)
    with pytest.raises(c.CameraConformError):c.verify_plan(result)


def test_changed_raw_plan_or_unrequested_shot_cannot_be_hidden_in_calibration(tmp_path):
    plan,_,_=fixture(tmp_path);source=Path(plan['config']['first_frame_plan']['path'])
    with pytest.raises(c.CameraConformError):c.derive_plan(source,tmp_path/'UNKNOWN.json',{'not_in_plan':1.4})
    assert not (tmp_path/'UNKNOWN.json').exists()
    result=c.derive_plan(source,tmp_path/'DERIVED.json',{'F1':1.4});source.write_bytes(source.read_bytes()+b' ')
    with pytest.raises(c.CameraConformError,match='raw_plan_file_changed'):c.verify_plan(result)


def test_persistent_static_plan_consumption_rechecks_raw_plan_and_calculation(tmp_path):
    plan,_,_=fixture(tmp_path);source=Path(plan['config']['first_frame_plan']['path']);raw=source.read_bytes()
    output=tmp_path/'DERIVED.json';value=c.derive_plan(source,output,{'F1':1.4})
    plan['config']['first_frame_plan']=dict(path=str(output),sha256=p.file_sha(output))
    assert s.validate_plan(plan['packet'],plan['config'])==value
    source.write_bytes(raw+b' ')
    with pytest.raises(c.CameraConformError,match='raw_plan_file_changed'):s.validate_plan(plan['packet'],plan['config'])
    source.write_bytes(raw);value['camera_conform']['shots']['F1']['achieved_vertical_extent']=999;p.write(output,value)
    plan['config']['first_frame_plan']['sha256']=p.file_sha(output)
    with pytest.raises(c.CameraConformError,match='camera_text_or_audit_changed'):s.validate_plan(plan['packet'],plan['config'])


def test_narrow_lens_uses_same_shot_guide_in_generation_and_h3_without_changing_room_schema(tmp_path):
    plan,shot,entity=fixture(tmp_path);source=plan['config']['first_frame_plan']['path'];canonical=deepcopy(entity['spatial_layout'])
    path=tmp_path/'CONFORMED.json';result=c.derive_plan(source,path,{'F1':1.4},width=160,height=256)
    plan['config']['first_frame_plan']=dict(path=str(path),sha256=p.file_sha(path))
    assert s.validate_plan(plan['packet'],plan['config'])==result
    assert 12<=s.camera_for(entity,shot,s.entry(plan,shot))['fov']<35
    changed=deepcopy(canonical);changed['cameras']['side']=result['shots'][0]['camera_override']
    with pytest.raises(ValidationError):e.validate_layout(changed) # Canonical room contract is still >=35.
    assert e.layout_schema()['properties']['cameras']['properties']['side']['properties']['fov']['minimum']==35
    run=tmp_path/'asset';p.write(run/'PLAN.json',plan)
    guide=s.guide(run,plan,shot,entity,width=160,height=256,create=True);frame_path=run/'frame.png';shutil.copyfile(guide['path'],frame_path)
    assert h._ready_environment_guide(run,entity,shot,dict(path=str(frame_path),environment_guide=guide))==guide
    assert entity['spatial_layout']==canonical
