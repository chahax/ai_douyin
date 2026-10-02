---
doc_status: archived_do_not_use_as_current
doc_category: archive_manifest
last_reviewed: 2026-09-04
---

# 2026-09 视频生产线重置归档

## 归档原因

原视频生成路线未达到期望的视觉质量和生产闭环要求，因此整体退出当前文档与生产入口。
本目录保存历史设计、实验记录、提示词和示例，只用于追溯。

## 退役实现

- `presenter_anime`
- `dual_framepack_active`
- `single_template`

## 内容范围

本次共移动 106 份历史文件：

- 89 份视频专项设计、质量工具说明、案例报告、提示词和示例。
- 17 份重置前的主线总览、能力、架构、进度、用户指南、部署说明、流程图、番茄视频闭环和根 README 快照，位于
  `pre_reset_mainline/`。

目录结构保留了原来的 `design/`、`examples/`、`prompts/`、`reference/` 和
`pre_reset_mainline/` 分类。

## 使用限制

- 归档内容不能作为当前功能说明。
- 归档中的“已完成”“生产可用”只代表当时结论，已被本次重置撤销。
- 如需复用某段代码或设计，必须按 `docs/VIDEO_PIPELINE_V2_BASELINE.md` 作为新候选重新验收。
