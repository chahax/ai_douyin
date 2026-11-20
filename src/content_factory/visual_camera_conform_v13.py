"""Deterministic per-shot lens calibration; no camera/subject relocation or models."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from .visual_shot_binding_v3 import fingerprint
from .visual_first_frame_static_v13 import SCHEMA,SHOT_FOV_MIN,SHOT_FOV_MAX

VERSION='camera_vertical_conform/v13'


class CameraConformError(ValueError):pass


def _number(value):return type(value) in (int,float) and math.isfinite(value)
def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def _dimensions(width,height):
    if any(type(n) is not int or not 64<=n<=2048 or n%16 for n in (width,height)):
        raise CameraConformError('camera_conform_invalid_render_dimensions')


def conform_camera(raw_camera,desired_vertical_extent,*,width=736,height=1312):
    """Solve horizontal FOV at the unchanged optical-axis target distance.

    Extent is in the camera's target plane (image-up direction), not a claim
    about an actor's height, location or the source novel's measurements.
    """
    _dimensions(width,height)
    if (not isinstance(raw_camera,dict) or set(raw_camera)!={'eye','target','fov'}
        or any(not isinstance(raw_camera.get(key),list) or len(raw_camera[key])!=3 for key in ('eye','target'))
        or any(not _number(n) for key in ('eye','target') for n in raw_camera[key])
        or not _number(raw_camera['fov']) or not SHOT_FOV_MIN<=raw_camera['fov']<=SHOT_FOV_MAX):
        raise CameraConformError('camera_conform_invalid_raw_camera')
    if not _number(desired_vertical_extent) or desired_vertical_extent<=0:
        raise CameraConformError('camera_conform_positive_extent_required')
    distance=math.dist(raw_camera['eye'],raw_camera['target'])
    if distance<=1e-9:raise CameraConformError('camera_conform_eye_target_coincident')
    aspect=width/height
    fov=math.degrees(2*math.atan((desired_vertical_extent*aspect)/(2*distance)))
    if not SHOT_FOV_MIN<=fov<=SHOT_FOV_MAX:
        raise CameraConformError('camera_conform_requested_extent_unreachable_without_moving_camera:'
            +json.dumps(dict(required_horizontal_fov=fov,allowed=[SHOT_FOV_MIN,SHOT_FOV_MAX],desired_vertical_extent=desired_vertical_extent)))
    camera=deepcopy(raw_camera);camera['fov']=fov
    raw_extent=2*distance*math.tan(math.radians(raw_camera['fov']/2))/aspect
    achieved=2*distance*math.tan(math.radians(fov/2))/aspect
    return dict(schema=VERSION,raw_camera=deepcopy(raw_camera),camera=camera,
        raw_camera_sha256=fingerprint(raw_camera),camera_sha256=fingerprint(camera),
        width=width,height=height,aspect_ratio=aspect,target_distance=distance,
        distance_definition='Euclidean eye-to-target distance along the renderer optical axis',
        desired_vertical_extent=desired_vertical_extent,raw_vertical_extent=raw_extent,achieved_vertical_extent=achieved,
        formula='horizontal_fov_degrees = degrees(2 * atan(desired_vertical_extent * (width / height) / (2 * target_distance)))',
        eye_unchanged=True,target_unchanged=True,production_camera_choice=True,novel_measurement_approved=False)


def _derive(value,source_binding,desired_extents,width,height):
    if value.get('schema')!=SCHEMA or value.get('camera_conform') is not None:
        raise CameraConformError('camera_conform_requires_unconformed_static_plan')
    shots=value.get('shots')
    if (not isinstance(shots,list) or len({s.get('shot_id') for s in shots})!=len(shots)
        or not isinstance(desired_extents,dict) or not desired_extents
        or not set(desired_extents)<={s.get('shot_id') for s in shots}):
        raise CameraConformError('camera_conform_invalid_explicit_shot_scope')
    result=deepcopy(value);reports={}
    for shot in result['shots']:
        sid=shot['shot_id']
        if sid not in desired_extents:continue
        if not shot.get('camera_override'):raise CameraConformError('camera_conform_explicit_raw_camera_required:'+sid)
        report=conform_camera(shot['camera_override'],desired_extents[sid],width=width,height=height)
        shot['camera_override']=deepcopy(report['camera']);reports[sid]=report
    result['camera_conform']=dict(schema=VERSION,source_static_plan=source_binding,
        width=width,height=height,desired_extents=deepcopy(desired_extents),shots=reports,
        scope='Only horizontal field of view changed; all original eye/target/static text/source/shot bindings preserved.',
        production_camera_choice=True,novel_measurement_approved=False)
    return result


def derive_plan(source_plan_path,output_path,desired_extents,*,width=736,height=1312):
    """Write a new art plan; source/native plans are read-only and never overwritten."""
    _dimensions(width,height);source=Path(source_plan_path).resolve();output=Path(output_path).resolve()
    if source==output:raise CameraConformError('camera_conform_output_must_be_new_file')
    value=_read(source);source_binding=dict(path=str(source),sha256=_sha(source),content_sha256=fingerprint(value))
    result=_derive(value,source_binding,desired_extents,width,height)
    if output.exists():
        if _read(output)!=result:raise CameraConformError('camera_conform_existing_output_changed')
    else:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    verify_plan(result)
    return result


def verify_plan(value):
    """Recompute the immutable source and every lens decision without writing."""
    proof=value.get('camera_conform',{})
    if proof.get('schema')!=VERSION:raise CameraConformError('camera_conform_audit_missing')
    source=proof.get('source_static_plan',{});path=Path(source['path'])
    if _sha(path)!=source.get('sha256'):raise CameraConformError('camera_conform_raw_plan_file_changed')
    raw=_read(path)
    if fingerprint(raw)!=source.get('content_sha256'):raise CameraConformError('camera_conform_raw_plan_content_changed')
    _dimensions(proof['width'],proof['height'])
    expected=_derive(raw,source,proof['desired_extents'],proof['width'],proof['height'])
    if value!=expected:raise CameraConformError('camera_conform_camera_text_or_audit_changed')
    return True
