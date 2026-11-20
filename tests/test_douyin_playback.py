from __future__ import annotations

from src.platform_adapter.douyin_playback import (
    DouyinRelevantPlaybackController,
    PlaybackOptions,
    SafeCommentPolicy,
    comment_similarity,
    enrich_candidate_engagement_signals,
    is_advertising_comment,
)

import pytest


class _FakeLocator:
    def __init__(self, page):
        self.page = page

    def evaluate(self, script: str):
        if 'data-douyin-visible-challenge' in script:
            return dict(blocking=False,frame_count=0,actionable_frames=0,visible_dialogs=0)
        if "verifycenter" in script or "扫码登录" in script:
            return False
        if "ready_state" in script:
            return {
                "found": True,
                "current_time": self.page.current_time,
                "duration": 20,
                "paused": not self.page.playing,
                "ended": False,
                "ready_state": 4,
            }
        if "video.play" in script:
            self.page.playing = True
            return True
        return None


class _FakePage:
    def __init__(self, url: str):
        self.url = url
        self.current_time = 2.0
        self.playing = False

    def locator(self, selector: str):
        return _FakeLocator(self)

    def wait_for_timeout(self, milliseconds: int):
        if self.playing:
            self.current_time += milliseconds / 1000


class _FakeSession:
    def __init__(self):
        self.page = None

    def open_page(self, url: str):
        self.page = _FakePage(url)
        return self.page


def test_playback_options_have_no_fixed_upper_limits() -> None:
    PlaybackOptions(
        max_videos=200,
        per_video_seconds=3_600,
        total_minutes=1_440,
    ).validate()


@pytest.mark.parametrize(
    "options",
    [
        PlaybackOptions(max_videos=0),
        PlaybackOptions(per_video_seconds=0),
        PlaybackOptions(total_minutes=0),
    ],
)
def test_playback_options_still_require_positive_work_values(options) -> None:
    with pytest.raises(ValueError, match="必须为正整数"):
        options.validate()


def test_playback_verifies_real_current_time_progress() -> None:
    controller = DouyinRelevantPlaybackController(_FakeSession())
    result = controller.run(
        [
            {
                "video_id": "7681138441245269931",
                "title": "法律科普",
                "author": "@律师",
                "url": "https://www.douyin.com/video/7681138441245269931",
                "relevance_score": 82,
            }
        ],
        PlaybackOptions(max_videos=1, per_video_seconds=5, total_minutes=1),
        domain_strategy_id="legal_services",
    )

    assert result.status == "completed"
    assert result.verified_videos == 1
    assert result.actual_watch_seconds >= 4.25
    assert result.items[0].end_current_time > result.items[0].start_current_time
    assert result.items[0].completion_ratio > 0


@pytest.mark.parametrize("code", ["human_required", "login_expired"])
def test_access_block_stops_playback_without_claiming_watch_success(code):
    class Locator(_FakeLocator):
        def evaluate(self, script):
            if "return 'login_expired'" in script:
                return code
            return super().evaluate(script)
    class Session(_FakeSession):
        def open_page(self, url):
            page = super().open_page(url)
            page.locator = lambda selector: Locator(page)
            return page
    result = DouyinRelevantPlaybackController(Session()).run(
        [{"video_id": "7681138441245269931", "url": "https://www.douyin.com/video/7681138441245269931"},
         {"video_id": "7681138441245269932", "url": "https://www.douyin.com/video/7681138441245269932"}],
        PlaybackOptions(per_video_seconds=5), domain_strategy_id="legal_services")
    assert result.status == "partial" and result.error_code == code
    assert result.verified_videos == 0 and result.actual_watch_seconds == 0
    assert len(result.items) == 1 and not result.items[0].playback_verified


def test_network_error_retains_its_code_and_stops_after_prior_verified_video():
    class NetworkError(RuntimeError):
        code = "network_error"
    class Session(_FakeSession):
        opened = 0
        def open_page(self, url):
            self.opened += 1
            if self.opened > 1:
                raise NetworkError("fixture disconnect")
            return super().open_page(url)
    session = Session()
    result = DouyinRelevantPlaybackController(session).run(
        [{"video_id": str(7681138441245269931 + i),
          "url": f"https://www.douyin.com/video/{7681138441245269931 + i}"} for i in range(3)],
        PlaybackOptions(per_video_seconds=5), domain_strategy_id="legal_services")
    assert result.status == "partial" and result.error_code == "network_error"
    assert result.verified_videos == 1 and result.actual_watch_seconds > 0
    assert session.opened == 2 and not result.items[1].playback_verified


