---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-15
model_usage: 当前项目能力总览，优先用于判断"现在能做什么"。视频生成能力以本文件为准。
---

> 文档状态：当前主线文档。用于快速判断项目当前已经落地、半自动可用、仍在实验的能力。

# 当前能力总览

更新时间：2026-06-15

## 一句话结论

项目主线已经形成"**对话式 Agent + 内容工厂 + 平台运营 + 定时调度**"四件套：

- **内容生产主线**：动漫数字人主讲（关键词/文章/文案 → 脚本 → 分段配音 → Sonic 角色层 → 动漫背景 → 字幕避让 → FFmpeg 合成 → 抖音发布）。
- **对话入口**：用户可以用自然语言调起任何 Skill（生成/发布/同步/评论/养号/番茄推广/知识库/记忆管理），涉及写操作的 Skill 必须用户确认后才执行。
- **任务调度**：基于 APScheduler + SQLite SKIP LOCKED 的队列，长任务和定时任务已经能在后台自动跑。
- **记忆系统**：用户偏好、对话历史、问题记忆自动入库，问题长期未解决会由每日 cron 让 LLM 给调查方向。

## 能直接使用的能力

| 能力 | 状态 | 入口 | 说明 |
|---|---|---|---|
| 对话式调用任意能力 | 可用 | Streamlit 聊天页 / `Agent(user_id).chat()` | 18+ Skill 自动注册；写操作需确认 |
| 关键词生成脚本和音频 | 可用 | `python main.py quick --keywords "励志"` | RAG/随机书籍提炼 + LLM 脚本 + GPT-SoVITS 配音，可选 BGM |
| 直接文本生成音频 | 可用 | `python main.py quick --text "..."` | 跳过脚本生成，直接 TTS |
| 导入知识库 | 可用 | `python main.py import-knowledge --books-dir data/books` | 将本地书籍导入 Chroma |
| 动漫数字人主讲视频 | 当前主线 | 管理后台在线制作 / `python main.py presenter ...` | 支持 `keywords`、`article_direct`、`article_extract` 三种输入；Edge-TTS + Sonic 角色层 + 动漫背景 + 字幕合成 |
| Presenter 资产预览 | 可用 | `python main.py presenter-assets ...` | 输出脚本、分段音频、背景图和 `segments.json`，跳过最终视频合成 |
| 背景场景规划器 | 暂停默认使用 | `python main.py debug-background-plan --text "..."` | 已保留调试能力，但默认关闭；当前回到 BackgroundResolver 内置规则生成英文 ComfyUI prompt |
| 单人口播视频合成 | 历史/兜底可用 | 管理后台选择"单人口播模板（旧格式）" / `compose_video()` | 模板视频循环到音频时长，替换音轨并输出 mp4 |
| 一键生成并发布 | 可用 | `python main.py auto-publish --keywords "励志"` | CLI 当前使用 `AutoPublishRequest` 默认模式，即 `presenter_anime` |
| 手动发布已有视频 | 可用 | `python main.py douyin-publish --video ... --title ...` | 浏览器自动上传、填写标题描述和话题 |
| 抖音视频同步 | 可用 | `python main.py douyin-sync` | 从创作者后台同步视频列表并落库 |
| 评论抓取 | 可用 | `python main.py douyin-fetch-comments --video-id X` / `--all` | 抓取评论并写入本地数据库 |
| 评论自动回复 | 可用 | `python main.py auto-reply --video-id X` / `--all` | 规则/LLM/默认回复 + 限流 + 历史记录 |
| 定时任务与队列 | 可用 | Streamlit"任务调度"页 / `ScheduledTask` 表 | 支持 cron / interval；后台 Worker 自动拉取；失败可重试 |
| 问题记忆 + 每日调查 | 可用 | 内置 `investigate_problems_daily` cron | 每天 09:37 自动扫描未解决问题并让 LLM 给摘要 |
| Streamlit 管理后台 | 可用 | `streamlit run src/web/app.py` | 视频、评论、规则、违禁词、用户、调度、对话等运营页面 |
| 双角色主动说话视频 | 管理后台可选 | 选择"双角色主动说话正式版" | FramePack 人物帧 + 绿色动态背景 + 主动说话高亮 |
| 小说推广视频平台支线 | MVP 测试版 | `python main.py fanqie-login` / `fanqie-promo-apply` / `fanqie-book-fetch` / `fanqie-promo-video` | 已新增 CLI 和 `src/platform_adapter/fanqie_promotion.py`，支持番茄达人中心登录态、申请推广、取小说章节、生成推广视频；页面自动化仍需实测修正，不视为稳定生产能力 |
| 抖音账号养号/活跃维护 | 测试版完成 | `python main.py douyin-warmup-login --account-id ...` / `python main.py douyin-warmup --account-id ... --mode daily` | 支持多账号独立浏览器 profile、手动登录、精选页推荐入口、按视频时长倍率停留、自动下滑、评论区打开/下滑、可控视频点赞和评论点赞；不自动发评论/关注/收藏 |

