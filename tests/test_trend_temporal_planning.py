from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.trend_intelligence.collection import TrendCollectionPlanner
from src.trend_intelligence.models import (
    TrendObservation,
    TrendTagTrafficSnapshot,
)
from src.trend_intelligence.providers.base import TrendCollectionResult
from src.trend_intelligence.providers.douyin_web import parse_visible_publish_time
from src.trend_intelligence.repository import TREND_SCHEMA_VERSION, TrendRepository
from src.trend_intelligence.service import TrendOperationsService
from src.trend_intelligence.source_policy import approved_manual_import_policy
from src.trend_intelligence.temporal import (
    build_tag_family_trend_signals,
    build_video_trend_signals,
)


def _profile(domain: str = "legal_services") -> AccountProfile:
    account_key = f"account_{domain}"
    config = (
        {"practice_areas": ["婚姻", "债务"]}
        if domain == "legal_services"
        else {"genres": ["重生", "复仇"]}
    )
    return AccountProfile(
        account_uuid=stable_account_uuid(account_key),
        account_key=account_key,
        display_name=account_key,
        domain_strategy_id=domain,
        seed_keywords=["法律"] if domain == "legal_services" else ["小说"],
        negative_keywords=["赌博"],
        domain_config=config,
    )


def _observation(
    *,
    item_id: str = "douyin:1",
    run_id: str,
    captured: str,
    metric: int,
    rank: int,
    published_at: str = "",
) -> TrendObservation:
    return TrendObservation(
        item_id=item_id,
        video_id=item_id.rsplit(":", 1)[-1],
        url=f"https://www.douyin.com/video/{item_id.rsplit(':', 1)[-1]}",
        title="夫妻共同债务证据怎么留",
        author="律师甲",
        keyword="法律",
        sort_key="latest",
        sort_label="最新发布",
        rank=rank,
        run_id=run_id,
        metric_text=str(metric),
        metric_value=metric,
        metric_kind="views",
        collected_at=captured,
        published_at=published_at,
        published_at_text="1天前" if published_at else "",
        root_keywords=["法律"],
        hashtags=["婚姻", "债务"],
    )


def test_domain_collection_planner_builds_bounded_tiered_batches() -> None:
    planner = TrendCollectionPlanner(max_pages_per_batch=30, max_keywords_per_batch=2)
    legal = planner.build(
        _profile("legal_services"),
        wave_kind="baseline",
        created_at="2026-09-01T00:00:00+00:00",
    )
    novel = planner.build(
        _profile("novel_promotion"),
        wave_kind="discovery",
        created_at="2026-09-01T00:00:00+00:00",
    )

    assert legal.repeat_interval_hours == 24
    assert legal.batches
    assert all(batch.estimated_pages <= 30 for batch in legal.batches)
    assert all(batch.expand_related_tags for batch in legal.batches)
    assert "婚姻" in legal.keywords
    assert novel.domain_strategy_id == "novel_promotion"
    assert any("高能反转" in keyword for keyword in novel.keywords)
    assert all(not batch.expand_related_tags for batch in novel.batches)


def test_momentum_plan_uses_hot_keywords_and_six_hour_interval() -> None:
    plan = TrendCollectionPlanner().build(
        _profile(),
        wave_kind="momentum",
        hot_keywords=["彩礼返还", "赌博债务"],
        created_at="2026-09-01T00:00:00+00:00",
    )
    assert plan.repeat_interval_hours == 6
    assert plan.keywords == ["彩礼返还"]
    assert all(batch.sorts == ("most_liked", "latest") for batch in plan.batches)


