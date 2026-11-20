from types import SimpleNamespace

from src.services import database
from src.services.smart_operations import (
    build_smart_operations_report,
    derive_published_topic_keywords,
    _operating_recommendations,
)


def test_topics_are_derived_from_recent_owned_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "douyin.db")
    with database.get_db() as db:
        db.executemany(
            """INSERT INTO videos(video_id,title,status,account_uuid,account_key)
               VALUES(?,?,?,?,?)""",
            [
                ("v1", "尾款没说清就催签 #装修合同 #合同纠纷", "published", "A", "account01"),
                ("v2", "退租两道钉眼要扣两千押金 #租房押金", "published", "A", "account01"),
                ("v3", "别的账号内容 #劳动争议", "published", "B", "account02"),
            ],
        )
        db.commit()

    topics = derive_published_topic_keywords("A", "account01")

    assert topics == ["租房押金", "装修合同"]


def test_report_marks_read_only_and_preserves_comment_warning(monkeypatch):
    import src.services.smart_operations as module

    monkeypatch.setattr(module, "latest_snapshots", lambda account_uuid: [{
        "video_id": "v1", "title": "装修合同", "publish_time": "2026-09-13",
        "collected_at": "2026-09-21T01:00:00+00:00", "play_count": 100,
        "like_count": 5, "comment_count": 1, "share_count": 0, "collect_count": 2,
        "completion_rate": None, "bounce_2s_rate": None, "avg_watch_seconds": None,
    }])
    monkeypatch.setattr(module, "snapshot_history", lambda account_uuid: [{
        "video_id": "v1", "collected_at": "2026-09-20T01:00:00+00:00",
        "play_count": 90, "like_count": 4, "comment_count": 1,
        "share_count": 0, "collect_count": 1, "completion_rate": 20.0,
        "bounce_2s_rate": 30.0, "avg_watch_seconds": 4.0,
    }, {
        "video_id": "v1", "collected_at": "2026-09-21T01:00:00+00:00",
        "play_count": 100, "like_count": 5, "comment_count": 1,
        "share_count": 0, "collect_count": 2, "completion_rate": None,
        "bounce_2s_rate": None, "avg_watch_seconds": None,
    }])
    monkeypatch.setattr(module, "review_prompts", lambda row: ["复核前两秒钩子"])
    monkeypatch.setattr(module, "analyze_snapshot", lambda row: ({
        "like_count": 5.0, "comment_count": 1.0, "share_count": 0.0,
        "collect_count": 2.0,
    }, "样本较少"))
    monkeypatch.setattr(module, "TrendRepository", lambda: SimpleNamespace(
        list_opportunities=lambda **kwargs: [],
        list_observations=lambda **kwargs: [],
    ))
    result = SimpleNamespace(
        status="completed", run_id="run", log_path="log.json",
        research_keywords=["装修合同"], published_data_sync_completed=True,
        synced_videos=1, synced_comments=0, comment_sync_failures=1,
        collected_count=10, unique_relevant_videos=8, skipped_irrelevant=2,
        video_records=[], started_at="2026-09-21T00:00:00+00:00",
        warnings=["评论暂未同步"], interaction_actions=0,
    )

    report = build_smart_operations_report("A", "account01", result)

    assert report["publication_submitted"] is False
    assert report["external_interactions_performed"] == 0
    assert report["backend_sync"]["completed"] is True
    assert report["backend_sync"]["comment_failures"] == 1
    assert report["owned_content_performance"][0]["metric_delta"]["play_count"] == 10
    assert report["owned_content_performance"][0]["last_known_retention"]["completion_rate"] == 20.0


def test_content_patterns_do_not_relabel_unknown_page_metric(monkeypatch):
    import src.services.smart_operations as module

    patterns = module._content_patterns([
        {"title": "这10条一定要写进装修合同", "hashtags": ["装修合同", "装修避坑"],
         "duration_seconds": 120, "visible_metric": 9999, "visible_metric_kind": "displayed_unknown",
         "primary_tag": "装修合同", "associated_keywords": ["装修合同"]},
        {"title": "退租为什么要扣押金？", "hashtags": ["租房押金"],
         "duration_seconds": 45, "visible_metric": 88, "visible_metric_kind": "displayed_unknown",
         "primary_tag": "租房押金", "associated_keywords": ["租房押金"]},
    ], keywords=["装修合同", "租房押金"])

    assert patterns["sample_size"] == 2
    assert patterns["median_duration_seconds"] == 82.5
    assert patterns["duration_buckets"]["short_60s_or_less"] == 1
    assert patterns["topic_coverage"] == {"装修合同": 1, "租房押金": 1}
    assert "不按点赞量解释" in patterns["metric_semantics"]


def test_operating_recommendations_are_evidence_bounded():
    performance = [
        {
            "video_id": "v1",
            "metrics": {"play_count": 668},
            "last_known_retention": {"completion_rate": 19.29, "bounce_2s_rate": 30.5},
        },
        {
            "video_id": "v2",
            "metrics": {"play_count": 120},
            "last_known_retention": {"completion_rate": 21.43, "bounce_2s_rate": 37.5},
        },
    ]
    patterns = {
        "topic_coverage": {"装修合同": 28, "租房押金": 1},
        "hook_signals": [
            {"label": "风险警告", "count": 25},
            {"label": "清单/数字承诺", "count": 15},
        ],
    }

    recommendations = _operating_recommendations(performance, patterns)

    titles = [item["title"] for item in recommendations]
    assert titles == ["优先验证高触达选题", "先改前两秒", "补齐关联样本", "测试标题结构"]
    assert "不要只凭两条作品永久定方向" in recommendations[0]["action"]
    assert "租房押金" in recommendations[2]["action"]
    assert "不把页面未确认数字当成效果证明" in recommendations[3]["action"]
