from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.content_factory.analysis_prompt_pack import (
    AnalysisPromptPackError,
    compile_analysis_prompt_pack,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DOCUMENT = (
    REPO_ROOT
    / "data"
    / "video_analysis"
    / "40426344181-1-192"
    / "RECONSTRUCTED_SCRIPT.md"
)


def _write_fixture(path: Path) -> None:
    path.write_text(
        """# 测试复刻稿

## 视频内容总结

### 核心冲突

一个人以假消息骗取另一个人的信任。

## 角色

| 角色 | 功能 | 表演关键词 |
|---|---|---|
| 粉衣女子 | 骗子 | 克制、观察对方反应 |
| 老人 | 受害者 | 信任、迟疑 |

## 表情、动作与表演节拍

| 时间 | 角色 | 表情 | 动作与视线 | 表演目的 |
|---|---|---|---|---|
| 0–3s | 粉衣女子 | 假装关心 | 低头看手机，再抬眼观察 | 制造信息差 |
| 3–6s | 老人 | 迟疑 | 手指停在屏幕上方 | 暂停决定 |

## 场景和关键道具

- 室内桌面，保持暖色主光方向一致。
- 同一部黑色手机，后期替换屏幕内容。

## 逐镜头复刻表

| 镜头 | 时间 | 画面与机位 | 台词/字幕 | 叙事作用 |
|---|---:|---|---|---|
| S01 | 0.0–1.2s | 粉衣女子中近景，低头看手机 | 粉衣女子：“这大哥三天就给我转了一万二。” | 建立骗局 |
| S02 | 1.2–3.8s | 手机屏幕特写，显示转账金额 | 到账一万元 | 金额升级 |
| S03 | 3.8–6.1s | 老人面部近景，手指缓慢停住 | 无 | 产生迟疑 |
""",
        encoding="utf-8",
    )


def test_compiler_builds_model_ready_segments(tmp_path: Path) -> None:
    source = tmp_path / "analysis.md"
    output = tmp_path / "pack.json"
    markdown = tmp_path / "pack.md"
    _write_fixture(source)

    pack = compile_analysis_prompt_pack(
        source,
        output_path=output,
        markdown_path=markdown,
    )

    assert pack["schema"] == "analysis_video_prompt_pack/v1"
    assert pack["segment_count"] == 3
    assert pack["source_duration_seconds"] == 6.1
    assert pack["segments"][0]["id"] == "segment-S01"
    assert pack["segments"][0]["generation"]["duration_seconds"] == 2.0
    assert pack["segments"][2]["generation"]["duration_seconds"] == 2.3
    assert pack["segments"][0]["participants"] == ["粉衣女子"]
    assert pack["segments"][2]["participants"] == ["老人"]
    assert pack["segments"][0]["generation"]["route"] == "single_shot_image_to_video"
    assert "可读手机界面" not in pack["segments"][0]["prompts"]["video_prompt_zh"]
    assert "不在生成视频内部切镜" in pack["segments"][0]["prompts"]["motion_prompt_zh"]
    assert output.exists()
    assert markdown.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["segment_count"] == 3
    assert "可直接提交的视频提示词" in markdown.read_text(encoding="utf-8")


def test_ui_shot_is_routed_to_deterministic_composite(tmp_path: Path) -> None:
    source = tmp_path / "analysis.md"
    _write_fixture(source)

    pack = compile_analysis_prompt_pack(source)
    ui_segment = pack["segments"][1]

    assert ui_segment["generation"]["route"] == "deterministic_ui_composite"
    assert ui_segment["generation"]["render_readable_text"] is False
    assert "不生成任何可读文字或数字" in ui_segment["prompts"]["video_prompt_zh"]
    assert "后期合成" in ui_segment["warnings"][0]


def test_native_full_video_mode_includes_dialogue_audio_and_subtitles(tmp_path: Path) -> None:
    source = tmp_path / "analysis.md"
    _write_fixture(source)

    pack = compile_analysis_prompt_pack(
        source,
        production_mode="native_full_video",
        generation_max_seconds=8.0,
    )
    first = pack["segments"][0]
    ui_segment = pack["segments"][1]

    assert pack["production_mode"] == "native_full_video"
    assert first["generation"]["render_audio"] is True
    assert first["generation"]["render_readable_text"] is True
    assert first["generation"]["route"] == "native_full_video_single_shot"
    assert first["generation"]["duration_seconds"] > 2.0
    assert "这大哥三天就给我转了一万二" in first["prompts"]["video_prompt_zh"]
    assert "时长约" in first["prompts"]["video_prompt_zh"]
    assert "准确口型" in first["prompts"]["video_prompt_zh"]
    assert "简体中文字幕" in first["prompts"]["video_prompt_zh"]
    assert first["postproduction"]["required"] is False
    assert ui_segment["generation"]["route"] == "native_full_video_ui"
    assert ui_segment["generation"]["render_readable_text"] is True
    assert "直接生成" in ui_segment["prompts"]["video_prompt_zh"]


def test_missing_shot_table_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad.md"
    source.write_text("# 没有镜头表\n\n## 角色\n\n无\n", encoding="utf-8")

    with pytest.raises(AnalysisPromptPackError, match="逐镜头复刻表"):
        compile_analysis_prompt_pack(source)


@pytest.mark.skipif(not REFERENCE_DOCUMENT.exists(), reason="reference analysis not available")
def test_current_reference_document_compiles_to_62_segments() -> None:
    pack = compile_analysis_prompt_pack(REFERENCE_DOCUMENT)

    assert pack["segment_count"] == 62
    assert pack["segments"][0]["source"]["shot_number"] == "S01"
    assert pack["segments"][-1]["source"]["shot_number"] == "S62"
    assert any(
        segment["generation"]["route"] == "deterministic_ui_composite"
        for segment in pack["segments"]
    )
    assert all(
        segment["generation"]["internal_cuts_allowed"] is False
        for segment in pack["segments"]
    )
