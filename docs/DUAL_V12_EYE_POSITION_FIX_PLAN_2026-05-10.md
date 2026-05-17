---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-10
model_usage: 当前 `dual_v12_micro_motion.mp4` 眼睛位置异常的原因跟踪和修复方案；后续实现眨眼动效时优先参考。
---

> 文档状态：当前主线解决方案。用于修复 `dual_v12_micro_motion.mp4` 中闭眼贴片位置不对的问题。

# dual_v12 眼睛位置异常跟踪与解决方案

> 日期：2026-05-10
> 分析对象：`data/videos/dual_v12_micro_motion.mp4`
> 核心代码：`src/content_factory/micro_motion.py`、`src/content_factory/video_composer.py`
> 相关素材：`data/motion_assets/na1/`、`data/motion_assets/n3/`
> 诊断截图：`data/diagnostics/dual_v12_t0_1.png`、`data/diagnostics/dual_v12_t1_7.png`

## 结论

`dual_v12_micro_motion.mp4` 眼睛位置不对，不是最终 FFmpeg 合成坐标导致的，而是在角色 PNG 序列生成阶段已经贴错。

当前实现使用一张 `340x70` 的双眼闭眼贴片，通过一个全局 `EYES_OFFSET` 贴到角色原图上：

```python
NA1_EYES_OFFSET = (590, 245)
N3_EYES_OFFSET = (570, 255)
```

这个策略不适合当前两张角色图，原因是：

1. 两个角色脸部角度不同，双眼的水平距离、垂直高度都不同。
2. 当前 `eyes_closed.png` 是水平双椭圆，不是根据角色眼睛形状绘制的闭眼线。
3. 男角色第二个椭圆被贴到耳朵附近。
4. 女角色左侧椭圆被贴到头发/额头区域。
5. 继续只调一个 `EYES_OFFSET`，最多只能让一只眼睛对齐，另一只眼睛仍会偏。

因此，正确修复方向是：**不要再用一个双眼贴片 + 一个 offset；改成每个角色、每只眼睛单独的闭眼 patch 和坐标。**

## 当前证据

### v12 产物状态

```text
data/videos/dual_v12_micro_motion.mp4
width=1080
height=1920
r_frame_rate=30/1
duration=31.566667
nb_frames=947
```

角色序列帧：

```text
data/videos/characters/na1_frames/*.png  946 帧
data/videos/characters/n3_frames/*.png   946 帧
```

最终视频 947 帧，角色序列 946 帧。这不是眼睛错位的主因，但说明生成链路还存在帧数边界不严谨的问题。

### 当前闭眼素材

```text
data/motion_assets/na1/eyes_closed.png
size=340x70
alpha_bbox=(10,23,335,47)

data/motion_assets/n3/eyes_closed.png
size=340x70
alpha_bbox=(10,25,330,45)
```

实际形态是两个深色水平椭圆。它不是闭眼线条，也没有贴合角色眼睑角度。

### 当前源图坐标系

角色素材原图尺寸：

```text
body.png: 1728x2304
```

最终合成时被缩放为：

```python
role_w = 540
role_h = 960
```

所以从角色源图到最终角色显示区域的缩放系数是：

```text
scale_x = 540 / 1728 = 0.3125
scale_y = 960 / 2304 = 0.4166667
```

如果在最终视频里看到眼睛偏了 `dx_final, dy_final`，回填到角色源图时要换算为：

```text
dx_source = dx_final / 0.3125
dy_source = dy_final / 0.4166667
```

不要直接拿最终视频坐标去改 `micro_motion.py` 的源图 offset。

## 错位根因

### 根因 1：双眼贴片结构不成立

当前 `eyes_closed.png` 是一张包含两只眼睛的整体贴片。它假设：

1. 两只眼睛在同一水平线上。
2. 两只眼睛间距固定。
3. 两个角色可以共用同类布局。

这三个假设都不成立。

男角色脸朝左，右侧眼睛靠近耳朵方向，但真实可见眼睛间距小于当前贴片两个椭圆的间距。结果是：第一只眼大致压到眼睛附近，第二只眼跑到耳朵位置。

女角色头部有明显倾斜，两只眼睛不在同一水平高度。结果是：右侧椭圆接近一只眼，左侧椭圆落到头发/额头上。

### 根因 2：当前代码只有一个 `eyes_offset`

当前接口：

