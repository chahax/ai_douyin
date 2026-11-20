# 分析文档到视频大模型提示词包

## 上游剧本整理模型

视频复刻链路现在明确分为三层：

1. 本地 `Qwen3-VL-4B-Instruct` 理解关键帧和可见画面，Paraformer 负责 ASR。
2. `Minimax-M2.7` 把 Qwen、ASR 和镜头对齐证据整理成详细复刻剧本。
3. 本文档描述的确定性编译器把复刻剧本转换成 Seedance 分段提示词。

MiniMax 整理入口：

```powershell
# 只检查证据和模型配置，不调用 API
.\.venv\Scripts\python.exe scripts\refine_video_script_minimax.py `
  data\video_analysis\40426344181-1-192

# 确认后实际调用 MiniMax，输出新文件，不覆盖已有剧本
.\.venv\Scripts\python.exe scripts\refine_video_script_minimax.py `
  data\video_analysis\40426344181-1-192 `
  --submit
```

默认输出 `RECONSTRUCTED_SCRIPT.minimax.md`，同时生成 `.meta.json`，记录模型、调用方、输入证据 SHA-256、输出 SHA-256 和生成时间。只有显式传入 `--overwrite` 才允许覆盖已有输出。

配置：

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=Minimax-M2.7
VIDEO_SCRIPT_MODEL=Minimax-M2.7
VIDEO_SCRIPT_TEMPERATURE=0.2
```

## 目标

`scripts/analysis_prompt_pack.py` 把复刻分析 Markdown 编译成结构化 JSON 和人工审核用 Markdown。它不负责直接调用某一家视频服务，而是在分析、生成和剪辑之间建立稳定协议。

默认采用离线、确定性编译：相同文档和参数会得到相同提示词，便于测试、复查和后续接入 Wan、LTX、Runway 或其他视频模型。模型差异由后续 adapter 处理，分析文档不需要为每一家服务重写。

工具支持两种生产模式：`postproduction` 让视频模型只负责稳定画面，其他元素后期添加；`native_full_video` 要求支持原生音视频的模型一次生成画面、普通话对白、同步口型、中文字幕和可见手机界面。

## 输入文档约定

必须包含 `## 逐镜头复刻表`：

| 镜头 | 时间 | 画面与机位 | 台词/字幕 | 叙事作用 |
|---|---:|---|---|---|
| S01 | 0.0–1.8s | 人物中近景，低头看手机 | 台词内容 | 建立冲突 |

以下章节可选，但建议提供：

- `## 视频内容总结`：下设核心冲突、剧情推进、主要情绪、表现形式和完播动力。
- `## 角色`：角色、人物功能和表演关键词。
- `## 表情、动作与表演节拍`：时间、角色、表情、动作与视线、表演目的。
- `## 场景和关键道具`：用于全局连续性检查的列表。

工具以逐镜头表作为硬分段边界。表演节拍按时间重叠自动关联到镜头，角色通过名称和项目内常用别名匹配。

## 输出协议

JSON 协议名为 `analysis_video_prompt_pack/v1`，主要结构如下：

```json
{
  "schema": "analysis_video_prompt_pack/v1",
  "global": {
    "style_zh": "全局风格",
    "character_bible": [],
    "locations_and_props": [],
    "continuity_rules_zh": [],
    "negative_prompt_zh": "全局负面提示词"
  },
  "segments": [
    {
      "id": "segment-S01",
      "source": {},
      "participants": [],
      "performance_reference": {},
      "generation": {},
      "prompts": {
        "keyframe_prompt_zh": "首帧提示词",
        "motion_prompt_zh": "单动作提示词",
        "video_prompt_zh": "可直接提交的组合提示词",
        "negative_prompt_zh": "负面提示词"
      },
      "postproduction": {},
      "warnings": []
    }
  ]
}
```

每段同时保留源时间和建议生成时长。短于模型常见下限的源镜头默认生成 2 秒，后期再回剪；长镜头默认最多建议生成 5 秒，避免一次动作过多。两个边界均可通过 CLI 修改。

## 三种制作路线

| 路线 | 适用镜头 | 执行方式 |
|---|---|---|
| `single_shot_image_to_video` | 单人或简单双人、没有可读界面 | 角色首帧加单动作图生视频 |
| `deterministic_ui_composite` | 手机金额、聊天、流水、收据、新闻标题、字幕 | 模型只生成设备和环境，文字界面后期合成 |
| `layered_multi_person_composite` | 多人同行、警方突入、控制和押解 | 背景与人物分层生成，按遮挡关系合成 |

无论哪一种路线，都禁止在生成视频内部切镜。`画面与机位` 是首帧构图和后期剪辑参考，不是让模型自己完成一组蒙太奇的指令。

使用 `native_full_video` 时，以上路线会改写为 `native_full_video_single_shot`、`native_full_video_ui` 或 `native_full_video_multi_person`。这是对目标模型能力的硬要求，不再输出空白屏幕或后期配音占位；分段之间仍需按照顺序组装。

## 内容复刻与画面复刻的分工

内容复刻负责：核心冲突、信息揭示顺序、情绪曲线、升级机制、因果对照、高潮回报和结尾尾钩。它回答“为什么观众会继续看”。

画面复刻负责：人物外形与表演、空间、关键道具、构图、机位、动作路径、色彩、剪辑节奏、界面和声音。它回答“如何让叙事在画面中被看懂”。

两者不能混成一条超长提示词。先由文档明确内容功能，再由工具把每个镜头转换成首帧、动作、负面约束和后期任务，生成模型只处理它擅长的画面连续性。

## 命令行

```powershell
.\.venv\Scripts\python.exe scripts\analysis_prompt_pack.py `
  data\video_analysis\40426344181-1-192\RECONSTRUCTED_SCRIPT.md `
  --output data\video_analysis\40426344181-1-192\video_prompt_pack.json `
  --markdown data\video_analysis\40426344181-1-192\VIDEO_MODEL_PROMPTS.md `
  --model-profile generic-image-to-video
```

要求视频模型直接生成对白、口型、字幕和界面：

```powershell
.\.venv\Scripts\python.exe scripts\analysis_prompt_pack.py `
  data\video_analysis\40426344181-1-192\RECONSTRUCTED_SCRIPT.md `
  --output data\video_analysis\40426344181-1-192\video_prompt_pack.native_full_video.json `
  --markdown data\video_analysis\40426344181-1-192\VIDEO_MODEL_PROMPTS_NATIVE_FULL.md `
  --model-profile native-audio-video `
  --production-mode native_full_video `
  --generation-max-seconds 8
```

可用参数：

- `--style`：覆盖全局画面风格。
- `--model-profile`：写入目标模型标签，供后续 adapter 识别。
- `--production-mode`：`postproduction` 或 `native_full_video`。
- `--generation-min-seconds`：建议生成最短时长，默认 2 秒。
- `--generation-max-seconds`：建议生成最长时长，默认 5 秒。

## 接入视频模型前的检查

1. 先审核角色参考、服装和场景参考是否齐全。
2. 确认每段只有一个主要动作，且首帧位于动作发生前。
3. 对 `deterministic_ui_composite` 准备对应的真实 UI 模板，不向视频模型索要文字。
4. 对 `layered_multi_person_composite` 制定人物层、背景层和遮挡顺序。
5. 生成后先检查身份、手部、动作闭合和闪烁，再进入剪辑和配音。
6. 最终按源时间恢复切镜，并另外添加对白、音效、字幕和界面。
