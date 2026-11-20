from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import creative_legal_acting_cues_v1 as c
from src.content_factory import creative_legal_current_direction_performance_v3 as direction_contract
from src.content_factory import creative_legal_current_direction_performance_v1 as performance

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/production_revisions/legal_dialogue_refinement_20261009/round_20/DELIVERABLE/FULL_SCRIPT.json'
DIRECTOR = ROOT / 'data/production_revisions/legal_current_production_20261010/round_03/call_366_director_r1.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    raw_direction = json.loads(DIRECTOR.read_text(encoding='utf-8-sig'))['output']
    direction = direction_contract.expand_direction(raw_direction, script)
    raw = {c.key(ref) + '_' + phase: ref + ' 原始 ' + phase + ' cue'
           for ref in c.own_refs(script, 'B1') for phase in c.PHASES}
    return script, direction, raw


def test_wire_only_fifteen_flat_string_fields_no_state_or_model_numbers():
    script, direction, raw = fixture()
    schema = c.schema(script, 'B1')
    assert len(schema['properties']) == 15
    assert all(p['type'] == 'string' for p in schema['properties'].values())
    assert schema['additionalProperties'] is False
    for field, value in [('B1_S01_before', .5), ('active_seconds', 8), ('state_changes', {})]:
        invalid = deepcopy(raw)
        invalid[field] = value
        with pytest.raises(ValidationError):
            c.expand_cues(invalid, script, 'B1', direction)


def test_complete_b1_original_cues_preserved_and_predeclared_timing_compiles():
    script, direction, raw = fixture()
    original = deepcopy(raw)
    result = c.expand_cues(raw, script, 'B1', direction)
    assert raw == original
    assert len(result['rows']) == 5
    assert result['cue_compilation']['all_original_cues_preserved'] is True
    assert result['cue_compilation']['numeric_model_response_repaired'] is False
    assert result['cue_compilation']['prior_response_spliced'] is False
    assert result['cue_compilation']['whole_film_performance_complete'] is False
    rows = {r['source_ref']: r for r in result['rows']}
    assert rows['B1.S01']['before_seconds'] == 1
    assert rows['B1.S01']['active_seconds'] == 1
    assert rows['B1.S01']['after_seconds'] == 0
    assert rows['B1.S02']['after_seconds'] == 1.5
    assert rows['B1.S03']['active_seconds'] == 2
    assert rows['B1.S03']['after_seconds'] == 1
    assert rows['B1.S04']['after_seconds'] == .5
    for row in result['rows']:
        for phase in c.PHASES:
            assert row[phase + '_performance'] == raw[c.key(row['source_ref']) + '_' + phase]
        if c.catalog(script)[row['source_ref']]['kind'] == 'dialogue':
            assert row['active_seconds'] >= performance.spoken_seconds(c.catalog(script)[row['source_ref']])
    compiled = performance.compile_prefix(script, direction, [result])
    assert len(compiled['schedule']) == 5 and compiled['complete'] is False
    assert compiled['final_state']['paper_location'] == 'xiaolin_near_edge'


def test_director_during_minimum_increases_action_time_without_changing_cue():
    script, direction, raw = fixture()
    changed = deepcopy(direction)
    changed['reaction_windows'].append({'source_ref': 'B1.S03', 'phase': 'during',
        'observer': c.CHARACTERS[0], 'minimum_seconds': 3, 'purpose': '观察纸笔到近沿'})
    result = c.expand_cues(raw, script, 'B1', changed)
    assert result['rows'][2]['active_seconds'] == 3
    assert result['rows'][2]['active_performance'] == raw['B1_S03_active']


def test_unknown_action_and_other_beat_are_rejected_without_guessing_time():
    script, direction, raw = fixture()
    with pytest.raises(ValueError, match='unconfigured original action duration'):
        c._declared_active_seconds({'kind': 'action', 'text': '新动作'}, 'B2.S01')
    with pytest.raises(ValueError, match='B1 only'):
        c.schema(script, 'B2')
    changed = deepcopy(script)
    changed['beats'][0]['steps'][0]['text'] += ' changed'
    with pytest.raises(ValueError, match='exact reviewed source'):
        c.schema(changed, 'B1')


def test_character_timing_rounds_up_to_tenth_and_never_shortens_director_window():
    assert c._declared_active_seconds({'kind': 'dialogue', 'text': '字' * 47}, 'B1.S02') == 10
    assert c._declared_active_seconds({'kind': 'dialogue', 'text': '字' * 48}, 'B1.S02') == 10.3
    script, direction, raw = fixture()
    invalid = deepcopy(direction)
    invalid['reaction_windows'][1]['minimum_seconds'] = 4
    with pytest.raises(ValidationError):
        c.expand_cues(raw, script, 'B1', invalid)
