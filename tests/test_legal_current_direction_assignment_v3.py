from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, Draft202012Validator
from src.content_factory import creative_legal_current_direction_performance_v2 as old
from src.content_factory import creative_legal_current_direction_performance_v3 as c

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/production_revisions/legal_dialogue_refinement_20261009/round_20/DELIVERABLE/FULL_SCRIPT.json'
RECEIPT = ROOT / 'data/production_revisions/legal_current_production_20261010/round_03/call_366_director_r1.json'


def fixture():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    receipt = json.loads(RECEIPT.read_text(encoding='utf-8-sig'))
    return script, receipt['output']


def test_original_366_only_local_count_bound_failed_and_full_values_preserved():
    before = hashlib.sha256(RECEIPT.read_bytes()).hexdigest()
    script, raw = fixture()
    errors = list(Draft202012Validator(old.direction_schema(script)).iter_errors(raw))
    assert len(errors) == 1
    assert list(errors[0].absolute_path) == ['B4', 'reaction_windows']
    assert errors[0].validator == 'maxItems' and errors[0].validator_value == 3
    assert len(raw['B4']['reaction_windows']) == 4
    result = c.expand_direction(raw, script)
    assert len(result['reaction_windows']) == 11
    assert [r for shot in result['shots'] for r in shot['source_refs']] == list(c.catalog(script))
    assert len(c.catalog(script)) == 19
    assert {name: result[name] for name in c.GLOBAL_FIELDS} == {name: raw[name] for name in c.GLOBAL_FIELDS}
    for shot in result['shots']:
        assert {name: shot[name] for name in c.CREATIVE_SHOT_FIELDS} == {
            name: raw[shot['beat_id']][name] for name in c.CREATIVE_SHOT_FIELDS}
    assert result['reaction_windows'] == [w for b in script['beats'] for w in raw[b['id']]['reaction_windows']]
    assert hashlib.sha256(RECEIPT.read_bytes()).hexdigest() == before
    assert json.loads(RECEIPT.read_text(encoding='utf-8-sig'))['status'] == 'contract_rejected'


def test_thirteen_global_windows_still_rejected():
    script, raw = fixture()
    invalid = deepcopy(raw)
    for phase in ('before', 'during'):
        invalid['B1']['reaction_windows'].append({
            'source_ref': 'B1.S01', 'phase': phase, 'observer': c.CHARACTERS[1],
            'minimum_seconds': .5, 'purpose': '独立窗口'})
    Draft202012Validator(c.direction_schema(script)).validate(invalid)
    with pytest.raises(ValidationError) as error:
        c.expand_direction(invalid, script)
    assert list(error.value.absolute_path) == ['reaction_windows']
    assert error.value.validator == 'maxItems' and error.value.validator_value == 12


def test_seven_local_windows_rejected():
    script, raw = fixture()
    invalid = deepcopy(raw)
    while len(invalid['B4']['reaction_windows']) < 7:
        invalid['B4']['reaction_windows'].append(deepcopy(invalid['B4']['reaction_windows'][0]))
    with pytest.raises(ValidationError) as error:
        c.expand_direction(invalid, script)
    assert list(error.value.absolute_path) == ['B4', 'reaction_windows']
