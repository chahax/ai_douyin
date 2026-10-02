from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.operations_accounts.maintenance import (
    AccountMaintenanceService,
    _select_playback_candidates,
)
from src.platform_adapter.douyin_playback import (
    PlaybackItemResult,
    PlaybackOptions,
    PlaybackRunResult,
)


def _context():
    profile = AccountProfile(
        account_uuid=stable_account_uuid("account01"),
        account_key="account01",
        display_name="法律号",
        domain_strategy_id="legal_services",
        seed_keywords=["法律", "婚姻"],
        domain_config={"practice_areas": ["婚姻家事"]},
    )
    return SimpleNamespace(
        profile=profile,
        account_uuid=profile.account_uuid,
        account_key=profile.account_key,
        identity_label="法律说法（uid01）",
        binding=SimpleNamespace(public_uid="uid01"),
        create_browser_session=lambda headless=False: _Session(),
    )


class _Session:
    def stop(self):
        pass


class _Runtime:
    def __init__(self):
        self.context = _context()
        self.leases = []

    def resolve(self, account_key):
        assert account_key == "account01"
        return self.context

    @contextmanager
    def operation_lease(self, context, **kwargs):
        self.leases.append(kwargs)
        yield "owner"

    def verify_identity(self, context, *, session=None):
        return SimpleNamespace(healthy=True, message="ok")


class _Research:
    def run(self, profile, provider, request, **kwargs):
        return SimpleNamespace(
            collected_observations=3,
            unique_videos=2,
            video_records=[
                {
                    "video_id": "7531234567890123456",
                    "title": "夫妻债务怎么认定",
                    "author": "@律师",
                    "url": "https://www.douyin.com/video/7531234567890123456",
                    "hashtags": ["法律科普"],
                    "duration_seconds": 15,
                    "associated_keywords": ["法律", "婚姻"],
                    "relevance_score": 82,
                }
            ],
            warnings=["账号相关度预检：保留 3 条，跳过 4 条不相关内容。"],
            status="completed",
            stopped_reason="",
        )


class _MetadataOnlyResearch(_Research):
    def run(self, profile, provider, request, **kwargs):
        result = super().run(profile, provider, request, **kwargs)
        result.status = "blocked"
        result.stopped_reason = "insufficient_research_sample"
        return result


class _HumanRequiredResearch(_Research):
    def run(self, profile, provider, request, **kwargs):
        return SimpleNamespace(
            collected_observations=0,
            unique_videos=0,
            video_records=[],
            warnings=["装修合同：需要人工完成登录或安全验证"],
            status="blocked",
            stopped_reason="human_required",
        )


class _Adapter:
    def sync_videos(self, page_limit=3):
        return SimpleNamespace(
            success=True,
            message="ok",
            videos=[SimpleNamespace(video_id="video-1")],
        )

    def fetch_comments(self, query):
        return SimpleNamespace(success=True, comments=[object(), object()])

    def close(self):
        pass


class _CommentFailureAdapter(_Adapter):
    def fetch_comments(self, query):
        return SimpleNamespace(success=False, comments=[])


class _CommentCountMismatchAdapter(_Adapter):
    def sync_videos(self, page_limit=3):
        return SimpleNamespace(
            success=True,
            message="ok",
            videos=[SimpleNamespace(
                video_id="video-1",
                creator_metrics={"comment_count": 2},
            )],
        )

    def fetch_comments(self, query):
        return SimpleNamespace(success=True, comments=[])


class _Playback:
    def __init__(self):
        self.calls = []

    def run(self, candidates, options, **kwargs):
        self.calls.append((candidates, options, kwargs))
        liked = bool(options.auto_like and options.max_likes > 0)
        commented = bool(options.auto_comment and options.max_comments > 0)
        item = PlaybackItemResult(
            video_id=candidates[0]["video_id"],
            title=candidates[0]["title"],
            author=candidates[0]["author"],
            url=candidates[0]["url"],
            relevance_score=candidates[0]["relevance_score"],
            planned_watch_seconds=15,
            start_current_time=1,
            end_current_time=16,
            actual_watch_seconds=15,
            duration_seconds=30,
            completion_ratio=0.5,
            playback_verified=True,
            liked=liked,
            like_status="clicked" if liked else "disabled",
            comment_family="agreement",
            comment_text="案例讲解得很明白，感谢普法。",
            comment_sent=commented,
            comment_status="sent" if commented else "disabled",
        )
        return PlaybackRunResult(
            status="completed",
            items=[item],
            verified_videos=1,
            actual_watch_seconds=15,
            likes_performed=int(liked),
            comments_sent=int(commented),
        )


def test_daily_maintenance_is_relevant_read_only_and_auditable(tmp_path) -> None:
    runtime = _Runtime()
    service = AccountMaintenanceService(
        runtime=runtime,
        research_factory=_Research,
        log_dir=tmp_path,
    )

    result = service.run(
        "account01",
        "daily",
        authorization_reference="ticket-001",
    )

    assert result.status == "completed"
    assert result.login_healthy is True
    assert result.unique_relevant_videos == 2
    assert result.skipped_irrelevant == 4
    assert result.interaction_actions == 0
    assert result.success_criteria["external_interactions_zero"] is True
    assert result.video_records[0]["duration_seconds"] == 15
    assert runtime.leases[0]["daily_limit"] == 20
    assert runtime.leases[0]["cooldown_seconds"] == 0
    assert (tmp_path / "account01").is_dir()


