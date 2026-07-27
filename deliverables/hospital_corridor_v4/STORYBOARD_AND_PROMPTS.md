# 《系鞋带》ComfyUI 电影短片制作报告

版本：1.0  
画幅：竖屏 9:16  
建议成片时长：约 39 秒  
目标设备：NVIDIA RTX 5070 Ti 16GB  

## 1. 项目概述

### 剧情梗概

深夜医院走廊，一个年轻男人收到母亲抢救失败的消息，却因为年幼女儿在身边，只能蹲下给她系鞋带，默默把眼泪憋回去。

### 创作定位

- 类型：现实主义亲情短片
- 情绪曲线：等待 → 噩耗 → 压抑 → 借系鞋带掩饰崩溃 → 恢复父亲身份
- 视觉基调：冷白、青灰、安静、克制
- 表演原则：不嚎哭、不捶墙、不夸张张嘴；悲伤主要通过眼神、呼吸、喉结和手指表达
- 核心视觉母题：一个人低下头，既是为了藏住眼泪，也是为了照顾孩子

## 2. 人物档案 Character Bible

### 2.1 主角：林默

- 姓名/代号：【林默／父亲】
- 年龄与体型：【31岁，中国男性，约178cm，清瘦，肩膀略窄，长期疲惫造成轻微含胸】
- 外貌特征：【偏长椭圆脸；下颌线清晰但不尖锐；肤色偏白且略显憔悴；内双深棕色眼睛；眼下有淡青色疲惫痕迹；眉毛平直、浓度适中；鼻梁挺直；薄唇；下巴有极淡青色胡茬；右眉尾下方有一颗很小的浅褐色痣】
- 发型：【黑色短发；侧面修短；顶部约4厘米；自然侧分；发丝略微凌乱；不染发、不卷发】
- 服装描述：【深炭灰色短款羊毛外套，哑光黑色纽扣，始终敞开；米白色圆领针织衫；深灰色直筒长裤；黑色低帮皮鞋；左腕佩戴黑色皮带简约腕表；无帽子、无眼镜、无首饰】
- 核心气质：【沉静、克制、有责任感；接近崩溃时仍本能地优先保护女儿】
- 表演限制：【最多出现一滴眼泪；不嚎哭、不跪地崩溃、不做夸张面部扭曲】

固定英文身份锚点：

```text
Lin Mo, a 31-year-old slim Chinese father, long oval face, clearly defined but not sharp jawline, pale slightly exhausted skin, straight medium-thick eyebrows, dark-brown hooded eyes, faint bluish under-eye circles, straight nose bridge, thin lips, extremely subtle dark stubble on the chin, a tiny light-brown mole directly below the outer end of his right eyebrow, short black hair with closely trimmed sides and a four-centimeter slightly messy side-parted top, restrained and responsible temperament
```

固定英文服装锚点：

```text
wearing an open charcoal-gray short wool coat with matte-black buttons, a cream crew-neck knitted sweater, dark-gray straight-leg trousers, black low-cut leather shoes, a minimalist black leather-strap wristwatch on his left wrist, no glasses, no jewelry, no hat
```

### 2.2 配角：林小满

- 姓名/代号：【林小满／女儿】
- 年龄与体型：【5岁，中国女孩，身形娇小，约108cm】
- 外貌特征：【圆润小脸；深棕色杏眼；齐眉薄刘海；神态天真、困倦】
- 发型：【黑色及肩直发；左右各用一枚暗红色小发夹固定】
- 服装描述：【雾霾蓝色连帽羽绒服；浅灰色打底裤；白色运动鞋；浅黄色儿童小书包】
- 核心气质：【安静、依赖父亲；不哭闹；通过靠近、观察和轻触表达关心】

固定英文身份锚点：

```text
Lin Xiaoman, a petite five-year-old Chinese girl, round childlike face, dark-brown almond eyes, thin eyebrow-length bangs, shoulder-length straight black hair held by one muted-red hair clip on each side, wearing a dusty-blue hooded puffer jacket, light-gray leggings, white sneakers and a pale-yellow child backpack
```

### 2.3 场景连续性

