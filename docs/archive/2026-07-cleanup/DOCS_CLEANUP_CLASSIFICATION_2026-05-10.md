---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-20
model_usage: 2026-05-10 的旧文档归类记录，已被 DOCS_RETENTION_ANALYSIS_2026-05-20.md 替代；不要作为当前主线依据。
---

> 文档状态：历史归档。本文仍把“2D 分层 + 微动作库”作为当时主线，已不符合 2026-05-20 的“动漫数字人主讲”当前主线。当前归类以 [docs 文档保留与遗弃分析](DOCS_RETENTION_ANALYSIS_2026-05-20.md) 为准。

# docs 文档归类清单

> 日期：2026-05-10
> 目的：梳理当前 `docs/` 下哪些文档仍是主线，哪些只作为历史记录，哪些可以后续归档或删除候选。

> 执行状态：已按本文档完成目录整理。实际浏览入口见 [README.md](README.md)。

> 标注状态：已给 Markdown 文档补充 `doc_status` 元数据，避免模型或后续检索把归档文档误认为当前方案。

## 归类原则

### 当前主线

仍然直接指导当前开发、运行、排查或产品决策。

### 参考保留

内容仍有价值，但不是当前开发的直接入口。

### 历史归档

记录曾经的问题、分析和试错过程。建议保留，但可以移动到 `docs/archive/`。

### 可删除候选

内容已经被更新文档覆盖，或明显是早期草案。删除前建议确认没有外部引用。

## 当前主线文档

这些建议留在 `docs/` 根目录。

| 文档 | 归类理由 |
|---|---|
| `PROJECT_INTRO.md` | 项目介绍入口。 |
| `SYSTEM_ARCHITECTURE.md` | 系统架构总览，仍有参考价值。 |
| `ARCHITECTURE_STATUS.md` | 当前架构状态，但需要后续更新日期和阶段状态。 |
| `DEVELOPMENT_PROGRESS.md` | 进度总览，但部分双角色视频状态已经落后，需要更新。 |
| `USER_GUIDE.md` | 使用说明，面向实际操作。 |
| `USER_PREFERENCES.md` | 用户偏好，体量小，保留。 |
| `DATA_PERSISTENCE_SPEC.md` | 数据持久化规格，和平台功能相关。 |
| `AUTO_REPLY_DESIGN.md` | 自动回复设计，平台功能主线之一。 |
| `EDGE_TTS_INTEGRATION.md` | 双角色语音和 TTS provider 仍相关。 |
| `GPT_SOVITS_QUICKSTART.md` | GPT-SoVITS 快速使用说明。 |
| `GPT_SOVITS_USAGE_AND_INTEGRATION.md` | GPT-SoVITS 集成细节。 |
| `CHARACTER_MOTION_OPTIONS_2026-05-10.md` | 人物动效方案总览。 |
| `IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md` | 当前推荐路线：2D 分层 + 微动作库。 |
| `IMPLEMENTATION_OPTION_2_LAYERED_2D.md` | 方案二基础版，建议保留但以后可被增强版替代。 |

## 当前可参考但非主线

这些可以留在根目录，也可以移动到 `docs/reference/`。

| 文档 | 归类理由 |
|---|---|
| `IMPLEMENTATION_OPTION_3_PORTRAIT_DIALOGUE.md` | 头像/半身对话备用路线。理论成立，但不是当前选择。 |
| `IMPLEMENTATION_OPTION_4_COMFYUI_ANIMATEDIFF.md` | ComfyUI/AnimateDiff 实验路线。适合后续探索。 |
| `SADTALKER_VIDEO_PLAN.md` | SadTalker 已部署和早期口型方案记录。当前不作为全身主线，但环境信息有价值。 |
| `TTS_MIGRATION_PLAN.md` | TTS 选型参考。 |
| `RAG_CHROMADB_PLAN.md` | RAG/ChromaDB 计划参考。 |
| `RAG_DATA_SECURITY.md` | RAG 数据安全说明。 |
| `RAG_DATA_SECURITY_PLAN.md` | RAG 数据安全计划，较详细。 |
| `VECTOR_DB_COMPARISON.md` | 向量库选型参考。 |
| `DEPLOYABLE_SERVICE_ROADMAP.md` | 部署路线参考。 |
| `ONE_COMMAND_PROMPT_AUTOMATION_DESIGN.md` | 一键 prompt 自动化早期设计，仍可参考。 |
| `PENDING_REVIEW_RECORD_ANALYSIS.md` | 待审核记录分析，平台运营参考。 |
| `DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md` | 抖音发布 hashtag 超时问题记录，排查时有价值。 |
| `抖音发布自动化需求文档.md` | 发布自动化需求源文档。 |
| `抖音发布自动化设计文档.md` | 发布自动化设计源文档。 |

## 建议历史归档

这些文档记录了重要试错过程，但已经不应作为当前实现依据。建议移动到：

```text
docs/archive/video-debug/
```

