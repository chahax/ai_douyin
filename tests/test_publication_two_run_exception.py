"""Frozen two-operation exception, real SQLite accounting/control, fake browser."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserControlRejected
from src.operations_accounts.repository import AccountBindingRepository
from src.operations_accounts.runtime import AccountRuntimeContext, AccountRuntimeService, RuntimeIdentityCheck
from src.scheduler import account_refresh


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(quota, 'ROOT', tmp_path)
    monkeypatch.setattr(quota, 'REGISTRY', tmp_path / 'registry.json')
    monkeypatch.setattr(quota, 'REGISTRY_V2', tmp_path / 'registry_v2.json')
    monkeypatch.setattr(quota, 'REGISTRY_V3', tmp_path / 'registry_v3.json')
    monkeypatch.setattr(bridge, 'ROOT', tmp_path)
    video = tmp_path / 'approved.mp4'
    video.write_bytes(b'approved original film')
    prepared = tmp_path / 'PREPARED.json'
    prepared.write_text(json.dumps({'decision_source': 'explicit_user_statement',
        'full_film_accepted_for_publication': True, 'user_statement': 'publish approved film',
        'ai_generated': True, 'fictional_story': True, 'account_uuid': 'acct:one', 'account_key': 'one',
        'video': {'path': str(video), 'sha256': sha(video)}, 'title': 'Approved',
        'description': '剧情虚构，非真实事件。', 'hashtags': ['劳动法'], 'visibility': 'public'}), encoding='utf-8')
    scheduler = tmp_path / 'scheduler.db'
    monkeypatch.setattr(account_refresh, 'DB', scheduler)
    monkeypatch.setattr(account_refresh, '_pending_manual_window', lambda *a: False)
    with account_refresh.connect(scheduler) as db:
        account_refresh._pause(db, 'acct:one', 'one', 'original challenge', 'human_required', 1000.)
    original = quota.control_snapshot('acct:one')
    value = quota.build_authorization(prepared, account_uuid='acct:one', account_key='one',
        recovery_key='extra:original-recovery', publish_key='extra:original-publish',
        recovery_control_revision=original['revision'] + 1,
        cancel_manual_command_id='original-manual', user_statement='允许取消开窗任务并追加2次，继续发布')
    authorization = tmp_path / 'AUTHORIZATION.json'
    authorization.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    reference = quota.register_authorization(authorization, sha(authorization))
    return NS(root=tmp_path, prepared=prepared, video=video, auth=authorization,
        value=value, ref=reference, scheduler=scheduler)


def test_real_scheduler_recovery_and_publish_consume_only_two_original_counted_leases(frozen, monkeypatch):
    f = frozen
    repository = AccountBindingRepository(f.root / 'account.db')
    with repository.connection() as db:
        db.execute("INSERT INTO douyin_accounts(account_uuid,account_key,created_at,updated_at) VALUES('acct:one','one','old','old')")
    repository.get_runtime_state('acct:one')
    with repository.connection() as db:
        db.execute('UPDATE account_runtime_state SET day_key=?,daily_runs=? WHERE account_uuid=?',
            (datetime.now(timezone.utc).date().isoformat(), f.value['baseline_daily_runs'], 'acct:one'))
    binding = NS(account_uuid='acct:one', account_key='one', platform_identity_key='public:original',
        browser_environment_key='env:one', browser_profile_dir='profile/one', storage_state_path='state/one',
        confirmed_by='user', created_at='2026', status='blocked')
    profile = NS(account_uuid='acct:one', account_key='one', profile_version=1, status='active')
    context = AccountRuntimeContext(profile, binding, 'env:one', 'profile/one', 'state/one')
    runtime = object.__new__(AccountRuntimeService)
    runtime.resolve = lambda *a, **k: context
    runtime.profiles = NS(get=lambda *a: profile)
    runtime.bindings = NS(get_runtime_state=repository.get_runtime_state, get=lambda *a: binding,
        acquire_runtime=repository.acquire_runtime, release_runtime=repository.release_runtime,
        connection=repository.connection)
    events = []
    class Owner:
        config = NS(headless=True)
        def new_tab(self, role):
            events.append(('new_tab', role))
            return NS(tab_id='identity-original-tab')
        def close_tab(self, tab_id):
            events.append(('close_tab', tab_id))
    runtime.verify_identity = lambda *a, **k: (
        events.append(('identity', repository.get_runtime_state('acct:one').daily_runs)),
        setattr(binding, 'status', 'active'),
        RuntimeIdentityCheck(True, 'active', 'same bound original identity', binding))[-1]
    resource = bridge.AccountBrowserResource(context, runtime)
    resource.session = Owner()
    store = BrowserControlStore(f.root / 'control.db')
    monkeypatch.setattr(bridge, '_runtime', lambda: runtime)
    monkeypatch.setattr(bridge, '_store', lambda: store)
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda *a: None)
    monkeypatch.setattr(bridge, '_controls', lambda *a: account_refresh.snapshot(f.scheduler)['controls'][0])
    monkeypatch.setattr(bridge, 'enabled', lambda: True)
    @bridge._with_active
    def publish(ctx, payload):
        with bridge._publication_lease(resource):
            events.append(('publish', repository.get_runtime_state('acct:one').daily_runs))
        return {'published_once': True}
    actor = BrowserControlActor(store, 'acct:one', bridge.binding_version(context), 'owner:one',
        {'recovery': bridge._recovery, 'publish': publish, 'manual': lambda *a: pytest.fail('manual still20')},
        admission=bridge._admission, context=resource)
    try:
        if getattr(f, 'queued_manual_first', False):
            pending_manual = store.submit('acct:one', bridge.binding_version(context), 'manual',
                'original-queued-manual', {'account_key': 'one'}, priority=200)
        publication = bridge.queue_prepared_publication(f.prepared, quota_authorization=f.ref)
        assert publication['priority'] == (250 if f.value['schema'] == quota.SCHEMA_V2 else 100)
        assert actor.run_next()['state'] == 'queued'  # Original pause still blocks publishing.
        assert account_refresh.request_account_recovery('acct:one', 'one', path=f.scheduler)
        token = account_refresh._claim_recovery('acct:one', 'one', path=f.scheduler)
        assert token
        # This reads a real row containing revision; public legacy snapshot lacks it.
        assert quota.control_snapshot('acct:one')['revision'] == f.value['recovery_control_revision']
        monkeypatch.setattr(bridge, '_await', lambda command: actor.run_next())
        check = bridge.managed_recovery('one')
        assert check.healthy
        assert quota.control_snapshot('acct:one')['state'] == 'recovering'  # No fake complete/activation.
        assert repository.get_runtime_state('acct:one').daily_runs == f.value['baseline_daily_runs'] + 1
        assert account_refresh._finish_recovery('acct:one', 'one', token,
            healthy=check.healthy, status=check.status, path=f.scheduler)
        assert quota.control_snapshot('acct:one')['revision'] == f.value['recovery_control_revision'] + 1
        assert actor.run_next()['state'] == 'succeeded'
        assert repository.get_runtime_state('acct:one').daily_runs == f.value['max_daily_runs']
        assert events.count(('identity', f.value['baseline_daily_runs'] + 1)) == events.count(('publish', f.value['max_daily_runs'])) == 1
        same = bridge.queue_prepared_publication(f.prepared, quota_authorization=f.ref)
        assert same['command_id'] == publication['command_id'] and same['state'] == 'succeeded'
        if getattr(f, 'queued_manual_first', False):
            assert actor.run_next()['state'] == 'queued'
            assert store.get(pending_manual['command_id'])['state'] == 'queued'
        else:
            assert actor.run_next() is None
        store.submit('acct:one', bridge.binding_version(context), 'manual', 'ordinary-manual', {'account_key': 'one'})
        assert actor.run_next()['state'] == 'queued'  # Extra22 never extends manual.
        # A later genuine scheduler request does not reuse old recovery success.
        with account_refresh.connect(f.scheduler) as db:
            account_refresh._pause(db, 'acct:one', 'one', 'new event', 'human_required', 2000.)
        assert account_refresh.request_account_recovery('acct:one', 'one', path=f.scheduler)
        assert account_refresh._claim_recovery('acct:one', 'one', path=f.scheduler)
        assert quota.registered_recovery('one') is None
    finally:
        actor.stop_heartbeat()


def context_for(f, kind='recovery'):
    payload = {'account_uuid': 'acct:one', 'account_key': 'one', 'quota_authorization': f.ref,
        'identity_probe_only': True}
    if kind == 'publish':
        from src.platform_adapter.models import PublishRequest
        p = json.loads(f.prepared.read_bytes())
        payload.update(video_sha256=p['video']['sha256'], authorization=f.value['prepared'],
            request=asdict(PublishRequest(video_path=p['video']['path'], title=p['title'], description=p['description'],
                hashtags=p['hashtags'], visibility=p['visibility'], ai_generated=True, fictional_story=True)))
    return NS(account_id='acct:one', command={'kind': kind,
        'idempotency_key': f.value['idempotency_keys'][kind], 'payload': payload})


@pytest.mark.parametrize('change', ['key', 'account', 'revision', 'state', 'video', 'prepared', 'auth_bytes', 'request'])
def test_frozen_exception_rejects_changed_scope_or_evidence(frozen, change):
    f = frozen
    ctx = context_for(f, 'publish')
    control = {'account_uuid': 'acct:one', 'account_key': 'one', 'state': 'active',
        'revision': f.value['recovery_control_revision'] + 1}
    if change == 'key': ctx.command['idempotency_key'] = 'new-retry-key'
    if change == 'account': ctx.account_id = 'another-account'
    if change == 'revision': control['revision'] += 1
    if change == 'state': control['state'] = 'paused'
    if change == 'video': f.video.write_bytes(b'changed original film')
    if change == 'prepared': f.prepared.write_bytes(b'changed prepared')
    if change == 'auth_bytes': f.auth.write_bytes(f.auth.read_bytes() + b' ')
    if change == 'request': ctx.command['payload']['request']['title'] = 'unapproved title'
    with pytest.raises(BrowserControlRejected, match='授权'):
        quota.authorized_daily_limit(ctx, 'publish', account_uuid='acct:one', control=control)


def test_registry_cannot_be_replaced_and_expiration_returns_ordinary_recovery(frozen, monkeypatch):
    f = frozen
    assert quota.register_authorization(f.auth, sha(f.auth)) == f.ref
    other = f.root / 'NEW_AUTHORIZATION.json'
    other.write_bytes(f.auth.read_bytes())
    with pytest.raises(BrowserControlRejected):
        quota.register_authorization(other, sha(other))
    class Tomorrow(datetime):
        @classmethod
        def now(cls, tz=None): return datetime.now(timezone.utc) + timedelta(days=1)
    monkeypatch.setattr(quota, 'datetime', Tomorrow)
    assert quota.registered_recovery('one') is None
    with pytest.raises(BrowserControlRejected): quota.validate_authorization(f.ref)


@pytest.mark.parametrize('kind,operation,limit', [('manual','manual-session',20),
    ('read','browser-read:sync_videos',20), ('maintenance','maintenance:playback',20),
    ('publish','other-operation',20), ('publish','publish',100)])
def test_other_operations_never_gain_extra_limit(frozen, kind, operation, limit):
    ctx = context_for(frozen)
    ctx.command['kind'] = kind
    assert quota.authorized_daily_limit(ctx, operation, default=limit, account_uuid='acct:one') == limit


@pytest.mark.parametrize('bad', [None, 'publish', 'cas', 'owner', 'generation', 'authorization'])
def test_explicit_unknown_manual_cancellation_is_narrow_and_audited(tmp_path, bad):
    store = BrowserControlStore(tmp_path / 'control.db')
    kind = 'publish' if bad == 'publish' else 'manual'
    command = store.submit('acct:one', 'original-binding', kind, 'unknown-original', {'account_key': 'one'})
    def unknown(*a): raise RuntimeError('original uncertainty')
    actor = BrowserControlActor(store, 'acct:one', 'original-binding', 'original-owner', {kind: unknown})
    try:
        before = actor.run_next()
        assert before['state'] == 'outcome_unknown'
        authorization = tmp_path / 'CANCEL_AUTHORIZATION.json'
        authorization.write_text(json.dumps({'decision_source': 'explicit_user_statement',
            'command_id': command['command_id'], 'account_uuid': 'acct:one',
            'user_statement': '允许取消开窗任务并追加2次，继续发布'}), encoding='utf-8')
        ref = {'path': str(authorization), 'sha256': sha(authorization)}
        if bad == 'authorization': authorization.write_text('{}')
        args = dict(expected_snapshot_sha256='wrong' if bad == 'cas' else snapshot_sha(before),
            reason='explicit cancellation, original result remains unknown', requested_by='human-authorized-root', authorization=ref)
        if bad:
            with pytest.raises(BrowserControlRejected):
                store.operator_cancel_unknown_manual(command['command_id'],
                    'wrong' if bad == 'owner' else actor.owner_id,
                    actor.generation + (bad == 'generation'), **args)
            assert store.get(command['command_id']) == before
        else:
            result = store.operator_cancel_unknown_manual(command['command_id'], actor.owner_id, actor.generation, **args)
            assert result['state'] == 'failed' and result['error_code'] == 'operator_cancelled_unknown_manual'
            assert result['result']['before_snapshot'] == before
            assert result['result']['original_outcome_known'] is False
            assert store.submit('acct:one', 'original-binding', kind, 'unknown-original', {'account_key': 'one'})['command_id'] == command['command_id']
            assert actor.run_next() is None
    finally:
        actor.stop_heartbeat()