## 对话式 Agent（新增）

完整说明见 `src/agent/` 和 `docs/PROJECT_INTRO.md`。

- Agent 接收用户消息，自动入库分层记忆（preference/problem/discarded/normal）。
- 涉及写操作的 Skill（`generate_presenter_video`、`publish_douyin`、`auto_reply_comments` 等）会先生成计划 JSON，用户回复"确认"才执行；"取消"则丢弃；其他输入视作修改请求。
- 任何内部异常都被 `_handle_chat_failure` 接住并写进 ProblemMemory，UI 永远拿到兜底文本。
- 默认示例 Skill（节选）：
  - 内容：`rag_search`、`generate_presenter_video`、`generate_audio`、`import_knowledge`
  - 平台：`publish_douyin`、`sync_douyin_videos`、`fetch_comments`、`auto_reply_comments`、`reply_single_comment`、`open_upload_page`
  - 番茄：`fanqie_login`、`fanqie_apply_promotion`、`fanqie_fetch_book`、`fanqie_generate_video`
  - 养号：`douyin_warmup`、`douyin_warmup_login`、`douyin_warmup_account_list`、`douyin_warmup_report`
  - 记忆：`get_user_preferences`、`update_user_preferences`、`investigate_problems`
  - 系统：`run_bash_command`

## 视频生成现状

外部项目、背景素材和 FramePack 目录关系见 [关联项目与视频生成集成说明](RELATED_PROJECTS_INTEGRATION.md)。

### 1. 动漫数字人主讲视频：当前主线

当前默认生产路径：

```text
关键词/直接文章/文章提炼
  -> 脚本生成、文章清洗或文章提炼
  -> 分段字幕
  -> Edge-TTS 逐段生成音频
  -> 按 5 秒字幕组提取背景动作
  -> 按需启动 ComfyUI 生成动漫背景，或回退到本地兜底背景
  -> Sonic/视频角色层叠加到右下角
  -> 字幕避让角色
  -> FFmpeg 拼接输出 mp4
  -> 可选自动上传到抖音
```

代表性输出：

- `data/videos/presenter_20260516_225643.mp4`：本地兜底背景完整版。
- `data/videos/presenter_20260516_225643_comfy_singlebg.mp4`：单张 ComfyUI 背景合成验证。
- `data/videos/presenter_20260516_225643_comfy_full.mp4`：ComfyUI 分段背景完整版。

关键代码：

- `main.py`：`presenter` / `presenter-assets` CLI，支持 `--input-mode` 和 `--text-file`。
- `src/services/auto_publish_service.py`：`video_mode=presenter_anime` 时调用 Presenter 管线。
- `src/content_factory/presenter_pipeline.py`：主讲视频编排。
- `src/content_factory/presenter/scene_planner.py`：背景文本理解、场景分类和场景库匹配。
- `src/content_factory/presenter/background_resolver.py`：背景选择、兜底背景、ComfyUI 按需生成。
- `src/content_factory/presenter/presenter_composer.py`：角色层、背景、字幕层合成。

