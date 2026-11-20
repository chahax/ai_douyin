"""Source-bound current pure-dialogue exchange, using six native acting fields.

The spec binds a contiguous dialogue interval and unchanged physical state.
A complete current exchange does not certify its preceding source coverage,
any whole beat or film, or actual media quality. Speech timing is a planning
assumption. The media dispatcher verifies approval of the service-native tail.
"""
from collections import Counter
from copy import deepcopy
import math
from jsonschema import Draft202012Validator
from src.content_factory import creative_natural_scene_performance_v1 as base
from src.content_factory import creative_film_material_exchange_v1 as material

VERSION = 'film_dialogue_exchange/v1'
SPEC_VERSION = 'film_dialogue_exchange_spec/v1'
SOURCE_SHA = base.SOURCE_SHA  # Convenience for the current source, not a gate.
NATIVE_UNIT_FIELDS = material.NATIVE_UNIT_FIELDS
NORMAL_SPOKEN_CHARACTERS_PER_SECOND = base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND
catalog, own_refs, digest = base.catalog, base.own_refs, base.digest
_LENGTHS = {'continuous_performance': 320, 'zhou_intent': 80,
            'xiaolin_intent': 80, 'camera': 160, 'delivery': 100}
_TEXT = {'type': 'string', 'minLength': 1}
_REFS = {'type': 'array', 'items': _TEXT, 'uniqueItems': True}
SPEC_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['schema', 'source_sha256', 'beat_id', 'interaction_id',
                 'source_refs', 'prior_source_refs', 'initial_state',
                 'final_state', 'brief'],
    'properties': {
        'schema': {'const': SPEC_VERSION},
        'source_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        'beat_id': _TEXT, 'interaction_id': _TEXT,
        'source_refs': {**_REFS, 'minItems': 2},
        'prior_source_refs': _REFS,
        'initial_state': {'type': 'object', 'minProperties': 1},
        'final_state': {'type': 'object', 'minProperties': 1},
        'brief': {'type': 'object',
                  'required': ['current_change', 'observation', 'cut_condition'],
                  'additionalProperties': _TEXT},
    },
}


def validate_spec(script, spec):
    """Reject wrong source, gaps, action sources, and changed physical state."""
    Draft202012Validator(SPEC_SCHEMA).validate(spec)
    if digest(script) != spec['source_sha256']:
        raise ValueError('dialogue exchange source identity changed')
    beat_ids = [beat['id'] for beat in script['beats']]
    if len(beat_ids) != len(set(beat_ids)) or spec['beat_id'] not in beat_ids:
        raise ValueError('dialogue exchange beat identity invalid')
    sources = catalog(script)
    ordered = list(sources)
    refs = spec['source_refs']
    beat_refs = own_refs(script, spec['beat_id'])
    if any(ref not in sources or ref not in beat_refs for ref in refs):
        raise ValueError('dialogue sources must belong to the current beat')
    first = ordered.index(refs[0])
    if ordered[first:first + len(refs)] != refs:
        raise ValueError('dialogue sources must be contiguous and ordered')
    if spec['prior_source_refs'] != ordered[:first]:
        raise ValueError('prior source refs must preserve the complete prefix')
    for ref in refs:
        source = sources[ref]
        if (source['kind'] != 'dialogue' or not source.get('speaker')
                or base.spoken_characters(source) <= 0):
            raise ValueError('action or empty source cannot compile as pure dialogue')
    # Canonical hashes distinguish e.g. True from 1 as well as state changes.
    if digest(spec['initial_state']) != digest(spec['final_state']):
        raise ValueError('pure dialogue exchange must preserve physical state')
    return sources


def current_catalog(script, spec):
    sources = validate_spec(script, spec)
    return {ref: deepcopy(sources[ref]) for ref in spec['source_refs']}


def schema(script, spec):
    validate_spec(script, spec)
    fields = {field: {'type': 'string', 'minLength': 1, 'maxLength': limit}
              for field, limit in _LENGTHS.items()}
    fields['post_pause_seconds'] = {'type': 'number', 'minimum': 0, 'maximum': 1.5}
    return {'type': 'object', 'additionalProperties': False,
            'required': list(NATIVE_UNIT_FIELDS), 'properties': fields}


