---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-13
model_usage: FramePack 图生视频接入方案。当前以“FramePack 手动生成 + 本项目自动抽帧/抠图/循环/合成”为可执行路线；不要假设 FramePack CLI 已稳定可用。
---

> 文档状态：当前主线方案。用于把 FramePack 生成的人物连续动作片段接入本项目视频合成流程。

# FramePack 接入方案

更新时间：2026-05-13

## 当前结论

FramePack 适合用来生成单个角色 2-4 秒的自然轻微动作片段。本项目目前不直接调用 FramePack 生成视频，而是接管它输出 MP4 之后的流程：

```text
角色图
  -> FramePack 手动生成人物动作 MP4
  -> 本项目抽帧为 PNG 序列
  -> chromakey/透明化
  -> 循环到音频时长
  -> 双角色叠加到竖屏背景
  -> 输出最终 mp4
```

已经验证的成片：

- `data/videos/dual_v14_framepack_idle.mp4`，1080x1920，30fps，约 31.56 秒
- `data/videos/dual_v14_healing_bg.mp4`，1080x1920，约 31.56 秒

## 为什么采用半自动路线

当前不把 FramePack 直接写进 `auto-publish`，原因是：

- FramePack 的本地启动和生成入口还不适合作为稳定 CLI 依赖。
- FramePack 输出通常是普通 RGB 视频，不带透明 alpha。
- 人物动作生成的质量受输入图、prompt、背景色影响，需要人工挑选。
- 项目侧的抽帧、抠图、循环、合成已经可控，适合先固定为后处理管线。

## 推荐素材规格

角色输入图建议：

- 单人完整角色图，尽量正面、无遮挡。
- 背景使用纯色，优先绿色或其他与人物颜色差异大的颜色。
- 不建议先裁成最终 540x960 小图；保留完整人物比例更稳。
- 角色 A 和角色 B 分别生成动作片段，不要把双人同框图直接交给 FramePack。

背景视频建议：

- 最终输出为竖屏 9:16，默认 1080x1920。
- 背景可以是短循环 mp4，也可以先由静态图转成视频。
- 文件放在 `data/videos/` 下，便于合成脚本引用。

## 项目侧代码入口

关键文件：

- `src/content_factory/framepack_pipeline.py`
- `src/content_factory/video_composer.py`

核心函数：

- `extract_frames(video_name)`：从 `data/framepack/output/{video_name}.mp4` 抽帧。
- `chromakey_frames(video_name)`：把纯色背景转成 RGBA PNG 序列。
- `loop_frames(video_name, target_duration, audio_path)`：循环短动作帧到目标时长。
- `compose_dual_character_sequence_video(...)`：把 A/B 两组 PNG 序列和音频合成最终视频。

## 当前目录约定

```text
data/framepack/
  input/          # 给 FramePack 使用的输入图
  output/         # FramePack 手动生成的 MP4，按 video_name 命名
  raw_frames/     # 抽出的原始 PNG 帧
  frames_alpha/   # 抠图后的 RGBA PNG 帧
  frames_looped/  # 循环到目标时长后的 PNG 帧

data/videos/
  dual_v14_framepack_idle.mp4
  dual_v14_healing_bg.mp4
```

## 基本使用方式

1. 准备角色图，放到 `data/framepack/input/`。
2. 在 FramePack 中手动生成角色动作视频。
3. 将输出保存为：

```text
data/framepack/output/na1_idle_v1.mp4
data/framepack/output/n3_idle_v1.mp4
```

4. 用项目脚本处理角色 A：

```bash
python src/content_factory/framepack_pipeline.py --video na1_idle_v1 --role a --audio-a data/ref_audio/role_a.wav
```

5. 用项目脚本处理角色 B：

```bash
python src/content_factory/framepack_pipeline.py --video n3_idle_v1 --role b --audio-b data/ref_audio/role_b.wav
```

6. 如果 A/B 视频都按 `na1_*` 和 `n3_*` 命名，也可以尝试双角色处理：

```bash
python src/content_factory/framepack_pipeline.py --video na1_idle_v1 --role dual --audio-a data/ref_audio/role_a.wav --audio-b data/ref_audio/role_b.wav --bg data/videos/bg_loop.mp4
```

## 当前边界

- `framepack_pipeline.py --role dual` 仍偏脚本化，适合本地验证，不是面向普通用户的稳定入口。
- 音频 A/B 目前按顺序拼接，不负责自动生成对话脚本。
- 如果 FramePack 输出背景不是纯色，`chromakey` 效果会不稳定，需要先处理素材或换背景。
- 这条路线尚未接入 `AutoPublishService`，不会被 `python main.py auto-publish` 自动调用。

## 下一步建议

1. 增加一个服务层请求模型，例如 `FramePackVideoRequest`。
2. 给 `framepack_pipeline.py` 增加更清晰的 `prepare` / `compose` 子命令。
3. 对输入资源做检查：MP4 是否存在、音频是否存在、帧数是否足够、背景是否存在。
4. 生成最终视频后再交给 `douyin-publish` 或 `AutoPublishService`。