- 地点：深夜综合医院住院部走廊
- 固定元素：冷白荧光灯、浅青灰墙面、灰白地砖、蓝色塑料候诊椅、红色“抢救中”灯牌、磨砂玻璃抢救室门
- 色彩：冷白与青灰为主；米白针织衫和浅黄书包提供少量暖色
- 鞋带状态：镜头01—05保持右脚鞋带松开；镜头05末系紧；镜头06—08保持系紧
- 医生只作为信息触发者，不建立独立特写

## 3. 人物参考图提示词

工作顺序：先生成版本A并确定唯一脸部母版，再借助 IPAdapter FaceID、PuLID 或 InstantID 生成版本B和版本C。

### 3.1 版本A：主角面部母版

尺寸：768×1024

```text
cinematic identity reference portrait of Lin Mo, a 31-year-old slim Chinese father, long oval face, clearly defined but not sharp jawline, pale slightly exhausted skin, straight medium-thick eyebrows, dark-brown hooded eyes, faint bluish under-eye circles, straight nose bridge, thin lips, extremely subtle dark stubble on the chin, a tiny light-brown mole directly below the outer end of his right eyebrow, short black hair with closely trimmed sides and a four-centimeter slightly messy side-parted top, restrained and responsible temperament,

wearing an open charcoal-gray short wool coat with matte-black buttons and a cream crew-neck knitted sweater, minimalist black leather-strap wristwatch, no glasses, no jewelry, no hat,

half-length portrait from chest upward, body facing the camera, head facing forward, direct neutral gaze, lips gently closed, shoulders relaxed, both ears visible, hands outside the frame, centered symmetrical composition, plain desaturated blue-gray studio background,

soft large-window key light from camera left at 45 degrees, subtle neutral fill light, soft shadow beneath the jaw, realistic skin texture, visible pores, natural facial asymmetry, subdued cool-neutral color grading, 50mm full-frame lens, eye-level camera, f/4, sharp focus on both eyes, high facial detail, photorealistic cinematic casting portrait, emotionally restrained, consistent character design, no beauty retouching
```

### 3.2 版本B：主角全身服装母版

尺寸：768×1024

```text
full-body cinematic character reference of the exact same Lin Mo, a 31-year-old slim Chinese father, approximately 178 centimeters tall, narrow shoulders, slightly tired posture with a very subtle forward hunch, long oval face, clearly defined but not sharp jawline, pale slightly exhausted skin, straight medium-thick eyebrows, dark-brown hooded eyes, faint bluish under-eye circles, straight nose bridge, thin lips, extremely subtle chin stubble, a tiny light-brown mole directly below the outer end of his right eyebrow, short slightly messy side-parted black hair with closely trimmed sides,

wearing an open charcoal-gray short wool coat ending below the hips, matte-black buttons, cream crew-neck knitted sweater, dark-gray straight-leg trousers, black low-cut leather shoes, minimalist black leather-strap wristwatch on his left wrist, no glasses, no jewelry, no hat,

standing naturally with feet shoulder-width apart, arms relaxed beside the body, fingers naturally separated, body and face directed toward the camera, restrained neutral expression, entire figure visible from hair to shoe soles, generous empty margin above the head and beneath the shoes, centered front-view composition,

plain seamless light blue-gray studio background, soft diffused natural light, gentle contact shadow beneath the shoes, evenly exposed dark clothing with visible wool and knitted fabric texture, realistic body proportions, 50mm full-frame lens, eye-level camera positioned at chest height, minimal perspective distortion, f/5.6, photorealistic cinematic wardrobe reference, accurate hands, accurate footwear, consistent identity, subdued cool-neutral color palette
```

### 3.3 版本C：父女关系与比例母版

尺寸：1024×1024

