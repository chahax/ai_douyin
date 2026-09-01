from datetime import datetime, timedelta, timezone
import sqlite3

from src.trend_intelligence.analysis import TrendAnalyzer, metric_to_number, stable_item_id
from src.trend_intelligence.feedback import OperationsFeedbackService
from src.trend_intelligence.models import (
    PublishedContentContext,
    TrendObservation,
    TrendTagRelation,
    TrendTagTrafficSnapshot,
    VideoMetricSnapshot,
)
from src.trend_intelligence.repository import TREND_SCHEMA_VERSION, TrendRepository


NOW = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)


def _observation(
    video_id: str,
    title: str,
    *,
    run_id: str,
    metric: int,
    rank: int,
    collected_at: datetime,
    keyword: str = "法律",
    sort_key: str = "comprehensive",
) -> TrendObservation:
    return TrendObservation(
        item_id=stable_item_id(video_id=video_id),
        video_id=video_id,
        url=f"https://www.douyin.com/video/{video_id}",
        title=title,
        author="@律师",
        keyword=keyword,
        sort_key=sort_key,
        sort_label=sort_key,
        rank=rank,
        run_id=run_id,
        metric_text=str(metric),
        metric_value=metric,
        collected_at=collected_at.isoformat(),
    )


def test_metric_parser_and_stable_identity() -> None:
    assert metric_to_number("2.4万") == 24_000
    assert metric_to_number("1.2亿") == 120_000_000
    assert metric_to_number("点赞很多") is None
    assert stable_item_id(video_id="123") == "douyin:123"


def test_single_run_is_sample_score_and_similar_hashtags_cluster() -> None:
    rows = [
        _observation(
            "101",
            "没有借条微信转账能追回吗 #借款证据",
            run_id="run-a",
            metric=20_000,
            rank=2,
            collected_at=NOW,
        ),
        _observation(
            "102",
            "只有聊天记录怎么证明借款 #借款证据",
            run_id="run-a",
            metric=12_000,
            rank=5,
            collected_at=NOW,
            sort_key="most_liked",
        ),
    ]
    clusters, briefs = TrendAnalyzer().analyze(rows, preferred_topics=["法律"])

    assert len(clusters) == 1
    assert clusters[0].score_kind == "sample"
    assert clusters[0].trend_score is None
    assert clusters[0].sample_count == 2
    assert briefs[0].status == "draft"
    assert "热门样本" in briefs[0].risks[0]


def test_two_collection_runs_create_real_trend_score() -> None:
    rows = [
        _observation(
            "201",
            "公司违法辞退怎么取证 #劳动仲裁",
            run_id="run-a",
            metric=1_000,
            rank=12,
            collected_at=NOW,
        ),
        _observation(
            "201",
            "公司违法辞退怎么取证 #劳动仲裁",
            run_id="run-b",
            metric=12_000,
            rank=3,
            collected_at=NOW + timedelta(hours=6),
        ),
    ]
    clusters, briefs = TrendAnalyzer().analyze(rows)

    assert clusters[0].score_kind == "trend"
    assert clusters[0].trend_score is not None
    assert clusters[0].trend_score > 0
    assert briefs[0].score_kind == "trend"


