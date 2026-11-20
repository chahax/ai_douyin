"""Model-authored acting cues; predeclared local timing, source-bound B1 only.
No existing numeric model response is repaired. The model supplies fifteen
complete cue strings, and each string is preserved verbatim in the performance.
"""
import re
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_current_direction_performance_v1 as performance

VERSION = 'legal_current_acting_cues/v1'
CURRENT_SOURCE_CONFIG = performance.CURRENT_SOURCE_CONFIG
CURRENT_ACTION_SECONDS = {'B1.S01': 1.0, 'B1.S03': 2.0}
TARGET_SPOKEN_CHARACTERS_PER_SECOND = 4.7
DEFAULT_DIALOGUE_AFTER_SECONDS = .5
catalog, own_refs, digest = performance.catalog, performance.own_refs, performance.digest
evidence_catalog = performance.evidence_catalog
obj, text, arr, key = performance.obj, performance.text, performance.arr, performance.key
CHARACTERS = performance.CHARACTERS
PHASES = ('before', 'active', 'after')


def _check_source(script, beat):
    if beat != 'B1':
        raise ValueError('acting cue contract currently supports complete B1 only')
    performance.performance_schema(script, beat)
    for ref in own_refs(script, beat):
        source = catalog(script)[ref]
        if source['kind'] == 'action' and ref not in CURRENT_ACTION_SECONDS:
            raise ValueError('unconfigured original action duration: ' + ref)


def schema(script, beat='B1'):
    _check_source(script, beat)
    return obj({key(ref) + '_' + phase: text()
                for ref in own_refs(script, beat) for phase in PHASES})


def _declared_active_seconds(source, ref):
    if source['kind'] == 'action':
        if ref not in CURRENT_ACTION_SECONDS:
            raise ValueError('unconfigured original action duration: ' + ref)
        return CURRENT_ACTION_SECONDS[ref]
    if source['kind'] != 'dialogue':
        raise ValueError('unsupported original source kind: ' + ref)
    characters = len(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', source['text']))
    # Integer ceiling of chars / 4.7 * 10, avoiding float rounding drift.
    return ((characters * 100 + 46) // 47) / 10


def expand_cues(raw, script, beat, direction):
    Draft202012Validator(schema(script, beat)).validate(raw)
    performance.validate_direction(direction, script)
    sources, wire, timing_rows = catalog(script), {}, []
    for ref in own_refs(script, beat):
        minimums = {'before': 0, 'during': 0, 'after': 0}
        for window in direction['reaction_windows']:
            if window['source_ref'] == ref:
                minimums[window['phase']] = max(minimums[window['phase']], window['minimum_seconds'])
        active = max(_declared_active_seconds(sources[ref], ref), minimums['during'])
        after_default = DEFAULT_DIALOGUE_AFTER_SECONDS if sources[ref]['kind'] == 'dialogue' else 0
        row = {
            'before_seconds': minimums['before'],
            'before_performance': raw[key(ref) + '_before'],
            'active_seconds': active,
            'active_performance': raw[key(ref) + '_active'],
            'after_seconds': max(minimums['after'], after_default),
            'after_performance': raw[key(ref) + '_after']}
        wire[key(ref)] = row
        timing_rows.append({'source_ref': ref, 'before_seconds': row['before_seconds'],
                            'active_seconds': row['active_seconds'], 'after_seconds': row['after_seconds'],
                            'declared_active_seconds': _declared_active_seconds(sources[ref], ref),
                            'director_minimum_seconds': minimums})
    result = performance.expand_performance(wire, script, beat)
    compiled = performance.compile_prefix(script, direction, [result])
    preserved = all(row[phase + '_performance'] == raw[key(row['source_ref']) + '_' + phase]
                    for row in result['rows'] for phase in PHASES)
    if not preserved:
        raise ValueError('original acting cue identity compilation failed')
    result['cue_compilation'] = {
        'schema': VERSION, 'source_cues_sha256': digest(raw),
        'script_sha256': digest(script), 'direction_sha256': digest(direction),
        'predeclared_action_seconds': deepcopy(CURRENT_ACTION_SECONDS),
        'target_spoken_characters_per_second': TARGET_SPOKEN_CHARACTERS_PER_SECOND,
        'dialogue_hard_max_characters_per_second': 5,
        'default_dialogue_after_seconds': DEFAULT_DIALOGUE_AFTER_SECONDS,
        'timing_rows': timing_rows, 'all_original_cues_preserved': preserved,
        'numeric_model_response_repaired': False, 'prior_response_spliced': False,
        'complete_beat': beat, 'source_steps': len(result['rows']),
        'prefix_total_duration_seconds': compiled['total_duration_seconds'],
        'whole_film_performance_complete': False, 'actual_media_readability': None,
        'creative_quality_passed': False}
    return result
