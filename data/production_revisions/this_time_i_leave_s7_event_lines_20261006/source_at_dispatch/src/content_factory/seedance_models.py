"""Versioned Seedance capabilities from the project's archived official guides."""
from __future__ import annotations

import json
from pathlib import Path
from collections import Counter

CATALOG = Path(__file__).resolve().parents[2]/'config/seedance_models.json'
TASK_TYPES = {'auto','text','reference','first_frame','first_last_frame','edit','extend'}


def load_catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def ark_model(model_id):
    for model in load_catalog()['ark_models']:
        if model['id']==model_id:return model
    raise ValueError(f'Unknown Ark model {model_id}; register its documented limits before calling it')


def validate_ark_request(model_id, duration, resolution, ratio, references, task_type='auto', output_format=None):
    model=ark_model(model_id)
    if type(duration) is not int or not (model['duration_min']<=duration<=model['duration_max'] or duration==-1):
        raise ValueError(f"{model_id} duration must be an integer between 4 and {model['duration_max']} seconds, or -1")
    if resolution not in model['resolutions']:
        raise ValueError(f"{model['name']} supports resolutions {model['resolutions']}")
    if output_format and output_format not in model['output_formats']:
        raise ValueError(f"{model['name']} supports output formats {model['output_formats']}")
    if task_type not in TASK_TYPES:raise ValueError('Unsupported Seedance task type')
    counts=Counter(r.kind for r in references)
    limits=model['reference_limits']
    if len(references)>limits['total'] or any(counts[k]>limits[k] for k in ('image','video','audio')):
        raise ValueError('Reference count exceeds the selected model limits')
    if counts['audio'] and not (counts['image'] or counts['video']) and not model['audio_only_reference']:
        raise ValueError('Seedance 2.0 audio references must be combined with images or video')
    roles=Counter(r.role for r in references)
    framed=roles['first_frame'] or roles['last_frame']
    if framed:
        if roles['first_frame']!=1 or roles['last_frame']>1 or len(references)!=1+roles['last_frame']:
            raise ValueError('Frame generation needs exactly one first frame, optionally one last frame, without mixed references')
        inferred='first_last_frame' if roles['last_frame'] else 'first_frame'
    else:
        inferred='reference' if references else 'text'
    task=inferred if task_type=='auto' else task_type
    if task in {'text','reference','first_frame','first_last_frame'} and task!=inferred:
        raise ValueError('Selected task type does not match the input material roles')
    if task in {'edit','extend'} and (not counts['video'] or framed):
        raise ValueError('Video edit/extend requires a reference_video')
    if model['family']=='2.5':
        if task in {'edit','extend','first_frame','first_last_frame'} and ratio!='adaptive':
            raise ValueError('Seedance 2.5 edit/extend/frame generation requires ratio=adaptive')
        if task=='edit' and duration!=-1:
            raise ValueError('Seedance 2.5 edit requires duration=-1')
    extras={}
    if model['family']=='2.5':
        if task in {'edit','extend'}:extras['omni_reference_task_type']=task
        if output_format:extras['output_format']=output_format
    return extras
