"""Reviewed per-shot assets -> native reference H3, without a motion rewrite.

Preparation is CPU-only. Existing first-frame plans and running comparisons are
never migrated. Only submit_next can POST, and an uncertain POST is not replayed.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import uuid

from PIL import Image

from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs
from . import visual_asset_pipeline_v3 as assets
from . import visual_h3_reference_bundle_v20 as references
from .visual_shot_binding_v3 import fingerprint

SCHEMA = 'visual_h3_reference_delivery/v20'
PREFIX = 'visual_h3_ref_v20'
INPUT_MODE = 'reference_assets/v20'
PROJECT = Path(__file__).resolve().parents[2]
RUNS = PROJECT / 'data/video_generation' / PREFIX
ROLES = ('video', 'audio', 'first', 'last')


class ReferenceDeliveryError(ValueError):
    pass


def policy_options(value):
    if (not isinstance(value, dict) or set(value)-{'mode','video_enabled','width','height'}
            or value.get('mode') not in (INPUT_MODE,'first_frame/v3')
            or type(value.get('video_enabled')) is not bool):
        raise ReferenceDeliveryError('explicit_h3_delivery_policy_required')
    if ('width' in value)!=('height' in value):
        raise ReferenceDeliveryError('reference_output_size_pair_required')
    if any(type(value[k]) is not int or not 64<=value[k]<=2048 or value[k]%32
           for k in ('width','height') if k in value):
        raise ReferenceDeliveryError('reference_dimensions_require_multiples_of_32')
    return {k:v for k,v in value.items() if k!='mode'}


def _config(asset_plan, supplied=None):
    cfg = deepcopy(supplied or {})
    allowed = {'service_url', 'input_root', 'output_root', 'gpu_lock_root',
               'protected_pause_path', 'base_workflow', 'runs_root',
               'video_enabled', 'width', 'height', 'timeout'}
    if set(cfg) - allowed:
        raise ReferenceDeliveryError('unsupported_reference_delivery_config')
    # Share the established service/path/lock validation, then select our own
    # separate namespace. No legacy run is passed to the legacy executor.
    root = Path(cfg.pop('runs_root', RUNS)).resolve()
    checked = native._config(asset_plan, dict(cfg, runs_root=str(native.DEFAULT_RUNS)))
    if root.name != PREFIX:
        raise ReferenceDeliveryError('new_reference_h3_namespace_required')
    checked['runs_root'] = str(root)
    checked.setdefault('width', 736)
    checked.setdefault('height', 1312)
    if any(type(checked[k]) is not int or not 64 <= checked[k] <= 2048
           or checked[k] % 32 for k in ('width', 'height')):
        raise ReferenceDeliveryError('reference_dimensions_require_multiples_of_32')
    return checked


def _scope(run, cfg):
    run = Path(run).resolve()
    if run.parent != Path(cfg['runs_root']) or 'recovery' in run.name.lower():
        raise ReferenceDeliveryError('new_reference_h3_run_scope_required')
    native.slug(run.name)
    return run


def _adapter():
    from . import visual_h3_reference_passthrough_v20
    return visual_h3_reference_passthrough_v20


def _prompt(shot, explicit):
    if explicit is None:
        return _adapter().prompt_from_shot(shot), None
    p = Path(explicit).resolve()
    # read_bytes avoids universal newline conversion of the original text.
    text = p.read_bytes().decode('utf-8')
    if not text.strip():
        raise ReferenceDeliveryError('complete_source_prompt_required')
    if any(a['text'] not in text for a in _adapter().audio_records_from_shot(shot)):
        raise ReferenceDeliveryError('explicit_source_prompt_missing_original_audio')
    return text, dict(path=str(p), sha256=native.file_sha(p))


def prepare(asset_run, run, config=None, *, shot_id=None, source_prompts=None):
    """Freeze original source and reviewed references; no service request/POST."""
    asset_run = Path(asset_run).resolve()
    snapshot = assets.status(asset_run)
    cfg = _config(snapshot['plan'], config)
    run = _scope(run, cfg)
    packet = snapshot['plan']['packet']
    shots = [s for s in packet['shots'] if shot_id is None or s['id'] == shot_id]
    if not shots or (shot_id is not None and len(shots) != 1):
        raise ReferenceDeliveryError('unique_existing_source_shot_required')
    source_prompts = source_prompts or {}
    if set(source_prompts) - {s['id'] for s in shots}:
        raise ReferenceDeliveryError('source_prompt_outside_selected_shots')
    base = native.read(cfg['base_workflow'])
    pause = dict(path=cfg['protected_pause_path'], sha256=native.file_sha(cfg['protected_pause_path']))
    plan = dict(schema=SCHEMA, asset_run=str(asset_run), asset_plan_sha256=native.file_sha(asset_run/'PLAN.json'),
                source=packet['source'], config=cfg, base_workflow_sha256=native.file_sha(cfg['base_workflow']),
                protected_pause=pause, shots=[], publication=False, production_approved=False,
                old_batch_resume=False, prompt_rewritten=False, model_called=False)
    documents = {}
    for shot in shots:
        sid = native.slug(shot['id'])
        bundle = references.collect(asset_run, sid)
        text, text_binding = _prompt(shot, source_prompts.get(sid))
        timing = native._timing(shot)
        scope = PREFIX+'/'+run.name+'/'+sid
        mapping = {r['reference_id']: scope+'/references/'+str(i)+Path(r['image']['path']).suffix.lower()
                   for i, r in enumerate(bundle['references'])}
        seed = int(fingerprint(dict(shot=shot, bundle=bundle['bundle_sha256']))[:14], 16)
        built = _adapter().build_graph(base, bundle, text, mapping, scope,
                                      cfg['width'], cfg['height'], timing['native_frames'], seed)
        graph = built['graph']
        row = dict(id=sid, scope=scope, timing=timing, source_shot_sha256=fingerprint(shot),
                   source_prompt_file=text_binding, source_prompt_sha256=built['source_prompt_sha256'],
                   bundle_sha256=bundle['bundle_sha256'], input_mapping=mapping,
                   graph_sha256=fingerprint(graph), compiled_prompt_sha256=fingerprint(built['compiled_prompt']))
        plan['shots'].append(row)
        documents[sid] = dict(bundle=bundle, source_text=text, built=built)
    run.mkdir(parents=True, exist_ok=True)
    with jobs.run_lock(run):
        if (run/'PLAN.json').exists() and native.read(run/'PLAN.json') != plan:
            raise ReferenceDeliveryError('frozen_reference_plan_changed_use_new_run')
        for row in plan['shots']:
            folder = run/'shots'/row['id']
            folder.mkdir(parents=True, exist_ok=True)
            doc = documents[row['id']]
            for name, value in [('REFERENCE_BUNDLE.json', doc['bundle']),
                                ('PROMPT_BINDING.json', doc['built']),
                                ('workflow_api.json', doc['built']['graph'])]:
                native.freeze(folder/name, value)
            text_path = folder/'SOURCE_PROMPT.txt'
            data = doc['source_text'].encode('utf-8')
            if text_path.exists() and text_path.read_bytes() != data:
                raise ReferenceDeliveryError('frozen_source_prompt_changed')
            if not text_path.exists():
                with text_path.open('xb') as stream:
                    stream.write(data)
            if not (folder/'STATE.json').exists():
                native.write(folder/'STATE.json', dict(id=row['id'], status='prepared', prompt_id=None,
                                                     plan_sha256=fingerprint(plan)))
        native.freeze(run/'PLAN.json', plan)
    return status(run)


def prepare_reused(manifest_path, segment_id, run, config=None):
    """Explicit new-shot contract; donor PLAN/source/policy stay unchanged."""
    from . import visual_h3_reference_reuse_v21 as reuse
    bundle = reuse.collect(manifest_path, segment_id)
    run = Path(run).resolve()
    if str(run) != bundle['expected_delivery_run']:
        raise ReferenceDeliveryError('reused_segment_delivery_scope_changed')
    asset_run = Path(bundle['asset_run'])
    snapshot = assets.status(asset_run)
    cfg = _config(snapshot['plan'], config)
    run = _scope(run, cfg)
    shot = bundle['original_source_shot']
    sid = native.slug(segment_id)
    text = Path(bundle['source_prompt_file']['path']).read_bytes().decode('utf-8')
    timing = native._timing(shot)
    if (cfg['width'], cfg['height'], timing['native_frames']) != (736, 1312, 362):
        raise ReferenceDeliveryError('reused_minute_native_profile_changed')
    scope = PREFIX+'/'+run.name+'/'+sid
    mapping = {r['reference_id']: scope+'/references/'+str(i)+Path(r['image']['path']).suffix.lower()
               for i, r in enumerate(bundle['references'])}
    seed = int(fingerprint(dict(shot=shot, bundle=bundle['bundle_sha256']))[:14], 16)
    built = _adapter().build_graph(native.read(cfg['base_workflow']), bundle, text, mapping, scope,
                                   cfg['width'], cfg['height'], timing['native_frames'], seed)
    row = dict(id=sid, scope=scope, timing=timing, source_shot=deepcopy(shot),
               source_shot_sha256=fingerprint(shot), source_prompt_file=bundle['source_prompt_file'],
               source_request=bundle['source_request'],
               original_prompt_utf8_sha256=bundle['original_prompt_utf8_sha256'],
               source_prompt_sha256=built['source_prompt_sha256'],
               prompt_adaptation_audit=bundle['prompt_adaptation_audit'], prompt_approval=bundle['prompt_approval'],
               bundle_sha256=bundle['bundle_sha256'], input_mapping=mapping,
               graph_sha256=fingerprint(built['graph']), compiled_prompt_sha256=fingerprint(built['compiled_prompt']))
    plan = dict(schema=SCHEMA, reuse_contract=reuse.CONTRACT, reuse_manifest=bundle['reuse_manifest'],
                asset_run=str(asset_run), asset_plan_sha256=native.file_sha(asset_run/'PLAN.json'),
                source=bundle['source'], config=cfg, base_workflow_sha256=native.file_sha(cfg['base_workflow']),
                protected_pause=dict(path=cfg['protected_pause_path'], sha256=native.file_sha(cfg['protected_pause_path'])),
                shots=[row], publication=False, production_approved=False, old_batch_resume=False,
                prompt_rewritten=False, model_called=False)
    run.mkdir(parents=True, exist_ok=True)
    with jobs.run_lock(run):
        if (run/'PLAN.json').exists() and native.read(run/'PLAN.json') != plan:
            raise ReferenceDeliveryError('frozen_reference_plan_changed_use_new_run')
        folder = run/'shots'/sid; folder.mkdir(parents=True, exist_ok=True)
        for name, value in [('REFERENCE_BUNDLE.json', bundle), ('PROMPT_BINDING.json', built), ('workflow_api.json', built['graph'])]:
            native.freeze(folder/name, value)
        path = folder/'SOURCE_PROMPT.txt'; encoded = text.encode('utf-8')
        if path.exists() and path.read_bytes() != encoded:
            raise ReferenceDeliveryError('frozen_source_prompt_changed')
        if not path.exists():
            with path.open('xb') as stream:stream.write(encoded)
        if not (folder/'STATE.json').exists():
            native.write(folder/'STATE.json', dict(id=sid,status='prepared',prompt_id=None,plan_sha256=fingerprint(plan)))
        native.freeze(run/'PLAN.json', plan)
    return status(run)


def _load(run, current=True):
    run = Path(run).resolve()
    plan = native.read(run/'PLAN.json')
    if (plan.get('schema') != SCHEMA or plan.get('publication') is not False
            or plan.get('production_approved') is not False or plan.get('old_batch_resume') is not False):
        raise ReferenceDeliveryError('not_new_reference_h3_plan')
    cfg = _config(dict(config=dict(image_service=plan['config'],
                                  gpu_lock_root=plan['config']['gpu_lock_root'],
                                  protected_pause_path=plan['config']['protected_pause_path'])), plan['config'])
    _scope(run, cfg)
    if not plan['shots'] or len({r['id'] for r in plan['shots']}) != len(plan['shots']):
        raise ReferenceDeliveryError('invalid_reference_shot_coverage')
    for row in plan['shots']:
        folder = run/'shots'/native.slug(row['id'])
        graph = native.read(folder/'workflow_api.json')
        bundle = native.read(folder/'REFERENCE_BUNDLE.json')
        state = native.read(folder/'STATE.json')
        binding = native.read(folder/'PROMPT_BINDING.json')
        if (state.get('plan_sha256') != fingerprint(plan) or state.get('id') != row['id']
                or fingerprint(graph) != row['graph_sha256'] or binding.get('graph') != graph
                or bundle.get('bundle_sha256') != row['bundle_sha256']
                or fingerprint(binding.get('compiled_prompt')) != row['compiled_prompt_sha256']
                or binding.get('source_prompt_sha256') != row['source_prompt_sha256']):
            raise ReferenceDeliveryError('frozen_reference_inputs_changed')
        if plan.get('reuse_contract') is not None:
            from . import visual_h3_reference_reuse_v21 as reuse
            if (plan['reuse_contract'] != reuse.CONTRACT or bundle.get('reuse_contract') != reuse.CONTRACT
                    or plan.get('reuse_manifest') != bundle.get('reuse_manifest')
                    or row.get('source_shot') != bundle.get('original_source_shot')
                    or fingerprint(row.get('source_shot')) != row.get('source_shot_sha256')
                    or row.get('id') != bundle.get('reuse_segment_id')
                    or row.get('source_request') != bundle.get('source_request')
                    or row.get('source_prompt_file') != bundle.get('source_prompt_file')
                    or row.get('prompt_adaptation_audit') != bundle.get('prompt_adaptation_audit')
                    or row.get('prompt_approval') != bundle.get('prompt_approval')
                    or bundle.get('expected_delivery_run') != str(run)):
                raise ReferenceDeliveryError('new_reused_source_shot_binding_changed')
        source_text = (folder/'SOURCE_PROMPT.txt').read_bytes().decode('utf-8')
        if hashlib.sha256(source_text.encode('utf-8')).hexdigest() != row['source_prompt_sha256']:
            raise ReferenceDeliveryError('frozen_source_text_changed')
        if current:
            references.validate(bundle)
            explicit = row['source_prompt_file']
            if explicit and native.file_sha(explicit['path']) != explicit['sha256']:
                raise ReferenceDeliveryError('source_prompt_file_changed')
            built = _adapter().build_graph(native.read(cfg['base_workflow']), bundle, source_text,
                                           row['input_mapping'], row['scope'], cfg['width'], cfg['height'],
                                           row['timing']['native_frames'], graph['129']['inputs']['noise_seed'])
            if built != binding:
                raise ReferenceDeliveryError('reference_graph_or_compilation_changed')
    if current and (native.file_sha(Path(plan['asset_run'])/'PLAN.json') != plan['asset_plan_sha256']
                    or native.file_sha(cfg['base_workflow']) != plan['base_workflow_sha256']):
        raise ReferenceDeliveryError('reference_upstream_plan_changed')
    return run, plan


def _state(folder, plan, row):
    state = native.read(folder/'STATE.json')
    claimed=(folder/'CLAIM.json').exists()
    if claimed:
        claim=native.read(folder/'CLAIM.json')
        request=native.read(folder/'REQUEST.json')
        if (claim.get('graph_sha256')!=row['graph_sha256']
                or claim.get('bundle_sha256')!=row['bundle_sha256']
                or fingerprint(request.get('prompt'))!=row['graph_sha256']):
            raise ReferenceDeliveryError('reference_submission_claim_changed')
    elif (folder/'RESPONSE.json').exists() or state.get('prompt_id'):
        raise ReferenceDeliveryError('reference_native_response_without_original_claim')
    response = native.read(folder/'RESPONSE.json') if (folder/'RESPONSE.json').exists() else {}
    if not isinstance(response,dict):response={}
    pid = response.get('prompt_id')
    if pid is not None:
        if not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pid):
            raise ReferenceDeliveryError('unsafe_reference_native_id')
        if state.get('prompt_id') not in (None, pid):
            raise ReferenceDeliveryError('reference_native_id_changed')
        state['prompt_id'] = pid
        if state['status'] == 'prepared':
            state['status'] = 'submitted'
    elif (folder/'CLAIM.json').exists() and state['status'] == 'prepared':
        state.update(status='outcome_unknown', reason='post_claim_without_known_response')
    if state['status']=='technical_saved':
        saved=native.read(folder/'RESULT.json')
        if (saved.get('schema')!=SCHEMA or saved.get('prompt_id')!=state.get('prompt_id')
                or saved.get('graph_sha256')!=row['graph_sha256']
                or saved.get('reference_bundle_sha256')!=row['bundle_sha256']
                or saved.get('source_prompt_sha256')!=row['source_prompt_sha256']
                or saved.get('technical_status')!='technical_saved'
                or saved.get('production_approved') is not False or saved.get('publication') is not False
                or set(saved.get('files',{}))!=set(ROLES)
                or state.get('result_sha256')!=native.file_sha(folder/'RESULT.json')):
            raise ReferenceDeliveryError('saved_reference_result_binding_changed')
        history=native.read(folder/'HISTORY.json').get(state['prompt_id'],{})
        terminal=history.get('status',{});prompt=history.get('prompt')
        if (terminal.get('completed') is not True or terminal.get('status_str')!='success'
                or not isinstance(prompt,list) or len(prompt)<3 or prompt[1]!=state['prompt_id']
                or native.native_graph_equivalence(native.read(folder/'workflow_api.json'),prompt[2]) is None):
            raise ReferenceDeliveryError('saved_reference_native_history_changed')
        for item in saved['files'].values():
            path=Path(item['path']).resolve()
            if not path.is_relative_to(folder/'artifacts') or native.file_sha(path)!=item['sha256']:
                raise ReferenceDeliveryError('saved_reference_output_changed')
    return state


def status(run):
    run, plan = _load(run, current=False)
    rows = [_state(run/'shots'/row['id'], plan, row) for row in plan['shots']]
    pids=[r['prompt_id'] for r in rows if r.get('prompt_id')]
    if len(set(pids))!=len(pids):raise ReferenceDeliveryError('distinct_native_id_required_each_shot')
    return dict(schema=SCHEMA, run=str(run), paused=(run/'PAUSE.json').exists(), shots=rows,
                technical_saved=sum(r['status'] == 'technical_saved' for r in rows), total=len(rows),
                video_enabled=plan['config']['video_enabled'], production_approved=False, publication=False)


def set_paused(run, paused=True, *, actor='operator'):
    run, _ = _load(run, current=False)
    if type(paused) is not bool or not actor:
        raise ReferenceDeliveryError('explicit_reference_pause_action_required')
    with jobs.run_lock(run):
        event = dict(actor=actor, paused=paused, at=time.time())
        (run/'CONTROL').mkdir(exist_ok=True)
        native.freeze(run/'CONTROL'/(uuid.uuid4().hex+'.json'), event)
        if paused:
            native.write(run/'PAUSE.json', event)
        else:
            (run/'PAUSE.json').unlink(missing_ok=True)
    return status(run)


def submit_next(run):
    run, plan = _load(run)
    cfg = plan['config']
    with jobs.run_lock(run):
        result = status(run)
        if result['paused'] or not cfg['video_enabled']:
            return dict(result, dispatch='paused' if result['paused'] else 'video_policy_disabled')
        row = next((r for r, s in zip(plan['shots'], result['shots']) if s['status'] != 'technical_saved'), None)
        if row is None:
            return result
        folder = run/'shots'/row['id']
        state = _state(folder, plan, row)
        if state['status'] != 'prepared':
            return result
        asset_plan = native.read(Path(plan['asset_run'])/'PLAN.json')
        with native._gpu(plan), assets.library._lock(Path(asset_plan['config']['library'])):
            _load(run)
            if (run/'PAUSE.json').exists():
                return dict(result, dispatch='paused')
            native._service_paths(cfg)
            queue = native._queue(cfg)
            if queue['queue_running'] or queue['queue_pending']:
                return dict(result, dispatch='waiting_gpu_queue')
            capability=native._http(cfg,'/object_info/'+_adapter().NODE)
            if (not isinstance(capability,dict) or _adapter().NODE not in capability
                    or not isinstance(capability[_adapter().NODE].get('input'),dict)):
                raise ReferenceDeliveryError('native_reference_node_capability_unconfirmed')
            native.freeze(folder/'CAPABILITY.json',capability)
            bundle = native.read(folder/'REFERENCE_BUNDLE.json')
            for ref in bundle['references']:
                jobs.stage_input({k: cfg[k] for k in ('service_url', 'input_root', 'output_root', 'timeout')},
                                 ref['image']['path'], row['input_mapping'][ref['reference_id']], ref['image']['sha256'])
            request = (native.read(folder/'REQUEST.json') if (folder/'REQUEST.json').exists() else
                       dict(prompt=native.read(folder/'workflow_api.json'), client_id=uuid.uuid4().hex))
            if fingerprint(request.get('prompt'))!=row['graph_sha256']:
                raise ReferenceDeliveryError('reference_prepost_request_changed')
            native.freeze(folder/'REQUEST.json', request)
            native.freeze(folder/'CLAIM.json', dict(at=time.time(), graph_sha256=row['graph_sha256'],
                                                   bundle_sha256=row['bundle_sha256']))
            try:
                response = native._http(cfg, '/prompt', request)
            except urllib.error.HTTPError as error:
                native.freeze(folder/'SUBMISSION_ERROR.json', dict(type='HTTPError', code=error.code))
                state.update(status='rejected' if error.code in (400, 422) else 'outcome_unknown',
                             reason='native_http_'+str(error.code))
            except Exception as error:
                native.freeze(folder/'SUBMISSION_ERROR.json', dict(type=type(error).__name__))
                state.update(status='outcome_unknown', reason='post_result_not_observed')
            else:
                native.freeze(folder/'RESPONSE.json', response)
                pid = response.get('prompt_id') if isinstance(response, dict) else None
                if isinstance(pid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pid):
                    state.update(status='submitted', prompt_id=pid, submitted_at=time.time())
                else:
                    state.update(status='outcome_unknown', reason='native_response_missing_id')
            native.write(folder/'STATE.json', state)
    return status(run)


def _collect(folder, plan, row, state, entry):
    cfg = plan['config']
    files = {}
    scope = (Path(cfg['output_root'])/row['scope']).resolve()
    for role, key, suffix in [('video', 'images', '.mp4'), ('audio', 'audio', '.flac'),
                              ('first', 'images', '.png'), ('last', 'images', '.png')]:
        records = entry.get('outputs', {}).get('save_'+role, {}).get(key)
        if not isinstance(records, list) or len(records) != 1 or records[0].get('type') != 'output':
            raise ReferenceDeliveryError('missing_original_reference_h3_output')
        record = records[0]
        name = record.get('filename')
        if (not isinstance(name, str) or '/' in name or '\\' in name or not name.startswith(role+'_')
                or Path(name).suffix.lower() != suffix):
            raise ReferenceDeliveryError('reference_native_filename_changed')
        sub = record.get('subfolder', '').replace('\\', '/')
        source = native.bound(cfg['output_root'], sub+'/'+name if sub else name)
        if source.parent != scope or not source.is_file() or not source.stat().st_size:
            raise ReferenceDeliveryError('reference_native_output_scope_changed')
        dest = folder/'artifacts'/name
        dest.parent.mkdir(exist_ok=True)
        digest = native.file_sha(source)
        if dest.exists() and native.file_sha(dest) != digest:
            raise ReferenceDeliveryError('reference_local_output_changed')
        if not dest.exists():
            jobs._copy_new(source, dest)
        if native.file_sha(dest) != digest:
            raise ReferenceDeliveryError('reference_copy_integrity_failed')
        files[role] = dict(path=str(dest), source_path=str(source), sha256=digest)
    meta = native._metadata(files['video']['path'])
    video = next((s for s in meta['streams'] if s.get('codec_type') == 'video'), {})
    audio = next((s for s in meta['streams'] if s.get('codec_type') == 'audio'), None)
    if (not audio or video.get('width') != cfg['width'] or video.get('height') != cfg['height']
            or int(video.get('nb_frames', -1)) != row['timing']['native_frames']
            or video.get('r_frame_rate') != '24/1'):
        raise ReferenceDeliveryError('reference_native_av_metadata_mismatch')
    if not any(s.get('codec_type') == 'audio' for s in native._metadata(files['audio']['path'])['streams']):
        raise ReferenceDeliveryError('reference_standalone_audio_missing')
    for role in ('first', 'last'):
        with Image.open(files[role]['path']) as image:
            if image.size != (cfg['width'], cfg['height']):
                raise ReferenceDeliveryError('reference_native_frame_size_mismatch')
            image.verify()
    result = dict(schema=SCHEMA, shot_id=row['id'], prompt_id=state['prompt_id'],
                  graph_sha256=row['graph_sha256'], reference_bundle_sha256=row['bundle_sha256'],
                  source_prompt_sha256=row['source_prompt_sha256'], files=files, timing=row['timing'],
                  native_metadata=meta, technical_status='technical_saved', content_status='media_review_required',
                  production_approved=False, publication=False, old_batch_resume=False)
    native.freeze(folder/'RESULT.json', result)
    state['status'] = 'technical_saved'
    state['result_sha256']=native.file_sha(folder/'RESULT.json')


def poll_collect(run):
    run, plan = _load(run, current=False)
    cfg = plan['config']
    with jobs.run_lock(run):
        source_error = None
        try:
            _load(run)
        except (OSError, ValueError, KeyError) as error:
            source_error = dict(type=type(error).__name__, message=str(error))
        for row in plan['shots']:
            folder = run/'shots'/row['id']
            state = _state(folder, plan, row)
            if not state.get('prompt_id') or state['status'] in ('technical_saved', 'failed', 'interrupted', 'rejected'):
                continue
            pid = state['prompt_id']
            history = native._http(cfg, '/history/'+native.slug(pid))
            if not isinstance(history, dict):
                raise ReferenceDeliveryError('invalid_reference_h3_history')
            entry = history.get(pid)
            if entry:
                prompt = entry.get('prompt')
                terminal = entry.get('status')
                if (not isinstance(prompt, list) or len(prompt) < 3 or prompt[1] != pid
                        or not native._verify_native_graph(folder, row, prompt[2], pid)
                        or not isinstance(terminal, dict) or type(terminal.get('completed')) is not bool
                        or terminal.get('status_str') not in ('success', 'error')):
                    raise ReferenceDeliveryError('reference_native_history_identity_changed')
                native.write(folder/'HISTORY.latest.json', history)
                if terminal['status_str'] == 'error':
                    events = [e[0] for e in terminal.get('messages', []) if isinstance(e, list) and e]
                    state.update(status='interrupted' if 'execution_interrupted' in events else 'failed',
                                 native_terminal=terminal)
                elif terminal['completed']:
                    native.freeze(folder/'HISTORY.json', history)
                    _collect(folder, plan, row, state, entry)
                else:
                    state['status'] = 'running'
            else:
                q = native._queue(cfg)
                matches = [x for x in q['queue_running']+q['queue_pending'] if x[1] == pid]
                if any(not native._verify_native_graph(folder, row, x[2], pid) for x in matches):
                    raise ReferenceDeliveryError('reference_native_queue_graph_changed')
                state.update(status='running' if matches else 'outcome_unknown',
                             reason=None if matches else 'original_id_absent_history_and_queue')
            native.write(folder/'STATE.json', state)
        if source_error:
            native.write(run/'INPUT_INVALID.json', dict(at=time.time(), error=source_error))
            return dict(status(run), dispatch='blocked_upstream_changed', input_error=source_error)
    return status(run)


def execute(run, *, poll_seconds=30, max_seconds=86400):
    if not 1 <= poll_seconds <= 60 or not 0 < max_seconds <= 86400:
        raise ReferenceDeliveryError('bounded_reference_poll_window_required')
    run = Path(run).resolve()
    with jobs.run_lock(run, 'RUNNER.lock'):
        start = time.monotonic()
        while True:
            state = poll_collect(run)
            active=any(s.get('prompt_id') and s['status'] in ('submitted','running') for s in state['shots'])
            stopping=state.get('dispatch')=='blocked_upstream_changed' or state['paused']
            elapsed=time.monotonic()-start
            if stopping:
                # Pause/upstream invalidation stops new work, but the original
                # known job may still finish. Keep collecting that ID only.
                if active and elapsed<max_seconds:
                    time.sleep(poll_seconds);continue
                return state
            if (state['technical_saved'] == state['total'] or not state['video_enabled']
                    or any(s['status'] in ('outcome_unknown', 'failed', 'interrupted', 'rejected') for s in state['shots'])):
                return state
            state = submit_next(run)
            if time.monotonic()-start >= max_seconds:
                return dict(state, dispatch='bounded_wait_ended_original_ids_preserved')
            time.sleep(poll_seconds)
