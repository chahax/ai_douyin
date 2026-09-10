"""Optional drama-first validation and lossless state assembly; never approval.

The draft contains no invented placeholder states. State prose is independently
model-authored and must still receive the existing full story review.
"""
from __future__ import annotations

import copy
import math
import re

from .script_screenplay import (
    BEAT_ROLES, REFERENCE_FIELDS, SHOT_FIELDS, VERSION_FIELDS,
    _definitions, _fields, _has_narration, _ids, _state, _text,
    validate_screenplay,
)

SCHEMA = 'script_drama/v1'
REVISION_VERSION_FIELDS = frozenset({'title', 'premise', 'dramatic_question', 'goal',
    'obstacle', 'stakes', 'resolution', 'legal_review_note', 'scene', 'spatial_layout'})


def _references(version, source_evidence, reference_source_ids):
    if not isinstance(source_evidence, list) or not source_evidence:
        raise ValueError('source_evidence: detailed source list required')
    sources = {}
    for source in source_evidence:
        if not isinstance(source, dict):
            raise ValueError('source_evidence: each source must be an object')
        sid = _text(source.get('source_id'), 'source.source_id')
        if sid in sources:
            raise ValueError('source_evidence: duplicate source ID')
        sources[sid] = source
    if not isinstance(reference_source_ids, (list, tuple)):
        raise ValueError('reference_source_ids: list or tuple required')
    selected = _ids(list(reference_source_ids), sources, 'reference_source_ids', allow_empty=True)
    refs = version['reference_usage']
    if not isinstance(refs, list) or not refs:
        raise ValueError('reference_usage: nonempty list required')
    shot_ids = [shot['shot_id'] for shot in version['shots']]
    for ref in refs:
        _fields(ref, REFERENCE_FIELDS, 'reference_usage')
        for key in ('source_id', 'borrowed_expression', 'adaptation'):
            _text(ref[key], 'reference_usage.' + key)
        _ids(ref['shot_ids'], shot_ids, 'reference_usage.shot_ids')
        sid = ref['source_id']
        if sid not in sources or (selected and sid not in selected):
            raise ValueError('reference_usage: source not in the detailed reference selection')
        source = sources[sid]
        analysis = source.get('expression_analysis')
        records = analysis.get('evidence') if isinstance(analysis, dict) else None
        if not isinstance(records, list) or not records:
            raise ValueError('reference_usage: source overview is not original evidence')
        evidence = {}
        for item in records:
            if not isinstance(item, dict):
                raise ValueError('source evidence: each record must be an object')
            eid = _text(item.get('id'), 'source evidence ID')
            if eid in evidence:
                raise ValueError('source evidence: duplicate ID')
            evidence[eid] = item
        _ids(ref['evidence_ids'], evidence, 'reference_usage.evidence_ids')
        media = source.get('media_evidence', {})
        source_duration = media.get('duration_seconds') if isinstance(media, dict) else None
        for eid in ref['evidence_ids']:
            item = evidence[eid]
            start, end = item.get('start_seconds'), item.get('end_seconds')
            if (item.get('channel') not in ('visual', 'asr')
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                    or start < 0 or end < start
                    or (type(source_duration) in (int, float) and end > source_duration + .25)):
                raise ValueError('source evidence: invalid channel or time range')
            _text(item.get('text'), 'source evidence text')


def _companion(data, kind, companion, source_evidence):
    if companion is None:
        return
    other = 'long' if kind == 'short' else 'short'
    validate_screenplay(companion, other, 180 if other == 'long' else 45, source_evidence)
    if (data['core_message'] != companion['core_message']
            or [(c['name'], c['identity']) for c in data['characters']]
            != [(c['name'], c['identity']) for c in companion['characters']]):
        raise ValueError('companion: both versions must preserve common core, names and identities')
    count, other_count = len(data['version']['shots']), len(companion['version']['shots'])
    if (kind == 'long' and count < other_count + 3) or (kind == 'short' and other_count < count + 3):
        raise ValueError('companion: long must contain at least three more shots than short')


