from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import creative_natural_scene_performance_v1 as c

SOURCE = Path(__file__).resolve().parents[1] / 'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    direction = {b['id']: {'observation': '当前拍人物选择', 'information_change': b['id'] + '信息改变',
                           'cut_reason': b['id'] + '观察对象改变'} for b in script['beats']}
    direction['B4']['information_change'] = '未来收夹出门哨兵内容'
    def unit(refs, pairs=None, states=None, pause=0):
        return {'source_refs': refs, 'continuous_performance': '两人在当前对话回合自然交换目光与回应，不额外填动作',
                'zhou_intent': '把公司安排告知并推进手续', 'xiaolin_intent': '听清公司是否要求自己离开',
                'camera': '随当前说话和接收反应自然观察，不按每句切换', 'delivery': '自然普通话和正常说话速度',
                'overlap_pairs': pairs or [], 'state_sources': states or [], 'post_pause_seconds': pause}
    raw = {'direction': direction, 'B1': {'semantic_units': [
        unit(['B1.S01', 'B1.S02'], [{'action_ref': 'B1.S01', 'dialogue_ref': 'B1.S02'}], pause=.2),
        unit(['B1.S03'], pause=.4),
        unit(['B1.S04', 'B1.S05', 'B1.S06', 'B1.S07'],
             [{'action_ref': 'B1.S05', 'dialogue_ref': 'B1.S04'}], ['B1.S07'])]}}
    return script, raw


def test_complete_source_and_cues_unchanged_with_explicit_natural_overlap():
    script, raw = fixture()
    before_source, before_raw = deepcopy(script), deepcopy(raw)
    result = c.compile_contract(raw, script)
    assert script == before_source and raw == before_raw
    assert result['complete_B1'] is True and result['whole_film_performance_complete'] is False
    assert [r['source_ref'] for r in result['schedule']] == c.own_refs(script, 'B1')
    assert len(result['schedule']) == 7
    for row in result['schedule']:
        assert row['original_text'] == c.catalog(script)[row['source_ref']]['text']
    rows = {r['source_ref']: r for r in result['schedule']}
    assert rows['B1.S01']['start'] == rows['B1.S02']['start']
    assert rows['B1.S05']['start'] < rows['B1.S04']['end']
    assert rows['B1.S05']['end'] == rows['B1.S04']['end']
    assert rows['B1.S06']['start'] >= rows['B1.S05']['end']
    assert result['timing_assumption']['normal_spoken_characters_per_second'] == 3.3
    assert result['timing_assumption']['measured_audio'] is False
    assert result['timing_assumption']['fit_scaled'] is False


def test_complete_coverage_duplicate_gap_and_wrong_type_are_rejected():
    script, raw = fixture()
    duplicate = deepcopy(raw)
    duplicate['B1']['semantic_units'][1]['source_refs'] = ['B1.S02', 'B1.S03']
    with pytest.raises(ValueError, match='covered exactly once'):
        c.compile_contract(duplicate, script)
    missing = deepcopy(raw)
    missing['B1']['semantic_units'][1]['source_refs'] = ['B1.S04']
    with pytest.raises(ValueError, match='covered exactly once'):
        c.compile_contract(missing, script)
    bad_type = deepcopy(raw)
    bad_type['B1']['semantic_units'][0]['delivery'] = 3.3
    with pytest.raises(ValidationError):
        c.compile_contract(bad_type, script)


def test_illegal_overlap_and_cross_unit_overlap_cannot_be_used():
    script, raw = fixture()
    invalid = deepcopy(raw)
    invalid['B1']['semantic_units'][2]['overlap_pairs'] = [{'action_ref': 'B1.S05', 'dialogue_ref': 'B1.S02'}]
    with pytest.raises(ValueError, match='illegal action/dialogue overlap'):
        c.compile_contract(invalid, script)
    invalid = deepcopy(raw)
    invalid['B1']['semantic_units'][1]['overlap_pairs'] = [{'action_ref': 'B1.S01', 'dialogue_ref': 'B1.S02'}]
    with pytest.raises(ValueError, match='must belong'):
        c.compile_contract(invalid, script)


