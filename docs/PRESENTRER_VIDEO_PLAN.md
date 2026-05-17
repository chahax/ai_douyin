# 数字人主讲视频生成方案

> 状态：半自动验证通过，待工程化收口
> 更新时间：2026-05-17
> 核心思路：脚本分段 → 每段生成背景图 + 叠加文字 → 口型视频（小窗口） → 按时间轴拼接
> 布局：小数字人（右下角小窗口）+ 大背景图（全屏）
> 当前实现入口：`main.py presenter`、`src/content_factory/presenter_pipeline.py`、`src/content_factory/presenter/`

---

## 零、当前实现状态

已验证：

- Edge-TTS 分段生成音频。
- Sonic 已产出的狐狸角色视频可作为右下角 `video_chroma` 数字人层。
- 背景可按 5 秒字幕组提取动作并生成 ComfyUI prompt。
- ComfyUI 分段背景可以合入视频并按段切换。
- 最终完整版样片：`data/videos/presenter_20260516_225643_comfy_full.mp4`。

尚未正式化：

- ComfyUI 生成仍是半自动 API 调用，待封装为 `BackgroundProvider`。
- Sonic 目前复用已有角色视频，尚未按每段音频自动重跑。
- ComfyUI 背景可能出现伪文字、海报、IP 角色过大，需要质检重抽。

---

## 一、整体流程

```
输入：主题/关键词
│
├─ ① 脚本生成
│   └─ LLM 根据主题生成完整讲解脚本
│   └─ 输出：段落列表 [{text, duration, keywords, style}, ...]
│
├─ ② 背景图生成（每段一张）
│   └─ 提取关键词 → ComfyUI/SD 生成全屏背景图
│   └─ 输出：段落背景图列表 [image_path, ...]
│
├─ ③ 文字叠加
│   └─ 背景图 + 段落文字 → 文字排版叠加
│   └─ 输出：带文字的背景图 [bg_with_text, ...]
│
├─ ④ 配音生成
│   └─ 段落文字 → TTS 生成音频
│   └─ 输出：音频片段列表 [audio_path, ...]
│
├─ ⑤ 口型视频生成（小窗口）
│   └─ 角色图 + 每段音频 → Sonic/LivePortrait
│   └─ 输出：小口型视频片段（约 270x480）
│
├─ ⑥ 片段合成
│   └─ 背景图(带文字) + 小数字人叠加 + 配音
│   └─ 输出：视频片段列表
│
├─ ⑦ 最终拼接
│   └─ 片段拼接 + BGM
│   └─ 输出：最终 mp4
│
└─ ⑧ 发布到抖音
```

### 布局说明

```
┌─────────────────────────────────┐
│                                 │
│   ComfyUI/SD 生成的高质量背景图   │
│   （全屏，1080x1920，每段不同）   │
│                                 │
│                                 │
│  ┌─────────┐                   │
│  │ 小数字人 │  ← 缩小到右下角    │
│  │ (口型)  │    约 360x480      │
│  └─────────┘    约 1/4 屏幕     │
│                                 │
│   叠加文字（底部字幕条）           │
└─────────────────────────────────┘
```

### 为什么小窗口布局更好

