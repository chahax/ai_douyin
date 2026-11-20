"""Frozen S02-S04 local H3 continuation; one POST per segment, no unknown retries."""
from __future__ import annotations
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

HELPER = Path(__file__).with_name('run_h3_six_children_s01_20261102.py')
spec = importlib.util.spec_from_file_location('h3_s01_helper', HELPER)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
ROOT = h.ROOT
BATCH = ROOT / 'data/video_generation/h3_six_children_60s_20261102'
SERVICE = h.RUN
SEEDANCE = h.SEEDANCE
VALIDATOR = ROOT / 'data/video_generation/h3_assistant_screenplay_full_20261016/runtime/validate_graph.py'
PYTHON = Path('D:/IT/AI_vido/ComfyUI/.venv/Scripts/python.exe')
IDS = ('S02', 'S03', 'S04')
PREFIX = 'six_children_60s_20261102'
DURATION = 362 / 24


def bound_ok(item):
    if h.sha(item['path']) != item['sha256']:
        raise ValueError('frozen_file_changed:' + item['path'])


def prepared_graph(base, prompt, segment):
    graph = copy.deepcopy(base)
    graph['condition']['inputs']['prompt'] = prompt
    graph['129']['inputs']['noise_seed'] = 2026110200 + int(segment[-2:]) - 1
    graph['ref_scene']['inputs']['image'] = PREFIX + '_' + segment + '_previous_native.png'
    for role in ('video', 'audio', 'first', 'last'):
        graph['save_' + role]['inputs']['filename_prefix'] = PREFIX + '/' + segment + '/' + role
    return graph


def verify_saved(run, client=None):
    receipt = h.read(run / 'receipt.json')
    if receipt.get('technical_status') != 'succeeded':
        raise ValueError('predecessor_not_successful')
    for row in [receipt['delivery'], *receipt['files'].values()]:
        bound_ok(row)
    graph = h.read(run / 'workflow_api.json')
    history = h.read(run / 'HISTORY.json')
    check_history(history, receipt['prompt_id'], graph, complete=True)
    if client is not None:
        check_history(client.get('/history/' + receipt['prompt_id']), receipt['prompt_id'], graph, complete=True)
    return receipt


def check_history(history, prompt_id, graph, complete=False):
    entry = history.get(prompt_id)
    if not entry:
        if complete:
            raise ValueError('predecessor_live_history_missing')
        return None
    if entry['prompt'][1] != prompt_id or entry['prompt'][2] != graph:
        raise ValueError('history_identity_mismatch')
    if complete and (entry['status'].get('status_str') != 'success' or not entry['status'].get('completed')):
        raise ValueError('predecessor_history_not_successful')
    return entry


def prepare(batch=BATCH):
    if (batch / 'PLAN.json').exists():
        raise ValueError('already_prepared')
    batch.mkdir(parents=True, exist_ok=True)
    first = verify_saved(SERVICE)
    base = h.read(SERVICE / 'workflow_api.json')
    if (base['condition']['inputs']['width'], base['condition']['inputs']['height'],
        base['condition']['inputs']['length'], base['124']['inputs']['steps'], base['130']['inputs']['fps']) != (736, 1312, 362, 12, 24):
        raise ValueError('unexpected_base_parameters')
    entries = []
    for segment in IDS:
        run = batch / segment
        (run / 'deliverables').mkdir(parents=True, exist_ok=True)
        source = SEEDANCE / 'segments' / segment / 'PROMPT.txt'
        h.original_copy(source, run / 'PROMPT.txt')
        graph = prepared_graph(base, source.read_text(encoding='utf-8'), segment)
        h.durable(run / 'workflow_api.json', graph, immutable=True)
        h.durable(run / 'STATE.json', dict(status='prepared', prompt_id=None, submissions=0))
        entries.append(dict(segment=segment, source_prompt=h.binding(source), prompt=h.binding(run / 'PROMPT.txt'),
                            graph=h.binding(run / 'workflow_api.json')))
    plan = dict(schema='h3_serial_continuation/v1', scope='existing S01 plus S02/S03/S04, no cloud, no publish',
                service_root=str(SERVICE.resolve()), service_url=h.URL, base_graph=h.binding(SERVICE / 'workflow_api.json'),
                first_receipt=h.binding(SERVICE / 'receipt.json'), first_history=h.binding(SERVICE / 'HISTORY.json'),
                first_prompt_id=first['prompt_id'], code=h.binding(__file__), helper=h.binding(HELPER),
                validator=h.binding(VALIDATOR), models=h.read(SERVICE / 'PLAN.json')['models'], segments=entries,
                max_new_submissions=3, native_width=736, native_height=1312, frames_per_segment=362, fps=24,
                steps=12, crop='720:1280:8:16', predecessor='previous H3 native last image only',
                audio_assembly='pad/trim each native segment audio to 362/24 seconds then concatenate',
                content_status='awaiting_human_review')
    h.durable(batch / 'PLAN.json', plan, immutable=True)
    h.durable(batch / 'STATE.json', dict(status='prepared', active_segment=None, completed_segments=['S01']))
    h.log(batch, 'PREPARED remaining three; no media submitted')
    return plan


