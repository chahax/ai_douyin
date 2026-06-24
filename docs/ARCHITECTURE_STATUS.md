---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-15
model_usage: 当前架构状态说明。用于区分已落地能力、半自动能力和后续规划。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin 架构状态总览

更新时间：2026-06-15

## 当前做到哪一步

项目当前已经形成一个本地运行的短视频内容运营 + AI 自动化平台，核心由四块组成：

- **对话式 Agent**：`src/agent/`，把全部 Skill 注册为可由 LLM 调用的工具，含"先出计划、用户确认、再执行"的安全拦截。
- **分层记忆**：`src/memory/`，自动分类用户消息、抽取偏好、跟踪问题，crash-safe 异常兜底。
- **任务调度**：`src/scheduler/`，APScheduler 触发 + SQLite 任务队列 + 后台 Worker，预置每日问题调查 cron。
- **内容工厂 + 平台运营**：动漫数字人主讲、单人口播兜底、FramePack 增强、抖音发布/同步/评论/回复、养号、番茄推广。

一句话判断：动漫数字人主讲是当前生产主线；所有能力都已挂在 Agent / Skill Registry 这层；长任务用 Scheduler + Worker 后台跑；问题会自动跟踪并由每日 LLM 摘要跟进。

## 组件状态

| 组件 | 状态 | 说明 |
|---|---|---|
| CLI `main.py` | 可用 | 薄入口，调用服务层 |
| `GenerationService` | 可用 | 脚本、TTS、BGM、对话生成编排 |
| `AutoPublishService` | 可用 | 关键词生成内容、合成模板视频、上传抖音、落库 |
| `video_composer.py` | 可用 | 单视频、双角色视频、双角色 PNG 序列合成 |
| `presenter_pipeline.py` | 当前主线 | 动漫数字人主讲编排，ComfyUI 按需启动并在生成后尝试关闭，后续待 provider 化 |
| `micro_motion.py` | 局部可用 | 角色眨眼/呼吸 PNG 序列 |
| `framepack_pipeline.py` | 半自动可用 | 接管 FramePack 输出后的抽帧/抠图/循环 |
| 抖音适配器 | 可用 | 浏览器自动化发布、同步、评论、回复 |
| 抖音账号养号 | 测试版完成 | 多账号 profile、随机观看、评论区浏览、可控点赞 |
| 番茄推广适配器 | MVP 测试版 | 登录态、推广申请、章节获取、推广视频生成；页面自动化仍需实测修正 |
| `Agent` + `SkillRegistry` | 可用 | 18+ Skill 自动注册；写操作需要用户确认；失败兜底写 ProblemMemory |
| 分层记忆 `MemoryLayerManager` | 可用 | preference/problem/discarded/normal 自动分类，问题去重 |
| `TaskQueue` Worker | 可用 | SQLite SKIP LOCKED 抢任务，支持 max_retries 重试 |
| `CronScheduler` | 可用 | APScheduler cron + interval，启动时从 DB 同步任务 |
| Streamlit 后台 | 可用 | 视频、评论、规则、用户、设置、对话、调度 |
| FastAPI | 未开始 | 暂无 HTTP API |
| 跨进程 Worker | 未开始 | 当前 SQLite 锁仅适合单进程 Worker |
| Docker / Compose 部署 | 未开始 | 暂无部署契约 |

## 视频生成状态

| 路线 | 状态 | 是否接入一键发布 |
|---|---|---|
| 动漫数字人主讲 | 当前主线 | 是，默认 `presenter_anime` |
| 单人口播模板视频 | 历史/兜底 | 管理后台可选旧格式 |
| 发布已有 mp4 | 已完成 | 不需要生成 |
| 双角色对话脚本 + 双声线 TTS | 局部完成 | 否 |
| 双角色 FFmpeg 叠加 | 局部完成 | 否 |
| 本地微动作 PNG 序列 | 局部完成 | 否 |
| FramePack 动作帧 | 半自动可用 | 否 |
当前默认生产路径是动漫数字人主讲。

## 当前 CLI 能力

- `generate`
- `quick`
- `import-knowledge`
- `douyin-login`
- `douyin-upload-page`
- `douyin-publish`
- `douyin-sync`
- `douyin-fetch-comments`
- `douyin-reply-comment`
- `auto-reply`
- `auto-publish`
- `presenter`
- `presenter-assets`
- `debug-background-plan`
- `douyin-warmup-login`
- `douyin-warmup`
- `douyin-warmup-report`
- `douyin-warmup-account`
- `fanqie-login`
- `fanqie-promo-apply`
- `fanqie-book-fetch`
- `fanqie-promo-video`

## 主要边界

- `auto-publish` 当前默认使用 `presenter_anime`。
- `presenter` 可直接生成数字人主讲视频；ComfyUI 不可用时会回退到本地兜底背景。
- FramePack 生成人物动作 MP4 仍建议手动完成。
- 双角色 SadTalker 曾受角色素材影响，稳定性不如 PNG 序列和 FramePack 路线。
- 发布后 `post_id` 可能依赖后续 `douyin-sync` 补齐，数据库以 `local_id` 作为本地追踪依据。
- 抖音创作者后台属于页面/内部接口自动化，页面变化会影响稳定性。
- 番茄推广当前属于 MVP 页面自动化，依赖达人中心和小说站页面 DOM；遇到验证码/短信/安全验证时需要人工处理。
- 番茄推广当前尚未实现抖音视频 ID 回填/绑定推广任务。
- Agent 失败兜底会把异常写进 ProblemMemory；每日 cron 调用 `investigate_problems` 让 LLM 给调查摘要。
- Scheduler 后台 Worker 仅适合单进程；跨进程需要切换到 PostgreSQL/MySQL 或独立队列。

## 推荐路线

1. 把动漫数字人主讲作为当前生产主线，把 ComfyUI 背景封装成 provider 并保留按需启动/生成后关闭的行为。
2. 把 FramePack/微动作合成封装成服务层，增加输入资源检查。
3. 给 `auto-publish` 增加模式参数，例如 `single`、`dual`、`framepack`、`presenter`。
4. 给 Agent 增加更多 Skill 覆盖（如运营报表、批量评论回复、批量养号），同时把写操作的 Skill 全部走"先确认再执行"。
5. 把 Agent 拆成独立服务（FastAPI 或 WebSocket），调度和对话解耦。
6. 部署契约：先做 Docker + Compose，再考虑云端。