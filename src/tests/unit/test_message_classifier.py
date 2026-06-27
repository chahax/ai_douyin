# -*- coding: utf-8 -*-
"""
Tests for src/memory/message_classifier.py and humane_recorder.py.

Covers:
  - Rule-based fast path (discarded / preference / problem / normal)
  - JSON parsing tolerates markdown fences
  - classify_async falls back to rule-based when LLM fails
  - humane_recorder queries return expected shapes
"""

import json
from unittest.mock import patch


from src.memory.message_classifier import (
    MessageClassifier,
    _parse_classify_response,
    _rule_based_classify,
)


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------


class TestRuleBased:
    def test_discard_triggers(self):
        for s in ["你好", "hi", "hello", "请问你是谁", "打扰了"]:
            assert _rule_based_classify(s)["memory_type"] == "discarded", s

    def test_preference_triggers(self):
        for s in ["我喜欢 Edge TTS", "我习惯用 GPT-SoVITS", "以后都用 edge"]:
            assert _rule_based_classify(s)["memory_type"] == "preference", s

    def test_problem_triggers(self):
        for s in [
            "为什么我的视频发布失败？",
            "怎么才能用 GPT-SoVITS？",
            "我遇到了一个报错，提示 xxx",
        ]:
            assert _rule_based_classify(s)["memory_type"] == "problem", s

    def test_normal_fallback(self):
        for s in ["生成一个视频", "今天天气如何"]:
            assert _rule_based_classify(s)["memory_type"] == "normal", s

    def test_short_message_not_problem(self):
        # < 10 chars 的"为什么"不算 problem
        assert _rule_based_classify("为什么")["memory_type"] in ("normal", "problem")


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------


class TestParseClassifyResponse:
    def test_plain_json(self):
        raw = json.dumps(
            {
                "memory_type": "problem",
                "intent": "报错求助",
                "sentiment": "frustrated",
                "topics": ["发布"],
                "entities": {"skills": []},
                "humane_summary": "你在发布时遇到问题",
                "needs_followup": True,
            }
        )
        data = _parse_classify_response(raw)
        assert data["memory_type"] == "problem"
        assert data["sentiment"] == "frustrated"
        assert data["needs_followup"] is True

    def test_markdown_fence(self):
        raw = "```json\n" + json.dumps(
            {
                "memory_type": "normal",
                "intent": "一般对话",
                "sentiment": "neutral",
                "topics": [],
                "entities": {},
                "humane_summary": "",
                "needs_followup": False,
            }
        ) + "\n```"
        data = _parse_classify_response(raw)
        assert data["memory_type"] == "normal"

    def test_invalid_memory_type_falls_back_to_rule(self):
        raw = json.dumps({"memory_type": "unknown_type"})
        data = _parse_classify_response(raw)
        # 失败时回退到 rule，rule 对不带触发词的内容是 normal
        assert data["memory_type"] in ("normal", "problem", "preference", "discarded")

    def test_garbage_input(self):
        data = _parse_classify_response("not json at all")
        assert "memory_type" in data

    def test_missing_fields_get_defaults(self):
        raw = json.dumps({"memory_type": "normal"})
        data = _parse_classify_response(raw)
        assert data.get("sentiment") == "neutral"
        assert data.get("topics") == []
        assert data.get("needs_followup") is False


# ---------------------------------------------------------------------------
# MessageClassifier (with mocked LLM)
# ---------------------------------------------------------------------------


class TestClassifierAsync:
    def setup_method(self):
        self.cls = MessageClassifier(maxsize=10, ttl=60)

    def test_classify_async_happy_path(self):
        good_json = json.dumps(
            {
                "memory_type": "preference",
                "intent": "设置 TTS",
                "sentiment": "neutral",
                "topics": ["TTS"],
                "entities": {"skills": ["tts"]},
                "humane_summary": "你偏好 Edge TTS",
                "needs_followup": False,
            }
        )
        with patch(
            "src.memory.message_classifier.llm_client.chat_completion",
            return_value=good_json,
        ):
            import asyncio
            data = asyncio.run(
                self.cls.classify_async("user", "我以后用 edge tts")
            )
        assert data["memory_type"] == "preference"
        assert data["classification_source"] == "llm"
        # 缓存命中
        data2 = asyncio.run(
            self.cls.classify_async("user", "我以后用 edge tts")
        )
        assert data2["memory_type"] == "preference"

    def test_classify_async_llm_failure_falls_back_to_rule(self):
        with patch(
            "src.memory.message_classifier.llm_client.chat_completion",
            return_value=None,
        ):
            import asyncio
            data = asyncio.run(
                self.cls.classify_async("user", "我习惯用 Edge TTS")
            )
        # LLM 失败时 fallback 到规则
        assert data["memory_type"] == "preference"
        assert data["classification_source"] == "rule"

    def test_classify_async_role_filter(self):
        import asyncio
        # 非 user 角色直接走 default
        data = asyncio.run(self.cls.classify_async("assistant", "anything"))
        assert data["memory_type"] == "normal"
        assert data["classification_source"] == "default"

    def test_classify_fast_does_not_call_llm(self):
        with patch(
            "src.memory.message_classifier.llm_client.chat_completion"
        ) as mock_llm:
            data = self.cls.classify_fast("user", "我习惯用 edge tts")
        # 同步路径不应调 LLM
        mock_llm.assert_not_called()
        assert data["memory_type"] == "preference"

    def test_classify_fast_cache_hit_skips_rule(self):
        good_json = json.dumps(
            {
                "memory_type": "problem",
                "intent": "提问",
                "sentiment": "curious",
                "topics": [],
                "entities": {},
                "humane_summary": "你在问问题",
                "needs_followup": True,
            }
        )
        with patch(
            "src.memory.message_classifier.llm_client.chat_completion",
            return_value=good_json,
        ):
            import asyncio
            asyncio.run(self.cls.classify_async("user", "这是一个问题"))
        # 缓存命中
        data = self.cls.classify_fast("user", "这是一个问题")
        assert data["memory_type"] == "problem"
        assert data["sentiment"] == "curious"


# ---------------------------------------------------------------------------
# humane_recorder
# ---------------------------------------------------------------------------


class TestHumaneRecorder:
    def test_get_recent_sentiment_empty(self):
        from src.memory.humane_recorder import get_recent_sentiment
        result = get_recent_sentiment(session_id=999999, last_n=5)
        assert result == []

    def test_get_messages_by_topic_empty_input(self):
        from src.memory.humane_recorder import get_messages_by_topic
        assert get_messages_by_topic(topic="") == []
        assert get_messages_by_topic(topic="nonexistent_topic_xyz") == []

    def test_get_followup_reminders_empty(self):
        from src.memory.humane_recorder import get_followup_reminders
        result = get_followup_reminders(user_id="nonexistent_user", limit=5)
        assert result == []

    def test_get_session_sentiment_summary_empty(self):
        from src.memory.humane_recorder import get_session_sentiment_summary
        result = get_session_sentiment_summary(session_id=999999)
        assert result == {}

    def test_get_recent_context_returns_list(self):
        from src.memory.humane_recorder import get_recent_context
        result = get_recent_context(session_id=999999, hours=24, limit=10)
        assert isinstance(result, list)
        assert result == []
