from src.trend_intelligence.providers.douyin_web import DouyinWebTrendProvider


def test_verification_continues_on_same_page_without_navigation(monkeypatch):
    class Page:
        ticks = 0

        def wait_for_timeout(self, timeout):
            self.ticks += 1

        def locator(self, selector):
            return self

        def count(self):
            return 20 if self.ticks >= 3 else 0

    page = Page()
    monkeypatch.setattr(DouyinWebTrendProvider, '_is_blocked', staticmethod(lambda p: p.ticks < 3))
    assert DouyinWebTrendProvider._await_manual_verification(page, 10)
    assert page.ticks == 3


def test_zero_timeout_does_not_interact_with_challenge():
    assert not DouyinWebTrendProvider._await_manual_verification(object(), 0)
