---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-15
model_usage: 当前开发进度总览。能力判断优先参考 CURRENT_CAPABILITIES.md，本文件用于看阶段状态。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin 开发进度总览

更新时间：2026-06-15

## 当前状态

项目已经完成单人口播视频的主流程：

```text
关键词/文本
  -> RAG/书籍内容
  -> LLM 生成脚本
  -> GPT-SoVITS 配音
  -> BGM 混音
  -> 模板视频循环合成
  -> 抖音自动发布
  -> 同步视频与评论
  -> 自动回复
```

当前主线已经切到动漫数字人主讲：`AutoPublishRequest.video_mode` 默认是 `presenter_anime`，管理后台"在线制作/发布"也默认选中"动漫数字人主讲"。单人口播模板视频保留为历史/兜底模式。

2026-05-16 至 2026-05-17，动漫数字人主讲路线完成验证：Edge-TTS 分段音频、Sonic 角色视频层、ComfyUI 分段背景、字幕避让和 FFmpeg 拼接均可跑出完整版。ComfyUI 不随平台启动，只在生成背景时按需启动，背景/视频输出完成后代码会尝试关闭 ComfyUI。下一步是把这套逻辑整理成正式 provider，并增加背景质检。

2026-05-24，Presenter CLI 增加三种输入通道：`keywords`、`article_direct`、`article_extract`。`presenter-assets` 现在可用于文章直制或文章提炼的生产预览链路，输出脚本、分段音频、背景图和 `segments.json`，只跳过最终视频合成。

2026-05-25，背景图图片理解质检方案完成设计但已暂缓。当前继续优先优化 ComfyUI/SDXL 模型、社会劳动类安全场景池和提示词。

2026-05-25，新增背景场景规划器第一版，但试用后默认关闭。当前主流程退回 BackgroundResolver 内置规则 + SDXL/Animagine 模型；`debug-background-plan` 仅保留为调试命令。

2026-05-30，抖音账号养号/活跃维护 CLI 测试版完成：支持多账号独立浏览器 profile、账号信息保存、手动登录、精选页推荐入口、按视频时长倍率随机停留、自动下滑、评论区打开和下滑、可控视频点赞和评论点赞，并记录本地日志。默认不自动发评论、关注、收藏，遇到验证码/安全验证会停留等待用户处理。

2026-06-15，Agent + 分层记忆 + 任务调度三件套落地：

- `src/agent/`：对话式入口，自动调 LLM + Skill Registry，写操作走"先计划、再确认"流程。
- `src/memory/`：用户画像 / 会话消息 / 分层记忆（preference / problem / discarded / normal）+ ProblemMemory 自动跟踪未解决问题。
- `src/scheduler/`：APScheduler 包装 + SQLite 任务队列 + 后台 Worker；Streamlit "任务调度"页内置每日 `investigate_problems` 自动播种。

## 阶段进度表

| 阶段 | 名称 | 状态 | 说明 |
|---|---|---|---|
| 阶段 0 | 基础加固 | 已完成 | 配置治理、依赖清单、环境自检、TTS 主通路收口 |
| 阶段 1 | 应用服务层抽取 | 已完成 | 请求/结果模型、统一服务方法、CLI 薄入口化 |
| 阶段 2 | Provider 抽象 + Ollama | 已完成 | LLM Provider 已拆出，Ollama 可用 |
| 阶段 3 | 抖音平台功能 | 已完成 | 发布、同步、评论抓取、自动回复 |
| 阶段 4 | Streamlit 管理后台 | 已完成 | 视频、评论、自动回复、规则、违禁词、用户等页面 |
| 阶段 4.1 | 单人口播视频生成 | 已完成 | 历史/兜底模式，管理后台可选"单人口播模板（旧格式）" |
| 阶段 4.2 | 双角色对话素材链 | 局部完成 | 对话生成、双声线 TTS、FFmpeg 合成函数已具备 |
| 阶段 4.3 | 微动作 PNG 序列 | 局部完成 | 眨眼/呼吸序列生成与最终合成已验证 |
| 阶段 4.4 | FramePack 动作帧 | 半自动可用 | FramePack 手动生成，本项目抽帧/抠图/合成 |
| 阶段 4.5 | 动漫数字人主讲 | 当前主线 | 支持关键词、文章直接、文章提炼三输入；ComfyUI 按需启动并在生成后尝试关闭 |
| 阶段 4.6 | 背景图图片质检 | 已暂缓 | 设计文档保留，当前不接入图片理解质检主链路 |
| 阶段 4.7 | 背景场景规划器 | 默认关闭 | 试用后暂缓进入主链路，保留调试命令和设计材料 |
| 阶段 4.8 | 抖音账号养号/活跃维护 | 测试版完成 | 多账号 profile、手动登录、随机看视频、评论区浏览、可控点赞和日志已完成 CLI 验证 |
| 阶段 4.9 | 对话式 Agent + Skill Registry | 已完成 | 18+ Skill 自动注册，写操作需用户确认；失败兜底写 ProblemMemory |
| 阶段 4.10 | 分层记忆 + 问题跟踪 | 已完成 | preference/problem/discarded/normal 自动分类，每日 cron 调查未解决问题 |
| 阶段 5 | 任务调度（APScheduler + 队列） | 已完成 | cron/interval 触发、SQLite 队列、Worker 重试、Streamlit 管理页 |
| 阶段 6 | API 服务层 | 未开始 | FastAPI 入口未实现；Agent 尚未拆为独立服务 |
| 阶段 7 | 跨进程 Worker / 多实例 | 未开始 | 当前 SQLite 锁仅适合单进程 |
| 阶段 8 | 打包与部署 | 未开始 | 暂无 Docker/compose |

