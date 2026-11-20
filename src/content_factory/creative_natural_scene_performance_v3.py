"""One complete opening interaction, exact reviewed source, native six-field wire.
The full script is background only. No missing B1 material is fabricated to pass
coverage; natural action/dialogue overlap and timing are declared locally.
"""
from copy import deepcopy
import math
from jsonschema import Draft202012Validator
from src.content_factory import creative_natural_scene_performance_v2 as previous
from src.content_factory import creative_natural_scene_performance_v1 as base

VERSION = 'natural_opening_exchange/v3'
SOURCE_SHA = base.SOURCE_SHA
CURRENT_SOURCE_REFS = ('B1.S01', 'B1.S02', 'B1.S03')
NATIVE_UNIT_FIELDS = previous.NATIVE_UNIT_FIELDS
NORMAL_SPOKEN_CHARACTERS_PER_SECOND = base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND
CURRENT_ACTION_SECONDS = {'B1.S01': 1.0}
DEFAULT_REFERENCE_DESCRIPTION = previous.DEFAULT_REFERENCE_DESCRIPTION
catalog, own_refs, digest = base.catalog, base.own_refs, base.digest
evidence_catalog = base.evidence_catalog
obj, text, arr = base.obj, base.text, base.arr


def current_catalog(script):
    sources = base._source(script)
    return {ref: deepcopy(sources[ref]) for ref in CURRENT_SOURCE_REFS}


def schema(script):
    return deepcopy(previous.schema(script)['properties']['opening_exchange'])


def compile_contract(raw, script):
    Draft202012Validator(schema(script)).validate(raw)
    sources = base._source(script)
    base._assert_no_dialogue_copy(raw, sources)
    first_duration = base.spoken_characters(sources['B1.S02']) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND
    reply_duration = base.spoken_characters(sources['B1.S03']) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND
    reply_start = max(CURRENT_ACTION_SECONDS['B1.S01'], first_duration)
    content_end = reply_start + reply_duration
    total = content_end + raw['post_pause_seconds']
    initial = deepcopy(base.INITIAL_STATE)
    final = {**deepcopy(initial), 'folder': 'open'}
    unit = {**deepcopy(raw), 'unit_id': 'U01', 'source_refs': list(CURRENT_SOURCE_REFS),
            'overlap_pairs': [{'action_ref': 'B1.S01', 'dialogue_ref': 'B1.S02'}],
            'state_sources': [], 'start': 0.0, 'content_end': round(content_end, 6),
            'end': round(total, 6), 'duration_seconds': round(total, 6),
            'start_state': initial, 'end_state': final,
            'dispatch_ready': total <= 15 + 1e-6,
            'status': 'ready' if total <= 15 + 1e-6 else 'needs_revision'}
    times = {'B1.S01': (0.0, CURRENT_ACTION_SECONDS['B1.S01']),
             'B1.S02': (0.0, first_duration),
             'B1.S03': (reply_start, content_end)}
    schedule = []
    for ref in CURRENT_SOURCE_REFS:
        source = sources[ref]
        start, end = times[ref]
        schedule.append({'source_ref': ref, 'unit_id': 'U01', 'source_kind': source['kind'],
                         'speaker': source['speaker'], 'original_text': source['text'],
                         'start': round(start, 6), 'end': round(end, 6),
                         'duration_seconds': round(end - start, 6), 'persistent_state': False})
    return {'schema': VERSION, 'script_sha256': digest(script), 'native_raw_sha256': digest(raw),
            'current_interaction': 'opening_exchange', 'source_refs': list(CURRENT_SOURCE_REFS),
            'semantic_units': [unit], 'schedule': schedule,
            'complete_current_interaction': True, 'complete_B1': False,
            'whole_film_performance_complete': False, 'unbuilt_source_refs': base.own_refs(script, 'B1')[3:],
            'source_seconds': round(total, 6), 'total_duration_seconds': round(total, 6),
            'duration_seconds': max(4, math.ceil(round(total, 6))) if total <= 15 + 1e-6 else None,
            'needs_revision': total > 15 + 1e-6, 'all_native_values_preserved': True,
            'source_text_unchanged': True, 'fit_scaled': False, 'initial_state': initial, 'final_state': final,
            'timing_assumption': {'normal_spoken_characters_per_second': NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
                                  'action_seconds': deepcopy(CURRENT_ACTION_SECONDS), 'measured_audio': False},
            'creative_quality_passed': False, 'actual_media_readability': None}


