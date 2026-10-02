---
doc_status: current
doc_category: mainline
last_reviewed: 2026-08-24
model_usage: 文档索引。找当前能力先看 CURRENT_CAPABILITIES.md，找具体使用方法看 USER_GUIDE.md。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。
> 整理日期：**2026-08-24**。当前能力以 `CURRENT_CAPABILITIES.md` 为准；专项报告只证明对应样片或工具链，不自动代表通用生产能力。

# AI Douyin 文档索引

整理日期：**2026-08-24**

> **2026-07-01 清理动作**：移走 4 篇过时文档到 `archive/2026-07-cleanup/`
> 给 4 篇缺 frontmatter 的补 `doc_status` 元数据
> 剩 34 篇主文档，多数 `last_reviewed: 2026-05-31` 之前，下次有空复审

## 当前主线

每份 Markdown 顶部都带有 `doc_status` 元数据，给人和模型判断用途：

- `current`：当前主线，可以作为当前状态或实施依据。
- `reference`：参考资料，只能辅助理解，不能覆盖当前主线。
- `deferred`：已暂缓或废弃的设计，不能作为当前实现方案。
- `archived_do_not_use_as_current`：历史归档，只用于追溯，不要作为当前实现方案。

建议阅读顺序：

1. [当前能力总览](CURRENT_CAPABILITIES.md)：现在已经能做什么，尤其是视频生成和 Agent/Scheduler。
2. [用户指南](USER_GUIDE.md)：常用命令和管理后台操作。
3. [开发进度](DEVELOPMENT_PROGRESS.md)：阶段状态与下一步。
4. [系统架构](SYSTEM_ARCHITECTURE.md)：模块关系和边界。
5. [架构状态](ARCHITECTURE_STATUS.md)：更细的状态说明。
6. [项目介绍](PROJECT_INTRO.md)：5 分钟能让人明白这个项目是什么。
7. [项目介绍（简历用）](RESUME.md)：可直接复制到简历项目栏的项目介绍与亮点 bullet。
8. [关联项目与视频生成集成说明](RELATED_PROJECTS_INTEGRATION.md)：FramePack、FramePack_oneclick、背景素材与当前项目的关系。

## LLM / Agent / Skill（这条主线最近改得最多）

- [Skill 规格](SKILL_SPEC.md)：所有 Skill 怎么定义 / 注册 / 调。
- [AI 助手改造方案 v0.2](LANGGRAPH_REFACTOR_PLAN.md)：P0 native tool calling 已实施；P1 streaming + P2 retry 待观察。
- [AI 助手改造日志](HARNESS_ITERATION_LOG.md)：迭代踩坑记录，含之前 LLM 一直返回空的根因 + P0 修复。
- [番茄批量抓取与推广工作流](FANQIE_PROMOTION_WORKFLOW.md)：番茄达人中心 + Skill 调用流程。

## 番茄运营平台支线

- [番茄推书任务闭环推进计划](FANQIE_PROMOTION_CLOSED_LOOP_PLAN.md)：从选书、数据库状态、可审计视频生产到抖音发布和番茄回填的实施与验收基线。
- [账号登录与用量控制方案](ACCOUNT_LOGIN_AND_USAGE_PLAN.md)：邮箱验证码登录、角色权限和每用户额度设计。
- [小说推广视频平台支线设计](NOVEL_PROMOTION_VIDEO_PLATFORM_DESIGN.md)：番茄推广平台、小说前 10 章提炼、推广视频生成和绑定规划。
- [Cloudflared 公网访问](CLOUDFLARED_PUBLIC_ACCESS.md)：用 Cloudflare Quick Tunnel 临时开放管理后台公网访问。

## 视频生成主线

- [Wan2.2 Animate Move 本机环境与社区工作流](COMFYUI_WAN22_ANIMATE_MOVE_SETUP.md)：已安装/未启动的状态边界、16GB 固定配置和社区方案筛选。
- [ComfyUI 多工作流、多画风统一测试](COMFYUI_MULTI_STYLE_WORKFLOW_TEST_PLAN.md)：四种画风、候选工作流、三轮隔离变量测试和统一审计产物。
- [ComfyUI 视频工作流类型目录](COMFYUI_WORKFLOW_TYPE_CATALOG.md)：文生/图生/首尾帧、动作与相机、人物替换、音频驱动、编辑、超分和长视频的本机就绪度与分组测试协议。
- [故事视频流水线](STORY_VIDEO_PIPELINE.md)
- [三联画合成器](TRIPLE_PANEL_COMPOSER.md)
- [视频控制模式](VIDEO_CONTROL_MODES.md) / [控制计划](VIDEO_CONTROL_PLAN.md) / [控制操作](VIDEO_CONTROL_OPERATIONS.md)
- [视频质量架构建议](VIDEO_QUALITY_ARCHITECTURE_RECOMMENDATIONS_2026-07-21.md)
- [视频审核包](VIDEO_REVIEW_PACKET.md) / [候选对比](VIDEO_CANDIDATE_BENCHMARK.md)
- [视频恢复](VIDEO_RECOVERY.md) / [平滑度](VIDEO_SMOOTHNESS.md) / [时序修复](VIDEO_TEMPORAL_REPAIR.md)
- [风格门禁](VIDEO_STYLE_GATE.md) / [灯光门禁](VIDEO_LIGHTING_GATE.md) / [关键帧重打光](KEYFRAME_RELIGHT.md)
- [视频 Recipe](VIDEO_RECIPE_MANIFEST.md) / [Agent Pack](VIDEO_AGENT_PACK.md) / [音频混流](VIDEO_AUDIO_MUX.md)
- [SadTalker 本地模式](SADTALKER_LOCAL_MODE.md) / [LivePortrait 本地模式](LIVEPORTRAIT_LOCAL_MODE.md)