def validate_plan(batch):
    plan = h.read(batch / 'PLAN.json')
    for key in ('base_graph', 'first_receipt', 'first_history', 'code', 'helper', 'validator'):
        bound_ok(plan[key])
    for segment in plan['segments']:
        for key in ('source_prompt', 'prompt', 'graph'):
            bound_ok(segment[key])
    for row in plan['models']:
        stat = Path(row['path']).stat()
        if stat.st_size != row['bytes'] or stat.st_mtime_ns != row['mtime_ns']:
            raise ValueError('model_file_changed')
    if plan['service_root'] != str(SERVICE.resolve()) or plan['service_url'] != h.URL:
        raise ValueError('service_identity_changed')
    review = h.read(batch / 'PRIMARY_DISPATCH_REVIEW.json')
    if review.get('approved_for_remaining_three_and_assembly') is not True or review.get('plan_sha256') != h.sha(batch / 'PLAN.json'):
        raise ValueError('primary_dispatch_review_required')
    return plan


def service_preflight(client, run):
    stats = client.get('/system_stats')
    argv = stats['system']['argv']
    for flag, name in [('--input-directory', 'input'), ('--output-directory', 'output')]:
        if flag not in argv or Path(argv[argv.index(flag)+1]).resolve() != (SERVICE / name).resolve():
            raise ValueError('wrong_service_paths')
    if '--offline' not in argv or '--disable-all-custom-nodes' not in argv:
        raise ValueError('wrong_service_mode')
    queue = client.get('/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('service_busy_no_submission')
    h.durable(run / 'SERVICE_PREFLIGHT.json', dict(system_stats=stats, queue=queue, at=h.now()))


def native_validate(run):
    report = run / 'NATIVE_VALIDATION.json'
    if not report.exists():
        env = os.environ.copy()
        cache = run / 'validation_cache'
        for key, folder in [('TEMP', 'temp'), ('TMP', 'temp'), ('HF_HOME', 'hf'), ('TORCH_HOME', 'torch'), ('XDG_CACHE_HOME', 'xdg'),
                            ('CUDA_CACHE_PATH', 'cuda'), ('TRITON_CACHE_DIR', 'triton'), ('TORCHINDUCTOR_CACHE_DIR', 'inductor')]:
            path = cache / folder
            path.mkdir(parents=True, exist_ok=True)
            env[key] = str(path.resolve())
        env.update(PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONIOENCODING='utf-8')
        command = [str(PYTHON), '-B', str(VALIDATOR), '--graph', str(run / 'workflow_api.json'),
                   '--report', str(report), '--input-root', str(SERVICE / 'input')]
        h.durable(run / 'VALIDATION_COMMAND.json', command, immutable=True)
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env=env, timeout=180)
        (run / 'validation.stdout.log').write_text(result.stdout, encoding='utf-8')
        (run / 'validation.stderr.log').write_text(result.stderr, encoding='utf-8')
        result.check_returncode()
    value = h.read(report)
    if not value.get('valid') or value.get('node_errors') or value.get('node_execution_performed') is not False or value.get('graph_sha256') != h.sha(run / 'workflow_api.json'):
        raise ValueError('native_validation_failed')


