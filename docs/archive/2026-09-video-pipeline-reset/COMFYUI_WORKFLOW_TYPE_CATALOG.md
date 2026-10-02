---
doc_status: current
doc_category: video-workflow-catalog
last_reviewed: 2026-08-26
model_usage: ComfyUI 视频工作流按功能类型的候选目录、本机就绪度和分组测试协议；不表示目录中的工作流已经可运行。
---

# ComfyUI 视频工作流类型目录与分组测试计划

## 1. 这份目录解决什么问题

`COMFYUI_MULTI_STYLE_WORKFLOW_TEST_PLAN.md` 解决的是“同一个动作生成任务，用哪种画风、哪条动作链路观感更好”。本文件补齐其他功能类型：文生视频、首尾帧、相机控制、人物替换、音频驱动、局部重绘、重打光、超分和长视频等。

**工作流类型**和**画风**不是一回事：

- 类型决定输入、输出和控制方式，例如“原视频 + 新人物参考图 → 人物替换视频”。
- 画风决定视觉外观，例如写实、二维动漫、柔和 3D 或墨线漫画。
- 不同类型不能硬塞进同一排行榜。人物替换和超分的输入、成功条件完全不同，只能先在组内测试，再汇总成本、稳定性和适用场景。

## 2. 状态口径

所有候选统一使用下面六级证据状态：

| 状态 | 含义 |
|---|---|
| `catalogued` | 只发现官方/社区方案或本机示例 JSON；节点、模型、依赖可能不完整。 |
| `static_ready` | 本机节点、主要模型和工作流静态文件基本齐全；尚未启动生成。 |
| `smoke_passed` | 已启动并生成可播放的最小样片，保存了工作流快照和运行清单。 |
| `single_run_evaluated` | 已有一次或少量实测及审计证据，但未完成多 seed 对比，不能写成 `benchmarked`。 |
| `benchmarked` | 已按本文件协议完成多 seed 对比和人工审核。 |
| `production_ready` | 已接入项目任务、审核、失败恢复和审计产物。 |

初始盘点阶段没有启动 ComfyUI；2026-08-26 已形成 Wan2.2 5B TI2V、LTX 2.3 I2V 和受控混合三条 103.63 秒 v2 文件，但连续性复核已撤回三条片原来的“通过/推荐”结论，统一标记为 `continuity_failed_needs_recut`。随后生成的受控 v3 已通过编码、黑帧、冻结、响度、声画时长和结构边界门禁，状态为 `technical_pass_continuity_review_pending`，必须完成 1.0 倍速带声音的整片人工审核后才能推荐。原生 Wan2.2 Animate Move 只有单次镜头级实测，不能标记为 `benchmarked`；VACE、Fun Control、SteadyDancer、ATI 等仍不能标记为可运行。

## 3. 八类工作流总览

| 组 | 类型 | 典型输入 → 输出 | 对当前推书短片的价值 | 本机最高状态 |
|---|---|---|---|---|
| `G01` | 首帧、角色与分镜准备 | 剧本/参考图 → 批准首帧、角色母版、分镜图 | 先锁定观感、构图和角色身份 | `static_ready` |
| `G02` | 基础视频生成 | 文本/单图/首尾帧 → 新视频 | 生成剧情微镜头主体 | Wan 5B / LTX I2V 为 `single_run_evaluated`；v2 需重剪，受控 v3 待整片人工审核 |
| `G03` | 动作、姿态、轨迹与相机控制 | 驱动视频/姿态/轨迹 → 受控视频 | 解决动作不合理、腿不动、镜头表达弱 | 原生 Animate Move 为镜头级 `single_run_evaluated`；未证明通用能力 |
| `G04` | 身份参考、人物替换与多主体 | 原视频/参考人物 → 换人或身份稳定视频 | 复用好动作和构图，同时生成原创角色 | `static_ready`（仅 Ingredients 子项） |
| `G05` | 口型、说话、唱歌与音频驱动 | 人像/视频 + 音频 → 表演视频 | 旁白出镜、对白和口型同步 | `catalogued` |
| `G06` | 视频编辑、扩图与重打光 | 视频 + 遮罩/编辑要求 → 修改后视频 | 修局部错误、背景、画幅和灯光 | `catalogued` |
| `G07` | 超分、插帧与时序修复 | 低清/抖动视频 → 交付级视频 | 放大、补帧、去闪烁和最终质检 | 项目已有部分非 ComfyUI 工具；ComfyUI 候选为 `catalogued` |
| `G08` | 长视频延展、拼接与交付 | 多段微镜头/首段 → 长片 | 将批准微镜头组成完整推书视频 | 项目拼接链可用；生成式延展为 `catalogued` |