## 当前 CLI 命令

```bash
# 内容/音频生成
python main.py generate --topic "成长" --count 1
python main.py quick --keywords "励志,成长"
python main.py quick --text "直接要配音的文本"
python main.py presenter --keywords "人生哲学导向"
python main.py presenter-assets --keywords "法律，规则"
python main.py presenter --input-mode article_direct --text-file data/articles/rule_law.txt
python main.py presenter --input-mode article_extract --text-file data/articles/rule_law.txt
python main.py debug-background-plan --text "这曾是无数外卖骑手、网约车司机、网络主播心中的困惑。"
python main.py import-knowledge --books-dir data/books

# 抖音平台
python main.py douyin-login
python main.py douyin-upload-page
python main.py douyin-publish --video data/videos/demo.mp4 --title "标题"
python main.py douyin-sync
python main.py douyin-fetch-comments --video-id X
python main.py douyin-fetch-comments --all
python main.py douyin-reply-comment --video-id X --comment-id Y --content "回复内容"
python main.py auto-publish --keywords "励志"
python main.py auto-reply --video-id X
python main.py auto-reply --all
python main.py douyin-warmup-login --account-id "douyin_novel_01" --wait-for-enter
python main.py douyin-warmup-account show --account-id "douyin_novel_01"
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 5
python main.py douyin-warmup-report --account-id "douyin_novel_01" --days 7

# 番茄推广
python main.py fanqie-login --wait-for-enter
python main.py fanqie-promo-apply --type novel --alias "小说推广号A" --keep-open
python main.py fanqie-book-fetch --book-name "小说名" --chapters 10 --headless
python main.py fanqie-promo-video --task-file data/fanqie_promotion/tasks/<task_id>/task.json
```

注意：当前 `main.py` 没有 `compose`、`publish`、`sync`、`fetch-comments` 这些短命令；请使用上面的真实命令名。

## 视频生成状态

| 模式 | 状态 | 说明 |
|---|---|---|
| 单人口播模板视频 | 已完成 | 历史/兜底模式，模板视频按音频时长循环 |
| 手动已有视频发布 | 已完成 | 用 `douyin-publish` 直接发布 mp4 |
| 双角色对话脚本 + 双声线 TTS | 局部完成 | `GenerationService.run_dialogue_generation()` 可返回结构化结果和 A/B 音频 |
| 双角色视频叠加 | 局部完成 | `compose_dual_character_video()` 支持角色视频/PNG + 背景合成 |
| 双角色 PNG 序列合成 | 局部完成 | `compose_dual_character_sequence_video()` 可合成两组角色帧 |
| 本地微动作 | 局部完成 | `micro_motion.py` 生成眨眼/呼吸角色帧 |
| FramePack 接入 | 半自动可用 | 手动生成 MP4，本项目后处理并合成 |
| 动漫数字人主讲 | 当前主线 | `keywords` / `article_direct` / `article_extract` 三输入 + Edge-TTS + Sonic 角色视频层 + ComfyUI 按需背景 + 字幕合成 |
| 抖音账号养号/活跃维护 | 测试版完成 | `douyin-warmup-login` / `douyin-warmup` / `douyin-warmup-account` / `douyin-warmup-report` 可用 |
| 双角色一键发布 | 管理后台可选 | `video_mode=dual_framepack_active`，依赖已有 FramePack 角色帧和背景素材 |

