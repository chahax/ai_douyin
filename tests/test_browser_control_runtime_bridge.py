"""Business bridge invariants; no real profile, browser or production store."""
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserControlRejected, BrowserControlDeferred
from src.platform_adapter.models import PublishRequest


def context(status='active'):
    from src.operations_accounts.runtime import AccountRuntimeContext
    binding = NS(account_uuid='acct:one', account_key='one', platform_identity_key='public:123',
        browser_environment_key='env:one', browser_profile_dir='profile/one', storage_state_path='state/one',
        confirmed_by='user', created_at='2026', status=status)
    return AccountRuntimeContext(binding=binding,
        profile=NS(profile_version=1, account_uuid='acct:one', account_key='one', status='active'),
        browser_environment_key='env:one', browser_profile_dir='profile/one',
        storage_state_path='state/one')


class Owner:
    def __init__(self):
        self.config = NS(headless=True)
        self.calls, self.tabs, self.closed = [], [], []

    def new_tab(self, role):
        self.tabs.append(role)
        return NS(tab_id='tab-' + str(len(self.tabs)), url='about:blank')

    def cmd(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return {'url': kwargs.get('url', 'about:blank'), 'result': None, 'count': 0}

    def close_tab(self, tab_id):
        self.closed.append(tab_id)

    def _check_domain_allowed(self, url):
        pass


@pytest.fixture(autouse=True)
def reset_active_context():
    token = bridge._active.set(None)
    try:
        yield
    finally:
        bridge._active.reset(token)


def borrowed(ctx=None):
    bridge._active.set(ctx or NS(check_dispatch=lambda: None))
    owner = Owner()
    resource = NS(ensure_session=lambda: owner)
    return owner, bridge.BorrowedSession(resource, 'playback')


def test_every_page_and_locator_command_rechecks_dispatch_and_routes_owned_tab():
    checks = []
    ctx = NS(check_dispatch=lambda: checks.append('checked'))
    owner, session = borrowed(ctx)
    checks.clear()
    token = bridge._active.set(ctx)
    try:
        page = session.open_page('https://www.douyin.com/')
        page.evaluate('1')
        page.locator('input').fill('x')
        page.locator('button').click()
    finally:
        bridge._active.reset(token)
    assert len(owner.calls) == 4 and len(checks) >= len(owner.calls)
    assert all(kwargs['tab_id'] == session.tab_id for _, kwargs in owner.calls)
    assert session.get_page() is page


def test_borrower_rejects_other_tabs_and_owner_lifecycle():
    owner, session = borrowed()
    with pytest.raises(BrowserControlRejected, match='其他标签'):
        session.cmd('evaluate', tab_id='some-other', js='1')
    for action in ('new_tab', 'close_tab', 'wait_for_close', 'stop'):
        with pytest.raises(BrowserControlRejected):
            session.cmd(action)
    session.stop()
    session.stop()
    assert owner.closed == [session.tab_id]


def test_default_compatibility_page_uses_borrowed_tab():
    from src.platform_adapter.browser_session import Page
    owner, session = borrowed()
    Page(session).evaluate('1')
    assert owner.calls[-1][1]['tab_id'] == session.tab_id


def test_submit_persists_without_starting_any_browser(tmp_path, monkeypatch):
    ctx = context()
    store = BrowserControlStore(tmp_path / 'control.db')
    monkeypatch.setattr(bridge, '_runtime', lambda: NS(resolve=lambda *_args, **_kw: ctx))
    monkeypatch.setattr(bridge, '_store', lambda: store)
    monkeypatch.setattr(bridge, 'ROOT', tmp_path)
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'frozen-original-video')
    request = PublishRequest(str(video), 'title', extra_metadata={'account_uuid': ctx.account_uuid})
    first = bridge.queue_publish_request('one', request, authorization='用户明确发布这部片')
    again = bridge.queue_publish_request('one', request, authorization='用户明确发布这部片')
    assert first['command_id'] == again['command_id']
    assert first['state'] == 'queued'
    assert store.snapshot(ctx.account_uuid)['owner'] is None
    changed = PublishRequest(str(video), 'changed title')
    with pytest.raises(BrowserControlRejected):
        bridge.queue_publish_request('one', changed, authorization='用户明确发布这部片')


