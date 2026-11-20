"""Known content revision and inherited spend; providers are simulated."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import run_selected_script_continuation_v4 as trial
from scripts.creative_evidenced_role_clients_v1 import parse_saved_response
from tests.test_creative_continuation_probe_contract_v3 import wire as valid_native


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('content-revision runner regression must stay offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


def isolated_project(monkeypatch, tmp_path):
    monkeypatch.setattr(trial, 'PROJECT', tmp_path)
    monkeypatch.setattr(trial, 'ROOT', tmp_path / 'trial')
    monkeypatch.setattr(trial, 'OUT', tmp_path / 'video')


def test_real502_failure_is_carried_as_spend_not_adopted_content():
    rp = trial.PARENT / 'call_502_continuation_performance.json'
    before = rp.read_bytes()
    inherited, binding, seed = trial.recovery_parent()
    assert inherited['calls_started'] == 502
    assert inherited['reported_tokens'] == 7708554
    assert inherited['calls_with_known_usage'] == 500
    assert inherited['unknown_token_reservations'] == 93117
    assert inherited['pending_ordinals'] == [70, 160]
    assert seed['status'] == 'contract_rejected'
    assert seed['failure']['category'] == 'validation'
    assert 'document_output' in seed
    assert rp.read_bytes() == before
    assert binding['format_recovery_attempts_remaining'] == 0
    assert binding['current_segment_content_revision_index'] == 2
    assert binding['old_native_adopted'] is False
    assert trial.approved_frame()['source_task_id'] == 'cgt-20261011192956-wrdkg'


def test_prepare_is_idempotent_and_relocation_cannot_claim_another_recovery(monkeypatch, tmp_path):
    isolated_project(monkeypatch, tmp_path)
    first = trial.prepare()
    assert first['new_calls'] == 0 and first['effective_calls_started'] == 502
    assert trial.prepare() == first
    claim = next((tmp_path / 'data/creative_content_revisions').glob('*/CLAIM.json'))
    before = claim.read_bytes()
    monkeypatch.setattr(trial, 'ROOT', tmp_path / 'different_directory')
    with pytest.raises(RuntimeError, match='immutable artifact changed'):
        trial.prepare()
    assert claim.read_bytes() == before


def test_existing_second_media_blocks_recovery_before_claim(monkeypatch, tmp_path):
    isolated_project(monkeypatch, tmp_path)
    media = tmp_path / 'data/video_generation/legal_script487_trial_20261011/second_v2/receipt.json'
    media.parent.mkdir(parents=True)
    media.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError):
        trial.prepare()
    assert not (tmp_path / 'data/creative_content_revisions').exists()


@pytest.mark.parametrize('review_failed', [False, True])
def test_repeat_text_reuses_one_writer_and_review_without_new_dispatch(monkeypatch, tmp_path, review_failed):
    isolated_project(monkeypatch, tmp_path)
    calls = []
    class Client:
        def call(self, role, messages, *, evidence, structured_schema, thinking, **kwargs):
            calls.append(role)
            x = trial.control.read(trial.ROOT / 'INPUT.json')
            if role == 'writer':
                native = valid_native(x['full_current_script'])
                text = trial.transport.encode_envelope(native, trial.contract.continuation_probe_schema(
                    x['full_current_script'], trial.COMPLETED, trial.REFS))
                model = 'MiniMax-M3'
            else:
                text = json.dumps({'script_sha256': trial.SOURCE_SHA,
                    'checks': [{'check': name, 'status': 'fail' if review_failed and name == 'initial_final_state' else 'pass', 'source_refs': trial.REFS,
                               'reason': 'explicit offline provider simulation'} for name in trial.REVIEW_CHECKS],
                    'revision_requirements': ['offline explicit state mismatch'] if review_failed else []}, ensure_ascii=False)
                model = 'deepseek-flash'
            payload = {'id': 'offline-' + role, 'model': model,
                'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                    'tool_calls': [{'type': 'function', 'function': {'name': 'submit_creative_json', 'arguments': text}}]}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}}
            raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            raw, manifest = evidence.save_body(raw, {'http_status_code': 200,
                'http_request_id': None, 'safe_response_headers': {}})
            return parse_saved_response(raw, manifest, role, model, thinking, structured_schema, evidence)
    monkeypatch.setattr(trial, 'BoundedFormatRoleClients', Client)
    first = trial.text()
    assert first['status'] == ('production_text_needs_attention' if review_failed else 'production_text_ready_for_single_continuation')
    assert calls == ['writer', 'director']
    assert trial.text() == first
    assert calls == ['writer', 'director']
    ledger = trial.control.read(trial.ROOT / 'CALL_LEDGER.json')
    assert [r['ordinal'] for r in ledger['calls']] == [503, 504]
    writer = trial.control.read(trial.ROOT / ledger['calls'][0]['receipt'])
    assert writer['request']['content_revision_policy']['max_new_requests'] == 1
    assert writer['request']['content_revision_policy']['revision_index'] == 2
    assert writer['request']['content_revision_policy']['format_recovery_attempts_remaining'] == 0
    assert 'format_recovery_policy' not in writer['request']
    if review_failed:
        assert not (trial.ROOT / 'VIDEO_TEXT_HANDOFF.json').exists()
        assert not (trial.OUT / 'receipt.json').exists()
        with pytest.raises(FileNotFoundError):
            trial.make_plan()
        return
    handoff = trial.control.read(trial.ROOT / 'VIDEO_TEXT_HANDOFF.json')
    assert not handoff['actual_video_quality_passed']
    assert not handoff['whole_film_direction_accepted']
    assert not (trial.OUT / 'receipt.json').exists()
    sibling = tmp_path / 'data/video_generation/legal_script487_trial_20261011/second_v2/receipt.json'
    sibling.parent.mkdir(parents=True)
    sibling.write_text('{"status":"failed"}', encoding='utf-8')
    with pytest.raises(ValueError, match='another original second-segment submission exists'):
        trial.make_plan()
