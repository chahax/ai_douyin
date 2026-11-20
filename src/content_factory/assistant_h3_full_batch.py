"""Source-recipe compiled local H3 batch; original IDs and native tails only."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from .assistant_seedance_batch import durable, process_lock
from .assistant_seedance_trial import ROOT, SOURCE, STORY_ID, bound, now, png_integrity, read, sha
from .creative_stage_contracts import digest
from .media_review_policy import mark_saved_candidate

OUT = ROOT / 'data/video_generation/h3_assistant_screenplay_full_20261016'
IDS = [f'S{i:02d}' for i in range(2, 13)]
BATCH_ID = 'assistant_h3_full_20261016'
S01_ID = 'a7b8c0d5-8ec7-4763-adaa-4cbeacd7a0f1'
BASE_SHA = 'b17945cf1589a4ec5685776b29b19d3187a55ece8f6b74cbb53c7c7903fdc672'


class LocalH3Client:
    def __init__(self, url='http://127.0.0.1:8190'):
        if url != 'http://127.0.0.1:8190':
            raise ValueError('only the authorized local H3 endpoint is allowed')
        self.url = url
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        with self.opener.open(self.url + path, timeout=60) as response:
            return json.load(response)

    def post_graph(self, request):
        # No transport or media retry. The caller must already own the durable claim.
        message = urllib.request.Request(self.url + '/prompt', data=json.dumps(request, ensure_ascii=False).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
        with self.opener.open(message, timeout=120) as response:
            return json.load(response)


def log(out, event, **fields):
    row = dict(at=now(), event=event, **fields)
    with (out / 'LOG.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    visible = {key: value for key, value in fields.items() if key in ('segment_id', 'prompt_id', 'phase', 'completed')}
    print(json.dumps(dict(event=event, **visible), ensure_ascii=False), flush=True)


def copy_original(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source.drive.upper() != 'D:' or target.drive.upper() != 'D:':
        raise ValueError('all original inputs/outputs and copies must remain on D:')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(target) != sha(source):
            raise ValueError('never overwrite a different staged original file')
    else:
        shutil.copy2(source, target)
    if sha(source) != sha(target):
        raise ValueError('original byte copy identity failed')
    return target


def history_graph_identity(graph, entry, prompt_id):
    if entry['prompt'][1] != prompt_id:
        raise ValueError('history has another prompt ID')
    actual = entry['prompt'][2]
    normalized = copy.deepcopy(actual)
    coercions = []
    for node, key, value in (('130', 'fps', 24), ('124', 'denoise', 1)):
        original, saved = graph[node]['inputs'][key], actual[node]['inputs'][key]
        if type(original) is int and original == value and type(saved) is float and saved == value:
            normalized[node]['inputs'][key] = original
            coercions.append('/' + node + '/inputs/' + key)
    if digest(normalized) != digest(graph):
        raise ValueError('history graph differs beyond the two archived native numeric coercions')
    return dict(graph_identity_verified=True, submitted_graph_digest=digest(graph),
                history_graph_digest=digest(actual), exact_known_numeric_coercions=coercions)


def compile_graph(base, recipe, parameters):
    if (recipe.get('schema') != 'assistant_h3_native_tail_recipe/v1'
            or set(parameters) != set(recipe['parameters'])
            or recipe['fixed'] != dict(width=1280, height=704, fps=24, length=362, steps=20, frame_idx=0)):
        raise ValueError('unexpected source recipe or named parameter contract')
    graph = copy.deepcopy(base)
    nodes = recipe['nodes']
    condition = nodes['condition']
    if (graph[condition]['class_type'] != 'MiniMaxH3ReferenceToVideo'
            or graph[nodes['model']]['inputs']['unet_name'] != 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'
            or any('lora' in row['class_type'].lower() for row in graph.values())):
        raise ValueError('wrong immutable REF2VA baseline or forbidden LoRA')
    original_condition = graph[condition]['inputs']
    if any(original_condition[key] != value for key, value in (('width', 1280), ('height', 704), ('length', 362))):
        raise ValueError('native baseline size/frame count differs')
    if graph[nodes['scheduler']]['inputs']['steps'] != 20 or graph[nodes['video']]['inputs']['fps'] != 24:
        raise ValueError('native baseline steps/fps differ')
    for index, node in enumerate(recipe['reference_nodes']):
        if original_condition.get(f'ref_images.ref_image_{index}') != [node, 0]:
            raise ValueError('scene/C01/C02 reference order changed')
    original_condition['prompt'] = parameters['prompt']
    original_condition['audio_vae'] = [nodes['audio_vae'], 0]
    original_condition['ref_audios.ref_audio_0'] = [nodes['audio_load'], 0]
    graph[nodes['audio_load']] = dict(class_type='LoadAudio', inputs=dict(audio=parameters['reference_audio_input']))
    graph[nodes['tail_load']] = dict(class_type='LoadImage', inputs=dict(image=parameters['native_tail_input']))
    graph[nodes['guide']] = dict(class_type='MiniMaxH3AddGuide', inputs=dict(
        positive=[condition, 0], latent=[condition, 1], vae=[nodes['video_vae'], 0],
        image=[nodes['tail_load'], 0], frame_idx=0))
    graph[nodes['guider']]['inputs']['conditioning'] = [nodes['guide'], 0]
    if graph[nodes['sampler']]['inputs']['latent_image'] != [condition, 1]:
        raise ValueError('sampler must retain the reference-condition latent')
    graph[nodes['noise']]['inputs']['noise_seed'] = parameters['noise_seed']
    for role, node in recipe['save_nodes'].items():
        graph[node]['inputs']['filename_prefix'] = parameters['output_prefix'] + '/' + role
    if graph['pick_first']['inputs']['batch_index'] != 0 or graph['pick_last']['inputs']['batch_index'] != 361:
        raise ValueError('native save-first/save-last selection differs')
    return graph


def check_schema(graph, schema):
    for node_id, node in graph.items():
        if node['class_type'] not in schema:
            raise ValueError('compiled node class absent from captured live schema')
    guide = schema['MiniMaxH3AddGuide']['input']
    for key, kind in (('positive', 'CONDITIONING'), ('latent', 'LATENT'), ('frame_idx', 'INT')):
        if guide['required'][key][0] != kind:
            raise ValueError('captured native AddGuide required socket contract changed')
    if guide['optional']['image'][0] != 'IMAGE' or guide['optional']['vae'][0] != 'VAE':
        raise ValueError('captured native AddGuide image/VAE contract differs')


def probe_media(path, *, audio_only=False):
    fields = 'stream=index,codec_type,codec_name,width,height,avg_frame_rate,nb_frames,nb_read_packets,sample_rate,channels,duration:format=duration,size'
    command = ['ffprobe', '-v', 'error', '-count_packets', '-show_entries', fields, '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=180)
    if result.returncode:
        raise ValueError('saved H3 container/packet metadata check failed')
    metadata = json.loads(result.stdout)
    videos = [row for row in metadata.get('streams', []) if row.get('codec_type') == 'video']
    audios = [row for row in metadata.get('streams', []) if row.get('codec_type') == 'audio']
    if not audios or any(int(row.get('nb_read_packets', 0)) <= 0 for row in videos + audios):
        raise ValueError('native video/audio packets are missing')
    if not audio_only:
        if (len(videos) != 1 or videos[0].get('width') != 1280 or videos[0].get('height') != 704
                or int(videos[0].get('nb_frames', 0)) != 362
                or abs(float(Fraction(videos[0]['avg_frame_rate'])) - 24) > .01):
            raise ValueError('native H3 resolution/fps/frame count differs')
    elif videos or len(audios) != 1 or audios[0].get('codec_name') != 'flac':
        raise ValueError('native audio output must be the original FLAC')
    if abs(float(metadata['format']['duration']) - 362 / 24) > .6:
        raise ValueError('native H3 output duration differs')
    return metadata


def binding(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def checked_d(path):
    path = Path(path).resolve()
    if path.drive.upper() != 'D:':
        raise ValueError('authorized H3 batch paths must remain on D:')
    return path


def failure_count(plan, out):
    if plan.get('failure_counter_reset') is not False or plan.get('failure_limit') != 10:
        raise ValueError('same story failure policy changed')
    if len(plan['failure_ledgers']) != 4:
        raise ValueError('all four historical failure sources are required')
    count = 0
    for index, row in enumerate(plan['failure_ledgers']):
        data = read(bound(row))
        if data.get('story_id') != STORY_ID:
            raise ValueError('historical story identity changed')
        if index == 0:
            value = data.get('failures_used')
        elif index < 3:
            value = data.get('trial_technical_failures')
            if value is None:
                combined, inherited = data.get('combined_known_failures'), data.get('inherited_failures')
                if type(combined) is not int or type(inherited) is not int or not 0 <= inherited <= combined:
                    raise ValueError('unknown historical failure count')
                value = combined - inherited
        else:
            if any(type(event.get('failure')) is not bool for event in data['events']):
                raise ValueError('unknown batch failure event')
            value = sum(event['failure'] for event in data['events'])
        if type(value) is not int or value < 0:
            raise ValueError('unknown historical failures cannot count as zero')
        count += value
    if count != plan['known_failures_at_preparation']:
        raise ValueError('historical failure count changed')
    if (out / 'MEDIA_EVENTS.json').exists():
        events = read(out / 'MEDIA_EVENTS.json')['events']
        if any(type(event.get('failure')) is not bool for event in events):
            raise ValueError('unknown current failure event')
        count += sum(event['failure'] for event in events)
    if count >= 10:
        raise ValueError('same story failure limit exhausted')
    return count


def admission(out=OUT):
    out = checked_d(out)
    plan = read(out / 'BATCH_PLAN.json')
    auth = read(bound(plan['authorization']))
    if (plan.get('schema') != 'assistant_h3_full_batch_plan/v1' or plan.get('story_id') != STORY_ID
            or auth.get('schema') != 'assistant_h3_full_batch_authorization/v1'
            or auth.get('story_id') != STORY_ID or auth.get('new_segments') != IDS
            or auth.get('max_new_video_submissions') != 11 or auth.get('max_submissions_per_segment') != 1
            or auth.get('original_tail_batch_continuation') is not True or auth.get('allow_assembly') is not True
            or auth.get('automatic_retry') is not False or auth.get('human_content_approval') is not False
            or auth.get('publishing_authorized') is not False or auth.get('local_h3_only') is not True):
        raise ValueError('this exact eleven-segment local authorization is required')
    if auth['screenplay'] != plan['screenplay']:
        raise ValueError('authorization screenplay differs')
    full = bound(plan['screenplay']).read_text(encoding='utf-8')
    if plan['baseline_graph']['sha256'] != BASE_SHA:
        raise ValueError('only the captured S01 native baseline is authorized')
    base = read(bound(plan['baseline_graph']))
    recipe = read(bound(plan['recipe']))
    schema = read(bound(plan['node_schema']))
    if recipe['baseline_graph_sha256'] != BASE_SHA:
        raise ValueError('recipe baseline differs')
    if (plan['service_url'] != 'http://127.0.0.1:8190' or plan['output_prefix'] != 'h3_assistant_screenplay_full_20261016'
            or [plan[key] for key in ('width', 'height', 'fps', 'length', 'steps', 'turbo_lora')]
            != [1280, 704, 24, 362, 20, False]):
        raise ValueError('native H3 settings changed')
    for key in ('input_root', 'output_root', 'global_claim_root'):
        checked_d(plan[key])
    refs = read(bound(plan['reference_map']))
    for row, node in zip(refs, recipe['reference_nodes']):
        if sha(row['source_path']) != row['source_sha256'] or sha(row['input_path']) != row['input_sha256']:
            raise ValueError('original scene/person reference bytes changed')
        if Path(row['input_path']).resolve() != (Path(plan['input_root']) / base[node]['inputs']['image']).resolve():
            raise ValueError('reference request mapping changed')
    if len(refs) != 3:
        raise ValueError('three fixed ordered references required')
    if [row['segment_id'] for row in plan['segments']] != IDS:
        raise ValueError('authorized segment range changed')
    for ordinal, row in enumerate(plan['segments'], 2):
        source, prompt = bound(row['source']).read_text(encoding='utf-8'), bound(row['prompt']).read_text(encoding='utf-8')
        if (row['ordinal'] != ordinal or row['predecessor_segment_id'] != f'S{ordinal-1:02d}'
                or row['duration_seconds'] != 15 or source not in full
                or any(line not in source or line not in prompt for line in row['dialogue'])):
            raise ValueError('source projection, dialogue or ordered lineage changed')
    existing = plan['existing_segment']
    if existing['segment_id'] != 'S01' or existing['task_id'] != S01_ID:
        raise ValueError('original S01 identity changed')
    for key in ('receipt', 'history', 'graph', 'video', 'audio', 'native_tail'):
        bound(existing[key])
    if plan['fixed_audio_reference'] != existing['audio']:
        raise ValueError('audio reference must remain the original S01 FLAC')
    history_graph_identity(base, read(existing['history']['path'])[S01_ID], S01_ID)
    failure_count(plan, out)
    return plan, recipe, base, schema


def reuse_s01(plan, out):
    original = plan['existing_segment']
    technical = read(original['receipt']['path'])
    if technical.get('state') != 'succeeded' or technical.get('prompt_id') != S01_ID:
        raise ValueError('S01 original technical result not successful')
    first = technical['files']['save_first']['path']
    if sha(first) != technical['files']['save_first']['sha256']:
        raise ValueError('S01 original first PNG differs from its service receipt')
    for role,node in (('video','save_video'),('audio','save_audio'),('native_tail','save_last')):
        if original[role]['sha256'] != technical['files'][node]['sha256']:
            raise ValueError('S01 source binding differs from its original service output')
    for path in (first, original['native_tail']['path']):
        info = png_integrity(path)
        if (info['width'], info['height']) != (1280, 704):
            raise ValueError('native S01 frame size changed')
    result = dict(segment_id='S01', story_id=STORY_ID, logical_task_id=BATCH_ID + '_S01_reused', prompt_id=S01_ID,
                  technical_status='succeeded', content_status='awaiting_human_review', content_review=None,
                  original_technical_result=original['receipt'], graph=original['graph'], history=original['history'],
                  graph_sha256=original['graph']['sha256'], history_graph_identity_verified=True,
                  source_bindings=dict(screenplay=plan['screenplay']),
                  video_path=original['video']['path'], video_sha256=original['video']['sha256'],
                  audio_path=original['audio']['path'], audio_sha256=original['audio']['sha256'],
                  last_frame=original['native_tail']['path'], last_frame_sha256=original['native_tail']['sha256'],
                  native_first=first, native_first_sha256=sha(first), last_frame_source='generation_service_original')
    path = out / 'segments/S01/receipt.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    durable(path, result, immutable=True)
    return path


def saved_row(path):
    row = read(path)
    if row.get('technical_status') != 'succeeded' or row.get('content_status') != 'awaiting_human_review':
        raise ValueError('segment has not been technically saved')
    for field, hashfield in (('video_path', 'video_sha256'), ('audio_path', 'audio_sha256'),
                             ('last_frame', 'last_frame_sha256'), ('native_first', 'native_first_sha256')):
        if sha(row[field]) != row[hashfield]:
            raise ValueError('saved native file identity changed')
    return dict(row, receipt=binding(path))


def prepare_segment(plan, recipe, base, schema, segment, predecessor, out):
    sid = segment['segment_id']
    directory = out / 'segments' / sid
    directory.mkdir(parents=True, exist_ok=True)
    relative_tail = f"{plan['output_prefix']}/{sid}/previous_native.png"
    relative_audio = f"{plan['output_prefix']}/shared/S01_reference_audio.flac"
    staged = copy_original(predecessor['last_frame'], Path(plan['input_root']) / relative_tail)
    copy_original(bound(plan['fixed_audio_reference']), Path(plan['input_root']) / relative_audio)
    parameters = dict(prompt=bound(segment['prompt']).read_text(encoding='utf-8'), noise_seed=2026101600+segment['ordinal'],
                      native_tail_input=relative_tail, reference_audio_input=relative_audio,
                      output_prefix=plan['output_prefix'] + '/' + sid)
    graph = compile_graph(base, recipe, parameters)
    check_schema(graph, schema)
    durable(directory / 'PARAMETERS.json', parameters, immutable=True)
    durable(directory / 'workflow_api.json', graph, immutable=True)
    preview = dict(segment_id=sid, graph=binding(directory / 'workflow_api.json'),
                   graph_digest=digest(graph), parameters=binding(directory / 'PARAMETERS.json'),
                   first_frame=dict(path=str(staged), sha256=sha(staged), source_prompt_id=predecessor['prompt_id']),
                   predecessor={key:predecessor[key] for key in ('segment_id','prompt_id','receipt','video_sha256','audio_sha256','last_frame_sha256')},
                   source_binding=segment['source'], prompt_binding=segment['prompt'],
                   source_bindings=dict(screenplay=plan['screenplay']), media_submissions=0)
    durable(directory / 'PREVIEW.json', preview, immutable=True)
    return graph, preview


def prepare(out=OUT):
    plan, recipe, base, schema = admission(out)
    copy_original(bound(plan['baseline_graph']), out / 'runtime/BASELINE_GRAPH_CAPTURE.json')
    first = saved_row(reuse_s01(plan, out))
    graph, preview = prepare_segment(plan, recipe, base, schema, plan['segments'][0], first, out)
    durable(out / 'PREPARED.json', dict(batch_plan=binding(out/'BATCH_PLAN.json'), authorization=plan['authorization'],
                                     recipe=plan['recipe'], node_schema=plan['node_schema'], S02_preview=preview,
                                     media_submissions=0, prepared_at=now()))
    return preview


def event(out, sid, kind, prompt_id=None, failure=False):
    path = out / 'MEDIA_EVENTS.json'
    data = read(path) if path.exists() else dict(story_id=STORY_ID, batch_id=BATCH_ID, events=[])
    data['events'].append(dict(at=now(), segment_id=sid, kind=kind, prompt_id=prompt_id, failure=failure))
    durable(path, data)
    log(out, kind, segment_id=sid, prompt_id=prompt_id)


def check_history_success(entry):
    status = entry.get('status', {})
    if status.get('status_str') == 'error':
        return False
    if status.get('status_str') != 'success' or status.get('completed') is not True:
        raise ValueError('original history is not completed successfully')
    return True


def service_file(plan, item, prefix):
    if item.get('type') != 'output':
        raise ValueError('service result is not an original output')
    relative = Path(item.get('subfolder', '')) / item['filename']
    root = checked_d(plan['output_root'])
    path = (root / relative).resolve()
    expected = (root / prefix).resolve()
    if not path.is_relative_to(expected.parent) or not path.name.startswith(expected.name + '_'):
        raise ValueError('original service path does not belong to this segment save prefix')
    if not path.is_file():
        raise ValueError('original service output is missing')
    return path


def check_predecessor(client, predecessor, plan):
    pid = predecessor['prompt_id']
    response = client.get('/history/' + pid)
    if pid not in response or not check_history_success(response[pid]):
        raise ValueError('current original predecessor is not successful')
    history_graph_identity(read(bound(predecessor['graph'])), response[pid], pid)
    if sha(predecessor['last_frame']) != predecessor['last_frame_sha256']:
        raise ValueError('predecessor native tail identity changed')
    output = response[pid]['outputs']['save_last']['images']
    if len(output) != 1 or output[0].get('type') != 'output':
        raise ValueError('predecessor service native tail is ambiguous')
    root = checked_d(plan['output_root'])
    native = (root / output[0].get('subfolder', '') / output[0]['filename']).resolve()
    if not native.is_relative_to(root) or sha(native) != predecessor['last_frame_sha256']:
        raise ValueError('current service native tail bytes differ from lineage')
    return response


def native_validate(plan, directory):
    report = directory / 'NATIVE_VALIDATION.json'
    helper = bound(plan['native_validator'])
    command = ['D:/IT/AI_vido/ComfyUI/.venv/Scripts/python.exe', '-B', str(helper),
               '--graph', str(directory / 'workflow_api.json'), '--report', str(report), '--input-root', plan['input_root']]
    with (directory / 'native_validate.stdout.log').open('w', encoding='utf-8') as stdout, (directory / 'native_validate.stderr.log').open('w', encoding='utf-8') as stderr:
        result = subprocess.run(command, cwd='D:/IT/AI_vido/ComfyUI', stdout=stdout, stderr=stderr, timeout=600)
    data = read(report)
    if (result.returncode or data.get('valid') is not True or data.get('node_errors')
            or data.get('node_execution_performed') is not False or data['graph_sha256'] != sha(directory/'workflow_api.json')):
        raise ValueError('native validation rejected the exact staged graph')


def state_action(directory):
    """Classify durable state before any network request; never heal a missing ID by POST."""
    receipt = directory / 'receipt.json'
    if receipt.exists():
        data = read(receipt)
        if data.get('technical_status') == 'succeeded':
            return 'saved', data
        if data.get('technical_status') == 'failed':
            raise ValueError('known service failure stops this batch; no automatic media retry')
        if data.get('prompt_id'):
            return 'query', data
    if (directory / 'SUBMISSION_CLAIM.json').exists():
        known = directory / 'SUBMISSION_RESPONSE.json'
        if known.exists() and read(known).get('prompt_id'):
            return 'query', dict(prompt_id=read(known)['prompt_id'], technical_status='pending')
        raise ValueError('durable claim has no known original ID; unknown request cannot be re-dispatched')
    return 'new', None


def review_gate(plan, out):
    review = read(out / 'PRIMARY_RUNTIME_REVIEW.json')
    required = dict(batch_plan_sha256=sha(out/'BATCH_PLAN.json'), authorization_sha256=plan['authorization']['sha256'],
                    runner_sha256=sha(__file__), recipe_sha256=plan['recipe']['sha256'],
                    node_schema_sha256=plan['node_schema']['sha256'], native_validator_sha256=plan['native_validator']['sha256'])
    if review.get('approved_for_batch_start') is not True or any(review.get(key) != value for key,value in required.items()):
        raise ValueError('primary review does not bind the actual runtime and source recipe')
    assembly = plan['assembly']
    script, recipe = bound(assembly['script']), bound(assembly['recipe'])
    assembly_review = read(out / 'PRIMARY_ASSEMBLY_REVIEW.json')
    expected = dict(assembly_script_sha256=sha(script), recipe_sha256=sha(recipe),
                    batch_plan_sha256=sha(out/'BATCH_PLAN.json'), authorization_sha256=plan['authorization']['sha256'])
    if assembly_review.get('approved_for_automatic_assembly') is not True or any(assembly_review.get(key)!=value for key,value in expected.items()):
        raise ValueError('automatic assembly startup review missing or changed')


def submit_once(plan, segment, graph, preview, predecessor, client, out):
    sid = segment['segment_id']
    directory = out/'segments'/sid
    if state_action(directory)[0] != 'new':
        raise ValueError('segment already has a durable submission state')
    if (out/'STOP_REQUESTED.json').exists():
        raise ValueError('user stop checkpoint exists; no new dispatch')
    failure_count(plan, out)
    review_gate(plan, out)
    response = check_predecessor(client, predecessor, plan)
    durable(directory/'PREDECESSOR_SERVICE_RECHECK.json', response)
    queue = client.get('/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('local generation queue must be empty before a new segment')
    native_validate(plan, directory)
    if (out/'STOP_REQUESTED.json').exists():
        raise ValueError('user stop checkpoint exists after native validation; no POST performed')
    if sha(preview['first_frame']['path']) != preview['first_frame']['sha256']:
        raise ValueError('staged service-original tail bytes changed before POST')
    if digest(read(bound(preview['graph']))) != digest(graph):
        raise ValueError('compiled graph changed before POST')
    request = dict(prompt=graph, client_id=str(uuid.uuid4()))
    durable(directory/'REQUEST.actual.json', request, immutable=True)
    claim = dict(at=now(), story_id=STORY_ID, batch_id=BATCH_ID, segment_id=sid,
                 batch_plan=binding(out/'BATCH_PLAN.json'), graph=preview['graph'],
                 actual_request=binding(directory/'REQUEST.actual.json'), predecessor=preview['predecessor'],
                 first_frame=preview['first_frame'], known_failures=failure_count(plan,out),
                 maximum_posts=1, automatic_retry=False)
    global_claim = Path(plan['global_claim_root'])/'H3_FULL_PERMANENT_CLAIMS_20261016'/f'{sid}.json'
    global_claim.parent.mkdir(parents=True, exist_ok=True)
    # Both locks are held by run(); exclusive immutable global file survives every process restart.
    if global_claim.exists():
        raise ValueError('story-wide permanent segment claim already exists; never POST again')
    durable(global_claim, claim, immutable=True)
    durable(directory/'SUBMISSION_CLAIM.json', claim, immutable=True)
    event(out,sid,'dispatch_reserved')
    # Native schema validation can take time: honor a stop or source change arriving during it.
    if (out/'STOP_REQUESTED.json').exists():
        raise ValueError('user stop checkpoint exists after claim; no POST performed; preserve claim')
    failure_count(plan,out)
    review_gate(plan,out)
    try:
        accepted = client.post_graph(request)
    except Exception as exc:
        durable(directory/'UNKNOWN_SUBMISSION.json', dict(at=now(),error_type=type(exc).__name__,error=str(exc),automatic_retry=False))
        raise
    durable(directory/'SUBMISSION_RESPONSE.json',accepted,immutable=True)
    if not accepted.get('prompt_id') or accepted.get('node_errors'):
        raise ValueError('POST lacks a usable original ID; evidence retained, no automatic re-dispatch')
    pid = accepted['prompt_id']
    row = dict(preview,story_id=STORY_ID,logical_task_id=BATCH_ID+'_'+sid,prompt_id=pid,technical_status='pending',
               content_status='awaiting_human_review',content_review=None)
    durable(directory/'receipt.json',row)
    ids = read(out/'job_ids.json') if (out/'job_ids.json').exists() else {}
    ids[sid]=pid
    durable(out/'job_ids.json',ids)
    event(out,sid,'submitted',pid)
    return row


def finish(plan,segment,record,entry,out):
    sid,pid = segment['segment_id'],record['prompt_id']
    directory=out/'segments'/sid
    history_graph_identity(read(directory/'workflow_api.json'),entry,pid)
    durable(directory/'HISTORY.json',{pid:entry})
    if not check_history_success(entry):
        record.update(technical_status='failed',history=binding(directory/'HISTORY.json'))
        durable(directory/'receipt.json',record)
        event(out,sid,'service_failed',pid,True)
        raise ValueError('known local service failure; no automatic retry')
    files={}
    for role,node,field,extension in [('video','save_video','images','.mp4'),('audio','save_audio','audio','.flac'),
                                      ('first','save_first','images','.png'),('last','save_last','images','.png')]:
        rows=entry['outputs'][node][field]
        if len(rows)!=1:
            raise ValueError('ambiguous native save output')
        original=service_file(plan,rows[0],plan['output_prefix']+'/'+sid+'/'+role)
        if original.suffix.lower()!=extension:
            raise ValueError('unexpected original output encoding')
        metadata=probe_media(original,audio_only=role=='audio') if role in ('video','audio') else png_integrity(original)
        if role in ('first','last') and (metadata['width'],metadata['height'])!=(1280,704):
            raise ValueError('native PNG dimensions differ')
        saved=copy_original(original,directory/('native_'+role+extension))
        files[role]=dict(path=str(saved),sha256=sha(saved),original_service_path=str(original),bytes=saved.stat().st_size,metadata=metadata)
    record.update(technical_status='succeeded',content_status='awaiting_human_review',content_review=None,
                  video_path=files['video']['path'],video_sha256=files['video']['sha256'],
                  audio_path=files['audio']['path'],audio_sha256=files['audio']['sha256'],
                  last_frame=files['last']['path'],last_frame_sha256=files['last']['sha256'],
                  native_first=files['first']['path'],native_first_sha256=files['first']['sha256'],
                  history=binding(directory/'HISTORY.json'),graph=binding(directory/'workflow_api.json'),
                  graph_sha256=sha(directory/'workflow_api.json'),history_graph_identity_verified=True,
                  files=files,last_frame_source='generation_service_original')
    durable(directory/'receipt.json',record)
    event(out,sid,'saved_awaiting_human_review',pid)
    return record


def wait_original(plan,segment,record,client,out,timeout=21600,poll=30):
    if timeout < 14400:
        raise ValueError('H3 segment timeout must allow at least four hours')
    pid=record['prompt_id'];started=time.monotonic()
    while True:
        response=client.get('/history/'+pid)
        if pid in response:
            return finish(plan,segment,record,response[pid],out)
        elapsed=time.monotonic()-started
        durable(out/'BATCH_STATUS.json',dict(at=now(),status='running',segment_id=segment['segment_id'],prompt_id=pid,
                                           phase='original_task_pending',elapsed_seconds=round(elapsed)))
        log(out,'original_task_pending',segment_id=segment['segment_id'],prompt_id=pid,phase='rendering')
        if elapsed>=timeout:
            raise TimeoutError('original task still pending; preserve ID and resume query, never re-submit')
        time.sleep(poll)


def run(out=OUT,client=None,timeout=21600,poll=30):
    out=checked_d(out)
    with process_lock(out/'.h3_batch_process.lock'):
        plan,recipe,base,schema=admission(out)
        with process_lock(Path(plan['global_claim_root'])/'.h3_full_dispatch.lock'):
            review_gate(plan,out)
            client=client or LocalH3Client(plan['service_url'])
            predecessor=saved_row(reuse_s01(plan,out)); chain=[predecessor]
            for segment in plan['segments']:
                sid=segment['segment_id'];directory=out/'segments'/sid
                action,record=state_action(directory)
                if action=='saved':
                    predecessor=saved_row(directory/'receipt.json');chain.append(predecessor)
                    log(out,'saved_segment_skipped',segment_id=sid,prompt_id=predecessor['prompt_id'])
                    continue
                graph,preview=prepare_segment(plan,recipe,base,schema,segment,predecessor,out)
                if action=='new':
                    current_plan,_,_,_=admission(out)
                    if current_plan != plan:
                        raise ValueError('batch inputs changed during execution')
                    record=submit_once(plan,segment,graph,preview,predecessor,client,out)
                else:
                    record=dict(preview,**{key:value for key,value in record.items() if key not in preview})
                    record.setdefault('logical_task_id',BATCH_ID+'_'+sid)
                    record.setdefault('story_id',STORY_ID)
                    ids=read(out/'job_ids.json') if (out/'job_ids.json').exists() else {}
                    ids[sid]=record['prompt_id'];durable(out/'job_ids.json',ids)
                    log(out,'resume_original_id',segment_id=sid,prompt_id=record['prompt_id'])
                wait_original(plan,segment,record,client,out,timeout,poll)
                predecessor=saved_row(directory/'receipt.json');chain.append(predecessor)
            durable(out/'COMPLETED_FILE_CHAIN.json',dict(schema='assistant_h3_completed_file_chain/v1',
                    batch_plan=binding(out/'BATCH_PLAN.json'),authorization=plan['authorization'],segments=chain,
                    technical_status='succeeded',content_status='awaiting_human_review',content_review=None),immutable=True)
            review_gate(plan,out)
            command=[sys.executable,'-B',str(bound(plan['assembly']['script'])),'execute','--manifest',str(out/'COMPLETED_FILE_CHAIN.json')]
            with (out/'assembly_runner.stdout.log').open('a',encoding='utf-8') as stdout,(out/'assembly_runner.stderr.log').open('a',encoding='utf-8') as stderr:
                result=subprocess.run(command,stdout=stdout,stderr=stderr,timeout=1800)
            if result.returncode:
                raise ValueError('local assembly stopped; no automatic fallback or regeneration')
            durable(out/'BATCH_STATUS.json',dict(at=now(),status='complete',segments=12,content_status='awaiting_human_review'))
            return dict(status='complete',content_status='awaiting_human_review',segments=12)


def status(out=OUT,client=None):
    plan=read(out/'BATCH_PLAN.json');client=client or LocalH3Client(plan['service_url'])
    rows=[]
    for sid in IDS:
        directory=out/'segments'/sid
        action,record=state_action(directory)
        row=dict(segment_id=sid,local_state=action)
        if record and record.get('prompt_id'):
            row['prompt_id']=record['prompt_id']
            response=client.get('/history/'+record['prompt_id'])
            row['service_status']=response.get(record['prompt_id'],{}).get('status',{}).get('status_str','pending')
        rows.append(row)
    return dict(segments=rows,media_submissions=0)
