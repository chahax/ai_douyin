---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-15
model_usage: 项目介绍。能力细节以 CURRENT_CAPABILITIES.md 为准。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin — 对话式 AI 短视频内容生成与抖音运营自动化平台

> 一款基于 AI 大模型 + 浏览器自动化的本地化抖音内容生产与运营平台。
>
> 当前能力细节见 [当前能力总览](CURRENT_CAPABILITIES.md)。

---

## 产品定位

传统抖音运营依赖大量人工操作：写脚本、找素材、配音、剪辑、上传、回复评论、养号……每一项都要花费大量时间。

AI Douyin 把这些重复性工作交给 AI 完成：用户可以**用自然语言一句话调度所有能力**（生成视频、发布、抓评论、自动回复、养号、查番茄推广），同时保留可视化运营后台给运营人员细粒度控制。

---

## 核心能力

### 1. 对话式 Agent + Skill Registry

整个平台的所有能力都以 Skill 形式注册到 `src/agent/registry.py`（当前 18+ 个），通过 LLM 自动调度：

- **内容生成**：`rag_search` / `generate_presenter_video` / `generate_audio` / `import_knowledge`
- **平台运营**：`publish_douyin` / `sync_douyin_videos` / `fetch_comments` / `auto_reply_comments` / `reply_single_comment`
- **账号养号**：`douyin_warmup` / `douyin_warmup_login` / `douyin_warmup_account_list` / `douyin_warmup_report`
- **番茄推广**：`fanqie_login` / `fanqie_apply_promotion` / `fanqie_fetch_book` / `fanqie_generate_video`
- **记忆与系统**：`get_user_preferences` / `update_user_preferences` / `investigate_problems` / `run_bash_command`

写操作会触发**"先计划、再确认、再执行"**的安全流程：LLM 输出 `​```plan ... ```​` 计划块，用户回复"确认"才执行，"取消"则丢弃，其他输入视作修改请求。

### 2. 动漫数字人主讲视频（当前生产主线）

```
关键词/直接文章/文章提炼
    ↓
AI 生成爆款短视频逐字稿（Hook + Body + 行动建议）
    ↓
Edge-TTS 分段配音 + BGM 混音
    ↓
按 5 秒字幕组提取背景动作 → 按需启动 ComfyUI SDXL 生成动漫背景（或回退到本地兜底）
    ↓
Sonic 角色视频层叠加到右下角，字幕避让
    ↓
FFmpeg 合成 9:16 1080×1920 MP4
    ↓
可选 Selenium 自动化上传抖音
```

支持 `keywords` / `article_direct` / `article_extract` 三种输入通道。

### 3. 知识库辅助创作（RAG）

内置古典典籍知识库（论语、孟子等），通过 Chroma 向量检索 + LLM 生成脚本：

```
用户输入关键词 → PDF/TXT 解析 → Embedding → 语义检索 → AI 结合知识生成脚本
```

### 4. 自动回复评论

```
评论进来
    ↓
意图分类 + 关键词规则匹配 + RAG 检索找到最相关的规则
    ↓
安全过滤（违禁词 + 安全规则）
    ↓
固定回复 / 大模型生成回复 / 限流
    ↓
浏览器自动发送至评论区
```

### 5. 任务调度（APScheduler + 队列）

长任务和定时任务通过 `src/scheduler/` 后台执行：

- **触发**：cron 表达式（如 `37 9 * * *`）、interval（每 N 分钟）。
- **执行**：SQLite 任务队列 + 后台 Worker 线程 `SELECT ... FOR UPDATE SKIP LOCKED`。
- **重试**：每个任务可配置 `max_retries` / `retry_delay_seconds`。
- **预置任务**：每日 09:37 自动扫描未解决问题并让 LLM 给调查方向。
- **管理界面**：Streamlit "任务调度"页（仪表板 / 定时任务 / 队列 / 执行记录）。

### 6. 数据看板 + 多用户权限

实时查看已发布视频的播放、点赞、评论数据；管理后台支持多角色分级：

| 角色 | 权限范围 |
|---|---|
| 超级管理员 | 所有功能、系统配置、用户管理 |
| 运营管理员 | 全部运营操作（发布、评论、自动回复） |
| 运营编辑 | 执行层（手动回复、查看数据） |
| 查看者 | 只读看板数据 |

### 7. 分层记忆系统

- **用户偏好**：默认 TTS/角色/声音/字号/BGM 音量/常用话题等，对话中自动提取并持久化。
- **对话历史**：每条消息入库，新会话可加载最近 20 条作为 LLM 上下文。
- **待确认计划**：LLM 输出暂存到 session，确认/取消后才执行。
- **问题跟踪**：用户提问自动入 `ProblemMemory`，每日 cron 自动调查并更新摘要。

