from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.operations_accounts.maintenance import (
    AccountMaintenanceService,
    _select_playback_candidates,
)
from src.platform_adapter.douyin_playback import (
    PlaybackItemResult,
    PlaybackOptions as _PlaybackOptions,
    PlaybackRunResult,
)

# This module retains the explicit historical search-candidate workflow.
# Default recommendation dispatch is covered without this override in
# test_recommendation_playback.py.
def PlaybackOptions(**kwargs):
    return _PlaybackOptions(source="search_candidates", **kwargs)


@pytest.fixture(autouse=True)
def _isolate_standard_maintenance_history(tmp_path, monkeypatch):
    monkeypatch.setattr("src.operations_accounts.maintenance.MAINTENANCE_LOG_DIR", tmp_path / "standard_history")
    monkeypatch.setattr("src.operations_accounts.maintenance.PlaybackOptions", PlaybackOptions)
    monkeypatch.setattr("src.operations_accounts.browser_control_runtime.enabled", lambda: False)


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


@pytest.mark.parametrize("code", ["human_required", "login_expired", "identity_unavailable", "identity_mismatch"])
def test_maintenance_keeps_identity_error_code_in_saved_result(tmp_path, code):
    import json
    runtime = _Runtime()
    runtime.verify_identity = lambda *a, **k: SimpleNamespace(healthy=False, status=code, message="identity failure")
    result = AccountMaintenanceService(runtime=runtime, log_dir=tmp_path).run("account01", "post-publish")
    assert result.error_code == code and result.status == "blocked"
    assert json.loads(Path(result.log_path).read_text(encoding="utf-8"))["error_code"] == code


@pytest.mark.parametrize("code", ["locked", "circuit_open", "login_unhealthy"])
def test_maintenance_retains_runtime_failure_without_asserting_expiry(tmp_path, code):
    from src.operations_accounts.runtime import AccountRuntimeError
    runtime = _Runtime()
    def fail(*a, **k):
        raise AccountRuntimeError(code, "runtime guard")
    runtime.resolve = fail
    result = AccountMaintenanceService(runtime=runtime, log_dir=tmp_path).run("account01", "post-publish")
    assert result.error_code == code
    assert "过期" not in result.message


def test_maintenance_network_failure_remains_ordinary_fault(tmp_path):
    runtime = _Runtime()
    def fail(*a, **k):
        raise TimeoutError("network timed out")
    runtime.verify_identity = fail
    result = AccountMaintenanceService(runtime=runtime, log_dir=tmp_path).run("account01", "post-publish")
    assert result.status == "failed" and result.error_code == "unexpected_error"
    assert "过期" not in result.message


def test_maintenance_checkpoints_refreshed_session_after_collection(tmp_path):
    events = []
    session = SimpleNamespace(save_storage_state=lambda: events.append("save"), stop=lambda: events.append("stop"))
    runtime = _Runtime()
    runtime.context.create_browser_session = lambda **kwargs: session
    class Adapter(_Adapter):
        def sync_videos(self, **kwargs):
            events.append("sync")
            return super().sync_videos(**kwargs)
    result = AccountMaintenanceService(runtime=runtime, adapter_factory=lambda *a, **k: Adapter(), log_dir=tmp_path).run(
        "account01", "post-publish")
    assert result.status == "completed"
    assert events == ["sync", "save", "stop"]


def test_borrowed_adapter_session_is_saved_before_outer_owner_closes(tmp_path, monkeypatch):
    events = []
    session = SimpleNamespace(save_storage_state=lambda: events.append("save"), stop=lambda: events.append("stop"))
    runtime = _Runtime()
    runtime.context.create_browser_session = lambda **kwargs: session
    class Adapter(_Adapter):
        def __init__(self, **kwargs):
            assert kwargs["session"] is session
        def sync_videos(self, **kwargs):
            events.append("sync")
            return super().sync_videos(**kwargs)
        def close(self):
            events.append("adapter-close")
    monkeypatch.setattr("src.platform_adapter.douyin_adapter.DouyinAdapter", Adapter)
    result = AccountMaintenanceService(runtime=runtime, log_dir=tmp_path).run("account01", "post-publish")
    assert result.status == "completed"
    assert events == ["sync", "save", "stop"]


