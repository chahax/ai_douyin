"""Opt-in, exact-command runtime bridge for an observed native publication URL.

Preparation is read-only. UI loading registers a callback; only the existing
account actor's idle tick installs a private handler and atomic claim wrapper.
The prior publisher, automatic reads, locator policy and sessions are preserved.
"""
import hashlib
import inspect
import json
import marshal
import os
from pathlib import Path
import threading
import types

from . import publication_claim_hot_bridge_v1 as bridge

ROOT = bridge.ROOT
ARM = ROOT / 'data/publication_known_link_runtime_v1/ARM.json'
SOURCE_PATHS = {
    'runtime': Path(__file__).resolve(),
    'verification': ROOT / 'src/operations_accounts/publication_known_link_verification_v1.py',
    'core': ROOT / 'src/operations_accounts/publication_verification_recovery.py',
    'browser_core': ROOT / 'src/operations_accounts/browser_control.py',
    'app': ROOT / 'src/web/app.py',
}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _sources(config):
    _require(set(config['sources']) == set(SOURCE_PATHS), 'known_link_runtime_exact_sources_required')
    for name, path in SOURCE_PATHS.items():
        _require(bridge.reference(path) == config['sources'][name], 'known_link_runtime_source_changed:' + name)


def _config(ref):
    value = bridge._read(ref)
    _require(set(value) == {'schema', 'backend_pid', 'backend_create_time', 'account_key', 'account_id',
        'owner_id', 'generation', 'binding_version', 'browser_db',
        'sources', 'retire_provider'} and value['schema'] == 'publication_known_link_runtime_config/v1',
        'known_link_runtime_config_invalid')
    _require(type(value['backend_pid']) is int and type(value['generation']) is int
        and value['owner_id'].startswith('backend:' + str(value['backend_pid']) + ':')
        and bridge._process(value['backend_pid']) == value['backend_create_time'], 'known_link_runtime_process_changed')
    _sources(value)
    _require(set(value['retire_provider']) == {'plan', 'app_before_hook'}, 'known_link_runtime_retirement_scope_required')
    bridge._read(value['retire_provider']['plan'])
    archive = value['retire_provider']['app_before_hook']
    _require(bridge.reference(archive['path']) == archive, 'known_link_runtime_prior_app_archive_changed')
    return value


def _load(config, namespace=None):
    modules = {}
    for name in ('core', 'verification'):
        path = SOURCE_PATHS[name]
        raw = path.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == config['sources'][name]['sha256'], 'known_link_runtime_loaded_source_changed')
        module_name = 'src.operations_accounts._known_link_' + name + '_' + config['sources'][name]['sha256'][:16]
        module = types.ModuleType(module_name)
        module.__file__, module.__package__ = str(path), 'src.operations_accounts'
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        modules[name] = module
    adapter, core = modules['verification'], modules['core']
    adapter.core = core
    if namespace is not None:
        for module in (core, adapter):
            module.BrowserControlRejected = namespace['BrowserControlRejected']
            module.BrowserCommandResult = namespace['BrowserCommandResult']
    _require(tuple(inspect.signature(adapter.run).parameters) == ('ctx', 'session'), 'known_link_runtime_run_signature_changed')
    proof = dict(verification_source=config['sources']['verification'], core_source=config['sources']['core'],
        run_code_sha256=hashlib.sha256(marshal.dumps(adapter.run.__code__)).hexdigest(),
        isolated_modules=True, canonical_modules_replaced=False)
    return adapter, proof


def _intent(command):
    return {key: command[key] for key in ('command_id', 'account_id', 'binding_version', 'kind',
        'idempotency_key', 'payload', 'request_sha', 'priority', 'created_at')}


def _base_config(config):
    return {key: value for key, value in config.items()
        if key not in ('verification_command_id', 'verification_request_sha256')}


