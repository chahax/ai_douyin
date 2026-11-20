"""Independent prepare-only CLI black boxes, with an audited offline sandbox.

Fixtures are deterministic test bytes. No real inference, ASR, HTTP, GPU,
model weights or production media are allowed in the child CLI process.
"""
from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
PARENT = PROJECT / 'data/qa/h3_asset_flow_offline_blackbox_v2'

GUARD = r'''
import json, os, sys
from pathlib import Path
ROOT = Path(os.environ['H3_OFFLINE_TEST_ROOT']).resolve()
LOG = ROOT / 'OFFLINE_AUDIT.jsonl'
RUNTIMES = {'torch','transformers','diffusers','tensorflow','onnxruntime','vllm','ollama','llama_cpp','whisper','faster_whisper','funasr'}
WEIGHTS = {'.safetensors','.ckpt','.gguf','.onnx','.pt','.pth'}
def log(event):
    with LOG.open('a',encoding='utf-8') as h:
        h.write(json.dumps({'event':event})+'\n')
def deny(event):
    log('blocked:'+event)
    raise RuntimeError('OFFLINE_BLACKBOX_PROHIBITED:'+event)
def inside(path):
    if isinstance(path,(str,bytes,os.PathLike)):
        return Path(os.fsdecode(path)).resolve().is_relative_to(ROOT)
    return True
def audit(event,args):
    if event.startswith('socket.') and event not in {'socket.__new__'}:
        deny(event)
    if event in {'subprocess.Popen','os.system','os.posix_spawn','os.spawn','pty.spawn'}:
        deny(event)
    if event=='import' and args and str(args[0]).split('.')[0] in RUNTIMES:
        deny('model_or_ASR_runtime_import')
    if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0])); mode=args[1] if len(args)>1 else None; flags=args[2] if len(args)>2 else 0
        if path.suffix.lower() in WEIGHTS:
            deny('model_weight_read')
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_TRUNC)))
        if writing and not inside(path): deny('write_outside_fixture')
    if event in {'os.mkdir','os.remove','os.rmdir','os.unlink'} and args and not inside(args[0]):
        deny('mutation_outside_fixture')
    if event in {'os.rename','os.replace'} and any(not inside(a) for a in args[:2]):
        deny('mutation_outside_fixture')
sys.addaudithook(audit)
log('guard_loaded')
'''


