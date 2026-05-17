# 动漫数字人主讲视频优化方案

> 状态：MVP 已可生成，展示效果进入半自动验证阶段
> 更新：2026-05-17
> 当前重点：把已验证的 Edge-TTS、Sonic 循环角色、ComfyUI 分段背景和 FFmpeg 合成收口成稳定 provider
> 后续扩展：支持自动添加 IP 人物，但需要先做素材规范、授权边界和角色资产配置

---

## 0. 2026-05-17 实测结论

本轮围绕“动漫数字人主讲 + 语义背景 + 自有 IP 角色”完成了一轮端到端验证。

已验证输出：

| 类型 | 输出 |
|---|---|
| 本地兜底背景完整版 | `data/videos/presenter_20260516_225643.mp4` |
| 单张 ComfyUI 背景合成版 | `data/videos/presenter_20260516_225643_comfy_singlebg.mp4` |
| ComfyUI 分段背景完整版 | `data/videos/presenter_20260516_225643_comfy_full.mp4` |
| ComfyUI 背景清单 | `data/presenter/20260516_225643/comfy_full_backgrounds.json` |

当前有效流程：

```text
关键词/文案
  -> 脚本生成或读取现有文案
  -> ScriptSegmenter 分成 5 秒左右的字幕段
  -> Edge-TTS 生成每段音频
  -> 根据一组字幕提取关键动作：choose / hesitate / trust_self / explore_practice / reflect_adjust
  -> ComfyUI 按动作生成分段背景
  -> 复用 Sonic 输出的狐狸 IP 口型/微动视频作为右下数字人层
  -> 字幕层避让数字人
  -> FFmpeg 单段合成并拼接为完整版
```

关键判断：

- 合成层没有问题，ComfyUI 图片可以正确进入视频并按段切换。
- 只靠文字 prompt 让 ComfyUI 稳定生成“完整 IP 人物入镜”不可靠，容易出现角色过大、重复头部或伪文字。
- 当前更稳的策略是：视频主讲数字人使用已有 Sonic 角色层；背景里只使用 IP 元素、小摆件或后续用参考图/区域重绘控制 IP 入镜。
- ComfyUI/Flux Schnell 对“不要文字”约束仍不稳定，背景中可能出现伪中文、伪英文、海报、牌匾。正式流程必须增加背景质检和重抽。
- Edge-TTS 可作为快速测试通路；GPT-SoVITS 当前环境缺 torch，暂不作为默认通路。

下一步开发边界：

1. 把本轮半自动 ComfyUI API 调用整理为 `BackgroundProvider`，不要继续靠临时脚本。
2. 增加背景质检：检测伪文字、海报、人物过大、下方安全区被占用，失败则重抽或回退。
3. 增加背景缓存：相同 `action + subject + style + seed` 不重复生成。
4. Sonic 先作为“已有 mp4 角色层”使用；真正按每段音频重跑 Sonic 需要等 Sonic 独立环境模型路径修好。

---

## 1. 当前 MVP 状态

当前版本已经可以用本地素材生成一个离线数字人主讲视频：

```text
输入文本/关键词
  -> 脚本分段
  -> TTS 生成音频或使用现有音频
  -> 自动生成动漫风背景或使用指定背景
  -> 渲染标题、关键词标签、字幕
  -> 叠加数字人 PNG / 帧序列
  -> FFmpeg 拼接输出 mp4
```

已具备能力：

| 能力 | 当前状态 |
|---|---|
| 文本输入 | 支持 `--text` 直接输入，也支持 `--keywords` 走脚本生成 |
| TTS | 支持 Edge TTS / GPT-SoVITS，Edge 依赖网络 |
| 音频复用 | 支持 `--audio` 使用现有音频，适合先测试画面 |
| 动漫背景 | 默认 `--background-style anime`，无背景时生成本地兜底背景；ComfyUI 分段背景已半自动验证 |
| 背景语义 | 已支持按 5 秒字幕组提取动作并生成 prompt，当前动作包括选择、犹豫、信任自己、探索实践、反思调整等 |
| 数字人素材 | 支持 `na1` / `n3`、静态图、帧序列、视频层；已验证绿幕/浅色背景视频可用 `video_chroma` 抠像叠加 |
| 角色位置 | 支持 `right_bottom` / `left_bottom` / `center_bottom` |
| 角色尺寸 | 支持 `small` / `medium` / `large` |
| 字幕避让 | 字幕会根据数字人位置和尺寸调整区域；长字幕不再用 `...`，而是通过分段展示 |
| 输出 | 输出到 `data/videos/*.mp4`，中间产物在 `data/presenter/*` |

