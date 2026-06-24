---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-15
model_usage: 文档索引。找当前能力先看 CURRENT_CAPABILITIES.md，找具体使用方法看 USER_GUIDE.md。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin 文档索引

> 整理日期：2026-06-15

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
6. [项目介绍（简历用）](RESUME.md)：可直接复制到简历项目栏的项目介绍与亮点 bullet。
7. [关联项目与视频生成集成说明](RELATED_PROJECTS_INTEGRATION.md)：FramePack、FramePack_oneclick、背景素材与当前项目的关系。
8. [账号登录与用量控制方案](ACCOUNT_LOGIN_AND_USAGE_PLAN.md)：邮箱验证码登录、角色权限和每用户额度设计。
9. [小说推广视频平台支线设计](NOVEL_PROMOTION_VIDEO_PLATFORM_DESIGN.md)：番茄推广平台、小说前 10 章提炼、推广视频生成和绑定规划。
10. [Cloudflared 公网访问](CLOUDFLARED_PUBLIC_ACCESS.md)：用 Cloudflare Quick Tunnel 临时开放管理后台公网访问。
11. [docs 文档保留与遗弃分析](DOCS_RETENTION_ANALYSIS_2026-05-20.md)：判断历史文档是否可遗弃。
12. [Codex 会话导入摘要](CODEX_SESSION_IMPORT_2026.md)：从 Codex 2026 原始记录整理出的历史决策和排查结论。

视频生成相关主线：

- [动漫数字人主讲视频优化方案](ANIME_DIGITAL_HUMAN_PLAN.md)
- [Presenter 输入通道改造设计](PRESENTER_INPUT_CHANNELS_DESIGN.md)
- [数字人主讲视频生成方案](PRESENTRER_VIDEO_PLAN.md)
- [Sonic 接入方案](SONIC_INTEGRATION_PLAN.md)
- [关联项目与视频生成集成说明](RELATED_PROJECTS_INTEGRATION.md)
- [Edge-TTS 到 GPT-SoVITS 本地声线方案](VOICE_CLONING_EDGE_TO_GPT_SOVITS.md)
- [FramePack 接入方案](FRAMEPACK_INTEGRATION_PLAN.md)

视频生成历史参考：

- [人物轻微动效方案总览](CHARACTER_MOTION_OPTIONS_2026-05-10.md)
- [方案二增强版：2D 分层 + 可复用微动作库](IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md)
- [dual_v12 眼睛位置异常修复方案](DUAL_V12_EYE_POSITION_FIX_PLAN_2026-05-10.md)

## 平台功能

- [账号登录与用量控制方案](ACCOUNT_LOGIN_AND_USAGE_PLAN.md)
- [小说推广视频平台支线设计](NOVEL_PROMOTION_VIDEO_PLATFORM_DESIGN.md)
- [Cloudflared 公网访问](CLOUDFLARED_PUBLIC_ACCESS.md)
- [自动回复设计](platform/AUTO_REPLY_DESIGN.md)
- [抖音账号养号/活跃维护计划](platform/DOUYIN_ACCOUNT_WARMUP_PLAN.md)
- [数据持久化规格](platform/DATA_PERSISTENCE_SPEC.md)
- [抖音发布 hashtag 超时问题](platform/DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md)
- [抖音发布自动化需求](platform/抖音发布自动化需求文档.md)
- [抖音发布自动化设计](platform/抖音发布自动化设计文档.md)

## 参考方案

- [方案二基础版：2D 分层动效](reference/IMPLEMENTATION_OPTION_2_LAYERED_2D.md)
- [方案三：头像/半身对话](reference/IMPLEMENTATION_OPTION_3_PORTRAIT_DIALOGUE.md)
- [方案四：ComfyUI / AnimateDiff](reference/IMPLEMENTATION_OPTION_4_COMFYUI_ANIMATEDIFF.md)
- [SadTalker 视频方案](reference/SADTALKER_VIDEO_PLAN.md)
- [可部署服务路线图](reference/DEPLOYABLE_SERVICE_ROADMAP.md)
- [RAG 数据安全](reference/RAG_DATA_SECURITY.md)
- [RAG 数据安全计划](reference/RAG_DATA_SECURITY_PLAN.md)
- [待审核记录分析](reference/PENDING_REVIEW_RECORD_ANALYSIS.md)
- [一键 Prompt 自动化设计](reference/ONE_COMMAND_PROMPT_AUTOMATION_DESIGN.md)
- [TTS 迁移方案](reference/TTS_MIGRATION_PLAN.md)
- [RAG ChromaDB 计划](reference/RAG_CHROMADB_PLAN.md)
- [向量库对比](reference/VECTOR_DB_COMPARISON.md)

## 暂缓/废弃设计

- [背景图图片质检与重抽设计](BACKGROUND_IMAGE_REVIEW_DESIGN.md)：`doc_status: deferred`，图片理解质检方案已暂缓，不进入当前生产链路。

## 历史归档

- `archive/video-debug/`：视频合成异常、SadTalker、alpha 合成等历史排查。
- `archive/old-plans/`：早期总览、旧待办、早期 ComfyUI 草案。
- `archive/prompts/`：prompt 备份。

## prompt

- `prompts/book-extraction.txt`
- `prompts/dialogue-generation.txt`
- `prompts/script-generation.txt`

## 文档整理记录

- [docs 文档保留与遗弃分析](DOCS_RETENTION_ANALYSIS_2026-05-20.md)
- [docs 旧文档归类清单，历史归档](DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md)
- [Codex 会话导入摘要](CODEX_SESSION_IMPORT_2026.md)