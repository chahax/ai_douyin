# AI 视频稳定输出控制模式

本文档用于选择生成工具、约束生成区域，并通过 `video_control/v1` 清单执行自动验收。目标不是依赖更长提示词，而是把“哪些像素允许变化、光线允许变化多少、哪些区域必须锁定”写成机器可检查的规则。

## 五种控制模式

| 模式 | 适用镜头 | 推荐工具 | 强制门禁 |
|---|---|---|---|
| `pixel_locked` | 手机亮光、窗外光点、空气颗粒、字幕动画 | Pillow/Canvas/FFmpeg 确定性合成 | 全局运动、锚点漂移、光线变化 |
| `micro_motion` | 单人呼吸、眨眼、轻微低头 | LTX、FramePack、受限 I2V | 光线闪烁、动作幅度、运动缺失 |
| `subject_only` | 固定背景中仅人物运动 | Wan Animate Move、人物蒙版、静态背景回贴 | 静态区锁定、人物区动态、光线稳定 |
| `replacement_relight` | 把人物替换进已有场景 | Wan Animate Replacement、背景视频、人物蒙版、Relighting LoRA | 参考图锁定、背景静止、光色稳定 |
| `free` | 转场、梦境、特效、允许大幅变化的镜头 | Wan/LTX/其他生成视频模型 | 仅阻止严重闪烁和颜色跳变 |

## 推荐工具链

### 1. 光线与色调

- `ColorMatchV2`：生成后对齐原始参考图，推荐 `reinhard_lab_gpu`，强度从 `0.5` 到 `0.7`。
- FFmpeg `deflicker`：处理帧间曝光闪烁，不解决人物变形。
- `WanAnimate_relight_lora_fp16.safetensors`：用于 Wan Animate Replacement 模式，让替换人物适应背景光色。

官方 ComfyUI LoRA：

```text
https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors
```

### 2. 区域锁定

- SAM2、BiRefNet：生成精确人物蒙版。
- 静态背景回贴：模型只负责人物区域，背景和前景从原图逐帧覆盖。
- 矩形或多边形软蒙版：没有分割模型时的快速方案，只适合测试。

### 3. 动作控制

- Wan Animate Move：人物姿态迁移；驱动视频必须是单人物、固定机位、手部清晰。
- FramePack：适合复用 2–5 秒人物动作资产。
- LivePortrait：适合头肩人像、表情和说话，不应承担全身动作。
- LTX I2V：适合少量剧情和镜头运动，不适合像素锁定。
- 确定性 2D 合成：当需求只是光点、呼吸缩放、轻微视差时优先使用。

### 4. 流畅度

- FFmpeg `minterpolate`：零安装、速度快，复杂手部可能产生中间帧形变。
- RIFE/FILM：运动插帧质量通常更高，应在人物和光线验收通过后使用。
- 插帧不是修复工具；原始帧存在换脸、手部变形或曝光闪烁时必须先拒绝原片。

## 固定处理顺序

```text
生成原始帧
→ 人物/背景分层
→ ColorMatchV2
→ 静态背景与前景回贴
→ Deflicker
→ video_control/v1 验收
→ 插帧
→ 发布规格质量门禁
```

## `video_control/v1` 清单

```json
{
  "template": "video_control/v1",
  "video_path": "candidate.mp4",
  "reference_image": "reference.png",
  "mode": "subject_only",
  "regions": {
    "foreground": {
      "rect": [0, 0, 300, 320],
      "motion": "static",
      "reference_lock": true
    },
    "subject": {
      "rect": [300, 0, 340, 320],
      "motion": "dynamic"
    }
  }
}
```

执行：

```powershell
.\.venv\Scripts\python.exe scripts\video_control_audit.py control.json
```

返回码：

- `0`：通过。
- `2`：门禁拒绝。
- 报告默认写到视频同目录，扩展名为 `.control.json`。

## 接入 `story_video/v1`

需要阻止未验收镜头进入成片时，在故事清单中启用：

```json
{
  "template": "story_video/v1",
  "require_scene_control": true,
  "scenes": [
    {
      "id": "opening",
      "video_path": "opening.mp4",
      "control_manifest": "opening.control.json",
      "lines": []
    }
  ]
}
```

装配器会在配音和合成之前执行每个场景的控制门禁，并确认控制清单验证的文件就是该场景的 `video_path`。任一场景失败时停止合成，同时保留对应的 `.control.json` 报告。

## 模型工作流约束

1. 正式 Wan Animate 不使用普通 Wan2.2 I2V/T2V LoRA；预览加速 LoRA 只能用于快速选型。
2. 人物驱动视频不能使用已经出现漂移的生成视频。
3. 双人物画面必须先确定主驱动人物，不能把整帧直接交给姿态提取。
4. 没有背景视频和人物蒙版时，不使用 Replacement/Relighting 模式。
5. 提示词不能代替区域锁定、参考图锁定和光线门禁。