def validate_drama(data, kind, duration, source_evidence, reference_source_ids=(), companion=None):
    """Check a stateless drama candidate without creating states or approval."""
    if kind not in ('short', 'long'):
        raise ValueError('kind must be short or long')
    target = 45 if kind == 'short' else 180
    if type(duration) is not int or duration != target:
        raise ValueError(f'{kind}: duration must be {target} integer seconds')
    _fields(data, {'schema', 'core_message', 'characters', 'version'}, 'drama')
    if data['schema'] != SCHEMA:
        raise ValueError(f'drama.schema must be {SCHEMA}')
    _text(data['core_message'], 'core_message')
    version = data['version']
    _fields(version, VERSION_FIELDS - {'initial_state'}, 'drama.version')
    for key in VERSION_FIELDS - {'props', 'initial_state', 'shots', 'reference_usage'}:
        _text(version[key], 'version.' + key)
    names, _ = _definitions(data['characters'], version['props'])
    low, high, minimum, maximum = (6, 9, 4, 15) if kind == 'short' else (9, 30, 3, 20)
    shots = version['shots']
    if not isinstance(shots, list) or not low <= len(shots) <= high:
        raise ValueError(f'{kind}: shot count must be {low}--{high}')
    beats, seconds, spoken = [], 0, 0
    for index, shot in enumerate(shots, 1):
        label = f'{kind}.S{index:02d}'
        _fields(shot, SHOT_FIELDS - {'end_state'}, label)
        if shot['shot_id'] != f'S{index:02d}':
            raise ValueError(f'{label}: shot IDs must be consecutive')
        length = shot['duration_seconds']
        if type(length) is not int or not minimum <= length <= maximum:
            raise ValueError(f'{label}: duration must be integer {minimum}--{maximum}')
        if shot['beat'] not in BEAT_ROLES:
            raise ValueError(f'{label}: unknown beat')
        beats.append(shot['beat'])
        speaker, dialogue = shot['dialogue_speaker'], shot['dialogue']
        if not isinstance(speaker, str) or not isinstance(dialogue, str):
            raise ValueError(f'{label}: speaker and dialogue must be text')
        if not (speaker == '' and dialogue == '') and (speaker not in names or not dialogue.strip()):
            raise ValueError(f'{label}: use one defined speaker or two empty strings')
        if len(dialogue) > length * 5:
            raise ValueError(f'{label}: dialogue exceeds 5 characters per second')
        _text(shot['action'], label + '.action')
        if _has_narration(shot['action']):
            raise ValueError(f'{label}: narration is forbidden')
        seconds += length
        spoken += len(dialogue)
    groups = [beat for i, beat in enumerate(beats) if i == 0 or beat != beats[i - 1]]
    if tuple(groups) != BEAT_ROLES:
        raise ValueError('beats: six roles must cover shots in contiguous ordered groups')
    if seconds != duration:
        raise ValueError(f'{kind}: total duration must be {duration}')
    if spoken > duration * 4:
        raise ValueError(f'{kind}: total dialogue exceeds 4 characters per second')
    ending = shots[-1]['dialogue']
    if not ending.strip() or ending.rstrip().endswith(('？', '?', '…', '...')) or any(
            word in ending for word in ('未完待续', '下集', '下期', '后续揭晓', '关注看后续')):
        raise ValueError('final dialogue must be a nonempty, closed ending')
    _references(version, source_evidence, reference_source_ids)
    _companion(data, kind, companion, source_evidence)
    return data


def merge_drama_states(drama, states, kind, duration, source_evidence,
                       reference_source_ids=(), companion=None):
    """Only insert complete model state fields; preserve all drama text exactly."""
    validate_drama(drama, kind, duration, source_evidence, reference_source_ids, companion)
    _fields(states, {'initial_state', 'end_states'}, 'state expansion')
    names, props = _definitions(drama['characters'], drama['version']['props'])
    _state(states['initial_state'], names, props, 'initial_state')
    rows = states['end_states']
    shots = drama['version']['shots']
    if not isinstance(rows, list) or len(rows) != len(shots):
        raise ValueError('end_states: exactly one ordered row per drama shot required')
    for shot, row in zip(shots, rows):
        _fields(row, {'shot_id', 'people', 'props'}, 'end_states row')
        if row['shot_id'] != shot['shot_id']:
            raise ValueError('end_states: cannot reorder, rename or duplicate shot IDs')
        _state({key: row[key] for key in ('people', 'props')}, names, props, row['shot_id'])
    result = copy.deepcopy(drama)
    result['schema'] = 'script_screenplay/v1'
    result['version']['initial_state'] = copy.deepcopy(states['initial_state'])
    for shot, row in zip(result['version']['shots'], rows):
        shot['end_state'] = copy.deepcopy({key: row[key] for key in ('people', 'props')})
    validate_screenplay(result, kind, duration, source_evidence, reference_source_ids)
    return result