---

## 技术特点

| 特点 | 说明 |
|------|------|
| **技术栈** | Python 3.11 / Streamlit / Selenium / APScheduler / FastAPI (规划中) / LangChain 风格 LLM 客户端 / Edge-TTS / GPT-SoVITS / MoviePy / FFmpeg / Chroma / SQLite / SQLAlchemy |
| **本地部署** | 所有 AI 模型和数据都在本地，不依赖云服务 |
| **本地优先** | 大模型可通过 Ollama 本地运行；Edge-TTS 等可选能力需要联网 |
| **可扩展 Skill** | 所有能力以 Skill 形式注册到统一 Registry，新增能力只需注册一个函数 |
| **安全可控** | 数据本地存储，知识库内容不对外传输；写操作全部需要用户确认 |
| **异常兜底** | Agent / Worker 任何异常都被 catch，写入 ProblemMemory 并由每日 LLM 自动跟进 |
| **自动化程度高** | 从脚本生成到视频发布到评论回复，全流程无需手动切换工具 |

---

## 适用场景

| 场景 | 解决的问题 |
|------|----------|
| 个人创作者 | 没有团队，独自运营多个账号，时间精力有限 |
| 内容批量生产 | 每天需要发布大量视频，人工操作效率低 |
| 知识类账号 | 需要引用古典文献/专业知识，内容准备耗时长 |
| 评论运营 | 视频多、评论多，人工回复不过来 |
| 矩阵号养号 | 多账号需要差异化活跃维护 |

---

## 数据安全

- **本地存储**：所有数据（视频、评论、知识库、记忆）保存在本地，不上传至第三方
- **磁盘加密支持**：可配合 Windows BitLocker 对存储目录整盘加密
- **访问审计**：检索和操作行为有日志记录
- **知识库脱敏**：导入文档时自动过滤敏感信息

---

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.11+
- 至少 8GB 内存（推荐 16GB）
- NVIDIA 显卡（用于本地 AI 模型加速，推荐非必需）

### 启动步骤

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 .env（复制 .env.example 修改）
copy .env.example .env

# 3. 先生成一段音频或数字人视频做本地验证
python main.py quick --keywords "人生哲学导向"
python main.py presenter --keywords "人生哲学导向" --tts-provider edge --max-segments 16

# 4. 首次发布前，先登录抖音创作者后台
python main.py douyin-login

# 5. 启动管理后台（含对话页 + 调度页）
streamlit run src/web/app.py
```

访问 **http://localhost:8501** 即可使用管理后台，对话页面直接用自然语言调度所有能力。

---

## 项目结构

```text
ai_douyin/
├── main.py                      # CLI 入口
├── src/
│   ├── agent/                   # 对话式 Agent（Skill Registry + LLM 计划 + 用户确认拦截）
│   │   ├── agent.py             # Agent.chat() 核心入口
│   │   ├── registry.py          # 18+ Skill 注册表
│   │   └── prompts.py           # Agent System Prompt 构造
│   ├── memory/                  # 分层记忆（用户画像 / 会话 / preference / problem / 问题跟踪）
│   ├── scheduler/               # APScheduler 定时 + SQLite 队列 + 后台 Worker + UI
│   ├── web/                     # Streamlit 管理后台（含对话、调度、视频、评论等）
│   ├── platform_adapter/        # 抖音平台对接（浏览器自动化）+ 番茄推广 MVP + 养号
│   ├── content_factory/         # 内容生成（脚本、配音、视频合成、Presenter 管线）
│   │   └── presenter/           # 动漫数字人主讲视频分段、背景、字幕和合成
│   ├── rag_engine/              # 知识库检索（Chroma + Embedding）
│   ├── services/                # 业务服务层
│   └── shared/                  # 配置、日志、LLM Provider、数据库
├── data/
│   ├── chroma_db/               # 知识库向量数据库
│   ├── books/                   # 导入的书籍/文档
│   ├── videos/                  # 生成的视频文件
│   ├── presenter/               # 数字人主讲视频中间产物
│   ├── ip_characters/           # IP 角色素材
│   ├── douyin.db                # SQLite（视频/评论/记忆/任务）
│   └── browser/                 # 抖音 / 番茄 登录态
└── scripts/
    └── sync_and_import_books.py # 书籍同步导入脚本
```

---

## 联系方式与支持

- 项目维护：[GitHub Issues](https://github.com/your-repo/issues)
- 文档：[docs/](./) 目录下有详细技术文档

---

> 本项目仅供技术研究与个人使用，请遵守抖音平台服务协议和相关法律法规。