---
doc_status: proposed
doc_category: implementation_plan
last_reviewed: 2026-05-14
model_usage: 数字人主讲视频的当前版本落地修改方案，优先级高于早期蓝图 docs/PRESENTRER_VIDEO_PLAN.md。
---

# 数字人主讲视频当前版本修改方案

更新时间：2026-05-14

## 一句话结论

当前项目已经具备脚本生成、TTS、BGM、FFmpeg 合成、抖音发布、FramePack/PNG 序列叠加等基础能力。这个版本不要从“每段都生成背景图 + 每段都跑 SadTalker”的完整理想链路开始，而是先做一个稳定的单人主讲 MVP：

```text
关键词/文本
  -> 脚本生成
  -> 分段
  -> TTS 生成音频并以真实音频时长校准分段
  -> 默认动漫风背景/可选指定背景图
  -> 叠加标题、关键词、底部字幕
  -> 叠加单个数字人 PNG 序列或静态透明图
  -> FFmpeg 输出竖屏 mp4
  -> 后续复用 douyin-publish / auto-publish 发布
```

第一版目标是稳定出片，不把 ComfyUI、SadTalker、发布自动化全部绑进同一个闭环。

## 当前可复用能力

| 能力 | 当前位置 | 复用方式 |
|---|---|---|
| 脚本生成 | `src/content_factory/script_generator.py`、`src/services/generation_service.py` | 继续复用现有 RAG/LLM 生成口播稿 |
| TTS | `src/content_factory/tts_engine.py` | 继续复用 GPT-SoVITS / Edge-TTS |
| 音频时长读取 | `src/content_factory/video_composer.py:get_duration` | 用真实音频时长校准时间轴 |
| BGM 混音 | `src/content_factory/audio_mixer.py` | MVP 可先跳过，或最终合成阶段统一混入 |
| 视频合成 | `src/content_factory/video_composer.py` | 新增单人主讲合成函数，复用 `_run_ffmpeg`、`get_duration` |
| FramePack/PNG 序列 | `data/framepack/frames_looped/*`、`src/content_factory/framepack_pipeline.py` | 优先用 PNG 序列做数字人层，比每段 SadTalker 更稳 |
| 自动发布 | `src/services/auto_publish_service.py`、`main.py douyin-publish` | 第一版先生成 mp4，发布作为独立步骤；第二版再接入 `auto-publish` |

## 关键取舍

### 1. 暂缓每段 SadTalker

原方案中每段音频都调用 SadTalker 生成口型视频，质量上限高，但慢且失败点多。当前项目已有 FramePack PNG 序列和透明角色图，第一版应使用：

- 首选：`data/framepack/frames_looped/na1_idle_v1/%06d.png`
- 备选：`data/png/na1_nobg.png` 或 `data/png/composite_na1.png`

这样主讲人有轻微动作或至少稳定站位，先保证出片。

### 2. 分段时长以音频为准

脚本分段可以先估算，但最终时间轴必须来自实际 TTS 音频时长。原因是 GPT-SoVITS / Edge-TTS 语速、停顿和标点处理都会影响最终长度。

推荐规则：

```text
先按文本切成段落
  -> 每段单独 TTS
  -> ffprobe 获取每段音频真实时长
  -> 用真实时长生成每段画面
  -> concat 拼接
```

### 3. 背景图生成先降级，但默认走动漫风

ComfyUI 背景图生成可以保留接口，但 MVP 不依赖它。第一版背景策略：

1. 有用户指定背景图/视频时使用指定素材。
2. 没有指定时生成 1080x1920 动漫风背景，适合作为数字人主讲的默认画面。
3. 仍没有可用素材时生成纯色/渐变背景图。

当前默认背景风格为 `anime`，后续可把同一个 `background_style` 参数接入 ComfyUI 工作流，生成更丰富的动漫教室、街景、书房、城市天台等场景。

### 4. 文字不要做全文上屏

长口播全文上屏会挤压画面，也容易截断。第一版文字层建议：

- 顶部：主题标题，最多 1-2 行。
- 中部：当前段关键词或金句，最多 2 行。
- 底部：短字幕，最多 2 行。

完整文案可以存在元数据里，不强求全部显示在画面上。

## 新增模块设计

```text
src/content_factory/presenter/
  __init__.py
  models.py               # PresenterSegment / PresenterRequest / PresenterResult
  script_segmenter.py     # 文本分段和样式标记
  text_overlay.py         # PIL 生成透明文字层或带字背景图
  background_resolver.py  # 背景素材选择和兜底
  presenter_composer.py   # 单段合成、最终拼接

src/content_factory/presenter_pipeline.py
  PresenterPipeline       # 主编排：脚本 -> 分段 -> TTS -> 画面 -> mp4
```

暂不新增：

- `sadtalker_wrapper.py`：放到第二阶段。
- `background_generator.py`：先做 ComfyUI 接口占位，第三阶段再接实图生成。
- `final_concatenator.py`：先并入 `presenter_composer.py`，避免模块过碎。

## 数据结构

```python
@dataclass
class PresenterSegment:
    index: int
    text: str
    style: str = "caption"  # title / caption / highlight
    keywords: list[str] = field(default_factory=list)
    audio_path: str = ""
    duration: float = 0.0
    bg_path: str = ""
    frame_path: str = ""
    clip_path: str = ""
```

