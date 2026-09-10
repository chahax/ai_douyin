"""Bounded edits to existing production v2 text; no story or media generation."""
from __future__ import annotations

import copy
import json
import re

from .script_screenplay import PRODUCTION_SCHEMA_V2, _fields, _text, compile_screenplay

SCENE_FIELDS = {'composition', 'lighting', 'shot_size', 'camera_angle', 'camera_movement'}
SHOT_FIELDS = {'composition', 'emotion_and_performance', 'shot_size', 'camera_angle', 'camera_movement'}
INTERPRETATION_FIELDS = {'presentation_mode', 'account_fit', 'source_pattern_rationale', 'protagonist'}


def parse_unique_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key: ' + key)
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def _location(production, pointer):
    if not isinstance(pointer, str):
        raise ValueError('production revise_field: canonical pointer required')
    parts = pointer.split('/')
    try:
        if len(parts) == 3 and parts[0] == '' and parts[1] in ('scene_design', 'interpretation'):
            allowed = SCENE_FIELDS if parts[1] == 'scene_design' else INTERPRETATION_FIELDS
            if parts[2] not in allowed:
                raise ValueError('production revise_field: frozen field')
            parent, key = production[parts[1]], parts[2]
        elif (len(parts) == 4 and parts[:2] == ['', 'shots']
                and re.fullmatch(r'0|[1-9][0-9]*', parts[2]) and parts[3] in SHOT_FIELDS):
            parent, key = production['shots'][int(parts[2])], parts[3]
        else:
            raise ValueError('production revise_field: forbidden or noncanonical pointer')
        if not isinstance(parent, dict) or key not in parent or not isinstance(parent[key], str):
            raise ValueError('production revise_field: existing string leaf required')
        return parent, key
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('production revise_field: pointer does not exist') from exc


def validate_production_revision_fields(production, fields):
    if not isinstance(production, dict) or production.get('schema') != PRODUCTION_SCHEMA_V2:
        raise ValueError('production revision requires screenplay_production/v2')
    if (not isinstance(fields, (list, tuple)) or not fields
            or any(not isinstance(field, str) for field in fields) or len(set(fields)) != len(fields)):
        raise ValueError('production revise_field: nonempty unique pointer list required')
    for pointer in fields:
        _location(production, pointer)
    return tuple(fields)


def apply_production_revision(story, production, replacements, fields, kind):
    compile_screenplay(story, production, kind)
    fields = validate_production_revision_fields(production, fields)
    _fields(replacements, set(fields), 'production revision')
    for pointer, value in replacements.items():
        _text(value, 'production revision ' + pointer)
    result = copy.deepcopy(production)
    for pointer in fields:
        parent, key = _location(result, pointer)
        parent[key] = replacements[pointer]
    compile_screenplay(story, result, kind)
    return result
