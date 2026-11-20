"""Resume exactly one bounded review call from its original verified trace.

No earlier model call is repeated. A persisted submission, even with an unknown
outcome, cannot be retried by this entry. The original failure chain is retained.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from . import script_pair as gate
from .production_revision import parse_unique_json
from .review_evidence_patch import TRACE_SCHEMA, canonical_sha, trace_bytes


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def _exclusive(path, raw):
    with path.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _replace(path, raw):
    pending = path.with_name(path.name + '.pending')
    _exclusive(pending, raw)
    os.replace(pending, path)


def resume_review_chain(client, trace_path, *, dry_run=False):
    """Verify the unfinished chain, call its next allowed mode once, return report.

    ``trace_path`` is the original intended report (for example review_1.json).
    An invalid new response is preserved and raises; a valid semantic rejection
    is saved and returned with passed=False, exactly as review_pair would return.
    Neither this function nor a successful report generates video or artifacts.
    ``dry_run=True`` returns the verified next-call budget without writes/calls.
    """
    target = Path(trace_path).resolve()
    if not re.fullmatch(r'review_[1-9][0-9]*\.json', target.name):
        raise ValueError('Resume requires the original review_N.json trace path')
    if target.exists():
        raise ValueError('An existing final report cannot be resumed or overwritten')
    base, stem = target.parent, target.stem
    snapshots = {}

    def read(path):
        if path.resolve().parent != base:
            raise ValueError('Review trace files must stay in their original directory')
        raw = path.read_bytes()
        snapshots[path] = raw
        return raw

    chain_path = base / f'{stem}_attempt_chain.json'
    chain_raw = read(chain_path)
    chain = parse_unique_json(chain_raw)
    messages = parse_unique_json(read(base / f'{stem}_request_1.json'))
    prompt_path = gate.PROMPT_PATH.with_name('script_pair_review.md')
    prompt_raw = prompt_path.read_bytes()
    prompt = prompt_path.read_text(encoding='utf-8')
    if (not isinstance(messages, list) or len(messages) != 2
            or any(not isinstance(row, dict) for row in messages)
            or [row.get('role') for row in messages] != ['system', 'user']
            or messages[0].get('content') != prompt):
        raise ValueError('Original review request must use the current exact review prompt')
    payload = parse_unique_json(messages[1]['content'])
    binding = gate.script_review_binding(payload)
    if (payload.get('review_contract_schema') != gate.CURRENT_SCRIPT_REVIEW_SCHEMA
            or any(payload.get(key) != value for key, value in binding.items())
            or payload.get('validated_structure') != gate._review_structural_facts(payload['scripts'])):
        raise ValueError('Original review payload binding or structural facts changed')
    if (not isinstance(chain, dict) or set(chain) != {
            'schema', 'candidate_sha256', 'evidence_sha256', 'prompt_sha256', 'attempts'}
            or chain.get('schema') != TRACE_SCHEMA
            or any(chain.get(key) != value for key, value in binding.items())
            or chain.get('prompt_sha256') != _sha(prompt.encode('utf-8'))
            or not isinstance(chain.get('attempts'), list) or not chain['attempts']):
        raise ValueError('Original attempt chain identity or shape is invalid')

    retry = gate.ScriptReviewRetryState(payload, prompt)
    for number, recorded in enumerate(chain['attempts'], 1):
        request_raw = read(base / f'{stem}_request_{number}.json')
        if canonical_sha(parse_unique_json(request_raw)) != canonical_sha(retry.messages):
            raise ValueError('Saved request differs from exact replay messages')
        response_raw = read(base / f'{stem}_response_{number}.txt')
        if not response_raw:
            raise ValueError('Missing actual response: its outcome must be resolved before resuming')
        entry, effective = retry.consume(response_raw.decode('utf-8'), number)
        entry.update(request_sha256=_sha(request_raw), response_sha256=_sha(response_raw),
                     merged_report_sha256=None)
        merged_path = base / f'{stem}_merged_{number}.json'
        if entry['mode'] == 'evidence_patch' and effective is not None:
            merged_raw = read(merged_path)
            if canonical_sha(parse_unique_json(merged_raw)) != canonical_sha(effective):
                raise ValueError('Saved merged report differs from actual patch replay')
            entry['merged_report_sha256'] = _sha(merged_raw)
        elif merged_path.exists():
            raise ValueError('Unexpected merged report outside a real applied patch')
        if canonical_sha(entry) != canonical_sha(recorded):
            raise ValueError('Saved request/response/parent/merged/chain SHA or entry changed')
        if entry['valid']:
            raise ValueError('An already validated chain cannot consume another call')

    number = len(chain['attempts']) + 1
    retry.assert_can_call(number)
    # A request or receipt outside the chain may already have consumed a paid
    # call. Never treat absence from the chain as permission to submit again.
    pattern = re.compile(re.escape(stem) + r'_(?:request|response|merged)_(\d+)\.(?:json|txt)$')
    for path in base.iterdir():
        match = pattern.fullmatch(path.name)
        if match and int(match.group(1)) >= number:
            raise ValueError('A next request/response already exists; unknown submission cannot be retried')
    journal_path = base / f'{stem}_resume_{number}.json'
    backup_path = base / f'{stem}_attempt_chain.before_resume_{number}.json'
    if journal_path.exists() or backup_path.exists():
        raise ValueError('This continuation has already been reserved; do not repeat its model call')

    def unchanged():
        if prompt_path.read_bytes() != prompt_raw or any(p.read_bytes() != raw for p, raw in snapshots.items()):
            raise ValueError('Original trace or prompt changed during continuation')

    unchanged()
    if dry_run:
        return {'schema': 'script_review_resume_preflight/v1', 'status': 'ready_for_one_bounded_call',
                'trace_path': str(target), **binding, 'original_chain_sha256': _sha(chain_raw),
                'prior_attempts': number - 1, 'mode_attempts': copy.deepcopy(retry.mode_attempts),
                'next_attempt': number, 'next_mode': retry.mode,
                'model_calls': 0, 'files_written': 0, 'video_generation_submitted': False}
    request_raw = trace_bytes(retry.messages)
    journal = {'schema': 'script_review_resume/v1', 'status': 'reserved', 'started_at_bjt': _now(),
        'trace_path': str(target), **binding, 'prior_attempts': number - 1,
        'prior_mode_attempts': copy.deepcopy(retry.mode_attempts), 'attempt': number,
        'mode': retry.mode, 'original_chain_sha256': _sha(chain_raw),
        'original_chain_backup_path': str(backup_path), 'request_sha256': _sha(request_raw),
        'replayed_model_calls': 0, 'new_model_calls': 0, 'video_generation_submitted': False}
    _exclusive(journal_path, trace_bytes(journal))
    try:
        _exclusive(backup_path, chain_raw)
        _exclusive(base / f'{stem}_request_{number}.json', request_raw)
        unchanged()
        journal.update(status='submitted_outcome_unknown', submitted_at_bjt=_now(), new_model_calls=1)
        _replace(journal_path, trace_bytes(journal))
        response = client.chat_completion_tracked(retry.messages,
            caller='pre_video_script_review', temperature=0.1, json_mode=True, use_cache=False)
        response_raw = (response or '').encode('utf-8')
        _exclusive(base / f'{stem}_response_{number}.txt', response_raw)
        journal.update(status='response_received', response_received_at_bjt=_now(), response_sha256=_sha(response_raw))
        metadata = getattr(getattr(client, 'provider', None), 'last_response_metadata', {})
        if isinstance(metadata, dict):
            journal['response_metadata'] = {k: copy.deepcopy(metadata[k]) for k in (
                'content_processing', 'content_is_raw_http_response', 'response_id',
                'response_model', 'usage', 'finish_reason') if k in metadata}
        entry, effective = retry.consume(response or '', number)
        entry.update(request_sha256=_sha(request_raw), response_sha256=_sha(response_raw),
                     merged_report_sha256=None)
        if entry['mode'] == 'evidence_patch' and effective is not None:
            merged_raw = trace_bytes(effective)
            _exclusive(base / f'{stem}_merged_{number}.json', merged_raw)
            entry['merged_report_sha256'] = _sha(merged_raw)
        unchanged()
        chain['attempts'].append(entry)
        continued_raw = trace_bytes(chain)
        _replace(chain_path, continued_raw)
        journal.update(chain_sha256=_sha(continued_raw), mode_attempts=copy.deepcopy(retry.mode_attempts),
                       status='response_invalid' if not entry['valid'] else 'report_validated')
        if not entry['valid']:
            raise RuntimeError(f'Resumed review response failed the unchanged gate: {retry.error}')
        report = copy.deepcopy(retry.report)
        report.update(format_attempts=number, format_trace_sha256=_sha(continued_raw),
                      prompt_sha256=_sha(prompt.encode('utf-8')), legal_review_status='pending_human_review')
        evidence = payload['evidence']
        if evidence.get('script_reference_selection'):
            report['source_review_scope'] = {**evidence['review_source_scope'],
                'full_source_evidence_sha256': evidence['script_reference_selection']['full_source_evidence_sha256'],
                'source_evidence_projection': [{'source_id': row['source_id'], **row['evidence_projection']}
                                               for row in evidence['source_evidence']]}
        gate.validate_saved_script_review_report(report, payload)
        report_raw = trace_bytes(report)
        _exclusive(target, report_raw)
        journal.update(status='completed_passed' if report['passed'] else 'completed_rejected',
                       report_sha256=_sha(report_raw))
        return report
    except Exception as exc:
        journal['error_type'] = type(exc).__name__
        raise
    finally:
        journal['finished_at_bjt'] = _now()
        _replace(journal_path, trace_bytes(journal))
