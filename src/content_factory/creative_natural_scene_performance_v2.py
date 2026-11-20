"""Array-free native acting wire, mapped locally to the frozen v1 source contract.
The model authors complete natural acting prose only. Fixed unit ownership and
legal overlap are derived from source380, never repaired from a failed response.
"""
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_natural_scene_performance_v1 as base

VERSION = 'natural_scene_performance/v2'
SOURCE_SHA = base.SOURCE_SHA
NORMAL_SPOKEN_CHARACTERS_PER_SECOND = base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND
CURRENT_ACTION_SECONDS = base.CURRENT_ACTION_SECONDS
catalog, own_refs, digest = base.catalog, base.own_refs, base.digest
evidence_catalog = base.evidence_catalog
obj, text, arr = base.obj, base.text, base.arr
pack_first, validate_timeline = base.pack_first, base.validate_timeline
NATIVE_UNIT_FIELDS = ('continuous_performance', 'zhou_intent', 'xiaolin_intent',
                      'camera', 'delivery', 'post_pause_seconds')
FIXED_UNITS = {
    'opening_exchange': {
        'source_refs': ['B1.S01', 'B1.S02', 'B1.S03'],
        'overlap_pairs': [{'action_ref': 'B1.S01', 'dialogue_ref': 'B1.S02'}],
        'state_sources': []},
    'material_offer': {
        'source_refs': ['B1.S04', 'B1.S05'],
        'overlap_pairs': [{'action_ref': 'B1.S05', 'dialogue_ref': 'B1.S04'}],
        'state_sources': []},
    'reading_discovery': {
        'source_refs': ['B1.S06', 'B1.S07'], 'overlap_pairs': [],
        'state_sources': ['B1.S07']}}


def schema(script):
    previous = base.schema(script)
    props = {'direction': deepcopy(previous['properties']['direction'])}
    for name in FIXED_UNITS:
        fields = {field: text() for field in NATIVE_UNIT_FIELDS if field != 'post_pause_seconds'}
        fields['post_pause_seconds'] = {'type': 'number', 'minimum': 0, 'maximum': 1.5}
        props[name] = obj(fields)
    return obj(props)


def compile_contract(raw, script):
    Draft202012Validator(schema(script)).validate(raw)
    mapped = {'direction': deepcopy(raw['direction']), 'B1': {'semantic_units': []}}
    for name, ownership in FIXED_UNITS.items():
        mapped['B1']['semantic_units'].append({**deepcopy(ownership), **deepcopy(raw[name])})
    result = base.compile_contract(mapped, script)
    preserved = (mapped['direction'] == raw['direction'] and all(
        all(unit[field] == raw[name][field] for field in NATIVE_UNIT_FIELDS)
        for (name, _), unit in zip(FIXED_UNITS.items(), mapped['B1']['semantic_units'])))
    if not preserved:
        raise ValueError('native acting values changed during deterministic mapping')
    result.update(native_schema=VERSION, native_raw_sha256=digest(raw),
                  mapped_contract_sha256=digest(mapped),
                  native_source_mapping={'schema': VERSION, 'source_sha256': SOURCE_SHA,
                      'fixed_units': deepcopy(FIXED_UNITS), 'all_native_values_preserved': preserved,
                      'failed_response_repaired': False, 'prior_response_spliced': False})
    return result


DEFAULT_REFERENCE_DESCRIPTION = (
    '输入参考仅用于同一位小林、同一位周姐的身份、服装和同一会议室环境；'
    '原参考中的道具位置和姿势不沿用。按当前新起态生成：工牌已戴在小林胸前，'
    '双方已经坐好，文件夹合着，纸笔在周姐一侧')


def render_prompt(candidate, script, reference_description=DEFAULT_REFERENCE_DESCRIPTION):
    prompt = base.render_prompt(candidate, script, reference_description)
    if 'B1.S05' not in candidate['source_refs']:
        old = '纸笔最多从周姐侧送到小林近桌沿一次；未签名，小林不碰笔。结束在以上已列完整单元，不预演未列对白、拒签、收夹或出门。'
        current = '纸和笔仍在周姐一侧，文件夹已打开，小林未碰笔。结束在本段最后一条原对白完整说完之后，保持当前同场景和道具位置。'
        if prompt.count(old) != 1:
            raise ValueError('fixed current-state prompt serialization differs from frozen base')
        prompt = prompt.replace(old, current)
    return prompt
