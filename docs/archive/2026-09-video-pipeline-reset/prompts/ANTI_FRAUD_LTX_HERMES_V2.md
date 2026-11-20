# 反诈动画短片 V2：Hermes Flux 故事板执行任务包

## 0. 任务边界（必须遵守）

你只负责生成故事板 PNG，不生成视频、不生成音频、不合成成片。

- 允许写入：`D:\IT\AI_vido\ComfyUI\output\` 下以 `anti_fraud_v2_` 开头的 PNG。
- 禁止修改：`D:\IT\ai_douyin\` 的任何文件、任何 ComfyUI 工作流 JSON、节点、模型目录或配置。
- 不下载模型，不切换模型，不重启 ComfyUI。若当前工作流不能使用以下参数，只报告阻塞原因。
- 目标视觉参考：`D:\IT\AI_vido\ComfyUI\output\flux_fixed_00001_.png`。它是画风和小杰三分之四视角的唯一首选参考；**不要**沿用旧素材 `D:\IT\ai_douyin\data\anti_fraud_scenes\xiaojie_ref.png` 的粗黑线、平涂、霓虹风格。

## 1. 固定模型与出图参数

| 项目 | 固定值 |
| --- | --- |
| Checkpoint | `flux1-schnell-fp8.safetensors` |
| 尺寸 | `704x1248`，竖屏 9:16 |
| Steps / CFG | `4 / 1.0` |
| Sampler / Scheduler | `euler / simple` |
| Denoise | `1.0` |
| 批次 | `1` |
| 正向 CLIP 节点 | 必须写入完整正向提示词；禁止为空 |
| 负向 CLIP 节点 | 必须写入完整负向提示词；禁止为空 |

每个任务只用表内指定 seed 生成一次。若触发拒绝条件，只允许保持所有其他参数不变、换一个 seed 重跑一次，并在报告中记录两个 seed。

## 2. 小杰四视图：先生成、先验收（不计入 22 个台词任务）

先完成下列四张角色参考图；四张均通过后，才开始 22 个镜头。之后每个镜头都以这四张图为身份核对基准，而不是重新设计角色。

| 编号 | 视图与构图 | Seed | 输出文件名 |
| --- | --- | ---: | --- |
| R01 | 正面半身，平静表情 | 2001 | `anti_fraud_v2_ref_01_front_seed2001.png` |
| R02 | 三分之四半身，低头看一部黑色手机；构图最接近目标参考图 | 2002 | `anti_fraud_v2_ref_02_three_quarter_seed2002.png` |
| R03 | 左侧脸半身，轻微担忧 | 2003 | `anti_fraud_v2_ref_03_profile_seed2003.png` |
| R04 | 全身站姿，白 T 恤与深灰长裤完整可见 | 2004 | `anti_fraud_v2_ref_04_full_body_seed2004.png` |

**四视图共用正向提示词：**

```text
modern cinematic 2D anime character reference sheet, refined clean lineart, soft cel shading with subtle gradients, natural warm Chinese skin tone, a 20-year-old Chinese male college student named Xiao Jie, neat short black hair with a soft fringe, dark brown eyes, slim build, plain loose white crewneck short-sleeve t-shirt, dark charcoal pants, modest dorm room at night, deep blue window, grey curtains, blue bedding, brown wooden desk, warm tungsten desk lamp, navy blue shadows and amber highlights, consistent facial proportions, vertical 9:16, no text
```

**四视图共用负向提示词：**

```text
neon, neon green skin, green face, cyan-magenta color cast, flat vector art, thick black outline, chibi, comic panel, child, middle-aged man, different hairstyle, different outfit, facial distortion, extra fingers, missing fingers, multiple phones, duplicate phone, text, watermark, logo, UI
```

## 3. 全局提示词拼接规则

对每个镜头，直接复制：`全局正向提示词 + 该镜头正向增量`。不得删掉全局锚点。

**全局正向提示词：**

```text
modern cinematic 2D anime keyframe, refined clean lineart, soft cel shading with subtle gradients, natural warm Chinese skin tone, same Xiao Jie character as the approved four-view references, 20-year-old Chinese male college student, neat short black hair with a soft fringe, dark brown eyes, slim build, plain loose white crewneck short-sleeve t-shirt, dark charcoal pants, coherent anatomy, one black smartphone only, vertical 9:16, high quality anime frame, no readable text
```

**全局负向提示词：**

```text
neon, neon green skin, green face, grey-green skin, cyan-magenta color cast, flat vector art, thick black outline, chibi, comic panel, exaggerated cartoon expression, different protagonist, different hairstyle, different outfit, facial distortion, deformed hands, extra fingers, missing fingers, duplicate phone, multiple phones, readable text, gibberish text, watermark, logo, subtitles, UI elements
```

### 强制画面规则

1. 小杰始终是短黑发、白色圆领短袖、深灰长裤；不得突然换成彩衣、长袖、绿脸或夸张头型。
2. 默认场景是同一间夜间寝室：深蓝窗外、灰窗帘、蓝灰床铺、棕色木桌、暖橙台灯。S4 的鞋店/餐厅允许切换地点，但服装、脸、发型与蓝橙柔和光影必须延续。
3. 每张图最多出现一部黑色手机；避免双手同时握手机。手机屏幕必须留空或虚化，所有可读文字、聊天、转账金额由后期 HTML/UI 叠加，不能让模型生成。
4. 不要分屏、拼贴、三段式、黑边或海报式排版；每张都是一张全屏单镜头关键帧。

## 4. 22 个按台词切分的 Flux 故事板任务

> 说明：`时长`是后续 LTX 单镜头建议时长，不是本任务生成视频。后续每张图仅生成一段 `3–5` 秒的微动作视频；长场景由多条短片段剪辑而成。

### S1：诱饵

#### S1-01｜旁白｜“深夜，小杰收到一条兼职返利消息。”

- **Seed：** `2101`；**时长：** `4s`；**输出：** `anti_fraud_v2_s01_01_narrator_seed2101.png`
- **正向增量：** `medium close three-quarter shot in the same dorm at night, Xiao Jie sits on the bed beside the wooden desk, looking down at one black smartphone held in one hand, neutral curiosity, warm desk lamp on the upper left, deep blue night window behind him`
- **负向增量：** `bright daytime, oversized phone, second phone, visible generated message text`
- **LTX 微动作备注：** 固定镜头；自然呼吸、一次眨眼、视线向手机轻微下移。
- **验收重点：** 构图必须接近 R02；手机屏幕为后期 UI 留出干净区域。

#### S1-02｜诈骗者｜“完成任务就能返现，先试一单，没有风险。”

- **Seed：** `2102`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s01_02_scammer_seed2102.png`
- **正向增量：** `over-the-shoulder medium shot, Xiao Jie in the same dorm listens to a phone notification, one black smartphone in the foreground with a blank dark screen reserved for later UI overlay, his face partially visible and curious, stable blue and amber lighting`
- **负向增量：** `visible chat text, scammer appearing in person, second character, split screen`
- **LTX 微动作备注：** 手机、手臂位置锁定；只做一次轻微眨眼与呼吸。
- **验收重点：** 诈骗者不出镜，不能生成聊天文字或第二个人物。

