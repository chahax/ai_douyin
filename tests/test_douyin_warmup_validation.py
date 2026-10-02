from __future__ import annotations

from src.platform_adapter.douyin_warmup import DouyinWarmupService


class EmptyLocator:
    def count(self) -> int:
        return 0


class SearchPageWithoutVideos:
    url = "https://www.douyin.com/search/%E6%B3%95%E5%BE%8B?type=video"

    def locator(self, selector: str):
        return EmptyLocator()


class WaitingPage:
    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


class EvalLocator:
    def evaluate(self, script: str):
        assert "data-e2e-vid" in script
        return {
            "video_id": "7677872222148529450",
            "url": "https://www.douyin.com/video/7677872222148529450",
        }


class RecommendFeedPage:
    url = "https://www.douyin.com/?recommend=1"

    def locator(self, selector: str):
        return EvalLocator()


def test_search_page_without_real_video_is_not_ready() -> None:
    service = DouyinWarmupService()

    assert service._prepare_content_page(
        SearchPageWithoutVideos(), use_search=True
    ) is False


def test_current_recommend_feed_identity_uses_data_e2e_video_id() -> None:
    service = DouyinWarmupService()

    identity = service._get_video_identity(RecommendFeedPage())

    assert identity["video_id"] == "7677872222148529450"
    assert identity["url"].endswith("/video/7677872222148529450")


def test_direct_video_page_does_not_reopen_search(monkeypatch) -> None:
    service = DouyinWarmupService()
    page = WaitingPage()
    page.url = "https://www.douyin.com/video/7677872222148529450"
    monkeypatch.setattr(
        service,
        "_get_video_identity",
        lambda current_page: {"video_id": "7677872222148529450"},
    )

    assert service._prepare_content_page(page, use_search=False) is True


def test_advance_requires_a_distinct_video_id(monkeypatch) -> None:
    service = DouyinWarmupService()
    identities = iter(
        [
            {"video_id": "100"},
            {"video_id": "100"},
            {"video_id": "101"},
        ]
    )
    monkeypatch.setattr(service, "_scroll_to_next", lambda page: None)
    monkeypatch.setattr(service, "_get_video_identity", lambda page: next(identities))

    assert service._advance_to_distinct_video(WaitingPage(), {"100"}) is True


def test_advance_fails_when_page_never_changes(monkeypatch) -> None:
    service = DouyinWarmupService()
    monkeypatch.setattr(service, "_scroll_to_next", lambda page: None)
    monkeypatch.setattr(
        service,
        "_get_video_identity",
        lambda page: {"video_id": "100"},
    )

    assert service._advance_to_distinct_video(WaitingPage(), {"100"}) is False
