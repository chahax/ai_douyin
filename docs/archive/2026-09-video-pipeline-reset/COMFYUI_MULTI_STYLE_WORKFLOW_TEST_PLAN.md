---
doc_status: current
doc_category: video-benchmark
last_reviewed: 2026-08-26
model_usage: ComfyUI 多工作流、多画风候选清单与统一测试协议；不表示所有候选已安装或可运行。
---

# ComfyUI 多工作流、多画风统一测试计划

> 本文件只负责“画风 × 动作生成”的横向测试。文生视频、首尾帧、相机控制、人物替换、音频驱动、局部编辑、超分和长视频等其他功能类型，见 [ComfyUI 视频工作流类型目录](COMFYUI_WORKFLOW_TYPE_CATALOG.md)。不同功能类型按各自输入合同和门禁分组测试，不跨组直接排名。

## 1. 目标与判断边界

目标不是收集最多的工作流，而是用同一组素材回答三个问题：

1. 哪种画风的整体观感最接近目标短片？
2. 哪条视频工作流的动作、肢体和时序最自然？
3. 最佳画风与最佳动作工作流组合后，能否稳定生产微镜头？

画风主要由**首帧/参考图、底模、LoRA、IP-Adapter 和提示词**决定；动作与时序主要由**WanAnimate、LTX、Fun Control、AnimateDiff 等视频链路**决定。不能在同一轮同时更换画风和视频链路，否则结果不可归因。

## 2. 统一画风组

第一轮固定使用已经安装的 Wan2.2 Animate Move，只替换参考人物图。

| ID | 画风 | 视觉要求 | 用途 |
|---|---|---|---|
| `s01_cinematic_real` | 写实电影感 | 自然肤色、真实布料、低锐化、电影光比 | 检查真人剧情上限 |
| `s02_clean_2d_anime` | 干净二维动漫 | 清晰线稿、稳定平涂、少量赛璐璐阴影、无写实毛孔 | 对标用户提供的动漫短片 |
| `s03_soft_3d` | 柔和3D动画 | 真实比例、柔和材质、不过度玩具化、表情清楚 | 测试更稳定的立体人物 |
| `s04_ink_comic` | 国风/墨线漫画 | 黑白或低饱和、稳定墨线、轻纸张纹理 | 测试低色彩但高构图表现力 |

四张参考图必须保持相同：角色身份、服装、人物占画面比例、朝向、全身可见程度和背景简洁度。禁止拿“动漫半身特写”和“写实全身照”直接比较。

本机可用于准备首帧的现有资产：

- `animagine-xl-3.1.safetensors`：二维动漫候选。
- `flux1-schnell-fp8.safetensors`：写实、3D、漫画首帧候选。
- `x-flux-comfyui` 的 IP-Adapter 工作流：身份/参考图增强候选。

首帧生成不纳入第一轮视频评分；先由人工批准四张风格母版，再开始动作测试。

## 3. 视频工作流候选

### 3.1 本机优先候选

