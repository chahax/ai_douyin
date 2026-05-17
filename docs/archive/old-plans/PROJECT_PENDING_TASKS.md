---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# 项目待办事项

更新时间：2026-04-27

---

## 低优先级

| 序号 | 任务 | 关联阶段/文档 | 说明 |
|------|------|----------------|------|
| L-1 | 自动回复管理 CLI 命令 | AUTO_REPLY_DESIGN.md | `main.py auto-reply` 下新增规则/违禁词/用户配置管理子命令（add-rule, list-rules, add-blocked-word, set-limit 等） |
| L-2 | Phase 5 端到端验证 | AUTO_REPLY_DESIGN.md | 对真实视频运行 `auto-reply --video-id` 验证完整流程 |
| L-3 | 自动回复违禁词 LLM 生成过滤 | AUTO_REPLY_DESIGN.md | `_generate_reply` 中 LLM 生成结果已做违禁词过滤，需确认 `comment_filter._has_blocked_word` 在生成侧调用路径正确 |

---

## 中优先级

| 序号 | 任务 | 关联阶段/文档 | 说明 |
|------|------|----------------|------|
| M-1 | Phase 4 Streamlit 管理界面 | ARCHITECTURE_STATUS.md | 视频/评论/规则/历史 四个 Tab，管理全链路数据 |
| M-2 | 定时调度能力 | ARCHITECTURE_STATUS.md | `scheduler/` 空目录，实现 cron 调度，支持自动抓评论+自动回复 |
| M-3 | Phase 5 端到端验证 | AUTO_REPLY_DESIGN.md | 对真实视频运行 `auto-reply --video-id` 验证完整流程 |

---

## 高优先级

| 序号 | 任务 | 关联阶段/文档 | 说明 |
|------|------|----------------|------|
| H-1 | Phase 5 API 服务层 | ARCHITECTURE_STATUS.md | FastAPI 入口，对外暴露评论/回复/规则管理 API |
| H-2 | Phase 6 异步任务执行 | ARCHITECTURE_STATUS.md | 队列 + Worker，支持后台批量处理视频列表 |

---

## 已完成（备忘）

- [x] Phase 0 基础加固
- [x] Phase 1 应用服务层抽取
- [x] Phase 2 Provider 抽象 + Ollama 接入
- [x] Phase 3.1 发布流程（publish_workflow）
- [x] Phase 3.2 同步流程（sync_workflow）
- [x] Phase 3.3 评论抓取（comment_workflow 浏览器自动化）
- [x] Phase 3.4 数据库服务层
- [x] 自动回复机器人核心逻辑（Phase 1~4）
- [x] auto-publish 一键发布命令
- [x] GPT-SoVITS TTS subprocess 封装
- [x] 评论抓取 `douyin-fetch-comments` 命令
- [x] 单条评论回复 `douyin-reply-comment` 命令
- [x] 自动回复机器人 `auto-reply` 命令