def compile_contract(raw, script, spec):
    sources = validate_spec(script, spec)
    Draft202012Validator(schema(script, spec)).validate(raw)
    base._assert_no_dialogue_copy(raw, sources)
    if not math.isfinite(raw['post_pause_seconds']):
        raise ValueError('post pause must be finite')
    refs = spec['source_refs']
    elapsed = 0.0
    schedule = []
    for ref in refs:
        source = sources[ref]
        seconds = base.spoken_characters(source) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND
        start, end = elapsed, elapsed + seconds
        schedule.append({'source_ref': ref, 'unit_id': 'U01',
                         'source_kind': 'dialogue', 'speaker': source['speaker'],
                         'original_text': source['text'], 'start': round(start, 6),
                         'end': round(end, 6), 'duration_seconds': round(seconds, 6),
                         'persistent_state': False})
        elapsed = end
    total = elapsed + raw['post_pause_seconds']
    ready = total <= 15 + 1e-6
    unit = {**deepcopy(raw), 'unit_id': 'U01', 'source_refs': deepcopy(refs),
            'overlap_pairs': [], 'state_sources': [], 'start': 0.0,
            'content_end': round(elapsed, 6), 'end': round(total, 6),
            'duration_seconds': round(total, 6),
            'start_state': deepcopy(spec['initial_state']),
            'end_state': deepcopy(spec['final_state']),
            'dispatch_ready': ready, 'status': 'ready' if ready else 'needs_revision'}
    ordered = list(sources)
    last = ordered.index(refs[-1])
    return {'schema': VERSION, 'script_sha256': digest(script),
            'interaction_spec': deepcopy(spec), 'interaction_spec_sha256': digest(spec),
            'native_raw_sha256': digest(raw),
            'current_interaction': spec['interaction_id'], 'beat_id': spec['beat_id'],
            'source_refs': deepcopy(refs), 'semantic_units': [unit],
            'schedule': schedule, 'source_seconds': round(total, 6),
            'total_duration_seconds': round(total, 6),
            'duration_seconds': max(4, math.ceil(round(total, 6))) if ready else None,
            'complete_current_interaction': True, 'complete_beat': False,
            'whole_film_performance_complete': False, 'coverage_pending': True,
            'prior_refs_required': deepcopy(spec['prior_source_refs']),
            'unbuilt_source_refs': ordered[last + 1:], 'needs_revision': not ready,
            'all_native_values_preserved': True, 'source_text_unchanged': True,
            'fit_scaled': False, 'initial_state': deepcopy(spec['initial_state']),
            'final_state': deepcopy(spec['final_state']),
            'timing_assumption': {
                'normal_spoken_characters_per_second': NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
                'action_seconds': {}, 'fixed_inter_turn_pause_seconds': 0.0,
                'measured_audio': False, 'fit_scaled': False},
            'creative_quality_passed': False, 'actual_media_readability': None,
            'requires_human_approved_service_tail_before_media': True}


