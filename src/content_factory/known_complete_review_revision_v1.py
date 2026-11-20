"""Admit one full content revision from a complete, rejected native review.

Duplicate identities are diagnosed only. No projected review is accepted or
stored as a gate; the original explicit revise and confirmed issue are kept.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path

from . import natural_director_pipeline_v10 as source_route

runtime = source_route.parent
core = runtime.core
VERSION = 'known_complete_review_revision/v1'
RECORD = 'KNOWN_COMPLETE_REVIEW_REVISION_001.json'


def _diagnose(raw, binding, state, response_ref):
    review, adjudication = raw.get('full_review', {}), raw.get('adjudication', {})
    issues, duplicates = review.get('issues'), adjudication.get('new_issues')
    if (review.get('native_verdict') != 'revise' or review.get('whole_text_reviewed') is not True
            or review.get('source_complete') is not True or review.get('draft_complete') is not True
            or not isinstance(issues, list) or len(issues) != 1 or not isinstance(duplicates, list)
            or len(duplicates) != 1 or issues[0] != duplicates[0]):
        raise ValueError('只支持明确全文revise及一个完全相同的已确认内容issue副本')
    issue = issues[0]; dispositions = adjudication.get('dispositions', [])
    if (issue.get('finding_status') != 'confirmed' or issue.get('severity_certainty') != 'confirmed'
            or issue.get('severity') not in {'minor', 'major', 'blocking'}
            or not issue.get('dimensions') or not issue.get('event_ids') or not issue.get('evidence') or not issue.get('impact')
            or len(dispositions) != 1 or dispositions[0].get('issue_id') != issue.get('issue_id')
            or dispositions[0].get('disposition') != 'confirmed' or not dispositions[0].get('basis')):
        raise ValueError('没有明确已确认的内容问题；不能因包装错误重写完整稿')
    checks = review.get('checks', [])
    dimensions = {row.get('dimension'): row for row in checks if isinstance(row, dict)}
    if (len(dimensions) != len(checks) or set(dimensions) != set(runtime.contracts.REVIEW_DIMENSIONS)
            or not set(issue['dimensions']).issubset(dimensions)
            or any(not row.get('assessment') or row.get('checked') is not True for row in checks)):
        raise ValueError('原生九维全文审查不完整')
    original_text = json.dumps(raw, ensure_ascii=False)
    kwargs = {'source_binding': binding['source']['binding_id'],
              'draft_binding': state['active']['writer_full']['file']['sha256'],
              'native_response_ref': response_ref, 'artifact_prefix': 'rejected-native-review'}
    try:
        runtime.roles.parse_review_bundle(original_text, **kwargs)
    except ValueError as exc:
        if str(exc) != 'Issue identity duplicated':
            raise ValueError('原生审查不是精确重复身份拒绝') from None
    else:
        raise ValueError('原生审查原本未被重复身份拒绝')
    # This in-memory rejection diagnostic is never returned, stored or used as
    # a passed bundle. Full validators still check all other ledger/review rows.
    diagnostic_copy = deepcopy(raw); diagnostic_copy['adjudication']['new_issues'] = []
    errors = [{'code': 'ISSUE_IDENTITY_DUPLICATED', 'location': '$.adjudication.new_issues[0]',
               'message': 'Exact value-identical copy of full_review.issues[0]; original native remains rejected.'}]
    try:
        runtime.roles.parse_review_bundle(json.dumps(diagnostic_copy, ensure_ascii=False), **kwargs)
    except ValueError as exc:
        prefix = 'Auxiliary review contract invalid: '
        if not str(exc).startswith(prefix):
            raise ValueError('重复之外存在未知审查合同错误') from None
        additional = json.loads(str(exc)[len(prefix):])
        expected_locations = {'$.issues', '$.issues[0].dimensions'}
        if (not additional or any(e.get('code') != 'REVIEW_ISSUE_COVERAGE' or e.get('location') not in expected_locations for e in additional)
                or any(row.get('issue_ids') != [] for row in checks)):
            raise ValueError('重复之外存在不支持的审查错误，不能继续') from None
        errors.extend(additional)
    return issue, errors


def _claim_path(run, source_binding, draft_sha, review_sha):
    identity = core._digest({'source': source_binding, 'draft': draft_sha, 'review': review_sha})
    root = Path(runtime.CANONICAL_REGISTRY).resolve() / '_known_complete_review_revisions'
    for path in root.glob('*/*.json'):
        row = core._read(path)
        if row.get('identity') == identity and Path(row.get('run_dir', '')).resolve() != run:
            raise RuntimeError('同一完整原生审查已有唯一返修owner')
    return root / 'v1' / (identity + '.json'), identity


def plan_revision(run_dir, *, _lock_owner=None):
    run = Path(run_dir).resolve(); lock = run / '.execution.lock'
    if lock.exists() and core._read(lock).get('owner') != _lock_owner:
        raise ValueError('源运行仍在执行')
    if (run / '.graph_driver.lock').exists():
        raise ValueError('源图运行仍在执行')
    source_route._source_route(run); b, s = runtime._verify(run)
    if (s['status'] != 'needs_attention' or s['stage'] != 'review_full' or s.get('halt_reason') != 'Issue identity duplicated'
            or s['calls_started'] != 2 or s['pending_call'] is not None or s['reported_tokens'] is None
            or set(s['active']) != {'writer_full'} or s['revisions_used'] or s['quality_revisions_used']
            or s['director_revisions_used'] or s['clarifications_used'] or s['full_reviews_used'] != 1):
        raise ValueError('不是首稿完整已知全文审查重复issue的有界返修停点')
    if b['budget']['max_revisions'] < 1 or b['budget']['max_calls'] - s['calls_started'] < 2:
        raise ValueError('原整稿返修或调用容量不足，不增加预算')
    qp, rp = run / 'REQUEST_002.json', run / 'RESPONSE_002.json'
    request, response = core._read(qp), core._read(rp)
    errors, tokens, text = runtime._response_evidence(response, b)
    if errors or tokens is None or request['stage'] != 'review_full' or request['role'] != 'director' or response['request_binding'] != core._binding(qp):
        raise ValueError('原审查结果、结束、用量或请求身份未知')
    payload = runtime._build_stage_payload(b, s); messages, parameters = runtime._request_spec(b, 'review_full', payload)
    if request['messages'] != messages or request['parameters'] != parameters or request['input_bindings'] != s['active']:
        raise ValueError('DeepSeek没有收到同一完整源、完整稿和冻结要求')
    writer = s['active']['writer_full']; writer_response = core._read(writer['receipt']['path'])
    writer_errors, writer_tokens, writer_text = runtime._response_evidence(writer_response, b)
    if (writer_errors or writer_tokens is None or Path(writer['file']['path']).read_bytes() != writer_text.encode()
            or writer_tokens + tokens != s['known_reported_tokens'] or writer_response.get('stage') != 'writer_full'):
        raise ValueError('原完整稿及两次累计用量证据不符')
    raw = runtime.roles.parse_json(text); issue, diagnostics = _diagnose(raw, b, s, core._binding(rp)['sha256'])
    target = deepcopy(s); target.pop('halt_reason', None)
    target.update(status='needs_full_revision', stage='writer_full', previous_draft=writer_text, previous_bundle=None,
        feedback={'native_review_text': text, 'native_review_request': core._binding(qp), 'native_review_response': core._binding(rp),
            'native_verdict': 'revise', 'confirmed_content_issue_id': issue['issue_id'], 'responsibility_layer': 'writer',
            'program_contract_errors': diagnostics, 'old_review_accepted': False,
            'required_action': 'MiniMax提交完整新自然文本稿后重新同源全文审核；不能手工补丁或采用旧审查为通过。'})
    new_payload = runtime.roles.build_writer_payload(b['source'], previous_draft=writer_text, feedback=target['feedback'], brief=b['brief'])
    m, p = runtime._request_spec(b, 'writer_full', new_payload)
    reserve = len(json.dumps({'messages': m, 'parameters': p}, ensure_ascii=False).encode()) + p['max_tokens'] + 4096
    if s['known_reported_tokens'] + reserve > b['budget']['max_total_tokens']:
        raise ValueError('完整新稿请求的原预算预留不足，不截稿或扩大预算')
    files = {run / n for n in ('BINDING.json', 'BINDING_ANCHOR.json', 'state.json', 'WRITER_ONLY_ROUTE.json', 'WRITER_ONLY_ROUTE_ANCHOR.json')}
    for pattern in ('STATE_*.json', 'REQUEST_*.json', 'RESPONSE_*.json', 'CLAIM_*.json', 'CALL_LEDGER_*.json', 'LOCAL_WRITER_RECOVERY_*.json'):
        files.update(run.glob(pattern))
    files.add(Path(writer['file']['path'])); snapshots = sorted(run.glob('STATE_*.json'))
    target_path = run / f'STATE_{len(snapshots)+1:05}.json'
    claim_path, identity = _claim_path(run, b['source']['binding_id'], writer['file']['sha256'], core._binding(rp)['sha256'])
    return {'schema': VERSION, 'status': 'known_complete_content_revision_proven', 'run_dir': str(run),
        'source_binding': b['source']['binding_id'], 'draft_binding': writer['file']['sha256'],
        'review_response': core._binding(rp), 'confirmed_content_issue': issue, 'program_contract_errors': diagnostics,
        'evidence': [core._binding(path) for path in sorted(files)], 'original_stop': core._binding(snapshots[-1]),
        'target_state': target, 'target_checkpoint': runtime._prepared_json_binding(target_path, target),
        'claim_path': str(claim_path), 'claim_identity': identity, 'calls_started': s['calls_started'],
        'reported_tokens': s['known_reported_tokens'], 'revisions_used': s['revisions_used'],
        'new_writer_reservation': reserve, 'budget': b['budget'], 'recovery_code': core._binding(Path(__file__).resolve()),
        'old_review_accepted': False, 'model_calls_started': 0, 'content_modified': False}


def _finish_existing(run):
    record = core._read(run / RECORD); core._verify_file(record['recovery_code'])
    for row in record['historical_evidence']:
        core._verify_file(row)
    core._verify_file(record['claim']); core._verify_file(record['target_checkpoint'])
    snapshots = sorted(run.glob('STATE_*.json'))
    if core._binding(snapshots[-1]) != record['target_checkpoint']:
        raise ValueError('源运行已经推进，不允许再次回退领取返修')
    runtime._verify(run, _state_override=core._read(record['target_checkpoint']['path']))
    runtime._recover_state_projection(run); _, state = runtime._verify(run)
    return {'schema': VERSION, 'status': 'revision_prepared', 'stage': state['stage'],
        'calls_started': state['calls_started'], 'reported_tokens': state['reported_tokens'],
        'revisions_used': state['revisions_used'], 'model_calls_started': 0, 'old_review_accepted': False,
        'recovery_record': core._binding(run / RECORD)}


def apply_revision(run_dir, *, reviewed_plan):
    run = Path(run_dir).resolve()
    with core._lock(run / '.execution.lock') as owner:
        if (run / RECORD).exists() and Path(core._read(run / RECORD)['target_checkpoint']['path']).exists():
            return _finish_existing(run)
        current = plan_revision(run, _lock_owner=owner)
        if current != reviewed_plan:
            raise ValueError('原native内容、当前stop或已审查计划变化')
        with core._lock(Path(runtime.CANONICAL_REGISTRY).resolve() / '.registration.lock'):
            claim_path, identity = _claim_path(run, current['source_binding'], current['draft_binding'], current['review_response']['sha256'])
            claim = {'schema': VERSION, 'identity': identity, 'run_dir': str(run), 'source_binding': current['source_binding'],
                'draft_binding': current['draft_binding'], 'review_response': current['review_response'],
                'original_stop': current['original_stop'], 'max_recovery_applications': 1}
            core._ensure(claim_path, claim)
            record = {key: current[key] for key in ('source_binding', 'draft_binding', 'review_response', 'confirmed_content_issue',
                'program_contract_errors', 'original_stop', 'target_checkpoint', 'calls_started', 'reported_tokens',
                'revisions_used', 'budget', 'recovery_code', 'old_review_accepted', 'model_calls_started', 'content_modified')}
            record.update(schema=VERSION, claim=core._binding(claim_path), historical_evidence=[
                row for row in current['evidence'] if Path(row['path']).name != 'state.json'])
            core._ensure(run / RECORD, record)
            runtime._save_state(run, current['target_state'])
        return _finish_existing(run)
