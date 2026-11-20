"""Natural semantic performance groups, exact source dialogue, local timing.
Timing is a project planning assumption, not measured actor speech. No model
line is rewritten, no source words are split, and no duration is fit-scaled.
"""
from copy import deepcopy
import math
import re
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_short_director_performance_v1 as helpers

VERSION = 'natural_scene_performance/v1'
SOURCE_SHA = '078b0bcee752062edb348f6a29a2bd2ad229a9333c8e2a934643bd5ab050c75e'
NORMAL_SPOKEN_CHARACTERS_PER_SECOND = 3.3
CURRENT_ACTION_SECONDS = {'B1.S01': 1.0, 'B1.S05': 2.0}
ALLOWED_OVERLAP_PAIRS = {('B1.S01', 'B1.S02'), ('B1.S05', 'B1.S04')}
PERSISTENT_STATE_REF = 'B1.S07'
PERSISTENT_WITH_REF = 'B1.S06'
INITIAL_STATE = {'folder': 'closed', 'paper': 'zhou_side', 'pen': 'zhou_side',
                 'paper_signed': False, 'xiaolin_pen_touched': False,
                 'zhou_position': 'seated', 'xiaolin_position': 'seated'}
TRANSITIONS = {'B1.S01': {'folder': 'open'},
               'B1.S05': {'paper': 'xiaolin_near_edge', 'pen': 'xiaolin_near_edge'}}
catalog, own_refs, digest = helpers.catalog, helpers.own_refs, helpers.digest
obj, text, arr = helpers.obj, helpers.text, helpers.arr
evidence_catalog = helpers.evidence_catalog


def _source(script):
    if digest(script) != SOURCE_SHA:
        raise ValueError('natural scene contract belongs to exact reviewed source380')
    if [b['id'] for b in script['beats']] != ['B1', 'B2', 'B3', 'B4']:
        raise ValueError('expected current four-beat source')
    return catalog(script)


def schema(script):
    _source(script)
    director = obj({b['id']: obj({'observation': text(), 'information_change': text(),
                                 'cut_reason': text()}) for b in script['beats']})
    pair = obj({'action_ref': {'enum': ['B1.S01', 'B1.S05']},
                'dialogue_ref': {'enum': ['B1.S02', 'B1.S04']}})
    unit = obj({'source_refs': arr({'enum': own_refs(script, 'B1')}, 1, 7),
                'continuous_performance': text(), 'zhou_intent': text(), 'xiaolin_intent': text(),
                'camera': text(), 'delivery': text(), 'overlap_pairs': arr(pair, 0, 2),
                'state_sources': arr({'const': PERSISTENT_STATE_REF}, 0, 1),
                'post_pause_seconds': {'type': 'number', 'minimum': 0, 'maximum': 1.5}})
    return obj({'direction': director, 'B1': obj({'semantic_units': arr(unit, 1, 7)})})