def test_paper_must_arrive_before_reading_and_notice_finish_before_delivery():
    script, raw = fixture()
    result = c.compile_contract(raw, script)
    late = deepcopy(result['schedule'])
    rows = {r['source_ref']: r for r in late}
    rows['B1.S05']['end'] = rows['B1.S06']['start'] + 1
    with pytest.raises(ValueError):
        c.validate_timeline(late, script, result['overlap_pairs'])
    early = deepcopy(result['schedule'])
    rows = {r['source_ref']: r for r in early}
    rows['B1.S05']['start'] = rows['B1.S02']['end'] - .5
    with pytest.raises(ValueError, match='before complete company notice'):
        c.validate_timeline(early, script, result['overlap_pairs'])


def test_persistent_state_has_no_extra_wait_and_cannot_stand_alone():
    script, raw = fixture()
    result = c.compile_contract(raw, script)
    rows = {r['source_ref']: r for r in result['schedule']}
    assert rows['B1.S07']['persistent_state'] is True
    assert rows['B1.S07']['duration_seconds'] == 0
    assert rows['B1.S07']['start'] == rows['B1.S06']['start']
    assert rows['B1.S07']['end'] == result['semantic_units'][-1]['end']
    invalid = deepcopy(raw)
    last = invalid['B1']['semantic_units'][-1]
    last['source_refs'].remove('B1.S07')
    last['state_sources'] = []
    extra = deepcopy(last)
    extra.update(source_refs=['B1.S07'], overlap_pairs=[], state_sources=['B1.S07'])
    invalid['B1']['semantic_units'].append(extra)
    with pytest.raises(ValueError, match='must share the S06'):
        c.compile_contract(invalid, script)


def test_overlong_unit_needs_revision_without_scaling_or_splitting_words():
    script, raw = fixture()
    merged = deepcopy(raw['B1']['semantic_units'][0])
    merged['source_refs'] = c.own_refs(script, 'B1')
    merged['overlap_pairs'] += raw['B1']['semantic_units'][-1]['overlap_pairs']
    merged['state_sources'] = ['B1.S07']
    merged['post_pause_seconds'] = 0
    raw['B1']['semantic_units'] = [merged]
    result = c.compile_contract(raw, script)
    assert result['needs_revision'] is True
    assert result['semantic_units'][0]['duration_seconds'] > 15
    assert result['semantic_units'][0]['status'] == 'needs_revision'
    candidate = c.pack_first(result)
    assert candidate['dispatch_ready'] is False
    assert candidate['duration_seconds'] is None
    assert candidate['fit_scaled'] is False
    with pytest.raises(ValueError, match='cannot be dispatched'):
        c.render_prompt(candidate, script)


def test_first_candidate_includes_notice_and_reply_only_intact_units_future_isolated():
    script, raw = fixture()
    result = c.compile_contract(raw, script)
    candidate = c.pack_first(result)
    assert candidate['dispatch_ready'] is True
    assert candidate['source_refs'] == ['B1.S01', 'B1.S02', 'B1.S03']
    assert [u['unit_id'] for u in candidate['semantic_units']] == ['U01', 'U02']
    assert candidate['duration_seconds'] <= 15
    prompt = c.render_prompt(candidate, script)
    assert '未来收夹出门哨兵内容' not in prompt
    for ref, source in c.catalog(script).items():
        if source['kind'] == 'dialogue':
            assert prompt.count(source['text']) == int(ref in candidate['source_refs'])
    assert 'time_scale' not in candidate and 'fit_scale' not in prompt


def test_changed_source_and_copying_dialogue_into_cue_are_rejected():
    script, raw = fixture()
    changed = deepcopy(script)
    changed['beats'][0]['steps'][1]['text'] += '改字'
    with pytest.raises(ValueError, match='exact reviewed source380'):
        c.compile_contract(raw, changed)
    bad = deepcopy(raw)
    bad['B1']['semantic_units'][0]['continuous_performance'] = script['beats'][0]['steps'][1]['text']
    with pytest.raises(ValueError, match='dialogue copied'):
        c.compile_contract(bad, script)
