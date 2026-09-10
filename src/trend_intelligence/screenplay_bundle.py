"""Load hashed, independently reviewed screenplay stages for final pair review.

Reading a bundle is not publication or final approval. No model calls, media
operations, normalizations, or file writes are performed here.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .script_outline import build_outline_messages
from .script_pair import _reference_source_ids, _source_json
from .script_screenplay import compile_screenplay, validate_screenplay, verify_story_review


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'staged_screenplay_bundle/v1'
BUNDLE_FIELDS = {'schema', 'workflow_request_path', 'workflow_request_sha256',
                 'source_evidence_path', 'source_evidence_sha256', 'reference_source_ids', 'short', 'long'}
VERSION_FIELDS = {f'{kind}_{suffix}' for kind in ('screenplay', 'review', 'production')
                  for suffix in ('path', 'sha256')}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _exact(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f'{label}: invalid fields, expected {sorted(expected)}')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def _read(value, root, expected_sha=None):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError('bundle artifact path must be nonempty')
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if (root / 'data').resolve() not in path.parents:
        raise ValueError('bundle artifacts must resolve inside this project data directory')
    if expected_sha is not None and (not isinstance(expected_sha, str)
                                     or not re.fullmatch(r'[a-f0-9]{64}', expected_sha)):
        raise ValueError('bundle artifact SHA256 must be a lowercase 64-character digest')
    raw = path.read_bytes()
    digest = _sha(raw)
    if expected_sha is not None and digest != expected_sha:
        raise ValueError(f'bundle artifact SHA256 mismatch: {path.name}')
    parsed = json.loads(raw, object_pairs_hook=_unique_object)
    return parsed, raw, {'path': str(path), 'sha256': digest}


def restore_source_input(workflow, full_sources):
    """Apply the saved candidate CLI's full-source identity restoration rules."""
    if (not isinstance(workflow, list) or len(workflow) != 2
            or any(not isinstance(row, dict) for row in workflow)
            or workflow[0].get('role') != 'system' or workflow[1].get('role') != 'user'
            or not isinstance(workflow[1].get('content'), str)):
        raise ValueError('bundle workflow must be an original two-message project request')
    result = copy.deepcopy(workflow)
    payload = json.loads(result[1]['content'], object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or not isinstance(payload.get('source_evidence'), list):
        raise ValueError('bundle workflow must contain source_evidence')
    if not isinstance(full_sources, list) or any(not isinstance(s, dict) for s in full_sources):
        raise ValueError('complete source evidence must be an array of source objects')
    by_id = {}
    for source in full_sources:
        sid = source.get('source_id')
        if not isinstance(sid, str) or not sid.strip() or sid in by_id:
            raise ValueError('complete source evidence IDs are missing or duplicated')
        by_id[sid] = source
    scope = payload.get('script_reference_selection')
    if scope:
        if (not isinstance(scope, dict)
                or scope.get('full_source_evidence_sha256') != _sha(_source_json(full_sources).encode('utf-8'))):
            raise ValueError('complete source evidence is not hash-bound to the original workflow')
    elif {s.get('source_id') for s in payload['source_evidence'] if isinstance(s, dict)} != set(by_id):
        raise ValueError('complete sources do not match the original workflow source collection')
    seen = set()
    for source in payload['source_evidence']:
        if not isinstance(source, dict) or source.get('source_id') in seen:
            raise ValueError('original workflow contains malformed/duplicate source records')
        seen.add(source.get('source_id'))
        original = by_id.get(source.get('source_id'))
        projection = source.get('evidence_projection', {})
        expected = projection.get('full_source_sha256') if isinstance(projection, dict) else None
        if original is None or (_sha(_source_json(original).encode('utf-8')) != expected
                                if expected else source != original):
            raise ValueError('source evidence does not match the original per-source binding')
    payload['source_evidence'] = copy.deepcopy(full_sources)
    result[1]['content'] = json.dumps(payload, ensure_ascii=False)
    return result


def load_screenplay_bundle(path, *, evidence, short_seconds=45, long_seconds=180,
                           reference_source_ids=(), project_root=None):
    """Return ``(compiled_pair, provenance)`` ready for mandatory final review.

    ``evidence.source_evidence`` must be the current full verified cohort, never
    the author projection. All input bytes are read once and SHA-bound. A newer
    source review, changed account positioning, stale story review, or different
    explicit reference selection invalidates this bundle.
    """
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    bundle, _, bundle_identity = _read(path, root)
    _exact(bundle, BUNDLE_FIELDS, 'bundle')
    if bundle['schema'] != SCHEMA:
        raise ValueError(f'bundle schema must be {SCHEMA}')
    if not isinstance(evidence, dict):
        raise ValueError('current evidence must be an object')
    workflow, workflow_raw, workflow_identity = _read(
        bundle['workflow_request_path'], root, bundle['workflow_request_sha256'])
    workflow_path = Path(workflow_identity['path'])
    if ((root / 'data/pre_video_scripts/_runs').resolve() not in workflow_path.parents
            or workflow_path.name != 'request.json'):
        raise ValueError('bundle workflow must be the saved _runs/request.json')
    full_sources, source_raw, source_identity = _read(
        bundle['source_evidence_path'], root, bundle['source_evidence_sha256'])
    restored = restore_source_input(workflow, full_sources)
    original = json.loads(restored[1]['content'])
    if _source_json(full_sources) != _source_json(evidence.get('source_evidence')):
        raise ValueError('bundle sources differ from the current full verified evidence')
    positioning = original.get('account_positioning')
    if (not isinstance(positioning, dict) or not positioning
            or _source_json(positioning) != _source_json(evidence.get('account_positioning'))):
        raise ValueError('bundle account_positioning differs from the current account')
    selected = _reference_source_ids(bundle['reference_source_ids'], full_sources)
    requested = _reference_source_ids(reference_source_ids, full_sources)
    context_scope = evidence.get('script_reference_selection', {})
    if not isinstance(context_scope, dict):
        raise ValueError('current reference selection must be an object')
    context_selected = _reference_source_ids(
        context_scope.get('requested_source_ids', ()), full_sources)
    if selected != requested or selected != context_selected:
        raise ValueError('bundle reference selection differs from the current explicit selection')
    if (short_seconds != 45 or long_seconds != 180
            or original.get('short_seconds') != short_seconds or original.get('long_seconds') != long_seconds
            or evidence.get('short_seconds') != short_seconds or evidence.get('long_seconds') != long_seconds):
        raise ValueError('bundle requires matching 45/180-second original and current requests')
    # Reuse the project gate: >=20 distinct sources with the exact independent
    # review/media identity, even when authoring used two detailed references.
    build_outline_messages(restored, '', reference_source_ids=selected)
    compiled, stories, identities = {}, {}, {}
    for kind, duration in (('short', short_seconds), ('long', long_seconds)):
        item = bundle[kind]
        _exact(item, VERSION_FIELDS, f'bundle.{kind}')
        story, story_raw, story_identity = _read(item['screenplay_path'], root, item['screenplay_sha256'])
        review, _, review_identity = _read(item['review_path'], root, item['review_sha256'])
        production, _, production_identity = _read(item['production_path'], root, item['production_sha256'])
        validate_screenplay(story, kind, duration, full_sources, reference_source_ids=selected)
        verify_story_review(story_raw, review, workflow_sha=_sha(workflow_raw), source_sha=_sha(source_raw))
        compiled[kind] = compile_screenplay(story, production, kind)
        stories[kind] = story
        identities[kind] = {'screenplay': story_identity, 'review': review_identity,
                            'production': production_identity}
    if stories['short']['core_message'] != stories['long']['core_message']:
        raise ValueError('staged versions must preserve the exact shared core_message')
    identity = lambda story: [(c['name'], c['identity']) for c in story['characters']]
    if identity(stories['short']) != identity(stories['long']):
        raise ValueError('staged versions must preserve the same character names and identities')
    if len(compiled['long']['shots']) < len(compiled['short']['shots']) + 3:
        raise ValueError('staged long version must add at least three shots')
    pair = {'core_message': stories['short']['core_message'], **compiled}
    provenance = {
        'schema': 'staged_screenplay_bundle_provenance/v1', 'bundle': bundle_identity,
        'workflow_request': workflow_identity, 'source_evidence': source_identity,
        'reference_source_ids': list(selected), **identities,
        'verified_at': datetime.now(timezone.utc).isoformat(),
        'compiled_pair_sha256': _sha(_source_json(pair).encode('utf-8')),
        'status': 'bindings_verified_pending_final_pair_review',
        'compilation': 'model_story_text_frozen_shared_state_and_production_projection',
        'compiler_sha256': _sha(Path(__file__).with_name('script_screenplay.py').read_bytes()),
        'loader_sha256': _sha(Path(__file__).read_bytes()),
        'model_calls': 0, 'media_generation': False,
        'notice': 'Prior story approval is not final pair approval. No author revisions are allowed in this run.',
    }
    return pair, provenance
