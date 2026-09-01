from src.platform_adapter.douyin_adapter import DouyinAdapter
from src.platform_adapter.models import VideoItem, VideoStats, VideoStatus


class _SyncWorkflow:
    def __init__(self, video: VideoItem):
        self.video = video

    def sync_videos(self, page_limit: int, interactive: bool):
        assert page_limit == 2
        assert interactive is False
        return [self.video], True


class _TrendRepository:
    def __init__(self):
        self.attachments: list[tuple[str, str]] = []
        self.snapshots = []

    def attach_video_id(self, local_id: str, video_id: str) -> bool:
        self.attachments.append((local_id, video_id))
        return True

    def record_video_snapshot(self, snapshot) -> None:
        self.snapshots.append(snapshot)


def test_sync_videos_records_trend_metric_snapshot(monkeypatch) -> None:
    video = VideoItem(
        video_id="douyin-501",
        title="测试作品",
        status=VideoStatus.PUBLISHED,
        publish_time="2026-08-30T08:00:00+00:00",
        stats=VideoStats(
            play_count=1_200,
            like_count=80,
            comment_count=9,
            share_count=7,
            collect_count=6,
        ),
    )
    trend_repository = _TrendRepository()
    adapter = object.__new__(DouyinAdapter)
    adapter.sync_workflow = _SyncWorkflow(video)

    monkeypatch.setattr("src.services.video_service.save_video", lambda _video: True)
    monkeypatch.setattr(
        "src.services.video_service.get_video_by_id",
        lambda _video_id: {"local_id": "local-501"},
    )
    monkeypatch.setattr(
        "src.services.video_service.mark_videos_deleted",
        lambda _ids, allow_empty=False: 0,
    )
    monkeypatch.setattr("src.services.sync_history_service.record_sync", lambda *args: None)
    monkeypatch.setattr(
        "src.trend_intelligence.repository.TrendRepository",
        lambda: trend_repository,
    )

    result = adapter.sync_videos(page_limit=2)

    assert result.success is True
    assert trend_repository.attachments == [("local-501", "douyin-501")]
    assert len(trend_repository.snapshots) == 1
    snapshot = trend_repository.snapshots[0]
    assert snapshot.views == 1_200
    assert snapshot.likes == 80
    assert snapshot.comments == 9
    assert snapshot.shares == 7
    assert snapshot.collects == 6
