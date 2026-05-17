---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史排查报告，用于解释 dual_v11_micro_motion.mp4 微动作效果异常原因；不要作为当前实现方案。
---

> 文档状态：历史排查报告，用于解释 `dual_v11_micro_motion.mp4` 微动作效果异常原因；不要作为当前实现方案。

# 微动作版本异常原因报告

> 日期：2026-05-10
> 分析对象：`data/videos/dual_v11_micro_motion.mp4`
> 相关代码：`src/content_factory/micro_motion.py`、`src/content_factory/video_composer.py`
> 相关素材：`data/motion_assets/na1/`、`data/motion_assets/n3/`

## 结论

当前“眨眼 + 轻微呼吸”版本已经技术上生成成功，但视觉效果不对。

核心原因不是 FFmpeg 合成失败，而是**微动作素材和动作逻辑不符合角色图本身**：

1. 闭眼素材是黑色椭圆贴片，不是基于角色眼睛绘制的闭眼线条。
2. 闭眼贴片位置不准，男角色第一版直接盖成黑眼罩效果。
3. 呼吸素材是大面积灰色椭圆阴影，直接覆盖胸口，像一块半透明污渍。
4. 眨眼时间计算使用逐帧随机，导致眨眼序列不可复现，也可能出现不连续或难以调试的问题。
5. PNG 序列帧数和最终视频帧数不完全一致，最终视频可能出现末帧补齐或重复。

因此，当前版本不建议继续调参数上线，应该先重做微动作素材和眨眼调度逻辑。

## 当前产物检查

### 文件存在

已生成代码和产物：

```text
src/content_factory/micro_motion.py
data/motion_assets/na1/body.png
data/motion_assets/na1/eyes_closed.png
data/motion_assets/na1/chest_shadow.png
data/motion_assets/n3/body.png
data/motion_assets/n3/eyes_closed.png
data/motion_assets/n3/chest_shadow.png
data/videos/characters/na1_frames/
data/videos/characters/n3_frames/
data/videos/dual_v11_micro_motion.mp4
```

### 视频参数正常

`dual_v11_micro_motion.mp4` 参数：

```text
width=1080
height=1920
r_frame_rate=30/1
duration=31.566667
nb_frames=947
```

容器、分辨率、帧率、时长都正常，所以问题不是视频编码或最终封装。

## 证据一：闭眼贴片素材不对

素材统计：

```text
data/motion_assets/na1/eyes_closed.png
size=340x70
alpha_bbox=10,23,335,47
alpha_pixels=3392

data/motion_assets/n3/eyes_closed.png
size=340x70
alpha_bbox=10,25,330,45
alpha_pixels=2682
```

实际观察：

```text
data/motion_assets/na1/eyes_closed.png
data/motion_assets/n3/eyes_closed.png
```

这两个文件本质上是两枚深色椭圆，不是角色对应风格的闭眼线条。

结果：

- 男角色闭眼时像被贴了黑眼罩。
- 女角色如果触发闭眼，也会出现不自然的黑色遮挡。
- 这不是“眨眼”，而是“黑色贴片覆盖眼睛”。

## 证据二：闭眼贴片位置不准

当前代码中的位置：

```python
NA1_EYES_OFFSET = (590, 245)
N3_EYES_OFFSET = (570, 255)
```

男角色第 2 帧检查：

```text
data/videos/characters/na1_frames/000002.png
```

观察结果：

- 左眼贴片压在眼睛和鼻梁附近，面积过大。
- 右眼贴片贴到了耳朵附近，而不是右眼。
- 因为男角色脸是侧角度，左右眼在透视和位置上并不是两个水平椭圆。

根因：

1. 用统一的 `340x70` 双眼贴片处理透视脸是不成立的。
2. 当前眼睛 offset 是粗略手调，不是基于角色眼睛真实区域绘制。
3. 贴片没有分左右眼，也没有适配角色头部角度。

## 证据三：呼吸层像灰色胸口污渍

素材统计：

```text
data/motion_assets/na1/chest_shadow.png
size=400x200
alpha_bbox=20,20,380,180
alpha_pixels=45645

data/motion_assets/n3/chest_shadow.png
size=400x200
alpha_bbox=20,20,380,180
alpha_pixels=45645
```

当前代码位置：

```python
NA1_CHEST_OFFSET = (664, 750)
N3_CHEST_OFFSET = (664, 750)
```

实际差异区域：

```text
DiffBBox=684,770,1044,930
DiffPixels=45645
```

观察结果：

- `chest_shadow.png` 是一个大灰色椭圆。
- 它覆盖在衣服胸口正中，形成明显灰色污渍。
- 呼吸效果不是身体起伏，而是灰色椭圆透明度周期变化。

根因：

1. 胸口阴影不是从原图衣服纹理中提取的自然局部层。
2. 两个角色共用相同尺寸和相同偏移，完全没有按角色身体姿态适配。
3. 透明度变化无法模拟呼吸，反而造成“胸口一块变暗/变亮”的视觉异常。

## 证据四：眨眼调度逻辑不可复现

当前代码：

```python
def _is_blink_frame(frame_idx: int, fps: int, config: MotionConfig) -> bool:
    t = frame_idx / fps
    blink_start = config.blink_offset
    while blink_start < t:
        blink_end = blink_start + config.blink_duration_frames / fps
        if blink_start <= t < blink_end:
            return True
        interval = random.uniform(config.blink_interval_min, config.blink_interval_max)
        blink_start += interval
    return False
```

