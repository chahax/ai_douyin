---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# 方案三实现细节：LivePortrait / 表情驱动头像版

> 日期：2026-05-10
> 可行性：高（取决于工具是否可用）
> 预计工作量：1-3 小时（不含工具部署）

## 核心思路

放弃"全身角色站位"的画面，改为**头像/半身对话窗口**。角色有自然的眨眼、头部微动、表情变化，不再强行贴合全身图。

画面设计示例：

```
┌─────────────────────────────────┐
│          背景（星空/光晕）          │
│                                 │
│   ┌───────┐     ┌───────┐     │
│   │ 头像A │     │ 头像B │     │
│   │(学长) │     │ (学弟) │     │
│   └───────┘     └───────┘     │
│                                 │
│         [字幕区域]               │
└─────────────────────────────────┘
```

## 可用工具对比

| 工具 | 驱动方式 | 输入 | 输出 | 部署难度 | 可复用片段 |
|------|---------|------|------|---------|-----------|
| **SadTalker** | 音频驱动口型 | 单图 + 音频 | 256x256 口型视频 | 低（已有） | ❌ 按音频生成 |
| **LivePortrait** | 驱动图驱动 | 驱动视频/表情 | 256x256 头像视频 | 中 | ✅ 表情片段可复用 |
| **Live2D / Eulerian** | 物理模拟 | 设定参数 | 循环动画 | 低 | ✅ 参数化，可循环 |
| **Wav2Lip** | 音频驱动口型 | 视频 + 音频 | 原尺寸口型视频 | 低 | ❌ 按音频生成 |
| **AnimateAnything** | 图生视频 | 单图 | 短视频 | 高 | ✅ 3-5s 片段可复用 |

**推荐：LivePortrait**（如果有）或 **AnimateAnything 类工具生成可复用片段**。

## 方案 A：LivePortrait 头像版

### 工具获取

- GitHub: `KwaiVEG/LivePortrait`
- 官方文档：https://github.com/KwaiVEG/LivePortrait/blob/main/README.md
- 推理需要 GPU，建议 6GB+ 显存

### 输入素材要求

每个角色需要：
1. **正脸清晰照**（不要侧脸、有遮挡）
2. **驱动视频/表情参考**（可以是别人说话的录像，或预设表情片段）

### 表情片段复用机制（核心）

LivePortrait 支持用**一段驱动视频**驱动任意人脸。如果预先录一段"轻微点头 + 眨眼"的 3-5 秒循环片段，可以：

1. 录制一段 3-5 秒的驱动视频（一个人正面说话，自然表情）
2. 用这段视频驱动角色 A 和角色 B 的头像图
3. 生成 3-5 秒角色动画片段
4. 用 FFmpeg `loop` 或 `stream_loop` 循环延长到配音时长

**复用优势**：一次录制，可给所有角色用。

### 实现步骤

#### Step 1: 准备角色头像图

从现有 GrabCut PNG 中裁剪出头部的干净区域：
```python
from PIL import Image
import numpy as np

def extract_head_from_grabcut(grabcut_png, output_png, head_bbox):
    """从 GrabCut PNG 中裁剪干净的头像区域"""
    img = Image.open(grabcut_png)
    # head_bbox: {"left": x, "top": y, "width": w, "height": h}
    head = img.crop((
        head_bbox["left"],
        head_bbox["top"],
        head_bbox["left"] + head_bbox["width"],
        head_bbox["top"] + head_bbox["height"]
    ))
    # 缩放到 512x512（LivePortrait 推荐输入尺寸）
    head_resized = head.resize((512, 512), Image.LANCZOS)
    head_resized.save(output_png)
```

推荐头部 bbox（基于 na1_nobg.png）：
```python
head_bbox = {
    "left": 504,   # alpha bbox left
    "top": 115,    # alpha bbox top
    "width": 738,  # alpha bbox width
    "height": 500  # 上身/头部区域高度
}
```

#### Step 2: 准备驱动视频

录制一段 3-5 秒的自然说话驱动视频（正面，固定镜头）：
- 包含轻微点头、眨眼、嘴角微动
- 无剧烈运动，背景简单
- 建议用手机正面录制，30fps，1080p

#### Step 3: 调用 LivePortrait

