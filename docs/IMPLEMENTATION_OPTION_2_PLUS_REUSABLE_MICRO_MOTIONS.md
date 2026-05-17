---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-10
model_usage: 当前主线文档，可以作为当前项目状态或实施依据。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# 方案二增强版：2D 分层 + 可复用微动作库

> 日期：2026-05-10
> 目标：在保留当前全身人物画面的前提下，让人物有轻微生动感。
> 当前判断：这是现阶段最稳、最简单、最符合当前画面的路线。

## 结论

推荐先实现：

1. 眨眼
2. 轻微呼吸

暂缓实现：

1. 微点头
2. 嘴角微动

原因：

- 眨眼和呼吸最自然，最容易被观众感知为“活了”。
- 微点头需要头颈分层和旋转锚点，稍微复杂。
- 嘴角微动如果不跟音频同步，容易像假口型，建议只用于待机状态。

## 核心思路

不是复用一个视频片段，而是复用一套动作曲线和渲染逻辑。

每个角色只需要准备自己的分层 PNG，动作参数可以共用：

```text
blink: 每 3-5 秒闭眼一次，持续 4-6 帧
breath: 胸口/肩部 0.2%-0.5% 缩放或 1px 级位移
nod: 头部绕脖子轻微旋转 0.3-0.8 度
mouth_idle: 嘴角 0.5-1px 轻微变化，只用于非说话状态
```

## 产物形态

推荐先做“角色透明视频层”，再接入当前 `video_composer.py`。

优先产物：

```text
data/motion_assets/
  na1/
    body.png
    eyes_open.png
    eyes_closed.png
    chest_shadow.png
    head.png              可选
    mouth_neutral.png     可选
    mouth_smile.png       可选
  n3/
    body.png
    eyes_open.png
    eyes_closed.png
    chest_shadow.png
```

输出：

```text
data/videos/characters/na1_micro_motion.mov
data/videos/characters/n3_micro_motion.mov
```

如果本机 FFmpeg 对 alpha 视频支持麻烦，第一版可以直接输出 PNG 序列：

```text
data/videos/characters/na1_frames/000001.png
data/videos/characters/na1_frames/000002.png
...
```

PNG 序列最稳，透明通道不会丢。

## 分层素材要求

### 最小分层

第一版只需要：

```text
body.png
eyes_open.png
eyes_closed.png
chest_shadow.png
```

说明：

- `body.png`：完整人物底图，保留透明背景。
- `eyes_open.png`：只包含睁眼区域，透明背景，和原图同尺寸。
- `eyes_closed.png`：只包含闭眼区域，透明背景，和原图同尺寸。
- `chest_shadow.png`：胸口/衣服阴影或轻微明暗变化层，透明背景。

所有层建议保持原始画布尺寸，例如 `1728x2304`。不要裁成小块后再靠坐标贴，第一版这样更容易对齐。

### 为什么不用整个人物移动

已经试过整层漂浮，观感像贴纸在滑动。增强版只动局部：

- 眨眼：只替换眼睛层。
- 呼吸：只让胸口阴影或肩部亮暗轻微变化。
- 头部：后续才做，且只做极小旋转。

## 动作一：眨眼

### 动作规则

每 3-5 秒眨一次眼。

每次眨眼持续 5 帧左右：

```text
frame 0: 睁眼
frame 1: 半闭，可选
frame 2: 闭眼
frame 3: 闭眼
frame 4: 半闭，可选
frame 5: 睁眼
```

如果没有半闭素材，先用：

```text
睁眼 -> 闭眼 -> 闭眼 -> 睁眼
```

也能用。

### 推荐参数

```text
fps: 30
blink_interval_min: 3.0s
blink_interval_max: 5.0s
blink_duration_frames: 4-6
```

两个角色不要同一时间眨眼，要错开。

示例：

```text
角色 A：3.4s, 8.1s, 12.7s, 17.2s
角色 B：4.6s, 9.8s, 15.1s, 20.4s
```

### 实现方式

每帧先画 `body.png`，然后根据当前帧是否处于 blink window，叠加 `eyes_open.png` 或 `eyes_closed.png`。

如果 `body.png` 已经包含睁眼，闭眼时需要先遮住原眼睛区域：

```text
body.png
  -> eye_cover_patch.png
  -> eyes_closed.png
```

所以更理想的分层是：

```text
body_without_eyes.png
eyes_open.png
eyes_closed.png
```

如果短期不想修底图，也可以直接把 `eyes_closed.png` 盖在原眼睛上，但闭眼线条要足够厚，能遮住睁眼。

## 动作二：轻微呼吸

### 动作规则

不要移动整个人。只做胸口/肩部的微变化。

可选做法：

1. 胸口阴影透明度周期变化。
2. 肩部/衣服层纵向 1px 轻微位移。
3. 上半身局部缩放 0.2%-0.5%，但要小心边缘裂缝。

第一版推荐做法 1：阴影透明度变化。

### 推荐参数

```text
breath_period: 4.5s - 6s
opacity_min: 0.85
opacity_max: 1.00
movement_px: 0 或 1
```

公式：

```text
alpha = 0.925 + 0.075 * sin(2 * PI * t / breath_period)
```

### 为什么优先用透明度变化

透明度变化不会造成边缘错位。位移和缩放都会可能露出底图裂缝，尤其是当前人物 PNG 抠图边缘并不完美。

## 动作三：微点头

