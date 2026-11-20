from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import creative_legal_current_direction_performance_v1 as c

SOURCE = Path(__file__).resolve().parents[1] / 'data/production_revisions/legal_dialogue_refinement_20261009/round_20/DELIVERABLE/FULL_SCRIPT.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    raw_direction = {
        'emotional_arc': '受压、质问、两次拒签、压力暂退',
        'causal_chain': '公司通知后催签，小林读到个人原因后两次拒绝',
        'ending_intent': '只停下签字，争议未解决',
        'spatial_design': '两人同一会议室',
        'initial_state': deepcopy(c.CURRENT_SOURCE_CONFIG['INITIAL']),
        'assets': [{'id': 'room', 'definition': '原会议室', 'story_function': '同场冲突'}],
        'shots': [], 'reaction_windows': [], 'source_assignments': {},
    }
    performances, raw_performances = [], []
    for beat in script['beats']:
        beat_id = beat['id']
        refs = c.own_refs(script, beat_id)
        shot_id = 'SH' + beat_id[1:]
        raw_direction['shots'].append({
            'shot_id': shot_id, 'beat_id': beat_id, 'new_information': '当前源的信息',
            'observation_target': '当前对话两人', 'framing': '两人中景',
            'stimulus_and_response': '由本拍触发对应反应', 'cut_reason': '信息对象改变'})
        raw_direction['reaction_windows'].append({
            'source_ref': refs[-1], 'phase': 'after', 'observer': c.CHARACTERS[0],
            'minimum_seconds': .5, 'purpose': '消化当前刺激'})
        raw = {}
        for ref in refs:
            raw_direction['source_assignments'][c.key(ref)] = shot_id
            active = max(2, c.spoken_seconds(c.catalog(script)[ref]))
            raw[c.key(ref)] = {'before_seconds': 0, 'before_performance': '不额外停顿',
                              'active_seconds': active, 'active_performance': '只演本源动作或原句',
                              'after_seconds': .5, 'after_performance': '不添动作的静止反应'}
        raw_performances.append(raw)
        performances.append(c.expand_performance(raw, script, beat_id))
    return script, raw_direction, c.expand_direction(raw_direction, script), raw_performances, performances


def test_current_source_all_19_steps_once_and_model_prose_preserved():
    script, _, direction, raw, performances = fixture()
    result = c.compile_complete(script, direction, performances)
    assert [r['source_ref'] for r in result['schedule']] == list(c.catalog(script))
    assert len(result['schedule']) == 19
    assert result['complete'] is True
    assert result['creative_quality_passed'] is False
    assert result['real_audio_or_video_verified'] is False
    for beat_raw, performance in zip(raw, performances):
        for row in performance['rows']:
            assert {k: row[k] for k in beat_raw[c.key(row['source_ref'])]} == beat_raw[c.key(row['source_ref'])]
            assert row['source_ref'] in c.catalog(script)


def test_paper_one_push_to_near_edge_and_b4_source_owned_retrieval_exit():
    script, _, direction, _, performances = fixture()
    result = c.compile_complete(script, direction, performances)
    rows = {r['source_ref']: r for r in result['schedule']}
    assert rows['B1.S03']['end_state']['paper_location'] == 'xiaolin_near_edge'
    assert rows['B4.S02']['end_state']['paper_location'] == 'xiaolin_near_edge'
    assert rows['B4.S03']['end_state']['paper_location'] == 'zhou_folder'
    assert rows['B4.S03']['end_state']['pen_location'] == 'zhou_folder'
    assert rows['B4.S03']['end_state']['folder_location'] == 'zhou_table_side'
    assert rows['B4.S03']['end_state']['zhou_position'] == 'seated_opposite'
    assert rows['B4.S05']['end_state']['zhou_position'] == 'walking_to_door'
    assert rows['B4.S05']['end_state']['folder_location'] == 'zhou_carried'
    assert result['final_state']['zhou_position'] == 'outside_room'
    assert result['final_state']['xiaolin_position'] == 'seated'
    assert all(r['end_state']['badge_location'] == 'xiaolin_neck' for r in rows.values())
    assert 'xiaolin_hands' not in result['final_state']


