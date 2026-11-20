"""Explicit source-reviewed same-frame endpoint conditioning, never output looping."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .visual_shot_binding_v3 import fingerprint

POLICY='source_static_first_last'
SCHEMA='source_static_endpoint_certificate/v15'


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def configured(config):
    policy=config.get('keyframe_policy')
    if policy is None:
        if 'source_endpoint_certificate' in config:raise ValueError('endpoint_certificate_requires_explicit_policy')
        return False
    if policy!=POLICY:raise ValueError('unsupported_h3_keyframe_policy')
    binding=config.get('source_endpoint_certificate')
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'}:raise ValueError('source_endpoint_certificate_required')
    return True


def _evidence(source,records):
    if _sha(source['path'])!=source['sha256']:raise ValueError('endpoint_source_changed')
    text=Path(source['path']).read_text(encoding='utf-8')
    if not isinstance(records,list) or not records:raise ValueError('endpoint_action_source_evidence_required')
    for item in records:
        if (not isinstance(item,dict) or set(item)!={'id','start','end','text','sha256'}
            or not isinstance(item['id'],str) or not item['id'].strip()
            or type(item['start']) is not int or type(item['end']) is not int
            or not 0<=item['start']<item['end']<=len(text) or text[item['start']:item['end']]!=item['text']
            or hashlib.sha256(item['text'].encode('utf-8')).hexdigest()!=item['sha256']):
            raise ValueError('endpoint_action_quote_or_range_changed')


def _authorization(value,shot_id,binding_sha):
    required={'actor','statement','shot_id','binding_sha256','same_start_end_pose','same_start_end_camera',
        'same_start_end_location','full_native_video_required'}
    if (not isinstance(value,dict) or set(value)!=required or value.get('shot_id')!=shot_id
        or value.get('binding_sha256')!=binding_sha or not isinstance(value.get('actor'),str) or not value['actor'].strip()
        or not isinstance(value.get('statement'),str) or not value['statement'].strip()
        or any(value.get(key) is not True for key in required-{'actor','statement','shot_id','binding_sha256'})):
        raise ValueError('endpoint_requires_explicit_current_shot_static_authorization')


def _expected(asset_run,snapshot,ready,bindings,shot_id,evidence,authorization):
    asset=Path(asset_run).resolve();packet=snapshot['plan']['packet']
    if len(bindings['shots'])!=1 or bindings['shots'][0]['id']!=shot_id:
        raise ValueError('endpoint_certificate_requires_single_explicit_shot_scope')
    shot=bindings['shots'][0];raw=[s for s in packet['shots'] if s['id']==shot_id]
    if len(raw)!=1:raise ValueError('endpoint_original_shot_missing')
    frame=ready['first_frames'][shot_id]
    _evidence(packet['source'],evidence);_authorization(authorization,shot_id,shot['binding_sha256'])
    return dict(schema=SCHEMA,policy=POLICY,asset_run=str(asset),book_id=str(packet['book_id']),source=deepcopy(packet['source']),
        shot_id=shot_id,scene_id=raw[0].get('scene_id'),source_shot_sha256=fingerprint(raw[0]),binding_sha256=shot['binding_sha256'],
        asset_plan=dict(path=str(asset/'PLAN.json'),sha256=_sha(asset/'PLAN.json')),
        ready=dict(path=str(asset/'H3_INPUT_READY.json'),sha256=_sha(asset/'H3_INPUT_READY.json')),
        frame=dict(path=str(Path(frame['path']).resolve()),sha256=frame['sha256'],binding_sha256=frame['binding_sha256']),
        source_action_evidence=deepcopy(evidence),authorization=deepcopy(authorization),
        semantic_equivalence_authority='explicit_operator_decision_not_automatic_motion_inference',
        conditioning=dict(source_same_frame=True,first_endpoint='reviewed_first_frame',last_endpoint='same_reviewed_first_frame',
            output_looping=False,output_static_frame_reuse=False,full_native_video_required=True))


def prepare_certificate(asset_run,output_path,shot_id,*,source_action_evidence,authorization):
    """Write a new explicit certificate after the normal reviewed-ready gate."""
    from . import visual_h3_handoff_v3 as handoff
    asset=Path(asset_run).resolve();output=Path(output_path).resolve()
    if output.is_relative_to(asset):raise ValueError('endpoint_certificate_must_not_write_original_asset_run')
    snapshot,ready,bindings=handoff.validate_ready(asset)
    value=_expected(asset,snapshot,ready,bindings,shot_id,source_action_evidence,authorization)
    output.parent.mkdir(parents=True,exist_ok=True)
    handoff.freeze(output,value)
    return dict(path=str(output),sha256=_sha(output))


def validate_certificate(asset_run,snapshot,ready,bindings,binding,shot):
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'} or _sha(binding['path'])!=binding['sha256']:
        raise ValueError('endpoint_certificate_file_changed')
    value=_read(binding['path'])
    expected=_expected(asset_run,snapshot,ready,bindings,shot['id'],value.get('source_action_evidence'),value.get('authorization'))
    if value!=expected or value['binding_sha256']!=shot['binding_sha256']:
        raise ValueError('endpoint_certificate_source_frame_or_authority_changed')
    return dict(schema=SCHEMA,policy=POLICY,certificate=deepcopy(binding),certificate_sha256=fingerprint(value),
        source_same_frame_conditioning=True,first_frame_sha256=value['frame']['sha256'],last_frame_sha256=value['frame']['sha256'],
        binding_sha256=shot['binding_sha256'],source_shot_sha256=value['source_shot_sha256'])
