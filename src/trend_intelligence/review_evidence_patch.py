"""Model-authored replacements for existing review quotes, never review decisions."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

PATCH_SCHEMA = 'script_review_evidence_patch/v1'
TRACE_SCHEMA = 'script_review_attempt_chain/v1'
PATCH_PROMPT_PATH = Path(__file__).with_name('prompts') / 'script_pair_review_evidence_patch.md'


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def trace_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


class FullReviewRequired(ValueError):
    """The model says a truthful quote requires reassessing a frozen finding."""


def _leaf(report, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('review evidence patch requires a canonical JSON pointer')
    keys = pointer[1:].split('/')
    # These paths only address machine-defined audit fields and actual shot IDs.
    # No general JSON-pointer editing of findings, issues or decisions is exposed.
    allowed = (len(keys) == 4 and keys[0] == 'shot_audit' and keys[2] == 'cross_field_evidence') or (
        keys[0] == 'character_audit' and ((len(keys) == 3 and keys[2] in ('performance_arc_quote', 'voice_quote'))
        or (len(keys) == 4 and keys[2] in ('dialogue_quotes', 'performance_quotes'))))
    if not allowed or not keys[1].isdigit() or str(int(keys[1])) != keys[1] or any('~' in k for k in keys):
        raise ValueError('review evidence patch cannot edit this field')
    try:
        parent = report
        for key in keys[:-1]:
            parent = parent[int(key)] if isinstance(parent, list) else parent[key]
        if not isinstance(parent, dict) or not isinstance(parent[keys[-1]], str):
            raise ValueError('review evidence patch requires an existing string leaf')
        return parent, keys[-1]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('review evidence patch path does not exist') from exc


def build_evidence_patch_messages(parent_report, payload, targets):
    paths = [target['path'] for target in targets]
    if not paths or len(paths) != len(set(paths)):
        raise ValueError('review evidence patch requires unique allowed paths')
    for path in paths:
        _leaf(parent_report, path)
    request = {'schema': PATCH_SCHEMA, 'candidate_sha256': payload['candidate_sha256'],
        'evidence_sha256': payload['evidence_sha256'], 'review_payload_sha256': canonical_sha(payload),
        'parent_report_sha256': canonical_sha(parent_report), 'allowed_paths': paths,
        'evidence_targets': copy.deepcopy(targets), 'parent_report': copy.deepcopy(parent_report)}
    return [{'role': 'system', 'content': PATCH_PROMPT_PATH.read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}]


def apply_evidence_patch(parent_report, patch, targets):
    if isinstance(patch, dict) and set(patch) == {'full_review_required'}:
        reason = patch['full_review_required']
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('full_review_required needs a nonempty reason')
        raise FullReviewRequired(reason)
    allowed = [target['path'] for target in targets]
    if (not allowed or len(allowed) != len(set(allowed)) or not isinstance(patch, dict)
            or set(patch) != set(allowed)):
        raise ValueError('review evidence patch keys must exactly equal allowed_paths')
    result = copy.deepcopy(parent_report)
    for target in targets:
        path, replacement = target['path'], patch[target['path']]
        if (not isinstance(replacement, str) or (not replacement.strip()
                and not (target.get('empty_allowed') is True and target['source_text'] == replacement == ''))):
            raise ValueError('review evidence patch values must be complete quote strings')
        parent, key = _leaf(result, path)
        parent[key] = replacement
    return result