| 对比项 | 大数字人（全屏） | 小数字人 + 大背景 |
|---|---|---|
| 生成分辨率 | 需要 1080x1920 | 只需 270x480 ✅ |
| 口型准确度 | 大图变形风险高 | 小图稳定 ✅ |
| 生成速度 | 慢 | 快 3-5 倍 ✅ |
| 背景质量 | 背景被压缩 | 背景全屏高质量 ✅ |
| 观感 | 单调 | 内容丰富 ✅ |
│   └─ 角色图 + 每段音频 → SadTalker
│   └─ 输出：口型视频片段 [talk_video, ...]
│
├─ ⑥ 片段合成
│   └─ 每段：背景图(带文字) + 口型视频叠加 + 配音
│   └─ 输出：视频片段列表 [clip, ...]
│
├─ ⑦ 最终拼接
│   └─ 所有片段按时间轴拼接 + BGM
│   └─ 输出：最终 mp4
│
└─ ⑧ 发布到抖音
```

---

## 二、脚本分段逻辑

### 分段规则

| 规则 | 说明 |
|---|---|
| 理想时长 | 3-5 秒/段 |
| 最短 | 不小于 2 秒 |
| 最长 | 不超过 8 秒（观感疲劳） |
| 断点依据 | 句号/感叹号天然断点 |
| 长句拆分 | 找逗号/顿号拆，字数 > 40 时触发 |
| 金句标记 | 感叹/反问/重点 → 标记 highlight 型 |

### 段落元数据结构

```python
{
    "index": 0,          # 段序号
    "text": "复利是理财中最强大的概念之一。",  # 原文
    "duration": 3.5,     # 预计时长（秒）
    "keywords": ["复利", "财富增长", "理财概念"],  # 背景图关键词
    "style": "caption",  # 文字样式：caption | highlight | title
    "voice": "zh-CN-YunjianNeural"  # 音色
}
```

### 样式类型定义

| 样式 | 用途 | 文字位置 | 背景 |
|---|---|---|---|
| `caption` | 普通讲解句 | 底部字幕条 | 半透明深色 |
| `highlight` | 金句/重点句 | 居中 | 无背景，字描边 |
| `title` | 话题引入 | 顶部 | 半透明渐变 |

---

## 三、背景图生成逻辑

### 关键词提取规则

```
输入：段落文字
处理步骤：
  1. 去掉语气词（啊、呢、嘛、吧、哦、嗯）
  2. 提取名词/动词（实体词）
  3. 过滤通用词（的、是、在、和、了）
  4. 保留 2-3 个最有画面感的词

示例：
  "时间越长，复利效应越明显"
  → 过滤后 → ["时间", "复利效应", "增长"]
  → 合并生成 → "复利效应, 时间增长, 指数曲线"
```

### 图像生成 Prompt 模板

```python
BACKGROUND_PROMPT = """
{keywords},
简洁插画风格, 现代扁平设计,
暖色调渐变, 教育科普感,
无文字, 无人脸, 无水印,
竖屏9:16, 高质量, 4K
"""

NEGATIVE_PROMPT = """
低质量, 模糊, 变形,
文字, 人脸, 水印,
裸露, 暴力, 恐怖
"""
```

### 风格匹配规则

| 关键词类型 | 画面风格 |
|---|---|
| 财富/理财/投资/复利 | 上升曲线图、硬币、金色渐变 |
| 健康/运动/身体 | 自然风景、阳光、跑步 |
| 心理/情绪/情感 | 柔和色调、人物沉思、天空 |
| 时间/效率/管理 | 时钟、日历、清单 |
| 学习/知识/成长 | 书籍、灯泡、阶梯上升 |
| 美食/烹饪 | 食材特写、厨房、暖色调 |
| 旅游/探索 | 地图、行李、风景 |

---

## 四、文字叠加逻辑

### 排版规则

```
背景图尺寸：1080 x 1920

caption 样式（底部字幕）：
  - 文字区宽度：960px（左右各留 60px）
  - 文字区高度：自适应，最小 120px
  - 背景：rgba(0,0,0,0.6)，圆角 16px
  - 字体大小：48px
  - 行高：1.5 倍
  - 最大行数：3 行（超出截断）
  - 位置：距底部 120px，居中

highlight 样式（居中金句）：
  - 字体大小：72px
  - 文字颜色：白色
  - 描边：2px 黑色
  - 无背景
  - 位置：画面中部偏上

title 样式（顶部标题）：
  - 背景：rgba(0,0,0,0.4) 渐变
  - 字体大小：36px
  - 位置：距顶部 80px
```

### 文字处理规则

```
1. 自动换行：标点符号处优先换行
2. 超长处理：超过最大行数 → 截断 + "..."
3. 英文/数字：字号可适当缩小 10%
4. 特殊符号：感叹号/问号保留，突出语气
```

### 叠加效果示意

```
┌────────────────────────┐
│                        │
│   [SD 生成的背景图]       │  ← 插画风格，视觉化表达内容
│   上升曲线/图标/数字     │
│                        │
│ ┌────────────────────┐ │
│ │ 复利是理财中最强大   │ │  ← 半透明深色背景条 + 白色文字
│ │ 的概念之一           │ │
│ └────────────────────┘ │
│                        │
│      [数字人口型叠加]    │  ← 右下角，透明通道 PNG
│                        │
└────────────────────────┘
```

---

## 五、口型视频生成逻辑

### SadTalker 输入输出

```
输入：
  - 角色图：1080x1920 PNG（透明通道或绿幕）
  - 音频：mp3/wav，对应段落文字

