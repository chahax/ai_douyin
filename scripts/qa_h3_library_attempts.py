"""Read-only QA adapter for an explicit, append-only H3 technical attempt route.

The sealed library QA remains untouched. Only its physical namespace expressions
are derived into an isolated module; all pixel, library, state, history, clock,
and content-quality limitations remain the original checks. No network or media
dispatch capability is added here. A timeout is never a terminal retry proof.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import uuid

SCRIPTS = Path(__file__).resolve().parent
for item in (SCRIPTS, SCRIPTS.parent):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))
import qa_h3_library_minute as base

PROJECT = base.PROJECT
ROUTE_SCHEMA = 'library_minute_attempt_routes/v1'
TERMINAL_SCHEMA = 'library_minute_terminal_failure/v1'
ABORT_SCHEMA = 'controlled_local_abort/v1'
SEALED_QA_SHA256 = 'b5cc0fab7b836d1f5fd9b1b57daf369973314c67c6640e1da764e38b02c758bc'
PRODUCER_ADAPTER = PROJECT / 'src/content_factory/visual_h3_library_attempts_v1.py'
read, bind, checked, require, sha, freeze = base.read, base.bind, base.checked, base.require, base.sha, base.freeze


def original_paths(run, sid):
    run = Path(run).resolve()
    require(sid in base.IDS, 'explicit_library_shot_id_required')
    return dict(segment_dir=run / 'segments' / sid,
                native_run=run / 'visual_h3_v3' / (run.name + '_' + sid))


def retry_paths(run, sid, attempt_id):
    run = Path(run).resolve()
    require(sid == 'S02' and attempt_id == 'A02', 'this_recovery_scope_allows_only_S02_A02')
    return dict(segment_dir=run / 'technical_attempts' / sid / attempt_id / 'segment',
                native_run=run / 'visual_h3_v3' / (run.name + '_' + sid + '_' + attempt_id))


def _queue_ids(value):
    require(isinstance(value, dict) and set(('queue_running', 'queue_pending')) <= set(value),
            'actual_native_queue_observation_required')
    ids = set()
    for name in ('queue_running', 'queue_pending'):
        require(isinstance(value[name], list), 'queue_observation_cannot_be_an_unreadable_status')
        for row in value[name]:
            require(isinstance(row, list) and len(row) >= 3 and isinstance(row[1], str),
                    'native_queue_row_identity_required')
            ids.add(row[1])
    return ids


def _original_evidence(value, run, sid, project):
    """Authenticate the original records without changing their outcome status."""
    paths = original_paths(run, sid)
    nr, folder = paths['native_run'], paths['native_run'] / 'shots' / sid
    required = dict(native_plan=nr / 'PLAN.json', request=folder / 'REQUEST.json',
                    response=folder / 'RESPONSE.json', claim=folder / 'CLAIM.json',
                    state=folder / 'STATE.json', workflow=folder / 'workflow_api.json')
    for name, path in required.items():
        require(checked(value[name], project) == path, 'terminal_evidence_must_bind_original_' + name)
    pid = value.get('prompt_id')
    state, plan, graph = read(required['state']), read(required['native_plan']), read(required['workflow'])
    response, claim, request = read(required['response']), read(required['claim']), read(required['request'])
    require(isinstance(pid, str) and bool(pid) and state.get('prompt_id') == response.get('prompt_id') == pid
            and state.get('id') == sid and state.get('plan_sha256') == base.digest(plan)
            and request.get('prompt') == graph and len(plan.get('shots', [])) == 1
            and plan.get('schema') == base.NATIVE_SCHEMA and plan.get('series_plan') == bind(run / 'PLAN.json'),
            'original_prompt_plan_request_response_identity_required')
    shot = plan['shots'][0]
    require(shot.get('id') == sid and shot.get('graph_sha256') == base.digest(graph)
            and claim.get('graph_sha256') == shot['graph_sha256']
            and claim.get('first_frame_sha256') == shot.get('first_frame', {}).get('sha256'),
            'terminal_original_submission_bindings_changed')
    require(not (folder / 'RESULT.json').exists(), 'successful_original_result_cannot_be_discarded_for_retry')
    return dict(pid=pid, state=state, graph=graph, nr=nr, folder=folder, required=required)


def _controlled_abort(value, run, sid, project):
    """An explicit local owner exit authorizes one *new* attempt; old stays unknown."""
    require(value.get('allow_new_attempt') is True and value.get('allow_same_source_technical_retry') is True
            and type(value.get('max_new_attempts')) is int and value['max_new_attempts'] == 1
            and value.get('old_native_outcome') == 'unknown_retained' and value.get('local_only') is True
            and type(value.get('external_paid_calls')) is int and value['external_paid_calls'] == 0,
            'controlled_abort_must_explicitly_retain_unknown_and_bound_one_local_new_attempt')
    old = _original_evidence(value, run, sid, project)
    pid, state, graph = old['pid'], old['state'], old['graph']
    require(state.get('status') in ('running', 'submitted', 'queued', 'outcome_unknown'),
            'controlled_abort_cannot_replace_successful_native_state')
    records = {}
    for name in ('preflight', 'abort_issued', 'owner_exit', 'fresh_service'):
        path = checked(value[name], project)
        require(path.is_relative_to(run), 'controlled_abort_evidence_must_belong_to_original_run')
        records[name] = read(path)
    pre, issued, exited, fresh = (records[k] for k in ('preflight', 'abort_issued', 'owner_exit', 'fresh_service'))
    require(pre.get('schema') == 'controlled_local_abort_preflight/v1'
            and pre.get('original_prompt_id') == pid and pre.get('request') == value['request']
            and pre.get('plan') == value['native_plan'] and pre.get('generation_repost_performed') is False
            and pre.get('old_result_not_claimed_failed') is True and pre.get('artifact_files') == []
            and pre.get('history') == {}
            and pre.get('at_epoch', 0) - state.get('submitted_at', pre.get('at_epoch', 0)) >= 1200,
            'controlled_abort_original_preflight_must_keep_unknown_evidence')
    queue = pre.get('queue', {})
    require(_queue_ids(queue) == {pid} and queue.get('queue_pending') == []
            and len(queue.get('queue_running', [])) == 1
            and base.media_qa.native.native_graph_equivalence(graph, queue['queue_running'][0][2]) is not None
            and pid not in pre.get('history', {}),
            'controlled_abort_preflight_requires_only_same_original_running_graph')
    interrupt = read(checked(pre['interrupt_request'], project))
    response = read(checked(pre['interrupt_response'], project))
    require(interrupt.get('method') == 'POST' and interrupt.get('path') == '/interrupt'
            and interrupt.get('body') == dict(prompt_id=pid) and interrupt.get('verified_running_ids') == [pid]
            and interrupt.get('pending_ids') == [] and interrupt.get('global_interrupt') is False
            and interrupt.get('generation_posts') == 0 and response.get('status') == 200,
            'targeted_interrupt_receipt_must_identify_original_prompt_without_repost')
    process, parent, guard = (pre.get(k, {}) for k in ('original_process', 'original_parent', 'original_guard'))
    require(process.get('ppid') == parent.get('pid') and bool(process.get('cmdline'))
            and process.get('cmdline') == parent.get('cmdline')
            and isinstance(process.get('create_time'), (int, float))
            and isinstance(parent.get('create_time'), (int, float))
            and isinstance(guard.get('create_time'), (int, float)) and bool(guard.get('cmdline')),
            'controlled_abort_must_bind_precise_original_family_and_guard')
    require(issued.get('original_prompt_id') == pid and issued.get('target_pid') == process.get('pid')
            and issued.get('target_create_time') == process.get('create_time')
            and issued.get('guard_retained_pid') == guard.get('pid')
            and issued.get('only_verified_local_listener') is True
            and issued.get('original_unknown_record_retained') is True and issued.get('replay_performed') is False
            and issued.get('at_epoch', 0) >= pre.get('at_epoch', float('inf')),
            'controlled_abort_issued_receipt_must_keep_original_unknown_and_precise_owner')
    checks = exited.get('process_checks', [])
    require(exited.get('schema') == 'controlled_local_owner_exit/v1' and isinstance(checks, list)
            and exited.get('observed_at_epoch', 0) > issued.get('at_epoch', float('inf')),
            'actual_local_owner_exit_observation_required')
    for expected in (process, parent):
        matches = [r for r in checks if r.get('pid') == expected['pid']
                   and r.get('expected_create_time') == expected['create_time']]
        require(len(matches) == 1 and matches[0].get('exists') is False
                and isinstance(matches[0].get('observed_at_epoch'), (int, float))
                and matches[0]['observed_at_epoch'] > issued.get('at_epoch', float('inf')),
                'both_original_listener_and_parent_must_be_observed_exited_after_abort')
    fresh_guard, fresh_process = fresh.get('guard', {}), fresh.get('process', {})
    require(fresh.get('schema') == 'controlled_local_fresh_service/v1'
            and all(fresh_guard.get(k) == guard.get(k) for k in ('pid', 'create_time', 'cmdline'))
            and fresh_process.get('cmdline') == process['cmdline']
            and isinstance(fresh_process.get('create_time'), (int, float))
            and fresh_process['create_time'] > issued.get('at_epoch', float('inf'))
            and fresh_process.get('pid') not in (process['pid'], parent['pid'])
            and (fresh_process.get('pid'), fresh_process.get('create_time')) != (process['pid'], process['create_time'])
            and fresh.get('listener_pid') == fresh_process.get('pid')
            and fresh.get('service_paths_verified') is True
            and fresh.get('persistent_queue_restore_enabled') is False
            and _queue_ids(fresh.get('queue', {})) == set()
            and fresh.get('observed_at_epoch', 0) >= exited.get('observed_at_epoch', float('inf'))
            and pid not in fresh.get('history', {}),
            'fresh_identical_local_service_and_original_guard_required_without_queue_restore')
    before = pre.get('original_native_state')
    if before != state:
        require(isinstance(before, dict) and before.get('status') == 'running'
                and state.get('status') == 'outcome_unknown'
                and {k: v for k, v in before.items() if k != 'status'} == {k: v for k, v in state.items() if k != 'status'},
                'only_actual_collector_running_to_unknown_transition_can_follow_owner_exit')
        settlement_path = checked(value['collector_settlement'], project)
        require(settlement_path.is_relative_to(run), 'collector_settlement_must_belong_to_same_run')
        settlement = read(settlement_path)
        require(settlement.get('schema') == 'controlled_local_collector_settlement/v1'
                and settlement.get('prompt_id') == pid and settlement.get('final_state') == value['state']
                and settlement.get('fresh_service') == value['fresh_service'],
                'collector_settlement_must_bind_same_original_unknown_state_and_fresh_service')
        log_path, exit_path = (checked(settlement[k], project) for k in ('collector_log', 'collector_exit'))
        require(log_path.is_relative_to(run) and exit_path.is_relative_to(run),
                'collector_log_and_exit_must_be_saved_inside_same_run')
        lines = [line for line in log_path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        require(bool(lines), 'actual_collector_unknown_observation_required')
        last, exit_record = json.loads(lines[-1]), read(exit_path)
        require(last.get('event') == 'original_id_observation' and last.get('original_id') == pid
                and last.get('result', {}).get('status') == 'outcome_unknown'
                and last.get('result', {}).get('shot') == state
                and isinstance(last.get('at_epoch'), (int, float))
                and last['at_epoch'] >= exited.get('observed_at_epoch', float('inf'))
                and last['at_epoch'] >= fresh_process['create_time']
                and type(exit_record.get('exit_code')) is int and exit_record['exit_code'] == 0
                and exit_record.get('at_epoch', 0) >= last['at_epoch'],
                'actual_same_original_collector_must_observe_unknown_and_exit_after_fresh_owner')
    return dict(prompt_id=pid, original_native=old['nr'], evidence=value,
                outcome_unknown=True, known_terminal_failure=False,
                local_owner_exit_confirmed=True, one_new_local_attempt_authorized=True)


def terminal_proof(binding, run, sid, project=PROJECT):
    """Verify either native error or an explicit local-abort/unknown decision."""
    run, project = Path(run).resolve(), Path(project).resolve()
    proof_path = checked(binding, project)
    expected = run / 'technical_attempts' / sid / 'A02' / 'TERMINAL_PROOF.json'
    require(proof_path == expected, 'retry_terminal_proof_must_be_immutable_in_this_attempt')
    value = read(proof_path)
    require(value.get('schema') in (TERMINAL_SCHEMA, ABORT_SCHEMA) and value.get('shot_id') == sid
            and isinstance(value.get('confirmed_by'), str) and bool(value['confirmed_by'].strip())
            and isinstance(value.get('evidence'), list) and bool(value['evidence'])
            and all(isinstance(s, str) and s.strip() for s in value['evidence']),
            'known_native_terminal_failure_confirmation_required')
    if value['schema'] == ABORT_SCHEMA:
        return dict(binding=bind(proof_path), **_controlled_abort(value, run, sid, project))
    require(value.get('completion_known') is True and value.get('outcome_unknown') is False,
            'native_terminal_error_cannot_keep_an_unknown_completion_flag')
    old = _original_evidence(value, run, sid, project)
    pid, state, graph = old['pid'], old['state'], old['graph']
    require(state.get('status') in ('failed', 'interrupted'),
            'timeout_unknown_or_success_cannot_authorize_retry')
    history_path = checked(value['history'], project)
    require(history_path.is_relative_to(run), 'actual_terminal_history_must_belong_to_original_run')
    event = read(history_path).get(pid, {})
    hp, status = event.get('prompt', []), event.get('status', {})
    require(len(hp) >= 3 and hp[1] == pid and isinstance(status.get('completed'), bool)
            and status.get('status_str') == 'error'
            and base.media_qa.native.native_graph_equivalence(graph, hp[2]) is not None,
            'native_terminal_history_must_report_error_for_same_original_graph')
    messages = status.get('messages', [])
    require(isinstance(messages, list) and any(
        isinstance(row, list) and len(row) >= 2 and row[0] in ('execution_error', 'execution_interrupted')
        and isinstance(row[1], dict) and row[1].get('prompt_id') == pid for row in messages),
        'actual_same_prompt_execution_error_or_interrupted_message_required')
    queue_path = checked(value['queue_observation'], project)
    require(queue_path.is_relative_to(run) and pid not in _queue_ids(read(queue_path)),
            'original_prompt_must_be_absent_from_actual_running_and_pending_queue')
    return dict(binding=bind(proof_path), prompt_id=pid, original_native=old['nr'],
                evidence=value, outcome_unknown=False, known_terminal_failure=True)


def resolve_routes(run, project=PROJECT):
    """Verify the whole immutable event chain without trusting producer routing."""
    project, run = Path(project).resolve(), Path(run).resolve()
    series = base.series_inputs(run, project)
    home = run / 'attempt_routing' / 'ROUTES'
    paths = sorted(home.glob('*.json'))
    require(bool(paths) and len(paths) <= 2, 'explicit_bounded_attempt_route_chain_required')
    require([p.name for p in paths] == [f'{i:04d}.json' for i in range(1, len(paths)+1)],
            'attempt_routes_must_be_contiguous_append_only_events')
    previous_binding, previous = None, None
    evidence = []
    for number, path in enumerate(paths, 1):
        require(path.resolve().parent == home.resolve(), 'attempt_route_path_escaped')
        value = read(path)
        require(value.get('schema') == ROUTE_SCHEMA and value.get('sequence') == number
                and value.get('previous') == previous_binding and value.get('series_plan') == series['plan_binding']
                and set(value.get('routes', {})) == set(base.IDS), 'immutable_route_chain_or_series_plan_changed')
        adapter = checked(value['adapter_code'], project)
        require(adapter == project / 'src/content_factory/visual_h3_library_attempts_v1.py',
                'explicit_frozen_technical_attempt_adapter_required')
        require(checked(value['producer_code'], project)
                == project / 'src/content_factory/visual_h3_library_minute_v2.py',
                'same_frozen_original_producer_code_required')
        changes = []
        for sid in base.IDS:
            row = value['routes'][sid]
            require(row.get('shot_id') == sid, 'route_shot_identity_changed')
            if row.get('kind') == 'original':
                require(row.get('attempt_id') == 'A01' and row.get('terminal_decision') is None,
                        'original_route_cannot_claim_retry_or_terminal_decision')
                selected = original_paths(run, sid)
            else:
                require(number == 2 and row.get('kind') == 'technical_retry'
                        and row.get('attempt_id') == 'A02', 'only_one_explicit_technical_retry_selection_allowed')
                selected = retry_paths(run, sid, row['attempt_id'])
                proof = terminal_proof(row.get('terminal_decision'), run, sid, project)
                evidence.append(proof)
            require(Path(row.get('segment_dir', '')).resolve() == selected['segment_dir']
                    and Path(row.get('native_run', '')).resolve() == selected['native_run'],
                    'selected_attempt_cannot_escape_exact_series_namespace')
            source = checked(row['source_case'], project)
            require(source == selected['segment_dir'] / 'SOURCE_CASE.json'
                    and sha(source) == sha(run / 'segments' / sid / 'SOURCE_CASE.json'),
                    'technical_retry_source_must_copy_same_canonical_script_bytes')
            if previous is not None and row != previous['routes'][sid]: changes.append(sid)
        require(number != 1 or all(row.get('kind') == 'original' for row in value['routes'].values()),
                'first_route_event_cannot_assume_a_previous_terminal_failure')
        if number == 2:
            require(changes == ['S02'] and value['routes']['S02']['kind'] == 'technical_retry',
                    'retry_event_can_only_change_S02_after_known_terminal_failure')
        previous, previous_binding = value, bind(path)
    return dict(manifest=previous_binding, routes=deepcopy(previous['routes']),
                series_plan=series['plan_binding'], terminal_evidence=evidence,
                event_bindings=[bind(p) for p in paths], run=run)


def _expression(code):
    return ast.parse(code, mode='eval').body


def _rewrite(function, replacements, expected):
    """Change only enumerated path expressions in the sealed reader's AST."""
    node = ast.parse(inspect.getsource(function)).body[0]
    counts = {name: 0 for name in replacements}
    patterns = {name: ast.dump(_expression(pair[0]), include_attributes=False)
                for name, pair in replacements.items()}
    class Routes(ast.NodeTransformer):
        def visit(self, value):
            if isinstance(value, ast.expr):
                dump = ast.dump(value, include_attributes=False)
                for name, pattern in patterns.items():
                    if dump == pattern:
                        counts[name] += 1
                        return ast.copy_location(_expression(replacements[name][1]), value)
            return super().visit(value)
    result = Routes().visit(node)
    require(counts == expected, 'sealed_QA_explicit_route_AST_replacement_count_changed')
    return ast.fix_missing_locations(ast.Module(body=[result], type_ignores=[])), counts


