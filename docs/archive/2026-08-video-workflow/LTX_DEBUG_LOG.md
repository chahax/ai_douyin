---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-08-24
model_usage: 历史 LTX 单次调试记录，仅用于追溯参数与失败原因。
---

# LTX 视频生成调试记录

> 项目：ai_douyin 反诈普法短视频  
> 工作流：LTX-2.3 ICLoRA 图片参考故事板  
> ComfyUI：v0.28.0（从 v0.18.1 升级）  
> GPU：RTX 5070 Ti 16GB  
> 日期：2026-07-18 ~ 07-19

---

## 输出对比

| # | 文件 | 尺寸 | 时长 | 故事板风格 | Prompt 语言 | 音频 | 问题 | 改进方向 |
|---|------|------|------|-----------|------------|------|------|---------|
| 01 | output_00001.mp4 | 4.0MB | 10s | ❌ 足球动漫（原版） | 英文 | 无 | 完全错——用了 workflow 自带 prompt | 换成我们的内容 |
| 02 | output_00002.mp4 | 326KB | 10s | ❌ 扁平插画风 | 英文 | 有 | 画质极差，画风不对 | 写实故事板 + 中文 prompt |
| 03 | output_00003.mp4 | 2.1MB | 10s | ✅ 写实法律 | 中英混杂 | 有 | 画风 OK，语言混杂 | 纯中文 prompt |
| 04 | output_00004.mp4 | 5.5MB | 20s | ❌ 暖黄色调 | 英文 | 有 | 怀旧滤镜，手部变形 | 干净光照 + 中文 prompt |
| 05 | output_00005.mp4 | 1.9MB | 20s | ✅ 干净光照 | ✅ 纯中文 | 有 | 手部仍不自然 | 面部表情特写 + 中远景避手 |
| 06 | output_00006.mp4 | 1.3MB | 20s | ✅ 面部特写 | ✅ 纯中文情绪 | 有 | 待评审 | — |

---

## 核心技术决策

| 决策 | 原因 |
|------|------|
| 放弃 Wan I2V | ComfyUI v0.28.0 内置 Wan 节点 VAE 通道不匹配（16ch→48ch），kijai wrapper 节点名已变 |
| 放弃 Animagine+PuLID | 画风变动漫，用户要写实 |
| 选择 LTX 2.3 | ✅ 端到端跑通，故事板→视频，自带音频生成 |
| 升级 ComfyUI | v0.18.1→v0.28.0，解决了 VAE 格式不支持、comfy_aimdo 版本等问题 |

---

## 已知限制

| 问题 | 原因 | 缓解方案 |
|------|------|---------|
| 手部变形 | LTX 2.3 模型通病 | 中远景构图，不给手部特写 |
| 生成慢（~15分钟/段） | 24GB 模型在 16GB 显存上 offload | 缩短帧数 / 降低分辨率 / 换大显存卡 |
| 704×1248 分辨率 | LTX 原生宽高比 | 后期 upscale |
| 角色一致性靠 prompt | 无 LoRA/IP-Adapter 锚定 | prompt 里反复强调外貌特征 |

---

## 故事板 prompt 演进

```
v1 (output_01):  原版 workflow 自带——足球动漫，忽略
v2 (output_02):  "simple flat illustration" → 扁平插画，太简陋
v3 (output_03):  "realistic photography" → 画风 OK，但暖黄
v4 (output_05):  "clean natural lighting, neutral white balance" → 干净了
v5 (output_06):  "close-up, facial expressions, eyebrows, tears" → 面部优化
```

## LTX prompt 演进

```
v3: 英文描述对话 → 中英混杂
v4→v5: "中文对话：喂？你是谁？" → 纯中文输出
v6: 加情绪描述"眉头紧锁，眼中含泪，嘴唇颤抖" → 表情增强
```

---

## 下次迭代

1. 把 6 段 output 串成完整反诈故事
2. 试 960×544 横屏看手部是否改善
3. 尝试 Kling API 对比手部质量
4. 把 workflow JSON + prompt 模板存为项目资产
