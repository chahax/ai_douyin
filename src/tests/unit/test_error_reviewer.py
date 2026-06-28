# -*- coding: utf-8 -*-
"""
Tests for src/agent/error_reviewer.py.

Covers:
  - build_review happy path (LLM returns valid JSON)
  - build_review JSON parser tolerates markdown fences / garbage
  - build_review falls back to safe default when LLM returns None
  - _signature is stable across retries with same inputs
  - review_and_store_async inserts a new row, increments on duplicate
  - LLM failure in build_review still returns a usable dict
"""

import json
from unittest.mock import patch


from src.agent.error_reviewer import (
    ErrorReviewer,
    _parse_review_response,
    _signature,
)


# ---------------------------------------------------------------------------
# _signature
# ---------------------------------------------------------------------------


class TestSignature:
    def test_stable_across_calls(self):
        exc = ValueError("boom")
        s1 = _signature("agent_chat", "session:1", exc, {"x": 1})
        s2 = _signature("agent_chat", "session:1", exc, {"x": 1})
        assert s1 == s2

    def test_differs_on_source(self):
        exc = ValueError("boom")
        s1 = _signature("agent_chat", "session:1", exc, {})
        s2 = _signature("skill_exec", "session:1", exc, {})
        assert s1 != s2

    def test_differs_on_message(self):
        s1 = _signature("x", "y", ValueError("a"), {})
        s2 = _signature("x", "y", ValueError("b"), {})
        assert s1 != s2


# ---------------------------------------------------------------------------
# _parse_review_response
# ---------------------------------------------------------------------------


class TestParseReviewResponse:
    def test_plain_json(self):
        raw = json.dumps(
            {
                "severity": "high",
                "category": "external_api",
                "summary": "调用超时",
                "root_cause_hypothesis": "网络问题",
                "suggested_fix": "重试",
                "is_recurring": True,
                "cluster_key": "timeout:publish_douyin",
            }
        )
        data = _parse_review_response(raw, ValueError("x"))
        assert data["severity"] == "high"
        assert data["category"] == "external_api"
        assert data["cluster_key"] == "timeout:publish_douyin"

    def test_markdown_fence(self):
        raw = "```json\n" + json.dumps(
            {
                "severity": "medium",
                "category": "transient",
                "summary": "s",
                "root_cause_hypothesis": "r",
                "suggested_fix": "f",
                "is_recurring": False,
                "cluster_key": "c",
            }
        ) + "\n```"
        data = _parse_review_response(raw, ValueError("x"))
        assert data["severity"] == "medium"

    def test_invalid_severity_normalized(self):
        raw = json.dumps(
            {
                "severity": "extreme",
                "category": "transient",
                "summary": "s",
                "root_cause_hypothesis": "r",
                "suggested_fix": "f",
                "cluster_key": "c",
            }
        )
        data = _parse_review_response(raw, ValueError("x"))
        assert data["severity"] == "medium"

    def test_invalid_category_normalized(self):
        raw = json.dumps(
            {
                "severity": "low",
                "category": "weird",
                "summary": "s",
                "root_cause_hypothesis": "r",
                "suggested_fix": "f",
                "cluster_key": "c",
            }
        )
        data = _parse_review_response(raw, ValueError("x"))
        assert data["category"] == "transient"

    def test_garbage_returns_fallback(self):
        data = _parse_review_response("not json", ValueError("original"))
        assert "severity" in data
        assert "category" in data

    def test_non_string_returns_fallback(self):
        data = _parse_review_response(None, ValueError("x"))
        assert data["severity"] == "medium"

    def test_missing_fields_get_defaults(self):
        raw = json.dumps({"severity": "low", "category": "transient"})
        data = _parse_review_response(raw, ValueError("x"))
        assert data.get("summary") != ""
        assert data.get("suggested_fix") == ""


# ---------------------------------------------------------------------------
# ErrorReviewer.build_review
# ---------------------------------------------------------------------------


