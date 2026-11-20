"""Protocol/clock QA only. Fake jobs here are never production media evidence."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from fractions import Fraction
import http.server
import threading
import sys

from PIL import Image
import pytest

from src.content_factory import visual_h3_prompt_parity_v19 as p


@pytest.fixture
def env(tmp_path, monkeypatch):
    actual_working = p.WORKING
    run = tmp_path / p.RUN.name
    run.mkdir()
    auth = run / 'USER_AUTHORIZATION.json'
    auth.write_text('{"protocol_test_only": true}', encoding='utf-8')
    monkeypatch.setattr(p, 'RUN', run)
    monkeypatch.setattr(p, 'AUTHORIZATION_SHA', p.sha(auth))
    pause = tmp_path / 'legacy/PAUSE.json'
    pause.parent.mkdir()
    pause.write_bytes(b'original pause bytes\r\n')
    monkeypatch.setattr(p, 'PAUSE', pause)
    monkeypatch.setattr(p, 'PAUSE_SHA', p.sha(pause))
    work = tmp_path / 'working/shots/F0010'
    work.mkdir(parents=True)
    for name in ('workflow_api.json', 'RESULT.json', 'HISTORY.json'):
        shutil.copyfile(actual_working / name, work / name)
    config = dict(service_url='http://127.0.0.1:8190', timeout=10)
    for key in ('input_root', 'output_root', 'gpu_lock_root'):
        path = tmp_path / key
        path.mkdir()
        config[key] = str(path)
    (work.parent.parent / 'PLAN.json').write_text(json.dumps(dict(config=config)), encoding='utf-8')
    monkeypatch.setattr(p, 'WORKING', work)
    models = tmp_path / 'models'
    graph = p.read(work / 'workflow_api.json')
    for kind, name in [('diffusion_models', graph['127']['inputs']['unet_name']),
                       ('text_encoders', graph['128']['inputs']['clip_name']),
                       *[('vae', graph[n]['inputs']['vae_name']) for n in ('119', '120')]]:
        path = models / kind / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test metadata only')
    monkeypatch.setattr(p, 'MODEL_ROOT', models)
    # Originals are read only; only small text/opening files are copied by prepare.
    return run, config


def fake_http(monkeypatch, config):
    calls, histories, queue = [], {}, dict(queue_running=[], queue_pending=[])

    def http(cfg, route, value=None):
        assert cfg['input_root'] == config['input_root']
        if route == '/system_stats':
            return dict(system=dict(argv=['comfy', '--input-directory', cfg['input_root'],
                                          '--output-directory', cfg['output_root']]))
        if route == '/queue':
            return deepcopy(queue)
        if route.startswith('/history/'):
            return deepcopy(histories.get(route.removeprefix('/history/'), {}))
        if route == '/prompt':
            calls.append(deepcopy(value))
            pid = 'timing_protocol_fixture_' + str(len(calls))
            queue['queue_running'] = [[0, pid, deepcopy(value['prompt']), {}]]
            return dict(prompt_id=pid, node_errors={})
        raise AssertionError(route)

    monkeypatch.setattr(p.h3, '_http', http)
    return calls, histories, queue


def complete_protocol_segment(run, config, index, calls, histories, queue):
    """Dummy files + injected ffprobe; cannot enter real assembly/video gate."""
    name = p.IDS[index]
    folder = run / 'segments' / name
    state = p.read(folder / 'STATE.json')
    graph = deepcopy(calls[index]['prompt'])
    graph['124']['inputs']['denoise'] = 1.0
    graph['130']['inputs']['fps'] = 24.0
    scope = run.name + '/' + name
    out = Path(config['output_root']) / scope
    out.mkdir(parents=True)
    outputs = {}
    for role, kind, ext in [('video', 'images', 'mp4'), ('audio', 'audio', 'flac'),
                             ('first', 'images', 'png'), ('last', 'images', 'png')]:
        filename = f'{role}_00001_.{ext}'
        path = out / filename
        if role in ('first', 'last'):
            Image.new('RGB', (p.WIDTH, p.HEIGHT), (index * 50, 20, 40 if role == 'last' else 70)).save(path)
        else:
            path.write_bytes((role + str(index) + ':protocol-fixture-not-native').encode())
        outputs['save_' + role] = {kind: [dict(filename=filename, subfolder=scope, type='output')]}
    entry = dict(prompt=[0, state['prompt_id'], graph], outputs=outputs,
                 status=dict(completed=True, status_str='success'))
    histories[state['prompt_id']] = {state['prompt_id']: entry}
    queue['queue_running'] = []
    return entry


def mock_metadata(monkeypatch):
    monkeypatch.setattr(p.h3, '_metadata', lambda path: dict(streams=[
        dict(codec_type='video', width=p.WIDTH, height=p.HEIGHT, nb_frames=str(p.FRAMES), r_frame_rate='24/1'),
        dict(codec_type='audio')]))


def test_prepare_is_offline_verbatim_first_only_and_idempotent(env, monkeypatch):
    run, _ = env
    monkeypatch.setattr(p.h3, '_http', lambda *a, **k: pytest.fail('prepare used HTTP'))
    plan = p.prepare(run)
    graph = p.read(run / 'segments/S01/workflow_api.json')
    assert graph['condition']['inputs']['prompt'] == plan['segments'][0]['text']
    assert p.text_sha(graph['condition']['inputs']['prompt']) == p.PROMPT_SHAS[0]
    assert p.sha(run / 'sources/S01.prompt.txt') == p.PROMPT_SHAS[0]
    assert not {'last_frame', 'ref_images'} & graph['condition']['inputs'].keys()
    assert graph['condition']['inputs']['length'] == 362
    assert p.sha(run / 'segments/S01/first_input.jpeg') == p.OPENING_SHA
    before = p.sha(run / 'PLAN.json')
    assert p.prepare(run) == plan
    assert p.sha(run / 'PLAN.json') == before
    assert not list(run.rglob('CLAIM.json'))


def test_two_segments_use_actual_this_run_native_tail_bytes(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, histories, queue = fake_http(monkeypatch, cfg)
    mock_metadata(monkeypatch)
    p.tick(run)
    assert len(calls) == 1
    complete_protocol_segment(run, cfg, 0, calls, histories, queue)
    assert p.tick(run)['technical_saved'] == 1
    p.tick(run)
    assert len(calls) == 2
    first = p.read(run / 'segments/S01/RESULT.json')
    second = p.read(run / 'segments/S02/SEGMENT.json')
    assert second['first_frame']['sha256'] == first['files']['last']['sha256']
    assert Path(second['first_frame']['path']).read_bytes() == Path(first['files']['last']['source_path']).read_bytes()
    assert second['provenance']['previous_prompt_id'] == first['prompt_id']
    assert calls[1]['prompt']['condition']['inputs']['prompt'] == p.read(p.SOURCE / 'segments/S02/REQUEST.actual.json')['content'][0]['text']
    assert len((run / 'NATIVE_IDS.jsonl').read_text().splitlines()) == 2
    assert (run / 'job_ids.txt').read_text().splitlines() == ['S01 timing_protocol_fixture_1', 'S02 timing_protocol_fixture_2']


def test_claimed_unknown_never_reposts_even_state_deleted(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    p.tick(run)
    folder = run / 'segments/S01'
    (folder / 'RESPONSE.json').unlink()
    (folder / 'STATE.json').unlink()
    assert p.tick(run)['segments'][0]['status'] == 'outcome_unknown'
    assert len(calls) == 1


def test_post_transport_loss_keeps_claim_and_does_not_retry(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    original = p.h3._http
    posts = []
    def lose(cfg, route, value=None):
        if route == '/prompt':
            posts.append(value)
            raise TimeoutError('response lost, original outcome unknown')
        return original(cfg, route, value)
    monkeypatch.setattr(p.h3, '_http', lose)
    assert p.tick(run)['segments'][0]['status'] == 'outcome_unknown'
    assert p.tick(run)['segments'][0]['status'] == 'outcome_unknown'
    assert len(posts) == 1 and not calls


def test_original_id_absent_is_retained_and_later_collected(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, histories, queue = fake_http(monkeypatch, cfg)
    mock_metadata(monkeypatch)
    p.tick(run)
    queue['queue_running'] = []
    first = p.tick(run)
    assert first['segments'][0]['status'] == 'outcome_unknown'
    pid = first['segments'][0]['prompt_id']
    complete_protocol_segment(run, cfg, 0, calls, histories, queue)
    assert p.tick(run)['technical_saved'] == 1
    assert len(calls) == 1
    assert p.read(run / 'segments/S01/RESULT.json')['prompt_id'] == pid


def test_protected_pause_mutation_blocks_before_post(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    p.PAUSE.write_bytes(b'changed pause')
    with pytest.raises(p.ParityError, match='bound_file_changed'):
        p.tick(run)
    assert not calls and not list(run.rglob('CLAIM.json'))


def test_native_queue_and_local_pause_prevent_dispatch(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, queue = fake_http(monkeypatch, cfg)
    queue['queue_pending'] = [[1, 'unrelated_original_id', {}, {}]]
    assert p.tick(run)['dispatch'] == 'waiting_gpu_queue'
    assert not calls
    queue['queue_pending'] = []
    (run / 'PAUSE.json').write_text('{}')
    assert p.tick(run)['paused'] is True
    assert not calls


def test_claimed_original_is_polled_while_source_pause_changed(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, histories, queue = fake_http(monkeypatch, cfg)
    mock_metadata(monkeypatch)
    p.tick(run)
    complete_protocol_segment(run, cfg, 0, calls, histories, queue)
    p.PAUSE.write_bytes(b'source changed blocks new POST only')
    assert p.tick(run)['technical_saved'] == 1
    with pytest.raises(p.ParityError):
        p.tick(run)
    assert len(calls) == 1


def test_history_permits_only_observed_float_casts(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, histories, queue = fake_http(monkeypatch, cfg)
    mock_metadata(monkeypatch)
    p.tick(run)
    entry = complete_protocol_segment(run, cfg, 0, calls, histories, queue)
    entry['prompt'][2]['condition']['inputs']['prompt'] += '\nextra wrapper is forbidden'
    with pytest.raises(p.ParityError, match='native_history_graph_changed'):
        p.tick(run)
    assert not (run / 'segments/S01/RESULT.json').exists()
    assert len(calls) == 1


def test_status_does_not_write_or_contact_service(env, monkeypatch):
    run, _ = env
    p.prepare(run)
    before = {str(x): (x.stat().st_mtime_ns, p.sha(x)) for x in run.rglob('*') if x.is_file()}
    monkeypatch.setattr(p.h3, '_http', lambda *a: pytest.fail('status used HTTP'))
    assert p.status(run)['technical_saved'] == 0
    after = {str(x): (x.stat().st_mtime_ns, p.sha(x)) for x in run.rglob('*') if x.is_file()}
    assert before == after


def test_clock_builder_never_uses_container_duration_or_fps_filter():
    command, filters = p.assembly_command(['one.mp4', 'two.mp4', 'three.mp4', 'four.mp4'], 'filter', 'out')
    assert filters.count('trim=end_frame=362') == 4
    assert filters.count('atrim=end_sample=724000') == 4
    assert 'settb=1/24,setpts=N' in filters and 'asettb=1/48000,asetpts=N' in filters
    assert 'fps=' not in filters and 'async=1' not in filters
    assert '-r' not in command and 'concat' not in command


def test_durable_response_recovers_same_id_after_state_loss(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    p.tick(run)
    (run / 'segments/S01/STATE.json').unlink()
    assert p.tick(run)['segments'][0]['prompt_id'] == 'timing_protocol_fixture_1'
    assert len(calls) == 1
    assert len((run / 'NATIVE_IDS.jsonl').read_text().splitlines()) == 1
    assert (run / 'job_ids.txt').read_text().splitlines() == ['S01 timing_protocol_fixture_1']


def test_stale_local_graph_is_rejected_before_claim(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    path = run / 'segments/S01/workflow_api.json'
    graph = p.read(path)
    graph['condition']['inputs']['last_frame'] = ['ref_scene', 0]
    path.write_text(json.dumps(graph), encoding='utf-8')
    with pytest.raises(p.ParityError, match='bound_file_changed'):
        p.tick(run)
    assert not calls and not (run / 'segments/S01/CLAIM.json').exists()


def test_occupied_input_name_and_wrong_service_paths_block_before_post(env, monkeypatch):
    run, cfg = env
    plan = p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    row = p.read(run / 'segments/S01/SEGMENT.json')
    target = Path(cfg['input_root']) / row['input_name']
    target.parent.mkdir(parents=True)
    target.write_bytes(b'another file must never be overwritten')
    with pytest.raises(p.ParityError, match='existing_copy_changed'):
        p.tick(run)
    assert target.read_bytes() == b'another file must never be overwritten'
    assert not calls and not (run / 'segments/S01/CLAIM.json').exists()
    original = p.h3._http
    def wrong(cfg, route, value=None):
        if route == '/system_stats':
            return dict(system=dict(argv=['comfy', '--input-directory', str(run), '--output-directory', cfg['output_root']]))
        return original(cfg, route, value)
    monkeypatch.setattr(p.h3, '_http', wrong)
    with pytest.raises(p.h3.HandoffIntegrityError, match='wrong_h3_service_paths'):
        p.tick(run)
    assert not calls


def test_shared_gpu_and_input_lease_are_obeyed(env, monkeypatch):
    run, cfg = env
    p.prepare(run)
    calls, _, _ = fake_http(monkeypatch, cfg)
    with p.jobs.run_lock(Path(cfg['gpu_lock_root']), 'GPU.lock'):
        with pytest.raises(p.jobs.JobBusyError):
            p.tick(run)
    with p.jobs.run_lock(Path(cfg['input_root']), 'VISUAL_GPU.lock'):
        with pytest.raises(p.jobs.JobBusyError):
            p.tick(run)
    assert not calls


def test_four_distinct_native_ids_and_video_hashes_are_required(env, monkeypatch):
    run, _ = env
    plan = p.prepare(run)
    fake = [dict(id=name, prompt_id='repeated-id', files=dict(video=dict(sha256='one-file', source_path='one-path')),
                 native_frames=362, fps=24, original_prompt_utf8_sha256=p.PROMPT_SHAS[i]) for i, name in enumerate(p.IDS)]
    monkeypatch.setattr(p, '_result', lambda run, plan, index: fake[index])
    with pytest.raises(p.ParityError, match='four_distinct_actual_native_videos_required'):
        p._production_rows(run, plan)
    assert not (run / 'FINAL_RESULT.json').exists()


def clock_metadata(frames=1448):
    return dict(streams=[dict(codec_type='video', width=736, height=1312, nb_frames=frames, nb_read_frames=frames,
                     r_frame_rate='24/1', avg_frame_rate='24/1', start_time='0', duration_ts=frames*512, time_base='1/12288'),
                dict(codec_type='audio', sample_rate='48000', channels=2, start_time='0',
                     duration_ts=frames*2000, time_base='1/48000')], format=dict(duration=str(frames/24)))


@pytest.mark.parametrize('change', [
    lambda m: m['streams'][0].update(nb_read_frames=1447),
    lambda m: m['streams'][0].update(nb_frames=1450, nb_read_frames=1450),
    lambda m: m['streams'][0].update(start_time='0.041016'),
    lambda m: m['streams'][1].update(start_time='0.001'),
    lambda m: m['streams'][1].update(duration_ts=2896002),
    lambda m: m['streams'][0].update(duration_ts=1448*512+1),
])
def test_final_clock_rejects_extra_frames_aac_delay_and_sample_drift(change):
    metadata = clock_metadata()
    assert p.verify_clock(metadata)['audio_samples'] == 2896000
    change(metadata)
    with pytest.raises(p.ParityError):
        p.verify_clock(metadata)


def test_excessive_native_audio_skew_stops_before_decode(monkeypatch):
    metadata = clock_metadata(362)
    metadata['streams'][1].update(duration_ts=362*2000+12001)
    monkeypatch.setattr(p, '_probe', lambda *a: metadata)
    monkeypatch.setattr(p.subprocess, 'check_output', lambda *a, **k: pytest.fail('decoded despite excessive skew'))
    with pytest.raises(p.ParityError, match='native_av_skew_exceeds'):
        p._inspect_clip('TIMING_ONLY.mp4')


def ffmpeg(args):
    return subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-filter_threads', '1',
                           '-filter_complex_threads', '1', *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=180)


def test_cpu_timing_only_four_h3_buckets_keep_1448_frames_and_exact_pcm(tmp_path):
    """64x80 generated fixtures are NOT real H3 jobs or eligible production input."""
    paths = []
    for i, extra in enumerate((512, -3200, 512, -1600)):
        path = tmp_path / f'TIMING_ONLY_{i}_362.mp4'
        samples = -(-362*32000//24) + extra
        filters = f'[0:v]trim=end_frame=362,setpts=N/(24*TB)[v];[1:a]atrim=end_sample={samples},asetpts=N/SR/TB[a]'
        ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=64x80:rate=24', '-f', 'lavfi', '-i',
                f'sine=frequency={440+i*100}:sample_rate=32000', '-filter_complex', filters, '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-threads', '1', '-c:a', 'aac',
                '-ar', '32000', '-ac', '2', '-video_track_timescale', '12288', str(path)])
        paths.append(path)
    inspected = [p._inspect_clip(path, expected_sha256=p.sha(path)) for path in paths]
    assert inspected[0]['trim_tail_samples'] > 0 and inspected[1]['pad_tail_samples'] > 0
    script, output = tmp_path/'TIMING_ONLY.filter', tmp_path/'TIMING_ONLY_60s.mp4'
    command, filters = p.assembly_command(paths, script, output, preset='ultrafast')
    script.write_text(filters, encoding='utf-8')
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    metadata = p._probe(output, True)
    assert p.verify_clock(metadata, width=64, height=80)['native_frames'] == 1448
    audio = next(s for s in metadata['streams'] if s['codec_type'] == 'audio')
    assert int(audio['duration_ts']) == 2896000
    assert p._duration(audio) == Fraction(1448, 24)
    reference = b''
    for path in paths:
        pcm = ffmpeg(['-i', str(path), '-map', '0:a:0', '-af', 'aresample=48000:async=0:first_pts=0',
                       '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1']).stdout
        reference += pcm[:724000*4] + b'\0'*max(0, 724000*4-len(pcm))
    pcm_script = tmp_path/'TIMING_ONLY_pcm.filter'
    pcm_script.write_text(filters + ';[video]nullsink\n', encoding='utf-8')
    inputs = [part for path in paths for part in ('-threads', '1', '-i', str(path))]
    actual = ffmpeg([*inputs, '-filter_complex_script', str(pcm_script), '-map', '[audio]',
                     '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1']).stdout
    assert actual == reference and len(actual)//4 == 2896000
    # Native production gate is independent of valid clocks and needs real results.
    with pytest.raises((FileNotFoundError, KeyError)):
        p._production_rows(tmp_path, dict())
    assert not (tmp_path/'FINAL_RESULT.json').exists()


@pytest.mark.parametrize('lose_response', [False, True])
def test_independent_cli_processes_real_loopback_transport_preserve_one_post(env, tmp_path, lose_response):
    """CLI, OS locks and HTTP transport, all inside temporary protocol fixtures."""
    run, cfg = env
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            if self.path == '/system_stats':
                self.respond(dict(system=dict(argv=['comfy', '--input-directory', cfg['input_root'],
                                                     '--output-directory', cfg['output_root']])))
            elif self.path == '/queue':
                self.respond(dict(queue_running=[[0, 'protocol_cli_only_1', requests[0]['prompt'], {}]] if requests else [],
                                  queue_pending=[]))
            elif self.path.startswith('/history/'):
                self.respond({})
            else:
                raise AssertionError(self.path)
        def do_POST(self):
            assert self.path == '/prompt'
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if lose_response:
                self.close_connection = True
                return
            self.respond(dict(prompt_id='protocol_cli_only_1', node_errors={}))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    worker = tmp_path / 'QA_ONLY_cli_driver.py'
    settings = dict(run=str(run), work=str(p.WORKING), models=str(p.MODEL_ROOT), pause=str(p.PAUSE),
                    pause_sha=p.PAUSE_SHA, auth_sha=p.AUTHORIZATION_SHA, url=f'http://127.0.0.1:{server.server_port}',
                    cli=str(p.ROOT / 'scripts/run_h3_seedance_prompt_parity_v19.py'), root=str(p.ROOT))
    worker.write_text('''import json,runpy,sys
from pathlib import Path
settings=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
sys.path.insert(0,settings['root'])
from src.content_factory import visual_h3_prompt_parity_v19 as p
p.RUN=Path(settings['run']);p.WORKING=Path(settings['work']);p.MODEL_ROOT=Path(settings['models'])
p.PAUSE=Path(settings['pause']);p.PAUSE_SHA=settings['pause_sha'];p.AUTHORIZATION_SHA=settings['auth_sha']
real_http=p.h3._http
def protocol_http(cfg,route,value=None):
    return real_http(dict(cfg,service_url=settings['url']),route,value)
p.h3._http=protocol_http
command=sys.argv[2]
sys.argv=[settings['cli'],command,'--run',settings['run'],'--through','S01','--max-seconds','0.001','--poll-seconds','0.01']
runpy.run_path(settings['cli'],run_name='__main__')
''', encoding='utf-8')
    settings_file = tmp_path / 'QA_ONLY_settings.json'
    settings_file.write_text(json.dumps(settings), encoding='utf-8')
    def invoke(command):
        result = subprocess.run([sys.executable, '-B', str(worker), str(settings_file), command],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    try:
        invoke('prepare')
        first = invoke('execute')
        second = invoke('execute')
        assert len(requests) == 1
        assert requests[0]['prompt']['condition']['inputs']['prompt'] == p._original_prompts()[0]['text']
        assert not {'last_frame', 'ref_images'} & requests[0]['prompt']['condition']['inputs'].keys()
        assert second['segments'][0]['status'] == ('outcome_unknown' if lose_response else 'running')
        if not lose_response:
            assert first['segments'][0]['prompt_id'] == second['segments'][0]['prompt_id'] == 'protocol_cli_only_1'
        assert (run/'segments/S01/CLAIM.json').exists() and not (run/'FINAL_RESULT.json').exists()
        assert p.sha(p.PAUSE) == p.PAUSE_SHA
    finally:
        server.shutdown();server.server_close();server_thread.join(5)
