"""Configurable local image jobs with frozen inputs and one native submission.

This module never restarts Comfy, removes another batch's pause, or approves images.
The caller owns semantic review and scheduling across image and vision workers.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import uuid

from PIL import Image

VERSION = 'visual_image_jobs/v3'
MODELS = dict(unet='flux-2-klein-4b.safetensors',
              clip='qwen_3_4b_fp4_flux2.safetensors', vae='flux2-vae.safetensors')
IMAGE_CLASSES = {'UNETLoader','CLIPLoader','VAELoader','KSamplerSelect','CLIPTextEncode',
                 'LoadImage','ImageCrop','VAEEncode','ReferenceLatent','CFGGuider',
                 'Flux2Scheduler','EmptyFlux2LatentImage','RandomNoise',
                 'SamplerCustomAdvanced','VAEDecode','SaveImage'}


class JobIntegrityError(ValueError):
    pass


class JobBusyError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _freeze(path, value):
    path = Path(path)
    if path.exists():
        if _read(path) != value:
            raise JobIntegrityError('frozen_record_changed:' + path.name)
        return
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_new(source, target):
    """Publish a complete local copy without replacing any existing target."""
    target = Path(target)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.copy')
    try:
        with temporary.open('xb') as out, Path(source).open('rb') as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        os.link(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('unsafe_identifier')
    return value


def _relative(value):
    if not isinstance(value, str) or '\\' in value or ':' in value:
        raise ValueError('unsafe_relative_path')
    p = PurePosixPath(value)
    if p.is_absolute() or not p.parts or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('unsafe_relative_path')
    return str(p)


def _bound(root, name):
    root = Path(root).resolve()
    try:
        relative = _relative(name)
    except ValueError as error:
        raise JobIntegrityError('invalid_bound_relative_path') from error
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise JobIntegrityError('path_outside_root')
    return path


@dataclass(frozen=True)
class Config:
    service_url: str
    input_root: str | Path
    output_root: str | Path
    allowed_prefix: str = 'visual_assets_v3'
    protected_pause_path: str | Path | None = None
    timeout: float = 30
    verify_service_paths: bool = True

    def normalized(self):
        url = urlsplit(self.service_url)
        if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')
                or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('local_comfy_url_required')
        if not 0 < self.timeout <= 300:
            raise ValueError('invalid_timeout')
        return dict(service_url=self.service_url.rstrip('/'),
                    input_root=str(Path(self.input_root).resolve()),
                    output_root=str(Path(self.output_root).resolve()),
                    allowed_prefix=_relative(self.allowed_prefix), timeout=self.timeout,
                    verify_service_paths=self.verify_service_paths,
                    protected_pause_path=str(Path(self.protected_pause_path).resolve())
                    if self.protected_pause_path else None)


@contextmanager
def run_lock(folder, name='EXECUTION.lock'):
    """Nonblocking cross-process lock; a crashed process releases its OS lock."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError('lock_directory_missing')
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in ('.','..'):
        raise ValueError('invalid_lock_name')
    with (folder / name).open('a+b') as handle:
        handle.seek(0)
        handle.write(b'0')
        handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise JobBusyError('job_already_executing') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def build_graph(items, prefix, models=None, width=768, height=1024, steps=4):
    """Independent single-view samplers sharing model loading.

    items: {id,prompt,seed,references:[{input_name,roi?}]}.
    Zero refs is casting; one ref is an angle or ROI detail; multiple refs
    compose only the people/environment selected by the upstream shot compiler.
    The graph embeds no labels or post-production captions.
    """
    prefix = _relative(prefix)
    if not items or not (isinstance(width, int) and isinstance(height, int)
                        and width >= 64 and height >= 64 and width % 16 == height % 16 == 0):
        raise ValueError('invalid_dimensions_or_empty_batch')
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError('invalid_steps')
    model = {**MODELS, **(models or {})}
    graph = {
        'unet': dict(class_type='UNETLoader', inputs=dict(unet_name=model['unet'], weight_dtype='default')),
        'clip': dict(class_type='CLIPLoader', inputs=dict(clip_name=model['clip'], type='flux2', device='default')),
        'vae': dict(class_type='VAELoader', inputs=dict(vae_name=model['vae'])),
        'sampler': dict(class_type='KSamplerSelect', inputs=dict(sampler_name='euler')),
    }
    ids = []
    for item in items:
        key = _slug(item['id'])
        if item.get('render_text',False) is not False:
            raise ValueError('production_images_do_not_embed_captions')
        if key in ids or key in graph:
            raise ValueError('duplicate_or_reserved_item_id')
        ids.append(key)
        text, seed = item['prompt'], item['seed']
        if not isinstance(text, str) or not text.strip() or type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError('invalid_prompt_or_seed')
        refs = item.get('references', [])
        if not isinstance(refs, list) or len(refs) > 9:
            raise ValueError('invalid_reference_count')
        def node(name, kind, **inputs):
            nid = key + '__' + name
            graph[nid] = dict(class_type=kind, inputs=inputs)
            return [nid, 0]
        positive = node('positive', 'CLIPTextEncode', text=text, clip=['clip', 0])
        negative = node('negative', 'CLIPTextEncode', text='', clip=['clip', 0])
        for i, ref in enumerate(refs):
            image = node('image_' + str(i), 'LoadImage', image=_relative(ref['input_name']))
            if ref.get('roi') is not None:
                roi = ref['roi']
                if (len(refs) != 1 or set(roi) != {'x', 'y', 'width', 'height'}
                        or any(type(v) is not int or v < 0 for v in roi.values())
                        or roi['width'] < 1 or roi['height'] < 1):
                    raise ValueError('detail_requires_one_valid_roi_reference')
                image = node('crop_' + str(i), 'ImageCrop', image=image, **roi)
            encoded = node('encode_' + str(i), 'VAEEncode', pixels=image, vae=['vae', 0])
            positive = node('positive_ref_' + str(i), 'ReferenceLatent', conditioning=positive, latent=encoded)
            negative = node('negative_ref_' + str(i), 'ReferenceLatent', conditioning=negative, latent=encoded)
        guider = node('guider', 'CFGGuider', model=['unet', 0], positive=positive, negative=negative, cfg=1)
        sigma = node('sigmas', 'Flux2Scheduler', steps=steps, width=width, height=height)
        latent = node('latent', 'EmptyFlux2LatentImage', width=width, height=height, batch_size=1)
        noise = node('noise', 'RandomNoise', noise_seed=seed)
        sample = node('sample', 'SamplerCustomAdvanced', noise=noise, guider=guider,
                      sampler=['sampler', 0], sigmas=sigma, latent_image=latent)
        decoded = node('decode', 'VAEDecode', samples=sample, vae=['vae', 0])
        node('save', 'SaveImage', images=decoded, filename_prefix=prefix + '/' + key)
    return graph


