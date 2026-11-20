"""CPU-only source, graph, original-ID and subprocess lifecycle checks.

The HTTP server below emits solid-colour fixture PNGs, never a model result.
"""
from contextlib import contextmanager
import copy
import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading

from PIL import Image
import pytest

from src.content_factory import visual_image_jobs_v3 as jobs
from src.content_factory import visual_scene_performance_stills_v36 as scene


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


@contextmanager
def server(root):
    state = dict(posts=0, graphs={}, completed=set(), reject=False, unknown=False)
    inputs, outputs = root/'input', root/'output'
    inputs.mkdir(); outputs.mkdir()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, value, code=200):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if self.path == '/system_stats':
                self.respond(dict(system=dict(argv=['main.py', '--input-directory', str(inputs), '--output-directory', str(outputs)])))
            elif self.path == '/queue':
                running = [[0, pid, g] for pid, g in state['graphs'].items() if pid not in state['completed']]
                self.respond(dict(queue_running=running, queue_pending=[]))
            elif self.path.startswith('/history/'):
                pid = self.path.rsplit('/', 1)[1]
                if pid not in state['completed']:
                    self.respond({}); return
                graph = state['graphs'][pid]
                images = {}
                dimensions = next(n['inputs'] for n in graph.values() if n['class_type']=='EmptyFlux2LatentImage')
                for nid, node in graph.items():
                    if node['class_type'] == 'SaveImage':
                        prefix = Path(node['inputs']['filename_prefix'])
                        target = outputs/prefix.parent/(prefix.name+'_00001_.png')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            Image.new('RGB', (dimensions['width'], dimensions['height']), 'navy').save(target)
                        images[nid] = dict(images=[dict(filename=target.name, subfolder=prefix.parent.as_posix(), type='output')])
                self.respond({pid: dict(prompt=[0, pid, graph], status=dict(completed=True, status_str='success'), outputs=images)})
            else:
                self.respond({}, 404)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['posts'] += 1
            if state['unknown']:
                self.respond(dict(error='unknown'), 500); return
            if state['reject']:
                self.respond(dict(error='invalid'), 400); return
            pid = 'fixture-original-'+str(state['posts'])
            state['graphs'][pid] = request['prompt']
            self.respond(dict(prompt_id=pid))
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    state.update(url=f'http://127.0.0.1:{httpd.server_port}', input_root=inputs, output_root=outputs)
    try:
        yield state
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)


def prepared(root, fake):
    files = {}
    for i, name in enumerate(('mother', *scene.CAST)):
        path = root/(name+'.png')
        Image.new('RGB', (64, 96), (40*i, 50, 80)).save(path)
        files[name] = path
    pause = root/'old_pause.json'; write(pause, {'untouched': True})
    cfg = root/'IMAGE_CONFIG.json'
    write(cfg, dict(service_url=fake['url'], input_root=str(fake['input_root']), output_root=str(fake['output_root']),
                    protected_pause_path=str(pause), verify_service_paths=True))
    auth = root/'AUTH.json'
    write(auth, dict(semantic_generation_gates=False, review_policy='user_reviews_completed_film',
                     engineering_limits=dict(image_submissions=8)))
    case = root/'source_case.json'; write(case, {'novel_source': 'fixture, not a production chapter'})
    mother_result = root/'mother_fixture_result.json'
    write(mother_result, dict(technical_status='saved', prompt_id='explicit-fixture-mother-original-id',
                             images=[dict(path=str(files['mother']), sha256=jobs.file_sha(files['mother']))]))
    spec = scene.make_spec(files['mother'], {k: files[k] for k in scene.CAST}, cfg, auth, case,
                           mother_native_result=mother_result, width=64, height=96)
    spec_path = root/'SPEC.json'; write(spec_path, spec)
    run = root/'scene'
    scene.prepare(spec_path, run)
    return run, spec_path, files, pause