def test_authorization_file_is_frozen_before_submission(tmp_path, monkeypatch):
    ctx = context()
    monkeypatch.setattr(bridge, '_runtime', lambda: NS(resolve=lambda *_args, **_kw: ctx))
    monkeypatch.setattr(bridge, 'ROOT', tmp_path)
    ref, video = tmp_path / 'review.json', tmp_path / 'video.mp4'
    ref.write_text('original')
    video.write_bytes(b'video')
    with pytest.raises(BrowserControlRejected, match='字节不一致'):
        bridge.queue_publish_request('one', PublishRequest(str(video), 'title'),
            authorization={'path': str(ref), 'sha256': 'changed'})


def test_binding_version_ignores_health_but_not_identity_or_profile():
    ctx = context()
    original = bridge.binding_version(ctx)
    ctx.binding.status = 'blocked'
    assert bridge.binding_version(ctx) == original
    ctx.profile.profile_version += 1
    assert bridge.binding_version(ctx) != original


def test_human_pause_defers_publish_but_allows_original_identity_recovery(monkeypatch):
    current = context('blocked')
    runtime = NS(resolve=lambda *_args, **_kw: current,
        profiles=NS(get=lambda *_: current.profile),
        bindings=NS(get_runtime_state=lambda *_: NS(lock_owner='', circuit_open_until='',
            day_key='', daily_runs=0), get=lambda *_: current.binding))
    resource = NS(account_key='one', runtime=runtime, manual_tasks={'manual': 'tab'}, context=current)
    ctx = NS(resource=resource, account_id=current.account_uuid,
        binding_version=bridge.binding_version(current), command={'kind': 'publish'})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: {'state': 'paused'})
    with pytest.raises(BrowserControlDeferred):
        bridge._admission(ctx, 'dispatch')
    ctx.command['kind'] = 'recovery'
    bridge._admission(ctx, 'start')


def test_unknown_legacy_lease_is_not_ignored_even_for_manual(monkeypatch):
    current = context()
    runtime = NS(resolve=lambda *_args, **_kw: current,
        bindings=NS(get_runtime_state=lambda *_: NS(lock_owner='old:unknown')))
    resource = NS(account_key='one', runtime=runtime, manual_tasks={})
    ctx = NS(resource=resource, account_id=current.account_uuid,
        binding_version=bridge.binding_version(current), command={'kind': 'manual'})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    with pytest.raises(BrowserControlDeferred, match='原业务锁'):
        bridge._admission(ctx, 'start')


def test_disabled_account_blocks_actual_page_click_even_without_version_change(monkeypatch):
    current = context()
    runtime = NS(profiles=NS(get=lambda *_: current.profile),
        bindings=NS(get=lambda *_: current.binding))
    resource = NS(account_key='one', context=current, runtime=runtime)
    ctx = NS(resource=resource, account_id=current.account_uuid,
        binding_version=bridge.binding_version(current), command={'kind': 'publish'})
    ctx.check_dispatch = lambda: None
    owner, session = borrowed(ctx)
    ctx.check_dispatch = lambda: bridge._admission(ctx, 'dispatch')
    current.profile.status = 'disabled'
    token = bridge._active.set(ctx)
    try:
        with pytest.raises(BrowserControlRejected, match='停用'):
            session.page.locator('button').click()
    finally:
        bridge._active.reset(token)
    assert owner.calls == []


@pytest.mark.parametrize('callback_context', ['none', 'other_task', 'other_thread'])
def test_late_page_callbacks_cannot_escape_origin_task_fence(callback_context):
    import threading
    owner, session = borrowed()
    failures = []
    def late():
        try:
            session.page.locator('button').click()
        except BrowserControlRejected as exc:
            failures.append(exc.code)
    if callback_context == 'none':
        bridge._active.set(None)
        late()
    elif callback_context == 'other_task':
        bridge._active.set(NS(check_dispatch=lambda: None))
        late()
    else:
        original = bridge.active_context()
        def wrong_thread():
            bridge._active.set(original)
            late()
        worker = threading.Thread(target=wrong_thread)
        worker.start()
        worker.join(timeout=3)
        assert not worker.is_alive()
    assert failures == ['late_task_callback']
    assert owner.calls == []


