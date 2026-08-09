---
doc_status: reference
doc_category: imported_context
last_reviewed: 2026-05-20
model_usage: Codex 2026 会话记录整理摘要。用于追溯历史决策、排查结论和已验证路线；不作为当前能力优先依据。
---

> 文档状态：Codex 会话导入摘要。原始记录来自 `~/.codex/sessions/2026`，本文件只保留可复用项目结论，已排除原始对话、账号授权码、临时公网地址等敏感或易过期内容。

# Codex 会话导入摘要（2026）

整理日期：2026-05-20

## 使用说明

- 当前真实能力优先看 [当前能力总览](CURRENT_CAPABILITIES.md)。
- 本文件用于理解“为什么现在是这个方案”，不要把其中的历史尝试直接当成当前主线。
- 原始 Codex `jsonl` 很长，且包含临时日志、外部路径、账号配置片段；本文件只做人工可读摘要。
- 涉及 `data/`、`.env`、浏览器登录态、邮箱授权码、临时 tunnel 的原始信息不要提交到 Git。

## 总体脉络

2026 年 4-5 月的 Codex 会话主要围绕四条线推进：

- 抖音发布链路：修复发布页 URL、成功判断、hashtag 填写与 pending_review 判断。
- 内容生成链路：RAG、Ollama、GPT-SoVITS、Edge-TTS、脚本 prompt 与文档状态整理。
- 视频生成链路：单人口播模板视频成为稳定主线；双角色、SadTalker、微动作、FramePack、ComfyUI/Sonic 作为半自动或实验路线逐步验证。
- 管理后台与协作：Streamlit 后台、账号登录/额度设计、Cloudflared 临时公网访问、Git 分支提交与合并。

## 关键结论

| 主题 | 结论 |
|---|---|
| 当前主线视频 | 单人口播模板视频最稳定，`auto-publish` 默认走这条路线。 |
| 双角色视频 | 已有对话、双声线、合成代码和样片，但不适合作为默认一键生产链路。 |
| SadTalker | 可用于口型驱动验证，但 256x256 头像视频和全身角色合成存在尺度/透明层问题，不建议强依赖为全身主线。 |
| 微动作 PNG | 眨眼/呼吸等轻微动作更适合当前角色视频路线，可作为“动一点”的低风险方案。 |
| FramePack | 适合生成 2-4 秒人物轻动作片段；当前推荐“手动生成 MP4 + 本项目抽帧/抠图/循环/合成”。 |
| ComfyUI 背景 | 已验证可生成 1080x1920 绿色/治愈系循环背景视频，适合作为数字人背景素材来源。 |
| 抖音发布状态 | 发布后短时间查不到作品不应直接判定失败，应记录 `pending_review` 并允许后续同步/人工确认。 |
| RAG/Embedding | 旧记录中出现过 `langchain_ollama` 缺失导致 Ollama embedding 初始化失败，依赖和 fallback 需要保持明确。 |
| 数据安全 | ChromaDB、浏览器登录态、日志、素材库等本地数据不应误提交；`.gitignore` 是重要保护层。 |
| 账号与公网访问 | 邮箱验证码、Cloudflared 适合本地临时协作，但授权码、临时域名、登录态不能进入文档主线或 Git。 |

## 会话摘要

### 2026-04-28：抖音发布与 RAG 数据安全

主要目标：排查抖音发布异常、hashtag 填写超时、发布成功判断和 RAG 数据安全文档。

保留结论：

- 抖音发布页 UI 变化会导致 hashtag 输入 selector 失效，问题应记录为平台适配风险。
- `Page.url` 包装层如果没有实时读取底层页面 URL，会影响发布成功判断。
- 发布成功判断不能只依赖宽泛的 `success/complete/published` class，需要结合真实页面状态。
- `data/chroma_db/`、`data/browser/`、`data/logs/` 等应视为本地数据，避免进入 Git。
- BitLocker 只能缓解设备丢失/磁盘脱机读取风险，不能替代应用级权限控制。

相关文件：