def test_changed_source_cannot_reuse_map_and_custom_explicit_config_is_possible():
    script, _, _, _, _ = fixture()
    changed = deepcopy(script)
    changed['beats'][0]['steps'][0]['text'] += ' changed'
    with pytest.raises(ValueError, match='exact reviewed source'):
        c.direction_schema(changed)
    explicit = deepcopy(c.CURRENT_SOURCE_CONFIG)
    explicit['SOURCE_SHA'] = c.digest(changed)
    assert c.direction_schema(changed, explicit)['type'] == 'object'


def test_model_cannot_send_state_or_return_wrong_performance_type():
    script, _, _, raw, _ = fixture()
    invalid = deepcopy(raw[0])
    invalid['B1_S03']['state_changes'] = {'paper_location': 'table_middle'}
    with pytest.raises(ValidationError):
        c.expand_performance(invalid, script, 'B1')
    with pytest.raises(ValidationError):
        c.expand_performance({'item': raw[0]}, script, 'B1')


def test_cross_beat_state_cannot_reset_and_no_manual_transition_patch():
    script, _, direction, _, performances = fixture()
    invalid = deepcopy(performances)
    invalid[1]['start_state']['paper_location'] = 'zhou_table_side'
    with pytest.raises(ValueError, match='cross-beat state'):
        c.compile_complete(script, direction, invalid)
    invalid = deepcopy(performances)
    invalid[0]['rows'][2]['state_changes'] = []
    with pytest.raises(ValueError, match='source-derived transitions'):
        c.compile_complete(script, direction, invalid)


def test_direction_source_assignment_cannot_cross_beat_or_orphan():
    script, raw_direction, _, _, _ = fixture()
    invalid = deepcopy(raw_direction)
    invalid['source_assignments']['B1_S05'] = 'SH2'
    with pytest.raises(ValueError, match='crosses beat'):
        c.expand_direction(invalid, script)
    invalid = deepcopy(raw_direction)
    invalid['source_assignments']['B1_S05'] = 'NONEXISTENT'
    with pytest.raises(ValueError, match='unknown/orphan'):
        c.expand_direction(invalid, script)


def test_reaction_window_and_dialogue_minimum_are_enforced():
    script, _, direction, raw, performances = fixture()
    invalid = deepcopy(performances)
    invalid[2]['rows'][-1]['after_seconds'] = 0
    with pytest.raises(ValueError, match='reaction window'):
        c.compile_complete(script, direction, invalid)
    too_fast = deepcopy(raw[0])
    too_fast['B1_S02']['active_seconds'] = 1
    with pytest.raises(ValidationError):
        c.expand_performance(too_fast, script, 'B1')


def test_single_step_15_seconds_and_total_180_seconds_are_enforced():
    script, _, direction, _, performances = fixture()
    invalid = deepcopy(performances)
    invalid[0]['rows'][0].update(before_seconds=3, active_seconds=13, after_seconds=.5)
    with pytest.raises(ValueError, match='single source step exceeds 15'):
        c.compile_complete(script, direction, invalid)
    invalid = deepcopy(performances)
    for performance in invalid:
        for row in performance['rows']:
            row.update(active_seconds=13, before_seconds=0, after_seconds=2)
    with pytest.raises(ValueError, match='180 seconds'):
        c.compile_complete(script, direction, invalid)


def test_prefix_has_five_current_sources_and_is_not_complete_production():
    script, _, direction, _, performances = fixture()
    result = c.compile_prefix(script, direction, performances[:1])
    assert len(result['schedule']) == 5
    assert result['complete'] is False
    assert result['final_state']['paper_location'] == 'xiaolin_near_edge'
    with pytest.raises(ValueError, match='complete performance required'):
        c.compile_complete(script, direction, performances[:1])


def test_config_cannot_move_state_on_dialogue_source():
    script, _, _, _, _ = fixture()
    invalid = deepcopy(c.CURRENT_SOURCE_CONFIG)
    invalid['TRANSITIONS']['B1.S02'] = invalid['TRANSITIONS'].pop('B1.S03')
    with pytest.raises(ValueError, match='original action source'):
        c.direction_schema(script, invalid)
