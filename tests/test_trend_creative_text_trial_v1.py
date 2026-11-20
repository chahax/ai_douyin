"""Offline tests of the new entry with the actual existing receive/ledger control."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import run_trend_creative_text_trial_v1 as trial
from scripts.creative_resume_dispatch_v3 import ContinuationRuntime, read
from src.content_factory.creative_workflow_roles import RoleResult
from src.content_factory.creative_trend_bridge import build_packet, validate_direction
from test_creative_trend_bridge import source_fixture, direction_fixture, confirmation_fixture, NOW, REFERENCE, STANDARDS


@pytest.fixture
def data():
    source = source_fixture()
    source['account_profile']['domain_strategy_id'] = 'legal_services'
    source['account_profile']['allowed_formats'] = ['案例拆解']
    for key in ('collection_run', 'opportunity'):
        source[key]['domain_strategy_id'] = 'legal_services'
    packet = build_packet(source, REFERENCE.read_text(encoding='utf-8'),
                          json.loads(STANDARDS.read_text(encoding='utf-8')), now=NOW)
    direction = direction_fixture(packet)
    direction['account_fit']['proposed_format'] = '案例拆解'
    facts = json.loads((trial.PROJECT / 'data/qa/legal_new_batch_script_flow_20261007/round_01/LABOUR_LEGAL_FACTS.json').read_text(encoding='utf-8'))
    return packet, direction, facts


def test_actual_wire_carries_full_reference_standards_and_law_without_editing_preview(data):
    packet, _, facts = data
    before = deepcopy(packet)
    wire = trial.build_wire(packet, facts, 'direction', now=NOW)
    context = json.loads(wire['messages'][1]['content'])
    assert context['reference_fulltext'] == REFERENCE.read_text(encoding='utf-8')
    assert len(context['writer_expression_criteria']) == 6
    assert context['verified_legal_context'] == facts
    assert context['evidence_roles']['fresh_batch'].endswith('source videos not watched')
    assert packet == before and not packet['dispatch_allowed']
    assert wire['role'] == 'writer' and wire['model'] == 'MiniMax-M3'
    assert wire['parameters']['thinking'] == 'disabled'


@pytest.mark.parametrize('fault', ['unconfirmed', 'changed_direction', 'changed_packet', 'future_confirmation'])
def test_invalid_confirmation_never_constructs_writer_wire(data, fault):
    packet, direction, facts = data
    confirmation = confirmation_fixture(packet, direction)
    if fault == 'unconfirmed':
        confirmation = None
    elif fault == 'changed_direction':
        direction['creative_brief']['ending'] = '新的结尾'
    elif fault == 'changed_packet':
        confirmation['packet_sha256'] = 'wrong'
    else:
        confirmation['confirmed_at'] = '2030-01-01T00:00:00Z'
    with pytest.raises(ValueError):
        trial.build_wire(packet, facts, 'draft', now=NOW, direction=direction, confirmation=confirmation)


def test_stale_sample_and_missing_law_stop_before_wire(data):
    packet, _, facts = data
    with pytest.raises(ValueError, match='blocked'):
        trial.build_wire(packet, facts, 'direction', now='2026-10-15T04:00:00Z')
    with pytest.raises(ValueError, match='legal source'):
        trial.build_wire(packet, {}, 'direction', now=NOW)


def runtime_case(tmp_path):
    source = tmp_path / 'operator.py'
    source.write_text('offline fake only')
    calls = []
    provider = SimpleNamespace(handler=None)
    def call(*args, **kwargs):
        calls.append((args, kwargs))
        return provider.handler(*args, **kwargs)
    models = {'writer': {'model': 'MiniMax-M3'}, 'director': {'model': 'deepseek-flash'}}
    inherited = {'calls_started': 276, 'reported_tokens': 4642952,
                 'unknown_token_reservations': 93117, 'pending_ordinals': [70, 160]}
    rt = ContinuationRuntime(tmp_path, tmp_path / 'trial', [source], inherited, models,
                             client_factory=lambda: SimpleNamespace(call=call), quota_state=None)
    rt.prepare()
    return rt, calls, provider


def response(direction, *, tokens=101, finish='tool_calls', mode='tool_call'):
    envelope = {'payload_json': json.dumps(direction, ensure_ascii=False)}
    metadata = {'response_id': 'offline-only-response', 'finish_reason': finish,
                'output_mode': mode, 'response_body_complete': True}
    if tokens is not None:
        metadata['total_tokens'] = tokens
    return RoleResult(json.dumps(envelope), metadata, {'offline': True})


def test_source_bound_direction_replay_has_one_dispatch_and_preserves_old_spend(tmp_path, data):
    packet, direction, facts = data
    rt, calls, provider = runtime_case(tmp_path)
    provider.handler = lambda *a, **kw: response(direction)
    wire = trial.build_wire(packet, facts, 'direction', now=NOW)
    result = rt.dispatch('trend_direction_r1', wire, lambda v: validate_direction(v, packet))
    raw = (rt.root / 'call_277_trend_direction_r1.json').read_bytes()
    assert result['status'] == 'contract_valid' and result['document_output'] == direction
    rt.dispatch('trend_direction_r1', wire, lambda v: validate_direction(v, packet))
    assert len(calls) == 1 and (rt.root / 'call_277_trend_direction_r1.json').read_bytes() == raw
    assert rt.summary()['effective_calls_started'] == 277
    assert rt.summary()['effective_reported_tokens'] == 4643053
    assert read(rt.ledger)['starting_spend']['unknown_token_reservations'] == 93117
    assert not rt.summary()['old_budget_reset']


@pytest.mark.parametrize('fault,expected', [('timeout','outcome_unknown'), ('missing_tool','interface_rejected'),
                                           ('truncated','interface_rejected'), ('type','contract_rejected')])
def test_existing_receive_control_is_used_without_retry(tmp_path, data, fault, expected):
    packet, direction, facts = data
    rt, calls, provider = runtime_case(tmp_path)
    wire = trial.build_wire(packet, facts, 'direction', now=NOW)
    def handler(*a, **kw):
        if fault == 'timeout':
            raise TimeoutError('offline simulated timeout')
        if fault == 'missing_tool':
            return response(direction, finish='stop', mode='content')
        if fault == 'truncated':
            return response(direction, finish='length')
        broken = deepcopy(direction)
        broken['characters'] = {'item': broken['characters']}
        return response(broken)
    provider.handler = handler
    result = rt.dispatch('trend_direction_r1', wire, lambda v: validate_direction(v, packet))
    assert result['status'] == expected
    rt.dispatch('trend_direction_r1', wire, lambda v: validate_direction(v, packet))
    assert len(calls) == 1
    assert read(rt.ledger)['starting_spend']['reported_tokens'] == 4642952
    if fault == 'timeout':
        with pytest.raises(RuntimeError, match='unknown outcome'):
            rt.dispatch('next', dict(wire, operator_version='different explicit wire'), lambda v: {})
        assert len(calls) == 1
