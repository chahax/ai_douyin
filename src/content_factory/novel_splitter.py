# -*- coding: utf-8 -*-
"""
src/content_factory/novel_splitter.py — V5-1 L1 LLM 拆镜

设计依据:
  - docs/design/v5-pure-video-pipeline.md §3 (L1 拆镜)
  - ship.md 附录 A.4.1 (L0 schema 校验) + A.4.2 (L1 业务校验) + A.5.2 (retry 参数变体)
  - 复用 I-4 (chat_completion_tracked) + I-3 (Pydantic schema 校验)
  - 复用 I-2 (容错模式：失败重试 + 异常分类)

流程:
  1. LLM 调用 (用 I-4 chat_completion_tracked, 自动记录 token/cost/cache)
  2. JSON 解析 + Pydantic schema 校验 (L0 失败 → ValidationError, 不重试)
  3. 业务规则校验 (段间连贯性、角色白名单 - L1 失败 → 触发 retry 变体)
  4. retry 3 次 (A.5.2): 默认 prompt → 加示例 prompt → 切备选模型 prompt

输入:
  - novel_text: str
  - novel_title: Optional[str]
  - style: str (默认 "dream_shaper_xl")

输出:
  - NovelSplit Pydantic model (含 novel_title, characters, scenes, total_duration_seconds)
  - 异常: 3 次 retry 全失败 → 抛 NovelSplitUnavailableError
"""

from __future__ import annotations

import json
import time
from typing import Optional

from pydantic import ValidationError

from src.content_factory.novel_schemas import (
    NovelSplit,
    calc_max_segments,
)
from src.shared.llm_client import llm_client
from src.shared.logger import logger


# -------------------------------------------------------------------
# 异常类（I-2 风格的纯增量模块）
# -------------------------------------------------------------------


class NovelSplitError(Exception):
    """novel_splitter 异常的基类。"""
    error_class: str = "UNKNOWN"

    def __init__(self, message: str, *, attempts: int = 0, last_error: str = ""):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class NovelSplitUnavailableError(NovelSplitError):
    """3 次 retry 全失败后抛出。"""
    error_class = "UNAVAILABLE"


class NovelSplitSchemaError(NovelSplitError):
    """L0 schema 错误 (Pydantic 校验失败) — 不重试。"""
    error_class = "SCHEMA"


class NovelSplitBusinessError(NovelSplitError):
    """L1 业务规则违反 (角色不在白名单等) — 触发 retry。"""
    error_class = "BUSINESS"


# -------------------------------------------------------------------
# Prompt 模板 + 变体
# -------------------------------------------------------------------


# 变体 1: 默认 prompt
PROMPT_V1 = """你是一位专业的短视频分镜师。请将以下小说片段拆成 {max_segments} 个 3-5 秒的镜头。

## 小说标题
{title}

## 小说片段
{text}

## 输出要求（严格 JSON 格式）
{{
  "novel_title": "提取或推断的标题",
  "characters": ["角色1", "角色2"],
  "scenes": [
    {{
      "scene_id": 0,
      "narration": "这段场景的旁白文本（30-200 字）",
      "dialogue": [
        {{"speaker": "角色名", "text": "对白（5-100 字）", "emotion": "neutral"}}
      ],
      "first_frame_prompt": "DreamShaper XL 风格的英文 prompt，描述场景开始画面（20-200 字符）",
      "last_frame_prompt": "DreamShaper XL 风格的英文 prompt，描述场景结束画面（20-200 字符）",
      "duration_seconds": 4.0
    }}
  ]
}}

## 硬约束
- duration_seconds 必须在 3.0-5.0 之间
- dialogue 角色必须在 characters 列表中
- first_frame_prompt / last_frame_prompt 必须呼应（同一个场景的视觉延续）
- 输出只能有 JSON，不能有 markdown 代码块或其他说明
"""


# 变体 2: 加 1 个示例 + "避免常见错误" 提示
PROMPT_V2 = PROMPT_V1 + """

## 示例
{{
  "novel_title": "林晚的早晨",
  "characters": ["林晚", "陈默"],
  "scenes": [
    {{
      "scene_id": 0,
      "narration": "清晨的阳光透过窗帘，林晚站在窗前，深吸一口气。",
      "dialogue": [],
      "first_frame_prompt": "anime girl Lin Wan standing by a sunlit window, morning light, soft focus, DreamShaper XL",
      "last_frame_prompt": "anime girl Lin Wan turning towards camera, sun rays through curtain, close-up, DreamShaper XL",
      "duration_seconds": 4.0
    }}
  ]
}}

## 避免错误
- 不要把对话塞进 narration（对话走 dialogue 列表）
- duration 不要用 0 / 1 / 10 这种极端值
- character 名不要带空格或特殊符号
"""