```text
cinematic full-body relationship reference featuring exactly two clearly separated people, the exact same Lin Mo and his five-year-old daughter Lin Xiaoman,

on the left stands Lin Mo, a 31-year-old slim Chinese father, approximately 178 centimeters tall, long oval face, clearly defined but not sharp jawline, pale slightly exhausted skin, straight medium-thick eyebrows, dark-brown hooded eyes, faint bluish under-eye circles, straight nose bridge, thin lips, extremely subtle chin stubble, a tiny light-brown mole directly below the outer end of his right eyebrow, short slightly messy side-parted black hair with closely trimmed sides, wearing an open charcoal-gray short wool coat with matte-black buttons, cream crew-neck knitted sweater, dark-gray straight-leg trousers, black low-cut leather shoes, black leather-strap wristwatch on his left wrist,

on the right stands Lin Xiaoman, his petite five-year-old Chinese daughter, approximately 108 centimeters tall, round childlike face, dark-brown almond-shaped eyes, thin eyebrow-length bangs, shoulder-length straight black hair, one muted-red hair clip on each side, wearing a dusty-blue hooded puffer jacket, light-gray leggings, clean white sneakers and a pale-yellow child backpack,

father and daughter standing side by side with a small natural gap between their bodies, the father's left hand gently holding the daughter's right hand, both facing the camera, neutral calm expressions, no crying, no smile, complete bodies visible, correct adult-to-child height ratio, centered balanced composition,

plain desaturated blue-gray studio background, soft diffused natural light from camera left, gentle neutral fill, subtle floor contact shadows, realistic skin and fabric textures, 50mm full-frame lens, eye-level camera positioned near the father's waist height, f/5.6, deep enough focus for both faces, photorealistic cinematic casting and wardrobe reference, subdued colors, consistent character identities, anatomically correct hands, exactly two people
```

### 3.4 参考图通用负向提示词

```text
anime, illustration, painting, 3d render, game character, plastic skin, waxy skin, excessive skin smoothing, glamour photography, fashion model pose, smiling broadly, open mouth, crying, tears, exaggerated sadness, heavy makeup, beard, thick mustache, glasses, hat, jewelry, different hairstyle, dyed hair, curly hair, round male face, square male face, missing eyebrow mole, duplicated mole, facial tattoo, long coat, black turtleneck, suit, tie, medical uniform, incorrect clothing color, buttoned coat, hands in pockets, cropped head, cropped feet, fisheye lens, wide-angle facial distortion, dutch angle, dramatic colored lighting, neon light, overexposure, underexposure, low resolution, blurry eyes, asymmetrical eyes, cross-eyed, malformed hands, fused fingers, extra fingers, missing fingers, extra limbs, duplicated person, text, logo, watermark
```

双人图追加：

```text
three people, extra child, two fathers, adult-sized child, child-sized adult, fused bodies, merged hands, matching adult clothing, school uniform, pink jacket
```

### 3.5 文生图参数

| 项目 | SDXL建议值 | Flux量化/FP8建议值 |
|---|---:|---:|
| 尺寸 | 768×1024；双人1024×1024 | 768×1024或1024×1024 |
| Batch | 1 | 1 |
| Steps | 28–34，起点30 | 20–28 |
| CFG/Guidance | 4.5–6.0，起点5.0 | 2.5–3.5 |
| Sampler | DPM++ 2M SDE | 按对应工作流 |
| Scheduler | Karras | 按对应工作流 |
| 精度 | FP16 | FP8或量化 |
| 高分修复 | 首轮关闭 | 首轮关闭 |
| VAE Tiling | 通常不需要 | OOM时启用 |

## 4. 分镜与技术方案总表