当前可测试命令示例：

```bash
python main.py presenter \
  --text "第一句用于标题。画面需要清晰，字幕不能挡住数字人。" \
  --title "展示效果测试" \
  --tts-provider edge \
  --character na1 \
  --character-position right_bottom \
  --character-size medium \
  --background-style anime \
  --output-dir data/videos
```

如果只想测试画面，不想依赖 TTS 网络：

```bash
python main.py presenter \
  --text "展示效果测试文案。" \
  --title "展示效果测试" \
  --audio data/ref_audio/role_a_new.wav \
  --character na1 \
  --background-style anime \
  --output-dir data/videos
```

---

## 2. 近期目标

MVP 已跑通，接下来不急着堆模型，先把展示效果做稳定。

优先级：

| 优先级 | 目标 | 说明 |
|---|---|---|
| P0 | 稳定画面布局 | 字幕、标题、关键词、数字人互不遮挡 |
| P0 | 固定 2-3 套画面模板 | 右下讲解、左下讲解、居中开场 |
| P1 | 动漫背景风格升级 | ComfyUI 已验证，下一步做 provider 化、缓存和质检 |
| P1 | Sonic 数字人接入 | 当前可复用 Sonic mp4 角色层；按音频重跑 Sonic 仍待环境修复 |
| P1 | 角色资产配置化 | 每个角色有独立配置，不写死路径和大小 |
| P2 | 自动添加 IP 人物 | 根据主题/账号定位自动选择或生成角色 |
| P2 | 批量生成与发布 | 生成、质检、发布全流程自动化 |

---

## 3. 推荐整体流程

```text
主题/关键词/直接文案
  |
  |-- 1. 生成/读取脚本
  |-- 2. 分段：title / caption / highlight
  |-- 3. 按段生成或匹配背景
  |       |-- 优先：预设动漫背景库
  |       |-- 其次：ComfyUI 按关键词生成
  |       |-- 兜底：程序生成 anime 背景
  |-- 4. 生成音频
  |       |-- Edge TTS 快速测试
  |       |-- GPT-SoVITS 正式音色
  |-- 5. 生成数字人画面
  |       |-- MVP：静态 PNG / FramePack 循环帧
  |       |-- 优化：Sonic 音频驱动口型
  |-- 6. 渲染文字层
  |-- 7. 合成单段视频
  |-- 8. 拼接 + BGM + 输出
```

关键原则：

- 音频时长是时间轴基准，不用预估时长。
- 背景和数字人分开生成，降低耦合。
- 数字人先小窗口叠加，降低口型瑕疵的视觉影响。
- 背景不要生成文字、人脸和复杂主体，避免和字幕/数字人抢画面。

---

## 4. 画面展示效果方案

### 4.1 基础画布

| 项 | 规格 |
|---|---|
| 画布 | 1080 x 1920 |
| 帧率 | 30 fps |
| 主要平台 | 抖音竖屏 |
| 安全边距 | 左右 54-72px，上方 54px，下方避开系统 UI |

### 4.2 布局模板

#### 模板 A：右下主讲，默认模板

适合大多数知识讲解。

```text
┌────────────────────────┐
│ 标题牌                  │
│ 关键词标签              │
│                        │
│        背景主体          │
│                        │
│ ┌────────────┐   数字人 │
│ │ 字幕框      │          │
│ └────────────┘          │
└────────────────────────┘
```

建议参数：

| 参数 | 值 |
|---|---|
| `character_position` | `right_bottom` |
| `character_size` | `medium` |
| 字幕位置 | 左下，自动避让右下数字人 |
| 适用 | 默认主讲、财经、成长、知识类 |

#### 模板 B：左下主讲

适合背景右侧有主体，或希望视觉重心在右侧。

