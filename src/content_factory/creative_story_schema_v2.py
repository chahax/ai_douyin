"""Story tool schema exposes every local speaker constraint before dispatch."""
from copy import deepcopy
from jsonschema import Draft202012Validator
from scripts.run_creative_emotion_revision_v1 import script_schema


def complete_story_schema(previous):
    known = sorted({s['speaker'] for b in previous['beats'] for s in b['steps'] if s['kind'] == 'dialogue'})
    if not known:
        raise ValueError('source dialogue speakers required')
    schema = deepcopy(script_schema(previous))
    step = schema['properties']['beats']['items']['properties']['steps']['items']
    step['properties']['speaker']['description'] = 'action必须为空字符串；dialogue必须是指定人物姓名。动作主体写在text中。'
    step['allOf'] = [
        {'if': {'properties': {'kind': {'const': 'action'}}},
         'then': {'properties': {'speaker': {'const': ''}}}},
        {'if': {'properties': {'kind': {'const': 'dialogue'}}},
         'then': {'properties': {'speaker': {'enum': known}}}}]
    return schema


def validate_complete_story(value, previous):
    Draft202012Validator(complete_story_schema(previous)).validate(value)
    ids = [b['id'] for b in value['beats']]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate beat identity')
    return {'complete_model_authored_revision': True, 'manual_content_patch': False,
            'creative_quality_passed': False, 'beat_count': len(ids),
            'speaker_constraints_present_in_request_schema': True}
