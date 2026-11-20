from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import creative_natural_scene_performance_v3 as c

SOURCE = Path(__file__).resolve().parents[1] / 'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    raw = {'continuous_performance': '周姐边展开文件夹边说明公司安排，小林接收意外消息后自然接话，双方交换目光。',
           'zhou_intent': '把公司决定当面说清楚', 'xiaolin_intent': '说明自己并没有提出离开的意愿',
           'camera': '自然观察通知与接收通知的当前互动', 'delivery': '正常普通话说话，不赶字不定格',
           'post_pause_seconds': .2}
    return script, raw


def test_native_six_fields_current_sources_only_not_fake_complete_b1():
    script, raw = fixture()
    schema = c.schema(script)
    assert set(schema['properties']) == set(c.NATIVE_UNIT_FIELDS)
    assert schema['additionalProperties'] is False
    assert all(value.get('type') != 'array' for value in schema['properties'].values())
    assert list(c.current_catalog(script)) == ['B1.S01', 'B1.S02', 'B1.S03']
    result = c.compile_contract(raw, script)
    assert result['complete_current_interaction'] is True
    assert result['complete_B1'] is False
    assert result['whole_film_performance_complete'] is False
    assert result['source_refs'] == ['B1.S01', 'B1.S02', 'B1.S03']
    assert [r['source_ref'] for r in result['schedule']] == result['source_refs']
    assert result['unbuilt_source_refs'] == ['B1.S04', 'B1.S05', 'B1.S06', 'B1.S07']
    assert len(result['semantic_units']) == 1
    assert result['schedule'][0]['start'] == result['schedule'][1]['start'] == 0
    assert result['schedule'][2]['start'] >= result['schedule'][1]['end']


def test_exact_source_and_native_prose_unmodified_with_normal_local_timing():
    script, raw = fixture()
    before_script, before_raw = deepcopy(script), deepcopy(raw)
    result = c.compile_contract(raw, script)
    assert script == before_script and raw == before_raw
    assert result['native_raw_sha256'] == c.digest(raw)
    assert {field: result['semantic_units'][0][field] for field in c.NATIVE_UNIT_FIELDS} == raw
    assert all(r['original_text'] == c.catalog(script)[r['source_ref']]['text'] for r in result['schedule'])
    assert result['timing_assumption']['normal_spoken_characters_per_second'] == 3.3
    assert result['timing_assumption']['measured_audio'] is False
    assert result['all_native_values_preserved'] is True and result['fit_scaled'] is False
    changed = deepcopy(script)
    changed['beats'][0]['steps'][1]['text'] += '改字'
    with pytest.raises(ValueError, match='exact reviewed source380'):
        c.compile_contract(raw, changed)


def test_sample_has_one_complete_answer_with_no_future_content_and_never_fits_short_cap():
    script, raw = fixture()
    result = c.compile_contract(raw, script)
    candidate = c.pack_first(result)
    assert candidate['dispatch_ready'] is True
    assert candidate['duration_seconds'] <= 15
    assert candidate['complete_current_interaction'] is True and candidate['complete_B1'] is False
    prompt = c.render_prompt(candidate, script)
    for ref, source in c.catalog(script).items():
        if source['kind'] == 'dialogue':
            assert prompt.count(source['text']) == int(ref in c.CURRENT_SOURCE_REFS)
    assert '本段结束时文件夹已打开，纸和笔仍在周姐一侧，小林未碰笔' in prompt
    assert 'direction' not in candidate
    blocked = c.pack_first(result, max_seconds=4)
    assert blocked['dispatch_ready'] is False
    assert blocked['semantic_units'] == [] and blocked['duration_seconds'] is None
    assert blocked['fit_scaled'] is False
    with pytest.raises(ValueError, match='unready'):
        c.render_prompt(blocked, script)


def test_illegal_type_prose_reshaping_and_current_or_future_dialogue_copy_are_rejected():
    script, raw = fixture()
    invalid = deepcopy(raw)
    invalid['camera'] = {'item': '错误对象'}
    with pytest.raises(ValidationError):
        c.compile_contract(invalid, script)
    invalid = deepcopy(raw)
    invalid['direction'] = {'B1': '不能多出全片导演'}
    with pytest.raises(ValidationError):
        c.compile_contract(invalid, script)
    for ref in ('B1.S02', 'B1.S04', 'B1.S06'):
        invalid = deepcopy(raw)
        invalid['continuous_performance'] = c.catalog(script)[ref]['text']
        with pytest.raises(ValueError, match='dialogue copied'):
            c.compile_contract(invalid, script)
    result = c.compile_contract(raw, script)
    candidate = c.pack_first(result)
    altered = deepcopy(candidate)
    altered['semantic_units'][0]['delivery'] = '手动改写'
    with pytest.raises(ValueError, match='altered'):
        c.render_prompt(altered, script)
