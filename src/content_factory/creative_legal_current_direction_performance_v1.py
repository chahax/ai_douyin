"""Source-bound direction and acting contracts with locally derived physical state.
The model assigns shots and supplies only acting/timing. Source text and physical
transitions are never repaired or supplied by this module.
"""
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_short_director_performance_v1 as base

VERSION = 'legal_current_direction_performance/v1'
catalog, own_refs, digest = base.catalog, base.own_refs, base.digest
evidence_catalog = base.evidence_catalog
obj, text, arr = base.obj, base.text, base.arr
CHARACTERS = base.CHARACTERS
CURRENT_SOURCE_CONFIG = {
    'SOURCE_SHA': 'c8d00326ae50379eb7fa978d65d7e2b4c06b6ff786aadc1704aa74226ab1a1ac',
    'INITIAL': {
        'badge_location': 'xiaolin_neck', 'paper_location': 'zhou_table_side',
        'paper_facing': 'face_up', 'paper_signed': 'unsigned',
        'pen_location': 'zhou_table_side', 'folder_location': 'zhou_table_side',
        'zhou_position': 'seated_opposite', 'xiaolin_position': 'seated'},
    'STATE_VALUES': {
        'badge_location': ['xiaolin_neck'],
        'paper_location': ['zhou_table_side', 'xiaolin_near_edge', 'zhou_folder'],
        'paper_facing': ['face_up', 'inside_folder'], 'paper_signed': ['unsigned'],
        'pen_location': ['zhou_table_side', 'xiaolin_near_edge', 'zhou_folder'],
        'folder_location': ['zhou_table_side', 'zhou_carried'],
        'zhou_position': ['seated_opposite', 'walking_to_door', 'outside_room'],
        'xiaolin_position': ['seated']},
    'TRANSITIONS': {
        'B1.S03': {'paper_location': ['zhou_table_side', 'xiaolin_near_edge'],
                    'pen_location': ['zhou_table_side', 'xiaolin_near_edge']},
        'B4.S03': {'paper_location': ['xiaolin_near_edge', 'zhou_folder'],
                    'paper_facing': ['face_up', 'inside_folder'],
                    'pen_location': ['xiaolin_near_edge', 'zhou_folder']},
        'B4.S05': {'folder_location': ['zhou_table_side', 'zhou_carried'],
                    'zhou_position': ['seated_opposite', 'walking_to_door']},
        'B4.S06': {'zhou_position': ['walking_to_door', 'outside_room']}}}


def key(ref):
    return ref.replace('.', '_')


def _assert_state(state, config):
    if set(state) != set(config['STATE_VALUES']) or any(
            state[k] not in config['STATE_VALUES'][k] for k in state):
        raise ValueError('state fields or values outside source configuration')
    if 'paper_location' in state and 'paper_facing' in state:
        if (state['paper_location'] == 'zhou_folder') != (state['paper_facing'] == 'inside_folder'):
            raise ValueError('paper face/location inconsistency')


def _assert_config(script, config):
    if digest(script) != config['SOURCE_SHA']:
        raise ValueError('state compiler belongs to exact reviewed source; rederive for changed source')
    states, initial, sources = config['STATE_VALUES'], config['INITIAL'], catalog(script)
    if set(initial) != set(states) or any(initial[k] not in states[k] for k in states):
        raise ValueError('invalid initial source state configuration')
    if set(config['TRANSITIONS']) - set(sources):
        raise ValueError('transition configuration refers to absent source')
    current = deepcopy(initial)
    for ref, source in sources.items():
        changes = config['TRANSITIONS'].get(ref, {})
        if changes and source['kind'] != 'action':
            raise ValueError('state transition must belong to an original action source')
        for field, pair in changes.items():
            if (field not in states or len(pair) != 2 or pair[0] == pair[1]
                    or pair[0] != current[field] or pair[1] not in states[field]):
                raise ValueError('invalid source-derived state transition: ' + ref)
            current[field] = pair[1]
        _assert_state(current, config)


def state_schema(config=CURRENT_SOURCE_CONFIG):
    return obj({k: {'enum': v} for k, v in config['STATE_VALUES'].items()})