@pytest.mark.parametrize('status,error,state', [('blocked', 'human_required', 'failed'),
    ('failed', 'network_error', 'failed'), ('completed', '', 'succeeded')])
def test_maintenance_receipt_status_is_not_promoted_to_success(monkeypatch, status, error, state):
    from src.operations_accounts import maintenance
    result = maintenance.AccountMaintenanceResult('original', 'one', status=status, error_code=error)
    monkeypatch.setattr(maintenance, 'AccountMaintenanceService', lambda **_: NS(run=lambda *_a, **_k: result))
    ctx = NS(resource=NS(runtime=object()))
    value = bridge._maintenance(ctx, {'account_key': 'one', 'mode': 'playback', 'options': {}})
    if isinstance(value, dict):
        assert state == 'succeeded'
    else:
        assert value.state == state
        assert value.result['maintenance_result']['run_id'] == 'original'


def test_nested_publish_accounts_attempt_without_changing_parent_mutex(tmp_path):
    path = tmp_path / 'accounts.db'
    @contextmanager
    def connection():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()
    today = bridge.datetime.now(bridge.timezone.utc).date().isoformat()
    with connection() as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT,lock_owner TEXT,day_key TEXT,daily_runs INTEGER,circuit_open_until TEXT,last_run_at TEXT,updated_at TEXT)')
        db.execute('INSERT INTO account_runtime_state VALUES(?,?,?,?,?,?,?)', ('acct:one', 'background:original', today, 3, '', '', ''))
    resource = NS(account_uuid='acct:one', runtime=NS(bindings=NS(connection=connection)))
    with bridge.operation_scope('acct:one', 'background:original'):
        with bridge._publication_lease(resource):
            pass
    with connection() as db:
        row = db.execute('SELECT * FROM account_runtime_state').fetchone()
        assert row['lock_owner'] == 'background:original'
        assert row['daily_runs'] == 4
    with bridge.operation_scope('acct:one', 'wrong-owner'):
        with pytest.raises(BrowserControlRejected, match='原运行锁'):
            with bridge._publication_lease(resource):
                pytest.fail('must not dispatch')


def test_human_window_projection_distinguishes_handoff_from_closure():
    command = {'command_id': 'manual', 'account_id': 'acct:one',
        'payload': {'account_key': 'one'}, 'state': 'waiting_human',
        'created_at': 1, 'updated_at': 2, 'result': {}}
    projected = bridge._manual_public(command)
    assert projected['state'] == 'running' and projected['handoff_ready'] is True
    assert projected['phase'] == 'window_open_waiting_handling'
    command.update(state='succeeded', result={'identity_verified': True, 'manual_tab_preserved': True})
    assert bridge._manual_public(command)['state'] == 'verified'


def test_background_priority_runs_under_same_parent_operation_token(tmp_path):
    store = BrowserControlStore(tmp_path / 'control.db')
    events = []
    def publish(ctx, payload):
        assert bridge._lease.get() == ('acct:one', 'background:original')
        events.append('published')
        return {'exact_post_verified': True}
    def background(ctx, payload):
        token = bridge._active.set(ctx)
        try:
            with bridge.operation_scope('acct:one', 'background:original'):
                events.append('item1')
                store.submit('acct:one', 'binding', 'publish', 'publish:once', {}, priority=100)
                bridge.background_safe_point({'next_candidate': 1, 'actual_watch_seconds': 5})
                events.append('item2')
        finally:
            bridge._active.reset(token)
        return {'finished': True}
    store.submit('acct:one', 'binding', 'maintenance', 'bg', {}, priority=0)
    actor = BrowserControlActor(store, 'acct:one', 'binding', 'owner',
        {'maintenance': background, 'publish': publish})
    try:
        assert actor.run_next()['state'] == 'succeeded'
        assert events == ['item1', 'published', 'item2']
        background_row = next(row for row in store.snapshot('acct:one')['commands'] if row['kind'] == 'maintenance')
        assert background_row['cursor']['next_candidate'] == 1
    finally:
        actor.close()