| ID | 工作流 | 主要能力 | 本机状态 | 统一测试优先级 |
|---|---|---|---|---|
| `w01_wananimate_move` | ComfyUI 原生 `WanAnimateToVideo` + WanAnimatePreprocess | 姿态驱动原创人物；成片不连接参考片像素/音频 | 5 个单人动作实测；v2 的跨引擎拼接已判连续性失败，v3 只在单个动作内使用单一引擎；`p12` 因残留第二人肢体导致姿态误识别而硬拒绝 | `single_run_evaluated`；不能外推通用能力 |
| `w02_wan22_5b_i2v` | 本机 Wan2.2 5B TI2V 原生节点链 | 用批准首帧生成动作；更依赖提示词 | 已有单 seed 103.63 秒 v2，但连续性复核判为 `needs_recut`；部分镜头在受控 v3 继续使用 | `single_run_evaluated` |
| `w03_ltx23_i2v` | [LTX 2.3 Text/Image-to-Video](https://github.com/Lightricks/ComfyUI-LTXVideo) | 首帧驱动、稳定轻动作和电影镜头表达 | 已有单 seed 103.63 秒 v2，但连续性复核判为 `needs_recut`；受控 v3 以 LTX 为主要稳定镜头来源 | `single_run_evaluated` |
| `w04_ltx23_ingredients` | LTX 2.3 Ingredients IC-LoRA | 多个参考成分控制人物/场景/风格 | Ingredients LoRA 已存在；缺 distilled LoRA，需改全模型链或补权重 | **P2** |
| `w05_ltx23_motion_track` | LTX 2.3 Motion Track IC-LoRA | 手绘轨迹约束局部移动 | 工作流存在，Motion Track LoRA 不在本机 | **P2，补模型后** |
| `w06_wan_fun_control` | [Wan Fun Control](https://docs.comfy.org/tutorials/video/wan/fun-control) | OpenPose、Depth、Canny、轨迹控制 | 示例 JSON 存在，Fun Control 主模型未发现 | **P2，补模型后** |
| `w07_scail_or_steady_dancer` | Kijai SCAIL / [SteadyDancer](https://github.com/MCG-NJU/SteadyDancer) | 更强姿态跟随、舞蹈/全身动作 | SteadyDancer 官方仓库已按提交固定并静态审计；本机缺专用模型，尚不能生成 | **P3，补模型后** |

LTX 官方节点仓库提供 I2V、V2V、Depth/Pose/Edge、Motion Track、HDR 等示例，但不同示例依赖不同 IC-LoRA；不能因为节点目录里有 JSON 就标记为可运行。

### 3.2 社区扩展候选

| ID | 社区工作流 | 候选价值 | 当前决定 |
|---|---|---|---|
| `w08_animatediff_ipadapter` | [AnimateDiff Evolved](https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved) + IP-Adapter + ControlNet | SD1.5/SDXL/动漫底模选择多，适合明显二维风格和视频转动漫 | 未安装；依赖 AnimateDiff、Advanced ControlNet、IPAdapter 等节点，先列入对照组 |
| `w09_v2v_style_transfer` | [Seamless Video Style Transfer](https://github.com/tenpel/comfyui-seamless-video-style-transfer) | Depth + LineArt 保结构，IP-Adapter 主导材质/色彩，适合真人视频转动漫或特殊材质 | 未安装；依赖约 9 组节点和多套 SD1.5 权重，只做专项风格迁移候选 |
| `w10_wananimate_plus` | [WanAnimatePlus](https://github.com/wuwukaka/ComfyUI-WanAnimatePlus) | 前缀帧、多参考、长片连接和漂移修正 | 未安装；必须整条替换节点链，不能和 Kijai 原链混搭 |
| `w11_filmclusive_capture_motion` | [Filmclusive Capture Motion](https://github.com/Filmclusive/ComfyUI-workflows) | Kijai WanAnimate 的社区布局、插值和后处理参考 | 不单独作为模型候选，只用于吸收节点布局与后处理参数 |
| `w12_hunyuan_ip2v` | [Kijai HunyuanVideoWrapper](https://github.com/kijai/ComfyUI-HunyuanVideoWrapper) IP2V | 参考图作为概念/风格提示，不只作为首帧 | 未安装；维护者已把主要能力转向原生 ComfyUI，优先级低 |
| `w13_aki_wananimate_low_vram` | [秋葉aaaki 低显存动作迁移流](https://www.youtube.com/watch?v=RhibjzJLbM8) | 候选价值是低显存配置、中文节点布局和操作简化 | 秋葉环境已用原生 Wan2.2 5B I2V 对 B2 同镜头真实出片，但并非 Move：抖动分 `0.52671`，出现手臂畸变、遮脸伪物和侵入肢体，**硬拒绝**。包内没有取得目标 Move/Mix JSON，不能把普通 I2V 冒充秋葉 Move 结论 |
| `w14_zl_motion_transfer_16g` | [ZL Wan2.2 动作迁移 5060Ti 16G 工作流](https://github.com/jing713507/wan22-comfyui-motion-transfer-workflow) | 单人、双人、多人分档；DW + OneEuro 小臂稳帧、BodyRatioMapper 骨骼对齐、双人面部独立预览 | 已下载并固定提交，静态审计发现主环境约缺 30 种节点、秋葉环境约缺 24 种，且主环境 Kijai 注册异常；没有运行一键安装脚本 | **阻塞，隔离修复后再测** |
| `w15_wan_mix_kj_mask_pose` | [Wan Animate Mix KJ 社区工作流](https://www.bilibili.com/video/BV15LS1BCEh5/) | 人物替换、动作迁移、分割遮罩和 SDPose 姿态分路，可测试“保留背景，只重生人物” | 工作流通过夸克分享；自定义节点、模型和素材许可需分别核验。只提取 JSON 审计，不采用整合包覆盖本机环境 |
| `w16_wanloop_multiref_longform` | [ComfyUI-CustomNodeKit](https://github.com/user2318/ComfyUI-CustomNodeKit) 的 WanAnimate 多参考图长视频流 | 多参考图、上下文窗口、分段接续、色漂校正、可选 Uni3C 运镜 | MIT；作者公开说明核心节点多且工作流复杂。列为长视频/镜头接续专项，不进入第一轮 3 秒动作排名 |

第三方工作流许可证不等于模型权重、LoRA 和参考素材许可证。任何候选进入发布链路前都要单独记录代码许可、模型许可和素材来源。

## 4. 固定测试素材

建议目录：

```text
data/qa/comfyui_multi_style_benchmark/v1/
  inputs/
    motion_m01_wait_and_turn_3s.mp4
    motion_m02_reach_and_pull_3s.mp4
    motion_m03_look_and_count_3s.mp4
    styles/
      s01_cinematic_real.png
      s02_clean_2d_anime.png
      s03_soft_3d.png
      s04_ink_comic.png
  runs/
  reports/
  benchmark.json
```

动作素材要求：

- `m01`：单人全身，站立、等待、转头看人；作为所有工作流的首轮硬基准。
- `m02`：伸手、接触、轻拉、对方响应；属于双人高难度，不参加第一轮。
- `m03`：看向对方并直接口头倒数；不看手表、不做无意义半蹲。
- 每段约 3 秒、16fps、人物无遮挡、脚和手尽量不出画，镜头固定。
- 可以从内部参考视频抽取动作，但公开交付只保留姿态/动作结果，不复制原视频人物身份、画面或水印。

## 5. 三轮测试顺序

### Round A：只比画风

- 固定 `w01_wananimate_move`。
- 固定 `m01_wait_and_turn_3s`。
- 依次测试 `s01` 至 `s04`。
- 选出 1～2 个观感最佳画风；不在本轮评价其他视频模型。

### Round B：只比视频工作流

- 固定 Round A 的最佳画风母版。
- 固定 `m01`、语义提示词、时长和输出规格。
- 比较 `w01`、`w02`、`w03`；准备好依赖后再加入 `w05`、`w06`、`w08`。
- 工作流不支持驱动视频时，用同一动作语义和首帧，但必须在报告中标记 `motion_source=prompt_only`，不能假装是等价姿态控制。

### Round C：复杂动作与双人

- 只使用 Round B 前两名。
- 先测 `m03`，最后测 `m02`。
- 双人失败时分别记录骨骼串线、身份互换、接触穿模、肢体新增和动作时序错误；不能只写“观感不好”。

## 6. 统一参数

| 参数 | 基准值 | 规则 |
|---|---:|---|
| 输出尺寸 | `480×832` | 所有候选先在同一低成本尺寸比较 |
| 帧率 | `16 fps` | 模型原生不同帧率时，保留原片并额外交付标准化版本 |
| 时长/帧数 | 约 `3.06 s / 49帧` | 不允许拿 2 秒和 5 秒结果直接比较 |
| seed | 固定并记录 | 不支持 seed 的工作流标记 `unsupported` |
| 后处理 | 首轮关闭插帧、锐化和放大 | 防止后处理掩盖模型真实问题 |
| 音频/字幕 | 关闭 | 第一轮只测画面、动作和时序 |
| 生成次数 | 每组合 2 个 seed | 不能用单次幸运结果代表工作流能力 |

## 7. 验收与评分

### 7.1 硬拒绝项

任一项出现即拒绝，不进入综合排名：

- 视频不可播放、黑帧、时长或画幅错误。
- 多手、多腿、肢体突然消失、严重穿模或人物身份互换。
- 关键动作完全没发生，或与动作语义相反。
- 首尾画风明显切换、脸部持续融化、背景大面积闪烁。
- 为掩盖问题进行了候选间不一致的裁剪、插帧、修脸或调色。

### 7.2 人工观感评分

用户已明确“观感首要”，人工评分权重如下：

| 项目 | 权重 | 重点 |
|---|---:|---|
| 完整观看观感 | 35 | 是否愿意继续看、节奏是否自然、有没有明显 AI 味 |
| 动作自然与连续 | 25 | 腿、手、重心、视线、接触动作是否符合常识 |
| 构图与叙事表达 | 15 | 人物关系、视线方向和动作是否表达剧本意义 |
| 画风保真与时序稳定 | 15 | 是否接近批准母版、连续播放是否漂移 |
| 角色身份一致 | 10 | 脸、发型、服装和体型是否稳定 |

速度、显存和生成耗时只作为同分候选的工程决策项，不得让“生成快但难看”的结果获胜。

机器门禁继续复用：

- `video_control/v1`
- `video_style_gate/v1`
- `video_candidate_benchmark/v1`
- `video_review_packet`

## 8. 每个候选的审计产物

每次运行必须保留：

```text
<candidate_id>/
  output_raw.mp4
  output_standardized.mp4
  workflow.snapshot.json
  run.manifest.json
  contact_sheet.png
  control.report.json
  style.report.json
  human_review.json
```

`run.manifest.json` 至少记录：工作流 ID、来源 URL、本机工作流路径、节点提交/版本、模型与 LoRA 文件名及 SHA-256、参考图、驱动视频、提示词、seed、尺寸、帧率、帧数、步数、CFG、采样器、显存峰值、耗时和异常。

候选命名：

```text
<workflow>__<style>__<motion>__seed<seed>
```

例如：

```text
w01_wananimate_move__s02_clean_2d_anime__m01_wait_and_turn__seed42
```

## 9. 当前执行顺序

1. v2 三条 103.63 秒文件已因连续性失败退出候选；当前只审核受控 v3，必须以 1.0 倍速、开启声音和字幕从头到尾连续播放，仍保持不可发布状态。
2. 通过本轮 34 秒剧情片后，再准备四张统一构图的风格母版，执行画风横测。
3. `w01` 原生 WanAnimate Move 已完成 5 个单人动作实测并进入受控完整片；只允许使用逐镜头批准窗口，仍不能外推到双人接触或含裁切旁人的驱动素材。
4. 秋葉通用包已只读审计，并仅将 JSON 抽到隔离目录；没有覆盖 `D:\IT\AI_vido\ComfyUI`，也没有运行包内脚本或可执行文件。
5. `w14` 已下载但受缺失节点和 Kijai 注册异常阻塞，只在隔离环境修复并通过单人基准后进入双人专项；`w15` 先测遮罩边缘和背景保真；`w16` 只在 3 秒微镜头稳定后测试分段接续。
6. 不提前安装 AnimateDiff、WanAnimatePlus 或大体积新模型；只有当前候选无法达到观感门槛时才进入下一梯队。

## 10. 2026-08-25 实际产物

- 原创剧本与镜头合同：`data/qa/reference_404263_multiflow_20260825/ORIGINAL_STORY_AND_SHOT_CONTRACT.md`。
- 纯 Wan 34 秒完整候选：`data/qa/reference_404263_multiflow_20260825/candidates/wan/reference_404263_original_wan_candidate.mp4`。
- Wan + LTX 34 秒混合候选：`data/qa/reference_404263_multiflow_20260825/candidates/hybrid/reference_404263_original_hybrid_candidate.mp4`。
- 两版均为 1080×1920、30fps、H.264 + AAC；黑帧、超过 1 秒冻结和音视频时长机器门禁通过。
- 两版审核报告均为 `pending_manual_review`；未授权发布、抖音上传或番茄回填。
- 混合版只在 `s04_escalation`、`s06a_luxury`、`s08a_raid` 使用 LTX，其余镜头使用 Wan，便于逐镜头归因。
- 新版 24 拍点动作/神态合同：`data/qa/reference_404263_performance_analysis_20260825/REFERENCE_PERFORMANCE_CONTRACT.md`。
- B2 同镜头实测复核：`data/qa/reference_404263_performance_benchmarks_20260825/B2_WORKFLOW_BENCHMARK_REVIEW.md`。结论为 LTX 轻动作第一、原生 Move 有条件保留、秋葉 5B 复杂肢体硬拒绝。
- 三次下载与静态审计：`data/tools/workflow_research_20260825/DOWNLOAD_AND_STATIC_AUDIT.md`。

以上 34 秒版本保留为历史基线，不再代表当前成片质量。当前版本见下一节。

## 11. 2026-08-26 完整成片复核与纠正

统一内容合同为 103.633333 秒、24 个表演拍点、1080×1920、30fps、H.264 + AAC 和正式 CosyVoice 旁白。旧计划的“72 个有效切镜”被证明是错误的强制配额：它诱发自动静帧尾巴、重复素材窗、裁切变化和同一动作跨模型。受控 v3 改为按动作需要保留 30 个有效切镜。所有版本均未使用参考视频像素或音频，且 `publish_allowed=false`。

| 候选 | 路径 | 结论 | 主要失败边界 |
|---|---|---|---|
| LTX v2 | `data/qa/reference_404263_full_workflows_20260825/candidates/ltx/reference_404263_ltx_full_candidate_v2.mp4` | `continuity_failed_needs_recut` | `p04` 约 13.75 秒由生成动作重置为自动静态母版 |
| Wan v2 | `data/qa/reference_404263_full_workflows_20260825/candidates/wan/reference_404263_wan_full_candidate_v2.mp4` | `continuity_failed_needs_recut` | `p04` 约 11.94–15.40 秒出现长静止 |
| Controlled v2 | `data/qa/reference_404263_full_workflows_20260825/candidates/controlled/reference_404263_controlled_full_candidate_v2.mp4` | `continuity_failed_needs_recut`；撤回推荐 | `p04` 约 12.24 秒同一动作由 Move 切 LTX，人物位置和动作回退 |
| Controlled v3 | `data/qa/reference_404263_full_workflows_20260825/candidates/controlled/reference_404263_controlled_full_candidate_v3.mp4` | `technical_pass_continuity_review_pending` | 技术与结构边界通过；完整观感、动作自然度和转场仍待人工整片审核 |

受控 v3 的硬规则是：同一动作不跨引擎、同一来源固定裁切、素材时间窗只向前、禁止重复精确时间窗、取消自动母版尾巴、精确末帧停留不超过 0.8 秒、慢放/拉伸不超过 1.6 倍。`p08/p14` 只在动作中间插入 1.2 秒可读 UI，再回到相邻的同源时间窗；`p19/p20` 使用同一 LTX 来源的连续窗口，让警员实际向前移动。

受控 v3 通过 ffprobe、黑帧、超过 2 秒非预期冻结、响度和声画时长门禁：黑段 `0`、冻结 `0`、`-16.3 LUFS`、LRA `6.3 LU`、true peak `-1.5 dBFS`、声画差 `0.003333s`；连续性专项测试 `18 passed`。这些结果只证明文件和代码合同，不证明人物动作自然或整片观感通过。逐边界证据、SHA-256、待审时间点和发布边界见 `data/qa/reference_404263_full_workflows_20260825/FULL_WORKFLOW_MODIFICATION_LOG.md` 与 `FULL_CANDIDATE_DELIVERY_MANIFEST.json`。

机器可读示例见 `docs/examples/comfyui_multi_style_benchmark.example.json`。