def pack_first(compiled, max_seconds=15):
    if compiled.get('schema') != VERSION:
        raise ValueError('different dialogue exchange compilation')
    if not 4 <= max_seconds <= 15:
        raise ValueError('native sample limit must be within four to fifteen seconds')
    spec = compiled['interaction_spec']
    Draft202012Validator(SPEC_SCHEMA).validate(spec)
    refs = spec['source_refs']
    if (compiled.get('interaction_spec_sha256') != digest(spec)
            or compiled.get('script_sha256') != spec['source_sha256']
            or compiled.get('source_refs') != refs
            or [row['source_ref'] for row in compiled.get('schedule', [])] != refs
            or any(row['source_kind'] != 'dialogue' for row in compiled['schedule'])
            or len(compiled.get('semantic_units', [])) != 1):
        raise ValueError('dialogue exchange source/spec binding changed')
    unit = compiled['semantic_units'][0]
    raw = {field: unit[field] for field in NATIVE_UNIT_FIELDS}
    if digest(raw) != compiled['native_raw_sha256']:
        raise ValueError('native dialogue exchange prose changed')
    if (unit['source_refs'] != refs or unit['overlap_pairs'] or unit['state_sources']
            or digest(unit['start_state']) != digest(spec['initial_state'])
            or digest(unit['end_state']) != digest(spec['final_state'])
            or digest(compiled['initial_state']) != digest(spec['initial_state'])
            or digest(compiled['final_state']) != digest(spec['final_state'])):
        raise ValueError('dialogue exchange source or physical state changed')
    ready = (not compiled['needs_revision'] and unit['dispatch_ready']
             and compiled['source_seconds'] <= max_seconds + 1e-6)
    return {'schema': VERSION + '/candidate', 'script_sha256': compiled['script_sha256'],
            'compiled_sha256': digest(compiled),
            'interaction_spec_sha256': compiled['interaction_spec_sha256'],
            'interaction_spec': deepcopy(spec),
            'native_raw_sha256': compiled['native_raw_sha256'],
            'semantic_units': deepcopy(compiled['semantic_units']) if ready else [],
            'source_refs': deepcopy(refs) if ready else [],
            'source_seconds': compiled['source_seconds'] if ready else 0,
            'duration_seconds': compiled['duration_seconds'] if ready else None,
            'dispatch_ready': ready, 'status': 'ready' if ready else 'needs_revision',
            'reason': None if ready else 'complete current dialogue exceeds limit; no truncation or speed fitting',
            'start_state': deepcopy(compiled['initial_state']) if ready else None,
            'end_state': deepcopy(compiled['final_state']) if ready else None,
            'complete_current_interaction': ready, 'complete_beat': False,
            'coverage_pending': True,
            'prior_refs_required': deepcopy(spec['prior_source_refs']),
            'unbuilt_source_refs': deepcopy(compiled['unbuilt_source_refs']),
            'fit_scaled': False, 'full_film_complete': False,
            'requires_human_approved_service_tail_before_media': True}


def render_prompt(candidate, script, spec):
    if (candidate.get('schema') != VERSION + '/candidate' or not candidate.get('dispatch_ready')
            or candidate.get('script_sha256') != digest(script)
            or candidate.get('interaction_spec_sha256') != digest(spec)
            or candidate.get('interaction_spec') != spec
            or len(candidate.get('semantic_units', [])) != 1):
        raise ValueError('unready or different dialogue exchange candidate')
    unit = candidate['semantic_units'][0]
    raw = {field: unit[field] for field in NATIVE_UNIT_FIELDS}
    exact = compile_contract(raw, script, spec)
    if pack_first(exact) != candidate:
        raise ValueError('dialogue source, prose, state or timing altered')
    sources = current_catalog(script, spec)
    lines = [f"{candidate['duration_seconds']}秒，9:16竖屏，中国当代普通公司写实剧情，同一场景继续对话。",
             '输入图片为上一段生成服务原始尾帧，作为first_frame承接同一人物、服装、会议室、双方位置及道具起态。',
             '自然中文普通话，正常谈话速度。目的、演法和观察描述是创作指令，不朗读。以下当前原对白各说一次，按原顺序，不增加对白或旁白。无字幕、配乐、标题和姓名标签。',
             '只完成当前对话与自然聆听。允许随交谈发生的视线、表情和身体姿态变化；保持纸笔文件夹和工牌起态及双方坐站位置，不重复上一段操作，不新增操作。',
             '连贯表演：' + raw['continuous_performance'],
             '周姐对对方的行动目的与潜台词：' + raw['zhou_intent'],
             '小林对对方的行动目的与潜台词：' + raw['xiaolin_intent'],
             '观察与机位：' + raw['camera'], '说话方式：' + raw['delivery']]
    for ref in spec['source_refs']:
        source = sources[ref]
        lines.append(source['speaker'].split('（')[0] + '原对白：「' + source['text'] + '」')
    if raw['post_pause_seconds'] > 0:
        lines.append(f"当前最后一句完整说完后留{raw['post_pause_seconds']:g}秒接收回答，不添新发言或操作。")
    lines.append('本段结束时保持道具、服装及双方位置与起态一致；不预演后续事件。')
    prompt = '\n'.join(lines)
    expected = Counter(source['text'] for source in sources.values())
    for source in catalog(script).values():
        if source['kind'] == 'dialogue' and prompt.count(source['text']) != expected[source['text']]:
            raise ValueError('dialogue exact uniqueness or future isolation failed')
    return prompt
