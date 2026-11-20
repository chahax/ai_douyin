"""Exact story text/initial-person leaf patches; all unselected fields stay intact."""
from __future__ import annotations

import copy

from .script_drama import _companion, _revision_location, _state_revision_location
from .script_screenplay import _fields, _text, validate_screenplay


def _story_revision_location(screenplay, pointer):
    if isinstance(pointer, str) and pointer.startswith('/version/initial_state/people/'):
        return _state_revision_location(screenplay, pointer)
    return _revision_location(screenplay, pointer)


def validate_story_revision_fields(screenplay, fields):
    """Explicit existing initial-person leaves only; no props/end states/drama change."""
    if (not isinstance(fields, (list, tuple)) or not fields
            or any(not isinstance(field, str) for field in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError('revise_field: a nonempty unique list of pointers is required')
    for pointer in fields:
        _story_revision_location(screenplay, pointer)
    return tuple(fields)


def apply_story_revision(screenplay, replacements, fields, kind, duration, source_evidence,
                         reference_source_ids=(), companion=None):
    validate_screenplay(screenplay, kind, duration, source_evidence, reference_source_ids)
    _companion(screenplay, kind, companion, source_evidence)
    fields = validate_story_revision_fields(screenplay, fields)
    _fields(replacements, set(fields), 'story revision')
    for pointer, value in replacements.items():
        _text(value, 'story revision ' + pointer)
    result = copy.deepcopy(screenplay)
    for pointer in fields:
        parent, key = _story_revision_location(result, pointer)
        parent[key] = replacements[pointer]
    validate_screenplay(result, kind, duration, source_evidence, reference_source_ids)
    _companion(result, kind, companion, source_evidence)
    return result
