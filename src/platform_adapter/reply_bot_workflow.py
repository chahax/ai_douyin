"""
reply_bot_workflow.py — 自动回复机器人浏览器自动化

复用 comment_workflow 的 reply_to_comment 逻辑，
提供独立的回复执行能力。
"""

from dataclasses import dataclass

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.comment_workflow import CommentWorkflow
from src.shared.logger import logger


@dataclass
class ReplyResult:
    success: bool
    comment_id: str
    reply_content: str
    message: str


class ReplyBotWorkflow:
    """
    回复机器人浏览器自动化。
    复用 CommentWorkflow 的 reply_to_comment 能力。
    """

    def __init__(self, session: BrowserSession):
        self.session = session
        self._comment_workflow = CommentWorkflow(session)

    def reply(self, post_id: str, comment_id: str, content: str) -> ReplyResult:
        """
        发送回复。
        成功返回 True，失败返回 False。
        """
        try:
            success = self._comment_workflow.reply_to_comment(post_id, comment_id, content)
            return ReplyResult(
                success=success,
                comment_id=comment_id,
                reply_content=content,
                message="发送成功" if success else "发送失败",
            )
        except Exception as exc:
            logger.exception("回复发送异常")
            return ReplyResult(
                success=False,
                comment_id=comment_id,
                reply_content=content,
                message=f"异常: {exc}",
            )
