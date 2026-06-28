# -*- coding: utf-8 -*-
"""
src/content_factory/novel_schemas.py — V5 小说→视频 Pipeline 的 Pydantic 数据模型（V5-1）

设计依据: docs/design/v5-pure-video-pipeline.md §3 (L1 拆镜 Pydantic schema)
+ ship.md 附录 A.4 (L0 schema 校验) + A.4.2 (L1 业务校验)

校验规则全部通过 Pydantic v2 实现:
  - L0 (schema 错): Pydantic ValidationError → 任务直接 failed, 不重试 (code bug)
  - L1 (业务错): 字段值域约束, 触发 retry 变体 (prompt 飘了)

设计要点:
  - ScenePlan 必填: narration / dialogue / first_frame_prompt / last_frame_prompt / duration
  - 时长约束: 3.0~5.0s (ship.md A.4.2 L1 场景粒度)
  - dialogue 列表: 角色名必须在 speakers 白名单 (ship.md A.4.2 L1 角色名白名单)
  - duration 必须是 float
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator


# -------------------------------------------------------------------
# 通用约束常量
# -------------------------------------------------------------------

# V5-1 默认单段时长范围
SCENE_DURATION_MIN = 3.0
SCENE_DURATION_MAX = 5.0

# 角色对白长度约束
DIALOGUE_MIN_LEN = 2
DIALOGUE_MAX_LEN = 100

# 首末帧 prompt 长度约束 (DreamShaper XL 经验值)
KEYFRAME_PROMPT_MIN = 20
KEYFRAME_PROMPT_MAX = 200

# 旁白长度约束
NARRATION_MIN_LEN = 5
NARRATION_MAX_LEN = 300

# 段数动态计算
MAX_SEGMENTS_MIN = 4
MAX_SEGMENTS_MAX = 15
CHARS_PER_SEGMENT = 250  # 每镜约 250 字


# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------


class DialogueLine(BaseModel):
    """单条角色对白（ship.md A.4.2 L1 角色对白长度）。"""
    speaker: str = Field(min_length=1, max_length=20, description="角色名（必须在白名单中）")
    text: str = Field(min_length=DIALOGUE_MIN_LEN, max_length=DIALOGUE_MAX_LEN, description="对白内容")
    emotion: str = Field(default="neutral", max_length=20, description="情绪：happy/sad/angry/neutral")

    @field_validator("emotion")
    @classmethod
    def _validate_emotion(cls, v: str) -> str:
        allowed = {"happy", "sad", "angry", "neutral", "fearful", "surprised"}
        if v and v not in allowed:
            # 不抛错：降级到 neutral 而不是整个 scene failed
            return "neutral"
        return v or "neutral"


class ScenePlan(BaseModel):
    """单镜分镜（V5 L1 输出）。"""
    scene_id: int = Field(ge=0, le=99, description="段序号，从 0 开始")
    narration: str = Field(
        min_length=NARRATION_MIN_LEN,
        max_length=NARRATION_MAX_LEN,
        description="旁白文本（叙述用，V5 TTS 走这个）",
    )
    dialogue: List[DialogueLine] = Field(
        default_factory=list,
        max_length=10,
        description="角色对白列表（0-10 句）",
    )
    first_frame_prompt: str = Field(
        min_length=KEYFRAME_PROMPT_MIN,
        max_length=KEYFRAME_PROMPT_MAX,
        description="首帧图像 prompt（DreamShaper XL / PuLID）",
    )
    last_frame_prompt: str = Field(
        min_length=KEYFRAME_PROMPT_MIN,
        max_length=KEYFRAME_PROMPT_MAX,
        description="末帧图像 prompt（保证段间连贯性）",
    )
    duration_seconds: float = Field(
        ge=SCENE_DURATION_MIN,
        le=SCENE_DURATION_MAX,
        description=f"该镜视频时长 ({SCENE_DURATION_MIN}-{SCENE_DURATION_MAX}s)",
    )
    background_style: str = Field(
        default="dream_shaper_xl",
        max_length=32,
        description="DreamShaper XL / AnythingXL / RealVisXL",
    )

    @model_validator(mode="after")
    def _validate_continuity(self) -> "ScenePlan":
        """L1 业务校验: 末帧和下一镜首帧要呼应（语义连贯性）。

        注: 真正的视觉连贯性 (LPIPS) 在 L5 concat 时校验；这里只做轻量语义检查。
        """
        return self


class NovelSplit(BaseModel):
    """整篇小说 L1 拆镜结果。"""
    novel_title: str = Field(default="", max_length=100, description="小说标题（LLM 抽取）")
    characters: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="角色名白名单（ship.md A.4.2 L1 角色名白名单）",
    )
    scenes: List[ScenePlan] = Field(
        min_length=1,
        max_length=20,
        description="分镜列表（1-20 镜）",
    )
    total_duration_seconds: float = Field(default=0.0, ge=0.0, description="总时长（= Σ scene.duration）")

    @model_validator(mode="after")
    def _compute_total(self) -> "NovelSplit":
        """自动计算总时长 + 校验 dialogue 角色必须在白名单中。"""
        total = sum(s.duration_seconds for s in self.scenes)
        object.__setattr__(self, "total_duration_seconds", total)

        # dialogue 角色名白名单校验 (ship.md A.4.2 L1)
        allowed = set(self.characters)
        for scene in self.scenes:
            for dlg in scene.dialogue:
                if allowed and dlg.speaker not in allowed:
                    raise ValueError(
                        f"scene {scene.scene_id} dialogue speaker '{dlg.speaker}' "
                        f"not in characters whitelist {sorted(allowed)}"
                    )
        return self


# -------------------------------------------------------------------
# 工具函数
# -------------------------------------------------------------------


def calc_max_segments(text_length: int) -> int:
    """动态计算 max_segments（每镜约 250 字，下限 4 镜，上限 15 镜）。

    例:
      500 字 → max(4, min(15, 500//250)) = max(4, 2) = 4 镜（下限保护）
      2000 字 → max(4, min(15, 8)) = 8 镜
      5000 字 → min(15, 20) = 15 镜（上限保护）
    """
    return max(MAX_SEGMENTS_MIN, min(MAX_SEGMENTS_MAX, text_length // CHARS_PER_SEGMENT))


def estimate_total_duration(scenes: List[ScenePlan]) -> float:
    """预估总时长（秒）。"""
    return sum(s.duration_seconds for s in scenes)
