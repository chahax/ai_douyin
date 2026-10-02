"""
auto_reply_service.py — 自动回复机器人主服务

协调：评论过滤 → 回复生成 → 浏览器发送 → 记录落库
"""

from dataclasses import dataclass, field
from typing import List

from src.platform_adapter.models import CommentRecord
from src.services.comment_filter import should_reply
from src.services.reply_context_service import (
    get_context, add_user_comment, add_bot_reply, build_context_prompt,
)
from src.services.reply_rules_service import match_rule, DEFAULT_REPLY
from src.services.user_profile_service import can_reply, record_reply
from src.services.video_service import get_video_by_id
from src.shared.logger import logger
from src.shared.llm_client import LLMClient


@dataclass
class ReplyAction:
    comment: CommentRecord
    reply_content: str
    source: str  # 'rule' | 'llm' | 'default'


@dataclass
class AutoReplyResult:
    success: bool
    video_id: str
    total_comments: int
    replied: int
    skipped: int
    failed: int
    actions: List[ReplyAction] = field(default_factory=list)
    message: str = ""


class AutoReplyService:
    """
    自动回复机器人主服务。

    流程：
      1. 抓取视频评论
      2. 对每条评论判断是否回复
      3. 生成回复内容（规则优先 → LLM → 默认）
      4. 浏览器自动化发送回复
      5. 更新用户计数、上下文、回复历史
    """

    def __init__(self, account_key: str):
        from src.platform_adapter.douyin_adapter import DouyinAdapter

        if not account_key.strip():
            raise ValueError("生成回复建议前必须选择已绑定的运营账号。")
        self.adapter = DouyinAdapter.for_account(account_key)
        self.session = self.adapter.session
        self.llm_client = LLMClient()

    def process_video(
        self,
        video_id: str,
        *,
        confirmed_comment_ids: set[str] | None = None,
    ) -> AutoReplyResult:
        """
        对指定视频执行自动回复。
        """
        logger.info(f"开始处理视频评论: {video_id}")

        # 获取视频信息（用于 prompt）
        video_info = get_video_by_id(video_id)
        video_title = video_info.get("title", "") if video_info else ""
        rag_context = video_info.get("rag_context", "") if video_info else ""

        # 1. 抓取评论
        from src.platform_adapter.models import CommentQuery
        fetch_result = self.adapter.fetch_comments(CommentQuery(post_id=video_id))

        if not fetch_result.success:
            return AutoReplyResult(
                success=False,
                video_id=video_id,
                total_comments=0,
                replied=0,
                skipped=0,
                failed=0,
                message=f"评论抓取失败: {fetch_result.message}",
            )

        comments = fetch_result.comments
        logger.info(f"获取到 {len(comments)} 条评论")

        replied = 0
        skipped = 0
        failed = 0
        actions: List[ReplyAction] = []

        for comment in comments:
            # 2. 判断是否应该回复
            user_can = can_reply(comment.author_name)
            result = should_reply(comment, user_can)

            if not result.should_reply:
                logger.info(f"  跳过 [{comment.comment_id}] {comment.content[:20]}: {result.reason}")
                skipped += 1
                continue

            # 3. 生成回复内容
            reply_content, source = self._generate_reply(comment, video_title, rag_context)

            actions.append(ReplyAction(comment, reply_content, source))
            # 外部互动必须由管理员逐条提交 comment_id 作为人工确认凭据。
            if comment.comment_id not in (confirmed_comment_ids or set()):
                skipped += 1
                continue
            sent = self.adapter.reply_to_comment(
                video_id,
                comment.comment_id,
                reply_content,
                human_confirmed=True,
            )

            if sent:
                # 5. 记录
                record_reply(comment.author_name)
                add_user_comment(comment.author_name, video_id, comment.content)
                add_bot_reply(comment.author_name, video_id, reply_content)
                _save_reply_history(comment, video_id, reply_content, source)

                logger.info(f"  回复成功 [{comment.comment_id}] {reply_content[:30]}")
                replied += 1
            else:
                logger.warning(f"  回复失败 [{comment.comment_id}]")
                failed += 1

        logger.info(f"处理完成: 回复={replied}, 跳过={skipped}, 失败={failed}")

        return AutoReplyResult(
            success=True,
            video_id=video_id,
            total_comments=len(comments),
            replied=replied,
            skipped=skipped,
            failed=failed,
            actions=actions,
            message=(
                f"生成 {len(actions)} 条回复建议；已发送 {replied} 条。"
                "未逐条人工确认的建议不会发送。"
            ),
        )

    def close(self) -> None:
        self.adapter.close()

    def _generate_reply(self, comment: CommentRecord, video_title: str, rag_context: str = "") -> tuple[str, str]:
        """
        生成回复内容。

        优先级：固定规则 → LLM 生成 → 默认回复
        """
        # 优先匹配关键词规则
        rule = match_rule(comment.content)
        if rule and rule.reply_type == "fixed":
            return rule.reply_template, "rule"

        # 检查是否是 LLM 规则
        if rule and rule.reply_type == "llm":
            content = self._llm_generate(comment, video_title, rag_context, rule.llm_model)
            return content, "llm"

        # 无规则匹配，尝试 LLM 生成
        llm_content = self._llm_generate(comment, video_title, rag_context, None)
        if llm_content:
            # 生成内容过违禁词检查
            from src.services.comment_filter import _has_blocked_word
            if not _has_blocked_word(llm_content):
                return llm_content, "llm"

        # 降级为默认回复
        return DEFAULT_REPLY, "default"

    def _llm_generate(self, comment: CommentRecord, video_title: str, rag_context: str = "", model: str | None = None) -> str:
        """调用 LLM 生成回复"""
        try:
            context = get_context(comment.author_name, "", limit=5)
            context_text = build_context_prompt(context)

            prompt = self._build_prompt(comment, context_text, video_title, rag_context)
            model = model or "qwen2.5:7b"

            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
            )
            # 提取回复内容（去掉引号等）
            content = response.strip().strip('""""')
            if content:
                return content
        except Exception as exc:
            logger.warning(f"LLM 生成失败: {exc}")

        return ""

    def _build_prompt(self, comment: CommentRecord, context_text: str, video_title: str, rag_context: str = "") -> str:
        """构建 LLM 回复 Prompt"""
        context_part = f"评论历史：\n{context_text}\n" if context_text else ""
        rag_part = f"【知识库参考】\n{rag_context}\n" if rag_context else ""
        return f"""你是抖音主播的AI助手，正在回复粉丝评论。
{rag_part}视频主题：{video_title}
{context_part}当前评论：
评论者：{comment.author_name}
内容：{comment.content}

请结合知识库内容，生成一条简短、自然的回复（20字以内）："""


def _save_reply_history(comment: CommentRecord, video_id: str, reply_content: str, source: str) -> None:
    """保存回复历史到数据库"""
    from src.services.database import get_db
    from datetime import datetime

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reply_history
                (user_nickname, video_id, comment_id, reply_content, auto_generated, model_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            comment.author_name,
            video_id,
            comment.comment_id,
            reply_content,
            1 if source != "rule" else 0,  # 固定规则回复算手动
            source,
            datetime.now().isoformat(),
        ))
        conn.commit()