def freeze_predecessor(batch, run, previous, client):
    receipt = verify_saved(previous, client)
    graph = h.read(run / 'workflow_api.json')
    target = SERVICE / 'input' / graph['ref_scene']['inputs']['image']
    h.original_copy(receipt['files']['last']['path'], target)
    frozen = dict(plan=h.binding(batch / 'PLAN.json'), graph=h.binding(run / 'workflow_api.json'),
                  predecessor_receipt=h.binding(previous / 'receipt.json'), predecessor_history=h.binding(previous / 'HISTORY.json'),
                  predecessor_native_tail=receipt['files']['last'], staged_input=h.binding(target))
    h.durable(run / 'FROZEN_INPUT.json', frozen, immutable=True)
    return frozen


def validate_frozen(run):
    frozen = h.read(run / 'FROZEN_INPUT.json')
    for row in frozen.values():
        bound_ok(row)


def execute_segment(batch, run, previous, client, sleep=time.sleep, validate_fn=native_validate, collect_fn=None):
    collect_fn = collect_fn or collect
    state = h.read(run / 'STATE.json')
    if state['status'] == 'saved':
        validate_frozen(run)
        return verify_saved(run, client)
    if state['status'] in ('failed', 'request_rejected'):
        raise ValueError('terminal_segment_not_replayed')
    if not state.get('prompt_id') and (run / 'SUBMISSION_RESPONSE.json').exists():
        response = h.read(run / 'SUBMISSION_RESPONSE.json')
        if response.get('prompt_id') and not response.get('node_errors'):
            state.update(prompt_id=response['prompt_id'], status='submitted')
            h.durable(run / 'STATE.json', state)
    if not state.get('prompt_id'):
        if (run / 'SUBMISSION_CLAIM.json').exists():
            raise ValueError('unknown_submission_not_replayed')
        freeze_predecessor(batch, run, previous, client)
        validate_fn(run)
        validate_frozen(run)
        service_preflight(client, run)
        request = dict(prompt=h.read(run / 'workflow_api.json'), client_id=str(uuid.uuid4()))
        h.durable(run / 'REQUEST.actual.json', request, immutable=True)
        h.durable(run / 'SUBMISSION_CLAIM.json', dict(at=h.now(), request=h.binding(run / 'REQUEST.actual.json'),
                   frozen_input=h.binding(run / 'FROZEN_INPUT.json')), immutable=True)
        state.update(status='submit_outcome_unknown', submissions=1)
        h.durable(run / 'STATE.json', state)
        response = client.post(request)
        h.durable(run / 'SUBMISSION_RESPONSE.json', response, immutable=True)
        if not response.get('prompt_id') or response.get('node_errors'):
            state['status'] = 'request_rejected'
            h.durable(run / 'STATE.json', state)
            raise ValueError('submission_not_accepted')
        state.update(status='submitted', prompt_id=response['prompt_id'])
        h.durable(run / 'STATE.json', state)
        (run / 'job_ids.txt').write_text(state['prompt_id'] + '\n', encoding='utf-8')
        h.log(batch, run.name + ' SUBMITTED ' + state['prompt_id'])
    validate_frozen(run)
    deadline = time.monotonic() + 21600
    while True:
        history = client.get('/history/' + state['prompt_id'])
        h.durable(run / 'HISTORY.latest.json', history)
        entry = check_history(history, state['prompt_id'], h.read(run / 'workflow_api.json'))
        if entry:
            if entry['status']['status_str'] == 'error':
                state['status'] = 'failed'
                h.durable(run / 'STATE.json', state)
                raise ValueError('native_execution_failed')
            if entry['status'].get('completed') and entry['status']['status_str'] == 'success':
                h.durable(run / 'HISTORY.json', history, immutable=True)
                return collect_fn(run, entry, state)
        if time.monotonic() > deadline:
            raise TimeoutError('original_id_retained')
        h.durable(run / 'QUEUE.latest.json', dict(at=h.now(), queue=client.get('/queue')))
        sleep(30)