#### S1-03｜小杰｜“就试一次，应该不会这么巧遇到骗局吧。”

- **Seed：** `2103`；**时长：** `4s`；**输出：** `anti_fraud_v2_s01_03_xiaojie_seed2103.png`
- **正向增量：** `medium close shot, same Xiao Jie holds one phone near his chest, eyebrows slightly raised, mouth barely open, conflicted but self-assured expression, warm lamp and blue window remain in the same positions`
- **负向增量：** `wide grin, panic scream, distorted mouth, extra hand`
- **LTX 微动作备注：** 一次眨眼，眉毛极小幅抬起，表情从好奇变为犹豫。
- **验收重点：** 情绪克制，不能直接演成崩溃或喜剧表情。

### S2：甜头

#### S2-01｜旁白｜“第一笔小额返款很快到账，防备心也跟着松了下来。”

- **Seed：** `2201`；**时长：** `4s`；**输出：** `anti_fraud_v2_s02_01_narrator_seed2201.png`
- **正向增量：** `same dorm and same composition, a soft cool phone glow gently reflects on Xiao Jie's natural skin, his shoulders relax slightly, restrained relief, blank phone screen reserved for a later success notification overlay`
- **负向增量：** `green face, glowing red eyes, neon light, generated payment text`
- **LTX 微动作备注：** 轻微呼气，肩膀放松极小幅度，眼神仍停在手机上。
- **验收重点：** 肤色必须自然；任何荧光绿肤色直接拒绝。