```python
import subprocess, os

def generate_portrait_animation(character_png, driver_video, output_mp4, duration=None):
    """
    用 LivePortrait 生成头像动画
    """
    cmd = [
        'python', 'LivePortrait/inference.py',
        '--image', character_png,
        '--video', driver_video,
        '--output', output_mp4,
        '--driving_multiplication', '1',  # 倍速，1=正常
    ]
    if duration:
        cmd.extend(['--duration', str(duration)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

# 示例
generate_portrait_animation(
    character_png='data/png/na1_portrait.png',
    driver_video='data/videos/portrait_driver_3s.mp4',
    output_mp4='data/videos/portrait_na1.mp4'
)
```

#### Step 4: 循环延长到配音时长

LivePortrait 输出的片段可能只有 3-5 秒，需要延长：

```python
from src.content_factory.video_composer import compose_video

# 循环角色视频直到对齐配音时长
role_video = compose_video(
    video_clip_path='data/videos/portrait_na1.mp4',
    audio_path='data/ref_audio/role_a_concat.wav',
    output_name='portrait_na1_looped'
)
```

#### Step 5: 最终合成

```python
compose_dual_character_video(
    background_path='data/videos/bg_loop.mp4',
    clip_a_path='data/videos/portrait_na1_looped.mp4',
    clip_b_path='data/videos/portrait_n3_looped.mp4',
    audio_a_path='data/ref_audio/role_a_concat.wav',
    audio_b_path='data/ref_audio/role_b_concat.wav',
    # 头像位置调整为竖屏上方
    role_a_x=270, role_a_y=200,   # 居中偏上
    role_b_x=270, role_b_y=700,   # 下方
    portrait=True,
)
```

## 方案 B：AnimateAnything / 图生视频 可复用片段

如果没有 LivePortrait，可以用图生视频工具生成 3-5 秒片段，然后循环使用。

### 推荐工具

| 工具 | 来源 | 说明 |
|------|------|------|
| **Stable Video Diffusion (SVD)** | Stability AI | 图生视频，3-5 秒，可本地 |
| **AnimateDiff** | ComfyUI 节点 | 轻量级图生视频 |
| **Damo-VIL** | 阿里 | 动作达人，最长 5 秒 |
| **I2VGen-XL** | 阿里 | 阿里云 ModelScope 可用 |
| **Modelscope 视频合成** | ModelScope | API 调用，免费额度 |

### 片段复用工作流

```
1. 准备角色头像图（512x512 正脸）
       ↓
2. 用图生视频工具生成 3-5 秒轻微动作片段
   （呼吸、眨眼、头发微动）
       ↓
3. 检查质量，选取最优片段
       ↓
4. 用 FFmpeg stream_loop 循环延长到配音时长
       ↓
5. 叠加到背景 + 配音音频
```

### 具体实现：Modelscope I2VGen-XL

```python
import requests, json, os

def generate_i2v_clip(model_id, image_path, prompt, duration=5):
    """
    用 ModelScope I2VGen-XL API 生成视频片段
    """
    api_url = "https://api.modelscope.cn/v1/inference"
    headers = {"Authorization": "Bearer YOUR_TOKEN"}

    payload = {
        "model_id": model_id,  # "i2vgen-xl"
        "input": {
            "image": open(image_path, "rb").read(),  # Base64
            "prompt": prompt,  # "A person gently blinking and breathing"
            "duration": duration,
        }
    }

    response = requests.post(api_url, json=payload, headers=headers, timeout=120)
    result = response.json()

    video_url = result["data"]["video_url"]

    # 下载视频片段
    clip_path = "data/videos/portrait_clip_temp.mp4"
    with open(clip_path, "wb") as f:
        f.write(requests.get(video_url).content)

    return clip_path

# 生成示例
clip = generate_i2v_clip(
    model_id="i2vgen-xl",
    image_path="data/png/na1_portrait.png",
    prompt="A person with gentle blinking and slight head movement, front view",
    duration=4
)
```

### FFmpeg 循环延长片段