def streams(metadata):
    return (next(s for s in metadata['streams'] if s['codec_type'] == 'video'),
            next(s for s in metadata['streams'] if s['codec_type'] == 'audio'))


def collect(run, entry, state):
    files = {}
    for role, kind, suffix in [('video', 'images', 'mp4'), ('audio', 'audio', 'flac'), ('first', 'images', 'png'), ('last', 'images', 'png')]:
        rows = entry['outputs']['save_' + role][kind]
        if len(rows) != 1 or rows[0]['type'] != 'output':
            raise ValueError('unexpected_output')
        row = rows[0]
        source = (SERVICE / 'output' / row.get('subfolder', '') / row['filename']).resolve()
        expected = (SERVICE / 'output' / PREFIX / run.name).resolve()
        if not source.is_relative_to(expected):
            raise ValueError('output_escape_or_wrong_segment')
        files[role] = dict(original_service_path=str(source), **h.original_copy(source, run / ('native_' + role + '.' + suffix)))
    native = h.metadata(files['video']['path'])
    v, a = streams(native)
    if (v['width'], v['height'], int(v['nb_frames']), v['r_frame_rate']) != (736, 1312, 362, '24/1'):
        raise ValueError('unexpected_native_dimensions')
    h.durable(run / 'NATIVE_METADATA.json', native, immutable=True)
    target = run / 'deliverables' / (run.name + '_h3_720x1280_with_audio.mp4')
    command = ['ffmpeg', '-nostdin', '-v', 'warning', '-i', files['video']['path'], '-vf', 'crop=720:1280:8:16',
               '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-c:a', 'copy', '-movflags', '+faststart', str(target)]
    run_ffmpeg_once(run, 'CROP', command, target)
    delivery = h.metadata(target)
    v, a = streams(delivery)
    if (v['width'], v['height'], int(v['nb_frames']), v['r_frame_rate']) != (720, 1280, 362, '24/1'):
        raise ValueError('unexpected_delivery_dimensions')
    receipt = dict(prompt_id=state['prompt_id'], technical_status='succeeded', content_status='awaiting_human_review',
                   files=files, delivery=h.binding(target), native_metadata=native, delivery_metadata=delivery,
                   predecessor=h.read(run / 'FROZEN_INPUT.json'), video_content_reviewed=False)
    h.durable(run / 'receipt.json', receipt, immutable=True)
    state.update(status='saved', delivery=str(target.resolve()))
    h.durable(run / 'STATE.json', state)
    return receipt