def isolated_reader(run, project=PROJECT):
    """Preserve every original check while resolving a selected physical attempt."""
    project, run = Path(project).resolve(), Path(run).resolve()
    source = SCRIPTS / 'qa_h3_library_minute.py'
    require(sha(source) == SEALED_QA_SHA256, 'sealed_library_QA_source_changed_re_review_required')
    selection = resolve_routes(run, project)
    spec = importlib.util.spec_from_file_location('_library_attempt_QA_' + uuid.uuid4().hex, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def selected(selected_run, sid, selected_project):
        require(Path(selected_run).resolve() == run and Path(selected_project).resolve() == project
                and sid in base.IDS, 'explicit_same_series_attempt_resolution_required')
        return selection['routes'][sid]
    module.__dict__.update(
        _route_native=lambda r, s, p: Path(selected(r, s, p)['native_run']).resolve(),
        _route_part=lambda r, s, p: Path(selected(r, s, p)['segment_dir']).resolve(),
        _route_manifest=lambda r: selection['manifest'])
    replacements = dict(
        current_native=("run / 'visual_h3_v3' / (run.name + '_' + sid)", '_route_native(run, sid, project)'),
        previous_native=("run / 'visual_h3_v3' / (run.name + '_' + previous_sid)", '_route_native(run, previous_sid, project)'),
        segment=("run / 'segments' / sid", '_route_part(run, sid, project)'),
        assembly=("dict(plan=value['plan_binding'], segments=output_rows)",
                  "dict(plan=value['plan_binding'], segments=output_rows, attempt_routes=_route_manifest(run))"))
    counts = {}
    for name, expected in (
        ('prepared_graph', dict(current_native=1, previous_native=1, segment=3, assembly=0)),
        ('preview_segment', dict(current_native=1, previous_native=0, segment=0, assembly=0)),
        ('validate', dict(current_native=1, previous_native=0, segment=1, assembly=1))):
        code, counts[name] = _rewrite(getattr(base, name), replacements, expected)
        exec(compile(code, str(Path(__file__).resolve()) + ':' + name, 'exec'), module.__dict__)
    return module, selection, counts


def _stable(selection, project):
    current = resolve_routes(selection['run'], project)
    require(current['manifest'] == selection['manifest'] and current['event_bindings'] == selection['event_bindings'],
            'attempt_selection_changed_during_read_only_QA')
    return current


def inspect_selected(run, sid, *, saved=False, project=PROJECT):
    module, selection, counts = isolated_reader(run, project)
    row = selection['routes'][sid]
    value = (module.validate_new_native if saved else module.prepared_graph)(row['native_run'], sid, project)
    _stable(selection, project)
    return dict(value=value, attempt_routes=selection, path_AST_replacements=counts,
                sealed_QA=bind(SCRIPTS / 'qa_h3_library_minute.py'), adapter_QA=bind(Path(__file__)),
                model_posts=0, GPU_calls=0, content_quality_passed=False)


def preview_segment(run, sid, project=PROJECT):
    module, selection, counts = isolated_reader(run, project)
    value = module.preview_segment(run, sid, project)
    _stable(selection, project)
    path = Path(value['manifest']['path']).parent / 'ATTEMPT_ROUTE_PREVIEW.json'
    freeze(path, dict(schema='library_minute_attempt_route_CPU_preview/v1',
        attempt_routes=selection['manifest'], events=selection['event_bindings'],
        selected_route=selection['routes'][sid], native_preview=value['manifest'],
        sealed_QA=bind(SCRIPTS / 'qa_h3_library_minute.py'), adapter_QA=bind(Path(__file__)),
        path_AST_replacements=counts, ASR_executed=False, content_quality_passed=False))
    return dict(value, attempt_route_preview=bind(path))


def qa(run, *, asr=False, project=PROJECT):
    module, selection, counts = isolated_reader(run, project)
    for name in ('FINAL_RESULT.json', 'ASSEMBLY_REQUEST.json'):
        require(read(Path(run) / name).get('attempt_routes') == selection['manifest'],
                'final_assembly_must_bind_actual_immutable_selected_attempt_routes')
    value = module.qa(run, asr=asr, project=project)
    _stable(selection, project)
    path = Path(value['manifest']['path']).parent / 'ATTEMPT_ROUTE_QA.json'
    freeze(path, dict(schema='library_minute_attempt_route_CPU_QA/v1',
        attempt_routes=selection['manifest'], events=selection['event_bindings'],
        selected_routes=selection['routes'], final_QA=value['manifest'],
        sealed_QA=bind(SCRIPTS / 'qa_h3_library_minute.py'), adapter_QA=bind(Path(__file__)),
        path_AST_replacements=counts, ASR_requested=asr,
        content_quality_passed=False, production_approved=False))
    return dict(value, attempt_route_QA=bind(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--prepared', choices=base.IDS)
    group.add_argument('--preview', choices=base.IDS)
    group.add_argument('--routes', action='store_true')
    parser.add_argument('--asr', action='store_true')
    args = parser.parse_args(argv)
    if args.routes:
        value = resolve_routes(args.run)
    elif args.prepared:
        value = inspect_selected(args.run, args.prepared)
    elif args.preview:
        value = preview_segment(args.run, args.preview)
    else:
        value = qa(args.run, asr=args.asr)
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