问题：

每一帧都会重新从 `blink_offset` 开始计算，并且在 while 循环里调用 `random.uniform()`。

这意味着：

1. 眨眼时间表不是预先固定的。
2. 第 100 帧和第 101 帧计算出来的历史随机间隔可能不同。
3. 眨眼窗口可能不连续，也难以复现。
4. `seed` 字段存在，但没有实际用于稳定随机序列。

正确做法应该是：

```text
先基于 seed 生成完整 blink_events 列表：
[(start_frame, end_frame), ...]

每帧只判断 frame_idx 是否落在事件区间内。
```

## 证据五：开头会异常眨眼

当前逻辑设置：

```python
blink_offset = 0.0
```

对角色 A 来说：

- 第 1 帧 `t=0` 不进入 while，因此不闭眼。
- 第 2 帧开始 `t>0`，会落入从 `0s` 开始的闭眼窗口。

结果：

男角色视频一开头就出现闭眼贴片。

这和正常人物状态不符。更自然的第一眨眼应该在 2-4 秒之后。

## 证据六：序列帧数和最终帧数不一致

当前序列帧数量：

```text
data/videos/characters/na1_frames: 946
data/videos/characters/n3_frames: 946
```

最终视频：

```text
nb_frames=947
duration=31.566667
```

说明：

- PNG 序列比最终视频少 1 帧。
- FFmpeg 可能在末尾重复或补齐最后一帧。
- 这不是主要视觉异常来源，但说明时长和帧数计算还不够严谨。

正确做法：

```python
total_frames = math.ceil(total_duration * fps)
```

并且最终 `-t` 应与 `total_frames / fps` 或音频总时长严格对齐。

## 当前实现中仍然正确的部分

不是所有东西都错了。以下方向是对的：

1. 使用 PNG 序列保留透明通道，这个选择正确。
2. 最终视频用 `compose_dual_character_sequence_video()` 叠加序列，这个方向正确。
3. 两个角色分开生成帧序列，这个结构正确。
4. 不再尝试 SadTalker 头像贴全身，这是正确路线。

问题集中在：

```text
素材质量 + 动作调度 + 局部贴合
```

而不是整体技术路线。

## 修复建议

### 第一优先级：先停用呼吸层

当前胸口灰色椭圆最破坏画面。

建议：

```text
第一版只保留眨眼。
删除或暂时忽略 chest_shadow.png。
```

原因：

- 呼吸层做不好比没有呼吸更糟。
- 眨眼如果做好，已经足够让人物生动一点。

### 第二优先级：重做闭眼素材

闭眼素材不能用黑色椭圆。

应该为每个角色单独制作：

```text
na1_left_eye_closed.png
na1_right_eye_closed.png
n3_left_eye_closed.png
n3_right_eye_closed.png
```

要求：

- 只画闭眼线条，不画大色块。
- 线条颜色、粗细、角度匹配原图。
- 每只眼睛单独贴合，不要使用一整张双眼贴片。
- 如果原睁眼遮不住，需要额外制作 `eye_cover_patch`，先盖住原眼睛再画闭眼线。

### 第三优先级：固定眨眼时间表

新增逻辑：

```python
def build_blink_events(duration, fps, seed, first_blink_min=2.0, first_blink_max=4.0):
    rng = random.Random(seed)
    events = []
    t = rng.uniform(first_blink_min, first_blink_max)
    while t < duration:
        start = round(t * fps)
        end = start + 5
        events.append((start, end))
        t += rng.uniform(3.0, 5.0)
    return events
```

渲染时只查表，不再逐帧调用 `random.uniform()`。

### 第四优先级：重新标定每只眼睛坐标

不要使用：

```python
NA1_EYES_OFFSET = (590, 245)
N3_EYES_OFFSET = (570, 255)
```

建议改成：

```python
NA1_LEFT_EYE_OFFSET = (...)
NA1_RIGHT_EYE_OFFSET = (...)
N3_LEFT_EYE_OFFSET = (...)
N3_RIGHT_EYE_OFFSET = (...)
```

并通过抽帧放大检查坐标。

### 第五优先级：呼吸后置

呼吸不要用灰色椭圆覆盖。

更可控的做法：

1. 先不做呼吸。
2. 如果后续要做，只做“衣服局部亮暗纹理层”，从原衣服纹理中提取，而不是手画椭圆。
3. 透明度变化控制在 3%-5%，不要 15%。

## 建议下一版目标

下一版建议命名：

```text
dual_v12_blink_only.mp4
```

目标：

1. 去掉 `chest_shadow.png`。
2. 只做眨眼。
3. 眨眼事件固定。
4. 每个角色每只眼睛单独素材。
5. 第一眨眼不早于 2 秒。

验收标准：

- 不出现黑眼罩。
- 不出现胸口灰色椭圆。
- 眨眼持续 4-6 帧。
- 两个角色眨眼不同步。
- 如果暂停在闭眼帧，也应该看起来像自然闭眼，而不是贴片。

## 最终判断

当前 `dual_v11_micro_motion.mp4` 效果不对的根因是：

```text
用粗糙贴片模拟细微表情，用大面积灰色椭圆模拟呼吸。
```

技术路线仍可保留，但必须回到更克制的实现：

```text
先只做高质量眨眼。
呼吸暂缓。
嘴角和点头继续暂缓。
```