| 参数 | 值 |
|---|---|
| `character_position` | `left_bottom` |
| `character_size` | `medium` |
| 字幕位置 | 右下，自动避让左下数字人 |
| 适用 | 右侧图表、右侧场景、对比讲解 |

#### 模板 C：居中开场

适合短视频开头 1-2 秒或 IP 人物首次亮相。

| 参数 | 值 |
|---|---|
| `character_position` | `center_bottom` |
| `character_size` | `large` |
| 字幕位置 | 中下偏上 |
| 适用 | 开场、口播强调、人设露出 |

### 4.3 字幕策略

当前字幕策略可继续沿用：

| 样式 | 用途 | 位置 |
|---|---|---|
| `title` | 第一段/开场 | 中上大字 |
| `caption` | 普通讲解 | 底部字幕框，避让数字人 |
| `highlight` | 金句/重点 | 居中大字，强描边 |

后续优化建议：

1. 增加“逐字出现”或“短句分批出现”，提升节奏感。
2. 高亮词用黄色或蓝色描边，不整句都做大字。
3. 字幕框透明度根据背景明暗自动调整。
4. 超长句强制拆短，避免字幕超过两行。

---

## 5. Sonic 数字人方案

用户倾向：用 Sonic 处理数字人，这个方向可行，建议作为 P1 接入。

### 5.1 Sonic 在本项目中的定位

Sonic 不负责整条视频，只负责生成“数字人层”：

```text
角色图 / 角色短视频 + 段落音频
  -> Sonic
  -> 口型同步数字人视频
  -> FFmpeg 缩放、抠像或透明叠加到背景
```

这样做的好处：

- 背景仍由 ComfyUI 或预设图库控制，画面更稳定。
- Sonic 出问题时可以降级为静态 PNG / FramePack 循环帧。
- 不要求 Sonic 直接生成 1080x1920，节省时间和显存。

### 5.2 推荐输入规格

| 项 | 推荐 |
|---|---|
| 人物图 | 正脸或轻微侧脸，脸部清晰 |
| 分辨率 | 原图 768px 以上，最终输出可缩到 360-540px 宽 |
| 背景 | 透明底优先，其次纯色绿幕/蓝幕 |
| 姿态 | 上半身或半身，手部不要遮脸 |
| 音频 | 每段 3-8 秒，过长先分段 |

### 5.3 输出与合成

Sonic 输出可能有三种形态，需要 wrapper 做兼容：

| 输出类型 | 处理方式 |
|---|---|
| 透明通道视频 | 直接 overlay |
| 绿幕/纯色背景视频 | FFmpeg `colorkey` 抠像后 overlay |
| 普通 RGB 视频 | 先裁剪/抠像，效果不稳时降级小窗口矩形 |

建议新增接口：

```python
class CharacterMotionProvider:
    def generate(
        self,
        character_id: str,
        audio_path: str,
        output_path: str,
        duration: float,
    ) -> str:
        ...
```

第一版实现：

- `StaticCharacterProvider`：当前 PNG / 帧序列方案。
- `SonicCharacterProvider`：调用 Sonic 生成口型视频。

---

## 6. ComfyUI 背景方案

用户倾向：用 ComfyUI 处理背景。2026-05-16 已用本机 ComfyUI `127.0.0.1:8190` 和 `flux1-schnell-fp8.safetensors` 跑通分段背景生成与合成。

### 6.1 背景生成原则

背景服务于内容，不要抢字幕和数字人。

当前 prompt 不再直接塞入中文字幕或原始关键词，而是先从一组字幕中提取动作，再生成英文画面描述。

动作规则示例：

| 动作 | 触发词 | 背景倾向 |
|---|---|---|
| `choose` | 选择、选错、决定、纠结 | 桌面上两张空白选项卡、决策场景 |
| `hesitate` | 担心、害怕、失败、不敢、迟迟 | 门口、光线、准备迈步 |
| `trust_self` | 相信自己、内心、光芒 | 镜子、自我观察、柔和光 |
| `explore_practice` | 探索、实践、找到、道路、迈出 | 手作原型、工具、尝试 |
| `record` | 记录、日记、小事、自豪 | 空白笔记本、笔、窗光 |
| `reflect_adjust` | 反思、调整、目标、计划 | 空白计划卡片、桌面整理 |
| `connect` | 朋友、导师、互相、启发 | 两杯茶、交流、抽象想法 |

