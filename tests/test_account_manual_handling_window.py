from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.operations_accounts import manual_handling as module
from src.operations_accounts.repository import AccountRuntimeUnavailable
from src.operations_accounts.runtime import AccountRuntimeError
from src.platform_adapter.douyin_identity import DOUYIN_SELF_URL


@pytest.fixture
def window(tmp_path, monkeypatch):
    events, logs = [], []
    profile = SimpleNamespace(account_uuid="account:window-01", account_key="account01")
    environment = dict(browser_environment_key="douyin-browser:original",
        browser_profile_dir=str(tmp_path / "original_profile"), storage_state_path=str(tmp_path / "original_state.json"))
    binding = SimpleNamespace(account_uuid=profile.account_uuid, account_key=profile.account_key, **environment)
    context = SimpleNamespace(account_uuid=profile.account_uuid, account_key=profile.account_key,
        profile=profile, binding=binding, **environment)
    state = SimpleNamespace(active_lease=False, open_error=None, stop_error=None, lease_error=None)
    class Session:
        config = SimpleNamespace(headless=False, user_data_dir=environment["browser_profile_dir"],
            storage_state_path=environment["storage_state_path"])
        def open_for_manual_login_until_closed(self, url, *, timeout_seconds, on_opened=None):
            assert state.active_lease
            events.append(("open", url, timeout_seconds))
            if state.open_error:
                raise state.open_error
            if on_opened is not None:
                on_opened()
            return SimpleNamespace(authenticated=True)
        def stop(self):
            assert state.active_lease
            events.append(("stop",))
            if state.stop_error:
                raise state.stop_error
    session = Session()
    def create(*, headless):
        assert state.active_lease
        events.append(("create", headless))
        return session
    prepared = SimpleNamespace(profile=SimpleNamespace(account_uuid=profile.account_uuid,
        account_key=profile.account_key), create_browser_session=create, **environment)
    class Runtime:
        def resolve(self, account_key, *, require_healthy=True):
            events.append(("resolve", account_key, require_healthy))
            return context
        @contextmanager
        def manual_browser_environment(self, account_key):
            events.append(("lease_enter", account_key))
            if state.lease_error:
                raise state.lease_error
            state.active_lease = True
            try:
                yield prepared
            finally:
                events.append(("lease_exit", account_key))
                state.active_lease = False
        def probe_unbound_identity(self, *a, **k):
            pytest.fail("manual window cannot probe identity")
        verify_identity = confirm_binding = probe_recovery = probe_unbound_identity
    monkeypatch.setattr(module, "_pause_for_handling", lambda uuid, key: events.append(("pause", uuid, key)))
    monkeypatch.setattr(module, "_handling_snapshot", lambda: events.append(("snapshot",)) or {})
    monkeypatch.setattr(module, "_manual_window_event", lambda *args: logs.append(args))
    return SimpleNamespace(runtime=Runtime(), profile=profile, binding=binding, context=context,
        prepared=prepared, session=session, events=events, logs=logs, state=state)


def invoke(window, **kwargs):
    return module.open_bound_manual_handling_window(window.profile.account_uuid, window.profile.account_key,
        runtime=window.runtime, **kwargs)


def test_automatic_dispatch_reaches_real_original_environment_helper_once(window,tmp_path,monkeypatch):
    import threading
    import time
    from src.operations_accounts import manual_window_jobs as jobs
    from src.scheduler import account_refresh as backend
    from src.scheduler.account_manual_windows import dispatch_human_windows
    db,windows=tmp_path/'refresh.db',tmp_path/'windows.db'
    uuid,key=window.profile.account_uuid,window.profile.account_key
    with backend.connect(db) as connection:
        backend._pause(connection,uuid,key,'challenge','human_required',time.time())
    window.runtime.profiles=SimpleNamespace(get=lambda _:SimpleNamespace(account_uuid=uuid,account_key=key,status='active'))
    window.runtime.bindings=SimpleNamespace(get_runtime_state=lambda _:SimpleNamespace(lock_owner=''))
    monkeypatch.setattr(module,'_handling_snapshot',lambda:backend.snapshot(db))
    opened,release=threading.Event(),threading.Event()
    def visible_page(url,*,timeout_seconds,on_opened):
        assert window.state.active_lease and window.session.config.headless is False
        window.events.append(('auto_open',url))
        on_opened()
        opened.set()
        assert release.wait(8)
        return SimpleNamespace(authenticated=True)
    monkeypatch.setattr(window.session,'open_for_manual_login_until_closed',visible_page)
    first=dispatch_human_windows(path=db,jobs_path=windows,runtime=window.runtime)[0]
    try:
        assert opened.wait(5)
        assert jobs.get_manual_window_job(uuid,key,path=windows)['state']=='running'
        assert dispatch_human_windows(path=db,jobs_path=windows,runtime=window.runtime)==[]
        manual=jobs.start_manual_window_job(uuid,key,'admin',runtime=window.runtime,path=windows)
        assert manual['job_id']==first['job_id']
        assert len([e for e in window.events if e[0]=='auto_open'])==1
    finally:
        release.set()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        final=jobs.get_manual_window_job(uuid,key,path=windows)
        if final['state']=='closed':break
        time.sleep(.01)
    assert final['state']=='closed' and not window.state.active_lease
    assert ('stop',) in window.events and ('lease_exit',key) in window.events
    assert backend.snapshot(db)['controls'][0]['state']=='paused'


