"""One scoped offline test for v15 B4 structure and captured callback lifecycle."""
from copy import deepcopy
from types import SimpleNamespace
import json
import socket
import pytest
from jsonschema import ValidationError
from scripts import run_legal_ending_revision_v15 as m

PARENT = m.PROJECT / m.PARENT
CURRENT = m.PROJECT / 'data/production_revisions/legal_ending_withdrawal_revision_20261011/round_03'


def test_four_step_actual_request_rejects431_accepts_temp_fixture_and_never_reenters(monkeypatch, tmp_path):
    def network_denied(*args, **kwargs):
        raise AssertionError('offline validation must not call any service')
    monkeypatch.setattr(socket.socket, 'connect', network_denied)
    monkeypatch.setattr(socket, 'create_connection', network_denied)
    root = tmp_path / 'four_steps'
    root.mkdir()
    m.control.write(root / 'SETUP.json', m.control.read(CURRENT / 'SETUP.json'))
    op = m.Revision(root)
    monkeypatch.setattr(op, 'runtime', lambda: SimpleNamespace(prepare=lambda: None))
    monkeypatch.setattr(op, 'summary', lambda: {})
    op.prepare()
    old = m.control.read(PARENT / 'call_431_complete_draft.json')
    original = deepcopy(old['output'])
    old_before = deepcopy(old)
    fixture = deepcopy(original)
    # This whole temporary fixture checks the contract only. It is never saved as a production draft.
    fixture['beats'][3]['steps'] = [deepcopy(original['beats'][3]['steps'][i]) for i in [0, 1, 3, 4]]
    fixture_before = deepcopy(fixture)
    phase = {'inflight': False, 'validated': False}
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError('captured validator re-entered in-flight runtime or accepted receipt')
    monkeypatch.setattr(op, 'accepted', forbidden)
    monkeypatch.setattr(op, 'script', forbidden)
    monkeypatch.setattr(op, 'prepare', lambda: None)

    def dispatch(label, request, validator):
        calls.append((label, deepcopy(request)))
        phase['inflight'] = True
        with pytest.raises(ValidationError):
            validator(deepcopy(original))
        valid = validator(deepcopy(fixture))
        assert valid['full_model_script'] is True
        assert valid['creative_text_changed_locally'] is False
        assert valid['creative_quality_passed'] is False
        expected = m.prior.compile_writer_script(fixture, m.control.read(root / 'INPUT.json')['source_direction'])
        assert valid['script_sha256'] == m.control.digest(expected)
        raw = deepcopy(expected)
        raw.pop('selected_candidate_id')
        assert raw == fixture
        bad_kind = deepcopy(fixture)
        bad_kind['beats'][3]['steps'][1].update(kind='dialogue', speaker='周姐（虚构人事主管）')
        with pytest.raises(ValidationError):
            validator(bad_kind)
        bad_hidden = deepcopy(fixture)
        bad_hidden['beats'][3]['steps'][1]['text'] = '周姐说“今天就到这儿。”'
        with pytest.raises(ValueError, match='dialogue hidden in action'):
            validator(bad_hidden)
        phase['validated'] = True
        return {'ordinal': 999, 'status': 'contract_rejected'}

    runtime = SimpleNamespace(dispatch=dispatch, check=forbidden, effective_receipt=forbidden)
    monkeypatch.setattr(op, 'runtime', lambda: runtime)
    result = op.dispatch('draft')
    assert len(calls) == 1 and phase['inflight'] and phase['validated']
    assert result['status'] == 'contract_rejected'
    label, request = calls[0]
    assert label == 'complete_draft'
    assert request['input_provenance']['operator_version'] == 'four_step_ending_revision/v15'
    assert request == m.control.read(root / 'request_previews/draft.json')
    body = json.loads(request['messages'][1]['content'])
    assert body['reference_fulltext'] == m.control.read(root / 'INPUT.json')['reference_fulltext']
    constraints = request['structured_schema']['properties']['beats']['items']['allOf']
    b4 = next(row for row in constraints if row['if']['properties']['id']['const'] == 'B4')
    steps = b4['then']['properties']['steps']
    assert steps['minItems'] == steps['maxItems'] == 4 and steps['items'] is False
    assert [(row['properties']['kind']['const'], row['properties']['speaker']['const']) for row in steps['prefixItems']] == [('dialogue', '周姐（虚构人事主管）'), ('action', ''), ('action', ''), ('action', '')]
    assert old == old_before and fixture == fixture_before
    assert m.control.read(PARENT / 'call_431_complete_draft.json') == old_before
    anchor = m.control.read(root / 'ANCHOR.json')
    inherited = anchor['inherited']
    parent_ledger = m.control.read(PARENT / 'CALL_LEDGER.json')
    assert inherited['calls_started'] == parent_ledger['starting_spend']['calls_started'] + 1
    assert inherited['reported_tokens'] == parent_ledger['starting_spend']['reported_tokens'] + old['response_metadata']['total_tokens']
    assert inherited['unknown_token_reservations'] == 93117
    assert anchor['budget_reset'] is False and anchor['automatic_retry'] is False
    assert not (root / 'FULL_MODEL_SCRIPT.json').exists()
