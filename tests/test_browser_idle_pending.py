import pytest
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor, BrowserCommandResult
from src.operations_accounts.browser_control_runtime import _has_pending_original_work


@pytest.mark.parametrize("state,expected", [
    ("failed", False), ("succeeded", False), ("outcome_unknown", True), ("waiting_human", True),
])
def test_idle_uses_unresolved_work_without_loading_full_history(tmp_path, state, expected):
    store = BrowserControlStore(tmp_path / "control.db")
    store.submit("acct:test", "binding", "read", "original", {})
    actor = BrowserControlActor(store, "acct:test", "binding", "owner",
        {"read": lambda *_: BrowserCommandResult(state, {"original": True})})
    try:
        actor.run_next()
        store.snapshot = lambda *_: pytest.fail("Idle must not load full historical receipts")
        assert _has_pending_original_work(store, "acct:test") is expected
        queued = store.submit("acct:test", "binding", "read", "queued", {})
        assert _has_pending_original_work(store, "acct:test")
        assert store.get(queued["command_id"])["state"] == "queued"
    finally:
        actor.stop_heartbeat()