def test_shared_window_uses_original_bound_context_and_lease_without_probe_or_complete(window):
    result = invoke(window)
    assert result.closed and result.target.url == DOUYIN_SELF_URL
    assert "后台核验" in result.message
    assert window.events == [("resolve", "account01", False), ("snapshot",),
        ("pause", "account:window-01", "account01"), ("lease_enter", "account01"),
        ("create", False), ("open", DOUYIN_SELF_URL, 1800), ("stop",), ("lease_exit", "account01")]
    assert [event[0] for event in window.logs] == ["requested", "opening", "closed"]


def test_injected_snapshot_uses_real_resolver_to_open_recorded_creator_page(window, monkeypatch):
    run_id, maintenance_id = "1" * 32, "maintenance:" + "a" * 32
    snapshot = {"controls": [dict(account_uuid=window.profile.account_uuid, account_key="account01",
        state="paused", error_code="human_required", updated_at=1020.0)],
        "runs": [dict(account_uuid=window.profile.account_uuid, account_key="account01", run_id=run_id,
            status="blocked", started_at=1000.0, finished_at=1020.0,
            detail=dict(error_code="human_required", maintenance_run_id=maintenance_id))]}
    receipt = dict(account_uuid=window.profile.account_uuid, account_key="account01", run_id=maintenance_id,
        mode="post-publish", status="blocked", error_code="human_required",
        started_at=datetime.fromtimestamp(1002, timezone.utc).isoformat(),
        finished_at=datetime.fromtimestamp(1018, timezone.utc).isoformat())
    monkeypatch.setattr(module, "_read_receipt", lambda *a: receipt)
    result = invoke(window, snapshot_data=snapshot)
    assert result.target.source == "creator_content" and result.target.run_id == run_id
    assert ("open", module.CREATOR_CONTENT_URL, 1800) in window.events
    assert ("snapshot",) not in window.events
    assert window.logs[-1] == ("closed", "account01", "creator_content", run_id)


@pytest.mark.parametrize("source,field,value", [
    ("context", "account_uuid", "account:other"), ("context", "account_key", "other"),
    ("binding", "account_uuid", "account:other"), ("binding", "account_key", "other"),
    ("context", "browser_environment_key", "other-browser"),
    ("context", "browser_profile_dir", "D:/different_profile"),
    ("context", "storage_state_path", "D:/different_state.json")])
def test_mismatched_requested_account_or_resolved_environment_never_pauses_or_opens(window, source, field, value):
    setattr(getattr(window, source), field, value)
    with pytest.raises(AccountRuntimeError) as error:
        invoke(window, snapshot_data={})
    assert error.value.code in {"account_uuid_mismatch", "browser_environment_mismatch"}
    assert not any(row[0] in {"pause", "lease_enter", "create", "open"} for row in window.events)


def test_missing_binding_is_rejected_before_pause(window):
    window.context.binding = None
    with pytest.raises(AccountRuntimeError) as error:
        invoke(window, snapshot_data={})
    assert error.value.code == "binding_required"
    assert not any(row[0] == "pause" for row in window.events)


@pytest.mark.parametrize("field,value", [("account_uuid", "account:other"), ("account_key", "other")])
def test_prepared_account_is_rechecked_inside_original_lease(window, field, value):
    setattr(window.prepared.profile, field, value)
    with pytest.raises(AccountRuntimeError) as error:
        invoke(window, snapshot_data={})
    assert error.value.code == "account_uuid_mismatch"
    assert ("lease_exit", "account01") in window.events
    assert not any(row[0] in {"create", "open"} for row in window.events)


@pytest.mark.parametrize("field,value", [("browser_environment_key", "other-browser"),
    ("browser_profile_dir", "D:/other_profile"), ("storage_state_path", "D:/other_state.json")])
def test_prepared_environment_is_rechecked_inside_lease_before_session_creation(window, field, value):
    setattr(window.prepared, field, value)
    with pytest.raises(AccountRuntimeError) as error:
        invoke(window, snapshot_data={})
    assert error.value.code == "browser_environment_mismatch"
    assert ("lease_exit", "account01") in window.events
    assert not any(row[0] in {"create", "open"} for row in window.events)


@pytest.mark.parametrize("field,value", [("headless", True), ("user_data_dir", "D:/wrong_profile"),
    ("storage_state_path", "D:/wrong_state.json")])
