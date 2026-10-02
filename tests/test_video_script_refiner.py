from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.content_factory.video_script_refiner import (
    REQUIRED_EVIDENCE_FILES,
    VideoScriptRefinementError,
    VideoScriptRefinementRequest,
    VideoScriptRefiner,
    build_refinement_preview,
)


VALID_DOCUMENT = """# 测试视频复刻级剧本

## 视频内容总结

### 核心冲突

测试。

### 剧情推进

测试。

### 主要情绪

测试。

### 表现形式

测试。

### 完播动力

测试。

## 内容复刻建议

测试。

## 画面复刻建议

测试。

## 角色

| 角色 | 人物功能 | 表演关键词 |
|---|---|---|
| 女子 | 主角 | 克制 |

## 表情、动作与表演节拍

| 时间 | 角色 | 表情 | 动作与视线 | 表演目的 |
|---|---|---|---|---|
| 0–4s | 女子 | 平静 | 看手机 | 建立信息 |

## 场景和关键道具

- 手机。

## 逐镜头复刻表

| 镜头 | 时间 | 画面与机位 | 台词/字幕 | 叙事作用 |
|---|---:|---|---|---|
| S01 | 0–4s | 中景，女子看手机 | 无 | 建立信息 |
"""


class FakeClient:
    provider_name = "openai_compatible"
    model_name = "Minimax-M2.7"

    def __init__(self, response: str = VALID_DOCUMENT) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat_completion_tracked(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.response


def _evidence_dir(tmp_path: Path) -> Path:
    for name in REQUIRED_EVIDENCE_FILES:
        value = {"schema": name, "answer": json.dumps({"scenes": []})}
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    return tmp_path


def test_preview_records_minimax_and_never_calls_network(tmp_path: Path) -> None:
    request = VideoScriptRefinementRequest(_evidence_dir(tmp_path))

    preview = build_refinement_preview(request)

    assert preview["model"] == "Minimax-M2.7"
    assert preview["network_called"] is False
    assert len(preview["inputs"]) == 4


def test_refiner_writes_script_and_model_provenance(tmp_path: Path) -> None:
    request = VideoScriptRefinementRequest(_evidence_dir(tmp_path))
    client = FakeClient()
    output = tmp_path / "RECONSTRUCTED_SCRIPT.minimax.md"

    metadata = VideoScriptRefiner(client, request).refine(output)

    assert output.read_text(encoding="utf-8").startswith("# 测试视频")
    assert metadata["model"] == "Minimax-M2.7"
    assert metadata["caller"] == "video_script_refine"
    assert Path(metadata["metadata_path"]).is_file()
    assert client.calls[0]["caller"] == "video_script_refine"
    assert client.calls[0]["use_cache"] is False


def test_refiner_rejects_wrong_active_model(tmp_path: Path) -> None:
    request = VideoScriptRefinementRequest(_evidence_dir(tmp_path))
    client = FakeClient()
    client.model_name = "deepseek-chat"

    with pytest.raises(VideoScriptRefinementError, match="model mismatch"):
        VideoScriptRefiner(client, request)


def test_refiner_protects_existing_script(tmp_path: Path) -> None:
    request = VideoScriptRefinementRequest(_evidence_dir(tmp_path))
    output = tmp_path / "existing.md"
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        VideoScriptRefiner(FakeClient(), request).refine(output)
