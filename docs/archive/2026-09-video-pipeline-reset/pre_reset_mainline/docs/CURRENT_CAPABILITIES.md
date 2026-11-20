---
doc_status: current
doc_category: mainline
last_reviewed: 2026-08-24
model_usage: 当前项目能力总览，优先用于判断"现在能做什么"。视频生成能力以本文件为准。
---

> 文档状态：当前主线文档。用于快速判断项目当前已经落地、半自动可用、仍在实验的能力。

# 当前能力总览

更新时间：2026-08-24

> 2026-08-07 基线说明：状态按“代码存在、自动化测试覆盖、本机样片验证、平台生产稳定”分层判断。仓库中存在实现或实验产物，不等同于已经成为稳定的一键生产能力。

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
| 三联画视频 | 可用、已测试 | `python main.py triple-panel ...` | 支持质量档位、区域缩放、运动报告和质量门禁；具体参数以 `--help` 为准 |
| 故事视频合成 | 可用、已测试 | `python main.py story-video ...` | 清单驱动，多角色/旁白音频，支持 `hold_last` 和输出帧率控制 |
| 视频质量档位 | 可用、已测试 | `presenter` / `auto-publish` 的 `--quality-profile` | `preview`、`publish`、`master` 三档，输出质量诊断 JSON |
| Presenter 资产预览 | 可用 | `python main.py presenter-assets ...` | 输出脚本、分段音频、背景图和 `segments.json`，跳过最终视频合成 |
| 背景场景规划器 | 暂停默认使用 | `python main.py debug-background-plan --text "..."` | 已保留调试能力，但默认关闭；当前回到 BackgroundResolver 内置规则生成英文 ComfyUI prompt |
| 单人口播视频合成 | 历史/兜底可用 | 管理后台选择"单人口播模板（旧格式）" / `compose_video()` | 模板视频循环到音频时长，替换音轨并输出 mp4 |
| 一键生成并发布 | 可用 | `python main.py auto-publish --account-id account01 --keywords "励志"` | 生成前先核验绑定身份和账号 UUID |
| 手动发布已有视频 | 可用 | `python main.py douyin-publish --account-id account01 --video ... --title ...` | 发布前显示并核验真实抖音身份 |
| 抖音视频同步 | 可用 | `python main.py douyin-sync --account-id account01` | 按运营账号同步并落库，账号间数据隔离 |
| 评论抓取 | 可用 | `python main.py douyin-fetch-comments --account-id account01 --video-id X` | 只读抓取本账号作品评论 |
| 评论回复建议 | 可用、只读 | 管理后台“回复建议” | 规则/LLM 生成建议；逐条人工确认前不会发送 |
| 定时任务与队列 | 可用 | Streamlit"任务调度"页 / `ScheduledTask` 表 | 支持 cron / interval；后台 Worker 自动拉取；失败可重试 |
| 问题记忆 + 每日调查 | 可用 | 内置 `investigate_problems_daily` cron | 每天 09:37 自动扫描未解决问题并让 LLM 给摘要 |
| Streamlit 管理后台 | 可用 | `streamlit run src/web/app.py` | 视频、评论、规则、违禁词、用户、调度、对话等运营页面 |
| 双角色主动说话视频 | 管理后台可选 | 选择"双角色主动说话正式版" | FramePack 人物帧 + 绿色动态背景 + 主动说话高亮 |
| 小说推广视频平台支线 | MVP 测试版 | `python main.py fanqie-login` / `fanqie-promo-apply` / `fanqie-book-fetch` / `fanqie-promo-video` | 已新增 CLI 和 `src/platform_adapter/fanqie_promotion.py`，支持番茄达人中心登录态、申请推广、取小说章节、生成推广视频；页面自动化仍需实测修正，不视为稳定生产能力 |

> 2026-08-13 V6/V6.1 真人剧情检查：旧 V6 技术产物仍只有 8/19 镜头，视觉预审仅 `b02` 暂通过，详见 `data/qa/task1_story_v6_partial_visual_review.json`，旧片全部禁止上传。现已为 19 个节拍重做 V6.1 真人写实动作锚点；P0 生产加载器验证为 19/19、40.8 秒、无结构错误，锚点文件和 SHA-256 全部匹配，审计见 `data/qa/task1_story_v61_anchor_review.json`。该审计只批准锚点进入失败镜头冒烟生成，不是成片人工批准。完整 V6.1 视频、机器质检、人工终审及匹配的生效 AIGC/解说混剪番茄任务仍未完成，禁止上传和回填。

