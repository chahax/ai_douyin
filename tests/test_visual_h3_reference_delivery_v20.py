"""Delivery protocol QA using real temporary reviewed-asset fixtures, no GPU.

Any generated small AV files are explicitly CPU protocol fixtures, never real
H3 media or evidence of visual/production acceptance.
"""
from copy import deepcopy
import http.server
import json
from pathlib import Path
import shutil
import subprocess
import threading

from PIL import Image
import pytest

from test_visual_h3_reference_bundle_v20 import setup as bundle_setup
from src.content_factory import visual_h3_reference_delivery_v20 as delivery
from src.content_factory import visual_asset_pipeline_v3 as assets
from src.content_factory import visual_image_jobs_v3 as jobs


@pytest.fixture
def make(bundle_setup, tmp_path):
    s = bundle_setup
    def create(*, video=True, three=False, service_url='http://127.0.0.1:18191', raw=True):
        packet = deepcopy(s['packet'])
        packet['shots'][0].update(start=0, end=5)
        if three:
            packet['characters'].append(dict(id='twin_child', name='Twin independent role', design_version='v1'))
            packet['scenes'][0]['cast'].append('twin_child')
            packet['shots'][0]['visible_cast'].append('twin_child')
            packet['shots'][0]['character_views']['twin_child'] = 'front'
            s['add']('twin_child', 'character', 'front', color='green')
        dirs = {key: tmp_path/key for key in ('input_root', 'output_root', 'gpu_lock_root')}
        for path in dirs.values():
            path.mkdir(exist_ok=True)
        pause = tmp_path/'OLD_PAUSE.json'
        pause.write_bytes(b'original protected bytes\r\n')
        service = dict(service_url=service_url, input_root=str(dirs['input_root']), output_root=str(dirs['output_root']))
        asset_run = tmp_path/'delivery_asset_run'
        assets.prepare(asset_run, packet, dict(library=str(s['lib']), image_service=service,
                       gpu_lock_root=str(dirs['gpu_lock_root']), protected_pause_path=str(pause)))
        runs = tmp_path/delivery.PREFIX
        run = runs/'protocol_case'
        config = dict(service, gpu_lock_root=str(dirs['gpu_lock_root']), protected_pause_path=str(pause),
                      base_workflow=str(delivery.native.DEFAULT_BASE), runs_root=str(runs), timeout=5,
                      video_enabled=video, width=64, height=96)
        text = '\ufeff原剧本对话和动作，保留原字节。\r\n角色说：“你好。”\r\nA memory returns.'
        prompt = tmp_path/'raw_prompt.txt'
        prompt.write_bytes(text.encode('utf-8'))
        return {**s, 'asset_run': asset_run, 'run': run, 'config': config, 'pause': pause, 'packet': packet,
                'prompts': {'shot1': str(prompt)} if raw else None, 'prompt': prompt, 'text': text}
    return create


def prepare(s):
    return delivery.prepare(s['asset_run'], s['run'], s['config'], source_prompts=s['prompts'])


def mock_native(monkeypatch, s):
    posts, histories = [], {}
    queue = dict(queue_running=[], queue_pending=[])
    gets = []
    def http(cfg, route, value=None):
        if value is None:
            gets.append(route)
        if route == '/system_stats':
            return dict(system=dict(argv=['comfy', '--input-directory', cfg['input_root'],
                                          '--output-directory', cfg['output_root']]))
        if route == '/queue':
            return deepcopy(queue)
        if route.startswith('/history/'):
            return deepcopy(histories.get(route.removeprefix('/history/'), {}))
        if route == '/object_info/MiniMaxH3ReferenceToVideo':
            return capability_fixture()
        if route == '/prompt':
            posts.append(deepcopy(value))
            pid = 'protocol_only_' + str(len(posts))
            queue['queue_running'] = [[0, pid, deepcopy(value['prompt']), {}]]
            return dict(prompt_id=pid, node_errors={})
        raise AssertionError(route)
    monkeypatch.setattr(delivery.native, '_http', http)
    return posts, histories, queue, gets


