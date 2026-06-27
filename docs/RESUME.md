---
doc_status: reference
doc_category: resume
last_reviewed: 2026-06-25
model_usage: 简历项目介绍参考。可复制到简历项目栏使用。
---

# 项目介绍（简历用）

> 这是一份**可以直接贴到简历项目栏**的项目介绍，包含标题、一句话定位、技术关键词、3 条项目描述（短/中/长）和亮点 bullet list。能力细节以 `CURRENT_CAPABILITIES.md` 为准。

---

## 项目标题（任选其一）

- **AI ShortVideo — 基于 LLM Agent 的本地化短视频内容生产与多平台运营自动化平台**
- **AI ShortVideo — 对话式 AI 短视频生成 + 视频平台自动化运营系统**
- **AI ShortVideo — 从脚本到发布的端到端 AI 短视频工厂**

---

## 一句话定位

> 用自然语言一句话驱动整个短视频生产 + 视频平台运营流程：LLM 生成脚本 → Edge-TTS/GPT-SoVITS 配音 → Sonic + ComfyUI 数字人视频合成 → 浏览器自动化发布 → 抓评论与自动回复 → 任务定时调度，全链路本地化运行。

---

## 技术关键词

`Python 3.11` · `Streamlit` · `LLM Agent / Tool Use` · `RAG (Chroma)` · `Ollama / OpenAI-compatible` · `Edge-TTS / GPT-SoVITS` · `ComfyUI / SDXL` · `MoviePy / FFmpeg` · `Selenium / Playwright` · `APScheduler` · `SQLite + SQLAlchemy` · `SQLite SKIP LOCKED` · `分层记忆 / 滑动窗口` · `多角色权限 / 审计日志`

---

## 项目描述（短版 · 2-3 行）

> **AI ShortVideo** 是本地运行的对话式 AI 短视频生产与多平台运营平台。我独立设计并实现了：(1) 可由 LLM 自动调度的 Skill Registry（18+ 个能力，含生成/发布/评论/养号/网络文学平台推广）；(2) "先生成计划、用户确认、再执行"的安全 Agent；(3) APScheduler + SQLite 任务队列的后台调度；(4) 动漫数字人主讲视频的端到端管线（Edge-TTS + Sonic + ComfyUI + FFmpeg）；(5) Selenium 驱动的视频平台浏览器自动化（发布/同步/评论/回复）。Streamlit 管理后台覆盖视频、评论、对话、调度等所有运营场景。

---

## 项目描述（中等 · 4-6 行）

> **AI ShortVideo** 是我从零搭建的端到端 AI 短视频内容平台，核心解决"个人/小团队如何用 AI 自动化多平台运营"的问题。
>
> 我独立负责整体架构与实现：
>
> - **对话式 Agent**（`src/agent/`）：把全平台能力以 Skill 形式注册到 LLM，LLM 通过 `​```plan ... ```​` 块输出执行计划，用户回复"确认"才执行；任何异常都被兜底并写入 ProblemMemory，由每日 cron 让 LLM 给调查方向。
> - **分层记忆**（`src/memory/`）：自动把用户消息分成 preference/problem/discarded/normal 四类；用户偏好自动入库、未解决问题自动跟踪、会话历史自动滚动到 20 条滑动窗口。
> - **任务调度**（`src/scheduler/`）：APScheduler 包装 + SQLite 任务队列 + 后台 Worker 线程用 `SELECT ... FOR UPDATE SKIP LOCKED` 抢任务，支持 `max_retries` 自动重试；Streamlit 内置"任务调度"页和"每日问题调查"预置任务。
> - **动漫数字人主讲视频**（`src/content_factory/presenter/`）：关键词/文章/提炼三种输入通道，Edge-TTS 分段配音，Sonic 角色视频层，ComfyUI/SDXL 按需启动生成动漫背景并自动关闭，本地兜底背景回退，字幕避让角色，FFmpeg 合成 9:16 1080×1920 MP4。
> - **视频平台浏览器自动化**（`src/platform_adapter/`）：Selenium 持久登录态、发布、同步视频、抓评论、规则/LLM 自动回复、多账号养号（精选页推荐/可控点赞/评论区浏览）；网络文学平台推广 MVP 复用同套浏览器会话。
> - **RAG + 内容工厂**：Chroma 向量库 + 本地 Ollama embedding + Edge-TTS / GPT-SoVITS 多音色 + BGM 混音。
> - **Streamlit 管理后台**：视频、评论、规则、违禁词、用户、对话、调度等多页面，含多角色权限与审计日志。