def test_comment_identity_challenge_remains_visible_with_completed_metrics(tmp_path):
    class Adapter(_Adapter):
        def fetch_comments(self, query):
            return SimpleNamespace(success=False, status="human_required", comments=[])
    result = AccountMaintenanceService(runtime=_Runtime(), adapter_factory=lambda *a, **k: Adapter(), log_dir=tmp_path).run(
        "account01", "post-publish")
    assert result.status == "completed" and result.published_data_sync_completed
    assert result.error_code == "human_required"


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
    assert result.error_code == "human_required"
    assert any("缓存样本" in warning for warning in result.warnings)


@pytest.mark.parametrize("sync_error", [None, "human_required", "network_error", "exception"])
def test_real_research_blocked_search_reaches_maintenance_receipt(tmp_path, monkeypatch, sync_error):
    import json
    from src.trend_intelligence.providers.base import TrendCollectionResult
    from src.trend_intelligence.repository import TrendRepository
    from src.trend_intelligence.research_workflow import AccountVideoResearchWorkflow
    blocked_search = {"query": "#夫妻债务", "query_kind": "hashtag",
                      "sort_key": "latest", "detection": "visible_challenge"}

    class Provider:
        provider_id = "blocked_fixture"
        def __init__(self, **kwargs):
            pass
        def collect(self, request, *, policy):
            assert request.keywords == ["法律", "婚姻"]
            return TrendCollectionResult(observations=[], stopped_reason="human_required",
                blocked_search=dict(blocked_search))

    class Adapter(_Adapter):
        def sync_videos(self, **kwargs):
            if sync_error == "exception":
                raise TimeoutError("offline fixture")
            if sync_error:
                return SimpleNamespace(success=False, status=sync_error, message="sync fixture")
            return super().sync_videos(**kwargs)

    monkeypatch.setattr("src.operations_accounts.maintenance.DouyinWebTrendProvider", Provider)
    workflow = AccountVideoResearchWorkflow(TrendRepository(tmp_path / "trend.db"),
        log_dir=tmp_path / "research")
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=lambda: workflow,
        adapter_factory=lambda *a, **k: Adapter(), log_dir=tmp_path / "maintenance").run(
            "account01", "smart-operations", authorization_reference="offline-fixture")
    saved = json.loads(Path(result.log_path).read_text(encoding="utf-8"))
    research_saved = json.loads(next((tmp_path / "research").glob("research_*.json")).read_text(encoding="utf-8"))
    assert research_saved["blocked_search"] == saved["blocked_search"] == blocked_search
    assert research_saved["stopped_reason"] == "human_required"
    assert result.playback_verified_videos == 0
    if sync_error is None:
        assert result.failure_stage == saved["failure_stage"] == "research"
        assert result.status == "partial" and result.published_data_sync_completed
        assert result.error_code == "human_required"
    else:
        assert result.failure_stage == saved["failure_stage"] == "published_data_sync"
        assert result.error_code == ("unexpected_error" if sync_error == "exception" else sync_error)
        assert not result.published_data_sync_completed


def test_identity_challenge_is_not_search_and_missing_context_is_not_guessed(tmp_path):
    runtime = _Runtime()
    runtime.verify_identity = lambda *a, **k: SimpleNamespace(
        healthy=False, status="human_required", message="identity fixture")
    result = AccountMaintenanceService(runtime=runtime, log_dir=tmp_path / "identity").run(
        "account01", "smart-operations", authorization_reference="offline-fixture")
    assert result.failure_stage == "identity" and result.blocked_search == {}
    legacy = AccountMaintenanceService(runtime=_Runtime(), research_factory=_HumanRequiredResearch,
        adapter_factory=lambda *a, **k: _Adapter(), log_dir=tmp_path / "legacy").run(
            "account01", "smart-operations", authorization_reference="offline-fixture")
    assert legacy.failure_stage == "research" and legacy.blocked_search == {}


