---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-15
model_usage: 当前用户使用手册。命令以本文件和 main.py 为准。
---

> 文档状态：当前主线文档。用于运行 CLI 和管理后台。

# AI Douyin 使用指南

更新时间：2026-06-15

## 环境准备

建议先确认：

- Python 环境已安装依赖：`pip install -r requirements.txt`
- `.env` 已从 `.env.example` 复制并按本机路径调整
- Ollama 已启动并能访问本地模型
- GPT-SoVITS SDK 路径和 conda Python 路径正确
- FFmpeg/ffprobe 可在命令行调用
- 首次发布前已完成抖音登录

关键配置项：

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

TTS_PROVIDER=edge
GPT_SOVITS_SDK_ROOT=./GPT_SoVITS
GPT_SOVITS_CONDA_PYTHON=C:/Users/<your-user>/.conda/envs/GPTSoVits/python.exe

DOUYIN_STORAGE_STATE_PATH=./data/browser/douyin/storage_state.json
DOUYIN_USER_DATA_DIR=./data/browser/douyin/user_data
```

## 常用命令

### 导入知识库

```bash
python main.py import-knowledge --books-dir data/books
```

### 生成音频

按主题从知识库检索并生成：

```bash
python main.py generate --topic "成长" --count 1
```

快速关键词生成：

```bash
python main.py quick --keywords "励志,成长"
```

直接文本配音：

```bash
python main.py quick --text "这里是一段直接生成配音的文本。"
```

指定输出目录：

```bash
python main.py quick --keywords "自律" --output-dir data/videos
```

### 一键生成并发布视频

```bash
python main.py auto-publish --keywords "励志,成长" --title "越自律越自由" --tags "励志,成长,自律"
```

当前 CLI `auto-publish` 没有 `--mode` 参数，会使用 `AutoPublishRequest` 里的默认 `video_mode`。截至 2026-05-20，代码默认值是 `presenter_anime`，也就是动漫数字人主讲路线。

当前默认路线：

```text
关键词/文章 -> 脚本 -> Edge-TTS 分段配音 -> Sonic 角色层 -> 动漫背景 -> 字幕合成 -> 抖音上传
```

ComfyUI 行为：

- 启动管理后台时不会启动 ComfyUI。
- 生成动漫背景时才会按需检查/启动 `127.0.0.1:8190` 的 ComfyUI。
- 背景图片生成完成后，如果是本次流程启动的 ComfyUI，代码会尝试关闭它。
- 如果 ComfyUI 不可用，会回退到本地兜底背景。

单人口播模板视频现在是历史/兜底模式。如果需要使用，需要在管理后台选择“单人口播模板（旧格式）”；CLI 后续建议补 `--mode single_template`：

```bash
python main.py auto-publish --keywords "成长" --template data/videos/template.mp4
```

### 生成动漫数字人主讲视频

关键词生成完整视频：

```bash
python main.py presenter --keywords "人生哲学导向" --character data/ip_characters/_incoming/sonic_test/fox_planner_576_mouthboost_upscale1080_sharp.mp4 --tts-provider edge --max-segments 16
```

只生成脚本、分段音频和背景图，不合成最终视频：

```bash
python main.py presenter-assets --keywords "法律，规则" --title "法律，规则" --max-segments 16
```

已有文章直接制作视频，不让 LLM 大改原文：

```bash
python main.py presenter --input-mode article_direct --text-file data/articles/rule_law.txt --title "法律，规则"
```

已有长文章先提炼成 60-90 秒短视频口播稿，再制作视频：

```bash
python main.py presenter --input-mode article_extract --text-file data/articles/rule_law.txt --title "法律，规则"
```

长文章默认不截断分段。如果只想生成前几段用于快速测试，可以加 `--max-segments 16`。

三种输入模式：

| 模式 | 说明 |
|---|---|
| `keywords` | 根据 `--keywords` 生成口播稿 |
| `article_direct` | 读取 `--text` 或 `--text-file`，清洗后直接制作 |
| `article_extract` | 读取 `--text` 或 `--text-file`，先提炼为短视频口播稿 |
 
`--no-comfy-background` 可用于快速本地兜底背景测试；正式质量测试建议不加该参数，走 ComfyUI 生产背景。

查看单段文本会匹配到什么背景场景：

```bash
python main.py debug-background-plan --text "这曾是无数外卖骑手、网约车司机、网络主播心中的困惑。"
```

背景场景规划器当前默认关闭，主流程已退回 `BackgroundResolver` 内置规则。`debug-background-plan` 仅用于调试场景库，不影响默认生成。

当前边界：

- `main.py presenter` 会直接生成数字人主讲视频；ComfyUI 不可用时会使用本地兜底背景。
- 管理后台“在线制作/发布”当前默认选择“动漫数字人主讲”，对应 `video_mode=presenter_anime`。
- `main.py presenter-assets` 会生成生产预览资产，但不合成最终视频。
- 文章提炼使用 `docs/prompts/article-to-presenter-script.txt`。

### 发布已有视频

```bash
python main.py douyin-publish --video data/videos/demo.mp4 --title "标题" --desc "描述" --tags "励志,成长"
```

### 登录和上传页

```bash
python main.py douyin-login
python main.py douyin-upload-page
```

### 抖音账号养号

首次为账号创建独立浏览器 profile，并由用户手动登录：

```bash
python main.py douyin-warmup-login --account-id "douyin_novel_01" --wait-for-enter
```

查看或更新账号基本信息：

```bash
python main.py douyin-warmup-account list
python main.py douyin-warmup-account show --account-id "douyin_novel_01"
python main.py douyin-warmup-account set --account-id "douyin_novel_01" --display-name "小说推广号A" --login-name "138****1234" --keywords "小说推荐,短剧反转,番茄小说"
```

基础养号，默认进入抖音精选页并点击“推荐”：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 5
```

