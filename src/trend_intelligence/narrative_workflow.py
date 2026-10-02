"""Evidence-led narrative planning. Structural validation is never media approval."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

STAGES = ('outline', 'script', 'production')
CHECKS = {
    'outline': ('hook', 'information_change', 'causal_consequence', 'character_audience_relation',
                'payoff_aftertaste', 'reference_transfer', 'account_fit'),
    'script': ('event_preservation', 'action_dialogue', 'knowledge_continuity', 'visible_consequence',
               'emotional_delivery', 'ending', 'legal_accuracy', 'filmability'),
    'production': ('story_preservation', 'shot_function', 'identity_props', 'sound_picture',
                   'cut_continuity', 'execution_capabilities'),
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + key)
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def identity(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': digest(path)}


def verify_file(binding):
    if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
        raise ValueError('Exact file identity required')
    path = Path(binding['path'])
    if not path.is_absolute() or digest(path) != binding['sha256']:
        raise ValueError('Bound file changed: ' + str(path))
    return path


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ': nonempty text required')
    return value


def fields(row, expected, label):
    if not isinstance(row, dict) or set(row) != set(expected):
        raise ValueError(label + ': fields must be ' + ', '.join(sorted(expected)))


def seconds(value, label, upper=180):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= upper:
        raise ValueError(label + ': finite positive duration required')
    return value


def ids(rows, key, label):
    if not isinstance(rows, list) or not rows:
        raise ValueError(label + ': nonempty list required')
    values = [text(r.get(key), label) for r in rows]
    if len(set(values)) != len(values):
        raise ValueError(label + ': duplicate identity')
    return set(values)


def validate_reference(reference):
    if reference.get('schema') != 'reference_impact_blueprint/v1':
        raise ValueError('Reviewed reference blueprint required')
    verify_file(reference['source'])
    if reference.get('source_id') != 'local-reference:' + reference['source']['sha256']:
        raise ValueError('Local reference ID must bind its original video hash')
    duration = seconds(reference['duration_seconds'], 'reference duration', 86400)
    evidence = reference['evidence_files']
    for binding in evidence:
        verify_file(binding)
    if not evidence or reference.get('review_status') != 'reviewed_with_limits':
        raise ValueError('Reference needs actual review and retained evidence')
    ids(reference['insights'], 'id', 'insights')
    for row in reference['insights']:
        if not 0 <= row['start'] < row['end'] <= duration:
            raise ValueError('Reference time outside original video')
        for key in ('observed', 'character_expression', 'audience_effect_hypothesis', 'mechanism',
                    'transferable', 'do_not_copy', 'uncertainty'):
            text(row.get(key), key)
    if not isinstance(reference.get('limitations'), list) or not reference['limitations']:
        raise ValueError('Reference limitations must remain explicit')
    return reference


def validate_candidate(candidate, stage, context, parent=None, kind=None):
    """Shape, timing and identity checks; quality requires the separate review."""
    if stage not in STAGES:
        raise ValueError('Unknown narrative stage')
    if kind is not None and (stage != 'script' or kind not in ('short', 'long')):
        raise ValueError('Only script supports a single version')
    kinds = (kind,) if kind else ('short', 'long')
    if stage == 'outline':
        fields(candidate, {'core', 'characters', 'reference_usage', 'short', 'long'}, stage)
        text(candidate['core'], 'core')
        characters = ids(candidate['characters'], 'id', 'characters')
        for role in candidate['characters']:
            fields(role, {'id', 'name', 'wants', 'hidden_or_known', 'stakes'}, 'role')
            for k, v in role.items(): text(v, k)
        allowed = {s['source_id']: {e['id'] for e in s.get('expression_analysis', {}).get('evidence', [])}
                   for s in context['source_evidence']}
        if context['reference']['source_id'] in allowed:
            raise ValueError('Style reference cannot replace a cohort source identity')
        allowed[context['reference']['source_id']] = {r['id'] for r in context['reference']['insights']}
        refs = candidate['reference_usage']
        if not isinstance(refs, list) or not refs:
            raise ValueError('Reference transfer required')
        for ref in refs:
            fields(ref, {'source_id', 'evidence_ids', 'borrowed_mechanism', 'original_change'}, 'reference usage')
            if ref['source_id'] not in allowed or not ref['evidence_ids'] or not set(ref['evidence_ids']) <= allowed[ref['source_id']]:
                raise ValueError('Unknown reference evidence')
            text(ref['borrowed_mechanism'], 'borrowed mechanism');text(ref['original_change'], 'original change')
        for kind in ('short', 'long'):
            v = candidate[kind]
            fields(v, {'title', 'opening_question', 'payoff', 'aftertaste', 'events'}, kind)
            for k in ('title', 'opening_question', 'payoff', 'aftertaste'): text(v[k], k)
            events = v['events'];ids(events, 'event_id', 'events')
            if len(events) < 3: raise ValueError('Need an event chain, not one assertion')
            for e in events:
                fields(e, {'event_id', 'duration_seconds', 'visible_action', 'new_information', 'consequence',
                           'character_emotion', 'audience_effect', 'mechanism'}, 'event')
                seconds(e['duration_seconds'], 'event duration')
                for k in set(e) - {'duration_seconds'}: text(e[k], k)
            if abs(sum(e['duration_seconds'] for e in events) - context[kind + '_seconds']) > .001:
                raise ValueError(kind + ': event duration total differs')
    elif stage == 'script':
        fields(candidate, set(kinds), stage)
        characters = {c['id'] for c in parent['characters']}
        for kind in kinds:
            v = candidate[kind];fields(v, {'event_spine', 'scenes', 'props', 'shots'}, kind)
            if v['event_spine'] != parent[kind]['events']:
                raise ValueError('Approved event spine changed')
            scenes = ids(v['scenes'], 'id', 'scenes')
            if not isinstance(v['props'], list):raise ValueError('props must be a list')
            props = ids(v['props'], 'id', 'props') if v['props'] else set()
            for s in v['scenes']:
                fields(s, {'id', 'location', 'time_context'}, 'scene')
                for k, value in s.items(): text(value, k)
            for prop in v['props']:
                fields(prop, {'id', 'name'}, 'prop');text(prop['name'], 'prop name')
            ids(v['shots'], 'shot_id', 'shots')
            event_ids = [e['event_id'] for e in v['event_spine']]
            totals = dict.fromkeys(event_ids, 0.0);previous = None;seen_events = []
            for shot in v['shots']:
                fields(shot, {'shot_id', 'event_id', 'scene_id', 'duration_seconds', 'participants', 'action',
                              'result', 'state_before', 'state_after', 'dialogue'}, 'shot')
                if shot['event_id'] not in totals or shot['scene_id'] not in scenes:
                    raise ValueError('Unknown event or scene')
                if not seen_events or seen_events[-1] != shot['event_id']: seen_events.append(shot['event_id'])
                d = seconds(shot['duration_seconds'], 'shot duration');totals[shot['event_id']] += d
                if not isinstance(shot['participants'], list) or not set(shot['participants']) <= characters:
                    raise ValueError('Unknown visible character')
                text(shot['action'], 'action');text(shot['result'], 'result')
                for key in ('state_before', 'state_after'):
                    state = shot[key];fields(state, {'characters', 'props'}, 'state')
                    fields(state['characters'], characters, 'character state');fields(state['props'], props, 'prop state')
                    for values in state.values():
                        for value in values.values():text(value, 'state value')
                if previous and previous['scene_id'] == shot['scene_id'] and previous['state_after'] != shot['state_before']:
                    raise ValueError('Same-scene state discontinuity')
                if not isinstance(shot['dialogue'], list):raise ValueError('dialogue must be a timed list')
                cursor = 0
                for line in shot['dialogue']:
                    fields(line, {'speaker', 'text', 'start', 'end', 'delivery'}, 'dialogue')
                    if line['speaker'] not in shot['participants'] or not cursor <= line['start'] < line['end'] <= d:
                        raise ValueError('Offscreen/overlapping/invalid dialogue')
                    text(line['text'], 'spoken text');text(line['delivery'], 'delivery');cursor = line['end']
                    if len(line['text']) > 6 * (line['end'] - line['start']):
                        raise ValueError('Dialogue exceeds practical duration')
                previous = shot
            if seen_events != event_ids or any(abs(totals[e['event_id']] - e['duration_seconds']) > .001 for e in v['event_spine']):
                raise ValueError('Event order/coverage/timing changed')
    else:
        fields(candidate, {'short', 'long'}, stage)
        for kind in ('short', 'long'):
            plans = candidate[kind]
            if not isinstance(plans, list) or [p.get('shot_id') for p in plans] != [s['shot_id'] for s in parent[kind]['shots']]:
                raise ValueError('Photography must cover frozen shots in order')
            for row in plans:
                fields(row, {'shot_id', 'camera', 'lighting', 'performance', 'sound_design', 'cut_reason',
                             'continuity_mode', 'execution_requirement'}, 'photography')
                for k, v in row.items():text(v, k)
                if row['continuity_mode'] not in ('raw_tail_continuation', 'planned_cut_requires_adapter'):
                    raise ValueError('Explicit continuity mode required')
    return candidate


def expand_script_delta(raw, parent, kind):
    """Materialize model-authored changes; never invent actions/dialogue or repair text."""
    from copy import deepcopy
    if kind not in ('short', 'long'):raise ValueError('Delta requires one script version')
    fields(raw, {kind}, 'delta script')
    version = raw[kind]
    fields(version, {'scenes', 'props', 'initial_state', 'shots'}, 'delta version')
    characters = {r['id'] for r in parent['characters']}
    props = {r['id'] for r in version['props']}
    state = deepcopy(version['initial_state'])
    fields(state, {'characters', 'props'}, 'initial state')
    for channel, allowed in [('characters', characters), ('props', props)]:
        fields(state[channel], allowed, 'initial ' + channel)
        for value in state[channel].values():text(value, 'initial state value')
    shots = []
    required = {'shot_id', 'event_id', 'scene_id', 'duration_seconds', 'participants',
                'action', 'result', 'dialogue', 'changes'}
    for raw_shot in version['shots']:
        fields(raw_shot, required, 'delta shot')
        shot = {k: deepcopy(v) for k, v in raw_shot.items() if k != 'changes'}
        shot['state_before'] = deepcopy(state)
        changes = raw_shot['changes']
        fields(changes, {'characters', 'props'}, 'changes')
        for channel, allowed in [('characters', characters), ('props', props)]:
            if not isinstance(changes[channel], dict) or not set(changes[channel]) <= allowed:
                raise ValueError('Unknown delta state identity')
            for key, value in changes[channel].items():
                text(value, 'changed state value');state[channel][key] = value
        shot['state_after'] = deepcopy(state)
        shots.append(shot)
    return {kind: {'event_spine': deepcopy(parent[kind]['events']),
                   'scenes': deepcopy(version['scenes']), 'props': deepcopy(version['props']), 'shots': shots}}


def review_template(stage, candidate_path, workflow_path):
    return {'schema': 'narrative_stage_review/v1', 'stage': stage, 'candidate': identity(candidate_path),
            'workflow': identity(workflow_path), 'decision': 'pending', 'reviewed_at_bjt': None,
            'checks': {key: {'passed': None, 'evidence': [], 'finding': ''} for key in CHECKS[stage]},
            'unresolved': [], 'limitations': []}


def require_review(review, stage, candidate_path, workflow_path):
    if review.get('schema') != 'narrative_stage_review/v1' or review.get('stage') != stage:
        raise ValueError('Wrong independent review scope')
    if review.get('candidate') != identity(candidate_path) or review.get('workflow') != identity(workflow_path):
        raise ValueError('Review binding changed')
    if review.get('decision') != 'passed' or review.get('unresolved'):
        raise ValueError('Actual independent review not passed')
    from datetime import datetime, timedelta
    timestamp = datetime.fromisoformat(review.get('reviewed_at_bjt') or '')
    if timestamp.utcoffset() != timedelta(hours=8):raise ValueError('Review must record Beijing time')
    fields(review.get('checks'), CHECKS[stage], 'review checks')
    for key, row in review['checks'].items():
        if row.get('passed') is not True or not isinstance(row.get('evidence'), list) or not row['evidence']:
            raise ValueError('Unchecked review item: ' + key)
        text(row.get('finding'), 'review finding')
        for evidence in row['evidence']:text(evidence, 'review evidence location')


def media_handoff_report(production):
    return {'status': 'blocked_until_reviewed_execution_adapter', 'automatic_submit': False,
            'reason': 'This workflow authors text; current video runner cannot consume this schema. No silent conversion.',
            'planned_cut_shots': {k: [r['shot_id'] for r in production[k]
                                     if r['continuity_mode'] == 'planned_cut_requires_adapter'] for k in ('short', 'long')},
            'required': ['reviewed full screenplay and production', 'supported execution plan',
                         'per-script campaign registration', 'native previous approved tail',
                         'actual segment audiovisual review', 'final cut and narrative review']}