def spoken_characters(source):
    return len(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', source['text']))


def _seconds(source, ref):
    if ref == PERSISTENT_STATE_REF:
        return 0.0
    if source['kind'] == 'dialogue':
        return spoken_characters(source) / NORMAL_SPOKEN_CHARACTERS_PER_SECOND
    if ref not in CURRENT_ACTION_SECONDS:
        raise ValueError('unconfigured source action duration: ' + ref)
    return CURRENT_ACTION_SECONDS[ref]


def _assert_no_dialogue_copy(unit, sources):
    fields = ('continuous_performance', 'zhou_intent', 'xiaolin_intent', 'camera', 'delivery')
    for field in fields:
        cue = unit[field]
        if any(source['kind'] == 'dialogue' and source['text'].rstrip('。！？!?') in cue
               for source in sources.values()):
            raise ValueError('source dialogue copied into performance prose: ' + field)


def validate_timeline(schedule, script, overlap_pairs):
    sources = _source(script)
    if [r['source_ref'] for r in schedule] != own_refs(script, 'B1'):
        raise ValueError('timeline must preserve complete B1 source order')
    rows = {r['source_ref']: r for r in schedule}
    if any(r['source_kind'] != sources[r['source_ref']]['kind']
           or r['speaker'] != sources[r['source_ref']]['speaker']
           or r['original_text'] != sources[r['source_ref']]['text'] for r in schedule):
        raise ValueError('source text or ownership changed')
    declared = {tuple(pair) for pair in overlap_pairs}
    if not declared.issubset(ALLOWED_OVERLAP_PAIRS):
        raise ValueError('undeclared or illegal action/dialogue overlap')
    for a, b in zip(schedule, schedule[1:]):
        if b['start'] < a['end'] - 1e-6:
            pair = (a['source_ref'], b['source_ref'])
            reverse = (b['source_ref'], a['source_ref'])
            continuous = pair == (PERSISTENT_WITH_REF, PERSISTENT_STATE_REF)
            if pair not in declared and reverse not in declared and not continuous:
                raise ValueError('source order violated by undeclared overlap')
    if rows['B1.S05']['start'] < rows['B1.S02']['end'] - 1e-6:
        raise ValueError('paper pushed before complete company notice')
    if rows['B1.S06']['start'] < rows['B1.S05']['end'] - 1e-6:
        raise ValueError('reading starts before paper arrives')
    if rows[PERSISTENT_STATE_REF]['start'] < rows['B1.S05']['end'] - 1e-6:
        raise ValueError('persistent reading state starts before paper arrives')
    return True


def compile_contract(raw, script):
    Draft202012Validator(schema(script)).validate(raw)
    sources = _source(script)
    raw_units = raw['B1']['semantic_units']
    covered = [ref for unit in raw_units for ref in unit['source_refs']]
    if covered != own_refs(script, 'B1'):
        raise ValueError('all seven B1 sources must be covered exactly once in order')
    clock, state, units, schedule, all_pairs = 0.0, deepcopy(INITIAL_STATE), [], [], []
    for index, unit in enumerate(raw_units, 1):
        _assert_no_dialogue_copy(unit, sources)
        refs = unit['source_refs']
        pair_list = [(p['action_ref'], p['dialogue_ref']) for p in unit['overlap_pairs']]
        if len(pair_list) != len(set(pair_list)) or not set(pair_list).issubset(ALLOWED_OVERLAP_PAIRS):
            raise ValueError('duplicate or illegal action/dialogue overlap')
        if any(a not in refs or b not in refs for a, b in pair_list):
            raise ValueError('overlap pair must belong to this complete semantic unit')
        persistent = unit['state_sources']
        if len(persistent) != len(set(persistent)) or set(persistent) != ({PERSISTENT_STATE_REF} & set(refs)):
            raise ValueError('persistent state source declaration differs from owned source')
        if PERSISTENT_STATE_REF in refs and PERSISTENT_WITH_REF not in refs:
            raise ValueError('S07 persistent state must share the S06 reading unit')
        unit_start, start_state = clock, deepcopy(state)
        local, consumed = {}, set()
        for ref in refs:
            if ref in consumed or ref == PERSISTENT_STATE_REF:
                continue
            pair = next((p for p in pair_list if ref in p), None)
            if pair:
                action_ref, dialogue_ref = pair
                action_seconds = _seconds(sources[action_ref], action_ref)
                dialogue_seconds = _seconds(sources[dialogue_ref], dialogue_ref)
                start = clock
                if pair == ('B1.S05', 'B1.S04'):
                    # The material is offered with the end of the current request,
                    # after the preceding complete company notice has finished.
                    action_start = start + max(0, dialogue_seconds - action_seconds)
                else:
                    action_start = start
                local[action_ref] = (action_start, action_start + action_seconds)
                local[dialogue_ref] = (start, start + dialogue_seconds)
                clock = max(local[action_ref][1], local[dialogue_ref][1])
                consumed.update(pair)
            else:
                seconds = _seconds(sources[ref], ref)
                local[ref] = (clock, clock + seconds)
                clock += seconds
                consumed.add(ref)
        content_end = clock
        clock += unit['post_pause_seconds']
        if PERSISTENT_STATE_REF in refs:
            local[PERSISTENT_STATE_REF] = (local[PERSISTENT_WITH_REF][0], clock)
        for ref in refs:
            source = sources[ref]
            start, end = local[ref]
            schedule.append({'source_ref': ref, 'unit_id': f'U{index:02}',
                             'source_kind': source['kind'], 'speaker': source['speaker'],
                             'original_text': source['text'], 'start': round(start, 6), 'end': round(end, 6),
                             'duration_seconds': 0.0 if ref in persistent else round(end - start, 6),
                             'persistent_state': ref in persistent})
        for ref in refs:
            state.update(TRANSITIONS.get(ref, {}))
        duration = clock - unit_start
        units.append({**deepcopy(unit), 'unit_id': f'U{index:02}',
                      'start': round(unit_start, 6), 'content_end': round(content_end, 6),
                      'end': round(clock, 6), 'duration_seconds': round(duration, 6),
                      'start_state': start_state, 'end_state': deepcopy(state),
                      'dispatch_ready': duration <= 15 + 1e-6,
                      'status': 'ready' if duration <= 15 + 1e-6 else 'needs_revision'})
        all_pairs.extend(pair_list)
    validate_timeline(schedule, script, all_pairs)
    return {'schema': VERSION, 'script_sha256': digest(script), 'raw_contract_sha256': digest(raw),
            'direction': deepcopy(raw['direction']), 'semantic_units': units, 'schedule': schedule,
            'complete_B1': True, 'whole_film_performance_complete': False,
            'unbuilt_beats': ['B2', 'B3', 'B4'], 'total_duration_seconds': round(clock, 6),
            'timing_assumption': {'normal_spoken_characters_per_second': NORMAL_SPOKEN_CHARACTERS_PER_SECOND,
                                  'action_seconds': deepcopy(CURRENT_ACTION_SECONDS),
                                  'measured_audio': False, 'fit_scaled': False},
            'needs_revision': any(not unit['dispatch_ready'] for unit in units),
            'overlap_pairs': [list(p) for p in all_pairs], 'final_state': state,
            'source_text_unchanged': True, 'creative_quality_passed': False,
            'actual_media_readability': None}


def pack_first(compiled, max_seconds=15, required_source_refs=('B1.S02', 'B1.S03')):
    if compiled.get('schema') != VERSION or compiled.get('script_sha256') != SOURCE_SHA:
        raise ValueError('different natural source compilation')
    if not 4 <= max_seconds <= 15:
        raise ValueError('native sample limit must remain within four to fifteen seconds')
    selected, seconds = [], 0.0
    for unit in compiled['semantic_units']:
        if not unit['dispatch_ready'] or seconds + unit['duration_seconds'] > max_seconds + 1e-6:
            break
        selected.append(deepcopy(unit))
        seconds += unit['duration_seconds']
    refs = [ref for unit in selected for ref in unit['source_refs']]
    ready = bool(selected) and set(required_source_refs).issubset(refs)
    return {'schema': VERSION + '/candidate', 'script_sha256': SOURCE_SHA,
            'compiled_sha256': digest(compiled), 'semantic_units': selected, 'source_refs': refs,
            'source_seconds': round(seconds, 6), 'duration_seconds': max(4, math.ceil(round(seconds, 6))) if ready else None,
            'dispatch_ready': ready, 'status': 'ready' if ready else 'needs_revision',
            'reason': None if ready else 'cannot fit complete notice and employee reply as intact semantic units',
            'start_state': deepcopy(selected[0]['start_state']) if selected else None,
            'end_state': deepcopy(selected[-1]['end_state']) if selected else None,
            'fit_scaled': False, 'full_film_complete': False}


def render_prompt(candidate, script, reference_description='复用同一位小林、同一位周姐及同一会议室的身份、服装与环境参考'):
    sources = _source(script)
    if (not candidate.get('dispatch_ready') or candidate.get('script_sha256') != SOURCE_SHA
            or candidate.get('duration_seconds') is None or candidate['duration_seconds'] > 15):
        raise ValueError('unready semantic candidate cannot be dispatched')
    refs = [ref for unit in candidate['semantic_units'] for ref in unit['source_refs']]
    if refs != candidate['source_refs'] or refs != own_refs(script, 'B1')[:len(refs)]:
        raise ValueError('first candidate source ownership changed')
    lines = [f"{candidate['duration_seconds']}秒，9:16竖屏，中国当代公司写实剧情。一段连贯的同场景对话表演。",
             reference_description + '。只有小林与周姐两人。',
             '自然中文普通话，正常谈话速度，允许话中动作、转移视线和接话；不按每句台词定格，不因每句台词切镜。',
             '动作与声音描述是演员指令，不朗读；下面原对白各说一次，不增对白，不译成其他语言。无字幕、旁白、配乐、标题和姓名标签。',
             '开始时双方已经坐在原位，文件夹合着，未签的纸笔在周姐一侧；身份和服装沿用参考，不重复入座。']
    for unit in candidate['semantic_units']:
        _assert_no_dialogue_copy(unit, sources)
        lines.extend(['连贯表演：' + unit['continuous_performance'],
                      '周姐目的：' + unit['zhou_intent'] + '；小林目的：' + unit['xiaolin_intent'] + '。',
                      '观察与机位：' + unit['camera'], '说话方式：' + unit['delivery']])
        for pair in unit['overlap_pairs']:
            if (pair['action_ref'], pair['dialogue_ref']) == ('B1.S01', 'B1.S02'):
                lines.append('打开文件夹与公司通知可以自然同时进行，不额外停下来等文件夹。')
            else:
                lines.append('纸笔在催看当前材料这句的末段送到手边；公司通知已完整说完，纸到位后才读原因栏。')
        for ref in unit['source_refs']:
            source = sources[ref]
            if source['kind'] == 'dialogue':
                lines.append(source['speaker'].split('（')[0] + '对白：「' + source['text'] + '」')
        if unit['post_pause_seconds'] > 0:
            lines.append(f"这个对话回合结束后仅保留{unit['post_pause_seconds']:g}秒有意义的消化，不添加新动作。")
    lines.append('纸笔最多从周姐侧送到小林近桌沿一次；未签名，小林不碰笔。结束在以上已列完整单元，不预演未列对白、拒签、收夹或出门。')
    prompt = '\n'.join(lines)
    for ref, source in sources.items():
        if source['kind'] == 'dialogue':
            expected = int(ref in refs)
            if prompt.count(source['text']) != expected:
                raise ValueError('current exact dialogue uniqueness or future isolation failed')
    return prompt
