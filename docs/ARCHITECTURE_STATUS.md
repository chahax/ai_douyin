---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-20
model_usage: 当前架构状态说明。用于区分已落地能力、半自动能力和后续规划。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# AI Douyin 架构状态总览

更新时间：2026-05-20

## 当前做到哪一步

项目当前已经形成一个本地运行的短视频内容运营工具：

- 内容生成：书籍/RAG -> LLM -> 短视频脚本
- 音频生成：Edge-TTS 当前用于快速测试和数字人主讲；GPT-SoVITS 保留为可选声线方案
- 视频生成：当前主线是动漫数字人主讲，单人口播模板视频保留为历史/兜底模式
- 动漫数字人：管理后台和服务默认 `presenter_anime`；ComfyUI 分段背景 + Sonic 视频角色层已验证
- 平台动作：抖音登录、发布、同步、抓评论、回复评论
- 管理后台：Streamlit 页面已覆盖主要运营操作
- 本地数据：SQLite + Chroma + 文件产物目录

一句话判断：当前主线是动漫数字人主讲；ComfyUI 不随平台启动，只在生成背景时按需启动并在生成后尝试关闭。单人口播模板视频是历史/兜底路线，双角色和 FramePack 是可选增强路线。

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
| Streamlit 后台 | 可用 | 视频、评论、规则、用户、设置 |
| FastAPI | 未开始 | 暂无 HTTP API |
| 队列/Worker | 未开始 | 长任务同步执行 |
| 定时调度 | 未开始 | 暂未形成调度能力 |

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

## 主要边界

- `auto-publish` 当前默认使用 `presenter_anime`。
- `presenter` 可直接生成数字人主讲视频；ComfyUI 不可用时会回退到本地兜底背景。
- FramePack 生成人物动作 MP4 仍建议手动完成。
- 双角色 SadTalker 曾受角色素材影响，稳定性不如 PNG 序列和 FramePack 路线。
- 发布后 `post_id` 可能依赖后续 `douyin-sync` 补齐，数据库以 `local_id` 作为本地追踪依据。
- 抖音创作者后台属于页面/内部接口自动化，页面变化会影响稳定性。

## 推荐路线

1. 继续把动漫数字人主讲作为当前生产主线。
2. 把 ComfyUI 背景封装成 provider，并保留按需启动/生成后关闭的行为。
3. 把 FramePack/微动作合成封装成服务层，增加输入资源检查。
4. 给 `auto-publish` 增加模式参数，例如 `single`、`dual`、`framepack`、`presenter`。
5. 等生成链路稳定后，再推进调度、API、队列和部署。