def test_partial_search_rows_cannot_turn_human_block_into_completed(tmp_path):
    class PartialBlockedResearch(_HumanRequiredResearch):
        def run(self, *args, **kwargs):
            research = super().run(*args, **kwargs)
            research.unique_videos = research.collected_observations = 1
            research.blocked_search = {"query": "婚姻", "query_kind": "keyword",
                "sort_key": "most_liked", "detection": "visible_challenge"}
            return research
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=PartialBlockedResearch,
        adapter_factory=lambda *a, **k: _Adapter(), log_dir=tmp_path).run(
            "account01", "smart-operations", authorization_reference="offline-fixture")
    assert result.status == "partial" and result.published_data_sync_completed
    assert result.unique_relevant_videos == 1
    assert result.error_code == "human_required" and result.failure_stage == "research"
    assert result.blocked_search["query"] == "婚姻"


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


@pytest.mark.parametrize("minutes", [20, 60, 180])
def test_playback_preserves_configured_options_and_extends_real_lease(tmp_path, minutes):
    from src.operations_accounts.maintenance import playback_lease_seconds
    runtime = _Runtime()
    playback = _Playback()
    service = AccountMaintenanceService(runtime=runtime, research_factory=_Research,
        playback_factory=lambda session: playback, log_dir=tmp_path)
    result = service.run("account01", "playback", authorization_reference="scheduled-plan",
        playback_options=PlaybackOptions(max_videos=20, per_video_seconds=90,
            total_minutes=minutes, min_relevance_score=60, auto_like=False, auto_comment=False))
    assert result.status == "completed" and result.playback_verified_videos == 1
    effective = playback.calls[0][1]
    assert (effective.max_videos, effective.per_video_seconds, effective.total_minutes) == (20, 90, minutes)
    assert not effective.auto_like and not effective.auto_comment
    assert result.interaction_actions == 0
    assert runtime.leases[0]["daily_limit"] == 3
    assert runtime.leases[0]["lock_seconds"] == playback_lease_seconds(minutes) == max(3600, minutes * 60 + 1800)


@pytest.mark.parametrize("reason, low_score", [("no_valid_videos", False), ("insufficient_research_sample", False), ("", True)])
def test_playback_no_candidates_is_saved_skip_with_no_watch_claim(tmp_path, reason, low_score):
    import json
    class Research(_Research):
        def run(self, *a, **k):
            result = super().run(*a, **k)
            result.status = "blocked" if reason else "completed"
            result.stopped_reason = reason
            if low_score:
                result.video_records[0]["relevance_score"] = 10
            else:
                result.video_records = []
                result.unique_videos = 0
            return result
    playback = _Playback()
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=Research,
        playback_factory=lambda session: playback, log_dir=tmp_path).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "skipped" and result.error_code == "no_playback_candidates"
    assert result.playback_verified_videos == 0 and result.actual_watch_seconds == 0
    assert not playback.calls and not result.playback_items
    assert result.success_criteria["verified_playback_completed"] is False
    assert json.loads(Path(result.log_path).read_text(encoding="utf-8"))["status"] == "skipped"


def test_insufficient_analysis_sample_can_play_existing_relevant_video(tmp_path):
    playback = _Playback()
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=_MetadataOnlyResearch,
        playback_factory=lambda session: playback, log_dir=tmp_path).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "completed" and result.playback_verified_videos == 1
    assert result.error_code == "" and playback.calls


@pytest.mark.parametrize("code", ["human_required", "login_expired", "identity_mismatch", "network_error"])
def test_playback_research_access_failure_is_never_an_empty_candidate_skip(tmp_path, code):
    class Research(_Research):
        def run(self, *a, **k):
            result = super().run(*a, **k)
            result.status = "partial"
            result.stopped_reason = code
            return result
    playback = _Playback()
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=Research,
        playback_factory=lambda session: playback, log_dir=tmp_path).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "blocked" and result.error_code == code
    assert result.playback_verified_videos == 0 and not playback.calls


