# 反诈六幕 LTX V2：Claude Code 执行任务包

将本文件从本标题开始完整复制给 Claude Code。目标是把反诈故事重制为与 LTX 样片相同的现代日系动漫风，并按 22 句台词输出 22 条短镜头。

## 0. 不可违反的目录边界

- **允许读写：** `D:\IT\AI_vido\ComfyUI`，仅限故事板输入、LTX 工作流副本、LTX 视频和该目录内的验收文件。
- **禁止修改：** `D:\IT\ai_douyin` 的任何文件；不得修改合成器、角色配音、清单、发布逻辑或旧视频。
- **禁止：** 下载模型、替换模型、修改 ComfyUI 源码、修改现有基线工作流。
- **禁止复用：** `D:\IT\ai_douyin\data\anti_fraud_scenes` 中的 `s1` 至 `s6` 图片或视频；它们不是目标画风。
- 当前这次工作只能在 `D:\IT\AI_vido\ComfyUI` 创建新文件。完成后只报告产物路径和验收结果。

## 1. 目标画风与输入约定

唯一画风参考：

- 样片视频：`D:\IT\AI_vido\ComfyUI\output\ltx_i2v_v1_00001_.mp4`
- 样片关键帧：`D:\IT\AI_vido\ComfyUI\input\flux_fixed_00001.png`

目标是现代日系动漫：干净线稿、赛璐璐明暗、夜间宿舍的冷蓝窗光与暖台灯光。每个镜头的故事板由 Hermes 先生成并人工审核，Claude Code **只做图生视频**，不得自行重画或替换故事板。

每个已审核故事板放到：

`D:\IT\AI_vido\ComfyUI\input\anti_fraud_ltx_v2\<镜头名>.png`

角色锁定：小杰是 20 岁中国男大学生、短黑发、瘦身形、白色圆领 T 恤、单部无品牌黑色手机、夜间宿舍。诈骗者、旁白和系统提示均为画外音；不生成诈骗者人物、字幕、聊天文字或 UI。母亲只在第 5 幕的已审核双人故事板中出现。

## 2. 当前本机 LTX 固定基线

从以下 API 工作流复制，不要改动原文件：

`D:\IT\AI_vido\ComfyUI\output\ltx_i2v_workflow_v1.json`

每个镜头复制为：

`D:\IT\AI_vido\ComfyUI\output\anti_fraud_ltx_v2\workflows\<镜头名>.json`

除 `LoadImage.image`、正向提示词、`RandomNoise.noise_seed` 和 `SaveVideo.filename_prefix` 外，以下节点及参数必须完全保持不变：

| 节点 | 固定值 |
| --- | --- |
| `UNETLoader` | `LTX2\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors`，`fp8_e4m3fn` |
| `LTXAVTextEncoderLoader` | `gemma_3_12B_it.safetensors` + `ltx-2.3-text-proj-only.safetensors` |
| `VAELoader` | `LTX-Kijai\LTX23_video_vae_bf16.safetensors` |
| `LTXVPreprocess` | `img_compression=18` |
| `LTXVConditioning` | `frame_rate=25` |
| `EmptyLTXVLatentVideo` | `704x1248`、`length=97`、`batch_size=1` |
| `LTXVImgToVideoInplace` | `strength=1.0`、`bypass=false` |
| `LTXVScheduler` | `steps=20`、`max_shift=2.05`、`base_shift=0.95`、`stretch=true`、`terminal=0.1` |
| `KSamplerSelect` | `euler` |
| `CFGGuider` | `cfg=1.0` |
| `LTXVTiledVAEDecode` | `horizontal_tiles=1`、`vertical_tiles=1`、`overlap=1`、`last_frame_fix=false` |
| `SaveVideo` | `format=mp4`、`codec=h264` |

基线时长为 `97 / 25 = 3.88 秒`。每句台词对应一条独立短镜头；不得循环、倒放、拉伸或把同一条动态视频重复拼接。若配音比镜头长，交由后续合成阶段作末帧停留或切镜头处理，不在本任务中改变 LTX 时长。

模型绝对路径：

- `D:\IT\AI_vido\ComfyUI\models\unet\LTX2\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors`
- `D:\IT\AI_vido\ComfyUI\models\clip\gemma_3_12B_it.safetensors`
- `D:\IT\AI_vido\ComfyUI\models\checkpoints\ltx-2.3-text-proj-only.safetensors`
- `D:\IT\AI_vido\ComfyUI\models\vae\LTX-Kijai\LTX23_video_vae_bf16.safetensors`

## 3. 全局提示词