def _rows(config, request_ref, *, db=None, states=('queued',)):
    if db is None:
        with bridge._ro(config['browser_db']) as connection:
            return _rows(config, request_ref, db=connection, states=states)
    row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (config['verification_command_id'],)).fetchone()
    _require(row is not None, 'known_link_runtime_command_missing')
    command = bridge._parsed(row)
    _require(command['kind'] == 'publication_verify' and command['state'] in states
        and command['account_id'] == config['account_id'] and command['binding_version'] == config['binding_version']
        and command['request_sha'] == config['verification_request_sha256']
        and command['payload'].get('known_link_verification') == request_ref,
        'known_link_runtime_exact_command_changed')
    if command['state'] == 'queued':
        _require(command['owner_id'] is None and command['generation'] is None, 'known_link_runtime_queued_owner_changed')
    else:
        _require(command['owner_id'] == config['owner_id'] and command['generation'] == config['generation'],
            'known_link_runtime_running_owner_changed')
    original = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
        (command['payload']['original_command_id'],)).fetchone()
    _require(original is not None, 'known_link_runtime_original_missing')
    original = bridge._parsed(original)
    _require(original['kind'] == 'publish' and original['state'] == 'outcome_unknown'
        and original['account_id'] == config['account_id'] and original['binding_version'] == config['binding_version']
        and command['payload']['original_snapshot_sha256'] == bridge._digest(original),
        'known_link_runtime_original_unknown_changed')
    others = db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",
        (config['account_id'],)).fetchall()
    _require(all(x['command_id'] in (original['command_id'], command['command_id']) for x in others),
        'known_link_runtime_other_live_command')
    return original, command


def prepare_runtime(request_ref, config_ref, output_directory, *, store=None, context=None):
    """RO preflight; a later explicit ARM admits one local read at an idle tick."""
    config = _config(config_ref)
    request = bridge._read(request_ref)
    adapter, proof = _load(config)
    if store is None or context is None:
        from . import browser_control_runtime as runtime
        store = store if store is not None else runtime._store()
        context = context if context is not None else runtime._runtime().resolve(config['account_key'], require_healthy=False)
    validated = adapter.validate_request(request_ref, store=store, context=context)
    original = validated['original']
    _require(original['state'] == 'outcome_unknown' and original['account_id'] == config['account_id']
        and original['binding_version'] == config['binding_version'], 'known_link_runtime_original_scope_changed')
    with bridge._ro(config['browser_db']) as db:
        owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (config['account_id'],)).fetchone()
    _require(owner is not None and owner['owner_id'] == config['owner_id'] and owner['generation'] == config['generation']
        and owner['binding_version'] == config['binding_version'] and owner['state'] == 'active',
        'known_link_runtime_owner_changed')
    directory = Path(output_directory).resolve()
    _require(directory.is_relative_to(ROOT / 'data') and not directory.exists(), 'known_link_runtime_new_directory_required')
    directory.mkdir(parents=True)
    return bridge._write_once(directory / 'PLAN.json', dict(schema='publication_known_link_runtime_plan/v1',
        request=request_ref, config=config_ref, original_snapshot_sha256=bridge._digest(original),
        idempotency_key=request['idempotency_key'], loaded_code=proof, plan_only=True,
        business_tasks_created=0, armed_actor_tick_may_enqueue_one_known_link_read=True, installed=False))


def handler_ready(command, owner_id, generation):
    """Pure-file ready proof for this exact independent, known-link read."""
    try:
        ref = command['payload']['known_link_verification']
        ready = bridge._read(bridge.reference(Path(ref['path']).parent / 'KNOWN_LINK_HANDLER_READY.json'))
        plan = bridge._read(ready['plan'])
        config = bridge._read(plan['config'])
        _sources(config)
        bridge._read(plan['request'])
        receipt = bridge._read(ready['actor_install'])
        retirement = bridge._read(receipt['prior_provider_retirement'])
        return (ready['schema'] == 'publication_known_link_handler_ready/v1'
            and ready['request'] == ref == plan['request'] and ready['command_id'] == command['command_id']
            and ready['owner_id'] == owner_id == config['owner_id'] and ready['generation'] == generation == config['generation']
            and ready['account_id'] == command['account_id'] == config['account_id']
            and ready['binding_version'] == command['binding_version'] == config['binding_version']
            and ready['command_intent_sha256'] == bridge._digest(_intent(command)) == plan['command_intent_sha256']
            and receipt['plan'] == ready['plan'] and receipt['command_id'] == command['command_id']
            and receipt['owner_id'] == owner_id and receipt['generation'] == generation
            and receipt['backend_pid'] == config['backend_pid']
            and receipt['backend_create_time'] == config['backend_create_time']
            and receipt['loaded_code'] == plan['loaded_code']
            and retirement['prior_plan'] == config['retire_provider']['plan']
            and retirement['owner_id'] == owner_id and retirement['generation'] == generation
            and retirement['called_original_restore'] is True and retirement['policy_files_modified'] is False)
    except Exception:
        return False


