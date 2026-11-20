"""Control-only fixtures: no platform, real profile or production database."""
import concurrent.futures
import json
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from src.operations_accounts.browser_control import (
    BrowserCommandResult, BrowserControlActor, BrowserControlDeferred, BrowserControlError,
    BrowserControlRejected, BrowserControlStore,
)


@pytest.fixture
def store(tmp_path):
    return BrowserControlStore(tmp_path / "control.sqlite")


def submit(store, key="one", kind="background", priority=0, account="a", binding="v1"):
    return store.submit(account, binding, kind, key, {"request": key}, priority)


def actor(store, handlers, **kwargs):
    return BrowserControlActor(store, "a", "v1", "owner", handlers, **kwargs)


@pytest.mark.parametrize('phase', ['admission', 'handler'])
def test_unexpected_failure_records_phase_without_replaying_unknown(store, phase):
    original = submit(store)
    calls = []

    def admission(ctx, current_phase):
        if phase == 'admission':
            raise sqlite3.OperationalError('private diagnostic content')

    def handler(ctx, payload):
        calls.append('handler')
        raise sqlite3.OperationalError('private diagnostic content')

    worker = actor(store, {'background': handler}, admission=admission)
    try:
        result = worker.run_next()
        assert result['state'] == 'outcome_unknown'
        assert result['result'] == dict(failure_phase=phase,
            handler_started=phase == 'handler', error_type='OperationalError')
        assert calls == ([] if phase == 'admission' else ['handler'])
        assert 'private diagnostic content' not in json.dumps(result)
        assert worker.run_next() is None
        assert store.get(original['command_id']) == result
    finally:
        worker.stop_heartbeat()


def test_concurrent_idempotency_has_one_original_id(store):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: submit(store), range(16)))
    assert len({r["command_id"] for r in results}) == 1
    assert len(store.snapshot("a")["commands"]) == 1
    with pytest.raises(BrowserControlRejected, match="different immutable"):
        store.submit("a", "v2", "background", "one", {"request": "one"})


def test_wrapped_timeout_retains_safe_cause_without_unlocking_unknown(store):
    from src.platform_adapter.browser_session import BrowserNavigationTimeout
    original = submit(store)
    def handler(ctx, payload):
        try:
            raise BrowserNavigationTimeout(dict(target_matched=False,
                navigation_committed=True, ready_state='loading', secret='private'))
        except BrowserNavigationTimeout as exc:
            raise RuntimeError('private credential URL') from exc
    worker = actor(store, {'background': handler})
    try:
        result = worker.run_next()
        assert result['state'] == 'outcome_unknown'
        cause = result['result']['exception_causes'][0]
        assert cause['code'] == 'browser_navigation_timeout'
        assert cause['navigation_evidence']['target_matched'] is False
        assert 'private' not in json.dumps(result)
        assert worker.run_next() is None
        assert store.get(original['command_id']) == result
    finally:
        worker.stop_heartbeat()


def test_diagnostics_bound_cycles_and_do_not_save_arbitrary_codes():
    from src.shared.exception_diagnostics import exception_causes
    first, second = RuntimeError('secret'), ValueError('secret')
    second.code = 'private_token'
    first.__cause__, second.__cause__ = second, first
    assert exception_causes(first) == [{'error_type': 'ValueError'}]


def test_concurrent_owner_single_winner(store):
    def acquire(i):
        try:
            return store.acquire_owner("a", "v1", str(i))
        except BrowserControlRejected:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(acquire, range(8)))
    assert sum(r is not None for r in results) == 1


def test_readonly_cross_process_style_snapshot_keeps_live_owner(store):
    owner = store.acquire_owner("a", "v1", "different-process-nonce")
    with sqlite3.connect(store.path) as db:
        before = db.execute("SELECT * FROM browser_control_owners").fetchall()
    other_client = BrowserControlStore(store.path)
    assert other_client.snapshot("a")["owner"]["state"] == "active"
    with sqlite3.connect(store.path) as db:
        assert before == db.execute("SELECT * FROM browser_control_owners").fetchall()
    assert owner["generation"] == 1


