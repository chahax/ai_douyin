"""Opt-in, once-only inspection on an existing manual actor/session.

No ARM means no imports, database reads, callbacks or browser actions. The
Streamlit entry registers a callback only; the original owner thread performs
the reviewed inspection between handlers, without completing its manual task.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import types

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM = RUN / 'manual_runtime_v1/ARM.json'
SOURCE_PATHS = {
    'bridge': Path(__file__).resolve(),
    'flow': ROOT / 'src/operations_accounts/manual_republication_flow_v1.py',
    'app': ROOT / 'src/web/app.py',
    'host': ROOT / 'src/operations_accounts/browser_control_runtime.py',
}
CONFIG_SCHEMA = 'manual_republication_runtime_config/v1'
REQUEST_SCHEMA = 'manual_republication_operator_request/v1'
PLAN_SCHEMA = 'manual_republication_runtime_plan/v1'
VIEWS = {'manage', 'upload'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def reference(path):
    path = Path(path).resolve()
    if not path.is_file() or not path.is_relative_to(ROOT):
        raise ValueError('manual_operator_project_file_required')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def _read(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'} or reference(ref['path']) != ref:
        raise ValueError('manual_operator_bound_file_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def _once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write((_canonical(value) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
    return reference(path)


def _process(pid):
    import psutil
    return psutil.Process(pid).create_time()


def _sources(config):
    if not isinstance(config.get('sources'), dict) or set(config['sources']) != set(SOURCE_PATHS):
        raise ValueError('manual_operator_exact_sources_required')
    for name, path in SOURCE_PATHS.items():
        if reference(path) != config['sources'][name]:
            raise ValueError('manual_operator_source_changed:' + name)


def _config(ref):
    value = _read(ref)
    fields = {'schema', 'backend_pid', 'backend_create_time', 'account_key', 'account_id',
              'owner_id', 'generation', 'binding_version', 'browser_db', 'control_db',
              'control_snapshot', 'manual_command_id', 'manual_request_sha256', 'tab_id',
              'authority', 'sources'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != CONFIG_SCHEMA:
        raise ValueError('manual_operator_config_invalid')
    for key in ('account_key', 'account_id', 'owner_id', 'binding_version',
                'manual_command_id', 'manual_request_sha256', 'tab_id'):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError('manual_operator_scope_required:' + key)
    if (type(value['backend_pid']) is not int or type(value['generation']) is not int
            or value['generation'] < 1 or not isinstance(value['backend_create_time'], (int, float))
            or isinstance(value['backend_create_time'], bool)
            or not value['owner_id'].startswith('backend:' + str(value['backend_pid']) + ':')
            or _process(value['backend_pid']) != value['backend_create_time']):
        raise ValueError('manual_operator_process_changed')
    if (not isinstance(value['control_snapshot'], dict)
            or set(value['control_snapshot']) != {'state', 'revision'}
            or value['control_snapshot']['state'] not in {'active', 'paused'}
            or type(value['control_snapshot']['revision']) is not int):
        raise ValueError('manual_operator_control_snapshot_invalid')
    if Path(value['authority']['path']).resolve() != (RUN / 'USER_AUTHORIZATION.json').resolve():
        raise ValueError('manual_operator_exact_new_authority_required')
    auth = _read(value['authority'])
    if (auth.get('schema') != 'explicit_republication_intent/v1'
            or not auth.get('user_statement') or auth.get('account_key') != value['account_key']
            or auth.get('account_uuid') != value['account_id']
            or not isinstance(auth.get('expected_public_uid'), str) or not auth['expected_public_uid']
            or auth.get('new_publication_limit') != 1 or type(auth.get('new_publication_limit')) is not int
            or auth.get('model_media_calls_allowed') is not False
            or auth.get('old_records_unchanged') is not True
            or not auth.get('declaration_requirement') or not auth.get('old_post_id')):
        raise ValueError('manual_operator_authority_scope_invalid')
    if reference(auth['media']['path']) != auth['media']:
        raise ValueError('manual_operator_authorized_media_changed')
    _sources(value)
    return value


def _request(ref, config_ref):
    request = _read(ref)
    if (not isinstance(request, dict) or set(request) != {'schema', 'config', 'action', 'view'}
            or request['schema'] != REQUEST_SCHEMA or request['config'] != config_ref
            or request['action'] != 'inspect_site' or request['view'] not in VIEWS):
        raise ValueError('manual_operator_inspection_only')
    return request


def _ro(path):
    path = Path(path).resolve()
    if not path.is_file() or not path.is_relative_to(ROOT / 'data'):
        raise ValueError('manual_operator_existing_project_database_required')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    return db


def _state(config):
    from .browser_control import BrowserControlStore
    from .publication_autonomous_reconciliation import unresolved
    with _ro(config['browser_db']) as db:
        owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',
                           (config['account_id'],)).fetchone()
        row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
                         (config['manual_command_id'],)).fetchone()
        manual = BrowserControlStore._command(row)
        pending = unresolved(types.SimpleNamespace(_command=BrowserControlStore._command),
            db, config['account_id'], ('running', 'paused', 'waiting_human', 'outcome_unknown'))
    if (not owner or owner['owner_id'] != config['owner_id'] or owner['generation'] != config['generation']
            or owner['binding_version'] != config['binding_version'] or owner['state'] != 'active'
            or not 0 <= time.time() - owner['heartbeat'] <= 60):
        raise ValueError('manual_operator_original_owner_changed')
    if (not manual or manual['kind'] != 'manual' or manual['state'] != 'waiting_human'
            or manual['account_id'] != config['account_id']
            or manual['binding_version'] != config['binding_version']
            or manual['owner_id'] != config['owner_id'] or manual['generation'] != config['generation']
            or manual['request_sha'] != config['manual_request_sha256']
            or manual['payload'].get('account_key') != config['account_key']
            or manual['payload'].get('account_uuid') != config['account_id']
            or (manual.get('result') or {}).get('tab_id') != config['tab_id']
            or manual['request_sha'] != _digest([manual['account_id'], manual['binding_version'],
                manual['kind'], manual['payload'], manual['priority']])):
        raise ValueError('manual_operator_original_manual_changed')
    if any(item['command_id'] != config['manual_command_id'] for item in pending):
        raise ValueError('manual_operator_other_live_work')
    with _ro(config['control_db']) as db:
        control = db.execute('SELECT state,revision FROM account_controls WHERE account_uuid=?',
                             (config['account_id'],)).fetchone()
    if not control or dict(control) != config['control_snapshot']:
        raise ValueError('manual_operator_control_changed')
    return {'manual_identity': {key: manual[key] for key in ('command_id', 'account_id',
        'binding_version', 'kind', 'request_sha', 'owner_id', 'generation')},
        'control_snapshot': dict(control)}


def validate_live(actor, resource, config):
    """No writes, session creation, navigation, pause change or manual completion."""
    actor._assert_thread()
    actor._check_owner()
    if (actor.account_id != config['account_id'] or actor.owner_id != config['owner_id']
            or actor.generation != config['generation'] or actor.binding_version != config['binding_version']
            or Path(actor.store.path).resolve() != Path(config['browser_db']).resolve()
            or actor._stack or resource.account_uuid != config['account_id']
            or resource.manual_tasks != {config['manual_command_id']: config['tab_id']}
            or getattr(resource, 'console_tasks', {}) or resource.session is None
            or resource.session.config.headless is not False
            or getattr(resource.session, '_proc', None) is None):
        raise ValueError('manual_operator_original_resource_changed')
    failure = getattr(resource.session, 'worker_failure', None)
    process_poll = getattr(resource.session._proc, 'poll', None)
    if not callable(failure) or failure() or not callable(process_poll) or process_poll() is not None:
        raise ValueError('manual_operator_worker_unhealthy')
    return _state(config)


def prepare(config_ref, request_ref, output_directory):
    """Validate local bindings, then save a new PLAN; never ARM or run a browser."""
    directory = Path(output_directory).resolve()
    if not directory.is_relative_to(RUN.resolve()) or directory.exists():
        raise ValueError('manual_operator_new_run_directory_required')
    config = _config(config_ref)
    request = _request(request_ref, config_ref)
    state = _state(config)
    return _once(directory / 'PLAN.json', dict(schema=PLAN_SCHEMA, config=config_ref,
        request=request_ref, state=state, action=request['action'], view=request['view'],
        prepared_only=True, uploaded=False, submitted=False))


def _plan(ref):
    plan = _read(ref)
    if (plan.get('schema') != PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve())
            or plan.get('uploaded') is not False or plan.get('submitted') is not False):
        raise ValueError('manual_operator_plan_invalid')
    config = _config(plan['config'])
    request = _request(plan['request'], plan['config'])
    if plan['action'] != request['action'] or plan['view'] != request['view']:
        raise ValueError('manual_operator_plan_request_changed')
    return plan, config, request


def _validate_refs(value):
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256'}:
            if reference(value['path']) != value:
                raise ValueError('manual_operator_result_artifact_changed')
        else:
            for item in value.values():
                _validate_refs(item)
    elif isinstance(value, list):
        for item in value:
            _validate_refs(item)


def status(plan_ref):
    """Pure file verification; a claim without a complete receipt never replays."""
    plan = _read(plan_ref)
    folder = Path(plan_ref['path']).parent
    if plan.get('schema') != PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):
        raise ValueError('manual_operator_plan_invalid')
    claim_path = folder / 'ACTION_CLAIM.json'
    result_path = folder / 'RESULT.json'
    unknown_path = folder / 'UNKNOWN.json'
    if result_path.exists():
        result = _read(reference(result_path))
        if (not claim_path.exists() or result.get('plan') != plan_ref
                or result.get('claim') != reference(claim_path)
                or result.get('status') != 'inspected' or result.get('submitted') is not False
                or result.get('uploaded') is not False):
            raise ValueError('manual_operator_cached_receipt_changed')
        claim = _read(result['claim'])
        if claim.get('plan') != plan_ref or claim.get('request') != plan['request']:
            raise ValueError('manual_operator_cached_claim_changed')
        _validate_refs(result)
        return {'status': 'inspected', 'result': reference(result_path)}
    if claim_path.exists():
        return {'status': 'outcome_unknown', 'claim': reference(claim_path),
                'unknown': reference(unknown_path) if unknown_path.exists() else None,
                'automatic_replay_allowed': False}
    return {'status': 'prepared', 'plan': plan_ref}


def _load_flow(config):
    path = SOURCE_PATHS['flow']
    raw = path.read_bytes()
    if reference(path) != config['sources']['flow']:
        raise ValueError('manual_operator_flow_source_changed')
    module = types.ModuleType('src.operations_accounts._manual_republication_reviewed_' + config['sources']['flow']['sha256'][:16])
    module.__file__, module.__package__ = str(path), 'src.operations_accounts'
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    if not callable(getattr(module, 'run_action', None)):
        raise ValueError('manual_operator_reviewed_flow_missing')
    blocked = getattr(module, 'InspectionBlocked', None)
    codes = getattr(module, 'BLOCK_REASONS', frozenset())
    if blocked is not None:
        if (not isinstance(blocked, type) or not issubclass(blocked, ValueError)
                or not isinstance(codes, frozenset)
                or any(not isinstance(code, str) or not 1 <= len(code) <= 100
                    or any(c not in 'abcdefghijklmnopqrstuvwxyz_' for c in code) for code in codes)):
            raise ValueError('manual_operator_safe_diagnostics_invalid')
        module.run_action._inspection_blocked_class = blocked
        module.run_action._inspection_blocked_codes = codes
    return module.run_action


def _perform(actor, resource, plan_ref, arm_ref, run_action):
    plan, config, request = _plan(plan_ref)
    folder = Path(plan_ref['path']).parent
    if status(plan_ref)['status'] != 'prepared':
        return status(plan_ref)
    if reference(ARM) != arm_ref:
        raise ValueError('manual_operator_arm_changed')
    if os.getpid() != config['backend_pid']:
        raise ValueError('manual_operator_wrong_process')
    if validate_live(actor, resource, config) != plan['state']:
        raise ValueError('manual_operator_prepared_state_changed')
    claim = dict(schema='manual_republication_inspection_claim/v1', plan=plan_ref,
        request=plan['request'], config=plan['config'], arm=arm_ref,
        actor_thread_id=threading.get_ident(), at_epoch=time.time(), action='inspect_site',
        uploaded=False, submitted=False)
    try:
        claim_ref = _once(folder / 'ACTION_CLAIM.json', claim)
    except FileExistsError:
        return status(plan_ref)
    try:
        # Claim precedes the only reviewed call. A lost acknowledgement stays unknown.
        result = run_action(actor, resource, config, request, folder / 'inspection')
        _plan(plan_ref)
        if reference(ARM) != arm_ref or validate_live(actor, resource, config) != plan['state']:
            raise ValueError('manual_operator_context_changed_after_inspection')
        if (not isinstance(result, dict) or result.get('schema') != 'manual_republication_inspection/v1'
                or result.get('action') != request['action'] or result.get('view') != request['view']
                or result.get('read_only') is not True or result.get('uploaded') is not False
                or result.get('submitted') is not False):
            raise ValueError('manual_operator_inspection_result_invalid')
        _validate_refs(result)
        ref = _once(folder / 'RESULT.json', dict(schema='manual_republication_runtime_result/v1',
            status='inspected', plan=plan_ref, claim=claim_ref, inspection=result,
            original_manual_unchanged=True, account_pause_changed=False,
            uploaded=False, submitted=False))
        return {'status': 'inspected', 'result': ref}
    except Exception as error:
        path = folder / 'UNKNOWN.json'
        if not path.exists():
            value = dict(schema='manual_republication_runtime_unknown/v1', plan=plan_ref,
                claim=claim_ref, status='outcome_unknown', error_type=type(error).__name__,
                scope='read_only_inspection', uploaded=False, submitted=False,
                publication_outcome_changed=False, automatic_replay_allowed=False)
            if (type(error) is getattr(run_action, '_inspection_blocked_class', None)
                    and getattr(error, 'code', None) in getattr(run_action, '_inspection_blocked_codes', ())):
                value['reason_code'] = error.code
            _once(path, value)
        return {'status': 'outcome_unknown', 'claim': claim_ref, 'automatic_replay_allowed': False}


def install_if_armed():
    """Register only; no browser work occurs on the Streamlit script thread."""
    if not ARM.is_file():
        return {'status': 'not_armed'}
    directory = None
    try:
        arm_ref = reference(ARM)
        arm = _read(arm_ref)
        if set(arm) != {'schema', 'plan'} or arm['schema'] != 'manual_republication_runtime_arm/v1':
            raise ValueError('manual_operator_arm_invalid')
        plan, config, request = _plan(arm['plan'])
        directory = Path(arm['plan']['path']).parent
        if os.getpid() != config['backend_pid']:
            return {'status': 'different_process_no_install'}
        cached = status(arm['plan'])
        if cached['status'] != 'prepared':
            return cached
        matches = []
        for thread in threading.enumerate():
            target = getattr(thread, '_target', None)
            if (thread.name == 'AccountBrowser-' + config['account_key'] and thread.is_alive()
                    and getattr(target, '__name__', None) == '_host'
                    and Path(target.__code__.co_filename).resolve() == SOURCE_PATHS['host'].resolve()
                    and getattr(thread, '_args', ()) == (config['account_key'],)):
                matches.append(target.__globals__)
        if len(matches) != 1:
            raise ValueError('manual_operator_unique_original_actor_required')
        namespace = matches[0]
        previous_poll = namespace['_poll_manual_windows']
        if getattr(previous_poll, '_manual_republication_plan', None) == arm['plan']:
            return {'status': 'callback_already_registered'}
        if getattr(previous_poll, '_manual_republication_plan', None) is not None:
            raise ValueError('manual_operator_other_request_registered')
        run_action = _load_flow(config)

        def poll(actor, resource):
            if (actor.account_id != config['account_id'] or actor.owner_id != config['owner_id']
                    or actor.generation != config['generation']):
                return previous_poll(actor, resource)
            defer = False
            try:
                # Validate the target thread before even its ordinary session poll.
                actor._assert_thread()
                actor._check_owner()
                value = previous_poll(actor, resource)
                if actor._stack:
                    defer = True
                    return value
                _perform(actor, resource, arm['plan'], arm_ref, run_action)
            except Exception as error:
                refusal = directory / 'REFUSED.json'
                if not refusal.exists():
                    _once(refusal, dict(schema='manual_republication_runtime_refusal/v1',
                        plan=arm['plan'], error_type=type(error).__name__,
                        reason=str(error) if isinstance(error, ValueError) else 'owner_guard_refused',
                        action_started=False))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:
                    namespace['_poll_manual_windows'] = previous_poll
            return None

        poll._manual_republication_plan = arm['plan']
        namespace['_poll_manual_windows'] = poll
        return {'status': 'callback_registered_waiting_original_actor_tick'}
    except Exception as error:
        return {'status': 'refused', 'error_type': type(error).__name__,
                'reason': str(error) if isinstance(error, ValueError) else 'original_actor_guard_refused'}