class OfflineCLIHarness:
    def __init__(self, root):
        self.root = Path(root).resolve()
        assert self.root.is_relative_to(PARENT.resolve())
        self.guard = self.root / 'guard'; self.guard.mkdir(parents=True)
        (self.guard / 'sitecustomize.py').write_text(GUARD, encoding='utf-8')

    def run(self, args, *, allow_blocked=False, timeout=40):
        log = self.root / 'OFFLINE_AUDIT.jsonl'
        if log.exists(): log.unlink()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
                   PYTHONPATH=os.pathsep.join((str(self.guard), str(PROJECT))), H3_OFFLINE_TEST_ROOT=str(self.root))
        result = subprocess.run([sys.executable, *map(str, args)], cwd=PROJECT, env=env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=timeout)
        events = [json.loads(line)['event'] for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
        if 'guard_loaded' not in events: raise AssertionError('The child offline audit guard was not active: '+result.stderr)
        blocked = [event for event in events if event.startswith('blocked:')]
        if blocked and not allow_blocked: raise AssertionError('CLI tried forbidden activity: '+str(blocked)+'\n'+result.stderr)
        return result, events


def official_cpu_consumption(graph, manifest):
    """Execute installed official node/model methods on CPU doubles only.

    The saved draft uses future input names; manifest-bound source files supply
    the same CPU image/audio values here. This does not claim physical staging,
    GPU inference, voice identity, or generated quality.
    """
    from PIL import Image
    import numpy as np
    import soundfile as sf
    nodes = Path('D:/IT/AI_vido/ComfyUI/comfy_extras/nodes_minimax_h3.py')
    model = Path('D:/IT/AI_vido/ComfyUI/comfy/model_base.py')
    helper = Path('D:/IT/AI_vido/ComfyUI/node_helpers.py')
    def require(ok, message):
        if not ok: raise AssertionError(message)
    def binding(path):
        path = Path(path).resolve(); return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def method(path, name, owner=None):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        body = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner).body if owner else tree.body
        found = [n for n in body if isinstance(n, ast.FunctionDef) and n.name == name]
        require(len(found) == 1, 'exact_official_source_method_required')
        node = deepcopy(found[0]); node.decorator_list = []; return node
    class Tensor:
        def __init__(self, tag, shape, source_sha=None, data=None):
            self.tag, self.source_sha, self.data = tag, source_sha, data
            self.shape = tuple(data.shape) if data is not None else tuple(shape); self.ndim = len(self.shape)
        def __getitem__(self, index):
            if self.data is not None: return Tensor(self.tag, (), self.source_sha, self.data[index])
            require(isinstance(index, slice), 'unexpected_image_stub_index')
            return self
        def movedim(self, a, b):
            require(self.data is not None, 'actual_decoded_waveform_required')
            return Tensor(self.tag, (), self.source_sha, np.moveaxis(self.data, a, b))
    image_calls, audio_calls, resamples = [], [], []
    def resize(image, width, height, crop):
        return Tensor(image.tag, (image.shape[0], height, width, image.shape[-1]), image.source_sha)
    def resample(wave, old, new):
        require(wave.data is not None and wave.data.ndim == 3, 'decoded_AUDIO_contract_required')
        length = round(wave.shape[-1] * new / old)
        old_x = np.arange(wave.shape[-1]); new_x = np.linspace(0, wave.shape[-1] - 1, length)
        values = np.stack([np.stack([np.interp(new_x, old_x, channel) for channel in batch]) for batch in wave.data]).astype('float32')
        resamples.append(dict(tag=wave.tag, from_rate=old, to_rate=new, from_frames=wave.shape[-1], to_frames=length))
        return Tensor(wave.tag, (), wave.source_sha, values)
    class VideoVAE:
        def encode(self, image):
            image_calls.append(dict(tag=image.tag, source_sha256=image.source_sha, shape=list(image.shape)))
            return Tensor(image.tag, (1, 24, 1, image.shape[1] // 16, image.shape[2] // 16), image.source_sha)
    class AudioVAE:
        audio_sample_rate = 32000
        def encode(self, wave):
            require(wave.data is not None and wave.ndim == 3 and wave.shape[0] == 1 and wave.shape[-1] in (1, 2),
                    'audio_VAE_must_receive_real_decoded_movedim_samples')
            audio_calls.append(dict(tag=wave.tag, source_sha256=wave.source_sha, shape=list(wave.shape),
                                    actual_sample_sha256=hashlib.sha256(wave.data.tobytes()).hexdigest()))
            return Tensor(wave.tag, (1, 32, 2, max(1, wave.shape[1] // 320)), wave.source_sha)
    class Clip:
        def tokenize(self, prompt, **kwargs): return kwargs
        def encode_from_tokens_scheduled(self, tokens):
            self.items = tokens['minimax_ref_items']; return [[None, {}]]
    refs = manifest['references']; voices = manifest['voice_resolution']['voices']; condition = graph['condition']['inputs']
    require(len(refs) == 9 and len(voices) <= 3, 'complete_nine_image_and_at_most_three_audio_contract')
    require(condition['vae'] == ['119', 0] and graph['119']['class_type'] == 'VAELoader'
            and 'video' in graph['119']['inputs']['vae_name'], 'actual_video_VAE_connection_required')
    require(graph['126']['inputs']['conditioning'] == ['guide_start', 0]
            and graph['125']['inputs']['guider'] == ['126', 0]
            and graph['125']['inputs']['latent_image'] == ['condition', 1], 'positive_and_latent_must_reach_actual_sampler')
    require(set(k for k in condition if k.startswith('ref_images.')) == {f'ref_images.ref_image_{i}' for i in range(9)},
            'all_nine_actual_image_ports_required')
    image_inputs = {}; audio_inputs = {}
    for i, ref in enumerate(refs):
        require(condition[f'ref_images.ref_image_{i}'] == [f'ref_{i}', 0]
                and graph[f'ref_{i}'] == dict(class_type='LoadImage', inputs={'image': ref['input_name']}),
                'actual_image_LoadImage_slot_changed')
        path = Path(ref['image']['path']); require(binding(path) == ref['image'], 'source_image_bytes_changed')
        with Image.open(path) as image:
            require(getattr(image, 'n_frames', 1) == 1, 'one_reference_one_image')
            image_inputs[f'ref_image_{i}'] = Tensor(f'P{i+1}', (1, image.height, image.width, 3), hashlib.sha256(image.convert('RGB').tobytes()).hexdigest())
    require(set(k for k in condition if k.startswith('ref_audios.')) == {f'ref_audios.ref_audio_{i}' for i in range(len(voices))},
            'every_manifest_voice_must_have_an_actual_audio_port')
    for i, voice in enumerate(voices):
        require(voice['slot'] == i and condition[f'ref_audios.ref_audio_{i}'] == [f'voice_{i}', 0]
                and graph[f'voice_{i}'] == dict(class_type='LoadAudio', inputs={'audio': voice['input_name']}),
                'actual_audio_LoadAudio_slot_changed')
        path = Path(voice['audio']['path']); require(binding(path) == voice['audio'], 'actual_reference_waveform_hash_changed')
        data, rate = sf.read(path, dtype='float32', always_2d=True)
        require(len(data) > 0 and data.shape[1] in (1, 2) and np.isfinite(data).all(), 'real_finite_AUDIO_samples_required')
        audio_inputs[f'ref_audio_{i}'] = dict(sample_rate=rate,
            waveform=Tensor(f'A{i+1}', (), voice['audio']['sha256'], np.swapaxes(data[None, :, :], 1, 2)))
    ns = dict(math=math, CANVAS_MULTIPLE=32, REF_IMAGE_SHORT_EDGE=2048, FRAME_PER_TOKEN=(1, 4, 4, 4, 4), FRAME_RESCALE=5.0/3.0,
              FPS=24, _resize=resize, io=SimpleNamespace(NodeOutput=lambda *items: items),
              comfy=SimpleNamespace(audio=SimpleNamespace(resample=resample)))
    latent = dict(samples=SimpleNamespace(is_nested=True, tensors=(Tensor('video', (1, 24, 107, 82, 46)), Tensor('audio', (1, 32, 2, 603)))))
    ns['_empty_av_latent'] = lambda width, height, length: (latent, 362)
    def install(path, name, owner=None):
        node = method(path, name, owner); exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), ns)
        return ns[name]
    setter = install(helper, 'conditioning_set_values'); ns['node_helpers'] = SimpleNamespace(conditioning_set_values=setter)
    install(nodes, '_encode_ref_audio')
    reference_execute = install(nodes, 'execute', 'MiniMaxH3ReferenceToVideo')
    guide_execute = install(nodes, 'execute', 'MiniMaxH3AddGuide')
    # Missing audio_vae deliberately reaches the official branch; tokenizer
    # audio labels alone must fail the final latent-payload assertion below.
    audio_vae = None
    if 'audio_vae' in condition:
        port = condition['audio_vae']; require(port == ['120', 0] and graph['120']['class_type'] == 'VAELoader'
                  and 'audio' in graph['120']['inputs']['vae_name'], 'real_reference_audio_VAE_loader_required')
        audio_vae = AudioVAE()
    clip, vae = Clip(), VideoVAE()
    positive, out_latent = reference_execute(None, clip=clip, vae=vae, audio_vae=audio_vae, prompt=condition['prompt'],
         width=736, height=1312, length=362, ref_image_size='match', ref_images=image_inputs, ref_audios=audio_inputs)
    guide = graph['guide_start']['inputs']
    require(guide['positive'] == ['condition', 0] and guide['latent'] == ['condition', 1] and guide['image'] == ['ref_8', 0]
            and guide['frame_idx'] == 0, 'P9_actual_guide_frame_zero_required')
    positive, = guide_execute(None, positive=positive, latent=out_latent, frame_idx=0, vae=vae, image=image_inputs['ref_image_8'])
    class Base:
        def extra_conds(self, **kwargs): return {}
    model_method = method(model, 'extra_conds', 'MiniMaxH3')
    cls = ast.ClassDef(name='CPUOfficialMiniMaxH3', bases=[ast.Name(id='Base', ctx=ast.Load())], keywords=[], body=[model_method], decorator_list=[])
    model_ns = dict(Base=Base, comfy=SimpleNamespace(conds=SimpleNamespace(CONDConstant=lambda value: value)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(model), 'exec'), model_ns)
    instance = model_ns['CPUOfficialMiniMaxH3'](); instance.audio_scale = lambda: 1.0
    payload = instance.extra_conds(**positive[0][1])['minimax_payload']
    require(len(audio_calls) == len(voices) and len(payload.get('cond_audio_latents', [])) == len(voices),
            'official_reference_audio_not_encoded_into_model_payload')
    require([x.tag for x in payload['cond_audio_latents']] == [f'A{i+1}' for i in range(len(voices))], 'actual_audio_latent_order_changed')
    require([x.tag for x in payload['cond_video_latents']] == ['P9'] + [f'P{i+1}' for i in range(9)]
            and len(image_calls) == 10 and payload['keyframes'][0]['resolved_frame_index'] == 0,
            'official_image_or_guide_latent_consumption_incomplete')
    return dict(schema='independent_official_ref_audio_CPU_protocol/v2', official_sources=[binding(nodes), binding(model), binding(helper)],
                image_VAE_calls=image_calls, audio_VAE_calls=audio_calls, resample_calls=resamples,
                model_positive_images=9, model_positive_audio_latents=len(payload['cond_audio_latents']), model_positive_keyframes=1,
                CPU_doubles=True, actual_decoded_waveforms=True, model_inference=False, physical_staging=False,
                voice_identity_locked=False, generated_quality_passed=False)


class OfflineGuardSelfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PARENT.mkdir(parents=True, exist_ok=True)

    def check_blocked(self, code, wanted):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness = OfflineCLIHarness(directory)
            result, events = harness.run(['-c', code], allow_blocked=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(any(wanted in event for event in events), (events, result.stderr))

    def test_guard_blocks_network_before_connecting(self):
        self.check_blocked("import socket; socket.socket().connect(('127.0.0.1',1))", 'socket.connect')

    def test_guard_blocks_nested_process_launch(self):
        self.check_blocked("import subprocess,sys; subprocess.run([sys.executable,'-c','print(1)'])", 'subprocess.Popen')

    def test_guard_blocks_in_process_model_runtime_import(self):
        self.check_blocked('import torch', 'model_or_ASR_runtime_import')

    def test_guard_blocks_weight_loading(self):
        self.check_blocked("open('unneeded.safetensors','rb')", 'model_weight_read')

    def test_guard_blocks_writes_outside_fixture(self):
        self.check_blocked("open('SHOULD_NOT_WRITE_FROM_CLI.txt','w').write('bad')", 'write_outside_fixture')

    def test_fixture_only_json_program_runs_without_forbidden_activity(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness = OfflineCLIHarness(directory)
            result, events = harness.run(['-c', "import json,os; from pathlib import Path; (Path(os.environ['H3_OFFLINE_TEST_ROOT'])/'ok.json').write_text(json.dumps({'production_ready':False})); print('ok')"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'ok')
            self.assertEqual(events, ['guard_loaded'])


def state_case():
    actors = ['ye_nan', 'ye_xijue', 'ye_dong', 'ye_yaner']
    def visible(ids):
        return {cid: {'pose': 'source-bound fixture posture', 'visible_parts': ['face', 'torso', 'hands']} for cid in ids}
    beats = [dict(start=0, end=4.1, cut=False, framing='medium', actors=visible(['ye_nan', 'ye_dong'])),
             dict(start=4.1, end=8, cut=True, framing='face_close', actors=visible(['ye_yaner'])),
             dict(start=8, end=14.2, cut=True, framing='face_close', actors=visible(['ye_dong'])),
             dict(start=14.2, end=15, cut=True, framing='medium', actors=visible(actors))]
    initial = {cid: dict(instance_id=cid + ':primary', position='unknown', posture='unknown', gaze='unknown', held_items=[],
                        body_ownership={'body': cid + ':primary'}) for cid in actors}
    rows = [dict(beat_index=i, deltas=[], body_actions=[], asserted_states={}) for i in range(4)]
    rows[2]['body_actions'] = [dict(performer_actor_id='ye_dong', owner_actor_id='ye_dong', body_part='right_wrist',
                                  relation='self', action='looks_at_own_wrist', source_span_ids=['action_0'])]
    return dict(schema='shot_actor_continuity_case/v1', actors=actors, camera_beats=beats,
                audio=[dict(speaker='ye_nan', mode='onscreen', start=.2, end=3.9),
                       dict(speaker='ye_yaner', mode='onscreen', start=4.2, end=7.8),
                       dict(speaker='ye_dong', mode='onscreen', start=8.2, end=13.9)],
                source_spans=[dict(id='action_0', kind='action', text='The boy looks at his own wrist.')],
                state_plan=dict(schema='shot_actor_state_plan/v1', initial=initial,
                                source_actions=[dict(source_span_id='action_0', actor_id='ye_dong', allowed_changes=['gaze'], body_parts=['right_wrist'])],
                                beats=rows),
                available_views={cid: ['front', 'left_oblique'] for cid in actors}, room_views=['front', 'side'],
                guide=dict(actual=True, image={'path': 'fixture-guide.png', 'sha256': 'a' * 64}), max_references=9,
                previous_selection={'actor_views': {cid: ['front', 'left_oblique'] if cid in ['ye_nan', 'ye_yaner'] else ['front'] for cid in actors}})


class OfflineComponentBlackBoxes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PARENT.mkdir(parents=True, exist_ok=True)

    def evaluate(self, case):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness = OfflineCLIHarness(directory)
            (Path(directory) / 'case.json').write_text(json.dumps(case), encoding='utf-8')
            code = "import json,os; from pathlib import Path; from src.content_factory import shot_actor_continuity_v1 as s; print(json.dumps(s.evaluate(json.loads((Path(os.environ['H3_OFFLINE_TEST_ROOT'])/'case.json').read_text()))))"
            result, _ = harness.run(['-c', code])
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_cut_return_keeps_same_instances_and_unknown_is_never_guessed(self):
        result = self.evaluate(state_case())
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['production_ready'])
        rows = result['state_plan_result']['beats']
        for row in rows:
            self.assertEqual(row['after']['ye_dong']['instance_id'], 'ye_dong:primary')
            self.assertEqual(row['after']['ye_dong']['posture'], 'unknown')
        self.assertEqual(rows[-1]['visible_instance_map']['ye_dong'], 'ye_dong:primary')
        angles = result['angle_selection']
        self.assertEqual(angles['side_priority'][0], 'ye_dong')
        self.assertEqual(angles['actor_views']['ye_dong'], ['front', 'left_oblique'])
        self.assertTrue(all('front' in views for views in angles['actor_views'].values()))
        self.assertEqual(angles['reference_budget']['used'], 9)
        self.assertTrue(angles['previous_selection_recomputed'])

    def test_cut_cannot_assert_a_new_pose_without_a_source_action(self):
        case = state_case(); case['state_plan']['beats'][-1]['asserted_states'] = {'ye_dong': {'posture': 'standing'}}
        result = self.evaluate(case)
        self.assertNotEqual(result['status'], 'ready')
        self.assertTrue(any(n['code'] == 'asserted_state_does_not_follow_carried_entity' for n in result['notices']))

    def test_self_wrist_action_cannot_use_another_child_body(self):
        case = state_case(); case['state_plan']['beats'][2]['body_actions'][0]['owner_actor_id'] = 'ye_nan'
        result = self.evaluate(case)
        self.assertNotEqual(result['status'], 'ready')
        self.assertTrue(any(n['code'] == 'self_body_action_owner_mismatch' for n in result['notices']))

    def test_duplicate_cast_instance_or_missing_priority_side_is_a_notice(self):
        case = state_case(); case['state_plan']['initial']['ye_nan']['instance_id'] = 'ye_dong:primary'
        result = self.evaluate(case)
        self.assertNotEqual(result['status'], 'ready')
        case = state_case(); case['available_views']['ye_dong'] = ['front']
        result = self.evaluate(case)
        self.assertNotEqual(result['status'], 'ready')
        self.assertTrue(any(n['code'] == 'priority_actor_side_view_missing' and n['actor_id'] == 'ye_dong' for n in result['notices']))

    def voice_program(self, program):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness = OfflineCLIHarness(directory)
            setup = """
import json,os,struct,wave
from pathlib import Path
from src.content_factory import voice_asset_registry_v1 as v
root=Path(os.environ['H3_OFFLINE_TEST_ROOT']); library=root/'voices'
def candidate(cid):
    path=root/(cid+'.wav')
    with wave.open(str(path),'wb') as h:
        h.setnchannels(1);h.setsampwidth(2);h.setframerate(16000);h.writeframes(b'\\x01\\x00'*3200)
    return v.register_candidate(library,path,book_id='fixture',character_id=cid,reference_text='fixture placeholder',source={'kind':'deterministic_CPU_test_bytes_not_speech'})
def confirm(row):
    v.review(library,book_id='fixture',asset_id=row['asset_id'],version=row['version'],audio_sha256=row['audio']['sha256'],decision='reviewed',reviewer='synthetic_fixture_only',checks={k:True for k in v.REVIEW_CHECKS},evidence={'audio_sha256':row['audio']['sha256'],'listening_performed':True,'observations':['Simulated review for deterministic test bytes, no real speaker quality claim.']})
    return v.make_binding(library,book_id='fixture',character_id=row['character_id'],asset_id=row['asset_id'],version=row['version'])
"""
            result, _ = harness.run(['-c', setup + '\n' + program])
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_candidate_voice_is_not_ready_without_a_bound_review(self):
        result = self.voice_program("row=candidate('child'); fixed={'schema':v.BINDING_SCHEMA,'book_id':'fixture','character_id':'child','voice_asset_id':row['asset_id'],'version':1,'audio_sha256':row['audio']['sha256']}; print(json.dumps(v.resolve_speakers(library,book_id='fixture',speaker_ids=['child'],bindings={'child':fixed})))")
        self.assertEqual(result['status'], 'missing_notice')
        self.assertFalse(result['voices'])
        self.assertFalse(result['fallback_used'])

    def test_reviewed_three_voice_slots_are_real_files_and_four_never_truncate(self):
        result = self.voice_program("fixed={cid:confirm(candidate(cid)) for cid in ['a','b','c','d']}; three=v.resolve_speakers(library,book_id='fixture',speaker_ids=['a','b','c'],bindings=fixed); four=v.resolve_speakers(library,book_id='fixture',speaker_ids=['a','b','c','d'],bindings=fixed); print(json.dumps({'three':three,'four':four}))")
        self.assertEqual(result['three']['status'], 'ready')
        self.assertEqual([v['slot'] for v in result['three']['voices']], [0, 1, 2])
        self.assertTrue(all(v['audio_metadata']['waveform_decode_verified'] for v in result['three']['voices']))
        self.assertFalse(result['three']['voice_identity_locked'])
        self.assertEqual(result['four']['status'], 'missing_notice')
        self.assertFalse(result['four']['voices'])
        self.assertTrue(any(n['code'] == 'voice_reference_capacity_exceeded' for n in result['four']['notices']))


class OfflineCLIEntryBlackBoxes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PARENT.mkdir(parents=True, exist_ok=True)
        cls.cli = PROJECT / 'scripts/prepare_h3_asset_flow_v2.py'

    def test_cli_help_exposes_only_prepare_and_validate(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            result, _ = OfflineCLIHarness(directory).run([self.cli, '--help'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('{prepare,validate}', result.stdout)
            self.assertNotIn('{prepare,validate,', result.stdout)

    def test_cli_rejects_every_production_command(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness = OfflineCLIHarness(directory)
            for action in ('submit', 'video', 'collect', 'execute', 'watch'):
                with self.subTest(action=action):
                    result, _ = harness.run([self.cli, action])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('invalid choice', result.stderr)
            self.assertFalse(any(p.name in {'READY.json', 'CLAIM.json', 'DRAFT_WORKFLOW.json'} for p in Path(directory).rglob('*')))

    def test_invalid_spec_is_notice_only_and_validate_does_not_rewrite(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            root = Path(directory); harness = OfflineCLIHarness(root)
            spec = root / 'invalid.json'; spec.write_text('{}', encoding='utf-8'); out = root / 'out'
            result, _ = harness.run([self.cli, 'prepare', '--spec', spec, '--out', out])
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['status'], 'needs_material_or_state')
            self.assertFalse(value['production_dispatch_allowed'])
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['CHECK_RESULT.json'])
            before = (out / 'CHECK_RESULT.json').read_bytes()
            verified, _ = harness.run([self.cli, 'validate', '--out', out])
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(json.loads(verified.stdout)['status'], 'notice_verified')
            self.assertEqual((out / 'CHECK_RESULT.json').read_bytes(), before)
            self.assertFalse(any(p.name.startswith(('READY', 'CLAIM')) for p in out.rglob('*')))


class OfficialAudioCPUProtocolBlackBoxes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PARENT.mkdir(parents=True, exist_ok=True)

    def protocol(self, mutate=''):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness = OfflineCLIHarness(directory)
            code = """
import hashlib,importlib.util,json,os,wave
from pathlib import Path
root=Path(os.environ['H3_OFFLINE_TEST_ROOT']); project=Path.cwd()
spec=importlib.util.spec_from_file_location('independent_offline_tests',project/'tests/test_h3_asset_flow_offline_blackbox_v2.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
old=project/'data/video_generation/h3_oral_revision_next_minute_20261113_v1'
nr=old/'visual_h3_v3'/(old.name+'_S04');plan=json.loads((nr/'PLAN.json').read_text(encoding='utf-8'))
graph=json.loads((nr/'shots/S04/workflow_api.json').read_text(encoding='utf-8')); voices=[]
for i,cid in enumerate(['ye_nan','ye_yaner','ye_dong']):
    path=root/('voice_'+str(i)+'.wav')
    with wave.open(str(path),'wb') as h:
        h.setnchannels(1);h.setsampwidth(2);h.setframerate(16000);h.writeframes(bytes([i+1,0])*3200)
    voice={'slot':i,'speaker_id':cid,'audio':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},'input_name':'offline_fixture/A'+str(i+1)+'.wav'}
    voices.append(voice);graph['voice_'+str(i)]={'class_type':'LoadAudio','inputs':{'audio':voice['input_name']}}
    graph['condition']['inputs']['ref_audios.ref_audio_'+str(i)]=['voice_'+str(i),0]
graph['condition']['inputs']['audio_vae']=['120',0]
manifest={'references':plan['shots'][0]['reference_map'],'voice_resolution':{'voices':voices}}
"""
            code += '\n' + mutate + "\ntry:\n    value=module.official_cpu_consumption(graph,manifest)\nexcept Exception as exc:\n    value={'rejected':str(exc)}\nprint(json.dumps(value))"
            result, _ = harness.run(['-c', code])
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_installed_official_methods_encode_waveforms_into_model_latents(self):
        value = self.protocol()
        self.assertNotIn('rejected', value, value)
        self.assertEqual(value['model_positive_images'], 9)
        self.assertEqual(value['model_positive_audio_latents'], 3)
        self.assertEqual(value['model_positive_keyframes'], 1)
        self.assertEqual(len(value['image_VAE_calls']), 10)
        self.assertEqual([v['tag'] for v in value['audio_VAE_calls']], ['A1', 'A2', 'A3'])
        self.assertEqual([v['shape'] for v in value['audio_VAE_calls']], [[1, 6400, 1]] * 3)
        self.assertEqual(len({v['source_sha256'] for v in value['audio_VAE_calls']}), 3)
        self.assertFalse(value['model_inference'])
        self.assertFalse(value['generated_quality_passed'])
        (PARENT / 'OFFICIAL_CPU_PROTOCOL_PROOF.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_audio_tokens_without_audio_VAE_cannot_claim_latent_consumption(self):
        value = self.protocol("graph['condition']['inputs'].pop('audio_vae')")
        self.assertEqual(value.get('rejected'), 'official_reference_audio_not_encoded_into_model_payload')

    def test_swapped_actual_LoadAudio_or_dropped_picture_is_rejected(self):
        value = self.protocol("graph['voice_0']['inputs']['audio']=graph['voice_1']['inputs']['audio']")
        self.assertEqual(value.get('rejected'), 'actual_audio_LoadAudio_slot_changed')
        value = self.protocol("graph['condition']['inputs'].pop('ref_images.ref_image_8')")
        self.assertEqual(value.get('rejected'), 'all_nine_actual_image_ports_required')


class IntegratedCLIAssetBlackBoxes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PARENT.mkdir(parents=True, exist_ok=True)
        cls.cli = PROJECT / 'scripts/prepare_h3_asset_flow_v2.py'

    def fixture(self, root, *, reviewed=True, mode='voice_required', mutation=''):
        harness = OfflineCLIHarness(root)
        code = "import json,os,sys; from pathlib import Path; sys.path.insert(0,str(Path.cwd()/'tests')); from h3_asset_flow_fixture_v2 import build_fixture; from src.content_factory import h3_asset_flow_v2 as flow; root=Path(os.environ['H3_OFFLINE_TEST_ROOT']); spec_path,out=build_fixture(root/'fixture',mode=%r,reviewed=%r); spec=flow.read(spec_path)\n" % (mode, reviewed)
        code += mutation + "\nspec_path.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8');print(json.dumps({'spec':str(spec_path),'out':str(out)}))"
        result, _ = harness.run(['-c', code])
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = json.loads(result.stdout)
        return harness, Path(paths['spec']), Path(paths['out'])

    def prepare(self, harness, spec, out):
        result, _ = harness.run([self.cli, 'prepare', '--spec', spec, '--out', out])
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_notice(self, out, value, code):
        self.assertEqual(value['status'], 'needs_material_or_state')
        self.assertFalse(value['production_dispatch_allowed'])
        self.assertFalse((out / 'DRAFT_WORKFLOW.json').exists())
        self.assertFalse((out / 'INPUT_MANIFEST.json').exists())
        self.assertIn(code, (out / 'CHECK_RESULT.json').read_text(encoding='utf-8'))

    def test_real_CLI_compiles_only_three_offline_artifacts_and_readonly_validates(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory)
            value = self.prepare(harness, spec, out)
            self.assertEqual(value['status'], 'offline_draft_valid')
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['CHECK_RESULT.json', 'DRAFT_WORKFLOW.json', 'INPUT_MANIFEST.json'])
            manifest = json.loads((out / 'INPUT_MANIFEST.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['references']), 9)
            self.assertEqual(len(manifest['voice_resolution']['voices']), 3)
            self.assertEqual(manifest['angle_selection']['side_priority'][0], 'ye_dong')
            self.assertEqual(manifest['angle_selection']['actor_views']['ye_dong'], ['front', 'left_oblique'])
            self.assertTrue(all(v[0] == 'front' for v in manifest['angle_selection']['actor_views'].values()))
            self.assertFalse(manifest['physical_staging_performed'])
            self.assertFalse(manifest['production_ready'])
            self.assertFalse(manifest['production_dispatch_allowed'])
            self.assertFalse(manifest['content_quality_passed'])
            self.assertFalse(manifest['voice_identity_locked'])
            self.assertEqual(manifest['routes']['image_references'], 9)
            self.assertEqual(manifest['routes']['audio_references'], 3)
            self.assertTrue(manifest['routes']['audio_vae_input_connected'])
            self.assertFalse(manifest['routes']['GPU_inference_performed'])
            before = {p.name: p.read_bytes() for p in out.iterdir()}
            validated, _ = harness.run([self.cli, 'validate', '--out', out])
            self.assertEqual(validated.returncode, 0, validated.stderr)
            self.assertEqual(json.loads(validated.stdout)['status'], 'offline_draft_verified')
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)
            self.assertEqual(self.prepare(harness, spec, out), value)
            self.assertFalse(any(p.name.startswith(('READY', 'CLAIM')) for p in Path(directory).rglob('*')))
            # Source images/voices are bound, but no future Comfy input names
            # have been physically staged by prepare-only code.
            self.assertFalse((Path(directory) / 'offline_h3_asset_v2').exists())

    def test_real_new_draft_consumes_three_decoded_waveforms_via_official_AST(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory)
            self.prepare(harness, spec, out)
            code = "import importlib.util,json;from pathlib import Path; s=importlib.util.spec_from_file_location('independent_offline_tests',Path.cwd()/'tests/test_h3_asset_flow_offline_blackbox_v2.py'); m=importlib.util.module_from_spec(s);s.loader.exec_module(m);out=Path(%r);print(json.dumps(m.official_cpu_consumption(json.loads((out/'DRAFT_WORKFLOW.json').read_text(encoding='utf-8')),json.loads((out/'INPUT_MANIFEST.json').read_text(encoding='utf-8')))))" % str(out)
            result, _ = harness.run(['-c', code])
            self.assertEqual(result.returncode, 0, result.stderr)
            proof = json.loads(result.stdout)
            self.assertEqual(proof['model_positive_audio_latents'], 3)
            self.assertEqual(proof['model_positive_images'], 9)
            self.assertEqual(proof['model_positive_keyframes'], 1)
            self.assertEqual([a['shape'] for a in proof['audio_VAE_calls']], [[1, 32000, 1]] * 3)
            self.assertFalse(proof['model_inference'])
            self.assertFalse(proof['generated_quality_passed'])
            (PARENT / 'INTEGRATED_DRAFT_OFFICIAL_CPU_PROOF.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_unreviewed_or_missing_state_inputs_leave_a_notice_without_a_draft(self):
        for kwargs, code in [({'reviewed': False}, 'voice_asset_missing_or_capacity'),
                             ({'mutation': "spec.pop('state_plan')"}, 'state_plan')]:
            with self.subTest(code=code), tempfile.TemporaryDirectory(dir=PARENT) as directory:
                harness, spec, out = self.fixture(directory, **kwargs)
                self.assert_notice(out, self.prepare(harness, spec, out), code)

    def test_missing_voice_mode_defaults_to_required_and_prompt_only_is_explicit(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory, reviewed=False, mutation="spec['voice'].pop('mode')")
            self.assert_notice(out, self.prepare(harness, spec, out), 'voice_asset_missing_or_capacity')
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory, reviewed=False, mode='prompt_only')
            self.assertEqual(self.prepare(harness, spec, out)['status'], 'offline_draft_valid')
            manifest = json.loads((out / 'INPUT_MANIFEST.json').read_text(encoding='utf-8'))
            graph = json.loads((out / 'DRAFT_WORKFLOW.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['voice_resolution']['control_mode'], 'prompt_only')
            self.assertEqual(manifest['voice_resolution']['voices'], [])
            self.assertEqual(manifest['routes']['audio_references'], 0)
            self.assertFalse(manifest['routes']['audio_vae_input_connected'])
            self.assertNotIn('audio_vae', graph['condition']['inputs'])
            self.assertFalse(any(k.startswith('ref_audios.') for k in graph['condition']['inputs']))
            self.assertFalse(manifest['voice_identity_locked'])

    def test_known_extra_actor_or_wrong_initial_basis_cannot_compile_a_draft(self):
        changes = [
            ("spec['guide']['review'].update(unexpected_actor_ids=['blue_copy'],observed_actor_count=5)", 'known_extra_actor'),
            ("state=flow._bound(spec['state_plan']);state['initial_basis']['guide_review_sha256']='0'*64;spec['state_plan']=flow.freeze(root/'wrong_basis.json',state)", 'state_initial_guide_binding')]
        for mutation, code in changes:
            with self.subTest(code=code), tempfile.TemporaryDirectory(dir=PARENT) as directory:
                harness, spec, out = self.fixture(directory, mutation=mutation)
                self.assert_notice(out, self.prepare(harness, spec, out), code)

    def test_structured_unknown_is_carried_and_legacy_portrait_pose_is_not_rendered(self):
        mutation = """
raw=flow._bound(spec['source_case']);entry=raw['shots'][0]
text=flow.core.check(entry['source']).read_text(encoding='utf-8');sentinel='LEGACY_STANDING_RESELECT_PROHIBITED'
start=len(text)+1;text=text+'\\n'+sentinel;path=root/'pose_context_fixture.txt';path.write_text(text,encoding='utf-8')
entry['source']=flow.bind(path);entry['source_scope']['end']=len(text)
entry['source_spans'].append({'id':'fixture_pose_context','kind':'context','start':start,'end':len(text),'text':sentinel,'sha256':flow.core.sha(sentinel)})
entry['source_state_span_ids'].append('fixture_pose_context')
for beat in entry['camera_beats']:
    if 'ye_dong' in beat['actors']:beat['actors']['ye_dong']['pose']=sentinel
spec['source_case']=flow.freeze(root/'source_pose_fixture.json',raw)
"""
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory, mutation=mutation)
            value = self.prepare(harness, spec, out)
            self.assertEqual(value['status'], 'offline_draft_valid')
            manifest = json.loads((out / 'INPUT_MANIFEST.json').read_text(encoding='utf-8'))
            self.assertNotIn('LEGACY_STANDING_RESELECT_PROHIBITED', manifest['compiled_prompt'])
            rows = manifest['actor_state']['state_plan_result']['beats']
            self.assertTrue(all(row['after']['ye_dong']['posture'] == 'unknown' for row in rows))
            self.assertEqual(rows[-1]['visible_instance_map']['ye_dong'], 'ye_dong:primary')

    def test_four_actual_source_speakers_receive_capacity_notice_without_truncation(self):
        mutation = """
raw=flow._bound(spec['source_case']);entry=raw['shots'][0];text=flow.core.check(entry['source']).read_text(encoding='utf-8')
quoted='“嗯。”';start=len(text)+1;text=text+'\\n'+quoted;path=root/'four_speaker_source.txt';path.write_text(text,encoding='utf-8')
entry['source']=flow.bind(path);entry['source_scope']['end']=len(text)
entry['source_spans'].append({'id':'fixture_fourth_audio','kind':'audio','start':start,'end':len(text),'text':quoted,'sha256':flow.core.sha(quoted)})
entry['audio'].append({'quote_index':3,'quote_sha256':flow.core.sha(quoted),'speaker':'ye_xijue','mode':'onscreen','start':14.3,'end':14.7})
spec['source_case']=flow.freeze(root/'four_speaker_source.json',raw)
"""
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory, mutation=mutation)
            value = self.prepare(harness, spec, out)
            self.assert_notice(out, value, 'voice_reference_capacity_exceeded')

    def test_native_guide_missing_original_or_swapped_history_locator_is_rejected(self):
        clone = """
import shutil
original=Path(spec['guide']['native_result']['path']);part=root/'native_fixture/shots/S03';part.mkdir(parents=True)
native=part.parents[1];shutil.copyfile(original.parent.parents[1]/'PLAN.json',native/'PLAN.json')
for name in ['REQUEST.json','HISTORY.json','STATE.json','workflow_api.json']:shutil.copyfile(original.parent/name,part/name)
result=flow.read(original);(part/'artifacts').mkdir()
for role,item in result['files'].items():
    target=part/'artifacts'/Path(item['path']).name;shutil.copyfile(item['path'],target);item['path']=str(target)
MODE_PLACEHOLDER
(part/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
spec['guide']['native_result']=flow.bind(part/'RESULT.json');spec['guide']['image']={k:result['files']['last'][k] for k in ['path','sha256']}
spec['guide']['review']['guide_image']=spec['guide']['image'];spec['guide']['review']['predecessor_result']=spec['guide']['native_result']
state=flow._bound(spec['state_plan']);state['initial_basis']={'guide_image':spec['guide']['image'],'native_result':spec['guide']['native_result'],'guide_review_sha256':flow.digest(spec['guide']['review'])}
spec['state_plan']=flow.freeze(root/'cloned_native_state.json',state)
"""
        for change, code in [("result['files'].pop('audio')", 'four_complete_originals'),
                             ("h=flow.read(part/'HISTORY.json');h[result['prompt_id']]['outputs']['save_last']['images'][0]['filename']='different_last.png';(part/'HISTORY.json').write_text(json.dumps(h),encoding='utf-8')", 'guide_original_output_history_locator_changed')]:
            with self.subTest(code=code), tempfile.TemporaryDirectory(dir=PARENT) as directory:
                harness, spec, out = self.fixture(directory, mutation=clone.replace('MODE_PLACEHOLDER', change))
                self.assert_notice(out, self.prepare(harness, spec, out), code)

    def test_immutable_draft_tamper_and_later_voice_revocation_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory); self.prepare(harness, spec, out)
            path = out / 'DRAFT_WORKFLOW.json'; graph = json.loads(path.read_text(encoding='utf-8'))
            graph['condition']['inputs'].pop('audio_vae'); path.write_text(json.dumps(graph), encoding='utf-8')
            result, _ = harness.run([self.cli, 'validate', '--out', out])
            self.assertNotEqual(result.returncode, 0)
        with tempfile.TemporaryDirectory(dir=PARENT) as directory:
            harness, spec, out = self.fixture(directory); self.prepare(harness, spec, out)
            code = "from pathlib import Path;import json;from src.content_factory import voice_asset_registry_v1 as v;s=json.loads(Path(%r).read_text(encoding='utf-8'));b=next(iter(s['voice']['bindings'].values()));v.review(s['voice']['library'],book_id=b['book_id'],asset_id=b['voice_asset_id'],version=b['version'],audio_sha256=b['audio_sha256'],decision='rejected',reviewer='offline_fixture_revocation',checks={},evidence={'audio_sha256':b['audio_sha256'],'listening_performed':False,'observations':['Offline revocation test only.']})" % str(spec)
            changed, _ = harness.run(['-c', code]); self.assertEqual(changed.returncode, 0, changed.stderr)
            result, _ = harness.run([self.cli, 'validate', '--out', out]); self.assertNotEqual(result.returncode, 0)

    def test_bound_base_workflow_cannot_swap_video_and_audio_VAE_roles(self):
        for node, wrong in [('119', 'minimax_h3_audio_vae_fp32.safetensors'),
                            ('120', 'minimax_h3_video_vae_int8_convrot.safetensors')]:
            mutation = "template=flow._bound(spec['base_workflow']);template[%r]['inputs']['vae_name']=%r;spec['base_workflow']=flow.freeze(root/'wrong_vae_template.json',template)" % (node, wrong)
            with self.subTest(node=node), tempfile.TemporaryDirectory(dir=PARENT) as directory:
                harness, spec, out = self.fixture(directory, mutation=mutation)
                value = self.prepare(harness, spec, out)
                self.assertEqual(value['status'], 'needs_material_or_state')
                self.assertFalse((out / 'DRAFT_WORKFLOW.json').exists())
                self.assertIn('vae', (out / 'CHECK_RESULT.json').read_text(encoding='utf-8').lower())


if __name__ == '__main__': unittest.main()
