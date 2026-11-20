"""Independent cross-layer review, isolated databases and fake transport only."""
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserControlRejected, BrowserCommandResult
from src.operations_accounts.runtime import AccountRuntimeContext, AccountRuntimeService, RuntimeIdentityCheck
from src.scheduler import account_refresh


def test_real_completion_claim_probe_finish_keeps_manual_tab_and_allows_publication(tmp_path, monkeypatch):
    """Do not replace backend_finish_recovery with a hand-written active flag."""
    monkeypatch.setattr('src.operations_accounts.interactive_desktop.require_interactive_desktop', lambda: None)
    db = tmp_path / 'scheduler.sqlite'
    binding = NS(account_uuid='review:A', account_key='review', platform_identity_key='public:review',
        browser_environment_key='review-env', browser_profile_dir='isolated-profile',
        storage_state_path='isolated-state', confirmed_by='admin', created_at='2026-10-18', status='blocked')
    profile = NS(account_uuid=binding.account_uuid, account_key=binding.account_key, profile_version=1, status='active')
    current = AccountRuntimeContext(profile, binding, 'review-env', 'isolated-profile', 'isolated-state')
    with account_refresh.connect(db) as connection:
        account_refresh._pause(connection, current.account_uuid, current.account_key,
            'original manual challenge', 'human_required', 1000.)
    events, tabs, closed = [], [], []
    class Owner:
        config = NS(headless=False)
        def new_tab(self, role):
            tab_id = f'tab-{len(tabs) + 1}'
            tabs.append((tab_id, role))
            return NS(tab_id=tab_id, url='about:blank', goto=lambda url: events.append(('goto', tab_id)))
        def cmd(self, action, **kwargs):
            return {'url': 'about:blank'}
        def close_tab(self, tab_id):
            closed.append(tab_id)
        def save_storage_state(self):
            pass
    owner = Owner()
    runtime = object.__new__(AccountRuntimeService)
    state = NS(lock_owner='', circuit_open_until='', day_key='', daily_runs=0)
    runtime.resolve = lambda *_a, **_kw: current
    runtime.profiles = NS(get=lambda _: profile)
    runtime.bindings = NS(get_runtime_state=lambda _: state, get=lambda _: binding)
    @contextmanager
    def operation_lease(ctx, **options):
        assert not state.lock_owner
        state.lock_owner = 'original-' + options['operation']
        try:
            with bridge.operation_scope(current.account_uuid, state.lock_owner):
                yield state.lock_owner
        finally:
            state.lock_owner = ''
    runtime.operation_lease = operation_lease
    def verify(ctx, *, session):
        assert session.owner is owner
        assert 'tab-1' not in closed
        binding.status = 'active'
        events.append(('identity', session.tab_id))
        return RuntimeIdentityCheck(True, 'active', 'original identity', binding)
    runtime.verify_identity = verify
    resource = bridge.AccountBrowserResource(current, runtime, headless=False)
    resource.session = owner
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: account_refresh.snapshot(db)['controls'][0])
    from src.operations_accounts import manual_handling
    monkeypatch.setattr(manual_handling, '_pause_for_handling', lambda *_: None)
    monkeypatch.setattr(manual_handling, 'resolve_manual_handling_target', lambda *_a, **_kw: NS(url='https://www.douyin.com/'))
    # The manual target resolver only consumes its supplied snapshot; isolate it
    # without redirecting the scheduler's own real connect/finish functions.
    original_snapshot = account_refresh.snapshot
    monkeypatch.setattr(account_refresh, 'snapshot', lambda path=None: original_snapshot(db if path is None else path))
    store = BrowserControlStore(tmp_path / 'control.sqlite')
    version = bridge.binding_version(current)
    manual = store.submit(current.account_uuid, version, 'manual', 'manual:original', {'account_key': current.account_key}, 200)
    publication = store.submit(current.account_uuid, version, 'publish', 'publish:original', {}, 100)
    def publish(ctx, payload):
        assert account_refresh.snapshot(db)['controls'][0]['state'] == 'active'
        assert ctx.resource.session is owner
        assert 'tab-1' not in closed
        events.append(('publish', 'same-owner'))
        return {'exact_post_verified': True}
    actor = BrowserControlActor(store, current.account_uuid, version, 'review-owner',
        {'manual': bridge._manual, 'recovery': bridge._recovery, 'publish': publish},
        admission=bridge._admission, context=resource)
    try:
        assert actor.run_next()['state'] == 'waiting_human'
        assert actor.run_next()['state'] == 'queued'
        completion = account_refresh.complete_account_handling(current.account_uuid,
            current.account_key, handled_by='review-admin', path=db)
        assert completion['accepted']
        token = account_refresh._claim_recovery(current.account_uuid, current.account_key, path=db)
        assert token
        store.submit(current.account_uuid, version, 'recovery', 'recovery:original', {}, 300)
        result = actor.run_next()
        assert result['state'] == 'succeeded' and result['result']['healthy']
        assert account_refresh._finish_recovery(current.account_uuid, current.account_key,
            token, healthy=result['result']['healthy'], status=result['result']['status'], path=db)
        assert account_refresh.snapshot(db)['handling_requests'][0]['status'] == 'completed'
        assert store.get(manual['task_id'])['result']['manual_tab_preserved']
        assert actor.run_next()['state'] == 'succeeded'
        assert store.get(publication['task_id'])['state'] == 'succeeded'
        assert closed == ['tab-2']
        assert events[-1] == ('publish', 'same-owner')
    finally:
        actor.close()