# 变体 3: 切备选模型 + 简化 prompt
PROMPT_V3 = """将小说片段拆为 {max_segments} 个 3-5 秒分镜。

小说: {text}

输出 JSON:
{{
  "novel_title": "...",
  "characters": [...],
  "scenes": [
    {{
      "scene_id": 0,
      "narration": "...",
      "dialogue": [{{"speaker": "...", "text": "...", "emotion": "neutral"}}],
      "first_frame_prompt": "...",
      "last_frame_prompt": "...",
      "duration_seconds": 4.0
    }}
  ]
}}

约束: duration 3.0-5.0; characters 必填; first/last prompt 20-200 字符; 仅 JSON 输出。
"""


PROMPT_VARIANTS = [PROMPT_V1, PROMPT_V2, PROMPT_V3]


# -------------------------------------------------------------------
# 主入口
# -------------------------------------------------------------------


def split_novel(
    novel_text: str,
    novel_title: Optional[str] = "",
    style: str = "dream_shaper_xl",
    caller: str = "v5_novel_split",
    use_cache: bool = True,
) -> NovelSplit:
    """
    L1 拆镜主入口。

    Args:
        novel_text: 小说文本（>= 100 字）
        novel_title: 可选标题（空则让 LLM 抽取）
        style: 视觉风格（DreamShaper XL / AnythingXL / RealVisXL）
        caller: I-4 caller tag（用于 LLM 限流豁免判断 + 计量统计）
        use_cache: I-4 缓存开关

    Returns:
        NovelSplit Pydantic model

    Raises:
        NovelSplitSchemaError: L0 schema 失败（不重试，code bug）
        NovelSplitBusinessError: L1 业务失败（被 retry 内部吸收）
        NovelSplitUnavailableError: 3 次 retry 全失败
    """
    if not novel_text or len(novel_text.strip()) < 50:
        raise NovelSplitError(f"novel_text 太短: {len(novel_text)} chars (min 50)")

    max_segments = calc_max_segments(len(novel_text))
    title_for_prompt = novel_title or "(无标题，请根据内容推断)"

    last_error_msg = ""

    for attempt_idx, prompt_template in enumerate(PROMPT_VARIANTS, start=1):
        prompt = prompt_template.format(
            max_segments=max_segments,
            title=title_for_prompt,
            text=novel_text,
        )

        messages = [
            {"role": "system", "content": "你只输出严格 JSON，不输出任何其他文字。"},
            {"role": "user", "content": prompt},
        ]

        logger.info(
            f"[v5 split] attempt {attempt_idx}/3, max_segments={max_segments}, "
            f"text_len={len(novel_text)}, style={style}"
        )

        # 调 LLM（I-4 治理: 限流 + 缓存 + 计量 + 记录）
        raw = llm_client.chat_completion_tracked(
            messages,
            caller=caller,
            temperature=0.7,
            json_mode=True,
            use_cache=use_cache,
        )

        if not raw:
            last_error_msg = f"LLM 返回空 (attempt {attempt_idx})"
            logger.warning(f"[v5 split] {last_error_msg}")
            continue  # 进入下一个变体

        # JSON 解析
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error_msg = f"JSON parse failed: {exc}"
            logger.warning(f"[v5 split] {last_error_msg}")
            continue  # 可能是 LLM 飘了, retry 变体

        # 强制 title
        if not data.get("novel_title") and novel_title:
            data["novel_title"] = novel_title

        # L0 schema 校验（一次性，不重试）
        try:
            result = NovelSplit.model_validate(data)
            logger.info(
                f"[v5 split] success: {len(result.scenes)} scenes, "
                f"{result.total_duration_seconds}s total, "
                f"{len(result.characters)} chars"
            )
            return result
        except ValidationError as exc:
            # Pydantic ValidationError 包含字段错 (e.g. duration_seconds=10 超出范围)
            # 这种通常是 prompt 飘了导致 LLM 输出格式错 (retry prompt 变体可能修复)
            last_error_msg = f"schema validation: {exc.errors()[0]['msg']}"
            logger.warning(f"[v5 split] L0 schema 失败: {last_error_msg}")
            continue

        # 不可达这里
    # 全部 retry 失败
    raise NovelSplitUnavailableError(
        f"3 次 retry 全失败: {last_error_msg}",
        attempts=len(PROMPT_VARIANTS),
        last_error=last_error_msg,
    )