def test_manual_page_stays_open_while_original_recovery_and_queued_publish_run(tmp_path, monkeypatch):
    """Real actor + bridge + original recovery method, fake page transport only."""
    monkeypatch.setattr('src.operations_accounts.interactive_desktop.require_interactive_desktop', lambda: None)
    from src.operations_accounts.runtime import AccountRuntimeService, RuntimeIdentityCheck
    from src.operations_accounts import manual_handling
    current = context('blocked')
    state = NS(lock_owner='', circuit_open_until='', day_key='', daily_runs=0)
    control = {'state': 'paused'}
    events = []
    owner = Owner()
    owner.config.headless = False
    def new_tab(role):
        owner.tabs.append(role)
        return NS(tab_id=f'tab-{len(owner.tabs)}', url='about:blank',
            goto=lambda url: events.append(('goto', role)))
    owner.new_tab = new_tab
    runtime = object.__new__(AccountRuntimeService)
    runtime.resolve = lambda *_a, **_kw: current
    runtime.profiles = NS(get=lambda *_: current.profile)
    runtime.bindings = NS(get_runtime_state=lambda *_: state, get=lambda *_: current.binding)
    @contextmanager
    def lease(ctx, **options):
        assert not state.lock_owner
        state.lock_owner = options['operation']
        with bridge.operation_scope(current.account_uuid, state.lock_owner):
            try:
                yield state.lock_owner
            finally:
                state.lock_owner = ''
    runtime.operation_lease = lease
    def verify(ctx, *, session):
        assert session.owner is owner
        assert owner.closed == []
        current.binding.status = 'active'
        events.append(('verified', session.tab_id))
        return RuntimeIdentityCheck(True, 'active', 'verified original identity', current.binding)
    runtime.verify_identity = verify
    resource = bridge.AccountBrowserResource(current, runtime, headless=False)
    resource.session = owner
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: control)
    monkeypatch.setattr(manual_handling, '_pause_for_handling', lambda *_: None)
    monkeypatch.setattr(manual_handling, 'resolve_manual_handling_target', lambda *_a, **_k: NS(url='https://www.douyin.com/'))
    from src.scheduler import account_refresh
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: {})
    store = BrowserControlStore(tmp_path / 'control.db')
    version = bridge.binding_version(current)
    manual = store.submit(current.account_uuid, version, 'manual', 'manual:once', {'account_key': 'one'}, priority=200)
    publication = store.submit(current.account_uuid, version, 'publish', 'publish:once', {}, priority=100)
    def published(ctx, payload):
        assert resource.manual_tasks == {}
        assert 'tab-1' not in owner.closed
        events.append(('published', 'same-owner'))
        return {'published': True}
    actor = BrowserControlActor(store, current.account_uuid, version, 'single-owner',
        {'manual': bridge._manual, 'recovery': bridge._recovery, 'publish': published},
        admission=bridge._admission, context=resource)
    try:
        assert actor.run_next()['state'] == 'waiting_human'
        assert state.lock_owner == ''
        assert store.get(publication['command_id'])['state'] == 'queued'
        assert actor.run_next()['state'] == 'queued'  # original account still paused
        store.submit(current.account_uuid, version, 'recovery', 'original:recovery', {}, priority=300)
        assert actor.run_next()['state'] == 'succeeded'
        assert store.get(manual['command_id'])['result']['manual_tab_preserved'] is True
        control['state'] = 'active'  # existing scheduler finishes its bound recovery
        assert actor.run_next()['state'] == 'succeeded'
        assert owner.closed == ['tab-2']  # only the recovery task returned its tab
        assert events[-1] == ('published', 'same-owner')
    finally:
        actor.close()