- [动漫数字人主讲视频优化方案](ANIME_DIGITAL_HUMAN_PLAN.md)
- [Presenter 输入通道改造设计](PRESENTER_INPUT_CHANNELS_DESIGN.md)
- [数字人主讲视频生成方案](PRESENTRER_VIDEO_PLAN.md)
- [Sonic 接入方案](SONIC_INTEGRATION_PLAN.md)
- [关联项目与视频生成集成说明](RELATED_PROJECTS_INTEGRATION.md)
- [Edge-TTS 到 GPT-SoVITS 本地声线方案](VOICE_CLONING_EDGE_TO_GPT_SOVITS.md)
- [FramePack 接入方案](FRAMEPACK_INTEGRATION_PLAN.md)
- [GPT-SoVITS Quickstart](GPT_SOVITS_QUICKSTART.md)
- [GPT-SoVITS 使用与集成](GPT_SOVITS_USAGE_AND_INTEGRATION.md)

## 视频生成历史参考（看历史用的，不进当前生产）

- [dual_v12 眼睛位置异常修复方案](DUAL_V12_EYE_POSITION_FIX_PLAN_2026-05-10.md)
- [人物轻微动效方案总览](CHARACTER_MOTION_OPTIONS_2026-05-10.md)
- [Presenter 视频修改方案](PRESENTER_VIDEO_MODIFICATION_PLAN.md)

> ⚠️ 上面前 3 篇 `last_reviewed: 2026-05-31` 之前的，复审状态后再用

## 平台功能 docs/

- [auto-reply 设计](platform/AUTO_REPLY_DESIGN.md)
- [抖音账号养号/活跃维护计划](platform/DOUYIN_ACCOUNT_WARMUP_PLAN.md)
- [数据持久化规格](platform/DATA_PERSISTENCE_SPEC.md)
- [抖音发布 hashtag 超时问题](platform/DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md)
- [抖音发布自动化需求](platform/抖音发布自动化需求文档.md)
- [抖音发布自动化设计](platform/抖音发布自动化设计文档.md)

## 热点情报与原创脚本（规划）

- [抖音网页采集路线与 Go/No-Go](TREND_INTELLIGENCE_DOUYIN_READINESS.md)：分析网页抓取的技术可行性、最新协议边界、书面授权门和法律关键词取样范围。
- [网页采集版热点情报架构](TREND_INTELLIGENCE_ARCHITECTURE.md)：人工导入默认、授权 Web Provider 可选的 Source Policy、Playwright、数据模型、趋势分析和 Presenter 集成。
- [网页采集版执行计划](TREND_INTELLIGENCE_IMPLEMENTATION_PLAN.md)：先完成 Python 离线 MVP，取得书面授权后再实施 P6/P7 网页采集和定时快照。

## 路线图 / 工程改进

- [改进路线图 v2](IMPROVEMENT_ROADMAP.md)：未来 3 周工程改进、清理、V4 质量提升。

## 设计 / 实现参考 docs/

- docs/design/logger-convergence.md —— 日志统一收敛设计
- docs/design/llm-governance.md —— LLM 调用治理
- docs/design/comfy-resilience.md —— ComfyUI 弹性设计
- docs/design/v5-pure-video-pipeline.md —— V5 纯视频流水线

## 参考方案 docs/

- [方案二基础版：2D 分层动效](reference/IMPLEMENTATION_OPTION_2_LAYERED_2D.md)
- [方案三：头像/半身对话](reference/IMPLEMENTATION_OPTION_3_PORTRAIT_DIALOGUE.md)
- [方案四：ComfyUI / AnimateDiff](reference/IMPLEMENTATION_OPTION_4_COMFYUI_ANIMATEDIFF.md)
- [SadTalker 视频方案](reference/SADTALKER_VIDEO_PLAN.md)
- [可部署服务路线图](reference/DEPLOYABLE_SERVICE_ROADMAP.md)
- [RAG 数据安全](reference/RAG_DATA_SECURITY.md) + [RAG 数据安全计划](reference/RAG_DATA_SECURITY_PLAN.md)
- [待审核记录分析](reference/PENDING_REVIEW_RECORD_ANALYSIS.md)
- [一键 Prompt 自动化设计](reference/ONE_COMMAND_PROMPT_AUTOMATION_DESIGN.md)
- [TTS 迁移方案](reference/TTS_MIGRATION_PLAN.md)
- [RAG ChromaDB 计划](reference/RAG_CHROMADB_PLAN.md)
- [向量库对比](reference/VECTOR_DB_COMPARISON.md)

## 历史归档

- `archive/2026-07-cleanup/`：本次清理移走的 4 篇过时文档（含清理记录 `ARCHIVE_LOG_2026-07.md`）
- `archive/2026-08-video-workflow/`：D2 启动失败报告、LTX 调试日志和医院走廊专项快照（含 `ARCHIVE_LOG_2026-08-24.md`）
- `archive/old-plans/`：早期项目总览、ComfyUI 草案
- `archive/prompts/`：prompt 备份
- `archive/video-debug/`：视频合成异常、SadTalker、alpha 合成等历史排查

## prompt 模板 docs/

- `prompts/book-extraction.txt`
- `prompts/dialogue-generation.txt`
- `prompts/script-generation.txt`

## 文档保留策略 docs/

- [docs 文档保留与遗弃分析 v2](DOCS_RETENTION_ANALYSIS_2026-05-20.md)：文档归档原则
- [2026-07-01 清理记录](archive/2026-07-cleanup/ARCHIVE_LOG_2026-07.md)
- [微调 Harness 迭代日志](HARNESS_ITERATION_LOG.md)
