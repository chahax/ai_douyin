"""Offline continuation preserves every paid-call slot and original response."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.trend_intelligence import script_pair as gate
from src.trend_intelligence.review_evidence_patch import TRACE_SCHEMA, trace_bytes
from src.trend_intelligence.review_resume import resume_review_chain
from src.trend_intelligence.saved_script_review import _verify_review_attempt_chain
from test_script_review_gate import review_case


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_history(base, payload, responses):
    prompt = gate.PROMPT_PATH.with_name('script_pair_review.md').read_text(encoding='utf-8')
    retry = gate.ScriptReviewRetryState(payload, prompt)
    chain = {'schema': TRACE_SCHEMA, **gate.script_review_binding(payload),
             'prompt_sha256': sha(prompt.encode('utf-8')), 'attempts': []}
    for number, response in enumerate(responses, 1):
        request_raw = trace_bytes(retry.messages)
        (base / f'review_1_request_{number}.json').write_bytes(request_raw)
        raw = response.encode('utf-8')
        (base / f'review_1_response_{number}.txt').write_bytes(raw)
        entry, effective = retry.consume(response, number)
        entry.update(request_sha256=sha(request_raw), response_sha256=sha(raw), merged_report_sha256=None)
        if entry['mode'] == 'evidence_patch' and effective is not None:
            merged = trace_bytes(effective)
            (base / f'review_1_merged_{number}.json').write_bytes(merged)
            entry['merged_report_sha256'] = sha(merged)
        chain['attempts'].append(entry)
    (base / 'review_1_attempt_chain.json').write_bytes(trace_bytes(chain))
    return retry, chain, prompt


@pytest.fixture
def four_calls(tmp_path, review_case):
    payload, valid, _ = review_case
    damaged = copy.deepcopy(valid)
    damaged['shot_audit'][0]['cross_field_evidence']['audio'] += '合成引文错误'
    response = json.dumps(damaged, ensure_ascii=False)
    retry, chain, prompt = write_history(tmp_path, payload, [response, '{bad JSON',
        json.dumps({'full_review_required': '合成原文说明必须完整复审。'}, ensure_ascii=False), response])
    assert retry.mode_attempts == {'full_report': 2, 'evidence_patch': 2}
    assert retry.mode == 'full_report'
    return tmp_path / 'review_1.json', payload, valid, retry, chain, prompt


class OneResponse:
    def __init__(self, response, callback=None):
        self.response, self.callback, self.calls = response, callback, []

    def chat_completion_tracked(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        if self.callback:
            self.callback()
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_dry_run_replays_history_without_reserving_or_calling(four_calls):
    target, _, _, _, _, _ = four_calls
    before = {p.name: p.read_bytes() for p in target.parent.iterdir()}
    result = resume_review_chain(None, target, dry_run=True)
    assert result['next_attempt'] == 5 and result['next_mode'] == 'full_report'
    assert result['mode_attempts'] == {'full_report': 2, 'evidence_patch': 2}
    assert result['model_calls'] == result['files_written'] == 0
    assert {p.name: p.read_bytes() for p in target.parent.iterdir()} == before


def test_resume_only_actual_fifth_full_call_and_saved_gate_replays_all_history(four_calls):
    target, payload, valid, retry, chain, prompt = four_calls
    originals = {p: p.read_bytes() for p in target.parent.iterdir()}
    client = OneResponse(json.dumps(valid, ensure_ascii=False))
    report = resume_review_chain(client, target)
    assert len(client.calls) == 1 and client.calls[0][0] == retry.messages
    assert client.calls[0][1] == {'caller': 'pre_video_script_review', 'temperature': 0.1,
                                  'json_mode': True, 'use_cache': False}
    assert report['passed'] and report['format_attempts'] == 5
    assert report['legal_review_status'] == 'pending_human_review'
    assert json.loads(target.read_bytes()) == report
    for p, raw in originals.items():
        if p.name == 'review_1_attempt_chain.json':
            assert (p.parent / 'review_1_attempt_chain.before_resume_5.json').read_bytes() == raw
        else:
            assert p.read_bytes() == raw
    continued = json.loads((target.parent / 'review_1_attempt_chain.json').read_bytes())
    assert continued['attempts'][:4] == chain['attempts']
    assert continued['attempts'][4]['mode'] == 'full_report'
    _verify_review_attempt_chain(report, payload, prompt, target.parent, 1, target.parent)
    journal = json.loads((target.parent / 'review_1_resume_5.json').read_bytes())
    assert journal['status'] == 'completed_passed' and journal['new_model_calls'] == 1
    assert journal['replayed_model_calls'] == 0
    assert journal['mode_attempts'] == {'full_report': 3, 'evidence_patch': 2}
    assert journal['video_generation_submitted'] is False
    assert journal['submitted_at_bjt'].endswith('+08:00')
    with pytest.raises(ValueError, match='existing final report'):
        resume_review_chain(client, target)
    assert len(client.calls) == 1


@pytest.mark.parametrize('file', ['review_1_request_2.json', 'review_1_response_1.txt',
                                'review_1_attempt_chain.json'])
def test_tampered_history_rejected_before_any_new_call(four_calls, file):
    target, _, valid, _, _, _ = four_calls
    p = target.parent / file
    if file.endswith('chain.json'):
        chain = json.loads(p.read_bytes())
        chain['attempts'][0]['response_sha256'] = '0' * 64
        p.write_bytes(trace_bytes(chain))
    else:
        p.write_bytes(p.read_bytes() + b' ')
    before = {p.name: p.read_bytes() for p in target.parent.iterdir()}
    client = OneResponse(json.dumps(valid, ensure_ascii=False))
    with pytest.raises(ValueError):
        resume_review_chain(client, target)
    assert client.calls == [] and not target.exists()
    assert {p.name: p.read_bytes() for p in target.parent.iterdir()} == before


@pytest.mark.parametrize('name', ['review_1_request_5.json', 'review_1_response_5.txt',
                                 'review_1_merged_5.json', 'review_1_resume_5.json'])
def test_pending_next_request_receipt_or_reservation_never_submits_twice(four_calls, name):
    target, _, valid, _, _, _ = four_calls
    (target.parent / name).write_text('{}', encoding='utf-8')
    client = OneResponse(json.dumps(valid, ensure_ascii=False))
    with pytest.raises(ValueError):
        resume_review_chain(client, target)
    assert client.calls == [] and not target.exists()


def test_unexpected_merged_report_is_not_accepted_as_a_real_patch(four_calls):
    target, _, valid, _, _, _ = four_calls
    (target.parent / 'review_1_merged_2.json').write_bytes(trace_bytes(valid))
    client = OneResponse(json.dumps(valid))
    with pytest.raises(ValueError, match='Unexpected merged'):
        resume_review_chain(client, target)
    assert not client.calls


def test_changed_payload_hash_does_not_become_a_new_candidate(four_calls):
    target, _, valid, _, _, _ = four_calls
    p = target.parent / 'review_1_request_1.json'
    request = json.loads(p.read_bytes())
    payload = json.loads(request[1]['content'])
    payload['candidate_sha256'] = '0' * 64
    request[1]['content'] = json.dumps(payload, ensure_ascii=False)
    p.write_bytes(trace_bytes(request))
    client = OneResponse(json.dumps(valid))
    with pytest.raises(ValueError, match='payload binding'):
        resume_review_chain(client, target)
    assert not client.calls


def test_exhausted_full_budget_has_no_extra_call(tmp_path, review_case):
    payload, valid, _ = review_case
    write_history(tmp_path, payload, ['{invalid'] * 3)
    client = OneResponse(json.dumps(valid))
    with pytest.raises(ValueError, match='余额已耗尽'):
        resume_review_chain(client, tmp_path / 'review_1.json')
    assert not client.calls
    assert not (tmp_path / 'review_1_request_4.json').exists()


def test_existing_valid_chain_cannot_be_reopened_even_if_report_file_missing(tmp_path, review_case):
    payload, valid, _ = review_case
    write_history(tmp_path, payload, [json.dumps(valid, ensure_ascii=False)])
    client = OneResponse(json.dumps(valid))
    with pytest.raises(ValueError, match='already validated'):
        resume_review_chain(client, tmp_path / 'review_1.json')
    assert not client.calls


def test_unknown_network_outcome_is_reserved_and_cannot_be_retried(four_calls):
    target, _, _, _, _, _ = four_calls
    client = OneResponse(ConnectionError('Synthetic uncertain outcome'))
    with pytest.raises(ConnectionError):
        resume_review_chain(client, target)
    journal = json.loads((target.parent / 'review_1_resume_5.json').read_bytes())
    assert journal['status'] == 'submitted_outcome_unknown' and journal['new_model_calls'] == 1
    assert not (target.parent / 'review_1_response_5.txt').exists()
    with pytest.raises(ValueError):
        resume_review_chain(client, target)
    assert len(client.calls) == 1 and not target.exists()


@pytest.mark.parametrize('kind', ['invalid_json', 'duplicate_json', 'bad_quote', 'no_response'])
def test_new_invalid_response_is_saved_without_manufacturing_a_report(four_calls, kind):
    target, _, valid, _, chain, _ = four_calls
    raw = json.dumps(valid, ensure_ascii=False)
    if kind == 'invalid_json': raw = '{invalid'
    elif kind == 'duplicate_json': raw = '{"checks":{},' + raw[1:]
    elif kind == 'bad_quote':
        value = copy.deepcopy(valid)
        value['shot_audit'][0]['cross_field_evidence']['audio'] += '仍不是真实原文'
        raw = json.dumps(value, ensure_ascii=False)
    else: raw = None
    client = OneResponse(raw)
    with pytest.raises(RuntimeError, match='unchanged gate'):
        resume_review_chain(client, target)
    assert len(client.calls) == 1 and not target.exists()
    assert (target.parent / 'review_1_response_5.txt').read_text(encoding='utf-8') == (raw or '')
    continued = json.loads((target.parent / 'review_1_attempt_chain.json').read_bytes())
    assert len(continued['attempts']) == 5 and continued['attempts'][:4] == chain['attempts']
    assert continued['attempts'][-1]['valid'] is False
    with pytest.raises(ValueError):
        resume_review_chain(client, target)
    assert len(client.calls) == 1


def test_real_negative_judgment_stays_negative_in_saved_report(four_calls):
    target, _, valid, _, _, _ = four_calls
    valid['checks']['spoken_fit'] = False
    valid['issues'] = [{'problem': '合成真实失败必须保留。',
                        'evidence': copy.deepcopy(valid['shot_audit'][0]['action_evidence'])}]
    report = resume_review_chain(OneResponse(json.dumps(valid, ensure_ascii=False)), target)
    assert report['passed'] is False and report['issues'] == valid['issues']
    journal = json.loads((target.parent / 'review_1_resume_5.json').read_bytes())
    assert journal['status'] == 'completed_rejected'


def test_trace_change_during_call_keeps_response_and_refuses_to_publish(four_calls):
    target, _, valid, _, _, _ = four_calls
    p = target.parent / 'review_1_response_1.txt'
    client = OneResponse(json.dumps(valid), callback=lambda: p.write_bytes(p.read_bytes() + b' '))
    with pytest.raises(ValueError, match='changed during continuation'):
        resume_review_chain(client, target)
    assert len(client.calls) == 1 and not target.exists()
    assert (target.parent / 'review_1_response_5.txt').exists()