### 暂缓原因

点头不是简单上下移动头部。自然的点头应该围绕脖子附近旋转。

需要额外素材：

```text
head.png
neck_patch.png
body_without_head.png
hair_back.png 可选
```

如果没有 `body_without_head.png`，头一动就会看到原头残影。

### 推荐实现

只旋转 `head.png`，角度非常小：

```text
angle = 0.5 * sin(2 * PI * t / 5.5)
```

旋转中心：

```text
pivot = 脖子根部，而不是头图中心
```

如果找不到准确 pivot，就先不要做点头。

## 动作四：嘴角微动

### 使用边界

可以做，但只适合待机表情。

不建议在说话时循环嘴角，因为音频和嘴型不同步会被看出来。

### 推荐规则

只做 1px 级的嘴角/表情变化：

```text
mouth_neutral.png
mouth_soft_smile.png
```

每 6-10 秒变化一次，不要连续动。

## 代码结构建议

新增模块：

```text
src/content_factory/micro_motion.py
```

建议接口：

```python
from dataclasses import dataclass

@dataclass
class MotionConfig:
    fps: int = 30
    duration: float = 31.5
    blink_interval_min: float = 3.0
    blink_interval_max: float = 5.0
    blink_duration_frames: int = 5
    breath_period: float = 5.2
    breath_opacity_min: float = 0.85
    breath_opacity_max: float = 1.0
    seed: int = 1


def render_micro_motion_character(
    asset_dir: str,
    output_dir: str,
    config: MotionConfig,
) -> str:
    """
    输入角色分层素材目录，输出透明 PNG 序列目录。
    返回 PNG 序列路径，例如 data/videos/characters/na1_frames/%06d.png。
    """
```

第一版输出 PNG 序列，而不是 MP4。

原因：

- PNG 序列有 alpha。
- FFmpeg overlay 最稳定。
- 避免 mp4 丢透明通道。

## 接入当前合成

当前 `compose_dual_character_video()` 已支持 PNG 作为角色输入，但它只支持单张 PNG 循环。微动作输出是 PNG 序列，需要新增一个合成函数或给现有函数增加序列输入支持。

建议新增函数：

```python
def compose_dual_character_sequence_video(
    background_path: str,
    role_a_sequence: str,  # data/videos/characters/na1_frames/%06d.png
    role_b_sequence: str,
    audio_a_path: str,
    audio_b_path: str,
    output_dir: str = "data/videos",
    output_name: str = "dual_micro_motion",
):
    ...
```

FFmpeg 输入方式：

```bash
ffmpeg -y \
  -stream_loop 2 -i data/videos/bg_loop.mp4 \
  -framerate 30 -i data/videos/characters/na1_frames/%06d.png \
  -framerate 30 -i data/videos/characters/n3_frames/%06d.png \
  -i data/ref_audio/role_a_concat.wav \
  -i data/ref_audio/role_b_concat.wav \
  -filter_complex "
    [0:v]scale=1080:1920[bg];
    [1:v]scale=540:960[ra];
    [2:v]scale=540:960[rb];
    [bg][ra]overlay=0:480[tmp1];
    [tmp1][rb]overlay=540:480[outv];
    [3:a][4:a]concat=n=2:v=0:a=1[outa]
  " \
  -map "[outv]" -map "[outa]" \
  -t 31.5 \
  -c:v libx264 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  data/videos/dual_v11_micro_motion.mp4
```

注意：

- PNG 序列输入天然带 alpha。
- 最终成片是普通 mp4，不需要 alpha。
- 透明只在中间叠加时需要。

## 第一版实施步骤

### Step 1：为角色 A 做最小分层

先只做男角色 `na1`：

```text
data/motion_assets/na1/body.png
data/motion_assets/na1/eyes_closed.png
data/motion_assets/na1/chest_shadow.png
```

如果 `body.png` 仍保留睁眼，`eyes_closed.png` 必须能盖住原眼睛。

### Step 2：实现 `micro_motion.py`

只支持：

```text
眨眼
胸口阴影呼吸
```

不要一开始做点头和嘴角。

### Step 3：生成 5 秒预览

输出：

```text
data/videos/characters/na1_preview_frames/
data/videos/na1_micro_preview.mp4
```

先看局部动作是否自然。

### Step 4：角色 B 同样处理

确认 A 没问题后，再拆 B。

### Step 5：整片合成

输出：

```text
data/videos/dual_v11_micro_motion.mp4
```

## 验收标准

必须满足：

1. 人物没有整体漂浮感。
2. 眨眼不遮不住原眼睛。
3. 胸口呼吸不产生边缘裂缝。
4. 两个角色眨眼不同步。
5. 视频仍是 1080x1920，30fps，音频完整。
6. 任何一帧都不能出现明显透明破洞、黑边、白边。

## 失败时的降级方案

如果胸口呼吸不好看：

- 只保留眨眼。

如果眨眼盖不住原眼睛：

- 需要重做 `body_without_eyes.png`。

如果 PNG 序列生成太慢：

- 先只生成 5 秒循环序列，再 loop 复用。
- 但注意眨眼循环点不要太明显。

## 推荐结论

第一版只做：

```text
眨眼 + 胸口阴影呼吸
```

不要做：

```text
整个人漂浮
嘴巴循环假口型
强行头部替换
SadTalker 头像贴全身
```

这条路线最接近“画面差不多了，只想让人物稍微活一点”的目标。
