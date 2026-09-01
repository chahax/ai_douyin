from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.trend_intelligence.feedback import OperationsFeedbackService
from src.trend_intelligence.models import (
    PublishedContentContext,
    VideoMetricSnapshot,
)
from src.trend_intelligence.repository import TREND_SCHEMA_VERSION, TrendRepository


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def _seed_video(
    repository: TrendRepository,
    *,
    index: int,
    account_uuid: str,
    gained: int,
    variant: str,
    hook: str,
    presentation: str,
    workflow: str,
    publish_window: str,
) -> None:
    local_id = f"local-{account_uuid}-{index}"
    video_id = f"{account_uuid}-{index}"
    published = NOW - timedelta(hours=6)
    repository.link_published_content(
        PublishedContentContext(
            local_id=local_id,
            video_id=video_id,
            cluster_id=f"cluster:{variant}",
            brief_id=f"brief:{index}",
            account_uuid=account_uuid,
            account_profile_version=2,
            domain_strategy_id="legal_services",
            strategy_version="v1",
            opportunity_id=f"opportunity:{variant}",
            script_id=f"script:{variant}:{index}",
            script_variant=variant,
            hook_type=hook,
            presentation_type=presentation,
            pacing="fast" if variant == "A" else "balanced",
            workflow_profile=workflow,
            publish_window=publish_window,
            duration_seconds=15,
            published_at=published.isoformat(),
        )
    )
    repository.record_video_snapshot(
        VideoMetricSnapshot(
            video_id=video_id,
            local_id=local_id,
            captured_at=published.isoformat(),
            views=100,
            likes=5,
        )
    )
    repository.record_video_snapshot(
        VideoMetricSnapshot(
            video_id=video_id,
            local_id=local_id,
            captured_at=NOW.isoformat(),
            views=100 + gained,
            likes=10 + gained // 20,
            comments=5 if variant == "A" else 1,
            shares=3 if variant == "A" else 0,
            collects=4 if variant == "A" else 1,
        )
    )


def test_published_context_round_trips_all_attribution_dimensions(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    _seed_video(
        repository,
        index=1,
        account_uuid="account:a",
        gained=500,
        variant="A",
        hook="question",
        presentation="talking_head",
        workflow="legal_presenter",
        publish_window="20:00-22:00",
    )
    context = repository.list_contexts()[0]
    assert context.account_uuid == "account:a"
    assert context.account_profile_version == 2
    assert context.opportunity_id == "opportunity:A"
    assert context.script_id == "script:A:1"
    assert context.script_variant == "A"
    assert context.presentation_type == "talking_head"
    assert context.publish_window == "20:00-22:00"
    assert TREND_SCHEMA_VERSION >= 6


def test_feedback_is_account_isolated_and_attributes_multiple_dimensions(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    for index, gained in enumerate((500, 400), start=1):
        _seed_video(
            repository,
            index=index,
            account_uuid="account:a",
            gained=gained,
            variant="A",
            hook="question",
            presentation="talking_head",
            workflow="legal_presenter",
            publish_window="20:00-22:00",
        )
    for index, gained in enumerate((100, 120), start=3):
        _seed_video(
            repository,
            index=index,
            account_uuid="account:a",
            gained=gained,
            variant="B",
            hook="statement",
            presentation="text_cards",
            workflow="legal_cards",
            publish_window="10:00-12:00",
        )
    _seed_video(
        repository,
        index=1,
        account_uuid="account:b",
        gained=10_000,
        variant="X",
        hook="conflict",
        presentation="story_drama",
        workflow="novel_drama",
        publish_window="23:00-24:00",
    )
    feedback = OperationsFeedbackService(repository)
    results = feedback.performance_results(account_uuid="account:a")
    dimensions = feedback.dimension_performance(account_uuid="account:a")

    assert len(results) == 4
    assert all(item.account_uuid == "account:a" for item in results)
    assert all(item.latest_window == "6h" for item in results)
    by_key = {(item.dimension, item.value): item for item in dimensions}
    assert by_key[("script_variant", "A")].sample_size == 2
    assert (
        by_key[("script_variant", "A")].average_relative_performance
        > by_key[("script_variant", "B")].average_relative_performance
    )
    assert by_key[("hook", "question")].win_rate == 1.0
    assert ("presentation", "story_drama") not in by_key


def test_learning_report_persists_winners_losers_and_score_adjustments(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    for index, gained in enumerate((600, 500, 120, 100), start=1):
        variant = "A" if index <= 2 else "B"
        _seed_video(
            repository,
            index=index,
            account_uuid="account:a",
            gained=gained,
            variant=variant,
            hook="question" if variant == "A" else "statement",
            presentation="talking_head" if variant == "A" else "text_cards",
            workflow="legal_presenter" if variant == "A" else "legal_cards",
            publish_window="20:00-22:00" if variant == "A" else "10:00-12:00",
        )
    feedback = OperationsFeedbackService(repository)
    recommendation = feedback.recommend_next_cycle(account_uuid="account:a")
    report = feedback.build_learning_report(
        account_uuid="account:a", profile_version=2
    )

    assert recommendation.status == "ready"
    assert "script_variant:A" in recommendation.winning_dimensions
    assert "script_variant:B" in recommendation.losing_dimensions
    assert report.score_adjustments["script_variant:A"] > 50
    assert report.score_adjustments["script_variant:B"] < 50
    assert report.next_cycle_allocation == {
        "proven": 0.7,
        "adjacent": 0.2,
        "experiment": 0.1,
    }
    stored = repository.latest_feedback_learning_report("account:a")
    assert stored is not None
    assert stored.report_id == report.report_id
    assert stored.dimensions[0].confidence > 0


def test_due_snapshot_windows_identifies_missing_6h_and_24h_only(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    published = NOW - timedelta(hours=25)
    repository.link_published_content(
        PublishedContentContext(
            local_id="local-due",
            video_id="video-due",
            account_uuid="account:a",
            published_at=published.isoformat(),
        )
    )
    repository.record_video_snapshot(
        VideoMetricSnapshot(
            video_id="video-due",
            local_id="local-due",
            captured_at=(published + timedelta(hours=1)).isoformat(),
            views=100,
        )
    )
    due = OperationsFeedbackService(repository).due_snapshot_windows(
        account_uuid="account:a", now=NOW
    )
    assert [item.window for item in due] == ["6h", "24h"]
    assert due[0].overdue_hours > due[1].overdue_hours


def test_learning_report_requires_account_scope(tmp_path) -> None:
    feedback = OperationsFeedbackService(TrendRepository(tmp_path / "trend.db"))
    try:
        feedback.build_learning_report(account_uuid="", profile_version=1)
    except ValueError as exc:
        assert "account_uuid" in str(exc)
    else:
        raise AssertionError("empty account_uuid must fail")