| 文档 | 归档理由 |
|---|---|
| `COMPOSITE_ISSUES_2026-05-09.md` | 记录 GrabCut、colorkey、alpha 合成问题，已被后续分析覆盖。 |
| `DUAL_CHARACTER_VIDEO_ROOT_CAUSE_REPORT.md` | 记录 2026-05-01 双角色问题根因，历史价值高，但当前方案已转向。 |
| `DUAL_CHARACTER_VIDEO_STATUS.md` | 早期双角色状态，内容已落后于 v8/v9/v10 后续判断。 |
| `VIDEO_ABNORMAL_ANALYSIS_2026-05-09.md` | 第一轮异常分析，建议归档保留。 |
| `VIDEO_ABNORMAL_ANALYSIS_ROUND2_2026-05-09.md` | 第二轮异常分析，解释了为什么不能继续 composite_layer，建议归档保留。 |
| `AUDIO_DEBUG_AND_VIDEO_MVP.md` | 早期音频和循环画面 MVP 方案，当前已过阶段。 |

## 可删除候选

这些不建议立刻删，先确认没有引用。确认后可删除或移动到 `docs/archive/old-plans/`。

| 文档 | 原因 |
|---|---|
| `COMFYUI_VIDEO_SYNTHESIS_PLAN.md` | 早期 ComfyUI 总体草案，已被 `IMPLEMENTATION_OPTION_4_COMFYUI_ANIMATEDIFF.md` 更具体地覆盖。 |
| `PROJECT_OVERVIEW_DETAILED.md` | 早期项目总览，可能已被 `PROJECT_INTRO.md` + `SYSTEM_ARCHITECTURE.md` 覆盖。 |
| `PROJECT_PENDING_TASKS.md` | 早期待办，可能已与当前状态不一致。删除前应和 `DEVELOPMENT_PROGRESS.md` 对照。 |

## prompt 文档

保留在原路径：

```text
docs/prompts/
```

| 文档 | 建议 |
|---|---|
| `book-extraction.txt` | 保留。 |
| `dialogue-generation.txt` | 保留，双角色脚本仍可能用。 |
| `script-generation.txt` | 保留。 |
| `script-generation.backup.20260327.txt` | 可归档到 `docs/archive/prompts/`，不建议直接删。 |

## screenshots 文档

| 文档 | 建议 |
|---|---|
| `docs/screenshots/README.md` | 保留或补充截图目录规范。当前很短，但无害。 |

## 建议目录结构

可以后续整理为：

```text
docs/
  PROJECT_INTRO.md
  SYSTEM_ARCHITECTURE.md
  ARCHITECTURE_STATUS.md
  DEVELOPMENT_PROGRESS.md
  USER_GUIDE.md
  CHARACTER_MOTION_OPTIONS_2026-05-10.md
  IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md

  reference/
    IMPLEMENTATION_OPTION_2_LAYERED_2D.md
    IMPLEMENTATION_OPTION_3_PORTRAIT_DIALOGUE.md
    IMPLEMENTATION_OPTION_4_COMFYUI_ANIMATEDIFF.md
    SADTALKER_VIDEO_PLAN.md
    TTS_MIGRATION_PLAN.md
    RAG_CHROMADB_PLAN.md
    VECTOR_DB_COMPARISON.md

  platform/
    AUTO_REPLY_DESIGN.md
    DATA_PERSISTENCE_SPEC.md
    DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md
    抖音发布自动化需求文档.md
    抖音发布自动化设计文档.md

  archive/
    video-debug/
      COMPOSITE_ISSUES_2026-05-09.md
      DUAL_CHARACTER_VIDEO_ROOT_CAUSE_REPORT.md
      DUAL_CHARACTER_VIDEO_STATUS.md
      VIDEO_ABNORMAL_ANALYSIS_2026-05-09.md
      VIDEO_ABNORMAL_ANALYSIS_ROUND2_2026-05-09.md
      AUDIO_DEBUG_AND_VIDEO_MVP.md
    old-plans/
      COMFYUI_VIDEO_SYNTHESIS_PLAN.md
      PROJECT_PENDING_TASKS.md
      PROJECT_OVERVIEW_DETAILED.md
    prompts/
      script-generation.backup.20260327.txt
```

## 不建议现在直接删除的原因

当前项目还在快速试错阶段，历史文档虽然不适合作为主线，但有两个价值：

1. 避免重复走错路，比如 SadTalker 头像贴全身、全身 alpha 裁头像、整层漂浮。
2. 解释为什么当前选择“2D 分层 + 微动作库”。

所以建议先移动归档，不要直接删。

## 立即行动建议

第一步只做文档归档，不删除：

```text
docs/archive/video-debug/
docs/archive/old-plans/
docs/archive/prompts/
```

第二步更新两个状态文档：

```text
ARCHITECTURE_STATUS.md
DEVELOPMENT_PROGRESS.md
```

把当前视频主线改为：

```text
当前视频主线：静态全身角色 + 2D 分层微动作库
已放弃路线：SadTalker 头像贴全身、整层漂浮微动
实验备用：头像对话、ComfyUI/AnimateDiff
```

第三步再决定是否删除可删除候选。
