---
doc_status: current
doc_category: mainline
last_reviewed: 2026-10-02
---

# 文档索引

当前主线是 AI 剧本与视频制作平台。阅读现行行为时，从产品方向、当前实现及实际任务回执开始；
历史设计、单片特许和旧治理版本不自动适用于新任务。

## 主线阅读顺序

| 文档 | 用途 |
|---|---|
| [项目介绍](PROJECT_INTRO.md) | 核心功能、用户目标与当前阶段 |
| [方向报告](../data/qa/creative_platform_refactor_20261002/direction_report.html) | 重构方向与产品取舍 |
| [当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md) | 已接线功能、版本、审核门和剩余项 |
| [大模型项目分析与操作导航](AI_PROJECT_GUIDE.md) | 代码定位、命令选择、证据核对和恢复规则 |
| [操作指南](USER_GUIDE.md) | 日常文本与镜段操作路径 |
| [阶段调试](CREATIVE_STAGE_DEBUGGING.md) | 断点、版本、反馈和恢复 |
| [系统架构](SYSTEM_ARCHITECTURE.md) | 模块职责与依赖边界 |
| [当前能力](CURRENT_CAPABILITIES.md) | 实现状态与验证范围 |
| [架构状态](ARCHITECTURE_STATUS.md)及[开发进度](DEVELOPMENT_PROGRESS.md) | 已完成机制和下一阶段工作 |

[AGENTS.md](../AGENTS.md)保存用户执行要求。最新会话中的用户授权、任务冻结版本、当前代码与回执
共同决定一次操作是否可执行；导航或历史样片本身不授予新增调用、视频批准或发布权限。

## 专门流程

- [可复用视频创作](REUSABLE_VIDEO_WORKFLOW.md)：简报、完整新稿、表达参考和资产复用；按日期保留演进记录。
- [视频制作记录](SCRIPT_VIDEO_RUN.md)：指定制作任务及其来源、叙事和审核记录；旧审核默认已被最新用户要求替代。
- [动作与对白时序合同](CREATIVE_ACTION_TIMING_CONTRACT.md)：文本计划的动作、交互、摄影和时序。
- [账号绑定与运营维护](operations/ACCOUNT_BINDING_AND_MAINTENANCE.md)。
- [账号内容机会架构](ACCOUNT_CONTENT_OPPORTUNITY_ARCHITECTURE.md)及[热点运营闭环](TREND_OPERATIONS_CLOSED_LOOP.md)。
- [抖音主动 AI 声明](DOUYIN_AI_DECLARATION.md)。
- [Seedance 参考资料](reference/seedance/README.md)：资料快照；实际调用以绑定模型、当前服务合同和回执为准。
- [本地导演台](DIRECTOR_WORKBENCH.md)及[导演稿文本验收](DIRECTOR_PIPELINE_TESTING.md)：具体实验或模块说明，不代表整个平台生产质量已通过。

## 当前验收与治理

- [v23 F01 验收](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)。
- [v23 独立反馈边界复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)。
- [剩余重构方向](../data/qa/creative_platform_refactor_20261002/implementation_review_v22/review_report.html)：F01 已由 v23 修复；F02–F07 状态以当前实现文档为准。
- [v23 迁移边界](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)：旧任务不静默改绑或重领预算。

工作目录说明可继续维护。治理包中的 `implementation_documents` 是当时验收的冻结快照，
不会随本索引更新；运行源码及冻结包完整性另按其哈希清单核对。

## 历史资料

- [视频流程 V2 历史设计基线](VIDEO_PIPELINE_V2_BASELINE.md)：2026-09 的重置设计，包含已被替代的自动内容检查设想。
- [截至 v22 的实现归档](archive/creative_workflow/CREATIVE_WORKFLOW_IMPLEMENTATION_through_v22.md)。
- [2026-09 视频生产线重置归档](archive/2026-09-video-pipeline-reset/ARCHIVE_MANIFEST.md)。
- `archive/2026-08-video-workflow/`、`archive/2026-07-cleanup/` 和 `archive/video-debug/` 保留更早资料。

历史资料可用于定位旧任务，不能据此恢复旧生产路线、改写原审核或把过去的特许推广到当前任务。
