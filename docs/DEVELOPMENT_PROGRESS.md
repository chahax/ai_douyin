---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-17
model_usage: 当前开发进度总览。能力判断优先参考 CURRENT_CAPABILITIES.md，本文件用于看阶段状态。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin 开发进度总览

更新时间：2026-05-17

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

双角色人物视频、微动作 PNG 序列、FramePack 动作帧已经有独立代码和样片验证，但还不是 `auto-publish` 的默认一键模式。

2026-05-16 至 2026-05-17，动漫数字人主讲路线完成半自动验证：Edge-TTS 分段音频、Sonic 角色视频层、ComfyUI 分段背景、字幕避让和 FFmpeg 拼接均可跑出完整版。下一步是把临时 ComfyUI API 调用整理成正式 provider，并增加背景质检。

## 阶段进度表

| 阶段 | 名称 | 状态 | 说明 |
|---|---|---|---|
| 阶段 0 | 基础加固 | 已完成 | 配置治理、依赖清单、环境自检、TTS 主通路收口 |
| 阶段 1 | 应用服务层抽取 | 已完成 | 请求/结果模型、统一服务方法、CLI 薄入口化 |
| 阶段 2 | Provider 抽象 + Ollama | 已完成 | LLM Provider 已拆出，Ollama 可用 |
| 阶段 3 | 抖音平台功能 | 已完成 | 发布、同步、评论抓取、自动回复 |
| 阶段 4 | Streamlit 管理后台 | 已完成 | 视频、评论、自动回复、规则、违禁词、用户等页面 |
| 阶段 4.1 | 单人口播视频生成 | 已完成 | 当前 `auto-publish` 默认模式 |
| 阶段 4.2 | 双角色对话素材链 | 局部完成 | 对话生成、双声线 TTS、FFmpeg 合成函数已具备 |
| 阶段 4.3 | 微动作 PNG 序列 | 局部完成 | 眨眼/呼吸序列生成与最终合成已验证 |
| 阶段 4.4 | FramePack 动作帧 | 半自动可用 | FramePack 手动生成，本项目抽帧/抠图/合成 |
| 阶段 4.5 | 动漫数字人主讲 | 半自动可用 | `main.py presenter` 可跑兜底版；ComfyUI 分段背景和 Sonic 视频层已验证，待 provider 化 |
| 阶段 5 | API 服务层 | 未开始 | FastAPI 入口未实现 |
| 阶段 6 | 异步任务执行 | 未开始 | 队列和 Worker 未实现 |
| 阶段 7 | 定时调度 | 未开始 | `src/scheduler/` 尚未形成能力 |
| 阶段 8 | 打包与部署 | 未开始 | 暂无 Docker/compose |

## 当前 CLI 命令

```bash
# 内容/音频生成
python main.py generate --topic "成长" --count 1
python main.py quick --keywords "励志,成长"
python main.py quick --text "直接要配音的文本"
python main.py presenter --keywords "人生哲学导向"
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
```

注意：当前 `main.py` 没有 `compose`、`publish`、`sync`、`fetch-comments` 这些短命令；请使用上面的真实命令名。

## 视频生成状态

| 模式 | 状态 | 说明 |
|---|---|---|
| 单人口播模板视频 | 已完成 | `auto-publish` 默认路线，模板视频按音频时长循环 |
| 手动已有视频发布 | 已完成 | 用 `douyin-publish` 直接发布 mp4 |
| 双角色对话脚本 + 双声线 TTS | 局部完成 | `GenerationService.run_dialogue_generation()` 可返回结构化结果和 A/B 音频 |
| 双角色视频叠加 | 局部完成 | `compose_dual_character_video()` 支持角色视频/PNG + 背景合成 |
| 双角色 PNG 序列合成 | 局部完成 | `compose_dual_character_sequence_video()` 可合成两组角色帧 |
| 本地微动作 | 局部完成 | `micro_motion.py` 生成眨眼/呼吸角色帧 |
| FramePack 接入 | 半自动可用 | 手动生成 MP4，本项目后处理并合成 |
| 动漫数字人主讲 | 半自动可用 | Edge-TTS + Sonic 角色视频层 + ComfyUI 分段背景已生成完整版，待一键化 |
| 双角色一键发布 | 未完成 | 尚未接入 `auto-publish` |

## 代表性输出

- `data/videos/dual_v13_blink_only.mp4`
- `data/videos/dual_v14_framepack_idle.mp4`
- `data/videos/dual_v14_healing_bg.mp4`
- `data/videos/presenter_20260516_225643_comfy_full.mp4`

这些样片说明 9:16 输出、PNG 序列叠加、FramePack 后处理路线已能跑出成片；它们不代表已经进入一键自动发布主流程。
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
| `src/content_factory/presenter/` | 分段、背景规则、字幕层和单段合成 |
| `src/content_factory/micro_motion.py` | 本地角色微动作序列 |
| `src/platform_adapter/douyin_adapter.py` | 抖音浏览器自动化适配 |
| `src/web/app.py` | Streamlit 管理后台 |

## 近期建议

1. 把动漫数字人主讲的 ComfyUI 背景生成封装成 `BackgroundProvider`，支持 `fallback|preset|comfyui|auto`。
2. 增加背景质检和失败回退：伪文字、海报、人物过大、安全区占用时重抽或回退。
3. 把双角色/FramePack 路线封装成服务层请求模型。
4. 增加资源检查和失败回退：模板视频、音频、背景、角色帧缺失时给出清晰错误。
5. 在稳定后给 `auto-publish` 增加 `--mode single|dual|framepack|presenter`。
6. 再考虑定时任务、API 和 Worker。
