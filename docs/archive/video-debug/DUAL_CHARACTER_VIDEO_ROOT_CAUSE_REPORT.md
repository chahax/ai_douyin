---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 双角色视频问题原因报告

> 日期：2026-05-01

## 结论

本次排查发现问题分为两层：

1. **角色 B 无法生成 SadTalker 口型视频**：根因仍是 `data/png/role_b.png` 素材不满足 SadTalker 3D 人脸关键点检测要求。它是偏卡通、非标准正面、张口表情的人像，OpenCV 能粗略检测到人脸不代表 SadTalker 的 3D 关键点模型可以稳定通过。
2. **已有混合方案的视频被截短**：`compose_dual_character_video()` 中音频滤镜使用 `[3:a][4:a]concat=n=2` 顺序拼接 A/B 音频，但输出总时长却取 `max(audio_a_dur, audio_b_dur)`。这会把应为 A+B 的视频截成较长单段音频的长度。

## 证据

| 项目 | 结果 |
|------|------|
| 角色 A 音频 | `18.550042s` |
| 角色 B 音频 | `13.006042s` |
| 正确顺序拼接时长 | `31.556084s` |
| 修复前 `dual_final_mixed.mp4` | `18.566667s`，只接近角色 A 单段时长 |
| 修复后验证文件 | `31.566667s` |

SadTalker 侧已尝试 `crop` / `resize` / `full` / GrabCut / 正方形裁剪，角色 B 均失败，说明不是简单预处理参数问题，而是素材对 3D landmark 模型不友好。

## 已修复内容

修改文件：`src/content_factory/video_composer.py`

1. 将双角色合成总时长从 `max(audio_a_dur, audio_b_dur)` 改为 `audio_a_dur + audio_b_dur`，匹配 `concat` 顺序拼接语义。
2. 增加背景视频时长校验，避免背景时长读取失败时发生除零或生成异常命令。
3. 增加静态图片输入支持：当 `clip_a_path` 或 `clip_b_path` 是 PNG/JPG/WebP/BMP 时，FFmpeg 自动加 `-loop 1 -framerate 24`，使其可作为全程视频流叠加。
4. 保留 colorkey 对图片和视频的处理，使 `role_b_grabcut.png` 这类深色背景静态兜底图可以去底后叠加。
5. 对未来的角色 B 口型视频增加时间偏移：当 `clip_b_path` 是视频文件时，B 画面会延后到 A 音频结束后开始，避免 A 段音频期间提前播放 B 的口型动画；静态 PNG 兜底仍保持全程可见。

## 验证

已执行：

```powershell
python -m py_compile src\content_factory\video_composer.py
```

已用现有素材生成验证视频：

```text
data/videos/dual_fix_validation.mp4
```

验证结果：

| 检查项 | 结果 |
|------|------|
| Python 语法检查 | 通过 |
| FFmpeg 合成 | 通过 |
| 输出时长 | `31.566667s` |
| B 角色静态兜底 | 可持续叠加 |
| B 角色深色背景 | colorkey 后已去除 |

## 仍未解决的限制

本次代码修复解决了**混合方案可用性**和**视频截短**问题，但没有让当前 `role_b.png` 通过 SadTalker。要让角色 B 也具备口型动画，需要至少满足以下之一：

1. 替换为更接近 `role_a.png` 的标准正面人像：正脸、五官清晰、闭口或自然微笑、无遮挡、背景简单。
2. 使用能处理卡通头像或非正面头像的替代口型驱动方案。
3. 生成一张同角色风格但正面、关键点友好的角色 B 新图，再重新跑 SadTalker。

当前可交付方案是：角色 A 使用 SadTalker 口型视频，角色 B 使用 colorkey 后的静态 PNG 叠加，最终视频时长和画面叠加已恢复正常。