按视频时长倍率停留，`--max-watch 0` 表示读到视频时长后不封顶：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --min-watch 8 --max-watch 0 --duration-ratio-min 0.1 --duration-ratio-max 2.0 --max-videos 5
```

强制打开评论区、下滑 3 次并最多点赞 2 条评论：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 1 --min-comment-opens 1 --comment-scrolls 3 --comment-like-probability 1 --max-comment-likes 2 --keep-open
```

10 个视频内最多 5 个视频赞、最多 5 个评论赞：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 10 --like-probability 0.5 --max-likes 5 --min-comment-opens 1 --comment-scrolls 3 --comment-like-probability 0.5 --max-comment-likes 5
```

查看养号日志：

```bash
python main.py douyin-warmup-report --account-id "douyin_novel_01" --days 7
```

说明：养号不会自动发评论、关注、收藏。遇到登录/验证码/安全验证时默认保持浏览器打开，用户处理后回终端按回车保存会话。

### 番茄小说推广 MVP

当前番茄推广支线是 CLI 测试版，目标是先跑通：番茄达人中心申请可推广小说 -> 获取小说名和推广别名 -> 搜索小说章节 -> 生成推广脚本和 Presenter 视频。

首次登录番茄达人中心并保存浏览器会话：

```bash
python main.py fanqie-login --wait-for-enter
```

浏览器打开后手动登录番茄达人中心，登录完成后回终端按回车。番茄会话目录与抖音登录方案类似，使用：

```text
data/browser/fanqie/user_data
data/browser/fanqie/storage_state.json
```

申请一本可推广小说，并填写推广别名：

```bash
python main.py fanqie-promo-apply --type novel --alias "小说推广号A" --keep-open
```

输出会保存任务文件：

```text
data/fanqie_promotion/tasks/<task_id>/task.json
```

根据小说名获取前 10 章：

```bash
python main.py fanqie-book-fetch --book-name "小说名" --chapters 10 --headless
```

用任务文件生成推广视频：

```bash
python main.py fanqie-promo-video --task-file "data/fanqie_promotion/tasks/<task_id>/task.json" --chapters 10 --max-segments 8
```

只生成脚本、音频和背景资产，不合成最终视频：

```bash
python main.py fanqie-promo-video --task-file "data/fanqie_promotion/tasks/<task_id>/task.json" --chapters 10 --max-segments 6 --assets-only
```

快速流程测试可跳过 ComfyUI 背景：

```bash
python main.py fanqie-promo-video --task-file "data/fanqie_promotion/tasks/<task_id>/task.json" --chapters 3 --max-segments 4 --assets-only --no-comfy-background
```

当前边界：

- 番茄推广页面自动化依赖页面 DOM 和按钮文案，仍需按实际页面继续修正。
- 遇到登录、验证码、短信验证或安全验证时，由用户手动完成，不绕过平台风控。
- 当前只做到申请推广、获取章节和生成视频；番茄平台绑定抖音视频 ID 尚未实现。
- 项目不保存明文账号、密码或验证码；浏览器登录态保存在本地 `data/browser/fanqie/`。

### 同步视频和评论

```bash
python main.py douyin-sync
python main.py douyin-fetch-comments --video-id X
python main.py douyin-fetch-comments --all
```

### 回复评论

```bash
python main.py douyin-reply-comment --video-id X --comment-id Y --content "谢谢你的评论"
python main.py auto-reply --video-id X
python main.py auto-reply --all
```

## 管理后台

启动：

```bash
streamlit run src/web/app.py
```

访问：

```text
http://localhost:8501
```

### 公网临时访问

本机已安装 `cloudflared`，可以用 Cloudflare Quick Tunnel 临时开放公网访问：

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8501 --no-autoupdate
```

后台运行和查看公网地址的方法见：

[Cloudflared 公网访问](CLOUDFLARED_PUBLIC_ACCESS.md)