#### S2-02｜小杰｜“真的到账了，原来这么简单。”

- **Seed：** `2202`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s02_02_xiaojie_seed2202.png`
- **正向增量：** `medium close three-quarter shot, same Xiao Jie has a small restrained smile while looking at one phone, relaxed eyes, no exaggerated happiness, warm amber desk lamp and deep blue window`
- **负向增量：** `laughing with open mouth, green skin, chibi face, duplicate phone`
- **LTX 微动作备注：** 嘴角微上扬、一次自然眨眼；镜头不动。
- **验收重点：** 只允许“松懈”，不允许夸张狂喜。

#### S2-03｜诈骗者｜“额度越高，佣金越多。”

- **Seed：** `2203`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s02_03_scammer_seed2203.png`
- **正向增量：** `side medium shot in the same dorm, Xiao Jie looks at a blank dark phone screen, a very slight tempted expression, warm lamp rim light, blue night background, no other person`
- **负向增量：** `visible text, numbers, second character, neon advertisement, green color cast`
- **LTX 微动作备注：** 固定镜头；眼神停留、一次小眨眼、嘴角恢复平静。
- **验收重点：** 不要把诈骗者画成真人或屏幕头像；只给后期 UI 留位。

### S3：陷阱

#### S3-01｜旁白｜“接着，所谓的客服把他拉进群，任务金额一次比一次大。”

- **Seed：** `2301`；**时长：** `4s`；**输出：** `anti_fraud_v2_s03_01_narrator_seed2301.png`
- **正向增量：** `later at night in the same dorm, medium side shot at the wooden desk, Xiao Jie leans slightly toward one blank phone, brow beginning to furrow, the window is darker and the lamp is warm, quiet tension`
- **负向增量：** `multiple screens, readable group chat, cyberpunk neon, different room`
- **LTX 微动作备注：** 微呼吸、一次眨眼、眉心从平缓变轻皱。
- **验收重点：** 寝室锚点与 S1 连续，不得切成霓虹办公室。

#### S3-02｜诈骗者｜“您的账户需要升级，缴纳保证金后，全部资金会一起返还。”

- **Seed：** `2302`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s03_02_scammer_seed2302.png`
- **正向增量：** `over-the-shoulder close medium shot, one black smartphone with an intentionally blank screen held in one hand, Xiao Jie's worried eyes visible above the phone, same blue and amber dorm lighting`
- **负向增量：** `account upgrade text, payment text, visible numbers, extra fingers, second phone`
- **LTX 微动作备注：** 手和手机完全固定；只做眼睛下移与一次眨眼。
- **验收重点：** 所有“升级/保证金”文字必须以后期叠加，故事板中不得出现乱码。

#### S3-03｜小杰｜“已经投了这么多，不能在这一步放弃。”

- **Seed：** `2303`；**时长：** `4s`；**输出：** `anti_fraud_v2_s03_03_xiaojie_seed2303.png`
- **正向增量：** `medium close front three-quarter shot, same Xiao Jie sits rigidly at the desk, one phone lowered near his chest, conflicted determined expression, eyebrows drawn together, natural skin, soft shadows`
- **负向增量：** `crying, angry shouting, heroic pose, black hoodie, facial morphing`
- **LTX 微动作备注：** 呼吸略紧、下颌轻收、一次慢眨眼；无镜头移动。
- **验收重点：** 表演是自我说服，不是愤怒或英雄化。

#### S3-04｜旁白｜“沉没成本，让他把怀疑压了下去。”

