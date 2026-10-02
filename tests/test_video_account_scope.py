from __future__ import annotations

from src.platform_adapter.models import CommentRecord, VideoItem, VideoStatus
from src.services.comment_service import count_comments, get_comments, save_comment
from src.services import database
from src.services.video_service import get_videos, mark_videos_deleted, save_video


def test_video_sync_and_deletion_are_scoped_to_operation_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "douyin.db")
    save_video(
        VideoItem(
            video_id="video-a",
            title="A 账号作品",
            status=VideoStatus.PUBLISHED,
            account_uuid="account:a",
            account_key="account-a",
        )
    )
    save_video(
        VideoItem(
            video_id="video-b",
            title="B 账号作品",
            status=VideoStatus.PUBLISHED,
            account_uuid="account:b",
            account_key="account-b",
        )
    )

    changed = mark_videos_deleted(
        [],
        allow_empty=True,
        account_uuid="account:a",
    )

    assert changed == 1
    assert get_videos(account_uuid="account:a")[0]["status"] == "failed"
    assert get_videos(account_uuid="account:b")[0]["status"] == "published"


def test_comment_queries_are_scoped_to_operation_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "douyin.db")
    for video_id, account_uuid in (("video-a", "account:a"), ("video-b", "account:b")):
        save_video(
            VideoItem(
                video_id=video_id,
                title=video_id,
                status=VideoStatus.PUBLISHED,
                account_uuid=account_uuid,
                account_key=account_uuid,
            )
        )
        save_comment(
            CommentRecord(
                comment_id=f"comment-{video_id}",
                author_name="viewer",
                content=f"content-{video_id}",
            ),
            video_id,
        )

    account_a_comments = get_comments(account_uuid="account:a")

    assert [item["comment_id"] for item in account_a_comments] == ["comment-video-a"]
    assert count_comments(account_uuid="account:a") == 1
    assert count_comments(account_uuid="account:b") == 1
