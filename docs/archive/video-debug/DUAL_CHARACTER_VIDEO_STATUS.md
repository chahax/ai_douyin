---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 双角色视频生成 — 问题说明文档

> 更新时间：2026-05-01

---

## 1. 当前完成情况

| 环节 | 状态 | 说明 |
|------|------|------|
| DialogueGenerator 对话生成 | ✅ 完成 | 生成 A/B 交替对话脚本，含角色人格 |
| Edge-TTS 音频生成 | ✅ 完成 | A 用云健音色，B 用小艺音色，语速区分 |
| SadTalker 口型驱动（角色A） | ✅ 完成 | role_a.png + 音频 → 口型视频，背景色 0x303030 |
| FFmpeg colorkey 去背景 | ✅ 完成 | SadTalker 输出视频 colorkey=0x303030 去除背景 |
| 竖屏视频合成 | ✅ 完成 | 1080x1920，背景循环，角色叠加，音频顺序拼接 |
| compose_dual_character_video() | ✅ 完成 | 支持 colorkey 参数，一体化 FFmpeg 合成 |
| SadTalker 口型驱动（角色B） | ❌ 失败 | 3D 人脸特征点检测失败 |

---

## 2. 角色 B 图片问题

### 2.1 错误信息

```
File ".../croper.py", line 131, in crop
    raise 'can not detect the landmark from source image'
TypeError: exceptions must derive from BaseException
```

### 2.2 原因分析

| 原因 | 说明 |
|------|------|
| 人脸角度 | 角色B图片为侧面/非标准正面照，3D人脸重建无法检测到足够的关键点 |
| 图片尺寸 | 469x472，分辨率足够但人脸占比不大 |
| 预处理模式 | `crop` 模式需要精确人脸检测，`resize`/`full` 均失败 |

### 2.3 已尝试的修复方案

| 方案 | 参数 | 结果 |
|------|------|------|
| crop 模式（原始图） | `--preprocess crop` | 人脸检测失败 |
| resize 模式（原始图） | `--preprocess resize` | 人脸检测失败 |
| full 模式（原始图） | `--preprocess full` | 人脸检测失败 |
| crop 模式（GrabCut 预处理图） | `--preprocess crop` | 人脸检测失败 |
| crop 模式（正方形裁剪图） | `--preprocess crop` | 人脸检测失败 |
| OpenCV Cascade 人脸检测 | — | 能检测到 1 个人脸，但 3D 关键点失败 |

### 2.4 结论

问题在 SadTalker 内部的 `face3d/extract_kp_videos_safe.py` 的 `extract_keypoint` 方法，它的 3D 人脸模型对输入图片要求比 OpenCV Cascade 更严格。需要提供**标准正面照**（类似 role_a.png 的质量）。

---

## 3. 当前临时方案

| 方案 | 效果 |
|------|------|
| 角色A SadTalker + colorkey 去背景 | ✅ 背景干净，叠加正常 |
| 角色B 用 GrabCut 透明 PNG 静态叠加 | ⚠️ 背景去除较干净，但无口型动画 |
| colorkey 参数 | `colorkey=True, colorkey_color='0x303030', similarity=0.25, blend=0.05` |

---

## 4. 已验证的工作流

```
对话脚本生成 → Edge-TTS 音频 → SadTalker 口型(A) → FFmpeg colorkey 去背景 → 竖屏合成
```

```
对话脚本生成 → Edge-TTS 音频 → GrabCut 抠图(B) → FFmpeg 叠加透明图 → 竖屏合成
```

---

## 5. 下一步建议

1. **角色 B 更换正面照图片**，替换 `data/png/角色 B.png`，重新生成 SadTalker 口型视频
2. **确认 role_a.png 图片质量**：作为参考基准，确保新图片与之类似（正面、光线均匀、背景干净）
3. **集成到 main.py auto-publish**：当双角色全部就绪后，可新增 `--mode dual` 参数触发双角色流水线

---

## 6. 文件索引

| 文件 | 说明 |
|------|------|
| `src/content_factory/dialogue_generator.py` | 双角色对话生成器 |
| `docs/prompts/dialogue-generation.txt` | 对话生成 prompt |
| `src/content_factory/video_composer.py` | 视频合成（含 `compose_dual_character_video`） |
| `data/videos/dual_colorkey_a_only.mp4` | 角色A colorkey 测试输出 |
| `data/videos/dual_final_mixed.mp4` | 混合方案测试输出 |
| `data/png/role_b.png` | 角色B原图（人脸检测失败） |
| `data/png/role_b_grabcut.png` | 角色B GrabCut 抠图版本 |
| `<your_sadtalker_install_path>` | SadTalker 根目录 |
