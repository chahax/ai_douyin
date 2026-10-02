# 反诈动画短片 V3：手部锁定与脸部微动作试运行

## 0. 结论与范围

V2 第一幕三条 LTX I2V 镜头在技术规格上通过，但均因持机手臂、手机和手指大幅运动而被拒绝。停止继续调 seed 或叠加提示词禁令：当前 LTX 工作流只有整帧 I2V 条件，不能可靠锁定画面内的手、手机和前臂。

本轮只重做并验证三个 V3 镜头；不生成其余故事板、不配音、不合成。

| V2 镜头 | V3 分镜类型 | 允许动态 |
| --- | --- | --- |
| `af_v2_s01_hook_l01_narrator` | 脸部反应镜头 | 一次自然眨眼、轻微呼吸、视线向下 |
| `af_v2_s01_hook_l02_scammer` | 手机静物插镜 | 无生成式人物动作；后续由合成阶段叠加不可读屏幕光或 UI |
| `af_v2_s01_hook_l03_xiaojie` | 脸部反应镜头 | 一次自然眨眼、眉毛极轻微上挑后恢复 |

## 1. 不可违反的构图规则

1. 脸部反应镜头只拍头部、肩部和上胸；双手、手腕、前臂和手机全部在画面外。角色可朝画面下方看，暗示正在看桌上的手机。
2. 手机插镜中手机平放在木桌中央或下三分之一处；不出现人物、手指或可读文字。手机和桌面是静态对象。
3. 三张关键帧必须使用同一宿舍：深蓝夜窗、灰色窗帘、蓝灰床品、棕木桌、暖钨丝台灯、蓝橙双光。不得出现白天、上下铺过道、镜子房间、吊灯或新家具。
4. 画风以 `D:\IT\AI_vido\ComfyUI\output\flux_fixed_00001_.png` 为唯一视觉锚点：现代 2D 动漫、细线稿、柔和赛璐璐渐变、自然暖肤色；禁止粗黑线、平涂漫画、霓虹青紫和写实风格。

## 2. Hermes：只重做三张关键帧

### 交付路径与命名

输出到 `D:\IT\AI_vido\ComfyUI\output\anti_fraud_v3\storyboards\`：

- `af_v2_s01_hook_l01_narrator_v3.png`
- `af_v2_s01_hook_l02_scammer_v3.png`
- `af_v2_s01_hook_l03_xiaojie_v3.png`

全部为 `704x1248` PNG。每张保留模型、seed、完整正负提示词和人工验收结论。

### 共用提示词

**正向基础：**

```text
modern cinematic 2D anime keyframe, refined clean lineart, soft cel shading with subtle gradients, natural warm Chinese skin tone, same Xiao Jie, a 20-year-old Chinese male college student with neat short black hair and dark brown eyes, same modest dorm room at night, deep blue night window, grey curtains, blue-grey bedding, brown wooden desk, warm tungsten desk lamp, navy shadows and amber highlights, vertical 9:16, coherent anatomy, no text
```

**负向基础：**

```text
hands, fingers, arms, wrists, phone held in hand, foreground phone, raised phone, daytime, bunk-bed corridor, mirror, ceiling lamp, new furniture, neon, green skin, cyan-magenta cast, flat vector art, thick black outline, chibi, photorealistic, text, watermark, UI, split screen
```

### 三张镜头增量

| 输出 | 正向增量 | 额外负向 |
| --- | --- | --- |
| `l01_narrator_v3` | `head and shoulders close-up, Xiao Jie sits at the desk, looking slightly downward below the frame with neutral curiosity, both hands and the phone completely outside the frame` | `visible hands, visible phone` |
| `l02_scammer_v3` | `close-up insert of one black smartphone lying flat and motionless on the brown wooden desk, blank dark screen, warm lamp reflection, no human in frame` | `person, face, hand, finger, readable message, chat bubbles` |
| `l03_xiaojie_v3` | `head and shoulders close-up, Xiao Jie looks slightly downward below the frame with restrained hesitation, both hands and the phone completely outside the frame` | `visible hands, visible phone, open mouth` |

### Hermes 验收

三张都必须先通过以下检查才可交给 Claude Code：同一夜间宿舍、同一角色与画风、没有手或持机动作风险、没有文字/UI、没有新人物。任何一张失败，只允许换 seed 重跑一次；仍失败则停止并报告。

## 3. Claude Code：按镜头类型处理

### 脸部反应镜头（l01、l03）

1. 复制 V3 PNG 到 `D:\IT\AI_vido\ComfyUI\input\anti_fraud_ltx_v3\`，保留同名。
2. 复制 `D:\IT\AI_vido\ComfyUI\output\ltx_i2v_workflow_v1.json` 为每镜头独立工作流；不下载模型、不修改 V2 工作流。
3. 固定 `704x1248 / 25 fps / 97 帧 / 3.88 秒 / steps=20 / CFG=1.0 / Euler / I2V strength=1.0`。提示词只描述该镜头允许的一次眨眼、轻微呼吸和视线或眉毛变化；负向提示词禁止镜头运动、肢体、手、手机、文字、UI、形变和闪烁。
4. 输出到 `D:\IT\AI_vido\ComfyUI\output\anti_fraud_ltx_v3\videos\<镜头名>_00001_.mp4`。
5. 每条导出 `f000`、`f048`、`f096`。先生成 `l01`；人工验收通过后再生成 `l03`。

### 手机静物插镜（l02）

不使用 LTX 生成式视频。交给 `ai_douyin` 后期：以 V3 静帧作完整 3.88 秒画面，仅可添加极弱、不可读的屏幕光变化；不做缩放、推拉、摇移或屏幕文字。该镜头应明确标记为 `static_insert_approved`，不拿“视频必须动态”的通用门禁误判。

## 4. V3 验收门槛

### 脸部反应镜头

- `f000`、`f048`、`f096` 的肩部、背景和角色构图稳定；
- 只有一次可恢复的自然眨眼，以及指定的极小表情或视线变化；
- 无手、手机、手指、手臂进入画面；无换脸、张嘴、镜头运动、文字、UI、闪烁或变形；
- 逐帧观看后通过，才能进入下一镜头。

### 手机静物插镜

- 三帧构图完全一致，无人物和手；
- 无可读文字、生成式 UI、闪烁或相机运动；
- 仅在最终合成时添加受控的不可读光效。

## 5. 失败退出规则

若 V3 的脸部反应镜头仍出现大幅头部或身体运动，停止 LTX 在人物镜头上的测试。下一候选不是继续扩写提示词，而是使用具备脸部/姿势区域条件的工作流或在后期只合成受控脸部区域；在确认本机存在所需模型与节点前，不切换到 Wan 或下载新模型。