def test_prepare_cpu_four_same_mothers_three_named_identities_no_semantic_gate(tmp_path):
    with server(tmp_path) as fake:
        run, spec, files, pause = prepared(tmp_path, fake)
        value = scene.prepare(spec, run)
        assert fake['posts'] == 0 and not value['complete']
        assert [s['status'] for s in value['shots']] == ['prepared']*4
        plan = jobs._read(run/'PLAN.json')
        assert len(plan['inputs']) == 4
        assert plan['inputs'][0]['original_source']['sha256'] == jobs.file_sha(files['mother'])
        for shot in plan['shots']:
            evidence = shot['reference_graph_evidence']
            assert evidence['positive_ancestry_verified'] is True
            assert [r['role'] for r in evidence['references']] == ['mother_photo', *scene.CAST]
        assert jobs._read(pause) == {'untouched': True}
        assert value['user_review_pending'] is True and value['semantic_generation_gates'] is False


@pytest.mark.parametrize('broken', ('remove_mother', 'negative_only', 'crop_instead', 'swap_identities', 'disconnected_sampler'))
def test_positive_pixel_ancestry_rejects_unconnected_or_substituted_refs(tmp_path, broken):
    with server(tmp_path) as fake:
        run, *_ = prepared(tmp_path, fake)
        plan = jobs._read(run/'PLAN.json'); shot = plan['shots'][0]
        graph = jobs._read(shot['graph']['path'])
        if broken == 'remove_mother':
            graph['S01__positive_ref_1']['inputs']['conditioning'] = ['S01__positive', 0]
        elif broken == 'negative_only':
            graph['S01__guider']['inputs']['positive'] = ['S01__positive', 0]
        elif broken == 'crop_instead':
            graph['S01__image_0']['class_type'] = 'ImageCrop'
        elif broken == 'swap_identities':
            a, b = graph['S01__image_1']['inputs'], graph['S01__image_2']['inputs']
            a['image'], b['image'] = b['image'], a['image']
        else:
            graph['S01__sample']['inputs']['guider'] = ['missing', 0]
        with pytest.raises(jobs.JobIntegrityError, match='positive_photographic'):
            scene.reference_graph_evidence(graph, 'S01', plan['inputs'])
        assert fake['posts'] == 0


def test_story_gaze_and_state_contracts_are_not_camera_portraits():
    states = scene.source_states()
    assert states['S01']['actors']['ye_xijue']['gaze'] == 'ye_nan'
    assert states['S02']['actors']['ye_xijue']['gaze'] == 'su_mo'
    assert states['S03']['actors']['su_mo']['eyes'] == 'open'
    assert states['S03']['bread_owner'] == 'ye_xijue' and states['S04']['bread_owner'] == 'su_mo'
    assert states['S04']['actors']['su_mo']['posture'] == 'standing_beside_same_bed'
    for sid in scene.SHOTS:
        assert all('camera' not in a['gaze'] for a in states[sid]['actors'].values())
        assert 'Image 1 is the authoritative same photographed room' in scene.performance_prompt(sid)


def test_mother_must_match_saved_native_provenance(tmp_path):
    with server(tmp_path) as fake:
        _, spec_path, *_ = prepared(tmp_path, fake)
        spec = jobs._read(spec_path)
        native = Path(spec['mother_native_result']['path'])
        write(native, dict(technical_status='saved', prompt_id='wrong-image', images=[]))
        spec['mother_native_result'] = scene._binding(native)
        other = tmp_path/'bad-mother-spec.json'; write(other, spec)
        with pytest.raises(jobs.JobIntegrityError, match='mother_must_match'):
            scene.prepare(other, tmp_path/'bad-scene')
        assert fake['posts'] == 0