def _direction_schema(script, config, wire):
    _assert_config(script, config)
    schema = deepcopy(base.direction_schema(script))
    schema['properties']['initial_state'] = obj({k: {'const': v} for k, v in config['INITIAL'].items()})
    if wire:
        shot = schema['properties']['shots']['items']
        del shot['properties']['source_refs']
        shot['required'].remove('source_refs')
        schema['properties']['source_assignments'] = obj({key(ref): text() for ref in catalog(script)})
        schema['required'].append('source_assignments')
    return schema


def direction_schema(script, config=CURRENT_SOURCE_CONFIG):
    return _direction_schema(script, config, True)


def validate_direction(direction, script, config=CURRENT_SOURCE_CONFIG):
    Draft202012Validator(_direction_schema(script, config, False)).validate(direction)
    sources, covered, ids = catalog(script), [], []
    for shot in direction['shots']:
        ids.append(shot['shot_id'])
        covered.extend(shot['source_refs'])
        if any(r not in own_refs(script, shot['beat_id']) for r in shot['source_refs']):
            raise ValueError('shot crosses beat ownership')
    if covered != list(sources) or len(ids) != len(set(ids)):
        raise ValueError('all original source steps must occur once, in order')
    windows = direction['reaction_windows']
    pairs = [(w['source_ref'], w['phase'], w['observer']) for w in windows]
    if len(pairs) != len(set(pairs)):
        raise ValueError('duplicate reaction window')
    if {w['source_ref'].split('.')[0] for w in windows} != {b['id'] for b in script['beats']}:
        raise ValueError('each beat needs a purposeful reaction requirement')
    return {'source_steps': len(sources), 'shots': len(ids),
            'initial_prerequisites_valid': True, 'creative_quality_passed': False}


def expand_direction(raw, script, config=CURRENT_SOURCE_CONFIG):
    Draft202012Validator(direction_schema(script, config)).validate(raw)
    result = deepcopy(raw)
    assignments = result.pop('source_assignments')
    ids = [s['shot_id'] for s in result['shots']]
    if len(set(ids)) != len(ids) or set(assignments.values()) != set(ids):
        raise ValueError('unknown/orphan/duplicate shot assignment')
    for shot in result['shots']:
        shot['source_refs'] = [r for r in catalog(script) if assignments[key(r)] == shot['shot_id']]
    validate_direction(result, script, config)
    return result