将下列全局正向提示词与每镜头的动作描述合并；视觉风格、人物与构图主要由已审核故事板锁定。

**全局正向提示词：**

```text
fixed locked-off camera, preserve the approved keyframe's modern Japanese anime style,
clean line art, cel shading, character identity, composition, wardrobe, night dorm lighting,
phone and hand pose. Only subtle natural breathing, exactly one natural blink, and the specified
single emotional change. Keep all objects present in the first frame unchanged.
```

**全局负向提示词：**

```text
camera movement, zoom, pan, tilt, cut, new object, removed object, duplicate phone, extra phone,
extra fingers, fused fingers, hand deformation, face deformation, identity change, hairstyle change,
wardrobe change, text, subtitles, letters, readable phone screen, UI, flicker, morphing,
background change, object movement
```

硬约束：一镜只允许一个微动作；手机、手臂和手指姿势在整个镜头中锁定；镜头角度只能在故事板之间变化，不能在同一条 LTX 视频中变化。种子只用于可复现，不能当作跨镜头角色一致性的手段。每条镜头首次使用下表种子；失败重跑时一次只能改一个参数并记录原因。

## 4. 22 个镜头的命名规则与执行清单

统一镜头名：`af_v2_s<两位幕号>_<幕名>_l<两位台词号>_<说话人>`。

- 故事板：`input\anti_fraud_ltx_v2\<镜头名>.png`
- 工作流副本：`output\anti_fraud_ltx_v2\workflows\<镜头名>.json`
- 视频前缀：`anti_fraud_ltx_v2\videos\<镜头名>`
- 预期视频：`output\anti_fraud_ltx_v2\videos\<镜头名>_00001_.mp4`

### 第 1 幕：hook（3 镜头）

| 镜头名 | 台词 / 画外音 | seed | 仅允许的 LTX 微动作 |
| --- | --- | ---: | --- |
| `af_v2_s01_hook_l01_narrator` | 旁白：深夜，小杰收到一条兼职返利消息。 | 4201 | 小杰自然呼吸一次、轻微向手机聚焦、眨眼一次。 |
| `af_v2_s01_hook_l02_scammer` | 诈骗者：完成任务就能返现，先试一单，没有风险。 | 4202 | 保持手机单手姿势；眼神轻微下移，表情从平静变为好奇。 |
| `af_v2_s01_hook_l03_xiaojie` | 小杰：就试一次，应该不会这么巧遇到骗局吧。 | 4203 | 眉毛极轻微上挑后恢复；禁止抬起、转动或新增手机。 |

### 第 2 幕：sweetener（3 镜头）

| 镜头名 | 台词 / 画外音 | seed | 仅允许的 LTX 微动作 |
| --- | --- | ---: | --- |
| `af_v2_s02_sweetener_l01_narrator` | 旁白：第一笔小额返款很快到账，防备心也跟着松了下来。 | 4211 | 肩膀和呼吸轻微放松，手机屏幕只保留不可读的柔和蓝光。 |
| `af_v2_s02_sweetener_l02_xiaojie` | 小杰：真的到账了，原来这么简单。 | 4212 | 一次眨眼，嘴角出现极轻微放松；不展示到账文字或 UI。 |
| `af_v2_s02_sweetener_l03_scammer` | 诈骗者：额度越高，佣金越多。 | 4213 | 小杰眼神停在手机，轻微期待；手、手机和背景不动。 |

### 第 3 幕：trap（4 镜头）

| 镜头名 | 台词 / 画外音 | seed | 仅允许的 LTX 微动作 |
| --- | --- | ---: | --- |
| `af_v2_s03_trap_l01_narrator` | 旁白：接着，所谓的客服把他拉进群，任务金额一次比一次大。 | 4221 | 小杰眼神变紧，眉心开始轻微收拢。 |
| `af_v2_s03_trap_l02_scammer` | 诈骗者：您的账户需要升级，缴纳保证金后，全部资金会一起返还。 | 4222 | 一次眨眼后轻微担忧；不显示群聊、客服或文字。 |
| `af_v2_s03_trap_l03_xiaojie` | 小杰：已经投了这么多，不能在这一步放弃。 | 4223 | 下颌轻微绷紧，呼吸变浅；手机握姿绝对不变。 |
| `af_v2_s03_trap_l04_narrator` | 旁白：沉没成本，让他把怀疑压了下去。 | 4224 | 视线短暂下移后固定，担忧表情被压住。 |

### 第 4 幕：vanity（3 镜头）

