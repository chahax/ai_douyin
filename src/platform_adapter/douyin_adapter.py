from src.platform_adapter.browser_session import BrowserSession, build_default_browser_session_config
from src.platform_adapter.comment_workflow import CommentWorkflow
from src.platform_adapter.models import (
    CommentQuery,
    CommentSyncResult,
    PublishRequest,
    PublishResult,
    SessionState,
    SyncResult,
    VideoItem,
)
from src.platform_adapter.publish_workflow import PublishWorkflow
from src.platform_adapter.sync_workflow import SyncWorkflow


class DouyinAdapter:
    def __init__(self, session: BrowserSession | None = None):
        self.session = session or BrowserSession(build_default_browser_session_config())
        self.publish_workflow = PublishWorkflow(self.session)
        self.comment_workflow = CommentWorkflow(self.session)
        self.sync_workflow = SyncWorkflow(self.session)

    def prepare_session(self) -> SessionState:
        return self.session.start()

    def get_session_state(self) -> SessionState:
        return self.session.get_state()

    def open_login_window(
        self,
        url: str | None = None,
        pause_seconds: int = 600,
        wait_for_enter: bool = False,
    ) -> SessionState:
        return self.session.open_for_manual_login(
            url=url,
            pause_seconds=pause_seconds,
            wait_for_enter=wait_for_enter,
        )

    def open_login_window_until_closed(
        self,
        url: str | None = None,
        timeout_seconds: int = 1800,
    ) -> SessionState:
        return self.session.open_for_manual_login_until_closed(
            url=url,
            timeout_seconds=timeout_seconds,
        )

    def open_upload_page(
        self,
        url: str,
        pause_seconds: int = 600,
        wait_for_enter: bool = False,
    ) -> SessionState:
        return self.session.open_page_and_click_button(
            url=url,
            button_text="上传视频",
            pause_seconds=pause_seconds,
            wait_for_enter=wait_for_enter,
        )

    def publish_video(self, request: PublishRequest, interactive: bool = False) -> PublishResult:
        return self.publish_workflow.publish(request, interactive=interactive)

    def reply_to_comment(self, post_id: str, comment_id: str, content: str) -> bool:
        """对指定评论发送回复"""
        success = self.comment_workflow.reply_to_comment(post_id, comment_id, content)
        if success:
            from src.services.comment_service import mark_comment_replied
            mark_comment_replied(comment_id, content)
        return success

    def fetch_comments(self, query: CommentQuery) -> CommentSyncResult:
        result = self.comment_workflow.fetch_comments(query)
        if result.success and result.comments:
            from src.services.comment_service import save_comment
            video_id = query.post_id or ""
            for c in result.comments:
                save_comment(c, video_id)
        return result

    def sync_videos(self, page_limit: int = 5, interactive: bool = False) -> SyncResult:
        """
        一次性同步已发布视频列表，并持久化到数据库。

        Args:
            page_limit: 最多翻页次数
            interactive: 启用交互模式

        Returns:
            SyncResult: 包含视频列表
        """
        from datetime import datetime
        from src.services.sync_history_service import record_sync
        from src.services.video_service import save_video, mark_videos_deleted

        started_at = datetime.now().isoformat()
        videos, api_success = self.sync_workflow.sync_videos(page_limit=page_limit, interactive=interactive)

        new_count = 0
        for v in videos:
            if save_video(v):
                new_count += 1

        # 标记在平台上已删除的视频为 failed
        # API成功但返回0个视频 → 平台上已无视频，应将所有 published 标记为 failed
        existing_ids = [v.video_id for v in videos if v.video_id]
        deleted_count = mark_videos_deleted(existing_ids, allow_empty=(api_success and len(videos) == 0))

        finished_at = datetime.now().isoformat()
        status = "success" if videos else "failed"
        record_sync("videos", len(videos), new_count, started_at, finished_at, status)

        msg = f"共同步到 {len(videos)} 个视频，新增 {new_count} 个"
        if deleted_count > 0:
            msg += f"，标记 {deleted_count} 个已删除"

        return SyncResult(
            success=bool(videos) or deleted_count > 0,
            status=status,
            videos=videos,
            message=msg,
        )

    def close(self) -> None:
        self.session.stop()
