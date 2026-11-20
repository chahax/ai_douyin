---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-23
model_usage: Docker 部署指南。覆盖构建、运行、配置、可选服务、局限与故障排查。
---

> 文档状态：当前主线文档。可以作为 Docker 部署的操作手册。

# AI Douyin Docker 部署指南

更新时间：2026-06-23

## 前置要求

| 组件 | 最低版本 | 备注 |
|---|---|---|
| Docker | 24.0+ | `docker --version` |
| Docker Compose | v2 (`docker compose`) | `docker compose version` |
| 内存 | 8 GB+ | 推荐 16 GB |
| 磁盘 | 5 GB+ | 镜像 ~1.5 GB + 数据 + 模型 |
| GPU | **不需要** | LLM 走 OpenAI 兼容 API；本地 Ollama 是可选边车 |

## 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/chahax/ai_douyin.git
cd ai_douyin

# 2. 复制环境变量模板
cp .env.example .env

# 3. 编辑 .env（至少填 LLM key）
#    推荐 DeepSeek（便宜 + 中文强）：
#      LLM_PROVIDER=openai_compatible
#      LLM_API_KEY=sk-xxx
#      LLM_BASE_URL=https://api.deepseek.com/v1
#      LLM_MODEL=deepseek-chat

# 4. 构建并启动
docker compose up -d

# 5. 看启动日志
docker compose logs -f app
# 看到 "You can now view your Streamlit app in your browser." 就好了

# 6. 打开浏览器
open http://localhost:8501
```

启动过程（首次）：
- `docker compose build`：3-5 分钟（pip install + playwright install chromium）
- `docker compose up -d`：5-10 秒（alembic + streamlit）
- 镜像大小：~1.5 GB（Python + 系统依赖 + Playwright Chromium）

## 可用 vs 不可用

### ✅ 容器内可用（开箱即用）

| 功能 | 备注 |
|---|---|
| Streamlit 管理后台 | http://localhost:8501 |
| 对话式 Agent + Skill Registry | 18+ Skill（mock LLM 也能演示） |
| 分层记忆 + 问题跟踪 | MemoryLayerManager + ProblemMemory |
| 任务调度 + 队列 | APScheduler + SQLite Worker |
| LLM 错误诊断 | ErrorReviewer 表 + 调度页错误 tab |
| Edge-TTS 配音 | 网络可达就行 |
| 单人口播模板视频 | FFmpeg 可用 |
| **我的记忆** 页 | sentiment / 偏好 / 待跟进 |
| **任务调度** 页 | 仪表板 / cron / 队列 / 错误诊断 |
| Alembic 迁移 | 启动自动跑 `alembic upgrade head` |

### ⚠️ 部分可用（需要 .env / 命令行 flag）

| 功能 | 绕过方式 |
|---|---|
| 动漫数字人主讲视频（ComfyUI 背景） | 加 `--no-comfy-background` 走本地兜底背景；或外部部署 ComfyUI 后设 `COMFYUI_HOST` |
| GPT-SoVITS 声线克隆 | 外部起 GPT-SoVITS 服务，设 `GPT_SOVITS_USE_SDK=false` + `GPT_SOVITS_API_URL` |
| Ollama 本地 LLM | 取消 compose.yml 里 ollama 注释 |

### ❌ 容器内不可用（需要登录态 / 主机浏览器）

| 功能 | 原因 |
|---|---|
| `douyin-login`（登录抖音） | 需要在**主机上**执行，不能 headless |
| 发布视频到抖音 | 需登录后的 Chrome profile，未挂进容器 |
| 抓取评论 / 自动回复 | 同上 |
| 番茄小说达人中心登录 | 同上 |

**MVP 用法**：把容器当成"Web UI + 记忆浏览 + 调度面板 + 视频试生成（不带背景）"。发布功能保留给主机上的 CLI。

## 配置说明

### `.env` 关键变量

```env
# === LLM ===
LLM_PROVIDER=openai_compatible          # mock | ollama | openai_compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# === TTS ===
TTS_PROVIDER=edge                        # edge | gpt_sovits

# === 可选：接外部 ComfyUI ===
# COMFYUI_HOST=192.168.1.100
# COMFYUI_PORT=8188
COMFYUI_MAIN_PATH=                       # 必须留空，否则容器内尝试启动会失败

# === 可选：接外部 GPT-SoVITS（HTTP 模式）===
# GPT_SOVITS_USE_SDK=false
# GPT_SOVITS_API_URL=http://host:9880

# === 必留空（容器内跑不起来） ===
GPT_SOVITS_SDK_ROOT=
GPT_SOVITS_CONDA_PYTHON=
```

完整列表见 `.env.example`。

### 容器内默认行为（docker-compose.yml 已设）

```yaml
environment:
  PYTHONPATH: /app
  LLM_PROVIDER: ${LLM_PROVIDER:-mock}    # 不设默认 mock
  COMFYUI_MAIN_PATH: ""                   # 禁掉自动启动
  TTS_PROVIDER: edge                      # 不用 conda
  TZ: Asia/Shanghai
