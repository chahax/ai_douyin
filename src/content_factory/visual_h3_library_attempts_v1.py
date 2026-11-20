"""Explicit local technical-attempt routing; never overwrite a prior native attempt.

The frozen producer is reused in an isolated function namespace. Only physical
path selection, input path resolution and the predecessor lookup are adapted.
There is no automatic retry and no terminal inference from timeout/low GPU.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
import subprocess
import types

from . import visual_h3_library_minute_v2 as base

SCHEMA = 'library_minute_attempt_routes/v1'
TERMINAL = 'library_minute_terminal_failure/v1'
LOCAL_ABORT = 'controlled_local_abort/v1'
IDS = base.IDS
read, bind, freeze = base.read, base.bind, base.freeze


def _root(run):
    run = Path(run).resolve()
    plan = read(run / 'PLAN.json')
    if plan.get('schema') != base.SERIES or plan.get('all_segments_new') is not True:
        raise ValueError('original_fresh_series_plan_required')
    return run


def _original_route(run, sid):
    return dict(shot_id=sid, attempt_id='A01', kind='original',
                segment_dir=str(base.part(run, sid)), native_run=str(base.native_run(run, sid)),
                source_case=bind(base.part(run, sid) / 'SOURCE_CASE.json'), terminal_decision=None)


def _validate_route(run, sid, route):
    if route.get('shot_id') != sid or not re.fullmatch(r'A[0-9]{2}', route.get('attempt_id', '')):
        raise ValueError('explicit_segment_attempt_required')
    number = int(route['attempt_id'][1:])
    if number == 1:
        if route != _original_route(run, sid):
            raise ValueError('original_attempt_paths_or_source_changed')
    else:
        folder = run / 'technical_attempts' / sid / route['attempt_id']
        if (number < 2 or route.get('kind') != 'technical_retry'
                or Path(route['segment_dir']) != folder / 'segment'
                or Path(route['native_run']) != run / 'visual_h3_v3' / (run.name + '_' + sid + '_' + route['attempt_id'])
                or route.get('terminal_decision') != bind(folder / 'TERMINAL_PROOF.json')):
            raise ValueError('technical_attempt_namespace_changed')
        if route['source_case'] != bind(folder / 'segment' / 'SOURCE_CASE.json'):
            raise ValueError('attempt_source_path_changed')
        if Path(base.core.check(route['source_case'])).read_bytes() != (base.part(run, sid) / 'SOURCE_CASE.json').read_bytes():
            raise ValueError('technical_retry_must_keep_exact_original_source')
    return route


def resolve_routes(run):
    """Read and authenticate the append-only selection chain. Does no I/O to HTTP."""
    run = _root(run)
    files = sorted((run / 'attempt_routing' / 'ROUTES').glob('*.json'))
    if not files:
        raise ValueError('attempt_routes_not_initialized')
    previous, routes = None, None
    for sequence, path in enumerate(files, 1):
        value = read(path)
        if (path.name != f'{sequence:04d}.json' or value.get('schema') != SCHEMA
                or value.get('sequence') != sequence or value.get('previous') != previous
                or value.get('series_plan') != bind(run / 'PLAN.json')
                or value.get('adapter_code') != bind(__file__)
                or value.get('producer_code') != bind(base.__file__)
                or set(value.get('routes', {})) != set(IDS)):
            raise ValueError('immutable_attempt_route_chain_changed')
        selected = value['routes']
        for sid in IDS:
            _validate_route(run, sid, selected[sid])
        if routes is None:
            if any(r['attempt_id'] != 'A01' for r in selected.values()):
                raise ValueError('route_chain_must_start_with_originals')
        else:
            changed = [sid for sid in IDS if selected[sid] != routes[sid]]
            if len(changed) != 1:
                raise ValueError('one_explicit_attempt_selection_per_event_required')
            sid = changed[0]
            if int(selected[sid]['attempt_id'][1:]) != int(routes[sid]['attempt_id'][1:]) + 1:
                raise ValueError('attempt_sequence_must_not_skip_or_reselect')
            proof = read(base.core.check(selected[sid]['terminal_decision']))
            validate_terminal(run, sid, routes[sid], proof)
        previous, routes = bind(path), selected
    return dict(manifest=previous, routes=routes, series_plan=bind(run / 'PLAN.json'))


def initialize(run):
    run = _root(run)
    with base.native.jobs.run_lock(run, 'ATTEMPT_ROUTING.lock'):
        folder = run / 'attempt_routing' / 'ROUTES'
        if not list(folder.glob('*.json')):
            freeze(folder / '0001.json', dict(schema=SCHEMA, sequence=1, previous=None,
                series_plan=bind(run / 'PLAN.json'), adapter_code=bind(__file__),
                producer_code=bind(base.__file__), routes={sid: _original_route(run, sid) for sid in IDS}))
        return resolve_routes(run)


def selected_paths(run, sid):
    if sid not in IDS:
        raise ValueError('explicit_four_segment_id_required')
    route = resolve_routes(run)['routes'][sid]
    return {key: Path(route[key]) for key in ('segment_dir', 'native_run')}


def terminal_proof(run, sid, history, queue_observation, *, confirmed_by, evidence):
    """Build a local evidence object; caller supplies actual saved terminal records."""
    route = resolve_routes(run)['routes'][sid]
    nr = Path(route['native_run'])
    folder = nr / 'shots' / sid
    proof = dict(schema=TERMINAL, shot_id=sid, prompt_id=read(folder / 'STATE.json').get('prompt_id'),
        native_plan=bind(nr / 'PLAN.json'),
        **{key: bind(folder / name) for key, name in dict(request='REQUEST.json', response='RESPONSE.json',
            claim='CLAIM.json', state='STATE.json', workflow='workflow_api.json').items()},
        history=bind(history), queue_observation=bind(queue_observation), confirmed_by=confirmed_by,
        evidence=evidence, completion_known=True, outcome_unknown=False)
    validate_terminal(_root(run), sid, route, proof)
    return proof


def validate_terminal(run, sid, route, proof):
    """A known native failure is mandatory; a timeout or queue disappearance is not."""
    if proof.get('schema') == LOCAL_ABORT:
        return validate_local_abort(run, sid, route, proof)
    nr = Path(route['native_run'])
    folder = nr / 'shots' / sid
    if (proof.get('schema') != TERMINAL or proof.get('shot_id') != sid
            or proof.get('completion_known') is not True or proof.get('outcome_unknown') is not False
            or not isinstance(proof.get('confirmed_by'), str) or not proof['confirmed_by'].strip()
            or not base._strings(proof.get('evidence'))):
        raise ValueError('explicit_known_native_terminal_proof_required')
    expected = dict(native_plan=nr / 'PLAN.json', request=folder / 'REQUEST.json',
        response=folder / 'RESPONSE.json', claim=folder / 'CLAIM.json', state=folder / 'STATE.json',
        workflow=folder / 'workflow_api.json')
    for key, path in expected.items():
        if proof.get(key) != bind(path):
            raise ValueError('terminal_original_record_binding_changed')
    for key in ('history', 'queue_observation'):
        path = Path(base.core.check(proof[key]))
        if not path.is_relative_to(run):
            raise ValueError('terminal_evidence_must_be_saved_inside_original_run')
    plan, state, request = read(nr / 'PLAN.json'), read(folder / 'STATE.json'), read(folder / 'REQUEST.json')
    row = plan['shots'][0]
    graph = read(folder / 'workflow_api.json')
    base.validate_graph(graph, row['scope'], row['reference_map'])
    pid = proof.get('prompt_id')
    if (not pid or plan.get('schema') != base.SCHEMA or plan.get('series_plan') != bind(run / 'PLAN.json')
            or row.get('id') != sid or state.get('id') != sid
            or state.get('plan_sha256') != base.core.digest(plan)
            or state.get('status') not in ('failed', 'interrupted') or state.get('prompt_id') != pid
            or read(folder / 'RESPONSE.json').get('prompt_id') != pid
            or request.get('prompt') != graph or base.core.digest(graph) != row['graph_sha256']
            or read(folder / 'CLAIM.json').get('graph_sha256') != row['graph_sha256']
            or read(folder / 'CLAIM.json').get('first_frame_sha256') != row['first_frame']['sha256']
            or (folder / 'RESULT.json').exists()):
        raise ValueError('unknown_running_or_success_cannot_authorize_retry')
    event = read(base.core.check(proof['history'])).get(pid, {})
    hp, status = event.get('prompt', []), event.get('status', {})
    messages = status.get('messages', [])
    terminal = any(isinstance(m, list) and len(m) == 2 and m[0] in ('execution_error', 'execution_interrupted')
                   and isinstance(m[1], dict) and m[1].get('prompt_id') == pid for m in messages)
    if (len(hp) < 3 or hp[1] != pid or base.native.native_graph_equivalence(graph, hp[2]) is None
            or status.get('status_str') != 'error' or type(status.get('completed')) is not bool or not terminal):
        raise ValueError('actual_terminal_error_history_required_not_inferred_failure')
    queue = read(base.core.check(proof['queue_observation']))
    if (any(not isinstance(queue.get(k), list) for k in ('queue_running', 'queue_pending'))
            or any(not isinstance(row, list) or len(row) < 3 for k in ('queue_running', 'queue_pending') for row in queue[k])
            or any(row[1] == pid for k in ('queue_running', 'queue_pending') for row in queue[k])):
        raise ValueError('old_native_ID_must_not_still_be_queued_or_running')
    return proof


def local_abort_proof(run, sid, approval):
    """Bind a root-authorized process-abort record without rewriting native state."""
    route = resolve_routes(run)['routes'][sid]
    nr = Path(route['native_run']); folder = nr / 'shots' / sid
    proof = deepcopy(read(approval))
    proof.update(native_plan=bind(nr / 'PLAN.json'),
        **{key: bind(folder / name) for key, name in dict(request='REQUEST.json', response='RESPONSE.json',
            claim='CLAIM.json', state='STATE.json', workflow='workflow_api.json').items()})
    validate_local_abort(_root(run), sid, route, proof)
    return proof


def validate_local_abort(run, sid, route, proof):
    """Independent controlled-abort channel: old native outcome stays unknown.

    Idle samples or an interrupt 200 cannot open this gate. An authenticated
    owner exit plus a fresh verified service and explicit one-attempt approval
    are required. This is local execution cessation, not a native success/error.
    """
    nr = Path(route['native_run']); folder = nr / 'shots' / sid
    if (proof.get('schema') != LOCAL_ABORT or proof.get('shot_id') != sid
            or not isinstance(proof.get('confirmed_by'), str) or not proof['confirmed_by'].strip()
            or not base._strings(proof.get('evidence'))
            or proof.get('allow_new_attempt') is not True
            or proof.get('allow_same_source_technical_retry') is not True
            or type(proof.get('max_new_attempts')) is not int or proof['max_new_attempts'] != 1
            or proof.get('old_native_outcome') != 'unknown_retained'
            or proof.get('local_only') is not True or type(proof.get('external_paid_calls')) is not int
            or proof['external_paid_calls'] != 0):
        raise ValueError('explicit_root_local_abort_and_one_new_attempt_approval_required')
    expected = dict(native_plan=nr / 'PLAN.json', request=folder / 'REQUEST.json', response=folder / 'RESPONSE.json',
                    claim=folder / 'CLAIM.json', state=folder / 'STATE.json', workflow=folder / 'workflow_api.json')
    for key, path in expected.items():
        if proof.get(key) != bind(path): raise ValueError('controlled_abort_original_records_changed')
    records = {}
    for key in ('preflight', 'abort_issued', 'owner_exit', 'fresh_service'):
        path = Path(base.core.check(proof[key]))
        if not path.is_relative_to(run): raise ValueError('controlled_abort_evidence_must_be_saved_inside_run')
        records[key] = read(path)
    pre, issued, exited, fresh = [records[k] for k in ('preflight', 'abort_issued', 'owner_exit', 'fresh_service')]
    plan, state, graph = read(nr / 'PLAN.json'), read(folder / 'STATE.json'), read(folder / 'workflow_api.json')
    row, pid = plan['shots'][0], proof.get('prompt_id')
    base.validate_graph(graph, row['scope'], row['reference_map'])
    if (not pid or plan.get('schema') != base.SCHEMA or plan.get('series_plan') != bind(run / 'PLAN.json')
            or row.get('id') != sid or state.get('id') != sid or state.get('plan_sha256') != base.core.digest(plan)
            or state.get('status') not in ('running', 'submitted', 'queued', 'outcome_unknown')
            or state.get('prompt_id') != pid or read(folder / 'RESPONSE.json').get('prompt_id') != pid
            or read(folder / 'REQUEST.json').get('prompt') != graph
            or read(folder / 'CLAIM.json').get('graph_sha256') != row['graph_sha256']
            or read(folder / 'CLAIM.json').get('first_frame_sha256') != row['first_frame']['sha256']
            or base.core.digest(graph) != row['graph_sha256'] or (folder / 'RESULT.json').exists()):
        raise ValueError('controlled_abort_preserves_original_unknown_not_fake_native_failure')
    original, parent, guard = [pre.get(k, {}) for k in ('original_process', 'original_parent', 'original_guard')]
    q = pre.get('queue', {})
    if (pre.get('schema') != 'controlled_local_abort_preflight/v1' or pre.get('original_prompt_id') != pid
            or pre.get('request') != proof['request']
            or pre.get('plan') != proof['native_plan'] or pre.get('history') != {}
            or len(q.get('queue_running', [])) != 1 or q.get('queue_pending') != []
            or len(q['queue_running'][0]) < 3 or q['queue_running'][0][1] != pid
            or base.native.native_graph_equivalence(graph, q['queue_running'][0][2]) is None
            or pre.get('artifact_files') != [] or pre.get('generation_repost_performed') is not False
            or pre.get('old_result_not_claimed_failed') is not True
            or pre.get('at_epoch', 0) - state.get('submitted_at', pre.get('at_epoch', 0)) < 1200):
        raise ValueError('controlled_abort_original_sole_ID_graph_and_stall_evidence_required')
    for identity in (original, parent, guard):
        if (type(identity.get('pid')) is not int or not isinstance(identity.get('create_time'), (int, float))
                or not base._strings(identity.get('cmdline'))):
            raise ValueError('exact_original_process_family_identity_required')
    if original.get('ppid') != parent['pid'] or original['cmdline'] != parent['cmdline']:
        raise ValueError('exact_original_listener_parent_relationship_required')
    interrupt_request = read(base.core.check(pre['interrupt_request']))
    interrupt_response = read(base.core.check(pre['interrupt_response']))
    if (interrupt_request.get('method') != 'POST' or interrupt_request.get('path') != '/interrupt'
            or interrupt_request.get('body') != {'prompt_id': pid}
            or interrupt_request.get('verified_running_ids') != [pid] or interrupt_request.get('pending_ids') != []
            or interrupt_request.get('global_interrupt') is not False or interrupt_request.get('generation_posts') != 0
            or interrupt_response.get('status') != 200):
        raise ValueError('actual_targeted_interrupt_acknowledgement_required')
    if (issued.get('original_prompt_id') != pid or issued.get('target_pid') != original['pid']
            or issued.get('target_create_time') != original['create_time']
            or issued.get('guard_retained_pid') != guard['pid']
            or issued.get('only_verified_local_listener') is not True
            or issued.get('original_unknown_record_retained') is not True or issued.get('replay_performed') is not False
            or issued.get('at_epoch', 0) < pre.get('at_epoch', 0)):
        raise ValueError('exact_original_owner_controlled_abort_issued_required')
    checks = exited.get('process_checks', [])
    if exited.get('schema') != 'controlled_local_owner_exit/v1' or exited.get('observed_at_epoch', 0) <= issued['at_epoch']:
        raise ValueError('original_owner_exit_must_be_observed_after_abort')
    for identity in (original, parent):
        matches = [c for c in checks if c.get('pid') == identity['pid'] and c.get('expected_create_time') == identity['create_time']]
        if (len(matches) != 1 or matches[0].get('exists') is not False
                or matches[0].get('observed_at_epoch', 0) <= issued['at_epoch']):
            raise ValueError('old_owner_and_wrapper_must_both_be_confirmed_exited')
    new, current_guard = fresh.get('process', {}), fresh.get('guard', {})
    if (fresh.get('schema') != 'controlled_local_fresh_service/v1'
            or any(current_guard.get(k) != guard[k] for k in ('pid', 'create_time', 'cmdline'))
            or type(new.get('pid')) is not int or new['pid'] in (original['pid'], parent['pid'])
            or new.get('create_time', 0) <= issued['at_epoch'] or new.get('cmdline') != original['cmdline']
            or fresh.get('listener_pid') != new['pid'] or fresh.get('queue') != dict(queue_running=[], queue_pending=[])
            or not isinstance(fresh.get('history'), dict) or pid in fresh['history']
            or fresh.get('observed_at_epoch', 0) < exited['observed_at_epoch']
            or fresh.get('service_paths_verified') is not True or fresh.get('persistent_queue_restore_enabled') is not False):
        raise ValueError('fresh_same_guard_service_without_old_native_execution_required')
    if pre.get('original_native_state') != state:
        before = pre.get('original_native_state', {})
        if (before.get('status') != 'running' or state.get('status') != 'outcome_unknown'
                or {k:v for k,v in before.items() if k != 'status'} != {k:v for k,v in state.items() if k != 'status'}):
            raise ValueError('only_actual_running_to_unknown_collector_transition_is_allowed')
        settlement_path = Path(base.core.check(proof['collector_settlement']))
        if not settlement_path.is_relative_to(run):
            raise ValueError('collector_settlement_must_be_saved_inside_run')
        settlement = read(settlement_path)
        if (settlement.get('schema') != 'controlled_local_collector_settlement/v1'
                or settlement.get('prompt_id') != pid or settlement.get('final_state') != proof['state']
                or settlement.get('fresh_service') != proof['fresh_service']):
            raise ValueError('actual_original_collector_settlement_required')
        log_path = Path(base.core.check(settlement['collector_log']))
        exit_path = Path(base.core.check(settlement['collector_exit']))
        if not log_path.is_relative_to(run) or not exit_path.is_relative_to(run):
            raise ValueError('collector_log_and_exit_evidence_must_belong_to_run')
        records = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        last = records[-1] if records else {}
        exit_record = read(exit_path)
        if (last.get('event') != 'original_id_observation' or last.get('original_id') != pid
                or last.get('result', {}).get('status') != 'outcome_unknown'
                or last['result'].get('shot') != state
                or last.get('at_epoch', 0) < max(exited['observed_at_epoch'], new['create_time'])
                or type(exit_record.get('exit_code')) is not int or exit_record['exit_code'] != 0
                or exit_record.get('at_epoch', 0) < last['at_epoch']):
            raise ValueError('original_GET_only_collector_must_observe_unknown_then_exit')
    return proof


def register_attempt(run, sid, proof):
    """Append one selected attempt after known failure. Prepares files, never POSTs."""
    run = _root(run)
    with base.native.jobs.run_lock(run, 'ATTEMPT_ROUTING.lock'):
        resolved = resolve_routes(run)
        old = resolved['routes'][sid]
        validate_terminal(run, sid, old, proof)
        if any((run / name).exists() for name in ('ASSEMBLY_REQUEST.json', 'FINAL_RESULT.json')):
            raise ValueError('cannot_change_an_assembled_series_selection')
        for later in IDS[IDS.index(sid)+1:]:
            paths = resolved['routes'][later]
            if ((Path(paths['native_run']) / 'PLAN.json').exists()
                    or any((Path(paths['segment_dir']) / name).exists() for name in ('GUIDE_STATE_REQUEST.json', 'LIBRARY_INPUT.json'))):
                raise ValueError('downstream_already_frozen_do_not_silently_repoint_tail')
        aid = 'A' + f"{int(old['attempt_id'][1:])+1:02d}"
        if not re.fullmatch(r'A[0-9]{2}', aid):
            raise ValueError('bounded_attempt_namespace_exhausted')
        folder = run / 'technical_attempts' / sid / aid
        segment = folder / 'segment'
        freeze(folder / 'TERMINAL_PROOF.json', proof)
        segment.mkdir(parents=True, exist_ok=True)
        for name in ('SOURCE_CASE.json', 'GUIDE_STATE_REVIEW.json'):
            source = Path(old['segment_dir']) / name
            target = segment / name
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError('existing_attempt_material_must_not_be_overwritten')
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(source.read_bytes())
        routes = deepcopy(resolved['routes'])
        routes[sid] = dict(shot_id=sid, attempt_id=aid, kind='technical_retry', segment_dir=str(segment),
            native_run=str(run / 'visual_h3_v3' / (run.name + '_' + sid + '_' + aid)),
            source_case=bind(segment / 'SOURCE_CASE.json'), terminal_decision=bind(folder / 'TERMINAL_PROOF.json'))
        previous = read(base.core.check(resolved['manifest']))
        sequence = previous['sequence'] + 1
        freeze(run / 'attempt_routing' / 'ROUTES' / f'{sequence:04d}.json', dict(schema=SCHEMA,
            sequence=sequence, previous=resolved['manifest'], series_plan=resolved['series_plan'],
            adapter_code=bind(__file__), producer_code=bind(base.__file__), routes=routes))
        return resolve_routes(run)


def routed_flow(run):
    """Reuse unchanged function code with isolated globals, never monkeypatch base."""
    run = _root(run)
    resolved = resolve_routes(run)
    namespace = dict(base.__dict__)
    for name, function in list(namespace.items()):
        if isinstance(function, types.FunctionType) and function.__module__ == base.__name__:
            isolated = types.FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)
            isolated.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = isolated
    def check_run(value):
        if Path(value).resolve() != run:
            raise ValueError('adapter_is_bound_to_one_explicit_series')
    def part(value, sid):
        check_run(value)
        if sid not in IDS: raise ValueError('explicit_four_segment_id_required')
        return Path(resolved['routes'][sid]['segment_dir'])
    def native_run(value, sid):
        check_run(value)
        if sid not in IDS: raise ValueError('explicit_four_segment_id_required')
        return Path(resolved['routes'][sid]['native_run'])
    def predecessor(value, sid):
        check_run(value)
        if sid == 'S01': return None
        if sid not in IDS: raise ValueError('explicit_four_segment_id_required')
        previous = IDS[IDS.index(sid)-1]
        path = native_run(run, previous) / 'shots' / previous / 'RESULT.json'
        if not path.exists(): return None
        plan = read(path.parents[2] / 'PLAN.json')
        if plan.get('schema') != base.SCHEMA or plan.get('series_plan') != resolved['series_plan']:
            raise ValueError('selected_current_series_predecessor_required')
        return bind(path)
    def validate_input(value):
        path = Path(base.core.check(value))
        matches = [sid for sid in IDS if path == part(run, sid) / 'LIBRARY_INPUT.json']
        if len(matches) != 1:
            raise ValueError('selected_attempt_input_path_required')
        sid = matches[0]
        data = read(path)
        if namespace['input_value'](run, sid) != data:
            raise ValueError('selected_library_source_description_or_pixels_changed')
        proof = {k: deepcopy(data[k]) for k in ('schema', 'source_case', 'first_image', 'predecessor_result',
            'guide_review', 'library_binding', 'binding_approval', 'library_resolution', 'references',
            'required_actor_assets', 'guide_visible_actor_ids', 'world_actor_state', 'script_fields', 'compiled_prompt_utf8_sha256')}
        proof['input'] = value
        return dict(data, entry=base.core._entries(data['source_case'])[0], proof=proof, quality_passed=False)
    original_approval = namespace['_approval']
    def launch_request(value, sid):
        nr, plan, _ = namespace['_load'](value, sid)
        return dict(schema=base.SCHEMA, shot_id=sid, plan=bind(nr / 'PLAN.json'), input=plan['input'],
            graph=bind(nr / 'shots' / sid / 'workflow_api.json'), code=plan['code'], series_plan=plan['series_plan'],
            publication=False, unknown_replay=False, attempt_routes=resolved['manifest'])
    def approval(value, sid):
        if resolve_routes(run)['manifest'] != resolved['manifest']:
            raise ValueError('selection_changed_after_worker_started')
        return original_approval(value, sid)
    namespace.update(part=part, native_run=native_run, _predecessor=predecessor,
                     validate_input=validate_input, launch_request=launch_request, _approval=approval)
    return types.SimpleNamespace(**namespace, attempt_routes=resolved['manifest'])


def assemble(run):
    """Same minute/clock, but every selected attempt and routing event is explicit."""
    run = _root(run)
    flow = routed_flow(run)
    rows = []
    with base.native.jobs.run_lock(run, 'ASSEMBLY.lock'):
        for sid in IDS:
            path = flow.part(run, sid) / 'FINAL_RESULT.json'
            descriptor = read(path)
            proof = flow.verify_native(descriptor['native_result'])
            result = proof['result']
            flow._load(run, sid)
            rows.append(dict(shot_id=sid, native_result=descriptor['native_result'],
                file={k: result['files']['video'][k] for k in ('path', 'sha256')},
                prompt_id=result['prompt_id'], kind='new', descriptor=bind(path)))
        if len({r['prompt_id'] for r in rows}) != 4 or len({r['file']['sha256'] for r in rows}) != 4:
            raise ValueError('four_distinct_native_originals_required')
        inputs = dict(plan=bind(run / 'PLAN.json'), segments=rows, attempt_routes=flow.attempt_routes)
        digest = base.core.digest(inputs)
        final, movie = run / 'FINAL_RESULT.json', run / 'H3_LIBRARY_BOUND_MINUTE_736x1312.mp4'
        if final.exists():
            previous = read(final)
            base.core.check(previous['file'])
            if previous.get('assembly_inputs_sha256') != digest or previous.get('attempt_routes') != flow.attempt_routes:
                raise ValueError('frozen_attempt_assembly_sources_changed')
            return previous
        if movie.exists(): raise ValueError('unreceipted_final_movie_preserved')
        adjustments = [base.clock_input(r['file']['path'], r['file']['sha256'], frames=362, width=736, height=1312) for r in rows]
        command, text = base.clock.assembly_command([r['file']['path'] for r in rows], run / 'ASSEMBLY_FILTER.txt', movie, frames=362)
        (run / 'ASSEMBLY_FILTER.txt').write_text(text, encoding='utf-8')
        freeze(run / 'ASSEMBLY_REQUEST.json', dict(inputs=inputs, adjustments=adjustments, command=command,
            all_segments_new=True, temporal_leading_trim=False, attempt_routes=flow.attempt_routes))
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
        (run / 'ASSEMBLY.stderr.log').write_text(result.stderr, encoding='utf-8')
        result.check_returncode()
        timing = base.clock.verify_clock(base.clock._probe(movie, count=True), frames=1448, width=736, height=1312)
        if resolve_routes(run)['manifest'] != flow.attempt_routes:
            raise ValueError('attempt_selection_changed_during_assembly')
        for row in rows:
            base.core.check(row['native_result']); base.core.check(row['file'])
        value = dict(schema=base.SERIES, file=bind(movie), segments=rows, native_ids=[r['prompt_id'] for r in rows],
            clock=timing, assembly_inputs_sha256=digest, attempt_routes=flow.attempt_routes,
            all_segments_new=True, production_approved=False, publication=False)
        freeze(final, value)
        return value