def run_ffmpeg_once(run, label, command, target):
    completed = run / (label + '_COMPLETED.json')
    h.durable(run / (label + '_COMMAND.json'), command, immutable=True)
    if completed.exists():
        bound_ok(h.read(completed))
        return
    if target.exists():
        raise ValueError('incomplete_local_encode_preserved:' + str(target))
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    (run / (label + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
    result.check_returncode()
    h.durable(completed, h.binding(target), immutable=True)


def assemble(batch, receipts):
    deliver = batch / 'deliverables'
    deliver.mkdir(exist_ok=True)
    inputs = [Path(r['delivery']['path']) for r in receipts]
    for receipt in receipts:
        bound_ok(receipt['delivery'])
    listing = batch / 'CONCAT.txt'
    text = ''.join("file '" + p.as_posix().replace("'", "'\\''") + "'\nduration " + f'{DURATION:.12f}' + '\n' for p in inputs)
    if listing.exists() and listing.read_text(encoding='utf-8') != text:
        raise ValueError('concat_inputs_changed')
    listing.write_text(text, encoding='utf-8')
    target = deliver / 'six_children_h3_opening_60s_review.mp4'
    command = ['ffmpeg', '-nostdin', '-v', 'warning', '-f', 'concat', '-safe', '0', '-i', str(listing)]
    for p in inputs:
        command += ['-i', str(p)]
    filters = [f'[{i+1}:a]apad,atrim=duration={DURATION:.12f},asetpts=PTS-STARTPTS[a{i}]' for i in range(4)]
    filters.append(''.join(f'[a{i}]' for i in range(4)) + 'concat=n=4:v=0:a=1[aout]')
    command += ['-filter_complex', ';'.join(filters), '-map', '0:v:0', '-map', '[aout]', '-c:v', 'copy',
                '-c:a', 'aac', '-b:a', '192k', '-t', f'{4 * DURATION:.12f}', '-movflags', '+faststart', str(target)]
    run_ffmpeg_once(batch, 'ASSEMBLY', command, target)
    metadata = h.metadata(target)
    v, a = streams(metadata)
    if (v['width'], v['height'], int(v['nb_frames']), v['r_frame_rate']) != (720, 1280, 1448, '24/1'):
        raise ValueError('unexpected_full_video_metadata')
    if abs(float(v['duration']) - 4 * DURATION) > .001 or abs(float(a['duration']) - 4 * DURATION) > .05:
        raise ValueError('unexpected_full_av_duration')
    packet_command = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_packets', '-show_entries',
                      'packet=pts_time,dts_time,duration_time', '-of', 'json', str(target)]
    packets = json.loads(subprocess.run(packet_command, capture_output=True, text=True, check=True).stdout)['packets']
    pts = sorted(float(p['pts_time']) for p in packets)
    if len(pts) != 1448 or any(abs((b-a)-1/24) > .0001 for a,b in zip(pts,pts[1:])):
        raise ValueError('video_packet_timeline_discontinuous')
    h.durable(batch / 'PACKET_TIMELINE.json', dict(command=packet_command, count=len(pts), first_pts=pts[0],
              last_pts=pts[-1], continuous=True, inspection='container packet timestamps only; no decoded frames'), immutable=True)
    receipt = dict(technical_status='succeeded', content_status='awaiting_human_review', delivery=h.binding(target),
                   segment_receipts=[dict(prompt_id=r['prompt_id'], delivery=r['delivery']) for r in receipts],
                   metadata=metadata, video_stream_copy=True, audio='per-segment pad/trim then concat and AAC encode',
                   video_content_reviewed=False)
    h.durable(batch / 'receipt.json', receipt, immutable=True)
    h.durable(batch / 'STATE.json', dict(status='saved', completed_segments=['S01', *IDS], active_segment=None,
              delivery=str(target.resolve()), content_status='awaiting_human_review'))
    h.log(batch, 'SAVED complete local H3 minute ' + str(target))
    return receipt


def execute(batch=BATCH, client=None, validate_fn=native_validate, collect_fn=None, assemble_fn=assemble):
    client = client or h.Client()
    with h.process_lock(batch / '.batch.lock'):
        validate_plan(batch)
        if h.read(batch / 'STATE.json')['status'] == 'saved':
            receipt = h.read(batch / 'receipt.json')
            bound_ok(receipt['delivery'])
            return receipt
        receipts = [verify_saved(SERVICE, client)]
        previous = SERVICE
        for segment in IDS:
            h.durable(batch / 'STATE.json', dict(status='running', active_segment=segment,
                      completed_segments=['S01', *list(IDS[:len(receipts)-1])]))
            run = batch / segment
            try:
                receipt = execute_segment(batch, run, previous, client, validate_fn=validate_fn, collect_fn=collect_fn)
            except Exception as error:
                h.durable(batch / 'STATE.json', dict(status='stopped', active_segment=segment,
                          completed_segments=['S01', *list(IDS[:len(receipts)-1])], error_type=type(error).__name__, error=str(error)))
                raise
            receipts.append(receipt)
            previous = run
        return assemble_fn(batch, receipts)


def status(batch=BATCH):
    result = dict(batch=h.read(batch / 'STATE.json'), segments={s: h.read(batch / s / 'STATE.json') for s in IDS})
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'execute', 'status'])
    parser.add_argument('--batch', type=Path, default=BATCH)
    args = parser.parse_args()
    globals()[args.command](args.batch)