- `docs/platform/DOUYIN_PUBLISH_HASHTAG_TIMEOUT_BUG.md`
- `src/platform_adapter/browser_session.py`
- `src/platform_adapter/publish_workflow.py`
- `src/services/auto_publish_service.py`

### 2026-04-29：双角色素材与 SadTalker 方案讨论

主要目标：评估两张角色 PNG、对话脚本、双角色语音和本地数字人合成路线。

保留结论：

- 角色 A/B 最好分别处理，避免双人同框图直接进入生成链路导致互相干扰。
- 透明 PNG 或纯色背景素材更适合后续抠图、叠加、循环合成。
- 双角色对话需要明确角色人格、声线、台词切分和最终合成策略。

相关文件：

- `docs/reference/SADTALKER_VIDEO_PLAN.md`
- `docs/GPT_SOVITS_QUICKSTART.md`

### 2026-05-01：双角色视频根因报告

主要目标：根据 `DUAL_CHARACTER_VIDEO_STATUS.md` 排查业务逻辑和视频异常。

保留结论：

- `role_b.png` 素材不适合 SadTalker 3D 人脸关键点流程，是角色 B 失败的重要原因。
- 当 A/B 两段视频顺序 `concat` 时，最终时长应按 `audio_a_dur + audio_b_dur`，不能用 `max(A, B)`。
- 静态角色图进入视频合成时，需要支持 PNG/JPG/WebP/BMP 并处理背景色/透明层。

相关文件：

- `src/content_factory/video_composer.py`
- `docs/archive/video-debug/DUAL_CHARACTER_VIDEO_ROOT_CAUSE_REPORT.md`

### 2026-05-09：视频异常分析

主要目标：分析项目生成的视频异常、画面错位、角色变形等问题。

保留结论：

- SadTalker 输出通常是 256x256 头像视频，直接拉伸到 1728x2304 全身角色层会导致头部放大、身体缺失或透明层异常。
- 多轮排查发现部分异常不是最终合成才出现，而是中间合成层已经错位。
- 需要保留中间帧和 `ffprobe` 信息，避免只看最终 mp4 猜原因。

相关文件：

- `docs/archive/video-debug/VIDEO_ABNORMAL_ANALYSIS_2026-05-09.md`
- `docs/archive/video-debug/VIDEO_ABNORMAL_ANALYSIS_ROUND2_2026-05-09.md`

### 2026-05-10：轻微动效、微动作和文档整理

主要目标：寻找“人物轻微动一下”的低风险方案，比较方案 2/3/4，并整理文档。

保留结论：

- 当前更适合先做轻微动效：眨眼、呼吸、轻微摆动、循环 PNG 序列，而不是强行全自动复杂视频生成。
- 方案 2（2D 分层 + 微动作库）可控性最高，适合作为当前项目内路线。
- FramePack/SadTalker/ComfyUI 可作为素材生成或增强路线，但不应直接覆盖当前主线。
- 文档需要区分 `current`、`reference`、`archived_do_not_use_as_current`，避免历史方案误导后续模型。

相关文件：

- `src/content_factory/video_composer.py`
- `docs/CHARACTER_MOTION_OPTIONS_2026-05-10.md`
- `docs/IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md`
- `docs/DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md`
- `docs/archive/video-debug/MICRO_MOTION_ABNORMAL_ANALYSIS_2026-05-10.md`
- `docs/DUAL_V12_EYE_POSITION_FIX_PLAN_2026-05-10.md`

### 2026-05-12：FramePack、RTX 50 系和 ComfyUI 背景

主要目标：确认 FramePack 在 RTX 50 系显卡上的 PyTorch/CUDA 兼容性，并生成可用于项目的背景视频。

保留结论：

- 旧 `torch 2.6/cu126` 组合可能不兼容 RTX 50 系 Blackwell 显卡，需要匹配支持 `sm_120` 的 PyTorch/CUDA 版本。
- FramePack_oneclick 可启动 WebUI，但生成失败时应先看 CUDA/PyTorch 兼容性，不要只调 prompt。
- ComfyUI 可作为背景素材生成工具，已验证能输出 1080x1920、30fps、H.264 的绿色/治愈系循环背景视频。
- 背景视频可放入 `data/videos/` 并作为后续角色叠加背景。

