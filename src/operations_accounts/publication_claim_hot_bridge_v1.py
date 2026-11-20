"""Explicit one-owner bridge for an already queued publication read-back.

An absent new ARM is inert. The UI import only registers a callback. Installation
and the sole allowed claim execute on the original actor thread, using the
original Store/owner/session and an isolated copy of the reviewed recovery
function. No module reload, owner recovery, browser action, or new queue entry.
"""
import hashlib
import inspect
import json
import marshal
import os
from pathlib import Path
import sqlite3
import threading
import time
import types

ROOT = Path(__file__).resolve().parents[2]
ARM = ROOT / 'data/publication_claim_hot_bridge_v1/ARM.json'
SOURCE_PATHS = {
    'bridge': Path(__file__).resolve(),
    'recovery': ROOT / 'src/operations_accounts/publication_verification_recovery.py',
    'core': ROOT / 'src/operations_accounts/browser_control.py',
    'paused_guard': ROOT / 'src/operations_accounts/paused_browser_claims.py',
    'app': ROOT / 'src/web/app.py',
}
HOST_PATH = ROOT / 'src/operations_accounts/browser_control_runtime.py'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def reference(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('bridge_reference_outside_project')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _read(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'} or reference(ref['path']) != ref:
        raise ValueError('bridge_reference_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def _write_once(path, value):
    path = Path(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('bridge_receipt_already_exists')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    return reference(path)


def _process(pid):
    import psutil
    return psutil.Process(pid).create_time()


def _sources(config):
    if set(config['sources']) != set(SOURCE_PATHS):
        raise ValueError('bridge_exact_reviewed_sources_required')
    for key, expected in SOURCE_PATHS.items():
        if Path(config['sources'][key]['path']).resolve() != expected.resolve() or reference(expected) != config['sources'][key]:
            raise ValueError('bridge_reviewed_source_changed:' + key)


def _ro(path):
    path = Path(path).resolve()
    if not path.is_file() or not path.is_relative_to(ROOT / 'data'):
        raise ValueError('bridge_original_database_missing')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    return db


def _parsed(row):
    value = dict(row)
    for field in ('payload', 'result', 'cursor'):
        if isinstance(value.get(field), str):
            value[field] = json.loads(value[field])
    value['task_id'] = value['command_id']
    return value


def _rows(config, db=None):
    if db is None:
        with _ro(config['browser_db']) as connection:
            return _rows(config, connection)
    original = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (config['original_command_id'],)).fetchone()
    queued = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (config['verification_command_id'],)).fetchone()
    owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (config['account_id'],)).fetchone()
    if not original or not queued or not owner:
        raise ValueError('bridge_original_rows_missing')
    original, queued, owner = dict(original), dict(queued), dict(owner)
    if (owner['owner_id'] != config['owner_id'] or owner['generation'] != config['generation']
            or owner['binding_version'] != config['binding_version'] or owner['state'] != 'active'
            or not 0 <= time.time() - owner['heartbeat'] <= 60
            or original['state'] != 'outcome_unknown' or original['kind'] != 'publish'
            or original['owner_id'] != config['owner_id'] or original['generation'] != config['generation']
            or queued['state'] != 'queued' or queued['kind'] != 'publication_verify'
            or queued['owner_id'] is not None or queued['generation'] is not None
            or queued['request_sha'] != config['verification_request_sha256']
            or any(row['account_id'] != config['account_id'] or row['binding_version'] != config['binding_version'] for row in (original, queued))):
        raise ValueError('bridge_exact_original_owner_or_command_changed')
    payload = json.loads(queued['payload'])
    if (payload.get('original_command_id') != original['command_id']
            or payload.get('original_snapshot_sha256') != _digest(_parsed(original))):
        raise ValueError('bridge_queued_verification_original_mismatch')
    with _ro(config['control_db']) as control:
        row = control.execute('SELECT state FROM account_controls WHERE account_uuid=?', (config['account_id'],)).fetchone()
    if not row or row['state'] != 'paused':
        raise ValueError('bridge_original_paused_state_changed')
    return original, queued


def _config(ref):
    config = _read(ref)
    fields = {'schema', 'backend_pid', 'backend_create_time', 'account_key', 'account_id', 'owner_id', 'generation',
              'binding_version', 'browser_db', 'control_db', 'original_command_id', 'verification_command_id',
              'verification_request_sha256', 'sources'}
    if set(config) != fields or config['schema'] != 'publication_claim_hot_bridge_config/v1':
        raise ValueError('bridge_config_contract_invalid')
    if (type(config['backend_pid']) is not int or type(config['generation']) is not int
            or not config['owner_id'].startswith('backend:' + str(config['backend_pid']) + ':')
            or _process(config['backend_pid']) != config['backend_create_time']):
        raise ValueError('bridge_original_process_identity_changed')
    _sources(config)
    return config


def prepare_plan(config_ref, output_directory):
    """RO preflight + new evidence PLAN only; never ARM or install anything."""
    directory = Path(output_directory).resolve()
    if not directory.is_relative_to(ROOT / 'data') or directory.exists():
        raise ValueError('bridge_new_project_plan_directory_required')
    config = _config(config_ref)
    original, queued = _rows(config)
    value = dict(schema='publication_claim_hot_bridge_plan/v1', config=config_ref,
                 original_row_sha256=_digest(original), queued_row_sha256=_digest(queued),
                 backend_pid=config['backend_pid'], backend_create_time=config['backend_create_time'],
                 owner_id=config['owner_id'], generation=config['generation'],
                 plan_only=True, installed=False, external_actions=False)
    directory.mkdir(parents=True)
    return _write_once(directory / 'PLAN.json', value)


def _load_claim(config):
    """Compile the exact reviewed bytes; do not trust timestamp-based pycache."""
    path = SOURCE_PATHS['recovery']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != config['sources']['recovery']['sha256']:
        raise ValueError('bridge_recovery_source_changed')
    name = 'src.operations_accounts._publication_claim_reviewed_' + config['sources']['recovery']['sha256'][:16]
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = 'src.operations_accounts'
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    function = module.claim
    parameter = inspect.signature(function).parameters.get('allowed_kinds')
    if (parameter is None or parameter.kind != inspect.Parameter.KEYWORD_ONLY
            or function.__code__.co_filename != str(path)):
        raise ValueError('bridge_loaded_claim_contract_invalid')
    proof = dict(source=config['sources']['recovery'], isolated_module=name,
                 function='claim', signature=str(inspect.signature(function)),
                 code_sha256=hashlib.sha256(marshal.dumps(function.__code__)).hexdigest(),
                 sys_modules_replaced=False)
    return function, module.BrowserControlRejected, proof


def _record_failure(directory, stage, error):
    # No exception text, credentials, raw UI or original command payloads.
    value = dict(schema='publication_claim_hot_bridge_refusal/v1', stage=stage,
                 error_type=type(error).__name__, reason=str(error) if isinstance(error, ValueError) else 'bridge_guard_refused',
                 browser_actions=False, new_queue_entries=False)
    try:
        path = directory / ('REFUSED_' + stage.upper() + '.json')
        if not path.exists():
            _write_once(path, value)
    except Exception:
        pass


def install_if_armed():
    """Called by an actual Streamlit rerun, never by health GET or startup."""
    if not ARM.is_file():
        return {'status': 'not_armed'}
    directory = None
    try:
        arm = json.loads(ARM.read_text(encoding='utf-8'))
        arm_ref = reference(ARM)
        if set(arm) != {'schema', 'plan'} or arm['schema'] != 'publication_claim_hot_bridge_arm/v1':
            raise ValueError('bridge_arm_contract_invalid')
        plan = _read(arm['plan'])
        directory = Path(arm['plan']['path']).parent
        if plan.get('schema') != 'publication_claim_hot_bridge_plan/v1':
            raise ValueError('bridge_plan_contract_invalid')
        config = _config(plan['config'])
        if os.getpid() != config['backend_pid']:
            return {'status': 'different_process_no_install'}
        installed_path = directory / 'ACTOR_INSTALLED_RECEIPT.json'
        if installed_path.is_file():
            installed = json.loads(installed_path.read_text(encoding='utf-8'))
            if (installed.get('plan') != arm['plan'] or installed.get('backend_pid') != config['backend_pid']
                    or installed.get('backend_create_time') != config['backend_create_time']
                    or installed.get('owner_id') != config['owner_id'] or installed.get('generation') != config['generation']):
                raise ValueError('bridge_existing_install_receipt_changed')
            return {'status': 'actor_install_already_recorded'}
        matches = []
        for thread in threading.enumerate():
            target = getattr(thread, '_target', None)
            if (thread.name == 'AccountBrowser-' + config['account_key'] and thread.is_alive()
                    and getattr(target, '__name__', '') == '_host'
                    and Path(target.__code__.co_filename).resolve() == HOST_PATH
                    and getattr(thread, '_args', ()) == (config['account_key'],)):
                matches.append(target.__globals__)
        if len(matches) != 1:
            raise ValueError('bridge_unique_original_actor_thread_required')
        namespace = matches[0]
        previous_poll = namespace['_poll_manual_windows']
        if getattr(previous_poll, '_publication_claim_hot_plan', None) == arm['plan']:
            return {'status': 'callback_already_registered'}
        claim_function, loaded_rejection, loaded_proof = _load_claim(config)
        old_rejection = namespace['BrowserControlRejected']

        def recheck_plan():
            if reference(ARM) != arm_ref or _read(arm['plan']) != plan:
                raise ValueError('bridge_arm_or_plan_changed_after_registration')
            _config(plan['config'])

        def poll(actor, resource):
            if (actor.account_id != config['account_id'] or actor.owner_id != config['owner_id']
                    or actor.generation != config['generation']):
                return previous_poll(actor, resource)
            previous_claim = None
            try:
                actor._assert_thread()
                actor._check_owner()
                recheck_plan()
                if actor._stack or resource.manual_tasks or getattr(resource, 'console_tasks', {}):
                    return previous_poll(actor, resource)  # Keep callback for the next safe tick.
                if (actor.binding_version != config['binding_version'] or resource.account_uuid != config['account_id']
                        or Path(actor.store.path).resolve() != Path(config['browser_db']).resolve()):
                    raise ValueError('bridge_original_actor_not_at_safe_idle_point')
                original, queued = _rows(config)
                if _digest(original) != plan['original_row_sha256'] or _digest(queued) != plan['queued_row_sha256']:
                    raise ValueError('bridge_prepared_command_snapshot_changed')
                previous_claim = actor.store.claim_next

                def guarded_claim(account_id, binding_version, owner_id, generation, *, above_priority=None,
                                  kinds=None, parent_command_id=None):
                    if (account_id != config['account_id'] or binding_version != config['binding_version']
                            or owner_id != config['owner_id'] or generation != config['generation']
                            or above_priority is not None or parent_command_id is not None):
                        return previous_claim(account_id, binding_version, owner_id, generation,
                            above_priority=above_priority, kinds=kinds, parent_command_id=parent_command_id)
                    if kinds is not None and 'publication_verify' not in kinds:
                        return None
                    try:
                        with _ro(config['browser_db']) as read_db:
                            finished = read_db.execute('SELECT state FROM browser_control_commands WHERE command_id=?',
                                                       (config['verification_command_id'],)).fetchone()
                            original_state = read_db.execute('SELECT state FROM browser_control_commands WHERE command_id=?',
                                                             (config['original_command_id'],)).fetchone()
                        if (finished and finished['state'] != 'queued'
                                or original_state and original_state['state'] != 'outcome_unknown'):
                            return previous_claim(account_id, binding_version, owner_id, generation,
                                above_priority=above_priority, kinds=kinds, parent_command_id=parent_command_id)
                        actor._assert_thread()
                        actor._check_owner()
                        recheck_plan()
                        if actor._stack or resource.manual_tasks or getattr(resource, 'console_tasks', {}):
                            raise ValueError('bridge_actor_became_busy')
                        with actor.store._db(write=True) as db:
                            actor.store._owner(db, account_id, owner_id, generation, binding_version)
                            original, queued = _rows(config, db)
                            if _digest(original) != plan['original_row_sha256'] or _digest(queued) != plan['queued_row_sha256']:
                                raise ValueError('bridge_original_command_changed_before_claim')
                            # This private bridge can only claim the already
                            # approved read-back, even if a caller passes None.
                            value = claim_function(actor.store, db, account_id, binding_version, owner_id, generation,
                                                   allowed_kinds=('publication_verify',))
                            if value and value['command_id'] != config['verification_command_id']:
                                raise ValueError('bridge_claim_selected_different_command')
                        return value
                    except loaded_rejection as error:
                        # Normalize to the old host's own exception class, but
                        # keep a pre-handler rejection out of run_next's host
                        # exit path. Store transaction has already rolled back.
                        mapped = old_rejection(getattr(error, 'code', 'bridge_rejected'), 'Reviewed bridge claim refused')
                        _record_failure(directory, 'claim', mapped)
                        return None
                    except Exception as error:
                        _record_failure(directory, 'claim', error)
                        return None

                guarded_claim._publication_claim_hot_plan = arm['plan']
                actor.store.claim_next = guarded_claim
                # Load the reviewed paused wrapper directly, without reloading
                # any canonical module or touching the old actor/session.
                guard_raw = SOURCE_PATHS['paused_guard'].read_bytes()
                guard_ns = {'__name__': 'src.operations_accounts._reviewed_paused_guard',
                            '__package__': 'src.operations_accounts'}
                exec(compile(guard_raw, str(SOURCE_PATHS['paused_guard']), 'exec'), guard_ns)
                guard_ns['install'](actor, resource, path=config['control_db'])
                namespace['_poll_manual_windows'] = previous_poll
                _write_once(directory / 'ACTOR_INSTALLED_RECEIPT.json', dict(
                    schema='publication_claim_hot_bridge_actor_install/v1', plan=arm['plan'],
                    backend_pid=os.getpid(), backend_create_time=_process(os.getpid()), owner_id=actor.owner_id,
                    generation=actor.generation, binding_version=actor.binding_version,
                    original_command_id=config['original_command_id'], verification_command_id=config['verification_command_id'],
                    actor_thread_id=threading.get_ident(), loaded_claim=loaded_proof,
                    old_rejection_module=old_rejection.__module__, paused_guard_reinstalled=True,
                    private_store_only=True, browser_actions=False, new_queue_entries=False))
            except Exception as error:
                if previous_claim is not None:
                    actor.store.claim_next = previous_claim
                namespace['_poll_manual_windows'] = previous_poll
                _record_failure(directory, 'actor_install', error)
            return previous_poll(actor, resource)

        poll._publication_claim_hot_plan = arm['plan']
        namespace['_poll_manual_windows'] = poll
        _write_once(directory / 'UI_IMPORT_RECEIPT.json', dict(
            schema='publication_claim_hot_bridge_ui_import/v1', plan=arm['plan'], backend_pid=os.getpid(),
            backend_create_time=_process(os.getpid()), callback_registered=True, actor_installed=False,
            browser_actions=False, new_queue_entries=False))
        return {'status': 'callback_registered_waiting_original_actor_tick'}
    except Exception as error:
        if directory is not None:
            _record_failure(directory, 'ui_import', error)
        return {'status': 'refused', 'error_type': type(error).__name__}