def _retire_provider(actor, resource, config, original, directory):
    """Retire the exact installed provider after its three reads are terminal."""
    retirement = config['retire_provider']
    prior_plan = bridge._read(retirement['plan'])
    prior_scope = bridge._read(prior_plan['scope'])
    prior_config = bridge._read(prior_plan['config'])
    ready_path = Path(retirement['plan']['path']).parent / 'ACTOR_PROVIDER_READY.json'
    ready_ref = bridge.reference(ready_path)
    ready = bridge._read(ready_ref)
    _require(ready['plan'] == retirement['plan'] and ready['owner_id'] == config['owner_id']
        and ready['generation'] == config['generation'] and ready['backend_pid'] == config['backend_pid']
        and ready['backend_create_time'] == config['backend_create_time']
        and prior_scope['publisher']['command_id'] == original['command_id']
        and prior_scope['account_uuid'] == config['account_id'] and prior_scope['binding_version'] == config['binding_version']
        and prior_config['owner_id'] == config['owner_id'] and prior_config['generation'] == config['generation'],
        'known_link_runtime_prior_provider_scope_changed')
    for key, ref in prior_config['sources'].items():
        if key == 'app':
            _require(ref['sha256'] == retirement['app_before_hook']['sha256']
                and Path(ref['path']).resolve() == SOURCE_PATHS['app'], 'known_link_runtime_prior_app_pin_changed')
        else:
            _require(bridge.reference(ref['path']) == ref, 'known_link_runtime_prior_provider_source_changed')
    with bridge._ro(config['browser_db']) as db:
        autos = db.execute("SELECT * FROM browser_control_commands WHERE kind='publication_verify' AND json_extract(payload,'$.original_command_id')=? AND idempotency_key LIKE ? ORDER BY created_at",
            (original['command_id'], 'publication-verify:' + original['command_id'] + ':%')).fetchall()
    _require(len(autos) == 3 and all(row['state'] == 'failed' for row in autos)
        and {row['idempotency_key'] for row in autos} == {'publication-verify:' + original['command_id'] + ':' + str(i) for i in (1, 2, 3)},
        'known_link_runtime_three_auto_reads_not_terminal')
    values = [cell.cell_contents for cell in (getattr(resource.ensure_session, '__closure__', None) or ())]
    providers = [x for x in values if getattr(x, 'actor', None) is actor and getattr(x, 'resource', None) is resource
        and getattr(x, 'plan_ref', None) == retirement['plan'] and callable(getattr(x, 'restore', None))]
    _require(len(providers) == 1, 'known_link_runtime_exact_provider_instance_missing')
    provider = providers[0]
    _require(resource.ensure_session is getattr(provider, 'ensure_wrapper', None)
        and actor.store.claim_next is getattr(provider, 'claim_wrapper', None)
        and provider.scope == prior_scope and provider.config == prior_config and provider.plan == prior_plan,
        'known_link_runtime_provider_instance_binding_changed')
    owner = resource.session
    _require(all(session.cmd is wrapper and getattr(wrapper, '_publication_locator_provider', None) == retirement['plan']
        for session, _, wrapper in provider.sessions.values())
        and (owner is None or (id(owner) in provider.sessions and provider.sessions[id(owner)][0] is owner
            and owner.cmd is provider.sessions[id(owner)][2])),
        'known_link_runtime_provider_owner_session_changed')
    restore_source = Path(provider.restore.__func__.__code__.co_filename).resolve()
    _require(bridge.reference(restore_source) == prior_config['sources']['provider'], 'known_link_runtime_provider_restore_code_changed')
    provider.restore()
    _require(resource.ensure_session is provider.previous_ensure and actor.store.claim_next is provider.previous_claim
        and all(session.cmd is previous for session, previous, _ in provider.sessions.values()),
        'known_link_runtime_provider_restore_incomplete')
    return bridge._write_once(directory / 'PRIOR_PROVIDER_RETIRED.json', dict(
        schema='publication_known_link_provider_retirement/v1', prior_plan=retirement['plan'], prior_ready=ready_ref,
        prior_app_archive=retirement['app_before_hook'], new_app_source=config['sources']['app'],
        original_publish_command_id=original['command_id'], prior_auto_commands=[row['command_id'] for row in autos],
        owner_id=actor.owner_id, generation=actor.generation, actor_thread_id=threading.get_ident(),
        called_original_restore=True, policy_files_modified=False, browser_or_queue_actions=False))