def test_real_other_process_reads_owner_without_reclassifying_it(store):
    store.acquire_owner("a", "v1", "original-process-owner")
    script = ("import json,sys; from src.operations_accounts.browser_control import BrowserControlStore; "
              "print(json.dumps(BrowserControlStore(sys.argv[1]).snapshot('a')))" )
    result = subprocess.run([sys.executable, "-B", "-c", script, str(store.path)],
                            capture_output=True, text=True, timeout=20, check=True)
    value = json.loads(result.stdout)
    assert value["owner"]["state"] == "active"
    assert value["owner"]["owner_id"] == "original-process-owner"


def test_existing_store_snapshot_does_not_need_write_lock(store):
    store.acquire_owner("a", "v1", "other")
    with sqlite3.connect(store.path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        assert BrowserControlStore(store.path).snapshot("a")["owner"]["state"] == "active"
        writer.rollback()


def test_existing_half_initialized_database_is_not_silently_repaired(tmp_path):
    path = tmp_path / "half.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE browser_control_owners(account_id TEXT PRIMARY KEY)")
    original = path.read_bytes()
    with pytest.raises(BrowserControlError, match="incomplete or incompatible"):
        BrowserControlStore(path)
    assert path.read_bytes() == original
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("browser_control_owners",)]


def test_existing_same_table_names_wrong_columns_rejected_without_writes(tmp_path):
    path = tmp_path / "wrong.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE browser_control_owners(account_id TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE browser_control_commands(command_id TEXT PRIMARY KEY)")
    original = path.read_bytes()
    with pytest.raises(BrowserControlError):
        BrowserControlStore(path)
    assert path.read_bytes() == original


def test_existing_schema_without_idempotency_unique_is_rejected(store):
    with sqlite3.connect(store.path) as db:
        original_sql = db.execute("SELECT sql FROM sqlite_master WHERE name='browser_control_commands'").fetchone()[0]
        db.execute("DROP TABLE browser_control_commands")
        db.execute(original_sql.replace("UNIQUE(account_id,idempotency_key)", "CHECK(priority IS NOT NULL)"))
    original = store.path.read_bytes()
    with pytest.raises(BrowserControlError, match="idempotency constraint"):
        BrowserControlStore(store.path)
    assert store.path.read_bytes() == original


def test_same_path_store_writers_wait_in_process_without_sqlite_busy_retry(store):
    """A long foreground metadata transaction must not race its heartbeat."""
    other = BrowserControlStore(store.path)
    store.acquire_owner("a", "v1", "owner")
    entered, release, heartbeat_done = threading.Event(), threading.Event(), threading.Event()
    def hold_transaction():
        with store._db(write=True) as db:
            db.execute("UPDATE browser_control_owners SET updated_at=updated_at WHERE account_id='a'")
            entered.set()
            assert release.wait(8)
    def heartbeat():
        other.heartbeat("a", "owner", 1)
        heartbeat_done.set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        holding = pool.submit(hold_transaction)
        assert entered.wait(5)
        waiting = pool.submit(heartbeat)
        # Exceed SQLite's 2s busy timeout deliberately. A separate Store object
        # shares the per-path in-process writer fence; no DB retry is performed.
        assert not heartbeat_done.wait(2.2)
        release.set()
        holding.result(timeout=5)
        waiting.result(timeout=5)
    assert heartbeat_done.is_set()
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"


def test_expired_heartbeat_unknown_and_not_reacquired(tmp_path):
    now = [100.]
    s = BrowserControlStore(tmp_path / "c.sqlite", clock=lambda: now[0], owner_ttl=10)
    s.acquire_owner("a", "v1", "old")
    now[0] = 111
    assert s.snapshot("a")["owner"]["state"] == "outcome_unknown"
    assert s.snapshot("a")["owner"]["persisted_state"] == "active"
    with pytest.raises(BrowserControlRejected):
        s.acquire_owner("a", "v1", "new")
    with pytest.raises(BrowserControlRejected):
        s.heartbeat("a", "old", 1)


def test_generation_fences_late_commands_after_clean_release(store):
    old = store.acquire_owner("a", "v1", "old")
    store.release_owner("a", "old", old["generation"])
    new = store.acquire_owner("a", "v1", "new")
    assert new["generation"] == 2
    with pytest.raises(BrowserControlRejected, match="generation"):
        store.heartbeat("a", "old", 1)