def capability_fixture():
    # Protocol shape only. Actual native capability was independently probed;
    # this server never claims to execute the model or validate a real weight.
    return {'MiniMaxH3ReferenceToVideo': {'input': {'required': {
        'clip': ['CLIP'], 'vae': ['VAE'], 'prompt': ['STRING'], 'width': ['INT'],
        'height': ['INT'], 'length': ['INT']}}}}


def cpu_native_fixture(s, posts):
    """Actual small CPU-decoded AV; history/job identities remain protocol-only."""
    run, plan = delivery._load(s['run'], current=False)
    row = plan['shots'][0]
    folder = run/'shots/shot1'
    state = delivery._state(folder, plan, row)
    out = Path(s['config']['output_root'])/row['scope']
    out.mkdir(parents=True, exist_ok=True)
    video = out/'video_00001_.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-filter_threads', '1',
                    '-f', 'lavfi', '-i', 'testsrc2=size=64x96:rate=24', '-f', 'lavfi', '-i',
                    'sine=frequency=600:sample_rate=32000', '-t', str(row['timing']['native_frames']/24),
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-c:a', 'aac', str(video)],
                   check=True, capture_output=True, timeout=60)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i', str(video), '-vn',
                    '-c:a', 'flac', str(out/'audio_00001_.flac')], check=True, capture_output=True, timeout=60)
    for role, color in [('first', 'red'), ('last', 'blue')]:
        Image.new('RGB', (64,96), color).save(out/(role+'_00001_.png'))
    outputs = {}
    for role, key, suffix in [('video','images','mp4'), ('audio','audio','flac'), ('first','images','png'), ('last','images','png')]:
        outputs['save_'+role] = {key: [dict(filename=role+'_00001_.'+suffix, subfolder=row['scope'], type='output')]}
    graph = deepcopy(posts[0]['prompt'])
    graph['124']['inputs']['denoise'] = 1.0
    graph['130']['inputs']['fps'] = 24.0
    entry = dict(prompt=[0, state['prompt_id'], graph], outputs=outputs,
                 status=dict(completed=True, status_str='success', messages=[]))
    return state['prompt_id'], entry


def test_prepare_load_status_video_disabled_are_cpu_only(make, monkeypatch):
    s = make(video=False)
    monkeypatch.setattr(delivery.native, '_http', lambda *a: pytest.fail('disabled/prepare contacted service'))
    first = prepare(s)
    assert first['video_enabled'] is False and first['technical_saved'] == 0
    _, plan = delivery._load(s['run'])
    original = (s['run']/'PLAN.json').read_bytes()
    assert prepare(s) == first
    assert (s['run']/'PLAN.json').read_bytes() == original
    assert delivery.submit_next(s['run'])['dispatch'] == 'video_policy_disabled'
    assert delivery.execute(s['run'], poll_seconds=1, max_seconds=.01)['video_enabled'] is False
    assert not list(s['run'].rglob('CLAIM.json'))
    assert not list(Path(s['config']['input_root']).rglob('*.png'))
    assert plan['production_approved'] is False


def test_three_people_without_composite_frame_keeps_all_global_and_view_slots(make, monkeypatch):
    s = make(three=True)
    monkeypatch.setattr(delivery.native, '_http', lambda *a: pytest.fail('prepare contacted service'))
    prepare(s)
    folder = s['run']/'shots/shot1'
    binding = delivery.native.read(folder/'PROMPT_BINDING.json')
    bundle = delivery.native.read(folder/'REFERENCE_BUNDLE.json')
    assert bundle['reference_count'] == 6
    assert len(binding['reference_map']) == 6
    assert binding['graph']['condition']['class_type'] == 'MiniMaxH3ReferenceToVideo'
    assert 'first_frame' not in binding['graph']['condition']['inputs']
    assert not (s['asset_run']/'H3_INPUT_READY.json').exists()
    assert not (s['asset_run']/'SHOT_BINDINGS.json').exists()
    assert (folder/'SOURCE_PROMPT.txt').read_bytes() == s['text'].encode('utf-8')
    assert binding['compiled_prompt'].encode().startswith(s['text'].encode())