| 镜头名 | 台词 / 画外音 | seed | 仅允许的 LTX 微动作 |
| --- | --- | ---: | --- |
| `af_v2_s04_vanity_l01_narrator` | 旁白：到账记录和群里的吹捧，让小杰以为自己找到了赚钱捷径。 | 4231 | 轻微放松并出现若有若无的期待；不得出现可读记录或群聊。 |
| `af_v2_s04_vanity_l02_xiaojie` | 小杰：等这单结算，我请大家吃饭，再买双一直想要的鞋。 | 4232 | 若故事板已有鞋盒，它必须从首帧静止存在；小杰仅有轻微笑意。 |
| `af_v2_s04_vanity_l03_narrator` | 旁白：可那些热闹的群友，都是骗子安排好的演员。 | 4233 | 小杰笑意轻微消退，眼神回到手机；不得生成群友或新人物。 |

### 第 5 幕：harvest（5 镜头）

| 镜头名 | 台词 / 画外音 | seed | 仅允许的 LTX 微动作 |
| --- | --- | ---: | --- |
| `af_v2_s05_harvest_l01_narrator` | 旁白：很快，骗子抛出了最后一道门槛：五万元保证金。 | 4241 | 小杰肩膀轻微僵住，视线固定在手机。 |
| `af_v2_s05_harvest_l02_scammer` | 诈骗者：这是最后一次认证，转完立刻能提现，错过名额就作废。 | 4242 | 小杰一次眨眼、眉心微皱；禁止转账 UI 和金额文字。 |
| `af_v2_s05_harvest_l03_xiaojie` | 小杰：我先想办法凑钱，马上就能把前面的钱全都拿回来。 | 4243 | 轻微吞咽或呼吸变化；禁止手部移动和手指变形。 |
| `af_v2_s05_harvest_l04_mother` | 母亲：怎么突然要这么多钱？你是不是遇到什么事了？ | 4244 | 仅限已审核双人故事板：母亲站在门边轻微眨眼，小杰保持座位和手机姿势。 |
| `af_v2_s05_harvest_l05_xiaojie` | 小杰：没事，我只是临时周转一下。 | 4245 | 小杰短暂避开视线后看回手机；母亲、桌面和手机均不移动。 |

### 第 6 幕：awakening（4 镜头）

| 镜头名 | 台词 / 画外音 | seed | 仅允许的 LTX 微动作 |
| --- | --- | ---: | --- |
| `af_v2_s06_awakening_l01_narrator` | 旁白：转账完成后，群聊忽然解散，所有联系人都失去了回应。 | 4251 | 小杰肩膀轻微下沉，手机光变暗但不可显示 UI 或文字。 |
| `af_v2_s06_awakening_l02_system` | 系统提示：您拨打的号码是空号，请查证后再拨。 | 4252 | 小杰凝视手机、一次自然眨眼；系统为画外音，不显示拨号界面。 |
| `af_v2_s06_awakening_l03_xiaojie` | 小杰：我被骗了……我现在就报警。 | 4253 | 从震惊到后悔的轻微表情变化；脸、手和手机不能变形。 |
| `af_v2_s06_awakening_l04_narrator` | 旁白：刷单返利不是赚钱机会，而是一步步掏空你的骗局。 | 4254 | 小杰安静低头，呼吸一次；固定镜头、固定背景、无新物体。 |

## 5. 每镜头首中尾验收（强制）

每条视频生成后，在 `D:\IT\AI_vido\ComfyUI\output\anti_fraud_ltx_v2\qa\<镜头名>\` 导出并审查：

- `frame_000.png`：首帧；
- `frame_048.png`：中帧；
- `frame_096.png`：尾帧。

每镜头逐项记录 `PASS` 或 `FAIL`：

1. 人物身份、发型、白 T 恤与已审核故事板一致；
2. 全程只有一部手机，手机数量、位置和朝向稳定；
3. 手掌、五根手指、手臂没有增生、融合或变形；
4. 人脸、眼睛和表情自然，无换脸或形变；
5. 只有表中允许的微动作，镜头没有推拉、摇移、切换；
6. 背景、台灯、窗帘、床、桌面和既有道具没有新增、消失或跳变；
7. 无文字、字幕、可读手机屏、UI、水印、闪烁或 morphing；
8. 输出为 `704x1248`、`25fps`、`97` 帧、约 `3.88` 秒、H.264。

任一项失败即判该镜头失败：保留失败报告，只改一个参数后重跑，并说明改了什么。不得以“整体看起来还行”跳过验收。

## 6. 最终交付格式

完成后按镜头逐行报告：镜头名、故事板路径、工作流 JSON 路径、视频路径、seed、首中尾验收结果、是否通过。最后汇总 `22/22` 的通过数量；少于 22 条通过时，不得宣称六幕重制完成。