> 2026-08-13 V6.1 缓存修复：Claude Code 2.1.226 使用 DeepSeek-V4-Pro 完成“只读审查 → 定向修改 → Codex 测试复核 → Claude 关闭复审”。LTX 运动缓存与时长对齐/MuseTalk/RIFE 交付缓存现已拆分；音频变化只重跑交付，锚点/动作/seed/模型变化会重跑 LTX；缺失或矛盾哈希全部失败关闭。专项与闭环相关测试合计 553 passed，另 1 个只因 P0 只读而不能写 `.pyc` 的用例以 7 文件 AST 解析替代；最终结论为 `APPROVED_FOR_VIDEO_SMOKE`，证据见 `data/qa/task1_story_v61_cache_split_acceptance_20260813.json`。这仍只允许失败镜头冒烟，不允许发布。
| 番茄批量抓取与队列 | 可用、页面侧仍需复测 | `fanqie-promo-list` / `fanqie-list-books` / `fanqie-batch-*` | 支持推广列表同步、本地书库、数据库批次、筛选抓取和调度入队；验证码及 DOM 变化仍需人工处理 |
| 抖音账号健康与运营维护 | 可用 | 管理后台“账号策略” / `python main.py douyin-maintenance --account-id ... --mode daily` | 真实身份唯一绑定、登录健康、相关内容预检、内容质量加权观看时长、真实播放校验、作品/评论同步、互斥锁/动态比例预算/熔断；播放模式可显式开启按候选点赞表现加权的点赞和安全评论，评论单独保留冷却 |

## 对话式 Agent（新增）

完整说明见 `src/agent/` 和 `docs/PROJECT_INTRO.md`。

- Agent 接收用户消息，自动入库分层记忆（preference/problem/discarded/normal）。
- 涉及写操作的 Skill（`generate_presenter_video`、`publish_douyin`、`auto_reply_comments` 等）会先生成计划 JSON，用户回复"确认"才执行；"取消"则丢弃；其他输入视作修改请求。
- 任何内部异常都被 `_handle_chat_failure` 接住并写进 ProblemMemory，UI 永远拿到兜底文本。
- 默认示例 Skill（节选）：
  - 内容：`rag_search`、`generate_presenter_video`、`generate_audio`、`import_knowledge`
  - 平台：`publish_douyin`、`sync_douyin_videos`、`fetch_comments`、`auto_reply_comments`、`reply_single_comment`、`open_upload_page`
  - 番茄：`fanqie_login`、`fanqie_apply_promotion`、`fanqie_fetch_book`、`fanqie_generate_video`
  - 账号维护：`douyin_maintenance`、`douyin_warmup_account_list`、`douyin_warmup_report`（`douyin_warmup` 仅为弃用别名）
  - 记忆：`get_user_preferences`、`update_user_preferences`、`investigate_problems`
  - 系统：`run_bash_command`

## 视频生成现状

### 2026-07 至 2026-08 新增的质量控制工具链

以下能力已经有独立模块、CLI/脚本或自动化测试覆盖，适合用于受控生产和验收；其中调用外部模型的步骤仍取决于本机模型、显存和 ComfyUI 节点是否齐全：

- 控制策略与计划：`video_control_policy.py`、`video_control_plan.py`、`video_agent_pack.py`。
- 质量与验收：`video_quality.py`、`video_quality_gate.py`、`video_review_packet.py`、`video_candidate_benchmark.py`。
- 修复与一致性：`video_recovery.py`、`video_temporal_repair.py`、`video_smoothness.py`、`video_style_gate.py`、`video_lighting_gate.py`、`video_appearance_lock.py`。
- 可控镜头：`deterministic_motion.py`、`deterministic_camera.py`、`keyframe_relight.py`。
- 成片辅助：`video_audio_mux.py`、`video_recipe.py`、`story_video.py`、`triple_panel.py`。
- 已形成 SadTalker、LivePortrait、Sonic、RIFE、LTX/WAN 等多路线的选择和回退规则，但并非每条路线都能在全新机器上开箱运行。

