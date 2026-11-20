---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-20
model_usage: docs 文档保留、归档和可遗弃候选分析。用于判断历史文档是否还能作为参考，不能替代 CURRENT_CAPABILITIES.md。
---

> 文档状态：当前文档归类与遗弃分析。能力判断仍以 `CURRENT_CAPABILITIES.md`、`DEVELOPMENT_PROGRESS.md`、`ARCHITECTURE_STATUS.md` 为准。

# docs 文档保留与遗弃分析

更新时间：2026-05-20

## 当前判断

当前项目主线已经切到“动漫数字人主讲”，对应 `video_mode=presenter_anime`。因此，凡是仍把“单人口播模板视频”“2D 分层微动作”或“双角色 FramePack”描述为默认主线的文档，都不应再作为当前实施依据。

本次只做分类和遗弃建议，不删除文件。

## 分类规则

| 分类 | 含义 | 处理建议 |
|---|---|---|
| 当前主线 | 能直接代表当前项目状态、操作方法或工程边界 | 保留在 `docs/` 根目录，定期更新 |
| 当前参考 | 仍有实现细节、集成方式或排查价值，但不能覆盖主线文档 | 保留，必要时移动到 `docs/reference/` |
| 历史归档 | 记录已完成、已放弃或阶段性试错 | 保留在 `docs/archive/`，不要作为当前依据 |
| 可遗弃候选 | 内容已被新文档覆盖，或只记录过时草案/早期 TODO | 可在确认无外部引用后删除或压缩成摘要 |
| 暂不遗弃 | 虽过期但包含排错结论、素材边界或第三方工具集成细节 | 保留归档 |

## 当前主线文档

这些文档应继续作为入口，后续也应优先更新它们。

| 文档 | 判断 | 备注 |
|---|---|---|
| `README.md` | 保留 | 文档索引，需要指向本分析替代旧归类清单 |
| `PROJECT_INTRO.md` | 保留 | 项目介绍已更新到动漫数字人主线 |
| `CURRENT_CAPABILITIES.md` | 保留 | 当前能力权威入口 |
| `DEVELOPMENT_PROGRESS.md` | 保留 | 当前阶段状态入口 |
| `ARCHITECTURE_STATUS.md` | 保留 | 架构状态入口 |
| `USER_GUIDE.md` | 保留 | 当前使用方法入口 |
| `RELATED_PROJECTS_INTEGRATION.md` | 保留 | FramePack、ComfyUI、外部项目关系入口 |
| `SYSTEM_ARCHITECTURE.md` | 保留但需更新 | 仍有架构价值，但部分链路仍写单人口播生产主线，应后续修正 |
| `ACCOUNT_LOGIN_AND_USAGE_PLAN.md` | 保留 | 账号、权限、额度设计仍可用 |
| `CLOUDFLARED_PUBLIC_ACCESS.md` | 保留 | 运维访问说明 |
| `CODEX_SESSION_IMPORT_2026.md` | 保留 | 历史会话摘要；其中早期主线判断不能覆盖 2026-05-20 主线 |
| `DOCS_RETENTION_ANALYSIS_2026-05-20.md` | 保留 | 本文件 |

## 视频生成文档归类

| 文档 | 当前分类 | 是否可遗弃 | 原因 |
|---|---|---|---|
| `ANIME_DIGITAL_HUMAN_PLAN.md` | 当前参考 | 否 | 动漫数字人主讲路线的主要技术背景，仍包含 Edge-TTS、Sonic、ComfyUI 分段背景、质检重抽等关键判断 |
| `PRESENTRER_VIDEO_PLAN.md` | 当前参考 | 否 | 名字有拼写问题但内容仍是 Presenter 长期蓝图，可保留作为蓝图 |
| `PRESENTER_VIDEO_MODIFICATION_PLAN.md` | 历史到当前参考之间 | 暂不遗弃 | 记录 Presenter MVP 收口路线；部分“不绑定 ComfyUI/发布”的判断已被当前默认主线推进覆盖，但工程分阶段思路仍有价值 |
| `SONIC_INTEGRATION_PLAN.md` | 当前参考 | 否 | Sonic 角色层仍是 Presenter 路线关键依赖 |
| `VOICE_CLONING_EDGE_TO_GPT_SOVITS.md` | 当前参考 | 否 | 声线迁移仍相关 |
| `EDGE_TTS_INTEGRATION.md` | 当前参考 | 否 | Edge-TTS 是当前 Presenter 快速通路 |
| `GPT_SOVITS_QUICKSTART.md` | 当前参考 | 否 | GPT-SoVITS 可选声线方案 |
| `GPT_SOVITS_USAGE_AND_INTEGRATION.md` | 当前参考 | 否 | GPT-SoVITS 集成细节仍可能复用 |
| `FRAMEPACK_INTEGRATION_PLAN.md` | 当前参考 | 否 | FramePack 是双角色可选增强路线，仍有素材后处理价值 |
| `CHARACTER_MOTION_OPTIONS_2026-05-10.md` | 历史参考 | 暂不遗弃 | 早期人物动效选型，对理解为什么转向 FramePack/Sonic 有价值 |
| `IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md` | 历史参考 | 可遗弃候选 | 已不再是当前主线；若 `micro_motion.py` 后续不用，可压缩为一段历史摘要 |
| `DUAL_V12_EYE_POSITION_FIX_PLAN_2026-05-10.md` | 历史调试 | 可遗弃候选 | 针对早期 dual_v12 眼睛位置异常，当前主线不依赖；确认无需复现旧样片后可删除 |