Prompt 约束示例：

```text
vertical 9:16 anime illustration, clean modern slice-of-life scene,
clear narrative action, plain clean walls,
open empty lower 35 percent reserved for subtitles and presenter overlay,
no written text, no Chinese characters, no English letters, no numbers,
no signs, no posters, no book titles, no labels, no logo, no watermark
```

Negative prompt：

```text
text, letters, numbers, sign, poster, frame, wall art, logo, watermark,
close-up portrait, large animal, full-size character, extra head, malformed face
```

实测注意：

- Flux Schnell 仍可能生成伪文字，尤其是墙面、画框、书本、纸张、海报附近。
- 不建议直接用纯文字 prompt 让完整 IP 人物进入背景，角色容易过大或变形。
- 第一版应把 IP 用作小摆件、小标识或不入镜；真正 IP 入镜需要参考图控制、区域重绘或后期合成。

### 6.2 背景来源优先级

| 优先级 | 来源 | 用途 |
|---|---|---|
| 1 | 预设动漫背景库 | 最稳定，适合批量生产 |
| 2 | ComfyUI 生成 + 质检重抽 | 适合主题强相关的段落 |
| 3 | 当前程序 anime 背景 | 兜底，保证一定能出视频 |

建议目录：

```text
data/anime_backgrounds/
  classroom/
  library/
  city/
  cafe/
  desk/
  finance/
  healing/
  tech/
  abstract/
```

### 6.3 背景元数据

每张背景最好配一个 JSON，便于自动匹配：

```json
{
  "id": "classroom_sunset_001",
  "path": "data/anime_backgrounds/classroom/classroom_sunset_001.png",
  "tags": ["学习", "成长", "知识", "教室"],
  "safe_area": {
    "caption": "left_bottom",
    "character": "right_bottom"
  },
  "dominant_colors": ["sky_blue", "warm_yellow"],
  "allow_ip_character": true
}
```

---

## 7. 自动添加 IP 人物方案

后续如果要自动添加 IP 人物，建议不要一开始就“按名字生成某个知名角色”。应该先建立“项目自有 IP 角色库”，再做自动选择和自动生成。

### 7.1 先明确合规边界

| 类型 | 建议 |
|---|---|
| 自有原创 IP | 推荐，可长期使用 |
| 已授权 IP | 可以用，但需记录授权来源和使用范围 |
| 公众熟知商业角色 | 不建议自动生成或直接使用 |
| 明星/真人肖像 | 不建议自动生成或冒用 |
| “某某风格”角色 | 谨慎，避免过度贴近具体受保护形象 |

建议系统内只允许两类：

1. `owned`：自己创建的原创 IP 人物。
2. `licensed`：已经确认授权的人物。

默认不自动使用 `external_reference` 类型。

### 7.2 IP 人物资产结构

建议新增角色库：

```text
data/ip_characters/
  mentor_male_01/
    character.json
    portrait.png
    full_body.png
    transparent.png
    sonic_source.png
    poses/
      right_bottom.png
      left_bottom.png
      center_bottom.png
    thumbnails/
      cover.png
  mentor_female_01/
    character.json
    ...
```

`character.json` 示例：

```json
{
  "id": "mentor_male_01",
  "name": "青禾老师",
  "status": "owned",
  "role": "knowledge_presenter",
  "style": "anime_modern",
  "gender_presentation": "male",
  "age_band": "young_adult",
  "personality_tags": ["理性", "温和", "知识感"],
  "topic_tags": ["学习", "成长", "财经", "效率"],
  "default_position": "right_bottom",
  "default_size": "medium",
  "voice_id": "default_male_warm",
  "motion_provider": "sonic",
  "assets": {
    "transparent": "transparent.png",
    "sonic_source": "sonic_source.png",
    "fallback_static": "transparent.png"
  },
  "license": {
    "type": "owned",
    "source": "project_generated",
    "notes": "项目原创角色，可用于账号内容"
  }
}
```

### 7.3 自动选择 IP 人物