近期已完成反诈故事、医院走廊和文书律师系列的多轮样片/交付物验证。它们证明流水线能产出成片，但其中一部分仍是项目专用脚本，不应视为通用产品 API。

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

### 4. 本地微动作 PNG 序列：历史实现已迁移

旧文档曾引用 `src/content_factory/micro_motion.py`，当前仓库已没有该文件。对应的受控微动作能力已迁移到 `deterministic_motion.py`、`video_control_*`、LivePortrait/SadTalker 路由及项目脚本中。历史样片仍可作为效果参考，但旧模块和旧命令不能再作为当前入口。

历史版本曾实现分层 PNG 加载、眨眼、呼吸阴影和双角色序列渲染；这些描述只适用于历史样片，不代表当前仍有同名公共模块。

已验证样片包括：

- `data/videos/dual_v13_blink_only.mp4`
- `data/videos/dual_v12_micro_motion.mp4`（历史问题版本，已归档分析）

这条路线适合低成本、可控、离线的角色轻微动态视频。

### 5. FramePack 动作素材：外部生成、项目内按具体流水线使用

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

- 当前仓库没有旧版 `src/content_factory/framepack_pipeline.py` 通用入口；FramePack 仍属于关联项目/外部生成工具，已有素材通过具体合成脚本或 `video_composer.py` 接入。
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

### 6. Wan2.2 Animate Move：环境已安装，目标 Move 流尚未提交验证

本机已安装 Kijai 社区版 WanVideoWrapper、WanAnimatePreprocess、14B FP8 主模型和姿态预处理权重，并生成 RTX 5070 Ti 16GB 的 `480×832 / 49 帧 / SDPA / offload` 用户工作流。

当前 Move 状态仍只代表**文件与路径静态校验通过**：尚未向目标 Move 工作流提交驱动视频，因此它仍不属于“可用”或“已测试”能力。2026-08-25 已另行启动秋葉通用环境，并用普通 Wan2.2 5B I2V 生成 2.06 秒烟测；这只证明秋葉运行环境可用，且结果弱于 LTX 对照，不能替代 Move 验证。固定配置、社区方案和烟测证据见 [Wan2.2 Animate Move 本机环境](COMFYUI_WAN22_ANIMATE_MOVE_SETUP.md)。

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

### 番茄真人剧情闭环（task 1，V6.1）

当前已完成 Claude Code（DeepSeek-V4-Pro）多轮审查、LTX/交付阶段缓存拆分、创意静态门和生产数据流修复。V6.1 使用 19 个真人写实表演节拍、固定人物声线和逐镜头审核锚点，不使用动漫人物、数字人主讲或解释性旁白。静态配置不冒充声音自然度证明；真实自然度仍须由前端冒烟审核和整片终审确认。

失败镜头冒烟入口为：

```powershell
# 默认只做静态校验；不会调用 TTS、ComfyUI、数据库、浏览器或平台接口
D:\IT\ai_douyin\.venv\Scripts\python.exe scripts\run_task1_story_v61_failed_smoke.py

# 可变执行不要手写命令。先生成窗口包；只有全部门禁通过时，
# packet.commands.render_seven_shot_smoke 才会出现绑定 runner SHA 的命令。
D:\IT\ai_douyin\.venv\Scripts\python.exe scripts\prepare_task1_story_v61_window_packet.py `
  --run-id YYYYMMDD_HHMMSS --output <全新窗口包路径>