def _validate_graph(graph, scope):
    if not isinstance(graph, dict) or not graph:
        raise ValueError('graph_required')
    saves = []
    images = []
    for nid, node in graph.items():
        _slug(nid)
        if not isinstance(node, dict) or not isinstance(node.get('inputs'), dict):
            raise ValueError('invalid_node')
        if node.get('class_type') not in IMAGE_CLASSES:
            raise ValueError('unsupported_nonlocal_or_nonimage_node')
        loader_name = {'UNETLoader':'unet_name','CLIPLoader':'clip_name','VAELoader':'vae_name'}.get(node.get('class_type'))
        if loader_name:
            _relative(node['inputs'][loader_name])
        if node.get('class_type') == 'SaveImage':
            prefix = _relative(node['inputs']['filename_prefix'])
            if not prefix.startswith(scope + '/'):
                raise ValueError('save_prefix_outside_job_scope')
            saves.append(prefix)
        elif node.get('class_type') == 'LoadImage':
            images.append(_relative(node['inputs']['image']))
    if not saves or len(saves) != len(set(saves)):
        raise ValueError('missing_or_duplicate_save_prefix')
    return set(images)


def stage_input(config, source, input_name, expected_sha256):
    cfg = config.normalized() if isinstance(config, Config) else Config(**config).normalized()
    source = Path(source).resolve()
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256) or file_sha(source) != expected_sha256:
        raise JobIntegrityError('input_source_sha_mismatch')
    with Image.open(source) as image:
        image.verify()
    target = _bound(cfg['input_root'], input_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_sha(target) != expected_sha256:
            raise JobIntegrityError('staged_input_already_differs')
    else:
        _copy_new(source,target)
    if file_sha(target) != expected_sha256:
        raise JobIntegrityError('staged_input_changed_during_copy')
    return dict(input_name=_relative(input_name), path=str(source), sha256=expected_sha256,
                staged_path=str(target))


def prepare_job(job_dir, graph, config, inputs=(), job_id=None):
    job = Path(job_dir).resolve()
    jid = _slug(job_id or job.name)
    cfg = config.normalized() if isinstance(config, Config) else Config(**config).normalized()
    if not Path(cfg['input_root']).is_dir() or not Path(cfg['output_root']).is_dir():
        raise ValueError('service_input_output_directories_required')
    names = _validate_graph(graph, cfg['allowed_prefix'] + '/' + jid)
    bindings = []
    for item in inputs:
        name = _relative(item['input_name'])
        if name in {b['input_name'] for b in bindings}:
            raise ValueError('duplicate_input_binding')
        bindings.append(stage_input(cfg, item.get('path') or _bound(cfg['input_root'], name), name, item['sha256']))
    if names != {x['input_name'] for x in bindings}:
        raise ValueError('graph_input_bindings_mismatch')
    for node in graph.values():
        if node['class_type'] == 'ImageCrop':
            crop = node['inputs']
            link = crop['image']
            if not isinstance(link,list) or len(link)!=2 or graph[link[0]]['class_type']!='LoadImage':
                raise ValueError('crop_requires_bound_native_input')
            source = _bound(cfg['input_root'],graph[link[0]]['inputs']['image'])
            with Image.open(source) as image:
                if (crop['x'] < 0 or crop['y'] < 0 or crop['width'] < 1 or crop['height'] < 1
                        or crop['x']+crop['width']>image.width or crop['y']+crop['height']>image.height):
                    raise ValueError('roi_outside_bound_source')
    protected = None
    if cfg['protected_pause_path']:
        pause = Path(cfg['protected_pause_path'])
        if not pause.is_file():
            raise JobIntegrityError('protected_pause_missing')
        protected = dict(path=str(pause), sha256=file_sha(pause))
    plan = dict(version=VERSION, job_id=jid, config=cfg, graph_sha256=digest(graph),render_text=False,
                inputs=sorted(bindings, key=lambda x:x['input_name']), protected_pause=protected)
    job.mkdir(parents=True, exist_ok=True)
    with run_lock(job):
        _freeze(job/'workflow_api.json', graph)
        _freeze(job/'PLAN.json', plan)
        if not (job/'STATE.json').exists():
            _write(job/'STATE.json', dict(status='prepared', job_id=jid, prompt_id=None,plan_sha256=digest(plan)))
    return status(job)


def _load(job_dir):
    job = Path(job_dir).resolve()
    plan = _read(job/'PLAN.json')
    graph = _read(job/'workflow_api.json')
    if plan.get('version') != VERSION or digest(graph) != plan['graph_sha256']:
        raise JobIntegrityError('frozen_graph_or_plan_changed')
    if _read(job/'STATE.json').get('plan_sha256') != digest(plan):
        raise JobIntegrityError('frozen_plan_changed')
    config = Config(**plan['config']).normalized()
    _validate_graph(graph, config['allowed_prefix'] + '/' + _slug(plan['job_id']))
    return job, plan, graph


def _inputs_ok(plan):
    for item in plan['inputs']:
        target = _bound(plan['config']['input_root'], item['input_name'])
        if str(target) != item['staged_path']:
            raise JobIntegrityError('staged_input_path_changed')
        for path in (Path(item['path']), target):
            if not path.is_file() or file_sha(path) != item['sha256']:
                raise JobIntegrityError('bound_input_changed')


def _state(job, plan):
    value = _read(job/'STATE.json')
    if value.get('job_id') != plan['job_id']:
        raise JobIntegrityError('job_state_identity_changed')
    if value.get('status')=='saved' and not (job/'RESULT.json').is_file():
        raise JobIntegrityError('saved_result_receipt_missing')
    response = _read(job/'RESPONSE.json') if (job/'RESPONSE.json').exists() else {}
    response = response if isinstance(response,dict) else {}
    if value.get('prompt_id') and not response.get('prompt_id'):
        raise JobIntegrityError('native_response_receipt_missing')
    if response.get('prompt_id'):
        if value.get('prompt_id') and value['prompt_id'] != response['prompt_id']:
            raise JobIntegrityError('native_prompt_identity_changed')
        if not (job/'CLAIM.json').is_file() or not (job/'REQUEST.json').is_file():
            raise JobIntegrityError('native_submission_proof_missing')
        claim = _read(job/'CLAIM.json')
        request = _read(job/'REQUEST.json')
        if (claim.get('graph_sha256') != plan['graph_sha256'] or claim.get('input_sha256') != digest(plan['inputs'])
                or digest(request.get('prompt')) != plan['graph_sha256']):
            raise JobIntegrityError('native_submission_proof_changed')
        value['prompt_id'] = response['prompt_id']
        if value['status']=='prepared':
            value['status']='submitted'
            value['receipt_recovered']=True
    value['paused'] = (job/'PAUSE.json').exists()
    return value


def status(job_dir):
    job, plan, _ = _load(job_dir)
    value = _state(job, plan)
    if (job/'CLAIM.json').exists() and not value.get('prompt_id') and value['status'] not in ('rejected',):
        value['status'] = 'outcome_unknown'
    return value


def set_paused(job_dir, paused=True):
    job, plan, _ = _load(job_dir)
    with run_lock(job):
        if paused:
            _freeze(job/'PAUSE.json', dict(job_id=plan['job_id'], graph_sha256=plan['graph_sha256'], source=VERSION))
        elif (job/'PAUSE.json').exists():
            marker = _read(job/'PAUSE.json')
            if marker != dict(job_id=plan['job_id'], graph_sha256=plan['graph_sha256'], source=VERSION):
                raise JobIntegrityError('foreign_pause_marker')
            (job/'PAUSE.json').unlink()
    return status(job)


def cancel_before_submit(job_dir):
    job, plan, _ = _load(job_dir)
    with run_lock(job):
        current = _state(job, plan)
        if current.get('prompt_id') or (job/'CLAIM.json').exists() or current['status'] not in ('prepared','cancelled'):
            raise ValueError('cannot_cancel_inflight_or_unknown_as_unsubmitted')
        current['status'] = 'cancelled'
        _write(job/'STATE.json', current)
    return status(job)


def _http(config, path, value=None):
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(config['service_url'] + path,
            data=None if value is None else json.dumps(value).encode(),
            headers={'Content-Type':'application/json'})
    with client.open(request, timeout=config['timeout']) as response:
        return json.load(response)


def _queue(config):
    queue = _http(config, '/queue')
    if not isinstance(queue, dict) or any(not isinstance(queue.get(k), list) for k in ('queue_running','queue_pending')):
        raise JobIntegrityError('invalid_queue_response')
    if any(not isinstance(r,list) or len(r)<3 or not isinstance(r[1],str) or not isinstance(r[2],dict)
           for r in queue['queue_running']+queue['queue_pending']):
        raise JobIntegrityError('invalid_queue_row')
    return queue


def _service_paths(config):
    if not config['verify_service_paths']:
        return
    argv = _http(config, '/system_stats')['system']['argv']
    try:
        paths = {name:Path(argv[argv.index(flag)+1]).resolve()
                 for name,flag in [('input_root','--input-directory'),('output_root','--output-directory')]}
    except (ValueError,IndexError,KeyError,TypeError):
        raise JobIntegrityError('service_paths_unconfirmed') from None
    if any(paths[name] != Path(config[name]) for name in paths):
        raise JobIntegrityError('wrong_local_service_paths')


def submit(job_dir):
    job, plan, graph = _load(job_dir)
    config = plan['config']
    with run_lock(job), run_lock(Path(config['input_root']), 'VISUAL_GPU.lock'):
        state = _state(job, plan)
        if state.get('prompt_id') or state['status'] in ('rejected','cancelled','saved','failed','interrupted'):
            return status(job)
        if (job/'CLAIM.json').exists():
            state.update(status='outcome_unknown', reason='claim_without_known_native_id')
            _write(job/'STATE.json', state)
            return status(job)
        if state['paused']:
            return dict(state, dispatch='paused_before_submit')
        _inputs_ok(plan)
        protected = plan['protected_pause']
        if protected and (not Path(protected['path']).is_file() or file_sha(protected['path']) != protected['sha256']):
            raise JobIntegrityError('protected_pause_changed')
        _service_paths(config)
        queue = _queue(config)
        if queue['queue_running'] or queue['queue_pending']:
            return dict(state, dispatch='waiting_gpu_queue')
        request = dict(prompt=graph, client_id=str(uuid.uuid4()))
        _freeze(job/'REQUEST.json', request)
        _freeze(job/'CLAIM.json', dict(at=time.time(), graph_sha256=plan['graph_sha256'], input_sha256=digest(plan['inputs'])))
        try:
            response = _http(config, '/prompt', request)
        except urllib.error.HTTPError as error:
            body = error.read().decode('utf-8', errors='replace')[:16000]
            _freeze(job/'SUBMISSION_ERROR.json', dict(type='HTTPError', code=error.code, response=body))
            state.update(status='rejected' if error.code in (400,422) else 'outcome_unknown', reason='native_http_'+str(error.code))
        except Exception as error:
            _freeze(job/'SUBMISSION_ERROR.json', dict(type=type(error).__name__, message=str(error)))
            state.update(status='outcome_unknown', reason='post_result_not_observed')
        else:
            _freeze(job/'RESPONSE.json', response)
            if not isinstance(response,dict) or not isinstance(response.get('prompt_id'),str) or not response['prompt_id']:
                state.update(status='outcome_unknown', reason='native_response_missing_id')
            else:
                _slug(response['prompt_id'])
                state.update(status='submitted', prompt_id=response['prompt_id'], submitted_at=time.time())
        _write(job/'STATE.json', state)
        return status(job)


def poll(job_dir):
    job, plan, graph = _load(job_dir)
    with run_lock(job):
        state = _state(job, plan)
        if not state.get('prompt_id') or state['status'] in ('saved','rejected','cancelled','failed','interrupted'):
            return status(job)
        native_id = _slug(state['prompt_id'])
        history = _http(plan['config'], '/history/' + native_id)
        if not isinstance(history,dict):
            raise JobIntegrityError('invalid_history_response')
        entry = history.get(native_id)
        if entry:
            prompt = entry.get('prompt')
            if not isinstance(prompt,list) or len(prompt)<3 or prompt[2] != graph:
                raise JobIntegrityError('native_history_graph_mismatch')
            _write(job/'HISTORY.json', history)
            events = [x[0] for x in entry.get('status',{}).get('messages',[]) if isinstance(x,list) and x]
            terminal = entry.get('status',{})
            if terminal.get('status_str')=='error':
                state.update(status='interrupted' if 'execution_interrupted' in events else 'failed', native_terminal=terminal)
            elif terminal.get('completed') is True:
                state.update(status='native_complete')
            else:
                state.update(status='running')
        else:
            queue = _queue(plan['config'])
            matches = [r for r in queue['queue_running']+queue['queue_pending'] if len(r)>2 and r[1]==native_id]
            if any(r[2] != graph for r in matches):
                raise JobIntegrityError('native_queue_graph_mismatch')
            state.update(status='running' if matches else 'outcome_unknown',
                         reason=None if matches else 'native_id_absent_from_history_and_queue')
        _write(job/'STATE.json', state)
        return status(job)


def collect(job_dir):
    job, plan, graph = _load(job_dir)
    with run_lock(job):
        state = _state(job, plan)
        if (job/'RESULT.json').exists():
            result = _read(job/'RESULT.json')
            if (result['prompt_id'] != state.get('prompt_id') or result.get('job_id') != plan['job_id']
                    or result.get('graph_sha256') != plan['graph_sha256'] or result.get('inputs_sha256') != digest(plan['inputs'])
                    or result.get('production_approved') is not False):
                raise JobIntegrityError('saved_result_identity_changed')
            for image in result['images']:
                if not Path(image['path']).resolve().is_relative_to(job/'artifacts'):
                    raise JobIntegrityError('saved_output_path_outside_job')
                if file_sha(image['path']) != image['sha256']:
                    raise JobIntegrityError('saved_output_changed')
            return result
        if state['status'] != 'native_complete':
            raise ValueError('poll_native_completion_before_collect')
        _inputs_ok(plan)
        native_id = state['prompt_id']
        entry = _read(job/'HISTORY.json')[native_id]
        if (entry['prompt'][2] != graph or not entry['status'].get('completed')
                or entry['status'].get('status_str') != 'success'):
            raise JobIntegrityError('invalid_native_completion')
        outputs = []
        seen = set()
        config = plan['config']
        scope = Path(config['output_root']) / config['allowed_prefix'] / plan['job_id']
        for nid, node in graph.items():
            if node['class_type'] != 'SaveImage':
                continue
            images = entry.get('outputs',{}).get(nid,{}).get('images',[])
            if not images:
                raise JobIntegrityError('expected_save_node_has_no_images')
            expected_name = PurePosixPath(node['inputs']['filename_prefix']).name + '_'
            for image in images:
                if image.get('type') != 'output':
                    raise JobIntegrityError('native_image_not_output')
                filename = image['filename']
                if not isinstance(filename,str) or '/' in filename or '\\' in filename:
                    raise JobIntegrityError('native_filename_is_not_basename')
                # Comfy on Windows returns os.path.relpath subfolders with backslashes.
                subfolder = image.get('subfolder','').replace('\\','/')
                relative = subfolder + '/' + filename if subfolder else filename
                source = _bound(config['output_root'], relative)
                if not source.is_relative_to(scope) or not source.name.startswith(expected_name) or source in seen:
                    raise JobIntegrityError('native_output_scope_or_identity_mismatch')
                seen.add(source)
                with Image.open(source) as im:
                    im.verify()
                target_dir = job/'artifacts'/nid
                target_dir.mkdir(parents=True,exist_ok=True)
                target = target_dir/source.name
                source_sha = file_sha(source)
                if target.exists():
                    if file_sha(target) != source_sha:
                        raise JobIntegrityError('local_output_already_differs')
                else:
                    _copy_new(source,target)
                with Image.open(target) as im:
                    dimensions = list(im.size)
                outputs.append(dict(path=str(target),source_path=str(source),sha256=file_sha(target),
                                    save_node=nid,dimensions=dimensions))
        result = dict(version=VERSION,job_id=plan['job_id'],prompt_id=native_id,graph_sha256=plan['graph_sha256'],
                      inputs_sha256=digest(plan['inputs']),images=outputs,technical_status='saved',
                      content_status='candidate_pending_visual_review',production_approved=False,local_only=True,render_text=False)
        _freeze(job/'RESULT.json',result)
        state['status']='saved'
        _write(job/'STATE.json',state)
        return result
