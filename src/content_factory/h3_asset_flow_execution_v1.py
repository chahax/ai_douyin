"""One explicitly approved Ref2VA submission from an immutable offline draft.

No auto-submit loop, transport retry, service restart, or unknown replay exists.
The offline compiler is unchanged; the optional prompt-profile helper is an
explicit, recomputed derivation, and only the local execution namespace stages.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time
import urllib.error
import uuid

from PIL import Image

from . import h3_asset_flow_v2 as flow
from . import visual_h3_handoff_v3 as native

VERSION = 'h3_asset_flow_execution/v1'
LAUNCH = 'h3_asset_flow_execution_launch/v1'
PROJECT = Path(__file__).resolve().parents[2]
read, bind, digest = flow.read, flow.bind, flow.digest


def _freeze(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    native.freeze(path, value)


def _service_anchor(manifest):
    return read(flow.core.check(manifest['guide']['native_plan']))['config']


def _config(value, manifest, run):
    cfg = deepcopy(value)
    keys = {'service_url', 'input_root', 'output_root', 'gpu_lock_root', 'protected_pause_path',
            'runs_root', 'timeout', 'video_enabled'}
    if set(cfg) - keys or keys - {'timeout'} - set(cfg):
        raise ValueError('explicit_execution_config_required')
    if cfg['service_url'] != 'http://127.0.0.1:8190' or type(cfg['video_enabled']) is not bool:
        raise ValueError('only_explicit_8190_local_video_policy_allowed')
    cfg.setdefault('timeout', 60)
    if type(cfg['timeout']) not in (int, float) or not math.isfinite(cfg['timeout']) or not 0 < cfg['timeout'] <= 300:
        raise ValueError('bounded_execution_HTTP_timeout_required')
    for key in keys - {'service_url', 'timeout', 'video_enabled'}:
        cfg[key] = str(Path(cfg[key]).resolve())
    anchor = _service_anchor(manifest)
    for key in ('service_url', 'input_root', 'output_root', 'gpu_lock_root', 'protected_pause_path'):
        observed = anchor[key] if key == 'service_url' else str(Path(anchor[key]).resolve())
        if cfg[key] != observed:
            raise ValueError('execution_must_preserve_original_service_lock_and_pause_scope')
    if Path(cfg['runs_root']).name != 'visual_h3_v3' or not Path(run).resolve().is_relative_to(PROJECT):
        raise ValueError('new_project_native_namespace_required')
    native._target(run, cfg)
    if any(not Path(cfg[key]).is_dir() for key in ('input_root', 'output_root')):
        raise ValueError('actual_service_input_output_directories_required')
    if not Path(cfg['protected_pause_path']).is_file():
        raise ValueError('preserved_original_PAUSE_file_required')
    return cfg


def _derive(out, run, prompt_profiles):
    out = Path(out).resolve()
    if flow.validate(out)['status'] != 'offline_draft_verified':
        raise ValueError('verified_offline_draft_required')
    manifest = read(out / 'INPUT_MANIFEST.json'); graph = read(out / 'DRAFT_WORKFLOW.json')
    if (manifest['voice_resolution']['control_mode'] != 'prompt_only'
            or manifest['voice_resolution']['voices'] or any(n['class_type'] == 'LoadAudio' for n in graph.values())):
        raise ValueError('this_execution_version_requires_explicit_prompt_only_native_AV')
    if prompt_profiles is not None:
        flow.core.check(prompt_profiles)
        from . import h3_asset_prompt_profiles_v1 as helper
        origin_manifest, origin_graph = deepcopy(manifest), deepcopy(graph)
        derived = helper.apply(deepcopy(manifest), deepcopy(graph), prompt_profiles)
        manifest, graph = derived['manifest'], derived['graph']
        restored = deepcopy(graph); restored['condition']['inputs']['prompt'] = origin_graph['condition']['inputs']['prompt']
        allowed = {'compiled_prompt', 'compiled_prompt_utf8_sha256', 'graph_sha256', 'presentation'}
        if (restored != origin_graph or set(manifest) != set(origin_manifest) | {'presentation'}
                or any(manifest[key] != value for key, value in origin_manifest.items() if key not in allowed)):
            raise ValueError('prompt_helper_cannot_change_assets_state_or_nonprompt_graph')
    manifest, graph = deepcopy(manifest), deepcopy(graph)
    entry = flow._bound(manifest['source_case'])['shots'][0]; sid = native.slug(entry['shot_id'])
    scope = native.PREFIX + '/' + Path(run).name + '_' + flow.core.sha(str(Path(run).resolve()))[:12] + '/' + sid
    for i, ref in enumerate(manifest['references']):
        ref['input_name'] = scope + '/images/P' + str(i + 1) + '.png'
        graph['ref_' + str(i)]['inputs'] = dict(image=ref['input_name'])
    for role in ('video', 'audio', 'first', 'last'):
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    manifest.update(scope=scope, graph_sha256=digest(graph), compiled_prompt=graph['condition']['inputs']['prompt'],
                    compiled_prompt_utf8_sha256=flow.core.sha(graph['condition']['inputs']['prompt']))
    flow.validate_graph(graph, manifest['references'], manifest['voice_resolution'], scope)
    if any('audio' in key for key in graph['condition']['inputs']):
        raise ValueError('prompt_only_does_not_mean_audio_reference_ready')
    return manifest, graph, entry, scope


def _snapshot(path):
    path = Path(path).resolve(); before = path.stat()
    file = bind(path)
    with Image.open(path) as image:
        mode = image.mode; size = list(image.size); rgb = hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
    after = path.stat()
    if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size or file != bind(path):
        raise ValueError('image_changed_during_execution_snapshot')
    return dict(**file, mtime_ns=after.st_mtime_ns, size_bytes=after.st_size,
                image_mode=mode, dimensions=size, rgb_sha256=rgb)


def _codes(prompt_profiles, extra):
    files = [__file__, flow.__file__, flow.core.__file__, flow.features.__file__, flow.features.registry.__file__,
             flow.continuity.__file__, flow.voices.__file__, native.__file__, native.jobs.__file__]
    if prompt_profiles is not None:
        from . import h3_asset_prompt_profiles_v1 as helper
        files.append(helper.__file__)
    files += list(extra)
    return [bind(p) for p in dict.fromkeys(str(Path(p).resolve()) for p in files)]


def prepare(run, offline_output, config, *, prompt_profiles=None, authorization=None, code_files=()):
    run = Path(run).resolve(); run.mkdir(parents=True, exist_ok=True)
    with native.jobs.run_lock(run):
        if (run / 'PLAN.json').exists():
            _, plan, _, _ = _load(run)
            if (plan['offline_output'] != str(Path(offline_output).resolve()) or plan['prompt_profiles'] != prompt_profiles
                    or plan['user_authorization'] != authorization or plan['config'] != _config(config, flow._bound(plan['live_manifest']), run)):
                raise ValueError('existing_execution_preserved_new_namespace_required')
            return status(run)
        manifest, graph, entry, scope = _derive(offline_output, run, prompt_profiles)
        cfg = _config(config, manifest, run)
        if authorization is not None:flow.core.check(authorization)
        if cfg['video_enabled'] and authorization is None:
            raise ValueError('explicit_user_authorization_binding_required')
        native._service_paths(cfg)  # GET only; proves where LoadImage/Save* resolve.
        sid = entry['shot_id']; folder = run / 'shots' / sid; folder.mkdir(parents=True, exist_ok=True)
        row = dict(id=sid, scope=scope, graph_sha256=digest(graph), first_frame=manifest['guide']['image'],
                   input_name=manifest['references'][-1]['input_name'], timing=native._timing(dict(start=0, end=15)))
        if row['timing']['native_frames'] != 362:
            raise ValueError('native_362_frame_contract_required')
        inputs = []; pause = bind(cfg['protected_pause_path'])
        with native._gpu(dict(config=cfg, protected_pause=pause)):
            for ref in manifest['references']:
                source = _snapshot(flow.core.check(ref['image']))
                staged = native.jobs.stage_input({k: cfg[k] for k in ('service_url', 'input_root', 'output_root', 'timeout')},
                    ref['image']['path'], ref['input_name'], ref['image']['sha256'])
                actual = _snapshot(staged['staged_path'])
                if source != _snapshot(source['path']) or source['sha256'] != actual['sha256'] or source['rgb_sha256'] != actual['rgb_sha256']:
                    raise ValueError('staged_original_image_pixels_changed')
                inputs.append(dict(slot=ref['slot'], tag=ref['tag'], input_name=ref['input_name'], source=source, staged=actual))
        _freeze(run / 'INPUT_MANIFEST.json', manifest)
        _freeze(run / 'STAGING_RECEIPT.json', dict(schema=VERSION, inputs=inputs, physical_staging_performed=True,
            model_calls=0, audio_reference_inputs=0, voice_identity_locked=False))
        out = Path(offline_output).resolve()
        plan = dict(schema=VERSION, config=cfg, shots=[row], offline_output=str(out),
            offline={name: bind(out / name) for name in ('CHECK_RESULT.json', 'INPUT_MANIFEST.json', 'DRAFT_WORKFLOW.json')},
            prompt_profiles=prompt_profiles, live_manifest=bind(run / 'INPUT_MANIFEST.json'),
            user_authorization=authorization,
            staging=bind(run / 'STAGING_RECEIPT.json'), protected_pause=pause, code=_codes(prompt_profiles, code_files),
            voice_control_mode='prompt_only', audio_reference_inputs=0, voice_identity_locked=False,
            publication=False, production_approved=False, old_batch_resume=False)
        _freeze(run / 'PLAN.json', plan); _freeze(folder / 'workflow_api.json', graph)
        if not (folder / 'STATE.json').exists():
            native.write(folder / 'STATE.json', dict(id=sid, status='prepared', prompt_id=None, plan_sha256=digest(plan)))
        _freeze(run / 'LAUNCH_REQUEST.json', launch_request(run))
        return status(run)


def _load(run, *, current=True):
    run = Path(run).resolve(); plan = read(run / 'PLAN.json')
    if (plan.get('schema') != VERSION or plan.get('publication') is not False or plan.get('production_approved') is not False
            or plan.get('voice_control_mode') != 'prompt_only' or len(plan.get('shots', [])) != 1):
        raise ValueError('explicit_single_shot_execution_plan_required')
    row = plan['shots'][0]; folder = run / 'shots' / native.slug(row['id']); graph = read(folder / 'workflow_api.json')
    if digest(graph) != row['graph_sha256']:
        raise ValueError('frozen_execution_graph_changed')
    manifest = flow._bound(plan['live_manifest'])
    flow.validate_graph(graph, manifest['references'], manifest['voice_resolution'], row['scope'])
    if current:
        for value in [*plan['offline'].values(), *plan['code'], plan['protected_pause'], plan['staging']]:
            flow.core.check(value)
        if plan.get('user_authorization') is not None:flow.core.check(plan['user_authorization'])
        if plan['config']['video_enabled'] and plan.get('user_authorization') is None:
            raise ValueError('execution_user_authorization_binding_missing')
        expected, expected_graph, _, _ = _derive(plan['offline_output'], run, plan['prompt_profiles'])
        if expected != manifest or expected_graph != graph or _config(plan['config'], manifest, run) != plan['config']:
            raise ValueError('source_profile_scope_or_service_binding_changed')
        _verify_staging(plan)
    return run, plan, row, folder


def _verify_staging(plan):
    receipt = flow._bound(plan['staging']); manifest = flow._bound(plan['live_manifest'])
    if len(receipt['inputs']) != len(manifest['references']):
        raise ValueError('all_physical_reference_inputs_required')
    for item, ref in zip(receipt['inputs'], manifest['references']):
        expected_path = native.bound(plan['config']['input_root'], ref['input_name'])
        if (item['slot'] != ref['slot'] or item['tag'] != ref['tag'] or item['input_name'] != ref['input_name']
                or item['source'] != _snapshot(ref['image']['path']) or item['source']['sha256'] != ref['image']['sha256']
                or item['staged'] != _snapshot(expected_path)):
            raise ValueError('source_or_staged_reference_SHA_mtime_or_RGB_changed')


def status(run):
    _, plan, row, folder = _load(run, current=False); state = native._shot_state(folder, plan, row)
    return dict(schema=VERSION, status=state['status'], shot_id=row['id'], prompt_id=state.get('prompt_id'),
                run=str(Path(run).resolve()), production_approved=False, publication=False,
                voice_control_mode='prompt_only', voice_identity_locked=False)


def launch_request(run):
    run, plan, row, folder = _load(run)
    return dict(schema=LAUNCH, plan=bind(run / 'PLAN.json'), graph=bind(folder / 'workflow_api.json'),
                manifest=plan['live_manifest'], staging=plan['staging'], offline=plan['offline'],
                prompt_profiles=plan['prompt_profiles'], source_code=plan['code'],
                user_authorization=plan['user_authorization'],
                protected_pause=plan['protected_pause'], shot_id=row['id'], unknown_replay=False, publication=False)


def _ledger(run, sid, pid, event):
    for name, line in [('job_ids.txt', sid + ' ' + pid + '\n'), ('LOG.md', '- ' + event + ' ' + sid + ' ' + pid + '\n')]:
        target = run / name
        if not target.exists() or line not in target.read_text(encoding='utf-8').splitlines(keepends=True):
            with target.open('a', encoding='utf-8') as handle:
                handle.write(line)


def submit(run):
    run = Path(run).resolve()
    with native.jobs.run_lock(run):
        run, plan, row, folder = _load(run); state = native._shot_state(folder, plan, row)
        if state['status'] != 'prepared' or (folder / 'CLAIM.json').exists() or (run / 'PAUSE.json').exists() or not plan['config']['video_enabled']:
            return status(run)
        approval = read(run / 'LAUNCH_APPROVAL.json')
        if (approval.get('schema') != LAUNCH or approval.get('request') != launch_request(run)
                or not isinstance(approval.get('approved_by'), str) or approval['approved_by'].strip().lower() != 'root'
                or not isinstance(approval.get('evidence'), list) or not approval['evidence']
                or any(not isinstance(v, str) or not v.strip() for v in approval['evidence'])):
            raise ValueError('complete_Root_launch_approval_required')
        with native._gpu(plan):
            _load(run); native._service_paths(plan['config']); queue = native._queue(plan['config'])
            if queue['queue_running'] or queue['queue_pending']:
                return dict(status(run), dispatch='waiting_gpu_queue')
            request = dict(prompt=read(folder / 'workflow_api.json'), client_id=uuid.uuid4().hex)
            _freeze(folder / 'REQUEST.json', request)
            _freeze(folder / 'CLAIM.json', dict(at=time.time(), graph_sha256=row['graph_sha256'], first_frame_sha256=row['first_frame']['sha256']))
            try:
                response = native._http(plan['config'], '/prompt', request)
            except Exception as error:
                _freeze(folder / 'SUBMISSION_ERROR.json', dict(type=type(error).__name__, message=str(error), retry=False))
                state['status'] = 'rejected' if isinstance(error, urllib.error.HTTPError) and error.code in (400, 422) else 'outcome_unknown'
            else:
                _freeze(folder / 'RESPONSE.json', response)
                pid = response.get('prompt_id') if isinstance(response, dict) else None
                try: native.slug(pid)
                except ValueError: state['status'] = 'outcome_unknown'
                else:
                    state.update(status='submitted', prompt_id=pid, submitted_at=time.time())
                    _ledger(run, row['id'], pid, 'NATIVE_ID')
            native.write(folder / 'STATE.json', state)
        return status(run)


def collect_known(run, prompt_id=None):
    run = Path(run).resolve()
    with native.jobs.run_lock(run):
        run, plan, row, folder = _load(run, current=False); state = native._shot_state(folder, plan, row); pid = state.get('prompt_id')
        if prompt_id is not None and prompt_id != pid:
            raise ValueError('collector_must_retain_original_native_UUID')
        if not pid or state['status'] in ('technical_saved', 'failed', 'interrupted', 'rejected'):
            return status(run)
        _ledger(run, row['id'], pid, 'NATIVE_ID')
        history = native._http(plan['config'], '/history/' + native.slug(pid))
        if not isinstance(history, dict):raise ValueError('actual_native_history_required')
        entry = history.get(pid)
        if entry is not None:
            prompt = entry.get('prompt', []); terminal = entry.get('status', {})
            if (len(prompt) < 3 or prompt[1] != pid or not native._verify_native_graph(folder, row, prompt[2], pid)
                    or type(terminal.get('completed')) is not bool or terminal.get('status_str') not in ('success', 'error')):
                raise ValueError('original_UUID_graph_and_native_history_required')
            native.write(folder / 'HISTORY.latest.json', history)
            if terminal['status_str'] == 'error':state.update(status='failed', native_terminal=terminal)
            elif terminal['completed']:
                _freeze(folder / 'HISTORY.json', history); native._collect(folder, plan, row, state, entry)
                _ledger(run, row['id'], pid, 'SAVED')
            else:state['status'] = 'running'
        else:
            queue = native._queue(plan['config']); matches = [r for r in queue['queue_running'] + queue['queue_pending'] if r[1] == pid]
            if any(not native._verify_native_graph(folder, row, r[2], pid) for r in matches):
                raise ValueError('original_UUID_queue_graph_changed')
            state['status'] = 'running' if matches else 'outcome_unknown'
        native.write(folder / 'STATE.json', state)
        return status(run)