## Agent / Skill 状态

- Agent：`src/agent/agent.py`，LLM 决策 + Skill 调度 + 用户确认拦截 + 异常兜底。
- Skill Registry：`src/agent/registry.py`，已注册 18+ Skill，涵盖内容/平台/养号/番茄/知识库/记忆管理/系统工具。
- 记忆：`src/memory/`，用户画像、会话、分层记忆、问题跟进。
- 调度：`src/scheduler/`，APScheduler cron/interval + SQLite 任务队列 + 后台 Worker。
- 内置任务：`investigate_problems_daily` 每日 09:37 自动调查未解决问题。
- UI 入口：Streamlit 管理后台"对话"页面（Agent.chat）和"任务调度"页面。

## 代表性输出

- `data/videos/dual_v13_blink_only.mp4`
- `data/videos/dual_v14_framepack_idle.mp4`
- `data/videos/dual_v14_healing_bg.mp4`
- `data/videos/presenter_20260516_225643_comfy_full.mp4`

这些样片说明 9:16 输出、PNG 序列叠加、FramePack 后处理路线已能跑出成片。管理后台已经提供相关模式入口，但素材检查、失败回退和时间轴精度仍需要继续加固。
`presenter_20260516_225643_comfy_full.mp4` 说明动漫数字人主讲路线的分段背景和合成层已验证，但 ComfyUI 生成仍需增加伪文字质检和重抽。

## 主要代码索引

| 文件 | 说明 |
|---|---|
| `main.py` | CLI 入口 |
| `src/services/generation_service.py` | 脚本、TTS、BGM、对话生成编排 |
| `src/services/auto_publish_service.py` | 一键生成并发布 |
| `src/content_factory/video_composer.py` | 单视频/双角色/PNG 序列 FFmpeg 合成 |
| `src/content_factory/framepack_pipeline.py` | FramePack 输出后处理 |
| `src/content_factory/presenter_pipeline.py` | 动漫数字人主讲视频编排 |
| `docs/prompts/article-to-presenter-script.txt` | 长文章提炼为 Presenter 口播稿的提示词 |
| `docs/prompts/background-scene-analysis.txt` | 背景场景语义分析提示词 |
| `data/background_scene_library/social_law.json` | 社会/法律/劳动类安全场景库 |
| `src/content_factory/presenter/scene_planner.py` | 背景场景规划器 |
| `src/content_factory/presenter/` | 分段、背景规则、字幕层和单段合成 |
| `src/content_factory/micro_motion.py` | 本地角色微动作序列 |
| `src/platform_adapter/douyin_adapter.py` | 抖音浏览器自动化适配 |
| `src/platform_adapter/douyin_warmup.py` | 抖音账号养号/活跃维护，多账号 profile、随机浏览、评论区浏览和可控点赞 |
| `src/platform_adapter/fanqie_promotion.py` | 番茄小说推广 MVP |
| `src/agent/agent.py` | Agent 核心（对话 + 计划 + 确认拦截） |
| `src/agent/registry.py` | Skill 注册表 + 18+ Skill 实现 |
| `src/memory/manager.py` | 用户画像 / 会话 / 消息 |
| `src/memory/problem_memory.py` | 分层记忆 + ProblemMemory |
| `src/scheduler/cron.py` | APScheduler 定时调度 |
| `src/scheduler/queue.py` | 任务队列 + Worker |
| `src/scheduler/ui.py` | Streamlit 调度管理页 |
| `src/web/app.py` | Streamlit 管理后台 |

## 近期建议

1. 把动漫数字人主讲的 ComfyUI 背景生成封装成 `BackgroundProvider`，支持 `fallback|preset|comfyui|auto`，并保留按需启动/生成后关闭的行为。
2. 增加背景质检和失败回退：伪文字、海报、人物过大、安全区占用时重抽或回退。
3. 把双角色/FramePack 路线封装成服务层请求模型。
4. 给 `auto-publish` 增加 `--mode single_template|dual_framepack_active|presenter_anime`，避免 CLI 默认模式和网页默认模式继续混淆。
5. 把 Agent 拆成独立服务（FastAPI / WebSocket），调度和对话解耦。
6. 把后台 Worker 切换到支持跨进程的队列（PostgreSQL / Redis / 专用 broker），再考虑多实例。