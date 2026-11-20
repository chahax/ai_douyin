from __future__ import annotations

import pytest

from src.platform_adapter.douyin_identity import (
    DouyinIdentityVerificationError,
    DouyinPageIdentityVerifier,
)


class _Locator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector

    def evaluate(self, script: str):
        if "data-douyin-visible-challenge" in script:
            return dict(blocking=self.page.challenge_visible,frame_count=1,
                actionable_frames=int(self.page.challenge_visible),visible_dialogs=0, surface_states=["challenge_ready"] if self.page.challenge_visible else [])
        if "publicMatch" in script:
            if not self.page.profile_open:
                return {}
            return {
                "nickname": "法律号",
                "avatar_url": "https://example.com/avatar.jpg",
                "public_uid": "dy-legal-01",
                "sec_uid": "",
            }
        return None

    def count(self) -> int:
        if self.selector == 'a[href*="/user/self"]':
            return 1
        return 0

    def first(self):
        return self

    def click(self) -> None:
        self.page.profile_open = True

    def inner_text(self) -> str:
        return self.page.body_text


class _Page:
    def __init__(self, *, challenge_visible: bool = False):
        self.challenge_visible = challenge_visible
        self.profile_open = False
        self.body_text = "抖音精选"

    def locator(self, selector: str):
        return _Locator(self, selector)

    def wait_for_timeout(self, milliseconds: int) -> None:
        pass


class _Session:
    def __init__(self, page):
        self.page = page

    def open_page(self, url: str):
        return self.page


def test_identity_probe_clicks_my_profile_after_self_url_redirect() -> None:
    page = _Page()

    identity = DouyinPageIdentityVerifier().probe(_Session(page))

    assert page.profile_open is True
    assert identity.nickname == "法律号"
    assert identity.public_uid == "dy-legal-01"


def test_identity_probe_only_blocks_for_visible_challenge() -> None:
    page = _Page(challenge_visible=True)

    with pytest.raises(DouyinIdentityVerificationError) as error:
        DouyinPageIdentityVerifier().probe(_Session(page))

    assert error.value.code == "human_required"


def test_identity_with_login_link_still_reuses_authenticated_profile():
    page = _Page()
    page.body_text = "法律号 抖音号：dy-legal-01 扫码登录"
    identity = DouyinPageIdentityVerifier().probe(_Session(page))
    assert identity.public_uid == "dy-legal-01"


def test_unreadable_profile_without_login_prompt_is_not_expiry():
    page = _Page()
    page.locator = lambda selector: _UnavailableLocator(page, selector)
    with pytest.raises(DouyinIdentityVerificationError) as error:
        DouyinPageIdentityVerifier().probe(_Session(page))
    assert error.value.code == "identity_unavailable"


class _UnavailableLocator(_Locator):
    def evaluate(self, script):
        return dict(blocking=False,frame_count=0,actionable_frames=0,visible_dialogs=0) if "data-douyin-visible-challenge" in script else {}


def test_explicit_login_prompt_without_identity_reports_expiry():
    page = _Page()
    page.body_text = "扫码登录 验证码登录"
    page.locator = lambda selector: _UnavailableLocator(page, selector)
    with pytest.raises(DouyinIdentityVerificationError) as error:
        DouyinPageIdentityVerifier().probe(_Session(page))
    assert error.value.code == "login_expired"


def timeout_session(page, **overrides):
    from src.platform_adapter.browser_session import BrowserNavigationTimeout
    proof = dict(navigation_committed=True, target_matched=True, ready_state='complete')
    proof.update(overrides)
    error = BrowserNavigationTimeout(proof)
    error.page = page
    calls = []
    class Session:
        def open_page(self, url):
            calls.append(url)
            raise error
    return Session(), calls


def test_committed_timeout_reads_original_identity_without_second_navigation():
    page = _Page()
    page.profile_open = True
    session, calls = timeout_session(page)
    assert DouyinPageIdentityVerifier().probe(session).public_uid == 'dy-legal-01'
    assert len(calls) == 1


@pytest.mark.parametrize('proof', [
    {'target_matched': False}, {'navigation_committed': False}, {'ready_state': 'loading'},
])
def test_timeout_never_accepts_stale_identity(proof):
    page = _Page()
    page.profile_open = True
    session, calls = timeout_session(page, **proof)
    with pytest.raises(DouyinIdentityVerificationError) as error:
        DouyinPageIdentityVerifier().probe(session)
    assert error.value.code == 'browser_navigation_timeout'
    assert error.value.navigation_evidence
    assert len(calls) == 1


def test_timeout_without_identity_does_not_click_or_reload():
    page = _Page()
    session, calls = timeout_session(page)
    with pytest.raises(DouyinIdentityVerificationError) as error:
        DouyinPageIdentityVerifier().probe(session)
    assert error.value.code == 'browser_navigation_timeout'
    assert not page.profile_open
    assert len(calls) == 1


def test_timeout_retains_real_challenge_priority():
    page = _Page(challenge_visible=True)
    page.profile_open = True
    session, calls = timeout_session(page)
    with pytest.raises(DouyinIdentityVerificationError) as error:
        DouyinPageIdentityVerifier().probe(session)
    assert error.value.code == 'human_required'
    assert len(calls) == 1