class TestBuildReview:
    def setup_method(self):
        self.r = ErrorReviewer(maxsize=10, ttl=60)

    def test_happy_path(self):
        good = json.dumps(
            {
                "severity": "high",
                "category": "external_api",
                "summary": "网络超时",
                "root_cause_hypothesis": "VPN 不稳定",
                "suggested_fix": "切到 4G 重试",
                "is_recurring": False,
                "cluster_key": "timeout:publish",
            }
        )
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            return_value=good,
        ):
            data = self.r.build_review(
                source="agent_chat",
                location="session:1",
                exc=TimeoutError("net"),
            )
        assert data["severity"] == "high"
        assert data["signature"] is not None

    def test_llm_returns_none_falls_back(self):
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            return_value=None,
        ):
            data = self.r.build_review(
                source="agent_chat",
                location="session:1",
                exc=ValueError("x"),
            )
        assert data["severity"] == "medium"
        assert "unknown:" in data["cluster_key"] or "parse_fail" in data["cluster_key"]

    def test_llm_raises_falls_back(self):
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            side_effect=RuntimeError("provider down"),
        ):
            data = self.r.build_review(
                source="skill_exec",
                location="skill:foo",
                exc=ValueError("x"),
            )
        assert data["severity"] == "medium"

    def test_cache_hit_skips_llm(self):
        good = json.dumps(
            {
                "severity": "high",
                "category": "external_api",
                "summary": "网络超时",
                "root_cause_hypothesis": "VPN",
                "suggested_fix": "切 4G",
                "is_recurring": False,
                "cluster_key": "timeout",
            }
        )
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            return_value=good,
        ):
            data1 = self.r.build_review(
                source="agent_chat", location="session:1", exc=ValueError("net")
            )
        # 第二次不调 LLM
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked"
        ) as mock_llm:
            data2 = self.r.build_review(
                source="agent_chat", location="session:1", exc=ValueError("net")
            )
        mock_llm.assert_not_called()
        assert data1["severity"] == data2["severity"]


# ---------------------------------------------------------------------------
# ErrorReviewer.review_and_store_async (with in-memory SQLite)
# ---------------------------------------------------------------------------


class TestReviewAndStoreAsync:
    def setup_method(self):
        from src.shared.database import Base, engine
        # 确保表已建
        Base.metadata.create_all(bind=engine)
        # 清空
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM error_reviews"))
            conn.commit()
        self.r = ErrorReviewer(maxsize=10, ttl=60)

    def test_first_call_inserts_new_row(self):
        good = json.dumps(
            {
                "severity": "medium",
                "category": "transient",
                "summary": "首次失败",
                "root_cause_hypothesis": "r",
                "suggested_fix": "f",
                "is_recurring": False,
                "cluster_key": "test:first",
            }
        )
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            return_value=good,
        ):
            import asyncio
            row_id = asyncio.run(
                self.r.review_and_store_async(
                    source="worker_task",
                    location="task:abc",
                    exc=ValueError("boom"),
                )
            )
        assert row_id is not None
        from src.shared.database import SessionLocal
        from src.memory.error_review_model import ErrorReview
        with SessionLocal() as sess:
            row = sess.query(ErrorReview).filter_by(id=row_id).first()
        assert row is not None
        assert row.occurrence_count == 1
        assert row.severity == "medium"

    def test_duplicate_call_increments_count(self):
        good = json.dumps(
            {
                "severity": "medium",
                "category": "transient",
                "summary": "s",
                "root_cause_hypothesis": "r",
                "suggested_fix": "f",
                "is_recurring": False,
                "cluster_key": "test:dup",
            }
        )
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            return_value=good,
        ):
            import asyncio
            id1 = asyncio.run(
                self.r.review_and_store_async(
                    source="agent_chat",
                    location="session:1",
                    exc=ValueError("same"),
                )
            )
            id2 = asyncio.run(
                self.r.review_and_store_async(
                    source="agent_chat",
                    location="session:1",
                    exc=ValueError("same"),
                )
            )
        assert id1 == id2
        from src.shared.database import SessionLocal
        from src.memory.error_review_model import ErrorReview
        with SessionLocal() as sess:
            row = sess.query(ErrorReview).filter_by(id=id1).first()
        assert row.occurrence_count == 2

    def test_different_signature_inserts_separate_row(self):
        good = json.dumps(
            {
                "severity": "low",
                "category": "transient",
                "summary": "s",
                "root_cause_hypothesis": "r",
                "suggested_fix": "f",
                "is_recurring": False,
                "cluster_key": "k",
            }
        )
        with patch(
            "src.agent.error_reviewer.llm_client.chat_completion_tracked",
            return_value=good,
        ):
            import asyncio
            id1 = asyncio.run(
                self.r.review_and_store_async(
                    source="agent_chat", location="session:1", exc=ValueError("a")
                )
            )
            id2 = asyncio.run(
                self.r.review_and_store_async(
                    source="skill_exec",
                    location="skill:x",
                    exc=ValueError("b"),
                )
            )
        assert id1 != id2