def pack_first(compiled, max_seconds=15, required_source_refs=('B1.S02', 'B1.S03')):
    if compiled.get('schema') != VERSION or compiled.get('script_sha256') != SOURCE_SHA:
        raise ValueError('different opening source compilation')
    if not 4 <= max_seconds <= 15:
        raise ValueError('native sample limit must be within four to fifteen seconds')
    if (compiled.get('source_refs') != list(CURRENT_SOURCE_REFS)
            or [r['source_ref'] for r in compiled.get('schedule', [])] != list(CURRENT_SOURCE_REFS)
            or len(compiled.get('semantic_units', [])) != 1):
        raise ValueError('opening must preserve its entire three-step interaction')
    unit = compiled['semantic_units'][0]
    raw = {field: unit[field] for field in NATIVE_UNIT_FIELDS}
    if digest(raw) != compiled['native_raw_sha256']:
        raise ValueError('native opening prose changed')
    ready = (not compiled['needs_revision'] and unit['dispatch_ready']
             and compiled['source_seconds'] <= max_seconds + 1e-6
             and set(required_source_refs).issubset(CURRENT_SOURCE_REFS))
    return {'schema': VERSION + '/candidate', 'script_sha256': SOURCE_SHA,
            'compiled_sha256': digest(compiled), 'native_raw_sha256': compiled['native_raw_sha256'],
            'semantic_units': deepcopy(compiled['semantic_units']) if ready else [],
            'source_refs': list(CURRENT_SOURCE_REFS) if ready else [],
            'source_seconds': compiled['source_seconds'] if ready else 0,
            'duration_seconds': compiled['duration_seconds'] if ready else None,
            'dispatch_ready': ready, 'status': 'ready' if ready else 'needs_revision',
            'reason': None if ready else 'complete notice and employee reply cannot fit; no truncation or speed fitting',
            'start_state': deepcopy(compiled['initial_state']) if ready else None,
            'end_state': deepcopy(compiled['final_state']) if ready else None,
            'complete_current_interaction': ready, 'complete_B1': False,
            'fit_scaled': False, 'full_film_complete': False}


def render_prompt(candidate, script, reference_description=DEFAULT_REFERENCE_DESCRIPTION):
    if (candidate.get('schema') != VERSION + '/candidate' or not candidate.get('dispatch_ready')
            or candidate.get('script_sha256') != SOURCE_SHA or len(candidate.get('semantic_units', [])) != 1
            or candidate.get('source_refs') != list(CURRENT_SOURCE_REFS)):
        raise ValueError('unready or different opening candidate')
    unit = candidate['semantic_units'][0]
    raw = {field: unit[field] for field in NATIVE_UNIT_FIELDS}
    exact = compile_contract(raw, script)
    if pack_first(exact) != candidate:
        raise ValueError('opening source, prose or local timing altered')
    sources = current_catalog(script)
    lines = [f"{candidate['duration_seconds']}秒，9:16竖屏，中国当代普通公司写实剧情，连贯的同场景对话。",
             reference_description + '。只有小林和周姐。',
             '自然中文普通话，正常谈话速度。角色目的、演法和观察描述是创作指令，不朗读。原对白各说一次，不增加旁白或其他对白。无字幕、配乐、标题和姓名标签。',
             '连贯表演：' + raw['continuous_performance'],
             '周姐的目的与潜台词：' + raw['zhou_intent'],
             '小林的目的与潜台词：' + raw['xiaolin_intent'],
             '观察与机位：' + raw['camera'], '说话方式：' + raw['delivery'],
             '周姐打开文件夹时可以自然说公司决定，小林听完这句后回应，保持这一个对话回合连贯。',
             sources['B1.S02']['speaker'].split('（')[0] + '原对白：「' + sources['B1.S02']['text'] + '」',
             sources['B1.S03']['speaker'].split('（')[0] + '原对白：「' + sources['B1.S03']['text'] + '」']
    if raw['post_pause_seconds'] > 0:
        lines.append(f"回应之后只留{raw['post_pause_seconds']:g}秒消化当前反馈，不另添操作。")
    lines.append('本段结束时文件夹已打开，纸和笔仍在周姐一侧，小林未碰笔；保持当前人物、会议室和道具位置。')
    prompt = '\n'.join(lines)
    for ref, source in base.catalog(script).items():
        if source['kind'] == 'dialogue' and prompt.count(source['text']) != int(ref in CURRENT_SOURCE_REFS):
            raise ValueError('opening exact dialogue uniqueness or future isolation failed')
    return prompt