Presenter 当前输入通道：

| 输入模式 | 命令参数 | 行为 |
|---|---|---|
| `keywords` | `--keywords "法律，规则"` | 走现有关键词/RAG/LLM 口播稿生成 |
| `article_direct` | `--input-mode article_direct --text-file data/articles/a.txt` | 读取文章，清洗后直接作为口播稿 |
| `article_extract` | `--input-mode article_extract --text-file data/articles/a.txt` | 用 `docs/prompts/article-to-presenter-script.txt` 提炼成 60-90 秒口播稿 |

ComfyUI 启停规则：

- Streamlit 管理平台启动时不启动 ComfyUI。
- 只有 Presenter 生成动漫背景时，`BackgroundResolver._create_comfy_background()` 才检查 `127.0.0.1:8190`。
- 如果 ComfyUI 没运行，代码会按需启动 `D:\IT\AI_vido\ComfyUI\main.py`。
- 背景图片生成完成后，如果是本次流程启动的 ComfyUI，代码会尝试关闭监听 `8190` 的进程。
- 如果 ComfyUI 启动失败或生成失败，流程会回退到本地兜底动漫背景。

当前边界：

- Sonic 当前复用已有角色视频层，尚未按每段音频自动重跑。
- ComfyUI/SDXL 背景仍可能出现伪文字；当前已退回 BackgroundResolver 内置规则，图片理解质检和 ScenePlanner 默认链路均已暂缓。
- ComfyUI 启停逻辑目前写在 `BackgroundResolver` 内部，后续仍建议抽成正式 `BackgroundProvider`。

### 2. 单人口播视频：历史/兜底路线

这是历史上最稳定的旧路径，现在保留为兜底模式：

```text
关键词/直接文本
  -> RAG 检索或随机书籍片段
  -> 智慧提炼与短视频脚本
  -> GPT-SoVITS 生成配音
  -> 可选 BGM 混音
  -> 模板视频 stream_loop 循环到音频长度
  -> FFmpeg 合成最终 mp4
  -> 可选自动上传到抖音
```

关键代码：

- `src/services/generation_service.py`
- `src/services/auto_publish_service.py`
- `src/content_factory/video_composer.py`
- `src/content_factory/tts_engine.py`
- `src/content_factory/audio_mixer.py`

单人口播模板模式使用 `DEFAULT_TEMPLATE_VIDEO` 作为模板视频。模板路径如果不存在，流程会在视频合成阶段失败，需要通过参数或配置换成可用 mp4。

管理后台的"在线制作/发布"下拉选择"单人口播模板（旧格式）"时走这条旧链路。

### 3. 双角色对话视频：管理后台可选

已经具备的组件：

- `DialogueGenerator` 可生成 A/B 结构化对话脚本。
- `TTSEngine(provider_type="edge")` 可为 A/B 生成不同声音。
- `compose_dual_character_video()` 可把两个角色视频或 PNG 叠到 9:16 背景上。
- `compose_dual_character_sequence_video()` 可把两组 PNG 序列叠到背景视频上。
- `compose_dual_character_sequence_video(active_speaker_timeline=...)` 已正式支持"谁说话谁轻微放大/高亮"。

当前边界：

- 这条链路还没有接入 `main.py auto-publish`。
- SadTalker 口型方案历史上受素材质量影响明显，角色 B 曾因人脸关键点失败阻塞。
- 当前更稳的方向是"静态/微动作/FramePack 角色序列 + 背景合成"，而不是强依赖双角色 SadTalker。

### 4. 本地微动作 PNG 序列：可生成可合成

`src/content_factory/micro_motion.py` 已实现：

