# AI 剧本与视频制作平台

本项目以创作简报、完整剧本、导演分镜、视频请求预览、逐段生成与用户审核为主线；
账号研究提供创作输入，浏览器发布和运营复盘属于下游能力。文本与视频都可以按阶段
暂停、查看、比较和恢复，模型或接口成功不等于内容通过。

> 2026-09-04 视频生产线重置：原 `presenter_anime`、
> `dual_framepack_active`、`single_template` 的视觉质量未达到生产要求，已经退出
> 管理页、工作流默认配置和自动发布入口。仓库中的旧合成代码与样片只用于历史追溯，
> 不代表当前可用的视频生产能力。

当前文档入口：

- [创作平台当前实现、v22 边界与验收](docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md)

- [创作阶段调试、版本与人工审核](docs/CREATIVE_STAGE_DEBUGGING.md)
- [可复用视频流程：创作简报、历史资产与逐段实审](docs/REUSABLE_VIDEO_WORKFLOW.md)

- [当前能力](docs/CURRENT_CAPABILITIES.md)
- [结构化提示词与 ComfyUI 导演台（本地候选编排）](docs/DIRECTOR_WORKBENCH.md)
- [导演稿分阶段生成与连续三稿文本验收](docs/DIRECTOR_PIPELINE_TESTING.md)
- [视频流程 V2 空白基线](docs/VIDEO_PIPELINE_V2_BASELINE.md)
- [系统架构](docs/SYSTEM_ARCHITECTURE.md)
- [操作指南](docs/USER_GUIDE.md)
- [视频旧方案归档](docs/archive/2026-09-video-pipeline-reset/ARCHIVE_MANIFEST.md)

## 当前边界

- 可以继续运行账号绑定、登录健康检查、相关内容调研和运营复盘。
- 可以在同一任务预算中自动推进文本、断点、单步、停止后续派发，并查看不可变版本及绑定反馈。
- 已记录实际消费字段与完整请求兼容证明；未改变的下游请求可复用，变化或未知调用保留原回执并停止。
- 请求预览、逐段候选、秒点责任反馈、批准链合成、成片交付、浏览器核验及运营回接共用版本链。
- 质量样本、人工金标、冻结留出及费用证据已接通；真实质量和收益仍须相应样本验证。
- 可以生成视频候选；保存成功后统一进入 `awaiting_human_review`，内容由用户审核。
- 用户明确批准某段后，才可用该段服务返回的原始尾帧继续紧邻下一段。
- 可以通过浏览器发布用户已批准的本地 MP4；提交后仍须完成作品和声明核验。
- 不提供“从关键词自动生成并发布视频”的生产能力。
- 新视频流程在目标样片、接口和质量门禁完成评审前不设置默认实现。