def test_actual_input_staging_each_slot_and_known_response_no_duplicate_post(make, monkeypatch):
    s = make()
    prepare(s)
    posts, _, _, _ = mock_native(monkeypatch, s)
    first = delivery.submit_next(s['run'])
    assert len(posts) == 1 and first['shots'][0]['prompt_id'] == 'protocol_only_1'
    _, plan = delivery._load(s['run'])
    row = plan['shots'][0]
    bundle = delivery.native.read(s['run']/'shots/shot1/REFERENCE_BUNDLE.json')
    for image in bundle['references']:
        path = Path(s['config']['input_root'])/row['input_mapping'][image['reference_id']]
        assert path.read_bytes() == Path(image['image']['path']).read_bytes()
    delivery.submit_next(s['run'])
    assert len(posts) == 1


def test_known_response_recovers_original_id_without_reposting(make, monkeypatch):
    s = make();prepare(s)
    posts, _, _, _ = mock_native(monkeypatch, s)
    delivery.submit_next(s['run'])
    path = s['run']/'shots/shot1/STATE.json'
    state = delivery.native.read(path)
    state.update(status='prepared', prompt_id=None)
    delivery.native.write(path, state)
    assert delivery.status(s['run'])['shots'][0]['prompt_id'] == 'protocol_only_1'
    delivery.submit_next(s['run'])
    assert len(posts) == 1


def test_claim_without_response_does_not_replay_even_if_state_reset(make, monkeypatch):
    s = make();prepare(s)
    posts, _, _, _ = mock_native(monkeypatch, s)
    delivery.submit_next(s['run'])
    folder = s['run']/'shots/shot1'
    (folder/'RESPONSE.json').unlink()
    state = delivery.native.read(folder/'STATE.json')
    state.update(status='prepared', prompt_id=None)
    delivery.native.write(folder/'STATE.json', state)
    assert delivery.submit_next(s['run'])['shots'][0]['status'] == 'outcome_unknown'
    assert len(posts) == 1


def test_transport_exception_retains_unknown_and_never_submits_again(make, monkeypatch):
    s = make();prepare(s)
    mock_native(monkeypatch, s)
    real = delivery.native._http
    count = []
    def lose(cfg, route, value=None):
        if route == '/prompt':
            count.append(value)
            raise TimeoutError('protocol transport response lost')
        return real(cfg, route, value)
    monkeypatch.setattr(delivery.native, '_http', lose)
    assert delivery.submit_next(s['run'])['shots'][0]['status'] == 'outcome_unknown'
    delivery.submit_next(s['run'])
    assert len(count) == 1


def test_original_id_absent_stays_unknown_then_can_resume_same_id(make, monkeypatch):
    s = make();prepare(s)
    posts, histories, queue, _ = mock_native(monkeypatch, s)
    delivery.submit_next(s['run'])
    queue['queue_running'] = []
    state = delivery.poll_collect(s['run'])
    assert state['shots'][0]['status'] == 'outcome_unknown'
    assert state['shots'][0]['prompt_id'] == 'protocol_only_1'
    pid, entry = cpu_native_fixture(s, posts)
    histories[pid] = {pid: entry}
    assert delivery.poll_collect(s['run'])['technical_saved'] == 1
    assert len(posts) == 1


def test_source_change_blocks_new_post_but_collects_original_native_outputs(make, monkeypatch):
    s = make();prepare(s)
    posts, histories, queue, _ = mock_native(monkeypatch, s)
    delivery.submit_next(s['run'])
    pid, entry = cpu_native_fixture(s, posts)
    histories[pid] = {pid: entry}
    queue['queue_running'] = []
    s['prompt'].write_bytes(b'source changed after original submission')
    state = delivery.poll_collect(s['run'])
    assert state['technical_saved'] == 1 and state['dispatch'] == 'blocked_upstream_changed'
    result = delivery.native.read(s['run']/'shots/shot1/RESULT.json')
    assert result['prompt_id'] == pid and set(result['files']) == {'video','audio','first','last'}
    assert result['production_approved'] is False
    with pytest.raises(ValueError):
        delivery.submit_next(s['run'])
    assert len(posts) == 1


