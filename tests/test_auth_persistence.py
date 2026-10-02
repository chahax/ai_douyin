from __future__ import annotations

from types import SimpleNamespace

from src.shared.config import settings
from src.web.components import auth


class FakeCookies(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_count = 0

    @property
    def _cookies(self):
        return self

    def save(self) -> None:
        self.save_count += 1


def test_signed_cookie_persists_and_restores_login(monkeypatch):
    monkeypatch.setattr(auth, "_get_session_secret", lambda: "test-session-secret")
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(auth, "st", fake_st)
    cookies = FakeCookies()

    auth._persist_session_cookie(cookies, "alice", "admin")

    assert cookies.save_count == 1
    assert settings.SESSION_COOKIE_NAME in cookies
    assert auth._try_restore_session_from_cookie(cookies) is True
    assert fake_st.session_state["user"] == "alice"
    assert fake_st.session_state["user_role"] == "admin"


def test_invalid_cookie_is_removed(monkeypatch):
    monkeypatch.setattr(auth, "_get_session_secret", lambda: "test-session-secret")
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state={}))
    cookies = FakeCookies({settings.SESSION_COOKIE_NAME: "invalid-token"})

    assert auth._try_restore_session_from_cookie(cookies) is False
    assert settings.SESSION_COOKIE_NAME not in cookies
    assert cookies.save_count == 1


def test_logout_marks_cookie_for_deletion_on_next_rerun(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={"user": "alice", "user_role": "admin"}
    )
    monkeypatch.setattr(auth, "st", fake_st)

    auth.logout_user()

    assert "user" not in fake_st.session_state
    assert "user_role" not in fake_st.session_state
    assert fake_st.session_state[auth._LOGOUT_PENDING_KEY] is True


def test_pending_queue_is_not_browser_confirmation(monkeypatch):
    monkeypatch.setattr(auth, '_get_session_secret', lambda: 'test-secret')
    monkeypatch.setattr(auth, 'st', SimpleNamespace(session_state={}))
    class PendingCookies(dict):
        _cookies = {}
        def save(self):
            pass
    cookies = PendingCookies()
    auth._persist_session_cookie(cookies, 'alice', 'viewer')
    token = cookies[settings.SESSION_COOKIE_NAME]
    assert not auth._confirm_cookie_write(cookies)
    assert not auth._try_restore_session_from_cookie(cookies)
    auth._persist_session_cookie(cookies, 'alice', 'viewer')
    assert cookies[settings.SESSION_COOKIE_NAME] == token
    cookies._cookies = dict(cookies)
    assert auth._confirm_cookie_write(cookies)
    assert auth._COOKIE_WRITE_PENDING_KEY not in auth.st.session_state


def test_login_refresh_logout_with_delayed_browser_ack(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src.services import user_profile_service
    import streamlit as st
    browser, queue = {}, {}
    class DelayedCookies(dict):
        def __init__(self):
            super().__init__()
            self._cookies = dict(browser)
            self._queue = queue
            for key, item in list(queue.items()):
                if self._cookies.get(key) == item['value']:
                    queue.pop(key)
        def ready(self):
            return True
        def __setitem__(self, key, value):
            queue[key] = dict(value=value, path='/')
        def save(self):
            pass  # Browser acknowledgement is deliberately delayed by the test.
    def acknowledge():
        for key, item in list(queue.items()):
            if item['value'] is None:
                browser.pop(key, None)
            else:
                browser[key] = item['value']
    def fake_login(username, password):
        st.session_state.update(user=username, user_role='viewer')
        return True, 'viewer'
    monkeypatch.setattr(auth, '_get_cookie_manager', DelayedCookies)
    monkeypatch.setattr(auth, '_get_session_secret', lambda: 'test-secret')
    monkeypatch.setattr(auth, 'login_user', fake_login)
    monkeypatch.setattr(user_profile_service, 'count_ip_accounts', lambda ip: 0)
    source = '''from src.web.components.auth import render_login_page, logout_user
import streamlit as st
if render_login_page():
    st.success('protected-content')
    st.button('logout', on_click=logout_user)
'''
    app = AppTest.from_string(source).run()
    app.text_input[0].set_value('test-only-user')
    app.text_input[1].set_value('test-only-password')
    app.button[0].click().run()
    assert not app.exception
    assert not app.success
    assert queue and not browser
    app.run()  # Still no acknowledgement: do not enter protected content.
    assert not app.success
    acknowledge()
    app.run()
    assert not app.exception
    assert app.success[0].value == 'protected-content'
    # A full refresh creates a fresh session; only the browser cookie survives.
    refreshed = AppTest.from_string(source).run()
    assert refreshed.success[0].value == 'protected-content'
    refreshed.button[0].click().run()
    assert not refreshed.success
    assert refreshed.session_state[auth._LOGOUT_PENDING_KEY]
    refreshed.run()  # Old browser cookie must not silently restore the user.
    assert not refreshed.success
    acknowledge()
    refreshed.run()
    assert not refreshed.exception
    assert not refreshed.success
    assert len(refreshed.text_input) == 2
    assert not browser


def test_cookie_adapter_requests_readback(monkeypatch):
    from streamlit_cookies_manager import cookie_manager
    calls = []
    def component(**kwargs):
        calls.append(kwargs)
        return ''
    monkeypatch.setattr(cookie_manager, '_component_func', component)
    monkeypatch.setattr(cookie_manager, 'st', SimpleNamespace(session_state={}))
    cookies = auth._get_cookie_manager()
    cookies[settings.SESSION_COOKIE_NAME] = 'test-only'
    cookies.save()
    assert calls[-1]['saveOnly'] is False
    assert calls[-1]['queue'][settings.SESSION_COOKIE_NAME]['path'] == '/'