def test_post_publish_syncs_own_data_without_interactions(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        adapter_factory=lambda account_key, headless=False: _Adapter(),
        log_dir=tmp_path,
    )

    result = service.run("account01", "post-publish")

    assert result.status == "completed"
    assert result.synced_videos == 1
    assert result.synced_comments == 2
    assert result.published_data_sync_completed is True
    assert result.success_criteria["published_data_synced"] is True
    assert result.interaction_actions == 0


def test_post_publish_comment_failure_does_not_fail_creator_metric_sync(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        adapter_factory=lambda account_key, headless=False: _CommentFailureAdapter(),
        log_dir=tmp_path,
    )

    result = service.run("account01", "post-publish")

    assert result.status == "completed"
    assert result.published_data_sync_completed is True
    assert result.synced_videos == 1
    assert result.comment_sync_failures == 1
    assert result.success_criteria["comments_sync_succeeded"] is False
    assert "评论" in result.message


def test_zero_parsed_comments_do_not_override_nonzero_backend_count(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        adapter_factory=lambda account_key, headless=False: _CommentCountMismatchAdapter(),
        log_dir=tmp_path,
    )

    result = service.run("account01", "post-publish")

    assert result.status == "completed"
    assert result.published_data_sync_completed is True
    assert result.synced_comments == 0
    assert result.comment_sync_failures == 1
    assert any("后台显示 2 条评论" in warning for warning in result.warnings)


def test_research_keyword_override_is_bound_and_limited(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        research_factory=_Research,
        log_dir=tmp_path,
    )

    result = service.run(
        "account01",
        "daily",
        authorization_reference="user-authorized",
        research_keywords=["租房押金", "装修合同", "劳动争议"],
    )

    assert result.status == "completed"
    assert result.research_keywords == ["租房押金", "装修合同"]


def test_smart_operations_combines_related_research_and_backend_metrics(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        research_factory=_Research,
        adapter_factory=lambda account_key, headless=False: _CommentFailureAdapter(),
        log_dir=tmp_path,
    )

    result = service.run(
        "account01",
        "smart-operations",
        authorization_reference="user-authorized",
        research_keywords=["装修合同", "租房押金"],
    )

    assert result.status == "completed"
    assert result.research_keywords == ["装修合同", "租房押金"]
    assert result.unique_relevant_videos == 2
    assert result.published_data_sync_completed is True
    assert result.comment_sync_failures == 1


def test_smart_operations_keeps_metadata_report_when_metric_semantics_are_unknown(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        research_factory=_MetadataOnlyResearch,
        adapter_factory=lambda account_key, headless=False: _Adapter(),
        log_dir=tmp_path,
    )

    result = service.run(
        "account01",
        "smart-operations",
        authorization_reference="user-authorized",
        research_keywords=["装修合同"],
    )

    assert result.status == "completed"
    assert result.unique_relevant_videos == 2
    assert result.published_data_sync_completed is True
    assert any("元数据" in warning for warning in result.warnings)


def test_smart_operations_still_syncs_backend_when_search_needs_human(tmp_path) -> None:
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        research_factory=_HumanRequiredResearch,
        adapter_factory=lambda account_key, headless=False: _Adapter(),
        log_dir=tmp_path,
    )

    result = service.run(
        "account01",
        "smart-operations",
        authorization_reference="user-authorized",
        research_keywords=["装修合同"],
    )

    assert result.status == "partial"
    assert result.published_data_sync_completed is True
    assert result.synced_videos == 1
    assert any("缓存样本" in warning for warning in result.warnings)


def test_playback_uses_analyzed_candidates_and_unified_log(tmp_path) -> None:
    playback = _Playback()
    service = AccountMaintenanceService(
        runtime=_Runtime(),
        research_factory=_Research,
        playback_factory=lambda session: playback,
        log_dir=tmp_path,
    )

    result = service.run(
        "account01",
        "playback",
        authorization_reference="ticket-playback-001",
        headless=False,
        playback_options=PlaybackOptions(
            max_videos=1,
            per_video_seconds=15,
            total_minutes=1,
            min_relevance_score=60,
            auto_like=True,
            auto_comment=False,
            base_like_ratio=1,
        ),
    )

    assert result.status == "completed"
    assert result.playback_candidates == 1
    assert result.playback_verified_videos == 1
    assert result.actual_watch_seconds == 15
    assert result.likes_performed == 1
    assert result.comments_sent == 0
    assert result.interaction_actions == 1
    assert result.success_criteria["verified_playback_completed"] is True
    assert result.success_criteria["interaction_policy_respected"] is True
    assert playback.calls[0][0][0]["relevance_score"] == 82
    assert result.interaction_policy["budget_mode"] == "dynamic_daily_ratio"
    assert "like_daily_cap" not in result.interaction_policy
    assert result.interaction_policy["daily_like_target"] == 1
    assert service.runtime.leases[0]["cooldown_seconds"] == 0
    assert result.log_path.startswith(str(tmp_path))


def test_playback_candidate_selection_excludes_recently_watched_video() -> None:
    records = [
        {
            "video_id": "7531234567890123456",
            "url": "https://www.douyin.com/video/7531234567890123456",
            "relevance_score": 90,
            "visible_metric": 10_000,
        },
        {
            "video_id": "7531234567890123457",
            "url": "https://www.douyin.com/video/7531234567890123457",
            "relevance_score": 80,
            "visible_metric": 8_000,
        },
    ]

    selected = _select_playback_candidates(
        records,
        min_relevance_score=60,
        max_videos=20,
        exclude_video_ids=["7531234567890123456"],
    )

    assert [item["video_id"] for item in selected] == ["7531234567890123457"]