根据主题、账号定位、内容语气自动选角色。

```text
输入：
  - keywords
  - topic category
  - target audience
  - tone

输出：
  - character_id
  - voice_id
  - layout profile
```

选择规则示例：

| 内容类型 | 推荐人物 |
|---|---|
| 学习/成长/效率 | 老师型、学长型 |
| 财经/理财 | 冷静专业型 |
| 情绪/心理 | 温和陪伴型 |
| 科技/工具 | 清爽理工型 |
| 生活方式 | 轻松朋友型 |

第一版可以用规则，不必直接上复杂模型：

```python
if "理财" in keywords or "投资" in keywords:
    character_id = "finance_mentor_01"
elif "学习" in keywords or "效率" in keywords:
    character_id = "study_mentor_01"
else:
    character_id = "default_presenter_01"
```

### 7.4 自动生成 IP 人物

自动生成 IP 人物要拆成两个阶段。

#### 阶段一：半自动

人先定方向，AI 生成候选，人工挑选入库。

```text
角色设定
  -> ComfyUI/SD 生成 4-8 张候选
  -> 人工选 1 张
  -> 抠图/修脸/统一风格
  -> 生成透明图和 Sonic source
  -> 写入 character.json
```

这是推荐的第一版，因为 IP 人物会影响账号辨识度，不能完全随机。

#### 阶段二：自动化

当角色规范稳定后，再做自动创建。

```text
主题/账号定位
  -> 角色设定生成
  -> ComfyUI 生成人物
  -> 自动质检
  -> 自动抠图
  -> Sonic 可用性测试
  -> 入库为待审核状态
```

自动质检至少包括：

- 是否有清晰正脸。
- 是否没有明显文字、水印、Logo。
- 是否不是已知商业角色的高度近似形象。
- 是否适合 Sonic 口型驱动。
- 是否能抠出干净透明图。

### 7.5 IP 人物与声音绑定

IP 人物不能只是一张图，最好绑定声音和语气：

```json
{
  "character_id": "mentor_male_01",
  "voice_profile": {
    "provider": "gpt_sovits",
    "voice": "mentor_male_warm",
    "speed": 1.0,
    "emotion": "calm"
  },
  "script_style": {
    "sentence_length": "short",
    "tone": "warm_explainer",
    "opening_style": "question"
  }
}
```

这样账号会更像一个持续存在的人设，而不是每条视频临时换脸。

---

## 8. 数据结构建议

### 8.1 PresenterRequest 后续字段

当前已有：

```python
character: str
character_position: str
character_size: str
background: str
background_style: str
```

建议后续扩展：

```python
character_id: str = ""
character_profile: str = ""
character_auto: bool = False
motion_provider: str = "static"  # static | sonic
layout_profile: str = "right_presenter"
background_provider: str = "auto"  # fallback | preset | comfyui | auto
ip_policy: str = "owned_or_licensed_only"
```

### 8.2 生成结果记录

每次生成需要保存完整元数据，便于复现：

```json
{
  "video_path": "data/videos/presenter_xxx.mp4",
  "character_id": "mentor_male_01",
  "motion_provider": "sonic",
  "background_provider": "comfyui",
  "layout_profile": "right_presenter",
  "segments": [],
  "assets": [],
  "created_at": "2026-05-15"
}
```

---

## 9. 实施路线

### 阶段 1：展示效果稳定

目标：不接新模型，先让现有 MVP 的画面更像成品。

任务：

1. 固化 3 个布局模板。
2. 字幕避让、标题牌、关键词标签继续细调。
3. 为不同背景亮度做字幕框透明度策略。
4. 输出 3-5 条测试样片。

验收：

- 字幕不遮挡数字人。
- 标题、关键词、字幕层级清楚。
- 角色在小屏手机上仍然可辨认。
- 没有明显空白、压线、文字溢出。

### 阶段 2：背景升级

目标：引入背景库和 ComfyUI。

任务：

1. 建立 `data/anime_backgrounds` 背景库。
2. 定义背景元数据 JSON。
3. 做关键词到背景分类的匹配。
4. 接 ComfyUI API 作为补缺生成器。

验收：

