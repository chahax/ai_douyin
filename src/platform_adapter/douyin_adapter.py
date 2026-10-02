from src.platform_adapter.browser_session import BrowserSession, build_default_browser_session_config
from src.platform_adapter.comment_workflow import CommentWorkflow
from src.platform_adapter.models import (
    CommentQuery,
    CommentSyncResult,
    PublishRequest,
    PublishResult,
    SessionState,
    SyncResult,
)
from src.platform_adapter.publish_workflow import PublishWorkflow
from src.platform_adapter.sync_workflow import SyncWorkflow
from src.shared.logger import logger


class DouyinAdapter:
    def __init__(self, session: BrowserSession | None = None, runtime_context=None):
        self.session = session or BrowserSession(build_default_browser_session_config())
        self.runtime_context = runtime_context
        self._identity_verified = False
        self.publish_workflow = PublishWorkflow(self.session)
        self.comment_workflow = CommentWorkflow(self.session)
        self.sync_workflow = SyncWorkflow(self.session)

    @classmethod
    def for_account(cls, account_key: str, *, headless: bool = False):
        from src.operations_accounts import AccountRuntimeService

        context = AccountRuntimeService().resolve(account_key)
        return cls(
            session=context.create_browser_session(headless=headless),
            runtime_context=context,
        )

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
        check = self._require_runtime_identity(force=True)
        if check is not None:
            raise RuntimeError(check[1])
        return self.session.open_page_and_click_button(
            url=url,
            button_text="上传视频",
            pause_seconds=pause_seconds,
            wait_for_enter=wait_for_enter,
        )

    def publish_video(self, request: PublishRequest, interactive: bool = False) -> PublishResult:
        from src.services.artifact_account import artifact_account
        from pathlib import Path
        owner = artifact_account({'production_manifest': str(Path(request.video_path).parent / 'production.json')})
        requested_owners = {value for value in (request.extra_metadata.get('account_uuid'), owner['account_uuid']) if value}
        if owner.get('account_conflict') or (self.runtime_context and any(value != self.runtime_context.account_uuid for value in requested_owners)):
            return PublishResult(success=False, status='account_mismatch', message='成片或发布请求属于其他运营账号，已阻止发布。')
        check = self._require_runtime_identity(force=True)
        if check is not None:
            return PublishResult(
                success=False,
                status=check[0],
                message=check[1],
            )
        request.extra_metadata["account_key"] = self.runtime_context.account_key
        request.extra_metadata["account_uuid"] = self.runtime_context.account_uuid
        request.extra_metadata["platform_identity_key"] = self.runtime_context.binding.platform_identity_key
        request.extra_metadata["binding_verified_at"] = self.runtime_context.binding.verified_at
        request.extra_metadata["douyin_identity"] = (
            self.runtime_context.identity_label
        )
        logger.info(
            "即将使用抖音账号 {} 发布（运营账号 {}）。",
            self.runtime_context.identity_label,
            self.runtime_context.account_key,
        )
        return self.publish_workflow.publish(request, interactive=interactive)

    def verify_published_video(self, request, post_id, publish_url):
        """Inspect an existing exact work through the bound browser; never upload."""
        from src.platform_adapter.publish_verification import video_id
        check = self._require_runtime_identity(force=True)
        if check is not None:
            raise RuntimeError(check[1])
        if video_id(publish_url) != post_id:
            raise ValueError('verification requires an exact published video URL')
        page = self.session.open_page(publish_url)
        return self.publish_workflow._verify_published_work(page, post_id, publish_url, request)

    def reply_to_comment(
        self,
        post_id: str,
        comment_id: str,
        content: str,
        *,
        human_confirmed: bool = False,
    ) -> bool:
        """对指定评论发送回复"""
        if not human_confirmed:
            logger.warning("评论回复需要人工逐次确认，本次未发送。")
            return False
        if self._require_runtime_identity(force=True) is not None:
            return False
        success = self.comment_workflow.reply_to_comment(post_id, comment_id, content)
        if success:
            from src.services.comment_service import mark_comment_replied
            mark_comment_replied(comment_id, content)
        return success

    def fetch_comments(self, query: CommentQuery) -> CommentSyncResult:
        check = self._require_runtime_identity()
        if check is not None:
            return CommentSyncResult(
                success=False,
                status=check[0],
                message=check[1],
            )
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
        check = self._require_runtime_identity()
        if check is not None:
            return SyncResult(success=False, status=check[0], message=check[1])

        from datetime import datetime
        from src.services.sync_history_service import record_sync
        from src.services.video_service import save_video, mark_videos_deleted

        started_at = datetime.now().isoformat()
        videos, api_success = self.sync_workflow.sync_videos(page_limit=page_limit, interactive=interactive)

        new_count = 0
        trend_repository = None
        try:
            from src.trend_intelligence.repository import TrendRepository

            trend_repository = TrendRepository()
        except Exception as exc:
            logger.warning(f"趋势指标快照存储不可用，视频同步继续: {exc}")
        for v in videos:
            v.account_uuid = self.runtime_context.account_uuid
            v.account_key = self.runtime_context.account_key
            if save_video(v):
                new_count += 1
            if v.creator_metrics is not None:
                from src.services.content_performance import record_snapshot
                record_snapshot(v)
            if trend_repository is not None and v.video_id and v.stats:
                try:
                    from src.services.video_service import get_video_by_id
                    from src.trend_intelligence.models import VideoMetricSnapshot

                    stored = get_video_by_id(v.video_id) or {}
                    local_id = stored.get("local_id") or ""
                    trend_repository.attach_video_id(local_id, v.video_id)
                    trend_repository.record_video_snapshot(
                        VideoMetricSnapshot(
                            video_id=v.video_id,
                            local_id=local_id,
                            publish_time=v.publish_time or "",
                            views=v.stats.play_count,
                            likes=v.stats.like_count,
                            comments=v.stats.comment_count,
                            shares=v.stats.share_count,
                            collects=v.stats.collect_count,
                        )
                    )
                except Exception as exc:
                    logger.warning(f"保存视频指标快照失败，视频同步继续: {exc}")

        # A bounded/partial list cannot prove deletion. Background refresh only
        # upserts observed works; reconciliation requires a complete snapshot.
        deleted_count = 0

        finished_at = datetime.now().isoformat()
        status = "success" if api_success else "failed"
        record_sync("videos", len(videos), new_count, started_at, finished_at, status)

        msg = f"共同步到 {len(videos)} 个视频，新增 {new_count} 个"
        if not api_success:
            msg = '作品接口未成功，不能认定账号没有作品；请核对创作者中心登录并查看同步日志。'
        if deleted_count > 0:
            msg += f"，标记 {deleted_count} 个已删除"

        return SyncResult(
            success=api_success,
            status=status,
            videos=videos,
            message=msg,
        )

    def close(self) -> None:
        self.session.stop()

    def verify_runtime_identity(self, *, force: bool = True):
        """Verify that the current browser still belongs to the bound account."""
        from src.operations_accounts import AccountRuntimeError, AccountRuntimeService

        if self.runtime_context is None:
            raise AccountRuntimeError(
                "account_binding_required",
                "该操作必须选择已绑定真实抖音身份的运营账号。",
            )
        if self._identity_verified and not force:
            from src.operations_accounts.runtime import RuntimeIdentityCheck

            return RuntimeIdentityCheck(
                healthy=True,
                status="active",
                message="当前浏览器身份已通过校验。",
                expected=self.runtime_context.binding,
            )
        check = AccountRuntimeService().verify_identity(
            self.runtime_context,
            session=self.session,
        )
        self._identity_verified = bool(check.healthy)
        return check

    def _require_runtime_identity(self, *, force: bool = False):
        if self.runtime_context is None:
            return (
                "account_binding_required",
                "该操作必须选择已绑定真实抖音身份的运营账号。",
            )
        if self._identity_verified and not force:
            return None
        check = self.verify_runtime_identity(force=True)
        if not check.healthy:
            return (check.status, check.message)
        self._identity_verified = True
        return None