def test_challenge_during_viewing_does_not_become_verified_watch():
    class Locator(_FakeLocator):
        def evaluate(self, script):
            if "return 'login_expired'" in script:
                return "human_required" if self.page.current_time > 2 else ""
            return super().evaluate(script)
    class Session(_FakeSession):
        def open_page(self, url):
            page = super().open_page(url)
            page.locator = lambda selector: Locator(page)
            return page
    result = DouyinRelevantPlaybackController(Session()).run(
        [{"video_id": "7681138441245269931", "url": "https://www.douyin.com/video/7681138441245269931"}],
        PlaybackOptions(per_video_seconds=5), domain_strategy_id="legal_services")
    assert result.error_code == "human_required" and result.verified_videos == 0
    assert not result.items[0].playback_verified


def test_missing_playing_video_is_a_failure_not_an_empty_candidate_skip():
    class Locator(_FakeLocator):
        def evaluate(self, script):
            if "ready_state" in script:
                return {"found": False}
            return super().evaluate(script)
    class Session(_FakeSession):
        def open_page(self, url):
            page = super().open_page(url)
            page.locator = lambda selector: Locator(page)
            return page
    result = DouyinRelevantPlaybackController(Session()).run(
        [{"video_id": "7681138441245269931", "url": "https://www.douyin.com/video/7681138441245269931"}],
        PlaybackOptions(per_video_seconds=5), domain_strategy_id="legal_services")
    assert result.error_code == "playback_video_missing" and result.verified_videos == 0


def test_safe_comment_uses_family_but_not_verbatim_copy() -> None:
    decision = SafeCommentPolicy().build(
        domain_strategy_id="legal_services",
        video_title="夫妻债务如何认定",
        visible_comments=["说得对", "确实有道理", "学到了"],
        recent_account_comments=["讲得很清楚，学到了。"],
    )

    assert decision.allowed is True
    assert decision.family == "agreement"
    assert decision.text not in {"说得对", "确实有道理", "学到了"}
    assert comment_similarity(decision.text, "讲得很清楚，学到了。") < 0.82


def test_advertising_comment_patterns_are_blocked() -> None:
    assert is_advertising_comment("免费法律咨询，加微信 13800138000") is True
    assert is_advertising_comment("点击 www.example.com 联系我") is True
    assert is_advertising_comment("这个提醒很有必要，感谢普法。") is False


def test_real_like_rate_and_proxy_signals_are_kept_distinct() -> None:
    rows = enrich_candidate_engagement_signals(
        [
            {"video_id": "1", "like_count": 1_000, "view_count": 10_000},
            {"video_id": "2", "like_count": 100, "view_count": 10_000},
            {
                "video_id": "3",
                "visible_metric": 88_000,
                "source_sort": "most_liked",
            },
        ]
    )

    assert rows[0]["observed_like_rate"] == 0.1
    assert rows[0]["like_performance_score"] > rows[1]["like_performance_score"]
    assert rows[2]["observed_like_rate"] is None
    assert rows[2]["like_signal_kind"] == "relative_displayed_metric_most_liked"


def test_high_like_performance_gets_higher_maintenance_like_probability() -> None:
    controller = DouyinRelevantPlaybackController(_FakeSession())
    result = controller.run(
        [
            {
                "video_id": "7681138441245269931",
                "title": "高点赞率法律视频",
                "author": "@律师甲",
                "url": "https://www.douyin.com/video/7681138441245269931",
                "relevance_score": 82,
                "like_count": 1_000,
                "view_count": 10_000,
            },
            {
                "video_id": "7681138441245269932",
                "title": "低点赞率法律视频",
                "author": "@律师乙",
                "url": "https://www.douyin.com/video/7681138441245269932",
                "relevance_score": 82,
                "like_count": 100,
                "view_count": 10_000,
            },
        ],
        PlaybackOptions(
            max_videos=2,
            per_video_seconds=20,
            total_minutes=1,
            base_like_ratio=0.25,
        ),
        domain_strategy_id="legal_services",
    )

    assert result.items[0].like_probability > result.items[1].like_probability
    assert result.items[0].planned_watch_seconds > result.items[1].planned_watch_seconds
