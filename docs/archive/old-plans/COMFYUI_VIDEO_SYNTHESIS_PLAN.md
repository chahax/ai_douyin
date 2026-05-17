---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 人生激励AI视频合成功能开发计划

## Context

用户要开发"人生激励AI短视频平台"项目，目前已有 `life_inspiration_video_example.py` 使用 Kling 文生视频模型生成9:16竖屏视频。但这只是单个视频生成，还没有完整的视频合成流程（包含TTS配音、字幕、BGM、图片轮播等）。

## 目标

扩展现有的 `life_inspiration_video_example.py`，实现完整的视频合成流程：
1. TTS 配音（使用 ElevenLabs 或豆包）
2. 图片轮播 + 视频合成
3. 字幕生成（卡拉OK式逐字高亮）
4. BGM 混音

## 关键文件

| 文件 | 用途 |
|------|------|
| `script_examples/life_inspiration_video_example.py` | 现有示例，需扩展 |
| `comfy_api_nodes/nodes_kling.py` | Kling 视频生成节点 |
| `comfy_api_nodes/nodes_elevenlabs.py` | ElevenLabs TTS 节点 |
| `comfy_extras/nodes_video.py` | CreateVideo, SaveVideo 等 |
| `comfy_extras/nodes_audio.py` | SaveAudio, VAE编解码等 |

## 实现方案

### 方案：基于 ComfyUI API 节点组合

不自己写底层 FFmpeg，而是利用 ComfyUI 现有节点组合实现：

**Prompt 流程设计：**

```
输入文案
   │
   ▼
[ElevenLabsTextToSpeech] ──► [Audio]
   │                           │
   │                     ┌─────┴─────┐
   │                     ▼           ▼
   │              [CreateVideo]  [LoadAudio/BGM]
   │                   │              │
   │                   ▼              │
   │              [Video] ◄───────────┘
   │                   │
   │              [SaveVideo]
   │                   │
   ▼              [Output Video]
[图片生成（可选）]
```

### 具体实现步骤

1. **创建 `life_inspiration_video_workflow.py`**

   - 封装一个 `LifeInspirationVideoWorkflow` 类
   - 支持输入：文案、风格选择、背景图片列表
   - 支持输出：合成后的视频路径

2. **工作流节点组合**

   ```
   1. ElevenLabsTextToSpeech (TTS配音)
      - 输入: script_text, voice
      - 输出: audio

   2. CreateVideo (图片+音频 → 视频)
      - 输入: images (背景图列表), audio, fps
      - 输出: video

   3. SaveVideo (保存视频)
      - 输入: video, filename_prefix
      - 输出: saved file
   ```

3. **后续扩展（可选）**

   - 字幕节点：需要找或写一个字幕生成节点
   - BGM混音：需要 AudioMix 或类似节点

## 验证方法

1. 运行修改后的示例，确保 TTS 能合成音频
2. 将音频和图片传入 CreateVideo，看能否生成视频
3. 检查输出视频是否包含音频

## 文件改动

- **新建**: `script_examples/life_inspiration_video_workflow.py`
- **修改**: `script_examples/life_inspiration_video_example.py` (备份为参考)
