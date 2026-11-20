"""Functional lifecycle checks with real Chrome and persistent command state."""
from types import SimpleNamespace as NS
import pytest

from test_browser_navigation_repair import local_browser
from src.platform_adapter.browser_session import BrowserSession, BrowserWorkerUnavailable
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserCommandResult, BrowserControlRejected
from src.operations_accounts.browser_control_runtime import _poll_manual_windows


def resource(session):
    value = NS(account_uuid="test:dead", session=session, manual_tasks={}, console_tasks={}, headless=True)
    def shutdown():
        value.session.stop()
        value.session = None
    value.shutdown = shutdown
    return value


def test_real_worker_exit_keeps_failed_command_and_next_task_can_open_browser(local_browser, tmp_path):
    session, url = local_browser
    store = BrowserControlStore(tmp_path / "control.db")
    state = resource(session)
    original = store.submit("test:dead", "binding", "read", "first", {})
    def first(*_):
        session.open_page(url)
        session._proc.kill()
        session._proc.wait(timeout=5)
        assert session.worker_failure() == "worker_exited"
        with pytest.raises(BrowserWorkerUnavailable):
            session.new_tab("must-not-restart-in-handler")
        return BrowserCommandResult("failed", {"worker_failed": True})
    actor = BrowserControlActor(store, "test:dead", "binding", "owner", {"read": first})
    try:
        assert actor.run_next()["state"] == "failed"
        frozen = store.get(original["command_id"])
        _poll_manual_windows(actor, state)
        assert state.session is None
        followup = store.submit("test:dead", "binding", "read", "next-independent", {})
        def second(*_):
            fresh = BrowserSession(session.config)
            state.session = fresh
            page = fresh.open_page(url)
            return {"links": page.locator("a").count()}
        actor.handlers["read"] = second
        assert actor.run_next()["result"] == {"links": 1}
        assert store.get(original["command_id"]) == frozen
        assert store.get(followup["command_id"])["state"] == "succeeded"
        assert store.snapshot("test:dead")["owner"]["state"] == "active"
    finally:
        if state.session:
            state.shutdown()
        actor.stop_heartbeat()


@pytest.mark.parametrize("terminal", ["outcome_unknown", "waiting_human"])
def test_unresolved_original_worker_loss_never_clears_or_replays(tmp_path, terminal):
    store = BrowserControlStore(tmp_path / "control.db")
    original = store.submit("test:dead", "binding", "read", "uncertain", {})
    actor = BrowserControlActor(store, "test:dead", "binding", "owner",
        {"read": lambda *_: BrowserCommandResult(terminal, {"original": True})})
    try:
        actor.run_next()
        frozen = store.get(original["command_id"])
        state = resource(NS(worker_failure=lambda: "response_channel_closed"))
        state.shutdown = lambda: pytest.fail("Protected original resource cannot be discarded")
        with pytest.raises(BrowserControlRejected) as error:
            _poll_manual_windows(actor, state)
        assert error.value.code == "worker_lost_unresolved"
        assert store.get(original["command_id"]) == frozen
    finally:
        actor.stop_heartbeat()
