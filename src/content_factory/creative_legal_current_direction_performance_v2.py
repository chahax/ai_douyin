"""Beat-owned direction wire; shot identifiers and source ownership compile locally.
Every model-returned creative value is preserved. No old source or receipt is
rewritten, and no invalid model mapping is repaired by this wrapper.
"""
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_current_direction_performance_v1 as base

VERSION = 'legal_current_direction_assignment/v2'
CURRENT_SOURCE_CONFIG = base.CURRENT_SOURCE_CONFIG
catalog, own_refs, digest = base.catalog, base.own_refs, base.digest
evidence_catalog = base.evidence_catalog
obj, text, arr = base.obj, base.text, base.arr
CHARACTERS = base.CHARACTERS
key, spoken_seconds, state_schema = base.key, base.spoken_seconds, base.state_schema
performance_schema = base.performance_schema
expand_performance = base.expand_performance
compile_prefix = base.compile_prefix
compile_complete = base.compile_complete
validate_direction = base.validate_direction
CREATIVE_SHOT_FIELDS = ('new_information', 'observation_target', 'framing',
                        'stimulus_and_response', 'cut_reason')
GLOBAL_FIELDS = ('emotional_arc', 'causal_chain', 'ending_intent', 'spatial_design', 'assets')


def direction_schema(script, config=CURRENT_SOURCE_CONFIG):
    previous = base.direction_schema(script, config)
    props = {name: deepcopy(previous['properties'][name]) for name in GLOBAL_FIELDS}
    for beat in script['beats']:
        beat_id = beat['id']
        window = obj({
            'source_ref': {'enum': own_refs(script, beat_id)},
            'phase': {'enum': ['before', 'during', 'after']},
            'observer': {'enum': CHARACTERS},
            'minimum_seconds': {'type': 'number', 'minimum': .5, 'maximum': 6},
            'purpose': text()})
        creative = {name: text() for name in CREATIVE_SHOT_FIELDS}
        creative['reaction_windows'] = arr(window, 1, 3)
        props[beat_id] = obj(creative)
    return obj(props)


def expand_direction(raw, script, config=CURRENT_SOURCE_CONFIG):
    Draft202012Validator(direction_schema(script, config)).validate(raw)
    result = {name: deepcopy(raw[name]) for name in GLOBAL_FIELDS}
    result.update(initial_state=deepcopy(config['INITIAL']), shots=[], reaction_windows=[])
    for index, beat in enumerate(script['beats'], 1):
        beat_id = beat['id']
        creative = raw[beat_id]
        result['shots'].append({
            'shot_id': f'SH{index:02}', 'beat_id': beat_id,
            'source_refs': own_refs(script, beat_id),
            **{name: deepcopy(creative[name]) for name in CREATIVE_SHOT_FIELDS}})
        result['reaction_windows'].extend(deepcopy(creative['reaction_windows']))
    base.validate_direction(result, script, config)
    return result