def spoken_seconds(source):
    return len(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', source['text'])) / 5


def performance_schema(script, beat, config=CURRENT_SOURCE_CONFIG):
    _assert_config(script, config)
    if beat not in [b['id'] for b in script['beats']]:
        raise ValueError('unknown beat')
    props, sources = {}, catalog(script)
    for ref in own_refs(script, beat):
        active = {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 15}
        if sources[ref]['kind'] == 'dialogue':
            active['minimum'] = spoken_seconds(sources[ref])
        props[key(ref)] = obj({
            'before_seconds': {'type': 'number', 'minimum': 0, 'maximum': 3},
            'before_performance': text(), 'active_seconds': active,
            'active_performance': text(),
            'after_seconds': {'type': 'number', 'minimum': 0, 'maximum': 3},
            'after_performance': text()})
    return obj(props)


def _changes(ref, config):
    return [{'field': field, 'from': pair[0], 'to': pair[1]}
            for field, pair in config['TRANSITIONS'].get(ref, {}).items()]


def _apply(state, ref, changes, config):
    if changes != _changes(ref, config):
        raise ValueError('state changes must equal current source-derived transitions: ' + ref)
    for change in changes:
        if state[change['field']] != change['from']:
            raise ValueError('impossible state precondition: ' + ref)
        state[change['field']] = change['to']
    _assert_state(state, config)
    return state


def expand_performance(raw, script, beat, config=CURRENT_SOURCE_CONFIG):
    Draft202012Validator(performance_schema(script, beat, config)).validate(raw)
    state = deepcopy(config['INITIAL'])
    for ref in catalog(script):
        if ref.startswith(beat + '.'):
            break
        _apply(state, ref, _changes(ref, config), config)
    result = {'beat_id': beat, 'start_state': deepcopy(state), 'rows': []}
    for ref in own_refs(script, beat):
        row = {'source_ref': ref, **deepcopy(raw[key(ref)]), 'state_changes': _changes(ref, config)}
        _apply(state, ref, row['state_changes'], config)
        result['rows'].append(row)
    result['end_state'] = deepcopy(state)
    return result


def compile_prefix(script, direction, performances, config=CURRENT_SOURCE_CONFIG):
    validate_direction(direction, script, config)
    expected = [b['id'] for b in script['beats']][:len(performances)]
    if [p['beat_id'] for p in performances] != expected:
        raise ValueError('beat order/duplicate invalid')
    state, clock, out, checks = deepcopy(config['INITIAL']), 0.0, [], []
    sources = catalog(script)
    shotfor = {r: shot for shot in direction['shots'] for r in shot['source_refs']}
    for performance in performances:
        beat = performance['beat_id']
        if performance['start_state'] != state:
            raise ValueError('cross-beat state mismatch')
        if [r['source_ref'] for r in performance['rows']] != own_refs(script, beat):
            raise ValueError('all original performance source steps must occur once, in order')
        wire = {key(r['source_ref']): {k: deepcopy(r[k]) for k in
                ('before_seconds', 'before_performance', 'active_seconds', 'active_performance',
                 'after_seconds', 'after_performance')} for r in performance['rows']}
        Draft202012Validator(performance_schema(script, beat, config)).validate(wire)
        for row in performance['rows']:
            ref, start = row['source_ref'], deepcopy(state)
            source = sources[ref]
            if source['kind'] == 'dialogue' and row['active_seconds'] + 1e-9 < spoken_seconds(source):
                raise ValueError('dialogue compressed above five spoken characters/second: ' + ref)
            duration = row['before_seconds'] + row['active_seconds'] + row['after_seconds']
            if duration > 15 + 1e-9:
                raise ValueError('single source step exceeds 15 seconds: ' + ref)
            for window in direction['reaction_windows']:
                if window['source_ref'] == ref:
                    field = {'before': 'before_seconds', 'during': 'active_seconds', 'after': 'after_seconds'}[window['phase']]
                    if row[field] + 1e-9 < window['minimum_seconds']:
                        raise ValueError('reaction window too short: ' + ref + ' ' + window['phase'])
                    checks.append({'source_ref': ref, 'phase': window['phase'], 'observer': window['observer'],
                                   'minimum_seconds': window['minimum_seconds'], 'actual_seconds': row[field],
                                   'mechanical_status': 'satisfied', 'actual_media_readability': None})
            _apply(state, ref, row['state_changes'], config)
            active_start = clock + row['before_seconds']
            active_end = active_start + row['active_seconds']
            end = active_end + row['after_seconds']
            out.append({'source_ref': ref, 'shot_id': shotfor[ref]['shot_id'], 'beat_id': beat,
                        'source_kind': source['kind'], 'speaker': source['speaker'], 'original_text': source['text'],
                        'start': round(clock, 6), 'active_start': round(active_start, 6),
                        'active_end': round(active_end, 6), 'end': round(end, 6),
                        'before_performance': row['before_performance'], 'active_performance': row['active_performance'],
                        'after_performance': row['after_performance'], 'start_state': start,
                        'end_state': deepcopy(state), 'original_performance_row_sha256': digest(row)})
            clock = end
        if performance['end_state'] != state:
            raise ValueError('end state must equal compiled transitions')
    if clock > 180:
        raise ValueError('current film exceeds 180 seconds; revise complete performance')
    shots = []
    for shot in direction['shots']:
        found = [r for r in out if r['shot_id'] == shot['shot_id']]
        if found:
            shots.append({**deepcopy(shot), 'start': found[0]['start'], 'end': found[-1]['end'],
                          'duration': round(found[-1]['end'] - found[0]['start'], 6)})
    return {'schema': VERSION, 'script_sha256': digest(script), 'source_config_sha256': digest(config),
            'direction_sha256': digest(direction), 'performance_sha256s': [digest(p) for p in performances],
            'complete': len(performances) == len(script['beats']), 'total_duration_seconds': round(clock, 6),
            'shots': shots, 'schedule': out, 'reaction_window_checks': checks, 'final_state': state,
            'real_audio_or_video_verified': False, 'creative_quality_passed': False,
            'physical_scope': 'source-derived coarse state only; actual acting, frame continuity and audio await human review'}


def compile_complete(script, direction, performances, config=CURRENT_SOURCE_CONFIG):
    result = compile_prefix(script, direction, performances, config)
    if not result['complete'] or len(result['schedule']) != len(catalog(script)):
        raise ValueError('complete performance required')
    return result
