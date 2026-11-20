"""One material-and-reading exchange from exact reviewed source380.

The model supplies six native acting fields. Fixed source ownership, one paper
movement, legal overlap, and normal dialogue timing are compiled locally.
A complete current tail exchange does not certify the preceding opening, B1,
or any actual media quality. No old source or acting module is modified.
"""
from copy import deepcopy
import math
from jsonschema import Draft202012Validator
from src.content_factory import creative_natural_scene_performance_v1 as base

VERSION = 'film_material_exchange/v1'
SOURCE_SHA = base.SOURCE_SHA
CURRENT_SOURCE_REFS = ('B1.S04', 'B1.S05', 'B1.S06', 'B1.S07')
PRIOR_SOURCE_REFS_REQUIRED = ('B1.S01', 'B1.S02', 'B1.S03')
NATIVE_UNIT_FIELDS = ('continuous_performance', 'zhou_intent', 'xiaolin_intent',
                      'camera', 'delivery', 'post_pause_seconds')
NORMAL_SPOKEN_CHARACTERS_PER_SECOND = base.NORMAL_SPOKEN_CHARACTERS_PER_SECOND
PUSH_SECONDS = 2.0
INITIAL_STATE = {'folder': 'open', 'paper': 'zhou_side', 'pen': 'zhou_side',
                 'paper_signed': False, 'xiaolin_pen_touched': False,
                 'zhou_position': 'seated', 'xiaolin_position': 'seated',
                 'badge': 'worn_by_xiaolin'}
FINAL_STATE = {**INITIAL_STATE, 'paper': 'xiaolin_near_edge', 'pen': 'xiaolin_near_edge'}
catalog, own_refs, digest = base.catalog, base.own_refs, base.digest
DEFAULT_REFERENCE_DESCRIPTION = (
    '输入图片是用户批准的上一段生成服务原始尾帧，作为first_frame承接同一小林、周姐、'
    '服装与小会议室及双方当前位置；工牌已戴在小林胸前，文件夹已打开，未签纸笔还在周姐侧')


def current_catalog(script):
    sources = base._source(script)
    return {ref: deepcopy(sources[ref]) for ref in CURRENT_SOURCE_REFS}


def schema(script):
    base._source(script)
    lengths = {'continuous_performance': 320, 'zhou_intent': 80,
               'xiaolin_intent': 80, 'camera': 160, 'delivery': 100}
    fields = {field: {'type': 'string', 'minLength': 1, 'maxLength': limit}
              for field, limit in lengths.items()}
    fields['post_pause_seconds'] = {'type': 'number', 'minimum': 0, 'maximum': 1.5}
    return {'type': 'object', 'additionalProperties': False,
            'required': list(NATIVE_UNIT_FIELDS), 'properties': fields}


def compile_contract(raw, script):
    Draft202012Validator(schema(script)).validate(raw)
    sources = base._source(script)
    base._assert_no_dialogue_copy(raw, sources)
    request_seconds = base.spoken_characters(sources['B1.S04']) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND
    reading_seconds = base.spoken_characters(sources['B1.S06']) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND
    push_start = max(0.0, request_seconds - PUSH_SECONDS)
    push_end = push_start + PUSH_SECONDS
    read_start = max(request_seconds, push_end)
    content_end = read_start + reading_seconds
    total = content_end + raw['post_pause_seconds']
    ready = total <= 15 + 1e-6
    times = {'B1.S04': (0.0, request_seconds), 'B1.S05': (push_start, push_end),
             'B1.S06': (read_start, content_end), 'B1.S07': (read_start, total)}
    schedule = []
    for ref in CURRENT_SOURCE_REFS:
        source = sources[ref]
        start, end = times[ref]
        persistent = ref == 'B1.S07'
        schedule.append({'source_ref': ref, 'unit_id': 'U01',
                         'source_kind': source['kind'], 'speaker': source['speaker'],
                         'original_text': source['text'], 'start': round(start, 6),
                         'end': round(end, 6),
                         'duration_seconds': 0.0 if persistent else round(end - start, 6),
                         'persistent_state': persistent})
    physical = {'source_ref': 'B1.S05', 'movement_count': 1,
                'paper_from': 'zhou_side', 'paper_to': 'xiaolin_near_edge',
                'pen_from': 'zhou_side', 'pen_to': 'xiaolin_near_edge',
                'zhou_hand_withdrawn_after_push': True,
                'reading_requires_arrival': True, 'paper_signed': False,
                'xiaolin_pen_touched': False}
    unit = {**deepcopy(raw), 'unit_id': 'U01', 'source_refs': list(CURRENT_SOURCE_REFS),
            'overlap_pairs': [{'action_ref': 'B1.S05', 'dialogue_ref': 'B1.S04'}],
            'state_sources': ['B1.S07'], 'start': 0.0,
            'content_end': round(content_end, 6), 'end': round(total, 6),
            'duration_seconds': round(total, 6),
            'start_state': deepcopy(INITIAL_STATE), 'end_state': deepcopy(FINAL_STATE),
            'physical_transition': physical, 'dispatch_ready': ready,
            'status': 'ready' if ready else 'needs_revision'}
    return {'schema': VERSION, 'script_sha256': digest(script),
            'native_raw_sha256': digest(raw), 'current_interaction': 'material_exchange',
            'source_refs': list(CURRENT_SOURCE_REFS), 'semantic_units': [unit],
            'schedule': schedule, 'source_seconds': round(total, 6),
            'total_duration_seconds': round(total, 6),
            'duration_seconds': max(4, math.ceil(round(total, 6))) if ready else None,
            'complete_current_interaction': True, 'complete_current_material_exchange': True,
            'current_remaining_unit_complete': True, 'complete_B1': False,
            'prior_refs_required': list(PRIOR_SOURCE_REFS_REQUIRED),
            'B1_coverage_pending': True, 'whole_film_performance_complete': False,
            'unbuilt_beats': ['B2', 'B3', 'B4'], 'needs_revision': not ready,
            'all_native_values_preserved': True, 'source_text_unchanged': True,
            'fit_scaled': False, 'initial_state': deepcopy(INITIAL_STATE),
            'final_state': deepcopy(FINAL_STATE), 'physical_transition': deepcopy(physical),
            'timing_assumption': {'normal_spoken_characters_per_second': NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
                                  'action_seconds': {'B1.S05': PUSH_SECONDS},
                                  'persistent_state_extra_seconds': {'B1.S07': 0.0},
                                  'measured_audio': False, 'fit_scaled': False},
            'creative_quality_passed': False, 'actual_media_readability': None,
            'requires_human_approved_service_tail_before_media': True}