def test_repository_persists_analysis_approval_and_snapshots(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    rows = [
        _observation(
            "301",
            "彩礼返还需要哪些证据 #彩礼",
            run_id="",
            metric=8_000,
            rank=1,
            collected_at=NOW,
        )
    ]
    run_id = repository.save_collection(
        rows,
        provider="test",
        keywords=["彩礼"],
    )
    assert run_id
    persisted = repository.list_observations()
    assert persisted[0].run_id == run_id

    clusters, briefs = TrendAnalyzer().analyze(persisted)
    repository.save_analysis(clusters, briefs)
    assert repository.summary() == {
        "runs": 1,
        "items": 1,
        "briefs": 1,
        "approved": 0,
        "snapshots": 0,
        "plans": 0,
        "content_analyses": 0,
        "opportunities": 0,
        "opportunity_scripts": 0,
    }
    assert repository.update_brief_status(briefs[0].brief_id, "approved") is True
    assert repository.get_brief(briefs[0].brief_id).status == "approved"

    repository.link_published_content(
        PublishedContentContext(
            local_id="local-301",
            brief_id=briefs[0].brief_id,
            cluster_id=clusters[0].cluster_id,
        )
    )
    assert repository.attach_video_id("local-301", "301") is True
    repository.record_video_snapshot(
        VideoMetricSnapshot(
            video_id="301",
            local_id="local-301",
            captured_at=NOW.isoformat(),
            views=100,
        )
    )
    assert repository.summary()["snapshots"] == 1


def test_repository_persists_run_scoped_tag_graph_and_rank_snapshots(
    tmp_path,
) -> None:
    repository = TrendRepository(tmp_path / "tag-graph.db")
    row = _observation(
        "351",
        "劳动仲裁证据清单 #法律科普 #劳动法",
        run_id="",
        metric=18_000,
        rank=2,
        collected_at=NOW,
    )
    row.root_keywords = ["法律"]
    row.hashtags = ["法律科普", "劳动法"]
    relation = TrendTagRelation(
        root_keyword="法律",
        source_kind="keyword",
        source_value="法律",
        target_tag="法律科普",
        relation_kind="keyword_hashtag",
        support_video_count=1,
        source_video_count=1,
        unique_authors=1,
        sort_coverage=1,
        weight=1.0,
        relationship_score=100.0,
        expanded=True,
        supporting_item_ids=[row.item_id],
        collected_at=NOW.isoformat(),
    )
    snapshot = TrendTagTrafficSnapshot(
        root_keyword="法律",
        tag="法律科普",
        sort_key="most_liked",
        sort_label="最多点赞",
        unique_video_count=1,
        best_rank=2,
        reciprocal_rank_score=0.6309,
        sample_score=72.5,
        visible_metric_max=18_000,
        visible_metric_median=18_000,
        top_item_ids=[row.item_id],
        collected_at=NOW.isoformat(),
    )

    run_id = repository.save_collection(
        [row],
        provider="test",
        keywords=["法律"],
        tag_relations=[relation],
        tag_traffic_snapshots=[snapshot],
    )

    persisted = repository.list_observations()
    assert persisted[0].root_keywords == ["法律"]
    assert persisted[0].hashtags == ["法律科普", "劳动法"]
    assert repository.latest_collection_run_id() == run_id
    relations = repository.list_tag_relations(run_id=run_id)
    traffic = repository.list_tag_traffic_snapshots(run_id=run_id)
    assert relations[0].supporting_item_ids == [row.item_id]
    assert relations[0].expanded is True
    assert traffic[0].score_kind == "sample_traffic_proxy"
    assert traffic[0].sort_key == "most_liked"

    with repository.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trend_tags").fetchone()[0] == 2
        assert (
            conn.execute("SELECT COUNT(*) FROM trend_observation_tags").fetchone()[0]
            == 2
        )


def test_repository_migrates_legacy_observation_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy-trend.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE trend_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            keyword TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            sort_label TEXT NOT NULL,
            rank INTEGER NOT NULL,
            metric_text TEXT NOT NULL DEFAULT '',
            metric_value INTEGER,
            collected_at TEXT NOT NULL,
            raw_text TEXT NOT NULL DEFAULT '',
            UNIQUE(run_id, item_id, keyword, sort_key)
        )
        """
    )
    conn.commit()
    conn.close()

    repository = TrendRepository(db_path)

    with repository.connection() as migrated:
        columns = {
            row["name"]
            for row in migrated.execute(
                "PRAGMA table_info(trend_observations)"
            ).fetchall()
        }
        version = migrated.execute("PRAGMA user_version").fetchone()[0]
    assert {
        "query_kind",
        "query_value",
        "query_depth",
        "root_keywords_json",
        "hashtags_json",
    } <= columns
    assert version == TREND_SCHEMA_VERSION


def test_feedback_requires_three_effective_videos_before_strategy(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    for index, gained in enumerate((100, 200, 400), start=1):
        local_id = f"local-{index}"
        video_id = str(400 + index)
        repository.link_published_content(
            PublishedContentContext(
                local_id=local_id,
                video_id=video_id,
                cluster_id="cluster:strong" if index < 3 else "cluster:adjacent",
                brief_id=f"brief-{index}",
            )
        )
        repository.record_video_snapshot(
            VideoMetricSnapshot(
                video_id=video_id,
                local_id=local_id,
                captured_at=NOW.isoformat(),
                views=100,
                likes=5,
            )
        )
        repository.record_video_snapshot(
            VideoMetricSnapshot(
                video_id=video_id,
                local_id=local_id,
                captured_at=(NOW + timedelta(hours=2)).isoformat(),
                views=100 + gained,
                likes=20 + index,
                comments=4,
            )
        )

    feedback = OperationsFeedbackService(repository)
    results = feedback.performance_results()
    recommendation = feedback.recommend_next_cycle()

    assert len(results) == 3
    assert results[0].relative_performance > results[-1].relative_performance
    assert recommendation.status == "ready"
    assert recommendation.sample_size == 3
    assert "cluster:strong" in recommendation.proven_topics
    assert recommendation.experiment_share == 0.1


def test_auto_publish_database_step_links_trend_context(tmp_path, monkeypatch) -> None:
    from src.services import auto_publish_service

    trend_db = tmp_path / "publish-trend.db"
    monkeypatch.setenv("TREND_DB_PATH", str(trend_db))
    monkeypatch.setattr(auto_publish_service, "save_video", lambda _video: True)
    monkeypatch.setattr(auto_publish_service, "get_duration", lambda _path: 18.5)

    request = auto_publish_service.AutoPublishRequest(
        keywords="劳动仲裁",
        hashtags=["劳动法"],
        video_mode="presenter_anime",
        trend_brief_id="brief-labor",
        trend_cluster_id="cluster-labor",
        hook_type="question",
        script_version="v2",
        workflow_profile="legal-presenter",
    )
    service = object.__new__(auto_publish_service.AutoPublishService)

    local_id = service._save_to_database(request, "generated.mp4")

    contexts = TrendRepository(trend_db).list_contexts()
    assert len(contexts) == 1
    assert contexts[0].local_id == local_id
    assert contexts[0].brief_id == "brief-labor"
    assert contexts[0].cluster_id == "cluster-labor"
    assert contexts[0].hook_type == "question"
    assert contexts[0].script_version == "v2"
    assert contexts[0].workflow_profile == "legal-presenter"
    assert contexts[0].duration_seconds == 18.5