def _revision_location(drama, pointer):
    """Accept canonical pointers to a small existing text-leaf whitelist only."""
    if not isinstance(pointer, str):
        raise ValueError('revise_field: canonical JSON pointer string required')
    shot = re.fullmatch(r'/version/shots/(0|[1-9][0-9]*)/(dialogue|action|beat)', pointer)
    character = re.fullmatch(r'/characters/(0|[1-9][0-9]*)/performance_arc', pointer)
    summary = re.fullmatch(r'/version/([a-z_]+)', pointer)
    try:
        if shot:
            parent, key = drama['version']['shots'][int(shot[1])], shot[2]
        elif character:
            parent, key = drama['characters'][int(character[1])], 'performance_arc'
        elif summary and summary[1] in REVISION_VERSION_FIELDS:
            parent, key = drama['version'], summary[1]
        else:
            raise ValueError('revise_field: forbidden or noncanonical pointer: ' + pointer)
        if not isinstance(parent, dict) or key not in parent or not isinstance(parent[key], str):
            raise ValueError('revise_field: existing string leaf required: ' + pointer)
        return parent, key
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('revise_field: pointer does not exist: ' + pointer) from exc


def validate_revision_fields(drama, fields):
    if (not isinstance(fields, (list, tuple)) or not fields
            or any(not isinstance(field, str) for field in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError('revise_field: a nonempty unique list of pointers is required')
    for pointer in fields:
        _revision_location(drama, pointer)
    return tuple(fields)


def apply_drama_revision(drama, replacements, fields, kind, duration, source_evidence,
                         reference_source_ids=(), companion=None):
    """Apply only requested text replacements; validate the complete frozen drama."""
    validate_drama(drama, kind, duration, source_evidence, reference_source_ids, companion)
    fields = validate_revision_fields(drama, fields)
    _fields(replacements, set(fields), 'drama revision')
    for pointer, value in replacements.items():
        _text(value, 'drama revision ' + pointer)
    result = copy.deepcopy(drama)
    for pointer in fields:
        parent, key = _revision_location(result, pointer)
        parent[key] = replacements[pointer]
    validate_drama(result, kind, duration, source_evidence, reference_source_ids, companion)
    return result


def _state_revision_location(screenplay, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('state revise_field: canonical JSON pointer required')
    parts = pointer[1:].split('/')
    decoded = [part.replace('~1', '/').replace('~0', '~') for part in parts]
    if '/'.join(part.replace('~', '~0').replace('/', '~1') for part in decoded) != pointer[1:]:
        raise ValueError('state revise_field: noncanonical escape')
    try:
        if len(decoded) == 4 and decoded[:2] == ['version', 'initial_state']:
            state, category, key = screenplay['version']['initial_state'], decoded[2], decoded[3]
        elif (len(decoded) == 6 and decoded[:2] == ['version', 'shots']
                and re.fullmatch(r'0|[1-9][0-9]*', decoded[2]) and decoded[3] == 'end_state'):
            state = screenplay['version']['shots'][int(decoded[2])]['end_state']
            category, key = decoded[4], decoded[5]
        else:
            raise ValueError('state revise_field: only existing state string leaves can change')
        if category not in ('people', 'props') or not isinstance(state[category], dict):
            raise ValueError('state revise_field: only people/props leaves can change')
        parent = state[category]
        if key not in parent or not isinstance(parent[key], str):
            raise ValueError('state revise_field: existing string leaf required')
        return parent, key
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('state revise_field: pointer does not exist') from exc


def validate_state_revision_fields(screenplay, fields):
    if (not isinstance(fields, (list, tuple)) or not fields
            or any(not isinstance(field, str) for field in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError('state revise_field: nonempty unique pointer list required')
    for pointer in fields:
        _state_revision_location(screenplay, pointer)
    return tuple(fields)


def apply_state_revision(screenplay, replacements, fields, kind, duration, source_evidence,
                         reference_source_ids=(), companion=None):
    """Revise complete state prose only, without touching any story field."""
    validate_screenplay(screenplay, kind, duration, source_evidence, reference_source_ids)
    _companion(screenplay, kind, companion, source_evidence)
    fields = validate_state_revision_fields(screenplay, fields)
    _fields(replacements, set(fields), 'state revision')
    for pointer, value in replacements.items():
        _text(value, 'state revision ' + pointer)
    result = copy.deepcopy(screenplay)
    for pointer in fields:
        parent, key = _state_revision_location(result, pointer)
        parent[key] = replacements[pointer]
    validate_screenplay(result, kind, duration, source_evidence, reference_source_ids)
    return result