@pytest.mark.parametrize('manual_pending', [False, True])
def test_changed_profile_releases_only_clean_owner_before_claiming_new_request(tmp_path, manual_pending):
    current = context()
    store = BrowserControlStore(tmp_path / 'control.db')
    original_version = bridge.binding_version(current)
    actor = BrowserControlActor(store, current.account_uuid, original_version, 'original-owner', {})
    actor.start()
    closed = []
    resource = NS(account_uuid=current.account_uuid, session=None,
        manual_tasks={'manual': 'tab'} if manual_pending else {}, shutdown=lambda: closed.append('known-clean-close'))
    current.profile.profile_version += 1
    new_version = bridge.binding_version(current)
    request = store.submit(current.account_uuid, new_version, 'publish', 'new-config', {}, priority=100)
    outcome = bridge._release_changed_binding(actor, resource, current)
    assert store.get(request['command_id'])['state'] == 'queued'
    if manual_pending:
        assert outcome == 'waiting_original'
        assert closed == []
        actor.close()
    else:
        assert outcome == 'released'
        assert closed == ['known-clean-close']
        next_actor = BrowserControlActor(store, current.account_uuid, new_version, 'next-owner',
            {'publish': lambda *_: {'known_result': True}})
        try:
            assert next_actor.run_next()['state'] == 'succeeded'
            assert next_actor.generation == 2
        finally:
            next_actor.close()


def test_queued_automatic_window_rechecks_current_incident_before_pause_or_browser(monkeypatch):
    from src.scheduler import account_refresh
    from src.scheduler import browser_visibility
    from src.operations_accounts import manual_handling
    monkeypatch.setattr(browser_visibility, 'automatic_window_allowed', lambda account_uuid, **kwargs: True)
    calls = []
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: {'issues': []})
    monkeypatch.setattr(manual_handling, '_pause_for_handling', lambda *_: calls.append('pause'))
    resource = NS(account_uuid='acct:one', account_key='one')
    ctx = NS(resource=resource)
    with pytest.raises(BrowserControlRejected, match='不再是当前'):
        bridge._manual(ctx, {'incident_id': 7})
    assert calls == []


@pytest.mark.parametrize('profile,lock_seconds', [('creator_metrics_ui', 600), ('creator_metrics_cli', 1800)])
def test_metrics_compatibility_uses_original_quota_inside_owner(tmp_path, monkeypatch, profile, lock_seconds):
    from src.platform_adapter import douyin_adapter
    from src.platform_adapter.models import SyncResult
    current = context()
    owner = Owner()
    leases = []
    @contextmanager
    def lease(ctx, **options):
        leases.append(options)
        yield 'original:metrics'
    runtime = NS(operation_lease=lease)
    resource = NS(context=current, runtime=runtime, ensure_session=lambda: owner)
    monkeypatch.setattr(douyin_adapter, 'DouyinAdapter', lambda **_: NS(
        sync_videos=lambda **_: SyncResult(True, 'success', message='known original data')))
    store = BrowserControlStore(tmp_path / 'control.db')
    store.submit(current.account_uuid, 'binding', 'read', 'metrics:once', {
        'method': 'sync_videos', 'params': {'page_limit': 5}, 'operation_profile': profile})
    actor = BrowserControlActor(store, current.account_uuid, 'binding', 'owner',
        {'read': bridge._adapter_read}, context=resource)
    try:
        result = actor.run_next()
        assert result['state'] == 'succeeded'
        assert result['result']['read_result']['message'] == 'known original data'
        assert leases == [dict(operation='creator_metrics', daily_limit=100,
            cooldown_seconds=60, lock_seconds=lock_seconds)]
        assert owner.tabs == ['read:sync_videos']
        assert owner.closed == ['tab-1']
    finally:
        actor.close()


def test_metrics_operation_profile_cannot_expand_other_business_quotas():
    with pytest.raises(BrowserControlRejected, match='其他业务'):
        bridge.managed_adapter_call('one', 'fetch_comments', {'query': {}},
            operation_profile='creator_metrics_ui')


