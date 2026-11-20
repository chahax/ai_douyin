# AI 视频控制操作手册

目标不是让提示词越来越长，而是先判断镜头允许哪些像素变化，再选择对应工具和验收模式。

## 本机工具库存

运行：

```powershell
.\.venv\Scripts\python.exe scripts\video_tool_inventory.py `
  --output data\qa\video_tool_inventory.json
```

库存检测同时检查节点、模型、VAE、文本编码器、蒙版模型、LoRA 和独立程序。状态含义：

- `ready`：执行该工具所需的主体组件齐全。
- `partial`：程序或节点存在，但缺少模型或关键插件。
- `missing`：本机没有可执行安装。
- 工具本身 `ready` 不等于完整流程 `ready`。例如 Wan Animate 模型齐全，但缺少 SAM2 模型时，自动人物蒙版流程仍为 `partial`。

2026-07-24 安装 SAM2 后的本机实测：

| 状态 | 工具 |
|---|---|
| `ready` | 确定性 2D 合成、ColorMatchV2、LTX I2V、Wan Animate Move、SAM2、FramePack、FFmpeg minterpolate |
| `partial` | Wan Animate Replacement、SadTalker、RIFE |
| `missing` | LivePortrait |

当前安装优先级：

1. `SAM2 model`：已安装 `sam2.1_hiera_small-fp16.safetensors`，92,181,820 bytes。节点中选择 `sam2.1_hiera_small.safetensors + fp16` 时会自动使用该文件。
2. `WanAnimate_relight_lora_fp16.safetensors`：仅在 Replacement/Relighting 镜头需要，约 1.44 GB，暂不下载。
3. `LivePortrait`：只有大量无手部头肩表情镜头时再安装。
4. `RIFE`：当前已有 FFmpeg minterpolate，最后再补；插帧不能修复原始变形。

下载来源：

- SAM2：`https://huggingface.co/Kijai/sam2-safetensors/blob/main/sam2.1_hiera_small-fp16.safetensors`
- Wan Relighting LoRA：`https://huggingface.co/Kijai/WanVideo_comfy/blob/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors`
- LivePortrait：`https://github.com/KwaiVGI/LivePortrait`

## 自动选型

先写 `video_shot_intent/v1`：

```json
{
  "template": "video_shot_intent/v1",
  "intent": {
    "motion": "micro",
    "framing": "medium",
    "camera": "locked",
    "background": "static",
    "contains_hands": true,
    "contains_phone": true
  }
}
```

运行：

```powershell
.\.venv\Scripts\python.exe scripts\video_control_recommend.py `
  docs\examples\video_shot_intent_phone_micro.example.json
```

推荐器会输出控制模式、首选工具、风险等级、必需素材、后处理步骤和警告。`video_control/v1` 也可以直接携带 `intent`，省略 `mode` 时自动选择；手写的 `mode` 与推荐结果冲突时直接拒绝。

加入本机可用性检查：

```powershell
.\.venv\Scripts\python.exe scripts\video_control_recommend.py `
  docs\examples\video_shot_intent_subject_action.example.json `
  --check-local `
  --output data\qa\subject_action_recommendation.json
```

输出会区分 `selected_tool_status` 和 `pipeline_status`。如果首选工具缺组件，会列出精确缺口与当前已经安装好的替代工具。

当前 `subject_action` 示例的本机结果为：

- `wan_animate_move = ready`
- `sam2_mask = ready`
- `color_match_v2 = ready`
- `pipeline_status = ready`

## SAM2 人物蒙版

SAM2 输出后必须检查手、手机、头发和衣服边缘。人物与手持物是两个对象时，分别分割再通过 `MaskComposite(add)` 合并；不要期待一个人物提示点自动包含手机。

填充内部孔洞并羽化：

```powershell
.\.venv\Scripts\python.exe scripts\refine_subject_mask.py `
  raw_mask.png refined_mask.png `
  --grow 2 `
  --feather 1.5
