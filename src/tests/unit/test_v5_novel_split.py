# -*- coding: utf-8 -*-
"""
Tests for V5-1 L1 LLM 拆镜 (novel_schemas + novel_splitter)。

覆盖:
  - 工具函数: calc_max_segments (5 cases)
  - DialogueLine: emotion 降级
  - ScenePlan: duration 约束 (L1 业务校验)
  - NovelSplit: 角色白名单 (L1 业务校验)
  - split_novel: 短输入拒绝、调用 LLM 异常传播

注: split_novel 的 end-to-end 真实 LLM 调用不在单测里跑（耗时长 + 外部依赖），
   由 scripts/_d1_smoke_test.py 单独跑（见后续）。
"""

import pytest
from unittest.mock import patch, MagicMock

from src.content_factory.novel_schemas import (
    DialogueLine,
    ScenePlan,
    NovelSplit,
    calc_max_segments,
    SCENE_DURATION_MIN,
    SCENE_DURATION_MAX,
    CHARS_PER_SEGMENT,
    MAX_SEGMENTS_MIN,
    MAX_SEGMENTS_MAX,
)
from src.content_factory.novel_splitter import (
    NovelSplitError,
    NovelSplitSchemaError,
    NovelSplitBusinessError,
    NovelSplitUnavailableError,
    split_novel,
    PROMPT_VARIANTS,
)


# ---------------------------------------------------------------------------
# calc_max_segments
# ---------------------------------------------------------------------------


class TestCalcMaxSegments:
    def test_very_short_text_clamps_to_min(self):
        """100 字 → 2 段 (计算) → max(4, 2) = 4 (下限保护)"""
        assert calc_max_segments(100) == MAX_SEGMENTS_MIN

    def test_short_text_clamps_to_min(self):
        assert calc_max_segments(500) == MAX_SEGMENTS_MIN  # 500//250=2

    def test_medium_text(self):
        assert calc_max_segments(2000) == 8  # 2000//250=8

    def test_long_text_clamps_to_max(self):
        assert calc_max_segments(5000) == MAX_SEGMENTS_MAX  # min(15, 20)=15

    def test_very_long_text_clamps_to_max(self):
        assert calc_max_segments(100000) == MAX_SEGMENTS_MAX

    def test_boundary_at_1000_chars(self):
        # 1000//250=4, 正好 = 下限
        assert calc_max_segments(1000) == 4

    def test_boundary_at_3750_chars(self):
        # 3750//250=15, 正好 = 上限
        assert calc_max_segments(3750) == MAX_SEGMENTS_MAX


# ---------------------------------------------------------------------------
# DialogueLine
# ---------------------------------------------------------------------------


class TestDialogueLine:
    def test_basic(self):
        d = DialogueLine(speaker="林晚", text="你好", emotion="happy")
        assert d.speaker == "林晚"
        assert d.text == "你好"
        assert d.emotion == "happy"

    def test_invalid_emotion_falls_back_to_neutral(self):
        """ship.md A.4.2 L1: 情绪不在白名单时降级不抛错。"""
        d = DialogueLine(speaker="x", text="有效长度", emotion="furious")
        assert d.emotion == "neutral"

    def test_empty_emotion_falls_back_to_neutral(self):
        d = DialogueLine(speaker="x", text="有效长度", emotion="")
        assert d.emotion == "neutral"

    def test_text_too_short_rejected(self):
        with pytest.raises(Exception):  # ValidationError
            DialogueLine(speaker="x", text="a")

    def test_text_too_long_rejected(self):
        with pytest.raises(Exception):
            DialogueLine(speaker="x", text="x" * 200)


# ---------------------------------------------------------------------------
# ScenePlan (L1 业务校验)
# ---------------------------------------------------------------------------


class TestScenePlan:
    def _make_valid_scene(self, **overrides):
        defaults = dict(
            scene_id=0,
            narration="旁白文本" * 3,
            dialogue=[],
            first_frame_prompt="a" * 30,
            last_frame_prompt="b" * 30,
            duration_seconds=4.0,
        )
        defaults.update(overrides)
        return ScenePlan(**defaults)

    def test_valid_scene(self):
        s = self._make_valid_scene()
        assert s.duration_seconds == 4.0
        assert s.background_style == "dream_shaper_xl"  # 默认

    def test_duration_below_min_rejected(self):
        with pytest.raises(Exception):
            self._make_valid_scene(duration_seconds=SCENE_DURATION_MIN - 0.5)

    def test_duration_above_max_rejected(self):
        with pytest.raises(Exception):
            self._make_valid_scene(duration_seconds=SCENE_DURATION_MAX + 0.5)

    def test_duration_at_boundaries_accepted(self):
        s_min = self._make_valid_scene(duration_seconds=SCENE_DURATION_MIN)
        s_max = self._make_valid_scene(duration_seconds=SCENE_DURATION_MAX)
        assert s_min.duration_seconds == SCENE_DURATION_MIN
        assert s_max.duration_seconds == SCENE_DURATION_MAX

    def test_keyframe_prompt_too_short_rejected(self):
        with pytest.raises(Exception):
            self._make_valid_scene(first_frame_prompt="x" * 10)

    def test_keyframe_prompt_too_long_rejected(self):
        with pytest.raises(Exception):
            self._make_valid_scene(first_frame_prompt="x" * 300)