输出：
  - 口型视频：mp4, 30fps, 透明通道或 RGB

参数建议：
  - preprocess：crop（从图像裁剪头部区域）
  - expression_scale：1.0（标准表情）
  - still：True（身体保持静止）
```

### 数字人位置规则

```
位置：画面右下角
  - x：720px（从左边算起，右侧 1/3 处）
  - y：960px（从顶部算起，偏下）
  - 宽度：360px（约画面 1/3 宽）
  - 高度：自动比例

透明通道处理：
  - 如果 SadTalker 输出无透明通道 → 用色键抠图（绿幕）
  - 叠加到背景：FFmpeg overlay
```

---

## 六、片段合成逻辑

### 单段合成流程

```
输入：
  - 背景图（带文字）：bg_0.png
  - 口型视频：talk_0.mp4
  - 配音音频：audio_0.mp3
  - 时长：3.5 秒

处理：
  1. 背景图作为底层
  2. 口型视频叠加在右下角
  3. 音频作为该段音轨
  4. 截断到精确时长

输出：clip_0.mp4（视频+音频，3.5 秒）
```

### FFmpeg 叠加命令

```bash
ffmpeg -y \
  -loop 1 -i bg_0.png \
  -i talk_0.mp4 \
  -i audio_0.mp3 \
  -filter_complex "
    [0:v]scale=1080:1920[bg];
    [1:v]scale=360:-1,setpts=PTS-STARTPTS+0/TB[head];
    [bg][head]overlay=720:960:shortest=1:format=auto[out]
  " \
  -map [out] -map 2:a \
  -t 3.5 -c:v libx264 -preset fast \
  -c:a aac clip_0.mp4
```

---

## 七、最终拼接逻辑

### 拼接规则

```
输入：[clip_0, clip_1, clip_2, ...] + BGM

处理：
  1. 用 FFmpeg concat 按顺序拼接所有片段
  2. 计算总时长
  3. BGM 循环或截断匹配总时长
  4. BGM 音量压低到 0.25（不抢人声）
  5. 人声音量保持 1.0

BGM 混音：
  - 人声音量：1.0（保持清晰）
  - BGM 音量：0.25（背景，不抢注意力）
  - 结尾处理：最后 1 秒 BGM 渐出（fadeout）
```

### 时间轴总览

```
        段落0(3.5s)  段落1(4s)  段落2(5s)  段落3(3s)
        |-----------|-----------|-----------|-----------|
背景图   [图+文字0]    [图+文字1]    [图+文字2]    [图+文字3]
数字人口型 [口型0]       [口型1]       [口型2]       [口型3]
音频     [配音0]       [配音1]       [配音2]       [配音3]
        |-----------|-----------|-----------|-----------|

BGM ─────────────────────────────────────────────────
                    全部片段拼接 + BGM 混音
                          ↓
                    最终视频 mp4
```

---

## 八、异常处理规则

| 情况 | 处理方式 |
|---|---|
| SadTalker 生成失败 | 跳过该段，用纯背景图 + 音频继续 |
| 背景图生成超时 | 用纯色渐变背景代替 |
| 某段音频时长和预计不符 | 以实际音频时长为准，调整时间轴 |
| 段落文字超长无法显示 | 截断显示，不影响音频 |
| BGM 文件不存在 | 跳过 BGM，仅保留人声 |

---

## 九、输入输出总结

```
输入：
  - 主题/关键词
  - 角色图（数字人形象，透明通道或绿幕）
  - 音色选择
  - 可选：背景风格偏好、BGM

输出：
  - 最终视频：data/videos/presenter_{timestamp}.mp4
  - 分段素材归档：data/presenter/{timestamp}/segments/