## reference 目录归类

| 文档 | 当前分类 | 是否可遗弃 | 原因 |
|---|---|---|---|
| `reference/IMPLEMENTATION_OPTION_2_LAYERED_2D.md` | 历史参考 | 可遗弃候选 | 已被增强版和后续 Presenter/FramePack 路线覆盖 |
| `reference/IMPLEMENTATION_OPTION_3_PORTRAIT_DIALOGUE.md` | 历史参考 | 暂不遗弃 | 头像/半身对话可作为备用路线参考 |
| `reference/IMPLEMENTATION_OPTION_4_COMFYUI_ANIMATEDIFF.md` | 当前参考 | 否 | ComfyUI/AnimateDiff 背景和视频探索仍相关 |
| `reference/SADTALKER_VIDEO_PLAN.md` | 历史参考 | 暂不遗弃 | SadTalker 踩坑和环境信息仍可避免重复尝试 |
| `reference/DEPLOYABLE_SERVICE_ROADMAP.md` | 当前参考 | 否 | 服务化路线仍可参考，但不是当前阶段 |
| `reference/TTS_MIGRATION_PLAN.md` | 当前参考 | 否 | TTS 选型迁移仍相关 |
| `reference/RAG_CHROMADB_PLAN.md` | 当前参考 | 否 | RAG/ChromaDB 仍是内容生成基础 |
| `reference/RAG_DATA_SECURITY.md` | 当前参考 | 否 | 数据安全说明仍相关 |
| `reference/RAG_DATA_SECURITY_PLAN.md` | 当前参考 | 否 | 可与上一份合并，但暂不建议删除 |
| `reference/VECTOR_DB_COMPARISON.md` | 当前参考 | 否 | 向量库选型资料仍有价值 |
| `reference/ONE_COMMAND_PROMPT_AUTOMATION_DESIGN.md` | 历史参考 | 可遗弃候选 | 如果当前不再推进 prompt 一键自动化，可归档或删除 |
| `reference/PENDING_REVIEW_RECORD_ANALYSIS.md` | 平台参考 | 暂不遗弃 | 运营状态和待审核问题排查可复用 |

## platform 目录归类

| 文档 | 当前分类 | 是否可遗弃 | 原因 |
|---|---|---|---|
| `platform/AUTO_REPLY_DESIGN.md` | 当前参考 | 否 | 自动回复仍是平台功能 |
| `platform/DATA_PERSISTENCE_SPEC.md` | 当前参考 | 否 | 数据持久化仍相关 |
| `platform/DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md` | 排查参考 | 暂不遗弃 | 发布自动化故障记录仍可能复用 |
| `platform/抖音发布自动化需求文档.md` | 历史到当前参考之间 | 暂不遗弃 | 原始需求可保留，但不能覆盖当前实现 |
| `platform/抖音发布自动化设计文档.md` | 历史到当前参考之间 | 暂不遗弃 | 原始设计可保留，但需以当前代码为准 |

## archive 目录归类

这些文件已经在归档目录，原则上不再移动回主线。

| 文档 | 当前分类 | 是否可遗弃 | 原因 |
|---|---|---|---|
| `archive/old-plans/PROJECT_OVERVIEW_DETAILED.md` | 旧总览 | 可遗弃候选 | 2026-03-22 版本，已被 `PROJECT_INTRO.md`、`CURRENT_CAPABILITIES.md`、`SYSTEM_ARCHITECTURE.md` 覆盖 |
| `archive/old-plans/PROJECT_PENDING_TASKS.md` | 旧待办 | 可遗弃候选 | 大量任务状态已过期；保留价值低，当前进度以 `DEVELOPMENT_PROGRESS.md` 为准 |
| `archive/old-plans/COMFYUI_VIDEO_SYNTHESIS_PLAN.md` | 旧草案 | 可遗弃候选 | 基于早期 ComfyUI/Kling 节点草案，已被 Presenter + BackgroundResolver 路线覆盖 |
| `archive/video-debug/AUDIO_DEBUG_AND_VIDEO_MVP.md` | 早期 MVP 调试 | 可遗弃候选 | 单人口播/音频早期排查，现已被当前能力文档覆盖 |
| `archive/video-debug/COMPOSITE_ISSUES_2026-05-09.md` | 调试归档 | 暂不遗弃 | alpha、colorkey、合成踩坑可避免重复错误 |
| `archive/video-debug/DUAL_CHARACTER_VIDEO_ROOT_CAUSE_REPORT.md` | 调试归档 | 暂不遗弃 | 双角色根因分析仍有排错价值 |
| `archive/video-debug/DUAL_CHARACTER_VIDEO_STATUS.md` | 历史状态 | 可遗弃候选 | 状态已明显过期，若 `CODEX_SESSION_IMPORT_2026.md` 的摘要足够，可删除 |
| `archive/video-debug/MICRO_MOTION_ABNORMAL_ANALYSIS_2026-05-10.md` | 调试归档 | 暂不遗弃 | 微动作异常排查对旧路线仍有参考价值 |
| `archive/video-debug/VIDEO_ABNORMAL_ANALYSIS_2026-05-09.md` | 调试归档 | 暂不遗弃 | 视频异常第一轮分析仍有历史排错价值 |
| `archive/video-debug/VIDEO_ABNORMAL_ANALYSIS_ROUND2_2026-05-09.md` | 调试归档 | 暂不遗弃 | 第二轮分析解释了放弃某些合成策略的原因 |
| `archive/prompts/README.md` | prompt 归档说明 | 暂不遗弃 | 无害，便于追溯 prompt 备份 |