def test_official_console_returns_only_its_closed_tab_preserving_verification_page(tmp_path):
    from src.operations_accounts.runtime import RuntimeIdentityCheck
    current = context()
    owner = Owner()
    owner.config.headless = False
    visits, leases = [], []
    def new_tab(role):
        owner.tabs.append(role)
        return NS(tab_id=f'tab-{len(owner.tabs)}', url='about:blank',
            goto=lambda url: visits.append((role, url)))
    owner.new_tab = new_tab
    @contextmanager
    def lease(ctx, **options):
        leases.append(options)
        yield 'official:original'
    identity_sessions = []
    def verify(ctx, *, session):
        identity_sessions.append(session)
        assert session.owner is owner
        return RuntimeIdentityCheck(True, 'active', 'same original identity', current.binding)
    runtime = NS(operation_lease=lease, verify_identity=verify)
    resource = bridge.AccountBrowserResource(current, runtime, headless=False)
    resource.session = owner
    # This existing human verification page is deliberately kept outside the
    # official-console task. Closing the console must never release it.
    resource.manual_tasks['other-manual-task'] = 'existing-manual-tab'
    store = BrowserControlStore(tmp_path / 'control.db')
    command = store.submit(current.account_uuid, 'binding', 'official_console', 'console:once', {})
    actor = BrowserControlActor(store, current.account_uuid, 'binding', 'owner',
        {'official_console': bridge._official_console}, context=resource)
    try:
        result = actor.run_next()
        assert result['state'] == 'waiting_human'
        assert result['result']['account_pause_changed'] is False
        assert owner.closed == ['tab-1']  # verified identity task only
        assert leases == [dict(operation='official_console', daily_limit=100,
            cooldown_seconds=0, lock_seconds=1800)]
        assert visits == [('official_console', 'https://creator.douyin.com/creator-micro/content/manage')]
        owner.window_status = lambda: {'open': True, 'closed': False, 'context_closed': False,
            'tabs': [{'tab_id': 'existing-manual-tab', 'role': 'manual', 'closed': False},
                     {'tab_id': 'tab-2', 'role': 'official_console', 'closed': True}]}
        bridge._poll_manual_windows(actor, resource)
        assert store.get(command['command_id'])['state'] == 'succeeded'
        assert store.get(command['command_id'])['result']['official_tab_closed'] is True
        assert resource.manual_tasks == {'other-manual-task': 'existing-manual-tab'}
        assert resource.console_tasks == {}
        assert resource.session is owner
        assert owner.closed == ['tab-1']
    finally:
        actor.close()


def test_open_official_console_defers_other_business_without_marking_account_paused(monkeypatch):
    current = context()
    control = {'state': 'active'}
    runtime = NS(resolve=lambda *_a, **_k: current,
        bindings=NS(get_runtime_state=lambda *_: NS(lock_owner='')))
    resource = NS(account_key='one', runtime=runtime, manual_tasks={}, console_tasks={'console': 'tab'})
    ctx = NS(resource=resource, account_id=current.account_uuid,
        binding_version=bridge.binding_version(current), command={'kind': 'publish'})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: control)
    with pytest.raises(BrowserControlDeferred):
        bridge._admission(ctx, 'start')
    assert control == {'state': 'active'}