def pack_first(compiled, max_seconds=15, required_source_refs=('B1.S04', 'B1.S06')):
    if compiled.get('schema') != VERSION or compiled.get('script_sha256') != SOURCE_SHA:
        raise ValueError('different material exchange source compilation')
    if not 4 <= max_seconds <= 15:
        raise ValueError('native sample limit must be within four to fifteen seconds')
    if (compiled.get('source_refs') != list(CURRENT_SOURCE_REFS)
            or [r['source_ref'] for r in compiled.get('schedule', [])] != list(CURRENT_SOURCE_REFS)
            or len(compiled.get('semantic_units', [])) != 1):
        raise ValueError('material exchange must preserve all four current sources')
    unit = compiled['semantic_units'][0]
    raw = {field: unit[field] for field in NATIVE_UNIT_FIELDS}
    if digest(raw) != compiled['native_raw_sha256']:
        raise ValueError('native material exchange prose changed')
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
            'reason': None if ready else 'complete offer and reading cannot fit; no truncation or speed fitting',
            'start_state': deepcopy(compiled['initial_state']) if ready else None,
            'end_state': deepcopy(compiled['final_state']) if ready else None,
            'complete_current_interaction': ready, 'complete_current_material_exchange': ready,
            'complete_B1': False, 'prior_refs_required': list(PRIOR_SOURCE_REFS_REQUIRED),
            'B1_coverage_pending': True, 'fit_scaled': False, 'full_film_complete': False,
            'requires_human_approved_service_tail_before_media': True}


def render_prompt(candidate, script, reference_description=DEFAULT_REFERENCE_DESCRIPTION):
    if (candidate.get('schema') != VERSION + '/candidate' or not candidate.get('dispatch_ready')
            or candidate.get('script_sha256') != SOURCE_SHA
            or len(candidate.get('semantic_units', [])) != 1
            or candidate.get('source_refs') != list(CURRENT_SOURCE_REFS)):
        raise ValueError('unready or different material exchange candidate')
    unit = candidate['semantic_units'][0]
    raw = {field: unit[field] for field in NATIVE_UNIT_FIELDS}
    exact = compile_contract(raw, script)
    if pack_first(exact) != candidate:
        raise ValueError('material exchange source, prose, state or local timing altered')
    sources = current_catalog(script)
    lines = [f"{candidate['duration_seconds']}秒，9:16竖屏，中国当代普通公司写实剧情，同一场景继续对话。",
             reference_description + '。只有小林与周姐两人，不重新入座、开夹或戴工牌。',
             '自然中文普通话，正常谈话速度。目的、演法和观察描述是创作指令，不朗读。以下原对白各说一次，不增加对白或旁白。无字幕、配乐、标题和姓名标签。',
             '连贯表演：' + raw['continuous_performance'],
             '周姐的目的与潜台词：' + raw['zhou_intent'],
             '小林的目的与潜台词：' + raw['xiaolin_intent'],
             '观察与机位：' + raw['camera'], '说话方式：' + raw['delivery'],
             '周姐在当前句催小林看材料的末段，把纸和笔一起从自己侧一次送到小林靠桌沿的位置，自己手收回；不把纸推向桌子中间，不重复推。',
             '这句与递材料自然重叠，纸笔到位且周姐完整说完后，小林才低头看原因栏并读出当前反问。小林不碰笔，读字与继续看那行字可以自然同时发生，不另加一个凝视动作块。',
             sources['B1.S04']['speaker'].split('（')[0] + '原对白：「' + sources['B1.S04']['text'] + '」',
             sources['B1.S06']['speaker'].split('（')[0] + '原对白：「' + sources['B1.S06']['text'] + '」']
    if raw['post_pause_seconds'] > 0:
        lines.append(f"当前反问完整说完后留{raw['post_pause_seconds']:g}秒承接理解变化，不添新发言或操作。")
    lines.append('本段结束时文件夹仍打开，未签纸笔停在小林近桌沿，小林未碰笔，工牌仍戴着，双方仍坐在原位；不预演后续拒签、收纸或出门。')
    prompt = '\n'.join(lines)
    for ref, source in base.catalog(script).items():
        if source['kind'] == 'dialogue' and prompt.count(source['text']) != int(ref in CURRENT_SOURCE_REFS):
            raise ValueError('material exchange exact dialogue uniqueness or future isolation failed')
    return prompt
