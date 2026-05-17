---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-13
model_usage: Edge-TTS 集成说明。仅说明双角色音频能力；完整视频能力以 CURRENT_CAPABILITIES.md 为准。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# Edge-TTS 音频生成文档

> 更新时间：2026-05-13
> 状态：已完成集成，可用于双角色不同音色；不是当前单人口播主通路。

---

## 定位说明

本文档描述 Edge-TTS 单独集成的配置和调用方法。当前项目能力总览见 [当前能力总览](CURRENT_CAPABILITIES.md)。

---

## 流程总览

```
对话脚本（LLM 生成）
    ↓
拆分台词 → Edge-TTS 分别生成 role_a.wav + role_b.wav
    ↓
可选：SadTalker / 微动作 PNG / FramePack 角色序列
    ↓
FFmpeg 叠加到背景 → 最终视频
```

---

## 1. Edge-TTS 音频生成

### 1.1 快速验证

```bash
pip install edge-tts

# 验证可用性
edge-tts --text "你好" --voice zh-CN-YunjianNeural --out test.wav
```

### 1.2 项目内调用

```python
from src.content_factory.tts_engine import TTSEngine

engine = TTSEngine(provider_type="edge")

# 角色A：沉稳学长
a_path = engine.generate_audio(
    text="这道题的原理其实很简单，我们来一步步分析。",
    filename="role_a.wav",
    voice="zh-CN-YunjianNeural",
    rate="+5%"
)

# 角色B：元气学弟
b_path = engine.generate_audio(
    text="哇，原来是这样！那还有其他方法吗？",
    filename="role_b.wav",
    voice="zh-CN-XiaoyiNeural",
    rate="+10%"
)
```

### 1.3 音色选择

| 角色类型 | 音色 | ShortName | 语速建议 |
|---------|------|-----------|---------|
| 沉稳学长 | 云健 | `zh-CN-YunjianNeural` | +5% |
| 元气学弟 | 小艺 | `zh-CN-XiaoyiNeural` | +10% |
| 知性女生 | 晓瑾 | `zh-CN-XiaojiaoNeural` | +0% |
| 成熟男声 | 云希 | `zh-CN-YunxiNeural` | +0% |
| 少年音 | 云野 | `zh-CN-YunyeNeural` | +15% |

更多音色通过 `engine.list_voices()` 查看所有中文音色。

---

## 配置切换

`.env` 中切换 TTS 提供者：

```env
# GPT-SoVITS（需角色原声，完全离线）
TTS_PROVIDER=gpt_sovits

# Edge-TTS（零配置，不同音色区分角色，需联网）
TTS_PROVIDER=edge
```

---

## 注意事项

| 项目 | 说明 |
|------|------|
| 网络要求 | Edge-TTS 每次生成需联网（1-3秒/句） |
| 视频生成 | Edge-TTS 只负责音频；视频合成由 `video_composer.py` 等模块完成 |
| 音频格式 | Edge-TTS 输出为 mp3 编码（.wav 扩展名），SadTalker 兼容 |
| 离线运行 | Edge-TTS 需联网；如果要完全离线，使用 GPT-SoVITS |
