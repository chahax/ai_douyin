import pytest

from src.platform_adapter.fanqie_batch import (
    _click_ranking_tab,
    _dismiss_known_modal,
    _wait_for_active_ranking,
)


MODAL = 'div[role="dialog"].arco-modal:visible'
RANKING = ".task-menu-second .task-menu-second-item"


class _TextItem:
    def __init__(self, text):
        self._text = text

    def inner_text(self):
        return self._text


class _Locator:
    def __init__(self, page, kind, index=-1):
        self.page = page
        self.kind = kind
        self.index = index

    def count(self):
        if self.kind == "modal":
            return 1 if self.page.modal_visible else 0
        if self.kind == "close":
            return 1 if self.page.modal_visible and self.page.close_icon else 0
        if self.kind == "buttons":
            return len(self.page.button_texts) if self.page.modal_visible else 0
        return 4

    def first(self):
        return _Locator(self.page, self.kind, 0)

    def nth(self, index):
        return _Locator(self.page, self.kind, index)

    def inner_text(self):
        return self.page.modal_text

    def all(self):
        return [_TextItem(text) for text in self.page.button_texts]

    def click(self):
        if self.kind == "ranking":
            self.page.ranking_clicks += 1
            if self.page.ranking_failures:
                self.page.ranking_failures -= 1
                raise RuntimeError("modal intercepted pointer events")
            self.page.active_ranking = (
                "爆款榜", "阅读榜", "潜力榜", "全部内容"
            )[self.index]
            return
        if self.kind == "close":
            self.page.dismiss_clicks += 1
            self.page.modal_visible = False
            return
        if self.kind == "buttons":
            self.page.dismiss_clicks += 1
            if self.page.button_texts[self.index] in {
                "关闭", "我知道了", "取消", "Close", "Cancel", "Dismiss"
            }:
                self.page.modal_visible = False

    def evaluate(self, _javascript):
        return self.page.active_ranking


class _Page:
    def __init__(
        self,
        *,
        modal_visible=False,
        modal_text="",
        button_texts=(),
        close_icon=False,
        ranking_failures=0,
        active_ranking="",
    ):
        self.modal_visible = modal_visible
        self.modal_text = modal_text
        self.button_texts = list(button_texts)
        self.close_icon = close_icon
        self.ranking_failures = ranking_failures
        self.active_ranking = active_ranking
        self.ranking_clicks = 0
        self.dismiss_clicks = 0

    def locator(self, selector):
        if selector == "":
            return _Locator(self, "root")
        if selector == RANKING:
            return _Locator(self, "ranking")
        if selector == MODAL:
            return _Locator(self, "modal")
        if " button," in selector:
            return _Locator(self, "buttons")
        if any(token in selector for token in (
            ".arco-modal-close-icon",
            'button[aria-label="Close"]',
            ".arco-modal-close-btn",
        )):
            return _Locator(self, "close")
        raise AssertionError(f"unexpected selector: {selector}")

    def wait_for_timeout(self, _milliseconds):
        return None


def test_no_modal_is_a_noop():
    page = _Page()

    assert _dismiss_known_modal(page) == "none"
    assert page.dismiss_clicks == 0


def test_informational_modal_closes_via_scoped_close_icon():
    page = _Page(
        modal_visible=True,
        modal_text="平台规则更新公告",
        button_texts=("查看详情",),
        close_icon=True,
    )

    assert _dismiss_known_modal(page) == "closed"
    assert page.modal_visible is False
    assert page.dismiss_clicks == 1


def test_exact_safe_button_closes_without_clicking_other_button():
    page = _Page(
        modal_visible=True,
        modal_text="温馨提示",
        button_texts=("查看详情", "我知道了"),
    )

    assert _dismiss_known_modal(page) == "closed"
    assert page.dismiss_clicks == 1


def test_business_modal_is_never_closed_even_with_close_control():
    page = _Page(
        modal_visible=True,
        modal_text="申请推广：确认提交申请",
        button_texts=("取消", "确认申请"),
        close_icon=True,
    )

    with pytest.raises(RuntimeError, match="Refusing to close business modal"):
        _dismiss_known_modal(page)

    assert page.modal_visible is True
    assert page.dismiss_clicks == 0


def test_authentication_modal_is_never_dismissed():
    page = _Page(
        modal_visible=True,
        modal_text="欢迎登录番茄达人\n验证码登录\n登录/注册",
        button_texts=("登录/注册",),
        close_icon=True,
    )

    with pytest.raises(RuntimeError, match="authentication required"):
        _dismiss_known_modal(page)

    assert page.modal_visible is True
    assert page.dismiss_clicks == 0


def test_unknown_modal_fails_with_text_and_buttons():
    page = _Page(
        modal_visible=True,
        modal_text="身份校验",
        button_texts=("立即验证",),
    )

    with pytest.raises(RuntimeError) as exc_info:
        _dismiss_known_modal(page)

    message = str(exc_info.value)
    assert "身份校验" in message
    assert "立即验证" in message
    assert page.dismiss_clicks == 0


def test_ranking_click_succeeds_without_modal():
    page = _Page()

    _click_ranking_tab(page, 2)

    assert page.ranking_clicks == 1


def test_ranking_click_retries_once_after_safe_close():
    page = _Page(
        modal_visible=True,
        modal_text="平台公告",
        close_icon=True,
        ranking_failures=1,
    )

    _click_ranking_tab(page, 2)

    assert page.ranking_clicks == 2
    assert page.dismiss_clicks == 1


def test_ranking_retry_is_bounded_to_one():
    page = _Page(
        modal_visible=True,
        modal_text="平台公告",
        close_icon=True,
        ranking_failures=2,
    )

    with pytest.raises(RuntimeError, match="failed after safe modal dismissal"):
        _click_ranking_tab(page, 2)

    assert page.ranking_clicks == 2
    assert page.dismiss_clicks == 1


def test_active_ranking_must_match_expected_label():
    page = _Page(active_ranking="潜力榜")

    _wait_for_active_ranking(page, "潜力榜", attempts=1)


def test_active_ranking_mismatch_fails_with_diagnostic():
    page = _Page(active_ranking="全部内容")

    with pytest.raises(RuntimeError, match="expected='爆款榜', active='全部内容'"):
        _wait_for_active_ranking(page, "爆款榜", attempts=2)


def test_active_ranking_mismatch_surfaces_late_login_modal():
    page = _Page(
        active_ranking="全部内容",
        modal_visible=True,
        modal_text="欢迎登录番茄达人\n密码登录\n登录/注册",
        button_texts=("登录/注册",),
        close_icon=True,
    )

    with pytest.raises(RuntimeError, match="authentication required"):
        _wait_for_active_ranking(page, "爆款榜", attempts=1)

    assert page.dismiss_clicks == 0
