---
doc_status: current
doc_category: video-environment
last_reviewed: 2026-08-25
model_usage: Wan2.2 Animate Move 的本机安装状态、固定配置、社区方案选择和后续启动验收基线。
---

# Wan2.2 Animate Move：本机环境与社区工作流

## 当前结论

截至 2026-08-25，Wan2.2 Animate Move 已完成**环境安装和静态校验**，但按本轮要求没有启动 ComfyUI、没有加载节点，也没有生成样片。本机同时保留官方原生工作流和项目生成的 16GB 优化工作流；两者不得混写成同一份验证结果。

| 层级 | 状态 | 说明 |
|---|---|---|
| 工作流文件 | 已安装 | 已写入 ComfyUI 用户工作流目录 |
| 第三方节点 | 已安装 | Kijai WanVideoWrapper 与 WanAnimatePreprocess 均已就位 |
| 模型权重 | 已就位 | 14B FP8、T5、VAE、CLIP Vision、SAM2、YOLO、ViTPose 和可选 LoRA 均存在 |
| 静态配置 | 已校验 | 路径、节点类型和 16GB 参数通过安装脚本校验 |
| 节点加载 | 未验证 | 本轮没有启动 ComfyUI，因此不能声称 `/object_info` 或启动日志已通过 |
| GPU/成片 | 未验证 | 尚未执行 3 秒动作驱动烟测，更不是生产可用结论 |

静态运行时检查：ComfyUI venv 使用 `torch 2.11.0+cu130`，`torch.cuda.is_available()` 为 `true`；OpenCV `4.13.0` 可导入；ONNX Runtime `1.27.0` 当前提供 CPU/Azure provider。

## 安装位置与固定版本

