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
            return self.page.challenge_visible
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