def test_simultaneous_official_clicks_share_atomic_key_then_explicit_new_click_gets_next_id(tmp_path, monkeypatch):
    current = context()
    store = BrowserControlStore(tmp_path / 'control.db')
    monkeypatch.setattr(bridge, '_runtime', lambda: NS(resolve=lambda *_a, **_k: current))
    monkeypatch.setattr(bridge, '_store', lambda: store)
    # Both callers saw the same empty snapshot before either request committed.
    monkeypatch.setattr(bridge, '_window_commands', lambda *_: [])
    first = bridge.queue_official_console(current.account_uuid, 'one', 'same-admin')
    second = bridge.queue_official_console(current.account_uuid, 'one', 'same-admin')
    assert first['command_id'] == second['command_id']
    assert len(store.snapshot(current.account_uuid)['commands']) == 1
    actor = BrowserControlActor(store, current.account_uuid, bridge.binding_version(current), 'owner',
        {'official_console': lambda *_: bridge.BrowserCommandResult('waiting_human', {'tab_id': 'original'})})
    try:
        actor.run_next()
        monkeypatch.setattr(bridge, '_window_commands',
                            lambda _, kind: store.commands_of_kind(current.account_uuid, kind))
        same_waiting = bridge.queue_official_console(current.account_uuid, 'one', 'same-admin')
        assert same_waiting['command_id'] == first['command_id']
        store.complete_waiting(first['command_id'], actor.owner_id, actor.generation,
            result={'official_tab_closed': True})
        following = bridge.queue_official_console(current.account_uuid, 'one', 'same-admin')
        assert following['command_id'] != first['command_id']
        assert len(store.snapshot(current.account_uuid)['commands']) == 2
    finally:
        actor.close()


def test_shared_settings_switch_and_explicit_environment_override(monkeypatch):
    from src.shared.config import settings
    monkeypatch.delenv('AI_DOUYIN_BROWSER_CONTROL', raising=False)
    monkeypatch.setattr(settings, 'AI_DOUYIN_BROWSER_CONTROL', True)
    assert bridge.enabled() is True
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', '0')
    assert bridge.enabled() is False
    monkeypatch.setattr(settings, 'AI_DOUYIN_BROWSER_CONTROL', False)
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', 'true')
    assert bridge.enabled() is True


def test_changed_profile_observes_closed_console_before_owner_migration(tmp_path):
    current = context()
    original_version = bridge.binding_version(current)
    store = BrowserControlStore(tmp_path / 'control.db')
    command = store.submit(current.account_uuid, original_version, 'official_console', 'console:once', {})
    actor = BrowserControlActor(store, current.account_uuid, original_version, 'original-owner',
        {'official_console': lambda *_: bridge.BrowserCommandResult('waiting_human', {'tab_id': 'console'})})
    actor.run_next()
    tabs = [{'tab_id': 'console', 'role': 'official_console', 'closed': True},
            {'tab_id': 'default', 'role': 'default', 'closed': False}]
    resource = NS(account_uuid=current.account_uuid, manual_tasks={},
        console_tasks={command['command_id']: 'console'}, headless=False,
        session=NS(window_status=lambda: {'closed': False, 'context_closed': False, 'tabs': tabs},
                   list_tabs=lambda: tabs))
    resource.shutdown = lambda: setattr(resource, 'session', None)
    current.profile.profile_version += 1
    assert bridge._release_changed_binding(actor, resource, current) == 'waiting_original'
    # Exact host ordering: original-owner close observation precedes migration.
    bridge._poll_manual_windows(actor, resource)
    result = store.get(command['command_id'])['result']
    assert result['official_tab_closed'] is True
    assert result.get('identity_verified') is not True
    assert bridge._release_changed_binding(actor, resource, current) == 'released'
    assert store.snapshot(current.account_uuid)['owner']['state'] == 'released'