def test_dispatch_rejects_account_disabled_after_task_start(monkeypatch):
    binding = NS(account_uuid='review:A', account_key='review', platform_identity_key='public:review',
        browser_environment_key='env', browser_profile_dir='profile', storage_state_path='state',
        confirmed_by='admin', created_at='2026', status='active')
    profile = NS(account_uuid='review:A', account_key='review', profile_version=1, status='active')
    context = AccountRuntimeContext(profile, binding, 'env', 'profile', 'state')
    version = bridge.binding_version(context)
    runtime = NS(profiles=NS(get=lambda _: profile),
        bindings=NS(get=lambda _: binding, get_runtime_state=lambda _: NS(lock_owner='')))
    resource = NS(context=context, runtime=runtime, account_key='review', manual_tasks={})
    ctx = NS(resource=resource, account_id='review:A', binding_version=version, command={'kind': 'publish'})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: {'state': 'active'})
    profile.status = 'disabled'
    assert bridge.binding_version(context) == version
    with pytest.raises(BrowserControlRejected):
        bridge._admission(ctx, 'dispatch')


def test_borrowed_storage_save_does_not_bypass_dispatch_fence():
    saved = []
    owner = NS(config=NS(headless=True),
        new_tab=lambda _: NS(tab_id='owned-tab', url='about:blank'),
        save_storage_state=lambda: saved.append('unsafe-send'))
    blocked = [False]
    def reject():
        if blocked[0]:
            raise BrowserControlRejected('account_disabled', 'disabled after preparation')
    token = bridge._active.set(NS(check_dispatch=reject))
    try:
        session = bridge.BorrowedSession(NS(ensure_session=lambda: owner), 'publish')
        blocked[0] = True
        with pytest.raises(BrowserControlRejected):
            session.save_storage_state()
        assert saved == []
    finally:
        bridge._active.reset(token)


def test_auto_window_event_is_revalidated_after_queue_delay_before_any_browser_action(monkeypatch):
    from src.operations_accounts import manual_handling
    # The formerly eligible incident was closed while waiting behind another task.
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: {
        'issues': [{'id': 7, 'account_uuid': 'review:A', 'account_key': 'review',
                    'status': 'closed', 'error_code': 'human_required', 'created_at': 10.}],
        'controls': [{'account_uuid': 'review:A', 'account_key': 'review', 'state': 'active'}]})
    def forbidden(*_args, **_kwargs):
        pytest.fail('A stale automatic incident must not pause the account or open a browser')
    monkeypatch.setattr(manual_handling, '_pause_for_handling', forbidden)
    monkeypatch.setattr(manual_handling, 'resolve_manual_handling_target', forbidden)
    resource = NS(session=None, headless=True, account_uuid='review:A', account_key='review',
        context=NS(profile=object()), shutdown=forbidden, ensure_session=forbidden)
    ctx = NS(resource=resource, task_id='original-auto-window', check_dispatch=lambda: None)
    try:
        result = bridge._manual(ctx, {'incident_id': 7, 'account_key': 'review'})
    except BrowserControlRejected as exc:
        assert exc.code == 'incident_no_longer_actionable'
    else:
        assert isinstance(result, BrowserCommandResult) and result.state == 'failed'


def test_late_borrowed_page_callback_cannot_dispatch_after_original_handler_returns(tmp_path):
    calls, leaked = [], []
    owner = NS(config=NS(headless=True),
        new_tab=lambda _: NS(tab_id='original-task-tab', url='about:blank'),
        cmd=lambda action, **kwargs: calls.append(action) or {'value': 1},
        close_tab=lambda _: None)
    resource = NS(ensure_session=lambda: owner, account_key='review')
    @_with_review_active
    def handler(ctx, payload):
        leaked.append(bridge.BorrowedSession(resource, 'original'))
        return {'finished': True}
    store = BrowserControlStore(tmp_path / 'late.sqlite')
    store.submit('review:A', 'v1', 'read', 'original', {})
    actor = BrowserControlActor(store, 'review:A', 'v1', 'owner', {'read': handler}, context=resource)
    try:
        assert actor.run_next()['state'] == 'succeeded'
        with pytest.raises(BrowserControlRejected):
            leaked[0].page.evaluate('1')
        assert calls == []
    finally:
        actor.close()


def _with_review_active(function):
    """Use the production context wrapper, keeping a readable test decorator."""
    return bridge._with_active(function)