# ---------------------------------------------------------------------------
# NovelSplit (角色白名单)
# ---------------------------------------------------------------------------


class TestNovelSplit:
    def _make_valid_split(self, **overrides):
        defaults = dict(
            novel_title="测试",
            characters=["林晚", "陈默"],
            scenes=[
                ScenePlan(
                    scene_id=0,
                    narration="场景一" * 3,
                    dialogue=[DialogueLine(speaker="林晚", text="对白测试")],
                    first_frame_prompt="a" * 30,
                    last_frame_prompt="b" * 30,
                    duration_seconds=4.0,
                ),
            ],
        )
        defaults.update(overrides)
        return NovelSplit(**defaults)

    def test_valid_split(self):
        ns = self._make_valid_split()
        assert ns.novel_title == "测试"
        assert len(ns.scenes) == 1
        assert ns.total_duration_seconds == 4.0

    def test_total_duration_auto_computed(self):
        scenes = [
            ScenePlan(
                scene_id=i, narration=f"旁白 {i}" * 5,
                dialogue=[], first_frame_prompt="a" * 30,
                last_frame_prompt="b" * 30, duration_seconds=4.0,
            )
            for i in range(3)
        ]
        ns = NovelSplit(novel_title="x", characters=[], scenes=scenes)
        assert ns.total_duration_seconds == 12.0

    def test_dialogue_speaker_not_in_whitelist_rejected(self):
        """ship.md A.4.2 L1: dialogue 角色必须 ∈ characters 白名单。"""
        with pytest.raises(Exception):  # ValidationError wrapping ValueError
            self._make_valid_split(
                characters=["林晚"],
                scenes=[
                    ScenePlan(
                        scene_id=0, narration="场景一" * 3,
                        dialogue=[DialogueLine(speaker="陌生人", text="对白测试")],
                        first_frame_prompt="a" * 30, last_frame_prompt="b" * 30,
                        duration_seconds=4.0,
                    ),
                ],
            )

    def test_dialogue_speaker_in_whitelist_accepted(self):
        ns = self._make_valid_split(
            characters=["林晚", "陈默"],
            scenes=[
                ScenePlan(
                    scene_id=0, narration="场景一" * 3,
                    dialogue=[DialogueLine(speaker="陈默", text="陈默说了一句话")],
                    first_frame_prompt="a" * 30, last_frame_prompt="b" * 30,
                    duration_seconds=4.0,
                ),
            ],
        )
        assert len(ns.scenes[0].dialogue) == 1

    def test_empty_characters_skips_whitelist_check(self):
        """空 characters 时不检查 (Whitelist 检查跳过)"""
        # 不应该有 dialogue,否则跳过
        ns = self._make_valid_split(
            characters=[],
            scenes=[
                ScenePlan(
                    scene_id=0, narration="场景一" * 3, dialogue=[],
                    first_frame_prompt="a" * 30, last_frame_prompt="b" * 30,
                    duration_seconds=4.0,
                ),
            ],
        )
        assert len(ns.characters) == 0


# ---------------------------------------------------------------------------
# split_novel (输入校验)
# ---------------------------------------------------------------------------


class TestSplitNovelInput:
    def test_empty_text_raises(self):
        with pytest.raises(NovelSplitError, match="太短"):
            split_novel("", novel_title="x")

    def test_short_text_raises(self):
        with pytest.raises(NovelSplitError, match="太短"):
            split_novel("太短", novel_title="x")

    def test_whitespace_text_raises(self):
        with pytest.raises(NovelSplitError, match="太短"):
            split_novel("    \n  \t  ", novel_title="x")

    def test_50_chars_accepted_min_length(self):
        """>= 50 字符通过 input 校验（实际 LLM 调用不在单测范围）。"""
        # 50 字通过输入检查后会调 LLM，mock 返回 None 让 NovelSplitUnavailableError
        with patch.object(__import__("src.content_factory.novel_splitter", fromlist=["llm_client"]).llm_client,
                          "chat_completion_tracked", return_value=None):
            with pytest.raises(NovelSplitUnavailableError):
                split_novel("a" * 50, novel_title="test")


# ---------------------------------------------------------------------------
# Prompt 变体完整性
# ---------------------------------------------------------------------------


class TestPromptVariants:
    def test_three_variants(self):
        assert len(PROMPT_VARIANTS) == 3

    def test_v2_has_example(self):
        assert "示例" in PROMPT_VARIANTS[1]

    def test_v3_is_simplified(self):
        """v3 是简化版（更短 prompt）"""
        assert len(PROMPT_VARIANTS[2]) < len(PROMPT_VARIANTS[0])
