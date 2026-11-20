"""CPU-only independent QA of attempt choice; no model, HTTP, ASR or GPU."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'scripts'))
import qa_h3_library_attempts as qa
from tests import test_visual_h3_library_minute_v2 as fixture
from src.content_factory import visual_h3_library_attempts_v1 as producer


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def initial_routes(run):
    routes = {}
    for sid in qa.base.IDS:
        paths = qa.original_paths(run, sid)
        routes[sid] = dict(shot_id=sid, attempt_id='A01', kind='original',
            **{k: str(v) for k, v in paths.items()},
            source_case=qa.bind(paths['segment_dir'] / 'SOURCE_CASE.json'), terminal_decision=None)
    value = dict(schema=qa.ROUTE_SCHEMA, sequence=1, previous=None,
        series_plan=qa.bind(run / 'PLAN.json'), adapter_code=qa.bind(producer.__file__),
        producer_code=qa.bind(fixture.flow.__file__), routes=routes)
    write(run / 'attempt_routing/ROUTES/0001.json', value)
    return value


@pytest.fixture
def run(tmp_path):
    root = fixture.run.__wrapped__(tmp_path)
    fixture.prepare(root); fixture.initial_guide(root); fixture.review(root, 'S01')
    fixture.flow.prepare_video(root, 'S01')
    initial_routes(root)
    return root


def save_CPU_native(run, sid, *, routed=False, color='gray'):
    """Protocol evidence only: bytes labelled CPU fixtures, never quality media."""
    paths = qa.retry_paths(run, sid, 'A02') if routed else qa.original_paths(run, sid)
    nr, part = paths['native_run'], paths['segment_dir']
    plan = qa.read(nr / 'PLAN.json'); row = plan['shots'][0]
    folder = nr / 'shots' / sid; graph = qa.read(folder / 'workflow_api.json')
    pid = 'CPU_only_' + sid + ('_A02' if routed else '_A01')
    files, outputs = {}, {}
    origin = Path(plan['config']['output_root']) / row['scope']; origin.mkdir(parents=True)
    for role, suffix in (('video', '.mp4'), ('audio', '.flac'), ('first', '.png'), ('last', '.png')):
        source = origin / (role + '_00001_' + suffix)
        if role in ('first', 'last'): Image.new('RGB', (736, 1312), color).save(source)
        else: source.write_bytes(('CPU protocol only, not media ' + role + pid).encode())
        local = folder / 'artifacts' / source.name; local.parent.mkdir(exist_ok=True); shutil.copyfile(source, local)
        files[role] = dict(qa.bind(local), source_path=str(source))
        outputs['save_' + role] = {('audio' if role == 'audio' else 'images'):
            [dict(filename=source.name, subfolder=row['scope'], type='output')]}
    write(folder / 'REQUEST.json', dict(prompt=graph))
    write(folder / 'RESPONSE.json', dict(prompt_id=pid))
    write(folder / 'CLAIM.json', dict(graph_sha256=row['graph_sha256'], first_frame_sha256=row['first_frame']['sha256']))
    write(folder / 'STATE.json', dict(id=sid, status='technical_saved', prompt_id=pid, plan_sha256=qa.base.digest(plan)))
    write(folder / 'HISTORY.json', {pid: dict(prompt=[1, pid, graph], outputs=outputs,
        status=dict(completed=True, status_str='success'))})
    result = dict(schema=qa.base.media_qa.native.SCHEMA, shot_id=sid, prompt_id=pid,
        graph_sha256=row['graph_sha256'], first_frame_sha256=row['first_frame']['sha256'], files=files,
        timing=row['timing'], technical_status='technical_saved', content_status='media_review_required',
        old_batch_resume=False, publication=False, production_approved=False, continuity_input=None)
    write(folder / 'RESULT.json', result)
    receipt = dict(schema=qa.base.INPUT_SCHEMA, native_result=qa.bind(folder / 'RESULT.json'), input=plan['input'],
        library_input=row['library_input'], native_records={k: qa.bind(p) for k, p in
            dict(plan=nr/'PLAN.json', request=folder/'REQUEST.json', history=folder/'HISTORY.json').items()},
        production_approved=False)
    write(nr / 'LIBRARY_RESULT.json', receipt)
    write(part / 'FINAL_RESULT.json', dict(native_result=qa.bind(folder / 'RESULT.json'), file=qa.bind(files['video']['path']),
        prompt_id=pid, postprocessing=[], library_receipt=qa.bind(nr / 'LIBRARY_RESULT.json'), production_approved=False))
    return result


def old_S02(run):
    save_CPU_native(run, 'S01')
    fixture.review(run, 'S02', visible=('su_mo',))
    fixture.flow.prepare_video(run, 'S02')
    nr = qa.original_paths(run, 'S02')['native_run']; folder = nr / 'shots/S02'
    plan = qa.read(nr / 'PLAN.json'); row = plan['shots'][0]; graph = qa.read(folder / 'workflow_api.json')
    pid = 'CPU_original_S02_unknown'
    write(folder / 'REQUEST.json', dict(prompt=graph))
    write(folder / 'RESPONSE.json', dict(prompt_id=pid))
    write(folder / 'CLAIM.json', dict(graph_sha256=row['graph_sha256'], first_frame_sha256=row['first_frame']['sha256']))
    write(folder / 'STATE.json', dict(id='S02', status='running', prompt_id=pid, plan_sha256=qa.base.digest(plan), submitted_at=0.0))
    return nr, folder, pid, graph


def proof_fixture(run, controlled=False):
    nr, folder, pid, graph = old_S02(run)
    at = run / 'CPU_abort_records'; at.mkdir()
    proof = dict(schema=qa.ABORT_SCHEMA if controlled else qa.TERMINAL_SCHEMA, shot_id='S02', prompt_id=pid,
        native_plan=qa.bind(nr / 'PLAN.json'),
        **{k: qa.bind(folder / f) for k, f in dict(request='REQUEST.json', response='RESPONSE.json',
            claim='CLAIM.json', state='STATE.json', workflow='workflow_api.json').items()},
        confirmed_by='CPU fixture only', evidence=['Synthetic process receipts, never a live process operation.'])
    if not controlled:
        state = qa.read(folder / 'STATE.json'); state['status'] = 'failed'; write(folder / 'STATE.json', state)
        proof['state'] = qa.bind(folder / 'STATE.json')
        write(at / 'history.json', {pid: dict(prompt=[1, pid, graph], status=dict(completed=False,
            status_str='error', messages=[['execution_interrupted', dict(prompt_id=pid)]]))})
        write(at / 'queue.json', dict(queue_running=[], queue_pending=[]))
        proof.update(history=qa.bind(at / 'history.json'), queue_observation=qa.bind(at / 'queue.json'),
                     completion_known=True, outcome_unknown=False)
    else:
        process = dict(pid=1001, create_time=10.0, ppid=1000, cmdline=['CPU_fixture', '--local'])
        parent = dict(pid=1000, create_time=9.0, cmdline=process['cmdline'])
        guard = dict(pid=999, create_time=8.0, cmdline=['CPU_guard_fixture'])
        write(at / 'interrupt.json', dict(method='POST', path='/interrupt', body=dict(prompt_id=pid),
            verified_running_ids=[pid], pending_ids=[], global_interrupt=False, generation_posts=0))
        write(at / 'response.json', dict(status=200))
        write(at / 'preflight.json', dict(schema='controlled_local_abort_preflight/v1', original_prompt_id=pid,
            at_epoch=1300.0, original_native_state=qa.read(folder / 'STATE.json'),
            request=proof['request'], plan=proof['native_plan'], generation_repost_performed=False,
            old_result_not_claimed_failed=True, artifact_files=[], queue=dict(queue_running=[[1, pid, graph]], queue_pending=[]),
            history={}, interrupt_request=qa.bind(at / 'interrupt.json'), interrupt_response=qa.bind(at / 'response.json'),
            original_process=process, original_parent=parent, original_guard=guard))
        write(at / 'issued.json', dict(at_epoch=1301.0, original_prompt_id=pid, target_pid=1001, target_create_time=10.0,
            guard_retained_pid=999, only_verified_local_listener=True, original_unknown_record_retained=True, replay_performed=False))
        write(at / 'owner_exit.json', dict(schema='controlled_local_owner_exit/v1', observed_at_epoch=1302.0, process_checks=[
            dict(pid=p['pid'], expected_create_time=p['create_time'], exists=False, observed_at_epoch=1302.0) for p in (process, parent)]))
        write(at / 'fresh.json', dict(schema='controlled_local_fresh_service/v1', guard=guard,
            process=dict(pid=1003, create_time=1303.0, cmdline=process['cmdline']), listener_pid=1003, observed_at_epoch=1304.0,
            queue=dict(queue_running=[], queue_pending=[]), history={}, service_paths_verified=True,
            persistent_queue_restore_enabled=False))
        proof.update(**{k: qa.bind(at / name) for k, name in dict(preflight='preflight.json', abort_issued='issued.json',
            owner_exit='owner_exit.json', fresh_service='fresh.json').items()},
            allow_new_attempt=True, allow_same_source_technical_retry=True, max_new_attempts=1,
            old_native_outcome='unknown_retained', local_only=True, external_paid_calls=0)
    path = run / 'technical_attempts/S02/A02/TERMINAL_PROOF.json'; write(path, proof)
    return path, proof


def select_A02(run, proof_path):
    previous = run / 'attempt_routing/ROUTES/0001.json'; value = deepcopy(qa.read(previous))
    paths = qa.retry_paths(run, 'S02', 'A02'); paths['segment_dir'].mkdir(parents=True, exist_ok=True)
    for name in ('SOURCE_CASE.json', 'GUIDE_STATE_REVIEW.json'):
        shutil.copyfile(run / 'segments/S02' / name, paths['segment_dir'] / name)
    value.update(sequence=2, previous=qa.bind(previous))
    value['routes']['S02'] = dict(shot_id='S02', attempt_id='A02', kind='technical_retry',
        **{k: str(v) for k, v in paths.items()}, source_case=qa.bind(paths['segment_dir'] / 'SOURCE_CASE.json'),
        terminal_decision=qa.bind(proof_path))
    write(run / 'attempt_routing/ROUTES/0002.json', value)
    return value


def settle_unknown(run, path, proof):
    state_path = Path(proof['state']['path']); state = qa.read(state_path)
    state['status'] = 'outcome_unknown'; write(state_path, state); proof['state'] = qa.bind(state_path)
    home = run / 'CPU_abort_records'
    log = home / 'collector.jsonl'
    log.write_text(json.dumps(dict(at_epoch=1305.0, event='original_id_observation',
        original_id=proof['prompt_id'], result=dict(status='outcome_unknown', shot=state))) + '\n', encoding='utf-8')
    write(home / 'collector_exit.json', dict(exit_code=0, at_epoch=1306.0))
    write(home / 'settlement.json', dict(schema='controlled_local_collector_settlement/v1',
        prompt_id=proof['prompt_id'], final_state=proof['state'], collector_log=qa.bind(log),
        collector_exit=qa.bind(home / 'collector_exit.json'), fresh_service=proof['fresh_service']))
    proof['collector_settlement'] = qa.bind(home / 'settlement.json'); write(path, proof)
    return proof


def test_init_route_and_sealed_AST_reader_preserve_nine_actual_refs(run):
    reader, routes, counts = qa.isolated_reader(run)
    value = reader.prepared_graph(qa.original_paths(run, 'S01')['native_run'], 'S01')
    assert value['routes']['actual_positive_reference_count'] == 9
    assert counts['prepared_graph'] == dict(current_native=1, previous_native=1, segment=3, assembly=0)
    assert routes['routes']['S01']['attempt_id'] == 'A01'
    assert qa.sha(PROJECT / 'scripts/qa_h3_library_minute.py') == qa.SEALED_QA_SHA256


@pytest.mark.parametrize('controlled', [False, True])
def test_native_error_and_explicit_local_abort_are_distinct_accepted_proofs(run, controlled):
    path, proof = proof_fixture(run, controlled)
    old_before = Path(proof['state']['path']).read_bytes()
    value = qa.terminal_proof(qa.bind(path), run, 'S02')
    assert value['outcome_unknown'] is controlled
    assert value['known_terminal_failure'] is (not controlled)
    assert Path(proof['state']['path']).read_bytes() == old_before


@pytest.mark.parametrize('change', ['still_alive', 'wrong_ctime', 'wrong_guard', 'reused_listener', 'queued_original', 'replay', 'unbound_limit'])
def test_controlled_abort_requires_exact_exit_fresh_family_and_bounded_decision(run, change):
    path, proof = proof_fixture(run, True)
    if change in ('still_alive', 'wrong_ctime'):
        target = Path(proof['owner_exit']['path']); value = qa.read(target)
        value['process_checks'][0]['exists' if change == 'still_alive' else 'expected_create_time'] = True if change == 'still_alive' else 123.0
        write(target, value); proof['owner_exit'] = qa.bind(target)
    elif change in ('wrong_guard', 'reused_listener', 'queued_original'):
        target = Path(proof['fresh_service']['path']); value = qa.read(target)
        if change == 'wrong_guard': value['guard']['create_time'] = 0.0
        elif change == 'reused_listener': value['process']['create_time'] = 10.0
        else: value['queue']['queue_pending'] = [[1, proof['prompt_id'], {}]]
        write(target, value); proof['fresh_service'] = qa.bind(target)
    elif change == 'replay': proof['old_native_outcome'] = 'failed'
    else: proof['max_new_attempts'] = 2
    write(path, proof)
    with pytest.raises(ValueError): qa.terminal_proof(qa.bind(path), run, 'S02')


def test_timeout_and_empty_queue_alone_cannot_be_native_terminal_failure(run):
    path, proof = proof_fixture(run)
    state_path = Path(proof['state']['path']); state = qa.read(state_path); state['status'] = 'outcome_unknown'; write(state_path, state)
    proof['state'] = qa.bind(state_path); write(path, proof)
    with pytest.raises(ValueError, match='timeout_unknown_or_success'): qa.terminal_proof(qa.bind(path), run, 'S02')


def test_real_collector_transition_to_unknown_is_preserved_and_verified(run):
    path, proof = proof_fixture(run, True); settle_unknown(run, path, proof)
    value = qa.terminal_proof(qa.bind(path), run, 'S02')
    assert value['outcome_unknown'] is True and value['known_terminal_failure'] is False
    assert qa.read(Path(proof['state']['path']))['status'] == 'outcome_unknown'


@pytest.mark.parametrize('change', ['no_settlement', 'wrong_original', 'collector_failed', 'boolean_exit'])
def test_changed_unknown_state_requires_actual_same_collector_observation_and_exit(run, change):
    path, proof = proof_fixture(run, True); settle_unknown(run, path, proof)
    if change == 'no_settlement': proof.pop('collector_settlement')
    else:
        settlement_path = Path(proof['collector_settlement']['path']); settlement = qa.read(settlement_path)
        if change == 'wrong_original':
            log = Path(settlement['collector_log']['path']); last = json.loads(log.read_text()); last['original_id'] = 'other'
            log.write_text(json.dumps(last) + '\n', encoding='utf-8'); settlement['collector_log'] = qa.bind(log)
        else:
            exit_path = Path(settlement['collector_exit']['path']); write(exit_path, dict(exit_code=False if change == 'boolean_exit' else 2, at_epoch=1306.0))
            settlement['collector_exit'] = qa.bind(exit_path)
        write(settlement_path, settlement); proof['collector_settlement'] = qa.bind(settlement_path)
    write(path, proof)
    with pytest.raises((KeyError, ValueError)): qa.terminal_proof(qa.bind(path), run, 'S02')


def test_retry_event_and_source_cannot_reselect_another_story(run):
    path, _ = proof_fixture(run); value = select_A02(run, path)
    assert qa.resolve_routes(run)['routes']['S02']['attempt_id'] == 'A02'
    source = Path(value['routes']['S02']['source_case']['path'])
    source.write_text('{}', encoding='utf-8'); value['routes']['S02']['source_case'] = qa.bind(source)
    write(run / 'attempt_routing/ROUTES/0002.json', value)
    with pytest.raises(ValueError, match='same_canonical_script_bytes'): qa.resolve_routes(run)


def test_retry_tail_reaches_S03_without_changing_old_attempt_or_global_QA(run):
    path, proof = proof_fixture(run, True); settle_unknown(run, path, proof); select_A02(run, path)
    old_bindings = {k: dict(v) for k, v in proof.items() if isinstance(v, dict) and 'sha256' in v}
    flow = producer.routed_flow(run); flow.prepare_video(run, 'S02')
    result = save_CPU_native(run, 'S02', routed=True, color='blue')
    value = qa.inspect_selected(run, 'S02', saved=True)['value']
    assert value['native_id'] == result['prompt_id']
    request = flow.review_request(run, 'S03'); actual = qa.read(Path(request['request']['path']))
    assert actual['guide_image'] == {k: result['files']['last'][k] for k in ('path', 'sha256')}
    review = dict(schema=fixture.flow.REVIEW, shot_id='S03', predecessor_result=actual['predecessor_result'],
        guide_image=actual['guide_image'], guide_visible_actor_ids=['su_mo'],
        world_actor_state={c:'CPU fixture current state' for c in qa.base.ACTORS},
        screen_identity_map=dict(su_mo='CPU fixture central'), completion_known=True, outcome_unknown=False,
        reviewed_by='CPU fixture only', evidence=['Protocol-only proof, not image quality.'])
    write(run / 'segments/S03/GUIDE_STATE_REVIEW.json', review); flow.prepare_video(run, 'S03')
    third = qa.inspect_selected(run, 'S03')['value']
    assert Path(third['context']['predecessor_result']['path']) == qa.retry_paths(run, 'S02', 'A02')['native_run'] / 'shots/S02/RESULT.json'
    assert third['context']['references'][-1]['asset_id'] == 'native_tail:' + result['prompt_id']
    assert third['routes']['actual_positive_reference_count'] == 9
    assert all(qa.bind(v['path']) == v for v in old_bindings.values())
    assert qa.sha(PROJECT / 'scripts/qa_h3_library_minute.py') == qa.SEALED_QA_SHA256


def test_event_gap_or_hash_chain_replacement_is_rejected(run):
    first = run / 'attempt_routing/ROUTES/0001.json'
    value = qa.read(first); value['previous'] = dict(path='fiction', sha256='0'*64); write(first, value)
    with pytest.raises(ValueError, match='immutable_route_chain'): qa.resolve_routes(run)