```

## 目录结构（容器内 vs 主机）

```
主机 ./data             →   容器 /app/data
├── wisdom_ai.db                (SQLAlchemy + Alembic 管)
├── douyin.db                   (raw SQL 服务层用)
├── chroma_db/                  (向量库)
├── books/                      (用户导入的书籍)
├── videos/                     (生成的视频)
├── presenter/                  (Presenter 中间产物)
├── browser/                    (Chrome profile — 容器内不用)
├── logs/                       (Streamlit + Worker 日志)
└── ...

容器内 /app/src                ← 镜像层（只读）
容器内 /app/alembic             ← 镜像层
容器内 /app/docker/entrypoint.sh
容器内 /usr/bin/ffmpeg          ← apt 装的
容器内 /usr/share/fonts/...     ← Noto CJK
容器内 /root/.cache/ms-playwright/  ← Chromium 二进制
```

## 数据备份

只需要备份主机上的 `./data/` 目录：

```bash
tar czf ai-douyin-backup-$(date +%Y%m%d).tar.gz data/
```

## 升级流程

```bash
# 拉新代码
git pull

# 重建镜像（应用代码改动）
docker compose build

# 重启容器（数据保留）
docker compose up -d

# 如果 alembic 有新迁移，entrypoint 自动跑
docker compose logs -f app | grep alembic
```

## 故障排查

### `alembic upgrade head` 失败

entrypoint 会 fallback 到 `INIT_DB_FALLBACK=1` + `ensure_migrated(strict=False)`，继续启动。如果还失败：

```bash
docker compose exec app alembic current
docker compose exec app alembic upgrade head --sql  # 看 SQL
docker compose exec app bash  # 进容器手动调试
```

### 健康检查不通过

```bash
docker compose ps                # 看 STATUS
docker compose logs app         # 启动日志
curl -fs http://localhost:8501/_stcore/health  # 手动测
```

### 字体豆腐（presenter 视频字幕）

`src/content_factory/presenter/text_overlay.py` 硬编码 `C:/Windows/Fonts/*.ttc`，容器里这些路径不存在。**当前未修**，可用 `--no-comfy-background` 走纯语音版，或等后续 PR。

### 抖音发布 / 评论抓取不可用

MVP 不支持。需要登录态 + 持久 Chrome profile，建议在主机上跑 `python main.py douyin-login` → 再 `python main.py douyin-publish`。

### 端口冲突

修改 `docker-compose.yml`：
```yaml
ports:
  - "9501:8501"   # host 9501 → container 8501
```

## 可选服务接入（取消注释即可）

### Ollama 边车

`docker-compose.yml` 里 ollama service 默认注释。需要：
1. 取消注释
2. `.env` 加 `OLLAMA_BASE_URL=http://ollama:11434`
3. `docker compose up -d`
4. 首次启动会拉模型：`docker compose exec ollama ollama pull qwen2.5:7b`

### GPT-SoVITS HTTP 服务

需要你自己 build 一个 GPT-SoVITS HTTP 镜像（`docker/gpt-sovits/Dockerfile`）：
```dockerfile
# 简化示例，仅供参考
FROM continuumio/miniconda3
RUN conda create -n sovits python=3.9 -y
# 拷贝 GPT_SoVITS 仓库、装依赖...
EXPOSE 9880
CMD ["bash", "-c", "source activate sovits && python api_v2.py"]
```
然后取消 compose.yml 里 `gpt-sovits` 注释，设 `GPT_SOVITS_API_URL=http://gpt-sovits:9880`。

### ComfyUI 边车

类似 GPT-SoVITS，需要你自己 build。需要 GPU passthrough + 8GB+ checkpoint 镜像。详见 [docker/comfyui/README.md](docker/comfyui/README.md)（待写）。

## 关键文件清单

| 文件 | 说明 |
|---|---|
| `Dockerfile` | 单阶段镜像（python:3.11-slim + ffmpeg + fonts + chromium） |
| `.dockerignore` | 不进镜像的内容（data/、.git/、tests/、RESUME.md） |
| `docker/entrypoint.sh` | 启动时跑 alembic + 确保 data/ 子目录 + exec CMD |
| `docker-compose.yml` | app 服务（必需）+ ollama / gpt-sovits / comfyui 注释的边车 |
| `docs/DOCKER.md` | 本文件 |

## 镜像细节

| 组件 | 来源 | 体积 |
|---|---|---|
| `python:3.11-slim` | Docker Hub | ~150 MB |
| `apt-get install` 依赖 | Debian 包 | ~200 MB |
| `pip install -r requirements.txt` | PyPI | ~600 MB |
| `playwright install chromium` | Playwright 自带 | ~300 MB |
| 源码 + alembic | 本仓库 | ~5 MB |
| **合计** | | **~1.3-1.5 GB** |