- **Seed：** `2304`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s03_04_narrator_seed2304.png`
- **正向增量：** `quiet profile medium close shot, Xiao Jie lowers his gaze at the same desk, one black phone rests face up but blank on the desk, his hand stays beside it, worried expression restrained by determination`
- **负向增量：** `phone text, stack of money, extra objects, visual glitch, grey-green face`
- **LTX 微动作备注：** 一次长眨眼、很小的叹气感；手机不动。
- **验收重点：** 不能出现夸张钞票、霓虹特效或变形侧脸。

### S4：膨胀

#### S4-01｜旁白｜“到账记录和群里的炫耀，让小杰以为自己找到了赚钱捷径。”

- **Seed：** `2401`；**时长：** `4s`；**输出：** `anti_fraud_v2_s04_01_narrator_seed2401.png`
- **正向增量：** `same dorm at night, Xiao Jie looks at one blank phone and allows himself a small confident smile, medium three-quarter shot, warmer amber light but still natural and cinematic, no readable screen content`
- **负向增量：** `money rain, casino, neon signs, visible chat text, green skin`
- **LTX 微动作备注：** 微笑轻微形成、一次眨眼、手机固定。
- **验收重点：** 先在寝室建立“膨胀”，不要改成网红炫富广告。

#### S4-02｜小杰｜“等这单结算，我请大家吃饭，再买双一直想要的鞋。”

- **Seed：** `2402`；**时长：** `4s`；**输出：** `anti_fraud_v2_s04_02_xiaojie_seed2402.png`
- **正向增量：** `same Xiao Jie in a tasteful warm shoe store, same white t-shirt and dark charcoal pants, seated on a shoe bench trying one white and blue sneaker, modest pleased expression, refined anime lighting, natural skin, no brand logos`
- **负向增量：** `different hairstyle, colorful jacket, exaggerated shopping bags, flat comic coloring, neon shop, logo, text`
- **LTX 微动作备注：** 只做一次眨眼和轻微低头看鞋；鞋、脚和镜头固定。
- **验收重点：** 必须与 R04 同一人同一套服装；若脸或比例漂移，拒绝。

#### S4-03｜旁白｜“可那些热闹的群友，都是骗子安排好的演员。”

- **Seed：** `2403`；**时长：** `4s`；**输出：** `anti_fraud_v2_s04_03_narrator_seed2403.png`
- **正向增量：** `back in the same dorm, over-the-shoulder shot, Xiao Jie sees a blank phone interface with soft neutral chat-bubble shapes but absolutely no letters, his smile is fading, cinematic blue and amber lighting`
- **负向增量：** `readable chat bubbles, real people emerging from phone, split screen, neon magenta cyan, monster faces`
- **LTX 微动作备注：** 眼神从松懈变为短暂迟疑；屏幕与手机保持静止。
- **验收重点：** 群友仅通过后期 UI 呈现，不能生成多张陌生角色脸。

### S5：收割

#### S5-01｜旁白｜“很快，骗子抛出了最后一道门槛：五万元保证金。”

- **Seed：** `2501`；**时长：** `4s`；**输出：** `anti_fraud_v2_s05_01_narrator_seed2501.png`
- **正向增量：** `same dorm, tense medium close shot, Xiao Jie holds one blank dark phone near his chest, eyes widen slightly, brow tightens, the warm desk lamp is dimmer against the deep blue night`
- **负向增量：** `50000 text, money text, payment interface, neon green light, extra hands`
- **LTX 微动作备注：** 一次短眨眼、轻吸气、眉心收紧；手机不动。
- **验收重点：** 金额和红色确认按钮由后期 UI 合成，模型不得生成。

#### S5-02｜诈骗者｜“这是最后一次认证，转完立刻能提现，错过名额就作废。”

- **Seed：** `2502`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s05_02_scammer_seed2502.png`
- **正向增量：** `side medium shot at the same desk, Xiao Jie stares at one blank phone placed upright on the desk, tense shoulders, one hand resting naturally beside the phone, no second person`
- **负向增量：** `scammer visible, readable text, confirmation button, hand close-up, deformed fingers`
- **LTX 微动作备注：** 只做呼吸和眼睛下移；手、手机、镜头全部固定。
- **验收重点：** 避免手指点击特写，降低后续 LTX 手部变形概率。

