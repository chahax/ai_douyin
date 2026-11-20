from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import creative_legal_current_direction_performance_v2 as c

SOURCE = Path(__file__).resolve().parents[1] / 'data/production_revisions/legal_dialogue_refinement_20261009/round_20/DELIVERABLE/FULL_SCRIPT.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    raw = {'emotional_arc': '受压至拒签，压力暂退', 'causal_chain': '通知、催签、看清原因、拒签',
           'ending_intent': '争议尚未解决', 'spatial_design': '两人同室',
           'assets': [{'id': 'room', 'definition': '原会议室', 'story_function': '同场冲突'}]}
    for beat in script['beats']:
        beat_id = beat['id']
        raw[beat_id] = {name: beat_id + '原创意表述' for name in c.CREATIVE_SHOT_FIELDS}
        raw[beat_id]['reaction_windows'] = [{
            'source_ref': c.own_refs(script, beat_id)[-1], 'phase': 'after',
            'observer': c.CHARACTERS[0], 'minimum_seconds': .5, 'purpose': '消化当前刺激'}]
    return script, raw


def test_four_shots_own_all_sources_once_and_preserve_creative_values():
    script, raw = fixture()
    result = c.expand_direction(raw, script)
    assert [s['shot_id'] for s in result['shots']] == ['SH01', 'SH02', 'SH03', 'SH04']
    assert [s['beat_id'] for s in result['shots']] == ['B1', 'B2', 'B3', 'B4']
    assert [ref for shot in result['shots'] for ref in shot['source_refs']] == list(c.catalog(script))
    assert sum(len(s['source_refs']) for s in result['shots']) == 19
    assert result['initial_state'] == c.CURRENT_SOURCE_CONFIG['INITIAL']
    for shot in result['shots']:
        assert all(shot[name] == raw[shot['beat_id']][name] for name in c.CREATIVE_SHOT_FIELDS)
        assert shot['source_refs'] == c.own_refs(script, shot['beat_id'])
    assert result['reaction_windows'] == [w for b in script['beats'] for w in raw[b['id']]['reaction_windows']]


def test_cross_beat_reaction_reference_rejected():
    script, raw = fixture()
    raw['B1']['reaction_windows'][0]['source_ref'] = 'B2.S01'
    with pytest.raises(ValidationError):
        c.expand_direction(raw, script)


def test_changed_source_cannot_reuse_current_configuration():
    script, raw = fixture()
    changed = deepcopy(script)
    changed['beats'][0]['steps'][0]['text'] += ' changed'
    with pytest.raises(ValueError, match='exact reviewed source'):
        c.expand_direction(raw, changed)


def test_model_cannot_backfill_mechanical_mapping_or_initial_state():
    script, raw = fixture()
    for field, value in [('initial_state', c.CURRENT_SOURCE_CONFIG['INITIAL']),
                         ('source_assignments', {'B1_S04': 'SH02'}),
                         ('shots', [])]:
        invalid = deepcopy(raw)
        invalid[field] = value
        with pytest.raises(ValidationError):
            c.expand_direction(invalid, script)
    for field, value in [('shot_id', 'SH02'), ('beat_id', 'B2'), ('source_refs', ['B2.S01'])]:
        invalid = deepcopy(raw)
        invalid['B1'][field] = value
        with pytest.raises(ValidationError):
            c.expand_direction(invalid, script)
