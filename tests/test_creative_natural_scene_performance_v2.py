from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import creative_natural_scene_performance_v2 as c

SOURCE = Path(__file__).resolve().parents[1] / 'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    raw = {'direction': {beat['id']: {'observation': '当前人物的选择',
        'information_change': beat['id'] + '的新信息', 'cut_reason': '当前观察需求改变'}
        for beat in script['beats']}}
    for name in c.FIXED_UNITS:
        raw[name] = {'continuous_performance': name + '：自然接话与当前动作，不添加新对白',
            'zhou_intent': '说明公司安排并请对方看材料', 'xiaolin_intent': '弄清本人意愿是否被误写',
            'camera': '自然观察当前对话回合，不逐句切换', 'delivery': '正常普通话谈话速度',
            'post_pause_seconds': .1}
    return script, raw


def test_native_schema_has_no_array_and_fixed_mapping_covers_seven_steps():
    script, raw = fixture()
    def all_types(value):
        if isinstance(value, dict):
            yield value.get('type')
            for child in value.values():
                yield from all_types(child)
        elif isinstance(value, list):
            for child in value:
                yield from all_types(child)
    assert 'array' not in list(all_types(c.schema(script)))
    result = c.compile_contract(raw, script)
    assert [r['source_ref'] for r in result['schedule']] == c.own_refs(script, 'B1')
    assert [u['source_refs'] for u in result['semantic_units']] == [
        ['B1.S01', 'B1.S02', 'B1.S03'], ['B1.S04', 'B1.S05'], ['B1.S06', 'B1.S07']]
    assert result['overlap_pairs'] == [['B1.S01', 'B1.S02'], ['B1.S05', 'B1.S04']]
    assert result['schedule'][-1]['persistent_state'] is True
    assert result['schedule'][-1]['duration_seconds'] == 0


def test_source_and_all_native_values_unchanged_with_provenance_hashes():
    script, raw = fixture()
    source_before, raw_before = deepcopy(script), deepcopy(raw)
    result = c.compile_contract(raw, script)
    assert script == source_before and raw == raw_before
    assert result['native_schema'] == c.VERSION
    assert result['native_raw_sha256'] == c.digest(raw)
    assert result['mapped_contract_sha256'] == result['raw_contract_sha256']
    assert result['native_source_mapping']['all_native_values_preserved'] is True
    assert result['native_source_mapping']['failed_response_repaired'] is False
    for name, unit in zip(c.FIXED_UNITS, result['semantic_units']):
        assert {field: unit[field] for field in c.NATIVE_UNIT_FIELDS} == raw[name]
    assert all(row['original_text'] == c.catalog(script)[row['source_ref']]['text'] for row in result['schedule'])
    changed = deepcopy(script)
    changed['beats'][0]['steps'][1]['text'] += ' changed'
    with pytest.raises(ValueError, match='exact reviewed source380'):
        c.compile_contract(raw, changed)


def test_first_sample_has_complete_notice_and_employee_reply_with_no_future_dialogue():
    script, raw = fixture()
    result = c.compile_contract(raw, script)
    candidate = c.pack_first(result)
    assert candidate['dispatch_ready'] is True
    assert {'B1.S02', 'B1.S03'}.issubset(candidate['source_refs'])
    assert candidate['semantic_units'][0]['source_refs'] == ['B1.S01', 'B1.S02', 'B1.S03']
    assert candidate['duration_seconds'] <= 15 and candidate['fit_scaled'] is False
    prompt = c.render_prompt(candidate, script)
    for ref, source in c.catalog(script).items():
        if source['kind'] == 'dialogue':
            assert prompt.count(source['text']) == int(ref in candidate['source_refs'])
    assert c.catalog(script)['B1.S06']['text'] not in prompt


def test_illegal_native_types_extra_fields_and_item_wrappers_are_rejected_not_repaired():
    script, raw = fixture()
    invalid_cases = []
    bad_type = deepcopy(raw)
    bad_type['opening_exchange']['camera'] = {'item': '机位'}
    invalid_cases.append(bad_type)
    wrapper = deepcopy(raw)
    wrapper['opening_exchange'] = {'item': wrapper['opening_exchange']}
    invalid_cases.append(wrapper)
    leaked = deepcopy(raw)
    leaked['overlap_pairs'] = {'item': {'action_ref': 'B1.S05', 'dialogue_ref': 'B1.S02'}}
    invalid_cases.append(leaked)
    for invalid in invalid_cases:
        before = deepcopy(invalid)
        with pytest.raises(ValidationError):
            c.compile_contract(invalid, script)
        assert invalid == before


def test_full_current_or_future_dialogue_copied_into_acting_still_rejected():
    script, raw = fixture()
    for ref in ('B1.S02', 'B1.S04', 'B1.S06'):
        invalid = deepcopy(raw)
        invalid['opening_exchange']['continuous_performance'] = c.catalog(script)[ref]['text']
        with pytest.raises(ValueError, match='dialogue copied'):
            c.compile_contract(invalid, script)



def test_first_exchange_prompt_keeps_paper_on_zhou_side_and_native_badge_state():
    script, raw = fixture()
    result = c.compile_contract(raw, script)
    candidate = c.pack_first(result, max_seconds=8)
    assert candidate['dispatch_ready'] is True
    assert candidate['source_refs'] == ['B1.S01', 'B1.S02', 'B1.S03']
    prompt = c.render_prompt(candidate, script)
    assert '工牌已戴在小林胸前' in prompt
    assert '原参考中的道具位置和姿势不沿用' in prompt
    assert '纸和笔仍在周姐一侧，文件夹已打开，小林未碰笔' in prompt
    assert '纸笔最多从周姐侧送到小林近桌沿一次' not in prompt
    assert '纸笔在催看当前材料这句的末段送到手边' not in prompt
    assert c.catalog(script)['B1.S04']['text'] not in prompt
