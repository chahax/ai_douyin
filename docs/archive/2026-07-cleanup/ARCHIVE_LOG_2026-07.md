---
doc_status: archive
doc_category: archive
last_reviewed: 2026-07-01
model_usage: 2026-07-01 文档清理记录。从根 docs/ 移到 archive/2026-07-cleanup/。
---

# 2026-07-01 文档清理记录

整理日期：**2026-07-01**

整理人：Claude Code（结合 LANGGRAPH_REFACTOR_PLAN 评审与 AI 助手 P0 实现期间发现的文档过时期问题）

## 整理原则

1. **按 frontmatter 的 `doc_status` 字段判定**（已有元数据的文档是真相的来源）
2. `archived_*` / `deferred` 状态的文档 → 移到 `archive/2026-07-cleanup/`
3. 在 `docs/README.md` 索引中加 `last_reviewed: 2026-07-01` 标签，便于以后 grep "过时的"
4. 不删除任何文档——归档可追溯

## 本次移走的 4 篇文档

| 文档 | 原状态 | 移走后位置 |
|---|---|---|
| `BACKGROUND_IMAGE_REVIEW_DESIGN.md` | `deferred`（图片理解质检已暂缓） | `archive/2026-07-cleanup/` |
| `CODEX_SESSION_IMPORT_2026.md` | `archived_do_not_use_as_current`（Codex 历史决策追溯） | `archive/2026-07-cleanup/` |
| `DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md` | `archived_do_not_use_as_current`（已被 `DOCS_RETENTION_ANALYSIS_2026-05-20.md` 替代） | `archive/2026-07-cleanup/` |
| `IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md` | `archived_design`（"2D 分层 + 微动作库"，已被动漫数字人主讲方案替代） | `archive/2026-07-cleanup/` |

## docs/ 根目录现在还有 34 篇

按修改时间分布：
- 2026-07-01：1 篇（`LANGGRAPH_REFACTOR_PLAN.md`）
- 2026-06-23 ~ 2026-06-29：11 篇（核心 doc + 状态报告 + 路线图）
- 2026-06-15：8 篇（历史 current 标记，但 last_reviewed 是 6-15 那天，需要复审）
- 2026-05-31：14 篇（实施 plan 五月批次）

## 5-31 那批次 (14 篇) 后续动作建议

14 篇都标 `doc_status: current`（或没标），但 `last_reviewed: 2026-05-31`，距今 ≥ 1 个月。**建议下次有空**：

1. 逐篇复读，确认是否真的还是 current
2. 把已变成"过去实现"的 plan 移到 `archive/2026-07-cleanup/` 或 `archive/old-plans/`
3. 顶部 `last_reviewed` 字段更新到复审日期

不过这是几天后的事，**不阻塞当前主线**。

## archive/ 子目录现在结构

```
docs/archive/
├── 2026-07-cleanup/                  ← 本次清理的 4 篇
│   ├── ARCHIVE_LOG_2026-07.md       (本文件)
│   ├── BACKGROUND_IMAGE_REVIEW_DESIGN.md
│   ├── CODEX_SESSION_IMPORT_2026.md
│   ├── DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md
│   └── IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md
├── old-plans/                         ← 历史项目总览/草案
├── prompts/                           ← prompt 备份
└── video-debug/                       ← 视频合成历史排查
```

## 与 docs/README.md 的关系

`docs/README.md` 已：
1. 删除 4 篇归档文档的链接
2. 把 5-31 那批文档标 `last_reviewed: 2026-07-01` 加注释 "review needed"
3. 加 `## 清理记录` 一节，指向本文件
