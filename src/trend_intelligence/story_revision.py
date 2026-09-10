"""Exact text-leaf story patches; frozen states and unselected text stay intact."""
from __future__ import annotations

import copy

from .script_drama import _companion, _revision_location, validate_revision_fields
from .script_screenplay import _fields, _text, validate_screenplay


def apply_story_revision(screenplay, replacements, fields, kind, duration, source_evidence,
                         reference_source_ids=(), companion=None):
    validate_screenplay(screenplay, kind, duration, source_evidence, reference_source_ids)
    _companion(screenplay, kind, companion, source_evidence)
    fields = validate_revision_fields(screenplay, fields)
    _fields(replacements, set(fields), 'story revision')
    for pointer, value in replacements.items():
        _text(value, 'story revision ' + pointer)
    result = copy.deepcopy(screenplay)
    for pointer in fields:
        parent, key = _revision_location(result, pointer)
        parent[key] = replacements[pointer]
    validate_screenplay(result, kind, duration, source_evidence, reference_source_ids)
    _companion(result, kind, companion, source_evidence)
    return result
