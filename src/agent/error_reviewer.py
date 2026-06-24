# -*- coding: utf-8 -*-
"""
src/agent/error_reviewer.py — 错误诊断 LLM 客户端

Phase 3：所有系统错误（agent chat / skill exec / worker task）经
这里调 LLM 生成结构化诊断，落 ErrorReview 表。

设计：
  - build_review 同步：调 LLM，缓存（同 signature 命中复用）
  - review_and_store_async 异步：调 LLM + 写库
  - LLM 失败 fallback（始终返回 review dict + signature）

LLM 输出 JSON：
  {
    "severity": "low" | "medium" | "high" | "critical",
    "category": "transient" | "config" | "external_api" | "logic" | "resource" | "auth" | "data",
    "summary": "<一句话人话>",
    "root_cause_hypothesis": "<最可能原因 1-2 句>",
    "suggested_fix": "<可执行下一步 1-2 句>",
    "is_recurring": true | false,
    "cluster_key": "<同类型稳定 key>"
  }
"""

import asyncio
import hashlib
import json
import logging
import re
import traceback
from datetime import datetime
from typing import Any

from src.shared.cache import TTLCache
from src.shared.database import SessionLocal
from src.shared.llm_client import llm_client


logger = logging.getLogger(__name__)


ERROR_REVIEW_PROMPT = """你是系统错误诊断助手。给定一次错误的上下文，输出严格 JSON：

{{
  "severity": "low" | "medium" | "high" | "critical",
  "category": "transient" | "config" | "external_api" | "logic" | "resource" | "auth" | "data",
  "summary": "<一句话人话描述发生了什么>",
  "root_cause_hypothesis": "<最可能的原因，1-2 句>",
  "suggested_fix": "<具体可执行的下一步，1-2 句>",
  "is_recurring": true | false,
  "cluster_key": "<同类型错误的稳定 key，如 'skill_timeout:publish_douyin' 或 'llm_empty_response'>"
}}

错误上下文：
- 来源: {source}
- 位置: {location}
- 错误类型: {error_type}
- 错误消息: {error_message}
- 堆栈片段: {traceback_snippet}
- 关联上下文: {context_extra}

只输出 JSON，不要任何解释。"""


def _signature(source: str, location: str, exc: Exception, ctx: dict) -> str:
    """计算去重签名：source|location|错误类型|错误消息。"""
    key = f"{source}|{location}|{type(exc).__name__}|{str(exc)[:120]}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


