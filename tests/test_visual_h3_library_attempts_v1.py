"""Real local HTTP attempts with immutable originals; no production endpoint."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from PIL import Image

from src.content_factory import visual_h3_library_attempts_v1 as adapter
from test_visual_h3_library_minute_v2 import run, prepare, initial_guide, review, approve, flow


def snapshot(folder):
    return {str(p.relative_to(folder)): flow.bind(p)['sha256'] for p in folder.rglob('*') if p.is_file()}


@pytest.fixture
def prepared(run):
    prepare(run); initial_guide(run); review(run, 'S01'); flow.prepare_video(run, 'S01')
    return run


def original_failed(run, sid='S01', status='failed'):
    nr, plan, row = flow._load(run, sid)
    folder = nr / 'shots' / sid; graph = flow.read(folder / 'workflow_api.json'); pid = 'controlled-old-id'
    flow.freeze(folder / 'REQUEST.json', dict(prompt=graph, client_id='fixture'))
    flow.freeze(folder / 'RESPONSE.json', dict(prompt_id=pid))
    flow.freeze(folder / 'CLAIM.json', dict(graph_sha256=row['graph_sha256'], first_frame_sha256=row['first_frame']['sha256']))
    flow.native.write(folder / 'STATE.json', dict(id=sid, status=status, prompt_id=pid,
        submitted_at=1000, plan_sha256=flow.core.digest(plan)))
    evidence = run / 'controlled_evidence'; evidence.mkdir(exist_ok=True)
    history = evidence / 'terminal_history.json'
    flow.freeze(history, {pid: dict(prompt=[1, pid, graph], status=dict(completed=False, status_str='error',
        messages=[['execution_interrupted', dict(prompt_id=pid)]]), outputs={})})
    queue = evidence / 'queue.json'; flow.freeze(queue, dict(queue_running=[], queue_pending=[]))
    return history, queue


def abort_approval(run, sid='S01'):
    nr, plan, row = flow._load(run, sid); folder = nr / 'shots' / sid
    state = flow.read(folder / 'STATE.json'); pid = state['prompt_id']; graph = flow.read(folder / 'workflow_api.json')
    root = run / 'controlled_evidence'; root.mkdir(exist_ok=True)
    def write(name, value):
        target = root / name; flow.freeze(target, value); return flow.bind(target)
    old = dict(pid=100, ppid=99, create_time=900, cmdline=['python', 'main.py', '--port', '8190'])
    parent = dict(pid=99, create_time=899, cmdline=old['cmdline'])
    guard = dict(pid=98, create_time=800, cmdline=['pythonw', 'guard.py'])
    interrupt = write('interrupt.json', dict(method='POST', path='/interrupt', body=dict(prompt_id=pid),
        verified_running_ids=[pid], pending_ids=[], global_interrupt=False, generation_posts=0))
    response = write('interrupt_response.json', dict(status=200))
    pre = write('preflight.json', dict(schema='controlled_local_abort_preflight/v1', at_epoch=2300,
        original_prompt_id=pid, original_native_state=state, original_process=old, original_parent=parent,
        original_guard=guard, request=flow.bind(folder / 'REQUEST.json'), plan=flow.bind(nr / 'PLAN.json'),
        queue=dict(queue_running=[[1, pid, graph]], queue_pending=[]), history={}, artifact_files=[],
        generation_repost_performed=False, old_result_not_claimed_failed=True,
        interrupt_request=interrupt, interrupt_response=response))
    issued = write('issued.json', dict(at_epoch=2301, original_prompt_id=pid, target_pid=old['pid'],
        target_create_time=old['create_time'], guard_retained_pid=guard['pid'], only_verified_local_listener=True,
        original_unknown_record_retained=True, replay_performed=False))
    exited = write('exit.json', dict(schema='controlled_local_owner_exit/v1', observed_at_epoch=2302,
        process_checks=[dict(pid=p['pid'], expected_create_time=p['create_time'], exists=False, observed_at_epoch=2302)
                        for p in (old, parent)]))
    fresh = write('fresh.json', dict(schema='controlled_local_fresh_service/v1', observed_at_epoch=2304,
        guard=guard, process=dict(pid=102, create_time=2303, cmdline=old['cmdline']), listener_pid=102,
        queue=dict(queue_running=[], queue_pending=[]), history={}, service_paths_verified=True,
        persistent_queue_restore_enabled=False))
    path = root / 'approval.json'
    flow.freeze(path, dict(schema=adapter.LOCAL_ABORT, shot_id=sid, prompt_id=pid,
        preflight=pre, abort_issued=issued, owner_exit=exited, fresh_service=fresh,
        confirmed_by='Controlled fixture; not a production process observation', evidence=['CPU protocol test only'],
        allow_new_attempt=True, allow_same_source_technical_retry=True, max_new_attempts=1,
        old_native_outcome='unknown_retained', local_only=True, external_paid_calls=0))
    return path


def test_initialize_only_creates_route_evidence_no_http_or_native_changes(prepared, monkeypatch):
    before = snapshot(prepared / 'visual_h3_v3')
    monkeypatch.setattr(flow.native, '_http', lambda *a, **k: pytest.fail('unexpected real HTTP'))
    value = adapter.initialize(prepared)
    assert value == adapter.initialize(prepared)
    assert all(row['attempt_id'] == 'A01' for row in value['routes'].values())
    assert snapshot(prepared / 'visual_h3_v3') == before
    assert flow.native_run(prepared, 'S01') == adapter.selected_paths(prepared, 'S01')['native_run']


@pytest.mark.parametrize('bad_status', ['running', 'outcome_unknown', 'technical_saved'])
def test_timeout_unknown_and_success_never_authorize_terminal_retry(prepared, bad_status):
    adapter.initialize(prepared); history, queue = original_failed(prepared, status=bad_status)
    with pytest.raises(ValueError, match='unknown_running_or_success'):
        adapter.terminal_proof(prepared, 'S01', history, queue, confirmed_by='fixture', evidence=['test'])
    assert len(list((prepared / 'attempt_routing/ROUTES').glob('*.json'))) == 1


def test_known_terminal_retry_keeps_all_original_bytes_and_isolated_module(prepared):
    adapter.initialize(prepared); history, queue = original_failed(prepared)
    old = snapshot(flow.native_run(prepared, 'S01'))
    proof = adapter.terminal_proof(prepared, 'S01', history, queue, confirmed_by='fixture', evidence=['test'])
    result = adapter.register_attempt(prepared, 'S01', proof)
    routed = adapter.routed_flow(prepared)
    assert result['routes']['S01']['attempt_id'] == 'A02'
    assert routed.prepare_video(prepared, 'S01', code_files=[adapter.__file__])['status'] == 'prepared'
    assert routed.native_run(prepared, 'S01') != flow.native_run(prepared, 'S01')
    assert snapshot(flow.native_run(prepared, 'S01')) == old
    assert flow.part(prepared, 'S01') == prepared / 'segments/S01'
    original = flow.read(flow.native_run(prepared, 'S01') / 'shots/S01/workflow_api.json')
    retry = flow.read(routed.native_run(prepared, 'S01') / 'shots/S01/workflow_api.json')
    assert original['condition']['inputs']['prompt'] == retry['condition']['inputs']['prompt']
    assert original['129'] == retry['129']
    assert len([v for v in retry.values() if v['class_type'] == 'LoadImage']) == 9
    assert original['save_video'] != retry['save_video']


@pytest.mark.parametrize('change', ['idle_only', 'interrupt_only', 'old_alive', 'parent_alive', 'no_approval', 'same_owner', 'old_in_queue'])
def test_controlled_abort_requires_owner_exit_fresh_service_and_explicit_approval(prepared, change):
    adapter.initialize(prepared); original_failed(prepared, status='running')
    path = abort_approval(prepared); data = flow.read(path)
    if change == 'idle_only': data.pop('owner_exit')
    elif change == 'interrupt_only': data.pop('fresh_service')
    elif change == 'no_approval': data['allow_new_attempt'] = False
    else:
        key = 'owner_exit' if change in ('old_alive', 'parent_alive') else 'fresh_service'
        p = Path(data[key]['path']); value = flow.read(p)
        if change in ('old_alive', 'parent_alive'): value['process_checks'][0 if change == 'old_alive' else 1]['exists'] = True
        elif change == 'same_owner': value['process']['pid'] = 100
        else: value['queue']['queue_running'] = [[1, 'controlled-old-id', {}]]
        p.write_text(json.dumps(value), encoding='utf-8'); data[key] = flow.bind(p)
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises((ValueError, KeyError)):
        adapter.local_abort_proof(prepared, 'S01', path)
    assert flow.read(flow.native_run(prepared, 'S01') / 'shots/S01/STATE.json')['status'] == 'running'


def test_controlled_abort_preserves_unknown_state_without_fabricated_failure(prepared):
    adapter.initialize(prepared); original_failed(prepared, status='outcome_unknown')
    path = abort_approval(prepared); before = snapshot(flow.native_run(prepared, 'S01'))
    proof = adapter.local_abort_proof(prepared, 'S01', path)
    value = adapter.register_attempt(prepared, 'S01', proof)
    assert value['routes']['S01']['attempt_id'] == 'A02'
    assert snapshot(flow.native_run(prepared, 'S01')) == before
    assert not (flow.native_run(prepared, 'S01') / 'shots/S01/HISTORY.json').exists()


@pytest.mark.parametrize('mutation', ['valid', 'missing_settlement', 'wrong_transition', 'wrong_identity', 'collector_not_exited'])
def test_only_actual_running_to_unknown_collector_settlement_is_allowed(prepared, mutation):
    adapter.initialize(prepared); original_failed(prepared, status='running')
    approval = abort_approval(prepared); data = flow.read(approval)
    folder = flow.native_run(prepared,'S01')/'shots/S01'; state = flow.read(folder/'STATE.json')
    state['status'] = 'outcome_unknown'
    if mutation == 'wrong_transition': state['status'] = 'queued'
    if mutation == 'wrong_identity': state['submitted_at'] += 1
    flow.native.write(folder/'STATE.json',state)
    evidence = approval.parent
    log = evidence/'collector.jsonl'
    log.write_text(json.dumps(dict(at_epoch=2305,original_id=state['prompt_id'],event='original_id_observation',
        result=dict(status='outcome_unknown',shot=state)))+'\n',encoding='utf-8')
    exit_record = evidence/'collector_exit.json'
    flow.freeze(exit_record,dict(exit_code=1 if mutation=='collector_not_exited' else 0,at_epoch=2306))
    settlement = evidence/'settlement.json'
    flow.freeze(settlement,dict(schema='controlled_local_collector_settlement/v1',prompt_id=state['prompt_id'],
        final_state=flow.bind(folder/'STATE.json'),fresh_service=data['fresh_service'],
        collector_log=flow.bind(log),collector_exit=flow.bind(exit_record)))
    if mutation != 'missing_settlement': data['collector_settlement'] = flow.bind(settlement)
    approval.write_text(json.dumps(data),encoding='utf-8')
    if mutation == 'valid':
        proof = adapter.local_abort_proof(prepared,'S01',approval)
        assert proof['state'] == flow.bind(folder/'STATE.json')
        assert adapter.register_attempt(prepared,'S01',proof)['routes']['S01']['attempt_id']=='A02'
        assert flow.read(folder/'STATE.json')['status']=='outcome_unknown'
    else:
        with pytest.raises((ValueError,KeyError)):
            adapter.local_abort_proof(prepared,'S01',approval)


def test_downstream_frozen_request_prevents_silent_tail_reselection(prepared):
    adapter.initialize(prepared); history, queue = original_failed(prepared)
    proof = adapter.terminal_proof(prepared, 'S01', history, queue, confirmed_by='fixture', evidence=['test'])
    flow.freeze(flow.part(prepared, 'S02') / 'GUIDE_STATE_REQUEST.json', dict(already_frozen=True))
    with pytest.raises(ValueError, match='downstream_already_frozen'):
        adapter.register_attempt(prepared, 'S01', proof)


def test_route_chain_tampering_and_escaped_paths_rejected(prepared):
    value = adapter.initialize(prepared)
    path = Path(value['manifest']['path']); data = flow.read(path)
    data['routes']['S02']['native_run'] = str(prepared / 'other')
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='original_attempt_paths'):
        adapter.resolve_routes(prepared)


@pytest.fixture(scope='module')
def cpu_media(tmp_path_factory):
    folder = tmp_path_factory.mktemp('attempt_cpu_media')
    for color in ('red', 'blue', 'green', 'yellow'):
        target = folder / color; target.mkdir()
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={color}:s=736x1312:r=24',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=32000', '-af',
            'aformat=channel_layouts=stereo,atrim=end_sample=482400,asetpts=N/SR/TB', '-frames:v', '362',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', '-ar', '32000', '-ac', '2',
            str(target / 'video_00001_.mp4')], capture_output=True, check=True, timeout=60)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(target / 'video_00001_.mp4'), '-vn',
            '-c:a', 'flac', str(target / 'audio_00001.flac')], capture_output=True, check=True, timeout=30)
        for role in ('first', 'last'): Image.new('RGB', (736, 1312), color).save(target / (role + '_00001_.png'))
    return folder


def test_local_http_failed_S02_then_new_attempt_real_tail_and_full_clock(run, cpu_media):
    cfg = flow.read(run / 'H3_CONFIG.json'); state = dict(posts=0, histories={}, pending={}, mode='success')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, data):
            body = json.dumps(data).encode(); self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path == '/system_stats': return self.send(dict(system=dict(argv=['--input-directory', cfg['input_root'], '--output-directory', cfg['output_root']])))
            if self.path == '/queue': return self.send(dict(queue_running=list(state['pending'].values()), queue_pending=[]))
            if self.path.startswith('/history/'): return self.send({k:v for k,v in state['histories'].items() if k == self.path.rsplit('/',1)[-1]})
            raise AssertionError(self.path)
        def do_POST(self):
            assert self.path == '/prompt'
            request = json.loads(self.rfile.read(int(self.headers['Content-Length']))); state['posts'] += 1
            pid = f"attempt-http-{state['posts']:03d}"; graph = request['prompt']
            if state['mode'] == 'unknown': return self.send({})
            if state['mode'] == 'stall':
                state['pending'][pid] = [1, pid, graph]; return self.send(dict(prompt_id=pid))
            color = ('red', 'blue', 'green', 'yellow')[state['posts']-1 if state['posts'] == 1 else state['posts']-2]
            outputs = {}
            for role in ('video','audio','first','last'):
                prefix = Path(graph['save_'+role]['inputs']['filename_prefix']); target = Path(cfg['output_root']) / prefix.parent
                target.mkdir(parents=True, exist_ok=True); source = next((cpu_media / color).glob(role+'_*'))
                shutil.copyfile(source, target / source.name)
                outputs['save_'+role] = {('audio' if role == 'audio' else 'images'):[dict(filename=source.name, subfolder=prefix.parent.as_posix(), type='output')]}
            state['histories'][pid] = dict(prompt=[1,pid,graph], status=dict(completed=True,status_str='success'), outputs=outputs)
            self.send(dict(prompt_id=pid))
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler); thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    cfg['service_url'] = 'http://127.0.0.1:' + str(server.server_port)
    (run / 'H3_CONFIG.json').write_text(json.dumps(cfg),encoding='utf-8')
    try:
        prepare(run); initial_guide(run); review(run,'S01'); flow.prepare_video(run,'S01'); approve(run,'S01')
        flow.submit(run,'S01'); assert flow.collect_known(run,'S01')['status'] == 'media_review_required'
        review(run,'S02',visible=('su_mo',)); flow.prepare_video(run,'S02'); approve(run,'S02')
        state['mode'] = 'stall'; flow.submit(run,'S02'); assert flow.collect_known(run,'S02')['status'] == 'running'
        oldnr = flow.native_run(run,'S02'); oldfolder = oldnr/'shots/S02'; pid = flow.read(oldfolder/'STATE.json')['prompt_id']
        graph = state['pending'].pop(pid)[2]
        state['histories'][pid] = dict(prompt=[1,pid,graph], status=dict(completed=False,status_str='error',
            messages=[['execution_interrupted',dict(prompt_id=pid)]]), outputs={})
        assert flow.collect_known(run,'S02')['status'] == 'blocked_native_failure'
        oldbytes = snapshot(oldnr); original_S01 = snapshot(flow.native_run(run,'S01'))
        evidence=run/'controlled_evidence'; evidence.mkdir(); queue=evidence/'queue.json'; flow.freeze(queue,dict(queue_running=[],queue_pending=[]))
        adapter.initialize(run)
        proof=adapter.terminal_proof(run,'S02',oldfolder/'HISTORY.latest.json',queue,confirmed_by='local HTTP fixture',evidence=['actual simulated server terminal'])
        adapter.register_attempt(run,'S02',proof); routed=adapter.routed_flow(run)
        assert routed.prepare_video(run,'S02',code_files=[adapter.__file__])['status'] == 'prepared'
        flow.freeze(routed.part(run,'S02')/'ROOT_LAUNCH_VIDEO.json',dict(request=routed.launch_request(run,'S02'),approved_by='fixture',evidence=['test']))
        state['mode']='success'; routed.submit(run,'S02'); assert routed.collect_known(run,'S02')['status']=='media_review_required'
        for sid in ('S03','S04'):
            request=routed.review_request(run,sid); q=flow.read(flow.core.check(request['request']))
            flow.freeze(routed.part(run,sid)/'GUIDE_STATE_REVIEW.json',dict(schema=flow.REVIEW,shot_id=sid,
                predecessor_result=q['predecessor_result'],guide_image=q['guide_image'],guide_visible_actor_ids=['su_mo'],
                world_actor_state={c:'Controlled fixture state' for c in q['required_actor_assets']},screen_identity_map={'su_mo':'left'},
                completion_known=True,outcome_unknown=False,reviewed_by='fixture',evidence=['CPU only']))
            assert routed.prepare_video(run,sid,code_files=[adapter.__file__])['status']=='prepared'
            flow.freeze(routed.part(run,sid)/'ROOT_LAUNCH_VIDEO.json',dict(request=routed.launch_request(run,sid),approved_by='fixture',evidence=['test']))
            routed.submit(run,sid); assert routed.collect_known(run,sid)['status']=='media_review_required'
        s03=flow.read(routed.part(run,'S03')/'LIBRARY_INPUT.json')
        assert s03['predecessor_result']==flow.bind(routed.native_run(run,'S02')/'shots/S02/RESULT.json')
        assert s03['first_image']==routed.verify_native(s03['predecessor_result'])['last_image']
        final=adapter.assemble(run)
        assert flow.clock._probe(Path(final['file']['path']), count=True)['streams']
        assert len(final['native_ids'])==4 and final['native_ids'][1]=='attempt-http-003'
        assert final['attempt_routes']==adapter.resolve_routes(run)['manifest']
        assert snapshot(oldnr)==oldbytes and snapshot(flow.native_run(run,'S01'))==original_S01
        assert state['posts']==5 and not (oldfolder/'RESULT.json').exists()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
