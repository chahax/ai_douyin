---
doc_status: active
doc_category: setup
last_reviewed: 2026-08-26
model_usage: RTX 5070 Ti 16GB 本地热门视频分析的环境、模型和运行边界。
---

# 本地视频分析环境

## 硬件基线

```text
GPU: NVIDIA GeForce RTX 5070 Ti, 16 GB VRAM
CPU: AMD Ryzen 7 9800X3D, 8C/16T
RAM: 32 GB
Disk D: 约 1.8 TB 可用（2026-08-26）
```

运行 Qwen3-VL 前应至少准备约 14 GB 空闲显存和 16 GB 可用内存。不得与 ComfyUI、Wan、LTX、FramePack 等模型同时驻留。

## Python 与媒体环境

```text
Python 3.14.3
PyTorch 2.11.0 + CUDA 12.8
Transformers 5.8.1
FFmpeg / FFprobe 8.0.1
OpenCV / PyAV 已安装
```

可选分析依赖记录在 `requirements-video-analysis.txt`。不安装 FlashAttention、bitsandbytes 或 vLLM；第一版使用 BF16、batch=1 和受控关键帧预算。

## 第一版模型

| 模型 | 用途 | 本地目录 |
|---|---|---|
| Qwen3-VL-4B-Instruct | 关键帧、字幕、结构、时间线和视觉内容理解 | `.local_models/video_analysis/Qwen3-VL-4B-Instruct` |
| Paraformer-zh | 中文语音转写、时间戳和法律热词 | `.local_models/video_analysis/paraformer-zh` |
| FSMN-VAD | 语音活动检测 | `.local_models/video_analysis/fsmn-vad` |
| CT-Punc | 中英文标点恢复 | `.local_models/video_analysis/ct-punc` |

本地模型只负责提取视频证据。证据整理为最终复刻剧本时，项目固定调用 `Minimax-M2.7`，入口为 `scripts/refine_video_script_minimax.py`；调用记录使用 `caller=video_script_refine` 写入 `llm_usage_logs`。

模型目录属于本地运行资产，不进入 Git。

2026-08-26 实际下载体积：Qwen 8.28 GiB、Paraformer 0.85 GiB、FSMN-VAD 0.004 GiB、CT-Punc 1.10 GiB。

## 安装与下载

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-video-analysis.txt
.\.venv\Scripts\python.exe scripts\download_video_analysis_models.py
.\.venv\Scripts\python.exe scripts\verify_video_analysis_models.py
.\.venv\Scripts\python.exe scripts\verify_video_analysis_models.py --asr-smoke
```

下载程序可断点续传。完成后写入 `.local_models/video_analysis/manifest.json`，记录仓库、目录、体积和文件清单 hash。

普通验证只读取 Qwen 配置、处理器、权重索引和 safetensors 头，不把 4B 权重装入显存。`--asr-smoke` 会在 CPU 上加载 Paraformer 并转写模型自带音频。

## 第一版推理预算

```text
单次只分析 1 个视频
先做镜头切分，再选 12～24 张关键帧
关键帧长边控制在 336～448
视频优先限制为 30 秒～3 分钟
ASR 与 VLM 串行运行，运行结束立即释放 GPU
```

## 数据边界

模型安装不改变采集授权边界。只有自有、许可或书面授权内容可以自动下载并进入完整视频分析；普通第三方公开视频默认只处理人工合法提供的本地样本或授权范围内的公开指标。

## 当前验证状态（2026-08-26）

- 4 组模型均已下载到 `.local_models/video_analysis`，总占用约 10.24 GiB，并生成了文件清单。
- Qwen3-VL-4B-Instruct 的配置、处理器、2 个权重分片及 713 个索引张量已通过离线完整性检查。
- Paraformer 已在 CPU 上完成中文语音识别冒烟测试，能够返回文字和时间戳；首次推理 RTF 约 0.302，预热后约 0.035。
- 本轮没有强行加载完整 Qwen 视频模型：检查时 RTX 5070 Ti 仅剩约 4.8 GiB 空闲显存，已有其他任务正在占用显卡。释放显存后再执行首条视频端到端测试，避免中断现有任务。
