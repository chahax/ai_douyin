"""Four original Seedance text values, local H3 first-frame-only comparison.

No rewriting, image synthesis, service restart or semantic retry lives here.
Preparation and inspection are CPU-only. Only execute may submit media.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from PIL import Image

from . import visual_h3_handoff_v3 as h3
from . import visual_image_jobs_v3 as jobs

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'data/video_generation/h3_seedance_prompt_parity_60s_20261107_v1'
SOURCE = ROOT / 'data/video_generation/six_children_seedance_60s_20261102_trusted'
WORKING = ROOT / 'data/video_generation/visual_h3_v3/novel5min_F0010_v15_736_20261107_v1/shots/F0010'
PAUSE = ROOT / 'data/video_generation/h3_six_children_full_script_recovery_20261104/PAUSE.json'
PAUSE_SHA = '9d5d0c747ef006a715dafe3ed527b7d4f94414ff7479b2c4155442cfebff377e'
OPENING_SHA = '7fd7a5ab3af9f3ce164077fec92fc89159c68d5b0001f8d85f343ceca00a88e7'
MODEL_ROOT = Path('D:/IT/AI_vido/ComfyUI/models')
IDS = ('S01', 'S02', 'S03', 'S04')
PROMPT_LENGTHS = (655, 644, 679, 660)
PROMPT_SHAS = ('234930746fdf29cd4b9a8340b1cfd115d656b4803b3ccb9ca636f1f8ce65a0a9',
               '70107e361da22a3bae4a570b8f08a6a26781e5f6c75f412eafd9905b3c1673ec',
               'cf152660cd1f81e32f8ba312c0670cd7bb15adbb353898477f4b463d348c4d6c',
               '5ac32d4dfb0118a9b9236d4a65c8c1fe40b26ac5e3d9ca3479c5b75c89ae2885')
AUTHORIZATION_SHA = '8c12aa67a1f8d6b16f2996993b7cca81f75664a15e1db70bbfe30115455e5944'
SCHEMA = 'h3_original_prompt_parity/v19'
WIDTH, HEIGHT, FRAMES, FPS, RATE = 736, 1312, 362, 24, 48000
SAMPLES = FRAMES * 2000
ROLES = ('video', 'audio', 'first', 'last')


class ParityError(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return h3.file_sha(path)


def text_sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def binding(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha(path))


def _check(item):
    if sha(item['path']) != item['sha256']:
        raise ParityError('bound_file_changed:' + str(item['path']))


def _freeze(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    jobs._freeze(Path(path), value)


def _write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    jobs._write(Path(path), value)


def _copy(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    original = sha(source)
    if target.exists():
        if sha(target) != original:
            raise ParityError('existing_copy_changed')
    else:
        jobs._copy_new(source, target)
    if sha(target) != original or sha(source) != original:
        raise ParityError('copy_source_changed')
    return binding(target)


def _scope(run):
    run = Path(run).resolve()
    if run != RUN.resolve():
        raise ParityError('only_independent_parity_namespace_allowed')
    return run


def _original_prompts():
    rows = []
    for name, length, expected_sha in zip(IDS, PROMPT_LENGTHS, PROMPT_SHAS):
        request = SOURCE / 'segments' / name / 'REQUEST.actual.json'
        prompt_file = request.with_name('PROMPT.txt')
        texts = [x.get('text') for x in read(request).get('content', []) if x.get('type') == 'text']
        if len(texts) != 1 or not isinstance(texts[0], str) or len(texts[0]) != length:
            raise ParityError('unique_original_text_value_required:' + name)
        # read_text normalizes CRLF; this comparison is not the file-byte SHA.
        value = texts[0]
        if text_sha(value) != expected_sha:
            raise ParityError('authorized_original_text_value_changed:' + name)
        if prompt_file.read_text(encoding='utf-8') != value:
            raise ParityError('source_prompt_file_and_request_disagree:' + name)
        rows.append(dict(id=name, text=value, utf8_sha256=text_sha(value),
                         request=binding(request), source_prompt_file=binding(prompt_file)))
    return rows


def _model_records(graph):
    pairs = [('diffusion_models', graph['127']['inputs']['unet_name']),
             ('text_encoders', graph['128']['inputs']['clip_name']),
             *[('vae', graph[n]['inputs']['vae_name']) for n in ('119', '120')]]
    out = []
    for kind, name in pairs:
        path = (MODEL_ROOT / kind / jobs._relative(name)).resolve()
        if not path.is_relative_to(MODEL_ROOT.resolve()) or not path.is_file():
            raise ParityError('required_local_model_missing')
        stat = path.stat()
        out.append(dict(path=str(path), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return out


def _working_graph():
    graph = read(WORKING / 'workflow_api.json')
    result = read(WORKING / 'RESULT.json')
    history = read(WORKING / 'HISTORY.json')
    pid = result['prompt_id']
    entry = history[pid]
    if (result.get('technical_status') != 'technical_saved'
            or entry['prompt'][1] != pid
            or entry['status'].get('completed') is not True
            or entry['status'].get('status_str') != 'success'
            or h3.native_graph_equivalence(graph, entry['prompt'][2]) is None
            or result['graph_sha256'] != h3.fingerprint(graph)):
        raise ParityError('known_working_h3_graph_native_proof_required')
    h3._validate_graph(graph, graph['save_video']['inputs']['filename_prefix'].rsplit('/', 1)[0],
                       graph['ref_scene']['inputs']['image'])
    if (graph['124']['inputs']['steps'], graph['condition']['inputs']['length'],
            graph['condition']['inputs']['width'], graph['condition']['inputs']['height']) != (12, FRAMES, WIDTH, HEIGHT):
        raise ParityError('working_graph_profile_changed')
    return graph


def prepare(run=RUN):
    """Freeze source values and the known-working profile; no HTTP or GPU work."""
    run = _scope(run)
    if (run / 'PLAN.json').exists():
        return _load(run, current=True)
    if sha(run / 'USER_AUTHORIZATION.json') != AUTHORIZATION_SHA:
        raise ParityError('four_local_posts_authorization_binding_required')
    prompts = _original_prompts()
    opening = SOURCE / 'assets/opening.original.jpeg'
    if sha(opening) != OPENING_SHA or sha(PAUSE) != PAUSE_SHA:
        raise ParityError('opening_or_protected_legacy_pause_changed')
    graph = _working_graph()
    source_plan = read(WORKING.parent.parent / 'PLAN.json')
    config = {k: source_plan['config'][k] for k in
              ('service_url', 'input_root', 'output_root', 'gpu_lock_root', 'timeout')}
    if config['service_url'] != 'http://127.0.0.1:8190':
        raise ParityError('original_loopback_h3_service_required')
    for key in ('input_root', 'output_root', 'gpu_lock_root'):
        config[key] = str(Path(config[key]).resolve())
        if not Path(config[key]).is_dir():
            raise ParityError('working_service_directory_missing:' + key)
    config['protected_pause_path'] = str(PAUSE.resolve())
    models = _model_records(graph)
    run.mkdir(parents=True, exist_ok=True)
    with jobs.run_lock(run):
        if (run / 'PLAN.json').exists():
            return _load(run, current=True)
        _freeze(run / 'BASE_WORKFLOW.json', graph)
        _copy(opening, run / 'sources/opening.original.jpeg')
        for row in prompts:
            path = run / 'sources' / (row['id'] + '.prompt.txt')
            encoded = row['text'].encode('utf-8')
            if path.exists():
                if path.read_bytes() != encoded:
                    raise ParityError('frozen_prompt_value_changed')
            else:
                with path.open('xb') as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
            row['frozen_prompt'] = binding(path)
        plan = dict(schema=SCHEMA, source_root=str(SOURCE.resolve()), config=config,
                    authorization=binding(run / 'USER_AUTHORIZATION.json'),
                    source_working_graph=binding(WORKING / 'workflow_api.json'),
                    source_working_result=binding(WORKING / 'RESULT.json'),
                    source_working_history=binding(WORKING / 'HISTORY.json'),
                    base_workflow=binding(run / 'BASE_WORKFLOW.json'),
                    opening=binding(opening), frozen_opening=binding(run / 'sources/opening.original.jpeg'),
                    protected_pause=dict(path=str(PAUSE.resolve()), sha256=PAUSE_SHA), models=models,
                    segments=prompts, width=WIDTH, height=HEIGHT, fps=FPS, frames_per_segment=FRAMES,
                    steps=12, max_submissions=4, keyframe_policy='first_only',
                    prompt_contract='exact_original_json_text_utf8/v1', semantic_retry=False,
                    production_approved=False, publication=False, old_batch_resume=False)
        _freeze(run / 'PLAN.json', plan)
        _freeze(run / 'PREPARATION.json', dict(plan=binding(run / 'PLAN.json'),
                    media_dispatched=False, source_code=binding(__file__)))
        _prepare_segment(run, plan, 0)
    return plan


def _load(run, *, current=False):
    run = _scope(run)
    prep = read(run / 'PREPARATION.json')
    _check(prep['plan'])
    if Path(prep['plan']['path']).resolve() != run / 'PLAN.json':
        raise ParityError('plan_path_changed')
    plan = read(run / 'PLAN.json')
    if (plan.get('schema'), tuple(x['id'] for x in plan.get('segments', [])),
            plan.get('keyframe_policy'), plan.get('max_submissions')) != (SCHEMA, IDS, 'first_only', 4):
        raise ParityError('frozen_parity_contract_changed')
    for name in ('base_workflow', 'frozen_opening'):
        _check(plan[name])
    for row in plan['segments']:
        _check(row['frozen_prompt'])
        if (text_sha(row['text']) != row['utf8_sha256']
                or Path(row['frozen_prompt']['path']).read_bytes() != row['text'].encode('utf-8')):
            raise ParityError('original_prompt_value_changed')
    if current:
        for name in ('source_working_graph', 'source_working_result', 'source_working_history', 'opening', 'protected_pause', 'authorization'):
            _check(plan[name])
        if plan['protected_pause'] != dict(path=str(PAUSE.resolve()), sha256=PAUSE_SHA):
            raise ParityError('legacy_pause_contract_changed')
        for row in plan['segments']:
            _check(row['request']); _check(row['source_prompt_file'])
        for row in plan['models']:
            stat = Path(row['path']).stat()
            if (stat.st_size, stat.st_mtime_ns) != (row['bytes'], row['mtime_ns']):
                raise ParityError('frozen_model_file_changed')
    return plan


def build_graph(base, prompt, input_name, scope, index):
    """Only these whitelisted numeric/path fields and the exact text may differ."""
    graph = deepcopy(base)
    condition = graph['condition']['inputs']
    condition.pop('last_frame', None)
    condition.pop('ref_images', None)
    condition.update(prompt=prompt, width=WIDTH, height=HEIGHT, length=FRAMES,
                     first_frame=['ref_scene', 0])
    graph['ref_scene']['inputs'] = dict(image=input_name)
    graph['129']['inputs']['noise_seed'] = 2026110700 + index
    graph['pick_first']['inputs']['batch_index'] = 0
    graph['pick_last']['inputs']['batch_index'] = FRAMES - 1
    for role in ROLES:
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    h3._validate_graph(graph, scope, input_name)
    if graph['124']['inputs']['steps'] != 12 or graph['130']['inputs']['fps'] != FPS:
        raise ParityError('frozen_sampler_profile_changed')
    if text_sha(graph['condition']['inputs']['prompt']) != text_sha(prompt):
        raise ParityError('original_prompt_not_passed_verbatim')
    return graph


def _result(run, plan, index):
    folder = run / 'segments' / IDS[index]
    segment = _segment(run, plan, index)
    result = read(folder / 'RESULT.json')
    response = read(folder / 'RESPONSE.json')
    if (result.get('schema') != SCHEMA or result.get('id') != IDS[index]
            or result.get('prompt_id') != response.get('prompt_id')
            or result.get('segment_sha256') != sha(folder / 'SEGMENT.json')
            or result.get('technical_status') != 'technical_saved'
            or result.get('production_approved') is not False or result.get('publication') is not False
            or set(result.get('files', {})) != set(ROLES)):
        raise ParityError('saved_result_binding_changed')
    for role, row in result['files'].items():
        path = Path(row['path']).resolve()
        source = Path(row['source_path']).resolve()
        if (path.parent != folder / 'artifacts'
                or source.parent != Path(plan['config']['output_root']) / segment['scope']):
            raise ParityError('saved_artifact_scope_changed')
        _check(row)
        if sha(source) != row['sha256']:
            raise ParityError('saved_native_source_changed')
    entry = read(folder / 'HISTORY.json')[result['prompt_id']]
    _history_identity(folder, segment, entry, result['prompt_id'])
    if entry['status'].get('completed') is not True or entry['status'].get('status_str') != 'success':
        raise ParityError('saved_native_terminal_changed')
    return result


def _prepare_segment(run, plan, index):
    folder = run / 'segments' / IDS[index]
    if (folder / 'SEGMENT.json').exists():
        return _segment(run, plan, index)
    if index:
        previous = _result(run, plan, index - 1)
        source = previous['files']['last']
        provenance = dict(previous_segment=IDS[index - 1], previous_prompt_id=previous['prompt_id'],
                          previous_result=binding(run / 'segments' / IDS[index - 1] / 'RESULT.json'),
                          native_last_frame_sha256=source['sha256'])
    else:
        source = plan['frozen_opening']
        provenance = dict(original_seedream_opening=plan['opening'])
    folder.mkdir(parents=True, exist_ok=True)
    first = _copy(source['path'], folder / ('first_input.jpeg' if index == 0 else 'first_input.png'))
    if first['sha256'] != source['sha256']:
        raise ParityError('first_frame_bytes_not_preserved')
    scope = run.name + '/' + IDS[index]
    input_name = scope + '/' + Path(first['path']).name
    prompt = plan['segments'][index]
    graph = build_graph(read(plan['base_workflow']['path']), prompt['text'], input_name, scope, index)
    _freeze(folder / 'workflow_api.json', graph)
    row = dict(id=IDS[index], scope=scope, input_name=input_name, first_frame=first,
               provenance=provenance, graph=binding(folder / 'workflow_api.json'),
               graph_sha256=h3.fingerprint(graph), original_prompt_utf8_sha256=prompt['utf8_sha256'],
               plan_sha256=sha(run / 'PLAN.json'))
    _freeze(folder / 'SEGMENT.json', row)
    return row


def _segment(run, plan, index):
    folder = run / 'segments' / IDS[index]
    row = read(folder / 'SEGMENT.json')
    if (Path(row['graph']['path']).resolve() != folder / 'workflow_api.json'
            or Path(row['first_frame']['path']).resolve() != folder / ('first_input.jpeg' if index == 0 else 'first_input.png')):
        raise ParityError('segment_local_input_or_graph_scope_changed')
    _check(row['first_frame']); _check(row['graph'])
    scope = run.name + '/' + IDS[index]
    if (row.get('id') != IDS[index] or row.get('scope') != scope
            or row.get('input_name') != scope + '/' + Path(row['first_frame']['path']).name
            or row.get('plan_sha256') != sha(run / 'PLAN.json')):
        raise ParityError('segment_binding_changed')
    graph = read(row['graph']['path'])
    expected = build_graph(read(plan['base_workflow']['path']), plan['segments'][index]['text'],
                           row['input_name'], scope, index)
    if (graph != expected or row['graph_sha256'] != h3.fingerprint(expected)
            or text_sha(graph['condition']['inputs']['prompt']) != row['original_prompt_utf8_sha256']):
        raise ParityError('graph_or_original_prompt_changed')
    if index:
        prev = run / 'segments' / IDS[index - 1] / 'RESULT.json'
        _check(row['provenance']['previous_result'])
        previous = read(prev)
        if (row['provenance']['previous_result']['path'] != str(prev)
                or row['provenance']['previous_prompt_id'] != previous['prompt_id']
                or row['first_frame']['sha256'] != previous['files']['last']['sha256']
                or row['provenance']['native_last_frame_sha256'] != previous['files']['last']['sha256']):
            raise ParityError('previous_h3_native_tail_chain_changed')
    elif row['first_frame']['sha256'] != plan['opening']['sha256']:
        raise ParityError('original_seedream_opening_changed')
    return row


def _state(run, plan, index):
    folder = run / 'segments' / IDS[index]
    if not (folder / 'SEGMENT.json').exists():
        return dict(id=IDS[index], status='waiting_previous_native_tail')
    segment = _segment(run, plan, index)
    state = read(folder / 'STATE.json') if (folder / 'STATE.json').exists() else dict(id=IDS[index], status='prepared')
    claim_path = folder / 'CLAIM.json'
    if claim_path.exists():
        claim = read(claim_path)
        if claim.get('segment_sha256') != sha(folder / 'SEGMENT.json'):
            raise ParityError('claim_segment_binding_changed')
        _check(claim['request'])
        request = read(folder / 'REQUEST.json')
        if request['prompt'] != read(segment['graph']['path']):
            raise ParityError('claimed_graph_changed')
        if not (folder / 'RESPONSE.json').exists():
            return dict(id=IDS[index], status='outcome_unknown', reason='claimed_post_without_response')
        response = read(folder / 'RESPONSE.json')
        pid = response.get('prompt_id')
        if response.get('node_errors') or not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pid):
            return dict(id=IDS[index], status='rejected' if response.get('node_errors') else 'outcome_unknown',
                        reason='native_response_rejected_or_missing_id')
        if state.get('prompt_id') not in (None, pid):
            raise ParityError('original_native_id_changed')
        state.update(prompt_id=pid)
        if state['status'] == 'prepared':
            state['status'] = 'submitted'
    elif (folder / 'RESPONSE.json').exists() or state.get('prompt_id'):
        raise ParityError('unclaimed_native_response_or_id')
    if (folder / 'RESULT.json').exists():
        _result(run, plan, index)
        state['status'] = 'technical_saved'
    return state


def status(run=RUN):
    """Read local evidence only. No HTTP, directory creation or business action."""
    run = _scope(run)
    plan = _load(run)
    states = [_state(run, plan, i) for i in range(4)]
    return dict(schema=SCHEMA, run=str(run), paused=(run / 'PAUSE.json').exists(), segments=states,
                technical_saved=sum(s['status'] == 'technical_saved' for s in states),
                total=4, production_approved=False, publication=False)


def _remember_id(run, name, pid):
    records = run / 'native_ids'
    records.mkdir(exist_ok=True)
    for path in records.glob('*.json'):
        item = read(path)
        if item['prompt_id'] == pid and item['id'] != name:
            raise ParityError('native_id_reused_across_segments')
    _freeze(records / (name + '.json'), dict(id=name, prompt_id=pid))
    ledger = run / 'NATIVE_IDS.jsonl'
    existing = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
    item = dict(id=name, prompt_id=pid)
    if any(x['id'] == name and x != item for x in existing):
        raise ParityError('append_ledger_native_id_changed')
    if item not in existing:
        with ledger.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(item) + '\n'); handle.flush(); os.fsync(handle.fileno())
    # Human-readable append ledger required by the media workflow. The JSON
    # ledger above remains authoritative; a crash between appends is repaired
    # from the durable original RESPONSE, never by submitting another job.
    text_ledger = run / 'job_ids.txt'
    lines = text_ledger.read_text(encoding='utf-8').splitlines() if text_ledger.exists() else []
    wanted = name + ' ' + pid
    for line in lines:
        fields = line.split(' ')
        if (len(fields) != 2 or fields[0] not in IDS or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', fields[1])
                or fields[0] == name and line != wanted):
            raise ParityError('text_native_id_ledger_changed')
    if wanted not in lines:
        with text_ledger.open('a', encoding='utf-8') as handle:
            handle.write(wanted + '\n'); handle.flush(); os.fsync(handle.fileno())


def _history_identity(folder, segment, entry, pid):
    prompt = entry.get('prompt')
    native = entry.get('status')
    if (not isinstance(prompt, list) or len(prompt) < 3 or prompt[1] != pid
            or not isinstance(native, dict) or type(native.get('completed')) is not bool
            or native.get('status_str') not in ('success', 'error')):
        raise ParityError('native_history_schema_or_id_changed')
    proof = h3.native_graph_equivalence(read(folder / 'workflow_api.json'), prompt[2])
    if proof is None or proof['source_graph_sha256'] != segment['graph_sha256']:
        raise ParityError('native_history_graph_changed')
    return proof


def _collect(run, plan, index, entry, state):
    folder = run / 'segments' / IDS[index]
    row = _segment(run, plan, index)
    files = {}
    for role, key, suffix in [('video', 'images', '.mp4'), ('audio', 'audio', '.flac'),
                               ('first', 'images', '.png'), ('last', 'images', '.png')]:
        values = entry.get('outputs', {}).get('save_' + role, {}).get(key)
        if not isinstance(values, list) or len(values) != 1 or values[0].get('type') != 'output':
            raise ParityError('four_native_save_nodes_required')
        record = values[0]
        filename = record.get('filename', '')
        if ('/' in filename or '\\' in filename or not filename.startswith(role + '_')
                or Path(filename).suffix.lower() != suffix):
            raise ParityError('native_output_filename_changed')
        source = jobs._bound(plan['config']['output_root'],
                            record.get('subfolder', '').replace('\\', '/') + '/' + filename)
        if source.parent != Path(plan['config']['output_root']) / row['scope'] or source.stat().st_size <= 0:
            raise ParityError('native_output_scope_changed')
        copy = _copy(source, folder / 'artifacts' / filename)
        files[role] = dict(**copy, source_path=str(source))
    metadata = h3._metadata(files['video']['path'])
    video = next((s for s in metadata['streams'] if s.get('codec_type') == 'video'), {})
    audio = next((s for s in metadata['streams'] if s.get('codec_type') == 'audio'), None)
    if (video.get('width'), video.get('height'), int(video.get('nb_frames', -1)),
            video.get('r_frame_rate')) != (WIDTH, HEIGHT, FRAMES, '24/1') or not audio:
        raise ParityError('native_av_format_changed')
    if not any(x.get('codec_type') == 'audio' for x in h3._metadata(files['audio']['path'])['streams']):
        raise ParityError('standalone_native_audio_missing')
    for role in ('first', 'last'):
        with Image.open(files[role]['path']) as image:
            if image.size != (WIDTH, HEIGHT):
                raise ParityError('native_endpoint_dimensions_changed')
            image.verify()
    result = dict(schema=SCHEMA, id=IDS[index], prompt_id=state['prompt_id'],
                  segment_sha256=sha(folder / 'SEGMENT.json'),
                  original_prompt_utf8_sha256=row['original_prompt_utf8_sha256'],
                  native_frames=FRAMES, fps=FPS, files=files, native_metadata=metadata,
                  technical_status='technical_saved', content_status='comparison_review_required',
                  production_approved=False, publication=False, semantic_retry=False)
    _freeze(folder / 'RESULT.json', result)
    state['status'] = 'technical_saved'
    _write(folder / 'STATE.json', state)
    return result


def tick(run=RUN):
    """At most one new POST; original IDs are always polled before any new work."""
    run = _scope(run)
    plan = _load(run)
    cfg = plan['config']
    with jobs.run_lock(run):
        for index, name in enumerate(IDS):
            folder = run / 'segments' / name
            state = _state(run, plan, index)
            if state['status'] == 'technical_saved':
                continue
            if state.get('prompt_id') and state['status'] not in ('failed', 'interrupted', 'rejected'):
                pid = state['prompt_id']
                _remember_id(run, name, pid)
                history = h3._http(cfg, '/history/' + pid)
                if not isinstance(history, dict):
                    raise ParityError('invalid_native_history_response')
                entry = history.get(pid)
                segment = _segment(run, plan, index)
                if entry:
                    proof = _history_identity(folder, segment, entry, pid)
                    _write(folder / 'HISTORY.latest.json', history)
                    _freeze(folder / ('native_graph_' + proof['native_graph_sha256'] + '.json'), proof)
                    if entry['status']['status_str'] == 'error':
                        state.update(status='failed', native_terminal=entry['status'])
                    elif entry['status']['completed']:
                        _freeze(folder / 'HISTORY.json', history)
                        _collect(run, plan, index, entry, state)
                        return status(run)
                    else:
                        state['status'] = 'running'
                else:
                    queue = h3._queue(cfg)
                    matches = [q for q in queue['queue_running'] + queue['queue_pending'] if q[1] == pid]
                    if any(h3.native_graph_equivalence(read(folder / 'workflow_api.json'), q[2]) is None for q in matches):
                        raise ParityError('original_queue_graph_changed')
                    state.update(status='running' if matches else 'outcome_unknown',
                                 reason=None if matches else 'original_id_absent_history_and_queue')
                    _write(folder / 'QUEUE.latest.json', queue)
                _write(folder / 'STATE.json', state)
                return status(run)
            if state['status'] in ('failed', 'interrupted', 'rejected', 'outcome_unknown'):
                return status(run)
            if (run / 'PAUSE.json').exists():
                return status(run)
            # A source change blocks new generation, never original-ID collection.
            _load(run, current=True)
            with h3._gpu(plan):
                _load(run, current=True)
                if (run / 'PAUSE.json').exists():
                    return status(run)
                h3._service_paths(cfg)
                queue = h3._queue(cfg)
                if queue['queue_running'] or queue['queue_pending']:
                    return dict(status(run), dispatch='waiting_gpu_queue')
                row = _prepare_segment(run, plan, index)
                staged = jobs._bound(cfg['input_root'], row['input_name'])
                _copy(row['first_frame']['path'], staged)
                if sha(staged) != row['first_frame']['sha256']:
                    raise ParityError('staged_first_frame_changed')
                request_path = folder / 'REQUEST.json'
                request = read(request_path) if request_path.exists() else dict(
                    prompt=read(folder / 'workflow_api.json'), client_id=uuid.uuid4().hex)
                _freeze(request_path, request)
                _freeze(folder / 'CLAIM.json', dict(at=time.time(), request=binding(request_path),
                            segment_sha256=sha(folder / 'SEGMENT.json'), native_post_budget=1))
                _write(folder / 'STATE.json', dict(id=name, status='outcome_unknown',
                            reason='post_claimed_before_dispatch'))
                try:
                    response = h3._http(cfg, '/prompt', request)
                except Exception as error:
                    _freeze(folder / 'POST_ERROR.json', dict(type=type(error).__name__, message=str(error)))
                    return status(run)
                _freeze(folder / 'RESPONSE.json', response)
                state = _state(run, plan, index)
                if state.get('prompt_id'):
                    _remember_id(run, name, state['prompt_id'])
                    state.update(status='submitted', reason=None, submitted_at=time.time())
                    _write(folder / 'STATE.json', state)
                return status(run)
    return status(run)


def execute(run=RUN, *, through=4, poll_seconds=30, max_seconds=86400):
    """Serial four-clip dispatch. Unknowns/terminal errors stop without replay."""
    if type(through) is not int or not 1 <= through <= 4:
        raise ParityError('through_must_be_1_to_4')
    if not 0 < poll_seconds <= 60 or not 0 < max_seconds <= 172800:
        raise ParityError('invalid_bounded_poll_settings')
    run = _scope(run)
    deadline = time.monotonic() + max_seconds
    with jobs.run_lock(run, 'RUNNER.lock'):
        while True:
            current = status(run)
            if current['technical_saved'] >= through:
                return current
            current = tick(run)
            active = current['segments'][min(current['technical_saved'], 3)]
            if current['paused'] or active['status'] in ('outcome_unknown', 'failed', 'interrupted', 'rejected'):
                return current
            if current['technical_saved'] >= through:
                return current
            if time.monotonic() >= deadline:
                return dict(current, execution='poll_window_ended_original_id_retained')
            time.sleep(poll_seconds)


def _duration(stream):
    try:
        return Fraction(int(stream['duration_ts'])) * Fraction(stream['time_base'])
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return Fraction(stream['duration'])


def _probe(path, count=False):
    command = ['ffprobe', '-v', 'error', '-threads', '1']
    if count:
        command += ['-count_frames']
    return json.loads(subprocess.check_output(command + ['-show_streams', '-show_format', '-of', 'json', str(path)],
                     text=True, encoding='utf-8', timeout=180))


def _inspect_clip(path, frames=FRAMES, expected_sha256=None):
    """CPU timing evidence. At most 0.25s source skew; no dropped dialogue."""
    if expected_sha256 is not None and sha(path) != expected_sha256:
        raise ParityError('assembly_source_changed')
    metadata = _probe(path, True)
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in metadata['streams'] if s['codec_type'] == 'audio')
    if (int(video.get('nb_frames', -1)), int(video.get('nb_read_frames', -1)),
            video.get('r_frame_rate'), video.get('avg_frame_rate')) != (frames, frames, '24/1', '24/1'):
        raise ParityError('decoded_native_frame_count_changed')
    target = Fraction(frames, FPS)
    if _duration(video) != target:
        raise ParityError('native_video_clock_changed')
    start = Fraction(audio['start_time'])
    delta = max(abs(_duration(audio) - target), abs(start + _duration(audio) - target), abs(start))
    if delta > Fraction(1, 4):
        raise ParityError('native_av_skew_exceeds_small_padding_tolerance')
    pcm = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-filter_threads', '1',
          '-i', str(path), '-map', '0:a:0', '-af', 'aresample=48000:async=0:first_pts=0',
          '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1'],
          stderr=subprocess.PIPE, timeout=180)
    if not pcm or len(pcm) % 4:
        raise ParityError('audio_decode_invalid')
    samples = len(pcm) // 4
    padding = Fraction(1024, int(audio['sample_rate'])) if audio.get('codec_name') == 'aac' else 0
    if abs(Fraction(samples, RATE) - target) > Fraction(1, 4) + padding + Fraction(1, RATE):
        raise ParityError('decoded_native_audio_skew')
    if expected_sha256 is not None and sha(path) != expected_sha256:
        raise ParityError('assembly_source_changed')
    return dict(source_metadata=metadata, source_sha256=expected_sha256, native_frames=frames,
                normalized_audio_rate=RATE, normalized_audio_channels=2,
                normalized_decoded_samples=samples, target_audio_samples=frames * 2000,
                trim_tail_samples=max(0, samples - frames * 2000), pad_tail_samples=max(0, frames * 2000 - samples))


def assembly_command(paths, filter_path, output, *, frames=FRAMES, preset='medium'):
    """Pure frame/sample clock construction; not a native-production gate."""
    if type(frames) is not int or frames <= 0 or not paths:
        raise ParityError('invalid_assembly_clock')
    cmd = ['ffmpeg', '-nostdin', '-v', 'warning', '-filter_complex_threads', '1']
    lines, joined = [], []
    for i, path in enumerate(paths):
        cmd += ['-threads', '1', '-i', str(path)]
        lines += [f'[{i}:v:0]trim=end_frame={frames},setpts=N/(24*TB),setsar=1[v{i}]',
                  f'[{i}:a:0]aresample=48000:async=0:first_pts=0,aformat=channel_layouts=stereo,'
                  f'apad=whole_len={frames*2000},atrim=end_sample={frames*2000},asetpts=N/SR/TB[a{i}]']
        joined += [f'[v{i}]', f'[a{i}]']
    lines += [''.join(joined) + f'concat=n={len(paths)}:v=1:a=1[vjoined][ajoined]',
              '[vjoined]settb=1/24,setpts=N[video]', '[ajoined]asettb=1/48000,asetpts=N[audio]']
    cmd += ['-filter_complex_script', str(filter_path), '-map', '[video]', '-map', '[audio]',
            '-fps_mode', 'passthrough', '-enc_time_base:v', '1:24', '-c:v', 'libx264', '-preset', preset,
            '-crf', '18', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
            '-ar', '48000', '-ac', '2', '-video_track_timescale', '12288', '-movie_timescale', '48000',
            '-movflags', '+faststart', str(output)]
    return cmd, ';\n'.join(lines) + '\n'


def verify_clock(metadata, *, frames=1448, width=WIDTH, height=HEIGHT):
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in metadata['streams'] if s['codec_type'] == 'audio')
    if (video['width'], video['height'], int(video.get('nb_frames', -1)), int(video.get('nb_read_frames', -1)),
            video['r_frame_rate'], video['avg_frame_rate']) != (width, height, frames, frames, '24/1', '24/1'):
        raise ParityError('final_native_frame_clock_or_resolution_changed')
    target = Fraction(frames, FPS)
    if any(Fraction(s.get('start_time', '-1')) != 0 for s in (video, audio)):
        raise ParityError('final_av_origin_not_zero')
    if (_duration(video) != target or int(audio['sample_rate']) != RATE or int(audio['channels']) != 2
            or abs(_duration(audio) - target) > Fraction(1, RATE)
            or abs(Fraction(metadata['format']['duration']) - target) > Fraction(1, 1000)):
        raise ParityError('final_av_duration_changed')
    return dict(native_frames=frames, fps=FPS, audio_rate=RATE, audio_samples=frames * 2000,
                seconds=float(target), audio_start=0, video_start=0, width=width, height=height)


def _production_rows(run, plan):
    rows = [_result(run, plan, i) for i in range(4)]
    if (len({r['prompt_id'] for r in rows}) != 4
            or len({r['files']['video']['sha256'] for r in rows}) != 4
            or len({r['files']['video']['source_path'] for r in rows}) != 4):
        raise ParityError('four_distinct_actual_native_videos_required')
    for i, row in enumerate(rows):
        if row.get('native_frames') != FRAMES or row.get('fps') != FPS:
            raise ParityError('native_receipt_clock_changed')
        if row['original_prompt_utf8_sha256'] != plan['segments'][i]['utf8_sha256']:
            raise ParityError('native_receipt_original_prompt_changed')
    return rows


def assemble(run=RUN):
    """Only four distinct, native-history-bound actual H3 results may enter."""
    run = _scope(run)
    plan = _load(run, current=True)
    with jobs.run_lock(run, 'ASSEMBLY.lock'):
        rows = _production_rows(run, plan)
        inputs = dict(plan=binding(run / 'PLAN.json'), results=[binding(run / 'segments' / name / 'RESULT.json') for name in IDS],
                      native_ids=[r['prompt_id'] for r in rows], video_sha256=[r['files']['video']['sha256'] for r in rows],
                      contract='native_frame_and_sample_clock/v2', frames=1448, audio_samples=2896000)
        digest = h3.fingerprint(inputs)
        output = run / 'h3_original_seedance_prompts_60s_736x1312.mp4'
        final = run / 'FINAL_RESULT.json'
        if final.exists():
            receipt = read(final)
            _check(receipt['file'])
            if receipt['assembly_inputs_sha256'] != digest:
                raise ParityError('final_inputs_changed')
            return receipt
        if output.exists():
            raise ParityError('unreceipted_output_preserved_no_overwrite')
        paths = [r['files']['video']['path'] for r in rows]
        timing = [_inspect_clip(path, expected_sha256=r['files']['video']['sha256']) for r, path in zip(rows, paths)]
        filters = run / 'ASSEMBLY_FILTER.txt'
        cmd, text = assembly_command(paths, filters, output)
        if filters.exists() and filters.read_text(encoding='utf-8') != text:
            raise ParityError('assembly_filter_changed')
        filters.write_text(text, encoding='utf-8')
        _freeze(run / 'ASSEMBLY_REQUEST.json', dict(inputs=inputs, inputs_sha256=digest, command=cmd,
                    filter_sha256=sha(filters), source_clock_adjustments=timing))
        process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
        (run / 'ASSEMBLY.stderr.log').write_text(process.stderr, encoding='utf-8')
        process.check_returncode()
        _production_rows(run, plan)
        metadata = _probe(output, True)
        clock = verify_clock(metadata)
        receipt = dict(schema=SCHEMA, file=binding(output), assembly_inputs_sha256=digest,
                       native_ids=inputs['native_ids'], source_clock_adjustments=timing, metadata=metadata,
                       clock=clock, content_status='comparison_review_required', production_approved=False,
                       publication=False, semantic_retry=False)
        _freeze(final, receipt)
        return receipt


def qa(run=RUN):
    """CPU metadata/audio inspection after dispatch; never a semantic pass."""
    run = _scope(run)
    plan = _load(run)
    rows = _production_rows(run, plan)
    evidence = dict(schema=SCHEMA, native_segments=[dict(id=r['id'], prompt_id=r['prompt_id'],
               timing=_inspect_clip(r['files']['video']['path'], expected_sha256=r['files']['video']['sha256'])) for r in rows],
               visual_review='root_required', asr='not_run', production_approved=False, publication=False)
    _write(run / 'QA_METADATA.json', evidence)
    return evidence
