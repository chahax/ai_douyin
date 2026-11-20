"""Private CPU runtime boundaries; no real service/ARM/browser/platform calls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import psutil
import pytest

from src.operations_accounts import publication_known_link_runtime_v1 as api
from src.operations_accounts import publication_locator_provider_v1 as locator
from src.operations_accounts import publication_claim_hot_bridge_v1 as bridge
from src.operations_accounts.browser_control import BrowserControlStore, BrowserCommandResult


class OldRejected(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    return bridge.reference(path)


@pytest.fixture
def case(tmp_path, monkeypatch):
    sources = {}
    for key, source in api.SOURCE_PATHS.items():
        path = tmp_path / ('source_' + key + '.py')
        path.write_bytes(source.read_bytes())
        sources[key] = path
    sources['verification'].write_text('''import json
from pathlib import Path
from .browser_control import BrowserCommandResult, BrowserControlRejected
def validate_request(ref, *, store, context, command=None, db=None):
    value=json.loads(Path(ref['path']).read_text(encoding='utf8'))
    return {'request':value,'original':value['original'],'target_url':'https://www.douyin.com/video/7709043480894524722'}
def enqueue(ref, *, store, runtime):
    runtime.events.append('enqueue_called')
    value=json.loads(Path(ref['path']).read_text(encoding='utf8'))
    original=value['original']
    payload=dict(original_command_id=original['command_id'],original_snapshot_sha256=value['original_sha'],
        known_link_verification=ref,account_key=value['account_key'],attempt=4,known_link_read_index=1,
        verification_purpose='explicit_known_native_link')
    row=store.submit(value['account_uuid'],value['binding_version'],'publication_verify',value['idempotency_key'],payload,400)
    if getattr(runtime,'lose_enqueue_receipt',False):raise RuntimeError('simulated local receipt loss')
    return {'command_id':row['command_id']}
def run(ctx, session):
    if getattr(ctx, 'raise_old', False):
        raise BrowserControlRejected('read_only_blocked', 'private test')
    session.open_page('https://www.douyin.com/video/7709043480894524722')
    return {'status': 'verified_published', 'private_test_only': True}
''', encoding='utf8')
    monkeypatch.setattr(api, 'SOURCE_PATHS', sources)
    arm = tmp_path / 'ARM.json'
    monkeypatch.setattr(api, 'ARM', arm)
    store = BrowserControlStore(tmp_path / 'browser.db')
    account, binding = 'account:known-link-test', 'binding-original'
    owner_id = 'backend:' + str(os.getpid()) + ':known-link-test'
    generation = store.acquire_owner(account, binding, owner_id)['generation']
    original = store.submit(account, binding, 'publish', 'publish:immutable', {'request': {'title': '两分钟完整版'}, 'video_sha256': 'new-two-minute'}, 100)
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id=?,generation=?,result=? WHERE command_id=?",
            (owner_id, generation, json.dumps({'status': 'submission_unknown'}), original['command_id']))
    original = store.get(original['command_id'])
    autos = []
    for number in (1, 2, 3):
        row = store.submit(account, binding, 'publication_verify', 'publication-verify:' + original['command_id'] + ':' + str(number),
            {'original_command_id': original['command_id'], 'attempt': number}, 400)
        with store._db(write=True) as db:
            db.execute("UPDATE browser_control_commands SET state='failed',result=? WHERE command_id=?",
                (json.dumps({'status': 'verification_pending'}), row['command_id']))
        autos.append(row['command_id'])
    key = 'known-link:' + original['command_id'] + ':frozen-baseline'
    request = put(tmp_path / 'request/REQUEST.json', {'schema': 'private_request', 'original': original,
        'original_sha':bridge._digest(original),'account_uuid':account,'account_key':'novel-test',
        'binding_version':binding,'idempotency_key':key})
    events = []
    def previous_claim(*args, **kwargs):
        events.append(('previous_claim', args, kwargs))
        return None
    store.claim_next = previous_claim
    def previous_handler(ctx, payload):
        events.append('previous_handler')
        if payload.get('raise_old'):
            raise OldRejected('old_handler_error', 'old unchanged')
        return 'old-return'
    actor = NS(account_id=account, binding_version=binding, owner_id=owner_id, generation=generation,
        store=store, _stack=[], handlers={'publication_verify': previous_handler},
        _assert_thread=lambda: events.append(('actor_thread', threading.get_ident())), _check_owner=lambda: events.append('owner_checked'))
    owner = NS(cmd=lambda action, **kwargs: ('original_rpc', action, kwargs))
    @contextmanager
    def lease(*args, **kwargs):
        events.append('lease_enter')
        yield
        events.append('lease_exit')
    resource = NS(account_uuid=account, manual_tasks={}, console_tasks={}, session=owner,
        context=NS(account_uuid=account, account_key='novel-test'), runtime=NS(operation_lease=lease, events=events), ensure_session=lambda: owner)
    def previous_poll(actor, resource):
        events.append('previous_poll')
    class Session:
        def __init__(self, resource, role):events.append('borrowed_session')
        def open_page(self, url):events.append(('open_page', url))
        def stop(self):events.append('session_stop')
    namespace = dict(_poll_manual_windows=previous_poll, BrowserControlRejected=OldRejected,
        BrowserCommandResult=BrowserCommandResult, BorrowedSession=Session, _with_active=lambda function: function,
        active_context=lambda: None)
    exec(compile('def _host(key):\n    return None\n', str(bridge.HOST_PATH), 'exec'), namespace)
    thread = NS(name='AccountBrowser-novel-test', _target=namespace['_host'], _args=('novel-test',), is_alive=lambda: True)
    monkeypatch.setattr(api.threading, 'enumerate', lambda: [thread])
    # Exact old-provider object, wrappers and restore implementation, with an
    # explicitly archived prior app hash for the intentional new inert hook.
    archive = tmp_path / 'prior_app.py'
    archive.write_text('# prior reviewed app\n', encoding='utf8')
    prior_app = dict(path=str(sources['app'].resolve()), sha256=bridge.reference(archive)['sha256'])
    prior_config_value = dict(owner_id=owner_id, generation=generation,
        sources={'provider': bridge.reference(Path(locator.__file__)), 'app': prior_app})
    prior_config = put(tmp_path / 'prior_provider/CONFIG.json', prior_config_value)
    prior_scope_value = dict(publisher={'command_id': original['command_id']}, account_uuid=account, binding_version=binding)
    prior_scope = put(tmp_path / 'prior_provider/SCOPE.json', prior_scope_value)
    prior_plan_value = dict(scope=prior_scope, config=prior_config)
    prior_plan = put(tmp_path / 'prior_provider/PLAN.json', prior_plan_value)
    put(tmp_path / 'prior_provider/ACTOR_PROVIDER_READY.json', dict(plan=prior_plan, owner_id=owner_id, generation=generation,
        backend_pid=os.getpid(), backend_create_time=psutil.Process().create_time()))
    provider = locator._Provider(actor, resource, namespace, prior_plan, prior_plan_value, prior_scope_value, prior_config_value, None)
    provider.install()
    config = dict(schema='publication_known_link_runtime_config/v1', backend_pid=os.getpid(), backend_create_time=psutil.Process().create_time(),
        account_key='novel-test', account_id=account, owner_id=owner_id, generation=generation, binding_version=binding,
        browser_db=str(store.path),
        sources={k: bridge.reference(v) for k, v in sources.items()},
        retire_provider={'plan': prior_plan, 'app_before_hook': bridge.reference(archive)})
    config_ref = put(tmp_path / 'CONFIG.json', config)
    return NS(folder=tmp_path, arm=arm, config=config, config_ref=config_ref, store=store, original=original, queued=None, key=key,
        request=request, actor=actor, resource=resource, namespace=namespace, previous_poll=previous_poll,
        previous_handler=previous_handler, previous_claim=previous_claim, provider=provider, owner=owner, events=events, sources=sources, autos=autos)


def prepare(case):
    return api.prepare_runtime(case.request, case.config_ref, case.folder / 'runtime', store=case.store, context=case.resource.context)


def install(case):
    ref = prepare(case)
    put(case.arm, dict(schema='publication_known_link_runtime_arm/v1', plan=ref))
    assert api.install_if_armed()['status'] == 'callback_registered_waiting_actor_tick'
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert (case.folder / 'runtime/ACTOR_INSTALLED_RECEIPT.json').is_file()
    case.queued = queued(case)
    return ref


def queued(case):
    with case.store._db() as db:
        return case.store._command(db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
            (case.config['account_id'], case.key)).fetchone())


def claim(case, **kwargs):
    c = case.config
    return case.store.claim_next(c['account_id'], c['binding_version'], c['owner_id'], c['generation'], **kwargs)


def context(case, command=None):
    command = command or case.store.get(case.queued['command_id'])
    return NS(task_id=command['command_id'], command=command, actor=case.actor, resource=case.resource,
        check_dispatch=lambda: case.events.append('dispatch_guard'))


def test_plan_and_ui_are_readonly(case):
    assert api.install_if_armed() == {'status': 'not_armed'}
    before = queued(case)
    ref = prepare(case)
    put(case.arm, dict(schema='publication_known_link_runtime_arm/v1', plan=ref))
    assert api.install_if_armed()['status'] == 'callback_registered_waiting_actor_tick'
    assert api.install_if_armed()['status'] == 'callback_already_registered'
    assert queued(case) is before is None
    assert 'enqueue_called' not in case.events
    assert not (case.folder / 'runtime/ACTOR_INSTALLED_RECEIPT.json').exists()
    assert case.resource.ensure_session is case.provider.ensure_wrapper


def test_exact_claim_runs_read_restores_old_instances_and_preserves_unknown(case):
    install(case)
    assert api.install_if_armed()['status'] == 'actor_install_already_recorded'
    assert case.resource.ensure_session is case.provider.previous_ensure
    assert case.owner.cmd is case.provider.sessions[id(case.owner)][1]
    value = claim(case)
    assert value['command_id'] == case.queued['command_id'] and value['state'] == 'running'
    result = case.actor.handlers['publication_verify'](context(case, value), value['payload'])
    assert result['status'] == 'verified_published'
    assert case.actor.handlers['publication_verify'] is case.previous_handler
    assert case.store.claim_next is case.previous_claim
    assert case.store.get(case.original['command_id']) == case.original
    assert len([x for x in case.events if isinstance(x, tuple) and x[0] == 'open_page']) == 1
    assert (case.folder / 'runtime/PRIOR_PROVIDER_RETIRED.json').is_file()


def test_busy_idle_tick_defers_without_retiring_provider(case):
    ref = prepare(case)
    put(case.arm, dict(schema='publication_known_link_runtime_arm/v1', plan=ref))
    api.install_if_armed()
    for busy in ('stack','manual','console'):
        if busy == 'stack':case.actor._stack.append('busy')
        else:getattr(case.resource, busy + '_tasks')['original'] = 'original'
        case.namespace['_poll_manual_windows'](case.actor, case.resource)
        assert case.resource.ensure_session is case.provider.ensure_wrapper
        assert queued(case) is None
        assert 'enqueue_called' not in case.events
        assert not (case.folder / 'runtime/ACTOR_INSTALLED_RECEIPT.json').exists()
        case.actor._stack.clear();case.resource.manual_tasks.clear();case.resource.console_tasks.clear()


@pytest.mark.parametrize('failure', ['source', 'owner', 'ready'])
def test_changed_source_owner_or_missing_ready_never_claims(case, failure):
    install(case)
    if failure == 'source':case.sources['verification'].write_text('# changed\n', encoding='utf8')
    elif failure == 'owner':case.actor.owner_id += ':changed'
    else:(case.folder / 'request/KNOWN_LINK_HANDLER_READY.json').unlink()
    assert claim(case) is None
    assert queued(case)['state'] == 'queued'
    assert case.store.get(case.original['command_id']) == case.original


def test_nonterminal_auto_does_not_retire_provider(case):
    ref = prepare(case)
    with case.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='running' WHERE command_id=?", (case.autos[-1],))
    put(case.arm, dict(schema='publication_known_link_runtime_arm/v1', plan=ref))
    api.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert case.resource.ensure_session is case.provider.ensure_wrapper
    assert queued(case) is None


def test_named_handler_catches_native_old_exception_and_finally_restores(case):
    install(case)
    value = claim(case)
    ctx = context(case, value)
    ctx.raise_old = True
    result = case.actor.handlers['publication_verify'](ctx, value['payload'])
    assert type(result) is BrowserCommandResult and result.state == 'failed'
    assert result.result['reason'] == 'read_only_blocked'
    assert case.actor.handlers['publication_verify'] is case.previous_handler
    assert case.store.claim_next is case.previous_claim


def test_unrelated_handler_and_rpc_return_identity_unchanged(case):
    install(case)
    other = NS(task_id='unrelated-original')
    assert case.actor.handlers['publication_verify'](other, {}) == 'old-return'
    with pytest.raises(OldRejected) as error:
        case.actor.handlers['publication_verify'](other, {'raise_old': True})
    assert error.value.code == 'old_handler_error'
    assert case.owner.cmd('unrelated_rpc', value='same') == ('original_rpc', 'unrelated_rpc', {'value': 'same'})
    assert claim(case, kinds=('read',)) is None


def test_changed_payload_after_install_is_not_claimed(case):
    install(case)
    with case.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET payload=json_set(payload,'$.attempt',5) WHERE command_id=?", (case.queued['command_id'],))
    assert claim(case) is None
    assert case.store.get(case.queued['command_id'])['state'] == 'queued'


@pytest.mark.parametrize('failure', ['wrong_thread', 'wrong_provider_marker'])
def test_wrong_thread_or_provider_binding_is_never_retired(case, failure):
    ref = prepare(case)
    put(case.arm, dict(schema='publication_known_link_runtime_arm/v1', plan=ref))
    api.install_if_armed()
    if failure == 'wrong_thread':
        def refuse_thread():raise OldRejected('wrong_thread', 'not actor thread')
        case.actor._assert_thread = refuse_thread
    else:
        case.owner.cmd._publication_locator_provider = {'path': 'wrong', 'sha256': 'wrong'}
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert case.resource.ensure_session is case.provider.ensure_wrapper
    assert queued(case) is None
    assert not (case.folder / 'runtime/ACTOR_INSTALLED_RECEIPT.json').exists()


def test_normal_idle_closed_session_does_not_open_browser_for_retirement(case):
    ref = prepare(case)
    case.resource.session = None
    put(case.arm, dict(schema='publication_known_link_runtime_arm/v1', plan=ref))
    api.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert case.resource.session is None
    assert case.resource.ensure_session is case.provider.previous_ensure
    assert (case.folder / 'runtime/PRIOR_PROVIDER_RETIRED.json').is_file()
    assert not any(isinstance(x, tuple) and x[0] == 'open_page' for x in case.events)


def test_enqueue_receipt_loss_recovers_exact_local_key_without_another_call(case):
    case.resource.runtime.lose_enqueue_receipt = True
    install(case)
    assert case.events.count('enqueue_called') == 1
    receipt=json.loads((case.folder/'runtime/QUEUE_RECEIPT.json').read_text(encoding='utf8'))
    assert receipt['recovered_from_exact_key'] is True
    assert claim(case)['command_id'] == case.queued['command_id']


def test_post_enqueue_install_failure_keeps_hold_and_resumes_same_cid(case, monkeypatch):
    original_install = api._install_actor
    monkeypatch.setattr(api, '_install_actor', lambda *args: (_ for _ in ()).throw(RuntimeError('simulated install gap')))
    ref=prepare(case);put(case.arm,dict(schema='publication_known_link_runtime_arm/v1',plan=ref))
    api.install_if_armed();case.namespace['_poll_manual_windows'](case.actor,case.resource)
    first=queued(case)
    assert first is not None and first['state']=='queued'
    assert claim(case) is None
    assert not any(isinstance(x,tuple) and x[0]=='previous_claim' for x in case.events)
    assert case.events.count('enqueue_called')==1
    monkeypatch.setattr(api,'_install_actor',original_install)
    assert api.install_if_armed()['status']=='callback_registered_waiting_actor_tick'
    case.namespace['_poll_manual_windows'](case.actor,case.resource)
    assert queued(case)['command_id']==first['command_id']
    assert case.events.count('enqueue_called')==1
    assert claim(case)['command_id']==first['command_id']
