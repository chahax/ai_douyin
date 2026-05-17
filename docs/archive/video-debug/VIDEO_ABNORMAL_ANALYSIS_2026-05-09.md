---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 生成视频异常原因分析报告

> 日期：2026-05-09
> 范围：双角色视频合成输出异常，重点检查 `data/videos` 最新成片、抽帧图片、SadTalker 输出、抠像 PNG 和 `src/content_factory/video_composer.py` 合成逻辑。

## 结论

当前异常的主因不是 MP4 编码、帧率或时长问题，而是角色视频与抠像遮罩不在同一空间坐标系中：

1. SadTalker 输出是 `256x256` 的头像/半头像方形视频。
2. GrabCut 抠像图是 `1728x2304` 的全身竖图。
3. 合成代码把 SadTalker 视频直接 `scale=540:960`，同时把全身 alpha 遮罩也 `scale=540:960` 后执行 `alphamerge`。
4. 这会让“头像视频内容”被“全身人物遮罩”裁切，最终出现只剩局部头像、脸部破洞、衣服缺失、人物轮廓错乱等画面异常。

因此，最新异常属于画面合成策略错误，尤其是 `alphamerge` 输入不匹配；不是 ffmpeg 生成失败，也不是成片容器损坏。

## 已确认现象

最新输出文件参数正常：

| 文件 | 分辨率 | 帧率 | 时长 | 结论 |
|---|---:|---:|---:|---|
| `data/videos/dual_both_grabcut.mp4` | 1080x1920 | 30fps | 31.566667s | 容器/编码正常 |
| `data/videos/dual_mixed_method.mp4` | 1080x1920 | 30fps | 31.566667s | 容器/编码正常 |
| `data/videos/dual_new_chars.mp4` | 1080x1920 | 30fps | 31.566667s | 容器/编码正常 |
| `data/videos/dual_no_colorkey.mp4` | 1080x1920 | 30fps | 31.566667s | 容器/编码正常 |

抽帧图片显示的异常非常明确：

- `data/mixed_method_frame.png`
- `data/both_grabcut_frame.png`
- `data/mixed_frame.png`

画面中角色只剩左侧局部头像，脸部有透明破洞，头发和身体轮廓明显错位。这说明视频流本身能正常输出，但角色层透明度/遮罩合成错误。

## 关键证据

### 1. SadTalker 输出尺寸与遮罩尺寸不一致

SadTalker 新输出：

```text
data/videos/sadtalker_new/2026_05_09_16.56.16.mp4
width=256
height=256
duration=13.000000
nb_frames=325

data/videos/sadtalker_new/2026_05_09_16.56.57.mp4
width=256
height=256
duration=18.520000
nb_frames=463
```

抠像 PNG：

```text
data/png/na1_nobg.png
width=1728
height=2304
pix_fmt=rgba
alpha bbox: x=504..1241, y=115..2141, w=738, h=2027

data/png/n3_nobg.png
width=1728
height=2304
pix_fmt=rgba
alpha bbox: x=420..1353, y=115..2141, w=934, h=2027
```

这两类素材不是同一画幅，不应直接缩放到同一个 `540x960` 区域后做 alpha 合并。

### 2. 合成代码直接把方形头像视频拉伸成竖向角色层

相关代码在 `src/content_factory/video_composer.py`：

```python
role_w, role_h = 540, 960

role_a_filter = (
    f"[1:v]scale={role_w}:{role_h}[sa];"
    f"[{alpha_a_idx_val}:v]scale={role_w}:{role_h},format=yuva420p[ma];"
    f"[ma]alphaextract[mask_a];"
    f"[sa][mask_a]alphamerge[ra]"
)
```

问题点：

- `[1:v]` 是 SadTalker 的 `256x256` 头像视频。
- `alpha_mask_a` 是全身抠像 PNG。
- 两者都被强制缩放到 `540x960`，但内容语义不同：一个是头像方形画面，一个是全身人物轮廓。
- `alphamerge` 会用遮罩 alpha 决定 SadTalker 视频哪些像素可见，坐标不一致时就会切掉脸、衣服和身体。

### 3. 时长问题已经不是当前主因

旧报告中曾发现双角色音频拼接时长被截短的问题。当前代码已使用：

```python
total_dur = audio_a_dur + audio_b_dur
```

最新成片均为 `31.566667s`，与 A/B 音频顺序拼接后的长度一致。因此当前主要异常不在时长截断，而在视觉合成。

## 根因拆解

### 根因一：SadTalker 只生成头像区域，无法提供全身视频层

