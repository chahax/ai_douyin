from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.platform_adapter.browser_session import BrowserSession, Page
from src.platform_adapter.models import BrowserSessionConfig


class Commands:
    _default_tab_id = "original"

    def __init__(self):
        self.calls = []

    def cmd(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return {"value": "value", "count": 1, "texts": ["text"], "matched": True}


def test_retained_locator_and_derived_locator_never_switch_to_new_task_tab():
    session = Commands()
    first = Page(session)
    retained = first.locator("input").nth(2).first()
    second = Page(session, tab_id="publishing")
    second.locator("input").fill("publish")
    retained.fill("background")
    first.evaluate("document.title")
    assert [call[1]["tab_id"] for call in session.calls] == ["publishing", "original", "original"]
    assert session.calls[1][1]["value"] == "background"
    assert retained.tab_id == "original"


def test_all_page_ownership_operations_including_declarations_keep_the_bound_page():
    session = Commands()
    page = Page(session, tab_id="publication")
    page.goto("http://127.0.0.1/")
    page.ai_content_declaration(set_selected=True)
    page.inspect_published_video("specific-post", ai_required=True, fiction_required=True)
    page.interact_visible_exact_text("publish", operation="inspect")
    page.first().click()
    assert all(kwargs["tab_id"] == "publication" for _, kwargs in session.calls)


def test_legacy_fakes_without_tab_protocol_remain_compatible():
    calls = []
    session = SimpleNamespace(cmd=lambda action, **kwargs: calls.append((action, kwargs)) or {})
    Page(session).locator("input").fill("old")
    assert calls == [("fill", {"selector": "input", "value": "old", "index": -1})]


def test_page_built_by_old_helpers_uses_borrowed_tab_before_owner_default():
    session = Commands()
    session.tab_id = "borrowed-publication"
    Page(session).locator("input").first().fill("borrowed")
    assert session.calls[0][1]["tab_id"] == "borrowed-publication"
    Page(session, tab_id="explicit").evaluate("document.title")
    assert session.calls[1][1]["tab_id"] == "explicit"


def test_status_without_owner_fails_without_launching_or_claiming_closed(tmp_path, monkeypatch):
    config = BrowserSessionConfig("http://127.0.0.1", "http://127.0.0.1",
        str(tmp_path / "state.json"), str(tmp_path / "profile"))
    session = BrowserSession(config)
    monkeypatch.setattr(session, "_start", lambda: pytest.fail("status must not create a worker"))
    with pytest.raises(RuntimeError):
        session.window_status()
    with pytest.raises(RuntimeError):
        session.list_tabs()
    assert session._response_timeout_seconds({"action": "window_status"}) == 5


def test_get_page_rejects_closed_or_missing_handle_without_default_fallback(tmp_path, monkeypatch):
    config = BrowserSessionConfig("http://127.0.0.1", "http://127.0.0.1",
        str(tmp_path / "state.json"), str(tmp_path / "profile"))
    session = BrowserSession(config)
    session._default_tab_id = "original"
    monkeypatch.setattr(session, "_start", lambda: None)
    monkeypatch.setattr(session, "_send", lambda command: {"tabs": [
        {"tab_id": "original", "closed": False}, {"tab_id": "closed", "closed": True}]})
    assert session.get_page().tab_id == "original"
    for handle in ("closed", "absent"):
        with pytest.raises(RuntimeError, match="missing or closed"):
            session.get_page(handle)


@pytest.mark.parametrize("role", ["", " ", None, "x" * 81])
def test_invalid_role_does_not_start_a_browser(tmp_path, monkeypatch, role):
    session = BrowserSession(BrowserSessionConfig("http://127.0.0.1", "http://127.0.0.1",
        str(tmp_path / "state.json"), str(tmp_path / "profile")))
    monkeypatch.setattr(session, "_start", lambda: pytest.fail("invalid role launched browser"))
    with pytest.raises(ValueError):
        session.new_tab(role)
