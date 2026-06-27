# -*- coding: utf-8 -*-
"""
src/memory/message_classifier.py — LLM 驱动的消息分类器

替代 src/memory/problem_memory.py:182-220 的关键词正则分类。
设计：
  - 同步快路径 `classify_fast` 给 add_message 用（不阻塞对话）
  - 异步慢路径 `classify_async` 调 LLM 做精细分类（带 metadata）
  - 缓存避免重复调 LLM
  - LLM 失败时 fallback 到原有规则

LLM 输出 JSON：
  {
    "memory_type": "preference" | "problem" | "discarded" | "normal",
    "intent": "<=10 chars",
    "sentiment": "positive" | "neutral" | "frustrated" | "curious" | "appreciative",
    "topics": ["<=3 中文标签"],
    "entities": {"skills": [], "videos": [], "people": []},
    "humane_summary": "<第二人称一句话复述>",
    "needs_followup": true | false
  }
"""

import asyncio
import hashlib
import json
import re
from typing import Any

from src.shared.cache import TTLCache
from src.shared.llm_client import llm_client
from src.shared.logger import logger


CLASSIFY_PROMPT = """你是用户消息分类助手。给定一条用户消息，输出严格 JSON：

{{
  "memory_type": "preference" | "problem" | "discarded" | "normal",
  "intent": "<=10字中文意图>",
  "sentiment": "positive" | "neutral" | "frustrated" | "curious" | "appreciative",
  "topics": ["<=3 个中文标签"],
  "entities": {{"skills": [], "videos": [], "people": []}},
  "humane_summary": "<第二人称一句话复述用户原话的核心信息，便于日后回顾>",
  "needs_followup": true | false
}}

判定规则：
- preference: 用户表达"我喜欢 / 我习惯 / 默认 / 以后用"等偏好
- problem:    用户提问、报错、求助、表达不满、要求修复
- discarded:  纯寒暄（你好/hi）、无关闲聊、明确测试性输入
- normal:     其他有效对话

消息内容：
\"\"\"
{content}
\"\"\"

只输出 JSON，不要任何解释。"""


# ---------------------------------------------------------------------------
# 规则 fallback（从原 _classify_message 复制）
# ---------------------------------------------------------------------------

_DISCARD_TRIGGERS = (
    "你好", "请问你是谁", "你是做什么的", "你能做什么", "hi", "hello",
    "帮我写个", "画个", "生成一个图片", "你好呀", "打扰了",
)
# 偏好触发词：覆盖「身份 / 风格 / 格式 / 禁忌」四类。
# 注意顺序——更具体的（"我是理科生"、"请用 X 风格"）放在通用词前面以优先命中。
_PREFERENCE_TRIGGERS = (
    # 身份 / 背景
    "我是理科生", "我是工科", "我是文科", "我是程序员", "我是开发",
    "我是产品", "我是运营", "我是设计", "我是学生", "我是工程师",
    "我是 ",  # 「我是 X」类，留空格避免误匹配「我是不想」
    # 风格 / 语气
    "请客观", "需要客观", "要客观", "请简洁", "需要简洁", "要简洁",
    "回复时", "回答时", "回答要", "回复要", "回答请", "回复请",
    "需要你", "希望你",
    # 格式 / 语言
    "请用中文", "用中文", "用英文", "给代码", "带示例", "给证据",
    # 禁忌
    "别用", "不要用", "不要加", "不要 emoji", "别加 emoji",
    # 老的创作偏好触发词（兼容既有数据）
    "我喜欢", "我习惯用", "偏好", "设置", "默认用", "我比较喜欢",
    "我的风格是", "我更倾向", "每次都", "以后用", "以后都",
)
_PROBLEM_TRIGGERS = (
    "怎么", "如何", "为什么", "是什么", "请问", "帮我",
    "解决", "报错", "问题", "错误", "不行", "失败",
    "卡在", "一直", "无法", "不工作", "出了什么问题",
)