| 镜头 | 景别/角度/运镜 | 构图与Hero Motion | 氛围 | 时长 | 建议方案 |
|---|---|---|---|---:|---|
| 01 | 大全景；平视；极缓慢推近 | 父女坐于走廊下方偏右。【交握双手前倾坐姿】→【缓慢抬眼望红灯并深呼吸】→【凝视红灯，双手仍扣紧】；轻微、缓慢 | 悬而未决 | 5秒 | LTX‑2.3 I2V或FramePack；推镜后期完成 |
| 02 | 中近景；平视；固定 | 林默左侧、女儿虚化右前景。【前倾凝视门口】→【听到结果后松开双手、背部僵直】→【双手分置膝上，十指微曲】；轻微、正常 | 噩耗落下 | 5秒 | LTX‑2.3；人物SAM2分层，门单独处理 |
| 03 | 面部特写；平视略侧；极慢推 | 右眉尾小痣清晰。【睁眼凝视】→【收紧下颌、吞咽、慢眨眼】→【嘴角恢复平直，视线下移】；极轻微、缓慢 | 瞬间失重 | 4秒 | LivePortrait面部驱动 |
| 04 | 双人中景；女儿视线高度轻仰；缓慢下移 | 父亲从座位下降。【坐直扶椅沿】→【前倾屈膝，身体垂直下降】→【左膝点地，单膝跪姿】；中等、缓慢 | 从儿子切换为父亲 | 5秒 | Wan2.2 Animate Move＋DWPose＋SAM2 |
| 05 | 手鞋特写；轻俯；固定 | 手、腕表、鞋带填满画面。【双手悬于鞋带上方】→【交叉、收紧、绕环，首次失败后重试】→【蝴蝶结系紧】；轻微、缓慢 | 悲伤转移到手指 | 6秒 | 三关键帧＋分段LTX/局部插值；严格拒绝手部畸变 |
| 06 | 面部近特写；女儿肩后；固定微推 | 一滴泪停在右下眼睑。【低头按住鞋面】→【闭眼吸气，一滴泪滑下，右拇指擦过】→【抬下巴，极淡安抚微笑】；极轻微、缓慢 | 情绪峰值 | 5秒 | LivePortrait底层＋局部Wan/泪痕合成 |
| 07 | 双人中近景；女儿视线高度；固定 | 父女同高。【林默跪姿注视，女儿手臂下垂】→【女儿抬右手触右颊，父亲慢眨眼并用左手覆盖】→【两手保持接触】；轻微、缓慢 | 无言理解 | 5秒 | 双层Wan Animate＋两路DWPose＋SAM2 |
| 08 | 背面中远景；平视；缓慢后拉 | 父女居中离开。【并肩站立、双手下垂】→【父亲伸左手牵女儿右手，同步前行】→【背影缩小，父亲低头看她后向前】；中等、缓慢 | 克制余韵 | 4秒 | LTX‑2.3；走路生成、后拉运镜后期完成 |

## 5. 最终视频生成提示词

以下提示词已包含主体、场景、起止动作、镜头语言与光影氛围。

### Shot 01

```text
The exact same Lin Mo, a 31-year-old slim Chinese father with a long oval face, straight eyebrows, dark-brown hooded eyes, faint bluish under-eye circles, a tiny light-brown mole directly below the outer end of his right eyebrow, short slightly messy side-parted black hair, an open charcoal-gray wool coat, cream crew-neck sweater, dark-gray trousers and a black leather-strap wristwatch, sits beside the exact same five-year-old Lin Xiaoman in a dusty-blue hooded puffer jacket, light-gray leggings, white sneakers and a pale-yellow backpack. Her right shoelace is visibly untied.

They sit on blue plastic waiting chairs in a quiet general-hospital corridor late at night, with cool-white fluorescent ceiling lights, pale blue-gray walls, gray-white tiled floor, frosted emergency-room doors and a small distant red emergency light.

Start: Lin Mo sits on the front edge of the chair, elbows resting on his knees, both hands tightly clasped, while his daughter leans quietly beside his right arm. Motion: with very small amplitude and slow speed, he gradually raises his eyes toward the distant red emergency light and completes one restrained deep breath; only his chest and shoulders rise slightly. End: his gaze remains fixed on the red light and his hands remain tightly clasped; the daughter stays almost still.

Vertical 9:16 cinematic wide establishing shot, eye-level camera, symmetrical corridor composition, father and daughter in the lower-right third, extremely slow controlled dolly-in, no pan, no handheld shake, 35mm lens. Cold diffused overhead fluorescent light, realistic low-contrast exposure, quiet suspended tension, restrained natural acting, photorealistic cinematic realism, stable architecture and stable identities.
```

参数：LTX `704×1248 / 97帧 / 25fps`；首尾停帧补足5秒；推镜优先后期完成。

### Shot 02

