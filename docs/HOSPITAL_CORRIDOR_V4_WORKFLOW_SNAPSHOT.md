# 医院走廊 V4 ComfyUI 工作流 Git 快照

> 快照日期：2026-07-27  
> 快照目的：在接入新的 Flux ControlNet、SDXL OpenPose 和 Flux IP-Adapter 之前，保存当前可复现的稳定工作流基线。

## 快照边界

本快照保存：

- 剧情、人物档案、分镜和最终提示词；
- Q版软萌布偶风格预设、风格参考图和人物身份锚点；
- 已验证的 LTX、LivePortrait、DWPose、Wan Animate 工作流 JSON；
- 最终 V4 下蹲镜头的关键帧、工作流和交付清单；
- 当前本地 ComfyUI 模型、节点和后续技术路线说明。

本快照不保存：

- ComfyUI 模型权重；
- Downloads 中尚未安装的新模型；
- 大量 QA 抽帧、缓存和失败候选；
- 完整生成视频二进制。最终视频仍保留在本地交付目录。

## 当前成片基线

| 项目 | 当前文件 |
|---|---|
| 完整 V4 粗剪 | `deliverables/hospital_corridor_v4/hospital_corridor_roughcut_v4_natural_lace.mp4` |
| V4 交付说明 | `deliverables/hospital_corridor_v4/DELIVERY.md` |
| V4 结果清单 | `deliverables/hospital_corridor_v4/FINAL_MANIFEST.json` |
| 分镜与提示词 | `deliverables/hospital_corridor_v4/STORYBOARD_AND_PROMPTS.md` |
| 最终下蹲关键帧 | `deliverables/hospital_corridor_v4/shot04_kneel_endpoint_natural_lace.png` |
| 最终下蹲 LTX 工作流 | `deliverables/hospital_corridor_v4/shot04_ltx23_natural_lace_workflow.json` |

视频二进制没有加入 Git；`FINAL_MANIFEST.json` 中保存了成片和镜头的 SHA256，可用于核验本地交付文件。

## 逐镜头工作流

| 镜头 | 工作流 | 核心输入 | 路线 |
|---|---|---|---|
| 01 等待 | `data/qa/hospital_video/ltx23_shot01_i2v_workflow.json` | `shot01_waiting_keyframe.png` | LTX-2.3 I2V |
| 08 离开 | `data/qa/hospital_video/ltx23_shot08_i2v_workflow.json` | `shot08_rear_walk_keyframe.png` | LTX-2.3 I2V |
| 03 面部特写 | `data/qa/hospital_video/liveportrait_shot03_workflow.json` | 面部关键帧 + blink driver | LivePortrait |
| 03 扩散备选 | `data/qa/hospital_video/ltx23_shot03_microexpression_driver_workflow.json` | 面部关键帧 | LTX-2.3 I2V |
| 04 姿态提取 | `data/qa/hospital_video/shot04_dwpose_endpoints_workflow.json` | 站姿与跪姿端点 | DWPose |
| 04 动作实验 | `data/qa/hospital_video/wan22_shot04_animate_workflow.json` | 首帧 + 驱动视频 | Wan2.2 Animate |
| 04 最终修正版 | `data/qa/hospital_video/ltx23_shot04_kneel_settle_lace_v3_workflow.json` | 自然垂落鞋带关键帧 | LTX-2.3 I2V |
| 06 情绪特写 | `data/qa/hospital_video/ltx23_shot06_expression_driver_workflow.json` | 面部关键帧 | LTX-2.3 I2V |
| 06 面部备选 | `data/qa/hospital_video/liveportrait_shot06_two_stage_workflow.json` | 面部关键帧 + 两段驱动 | LivePortrait |

## 关键帧

Git 快照包含 `data/qa/hospital_keyframes/selected/` 中下列最终或工作流输入关键帧：

- `shot01_waiting_keyframe.png`
- `shot03_face_closeup_keyframe.png`
- `shot04_kneel_endpoint_lace_v3.png`
- `shot04_kneel_target_flipped.png`
- `shot06_face_base_keyframe.png`
- `shot08_rear_walk_keyframe.png`

`shot04_kneel_endpoint_v2.png` 属于早期端点，不纳入当前 V4 Git 快照。

Git 快照同时保留三段体积较小、用于复现动作的驱动素材：

- `data/qa/hospital_video/shot03_blink_driver_pingpong.mp4`
- `data/qa/hospital_video/shot06_smile_driver_0_32_hold.mp4`
- `data/qa/hospital_video/shot04_pose_driver_floor_kneel_v2_416x736_16fps.mp4`

工作流载入 ComfyUI 前，需要按 JSON 中的 `LoadVideo` 文件名将这些素材复制或重命名到 ComfyUI `input` 目录。

## 可复用基础模板

- `assets/workflows/animagine_keyframe.json`
- `assets/workflows/ltx23_icloara_api.json`
- `assets/workflows/wan22_i2v_4step.json`
- `assets/workflows/wan22_i2v_api.json`
- `presets/styles/chibi_plush_3d.json`
- `assets/style_references/chibi_plush_3d_reference.jpg`
- `data/qa/hospital_character_reference/chibi_plush_3d/linmo_xiaoman_anchor_v1.png`

## 新下载组件的边界

以下文件已在 `C:\Users\c\Downloads` 验证，但在本快照时点尚未安装：

| 文件 | 识别结果 | 大小约 |
|---|---|---:|
| `diffusion_pytorch_model (1).safetensors` | InstantX FLUX.1-dev ControlNet Union | 6.15GiB |
| `diffusion_pytorch_model.safetensors` | SDXL OpenPose ControlNet | 2.33GiB |
| `model.safetensors` | OpenAI CLIP ViT-L/14 | 1.59GiB |
| `ip_adapter.safetensors` | XLabs Flux IP-Adapter V2 | 0.99GiB |
| `x-flux-comfyui-main.zip` | XLabs ComfyUI 节点源码 | 1.58MiB |

四个 safetensors 文件均能正常读取张量目录；ZIP `testzip()` 返回正常。它们不进入 Git，也不属于当前稳定基线。

## 恢复原则

1. 先恢复本快照中的 JSON、关键帧、风格预设和人物锚点。
2. 按 `COMFYUI_SCRIPT_TO_VIDEO_ROADMAP_2026-07-26.md` 中的环境清单恢复模型与节点。
3. 将关键帧和驱动素材复制到各工作流 JSON 所引用的 ComfyUI `input` 文件名。
4. 先分别运行镜头 08、01，再运行 03、06，最后测试镜头 04。
5. 新 ControlNet/IP-Adapter 必须在独立工作流副本中接入，不覆盖这份稳定快照。