def test_known_id_collect_survives_external_spec_photo_auth_and_case_change(tmp_path):
    with server(tmp_path) as fake:
        run, spec_path, files, pause = prepared(tmp_path, fake)
        before = pause.read_bytes()
        assert scene.submit_next(run)['shots'][0]['prompt_id'] == 'fixture-original-1'
        spec = jobs._read(spec_path)
        for path in (spec_path, Path(spec['authorization']['path']), Path(spec['source_case']['path'])):
            path.write_text('changed after original POST', encoding='utf-8')
        files['mother'].write_bytes(b'changed original photo')
        fake['completed'].add('fixture-original-1')
        status = scene.collect_known(run)
        assert status['shots'][0]['status'] == 'saved' and fake['posts'] == 1
        receipt = scene.result(run, 'S01')
        assert receipt['native_id'] == 'fixture-original-1'
        assert receipt['image']['dimensions'] == [64, 96]
        assert receipt['production_approved'] is False and receipt['content_status']=='user_review_pending'
        assert scene.collect_known(run) == status
        with pytest.raises(jobs.JobIntegrityError, match='bound_file_changed'):
            scene.submit_next(run)
        assert fake['posts'] == 1 and pause.read_bytes() == before


@pytest.mark.parametrize('mode,expected', [('unknown', 'outcome_unknown'), ('reject', 'rejected')])
def test_unknown_and_known_rejection_never_retry_or_skip_to_new_job(tmp_path, mode, expected):
    with server(tmp_path) as fake:
        run, *_ = prepared(tmp_path, fake)
        fake[mode] = True
        assert scene.submit_next(run)['shots'][0]['status'] == expected
        for _ in range(2):
            scene.submit_next(run); scene.collect_known(run)
        assert fake['posts'] == 1 and scene.budget(run)['claimed'] == 1
        assert scene.status(run)['shots'][1]['status']=='prepared'


@pytest.mark.parametrize('which', ['photo', 'spec', 'auth', 'graph', 'plan', 'snapshot'])
def test_modified_inputs_or_plan_cannot_dispatch(tmp_path, which):
    with server(tmp_path) as fake:
        run, spec, files, _ = prepared(tmp_path, fake)
        plan = jobs._read(run/'PLAN.json')
        path = {'photo': files['mother'], 'spec': spec,
                'auth': Path(plan['authorization']['path']),
                'graph': Path(plan['shots'][0]['graph']['path']),
                'plan': run/'PLAN.json', 'snapshot': run/'SPEC.snapshot.json'}[which]
        path.write_text('{}', encoding='utf-8')
        with pytest.raises((jobs.JobIntegrityError, ValueError, KeyError)):
            scene.submit_next(run)
        assert fake['posts'] == 0


def test_actual_subprocess_http_four_images_serial_resume_and_technical_result(tmp_path):
    """Real process+HTTP+PNG IO black box; fixture art is not production media."""
    with server(tmp_path) as fake:
        run, spec, _, pause = prepared(tmp_path, fake)
        before = pause.read_bytes()
        script = Path(__file__).resolve().parents[1]/'scripts/run_scene_performance_stills_v36.py'
        def cli(action):
            result = subprocess.run([sys.executable, str(script), action, '--run', str(run)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        for index, sid in enumerate(scene.SHOTS, 1):
            value = cli('submit-next')
            assert value['current'] == sid and fake['posts']==index
            assert cli('submit-next')['current'] == sid and fake['posts']==index
            fake['completed'].add('fixture-original-'+str(index))
            collected = cli('collect-known')
            assert collected['shots'][index-1]['status']=='saved'
        assert cli('status')['complete'] is True
        assert cli('submit-next')['dispatch']=='all_images_saved' and fake['posts']==4
        assert cli('budget')['remaining']==0 and scene.complete(run)
        for sid in scene.SHOTS:
            result = scene.result(run, sid)
            assert jobs.file_sha(result['image']['path'])==result['image']['sha256']
            assert jobs._read(result['native_result']['path'])['technical_status']=='saved'
        assert pause.read_bytes()==before


def test_changed_saved_png_rejected_not_marked_complete(tmp_path):
    with server(tmp_path) as fake:
        run, *_ = prepared(tmp_path, fake)
        scene.submit_next(run); fake['completed'].add('fixture-original-1'); scene.collect_known(run)
        receipt = scene.result(run, 'S01')
        Path(receipt['image']['path']).write_bytes(b'not the original native PNG')
        with pytest.raises(jobs.JobIntegrityError):
            scene.complete(run)