def _install_actor(actor, resource, namespace, plan_ref, plan, config, directory, adapter, proof, retired_ref):
    actor._assert_thread()
    actor._check_owner()
    _require(not actor._stack and not resource.manual_tasks and not getattr(resource, 'console_tasks', {}),
        'known_link_runtime_actor_busy')
    _require(actor.account_id == config['account_id'] == resource.account_uuid
        and actor.owner_id == config['owner_id'] and actor.generation == config['generation']
        and actor.binding_version == config['binding_version']
        and Path(actor.store.path).resolve() == Path(config['browser_db']).resolve(), 'known_link_runtime_actor_changed')
    original, command = _rows(config, plan['request'])
    _require(bridge._digest(command) == plan['queued_snapshot_sha256'], 'known_link_runtime_prepared_command_changed')
    adapter.validate_request(plan['request'], store=actor.store, context=resource.context, command=command)
    previous_handler, previous_claim = actor.handlers['publication_verify'], actor.store.claim_next
    previous_delegate = getattr(previous_claim, '_known_link_previous_claim', previous_claim)
    old_rejection, old_result = namespace['BrowserControlRejected'], namespace['BrowserCommandResult']

    def guard():
        actor._assert_thread()
        actor._check_owner()
        _require(bridge._read(plan_ref) == plan and _config(plan['config']) == _base_config(config),
            'known_link_runtime_plan_changed')
        _require(actor.owner_id == config['owner_id'] and actor.generation == config['generation']
            and actor.account_id == config['account_id'] == resource.account_uuid
            and actor.binding_version == config['binding_version'], 'known_link_runtime_owner_changed')

    def restore(keep_hold=False):
        if actor.handlers.get('publication_verify') is selective:
            actor.handlers['publication_verify'] = previous_handler
        if actor.store.claim_next is exact_claim:
            actor.store.claim_next = previous_claim if keep_hold else previous_delegate

    def scoped(ctx, payload):
        guard()
        ctx.check_dispatch()
        _require(ctx.actor is actor and ctx.resource is resource and ctx.task_id == config['verification_command_id'],
            'known_link_runtime_context_changed')
        _, current = _rows(config, plan['request'], states=('running',))
        _require(bridge._digest(_intent(current)) == plan['command_intent_sha256'], 'known_link_runtime_running_intent_changed')
        adapter.validate_request(plan['request'], store=actor.store, context=resource.context, command=current)
        with resource.runtime.operation_lease(resource.context, operation='publication-verification-read', daily_limit=20, cooldown_seconds=0):
            resource.ensure_session()
            session = namespace['BorrowedSession'](resource, 'publication-verification-read')
            try:
                return adapter.run(ctx, session)
            except old_rejection as error:
                if error.code in {'owner_unknown', 'owner_fenced', 'command_fenced'}:
                    raise
                return old_result('failed', {'status': 'verification_blocked', 'reason': error.code})
            except Exception as error:
                return old_result('failed', {'status': 'verification_pending', 'reason': 'read_failed', 'error_type': type(error).__name__})
            finally:
                session.stop()

    wrapped = namespace['_with_active'](scoped)

    def selective(ctx, payload):
        if ctx.task_id != config['verification_command_id']:
            return previous_handler(ctx, payload)
        try:
            return wrapped(ctx, payload)
        finally:
            restore()

    def exact_claim(account_id, binding_version, owner_id, generation, *, above_priority=None, kinds=None, parent_command_id=None):
        args = dict(above_priority=above_priority, kinds=kinds, parent_command_id=parent_command_id)
        if (account_id, binding_version, owner_id, generation) != (config['account_id'], config['binding_version'], config['owner_id'], config['generation']) or above_priority is not None or parent_command_id is not None:
            return previous_claim(account_id, binding_version, owner_id, generation, **args)
        current = actor.store.get(config['verification_command_id'])
        if not current or current['state'] != 'queued':
            return previous_claim(account_id, binding_version, owner_id, generation, **args)
        if kinds is not None and 'publication_verify' not in kinds:
            return None
        try:
            guard()
            _require(not actor._stack and not resource.manual_tasks and not getattr(resource, 'console_tasks', {}),
                'known_link_runtime_actor_became_busy')
            _require(actor.handlers.get('publication_verify') is selective
                and handler_ready(current, owner_id, generation), 'known_link_runtime_handler_not_ready')
            adapter.validate_request(plan['request'], store=actor.store, context=resource.context, command=current)
            with actor.store._db(write=True) as db:
                actor.store._owner(db, account_id, owner_id, generation, binding_version)
                original, queued = _rows(config, plan['request'], db=db)
                _require(bridge._digest(original) == plan['original_snapshot_sha256']
                    and bridge._digest(queued) == plan['queued_snapshot_sha256'], 'known_link_runtime_atomic_snapshot_changed')
                adapter.validate_request(plan['request'], store=actor.store, context=resource.context, command=queued, db=db)
                db.execute("UPDATE browser_control_commands SET state='running',owner_id=?,generation=?,updated_at=? WHERE command_id=? AND state='queued'",
                    (owner_id, generation, actor.store.clock(), config['verification_command_id']))
                from .browser_execution_journal import record
                claimed = actor.store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (config['verification_command_id'],)).fetchone())
                record(db, claimed, 'admission_pending', actor.store.clock())
                return claimed
        except Exception as error:
            bridge._record_failure(directory, 'known_link_claim', error)
            return None

    actor.handlers['publication_verify'], actor.store.claim_next = selective, exact_claim
    try:
        install_ref = bridge._write_once(directory / 'ACTOR_INSTALLED_RECEIPT.json', dict(
            schema='publication_known_link_actor_install/v1', plan=plan_ref, backend_pid=os.getpid(),
            admission_plan=plan['admission_plan'],
            backend_create_time=config['backend_create_time'], owner_id=actor.owner_id, generation=actor.generation,
            command_id=config['verification_command_id'], actor_thread_id=threading.get_ident(), loaded_code=proof,
            prior_provider_retirement=retired_ref, private_handler_and_claim_only=True, browser_actions=False, new_business_tasks=0))
        bridge._write_once(Path(plan['request']['path']).parent / 'KNOWN_LINK_HANDLER_READY.json', dict(
            schema='publication_known_link_handler_ready/v1', plan=plan_ref, request=plan['request'], actor_install=install_ref,
            command_id=config['verification_command_id'], account_id=actor.account_id, binding_version=actor.binding_version,
            owner_id=actor.owner_id, generation=actor.generation, command_intent_sha256=plan['command_intent_sha256']))
    except Exception:
        restore(keep_hold=True)
        raise