```

截至 2026-08-20，默认静态校验已通过：计划 SHA 锁定，19 个节拍可解析；首轮固定为 `b01/b03/b04/b05/b06/b07/b08`，总计 14.1 秒；7 个锚点 SHA 和 7 条人物声线引用均有效。审计记录见 `data/qa/task1_story_v61_static_revalidation_20260820.json`。这仍是静态证据，不代表已经生成视频或音频。

运行器随后经 Claude Code 的 `deepseek-v4-pro / firstParty` 做创意静态与真实生产数据流复审。复审发现并关闭两项实际阻断：主 CosyVoice3 runner 原本不接受 Provider 的路径参数，真实批量语音会在 argparse 阶段失败；固定 65 帧 LTX 无法承载 3.2/3.3/3.9 秒镜头，最终镜头内 CTA 永远无法生成。现在 runner 显式接受并使用 CosyVoice 根、模型、项目和缓存路径，且保持离线模型保护；LTX 按镜头在 65/97/129 三个受控档位中选择最小可用值，`b11/b15/b18_cta` 使用 97 帧，其余镜头保持 65 帧。关闭结论为 `V61_PRODUCTION_DATA_FLOW_APPROVED`。

2026-08-14 又把运行时源码摘要从“仅记录”升级为执行硬门：Provider、生产加载/生成、情绪 TTS、CosyVoice runner 和创意审计必须匹配受审 SHA；窗口包还固定 smoke runner SHA，并把它传给执行命令，runner 在创建任何进度/音频/渲染目录及调用 TTS/GPU 前重新验证。DeepSeek 关闭复审结论为 `V61_RUNTIME_SOURCE_BINDING_APPROVED`。当前回归为主执行/窗口门 `64 passed`、P0 Provider `212 passed`。逐镜头人工审核模板位于 `data/qa/task1_story_v61_failed_smoke_review_template.json`。

冒烟样片审核已简化为 Streamlit 前端待审核队列：渲染进度一旦包含镜头证据仍拒绝覆盖；操作人在“视频审核”页查看联系表、完整播放视频并逐项确认后点击通过或驳回，登录用户名、备注、决定、播放时间和产物摘要写回审核 JSON，同时写入显式的闭环数据库审计事件，不再使用 Ed25519、`allowed_signers`、审核人就绪证明或 `.sig` 文件。空模板、缺产物、哈希不符或数据库事件缺失的记录不能成为有效批准。完整 19 节拍入口仍会重新验证进度 SHA、7 个 MP4 SHA/时长/50fps/口型阶段证据，并直接复用这 7 个已批准 MP4，只生成剩余 12 镜头。操作见 `docs/FANQIE_V61_HUMAN_REVIEW_SIGNING.md`。

19 镜头之后的整片门禁代码也已完成：每次可变渲染使用同一 run ID 绑定且全新的进度、复验回执、视频、音频和证据路径；7 镜头通过机器包 SHA 绑定后续生产脚本的路径和 SHA-256，整片运行器、合成器与最终终审都会重新计算并拒绝源码或产物变化。19 镜头成功后，运行器会用独占创建方式写入 `fanqie_v61_render_attestation_receipt/v1` 自动回执，绑定最终进度 SHA、计划 SHA、19 镜头边界和非秘密的渲染者标识；它用于满足 P0 的不可变渲染来源门，不需要用户生成或保管密钥，也不是人工审核签名。合成器校验 19 节拍、40.8 秒、50fps、音轨、字幕和无主持人；终审包从候选整片抽取 11 帧，终审验证器会再次抽帧、重建联系表并重验原始 7 镜头与复用片段。人工终审同样在 Streamlit“视频审核”页完成，不要求渲染者或审核者配置密钥。最终审核文件只有在数据库决定事件完整复现审核来源、决定、候选哈希和机器审核包哈希时才显示为有效；残缺事件或批准后产物变化会进入审计异常。2026-08-20 主执行、渲染回执、前端审核与窗口门联合回归为 `159 passed`；P0 登记/发布授权专项为 `60 passed`，P3/调度专项为 `130 passed`。这表示执行与审核门禁可进入真实渲染，不表示视频已经生成、声音自然度已经证明或整片已经人工批准。

终审到真实发布之间的匹配任务门也已实现：`fanqie-promo-list --no-sync --output-json` 生成带 UTC 扫描时刻且不可覆盖的只读列表证据；授权器只接受 15 分钟内唯一匹配书 ID、别名、`AIGC/解说混剪`、生效/可用/未填写且有回填入口的行，并以 `fanqie-story-publish-authorization` OpenSSH 签名绑定数据库任务版本、整片 SHA、完整终审证据和唯一幂等键。P3 使用乐观锁原子认领发布任务，并在浏览器上传前再次校验候选和六份证据摘要。单元/实时列表门为 `58 passed`，P3 回归为 `139 passed`（只读 P0 下排除 1 个写 `.pyc` 的语法测试，7 文件 AST 验证通过）；真实 OpenSSH 和预检后篡改不调用浏览器均已验证。Claude Code/DeepSeek 分别给出 `AUTHORIZATION_EVIDENCE_APPROVED` 与 `P3_AUTHORIZATION_INTEGRATION_APPROVED`。该能力尚未签发真实授权，因为当前没有合格整片和匹配任务。

人工终审进入数据库的桥梁也已实现：前端先把最终审核文件 SHA、候选 SHA、机器审核包 SHA 和登录账号写入显式权威库 `data/fanqie_closed_loop_p0.db` 的 `review_approved/review_rejected` 事件；`scripts/register_fanqie_story_v61_candidate.py` 强制显式传入同一 `--db`、默认只读，只有找到唯一匹配的前端批准事件后，才把生产验证器重新验过的 V6.1 整片原子登记到一个新的匹配 `AIGC/解说混剪` 任务。它绑定书 ID、推广别名、任务 version、来源创作任务 ID、目标推广任务 ID/UUID，以及计划、候选、终审决定、证书、清单、字幕、19 个镜头视频、19 条音频和 11 抽帧摘要；SQLite 以 `BEGIN IMMEDIATE` 串行化跨目标候选唯一性，按合法状态链建立脚本、`story_video`、人工审核和事件。默认 `wisdom_ai.db` 目前不是闭环权威库，前端和登记工具禁止隐式使用它。登记工具本身不能浏览器上传、发布或回填，登记后仍需实时短期发布授权。

当前门禁仍然关闭：尚未生成 V6.1 冒烟视频和整片，尚未取得人工视频批准，也尚未确认匹配的 `AIGC/解说混剪` 番茄任务。现有 task 1 是 `AI数字人` 类型，不能承接无主讲人的真人剧情片。因此严禁上传样片、发布抖音或回填番茄。

2026-08-20 审核流程调整：固定的 `2026-08-18T20:40:00+08:00` TTS/GPU 时间锁及其兼容常量已经从执行源码删除，7 镜头和 19 镜头入口在静态检查、运行时预检、磁盘和不可变路径通过后可立即执行。校验模式仍不能覆盖自定义渲染证据；审核通过也不会自动打开抖音上传或番茄回填。P3 在调用浏览器前仍会重新查询任务版本/状态/有效期、视频任务状态/路径/SHA、审核决定/机器门/SHA；任何并发撤销或到期都会写失败审计且不调用浏览器。

旧的 2026-08-14 只读快照仍保留为历史证据，其中的 `execution_window_open` 和 `trusted_human_reviewer_ready` 阻断项已经失效，不能再作为当前操作依据。当前尚没有已渲染的 V6.1 7 镜头、19 镜头、整片或人工审核批准；数据库合格任务、发布和绑定仍为 0，因此抖音上传与番茄回填继续保持 `false`。

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
| 打包部署 | 基础契约已有 | 已有 Dockerfile、Compose 和 `docs/DOCKER.md`；仍需按目标机器验证模型、GPU 和浏览器依赖 |
| Agent 多用户隔离 | 未开始 | 当前 `user_id="default"`；权限/限流依赖 Streamlit `auth.py` |

## 推荐使用顺序

1. 想"一句话搞定"：用 Streamlit 聊天页直接说"帮我生成一个关于'自律'的动漫数字人视频"或"把所有视频评论自动回一遍"，Agent 会先出计划，确认后执行。
2. 当前生产主线：使用管理后台"动漫数字人主讲"，或 CLI `python main.py auto-publish --keywords "..."` 的默认 `presenter_anime` 模式。
3. 需要快速生成主讲样片但不发布：使用 `python main.py presenter --keywords "..."`。
4. 需要历史兜底模式：管理后台选择"单人口播模板（旧格式）"。
5. 需要检查或发布已有素材：使用 `douyin-publish`、`douyin-sync`。
6. 需要长期无人值守：到“任务调度”页配置 `douyin_maintenance`；评论等外部互动不允许无人值守执行。
7. 需要更丰富双角色画面：使用 FramePack 半自动路线生成角色动作帧，再用项目侧合成。