def test_actual_session_must_use_visible_original_profile_and_is_stopped_on_rejection(window, field, value):
    setattr(window.session.config, field, value)
    with pytest.raises(AccountRuntimeError) as error:
        invoke(window, snapshot_data={})
    assert error.value.code == "browser_environment_mismatch"
    assert ("stop",) in window.events and ("lease_exit", "account01") in window.events
    assert not any(row[0] == "open" for row in window.events)


@pytest.mark.parametrize("different_account", [False, True])
def test_production_relative_session_config_must_resolve_to_exact_original_binding(window, tmp_path, monkeypatch, different_account):
    monkeypatch.chdir(tmp_path)
    profile_relative = "data/douyin_warmup/account01/profile"
    state_relative = "data/douyin_warmup/account01/storage_state.json"
    for source in (window.context, window.binding, window.prepared):
        source.browser_profile_dir = str((tmp_path / profile_relative).resolve())
        source.storage_state_path = str((tmp_path / state_relative).resolve())
    window.session.config.user_data_dir = profile_relative.replace("account01", "account02") if different_account else profile_relative
    window.session.config.storage_state_path = state_relative
    if different_account:
        with pytest.raises(AccountRuntimeError) as error:
            invoke(window, snapshot_data={})
        assert error.value.code == "browser_environment_mismatch"
        assert not any(row[0] == "open" for row in window.events)
        assert ("stop",) in window.events
    else:
        result = invoke(window, snapshot_data={})
        assert result.closed and ("open", DOUYIN_SELF_URL, 1800) in window.events


def test_unknown_original_lease_is_not_stolen_and_original_exception_is_preserved(window):
    original = AccountRuntimeUnavailable("locked", "原未知任务仍持有锁", retry_at="old-claim")
    window.state.lease_error = original
    with pytest.raises(AccountRuntimeUnavailable) as error:
        invoke(window, snapshot_data={})
    assert error.value is original
    assert not any(row[0] in {"create", "open"} for row in window.events)
    assert window.logs[-1][-1] == "AccountRuntimeUnavailable"


def test_open_failure_closes_original_session_before_releasing_lease_without_logging_payload(window):
    original = RuntimeError("cookie: sensitive-session-token; https://private.example/?token=secret")
    window.state.open_error = original
    with pytest.raises(RuntimeError) as error:
        invoke(window, snapshot_data={})
    assert error.value is original
    assert window.events[-2:] == [("stop",), ("lease_exit", "account01")]
    assert window.logs[-1][-1] == "RuntimeError"
    assert "secret" not in repr(window.logs) and "sensitive-session-token" not in repr(window.logs)


def test_cleanup_failure_does_not_replace_original_open_failure(window):
    original = TimeoutError("original timeout")
    window.state.open_error = original
    window.state.stop_error = RuntimeError("cleanup failure")
    with pytest.raises(TimeoutError) as error:
        invoke(window, snapshot_data={})
    assert error.value is original
    assert any(row[0] == "cleanup_failed" and row[-1] == "RuntimeError" for row in window.logs)
    assert not window.state.active_lease


def test_default_pause_dependency_preserves_current_exception(window, monkeypatch):
    from src.scheduler import account_refresh
    monkeypatch.undo()
    calls = []
    monkeypatch.setattr(account_refresh, "pause_account", lambda *a, **k: calls.append((a, k)))
    module._pause_for_handling(window.profile.account_uuid, "account01")
    assert calls[0][1] == {"preserve_existing_pause": True}


def test_progress_waits_for_actual_open_confirmation_before_waiting_and_closing(window):
    phases = []
    result = invoke(window, on_progress=phases.append)
    assert result.closed
    assert phases == ['validating', 'preparing', 'acquiring', 'starting_browser', 'window_open_waiting_close', 'closed']
    assert [row[0] for row in window.logs] == ['requested', 'opening', 'page_opened', 'closed']


def test_startup_timeout_never_reports_opened_or_closed_and_releases_original_lease(window):
    phases = []
    window.state.open_error = TimeoutError('private startup details')
    with pytest.raises(TimeoutError):
        invoke(window, on_progress=phases.append)
    assert phases == ['validating', 'preparing', 'acquiring', 'starting_browser']
    assert not window.state.active_lease
    assert window.events[-2:] == [('stop',), ('lease_exit', 'account01')]
    assert not any(row[0] in ('page_opened', 'closed') for row in window.logs)


def test_missing_actual_open_confirmation_cannot_report_closed(window):
    phases = []
    window.session.open_for_manual_login_until_closed = lambda *args, **kwargs: None
    with pytest.raises(AccountRuntimeError) as error:
        invoke(window, on_progress=phases.append)
    assert error.value.code == 'manual_window_not_opened'
    assert phases[-1] == 'starting_browser'
    assert 'window_open_waiting_close' not in phases and 'closed' not in phases
    assert not window.state.active_lease