def _admit_at_idle(actor, resource, namespace, admission_ref, admission, config, directory, adapter, proof):
    """The actor cannot call run_next between local admission and installation."""
    actor._assert_thread()
    actor._check_owner()
    _require(actor.account_id == resource.account_uuid == config['account_id']
        and actor.owner_id == config['owner_id'] and actor.generation == config['generation']
        and actor.binding_version == config['binding_version']
        and Path(actor.store.path).resolve() == Path(config['browser_db']).resolve()
        and not actor._stack and not resource.manual_tasks and not getattr(resource, 'console_tasks', {}),
        'known_link_runtime_admission_actor_changed')
    validated = adapter.validate_request(admission['request'], store=actor.store, context=resource.context)
    original = validated['original']
    _require(bridge._digest(original) == admission['original_snapshot_sha256'], 'known_link_runtime_original_before_admission_changed')
    hold = actor.store.claim_next
    if getattr(hold, '_known_link_admission_plan', None) == admission_ref:
        retired_ref = bridge.reference(directory / 'PRIOR_PROVIDER_RETIRED.json')
        retired = bridge._read(retired_ref)
        _require(retired['prior_plan'] == config['retire_provider']['plan'] and retired['owner_id'] == actor.owner_id
            and retired['generation'] == actor.generation and retired['called_original_restore'] is True,
            'known_link_runtime_admission_resume_changed')
    else:
        retired_ref = _retire_provider(actor, resource, config, original, directory)
        previous_claim = actor.store.claim_next

        def hold_claim(account_id, binding_version, owner_id, generation, **kwargs):
            if (account_id, binding_version, owner_id, generation) == (
                    config['account_id'], config['binding_version'], config['owner_id'], config['generation']):
                try:
                    with bridge._ro(config['browser_db']) as db:
                        row = db.execute("SELECT state FROM browser_control_commands WHERE account_id=? AND idempotency_key=?",
                            (account_id, admission['idempotency_key'])).fetchone()
                    if row is not None and row['state'] == 'queued':
                        return None  # No fall-through to the cached handler.
                except Exception as error:
                    bridge._record_failure(directory, 'known_link_hold', error)
                    return None
            return previous_claim(account_id, binding_version, owner_id, generation, **kwargs)

        hold_claim._known_link_admission_plan = admission_ref
        hold_claim._known_link_previous_claim = previous_claim
        actor.store.claim_next = hold_claim
    intent = dict(schema='publication_known_link_enqueue_intent/v1', admission_plan=admission_ref,
        request=admission['request'], account_id=config['account_id'], idempotency_key=admission['idempotency_key'],
        max_local_enqueue_calls=1, upload_or_publish_allowed=False)
    intent_path = directory / 'QUEUE_INTENT.json'
    # A previous local call without a receipt is recovered by the existing key;
    # its absence never authorizes a second enqueue.
    already_intended = intent_path.exists()
    bridge._write_once(intent_path, intent)
    enqueue_error = None
    if not already_intended:
        try:
            adapter.enqueue(admission['request'], store=actor.store, runtime=resource.runtime)
        except Exception as error:
            enqueue_error = error
            bridge._record_failure(directory, 'known_link_enqueue', error)
    with bridge._ro(config['browser_db']) as db:
        row = db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
            (config['account_id'], admission['idempotency_key'])).fetchone()
    _require(row is not None, 'known_link_runtime_local_enqueue_receipt_unknown')
    command = bridge._parsed(row)
    effective = dict(config, verification_command_id=command['command_id'], verification_request_sha256=command['request_sha'])
    _, command = _rows(effective, admission['request'])
    adapter.validate_request(admission['request'], store=actor.store, context=resource.context, command=command)
    receipt_path = directory / 'QUEUE_RECEIPT.json'
    if receipt_path.exists():
        queue_receipt = bridge.reference(receipt_path)
        previous_receipt = bridge._read(queue_receipt)
        _require(previous_receipt['intent'] == bridge.reference(intent_path)
            and previous_receipt['command_id'] == command['command_id']
            and previous_receipt['request_sha256'] == command['request_sha'], 'known_link_runtime_existing_enqueue_receipt_changed')
    else:
        queue_receipt = bridge._write_once(receipt_path, dict(
            schema='publication_known_link_enqueue_receipt/v1', intent=bridge.reference(intent_path),
            command_id=command['command_id'], request_sha256=command['request_sha'],
            recovered_from_exact_key=already_intended or enqueue_error is not None))
    actual = dict(schema='publication_known_link_actual_command_plan/v1', admission_plan=admission_ref,
        request=admission['request'], config=admission['config'], original_snapshot_sha256=admission['original_snapshot_sha256'],
        command_intent_sha256=bridge._digest(_intent(command)), queued_snapshot_sha256=bridge._digest(command),
        loaded_code=proof, queue_receipt=queue_receipt, command_id=command['command_id'])
    actual_ref = bridge._write_once(directory / 'ACTUAL_COMMAND_PLAN.json', actual)
    _install_actor(actor, resource, namespace, actual_ref, actual, effective, directory, adapter, proof, retired_ref)
    # The exact handler's outer finally restores this delegate, rather than the
    # temporary hold. Failed installation deliberately leaves the hold in place.