- 无 ComfyUI 时仍能用预设库出视频。
- ComfyUI 失败时自动降级。
- 背景没有文字、水印、人脸干扰。

### 阶段 3：Sonic 数字人

目标：将静态数字人升级为口型同步数字人。

任务：

1. 封装 `CharacterMotionProvider`。
2. 接入 `StaticCharacterProvider` 保留当前能力。
3. 接入 `SonicCharacterProvider`。
4. 支持透明/绿幕/RGB 三类输出。
5. 用 3 个角色测试口型稳定性。

验收：

- 口型视频时长与音频一致。
- 失败时自动回退静态/循环帧。
- 右下中号人物在手机上口型可感知。

### 阶段 4：IP 人物库

目标：可手动添加并自动选择原创/授权 IP 人物。

任务：

1. 建立 `data/ip_characters` 目录规范。
2. 定义 `character.json`。
3. 支持 `--character` 读取 IP 角色 ID。
4. 做主题到角色的简单规则匹配。
5. 角色和音色绑定。

验收：

- 可以添加一个新 IP 人物，不改代码即可使用。
- 可以根据关键词自动选择默认角色。
- 未授权角色不会被自动使用。

### 阶段 5：自动创建 IP 人物

目标：半自动生成新 IP 人物，并进入待审核资产库。

任务：

1. 角色设定 Prompt 模板。
2. ComfyUI 生成人物候选。
3. 抠图/透明图生成。
4. Sonic 可用性预检。
5. 入库为 `pending_review`。

验收：

- 自动生成的人物不会直接发布，必须审核。
- 每个角色有来源、状态、授权记录。
- 通过审核后才能进入自动选择池。

---

## 10. 主要风险与处理

| 风险 | 影响 | 应对 |
|---|---|---|
| Sonic 对动漫脸不稳定 | 口型怪、脸变形 | 小窗口显示；失败回退静态/循环帧 |
| ComfyUI 背景不稳定 | 风格跑偏、伪文字、海报、水印感 | 背景库优先；ComfyUI 增加质检重抽；失败回退本地兜底 |
| 背景 IP 入镜不稳定 | 角色过大、重复头、抢主讲人 | 先只用 IP 小元素；完整 IP 入镜改用参考图控制或后期合成 |
| 字幕遮挡数字人 | 观感差 | 布局模板 + 安全区配置 |
| IP 人物版权风险 | 发布风险高 | 只允许 owned/licensed 自动使用 |
| 自动生成角色不一致 | 账号人设弱 | 先半自动审核，再自动化 |
| 角色和声音不匹配 | 违和 | 人物绑定 voice profile |
| 生成耗时过长 | 批量效率低 | 背景缓存、角色缓存、分段并发 |

---

## 11. 当前建议决策

建议现在先这样定：

1. 数字人尺寸暂不固定，继续保留 `small / medium / large`，默认 `medium`。
2. 默认布局用 `right_bottom + medium`。
3. Sonic 作为数字人 P1 接入，但必须保留静态/帧序列降级。
4. ComfyUI 背景作为 P1 接入，但必须保留预设库和程序背景兜底。
5. IP 人物先做“原创/授权角色库”，不要直接自动生成知名角色。
6. 自动添加 IP 人物第一版做“自动选择已有角色”，第二版再做“自动生成待审核角色”。

---

## 12. 下一步具体开发项

最小改动顺序：

1. 增加背景 provider：`fallback|preset|comfyui|auto`，把本轮半自动 ComfyUI API 调用收进代码。
2. 增加背景质检：伪文字、海报、人物过大、安全区占用时重抽或回退。
3. 增加背景缓存和 manifest：保存 prompt、seed、action、原字幕组、输出图路径。
4. 增加 `layout_profile` 配置，把现在的位置/尺寸/字幕安全区固化成模板。
5. 增加 `characters.json` 或 `data/ip_characters/*/character.json` 读取。
6. 让 `--character` 同时支持旧的 `na1`、明确路径和新的 IP `character_id`。
7. 增加 `motion_provider=static|video_chroma|sonic` 抽象层。
8. 生成结果保存完整元数据，方便复现和排查。

推荐先做第 1-3 项，因为当前最大不稳定点已经从合成层转移到“背景生成质量和可复现性”。