```text
The exact same Lin Mo with the fixed long oval face, dark-brown hooded eyes, right-eyebrow mole, short side-parted black hair, open charcoal-gray wool coat and cream sweater sits in the same late-night hospital corridor. His daughter remains a soft out-of-focus foreground silhouette on camera right. A doctor appears only as a partial shoulder and arm in the distant background. The frosted emergency-room door has just opened and the distant red emergency light remains unchanged.

Start: Lin Mo leans forward on the waiting chair, both hands clasped and his gaze fixed on the newly opened emergency-room door. Motion: after hearing the result, with very small amplitude and normal speed, he stops breathing briefly, slowly separates his clasped hands, straightens his back by only a few centimeters and places each hand on one knee; his fingers curl inward slightly. End: he remains rigid and silent with both hands resting separately on his knees, eyes fixed ahead and lips closed.

Vertical medium close shot at eye level, fixed tripod, Lin Mo on the left side of frame, daughter blurred in the right foreground, emergency-room door in soft background focus, 65mm lens. Cool-white hospital top light, muted colors, quiet psychological shock, no crying, no exaggerated reaction, realistic breathing and subtle finger tension, no focus pulsing.
```

参数：LTX `704×1248 / 97帧 / 25fps`；林默单独生成；医生与门作为独立背景层。

### Shot 03

```text
An extreme close-up of the exact same Lin Mo, preserving his long oval face, straight eyebrows, dark-brown hooded eyes, faint bluish under-eye circles, thin lips, subtle chin stubble and the tiny light-brown mole directly below the outer end of his right eyebrow. The hospital corridor is a stable soft blue-gray background blur with a faint distant red bokeh point.

Start: he stares forward with both eyes open, jaw relaxed and lips gently closed. Motion: with extremely small amplitude and very slow speed, he tightens his jaw, swallows once so that his Adam's apple moves downward, holds moisture along the lower eyelids, then completes one slow blink without releasing a tear. End: his lips return to a straight neutral line and his gaze slowly lowers toward his daughter outside the bottom of frame.

Vertical facial close-up, eye-level three-quarter angle, locked camera with an almost imperceptible digital push-in below three percent, 85mm portrait lens, sharp focus on both eyes. Soft cold overhead light, subtle lower-eyelid catchlight, realistic pores, natural facial asymmetry, restrained grief, no beauty retouching and no lip movement.
```

参数：LivePortrait，约4秒；低姿态强度；无需OpenPose。

### Shot 04

```text
The exact same Lin Mo in his open charcoal-gray wool coat and cream sweater sits beside the exact same five-year-old Lin Xiaoman in her dusty-blue puffer jacket and pale-yellow backpack. Her right white sneaker has an untied shoelace. They are beside blue plastic chairs in the same late-night hospital waiting area under cool-white fluorescent lights.

Start: Lin Mo sits upright on the front edge of the chair, his right hand touching the chair edge; the daughter stands still and looks down at her untied right shoe. Motion: with medium amplitude and slow speed, he presses his right hand against the chair edge, shifts his weight forward, bends both knees and lowers his torso along a controlled vertical path; his right foot remains planted while his left knee moves toward the floor. End: his left knee gently touches the floor in a one-knee kneeling posture, his head below the daughter's shoulder height, and both hands stop near his thighs without touching the shoe yet.

Vertical two-person medium shot from the daughter's eye level, slightly low angle toward the father, camera tilting downward very slowly to follow his descent, 50mm lens, no lateral movement. Cold diffused hospital light, restrained realistic movement, quiet transition from grieving son to protective father, stable clothing and exact body proportions.
```

参数：Wan Animate `416×736 / 49帧 / 16fps / Steps 12 / CFG 1.0 / Euler / simple`；DWPose驱动；SAM2仅跟踪林默。

### Shot 05

