"""Approved adjacent third segment; providers are simulated, media not called."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import run_selected_script_continuation_v5 as trial
from scripts.creative_evidenced_role_clients_v1 import parse_saved_response


def valid_native(script):
    return {'script_sha256': trial.SOURCE_SHA, 'source_refs': trial.REFS,
        'current_direction': {'information_change': '小林明确指出公司决定与个人原因的矛盾。',
            'observation': '保持小林面部和指尖动作的空间关系。',
            'stimulus_reaction': '承接已读清纸面，直接质问，不重复前段。',
            'cut_reason': '完整质问与接收后再结束本段。'},
        'performance': {'script_sha256': trial.SOURCE_SHA, 'source_refs': trial.REFS, 'availability': 'known',
            'continuous_performance': '小林从已读清纸面的状态直接质问，手指自然悬在原因栏上方，不碰纸，周姐听着。',
            'actor_goals': [{'actor_id': 'zhou', 'immediate_objective': '听完当前质问，未回复。',
                'source_reception': {'stimuli': [{'source_ref': 'B2.S01', 'channel': 'spoken', 'phase': 'current'}],
                    'response': '安静听完，没有未来软化或接话。'}},
                {'actor_id': 'xiaolin', 'immediate_objective': '问清公司决定为何成为自己的原因。',
                'source_reception': {'stimuli': [{'source_ref': 'B1.S04', 'channel': 'visible', 'phase': 'completed'}],
                    'response': '已读到纸面原因，质问由这个矛盾触发。'}}],
            'camera': '小林中近景保持连续，不用插切吞掉质问。', 'spoken_language': 'zh-CN',
            'dialogue_delivery': [{'source_ref': 'B2.S01', 'speech_tone': '正常普通话，带不信与委屈，不喊叫。',
                'listener_behavior': '周姐听完当前句，未提前回复。'}],
            'action_timings': [{'source_ref': 'B2.S02', 'duration_seconds': 4,
                'overlap_with': 'B2.S01', 'overlap_offset_seconds': 4.2}], 'post_reaction_seconds': 1.5,
            'ending_state': '小林手指悬在字上方未碰纸，周姐未开口，纸笔仍在周姐一侧，两人坐着。'}}


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


def test_real_completed_second_spend_and_native_tail_approval_are_carried():
    rp = trial.PARENT / 'call_503_continuation_performance.json'
    before = rp.read_bytes()
    inherited, binding, seed = trial.recovery_parent()
    assert inherited['calls_started'] == 504
    assert inherited['reported_tokens'] == 7724173
    assert inherited['calls_with_known_usage'] == 502
    assert inherited['unknown_token_reservations'] == 93117
    assert inherited['pending_ordinals'] == [70, 160]
    assert seed['status'] == 'contract_valid'
    assert 'document_output' in seed
    assert rp.read_bytes() == before
    assert binding['format_recovery_attempts_remaining'] == 0
    assert binding['current_segment_content_revision_index'] == 0
    assert binding['historical_previous_segment_content_revision_index'] == 2
    assert trial.approved_frame()['source_task_id'] == 'cgt-20261011223449-wsn9f'
    assert trial.approved_frame()['sha256'] == 'a980fb18daa9d8f421102f0e989d05ba1de10e7cb2c92b326c7a1c1e4a9c07bc'


def test_prepare_is_idempotent_and_relocation_cannot_claim_another_recovery(monkeypatch, tmp_path):
    isolated_project(monkeypatch, tmp_path)
    first = trial.prepare()
    assert first['new_calls'] == 0 and first['effective_calls_started'] == 504
    assert trial.prepare() == first
    claim = next((tmp_path / 'data/creative_continuation_stages').glob('*/CLAIM.json'))
    before = claim.read_bytes()
    monkeypatch.setattr(trial, 'ROOT', tmp_path / 'different_directory')
    with pytest.raises(RuntimeError, match='immutable artifact changed'):
        trial.prepare()
    assert claim.read_bytes() == before


def test_existing_second_media_blocks_recovery_before_claim(monkeypatch, tmp_path):
    isolated_project(monkeypatch, tmp_path)
    media = tmp_path / 'data/video_generation/legal_script487_trial_20261011/third_v2/receipt.json'
    media.parent.mkdir(parents=True)
    media.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError):
        trial.prepare()
    assert not (tmp_path / 'data/creative_continuation_stages').exists()


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
    assert [r['ordinal'] for r in ledger['calls']] == [505, 506]
    writer = trial.control.read(trial.ROOT / ledger['calls'][0]['receipt'])
    assert writer['request']['content_revision_policy']['max_new_requests'] == 1
    assert writer['request']['content_revision_policy']['revision_index'] == 0
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
    sibling = tmp_path / 'data/video_generation/legal_script487_trial_20261011/third_v2/receipt.json'
    sibling.parent.mkdir(parents=True)
    sibling.write_text('{"status":"failed"}', encoding='utf-8')
    with pytest.raises(ValueError, match='another original third-segment submission exists'):
        trial.make_plan()