def test_pauses_queue_and_shared_both_gpu_leases_block_new_post(make, monkeypatch):
    s = make();prepare(s)
    posts, _, queue, _ = mock_native(monkeypatch, s)
    delivery.set_paused(s['run'], True)
    assert delivery.submit_next(s['run'])['dispatch'] == 'paused'
    delivery.set_paused(s['run'], False)
    queue['queue_pending'] = [[0, 'other_protocol_job', {}, {}]]
    assert delivery.submit_next(s['run'])['dispatch'] == 'waiting_gpu_queue'
    queue['queue_pending'] = []
    with jobs.run_lock(Path(s['config']['gpu_lock_root']), 'GPU.lock'):
        with pytest.raises(jobs.JobBusyError):
            delivery.submit_next(s['run'])
    with jobs.run_lock(Path(s['config']['input_root']), 'VISUAL_GPU.lock'):
        with pytest.raises(jobs.JobBusyError):
            delivery.submit_next(s['run'])
    s['pause'].write_bytes(b'changed protected old pause')
    with pytest.raises(ValueError, match='pause_changed'):
        delivery.submit_next(s['run'])
    assert not posts and not list(s['run'].rglob('CLAIM.json'))


def test_wrong_live_service_paths_and_conflicting_staged_slot_refuse_before_post(make, monkeypatch):
    s = make();prepare(s)
    posts, _, _, _ = mock_native(monkeypatch, s)
    real = delivery.native._http
    def wrong(cfg, route, value=None):
        if route == '/system_stats':
            return dict(system=dict(argv=['comfy','--input-directory',str(s['tmp']), '--output-directory',cfg['output_root']]))
        return real(cfg, route, value)
    monkeypatch.setattr(delivery.native, '_http', wrong)
    with pytest.raises(ValueError, match='wrong_h3_service_paths'):
        delivery.submit_next(s['run'])
    monkeypatch.setattr(delivery.native, '_http', real)
    _, plan = delivery._load(s['run'])
    target = Path(s['config']['input_root'])/next(iter(plan['shots'][0]['input_mapping'].values()))
    target.parent.mkdir(parents=True)
    target.write_bytes(b'wrong existing file must be preserved')
    with pytest.raises(ValueError, match='staged_input_already_differs'):
        delivery.submit_next(s['run'])
    assert target.read_bytes() == b'wrong existing file must be preserved'
    assert not posts


def test_history_float_cast_allowed_but_changed_ref_slot_is_rejected(make, monkeypatch):
    s = make();prepare(s)
    posts, histories, _, _ = mock_native(monkeypatch, s)
    delivery.submit_next(s['run'])
    pid, entry = cpu_native_fixture(s, posts)
    first = deepcopy(entry)
    slot = 'ref_images.ref_image_0'
    entry['prompt'][2]['condition']['inputs'][slot] = ['v20_reference_1', 0]
    histories[pid] = {pid: entry}
    with pytest.raises(ValueError, match='history_identity_changed'):
        delivery.poll_collect(s['run'])
    histories[pid] = {pid: first}
    assert delivery.poll_collect(s['run'])['technical_saved'] == 1
    assert len(posts) == 1


def test_unclaimed_response_and_fake_saved_state_cannot_bypass_original_proof(make, monkeypatch):
    s = make();prepare(s)
    monkeypatch.setattr(delivery.native, '_http', lambda *a: pytest.fail('invalid local state contacted service'))
    folder = s['run']/'shots/shot1'
    delivery.native.write(folder/'RESPONSE.json', dict(prompt_id='unclaimed_protocol_id'))
    with pytest.raises(ValueError):
        delivery.status(s['run'])
    (folder/'RESPONSE.json').unlink()
    state = delivery.native.read(folder/'STATE.json')
    state['status'] = 'technical_saved'
    delivery.native.write(folder/'STATE.json', state)
    with pytest.raises((ValueError, OSError)):
        delivery.status(s['run'])


