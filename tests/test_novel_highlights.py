from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest

from src.content_factory.novel_splitter import (
    NovelSplitError,
    _find_dialogue_emotion_errors,
    _find_dialogue_timing_errors,
    _fit_dialogue_durations,
    _restore_unique_source_dialogue,
    split_novel,
)
from src.content_factory.novel_schemas import NovelSplit
from src.trend_intelligence.novel_highlights import (
    NovelHighlightAnalysisError,
    NovelHighlightAnalyzer,
    analyze_reference_video_highlights,
)


class _HighlightClient:
    def __init__(self, low_quote: tuple[str, str], high_quote: tuple[str, str]):
        self.low_quote = low_quote
        self.high_quote = high_quote

    def chat_completion_tracked(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        if self.high_quote[0] in prompt:
            return json.dumps(
                {
                    "highlights": [
                        {
                            "title": "身份揭晓后的决裂",
                            "start_quote": self.high_quote[0],
                            "end_quote": self.high_quote[1],
                            "setup": "众人逼迫她认错",
                            "conflict": "她要说出真相，对方要维持谎言",
                            "turning_point": "证据被当众拿出",
                            "emotional_peak": "她说出真相，对方失语",
                            "aftershock": "旁观者后退，他低下头",
                            "cliffhanger": "门外又传来脚步声",
                            "characters": ["她", "他"],
                            "emotion_curve": [
                                "压抑", "逼迫", "反抗", "爆发", "错愕", "余波"
                            ],
                            "scores": {
                                "conflict": 10,
                                "emotion": 9.5,
                                "reversal": 10,
                                "visual": 9,
                                "completeness": 9,
                            },
                        }
                    ]
                },
                ensure_ascii=False,
            )
        if self.low_quote[0] in prompt:
            return json.dumps(
                {
                    "highlights": [
                        {
                            "title": "短暂争执",
                            "start_quote": self.low_quote[0],
                            "end_quote": self.low_quote[1],
                            "setup": "两人谈话",
                            "conflict": "意见不同",
                            "turning_point": "她放下杯子",
                            "emotional_peak": "短暂沉默",
                            "aftershock": "继续等待",
                            "cliffhanger": "没有",
                            "characters": ["她"],
                            "emotion_curve": ["平静", "不满", "沉默"],
                            "scores": {
                                "conflict": 5,
                                "emotion": 4,
                                "reversal": 3,
                                "visual": 5,
                                "completeness": 6,
                            },
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps({"highlights": []}, ensure_ascii=False)


def test_long_novel_scan_ranks_source_anchored_emotional_highlight() -> None:
    low_start = "她把茶杯放回桌上。"
    low_end = "房间重新安静下来。"
    high_start = "大门忽然被人推开。"
    high_end = "他终于在所有人面前低下了头。"
    source = (
        "序章里一切都很平静。" * 45
        + low_start
        + "她问了一句，对方没有回答。"
        + low_end
        + "他们继续等待消息。" * 70
        + high_start
        + "她从口袋里拿出保存多年的证据，说出了被隐瞒的真相。"
        + "刚才还在指责她的人同时后退，连呼吸都停了一瞬。"
        + high_end
        + "门外又响起急促的脚步声。" * 40
    )
    analyzer = NovelHighlightAnalyzer(
        _HighlightClient((low_start, low_end), (high_start, high_end)),
        chunk_chars=1200,
        overlap_chars=200,
    )

    report = analyzer.analyze(
        source,
        novel_title="测试小说",
        reference_analyses=[
            {
                "video_id": "reference",
                "duration_seconds": 60,
                "expression_analysis": {
                    "evidence": [
                        {"id": "E1", "start_seconds": 0, "end_seconds": 2},
                        {"id": "E2", "start_seconds": 30, "end_seconds": 34},
                    ],
                    "conflict": {
                        "trigger": {"text": "参考触发", "evidence_ids": ["E1"]},
                        "turning_point": {
                            "text": "参考峰值",
                            "evidence_ids": ["E2"],
                        },
                    },
                },
            }
        ],
        driver_mode="reference_video",
    )

    selected = report.selected_highlight
    assert selected.title == "身份揭晓后的决裂"
    assert source[selected.source_start_char : selected.source_end_char].startswith(
        high_start
    )
    assert source[selected.source_start_char : selected.source_end_char].endswith(high_end)
    assert report.driver_mode == "reference_video"
    assert report.driver_decision["duration_from"] == "reference_video_median"
    assert selected.recommended_duration_seconds == 60
    assert sum(
        item["duration_seconds"] for item in selected.amplification_plan
    ) == selected.recommended_duration_seconds
    assert selected.amplification_plan[3]["stage"] == "情绪峰值"
    assert selected.amplification_plan[4]["duration_seconds"] >= 14

    novel_driven = analyzer.analyze(source, novel_title="测试小说")
    assert novel_driven.driver_mode == "novel_highlight"
    assert novel_driven.driver_decision["duration_from"] == "novel_span_and_emotion_steps"
    assert novel_driven.selected_highlight.recommended_duration_seconds == 45
    assert novel_driven.selected_highlight.amplification_plan[4]["duration_seconds"] == 7


def test_reference_video_contributes_only_evidence_backed_position_ratios() -> None:
    pattern = analyze_reference_video_highlights(
        [
            {
                "video_id": "v1",
                "duration_seconds": 60,
                "expression_analysis": {
                    "evidence": [
                        {"id": "E1", "start_seconds": 0, "end_seconds": 2},
                        {"id": "E2", "start_seconds": 30, "end_seconds": 34},
                    ],
                    "conflict": {
                        "trigger": {"text": "先展示威胁", "evidence_ids": ["E1"]},
                        "turning_point": {
                            "text": "证据出现",
                            "evidence_ids": ["E2"],
                        },
                    },
                },
            }
        ]
    )

    assert pattern.sample_count == 1
    assert pattern.median_hook_position_ratio == pytest.approx(1 / 60, abs=0.0001)
    assert pattern.median_peak_position_ratio == pytest.approx(32 / 60, abs=0.0001)
    assert pattern.conflict_patterns == ["trigger", "turning_point"]


def test_hallucinated_highlight_quotes_are_rejected() -> None:
    class _BadClient:
        def chat_completion_tracked(self, messages, **kwargs):
            return json.dumps(
                {
                    "highlights": [
                        {
                            "start_quote": "原文并不存在的开头",
                            "end_quote": "原文并不存在的结尾",
                            "scores": {},
                        }
                    ]
                },
                ensure_ascii=False,
            )

    with pytest.raises(NovelHighlightAnalysisError, match="精确定位"):
        NovelHighlightAnalyzer(_BadClient()).analyze("真实原文内容。" * 40)


def test_reference_video_driver_requires_timed_peak_evidence() -> None:
    with pytest.raises(NovelHighlightAnalysisError, match="时间证据"):
        NovelHighlightAnalyzer(_HighlightClient(("甲" * 4, "乙" * 4), ("丙" * 4, "丁" * 4))).analyze(
            "真实小说原文。" * 40,
            driver_mode="reference_video",
            reference_analyses=[],
        )


def _highlight_report(source: str, start: int, end: int) -> dict:
    segment = source[start:end]
    return {
        "schema": "novel_highlight_analysis/v1",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest().upper(),
        "selected_highlight": {
            "title": "当众决裂",
            "source_start_char": start,
            "source_end_char": end,
            "source_start_quote": segment[:8],
            "source_end_quote": segment[-8:],
            "conflict": "双方目标正面冲突",
            "turning_point": "证据出现",
            "emotional_peak": "关键人物当众决裂",
            "aftershock": "对手沉默，旁观者后退",
            "recommended_duration_seconds": 60,
            "amplification_plan": [
                {"stage": "情绪峰值", "duration_seconds": 18, "focus": "前中后反应"}
            ],
        },
    }


def test_splitter_uses_bound_highlight_span_and_dynamic_duration() -> None:
    source = "开头不应进入分镜。" * 10 + "高光开始。" + "冲突持续升级。" * 20 + "高光结束。" + "结尾不应进入分镜。" * 10
    start = source.index("高光开始。")
    end = source.index("高光结束。") + len("高光结束。")
    report = _highlight_report(source, start, end)
    response = {
        "novel_title": "测试小说",
        "characters": [],
        "scenes": [
            {
                "scene_id": index,
                "narration": f"这是第{index}个镜头的剧情动作。",
                "dialogue": [],
                "first_frame_prompt": "cinematic opening frame with consistent character",
                "last_frame_prompt": "cinematic closing frame with consistent character",
                "duration_seconds": 4.5,
            }
            for index in range(13)
        ],
    }

    with patch(
        "src.content_factory.novel_splitter.llm_client.chat_completion_tracked",
        side_effect=[
            json.dumps(response, ensure_ascii=False),
            json.dumps(
                {"checked_scene_count": 13, "unsupported": []},
                ensure_ascii=False,
            ),
        ],
    ) as completion:
        result = split_novel(
            source,
            novel_title="测试小说",
            highlight_report=report,
        )

    assert len(result.scenes) == 13
    assert result.total_duration_seconds == 58.5
    prompt = completion.call_args_list[0].args[0][-1]["content"]
    assert "高光开始" in prompt
    assert "开头不应进入分镜" not in prompt
    assert "情绪峰值必须拆成至少三个相邻镜头" in prompt
    assert "目标总时长为 60 秒" in prompt


def test_splitter_rejects_dialogue_that_is_not_in_highlight_source() -> None:
    source = "林夏遇到麻烦时，她走到他身边说：老公，别怕，我罩着你！随后林夏愣住了。" * 3
    report = _highlight_report(source, 0, len(source))
    bad_response = {
        "novel_title": "测试小说",
        "characters": ["林夏"],
        "scenes": [
            {
                "scene_id": index,
                "narration": f"这是第{index}个镜头的剧情动作。",
                "dialogue": (
                    [{"speaker": "林夏", "text": "你到底是谁？", "emotion": "surprised"}]
                    if index == 0 else []
                ),
                "first_frame_prompt": "cinematic opening frame with consistent character",
                "last_frame_prompt": "cinematic closing frame with consistent character",
                "duration_seconds": 4.5,
            }
            for index in range(13)
        ],
    }

    with patch(
        "src.content_factory.novel_splitter.llm_client.chat_completion_tracked",
        return_value=json.dumps(bad_response, ensure_ascii=False),
    ):
        with pytest.raises(Exception, match="对白不在原文"):
            split_novel(source, novel_title="测试小说", highlight_report=report)


def test_splitter_restores_only_unique_punctuation_variant() -> None:
    storyboard = NovelSplit.model_validate(
        {
            "novel_title": "测试小说",
            "characters": ["林夏"],
            "scenes": [
                {
                    "scene_id": 0,
                    "narration": "林夏迟疑片刻后终于点头答应。",
                    "dialogue": [
                        {"speaker": "林夏", "text": "好！好！！！", "emotion": "stunned"}
                    ],
                    "first_frame_prompt": "cinematic close-up before the answer, controlled lighting",
                    "last_frame_prompt": "cinematic reaction after the answer, controlled lighting",
                    "duration_seconds": 4.0,
                }
            ],
        }
    )
    repairs = _restore_unique_source_dialogue(
        storyboard,
        "他红着脸说：“好……好！！！”然后低下了头。",
    )
    assert repairs == [
        {"scene_id": 0, "before": "好！好！！！", "after": "好……好！！！"}
    ]
    assert storyboard.scenes[0].dialogue[0].text == "好……好！！！"


def test_splitter_does_not_repair_changed_or_ambiguous_wording() -> None:
    storyboard = NovelSplit.model_validate(
        {
            "novel_title": "测试小说",
            "characters": ["林夏"],
            "scenes": [
                {
                    "scene_id": 0,
                    "narration": "林夏仍然没有给出明确答案。",
                    "dialogue": [
                        {"speaker": "林夏", "text": "我答应你", "emotion": "neutral"}
                    ],
                    "first_frame_prompt": "cinematic close-up before the uncertain answer",
                    "last_frame_prompt": "cinematic reaction after the uncertain answer",
                    "duration_seconds": 4.0,
                }
            ],
        }
    )
    repairs = _restore_unique_source_dialogue(
        storyboard,
        "她问：“你答应我吗？”他又问：“你答应她吗？”",
    )
    assert repairs == []
    assert storyboard.scenes[0].dialogue[0].text == "我答应你"


def test_dialogue_timing_rejects_long_line_in_five_second_shot() -> None:
    storyboard = NovelSplit.model_validate(
        {
            "novel_title": "测试小说",
            "characters": ["洛雪微"],
            "scenes": [
                {
                    "scene_id": 0,
                    "narration": "她贴近他，一字一句地提出要求。",
                    "dialogue": [
                        {
                            "speaker": "洛雪微",
                            "text": "你是有老婆的男人，要和别的女人保持距离，就算要和别的女人说话也得有我在场知道不？",
                            "emotion": "tense",
                        }
                    ],
                    "first_frame_prompt": "cinematic tense close-up before the warning begins",
                    "last_frame_prompt": "cinematic tense close-up while the warning continues",
                    "duration_seconds": 5.0,
                }
            ],
        }
    )
    assert "约需" in _find_dialogue_timing_errors(storyboard)[0]


def test_dialogue_timing_extends_small_overrun_but_not_past_hard_cap() -> None:
    storyboard = NovelSplit.model_validate(
        {
            "novel_title": "测试小说",
            "characters": ["甲"],
            "scenes": [
                {
                    "scene_id": 0,
                    "narration": "他在停顿之后继续把这一句话说完。",
                    "dialogue": [
                        {"speaker": "甲", "text": "这句话需要多一点时间才能够完整说完吧", "emotion": "tense"}
                    ],
                    "first_frame_prompt": "cinematic close-up while the sentence begins slowly",
                    "last_frame_prompt": "cinematic close-up as the sentence reaches its end",
                    "duration_seconds": 4.0,
                }
            ],
        }
    )
    repairs = _fit_dialogue_durations(storyboard)
    assert repairs[0]["after_seconds"] == 4.5
    assert storyboard.total_duration_seconds == 4.5
    assert _find_dialogue_timing_errors(storyboard) == []


def test_dialogue_emotion_rejects_flat_high_conflict_storyboard() -> None:
    storyboard = NovelSplit.model_validate(
        {
            "novel_title": "测试小说",
            "characters": ["甲", "乙"],
            "scenes": [
                {
                    "scene_id": index,
                    "narration": "两个人继续完成这一轮情绪对抗。",
                    "dialogue": [
                        {
                            "speaker": "甲" if index % 2 == 0 else "乙",
                            "text": f"这是第{index}句对白",
                            "emotion": "neutral",
                        }
                    ],
                    "first_frame_prompt": "cinematic opening frame with two consistent characters",
                    "last_frame_prompt": "cinematic closing frame with two consistent characters",
                    "duration_seconds": 4.0,
                }
                for index in range(6)
            ],
        }
    )
    assert "过平" in _find_dialogue_emotion_errors(storyboard)[0]


def test_splitter_rejects_highlight_report_for_another_source() -> None:
    source = "原始小说内容。" * 30
    report = _highlight_report(source, 0, 50)
    report["source_sha256"] = "0" * 64

    with pytest.raises(NovelSplitError, match="哈希不一致"):
        split_novel(source, highlight_report=report)