def _rule_based_classify(content: str) -> dict:
    """关键词规则分类。失败/不确定时返回 'normal'。"""
    content_lower = content.lower().strip()

    for trigger in _DISCARD_TRIGGERS:
        if trigger in content_lower:
            return {
                "memory_type": "discarded",
                "intent": "寒暄",
                "sentiment": "neutral",
                "topics": [],
                "entities": {},
                "humane_summary": "",
                "needs_followup": False,
                "classification_source": "rule",
            }

    for trigger in _PREFERENCE_TRIGGERS:
        if trigger in content_lower:
            return {
                "memory_type": "preference",
                "intent": "设置偏好",
                "sentiment": "neutral",
                "topics": ["偏好设置"],
                "entities": {},
                "humane_summary": f"你表达了偏好：{content[:60]}",
                "needs_followup": False,
                "classification_source": "rule",
            }

    for trigger in _PROBLEM_TRIGGERS:
        if trigger in content_lower and len(content) > 10:
            return {
                "memory_type": "problem",
                "intent": "提问或求助",
                "sentiment": "neutral",
                "topics": [],
                "entities": {},
                "humane_summary": f"你遇到了问题：{content[:60]}",
                "needs_followup": True,
                "classification_source": "rule",
            }

    return {
        "memory_type": "normal",
        "intent": "一般对话",
        "sentiment": "neutral",
        "topics": [],
        "entities": {},
        "humane_summary": "",
        "needs_followup": False,
        "classification_source": "rule",
    }


def _default_for_role(role: str) -> dict:
    if role == "assistant":
        return {
            "memory_type": "normal",
            "intent": "助手回复",
            "sentiment": "neutral",
            "topics": [],
            "entities": {},
            "humane_summary": "",
            "needs_followup": False,
            "classification_source": "default",
        }
    if role == "tool":
        return {
            "memory_type": "normal",
            "intent": "工具结果",
            "sentiment": "neutral",
            "topics": [],
            "entities": {},
            "humane_summary": "",
            "needs_followup": False,
            "classification_source": "default",
        }
    return _rule_based_classify("")


# ---------------------------------------------------------------------------
# 缓存 key
# ---------------------------------------------------------------------------

def _key_for(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# MessageClassifier — 单例
# ---------------------------------------------------------------------------

class MessageClassifier:
    """LLM 驱动的消息分类器，带缓存和规则 fallback。"""

    def __init__(self, *, maxsize: int = 500, ttl: int = 600):
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)

    # -- 同步快路径 -----------------------------------------------------

    def classify_fast(self, role: str, content: str) -> dict:
        """
        同步快路径：缓存命中 → 返回；否则走规则。
        不调 LLM，不阻塞。
        """
        if role != "user":
            return _default_for_role(role)
        key = _key_for(content)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        return _rule_based_classify(content)

    # -- 异步慢路径 -----------------------------------------------------

    async def classify_async(self, role: str, content: str) -> dict:
        """
        异步 LLM 分类。永不抛异常，失败 fallback 到规则。
        """
        if role != "user":
            return _default_for_role(role)
        key = _key_for(content)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            resp = await asyncio.to_thread(
                llm_client.chat_completion,
                [
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
                json_mode=True,
            )
            if not resp:
                raise RuntimeError("LLM 返回为空")
            data = _parse_classify_response(resp)
            data["classification_source"] = "llm"
            self._cache[key] = data
            return data
        except Exception as exc:
            logger.warning("MessageClassifier LLM 失败，fallback 规则: %s", exc)
            return _rule_based_classify(content)

    def clear_cache(self) -> None:
        """测试用。"""
        self._cache.clear()


# ---------------------------------------------------------------------------
# JSON 解析容错
# ---------------------------------------------------------------------------

def _parse_classify_response(resp: Any) -> dict:
    """从 LLM 响应里抽出 JSON dict。兼容 ```json``` 围栏。"""
    if not isinstance(resp, str):
        return _rule_based_classify("")
    s = resp.strip()
    # 去掉 markdown 围栏
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    # 尝试直接 parse
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        # 尝试抓 {...} 子串
        m = re.search(r"\{[^{}]*\}", s, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return _rule_based_classify("")
        else:
            return _rule_based_classify("")

    # 容错：确保必需字段
    if "memory_type" not in data or data["memory_type"] not in (
        "preference", "problem", "discarded", "normal"
    ):
        return _rule_based_classify("")
    for k, default in [
        ("intent", ""),
        ("sentiment", "neutral"),
        ("topics", []),
        ("entities", {}),
        ("humane_summary", ""),
        ("needs_followup", False),
    ]:
        data.setdefault(k, default)
    return data


# 单例
classifier = MessageClassifier()
