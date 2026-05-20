---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-20
model_usage: 当前项目能力总览，优先用于判断“现在能做什么”。视频生成能力以本文件为准。
---

> 文档状态：当前主线文档。用于快速判断项目当前已经落地、半自动可用、仍在实验的能力。

# 当前能力总览

更新时间：2026-05-20

## 一句话结论

当前项目主线已经切到“动漫数字人主讲”：关键词/文案 -> 脚本 -> 分段配音 -> Sonic 角色视频层 -> 动漫背景 -> 字幕避让 -> FFmpeg 合成 -> 抖音发布。管理后台和 `AutoPublishRequest.video_mode` 当前默认都是 `presenter_anime`。

单人口播模板视频仍可用，但现在定位为历史稳定/兜底路线，不再作为当前主线。双角色人物视频、FramePack 动作帧、微动作 PNG 序列已有可用合成代码和本地样片，作为可选增强路线。

当前默认规则：

- 当前网页平台实际默认：`src/web/app.py` 的“在线制作/发布”下拉框默认选中“动漫数字人主讲”，传入 `video_mode=presenter_anime`。
- 服务层默认：`AutoPublishRequest.video_mode` 默认是 `presenter_anime`。
- ComfyUI 默认不随 Streamlit 平台启动；只有生成 Presenter 动漫背景时才按需启动，生成完成后由代码尝试关闭。

## 能直接使用的能力

| 能力 | 状态 | 入口 | 说明 |
|---|---|---|---|
| 关键词生成脚本和音频 | 可用 | `python main.py quick --keywords "励志"` | RAG/随机书籍提炼 + LLM 脚本 + GPT-SoVITS 配音，可选 BGM |
| 直接文本生成音频 | 可用 | `python main.py quick --text "..."` | 跳过脚本生成，直接 TTS |
| 导入知识库 | 可用 | `python main.py import-knowledge --books-dir data/books` | 将本地书籍导入 Chroma |
| 动漫数字人主讲视频 | 当前主线 | 管理后台在线制作 / `python main.py presenter ...` | Edge-TTS + Sonic 角色层 + 动漫背景 + 字幕合成；默认 `video_mode=presenter_anime` |
| 单人口播视频合成 | 历史/兜底可用 | 管理后台选择“单人口播模板（旧格式）” / `compose_video()` | 模板视频循环到音频时长，替换音轨并输出 mp4 |
| 一键生成并发布 | 可用 | `python main.py auto-publish --keywords "励志"` | CLI 当前使用 `AutoPublishRequest` 默认模式，即 `presenter_anime` |
| 手动发布已有视频 | 可用 | `python main.py douyin-publish --video ... --title ...` | 浏览器自动上传、填写标题描述和话题 |
| 抖音视频同步 | 可用 | `python main.py douyin-sync` | 从创作者后台同步视频列表并落库 |
| 评论抓取 | 可用 | `python main.py douyin-fetch-comments --video-id X` / `--all` | 抓取评论并写入本地数据库 |
| 评论自动回复 | 可用 | `python main.py auto-reply --video-id X` / `--all` | 规则/LLM/默认回复 + 限流 + 历史记录 |
| Streamlit 管理后台 | 可用 | `streamlit run src/web/app.py` | 视频、评论、规则、违禁词、用户等运营页面 |
| 双角色主动说话视频 | 管理后台可选 | 选择“双角色主动说话正式版” | FramePack 人物帧 + 绿色动态背景 + 主动说话高亮 |

## 视频生成现状

外部项目、背景素材和 FramePack 目录关系见 [关联项目与视频生成集成说明](RELATED_PROJECTS_INTEGRATION.md)。

### 1. 动漫数字人主讲视频：当前主线

当前默认生产路径：

```text
关键词/直接文案
  -> 脚本生成或直接读取
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

- `src/services/auto_publish_service.py`：`video_mode=presenter_anime` 时调用 Presenter 管线。
- `src/content_factory/presenter_pipeline.py`：主讲视频编排。
- `src/content_factory/presenter/background_resolver.py`：背景选择、兜底背景、ComfyUI 按需生成。
- `src/content_factory/presenter/presenter_composer.py`：角色层、背景、字幕层合成。

ComfyUI 启停规则：

- Streamlit 管理平台启动时不启动 ComfyUI。
- 只有 Presenter 生成动漫背景时，`BackgroundResolver._create_comfy_background()` 才检查 `127.0.0.1:8190`。
- 如果 ComfyUI 没运行，代码会按需启动 `D:\IT\AI_vido\ComfyUI\main.py`。
- 背景图片生成完成后，如果是本次流程启动的 ComfyUI，代码会尝试关闭监听 `8190` 的进程。
- 如果 ComfyUI 启动失败或生成失败，流程会回退到本地兜底动漫背景。

当前边界：

- Sonic 当前复用已有角色视频层，尚未按每段音频自动重跑。
- ComfyUI 背景仍会出现伪文字、海报、画框和 IP 角色过大问题，正式批量前需要质检重抽和背景缓存。
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

管理后台的“在线制作/发布”下拉选择“单人口播模板（旧格式）”时走这条旧链路。

### 3. 双角色对话视频：管理后台可选

已经具备的组件：

- `DialogueGenerator` 可生成 A/B 结构化对话脚本。
- `TTSEngine(provider_type="edge")` 可为 A/B 生成不同声音。
- `compose_dual_character_video()` 可把两个角色视频或 PNG 叠到 9:16 背景上。
- `compose_dual_character_sequence_video()` 可把两组 PNG 序列叠到背景视频上。
- `compose_dual_character_sequence_video(active_speaker_timeline=...)` 已正式支持“谁说话谁轻微放大/高亮”。

当前边界：

- 这条链路还没有接入 `main.py auto-publish`。
- SadTalker 口型方案历史上受素材质量影响明显，角色 B 曾因人脸关键点失败阻塞。
- 当前更稳的方向是“静态/微动作/FramePack 角色序列 + 背景合成”，而不是强依赖双角色 SadTalker。

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
- `data/videos/test_viewer_green_dual_v3_active_speaker.mp4`，在 v2 基础上测试“谁说话谁轻微放大/高亮”

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

## 还没有完成的能力

| 能力 | 当前状态 | 备注 |
|---|---|---|
| 双角色视频一键生成发布 | 管理后台可选 | 组件具备，但素材缺失和时间轴精度仍需失败回退 |
| FramePack 全自动生成 | 未完成 | 生成动作 MP4 仍是手动步骤 |
| 定时任务 | 未完成 | `src/scheduler/` 为空 |
| FastAPI 服务化 | 未开始 | 目前是 CLI + Streamlit |
| 队列/Worker | 未开始 | 长任务仍同步执行 |
| 打包部署 | 未开始 | 暂无 Docker/compose |

## 推荐使用顺序

1. 当前主线：使用管理后台“动漫数字人主讲”，或 CLI `python main.py auto-publish --keywords "..."` 的默认 `presenter_anime` 模式。
2. 需要快速生成主讲样片但不发布：使用 `python main.py presenter --keywords "..."`。
3. 需要历史兜底模式：管理后台选择“单人口播模板（旧格式）”。
4. 需要检查或发布已有素材：使用 `douyin-publish`、`douyin-sync`。
5. 需要更丰富双角色画面：使用 FramePack 半自动路线生成角色动作帧，再用项目侧合成。