- ComfyUI：`D:\IT\AI_vido\ComfyUI`
- 官方原生工作流：`D:\IT\AI_vido\ComfyUI\user\default\workflows\video_wan2_2_14B_animate.json`
- 官方原生工作流本机 SHA-256：`d94ab3e3746a6a3d6fb45fdc225cbfcddfa2064fd232b4b0a414b037d8f91fcb`
- 项目 16GB 优化工作流：`D:\IT\AI_vido\ComfyUI\user\default\workflows\wan22_animate_move_rtx5070ti_16gb.json`
- 项目 16GB 优化工作流 SHA-256：`052f514ab10c2782953252cbe19be9d1735e48844f9617394f832021125fbdd5`
- 主节点：[Kijai/ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)，本机提交 `088128b224242e110d3906c6750e9a3a348a659b`
- 预处理节点：[Kijai/ComfyUI-WanAnimatePreprocess](https://github.com/kijai/ComfyUI-WanAnimatePreprocess)，包版本 `1.0.3`
- 预处理源码压缩包 SHA-256：`51ddaed4b76291056ff47489042fa21eb96276519119e127013b983dd072fd06`

`ComfyUI-WanVideoWrapper` 目录有大量 Python 3.14 兼容改动，不能直接 `git pull` 或重装覆盖。升级前必须先保存补丁并做独立 worktree/副本验证。

## 模型与预处理资产

| 用途 | 本机相对路径 |
|---|---|
| Wan2.2 Animate 14B FP8 | `models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors` |
| T5 | `models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| VAE | `models/vae/wan_2.1_vae.safetensors` |
| CLIP Vision | `models/clip_vision/clip_vision_h.safetensors` |
| SAM2 | `models/sam2/sam2.1_hiera_small-fp16.safetensors` |
| ViTPose | `models/detection/onnx/wholebody/vitpose-l-wholebody.onnx` |
| YOLO | `models/detection/process_checkpoint/det/yolov10m.onnx` |
| Relight LoRA（可选） | `models/loras/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors` |
| LightX2V LoRA（可选） | `models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` |

当前 ONNX Runtime 只有 `CPUExecutionProvider`，所以工作流把姿态检测固定为 CPU；Wan 14B 扩散仍由 CUDA/PyTorch 执行。以后若安装 `onnxruntime-gpu`，必须先处理 CPU/GPU 包共存问题，再把配置改为 `CUDAExecutionProvider`，不能只改下拉框。

## RTX 5070 Ti 16GB 初始参数

| 参数 | 值 |
|---|---:|
| 模式 | `Move` |
| 画幅 | `480×832` 竖屏 |
| 帧率 | `16 fps` |
| 单次帧数 | `49`，约 3.06 秒 |
| frame/context window | `49 / 49` |
| block swap | `30` |
| attention | `sdpa` |
| model load | `offload_device` |

这些是首次烟测参数，不是最终画质参数。先验证人物身份、腿部动作、视线和手臂轨迹，再逐步增加帧数或分辨率；禁止直接用完整 40 秒参考视频一次生成。

## 可重复配置

配置真相来源：`config/comfyui_wan22_animate_move.json`。

只检查、不写入：

```powershell
.venv\Scripts\python.exe scripts\configure_wan22_animate_move.py --check-only
```

重新安装工作流：

```powershell
.venv\Scripts\python.exe scripts\configure_wan22_animate_move.py
```

目标文件存在但内容不同时，脚本默认拒绝覆盖；确认只替换项目生成的目标文件时才使用 `--force`。脚本不会启动 ComfyUI。

## 非官方/社区方案筛选

| 方案 | 适用点 | 当前决定 |
|---|---|---|
| [Kijai WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper) + [WanAnimatePreprocess](https://github.com/kijai/ComfyUI-WanAnimatePreprocess) | 社区采用量较高，Move/Mix、预处理和 16GB offload 能力完整 | **已安装，当前主线** |
| [WanAnimatePlus](https://github.com/wuwukaka/ComfyUI-WanAnimatePlus) | 长视频连接、多参考图、前缀帧和漂移修正 | 暂不安装；要求整条节点链替换，不能与 Kijai 原链混搭 |
| [Filmclusive 工作流包](https://github.com/Filmclusive/ComfyUI-workflows) | 有 Capture Motion、图参考视频参考和角色替换变体 | 只做参数/布局参考；节点密集，不直接进入生产环境 |
| [IAMCCS 工作流与节点](https://github.com/IAMCCS/comfyui-iamccs-workflows) | Native WanAnimate、LoRA 和长视频扩展 | 暂不安装；新增节点面较大，后续需单独审计 |
| [16GB 单/双/多人动作迁移样例](https://github.com/jing713507/wan22-comfyui-motion-transfer-workflow) | 声称面向 16GB，包含单双人和姿态对齐 | 仅研究；当前社区采用量极低，不能直接信任其“多人稳定”结论 |
| [秋葉aaaki：Wan2.2 Animate 低显存动作迁移流](https://www.youtube.com/watch?v=RhibjzJLbM8) / [搭建讲解](https://www.youtube.com/watch?v=uWbPiHl1fq4) | 面向低显存的 Move 动作迁移和中文搭建说明；公开说明称模型、插件和工作流在评论区 | 通用 `ComfyUI-aki-v2.7z` 已下载并静态审计，但包内 `user/default/workflows` 为空，**未取得这份目标 Move JSON**；继续保留为来源待办 |
| [秋葉aaaki：Wan2.2 Animate 视频无缝替换 + GGUF](https://www.bilibili.com/video/BV1QZ4MzfELa/) | 更接近 Mix/人物替换：保留源视频镜头与动作，替换参考角色；GGUF 面向低显存 | 本次通用整合包不含可确认的目标 Mix 用户工作流；仍需从对应分享单独取得 JSON 后审计 |

秋葉方案需要区分两条链：低显存“动作迁移”属于 **Move**，与本机当前主线解决同一问题；“视频无缝替换”属于 **Mix/人物替换**，更适合测试保留参考视频背景、构图、动作和光色。秋葉整合包/启动器只是运行环境，不是独立的视频模型或工作流类型。

在拿到秋葉工作流文件后，先只提取 JSON 并做静态比较，不直接把整个整合包覆盖到 `D:\IT\AI_vido\ComfyUI`：

1. 保存原下载地址、发布时间、压缩包 SHA-256 和解压文件清单。
2. 检查 JSON 的节点类型、模型文件名、Move/Mix 模式、block swap、量化格式、分辨率、帧数、采样步数和后处理。
3. 与本机 `wan22_animate_move_rtx5070ti_16gb.json` 做节点级差异；重复节点不重装。
4. 新节点和 Python 依赖在隔离副本验证，禁止用秋葉整合包覆盖本机已有 Python 3.14 兼容修改。
5. 先做同一输入的 3 秒烟测，再决定是否吸收参数或另存为候选工作流。

## 秋葉通用整合包审计与烟测（2026-08-25）

- 下载文件：`C:\Users\c\Downloads\ComfyUI-aki-v2.7z`，物理大小 `3,512,395,676` 字节。
- SHA-256：`4764258FF33B2516CFFB6AE984653E83E66588BBEE9BA772FB5A08D1D3863947`。
- 归档格式：7zAES、solid archive；共 68,382 个文件、9,981 个目录。先完成静态审计，随后为用户要求的真实烟测在隔离目录启动包内 Python；未运行图形启动器。
- 先将 JSON 工作流提取到 `data/workflow_archive/aki_v2_20260825`：共 174 个 JSON、3,429,758 字节；随后完整解压到 `data/tools/aki_v2_runtime`，与现有 ComfyUI 隔离。
- JSON 构成：WanVideoWrapper 示例 26 个、HunyuanVideoWrapper 示例 12 个、ComfyUI 官方模板 136 个。
- 包内 `ComfyUI/user/default/workflows` 目录存在但无 JSON 文件，因此这份整合包不能替代目标秋葉 Move/Mix 分享，也不能覆盖现有 ComfyUI。
- 本机已单独安装的官方 `video_wan2_2_14B_animate.json` 和 16GB 优化工作流不来自这次秋葉通用包，两者证据应继续分开记录。
- 已在独立端口 8191 启动秋葉环境，并挂载现有模型运行原生 Wan2.2 5B I2V，成功生成 320x576、33 帧 MP4。6/8/12 步抖动分数分别为 0.19078、0.19312、0.80491；手机可保持可见，但交接动作不足，且全部弱于 LTX 对照 0.06347。证据见 `data/qa/reference_404263_aki_v2_20260825/AKI_V2_SMOKE_REPORT.md`。这只证明整合包运行环境可用，不证明目标 Move/Mix 流可用。

## 下一次允许启动时的验收顺序

多画风与其他视频工作流不会混在首次烟测里；完整候选和分轮规则见 [ComfyUI 多工作流、多画风统一测试计划](COMFYUI_MULTI_STYLE_WORKFLOW_TEST_PLAN.md)。

1. 启动后检查日志中 `ComfyUI-WanVideoWrapper` 与 `ComfyUI-WanAnimatePreprocess` 是否成功注册。
2. 用 `/object_info` 核对 `WanVideoAnimateEmbeds`、`OnnxDetectionModelLoader`、`PoseAndFaceDetection` 等关键节点。
3. 导入已安装工作流，确认所有模型下拉框没有红色缺失项。
4. 先用单人、全身可见、无遮挡的 3 秒驱动视频生成 49 帧烟测。
5. 机器检查首/中/尾帧后，再人工看完整连续播放；通过后才进入逐微镜头生产。
6. 双人拉手镜头不能作为第一个烟测。先验证单人动作，再考虑分别驱动或分层合成。