```text
A close-up showing only the exact same father's natural adult hands, his black leather-strap wristwatch on the left wrist, the cuff of his cream knitted sweater and charcoal-gray wool coat, together with the daughter's right white sneaker and its untied white shoelace. Exactly two hands and exactly one shoe are visible on the stable gray-white tiled hospital floor.

Start: both hands hover approximately three centimeters above the two loose lace ends, the left hand above the left lace and the right hand above the right lace. Motion: with small amplitude and slow deliberate speed, each hand pinches one lace end, crosses the laces and pulls them tight; the fingers form two loops, the first attempt slips loose, both hands pause for half a second, then repeat the loop-and-pull path. End: both hands pull horizontally in opposite directions until a compact symmetrical bow is tight, then stop on either side of the shoe.

Vertical insert close-up, slight overhead angle, locked tripod, 70mm macro-style lens, shoe centered, both wrists entering from the upper edge, no camera motion and no focus breathing. Soft cold fluorescent light with natural hand shadows, amplified tactile realism, subtle finger tremor, accurate anatomy and stable shoelace topology.
```

参数：K1起始、K2交叉失败、K3系紧三张关键帧；分为两段25–33帧局部生成；不要依赖OpenPose控制鞋带拓扑。

### Shot 06

```text
A close-up of the exact same Lin Mo kneeling in front of his daughter. His fixed facial features remain unchanged. The blurred shoulder of the daughter's dusty-blue puffer jacket occupies a small part of the foreground. Only one subtle tear is present beneath his right eye. The hospital corridor remains softly blurred and completely stable.

Start: Lin Mo keeps his head lowered, eyes open, both hands resting beside the daughter's shoe outside the lower edge of frame. Motion: with extremely small amplitude and slow speed, he closes both eyes for one second and inhales; a single tear travels from his right lower eyelid only to the middle of his right cheek. He raises his right thumb along a short direct path, wipes once across the tear and lowers the hand out of frame. End: he opens his eyes, raises his chin slightly and forms an extremely faint reassuring smile while keeping his lips closed.

Vertical close-up from over the daughter's shoulder, eye-level with the kneeling father, locked camera followed by a very slow subtle push-in, 85mm lens, stable focus on his eyes. Cold soft hospital top light, realistic wet tear highlight, controlled breathing, restrained grief changing into protective tenderness, no sobbing and no second tear.
```

参数：LivePortrait生成面部底层；擦拭可用短Wan驱动；泪痕优先后期跟踪合成。

### Shot 07

```text
The exact same Lin Mo remains in a one-knee kneeling posture, facing the exact same five-year-old Lin Xiaoman. Their faces, hair and clothing exactly match the approved character references. The daughter's right shoelace is now fully tied. They remain in the same quiet hospital waiting area with the frosted emergency-room door softly blurred and closed in the background.

Start: Lin Mo looks quietly at his daughter; the daughter's right arm hangs naturally beside her body and the father's left hand rests near his left thigh. Motion: with small amplitude and slow speed, the daughter raises her right hand along a direct curved path and gently places her fingertips on his right cheek. Lin Mo does not move away and completes one slow blink. He then raises his left hand and softly covers the back of her right hand. End: her fingertips remain against his cheek and his left hand remains gently over the back of her hand; both hold still and maintain eye contact.

Vertical two-person medium close shot at the daughter's eye level, fixed tripod, both faces visible in profile-three-quarter view, 65mm lens, no camera movement. Cool diffused fluorescent light, quiet wordless empathy, extremely restrained acting, stable faces, stable hands and natural father-daughter scale.
```

参数：小满与林默分成两路Wan Animate生成；每路沿用`416×736 / 49帧 / 16fps / 12步 / CFG 1.0`；DWPose＋SAM2分层合成。

### Shot 08

```text
Rear view of the exact same Lin Mo on the left and the exact same five-year-old Lin Xiaoman on the right. Lin Mo wears the same open charcoal-gray wool coat, cream sweater and dark-gray trousers. The daughter wears the same dusty-blue puffer jacket, pale-yellow backpack and white sneakers. Her right shoelace is fully tied. The same long symmetrical late-night hospital corridor extends toward a distant vanishing point under stable cool-white fluorescent lights.

Start: Lin Mo stands on his daughter's left side with his left hand hanging naturally; the daughter's right hand hangs beside her body. Motion: with medium amplitude and slow natural speed, he extends his left hand and closes it gently around her right hand. They begin walking forward together along the center of the corridor with short synchronized steps. While walking, he lowers his head slightly and glances toward her once. End: he turns his face forward again while they continue walking away, their rear silhouettes becoming gradually smaller near the corridor's vanishing point.

Vertical rear medium-wide shot, eye-level locked central perspective, extremely slow controlled dolly backward while the subjects walk away, 50mm lens, no orbit and no handheld shake. Cold neutral hospital lighting, long soft floor reflections, quiet unresolved grief and continued responsibility, subdued cinematic realism, stable architecture and no sentimental lighting change.
```

