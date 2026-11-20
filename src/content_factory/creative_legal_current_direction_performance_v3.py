"""Beat-owned direction with up to six local reaction windows, twelve globally.
The only change from v2 is a local cardinality bound. Source text, returned
creative values, prior responses and old validation results remain unchanged.
"""
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_current_direction_performance_v2 as previous

VERSION = 'legal_current_direction_assignment/v3'
CURRENT_SOURCE_CONFIG = previous.CURRENT_SOURCE_CONFIG
catalog, own_refs, digest = previous.catalog, previous.own_refs, previous.digest
evidence_catalog = previous.evidence_catalog
obj, text, arr = previous.obj, previous.text, previous.arr
CHARACTERS = previous.CHARACTERS
key, spoken_seconds, state_schema = previous.key, previous.spoken_seconds, previous.state_schema
performance_schema = previous.performance_schema
expand_performance = previous.expand_performance
compile_prefix = previous.compile_prefix
compile_complete = previous.compile_complete
validate_direction = previous.validate_direction
CREATIVE_SHOT_FIELDS = previous.CREATIVE_SHOT_FIELDS
GLOBAL_FIELDS = previous.GLOBAL_FIELDS


def direction_schema(script, config=CURRENT_SOURCE_CONFIG):
    schema = previous.direction_schema(script, config)
    for beat in script['beats']:
        schema['properties'][beat['id']]['properties']['reaction_windows']['maxItems'] = 6
    return schema


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
    previous.validate_direction(result, script, config)
    return result