---

## 项目描述（详细 · 适合面试展开）

> **AI ShortVideo** 是我从零搭建、本地化运行的对话式 AI 短视频内容生成与多平台运营自动化平台，覆盖从脚本生成、视频合成到视频平台发布、评论回复、账号养号的完整闭环。
>
> ### 架构与亮点
>
> **1. LLM Agent + Tool-Use 调度**
>
> - 把全平台能力（内容生成 / 平台运营 / 网络文学平台推广 / 养号 / 知识库 / 系统工具）封装为 18+ 个 Skill 注册到统一 Registry；LLM 通过 prompt 自动选择并调用。
> - 设计了"先生成 `​```plan ... ```​` 计划块、用户回复确认/取消、再执行"的 Safety Guard，写操作 100% 需要用户确认。
> - 任何内部异常都被 `_handle_chat_failure` 接住，返回兜底文案并写入 ProblemMemory，绝不抛 traceback 到 UI。
>
> **2. 分层记忆与异常自愈**
>
> - 三层记忆（ConversationMemory 滑动窗口 + UserMemory 偏好 + ProblemMemory 问题跟踪），自动分类用户消息并去重。
> - 每日 cron 调用 `investigate_problems` 让 LLM 给未解决问题生成调查方向，长期未解决的问题自动续期。
>
> **3. 任务调度系统**
>
> - 自研轻量级队列：APScheduler 触发（cron / interval）→ 创建 `TaskExecution` → 后台 Worker 用 SQLite `SELECT ... FOR UPDATE SKIP LOCKED` 抢任务 → 调 SkillRegistry 执行 → 失败自动重试到 `max_retries` 上限。
> - 完整状态机：`pending → running → completed / failed / cancelled`，配 Streamlit "任务调度"页（仪表板 / 任务 / 队列 / 执行记录）支持热启用/停用、即时入队、错误查看。
>
> **4. 动漫数字人主讲视频（生产主线）**
>
> - 关键词 / 文章直接 / 文章提炼三种输入通道。
> - Edge-TTS 分段配音 → Sonic 角色视频层 → ComfyUI SDXL 按需启动生成动漫背景并自动关闭（本地兜底背景回退）→ 字幕避让 → FFmpeg 合成 9:16 1080×1920 MP4。
> - 整条管线已端到端跑通并落地完整样片。
>
> **5. 视频平台自动化（Selenium）**
>
> - 持久登录态、发布视频、同步创作者后台视频列表、抓评论、规则/LLM 自动回复（含限流 + 违禁词 + 历史）。
> - 多账号养号（`douyin_warmup`）：独立 browser profile、精选页推荐入口、按视频时长倍率随机停留、评论区打开和下滑、可控视频/评论点赞。
> - 网络文学平台推广 MVP：复用浏览器会话，登录态 / 申请推广 / 获取章节 / 生成推广视频全链路跑通。
>
> **6. RAG + 多 TTS Provider**
>
> - Chroma 向量库 + Ollama 本地 embedding；古典典籍导入自动 chunk + 元数据。
> - Edge-TTS（默认）和 GPT-SoVITS（可选声线克隆）双 Provider 切换。
>
> **7. Streamlit 管理后台**
>
> - 视频 / 评论 / 规则 / 违禁词 / 用户 / 对话 / 调度 / 设置多页面，多角色权限（超管 / 运营管理员 / 运营编辑 / 查看者）+ 审计日志。
>
> ### 关键结果
>
> - **生产可用**：动漫数字人主讲端到端管线已稳定输出完整样片（`data/videos/presenter_*_comfy_full.mp4`）。
> - **多 Skill 协作**：所有平台能力（生成 / 发布 / 评论 / 养号 / 网络文学平台）已注册到 Skill Registry，可由 LLM 一句话串起来。
> - **无人值守**：通过 Streamlit "任务调度"页配置 cron，长任务后台自动跑，失败自动重试，问题自动跟踪。
> - **本地化 / 数据安全**：所有 AI 模型和数据本地运行，知识库内容不外传；可配合 Windows BitLocker 整盘加密。