#### S5-03｜小杰｜“我先想办法凑钱，马上就能把前面的钱全都拿回来。”

- **Seed：** `2503`；**时长：** `4s`；**输出：** `anti_fraud_v2_s05_03_xiaojie_seed2503.png`
- **正向增量：** `medium close three-quarter shot in the same dorm, Xiao Jie sits at the desk with one phone in one hand and a simple closed wallet on the desk, worried but self-persuading expression, natural blue and amber lighting`
- **负向增量：** `piles of cash, bank logo, extra phone, exaggerated panic, neon`
- **LTX 微动作备注：** 嘴唇轻抿、一次慢眨眼、微弱呼吸；钱包和手机位置不动。
- **验收重点：** 不要出现钞票堆或银行标志，避免广告/诈骗视觉误导。

#### S5-04｜母亲｜“怎么突然要这么多钱？你是不是遇到什么事了？”

- **Seed：** `2504`；**时长：** `4s`；**输出：** `anti_fraud_v2_s05_04_mother_seed2504.png`
- **正向增量：** `same Xiao Jie in profile in the same dorm, holding one black phone to his ear, guilty and tense expression, mother is voice only and does not appear in frame, warm desk lamp, deep blue night window`
- **负向增量：** `mother visible, second person, second phone, crying face, distorted ear or hand`
- **LTX 微动作备注：** 固定镜头；一次小眨眼、眼神回避、轻微吞咽感。
- **验收重点：** 母亲绝不出镜；手机贴耳但手指必须完整自然。

#### S5-05｜小杰｜“没事，我只是临时周转一下。”