## 4. 各组候选与本机状态

### 4.1 G01：首帧、角色与分镜准备

| 子类型 | 本机候选 | 当前证据 | 状态 |
|---|---|---|---|
| 二维动漫首帧 | Animagine XL 3.1 | checkpoint 与项目分镜工作流存在 | `static_ready` |
| 写实/3D/漫画首帧 | FLUX Schnell + `x-flux-comfyui` | checkpoint、节点与示例存在 | `static_ready` |
| 参考身份/构图约束 | x-flux IP-Adapter、OpenPose/Union ControlNet | 节点或模型部分存在；需逐工作流适配 | `static_ready`（部分） |
| 多镜头分镜 | 项目 `animagine_keyframe.json`、`flux_storyboard` 类工作流 | 工作流文件存在，尚未纳入统一烟测 | `static_ready` |

这一组的交付物不是视频，而是经过人工批准的角色母版和首帧。首帧未批准时，不应进入耗时的视频生成。

### 4.2 G02：基础视频生成

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 文生视频 `T2V` | LTX 2.3、Wan 2.1/2.2 示例 | LTX 节点与基础模型存在；Wan T2V 专用大模型未确认 | LTX `static_ready`，Wan `catalogued` |
| 单图生视频 `I2V` | Wan2.2 TI2V 5B、LTX 2.3 I2V | 两者已有单 seed 长片与来源审计；v2 的 72 切镜配额造成静帧尾巴、重复窗口和动作重置，已判需重剪；受控 v3 改为 30 个有效切镜并待整片人工审核 | `single_run_evaluated` |
| 首尾帧生视频 `FLF2V` | [Wan2.1 FLF2V](https://github.com/Wan-Video/Wan2.1) | Kijai 示例存在；专用 14B 720P 权重未发现，16GB 显存成本高 | `catalogued` |
| 参考图生视频 `R2V` | [VACE](https://github.com/ali-vilab/VACE)、LTX Ingredients | VACE 例程存在但主模型未发现；Ingredients IC-LoRA 已有，示例仍需适配本机模型布局 | `catalogued` / 部分 `static_ready` |
| 图像 + 音频联合视频 | Wan2.2 Ovi、LTX 音视频链 | 例程存在，专用权重/音频条件模型未齐 | `catalogued` |

首尾帧工作流适合明确“开始姿态”和“结束姿态”，但不能保证中间动作一定符合人体力学。它应和动作迁移组并列测试，不能替代动作控制。

### 4.3 G03：动作、姿态、轨迹与相机控制

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 完整动作迁移 | Wan2.2 Animate Move | 原生 `WanAnimateToVideo` + Animate 14B FP8 已完成 5 个单人镜头；v2 中跨引擎拼接导致动作回退，v3 只保留同一动作内单引擎使用；`p12` 因裁切驱动残留第二人肢体而硬拒绝 | `single_run_evaluated`（双人和通用能力未就绪） |
| 单双/多人动作迁移 | [ZL 5060Ti 16G 工作流](https://github.com/jing713507/wan22-comfyui-motion-transfer-workflow) | 仓库已下载并固定提交；主环境约缺 30 种节点、秋葉环境约缺 24 种，主环境 Kijai 注册异常；未运行批量安装脚本 | `catalogued`（运行阻塞） |
| 姿态控制 | SCAIL、[SteadyDancer](https://github.com/MCG-NJU/SteadyDancer)、One-to-All、Fun Control | SteadyDancer 官方仓库已下载审计，但专用模型未发现；其他候选仍只有示例或线索 | `catalogued` |
| 点/局部轨迹控制 | LTX Motion Track、[Wan ATI Track](https://github.com/bytedance/ATI)、TimeToMove | ATI 官方仓库已下载，原生 `WanTrackToVideo` 节点存在，但 ATI 专用权重缺失；Motion Track 也缺专用 LoRA | `catalogued` |
| 深度/边缘/姿态联合控制 | LTX Union Control、Wan Fun Control、VACE | 例程存在；专用 IC-LoRA/主模型和部分预处理节点未齐 | `catalogued` |
| 相机运动控制 | [ReCamMaster](https://github.com/KlingAIResearch/ReCamMaster)、Wan Fun Camera | Kijai 例程存在；ReCam/Fun 专用权重未发现 | `catalogued` |

这组是当前最重要的专项组。动作迁移解决“人怎么动”，轨迹控制解决“手或物体往哪里走”，相机控制解决“观众怎么看”，三者不应混为一个参数。

### 4.4 G04：身份参考、人物替换与多主体

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 多参考身份/场景成分 | LTX 2.3 Ingredients | Ingredients IC-LoRA 已存在；需把官方例程适配为本机可加载的全模型或蒸馏链 | `static_ready`（需适配） |
| 主体参考生视频 | Phantom Subject2Vid、Stand-In | Kijai 例程存在；专用模型未发现 | `catalogued` |
| 原视频人物替换 | [MoCha](https://github.com/Orange-3DV-Team/MoCha)、[秋葉 Wan2.2 Animate Mix/GGUF](https://www.bilibili.com/video/BV1QZ4MzfELa/)、[Mix KJ 遮罩/SDPose 流](https://www.bilibili.com/video/BV15LS1BCEh5/) | Kijai MoCha 例程存在但专用权重未发现；已下载的秋葉通用整合包没有用户工作流 JSON，不能证明目标 Mix 流已取得；Mix KJ 仍待独立静态审计 | `catalogued` |
| 多人姿态/多人动作 | WanAnimate、SCAIL、One-to-All | 节点示例存在；双人接触仍需单独硬门禁 | `catalogued` |

这一组最接近“从参考视频保留动作和背景、把人物重新生成成原创角色”。它比逐帧抽原片做普通 I2V 更可审计，因为输入、遮罩、参考身份和保留区域可以明确记录。

### 4.5 G05：口型、说话、唱歌与音频驱动

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 单人长口播/视频配音 | [InfiniteTalk](https://github.com/MeiGen-AI/InfiniteTalk) | Kijai I2V/V2V 例程存在；专用模型和音频编码器未发现 | `catalogued` |
| 多人对白 | [MultiTalk](https://github.com/MeiGen-AI/MultiTalk) | WanVideoWrapper 支持线索存在；本机未发现专用权重 | `catalogued` |
| LTX 视频对口型 | LTX 2.3 Lipdub | 官方例程存在；Lipdub IC-LoRA 未发现 | `catalogued` |
| 单图说话/头像 | FantasyTalking、FantasyPortrait、SkyReels Talking Avatar、LongCat Avatar | Kijai 例程存在；专用权重未发现 | `catalogued` |
| 轻量头像链 | 本项目 SadTalker、LivePortrait、Sonic | 已有专项文档和既有试验记录；不等于全身剧情视频 | 按各专项文档判断 |

音频驱动组必须单独测音画同步，不能沿用纯画面综合分。完整人物肢体自然度、口型同步和声画时长都要过门禁。

### 4.6 G06：视频编辑、扩图与重打光

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 局部重绘/去物体 | LTX Inpaint、VACE Masked V2V | 例程存在；对应 IC-LoRA/VACE 主模型未发现 | `catalogued` |
| 扩图/横竖版适配 | LTX Outpaint、VACE Expand Anything | 例程存在；对应专用权重未发现 | `catalogued` |
| 视频转视频/风格迁移 | LTX V2V、VACE V2V、AnimateDiff 社区链 | LTX 例程存在；专用 V2V IC-LoRA 未发现，AnimateDiff 未安装 | `catalogued` |
| 视频重打光 | [UniLumos](https://github.com/alibaba-damo-academy/Lumos-Custom)、LTX HDR | Kijai/LTX 例程存在；专用权重未发现 | `catalogued` |
| 角色/背景替换 | MoCha、VACE Swap Anything | 例程或官方方案存在；专用权重未发现 | `catalogued` |

编辑组的第一原则是“未编辑区域保持不变”。如果只是编辑一只手却让整个人脸、背景和构图重生成，即使画面漂亮也判失败。

### 4.7 G07：超分、插帧与时序修复

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 生成式视频超分 | [FlashVSR](https://github.com/OpenImagingLab/FlashVSR)、LTX Pixel Spatial Upscaler | 例程存在；专用模型/IC-LoRA 未发现 | `catalogued` |
| 普通放大 | ESRGAN 类节点 | 本机 `upscale_models` 未发现有效模型 | `catalogued` |
| 插帧 | RIFE/FILM 类工作流 | 当前节点目录未发现对应实现 | `catalogued` |
| 去闪烁/时序修复 | 项目 `VIDEO_TEMPORAL_REPAIR.md` 链路 | 已有本地工具和专项审核协议；是否可用看该文档与样片证据 | 项目能力，不归 ComfyUI 候选状态 |

FlashVSR 官方特别提示，缺少其局部稀疏注意力实现的第三方早期版本可能明显降质。因此后续不能只看“能跑”，还要记录具体实现和模型版本。

### 4.8 G08：长视频延展、拼接与交付

| 子类型 | 候选 | 本机证据与缺口 | 状态 |
|---|---|---|---|
| 基于首段延展 | VACE `firstclip`、SkyReels Diffusion Forcing | 例程/官方方案存在；专用模型未发现 | `catalogued` |
| 多参考图分段接续 | [WanAnimatePlus](https://github.com/wuwukaka/ComfyUI-WanAnimatePlus)、[ComfyUI-CustomNodeKit](https://github.com/user2318/ComfyUI-CustomNodeKit) | 两者均提供多参考图与上下文/过渡接续能力；后者另有色漂修正和 Uni3C 运镜；本机未安装 | `catalogued` |
| 长口播 | InfiniteTalk V2V | 例程存在；专用模型未发现 | `catalogued` |
| 微镜头拼接 | 项目 Story Video、三联画、音频混流与审核包 | 项目已有实现和文档 | 按项目主线状态判断 |
| 交付编码 | FFmpeg 标准化、字幕、音频混流 | 项目已有实现 | 按项目主线状态判断 |

长视频不建议一次生成到底。优先生产 3～5 秒可审核微镜头，再由项目流水线拼接；只有镜头内连续动作无法切开时才测试生成式延展。

## 5. 分组测试协议

### 5.1 不能跨组直接排名

统一报告可以汇总成功率、耗时、峰值显存和人工可用率，但只在同一测试组内计算质量排名：

| 测试组 | 固定输入 | 核心质量指标 | 关键硬拒绝项 |
|---|---|---|---|
| `B01_generation` | 同一剧本、批准首帧/首尾帧 | 完整观感、语义、构图、动作、身份 | 动作缺失、人物畸形、首尾条件不成立 |
| `B02_motion_control` | 同一驱动视频、角色母版 | 动作跟随、重心、手脚、身份、背景 | 肢体新增/消失、接触穿模、动作时序反转 |
| `B03_camera_control` | 同一源视频、相机轨迹 | 轨迹符合度、主体稳定、背景几何 | 主体漂移、镜头方向错误、结构崩坏 |
| `B04_identity_edit` | 同一原视频、参考身份、遮罩 | 身份一致、动作/背景保留、边缘稳定 | 未编辑区明显改变、身份混合、遮罩边缘闪烁 |
| `B05_audio` | 同一人像/视频与 WAV | 口型同步、表情、动作、音画时长 | 明显错口型、音画截断、多人口型串线 |
| `B06_editing` | 同一视频、遮罩和编辑指令 | 编辑命中、保留区域、时序一致 | 改错区域、背景重构、局部闪烁 |
| `B07_enhancement` | 同一低清视频 | 清晰度、细节保真、时序、编码 | 凭空造纹理、脸变形、帧间锐度跳变 |
| `B08_longform` | 同一 3 段素材/首段 | 接缝、身份漂移、节奏、声画连续 | 接缝跳变、累计漂色、人物身份变化 |

### 5.2 所有组共享的工程指标

- 每个候选至少 2 个 seed；不允许用单次幸运结果代表能力。
- 记录模型、LoRA、节点提交、工作流 SHA-256、提示词、输入素材 SHA-256、时长、尺寸、帧率、耗时和显存峰值。
- 保存原始输出和标准化输出；评分先看原始输出，不能用后处理掩盖模型问题。
- `smoke_passed` 只证明能运行，不能自动升级为“效果可用”。
- 任一外部人物/视频只作为内部动作或构图参考；发布候选必须记录素材授权，并优先使用原创人物与首帧。

## 6. 对当前项目的建议测试顺序

按“观感优先、避免一次下载多套大模型”的原则：

1. **P0：G01 + G02 + G03。** 先批准首帧；比较 Wan2.2 5B I2V、LTX 2.3 I2V 和 WanAnimate Move，确认“提示词动作”和“驱动动作”哪条更自然。
2. **P1：G04。** 如果驱动动作可用但人物/背景保真不足，再引入 LTX Ingredients 或 MoCha；这比继续堆动作提示词更对症。
3. **P1：相机专项。** 只有动作已经自然但镜头无观感时，才补 ReCamMaster/Fun Camera，避免同时更换人物、动作和镜头。
4. **P2：G06。** 用 Inpaint/Outpaint/Relight 修批准候选，不用它们抢救肢体已经崩坏的底片。
5. **P2：G05。** 需要角色对白或口播时，再选择 InfiniteTalk、LTX Lipdub 或既有轻量头像链。
6. **P3：G07 + G08。** 最后做超分、插帧、时序修复、拼接和交付编码。

在 P0 结果出来前，不批量安装上表所有专用模型。每次只补一个测试组所需依赖，并先做 3 秒低成本烟测。

## 7. 审计目录与机器清单

建议目录：

```text
data/qa/comfyui_workflow_type_benchmark/v1/
  inputs/
    generation/
    motion_control/
    camera_control/
    identity_edit/
    audio/
    editing/
    enhancement/
    longform/
  runs/<benchmark_group>/<candidate_id>/
    output_raw.mp4
    output_standardized.mp4
    workflow.snapshot.json
    run.manifest.json
    contact_sheet.png
    machine_gate.json
    human_review.json
  reports/
    group_ranking.json
    workflow_type_summary.md
```

机器可读的分组清单示例见 `docs/examples/comfyui_workflow_type_benchmark.example.json`。

## 8. 主要开源来源

- [Kijai ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)：本机 Wan 类例程的主要来源。
- [Lightricks ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)：LTX T2V/I2V/V2V、控制、编辑、音频和增强例程来源。
- [Wan2.1](https://github.com/Wan-Video/Wan2.1)：T2V、I2V、FLF2V 与 VACE 基础来源。
- [VACE](https://github.com/ali-vilab/VACE)：生成、参考、姿态、局部编辑、替换、扩图和延展的一体化方案。
- [ReCamMaster](https://github.com/KlingAIResearch/ReCamMaster)：视频相机轨迹重拍。
- [MoCha](https://github.com/Orange-3DV-Team/MoCha)：保留源视频动作与场景的人物替换。
- [InfiniteTalk](https://github.com/MeiGen-AI/InfiniteTalk) / [MultiTalk](https://github.com/MeiGen-AI/MultiTalk)：单人长口播与多人音频驱动视频。
- [UniLumos](https://github.com/alibaba-damo-academy/Lumos-Custom)：图像/视频重打光。
- [FlashVSR](https://github.com/OpenImagingLab/FlashVSR)：生成式流式视频超分。
- [ZL Wan2.2 16G 动作迁移工作流](https://github.com/jing713507/wan22-comfyui-motion-transfer-workflow)：单双/多人分档、骨骼对齐和表情捕捉候选。
- [ComfyUI-CustomNodeKit](https://github.com/user2318/ComfyUI-CustomNodeKit)：多参考图、长视频上下文窗口、姿态和运镜扩展。
- [WanAnimatePlus](https://github.com/wuwukaka/ComfyUI-WanAnimatePlus)：多参考图注入和片段无缝接续。
- [Filmclusive 工作流集](https://github.com/Filmclusive/ComfyUI-workflows)：Wan Animate、MoCha、LTX 和 VACE 的社区布局对照；只作静态参考，不把其效果描述当作本机验证结果。

## 9. 2026-08-26 当前生产路由结论

本轮证明“按镜头路由”比继续寻找一个万能工作流更可靠：

| 能力区间 | 首选 | 已知边界 |
|---|---|---|
| 轻动作、表情、稳定构图 | LTX 2.3 I2V | 大幅肢体和长时间手机交互较弱 |
| 走路、购物、较大动作 | Wan2.2 5B I2V | 复杂灯光、链条和重复手机等交互道具不稳定 |
| 单人全身姿态迁移 | Wan2.2 Animate Move | 驱动必须只有一个完整人物；裁切旁人肢体会被误识别，不能外推双人接触 |
| 可读手机 UI、金额、证据和短道具动作 | 确定性插镜 | 不交给生成模型伪造精确状态 |

三条 v2 虽可播放，但连续性复核均为 `continuity_failed_needs_recut`，不再推荐。当前只保留受控 v3 作为待审候选：机器技术门禁和结构边界审计已通过，动作自然度、转场连续性与整体观感仍待 1.0 倍速完整人工审核。完整路径、SHA-256、证据和失败边界记录在 `data/qa/reference_404263_full_workflows_20260825/FULL_WORKFLOW_MODIFICATION_LOG.md` 与 `FULL_CANDIDATE_DELIVERY_MANIFEST.json`；发布、抖音上传和番茄回填仍全部禁止。
