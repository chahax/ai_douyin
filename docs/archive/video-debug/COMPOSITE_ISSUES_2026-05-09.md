---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 视频合成问题诊断报告

> 日期：2026-05-09

## 问题现象

| 报告 | 说明 |
|------|------|
| 用户反馈 1 | 角色背景透明了，只有头像部分，衣领也透明了（只有角色 A）|
| 用户反馈 2 | 生成的不对劲，只有角色 A，有人物轮廓，但轮廓中只有头像 |

## 根因分析

### 1. 角色 A（GrabCut alpha 叠加）问题

**诊断数据：**
- na1_nobg.png: 1728x2304, GrabCut 身体区域 alpha=255（完全不透明）
- SadTalker na1 输出: 256x256, 人物占 y=0-255, x=39-255（充满整个输出）
- 缩放后 540x960，身体区域 y≈48-892, x≈158-388

**问题：** GrabCut PNG 是全身图，缩放到 540x960 后，身体宽度约 230px，占角色区域的约 43%。但 sadtalker 人物本身是 256x256 填充整个帧的。当用 sadtalker 输出 + GrabCut alpha 做 `alphamerge` 时，**alphamerge 只在 alpha>0 时保留 sadtalker 内容**。如果 GrabCut alpha 身体区域的值和 sadtalker 内容匹配，可能出现可见性问题。

**更可能的问题：** na1_nobg.png 的 GrabCut 对衣服区域抠图不够精确，衣服边缘 alpha 偏低。

### 2. 角色 B（colorkey）问题

**诊断数据：**
- n3 SadTalker 输出背景: (242, 240, 237)，接近白色
- colorkey=0xF0F0F0, similarity=0.08
- FFmpeg colorkey 按 YUV 色差计算，实际阈值约 ±20
- 背景 (242,240,237) vs 键值 (240,240,240): YUV 色差约 4.7，在阈值内 → 背景被去除

**问题：** colorkey 参数 0xF0F0F0 + similarity=0.08 对浅灰背景有效，但可能同时误伤了角色的浅色衣服。

### 3. 两个角色叠加位置

| 参数 | 值 | 说明 |
|------|------|------|
| role_a_x/y | 0/480 | 左侧，头部在 y=480-1440 |
| role_b_x/y | 540/480 | 右侧，头部在 y=480-1440 |
| SadTalker 内容 | 256x256 → 540x960 | 缩放后高度 960px，实际内容充满整个 256px |

## 当前已知事实

1. `dual_no_colorkey.mp4` 中眼睛嘴巴都完整 → sadtalker 原始输出没问题
2. colorkey 各种参数都会误伤深色五官（相似度高了）或背景（相似度低了）
3. GrabCut alpha 对 na1 身体区域有效，但合成都只有头像
4. `test_a_only.mp4` (18.55s, 2.3MB) 和 `test_b_only.mp4` (13.0s, 2.7MB) 单角色测试正常
5. `test_ab_combined.mp4` (31.56s, 2.7MB) 两者叠加测试正常

## 尝试过的方案

| 方案 | 结果 | 问题 |
|------|------|------|
| colorkey=0x303030 similarity=0.25 | 失败 | 背景白色无法去除 |
| colorkey=0xF8F8F8 similarity=0.05 | 失败 | 衣服也被透明化 |
| GrabCut alpha + alphamerge | 失败 | 只有头像轮廓 |
| GrabCut A + colorkey B 混合 | 失败 | 同上 |
| 无 colorkey 直接叠加 | 成功 | 背景不透明 |

## 根本问题

**GrabCut PNG 叠加到 SadTalker 视频的方式有缺陷。** `alphamerge` 将 GrabCut 的 alpha 通道直接作为输出的 alpha，这要求 GrabCut 的 alpha 必须和 SadTalker 生成的人物轮廓完全匹配。如果 GrabCut 在身体区域有任何不精确（衣服边缘、背景过渡），就会在叠加时出现"只有头像"的效果。

## 建议方案

用**两张图分别做 GrabCut**，用 FFmpeg 混合叠加：
1. 将两张 GrabCut PNG 的 alpha 通道作为叠加权重的参考
2. 或者对 SadTalker 输出视频逐帧做 colorkey + 高斯模糊边缘
3. 最稳定方案：重新生成即梦图片，让即梦直接生成**竖屏 9:16 构图**的角色图（角色位于画面中上方，头部约占画面 60%），避免缩放失真