def test_different_accounts_and_binding_rejection(store):
    called = []
    submit(store, binding="old")
    submit(store, account="b")
    a = actor(store, {"background": lambda ctx, payload: called.append(payload) or {}})
    assert a.run_next()["error_code"] == "binding_changed"
    assert called == []
    assert store.snapshot("b")["commands"][0]["state"] == "queued"
    a.close()


def test_safe_point_persists_cursor_runs_priority_same_thread_then_resumes(store):
    events, identities, threads = [], [], []
    resource = object()
    def publish(ctx, payload):
        threads.append(threading.get_ident())
        identities.append(ctx.resource)
        paused = store.snapshot("a")["commands"]
        background = next(c for c in paused if c["kind"] == "background")
        assert background["state"] == "paused"
        assert background["cursor"] == {"item": 3, "last_result": "original-id"}
        events.append("publish")
        return {"work_id": "original-publication"}
    def background(ctx, payload):
        threads.append(threading.get_ident())
        identities.append(ctx.resource)
        events.append("before")
        submit(store, "publication", "publish", 100)
        assert ctx.safe_point({"item": 3, "last_result": "original-id"}) >= 0
        events.append("after")
        return {"resumed_item": 4}
    submit(store)
    gates = []
    a = actor(store, {"background": background, "publish": publish}, context=resource,
              admission=lambda ctx, phase: gates.append((ctx.command["kind"], phase)))
    result = a.run_next()
    assert result["state"] == "succeeded"
    assert events == ["before", "publish", "after"]
    assert len(set(threads)) == 1 and identities == [resource, resource]
    assert gates == [("background", "start"), ("publish", "start"), ("background", "resume")]
    a.close()


@pytest.mark.parametrize("outcome", ["failed", "waiting_human", "outcome_unknown", "exception"])
def test_priority_failure_or_unknown_never_blindly_resumes_background(store, outcome):
    events = []
    def publish(ctx, payload):
        if outcome == "exception":
            raise TimeoutError("external result not known")
        return BrowserCommandResult(outcome, {"original_id": "must-preserve"})
    def background(ctx, payload):
        submit(store, "pub", "publish", 100)
        ctx.safe_point({"next_item": 4})
        events.append("unsafe-resume")
        return {}
    submit(store)
    a = actor(store, {"background": background, "publish": publish})
    assert a.run_next()["state"] == "paused"
    assert events == []
    assert a.run_next() is None
    with pytest.raises(BrowserControlRejected):
        a.close()
    a.stop_heartbeat()


def test_resume_rechecks_changed_safety_gate(store):
    blocked = [False]
    def admission(ctx, phase):
        if blocked[0]:
            raise BrowserControlDeferred("human_required", "manual verification now required")
    def publish(ctx, payload):
        blocked[0] = True
        return {"published_id": "known"}
    def background(ctx, payload):
        submit(store, "pub", "publish", 100)
        ctx.safe_point({"item": 1})
        pytest.fail("Must not resume")
    submit(store)
    a = actor(store, {"background": background, "publish": publish}, admission=admission)
    assert a.run_next()["state"] == "paused"
    assert store.get(next(c["task_id"] for c in store.snapshot("a")["commands"] if c["kind"] == "publish"))["state"] == "succeeded"
    a.stop_heartbeat()


def test_deferred_admission_preserves_queue_and_id(store):
    original = submit(store, kind="publish")
    calls = []
    def gate(ctx, phase):
        raise BrowserControlDeferred("human_required", "wait")
    a = actor(store, {"publish": lambda c, p: calls.append(p) or {}}, admission=gate)
    result = a.run_next()
    assert result["state"] == "queued" and result["command_id"] == original["command_id"]
    assert result["owner_id"] is None
    assert calls == [] and store.list_pending_accounts() == ["a"]
    a.close()


def test_waiting_human_short_handler_and_explicit_known_close(store):
    submit(store, kind="manual")
    a = actor(store, {"manual": lambda c, p: BrowserCommandResult("waiting_human", {"tab_id": "original-tab"})})
    command = a.run_next()
    assert command["state"] == "waiting_human"
    with pytest.raises(BrowserControlRejected):
        store.complete_waiting(command["task_id"], "other", 1)
    finished = store.complete_waiting(command["task_id"], a.owner_id, a.generation, {"window_closed": True, "identity_verified": False})
    assert finished["result"]["identity_verified"] is False
    a.close()


