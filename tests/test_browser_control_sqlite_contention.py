import sqlite3
from types import SimpleNamespace

import pytest

from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlRejected, BrowserControlStore


def busy():
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


def actor_for(store):
    return BrowserControlActor(store, "account", "binding", "owner", {}, heartbeat_seconds=store.owner_ttl / 2)


@pytest.mark.parametrize("phase", ["heartbeat", "claim_next"])
def test_predispatch_busy_preserves_original_queue(tmp_path, monkeypatch, phase):
    store = BrowserControlStore(tmp_path / "control.db")
    command = store.submit("account", "binding", "read", "original", {})
    actor = actor_for(store)
    actor.start()
    try:
        monkeypatch.setattr(store, phase, lambda *a, **k: (_ for _ in ()).throw(busy()))
        assert actor.run_next() is None
        assert store.get(command["command_id"])["state"] == "queued"
        assert actor._heartbeat_error is None
    finally:
        actor.stop_heartbeat()


def test_handler_completion_busy_is_not_swallowed(tmp_path, monkeypatch):
    store = BrowserControlStore(tmp_path / "control.db")
    command = store.submit("account", "binding", "read", "original", {})
    actor = actor_for(store)
    monkeypatch.setattr(actor, "_execute", lambda *a: (_ for _ in ()).throw(busy()))
    try:
        with pytest.raises(sqlite3.OperationalError):
            actor.run_next()
        assert store.get(command["command_id"])["state"] == "running"
    finally:
        actor.stop_heartbeat()


def test_ttl_expiry_after_busy_still_fences_owner(tmp_path, monkeypatch):
    now = [100.]
    store = BrowserControlStore(tmp_path / "control.db", clock=lambda: now[0], owner_ttl=10)
    actor = actor_for(store)
    actor.start()
    original = store.heartbeat
    try:
        monkeypatch.setattr(store, "heartbeat", lambda *a: (_ for _ in ()).throw(busy()))
        assert actor.run_next() is None
        monkeypatch.setattr(store, "heartbeat", original)
        now[0] += 11
        with pytest.raises(BrowserControlRejected, match="live"):
            actor.run_next()
    finally:
        actor.stop_heartbeat()


def test_heartbeat_busy_waits_normal_interval_without_marking_unknown():
    events = []
    waits = iter([False, False, True])
    def heartbeat(*args):
        events.append("heartbeat")
        if len(events) == 1:
            raise busy()
    store = SimpleNamespace(owner_ttl=90, heartbeat=heartbeat, mark_owner_unknown=lambda *args: events.append("unknown"))
    actor = actor_for(store)
    actor._stop = SimpleNamespace(wait=lambda seconds: next(waits))
    actor._heartbeats()
    assert events == ["heartbeat", "heartbeat"]
    assert actor._heartbeat_error is None


def test_noncontention_database_error_propagates(tmp_path, monkeypatch):
    actor = actor_for(BrowserControlStore(tmp_path / "control.db"))
    monkeypatch.setattr(actor, "start", lambda: (_ for _ in ()).throw(sqlite3.DatabaseError("corrupt")))
    with pytest.raises(sqlite3.DatabaseError):
        actor.run_next()


def test_browser_action_guards_check_fencing_without_writing_heartbeats(tmp_path,monkeypatch):
    store=BrowserControlStore(tmp_path/'control.db')
    actor=actor_for(store)
    actor.start()
    try:
        monkeypatch.setattr(store,'heartbeat',lambda *args:pytest.fail('read/click guards must not write'))
        for _ in range(20):actor._check_owner()
        with store._db(write=True) as db:
            db.execute("UPDATE browser_control_owners SET generation=generation+1")
        with pytest.raises(BrowserControlRejected,match='generation'):actor._check_owner()
    finally:actor.stop_heartbeat()


def test_readonly_dispatch_guard_never_extends_expired_owner(tmp_path):
    clock=[1000.0]
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:clock[0])
    actor=actor_for(store);actor.start()
    try:
        clock[0]+=91
        with pytest.raises(BrowserControlRejected,match='live'):actor._check_owner()
    finally:actor.stop_heartbeat()


def test_real_rollback_journal_reader_defers_commit_without_replaying(tmp_path):
    store = BrowserControlStore(tmp_path / "control.db")
    command = store.submit("account", "binding", "read", "original", {})
    calls = []
    actor = actor_for(store)
    actor.handlers["read"] = lambda ctx, payload: calls.append("once") or {"ok": True}
    actor.start()
    reader = sqlite3.connect(store.path)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM browser_control_owners").fetchall()
        assert actor.run_next() is None
        assert calls == []
        assert store.get(command["command_id"])["state"] == "queued"
        reader.rollback()
        assert actor.run_next()["state"] == "succeeded"
        assert actor.run_next() is None
        assert calls == ["once"]
    finally:
        reader.close()
        actor.stop_heartbeat()
