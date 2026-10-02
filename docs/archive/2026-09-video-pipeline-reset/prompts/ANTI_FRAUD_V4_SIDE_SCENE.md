# 反诈动画短片 V4：侧后方人物与环境局部动态

## 0. 方向调整

停止正脸人物 LTX 试验。人物不需要说话口型，也不需要眨眼来证明画面在动。

V4 使用全屏单画面：

- 人物采用侧后方、背影或侧脸构图；
- 人物、衣服、头部和肩部保持静态母版像素；
- 只让窗外夜景、台灯亮度、手机屏幕光和轻微空气颗粒发生受控变化；
- 不使用三段式、拼贴、推拉、摇移或整帧生成式动画。

## 1. 第一幕三镜头

| 镜头 | 画面 | 动态 |
| --- | --- | --- |
| `l01_narrator` | 小杰侧后方坐在桌前，人物只显示后脑、侧脸轮廓和肩部；允许桌边出现一部静止手机 | 静态建立镜头；环境变化可选，不要求为了通过门禁而制造伪动态 |
| `l02_scammer` | 已批准的手机静物母版 `master_phone_seed3123.png` | 手机屏幕产生一次柔和冷光脉冲；无文字、无 UI |
| `l03_xiaojie` | 与 l01 使用同一人物母版，可改变裁切或静态色调，不重新生成人物 | 台灯亮度极轻微降低，窗外灯光保持缓慢变化 |

## 2. Hermes：只生成侧后方人物母版

不再生成正脸，不生成视频，不评价通过，不修改 `D:\IT\ai_douyin`。

输出四张候选到：

`D:\IT\AI_vido\ComfyUI\output\anti_fraud_v4\candidates\`

```text
master_side_seed4101.png
master_side_seed4102.png
master_side_seed4103.png
master_side_seed4104.png
```

固定参数：

- `flux1-schnell-fp8.safetensors`
- `704x1248`
- `steps=4`
- `CFG=1.0`
- `euler/simple`
- `denoise=1.0`

正向提示词：

```text
modern cinematic 2D anime keyframe, refined clean lineart, soft cel shading with subtle gradients, a 20-year-old Chinese male college student named Xiao Jie, neat short black hair, wearing a loose plain white crewneck short-sleeve t-shirt, rear three-quarter side view from behind his left shoulder, seated quietly at a brown wooden desk in a modest dorm room at night, only the back of his head, a small side facial silhouette and shoulders are visible, face turned downward toward the desk, at most one black smartphone lies flat and motionless near the far edge of the desk, deep blue night window, grey curtains, blue-grey bedding, warm tungsten desk lamp, navy shadows and amber highlights, fixed camera, vertical 9:16, no text, no watermark
```

候选只按实际画面验收，不依赖负向提示词。

通过门槛：

1. 不是正脸；只显示后脑、少量侧脸轮廓和肩部；
2. 白色圆领短袖、短黑发和自然肤色一致；
3. 不出现手指或持机动作；允许自然静止的手臂轮廓和一部平放、不接触人物的手机；
4. 夜间宿舍包含蓝窗、灰窗帘、蓝灰床品、棕木桌和暖台灯；
5. 没有镜子、白天、上下铺过道、第二个人物、文字或 UI。

四张生成后停止，由 Codex 目视选择一张。未获批准前，不生成视频。

## 3. Claude Code：不再运行人物 LTX

Claude Code 只负责准备静态母版和受控图层，不运行 LTX、Wan、Sonic 或其他人物生成模型。

### l01 环境动态

- 人物母版完整保持静态；
- 该镜头允许标记为 `static_establishing_approved`；只要构图、人物和技术规格通过，就不强制内部动态；
- 桌边静置手机在约 `0.7s` 时产生一次柔和冷蓝色来信光脉冲，约 `1.5s` 后恢复；
- 手机光效可轻微照亮手机周围的小块桌面，但不能进入人物、椅子或床铺区域；
- 窗户区域添加 2 至 4 个低亮度、低透明度远景光点；
- 光点在 3.88 秒内只改变透明度，不改变人物或房间结构；
- 可添加极少量缓慢上浮的空气颗粒，透明度不高于 `0.10`。

### l02 手机光效

使用：

`D:\IT\AI_vido\ComfyUI\output\anti_fraud_v31\candidates\master_phone_seed3123.png`

- 手机和桌面完全静止；
- 仅在手机屏幕范围添加一次冷蓝色柔光脉冲；
- 光效总时长约 `0.8s`，峰值透明度不高于 `0.18`；
- 不生成文字、聊天气泡、金额、按钮或 UI。

### l03 环境动态

- 复用 l01 的同一人物母版；
- 台灯亮度在 3.88 秒内缓慢降低约 `3%`，随后保持；
- 窗外光点变化可以延续，但不能与 l01 完全重复；
- 人物区域保持原始像素不变。

## 4. 技术规格

- 工作分辨率：`704x1248`
- 帧率：`25 fps`
- 帧数：`97`
- 时长：`3.88s`
- 输出：H.264 / `yuv420p`
- 镜头：固定
- 布局：全屏 `single_scene`

## 5. 验收

逐镜头导出 `f000`、`f048`、`f096`。

通过条件：

- 人物头部、肩部、衣服和轮廓三帧像素位置一致；
- 背景家具和构图不发生生成式变化；
- 只有指定区域的光效或颗粒变化；
- 对标记为 `environment_dynamic` 的镜头，动态必须在正常速度播放时肉眼可见，不能依赖差分图才能确认；
- `blend=difference,signalstats` 的 `YAVG` 只作诊断，不能单独作为通过依据；变化必须发生在叙事目标区域并具有可见意义；
- 标记为 `static_establishing_approved` 的镜头不套用动态阈值，但必须在 review JSON 中明确记录静态用途；
- 无手、手机增生、人物变形、文字、UI、镜头运动或闪烁；
- 动态虽然克制，但整幅画面仍保持完整全屏视觉，不形成局部视频窗口或三段式拼图。