```

反诈人物真实测试记录位于 `data\qa\sam2_mask_test\README.md`。最终蒙版手机区域覆盖率为 `1.0`，已知背景误选率为 `0.0`。

## Wan Subject-Only 已验证方案

本机已完成一条真实 9:16 反诈人物视频：

```text
D:\IT\AI_vido\ComfyUI\output\wan_anti_fraud_subject_v1\composite_static_bg_smooth30.mp4
```

固定参数：

- `416×736`
- Wan Animate 14B FP8
- 不加载普通 Wan 加速 LoRA
- `12 steps / CFG 1.0 / Euler / simple`
- `49 frames / 16 fps`
- ColorMatchV2 `reinhard_lab_gpu / 0.65`
- SAM2 人物与手机联合蒙版
- 静态背景回贴
- 门禁通过后再用 FFmpeg 插值到 30 fps

原始 Wan 输出的左背景活动比例为 `0.2416`，被门禁拒绝；回贴后为 `0.0`，30 fps 最终版再次通过。完整工作流、报告和首中尾帧位于 `data\qa\wan_anti_fraud_subject_v1\README.md`。

对于手持物镜头，应单独声明 `phone_hand` 区域并设置运动上限：

```json
{
  "phone_hand": {
    "rect": [105, 350, 155, 190],
    "motion": "dynamic",
    "max_frame_distance": 8.0,
    "max_anchor_distance": 14.0,
    "max_active_pixel_ratio": 0.2
  }
}
```

它允许手和手机做小幅整体运动，但会拒绝手机单独旋转、抬高、脱手或手臂大幅漂移。

## 工具决策表

| 镜头要求 | 首选工具 | 控制模式 | 原因 |
|---|---|---|---|
| 人物、手、手机都不能动，只要来信光或粒子 | `deterministic_motion/v1` | `pixel_locked` | 不让生成模型重画手和手机，并自动限制活动面积 |
| 全屏故事板太静，需要整幅画面缓慢运动 | `deterministic_camera/v1` | `deterministic_full_frame` | 受限推拉/平移，不重画人物且不产生三段式 |
| 关键帧光源方向或局部色温错误 | `keyframe_relight/v1` | `masked_pixel_preserve` | 只改变批准遮罩，遮罩外必须逐像素不变 |
| 结构已稳定但曝光周期闪烁 | `video_temporal_repair/v1` | 保持原模式 | 只修 Y 通道并重新运行原始门禁 |
| 结构正确但低帧率、重复帧或节奏卡顿 | `video_smoothness/v1` | 保持原模式 | 同一时间轴比较重复帧、速度突变和运动保留率 |
| 单条都能看但跨镜头画风、线稿或肤色不统一 | `video_style_gate/v1` | 保持原模式 | 与唯一批准参考比较色彩、边缘和时间漂移 |
| 人物或场景光线偏亮、偏冷、光向相反或随时间漂移 | `video_lighting_gate/v1` | 保持原模式 | 与批准参考比较曝光、色温、对比度、低频光向和时间漂移 |
| 无手部入镜的头肩眨眼、轻微表情 | LivePortrait | `micro_motion` | 只驱动脸部，不重画身体 |
| 中景轻微身体动作 | FramePack | `micro_motion` | 比自由 I2V 更容易限制动作 |
| 固定背景、单人动作迁移 | Wan Animate Move + SAM2/BiRefNet 蒙版 | `subject_only` | 动态人物与静态背景分层 |
| 人物放进已有背景并匹配光线 | Wan Animate Replacement + Relighting LoRA | `replacement_relight` | 专门处理替换与环境光 |
| 运镜、转场、环境也必须变化 | Wan/LTX I2V | `free` | 接受更高漂移风险 |

可见手或手机的“微动作”默认推荐 `pixel_locked`。提示词中的 `keep hands fixed`、`phone unchanged` 不能替代像素锁定；需要脸动时，应裁掉手和手机后使用 LivePortrait，再与原图合成。

## 两级验收

### 严格模式

`allow_user_overrides` 保持 `false`。任何光线闪烁、参考图漂移、静态区变化或动作越界都会阻止配音和合成。

### 实用模式

用户明确看过并接受某条视频时：

1. 保留严格门禁的失败项，不改写成通过。
2. Review JSON 必须包含 `status=accepted_by_user_override`、`user_override=true`、`composition_eligible=true`、原因和相同的 `video_path`。
3. 故事清单设置 `allow_user_overrides=true`，并为该镜头填写 `control_review`。
4. 合成报告把严格失败降为 warning，并记录用户放行路径、原因和审核者。

这允许“画面不完美但流畅可用”的片段进入实用成片，同时不会丢失质量问题。

## 批量审计

单条视频：

```powershell
.\.venv\Scripts\python.exe scripts\video_control_audit.py shot.control.json
```

整个故事：

```powershell
.\.venv\Scripts\python.exe scripts\story_video_control_audit.py story.json `
  --output-dir data\qa\story_controls
```

反诈 l03 的已认可实战样例：

```powershell
.\.venv\Scripts\python.exe scripts\story_video_control_audit.py `
  data\anti_fraud_scenes\story_video_l03_controlled_probe.json `
  --output-dir data\qa\anti_fraud_l03_controlled
```

该样例会同时保留机器严格拒绝结果与用户明确放行记录。