```python
render_micro_motion_character(
    asset_dir,
    output_dir,
    config,
    eyes_offset=NA1_EYES_OFFSET,
)
```

内部逻辑：

```python
if _is_blink_frame(frame_idx, config.fps, config):
    if eyes_closed is not None:
        frame = _paste_centered(frame, eyes_closed, eyes_offset)
```

这意味着一张贴片只能做平移，不能分别控制左右眼，也不能处理头部倾斜。

### 根因 3：v12 很可能复用了旧序列帧

`dual_v12_micro_motion.mp4` 的生成时间晚于角色 PNG 序列目录时间，但角色帧目录仍是旧目录：

```text
data/videos/characters/na1_frames
data/videos/characters/n3_frames
```

这说明 v12 可能只是重新合成了最终视频，没有重新生成校正后的角色序列。后续生成必须使用版本化输出目录，避免旧帧残留：

```text
data/videos/characters/v12_na1_frames/
data/videos/characters/v12_n3_frames/
```

或：

```text
data/videos/characters/v13_blink_only/na1/
data/videos/characters/v13_blink_only/n3/
```

## 推荐修复方案

### 方案 A：每只眼睛一个 patch，推荐

新增素材结构：

```text
data/motion_assets/na1/
  body.png
  blink_left.png
  blink_right.png

data/motion_assets/n3/
  body.png
  blink_left.png
  blink_right.png
```

注意这里的 `left/right` 必须明确使用“观众视角”命名，建议实际文件名写得更清楚：

```text
viewer_left_eye_closed.png
viewer_right_eye_closed.png
```

新增坐标：

```python
NA1_EYE_PATCHES = [
    ("viewer_left_eye_closed.png",  (590, 260)),
    ("viewer_right_eye_closed.png", (750, 235)),
]

N3_EYE_PATCHES = [
    ("viewer_left_eye_closed.png",  (675, 300)),
    ("viewer_right_eye_closed.png", (815, 245)),
]
```

上面的坐标是基于当前源图观察得到的初始校准范围，不是最终像素锁定值。实现时应该用调试预览图确认后再微调。

优势：

1. 每只眼睛可以独立移动。
2. 女角色两只眼高度不同的问题可以解决。
3. 后续如果需要眨眼半闭帧，也可以分别替换左右眼 patch。
4. 不需要修改最终视频合成逻辑，只改角色序列生成。

### 方案 B：每个角色一张全画布闭眼层，最稳但素材成本稍高

新增素材：

```text
data/motion_assets/na1/eyes_closed_full.png  # 1728x2304
data/motion_assets/n3/eyes_closed_full.png   # 1728x2304
```

这两张图和 `body.png` 同尺寸，除了眼睛闭合区域，其余完全透明。代码里直接贴到 `(0, 0)`：

```python
frame = _paste(frame, eyes_closed_full, (0, 0))
```

优势是坐标最少，不容易错；缺点是每个角色都要单独做一张全尺寸闭眼层。

如果短期只追求稳定产出，方案 B 比方案 A 更适合。

## 具体实现步骤

### Step 1：停止使用当前 `eyes_closed.png`

保留文件用于历史追踪，但渲染逻辑不再读取它：

```text
data/motion_assets/*/eyes_closed.png
```

当前素材是黑椭圆，不适合作为正式闭眼层。

### Step 2：新增眼睛 patch 配置

建议在 `src/content_factory/micro_motion.py` 中增加数据结构：

```python
@dataclass(frozen=True)
class EyePatch:
    file_name: str
    offset: tuple[int, int]


NA1_EYE_PATCHES = [
    EyePatch("viewer_left_eye_closed.png", (590, 260)),
    EyePatch("viewer_right_eye_closed.png", (750, 235)),
]

N3_EYE_PATCHES = [
    EyePatch("viewer_left_eye_closed.png", (675, 300)),
    EyePatch("viewer_right_eye_closed.png", (815, 245)),
]
```

然后把 `render_micro_motion_character()` 的参数从：

```python
eyes_offset: tuple = None
```

改为：

```python
eye_patches: list[EyePatch] | None = None
```

闭眼时逐个贴：

```python
if is_blink:
    for patch in loaded_eye_patches:
        frame = _paste(frame, patch.image, patch.offset)
```

### Step 3：生成版本化帧目录

不要再覆盖或复用：

```text
data/videos/characters/na1_frames/
data/videos/characters/n3_frames/
```