公网地址会把管理后台暴露到互联网，使用前请确认账号登录、角色权限和用户用量限制已启用。

后台主要页面：

| 页面 | 能力 |
|---|---|
| 看板 | 视频数、评论数、回复率等统计 |
| 视频 | 同步视频、抓取评论、一键生成并发布 |
| 评论 | 查看评论和回复状态 |
| 自动回复 | 对单个或全部视频执行自动回复 |
| 规则 | 管理关键词回复规则 |
| 违禁词 | 管理回复过滤词 |
| 用户 | 管理角色与限流 |
| 对话 | 直接用自然语言调起任意 Skill（Agent + Skill Registry） |
| 任务调度 | 仪表板 / 定时任务 / 任务队列 / 执行记录 |
| 设置 | 查看当前配置 |

### 对话式 Agent

Streamlit"对话"页面背后是 `src/agent/agent.py`：

- 用户发消息 → 自动入库分层记忆 → Agent 调 LLM + Skill Registry。
- 涉及写操作的 Skill（生成视频、发布、自动回复、养号、番茄推广等）会先生成 `​```plan ... ```​` 计划块。
- 用户回复"确认"才执行，"取消"则丢弃，其他输入视作修改请求。
- 任何异常都被兜底成"抱歉，我现在处理这条消息时遇到了点问题"，并写入 ProblemMemory。

可以直接说：

- "帮我生成一个关于'自律'的动漫数字人视频"
- "把所有视频的评论自动回一遍"
- "把昨天那个视频再同步一次评论"
- "把默认 TTS 换成 GPT-SoVITS"

### 任务调度

"任务调度"页面提供：

- **仪表板**：活跃任务 / 排队中 / 运行中 / 已完成 / 失败 + 启动/停止调度器按钮。
- **定时任务**：新建 cron / interval 任务，可选 Skill 列表 + 重试次数 + JSON 参数。
- **任务队列**：查看 pending / running 任务。
- **执行记录**：按状态筛选历史执行，可展开查看错误详情或返回 JSON。
- **预置任务**：首次启动会自动播种 `investigate_problems_daily`（每日 09:37 调查未解决问题）。
- **快捷按钮**：UI 上提供"📊 CodeGraph 周更"按钮，自动注册每周日凌晨 3:00 重跑 `codegraph init -i`。

后台 Worker 由 `src/scheduler/runner.py` 在 Streamlit 启动时静默拉起，SQLite `SELECT ... FOR UPDATE SKIP LOCKED` 保证多 Worker 不会重复抢同一任务（适合单进程）。

## 视频生成方式

### 单人口播模板视频

这是历史/兜底路线，不是当前默认主线。

入口：

- CLI：`python main.py auto-publish --keywords "..."`
- 后台：视频页的“一键生成并发布视频”

输出：

- 音频和混音结果在 `data/videos/`
- 最终 mp4 在 `data/videos/`
- 发布记录写入 `data/douyin.db`

### FramePack 半自动合成

FramePack 生成 MP4 后，项目侧可处理抽帧、抠图、循环和合成。

处理单角色：

```bash
python src/content_factory/framepack_pipeline.py --video na1_idle_v1 --role a --audio-a data/ref_audio/role_a.wav
python src/content_factory/framepack_pipeline.py --video n3_idle_v1 --role b --audio-b data/ref_audio/role_b.wav
```

尝试双角色合成：

```bash
python src/content_factory/framepack_pipeline.py --video na1_idle_v1 --role dual --audio-a data/ref_audio/role_a.wav --audio-b data/ref_audio/role_b.wav --bg data/videos/bg_loop.mp4
```

更多说明见 [FramePack 接入方案](FRAMEPACK_INTEGRATION_PLAN.md)。

## 常见问题

### 生成视频失败：模板不存在

`auto-publish` 默认模板路径在 `src/services/auto_publish_service.py` 中。可以用 `--template` 指定本地存在的 mp4。

### TTS 失败

检查：

- `GPT_SOVITS_SDK_ROOT` 是否存在
- `GPT_SOVITS_CONDA_PYTHON` 是否存在
- 默认参考音频是否存在
- GPT-SoVITS 权重路径是否与本机一致

### RAG 检索为空

先导入知识库：

```bash
python main.py import-knowledge --books-dir data/books
```

并确认 Ollama embedding 模型已拉取。

### 发布失败

先重新登录：

```bash
python main.py douyin-login
```

再确认 `data/browser/douyin/` 下有登录态文件，且抖音创作者后台页面没有改版导致选择器失效。

### 命令不存在

当前没有这些旧命令：

- `python main.py compose`
- `python main.py publish`
- `python main.py sync`
- `python main.py fetch-comments`

请使用：

- `douyin-publish`
- `douyin-sync`
- `douyin-fetch-comments`
- `auto-publish`