class ErrorReviewer:
    """错误诊断 LLM 客户端（同步 + 异步）。"""

    def __init__(self, *, maxsize: int = 200, ttl: int = 3600):
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)

    # -- 同步 build -----------------------------------------------------

    def build_review(
        self,
        *,
        source: str,
        location: str,
        exc: Exception,
        context_extra: dict | None = None,
    ) -> dict:
        """
        同步调 LLM 生成诊断。永不抛异常，LLM 失败时返回 fallback 字典。
        """
        ctx = context_extra or {}
        sig = _signature(source, location, exc, ctx)
        cached = self._cache.get(sig)
        if cached is not None:
            return cached

        try:
            traceback_snippet = "".join(
                traceback.format_exception(exc)
            )[-1200:]
            prompt = ERROR_REVIEW_PROMPT.format(
                source=source,
                location=location,
                error_type=type(exc).__name__,
                error_message=str(exc)[:300],
                traceback_snippet=traceback_snippet,
                context_extra=json.dumps(ctx, ensure_ascii=False)[:500],
            )
            resp = llm_client.chat_completion(
                [
                    {"role": "system", "content": "严格输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                json_mode=True,
            )
            data = _parse_review_response(resp, exc)
            data["signature"] = sig
            self._cache[sig] = data
            return data
        except Exception as exc2:
            logger.warning("ErrorReviewer LLM 失败，fallback: %s", exc2)
            return self._fallback(exc, sig)

    # -- 异步 store -----------------------------------------------------

    async def review_and_store_async(
        self,
        *,
        source: str,
        location: str,
        exc: Exception,
        context_extra: dict | None = None,
    ) -> int | None:
        """
        异步 build + 写 ErrorReview 表。同 signature 自增 occurrence_count。
        返回新行或已有行的 id，失败返回 None。
        """
        from src.memory.error_review_model import ErrorReview

        review = await asyncio.to_thread(
            self.build_review,
            source=source,
            location=location,
            exc=exc,
            context_extra=context_extra,
        )
        try:
            with SessionLocal() as sess:
                existing = (
                    sess.query(ErrorReview)
                    .filter_by(signature=review["signature"])
                    .first()
                )
                if existing is not None:
                    existing.occurrence_count += 1
                    existing.last_seen_at = datetime.utcnow()
                    if not existing.is_recurring and review.get("is_recurring"):
                        existing.is_recurring = True
                    # 永远覆盖最新诊断
                    for k in (
                        "severity",
                        "category",
                        "summary",
                        "root_cause",
                        "suggested_fix",
                        "cluster_key",
                    ):
                        v = review.get(k)
                        if v:
                            setattr(existing, k, str(v)[:500])
                    sess.commit()
                    return existing.id

                row = ErrorReview(
                    source=source,
                    location=location,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:1000],
                    traceback_snippet="".join(
                        traceback.format_exception(exc)
                    )[-2000:],
                    severity=review.get("severity", "medium"),
                    category=review.get("category", "transient"),
                    summary=review.get("summary", "")[:300],
                    root_cause=review.get("root_cause_hypothesis", "")[:500],
                    suggested_fix=review.get("suggested_fix", "")[:500],
                    cluster_key=review.get("cluster_key", "")[:128],
                    is_recurring=bool(review.get("is_recurring", False)),
                    signature=review["signature"],
                    context_extra=json.dumps(
                        context_extra or {}, ensure_ascii=False
                    )[:2000],
                    occurrence_count=1,
                    first_seen_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow(),
                )
                sess.add(row)
                sess.commit()
                sess.refresh(row)
                return row.id
        except Exception:
            logger.exception("ErrorReviewer: store failed")
            return None

    def clear_cache(self) -> None:
        """测试用。"""
        self._cache.clear()

    # -- fallback -------------------------------------------------------

    def _fallback(self, exc: Exception, sig: str) -> dict:
        return {
            "severity": "medium",
            "category": "transient",
            "summary": str(exc)[:200],
            "root_cause_hypothesis": "(LLM 不可用，无假设)",
            "suggested_fix": "查看日志以获取更多信息。",
            "is_recurring": False,
            "cluster_key": f"unknown:{type(exc).__name__}",
            "signature": sig,
        }


# ---------------------------------------------------------------------------
# JSON 解析
# ---------------------------------------------------------------------------


def _parse_review_response(resp: Any, exc: Exception) -> dict:
    """从 LLM 响应里抽出 JSON dict。"""
    if not isinstance(resp, str):
        return _fallback_parse(exc, "non-string response")

    s = resp.strip()
    # 去掉 markdown 围栏
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\}", s, re.DOTALL)
        if not m:
            return _fallback_parse(exc, "no json in response")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return _fallback_parse(exc, "json decode failed")

    # 校验
    severity = data.get("severity")
    if severity not in ("low", "medium", "high", "critical"):
        data["severity"] = "medium"
    category = data.get("category")
    if category not in (
        "transient",
        "config",
        "external_api",
        "logic",
        "resource",
        "auth",
        "data",
    ):
        data["category"] = "transient"
    data.setdefault("summary", str(exc)[:200])
    data.setdefault("root_cause_hypothesis", "")
    data.setdefault("suggested_fix", "")
    data.setdefault("is_recurring", False)
    data.setdefault("cluster_key", f"{type(exc).__name__}:{category}")
    return data


def _fallback_parse(exc: Exception, reason: str) -> dict:
    return {
        "severity": "medium",
        "category": "transient",
        "summary": f"{type(exc).__name__}: {exc}"[:200],
        "root_cause_hypothesis": f"(parse failed: {reason})",
        "suggested_fix": "查看日志。",
        "is_recurring": False,
        "cluster_key": f"parse_fail:{type(exc).__name__}",
    }


# 单例
error_reviewer = ErrorReviewer()
