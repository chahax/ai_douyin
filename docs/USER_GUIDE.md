---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-20
model_usage: 当前用户使用手册。命令以本文件和 main.py 为准。
---

> 文档状态：当前主线文档。用于运行 CLI 和管理后台。

# AI Douyin 使用指南

更新时间：2026-05-20

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
GPT_SOVITS_CONDA_PYTHON=C:/Users/c/.conda/envs/GPTSoVits/python.exe

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
关键词 -> 脚本 -> Edge-TTS 分段配音 -> Sonic 角色层 -> 动漫背景 -> 字幕合成 -> 抖音上传
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

本地兜底背景版可直接运行：

```bash
python main.py presenter --keywords "人生哲学导向" --character data/ip_characters/_incoming/sonic_test/fox_planner_576_mouthboost_upscale1080_sharp.mp4 --tts-provider edge --max-segments 16
```

当前边界：

- `main.py presenter` 会直接生成数字人主讲视频；ComfyUI 不可用时会使用本地兜底背景。
- 管理后台“在线制作/发布”当前默认选择“动漫数字人主讲”，对应 `video_mode=presenter_anime`。
- ComfyUI 分段背景已验证，但还没有封装成正式 CLI 参数；暂时属于半自动流程。
- 已验证样片：`data/videos/presenter_20260516_225643_comfy_full.mp4`。

### 发布已有视频

```bash
python main.py douyin-publish --video data/videos/demo.mp4 --title "标题" --desc "描述" --tags "励志,成长"
```

### 登录和上传页

```bash
python main.py douyin-login
python main.py douyin-upload-page
```

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
| 设置 | 查看当前配置 |

## 视频生成方式

### 单人口播模板视频

这是当前推荐的稳定路线。

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