def test_original_collection_challenge_is_not_hidden_by_later_sample_gate(tmp_path):
    class Research(_MetadataOnlyResearch):
        def run(self, *a, **k):
            result = super().run(*a, **k)
            result.stages = [SimpleNamespace(stage="trend_collection", message="human_required")]
            return result
    playback = _Playback()
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=Research,
        playback_factory=lambda session: playback, log_dir=tmp_path).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "blocked" and result.error_code == "human_required"
    assert not playback.calls


def test_research_provider_cannot_close_borrowed_verified_session(tmp_path):
    events = []
    session = SimpleNamespace(stop=lambda: events.append("stop"), save_storage_state=lambda: events.append("save"))
    runtime = _Runtime()
    runtime.context.create_browser_session = lambda **kwargs: session
    class Research(_Research):
        def run(self, profile, provider, request, **kwargs):
            provider.session_factory(True).stop()
            assert not events
            return super().run(profile, provider, request, **kwargs)
    class Playback(_Playback):
        def run(self, *a, **k):
            assert not events
            events.append("play")
            return super().run(*a, **k)
    playback = Playback()
    result = AccountMaintenanceService(runtime=runtime, research_factory=Research,
        playback_factory=lambda actual: playback if actual is session else None, log_dir=tmp_path).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "completed" and events == ["play", "save", "stop"]


def test_playback_error_retains_previous_verified_evidence_and_structured_code(tmp_path):
    class Playback(_Playback):
        def run(self, *a, **k):
            result = super().run(*a, **k)
            result.status = "partial"
            result.error_code = "network_error"
            return result
    result = AccountMaintenanceService(runtime=_Runtime(), research_factory=_Research,
        playback_factory=lambda session: Playback(), log_dir=tmp_path).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "blocked" and result.error_code == "network_error"
    assert result.playback_verified_videos == 1 and result.actual_watch_seconds == 15


def _scoped_playback_runtime(tmp_path):
    from src.operations_accounts import AccountProfileRepository, AccountBindingRepository
    from src.operations_accounts.runtime import AccountRuntimeService
    context = _context()
    profiles = AccountProfileRepository(tmp_path / "scoped_accounts.db")
    profiles.save(context.profile)
    runtime = AccountRuntimeService(profile_repository=profiles,
                                    binding_repository=AccountBindingRepository(profiles.db_path))
    runtime.resolve = lambda key: context
    runtime.verify_identity = lambda *a, **k: SimpleNamespace(healthy=True, message="ok")
    return runtime, context


def _legacy_playback_file(root, context, run_id, **overrides):
    import json
    from datetime import datetime, timezone
    payload = {"run_id": run_id, "account_key": context.account_key,
        "account_uuid": context.account_uuid, "mode": "playback", "runtime_lease_acquired": True,
        "started_at": datetime.now(timezone.utc).isoformat(), "status": "completed", "error_code": ""}
    payload.update(overrides)
    target = Path(root) / context.account_key / f"maintenance_{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_playback_scope_inherits_standard_and_custom_history_without_duplicate_or_reset(tmp_path):
    import shutil
    import src.operations_accounts.maintenance as module
    runtime, context = _scoped_playback_runtime(tmp_path)
    first = _legacy_playback_file(module.MAINTENANCE_LOG_DIR, context, "old-standard")
    custom = tmp_path / "custom_history"
    copied = custom / context.account_key / first.name
    copied.parent.mkdir(parents=True)
    shutil.copyfile(first, copied)
    _legacy_playback_file(custom, context, "old-custom")
    playback = _Playback()
    service = AccountMaintenanceService(runtime=runtime, research_factory=_Research,
        playback_factory=lambda session: playback, log_dir=custom)
    result = service.run("account01", "playback", authorization_reference="scheduled-plan")
    assert result.status == "completed"
    usage = runtime.get_operation_usage(context, "playback")
    assert usage["legacy_baseline"] == 2 and usage["runs"] == 3
    changed = AccountMaintenanceService(runtime=runtime, research_factory=_Research,
        playback_factory=lambda session: playback, log_dir=tmp_path / "different_destination")
    denied = changed.run("account01", "playback", authorization_reference="scheduled-plan")
    assert denied.error_code == "daily_quota_exceeded"
    assert len(playback.calls) == 1 and runtime.get_operation_usage(context, "playback")["runs"] == 3