```

---

## 十、技术栈

### 写实版数字人（推荐 Sonic）

| 环节 | 技术选型 |
|---|---|
| 脚本生成 | LLM + RAG（已有 `DialogueGenerator` / `script_generator.py`） |
| 配音生成 | Edge-TTS / GPT-SoVITS（已有 `TTSEngine`） |
| 背景图生成 | ComfyUI / Stable Diffusion（当前测试端口 `http://127.0.0.1:8190/prompt`，后续做成可配置） |
| 口型视频 | **Sonic**（腾讯 PCG + 浙江大学 CVPR 2025，~30-60MB，口型最准、速度最快） |
| 文字叠加 | PIL/Pillow 或 ImageMagick |
| 视频合成 | FFmpeg（已有 `video_composer.py`） |
| BGM 混音 | FFmpeg / MoviePy（已有 `audio_mixer.py`） |

**Sonic 核心优势**：
- 相比 SadTalker：口型更准、速度更快、显存需求更低
- 半身写实输出（胸以上），头部轻微自然转动
- 支持写实图和动漫图
- GitHub: `jixiaozhong/Sonic`，CVPR 2025

### 动漫版数字人

| 环节 | 技术选型 |
|---|---|
| 口型视频 | LivePortrait（优先）/ SadTalker |
| 背景图生成 | ComfyUI + anime模型（CounterfeitV3 / AnimagineXL3） |
| 其他环节 | 同写实版 |

---

## 十一、代码模块规划

```
src/content_factory/
  presenter_pipeline.py      # 主流程编排

src/content_factory/presenter/
  script_segmenter.py        # 脚本分段
  background_provider.py     # ComfyUI/预设库/兜底背景 provider
  text_overlay.py            # 文字叠加到背景图
  sadtalker_wrapper.py       # SadTalker 调用封装
  segment_composer.py        # 单段合成（背景+口型+音频）
  final_concatenator.py      # 片段拼接 + BGM 混音
```

---

## 十二、与现有代码的集成

```
现有组件（复用）：
  - src/content_factory/script_generator.py      # 脚本生成
  - src/content_factory/tts_engine.py             # TTS 配音
  - src/content_factory/audio_mixer.py            # BGM 混音
  - src/content_factory/video_composer.py         # FFmpeg 封装
  - src/services/auto_publish_service.py          # 自动发布服务

新增组件：
  - presenter_pipeline.py                          # 主流程
  - presenter/script_segmenter.py                  # 分段逻辑
  - presenter/background_provider.py                # ComfyUI/预设库/兜底背景 provider
  - presenter/text_overlay.py                      # 文字叠加
  - presenter/sadtalker_wrapper.py                 # SadTalker 调用
```

---

## 十三、实施步骤

**第一阶段：Sonic 验证（写实版，1-2小时）**
1. 安装 `vshortt73/sonic-talking-head` 独立版
2. 下载 Sonic 模型文件到本地
3. 用写实角色图 + 音频测试生成，验证质量和速度
4. 写 `sonic_wrapper.py` 封装类

**第二阶段：最小闭环（单段验证）**
1. 写 `script_segmenter.py` — 输入一段文字，输出分段元数据
2. 调用 ComfyUI 生成一张背景图，验证 prompt 效果
3. 用 PIL 把文字叠加到背景图
4. Sonic 生成一段口型视频
5. FFmpeg 合成：背景图 + 口型视频 + 音频

**第三阶段：多段扩展**
1. 扩展到 3-5 段，验证时间轴拼接
2. 实现 `background_provider.py` 调用 ComfyUI API，并保留预设库/本地兜底背景
3. 完善 `text_overlay.py` 排版（caption/highlight/title 三种样式）

**第四阶段：动漫版（可选）**
1. LivePortrait / SadTalker 动漫口型测试
2. 动漫角色图 + 动漫背景图测试
3. 动漫版 PresenterPipeline

**第五阶段：集成到发布流程**
1. 封装 `presenter_pipeline.py` 主类，支持 `--driver sonic`
2. 新增 `python main.py presenter-publish --driver sonic --keywords "..."`
3. 集成到 `auto_publish_service.py` 作为 `--mode presenter` 选项
4. Streamlit 后台支持选择写实/动漫口型引擎