## 其他文档

| 文档 | 当前分类 | 是否可遗弃 | 原因 |
|---|---|---|---|
| `DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md` | 历史归档 | 可遗弃候选 | 已被本文件替代，且旧文档仍把 2D 微动作当主线 |
| `USER_PREFERENCES.md` | 当前参考 | 否 | 用户偏好小而关键 |
| `screenshots/README.md` | 参考说明 | 暂不遗弃 | 目录说明，无害 |
| `prompts/README.md` | 当前参考 | 否 | prompt 目录入口 |

## 建议优先遗弃候选

如果要减少文档噪音，建议按这个顺序处理。删除前先执行一次全文引用检查。

| 优先级 | 文档 | 建议动作 |
|---|---|---|
| 1 | `DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md` | 保留到 `archive/old-plans/` 或删除；本文件已替代它 |
| 2 | `archive/old-plans/PROJECT_PENDING_TASKS.md` | 删除或只保留 5 行摘要 |
| 3 | `archive/old-plans/PROJECT_OVERVIEW_DETAILED.md` | 删除或只保留历史摘要 |
| 4 | `archive/old-plans/COMFYUI_VIDEO_SYNTHESIS_PLAN.md` | 删除或只保留“早期 ComfyUI/Kling 草案”摘要 |
| 5 | `archive/video-debug/AUDIO_DEBUG_AND_VIDEO_MVP.md` | 若不再排查旧单人口播 MVP，可删除 |
| 6 | `archive/video-debug/DUAL_CHARACTER_VIDEO_STATUS.md` | 若 `CODEX_SESSION_IMPORT_2026.md` 已覆盖关键结论，可删除 |
| 7 | `DUAL_V12_EYE_POSITION_FIX_PLAN_2026-05-10.md` | 确认旧样片无需复现后可归档或删除 |
| 8 | `reference/IMPLEMENTATION_OPTION_2_LAYERED_2D.md` | 若保留增强版摘要，则基础版可删除 |
| 9 | `IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md` | 若微动作路线不再维护，可归档或删除 |
| 10 | `reference/ONE_COMMAND_PROMPT_AUTOMATION_DESIGN.md` | 若近期不做 prompt 自动化，可归档或删除 |

## 不建议遗弃的历史文档

这些文档虽然不是当前主线，但仍记录了重要失败原因、第三方工具边界或可复用集成细节。

| 文档 | 保留原因 |
|---|---|
| `ANIME_DIGITAL_HUMAN_PLAN.md` | 当前主线的技术细节最多 |
| `PRESENTRER_VIDEO_PLAN.md` | Presenter 蓝图，虽然文件名拼写错误但引用较多 |
| `SONIC_INTEGRATION_PLAN.md` | Sonic 角色层仍相关 |
| `FRAMEPACK_INTEGRATION_PLAN.md` | 双角色可选路线仍依赖它 |
| `reference/SADTALKER_VIDEO_PLAN.md` | 避免重复走 SadTalker 旧坑 |
| `archive/video-debug/COMPOSITE_ISSUES_2026-05-09.md` | 合成失败经验有排错价值 |
| `archive/video-debug/VIDEO_ABNORMAL_ANALYSIS_ROUND2_2026-05-09.md` | 解释旧合成路线为什么不继续 |
| `platform/DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md` | 发布自动化故障仍可能复现 |

## 建议后续动作

1. 先把 `SYSTEM_ARCHITECTURE.md` 更新到动漫数字人主线，避免主线文档内部冲突。
2. 把 `DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md` 标记为历史归档，README 改指向本文件。
3. 对“建议优先遗弃候选”做一次引用检查。
4. 如果确认不需要历史细节，再删除候选文档；否则只移动到 `docs/archive/old-plans/` 并保留 `archived_do_not_use_as_current`。
