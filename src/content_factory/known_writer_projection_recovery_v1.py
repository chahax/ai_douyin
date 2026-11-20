"""Recover one proven local publication failure without another model call.

Only the first complete native writer and its already-published immutable
review-stage snapshot are eligible. This module neither reviews nor dispatches.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path

from . import natural_director_pipeline_v10 as source_route

runtime = source_route.parent
core = runtime.core
VERSION = 'known_writer_projection_recovery/v1'
RECORD = 'LOCAL_WRITER_RECOVERY_001.json'


def plan_recovery(run_dir, *, _lock_owner=None):
    """Read-only proof; a valid native body alone does not grant a new request."""
    run = Path(run_dir).resolve()
    lock = run / '.execution.lock'
    if lock.exists() and core._read(lock).get('owner') != _lock_owner:
        raise ValueError('源运行执行锁存在')
    if (run / '.graph_driver.lock').exists():
        raise ValueError('源运行图执行锁存在')
    source_route._source_route(run)
    binding, state = runtime._verify(run)
    paths = sorted(run.glob('STATE_*.json'))
    if ([p.name for p in paths] != [f'STATE_{n:05}.json' for n in range(1, 6)]
            or state['status'] != 'needs_attention' or state['stage'] != 'writer_full'
            or state['calls_started'] != 1 or state['pending_call'] is not None
            or state['reported_tokens'] is None or state['active']
            or not str(state.get('halt_reason', '')).startswith('[WinError 5]')
            or '.state-' not in state['halt_reason'] or 'state.json' not in state['halt_reason']):
        raise ValueError('不属于首份完整writer的已知本地投影故障')
    if any(state[k] for k in ('revisions_used', 'director_revisions_used', 'clarifications_used',
                             'draft_clarifications_used', 'full_reviews_used')):
        raise ValueError('源阶段计数不符合首份writer恢复范围')
    initial, admitted, adopted, published, stopped = [core._read(p) for p in paths]
    if (initial['calls_started'] != 0 or admitted['pending_call'] != 1
            or adopted['pending_call'] is not None or adopted['active']
            or adopted['status'] != 'running' or adopted['stage'] != 'writer_full'):
        raise ValueError('本地检查点轨迹不符')
    expected_stop = {**adopted, 'status': 'needs_attention', 'halt_reason': state['halt_reason']}
    if stopped != expected_stop:
        raise ValueError('故障后检查点含其他状态变更，不能局部恢复')
    request_path, response_path, ledger_path = (run / f'{name}_001.json' for name in ('REQUEST', 'RESPONSE', 'CALL_LEDGER'))
    request, response = core._read(request_path), core._read(response_path)
    errors, tokens, text = runtime._response_evidence(response, binding)
    if (errors or tokens is None or request['stage'] != 'writer_full' or request['role'] != 'writer'
            or response['request_binding'] != core._binding(request_path)
            or tokens != state['known_reported_tokens'] or tokens != adopted['known_reported_tokens']):
        raise ValueError('writer原生内容、结束、请求身份或实际用量不完整')
    payload = runtime.roles.build_writer_payload(binding['source'], previous_draft=initial['previous_draft'],
        feedback=initial['feedback'], brief=binding['brief'])
    messages, parameters = runtime._request_spec(binding, 'writer_full', payload)
    if request['messages'] != messages or request['parameters'] != parameters or request['input_bindings'] != initial['active']:
        raise ValueError('原请求不是完整冻结来源和原始创作要求')
    draft_path = run / 'DRAFT_001.md'
    if draft_path.read_bytes() != text.encode('utf-8'):
        raise ValueError('已存完整稿不是同一原生writer正文')
    target = deepcopy(adopted)
    target.update(stage='review_full', previous_draft=None, feedback=None, draft_clarifications_used=0,
        previous_bundle=None, director_previous=None, director_feedback=None, director_rejected_receipt=None)
    target['active'] = {'writer_full': {'file': core._binding(draft_path), 'receipt': core._binding(response_path)}}
    if published != target:
        raise ValueError('既有review快照不是原生writer的精确程序派生')
    temps = [p for p in run.glob('.state-*') if core._read(p) == published]
    if len(temps) != 1:
        raise ValueError('缺少唯一且完全匹配的失败本地投影临时文件')
    files = [run / 'BINDING.json', run / 'BINDING_ANCHOR.json', run / 'state.json',
        run / 'WRITER_ONLY_ROUTE.json', run / 'WRITER_ONLY_ROUTE_ANCHOR.json',
        *paths, request_path, response_path, ledger_path, draft_path, temps[0]]
    return {'schema': VERSION, 'status': 'local_recovery_proven', 'run_dir': str(run),
        'evidence': [core._binding(p) for p in files], 'original_stop': core._binding(paths[-1]),
        'already_published_target': core._binding(paths[-2]), 'target_state': target,
        'target_checkpoint': runtime._prepared_json_binding(run / 'STATE_00006.json', target),
        'source_binding': binding['source']['binding_id'], 'calls_started': 1, 'reported_tokens': tokens,
        'recovery_code': core._binding(Path(__file__).resolve()), 'model_calls_authorized': False,
        'content_modified': False, 'historical_files_preserved': True}


def _finish_existing(run):
    record = core._read(run / RECORD)
    core._verify_file(record['recovery_code'])
    for row in record['historical_evidence']:
        core._verify_file(row)
    checkpoint = record['target_checkpoint']; core._verify_file(checkpoint)
    paths = sorted(run.glob('STATE_*.json'))
    if core._binding(paths[-1]) != checkpoint:
        raise ValueError('恢复后源运行已推进，不允许回退')
    runtime._verify(run, _state_override=core._read(checkpoint['path']))
    runtime._recover_state_projection(run)
    _, state = runtime._verify(run)
    return {'schema': VERSION, 'status': 'recovered', 'run_dir': str(run),
        'stage': state['stage'], 'calls_started': state['calls_started'], 'reported_tokens': state['reported_tokens'],
        'recovery_record': core._binding(run / RECORD), 'model_calls_started': 0}


def apply_recovery(run_dir, *, reviewed_plan):
    """Append one proof/checkpoint; all old snapshots and native files remain.

    ``reviewed_plan`` is the exact read-only plan reviewed by the controller.
    The only replacement is state.json, the derived projection of snapshots.
    """
    run = Path(run_dir).resolve()
    with core._lock(run / '.execution.lock') as owner:
        if (run / RECORD).exists() and (run / 'STATE_00006.json').exists():
            return _finish_existing(run)
        current = plan_recovery(run, _lock_owner=owner)
        if current != reviewed_plan:
            raise ValueError('待恢复证据与已审查计划变化')
        # state.json is the sole mutable projection. Every historical source,
        # snapshot, receipt, draft and failed temp file stays byte-for-byte.
        historical = [r for r in current['evidence'] if Path(r['path']).name != 'state.json']
        record = {'schema': VERSION, 'mode': 'append_existing_native_writer_projection',
            'source_binding': current['source_binding'], 'original_stop': current['original_stop'],
            'already_published_target': current['already_published_target'],
            'historical_evidence': historical, 'target_checkpoint': current['target_checkpoint'],
            'recovery_code': current['recovery_code'], 'calls_started': 1,
            'reported_tokens': current['reported_tokens'], 'model_calls_started': 0, 'content_modified': False}
        core._ensure(run / RECORD, record)
        # If this local replacement fails again, the immutable sixth snapshot
        # and record allow only verified local projection completion next time.
        runtime._save_state(run, current['target_state'])
        return _finish_existing(run)