```python
@dataclass
class PresenterRequest:
    keywords: str = ""
    text: str = ""
    title: str = ""
    voice: str = ""
    tts_provider: str = "gpt_sovits"
    character: str = "na1"
    background: str = ""
    bgm: str = ""
    output_dir: str = "data/videos"
```

## MVP 流程

### 阶段 1：离线生成 mp4

新增命令：

```bash
python main.py presenter --keywords "低谷期如何重新振作" --character na1
python main.py presenter --text "直接输入一段口播文案..." --title "低谷期"
python main.py presenter --text "..." --background-style anime
```

内部步骤：

1. 获取脚本：有 `--text` 则直接用，没有则调用现有 `GenerationService` / `ScriptGenerator`。
2. 分段：按句号、问号、感叹号、换行切分，目标 3-6 秒一段。
3. 每段 TTS：输出到 `data/presenter/{timestamp}/audio/seg_000.wav`。
4. 读取音频真实时长：写回 `PresenterSegment.duration`。
5. 文字层：用 PIL 生成透明 PNG，尺寸 1080x1920。
6. 合成单段：背景 + 数字人层 + 文字层 + 段落音频。
7. 拼接：FFmpeg concat 所有段落，输出 `data/videos/presenter_{timestamp}.mp4`。

验收标准：

- 给一段 100-250 字文案，能输出 15-45 秒竖屏 mp4。
- 视频有背景、主讲人、标题/字幕、人声。
- 音画时长对齐，结尾不黑屏，播放不卡顿。

### 阶段 2：接入自动发布

在 `AutoPublishRequest` 增加：

```python
video_mode: str = "single_template"  # single_template / dual_framepack_active / presenter
character: str = "na1"
background: str = ""
```

在 `AutoPublishService._compose_video()` 中增加 `presenter` 分支：

```text
request.video_mode == "presenter"
  -> PresenterPipeline.run()
  -> 返回生成的 mp4
```

在 `main.py auto-publish` 增加：

```bash
--video-mode presenter
--character na1
--background data/videos/bg_comfy_green_loop_motion.mp4
```

验收标准：

- `python main.py auto-publish --keywords "成长" --video-mode presenter` 能生成并进入现有发布流程。
- 发布失败时仍保留本地 mp4，数据库状态按现有逻辑处理。

### 阶段 3：增强视觉质量

这一阶段再接入原方案中的重能力：

- ComfyUI 每段背景图生成。
- SadTalker 单段口型生成。
- 金句段落做更强视觉样式。
- BGM 在最终视频阶段统一混入并淡出。
- 生成封面图。

## FFmpeg 合成策略

### 单段合成

输入：

- 背景图或背景视频
- 数字人 PNG 序列或静态 PNG
- 文字层 PNG
- 段落音频

输出：

- `segment_000.mp4`

关键点：

- 背景统一缩放到 `1080:1920`。
- 数字人放右下或下中位置，第一版固定参数。
- 文字层用 `overlay=0:0` 覆盖。
- `-t` 使用真实音频时长，或使用 `-shortest`。
- 输出统一 `yuv420p`，保证抖音兼容。

### 最终拼接

用 concat demuxer 拼接同编码参数的片段，减少重编码问题。若加入 BGM，则拼接后再统一混音。

## 目录结构

```text
data/presenter/{timestamp}/
  request.json
  script.txt
  segments.json
  audio/
    seg_000.wav
  text_layers/
    seg_000.png
  clips/
    seg_000.mp4
  final/
    presenter_{timestamp}.mp4
```

最终可发布文件同时复制或输出到：

```text
data/videos/presenter_{timestamp}.mp4
```

## 风险与兜底

| 风险 | 兜底 |
|---|---|
| TTS 某段失败 | 记录失败段，整条任务失败，不生成残缺视频 |
| 字幕过长 | 自动缩小字号，仍超出则只显示关键词 |
| 背景不存在 | 使用渐变背景图 |
| PNG 序列不存在 | 使用静态角色透明图 |
| FFmpeg 合成失败 | 保留中间素材和命令日志，便于复现 |
| 自动发布失败 | 保留本地 mp4，允许手动 `douyin-publish` |

## 推荐实施顺序

1. 新建 `presenter` 包和数据结构。
2. 实现 `script_segmenter.py`，先支持纯文本分段。
3. 实现 `text_overlay.py`，先生成可读字幕层。
4. 实现 `presenter_composer.py`，跑通“背景 + 静态角色 + 字幕 + 音频”。
5. 实现 `PresenterPipeline`，串起 TTS 和合成。
6. 给 `main.py` 增加 `presenter` 命令。
7. 手动用 2-3 条文案验收。
8. 再接入 `auto-publish --video-mode presenter`。

## 和原方案的关系

原文档 `docs/PRESENTRER_VIDEO_PLAN.md` 作为长期蓝图保留。本修改方案是当前版本落地路线，核心变化是：

- 先不用每段 SadTalker。
- 先不强依赖每段 ComfyUI 背景图。
- 先产出本地 mp4，再接发布。
- 以真实音频时长作为时间轴来源。
- 优先复用当前项目已有素材和 FFmpeg 合成能力。
