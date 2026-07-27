# 本地 ComfyUI「剧本到视频」技术路线与环境说明

> 环境盘点日期：2026-07-26  
> 模型保留/清理分类更新：2026-07-27  
> 目标硬件：NVIDIA GeForce RTX 5070 Ti 16GB  
> 目标：把“剧情梗概/剧本 → 人物档案 → 分镜 → 人物参考图 → 分镜视频 → 审核修复 → 成片”固化成可换剧本、可换画风、可复用的本地生产流程。

## 1. 结论先行

当前机器已经具备可工作的图像与视频生成基础，不需要重新搭建一套 ComfyUI，也不需要立即下载另一批大型视频模型。

近期最合理的方向是：

1. 先把已经验证过的“医院走廊”流程固化成**分阶段工作流模板**，而不是做一个一次运行十几个小时、失败后全部重来的超大 ComfyUI 图。
2. 把人物身份、画风和动作拆成三个独立控制层：
   - 人物身份：角色母版图 + PuLID/可选 IP-Adapter + 后续角色 LoRA。
   - 画风：风格预设 + 风格参考图 + 可选风格 LoRA。
   - 动作：分镜首帧 + Hero Motion 提示词 + DWPose/OpenPose/驱动视频。
3. 视频模型按镜头风险路由：
   - 低风险微动、背面、远景：LTX-2.3 I2V。
   - 一般人物动作：Wan2.2 TI2V 5B。
   - 面部表情与说话：LivePortrait/Sonic/SadTalker。
   - 明确全身动作或角色替换：Wan2.2 Animate。
   - 手部、系鞋带、下蹲等高风险动作：短镜头拆分、姿态驱动、局部修复和剪辑遮掩，不强求一个长镜头一次生成。
4. 下一项最值得补齐的是 **SDXL OpenPose ControlNet 权重**。目前已装 `comfyui_controlnet_aux`，它能生成姿态预处理图，但本地 `models/controlnet` 里没有实际 ControlNet 模型权重。
5. Wan2.2 I2V A14B、FLUX 大型训练等暂时不列为优先项。它们可以提高上限，但会明显增加 16GB 显存机器的等待时间、内存卸载压力和调试成本。

## 2. 当前本地环境

### 2.1 硬件和系统

| 项目 | 当前状态 |
|---|---|
| 操作系统 | Windows 10，NT 10.0.19045 |
| PowerShell | 5.1.19041.6456 |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| 显存 | 16303 MiB，约 15.9GB |
| NVIDIA 驱动 | 610.62 |
| CUDA UMD | 13.3 |
| GPU 模式 | WDDM |

这套硬件适合 FP8/量化模型、分块 VAE、CPU offload 和中等分辨率视频。它不适合同时常驻多个 14B/22B 全精度模型。

### 2.2 ComfyUI 与 Python

| 项目 | 当前状态 |
|---|---|
| ComfyUI 路径 | `D:\IT\AI_vido\ComfyUI` |
| ComfyUI 地址 | `http://127.0.0.1:8190` |
| 启动参数 | `main.py --listen 127.0.0.1 --port 8190` |
| ComfyUI 版本 | 0.28.0 |
| Git 提交 | `83082a51c420a364b15ea5f40d61da74e35b2da5` |
| Python | 3.14.3 |
| PyTorch | 2.11.0+cu130 |
| Torch CUDA | 13.0 |
| torchvision | 0.26.0+cu130 |
| torchaudio | 2.11.0+cu130 |
| ComfyUI 前端 | 1.42.8 |
| transformers | 5.4.0 |
| diffusers | 0.38.0 |
| accelerate | 1.14.0 |
| safetensors | 0.8.0rc0 |
| xformers | 未安装 |

注意：