---

## 简历 bullet list（任选 5-8 条）

- 独立设计并实现本地化 LLM Agent + Skill Registry：18+ 个 Skill（生成 / 发布 / 评论 / 养号 / 网络文学平台推广 / 知识库 / 记忆管理）由 LLM 通过 prompt 自动调度，写操作 100% 走"先生成计划、用户确认、再执行"安全流程。
- 设计并落地分层记忆系统（preference/problem/discarded/normal 分类 + 滑动窗口 + ProblemMemory 自动去重 + 每日 LLM 自动跟进未解决问题），Agent 任何异常都被兜底，绝不抛到 UI。
- 实现 APScheduler + SQLite SKIP LOCKED 任务队列：cron/interval 触发 + 后台 Worker 抢任务 + max_retries 自动重试，配 Streamlit "任务调度"页支持热启用/停用、即时入队、错误查看。
- 主导动漫数字人主讲视频端到端管线：关键词 / 文章直接 / 文章提炼三种输入通道，Edge-TTS 分段配音 + Sonic 角色视频层 + ComfyUI SDXL 按需启动生成动漫背景并自动关闭 + 本地兜底背景回退 + 字幕避让 + FFmpeg 合成 9:16 MP4。
- 实现 Selenium 驱动的视频平台浏览器自动化：持久登录态、发布、同步创作者后台、抓评论、规则/LLM 自动回复（限流 + 违禁词 + 历史），覆盖多账号养号（精选页推荐入口 / 可控点赞 / 评论区浏览）。
- 搭建网络文学平台推广 MVP：复用浏览器会话支持登录态 / 申请推广 / 获取章节 / 生成 Presenter 推广视频。
- 基于 Chroma + Ollama embedding 构建本地 RAG 知识库，支持古典典籍导入 + 语义检索 + LLM 脚本生成。
- 设计 Streamlit 多页面管理后台（视频 / 评论 / 规则 / 违禁词 / 用户 / 对话 / 调度）+ 多角色权限（超管 / 运营管理员 / 运营编辑 / 查看者）+ 审计日志。

---

## 数据亮点（可按简历篇幅选择）

- 代码规模：~7000+ 行 Python（`src/` 下 6 大模块），36+ 张 SQLite 表覆盖内容/记忆/调度。
- 视频管线：动漫数字人主讲已稳定跑通完整样片；支持 9:16 1080×1920、30fps、多段背景无缝合成。
- 平台覆盖：视频平台（发布 / 同步 / 评论 / 回复 / 养号）+ 网络文学平台（推广申请 / 章节获取 / 推广视频）。
- Agent 能力：18+ Skill 全部注册，写操作 100% 用户确认；异常兜底 + ProblemMemory + 每日 cron 自动调查。

---

## 简历写作建议

- **简历项目栏控制在 8-12 行**，用"项目描述（中等版）"或"简历 bullet list"挑 5-6 条最有代表性的写。
- **突出"独立 + 全栈 + 端到端"**：强调你从架构设计到落地实现都是一个人搞定。
- **量化**：尽量带数字（18+ Skill、9:16 1080×1920、SQLite SKIP LOCKED、Edge-TTS + ComfyUI 多 Provider 等）。
- **避免堆砌**：选 2-3 个亮点深挖，不要把模块名全列上。
- **面试准备**：候选人最容易展开的点是"Agent Safety Guard（先计划再确认）"、"分 层记忆自动分类"、"APScheduler + SQLite 队列"、"ComfyUI 按需启动/关闭"这几个。