def test_publish_start_limits_keep_original_command_queued_until_next_utc_day(tmp_path, monkeypatch):
    from datetime import datetime as RealDatetime, timedelta
    from src.operations_accounts.models import AccountRuntimeState
    current = context()
    clock = [RealDatetime(2026, 10, 18, 23, 59, tzinfo=bridge.timezone.utc)]
    monkeypatch.setattr(bridge, 'datetime', NS(now=lambda _tz: clock[0]))
    state = AccountRuntimeState(current.account_uuid, day_key='2026-10-18', daily_runs=20,
        circuit_open_until=(clock[0] + timedelta(hours=1)).isoformat())
    runtime = NS(resolve=lambda *_a, **_k: current,
        bindings=NS(get_runtime_state=lambda *_: state))
    browser_calls = []
    resource = NS(account_key='one', account_uuid=current.account_uuid, context=current,
        runtime=runtime, manual_tasks={}, console_tasks={}, ensure_session=lambda: browser_calls.append('browser'))
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: {'state': 'active'})
    store = BrowserControlStore(tmp_path / 'control.db')
    version = bridge.binding_version(current)
    # Advance both admission's UTC date and the durable retry clock. The long
    # TTL isolates quota rollover from the independently tested heartbeat gate.
    store.clock = lambda: clock[0].timestamp()
    store.owner_ttl = 2 * 86400
    original = store.submit(current.account_uuid, version, 'publish', 'approved-original-video', {}, priority=100)
    def publish(ctx, payload):
        browser_calls.append('handler')
        ctx.resource.ensure_session()
        return {'known_result': True}
    actor = BrowserControlActor(store, current.account_uuid, version, 'original-owner',
        {'publish': publish}, admission=bridge._admission, context=resource)
    try:
        first = actor.run_next()
        assert first['command_id'] == original['command_id']
        assert first['state'] == 'queued' and first['error_code'] == 'circuit_open'
        state.circuit_open_until = ''
        capped = actor.run_next()
        assert capped['command_id'] == original['command_id']
        assert capped['state'] == 'queued' and capped['error_code'] == 'daily_quota_exceeded'
        assert browser_calls == [] and state.daily_runs == 20
        clock[0] += timedelta(days=1)
        following = actor.run_next()
        assert following['command_id'] == original['command_id']
        assert following['state'] == 'succeeded'
        assert browser_calls == ['handler', 'browser']
        assert state.daily_runs == 20 and state.day_key == '2026-10-18'  # readonly admission
    finally:
        actor.close()


def test_nested_publish_without_quota_keeps_same_request_queued_and_background_paused(tmp_path, monkeypatch):
    from src.operations_accounts.models import AccountRuntimeState
    from src.operations_accounts.browser_control import BrowserControlSuspended
    current = context()
    state = AccountRuntimeState(current.account_uuid,
        day_key=bridge.datetime.now(bridge.timezone.utc).date().isoformat(), daily_runs=20,
        lock_owner='background:original')
    runtime = NS(resolve=lambda *_a, **_k: current,
        bindings=NS(get_runtime_state=lambda *_: state))
    resource = NS(account_key='one', account_uuid=current.account_uuid,
        context=current, runtime=runtime, manual_tasks={}, console_tasks={})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: {'state': 'active'})
    store = BrowserControlStore(tmp_path / 'control.db')
    version = bridge.binding_version(current)
    calls, publication = [], []
    def publish(*_):
        calls.append('publish/browser')
        return {'should_not_run': True}
    def background(ctx, payload):
        publication.append(store.submit(current.account_uuid, version, 'publish', 'priority-original', {}, priority=100))
        try:
            with bridge.operation_scope(current.account_uuid, 'background:original'):
                ctx.safe_point({'next_candidate': 1, 'actual_watch_seconds': 5})
                calls.append('continued-background')
        except BrowserControlSuspended:
            return {'legacy_handler_caught_exception': True}
    original = store.submit(current.account_uuid, version, 'maintenance', 'background-original', {}, priority=0)
    actor = BrowserControlActor(store, current.account_uuid, version, 'owner',
        {'maintenance': background, 'publish': publish}, admission=bridge._admission, context=resource)
    try:
        # The maintenance handler represents an already admitted parent lease.
        with bridge.operation_scope(current.account_uuid, 'background:original'):
            result = actor.run_next()
        assert result['command_id'] == original['command_id']
        assert result['state'] == 'paused' and result['cursor']['next_candidate'] == 1
        pending = store.get(publication[0]['command_id'])
        assert pending['state'] == 'queued' and pending['error_code'] == 'daily_quota_exceeded'
        assert calls == []
        assert state.daily_runs == 20 and state.lock_owner == 'background:original'
    finally:
        actor.stop_heartbeat()  # Intentionally unresolved local test checkpoint.


@pytest.fixture(autouse=True)
def legacy_daily_cap_policy(monkeypatch):
    """Keep historical cap regressions explicit; production now defaults off."""
    monkeypatch.setenv("AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT", "1")