def test_repository_persists_plan_run_context_and_publication_time(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile = _profile()
    service = TrendOperationsService(repository=repository)
    plan = service.create_collection_plan(profile, wave_kind="momentum")
    batch = plan.batches[0]
    observation = _observation(
        run_id="",
        captured="2026-09-01T08:00:00+00:00",
        metric=100,
        rank=5,
        published_at="2026-08-31T08:00:00+00:00",
    )
    run_id = repository.save_collection(
        [observation],
        provider="fixture",
        keywords=batch.keywords,
        account_uuid=profile.account_uuid,
        profile_version=profile.profile_version,
        domain_strategy_id=profile.domain_strategy_id,
        strategy_version=profile.strategy_version,
        plan_id=plan.plan_id,
        batch_id=batch.batch_id,
        wave_kind=batch.wave_kind,
    )

    stored = repository.list_observations()[0]
    run = repository.list_collection_runs(plan_id=plan.plan_id)[0]
    assert TREND_SCHEMA_VERSION >= 3
    assert stored.published_at == "2026-08-31T08:00:00+00:00"
    assert stored.metric_kind == "views"
    assert run["run_id"] == run_id
    assert run["account_uuid"] == profile.account_uuid
    assert run["batch_id"] == batch.batch_id
    assert repository.list_collection_plans(account_uuid=profile.account_uuid)[0][
        "plan_id"
    ] == plan.plan_id


def test_schema_v2_database_is_migrated_additively(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE trend_collection_runs (
                run_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                keywords_json TEXT NOT NULL, status TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL, finished_at TEXT
            );
            CREATE TABLE trend_items (
                item_id TEXT PRIMARY KEY, platform TEXT NOT NULL DEFAULT 'douyin',
                video_id TEXT, url TEXT NOT NULL, title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE trend_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                item_id TEXT NOT NULL, keyword TEXT NOT NULL,
                sort_key TEXT NOT NULL, sort_label TEXT NOT NULL,
                rank INTEGER NOT NULL, metric_text TEXT NOT NULL DEFAULT '',
                metric_value INTEGER, collected_at TEXT NOT NULL,
                raw_text TEXT NOT NULL DEFAULT '',
                query_kind TEXT NOT NULL DEFAULT 'keyword',
                query_value TEXT NOT NULL DEFAULT '',
                query_depth INTEGER NOT NULL DEFAULT 0,
                root_keywords_json TEXT NOT NULL DEFAULT '[]',
                hashtags_json TEXT NOT NULL DEFAULT '[]',
                UNIQUE(run_id, item_id, keyword, sort_key)
            );
            PRAGMA user_version = 2;
            """
        )
    repository = TrendRepository(db_path)
    with repository.connection() as conn:
        observation_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(trend_observations)")
        }
        item_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(trend_items)")
        }
        run_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(trend_collection_runs)")
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert {"metric_kind", "published_at", "published_at_text"} <= observation_columns
    assert {"published_at", "published_at_text"} <= item_columns
    assert {"account_uuid", "plan_id", "batch_id", "wave_kind"} <= run_columns
    assert version == TREND_SCHEMA_VERSION


class _FixtureProvider:
    provider_id = "fixture"

    def collect(self, request, *, policy):
        keyword = request.keywords[0]
        return TrendCollectionResult(
            observations=[
                TrendObservation(
                    item_id=f"fixture:{keyword}",
                    video_id="1",
                    url="https://example.test/video/1",
                    title=f"{keyword} 示例",
                    author="fixture",
                    keyword=keyword,
                    sort_key=request.sorts[0],
                    sort_label=request.sorts[0],
                    rank=1,
                    metric_text="100",
                    metric_value=100,
                )
            ]
        )


def test_collection_plan_can_resume_from_pending_batches(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile = _profile("novel_promotion")
    service = TrendOperationsService(repository=repository)
    plan = service.create_collection_plan(profile, wave_kind="discovery")
    first = plan.batches[0]

    run_id, _ = service.collect_plan_batch(
        _FixtureProvider(),
        plan,
        first.batch_id,
        account_profile=profile,
        policy=approved_manual_import_policy(),
    )

    assert run_id
    assert first.batch_id not in {
        item.batch_id for item in service.pending_plan_batches(plan)
    }
    progress = service.collection_plan_progress(plan)
    assert progress["completed_batches"] == 1
    assert progress["pending_batches"] == len(plan.batches) - 1


def test_video_temporal_signal_distinguishes_rising_falling_and_insufficient() -> None:
    rows = [
        _observation(
            item_id="douyin:rise",
            run_id="r1",
            captured="2026-08-31T00:00:00+00:00",
            metric=100,
            rank=12,
        ),
        _observation(
            item_id="douyin:rise",
            run_id="r2",
            captured="2026-09-01T00:00:00+00:00",
            metric=10_000,
            rank=2,
        ),
        _observation(
            item_id="douyin:fall",
            run_id="r1",
            captured="2026-08-31T00:00:00+00:00",
            metric=10_000,
            rank=2,
        ),
        _observation(
            item_id="douyin:fall",
            run_id="r2",
            captured="2026-09-01T00:00:00+00:00",
            metric=100,
            rank=18,
        ),
        _observation(
            item_id="douyin:one",
            run_id="r2",
            captured="2026-09-01T00:00:00+00:00",
            metric=50,
            rank=8,
        ),
    ]
    signals = {item.item_id: item for item in build_video_trend_signals(rows)}
    assert signals["douyin:rise"].direction == "rising"
    assert signals["douyin:rise"].metric_velocity_per_hour > 0
    assert signals["douyin:fall"].direction == "falling"
    assert signals["douyin:one"].direction == "insufficient"
    assert signals["douyin:one"].confidence == 0


def test_tag_family_signal_uses_cross_run_score_rank_and_metric_changes() -> None:
    snapshots = [
        TrendTagTrafficSnapshot(
            root_keyword="法律",
            tag="彩礼",
            sort_key="latest",
            sort_label="最新发布",
            unique_video_count=5,
            best_rank=12,
            reciprocal_rank_score=1.0,
            sample_score=20,
            visible_metric_max=100,
            run_id="r1",
            collected_at="2026-08-31T00:00:00+00:00",
        ),
        TrendTagTrafficSnapshot(
            root_keyword="法律",
            tag="彩礼",
            sort_key="latest",
            sort_label="最新发布",
            unique_video_count=12,
            best_rank=2,
            reciprocal_rank_score=3.0,
            sample_score=80,
            visible_metric_max=10_000,
            run_id="r2",
            collected_at="2026-09-01T00:00:00+00:00",
        ),
    ]
    signal = build_tag_family_trend_signals(snapshots)[0]
    assert signal.direction == "rising"
    assert signal.point_count == 2
    assert signal.sample_score_velocity_per_hour > 0


def test_visible_publish_time_normalizes_relative_and_china_calendar_dates() -> None:
    captured = "2026-09-01T08:00:00+00:00"
    assert parse_visible_publish_time("2小时前", collected_at=captured).startswith(
        "2026-09-01T06:00:00"
    )
    assert parse_visible_publish_time("昨天", collected_at=captured).startswith(
        "2026-08-31T08:00:00"
    )
    assert parse_visible_publish_time("08-30", collected_at=captured).startswith(
        "2026-08-29T16:00:00"
    )
    assert parse_visible_publish_time("不详", collected_at=captured) == ""


def test_plan_id_is_stable_for_same_profile_wave_and_creation_time() -> None:
    planner = TrendCollectionPlanner()
    created_at = datetime(2026, 9, 1, tzinfo=timezone.utc).isoformat()
    left = planner.build(_profile(), created_at=created_at)
    right = planner.build(_profile(), created_at=created_at)
    assert left.plan_id == right.plan_id
    assert [item.batch_id for item in left.batches] == [
        item.batch_id for item in right.batches
    ]