```python
def loop_clip_to_duration(clip_path, target_duration, output_path):
    """用 FFmpeg stream_loop 把短片段循环延长到目标时长"""
    clip_dur = get_duration(clip_path)
    repeat_count = int(target_duration / clip_dur) + 2

    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', str(repeat_count),
        '-i', clip_path,
        '-t', str(target_duration),
        '-c:v', 'libx264', '-preset', 'fast',
        '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2',
        output_path
    ]
    subprocess.run(cmd, capture_output=True)

loop_clip_to_duration(
    clip_path='data/videos/portrait_na1_clip.mp4',
    target_duration=18.55,  # role_a 音频时长
    output_path='data/videos/portrait_na1_18s.mp4'
)
```

## 方案 C：SadTalker 头像版（最简单已有方案）

如果不想部署新工具，直接用 SadTalker 但只输出头像框：

### 输入素材

需要两张正脸清晰的照片（不要全身）：
- `na1_portrait.png` — 从 na1_nobg.png 裁剪头部区域（512x512）
- `n3_portrait.png` — 从 n3_nobg.png 裁剪头部区域（512x512）

### SadTalker 生成

```python
import os, subprocess

FFMPEG = "C:/Users/<your-user>/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.0.1-full_build/bin/ffmpeg.exe"

def generate_sadtalker_portrait(portrait_img, audio_path, output_mp4):
    """
    用 SadTalker 生成头像口型视频（只取头部区域）
    """
    # 1. SadTalker 生成全身视频
    sadtalker_cmd = [
        'python', 'SadTalker/inference.py',
        '--driven_audio', audio_path,
        '--source_image', portrait_img,
        '--result_dir', 'data/videos/sadtalker_portrait_temp',
        '--still',
        '--preprocess', 'crop',  # 只保留头部crop
        '--enhancer', 'none',
    ]
    subprocess.run(sadtalker_cmd)

    # 2. 从输出中取 256x256 头像区域
    # SadTalker 输出路径不固定，找最新文件
    output_dir = 'data/videos/sadtalker_portrait_temp'
    mp4_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
    latest = sorted(mp4_files)[-1]
    full_path = os.path.join(output_dir, latest)

    # 3. 裁剪为 540x960 头像框（上下居中）
    crop_cmd = [
        FFMPEG, '-y', '-i', full_path,
        '-vf', 'scale=540:960',
        '-aspect', '9:16',
        output_mp4
    ]
    subprocess.run(crop_cmd)
    return output_mp4
```

### 最终合成

与方案 A Step 5 相同，用 `compose_dual_character_video` 叠加到背景。

## 三种方案对比

| 维度 | 方案A: LivePortrait | 方案B: 图生视频 | 方案C: SadTalker头像版 |
|------|---------------------|----------------|----------------------|
| 部署难度 | 需要 GPU + 工具安装 | API 调用或本地 | 已有，改造最小 |
| 表情自然度 | 高（驱动视频控制） | 中（模型决定） | 中（口型准确但表情单一） |
| 可复用片段 | ✅ 驱动视频可复用 | ✅ 3-5s 片段可复用 | ❌ 必须按音频生成 |
| 开发量 | 中（工具部署+脚本） | 中（API调试） | 低（改输入素材即可） |
| 推荐程度 | 高（有GPU时） | 高（无本地GPU时） | 中（快速出效果） |

## 产出清单

- [ ] 角色头像图：`na1_portrait.png`、`n3_portrait.png`
- [ ] 驱动视频（可选）：`portrait_driver_3s.mp4`
- [ ] 头像动画片段：`portrait_na1_clip.mp4`、`portrait_n3_clip.mp4`
- [ ] 循环延长片段：`portrait_na1_looped.mp4`、`portrait_n3_looped.mp4`
- [ ] 最终视频：`dual_v11_portrait.mp4`

## 与现有 video_composer.py 的集成

`compose_dual_character_video` 已支持传入 MP4 视频作为 `clip_a_path`/`clip_b_path`，无需修改函数本身。

唯一需要调整的是 `role_a_x/y` 和 `role_b_x/y`，头像场景建议：

```python
compose_dual_character_video(
    ...
    role_a_x=270, role_a_y=100,   # 角色A 居中偏上
    role_b_x=270, role_b_y=700,   # 角色B 居中偏下
)
```

或者改成"两个头像并排在上半区"：

```python
role_a_x=0, role_a_y=200,    # 左上
role_b_x=540, role_b_y=200,  # 右上
role_w=540, role_h=720,      # 头像高度更大
```
