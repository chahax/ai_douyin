---
doc_status: active
doc_category: ltx-v2-acceptance
last_reviewed: 2026-07-22
reference_sample: data/presenter/ltx_i2v_v1/final/ltx_i2v_v1_publish.mp4
---

# LTX V2 统一画风验收清单

本清单用于把 Hermes 的故事板和 Claude Code 的 LTX 图生视频交接给 Codex / `ai_douyin` 合成为完整故事视频。每个镜头必须独立验收；任一“拒绝”项出现，即不得进入 `story_video/v1` 清单，也不得用 FFmpeg、裁剪或配音掩盖问题。

## 0. 验收对象与基准

- **基准样片**：`data/presenter/ltx_i2v_v1/final/ltx_i2v_v1_publish.mp4`。
- **画面模式**：全屏单画面（`single_scene`），没有上/中/下三段、静态拼图、边框或留白。
- **单镜头目标**：LTX 原片为 `704×1248`、`25 fps`、`97` 帧、约 `3.88 s`；最终由 `ai_douyin` 转为发布规格。
- **动作策略**：固定镜头下的微动作，例如自然呼吸、一次眨眼、微小视线或表情变化。角色、手、手机和背景不能发生叙事外的重构。

## 1. 交接包与命名（必须齐全）

每个镜头使用同一个基名 `<scene>_<shot>`，其中 `scene` 采用 `s01`、`s02`……，`shot` 采用 `sh01`、`sh02`……。只使用小写字母、数字和下划线。

| 资产 | 必须命名 | 交接要求 |
|---|---|---|
| 已批准故事板 | `<scene>_<shot>_keyframe.png` | Hermes 交付；保留正/负提示词、模型、seed 与尺寸。 |
| LTX 原始镜头 | `<scene>_<shot>_ltx_v2.mp4` | Claude Code 交付；`704×1248 / 25 fps / 约 3.88 s`。 |
| 三帧证据 | `<scene>_<shot>_ltx_v2_contact_sheet.png` | 包含首/中/尾帧，帧号与时间可辨认。 |
| 参数与人工结论 | `<scene>_<shot>_ltx_v2_review.json` | 记录工作流 JSON 路径、模型、seed、提示词、通过/拒绝和原因。 |
| Codex 交接目录 | `data/stories/<story_id>/ltx_v2/scenes/` | 仅把“通过”的 `.mp4` 放入此目录，并在故事清单中用相对 `video_path` 引用。 |

`<scene>_<shot>_ltx_v2_review.json` 至少包含：`status`（`accepted` 或 `rejected`）、`scene_id`、`shot_id`、`keyframe_path`、`video_path`、`workflow_path`、`seed`、`duration_seconds`、`frame_checks`、`issues` 和 `reviewer`。缺少任一项视为**拒绝**。

## 2. 单镜头人工验收

以下六项均为硬门槛。人工检查必须对比故事板、首帧、中帧和尾帧，而不是只看单张封面。

| 项目 | 通过标准 | 拒绝标准 |
|---|---|---|
| 角色一致性 | 脸型、发型、发色、肤色、服装、年龄感与批准故事板一致；同一角色跨镜头可辨认。 | 换脸、性别/年龄明显变化、发型或服装无剧情理由地变化；首尾身份不一致。 |
| 画风与色彩 | 与 `ltx_i2v_v1` 的现代二维动漫基调一致：干净线稿、稳定阴影、夜景蓝冷光与室内暖光关系自然；同场景色温稳定。 | 平涂霓虹漫画、写实照片、3D、油画等混入；颜色跳变、曝光闪烁、脏灰或明显与同故事其他镜头不统一。 |
| 手机与手指 | 每个角色每一时刻只有剧情需要的手机数量；手指数量、关节、握持方向和手机边缘自然，首尾保持同一持机关系。 | 双手机、凭空出现/消失的手机、多指/少指、手指粘连、穿模、手机融入手掌或镜头外移入错误位置。 |
| 镜头稳定 | 背景、台灯、窗帘、桌面等相对位置稳定；无推拉、摇移、切镜头。人物只做提示词规定的微动作。 | 非剧情要求的缩放、平移、视角变化、切镜头、背景重绘/抖动，或动作幅度大到破坏配音时间轴。 |
| 形变与闪烁 | 面部五官、衣物纹理、背景边缘在连续播放中稳定；眨眼可自然闭合和恢复。 | 五官/手部融化、肢体拉伸、局部跳帧、边缘闪烁、黑帧、马赛克或无法观看的压缩伪影。 |
| 叙事可用性 | 画面动作与该镜头台词和情绪一致，首尾可无缝用于故事时间轴。 | 动作与台词冲突、角色看向错误对象、生成文字/UI、无关人物或物体进入画面。 |

**判定规则**：六项全部符合才记为 `accepted`。任一拒绝项即记为 `rejected`，只允许在工作流中优先调整一个最相关参数后重跑；禁止把不同种类问题一次性混改，避免无法追踪原因。