def test_saved_result_and_four_native_artifacts_are_revalidated_read_only(make, monkeypatch):
    s = make();prepare(s)
    posts, histories, _, _ = mock_native(monkeypatch, s)
    delivery.submit_next(s['run'])
    pid, entry = cpu_native_fixture(s, posts)
    histories[pid] = {pid: entry}
    assert delivery.poll_collect(s['run'])['technical_saved'] == 1
    watched = {str(p): (p.stat().st_mtime_ns, assets.file_sha(p)) for p in s['run'].rglob('*') if p.is_file()}
    monkeypatch.setattr(delivery.native, '_http', lambda *a: pytest.fail('status contacted native service'))
    assert delivery.status(s['run'])['technical_saved'] == 1
    assert watched == {str(p): (p.stat().st_mtime_ns, assets.file_sha(p)) for p in s['run'].rglob('*') if p.is_file()}
    receipt = delivery.native.read(s['run']/'shots/shot1/RESULT.json')
    Path(receipt['files']['last']['path']).write_bytes(b'changed collected endpoint')
    with pytest.raises(ValueError, match='output_changed'):
        delivery.status(s['run'])


def test_malformed_native_queue_and_unconfirmed_reference_node_never_post(make, monkeypatch):
    s = make();prepare(s)
    posts, _, queue, _ = mock_native(monkeypatch, s)
    queue['queue_running'] = {}
    with pytest.raises(ValueError, match='invalid_h3_queue_response'):
        delivery.submit_next(s['run'])
    queue['queue_running'] = []
    real = delivery.native._http
    def wrong(cfg, route, value=None):
        if route == '/object_info/MiniMaxH3ReferenceToVideo':
            return {}
        return real(cfg, route, value)
    monkeypatch.setattr(delivery.native, '_http', wrong)
    with pytest.raises(ValueError, match='capability_unconfirmed'):
        delivery.submit_next(s['run'])
    assert not posts and not list(s['run'].rglob('CLAIM.json'))


def test_explicit_source_missing_original_audio_is_rejected_before_plan(make):
    s = make()
    s['prompt'].write_bytes('只剩画面描述，遗漏了原有旁白。'.encode('utf-8'))
    with pytest.raises(ValueError, match='missing_original_audio'):
        prepare(s)
    assert not (s['run']/'PLAN.json').exists()


def test_source_renderer_keeps_original_action_audio_and_refuses_legacy_adapter_camera():
    shot = dict(visual_prompt='The child turns, then the camera follows into the doorway.',
                audio=[dict(speaker='child', mode='onscreen', text='We can go now.')])
    text, binding = delivery._prompt(shot, None)
    assert text.startswith(shot['visual_prompt']) and 'We can go now.' in text
    assert 'locked-off' not in text and 'integrated_multimodal_description' not in text
    assert binding is None
    shot['staging_provenance'] = dict(schema='continuous_source_home_staging/v6')
    with pytest.raises(ValueError, match='legacy_v6_staging_requires_explicit_original'):
        delivery._prompt(shot, None)


def test_real_loopback_http_transport_one_post_and_resume_without_gpu(make):
    posts, settings = [], {}
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def response(self, value):
            raw = json.dumps(value).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path == '/system_stats':
                self.response(dict(system=dict(argv=['comfy','--input-directory',settings['input_root'],
                                                     '--output-directory',settings['output_root']])))
            elif self.path == '/queue':
                self.response(dict(queue_running=[[0,'loopback_protocol_id',posts[0]['prompt'],{}]] if posts else [], queue_pending=[]))
            elif self.path.startswith('/history/'):
                self.response({})
            elif self.path == '/object_info/MiniMaxH3ReferenceToVideo':
                self.response(capability_fixture())
            else:
                raise AssertionError(self.path)
        def do_POST(self):
            assert self.path == '/prompt'
            posts.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.response(dict(prompt_id='loopback_protocol_id',node_errors={}))
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        s = make(service_url=f'http://127.0.0.1:{server.server_port}')
        settings.update(s['config'])
        prepare(s)
        state = delivery.submit_next(s['run'])
        assert state['shots'][0]['prompt_id'] == 'loopback_protocol_id'
        state = delivery.poll_collect(s['run'])
        assert state['shots'][0]['status'] == 'running'
        delivery.submit_next(s['run'])
        assert len(posts) == 1
        assert posts[0]['prompt']['condition']['class_type'] == 'MiniMaxH3ReferenceToVideo'
        assert not (s['run']/'shots/shot1/RESULT.json').exists()
    finally:
        server.shutdown();server.server_close();thread.join(5)