- **Seed：** `2505`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s05_05_xiaojie_seed2505.png`
- **正向增量：** `same dorm after the call, Xiao Jie lowers one phone onto the wooden desk, medium close shot, forced calm expression hiding guilt, eyes avoid the phone, warm lamp and blue window unchanged`
- **负向增量：** `button pressing close-up, readable phone UI, multiple hands, green skin, dramatic tears`
- **LTX 微动作备注：** 手机已静置；只做一次呼气、视线偏开、嘴角轻微收紧。
- **验收重点：** 不生成手指点击“确认转账”；该动作以后期 UI 或剪辑表达。

### S6：醒悟

#### S6-01｜旁白｜“转账完成后，群聊忽然解散，所有联系人都失去了回应。”

- **Seed：** `2601`；**时长：** `4s`；**输出：** `anti_fraud_v2_s06_01_narrator_seed2601.png`
- **正向增量：** `same dorm near midnight, the desk lamp is very soft, Xiao Jie stares at one black phone with a blank dark screen, medium close shot, shocked stillness, natural skin and restrained blue shadows`
- **负向增量：** `glitch art, green neon, disappearing body, readable group chat, sci-fi interface`
- **LTX 微动作备注：** 固定镜头；一次长眨眼、呼吸变浅、视线停在手机上。
- **验收重点：** “群聊消失”仅由后期 UI 表达，人物不能变成故障特效。

#### S6-02｜系统提示｜“您拨打的号码是空号，请查证后再拨。”

- **Seed：** `2602`；**时长：** `3.5s`；**输出：** `anti_fraud_v2_s06_02_system_seed2602.png`
- **正向增量：** `same Xiao Jie in side profile, one black phone to his ear, his face has a quiet realization, same dorm window and lamp, no other person, cinematic anime frame`
- **负向增量：** `system robot, floating text, extra character, crying distortion, neon UI`
- **LTX 微动作备注：** 手机和手固定；一次缓慢眨眼、肩膀轻微下沉。
- **验收重点：** 系统只有声音；画面没有系统机器人、字幕或乱码。

#### S6-03｜小杰｜“我被骗了……我现在就报警。”

- **Seed：** `2603`；**时长：** `4s`；**输出：** `anti_fraud_v2_s06_03_xiaojie_seed2603.png`
- **正向增量：** `medium close front three-quarter shot, same Xiao Jie sits upright in the same dorm, one phone held low in one hand, regretful but newly resolved expression, moist eyes without tears falling, natural warm skin, blue and amber light`
- **负向增量：** `screaming, collapse, tears streaming, police visible, distorted face, multiple phones`
- **LTX 微动作备注：** 先短暂停顿，再一次眨眼，眼神从失焦变为坚定；镜头不动。
- **验收重点：** 是克制的清醒，不是夸张崩溃；不能出现警察或第二角色。

#### S6-04｜旁白｜“刷单返利不是赚钱机会，而是一步步掏空你的骗局。”

- **Seed：** `2604`；**时长：** `4s`；**输出：** `anti_fraud_v2_s06_04_narrator_seed2604.png`
- **正向增量：** `final quiet medium shot in the same dorm before dawn, Xiao Jie places one phone on the desk and looks forward with a sober resolved expression, warm desk lamp, deep blue night window, clean negative space in the upper third for a later warning end card`
- **负向增量：** `generated warning text, logo, police station, sunrise daylight, neon, comic panel, black borders`
- **LTX 微动作备注：** 一次自然眨眼、轻微呼吸；手机和构图固定。
- **验收重点：** 上方留白必须干净，供最终警示语后期叠加；禁止模型生成标语。

## 5. 输出与 Seed 记录格式

每完成一张 PNG，在回复中用下列 JSON 行记录；不要另写工作流或配置文件：

```json
{
  "task_id": "S1-01",
  "speaker": "narrator",
  "line": "深夜，小杰收到一条兼职返利消息。",
  "model": "flux1-schnell-fp8.safetensors",
  "seed_requested": 2101,
  "seed_used": 2101,
  "width": 704,
  "height": 1248,
  "steps": 4,
  "cfg": 1.0,
  "sampler": "euler",
  "scheduler": "simple",
  "positive_prompt": "完整实际提交的正向提示词",
  "negative_prompt": "完整实际提交的负向提示词",
  "output_path": "D:\\IT\\AI_vido\\ComfyUI\\output\\anti_fraud_v2_s01_01_narrator_seed2101.png",
  "result": "pass | rejected",
  "rejection_reason": null
}
```

输出文件名只能使用本任务包指定的名称；若因拒绝条件换 seed 重跑，则替换末尾 seed，例如：`anti_fraud_v2_s01_01_narrator_seed3101.png`，并在记录中保留原 seed 和拒绝原因。

## 6. 验收与拒绝标准

### 通过条件

- 小杰与 R01–R04 的脸型、短黑发、白 T 恤、深灰裤一致；六幕至少可被人工一眼认作同一人。
- 肤色自然，画风接近 `flux_fixed_00001_.png`：精致线稿、柔和渐变赛璐璐阴影、蓝橙夜景光，而非旧片源的平涂漫画。
- 一部手机、自然手指、无变脸、无双手/双手机冲突。
- 所有画面是全屏竖屏单镜头；无三段式、无拼贴、无黑边、无文字和水印。
- 每张图都能用于后续固定镜头 LTX 微动作，不依赖大幅肢体、镜头运动或生成可读 UI。

### 直接拒绝，不进入 LTX

- 绿脸、灰绿皮肤、青绿/洋红霓虹主色、粗黑线极简平涂、夸张漫画脸。
- 角色脸、发型、白 T 恤或年龄明显偏离四视图；S4 也不能换人。
- 多手机、双手握手机、额外/缺失手指、手机与手部融合、面部畸形。
- AI 生成可读文字、乱码、金额、转账按钮、聊天记录、Logo、水印或字幕。
- 分屏、三段式、海报排版、黑边、镜头内出现诈骗者/母亲/警察等非小杰角色。

## 7. 最终回报格式

完成后按顺序回报：

1. 四视图路径与每张是否通过；
2. 22 个任务的 JSON 记录（不可省略 seed）；
3. 通过清单、拒绝清单与重跑次数；
4. 明确列出“可交给 Claude Code 生成 LTX”的 PNG 路径；
5. 若任一镜头未通过，不得以“差不多”标记通过，必须写 `blocked` 并说明拒绝原因。
