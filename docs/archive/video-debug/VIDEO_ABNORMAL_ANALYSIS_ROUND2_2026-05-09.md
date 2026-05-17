---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 生成视频异常第二轮分析报告

> 日期：2026-05-09
> 本轮重点：`data/videos/dual_final_v7.mp4`、`dual_final_v6.mp4`、中间层 `data/png/composite_na1.png`、`data/png/composite_n3.png`、脚本 `data/png/composite_layer.py`。

## 结论

最新生成的视频仍然不对，但异常类型已经变化。

上一轮主要问题是：把 SadTalker 的 `256x256` 头像视频和全身 alpha 遮罩直接 `alphamerge`，导致人物被错误裁切。

这一轮已经尝试改成“全身静态 PNG + SadTalker 头像叠加”的方向，人物身体回来了，但新的中间层生成逻辑仍然错误：

1. `composite_layer.py` 只从 SadTalker 视频抽取第 1 帧，生成静态头像 PNG，后续视频里口型动画实际上不会保留。
2. SadTalker 头像没有被裁成“仅脸部/头部”，而是保留了较大的方形/矩形区域，导致成片出现明显矩形块。
3. 头像贴合位置计算过于粗糙，使用全身 alpha 的上 42% 估算头部，结果把新头像贴到了原头像前方/下方，形成“双头”。
4. 中间层 `composite_na1.png` 和 `composite_n3.png` 本身已经错了，所以 `dual_final_v7.mp4` 只是把错误中间层缩放叠加到了背景上。

因此，本轮根因在 `data/png/composite_layer.py` 的角色中间层生成方案，而不是 `dual_final_v7.mp4` 的编码或背景合成。

## 最新产物检查

### 成片参数

`data/videos/dual_final_v7.mp4`：

```text
video:
codec_name=h264
width=1080
height=1920
pix_fmt=yuv420p
r_frame_rate=30/1
duration=31.566667
nb_frames=947

audio:
codec_name=aac
sample_rate=24000
channels=1
duration=31.556000
```

`data/videos/dual_final_v6.mp4` 参数与 v7 基本一致：

```text
width=1080
height=1920
duration=31.566667
nb_frames=947
```

判断：成片容器、分辨率、帧率、音频轨道、总时长均正常。当前不是编码失败，也不是音画时长异常。

### 抽帧现象

抽帧文件：

- `data/png/dual_final_v7_frame.png`
- `data/png/dual_final_v6_frame.png`
- `data/png/analysis_v7_t0.png`
- `data/png/analysis_v7_t10.png`
- `data/png/analysis_v7_t20.png`
- `data/png/analysis_v7_t30.png`

观察到的问题：

1. 左侧男角色出现两个头：原全身 PNG 的头还在，SadTalker 头像又贴了一层。
2. 右侧女角色同样出现双头/重影。
3. SadTalker 头像下半部分有明显水平矩形边界，像一块方形贴图压在身体上。
4. 头像和身体的颈部、肩部、发型位置没有对齐。
5. v6/v7 成片里人物缩放后问题仍然可见，说明错误发生在角色中间层，不是最终背景叠加阶段才产生。

## 关键中间层证据

### `composite_na1.png`

文件：

```text
data/png/composite_na1.png
width=1728
height=2304
pix_fmt=rgba
```

视觉结果：

- 原始全身男角色头部仍然保留。
- SadTalker 男头像被贴在原头部前方偏右下位置。
- 新头像尺寸过大，覆盖到胸口区域。
- 新头像底部有明显矩形边界，说明 colorkey 没有正确生成干净 alpha，或者保留了 SadTalker 方形画面的非透明区域。

这说明 `composite_na1.png` 在进入最终视频合成前已经是错误素材。

### `composite_n3.png`

文件：

```text
data/png/composite_n3.png
width=1728
height=2304
pix_fmt=rgba
```

视觉结果：

- 原始女角色头发和头部仍然在后方。
- SadTalker 女头像叠在前方，尺寸过大。
- 脸部下缘到胸口位置出现明显横向矩形切线。
- 头发、脖子、衣领不连续。

同样说明错误发生在中间层生成阶段。

## 代码定位

问题脚本：

```text
data/png/composite_layer.py
```

### 问题一：只抽取 SadTalker 第一帧，丢失口型动画

相关代码：

```python
cmd = [
    FFMPEG, "-y",
    "-i", sadtalker_mp4,
    "-vframes", "1",
    "-vf", f"colorkey={colorkey_hex}:similarity={similarity},scale=600:600",
    "-pix_fmt", "rgba",
    output_png
]
```

`-vframes 1` 只取一帧，并保存为 PNG。这样生成的 `composite_na1.png` / `composite_n3.png` 是静态图片，不可能保留 SadTalker 的动态口型。

如果后续最终视频使用的是这个 PNG 中间层，那角色嘴巴不会动；如果又叠加了 SadTalker 视频，则会进一步产生多层头像叠加问题。

### 问题二：colorkey 没有得到干净头像 alpha

相关代码：

```python
"-vf", f"colorkey={colorkey_hex}:similarity={similarity},scale=600:600",
```

当前 SadTalker 输出背景、人物衣领、脸部高光、浅色衣服区域都接近浅色。单靠 `colorkey` 很难准确只保留头发和脸。

结果是：SadTalker 方形画面的部分背景或衣领区域被保留下来，在合成图里形成明显的水平矩形边界。

