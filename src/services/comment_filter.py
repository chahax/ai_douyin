"""
comment_filter.py — 评论过滤器

判断评论是否应该被回复
"""

import re
from dataclasses import dataclass

from src.platform_adapter.models import CommentRecord
from src.services.database import get_db


@dataclass
class FilterResult:
    should_reply: bool
    reason: str  # 跳过原因，为空表示应该回复


def _is_noise(content: str) -> bool:
    """判断是否为无意义评论（纯数字/符号/英文，无中文）"""
    stripped = content.strip()
    if not stripped:
        return True
    # 移除非中文内容，检查是否还有中文字符
    chinese_chars = re.sub(r'[一-鿿\w]', '', stripped)
    # 如果去掉中文字母数字下划线后剩下的都是标点，且原内容长度 > 3，认为是噪音
    if len(stripped) > 3 and not re.search(r'[一-鿿]', stripped):
        return True
    return False


def _has_blocked_word(content: str) -> bool:
    """检查评论内容是否包含违禁词"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT word FROM blocked_words")
        words = [row[0] for row in cursor.fetchall()]

    for word in words:
        if word in content:
            return True
    return False


def should_reply(comment: CommentRecord, user_can_reply: bool) -> FilterResult:
    """
    判断是否应该回复某条评论。

    按优先级检查：
    1. 作者评论 → 跳过
    2. 空评论 → 跳过
    3. 纯数字/符号评论 → 跳过
    4. 违禁词评论 → 跳过
    5. 已回复评论 → 跳过
    6. 用户超限 → 跳过
    """
    # 1. 作者评论
    if getattr(comment, 'is_author', False):
        return FilterResult(False, "作者评论")

    # 2. 空评论
    content = comment.content.strip() if comment.content else ""
    if not content:
        return FilterResult(False, "空评论")

    # 3. 纯数字/符号评论
    if _is_noise(content):
        return FilterResult(False, "纯数字/符号评论")

    # 4. 违禁词
    if _has_blocked_word(content):
        return FilterResult(False, "违禁词")

    # 5. 已回复
    if getattr(comment, 'is_replied', 0) == 1:
        return FilterResult(False, "已回复")

    # 6. 用户超限
    if not user_can_reply:
        return FilterResult(False, "用户超限")

    return FilterResult(True, "")


def filter_comment(comment: CommentRecord, user_can_reply: bool) -> FilterResult:
    """should_reply 的别名，保持向后兼容"""
    return should_reply(comment, user_can_reply)