- ComfyUI 官方说明 Python 3.14 可以运行，但部分自定义节点依赖可能有兼容问题；Python 3.13 支持更成熟，遇到疑难节点时可用 3.12 作为退路。当前环境已能运行，因此**不要为了“统一版本”立即重装**，只在出现明确兼容故障时建立第二套隔离环境。[ComfyUI 官方仓库](https://github.com/comfy-org/ComfyUI)
- 未安装 xformers 不等于无法生成；当前 PyTorch 可使用 SDPA。只有某个工作流的显存或速度测试明确证明有收益时，才考虑补装。

### 2.3 已安装的主要自定义节点

| 节点目录 | 主要用途 | 状态 |
|---|---|---|
| `ComfyUI-LTXVideo` | LTX 图生视频/文生视频 | 已安装 |
| `ComfyUI-WanVideoWrapper` | Wan 系列视频推理与控制 | 已安装，提交 `088128b` |
| `ComfyUI-LivePortraitKJ` | 人脸表情、头部动作驱动 | 已安装 |
| `ComfyUI_Sonic` | 音频驱动人物视频 | 已安装，提交 `9a3c1ef` |
| `comfyui_controlnet_aux` | DWPose/OpenPose 等预处理器 | 已安装 |
| `ComfyUI-segment-anything-2` | SAM2 主体分割、遮罩和合成 | 已安装 |
| `ComfyUI-VideoHelperSuite` | 视频载入、帧序列、合成导出 | 已安装，提交 `4ee72c0` |
| `PuLID_ComfyUI` | 人物身份特征控制 | 已安装，提交 `93e0c4c` |
| `ComfyUI-KJNodes` | 常用图像/视频辅助节点 | 已安装 |

重要区别：`comfyui_controlnet_aux` 是**姿态检测/预处理器集合**，不是 ControlNet 权重本身。当前本机可得到 DWPose 骨架图，但还缺少适配 SDXL/Animagine 的 OpenPose ControlNet 模型。

### 2.4 已安装的主要模型

当前 `ComfyUI\models` 约占 195.7GB。以下是本次流程相关的主要模型。

#### 静态图像

| 本地模型 | 大小约 | 用途 |
|---|---:|---|
| `animagine-xl-3.1.safetensors` | 6.46GB | 动漫、Q版、插画风人物母版 |
| `flux1-schnell-fp8.safetensors` | 16.05GB | 快速高质量文生图、写实或 3D 风格母版 |
| `ip-adapter_pulid_sdxl_fp16.safetensors` | 0.74GB | PuLID SDXL 身份控制 |
| `clip_vision_h.safetensors` | 1.18GB | 视觉参考编码 |
| InsightFace AntelopeV2 | 约 0.37GB | 人脸检测与身份特征 |

#### 视频

| 本地模型 | 大小约 | 用途 |
|---|---:|---|
| `ltx-2.3-22b-dev.safetensors` | 22.71GB | LTX-2.3 完整模型 |
| `ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors` | 26.29GB | LTX 快速蒸馏 FP8 |
| `gemma_3_12B_it.safetensors` | 22.71GB | LTX 文本编码 |
| LTX 视频/音频 VAE | 约 1.69GB | LTX 解码 |
| `wan2.2_ti2v_5B_fp16.safetensors` | 9.31GB | Wan 5B 文生/图生视频 |
| `Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors` | 17.14GB | 角色动作驱动/替换 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.27GB | Wan 文本编码 |
| Wan VAE | 约 1.55GB | Wan 解码 |
| `lightx2v_I2V_14B_480p...LoRA` | 0.69GB | Wan I2V 加速 LoRA |

#### 面部与后期

| 本地模型 | 用途 |
|---|---|
| LivePortrait 模型组 | 头部姿态、眨眼、嘴型和表情驱动 |
| SAM2 节点与相关资产 | 主体跟踪、局部遮罩、分层合成 |
| Whisper Tiny（Sonic 目录） | 音频/语音相关处理 |

### 2.5 已验证项目资产

| 资产 | 路径 |
|---|---|
| 医院走廊 V4 成片交付目录 | `D:\IT\ai_douyin\deliverables\hospital_corridor_v4` |
| 分镜与提示词报告 | `D:\IT\ai_douyin\deliverables\hospital_corridor_v4\STORYBOARD_AND_PROMPTS.md` |
| Q版毛绒 3D 风格预设 | `D:\IT\ai_douyin\presets\styles\chibi_plush_3d.json` |
| 林默/小满 Q版人物锚点 | `D:\IT\ai_douyin\data\qa\hospital_character_reference\chibi_plush_3d\linmo_xiaoman_anchor_v1.png` |
| 用户提供的画风参考 | `D:\IT\ai_douyin\assets\style_references\chibi_plush_3d_reference.jpg` |

### 2.6 模型与工具的保留/清理分类

以下分类依据本地文件、项目工作流和文档引用综合判断。这里的“可删除”只表示**清理候选**，本次没有删除现有模型。

状态定义：

- **在使用/保留**：已有项目、工作流或风格预设明确引用，删除会直接破坏当前能力。
- **按需保留**：当前主线不一定调用，但后续镜头或备用路线需要，暂时不建议删除。
- **可清理候选**：当前没有形成有效能力，或者是失败下载/缓存；确认后可以清理。
- **依赖不明，勿直接删除**：看似重复，但不同节点可能写死了目录；必须先做节点加载测试。

#### 2.6.1 当前在使用或明确应保留的模型

| 模型或模型组 | 本地路径 | 状态 | 依据 |
|---|---|---|---|
| FLUX.1 Schnell FP8 | `models\checkpoints\flux1-schnell-fp8.safetensors` | 在使用/保留 | 项目默认 checkpoint、Q版毛绒风格预设及多个静态图工作流明确引用 |
| Animagine XL 3.1 | `models\checkpoints\animagine-xl-3.1.safetensors` | 在使用/保留 | `assets\workflows\animagine_keyframe.json` 和风格预设引用；还是 SDXL OpenPose 路线的底模 |
| LTX-2.3 蒸馏 Transformer | `models\unet\LTX2\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors` | 在使用/保留 | 已验证 LTX 视频主线 |
| LTX Gemma 文本编码 | `models\clip\gemma_3_12B_it.safetensors` | 在使用/保留 | 当前 LTX 蒸馏工作流明确引用 |
| LTX text projection | `models\checkpoints\ltx-2.3-text-proj-only.safetensors` | 在使用/保留 | 当前 LTX API/提示词工作流明确引用 |
| LTX 视频/音频 VAE | `models\vae\LTX-Kijai\` | 在使用/保留 | LTX 视频与音频解码 |
| LTX Ingredients IC-LoRA | `models\loras\LTX\ltx-2.3-22b-ic-lora-ingredients-0.9.safetensors` | 在使用/保留 | 参考图/故事板路线 |
| Wan2.2 TI2V 5B | `models\diffusion_models\wan2.2_ti2v_5B_fp16.safetensors` | 在使用/保留 | `assets\workflows\wan22_i2v_4step.json` 明确引用 |
| Wan2.2 Animate 14B FP8 | `models\diffusion_models\Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors` | 按需保留 | 下蹲、起身、全身动作和角色替换路线 |
| UMT5 XXL FP8 | `models\text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 在使用/保留 | Wan 文本编码依赖 |
| Wan2.2 VAE | `models\vae\wan2.2_vae.safetensors` | 在使用/保留 | Wan2.2 解码依赖 |
| PuLID SDXL | `models\pulid\ip-adapter_pulid_sdxl_fp16.safetensors` | 在使用/保留 | Q版毛绒风格预设已登记身份控制路线 |
| CLIP Vision H | `models\clip_vision\clip_vision_h.safetensors` | 在使用/保留 | PuLID/视觉参考编码路线；它不是 XLabs Flux IP-Adapter 要求的 CLIP-L |
| LivePortrait 模型组 | `models\liveportrait\` | 在使用/保留 | 面部微动工作流和已验证视频明确引用 |
| SAM2 Small FP16 | `models\sam2\sam2.1_hiera_small-fp16.safetensors` | 在使用/保留 | 主体跟踪、遮罩、分层合成 |

#### 2.6.2 已安装但属于备用路线

| 模型或模型组 | 大小约 | 状态 | 删除影响 |
|---|---:|---|---|
| `checkpoints\svd_xt_1_1.safetensors` | 4.45GB | 按需保留 | 可能影响 Sonic/SVD 路线；若完全不用 Sonic 和 SVD，可作为整组清理候选 |
| `loras\Wan22_relight\WanAnimate_relight_lora_fp16.safetensors` | 1.34GB | 按需保留 | 删除后失去 Wan Animate relight 路线 |
| `vae\wan_2.1_vae.safetensors` | 0.24GB | 按需保留 | 删除后部分 Wan2.1 或旧工作流可能无法载入 |
| `clip\LTX\ltx-2.3_text_projection_bf16.safetensors` | 2.15GB | 按需保留 | 与当前 projection 文件 SHA256 不同，不是简单重复；可能服务另一套 LTX 节点 |
| LTX 完整/开发版三件套 | 约 70.28GB | 冷备/高风险清理候选 | 包括 `checkpoints\ltx-2.3-22b-dev`、`text_encoders\ltx-2.3-22b-dev`、`text_encoders\ltx-2.3-22b-dev-with-proj`；当前找到的主线工作流使用蒸馏版，但删除会失去完整质量/另一套节点路线 |

LTX 完整/开发版占用最大，但不应仅凭文件名判断重复。若需要腾出约 70GB，必须先：

1. 导出所有 LTX API 工作流；
2. 搜索工作流 JSON 中是否引用这三个文件；
3. 重启 ComfyUI 并分别验证蒸馏视频、IC-LoRA、音频和放大流程；
4. 先移动到隔离备份目录观察，不直接永久删除。

#### 2.6.3 明确或较安全的清理候选

| 文件/目录 | 大小约 | 分类 | 说明 |
|---|---:|---|---|
| `models\checkpoints\.cache\huggingface\download\*.incomplete` | 2.50GB | 可清理候选 | 2026-03 的失败下载残留，不是有效模型 |
| `custom_nodes\_liveportrait_install` | 0 | 可清理候选 | 空的安装暂存目录 |
| `custom_nodes\__pycache__` | 可忽略 | 可清理候选 | Python 缓存，可自动重建 |
| `loras\lightx2v_I2V_14B_480p_...safetensors` | 0.69GB | 可清理候选 | 当前没有匹配的 Wan I2V 14B 主模型；保留它不会单独形成可用能力 |

#### 2.6.4 看似重复但不要直接删除

本地 InsightFace AntelopeV2 在下面两个目录各有一套：

```text
models\insightface\antelopev2\
models\insightface\models\antelopev2\
```

`glintr100.onnx` 和 `1k3d68.onnx` 已做 SHA256 比较，两处内容完全相同，理论上重复约 0.37GB。但是 PuLID、InsightFace 或其他节点可能分别查找这两个固定目录，因此分类为**依赖不明，勿直接删除**。只有在逐个节点验证搜索路径后，才能合并。

#### 2.6.5 自定义节点状态

| 节点 | 状态 | 是否可删 |
|---|---|---|
| `ComfyUI-LTXVideo` | 在使用 | 不可删 |
| `ComfyUI-WanVideoWrapper` | 在使用 | 不可删 |
| `ComfyUI-KJNodes` | 多个视频节点的基础依赖 | 不可删 |
| `ComfyUI-VideoHelperSuite` | 视频读写与合成 | 不可删 |
| `comfyui_controlnet_aux` | DWPose/OpenPose 等预处理 | 保留；即使暂时没有 ControlNet 权重也会用于生成姿态图 |
| `ComfyUI-segment-anything-2` | SAM2 遮罩合成 | 不可删 |
| `ComfyUI-LivePortraitKJ` | 面部微动 | 不可删 |
| `PuLID_ComfyUI` | SDXL 人物身份路线 | 保留 |
| `ComfyUI_Sonic` | 音频驱动备用路线 | 按需保留；若未来完全不做口型/数字人，可连同 SVD 依赖一起评估 |
| `x-flux-comfyui` | 已重启加载并通过 8 镜头关键帧实测 | 新增强工作流依赖；保留 |

#### 2.6.6 ControlNet 与 Flux IP-Adapter 当前真实状态

截至 2026-07-27 本次更新：

- 已将 `InstantX/FLUX.1-dev-Controlnet-Union` 主权重安装到 `models\controlnet\InstantX_FLUX1_dev_Controlnet_Union\diffusion_pytorch_model.safetensors`。
- 已将 xinsir SDXL OpenPose 主权重安装到 `models\controlnet\xinsir_sdxl_openpose\diffusion_pytorch_model.safetensors`。
- 已将 `x-flux-comfyui` 解压到 `custom_nodes\x-flux-comfyui`；它要求的 GitPython、einops、transformers、diffusers、sentencepiece、OpenCV 在当前 ComfyUI Python 环境中均已存在。
- 已将 `XLabs-AI/flux-ip-adapter-v2` 安装到 `models\xlabs\ipadapters\ip_adapter.safetensors`。
- 已将配套 OpenAI CLIP ViT-L/14 安装到 `models\clip_vision\openai_clip_vit_l14\model.safetensors`；本地已有的 `clip_vision_h.safetensors` 是另一模型，不能互相替代。
- Downloads 中的原始下载文件仍保留，未删除，可作为离线备份。
- `LoadFluxIPAdapter`、`ApplyFluxIPAdapter`、`ApplyAdvancedFluxIPAdapter` 已在 ComfyUI 重启后成功加载；`ip_adapter.safetensors` 与 OpenAI CLIP ViT-L/14 已完成 8 镜头关键帧实测。
- 本机 `Flux.1 Schnell FP8 + x-flux-comfyui` 必须使用 `XlabsSampler`。核心 `KSampler` 实测报 `DoubleStreamBlock.forward() got unexpected keyword argument 'attn_mask'`，不能作为这套增强模板的采样器。
- InstantX Flux Union 已作为备选权重安装，但本项目没有把它纳入成片主线，仍需以后针对具体姿态镜头单独验证。

“已下载”“文件已安装”“重启后已验证”是三个不同状态。本次 Git 快照保存的是接入这些新组件之前的稳定基线；新组件不会覆盖该基线。

远程备选信息：

| 备选 | 应下载文件 | 下载页 | 若以后安装的建议位置 |
|---|---|---|---|
| InstantX FLUX.1-dev ControlNet Union | `diffusion_pytorch_model.safetensors`，约 6.6GB；同时保存 `config.json` | [Hugging Face](https://huggingface.co/InstantX/FLUX.1-dev-Controlnet-Union/tree/main) | `models\controlnet\InstantX_FLUX1_dev_Controlnet_Union\` |
| XLabs Flux IP-Adapter V2 | `ip_adapter.safetensors`，约 1.06GB | [Hugging Face](https://huggingface.co/XLabs-AI/flux-ip-adapter-v2/tree/main) | `models\xlabs\ipadapters\` |
| IP-Adapter 配套 CLIP-L | `model.safetensors`，约 1.71GB | [OpenAI CLIP ViT-L/14](https://huggingface.co/openai/clip-vit-large-patch14/tree/main) | `models\clip_vision\model.safetensors` |

InstantX Union 和 XLabs Flux IP-Adapter 都面向 FLUX.1-dev，并受 FLUX.1-dev 非商业许可约束；不能因为本地已有 Apache 2.0 的 Flux Schnell，就推定这些适配器也可直接商用。

## 3. 当前能力和已知缺口

### 已经能完成

- 剧情梗概拆分为人物档案、分镜和逐镜头提示词。
- 用 FLUX Schnell 或 Animagine XL 生成人物参考图。
- 用 LTX-2.3 和 Wan2.2 5B 进行图生视频。
- 用 LivePortrait 处理表情和头部微动。
- 用 Wan Animate + DWPose 驱动较明确的人体动作。
- 用 SAM2 做主体遮罩和分层合成。
- 用 VideoHelperSuite/FFmpeg 组装镜头、音频和成片。
- 同一剧情切换写实、动漫、Q版毛绒 3D 等风格。

### 当前主要缺口

1. **人物一致性已有可用增强模板，但还没有完全产品化**
   已验证 XLabs Flux IP-Adapter + 人物母版图可以改善跨镜头脸型连续性；跨大量场景、侧脸、全身和复杂动作时仍会漂移，长期角色仍建议训练角色 LoRA。

2. **姿态预处理器与两套 ControlNet 权重已经具备，但尚未形成统一姿态模板**
   本机已有 DWPose/OpenPose 预处理、xinsir SDXL OpenPose 和 InstantX Flux Union；下一步是针对下蹲、行走、手部动作分别做兼容性和参数验收。

3. **已有 Flux IP-Adapter，但 SDXL IPAdapter Plus 仍未安装**
   当前 XLabs 方案服务 Flux 关键帧；若要在 Animagine/SDXL 中把人物内容参考与画风参考拆开控制，仍可按需安装 ComfyUI IPAdapter Plus。它不是当前阻塞项。

4. **没有 FLUX Redux**  
   Redux 能增强图像变化和参考图重绘，但 FLUX.1 Redux dev 受 FLUX dev 非商业许可约束，下载前需要先确认使用场景。

5. **复杂连续动作仍是生成模型的弱项**  
   例如下蹲、系鞋带、手指抓握、鞋带受重力垂落。解决办法不是单纯加大提示词，而是：
   - 缩短镜头；
   - 使用真人/3D/DWPose 驱动；
   - 将起身、下蹲、手部特写拆成多个镜头；
   - 用 SAM2、局部重绘和剪辑完成最后 10%。

6. **Python 3.14 的自定义节点兼容风险**  
   当前可运行，先保持；若某个节点反复因二进制依赖失败，再建立 Python 3.13 的独立 ComfyUI 环境，不污染现有环境。

## 4. 建议的最终生产架构

不要把全部逻辑压进一个巨大 ComfyUI 工作流。建议采用“外部项目控制器 + 多个稳定 ComfyUI 模板”的结构。

```text
剧情梗概/剧本
  ↓
人物档案 + 风格预设 + 分镜表
  ↓（人工确认）
角色母版图/表情表/服装表
  ↓（身份确认）
各镜头首帧或关键帧
  ↓（构图确认）
按风险自动选择 LTX / Wan 5B / LivePortrait / Wan Animate
  ↓
逐镜头候选视频（每镜头 2～4 个）
  ↓
质量检测 + 人工挑选 + 局部修复
  ↓
FFmpeg 合成、配音、音乐、字幕
  ↓
交付视频 + 工作流 + 参数清单 + 可复现清单
```

外部控制器建议维护四类文件：

```text
projects/<project_id>/
  project.json              # 项目、画幅、时长、帧率、风格
  characters/
    linmo.json              # 人物档案、母版图、LoRA/PuLID 参数
  shots/
    shot_001.json           # 每个镜头的动作、首帧、模型和参数
  workflows/
    image_master_api.json   # ComfyUI API 工作流模板
    ltx_i2v_api.json
    wan_ti2v_api.json
    wan_animate_api.json
  outputs/
    shot_001/candidate_01.mp4
  manifest.json             # 模型文件、哈希、seed、提示词、审核结果
```

这样以后替换剧本时，只替换项目数据和提示词；更换画风时，替换风格预设、参考图和相应 checkpoint/LoRA，不需要重建整条系统。

## 5. 人物固定与多画风策略

### 5.1 人物身份层

每个主角至少保留：

- 正面、左 45°、右 45°、侧面；
- 半身、全身；
- 中性、悲伤、微笑、哭泣等表情；
- 固定发型、肤色、面部比例、服装色号和配件；
- 一张无复杂背景、光照中性的“唯一身份锚点”。

第一阶段使用“锚点图 + PuLID/参考图 + I2V”。当同一角色要反复出现在多个项目中时，再训练角色 LoRA。

### 5.2 风格层

人物身份和画风不要写死在同一个 LoRA 中。建议：

- 角色 LoRA：只学林默/小满是谁；
- 风格 LoRA 或风格参考：只学写实、动漫、毛绒 Q 版等视觉语言；
- 项目预设：保存 checkpoint、LoRA 权重、正/负提示词、灯光、色彩和后期 LUT。

当前 Q版毛绒 3D 风格可以固定。最稳的做法是先生成该风格下的角色母版图，再从同一母版图生成所有镜头首帧，而不是让视频模型直接从文字重新想象角色。

### 5.3 角色 LoRA 的建议

16GB 显存优先训练 **SDXL/Animagine 角色 LoRA**：

- 工具：[kohya_ss](https://github.com/bmaltais/kohya_ss)
- 数据：15～30 张高质量、身份一致、角度与表情覆盖合理的图；
- 分辨率：1024 桶；
- batch size：1；
- 开启 cache latents、gradient checkpointing；
- 角色与画风分开训练。

FLUX LoRA 可作为后续实验。`ai-toolkit` 的官方 FLUX 示例偏向 24GB 显存环境，16GB 需要更激进的量化和卸载，训练时间也更长，因此不作为近期主线。[ai-toolkit](https://github.com/ostris/ai-toolkit)

## 6. 镜头模型路由建议

| 镜头类型 | 首选技术 | 原因 | 16GB 建议 |
|---|---|---|---|
| 走廊空镜、人物静坐、背面离开 | LTX-2.3 I2V 蒸馏版 | 微动、氛围和运镜效率较好 | 先低分辨率/短帧数试片 |
| 一般走路、转身、抬手 | Wan2.2 TI2V 5B | 动作与画面质量平衡 | 开启 offload，先 480p 级试片 |
| 面部特写、忍泪、眨眼、轻微转头 | LivePortrait | 比扩散视频更稳定可控 | 使用干净正脸/半侧脸母版 |
| 说话、音频驱动 | Sonic 或 SadTalker | 口型和语音同步 | 先短句，避免过大头部运动 |
| 下蹲、起身、全身姿态复制 | Wan2.2 Animate + DWPose/驱动视频 | 有明确动作来源 | 每段 2～4 秒，减少连续复合动作 |
| 系鞋带、拿小物体、复杂手指 | 分镜拆分 + OpenPose/手部首帧 + SAM2 合成 | 直接生成最容易出现解剖错误 | 用手部特写和反应镜头遮掩动作连接 |
| 真正的首尾帧强约束 | Wan2.2 I2V A14B 或专门首尾帧工作流 | 比 5B 更稳定、支持 480p/720p | 暂缓；原始模型资源要求很高 |

### LTX 参数约束

LTX-2.3 官方建议宽高可被 32 整除，帧数满足 `8n + 1`。例如 65、81、97 帧。蒸馏模型的官方检查点说明是 8 steps、CFG=1；本地具体节点若有封装默认值，以已验证工作流为准。[LTX-2.3 模型页](https://huggingface.co/Lightricks/LTX-2.3)

### 通用试片参数

这些是 RTX 5070 Ti 16GB 的起始区间，不是所有模型的固定值：

- 竖屏首帧：768×1024 或 832×1216；
- 视频试片：512×768、576×1024，或模型原生的相近桶；
- 成品前再升到 720p 级，并使用分块 VAE；
- 帧率：先生成 16～24fps，再用 RIFE/FFmpeg 插帧到交付帧率；
- 单镜头：2～5 秒；
- 每镜头先生成 2～4 个低成本候选；
- 固定 seed、模型文件名、LoRA 权重、参考图哈希和提示词；
- 大模型使用 FP8/量化、model offload、text encoder CPU offload；
- 不让 LTX、Wan、FLUX 大模型同时驻留显存。

## 7. 分阶段实施路线

### P0：冻结已经成功的流程

目标：保证医院走廊项目可以复现。

- 保存每个镜头的 API 工作流、seed、提示词、模型文件名和输入图。
- 把人物母版、风格参考、动作驱动、音频和成片分目录管理。
- 为失败镜头记录“失败类型”：身份漂移、动作不自然、手部错误、画风漂移、闪烁。
- 不在这一阶段升级 Python、Torch 或批量更新全部自定义节点。

验收：在不手动重连节点的情况下，可重新生成任意一个镜头。

### P1：做成可换剧本的分阶段母工作流

目标：输入新剧本后，自动生成项目骨架。

- 剧本解析器输出 Character Bible、Shot List、Hero Motion。
- 自动为镜头标注风险级别：低/中/高。
- 依据风险选择静态图和视频工作流模板。
- 每一步设置人工确认点：人物、首帧、低清视频、成片。
- 外部脚本通过 ComfyUI API 排队，不把所有阶段塞进一个图。

验收：替换剧情梗概后，自动产生新的项目目录、分镜 JSON 和待生成队列。

### P2：强化人物一致性和画风切换

目标：同一角色跨镜头不换脸，切换风格仍保留人物核心特征。

- 先用已装 PuLID 建立身份锁定模板。
- 对长期角色训练 SDXL/Animagine 角色 LoRA。
- 可选安装 IPAdapter Plus，用不同输入分别控制人物和风格。
- 每种画风建立一个独立 preset。
- 增加角色对比图和人工身份审核。

验收：10 个不同景别/角度的静态首帧中，角色可被稳定辨认，服装和发型不漂移。

### P3：动作控制与高风险镜头

目标：降低下蹲、系鞋带、手部动作的畸形率。

- 安装 SDXL OpenPose ControlNet 权重。
- 用 DWPose 从真人参考视频或人工关键帧生成驱动序列。
- 将复合动作拆成“起始姿态 → 单一动作路径 → 结束姿态”。
- 高风险手部镜头采用单独首帧、局部重绘和 SAM2 合成。
- 建立“动作失败后自动降级”策略：长镜头改短镜头、全身改中近景、动作改反应镜头。

验收：关键姿态正确，四肢数量与方向正常，动作路径可读；不要求模型在一个长镜头里完成多个高难动作。

### P4：自动质量检查与修复

目标：把明显失败候选在人工审核前自动淘汰。

- 抽帧和接触表；
- 场景切变、黑帧、冻结帧检测；
- 光流/闪烁指标；
- 人脸或角色相似度；
- SAM2 遮罩一致性；
- RIFE 插帧与时域修复；
- 审核结果写回 manifest。

可参考：

- [SAM 2 官方仓库](https://github.com/facebookresearch/sam2)
- [RIFE 官方仓库](https://github.com/hzwer/ECCV2022-RIFE)
- [VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)

### P5：产品化

目标：形成“选剧本、选画风、选角色、开始分阶段生成”的简单界面。

界面不应只提供一个“全部生成”按钮，而应提供：

1. 生成人物方案；
2. 确认人物；
3. 生成分镜首帧；
4. 确认构图；
5. 生成低清候选；
6. 选择/重试失败镜头；
7. 高清生成与合成。

这种分阶段设计能显著降低大模型长时间运行后整批报废的成本。

## 8. 建议下载清单

### 8.1 优先级 A：建议近期补齐

| 模型/节点 | 作用 | 官方地址 | 本地目标 | 备注 |
|---|---|---|---|---|
| SDXL OpenPose ControlNet | 用 DWPose/OpenPose 精确控制 Animagine/SDXL 首帧姿态 | [xinsir/controlnet-openpose-sdxl-1.0](https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0) | `D:\IT\AI_vido\ComfyUI\models\controlnet` | 约 5GB 级；下载具体 safetensors 前核对模型页说明 |

这是当前唯一明确的“功能缺口型”下载。安装前先备份工作流，并只下载模型页要求的主权重，避免把整个仓库的重复文件全部拉下。

### 8.2 优先级 B：按需求安装

| 模型/节点 | 作用 | 官方地址 | 是否必须 |
|---|---|---|---|
| ComfyUI IPAdapter Plus | 分离控制人物内容和风格参考 | [cubiq/ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | 否；项目已进入维护模式，先用 PuLID 验证 |
| IP-Adapter 模型 | 配合 IPAdapter Plus 使用 | [h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter) | 仅安装节点后需要 |
| PuLID 官方模型 | 补充不同底模的人物身份权重 | [guozinan/PuLID](https://huggingface.co/guozinan/PuLID) | 当前已有 SDXL 版本；缺哪种再下哪种 |
| FLUX.1 Redux dev | 参考图变体、重绘、风格迁移 | [black-forest-labs/FLUX.1-Redux-dev](https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev) | 否；受 FLUX dev 非商业许可约束 |
| kohya_ss | 训练 SDXL/Animagine 角色 LoRA | [bmaltais/kohya_ss](https://github.com/bmaltais/kohya_ss) | 角色需要跨项目复用时安装 |

### 8.3 优先级 C：暂缓的大模型

| 模型 | 官方地址 | 暂缓原因 |
|---|---|---|
| Wan2.2 I2V A14B | [Wan-AI/Wan2.2-I2V-A14B](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B) | 官方原始单卡示例注明至少 80GB 显存；ComfyUI 量化/offload 可降低门槛，但在 16GB 上仍会很慢。只有确实需要更稳定 I2V/首尾帧时再评估量化版 |
| FLUX 角色 LoRA 本地训练 | [ostris/ai-toolkit](https://github.com/ostris/ai-toolkit) | 官方示例偏向 24GB；先用 SDXL LoRA 获得更高投入产出比 |
| 其他重复视频基础模型 | 各模型官方页 | 当前 LTX 2.3、Wan 5B、Wan Animate 已覆盖主要任务；先提高工作流和控制质量 |

### 8.4 已安装模型的官方来源

- [FLUX.1 Schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
- [Animagine XL 3.1](https://huggingface.co/cagliostrolab/animagine-xl-3.1)
- [LTX-2.3](https://huggingface.co/Lightricks/LTX-2.3)
- [LTX ComfyUI 节点](https://github.com/Lightricks/ComfyUI-LTXVideo)
- [Wan2.2 官方代码](https://github.com/Wan-Video/Wan2.2)
- [Wan2.2 TI2V 5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B)
- [Wan2.2 Animate 14B](https://huggingface.co/Wan-AI/Wan2.2-Animate-14B)
- [WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)
- [LivePortrait 官方仓库](https://github.com/KlingAIResearch/LivePortrait)
- [LivePortrait ComfyUI 节点](https://github.com/kijai/ComfyUI-LivePortraitKJ)
- [ControlNet Aux](https://github.com/Fannovel16/comfyui_controlnet_aux)
- [PuLID 官方仓库](https://github.com/ToTheBeginning/PuLID)

## 9. 许可与商用提醒

下载模型前不要只看代码仓库许可证，还要查看具体权重的模型卡。

| 模型 | 模型页标注 | 使用提醒 |
|---|---|---|
| FLUX.1 Schnell | Apache 2.0 | 模型卡允许个人、科研和商业用途，仍需遵守可接受使用政策 |
| FLUX.1 Redux dev | FLUX dev 非商业许可 | 商用前必须重新核对权利范围 |
| Wan2.2 系列 | Apache 2.0 | 生成内容仍需符合法律与平台规则 |
| LTX-2.3 | LTX-2 Community License | 发布或商用前检查社区许可全文 |
| Animagine XL 3.1 | OpenRAIL++ | 注意模型卡中的使用限制 |

本项目文档中的“建议下载”不等于自动授权商用。

## 10. 建议的下一步执行顺序

1. **冻结现有医院走廊工作流**：保存所有成功镜头的 API JSON、seed、模型、参考图和提示词。
2. **建立项目 JSON 规范**：先让同一套流程能换剧情，不做模型升级。
3. **固化 SDXL OpenPose 与 Flux Union 姿态模板**：权重已经就位，下一步重点验收“下蹲/系鞋带”。
4. **制作 Q版毛绒 3D 的完整人物母版**：正面、45°、侧面、全身和表情表。
5. **用 PuLID 测试 10 张跨镜头静态首帧**：确认身份一致性上限。
6. **若仍漂移，再训练 SDXL 角色 LoRA**。
7. **最后再评估 SDXL IPAdapter Plus、FLUX Redux 或 Wan I2V A14B**，不要同时引入多个变量；Flux IP-Adapter 增强模板已经完成实测。

近期里程碑建议定义为：

> 输入一段新剧情和一个风格预设，在不改 ComfyUI 节点连线的情况下，自动建立项目目录，生成人物档案、分镜 JSON、人物候选图和逐镜头任务；用户只需在人物、首帧和低清视频三个关口确认或重试。

这比“完全无人值守的一键成片”更现实，也更适合当前本地显卡和生成模型的稳定性。