- 分层 PNG 角色素材加载
- 眨眼事件生成
- 胸口阴影呼吸效果
- 双角色 PNG 序列并行渲染

已验证样片包括：

- `data/videos/dual_v13_blink_only.mp4`
- `data/videos/dual_v12_micro_motion.mp4`（历史问题版本，已归档分析）

这条路线适合低成本、可控、离线的角色轻微动态视频。

### 5. FramePack 动作帧：半自动可用

当前推荐路线：

```text
角色图
  -> FramePack 手动生成 2-4 秒人物动作 MP4
  -> 本项目抽帧
  -> chromakey/透明化
  -> 循环到目标音频长度
  -> 双角色 PNG 序列合成最终视频
```

关键代码：

- `src/content_factory/framepack_pipeline.py`
- `src/content_factory/video_composer.py`

已验证样片：

- `data/videos/dual_v14_framepack_idle.mp4`，1080x1920，30fps，约 31.56 秒
- `data/videos/dual_v14_healing_bg.mp4`，1080x1920，约 31.56 秒
- `data/videos/dual_v15_green_motion_bg.mp4`，复用历史 FramePack 人物素材，背景替换为 `bg_comfy_green_loop_motion.mp4`
- `data/videos/dual_v16_green_active_speaker_official.mp4`，正式版主动说话角色放大/高亮样片
- `data/videos/dual_final_v10.mp4`，较早的双角色同屏候选样片
- `data/videos/dual_final_mixed.mp4`，更早的头像式双角色对话样片
- `data/videos/test_viewer_green_dual_v2_close.mp4`，浅绿色动态背景 + 更近角色构图测试
- `data/videos/test_viewer_green_dual_v3_active_speaker.mp4`，在 v2 基础上测试"谁说话谁轻微放大/高亮"

历史双角色背景和人物素材已集中到 `data/asset_collections/history_dual_framepack_2026_05_13/`。

管理后台在线制作可选择 `dual_framepack_active`：生成 A/B 对话音频，复用 FramePack 人物 PNG 序列和 `bg_comfy_green_loop_motion.mp4`，并在合成阶段套用主动说话角色放大/高亮。自动上传阶段默认以 headless 浏览器运行，不弹出可见浏览器窗口；首次登录仍需要手动使用可见浏览器完成。

当前边界：

- FramePack 生成 MP4 这一步仍建议手动通过官方 Gradio 完成。
- 本项目侧已能处理 FramePack 输出后的抽帧、抠图、循环和最终合成。
- 主动说话高亮当前按整段 A/B 音频切换；要做到真实交替对话，需要对每句台词生成时间轴。
- 等 FramePack CLI/API 稳定后，再考虑接入一键流水线。

## 平台运营能力

当前抖音平台侧能力已经比较完整：

- 登录态保存：`douyin-login`
- 打开上传页：`douyin-upload-page`
- 发布已有视频：`douyin-publish`
- 生成并发布：`auto-publish`
- 同步创作者后台视频：`douyin-sync`
- 抓评论：`douyin-fetch-comments`
- 单条回复：`douyin-reply-comment`
- 自动回复：`auto-reply`
- 本地 SQLite 记录视频、评论、回复历史、规则、违禁词、用户限流

番茄推广支线当前是 MVP 测试版：

- 登录态：`python main.py fanqie-login --wait-for-enter`，复用与抖音类似的浏览器会话目录 `data/browser/fanqie/`。
- 推广申请：`python main.py fanqie-promo-apply --type novel --alias "小说推广号A" --keep-open`。
- 小说章节获取：`python main.py fanqie-book-fetch --book-name "小说名" --chapters 10 --headless`。
- 推广视频生成：`python main.py fanqie-promo-video --task-file data/fanqie_promotion/tasks/<task_id>/task.json`。
- 当前边界：页面 DOM、验证码/安全验证和推广申请结果仍需要人工实测；绑定抖音视频 ID 和番茄任务尚未实现。