def test_unknown_survives_restart_and_is_not_dispatched_again(store):
    original = submit(store)
    a = actor(store, {"background": lambda c, p: (_ for _ in ()).throw(TimeoutError())})
    assert a.run_next()["state"] == "outcome_unknown"
    a.stop_heartbeat()
    other = BrowserControlStore(store.path)
    same = submit(other)
    assert same["task_id"] == original["task_id"] and same["state"] == "outcome_unknown"
    with pytest.raises(BrowserControlRejected):
        actor(other, {}).run_next()


def test_long_handler_has_heartbeat_without_browser_cross_thread(tmp_path):
    now = [100.]
    s = BrowserControlStore(tmp_path / "h.sqlite", owner_ttl=10, clock=lambda: now[0])
    thread_ids = []
    def handler(ctx, payload):
        thread_ids.append(threading.get_ident())
        # Advance beyond the original TTL while waiting for each actual durable
        # heartbeat. This avoids assuming subsecond disk latency on Windows.
        for _ in range(12):
            now[0] += 1
            deadline = time.monotonic() + 5
            while s.snapshot("a")["owner"]["heartbeat"] < now[0]:
                assert time.monotonic() < deadline
                time.sleep(.02)
        assert s.snapshot("a")["owner"]["state"] == "active"
        assert s.snapshot("a")["owner"]["heartbeat"] == 112
        return {}
    submit(s)
    a = actor(s, {"background": handler}, heartbeat_seconds=.04)
    assert a.run_next()["state"] == "succeeded"
    assert thread_ids == [threading.get_ident()]
    a.close()


def test_nonowner_thread_cannot_dispatch_browser(store):
    a = actor(store, {}).start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(a.run_next)
        with pytest.raises(BrowserControlRejected, match="owner thread"):
            future.result()
    a.close()


def test_dispatch_gate_is_public_and_checked_again(store):
    calls = []
    def handler(ctx, payload):
        ctx.check_dispatch()
        calls.append("external")
        return {}
    gates = []
    submit(store)
    a = actor(store, {"background": handler}, admission=lambda c, p: gates.append(p))
    assert a.run_next()["state"] == "succeeded"
    assert gates == ["start", "dispatch"] and calls == ["external"]
    a.close()


def test_priority_waits_for_explicit_safe_point_or_current_task_end(store):
    calls = []
    def background(ctx, payload):
        submit(store, "publication", "publish", 100)
        calls.append("background-completed")
        return {}
    submit(store)
    a = actor(store, {"background": background, "publish": lambda c, p: calls.append("publish") or {}})
    assert a.run_next()["state"] == "succeeded"
    assert calls == ["background-completed"]
    assert a.run_next()["state"] == "succeeded"
    assert calls == ["background-completed", "publish"]
    a.close()


def test_legacy_handler_cannot_launder_caught_suspension_as_success(store):
    def background(ctx, payload):
        submit(store, "publication", "publish", 100)
        try:
            ctx.safe_point({"saved_item": 2})
        except Exception:
            pass
        with pytest.raises(Exception, match="suspended"):
            ctx.check_dispatch()
        return {"legacy_result": "failed-but-caught"}
    submit(store)
    a = actor(store, {"background": background,
                      "publish": lambda c, p: BrowserCommandResult("failed", {})})
    result = a.run_next()
    assert result["state"] == "paused" and result["cursor"] == {"saved_item": 2}
    a.stop_heartbeat()


def test_only_manual_recovery_can_cross_known_paused_background(store):
    def background(ctx, payload):
        submit(store, "pub", "publish", 100)
        ctx.safe_point({"saved_item": 2})
        return {}
    submit(store)
    called = []
    a = actor(store, {"background": background,
                      "publish": lambda c, p: BrowserCommandResult("failed", {}),
                      "recovery": lambda c, p: called.append("recovery") or {"healthy": True}})
    assert a.run_next()["state"] == "paused"
    submit(store, "new-business", "publish", 500)
    submit(store, "recovery", "recovery", 300)
    assert a.run_next()["state"] == "succeeded"
    assert called == ["recovery"]
    assert a.run_next() is None
    assert store.get(next(c["task_id"] for c in store.snapshot("a")["commands"] if c["kind"] == "background"))["state"] == "paused"
    a.stop_heartbeat()
