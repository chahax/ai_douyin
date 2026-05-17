---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-13
model_usage: Edge-TTS 声线参考与 GPT-SoVITS 本地离线声线方案。
---

# Edge-TTS 到 GPT-SoVITS 本地声线方案

更新时间：2026-05-13

## 结论

可以先用 Edge-TTS 生成稳定的角色参考音频，再把这些音频作为 GPT-SoVITS 的参考声线，用本地 GPT-SoVITS 离线生成后续内容。

需要注意：Edge-TTS 本身是联网服务，不能离线；GPT-SoVITS 可以离线，但当前本机 GPT-SoVITS 环境还缺 `torch`，需要先修复环境。

## 推荐路线

1. 用 Edge-TTS 为角色 A/B 各生成 20 到 60 秒干净参考音频。
2. 人工挑选无噪声、无背景音乐、音量稳定的片段。
3. 保存到：

```text
data/ref_audio/role_a_edge_ref.wav
data/ref_audio/role_b_edge_ref.wav
```

4. 在 GPT-SoVITS 配置里为 A/B 分别绑定参考音频和参考文本。
5. 后续生成双角色视频时，用 GPT-SoVITS 本地生成音频，不再依赖 Edge-TTS 联网。

## 当前阻塞

当前 GPT-SoVITS SDK 报错：

```text
ModuleNotFoundError: No module named 'torch'
```

这说明 `GPT_SOVITS_CONDA_PYTHON` 指向的 Python 环境没有安装 PyTorch，或者指向了错误环境。修复后才能用本地 GPT-SoVITS 离线生成。

## 生产建议

- 短期：双角色继续默认 Edge-TTS，但要接受它需要联网。
- 中期：修复 GPT-SoVITS 本地环境，把 Edge-TTS 参考音频迁移为本地声线。
- 长期：每个角色维护固定参考音频、参考文本、音色参数，避免每次生成声音漂移。
