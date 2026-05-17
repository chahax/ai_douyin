---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-17
model_usage: 当前架构状态说明。用于区分已落地能力、半自动能力和后续规划。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin 架构状态总览

更新时间：2026-05-17

## 当前做到哪一步

项目当前已经形成一个本地运行的短视频内容运营工具：

- 内容生成：书籍/RAG -> LLM -> 短视频脚本
- 音频生成：Edge-TTS 当前用于快速测试和数字人主讲；GPT-SoVITS 保留为可选声线方案
- 视频生成：单人口播模板视频合成已接入发布主流程
- 动漫数字人：`main.py presenter` 可生成本地兜底背景版；ComfyUI 分段背景 + Sonic 视频角色层已半自动验证
- 平台动作：抖音登录、发布、同步、抓评论、回复评论
- 管理后台：Streamlit 页面已覆盖主要运营操作
- 本地数据：SQLite + Chroma + 文件产物目录

一句话判断：单人口播视频从生成到发布已经可用；动漫数字人主讲、双角色和 FramePack 已有验证链路，但仍是半自动能力。

## 组件状态

| 组件 | 状态 | 说明 |
|---|---|---|
| CLI `main.py` | 可用 | 薄入口，调用服务层 |
| `GenerationService` | 可用 | 脚本、TTS、BGM、对话生成编排 |
| `AutoPublishService` | 可用 | 关键词生成内容、合成模板视频、上传抖音、落库 |
| `video_composer.py` | 可用 | 单视频、双角色视频、双角色 PNG 序列合成 |
| `presenter_pipeline.py` | 半自动可用 | 动漫数字人主讲编排，当前 ComfyUI 背景待 provider 化 |
| `micro_motion.py` | 局部可用 | 角色眨眼/呼吸 PNG 序列 |
| `framepack_pipeline.py` | 半自动可用 | 接管 FramePack 输出后的抽帧/抠图/循环 |
| 抖音适配器 | 可用 | 浏览器自动化发布、同步、评论、回复 |
| Streamlit 后台 | 可用 | 视频、评论、规则、用户、设置 |
| FastAPI | 未开始 | 暂无 HTTP API |
| 队列/Worker | 未开始 | 长任务同步执行 |
| 定时调度 | 未开始 | 暂未形成调度能力 |

## 视频生成状态

| 路线 | 状态 | 是否接入一键发布 |
|---|---|---|
| 单人口播模板视频 | 已完成 | 是 |
| 发布已有 mp4 | 已完成 | 不需要生成 |
| 双角色对话脚本 + 双声线 TTS | 局部完成 | 否 |
| 双角色 FFmpeg 叠加 | 局部完成 | 否 |
| 本地微动作 PNG 序列 | 局部完成 | 否 |
| FramePack 动作帧 | 半自动可用 | 否 |
| 动漫数字人主讲 | 半自动可用 | 否 |

当前最稳的生产路径仍是 `auto-publish` 的单人口播模板视频。

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

## 主要边界

- `auto-publish` 只自动合成单人口播模板视频，不会自动调用双角色/FramePack 管线。
- `presenter` 可直接生成本地兜底背景版，ComfyUI 分段背景仍是半自动流程。
- FramePack 生成人物动作 MP4 仍建议手动完成。
- 双角色 SadTalker 曾受角色素材影响，稳定性不如 PNG 序列和 FramePack 路线。
- 发布后 `post_id` 可能依赖后续 `douyin-sync` 补齐，数据库以 `local_id` 作为本地追踪依据。
- 抖音创作者后台属于页面/内部接口自动化，页面变化会影响稳定性。

## 推荐路线

1. 继续把单人口播视频作为稳定生产线。
2. 先把动漫数字人主讲的 ComfyUI 背景封装成 provider，并增加质检重抽。
3. 把 FramePack/微动作合成封装成服务层，增加输入资源检查。
4. 给 `auto-publish` 增加模式参数，例如 `single`、`dual`、`framepack`、`presenter`。
5. 等生成链路稳定后，再推进调度、API、队列和部署。