相关文件和产物：

- `tools/comfyui_green_background/`
- `docs/comfyui_green_background_implemented.md`
- `docs/comfyui_flux_sdxl_local_background_plan.md`
- `data/videos/bg_comfy_green_loop.mp4`
- `data/videos/bg_comfy_green_loop_motion.mp4`

### 2026-05-13：当前能力总览、关联项目、后台登录与公网访问

主要目标：总结当前项目能实现什么，整理视频能力和关联项目，并补充后台登录、验证码、公网访问。

保留结论：

- 当前项目最稳定能力是“关键词/文本 -> RAG/脚本 -> TTS -> BGM -> 模板视频合成 -> 抖音发布 -> 同步/评论/自动回复”。
- 双角色、微动作 PNG、FramePack 已有代码和样片，但仍是半自动/实验链路，尚未接入 `auto-publish` 默认模式。
- 抖音发布后应以 `pending_review` 记录等待审核/同步，不应因为作品页短时间查不到就标记失败。
- Streamlit 后台增加登录和角色权限后，可以通过 Cloudflared 临时开放给外部访问，但仅适合作临时协作。
- 邮箱 SMTP 授权码属于敏感信息，只能放本地 `.env`，不能写入文档或提交。

相关文件：

- `docs/CURRENT_CAPABILITIES.md`
- `docs/RELATED_PROJECTS_INTEGRATION.md`
- `docs/ACCOUNT_LOGIN_AND_USAGE_PLAN.md`
- `docs/CLOUDFLARED_PUBLIC_ACCESS.md`
- `src/web/app.py`
- `src/services/user_profile_service.py`
- `src/shared/config.py`
- `.env.example`

### 2026-05-14 至 2026-05-17：Presenter 工作流、文档、Git 分支合并

主要目标：评估 `docs/PRESENTRER_VIDEO_PLAN.md`，实现动漫数字人主讲视频 MVP，整理文档，提交并合并分支。

保留结论：

- Presenter 路线落地为独立模块，不直接污染旧 `video_composer.py` 主线。
- Edge-TTS 可作为快速默认通路，GPT-SoVITS 作为本地声线/克隆路线继续保留。
- Presenter 流程包括脚本分段、背景解析、字幕/文本叠加、Sonic 角色层和 FFmpeg 合成。
- 代码和文档已提交到 `codex-presenter-mvp` 并合并回 `master`。
- 合并时注意区分代码/文档和本地 ChromaDB、素材、浏览器状态等未提交数据。

相关文件：

- `src/content_factory/presenter/`
- `src/content_factory/presenter_pipeline.py`
- `docs/ANIME_DIGITAL_HUMAN_PLAN.md`
- `docs/PRESENTER_VIDEO_MODIFICATION_PLAN.md`
- `docs/PRESENTRER_VIDEO_PLAN.md`
- `docs/VOICE_CLONING_EDGE_TO_GPT_SOVITS.md`
- `README.md`
- `main.py`
- `requirements.txt`

## 不导入的内容

以下内容存在于原始会话中，但不应进入项目主线文档：

- 邮箱 SMTP 授权码、账号验证码、真实登录态。
- Cloudflared 临时公网域名。
- 长篇原始 shell 输出、模型下载日志、浏览器 DOM 日志。
- 已过期的端口、PID、一次性测试 URL。
- 原始聊天中的口语化讨论和重复中断信息。

## 后续使用建议

- 新模型接手项目时，先读 `README.md`、`docs/CURRENT_CAPABILITIES.md`、`docs/USER_GUIDE.md`，再读本文件。
- 涉及视频异常时，优先查 `docs/archive/video-debug/`，不要重复走 SadTalker 拉伸全身角色的旧坑。
- 涉及 FramePack 时，按 `docs/FRAMEPACK_INTEGRATION_PLAN.md` 的半自动后处理路线理解，不要假设已有稳定 CLI/API。
- 涉及公网访问或邮箱登录时，先检查 `.env.example` 和本地 `.env`，不要把真实授权码写回文档。