参数：LTX `704×1248 / 97帧 / 25fps`；模型只负责走路；后拉运镜后期完成。

### 5.1 视频通用负向提示词

```text
identity change, different face, different clothes, different hairstyle, beard, glasses, hat, jewelry, broad smile, screaming, exaggerated crying, melodramatic acting, multiple tears, extra people, duplicate person, age change, gender change, coat buttoned closed, black turtleneck, suit, medical uniform, warped face, deformed hands, fused fingers, extra fingers, missing fingers, extra limbs, floating objects, camera shake, fast camera movement, flicker, exposure pumping, changing background, moving walls, bending corridor, changing fluorescent lights, neon cyberpunk lighting, warm orange filter, shallow-focus flicker, low resolution, text, subtitle, logo, watermark
```

## 6. 模型与基础参数

### LTX‑2.3 I2V

- 本机已验收基线：704×1248、25fps、97帧、约3.88秒
- 适用：镜头01、02、08；镜头05仅作为分段局部尝试
- 定位：场景运动和自由运动，不用于像素级锁定
- 长镜头策略：分段生成或添加首尾停帧，不盲目增加单段帧数

### Wan2.2 Animate 14B FP8

- 本机已验证基线：416×736、49帧、16fps
- Steps：12
- CFG：1.0
- Sampler：Euler
- Scheduler：simple
- 适用：镜头04、06局部、07分层
- 配套：DWPose驱动、SAM2人物蒙版、ColorMatchV2、静态背景回贴

### LivePortrait

- 适用：无手部大面积遮挡的头肩微表情
- 推荐镜头：03；镜头06的面部底层
- 控制原则：低头姿强度、低表情强度，避免嘴部自行说话

### Motion Bucket ID

本项目使用的 LTX、Wan Animate、LivePortrait 和 FramePack 均不使用 Motion Bucket ID。该参数主要属于 Stable Video Diffusion 一类工作流，不能将示例值127直接套入上述模型。

## 7. 统一后期与验收规范

- 最终画布：1080×1920
- 最终帧率：30fps
- 编码：H.264
- 像素格式：yuv420p
- 色彩标记：BT.709
- 发布码率：约3 Mbps CBR
- 归档母版：约6 Mbps或更高
- 插帧顺序：生成 → 动作检查 → 身份检查 → 灯光检查 → 背景回贴 → ColorMatch → 插帧
- RIFE与FFmpeg插帧各输出一版，重点比较手、鞋、腿和人物接触区域
- 任何手部畸变、鞋带穿透、人物身份改变、灯光闪烁或墙面漂移均应在插帧前拒绝或修复
- 保存每个镜头的关键帧、提示词、负向提示词、模型、VAE、工作流、seed、尺寸、帧数和审核结果

## 8. 最终连续性检查清单

- [ ] 林默右眉尾下方的小痣在所有正脸和侧脸镜头中位置一致
- [ ] 林默始终为短侧分黑发、深炭灰短外套、米白针织衫
- [ ] 黑色皮带腕表始终位于林默左腕
- [ ] 小满始终为雾霾蓝羽绒服、浅黄色书包和白色运动鞋
- [ ] 镜头01—05右鞋带松开；镜头05末系紧；镜头06—08保持系紧
- [ ] 全片最多只有一滴眼泪
- [ ] 所有Hero Motion均具备清晰起始姿态、动作路径和结束姿态
- [ ] 所有生成运镜均保持缓慢稳定；复杂推拉优先在后期完成
- [ ] 镜头05和07逐帧检查手指、鞋带与接触关系
- [ ] 最终输出符合1080×1920、30fps、H.264、yuv420p和BT.709
