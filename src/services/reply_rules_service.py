"""
reply_rules_service.py — 自动回复规则服务

提供回复规则的 CRUD 和匹配查询操作
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.services.database import get_db


DEFAULT_REPLY = "感谢支持！"


@dataclass
class ReplyRule:
    id: int
    keyword: str
    reply_template: str
    match_type: str       # 'exact' | 'contains' | 'regex'
    reply_type: str       # 'fixed' | 'llm' | 'default'
    llm_model: str        # LLM 模型名称
    enabled: bool


def _now() -> str:
    return datetime.now().isoformat()


# ─── CRUD ────────────────────────────────────────────────

def add_rule(
    keyword: str,
    reply_template: str,
    match_type: str = "contains",
    reply_type: str = "fixed",
    llm_model: str = "",
    enabled: bool = True,
) -> int:
    """添加新规则，返回新规则 ID"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO auto_reply_rules
                (keyword, reply_template, match_type, reply_type, llm_model, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (keyword, reply_template, match_type, reply_type, llm_model, int(enabled), _now()))
        conn.commit()
        return cursor.lastrowid


def get_rules(enabled_only: bool = False) -> list[ReplyRule]:
    """获取所有规则"""
    with get_db() as conn:
        cursor = conn.cursor()
        if enabled_only:
            cursor.execute("""
                SELECT id, keyword, reply_template, match_type, reply_type, llm_model, enabled
                FROM auto_reply_rules WHERE enabled = 1 ORDER BY LENGTH(keyword) DESC
            """)
        else:
            cursor.execute("""
                SELECT id, keyword, reply_template, match_type, reply_type, llm_model, enabled
                FROM auto_reply_rules ORDER BY LENGTH(keyword) DESC
            """)
        return [
            ReplyRule(
                id=row[0],
                keyword=row[1],
                reply_template=row[2],
                match_type=row[3] or "contains",
                reply_type=row[4] or "fixed",
                llm_model=row[5] or "",
                enabled=bool(row[6]),
            )
            for row in cursor.fetchall()
        ]


def update_rule(
    rule_id: int,
    keyword: Optional[str] = None,
    reply_template: Optional[str] = None,
    match_type: Optional[str] = None,
    reply_type: Optional[str] = None,
    llm_model: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> bool:
    """更新规则字段"""
    fields = []
    values = []
    if keyword is not None:
        fields.append("keyword = ?")
        values.append(keyword)
    if reply_template is not None:
        fields.append("reply_template = ?")
        values.append(reply_template)
    if match_type is not None:
        fields.append("match_type = ?")
        values.append(match_type)
    if reply_type is not None:
        fields.append("reply_type = ?")
        values.append(reply_type)
    if llm_model is not None:
        fields.append("llm_model = ?")
        values.append(llm_model)
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(int(enabled))

    if not fields:
        return False

    values.append(rule_id)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE auto_reply_rules SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_rule(rule_id: int) -> bool:
    """删除规则"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM auto_reply_rules WHERE id = ?", (rule_id,))
        conn.commit()
        return cursor.rowcount > 0


# ─── 匹配查询 ────────────────────────────────────────────

def match_rule(comment_content: str) -> Optional[ReplyRule]:
    """
    匹配评论内容，返回第一个匹配的规则。
    按 keyword 长度降序排列，最长匹配优先（避免"买"和"怎么买"冲突）。
    """
    rules = get_rules(enabled_only=True)
    content = comment_content.strip()

    for rule in rules:
        if rule.reply_type == "default":
            continue  # 默认回复规则特殊处理

        matched = False
        if rule.match_type == "exact":
            matched = content == rule.keyword.strip()
        elif rule.match_type == "contains":
            matched = rule.keyword.strip() in content
        elif rule.match_type == "regex":
            try:
                matched = bool(re.search(rule.keyword, content))
            except re.error:
                matched = False

        if matched:
            return rule

    return None


def match_llm_rule() -> Optional[ReplyRule]:
    """查找第一条启用且 reply_type='llm' 的规则，用于指定 LLM 模型"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, keyword, reply_template, match_type, reply_type, llm_model, enabled
            FROM auto_reply_rules
            WHERE enabled = 1 AND reply_type = 'llm'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            return ReplyRule(
                id=row[0], keyword=row[1], reply_template=row[2],
                match_type=row[3] or "contains", reply_type=row[4] or "llm",
                llm_model=row[5] or "", enabled=True,
            )
    return None