def install_if_armed():
    """UI import is inert without a new exact ARM; never installs on UI thread."""
    if not ARM.is_file():
        return {'status': 'not_armed'}
    directory = None
    try:
        arm_ref = bridge.reference(ARM)
        arm = bridge._read(arm_ref)
        _require(set(arm) == {'schema', 'plan'} and arm['schema'] == 'publication_known_link_runtime_arm/v1', 'known_link_runtime_arm_invalid')
        plan_ref = arm['plan']
        plan = bridge._read(plan_ref)
        directory = Path(plan_ref['path']).parent
        _require(plan['schema'] == 'publication_known_link_runtime_plan/v1', 'known_link_runtime_plan_invalid')
        config = _config(plan['config'])
        if os.getpid() != config['backend_pid']:
            return {'status': 'different_process_no_install'}
        if (directory / 'ACTOR_INSTALLED_RECEIPT.json').exists():
            installed = bridge._read(bridge.reference(directory / 'ACTOR_INSTALLED_RECEIPT.json'))
            actual = bridge._read(installed['plan'])
            _require(installed['admission_plan'] == plan_ref == actual['admission_plan']
                and installed['command_id'] == actual['command_id']
                and installed['owner_id'] == config['owner_id'] and installed['generation'] == config['generation']
                and installed['backend_pid'] == config['backend_pid'] and installed['backend_create_time'] == config['backend_create_time']
                and installed['loaded_code'] == plan['loaded_code'], 'known_link_runtime_prior_install_receipt_changed')
            return {'status': 'actor_install_already_recorded'}
        threads = [t for t in threading.enumerate() if t.name == 'AccountBrowser-' + config['account_key'] and t.is_alive()
            and getattr(getattr(t, '_target', None), '__name__', '') == '_host'
            and Path(t._target.__code__.co_filename).resolve() == bridge.HOST_PATH
            and getattr(t, '_args', ()) == (config['account_key'],)]
        _require(len(threads) == 1, 'known_link_runtime_unique_original_thread_required')
        namespace = threads[0]._target.__globals__
        previous_poll = namespace['_poll_manual_windows']
        if getattr(previous_poll, '_known_link_runtime_plan', None) == plan_ref:
            return {'status': 'callback_already_registered'}
        adapter, proof = _load(config, namespace)
        _require(proof == plan['loaded_code'], 'known_link_runtime_loaded_code_changed')

        def poll(actor, resource):
            if (actor.account_id, actor.owner_id, actor.generation) != (config['account_id'], config['owner_id'], config['generation']):
                return previous_poll(actor, resource)
            try:
                actor._assert_thread()
                actor._check_owner()
                _require(bridge.reference(ARM) == arm_ref, 'known_link_runtime_arm_changed')
                _require(bridge._read(plan_ref) == plan and _config(plan['config']) == config, 'known_link_runtime_plan_changed')
                if actor._stack or resource.manual_tasks or getattr(resource, 'console_tasks', {}):
                    return previous_poll(actor, resource)
                _admit_at_idle(actor, resource, namespace, plan_ref, plan, config, directory, adapter, proof)
            except Exception as error:
                bridge._record_failure(directory, 'known_link_install', error)
            namespace['_poll_manual_windows'] = previous_poll
            return previous_poll(actor, resource)

        poll._known_link_runtime_plan = plan_ref
        namespace['_poll_manual_windows'] = poll
        bridge._write_once(directory / 'UI_IMPORT_RECEIPT.json', dict(schema='publication_known_link_ui_import/v1',
            plan=plan_ref, backend_pid=os.getpid(), callback_registered=True, actor_installed=False))
        return {'status': 'callback_registered_waiting_actor_tick'}
    except Exception as error:
        if directory is not None:
            bridge._record_failure(directory, 'known_link_ui_import', error)
        return {'status': 'refused', 'error_type': type(error).__name__}