SadTalker 输入全身图后，实际输出仍是 `256x256` 方形头部驱动视频。它不是一个带全身透明通道的角色视频。

后续如果把这个头像视频当成全身角色视频使用，就一定会出现拉伸、错位、人物缺失等问题。

### 根因二：全身 alpha 遮罩不能直接套到 SadTalker 头像视频

`na1_nobg.png` 和 `n3_nobg.png` 的 alpha 是基于原始全身图生成的。它描述的是全身人物在 `1728x2304` 中的位置。

SadTalker 输出的 `256x256` 视频描述的是裁剪后的脸部区域。两者没有共同坐标系，直接 `alphamerge` 等于用全身轮廓去裁头像视频。

这正好解释了抽帧中“只剩头部轮廓、脸上有破洞、衣服透明”的现象。

### 根因三：colorkey 对浅色衣服/背景不稳定

项目里尝试过用 `colorkey` 去掉浅色背景。角色衣服、脸部高光、浅色背景都接近白色或浅灰色。

`colorkey=0xF0F0F0` 一类参数可以去背景，但也会误伤浅色衣服和脸部高光；阈值调低则背景去不干净，调高则人物被抠坏。所以 colorkey 只能作为临时兜底，不适合作为稳定生产方案。

## 建议修复方案

### 方案 A：最快可用，头像视频 + 全身静态身体分层

目标：保留 SadTalker 口型，同时不再用全身 alpha 裁切头像视频。

做法：

1. 使用 `na1_nobg.png` / `n3_nobg.png` 作为全身静态角色层。
2. 从 SadTalker `256x256` 视频中只取脸部/头部区域。
3. 将 SadTalker 头像按原始角色图中的头部位置叠到全身 PNG 上。
4. 最后把“全身 PNG + 动态头像”作为角色层叠到背景上。

优点：改动较小，能保留口型动画。
缺点：需要为每个角色配置头部贴合位置和缩放比例。

### 方案 B：素材侧修复，生成适合 SadTalker 的半身/头像素材

目标：让 SadTalker 输出与最终叠加区域天然一致。

做法：

1. 不再给 SadTalker 喂全身图。
2. 为每个角色准备正脸、清晰、闭口或自然微笑、背景简单的头像/胸像图。
3. 最终视频设计为双头像对话，而不是全身人物对话。

优点：最符合 SadTalker 能力边界，稳定性高。
缺点：视觉形态从全身角色变为头像/胸像。

### 方案 C：更彻底，替换口型驱动方案

目标：生成真正支持透明背景/半身/全身的角色动画层。

可选方向：

1. 使用支持透明通道输出的 talking head 或 live portrait 管线。
2. 使用 ComfyUI/AnimateDiff/LivePortrait 类方案生成角色动画，再单独做背景合成。
3. 如果坚持全身角色，需要引入身体动画或至少头身分离绑定，而不是只依赖 SadTalker。

优点：最终效果上限最高。
缺点：开发量和依赖复杂度明显更高。

## 不建议继续投入的方向

1. 不建议继续微调 `colorkey_similarity` 作为主方案。浅色衣服和浅色背景天然冲突，参数调优只能局部改善。
2. 不建议继续把全身 GrabCut alpha 直接 `alphamerge` 到 SadTalker 输出上。当前异常正是这个策略造成的。
3. 不建议把 `256x256` SadTalker 视频强制拉伸到 `540x960`。这会破坏画面比例，也不能补出身体内容。

## 推荐落地顺序

1. 先停用 `alpha_mask_a/alpha_mask_b` 对 SadTalker 视频的直接 `alphamerge`。
2. 增加“静态全身 PNG + 动态头像 overlay”的角色合成模式。
3. 为每个角色维护一组头部贴合参数，例如 `head_x/head_y/head_w/head_h`。
4. 用 `dual_both_grabcut.mp4` 同一批素材重新生成验证视频。
5. 如果后续要规模化生产，再考虑素材规范或替换口型动画方案。

## 最终判断

生成视频异常的直接原因是 `video_composer.py` 的 alpha 合成假设错误：代码假设 SadTalker 输出视频和 GrabCut 全身遮罩可以直接对齐，但实际 SadTalker 输出是 `256x256` 头像视频，GrabCut 遮罩是 `1728x2304` 全身图。两者强行缩放后执行 `alphamerge`，导致角色层被错误裁切。

短期应采用“全身静态图 + SadTalker 头像局部叠加”的分层方案；长期应统一素材规格，或更换支持目标画幅/透明角色输出的动画生成管线。