def test_first_denied_scope_freezes_history_before_directory_change(tmp_path, monkeypatch):
    import src.operations_accounts.maintenance as module
    runtime, context = _scoped_playback_runtime(tmp_path)
    for index in range(3):
        _legacy_playback_file(module.MAINTENANCE_LOG_DIR, context, f"old-{index}")
    playback = _Playback()
    service = AccountMaintenanceService(runtime=runtime, research_factory=_Research,
        playback_factory=lambda session: playback, log_dir=tmp_path / "custom")
    result = service.run("account01", "playback", authorization_reference="scheduled-plan")
    assert result.error_code == "daily_quota_exceeded"
    before = runtime.get_operation_usage(context, "playback")
    assert before["runs"] == before["legacy_baseline"] == 3
    monkeypatch.setattr(module, "MAINTENANCE_LOG_DIR", tmp_path / "another_standard")
    result = AccountMaintenanceService(runtime=runtime, research_factory=_Research,
        playback_factory=lambda session: playback, log_dir=tmp_path / "another_custom").run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.error_code == "daily_quota_exceeded" and not playback.calls
    assert runtime.get_operation_usage(context, "playback") == before


@pytest.mark.parametrize("damage", ["malformed", "identity_conflict", "run_conflict"])
def test_uncertain_legacy_playback_history_stops_without_new_admission(tmp_path, damage):
    import json
    import src.operations_accounts.maintenance as module
    runtime, context = _scoped_playback_runtime(tmp_path)
    first = _legacy_playback_file(module.MAINTENANCE_LOG_DIR, context, "old")
    custom = tmp_path / "custom"
    if damage == "malformed":
        first.write_text("{broken", encoding="utf-8")
    elif damage == "identity_conflict":
        payload = json.loads(first.read_text(encoding="utf-8"))
        payload["account_uuid"] = "another-uuid"
        first.write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload = json.loads(first.read_text(encoding="utf-8"))
        payload["status"] = "failed"
        target = custom / context.account_key / first.name
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(payload), encoding="utf-8")
    playback = _Playback()
    result = AccountMaintenanceService(runtime=runtime, research_factory=_Research,
        playback_factory=lambda session: playback, log_dir=custom).run(
        "account01", "playback", authorization_reference="scheduled-plan")
    assert result.error_code == "quota_history_unavailable" and result.status == "blocked"
    assert not result.runtime_lease_acquired and not playback.calls
    assert runtime.get_operation_usage(context, "playback") is None


def test_legacy_scope_counts_utc_day_attempts_and_excludes_known_admission_denials(tmp_path):
    from datetime import datetime, timedelta, timezone
    import src.operations_accounts.maintenance as module
    runtime, context = _scoped_playback_runtime(tmp_path)
    root = module.MAINTENANCE_LOG_DIR
    _legacy_playback_file(root, context, "yesterday", started_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    _legacy_playback_file(root, context, "denied", error_code="locked")
    _legacy_playback_file(root, context, "not-admitted", runtime_lease_acquired=False)
    _legacy_playback_file(root, context, "failed-after-admission", status="failed", error_code="network_error")
    service = AccountMaintenanceService(runtime=runtime, log_dir=tmp_path / "custom")
    assert service._playback_quota_options(context)["quota_baseline"] == 1