### 问题三：头部 bbox 估算过粗，导致贴合位置错误

相关代码：

```python
person_top, person_bottom = ys.min(), ys.max()
person_height = person_bottom - person_top
head_bottom = int(person_top + person_height * 0.42)
head_ys, head_xs = np.where((alpha > 128) & (np.arange(h)[:, None] < head_bottom))
```

这个逻辑把人物 alpha 的上 42% 当作头部区域。但对全身图来说，上 42% 会包含头、脖子、肩膀、胸口、头发外扩区域，尤其女角色长发会显著扩大 bbox。

后续用这个 bbox 的中心点贴 SadTalker 头像：

```python
paste_x = head["center_x"] - target_face_w // 2
paste_y = head["center_y"] - target_face_h // 2
```

这会让 SadTalker 头像按“上半身区域中心”而不是“脸部中心”对齐，导致头像整体下移或偏移。

### 问题四：没有先移除原始全身 PNG 的头部

当前流程是：

```python
result = grabcut.copy()
result.paste(face_rgba, (paste_x, paste_y), face_rgba)
```

也就是直接把 SadTalker 头像贴在原全身图上。原图头部没有被擦除、遮挡或替换，所以必然出现两个头或重影。

如果要做“动态头像替换”，至少需要：

1. 从全身 PNG 中分离身体层和头部层。
2. 在身体层上抹掉原头部区域，或者用头像层完全覆盖原头部。
3. SadTalker 头像只输出头脸区域，不带方形背景。
4. 用明确的脸部关键点或人工参数对齐，而不是靠全身 alpha 粗略估算。

## 本轮根因

本轮的根本问题是：虽然方向从“alpha 裁 SadTalker 视频”改成了“全身图 + 头像贴图”，但实现仍然把 SadTalker 头像当作一张普通贴图粗略粘到原图上，没有解决三个关键问题：

1. 动态性：PNG 中间层无法承载 SadTalker 的逐帧口型动画。
2. 透明性：SadTalker 头像没有被稳定抠成干净 RGBA。
3. 对齐性：贴图位置和尺寸没有基于脸部关键点或人工精调参数。

这三个问题叠加后，最终视频表现为双头、矩形贴片、头像错位、嘴部动画不可控。

## 修复建议

### 短期可交付方案：改成静态全身角色，不叠 SadTalker 头像

如果当前优先目标是“视频画面先正常”，建议暂时放弃 SadTalker 头像叠加：

1. 使用 `na1_nobg.png` 和 `n3_nobg.png` 作为全身静态角色。
2. 只做背景、字幕、音频、角色出场布局。
3. 不再生成 `composite_na1.png` / `composite_n3.png` 这种头像替换中间层。

优点：最快得到画面干净的视频。
缺点：角色没有口型动画。

### 中期方案：保留口型，但改成头像框/半身对话

如果必须保留 SadTalker 口型，建议不要和全身图强行融合：

1. 直接使用 SadTalker 的 `256x256` 输出。
2. 做成两个头像/圆形或方形对话窗口。
3. 背景和全身图不要混用，避免双头和贴合问题。
4. 画面设计改成“角色头像对话”而不是“全身角色讲话”。

优点：SadTalker 能力边界内，稳定。
缺点：视觉形态不是全身角色。

### 长期方案：真正做头身分离和逐帧合成

如果要实现“全身角色 + 动态口型”，需要重做管线：

1. 人工或模型标定每个角色的脸部 bbox、脖子位置、头部旋转角。
2. 生成身体底图时去掉原头部，或提供无头身体层。
3. 对 SadTalker 每一帧做抠像、裁切、缩放、旋转。
4. 将每一帧头像贴回身体层，再与背景合成。
5. 每个角色都需要独立配置贴合参数，不能只用统一比例。

优点：能接近目标效果。
缺点：开发量较高，且贴合质量强依赖素材和参数。

## 不建议继续的方向

1. 不建议继续用 `composite_layer.py` 当前逻辑生成中间层。它已经证明会产生双头和矩形贴片。
2. 不建议只调 `similarity` 或 `colorkey_hex`。这最多改善矩形边缘，不能解决双头、错位和静态 PNG 丢动画的问题。
3. 不建议继续用全身 alpha 的上 42% 自动估算头部位置。不同角色姿势、头发长度、身体比例差异太大，这个规则不稳定。
4. 不建议把 SadTalker `256x256` 输出当作全身角色素材。它只能作为头像/脸部动画源。

## 建议下一步

如果目标是马上生成可看的视频：

1. 停用 `data/png/composite_layer.py`。
2. 使用 `na1_nobg.png`、`n3_nobg.png` 直接作为静态角色层。
3. 重新生成 `dual_final_v8.mp4`，先确保没有双头、矩形块、贴图错位。

如果目标是继续保留口型：

1. 改成头像对话版，不和全身图融合。
2. 或者重做逐帧头身分离合成，不再生成单帧 `composite_*.png`。

## 最终判断

`dual_final_v7.mp4` 的问题不是视频编码问题，而是错误的中间角色层导致的。`composite_na1.png` 和 `composite_n3.png` 已经包含双头、错位头像和矩形贴片，最终视频只是把这些错误素材缩放到了背景上。

当前应先决定产品形态：要“画面稳定”就用静态全身角色；要“口型动画”就改成头像对话；要“全身角色动态口型”则必须重做头身分离逐帧合成管线。
