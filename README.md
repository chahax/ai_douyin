# AI 剧本与视频制作平台

本项目围绕创作简报、完整剧本、导演安排、视频请求预览、逐段生成和用户人工审核运行。
用户可以在文本阶段和视频片段之间暂停、比较版本、提交反馈并恢复；账号研究提供可选输入，
浏览器发布和运营复盘是独立下游。

截至 2026-10-02，核心流程和已发现的 P1 闭环已完成离线验收。v23 修复了运行中反馈丢失，
仍需完善完整页面操作链、执行锁恢复工具，以及真实创作质量和服务运行证据。

## 从这里开始

- [项目介绍](docs/PROJECT_INTRO.md)：产品目标、核心功能与当前阶段。
- [大模型项目分析与操作导航](docs/AI_PROJECT_GUIDE.md)：阅读顺序、代码定位、执行入口和恢复边界。
- [文档索引](docs/README.md)：区分现行说明、专门流程与历史资料。
- [创作平台当前实现](docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md)：现行合同、治理绑定和 F01–F07 状态。
- [操作指南](docs/USER_GUIDE.md)：文本调试、单段候选、人工批准、合成与交付。
- [系统架构](docs/SYSTEM_ARCHITECTURE.md)和[当前能力](docs/CURRENT_CAPABILITIES.md)。
- [创作阶段调试](docs/CREATIVE_STAGE_DEBUGGING.md)：断点、单步、反馈、版本和恢复。

## 执行边界

- 文本自动推进、断点和单步使用同一运行器。必修反馈、待核实审核、未知外部结果或预算不足阻止推进。
- 新治理任务绑定 v23；普通入口的协议默认值和旧任务绑定以实际代码、`state.json` 为准，不能统一改绑。
- 生成服务成功且文件完整保存后，视频内容状态为 `awaiting_human_review`。助手不主动抽帧、听看、ASR 或调用音画审核模型。
- 用户明确批准当前视频及服务返回的原始尾帧后，才可继续紧邻下一段；被拒绝的片段回到有证据的责任阶段修复。
- 合成成功仍等待用户整片审核。发布需要已批准成片、绑定账号、平台主动 AI 声明和虚构说明读回；待核验保留提交锁。
- 同任务恢复保留累计调用、token、返修和本稿视频失败账本。换目录、改焦点或清理登记不产生新额度。
- 文本调用、媒体生成和浏览器发布分别按用户已有授权执行；分析或预览任务不自动触发付费生成与发布。

## 当前证据与下一步

[v23 验收](data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)
保存 743 项核心和 13 项 UI 回执；[独立复核](data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)
另重跑 18 项反馈边界并核对源码和工件哈希。它们证明相应离线执行行为，真实创作效果和生产全链路仍待验证。

当前优先完善分段工作台并开展人工质量试点；核心责任拆分和字段依赖优化逐步推进。
完整清单见[实现文档的剩余项](docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md#独立复核后的剩余项)。

## 历史路线

2026-09-04 退出生产的 `presenter_anime`、`dual_framepack_active` 和 `single_template`
及其样片保留为历史资产，不能恢复为默认生产入口。通用工作流中的
`video_pipeline=disabled_pending_redesign` 针对这些旧路线；当前创作候选通过上述独立显式入口执行。

[视频流程 V2 历史设计基线](docs/VIDEO_PIPELINE_V2_BASELINE.md)和
[重置归档](docs/archive/2026-09-video-pipeline-reset/ARCHIVE_MANIFEST.md)用于追溯。
