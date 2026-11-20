"""Fixed upload UI inspection: fake transport, real control and capture helper."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserControlRejected


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    calls, leases, closed, identities = [], [], [], []
    class Owner:
        config = NS(headless=True)
        def new_tab(self, role):
            calls.append(('new_tab', role))
            return NS(tab_id='inspection-tab')
        def close_tab(self, tab_id):
            closed.append(tab_id)
        def _check_domain_allowed(self, url):
            assert url == bridge.UPLOAD_INSPECTION_URL
        def cmd(self, action, **params):
            assert params['tab_id'] == 'inspection-tab'
            calls.append((action, params))
            if action == 'goto':
                assert params['url'] == bridge.UPLOAD_INSPECTION_URL
                return {'url': params['url']}
            if action == 'evaluate':
                return {'value': {'visible_text': '上传视频', 'buttons': [], 'progress': []}}
            if action == 'wait_for_timeout':
                assert params['ms'] == 2000
                return {}
            if action == 'screenshot':
                Path(params['path']).write_bytes(b'isolated-fake-ui-png')
                return {}
            pytest.fail('Inspection must not call form, upload, network or publish actions: ' + action)
    owner = Owner()
    current = NS(account_uuid='inspect:A')
    healthy = [True]
    @contextmanager
    def lease(context, **options):
        assert context is current
        leases.append(options)
        with bridge.operation_scope(current.account_uuid, 'original-read-lease'):
            yield
    def verify(context, *, session):
        assert context is current and session.owner is owner
        identities.append(session)
        return NS(healthy=healthy[0], status='identity_mismatch' if not healthy[0] else 'active', message='original identity check')
    resource = NS(runtime=NS(operation_lease=lease, verify_identity=verify),
        context=current, ensure_session=lambda: owner, account_key='inspect')
    monkeypatch.setattr(bridge, 'ROOT', tmp_path)
    from src.platform_adapter import douyin_adapter
    monkeypatch.setattr(douyin_adapter, 'DouyinAdapter', lambda **_: pytest.fail('Inspection must not construct publishing adapter'))
    store = BrowserControlStore(tmp_path / 'control.sqlite')
    command = store.submit('inspect:A', 'original-binding', 'read', 'inspect-once',
        {'method': 'inspect_upload_surface', 'params': {}, 'operation_profile': None})
    actor = BrowserControlActor(store, 'inspect:A', 'original-binding', 'owner',
        {'read': bridge._adapter_read}, context=resource)
    return NS(actor=actor, store=store, command=command, calls=calls, leases=leases,
        closed=closed, identities=identities, healthy=healthy, root=tmp_path)


def test_real_actor_inspects_fixed_surface_under_original_20_quota_and_same_borrowed_tab(fixture):
    f = fixture
    try:
        result = f.actor.run_next()
        assert result['state'] == 'succeeded'
        value = result['result']['read_result']
        assert len(f.identities) == 1
        assert f.leases == [{'operation': 'browser-read:inspect_upload_surface', 'daily_limit': 20, 'cooldown_seconds': 0}]
        assert [action for action, _ in f.calls] == ['new_tab', 'goto', 'wait_for_timeout', 'evaluate', 'screenshot']
        assert f.closed == ['inspection-tab']
        assert value['status'] == 'inspected' and value['upload_started'] is False
        assert value['platform_submission_started'] is False
        assert value['upload_completion_assessed_by_diagnostic'] is False
        assert value['ui'] == {'visible_text': '上传视频', 'buttons': [], 'progress': []}
        evidence = Path(value['evidence']['path'])
        assert evidence.parent == f.root / 'data/publication_upload_inspections' / f.command['command_id']
        assert evidence.exists() and Path(value['screenshot']['path']).exists()
        assert not list(f.root.rglob('publish_journal.json'))
    finally:
        f.actor.close()


def test_original_identity_failure_prevents_fixed_upload_page_and_capture(fixture):
    f = fixture
    f.healthy[0] = False
    try:
        result = f.actor.run_next()
        assert result['state'] == 'failed' and result['error_code'] == 'identity_mismatch'
        assert [action for action, _ in f.calls] == ['new_tab']
        assert f.closed == ['inspection-tab']
        assert not (f.root / 'data/publication_upload_inspections').exists()
    finally:
        f.actor.close()


@pytest.mark.parametrize('params', [{'url': 'https://example.com'}, {'script': 'arbitrary'},
    {'evidence_dir': 'C:/outside'}, {'file_path': 'video.mp4'}, [], None])
def test_inspection_rejects_all_nonempty_or_nonobject_params_before_resource_use(params):
    with pytest.raises(BrowserControlRejected) as error:
        bridge._adapter_read(NS(), {'method': 'inspect_upload_surface', 'params': params})
    assert error.value.code == 'inspection_params_invalid'


def test_inspection_cannot_borrow_creator_metrics_higher_quota():
    with pytest.raises(BrowserControlRejected) as error:
        bridge._adapter_read(NS(resource=object()), {'method': 'inspect_upload_surface', 'params': {},
            'operation_profile': 'creator_metrics_cli'})
    assert error.value.code == 'operation_profile_invalid'


def test_queue_inspection_only_persists_empty_fixed_request_without_owner(tmp_path, monkeypatch):
    store = BrowserControlStore(tmp_path / 'queue.sqlite')
    monkeypatch.setattr(bridge, '_submit', lambda account, kind, payload, key, priority:
        store.submit('inspect:A', 'binding', kind, key, payload, priority))
    command = bridge.queue_inspect_upload('inspect')
    assert command['state'] == 'queued'
    assert command['payload'] == {'method': 'inspect_upload_surface', 'params': {}, 'operation_profile': None}
    assert store.snapshot('inspect:A')['owner'] is None


@pytest.mark.parametrize('limit', ['daily_quota_exceeded', 'circuit_open'])
def test_inspection_known_20_daily_or_circuit_gate_retains_original_queued_id_before_handler(tmp_path, monkeypatch, limit):
    monkeypatch.setenv('AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT', '1')
    from src.operations_accounts.runtime import AccountRuntimeContext
    binding = NS(account_uuid='inspect:A', account_key='inspect', platform_identity_key='public:inspect',
        browser_environment_key='env', browser_profile_dir='profile', storage_state_path='state',
        confirmed_by='admin', created_at='2026', status='active')
    profile = NS(profile_version=1, account_uuid='inspect:A', account_key='inspect', status='active')
    current = AccountRuntimeContext(profile, binding, 'env', 'profile', 'state')
    now = datetime.now(timezone.utc)
    state = NS(lock_owner='', day_key=now.date().isoformat(),
        daily_runs=20 if limit == 'daily_quota_exceeded' else 0,
        circuit_open_until=(now + timedelta(hours=1)).isoformat() if limit == 'circuit_open' else '')
    runtime = NS(resolve=lambda *_a, **_kw: current,
        profiles=NS(get=lambda _: profile), bindings=NS(get_runtime_state=lambda _: state, get=lambda _: binding))
    resource = NS(runtime=runtime, context=current, account_key='inspect', manual_tasks={}, console_tasks={})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda _: None)
    monkeypatch.setattr(bridge, '_controls', lambda _: {'state': 'active'})
    store = BrowserControlStore(tmp_path / 'quota.sqlite')
    version = bridge.binding_version(current)
    original = store.submit('inspect:A', version, 'read', 'inspection-original',
        {'method': 'inspect_upload_surface', 'params': {}, 'operation_profile': None})
    actor = BrowserControlActor(store, 'inspect:A', version, 'owner',
        {'read': lambda *_: pytest.fail('Known quota must defer before handler/browser')},
        admission=bridge._admission, context=resource)
    try:
        result = actor.run_next()
        assert result['state'] == 'queued' and result['error_code'] == limit
        assert result['command_id'] == original['command_id']
        assert result['owner_id'] is None
    finally:
        actor.close()


def _cli():
    path = Path(__file__).parents[1] / 'scripts/account_browser_control.py'
    spec = importlib.util.spec_from_file_location('isolated_inspection_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_queue_inspection_does_not_start_backend_or_browser(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(bridge, 'queue_inspect_upload', lambda account: calls.append(account) or
        {'command_id': 'a' * 32, 'account_id': 'inspect:A', 'kind': 'read', 'state': 'queued'})
    monkeypatch.setattr(bridge, 'pump_pending', lambda: pytest.fail('CLI cannot execute backend'))
    monkeypatch.setattr(sys, 'argv', ['control', 'queue-inspect-upload', 'inspect'])
    _cli().main()
    result = json.loads(capsys.readouterr().out)
    assert calls == ['inspect']
    assert result['browser_started'] is False and result['upload_started'] is False


def test_original_status_returns_inspection_evidence_without_new_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(bridge, 'snapshot', lambda account: {'account_id': 'inspect:A', 'owner': None,
        'commands': [{'command_id': 'original', 'kind': 'read', 'state': 'succeeded',
            'payload': {'method': 'inspect_upload_surface'}, 'result': {'read_result': {'evidence': {'path': 'D:/evidence'}}}}]})
    monkeypatch.setattr(sys, 'argv', ['control', 'status', 'inspect'])
    _cli().main()
    result = json.loads(capsys.readouterr().out)
    assert result['commands'][0]['result']['read_result']['evidence']['path'] == 'D:/evidence'


@pytest.mark.parametrize('method,params', [
    ('sync_videos', {'page_limit': 2, 'interactive': False}),
    ('fetch_comments', {'query': {'post_id': '123'}}),
    ('verify_published_video', {'request': {'video_path': 'frozen.mp4', 'title': 'original'},
                                'post_id': '123', 'publish_url': 'https://www.douyin.com/video/123'}),
])
def test_original_three_read_handlers_keep_existing_method_and_typed_params(monkeypatch, method, params):
    from src.platform_adapter import douyin_adapter
    from src.platform_adapter.models import CommentQuery, PublishRequest
    calls, leases, stopped = [], [], []
    @contextmanager
    def lease(context, **options):
        leases.append(options)
        yield
    def method_call(**received):
        calls.append(received)
        return {'existing': method}
    monkeypatch.setattr(douyin_adapter, 'DouyinAdapter', lambda **_: NS(**{method: method_call}))
    monkeypatch.setattr(bridge, 'BorrowedSession', lambda *_: NS(stop=lambda: stopped.append(True)))
    ctx = NS(resource=NS(runtime=NS(operation_lease=lease), context=object()))
    result = bridge._adapter_read(ctx, {'method': method, 'params': params})
    assert result == {'read_result': {'existing': method}}
    assert leases == [{'operation': 'browser-read:' + method, 'daily_limit': 20, 'cooldown_seconds': 0}]
    if method == 'fetch_comments':
        assert isinstance(calls[0]['query'], CommentQuery)
    elif method == 'verify_published_video':
        assert isinstance(calls[0]['request'], PublishRequest)
    else:
        assert calls[0] == params
    assert stopped == [True]