改成：

```text
data/videos/characters/v13_blink_only/na1/
data/videos/characters/v13_blink_only/n3/
```

这样每次看视频时能确认用的是哪一版帧，不会出现“代码改了但视频还在吃旧帧”的误判。

### Step 4：先出 blink-only 校准版

先不要叠胸口呼吸层，避免灰色胸口阴影干扰判断：

```text
data/videos/dual_v13_blink_only.mp4
```

校准目标：

1. 闭眼只出现在眼睛位置。
2. 不遮住耳朵、头发、额头、脸颊。
3. 每次眨眼持续 4-5 帧。
4. 两个角色不要第一秒就眨眼。
5. 暂不要求呼吸效果。

### Step 5：加调试预览图

每次生成角色序列后，额外输出几张校准图：

```text
data/diagnostics/v13_na1_blink_frame.png
data/diagnostics/v13_n3_blink_frame.png
data/diagnostics/v13_dual_preview_t2_5.png
```

校准图可以在闭眼 patch 外画一个临时红框，确认位置后正式视频不输出红框。

### Step 6：修正眨眼调度

当前 `_is_blink_frame()` 每帧重新走随机间隔，后续也应该一并修掉。推荐预生成 blink events：

```python
def build_blink_events(duration: float, fps: int, seed: int, first_min=2.0, first_max=4.0):
    rng = random.Random(seed)
    events = []
    t = rng.uniform(first_min, first_max)
    while t < duration:
        start = int(round(t * fps))
        events.append((start, start + 5))
        t += rng.uniform(3.0, 5.0)
    return events
```

渲染时只判断帧号是否落在事件区间：

```python
is_blink = any(start <= frame_idx < end for start, end in blink_events)
```

## 初始校准坐标建议

以下是根据当前角色源图观察出的初始范围，后续以调试图微调为准。

### na1 男角色

角色源图：`data/motion_assets/na1/body.png`

当前错误：

```text
NA1_EYES_OFFSET = (590, 245)
```

效果：

1. 观众左侧椭圆接近眼睛，但形状过大。
2. 观众右侧椭圆贴到耳朵附近。

建议拆成：

```text
viewer_left_eye_closed:  x=590-610, y=260-275
viewer_right_eye_closed: x=750-770, y=235-250
```

### n3 女角色

角色源图：`data/motion_assets/n3/body.png`

当前错误：

```text
N3_EYES_OFFSET = (570, 255)
```

效果：

1. 观众左侧椭圆落到头发/额头。
2. 观众右侧椭圆接近一只眼，但仍显得粗黑。

建议拆成：

```text
viewer_left_eye_closed:  x=675-700, y=300-320
viewer_right_eye_closed: x=815-835, y=245-265
```

女角色头是倾斜的，所以左右眼 y 值差距较大，这是正常的。

## 验收标准

修复后必须检查以下文件：

```text
data/diagnostics/v13_na1_blink_frame.png
data/diagnostics/v13_n3_blink_frame.png
data/videos/dual_v13_blink_only.mp4
```

验收规则：

1. 单帧截图里，闭眼线必须落在眼睛上，不得盖到耳朵、头发、额头。
2. patch 不能是黑色大椭圆，应是贴合角色风格的细闭眼线或眼睑阴影。
3. 男角色和女角色都要单独检查，不能只看最终缩小视频。
4. 最终视频里如果肉眼看不清眨眼，先检查角色源帧，再检查最终视频。
5. 通过后再考虑恢复轻微呼吸，呼吸不应该和眨眼同一轮一起调。

## 不建议的修复方式

不要继续只改：

```python
NA1_EYES_OFFSET = (...)
N3_EYES_OFFSET = (...)
```

原因是当前素材两个椭圆之间的相对距离已经错了，只移动整张贴片无法同时对齐两只眼睛。

也不建议继续用黑椭圆闭眼层。即使位置对齐，观感也会像眼睛被涂黑，而不是自然眨眼。

## 推荐下一版目标

下一版不要叫 `dual_v12_micro_motion`，建议命名：

```text
dual_v13_blink_only.mp4
```

范围只做：

1. 重做闭眼素材。
2. 每只眼睛单独坐标。
3. 输出版本化角色帧目录。
4. 预生成 deterministic blink events。
5. 不启用胸口呼吸。

这版确认眼睛位置正确后，再进入 `dual_v14_blink_breath_subtle.mp4`。