## 3. 每条 3.88 秒 LTX 镜头的首中尾检查

以 `25 fps / 97` 帧为固定验收点。Claude Code 必须导出下列帧并写入 review JSON；Codex 只接收同时具备三帧证据的镜头。

| 检查点 | 帧号 / 时间 | 必查内容 | 通过标准 | 拒绝标准 |
|---|---:|---|---|---|
| 首帧 | `f000 / 0.00 s` | 是否与批准故事板一致 | 构图、人物、服装、手机和背景与关键帧一致。 | 起始即换脸、双手机、错误构图或明显画风不一致。 |
| 中帧 | `f048 / 1.92 s` | 微动作和稳定性 | 有自然、轻微的动作；手/手机/背景仍锁定。 | 近乎完全静止，或手部、手机、脸和背景出现形变/漂移。 |
| 尾帧 | `f096 / 3.84 s` | 收束与可拼接性 | 表情或视线完成小幅变化；人物身份、构图、色彩稳定。 | 镜头漂移、姿态突变、末帧糊掉/闪烁，或无法与下一镜头拼接。 |

连续播放复核时，至少完整观看两遍：一次关注脸和手，一次关注背景和色彩。发现问题即拒绝，不以“抽帧刚好正常”为通过理由。

## 4. 声画与时间轴验收

1. `story_video/v1` 中每个 `scene.id` 都必须引用一个已验收的 V2 片段；不得继续引用旧的 `data/anti_fraud_scenes/clips/` 画风素材。
2. 每一条旁白/角色台词必须有已声明的 `speaker`，且该 `speaker` 存在于 `cast`；录音优先使用 `audio_path`，否则使用其绑定的 TTS 配置。
3. 场景时长必须覆盖该场景全部台词、停顿和尾部缓冲。音频结束早于画面或结尾被硬截断为**拒绝**；视频可循环/延长时，循环点不得可见。
4. 角色说话时，画面动作不得出现与台词冲突的口型大幅变化；若没有口型驱动，使用旁白式微动作即可，不强行制造假口型。
5. 合成后检查 `<output>.timeline.json`：每条 `start`、`end` 递增且不重叠；最终视频时长与时间轴最后一个 `end` 的差值不超过 `0.35 s`。否则**拒绝**并修正清单、音频或场景时长。

## 5. 最终成片规格与质量门禁

最终成片由 `ai_douyin` 的 `publish` 档位输出并执行 `VideoQualityGate`。必须满足：

| 项目 | 通过标准 | 拒绝标准 |
|---|---|---|
| 画幅与布局 | `1080×1920`、竖屏全屏 `single_scene`。 | 非 9:16、上下静态拼图、黑边、错误裁切。 |
| 视频编码 | H.264、`yuv420p`、`30 fps`、BT.709 色彩标记、CBR 目标 `3 Mbps`。 | 非 H.264 / 非 `yuv420p` / 非 30 fps；色彩标签缺失或明显错误；视频码率低于 `2 Mbps`。 |
| 音频编码 | AAC，目标 `192 kbps`，存在可解码音频流。 | 无音轨、音频损坏、角色/旁白缺失或严重削波。 |
| 自动门禁 | `<output>.quality.json` 的 `passed` 必须为 `true`，且不允许 `file_missing`、`probe_failed`、`video_stream_missing`、`audio_stream_missing`、`duration_invalid`、`dimensions_mismatch`、`fps_mismatch`、`codec_mismatch`、`pixel_format_mismatch` 或 `frame_scan_unavailable`。 | 任一列出的错误，或动态镜头被标记为静止。 |
| 人工终检 | 抽查成片首/中/尾与每个场景切点；画风、角色、手机/手和声画同步均连续。 | 任何旧画风素材混入、角色身份跳变、切点闪帧、声画错位或质量报告与实际画面矛盾。 |

> 说明：当前 `ltx_i2v_v1` 发布样片的质量报告已验证 `single_scene` 与动态检测流程，但其视频码率约 `1.98 Mbps`，并且 BT.709 primaries/transfer 标签为 warning。它可作为视觉基准，不可作为 V2 最终交付规格的豁免；V2 成片必须消除这些警告或在交接记录中明确技术原因并由 Codex 重新编码。

## 6. 交接给 Codex 的最小清单

在请求合成完整故事前，发送以下内容：

```text
故事清单：data/stories/<story_id>/story_video_v2.json
已验收镜头目录：data/stories/<story_id>/ltx_v2/scenes/
镜头证据目录：data/stories/<story_id>/ltx_v2/reviews/
画风基准：data/presenter/ltx_i2v_v1/final/ltx_i2v_v1_publish.mp4
验收结论：所有 <scene>_<shot>_ltx_v2_review.json 均为 accepted
```

Codex 合成后应回交：`<output>.mp4`、`<output>.manifest.json`、`<output>.timeline.json`、`<output>.quality.json` 和 `<output>.story/`。上述任一文件缺失，或质量报告未通过，则该故事视频仍处于**拒绝/待修正**状态。
