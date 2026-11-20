# 反诈动画短片 V3.1：母版静帧停机门

## 0. 当前状态

V3 三张故事板全部拒绝，禁止交给 Claude Code：

- `af_v2_s01_hook_l01_narrator_v3.png`：可见双手和手机，且服装不是白色短袖；
- `af_v2_s01_hook_l02_scammer_v3.png`：可见人物；
- `af_v2_s01_hook_l03_xiaojie_v3.png`：可见双手和手机，且服装不是白色短袖。

PNG 内嵌提示词已经包含相应约束，因此不是提示词漏写。Flux Schnell 的文本约束无法作为手、手机和构图的可靠控制器；本轮用构图与人工选择消除风险，而不再依赖负向提示词。

## 1. 本轮只交付两张母版静帧

Hermes 只生成候选图，不生成视频，不评价“通过”，不修改 `D:\IT\ai_douyin`，不下载或切换模型。

| 母版 | 生成候选 | 最终用途 |
| --- | --- | --- |
| `master_face` | 四张 | 作为第一幕 l01 与 l03 的共同角色/房间锚点；Claude Code 先只用它测试一条脸部微动作 |
| `master_phone` | 四张 | 作为 l02 的完整静态手机插镜；不使用 LTX |

### 输出目录

`D:\IT\AI_vido\ComfyUI\output\anti_fraud_v31\candidates\`

候选命名：

```text
master_face_seed3111.png
master_face_seed3112.png
master_face_seed3113.png
master_face_seed3114.png
master_phone_seed3121.png
master_phone_seed3122.png
master_phone_seed3123.png
master_phone_seed3124.png
```

每张为 `704x1248`。Hermes 必须返回八张绝对路径、seed、实际提示词，并停止等待 Codex 的人工选片结论。

## 2. 模型与工作流

保留本机 `flux1-schnell-fp8.safetensors`、`704x1248`、`steps=4`、`CFG=1.0`、`euler/simple`、`denoise=1.0`。不使用负向提示词来承诺排除肢体；负向提示词可留空，最终选择以实际图像为准。

视觉参考只使用：

`D:\IT\AI_vido\ComfyUI\output\flux_fixed_00001_.png`

## 3. master_face 提示词

```text
modern cinematic 2D anime portrait, refined clean lineart, soft cel shading with subtle gradients, natural warm Chinese skin tone, a 20-year-old Chinese male college student named Xiao Jie, neat short black hair with a soft fringe, dark brown eyes, wearing a loose plain white crewneck short-sleeve t-shirt, tight head-and-shoulders portrait cropped immediately below the clavicles, face occupies the center of the vertical frame, sitting in the same modest dorm room at night, deep blue night window, grey curtains, blue-grey bedding, brown wooden desk edge, warm tungsten desk lamp, navy shadows and amber highlights, looking slightly downward with restrained neutral curiosity, vertical 9:16, no text, no watermark
```

### 选择门槛

只有符合全部项目的候选才可选为 `master_face`：

1. 画面下缘只到锁骨或上胸；不出现手、手腕、前臂、手机或完整裤子；
2. 服装必须是宽松白色圆领短袖；
3. 夜间宿舍为蓝窗、灰窗帘、蓝灰床品、棕木桌和暖台灯；没有镜子、吊灯、白天或上下铺过道；
4. 人脸、发型、肤色和画风接近视觉参考；没有文字、UI、第二个人物；
5. 不允许用“看上去差不多”放行。四张均不满足则报告失败，不再生成新 seed。

## 4. master_phone 提示词

```text
modern cinematic 2D anime still-life insert, one black smartphone lying flat and centered on a brown wooden desk, blank unlit screen, the phone occupies the lower third, warm tungsten desk lamp reflection, deep blue night window and grey curtain softly out of focus in the background, same modest dorm room at night, navy shadows and amber highlights, vertical 9:16, no text, no watermark
```

### 选择门槛

只有以下项目全满足才可选为 `master_phone`：画面内只有一部平放的手机和室内静物；没有人物、脸、手、手指、可读屏幕文字、聊天气泡或 UI；夜间房间颜色与 `master_face` 一致。

## 5. Codex 选片后的交接

Codex 从每组四张中只批准一张，复制为：

```text
D:\IT\AI_vido\ComfyUI\input\anti_fraud_ltx_v31\master_face.png
D:\IT\AI_vido\ComfyUI\input\anti_fraud_ltx_v31\master_phone.png
```

在 Codex 明确批准前，Claude Code 不得运行 LTX。

## 6. Claude Code 的唯一试运行

批准 `master_face` 后，Claude Code 只生成一条：

`af_v2_s01_hook_l01_narrator_v31_00001_.mp4`

使用 LTX 2.3 基线：`704x1248 / 25 fps / 97 帧 / 3.88 秒 / steps=20 / CFG=1.0 / Euler / I2V strength=1.0`。允许且仅允许：一次自然眨眼、极轻微呼吸、眼神下移。禁止任何镜头、头部或肩部的大幅移动，以及文字/UI/闪烁/形变。

导出 `f000`、`f048`、`f096`。Codex 目视通过后，才把同一 `master_face` 用于 l03，并在后续镜头中建立相同的母版选择流程。