## 调度与自动化能力

- **任务定义**：`ScheduledTask` 表 + Streamlit"任务调度"页面（仪表板 / 定时任务 / 队列 / 执行记录）。
- **触发器**：cron 表达式（如 `37 9 * * *`）、interval（每 N 分钟）。
- **执行**：后台 Worker 线程 `SELECT ... FOR UPDATE SKIP LOCKED` 抢任务，调 `SkillRegistry.call()` 执行。
- **重试**：每个任务有 `max_retries` / `retry_delay_seconds`，失败自动重试到上限。
- **预置任务**：首次启动时会自动播种 `investigate_problems_daily`（每日 09:37 扫描未解决问题）。
- **内置 Skill 任务**：UI 上提供"📊 CodeGraph 周更"快捷按钮，自动注册每周日凌晨 3:00 重跑 `codegraph init -i`。

## 记忆与对话能力

- **用户偏好**：默认 TTS/角色/声音/字号/BGM 音量/常用话题等，可在对话中通过 Skill 调整并自动持久化到 `user_profiles`。
- **会话历史**：每条对话自动入库 `conversation_sessions` / `conversation_messages`，新会话可加载最近 20 条作为 LLM 上下文。
- **待确认计划**：LLM 输出的 `​```plan ... ```​` 块暂存到 `ConversationSession.pending_plan`，用户回复"确认/取消"才执行或丢弃。
- **分层记忆**：
  - `preference` 自动提取偏好写入 `user_memory`。
  - `problem` 写入 `problem_memory`，自动去重。
  - `discarded` 不入库（闲聊/无效提问）。
  - `normal` 进入 `conversation_memory` 滑动窗口。
- **问题跟进**：每日 cron 自动调用 `investigate_problems` 让 LLM 给调查摘要，长期未解决的会保留 `last_investigation_note`。

## 还没有完成的能力

| 能力 | 当前状态 | 备注 |
|---|---|---|
| 双角色视频一键生成发布 | 管理后台可选 | 组件具备，但素材缺失和时间轴精度仍需失败回退 |
| FramePack 全自动生成 | 未完成 | 生成动作 MP4 仍是手动步骤 |
| 番茄推广视频 ID 绑定 | 未完成 | 当前只到申请推广、取章节、生成视频；尚未自动回填/绑定抖音视频 ID |
| FastAPI 服务化 | 未开始 | 目前是 CLI + Streamlit；Agent 尚未拆为独立 HTTP 服务 |
| 跨进程 Worker | 未开始 | 当前 SQLite SKIP LOCKED 适合单进程；多 Worker 需要切换到 PostgreSQL/MySQL 或专用队列 |
| 打包部署 | 未开始 | 暂无 Docker/compose |
| Agent 多用户隔离 | 未开始 | 当前 `user_id="default"`；权限/限流依赖 Streamlit `auth.py` |

## 推荐使用顺序

1. 想"一句话搞定"：用 Streamlit 聊天页直接说"帮我生成一个关于'自律'的动漫数字人视频"或"把所有视频评论自动回一遍"，Agent 会先出计划，确认后执行。
2. 当前生产主线：使用管理后台"动漫数字人主讲"，或 CLI `python main.py auto-publish --keywords "..."` 的默认 `presenter_anime` 模式。
3. 需要快速生成主讲样片但不发布：使用 `python main.py presenter --keywords "..."`。
4. 需要历史兜底模式：管理后台选择"单人口播模板（旧格式）"。
5. 需要检查或发布已有素材：使用 `douyin-publish`、`douyin-sync`。
6. 需要长期无人值守：到"任务调度"页配置 cron，调度对应的 Skill（如 `sync_douyin_videos`、`auto_reply_comments`）。
7. 需要更丰富双角色画面：使用 FramePack 半自动路线生成角色动作帧，再用项目侧合成。