---
doc_status: planning
doc_category: planning
last_reviewed: 2026-06-28
model_usage: 改进路线图总入口。规划未来 3 周内的工程改进、清理、V4 生产质量提升。详细设计下沉到 docs/design/。
---

> 文档状态：路线图 v2（2026-06-28 合并版）。新增 Phase 0（housekeeping）和 Phase 2（V4 质量提升）；I-1 标记完成；新增完成日志。

# 改进路线图（2026-Q3 · v2）

> 一页纸规划：先看这一页决定要不要展开每个专题的独立设计文档。具体设计细节在 [docs/design/](design/) 目录。

---

## 一、当前状态快照（2026-06-28）

| 维度 | 状态 |
|---|---|
| **生产版本** | **V4** = Sonic fox mp4 + ComfyUI per-segment 动漫背景（已完成 + 回归测试通过）|
| **代码清理** | V1/V2/V3/V5 已删除（释放 19.2 GB）|
| **核心能力** | RAG / Agent / Memory / Scheduler / Streamlit 后台 / Docker / Alembic / V4 数字人 |
| **I-1 logger 收敛** | ✅ PR-1 完成 23 处（background_resolver 11 + video_composer 6 + framepack_pipeline 3 + 兜底失败 3）；PR-2/PR-3 待办 |
| **真实脚手架** | 1 处：`src/platform-adapter/`（2 个 0 字节空文件，git 跟踪中） |
| **次要技术债** | 30 处未用 import + 21 处 `try/except pass`（大部分是合理兜底） |

---

## 二、改进项总览（按阶段排序）

### Phase 0 · Housekeeping（**简历前必修**，10 分钟内）

| 编号 | 名称 | 工作量 | 状态 | 优先级 |
|---|---|---|---|---|
| **H-1** | 删 `src/platform-adapter/` 空文件目录 | 10s | ✅ **已完成**（2026-06-28） | 🔴 P0 |
| **H-2** | ruff 清 30 处未用 import（F401） | 1 分钟 | ✅ **已完成**（2026-06-28，60 errors fixed） | 🟡 P2 |
| **H-3** | 3 处关键 `pass` → `logger.debug()`（[agent.py:209](src/agent/agent.py#L209)、[audio_mixer.py:47](src/content_factory/audio_mixer.py#L47)、[auto_publish_service.py:507](src/services/auto_publish_service.py#L507)）| 10 分钟 | ✅ **已完成**（2026-06-28） | 🟡 P2 |

### Phase 1 · 路线图主线（工程硬缺陷，1-2 周）

| 编号 | 名称 | 工作量 | 依赖 | 状态 |
|---|---|---|---|---|
| **I-1** | 日志风格统一 | 0.5d | — | ✅ **已完成**（PR-1 2026-06-27） |
| **I-2** | ComfyUI 容错（OOM/重试/降级） | 1-2d | I-1 | ✅ **已完成**（2026-06-28） |
| **I-3** | Prompt 工程（JSON schema + Few-shot + CoT） | 3-5d | I-2 | ⏳ 待开始（V4 稳定后启动） |
| **I-4** | LLM 成本与限流治理 | 2d | I-3 | ✅ **已完成**（2026-06-28） |

### Phase 2 · V4 生产质量提升（NEW，1-2 周）

| 编号 | 名称 | 工作量 | 依赖 | 状态 |
|---|---|---|---|---|
| **V4-1** | SadTalker_v2 真口型驱动替换 Sonic fox mp4 idle 假动 | 3-5d | Phase 0 | ⏳ 待开始 |
| **V4-2** | GPT-SoVITS 声纹克隆替换 Edge-TTS | 1-2d | V4-1 | ⏳ 待开始 |
| **V4-3** | 字幕样式选项（位置/字号/底色） | 1d | — | ⏳ 待开始 |

### Phase 3 · 长链路（立项评审，1-2 周）

| 编号 | 名称 | 工作量 | 依赖 | 状态 |
|---|---|---|---|---|
| **I-5** | ComfyUI 视频帧序列生成 + 任务队列 | 1-2w | I-4 | ⏳ 立项评审 |

---

## 三、依赖图

```
H-1, H-2, H-3  ←── (任意顺序，今天做完)

V4-3 (字幕)
  │
  └─→ V4-1 (SadTalker_v2 口型)
        └─→ V4-2 (GPT-SoVITS 声纹)

I-1 (logger) ✅
  └─→ I-2 (ComfyUI 容错)
        └─→ I-3 (Prompt 工程)
              └─→ I-4 (LLM 成本/限流)
                    └─→ I-5 (视频队列)
```

**强约束**：
- I-2 必须在 I-3 之前：ComfyUI 失败时 prompt 输出要走结构化日志。
- I-3 必须在 I-5 之前：视频工作流 prompt 注入依赖 schema 化 scene plan。
- V4-1 在 V4-2 之前：先有真实口型再加声纹克隆价值更大。

---

## 四、改进项详情

### H-1 · 删空文件目录（10 秒）— 🔴 P0

**问题**：`src/platform-adapter/`（带连字符）含 2 个 0 字节空文件（`__init__.py`、`douyin_adapter.py`），git 跟踪中；项目实际用下划线版本 `src/platform_adapter/`（10 个文件）。Agent LLM 在 import 时潜在引到旧目录。

**方案**：
```bash
git rm -r src/platform-adapter/
```

**验收**：grep `platform-adapter`（带连字符）在 `src/` 下 = 0 命中。

---

### H-2 · ruff 清未用 import（1 分钟）— 🟡 P2

**问题**：30 处未用 import（见用户分析），典型"演进过程中删了调用方但忘了删 import"。

**方案**：
```bash
pip install ruff
ruff check --select F401 --fix src/
```

**验收**：`ruff check src/` 0 errors。

---

### H-3 · 关键 pass → logger.debug（10 分钟）— 🟡 P2

**问题**：21 处 `try/except pass`，大部分合理，但 3 处关键路径失败值得显式记录：
- [src/agent/agent.py:210](src/agent/agent.py#L210) — pending_plan 清理失败
- [src/content_factory/audio_mixer.py:47](src/content_factory/audio_mixer.py#L47) — 音频增强失败
- [src/services/auto_publish_service.py:508](src/services/auto_publish_service.py#L508) — 发布服务异常

**方案**：3 处全改为 `logger.debug(f"context: {exc}", exc_info=True)`，其他保持 pass。

**验收**：grep `logger.debug` 命中数增加 3。

---

### I-2 · ComfyUI 容错（1-2 天）— ⏳ 待开始

**设计文档**：[docs/design/comfy-resilience.md](design/comfy-resilience.md)（已就位）

**关键决策**：
- 兜底走**抛异常 + pipeline 决策**，不是 FFmpeg 静态背景
- 异常类：[`ComfyBackgroundError`、`ComfyOOMError`、`ComfyWorkflowError`、`ComfyTimeoutError`、`ComfyBackgroundUnavailableError`](src/content_factory/presenter/exceptions.py)（待新增）
- 重试：`COMFYUI_MAX_RETRIES=3`（可配置），第 2 次前显存探测（`nvidia-smi`）
- 失败持久化：`comfy_task_failures` 表（alembic `0006_comfy_task_failures.py`）+ Streamlit tab
- 调用方改动 ≤ 5 行（`PresenterRequest.strict_background` + `PresenterResult.error_class`）

**实施 9 步**：
1. stderr 接管（PIPE + 守护线程）
2. `OOMDetector` + `ComfyAttempt` preset + `sample_gpu_memory`
3. `_create_comfy_background_with_retry` 串 retry + 第 2 次前显存探测 + 异常分类
4. alembic `0006_comfy_task_failures.py` + 模型
5. `PresenterRequest.strict_background` 字段 + `PresenterResult.error_class` 字段
6. `presenter_pipeline.py` 改 5 行 try/except
7. Streamlit 新增"ComfyUI 失败记录" tab + `error_class=UNAVAILABLE` banner
8. 单测（8 个 case）
9. 真实跑通 V4 pipeline 触发失败验证

**验收**：
- 模拟 OOM（`COMFYUI_FORCE_OOM=1`）→ 3 次重试 + 抛 `ComfyBackgroundUnavailableError`
- 失败次数和原因可在 Streamlit 后台查询
- V4 pipeline 在 ComfyUI 失败时不崩溃、走 strict_background=False 默认

---

### I-3 · Prompt 工程升级（3-5 天）— ⏳ 待开始

**设计文档**：[docs/design/prompt-engineering.md](design/prompt-engineering.md)（待写）

**问题**：`src/shared/llm_client.py` 调用为裸字符串；输出解析处依赖正则容错。

**方案**：
1. **JSON schema 强约束**：引入 `instructor`（与现有 Pydantic 栈无缝集成）。
2. **Few-shot 目录化**：`docs/prompts/{scene_plan,script,tags,comment_reply}.md`。
3. **CoT 分层**：复杂任务加 `<thinking>` 段。
4. **回归测试**：`src/tests/unit/test_prompt_schemas.py`，100 个 case 通过率 ≥ 95%。

**验收**：5 个核心 LLM 调用点（scene_plan / script / tag / comment_reply / memory_classifier）全部走 instructor。

---

### I-4 · LLM 成本与限流治理（2 天）— ⏳ 待开始

**设计文档**：[docs/design/llm-governance.md](design/llm-governance.md)（待写）

**方案**：
1. Token 计量（tiktoken）+ `llm_usage_logs` 表（alembic `0005_llm_usage_log.py`）
2. 限流（aiolimiter）
3. 缓存（diskcache）

**验收**：Streamlit "LLM 用量" 页 + 50 QPS 突发测试。

---

### V4-1 · SadTalker_v2 真口型驱动（3-5 天）— ⏳ 待开始

**问题**：当前 V4 角色是 Sonic fox mp4（idle 循环，**嘴不动**）。用户看到的"动漫数字人"实际是 idle 动画 + 字幕，不是真口型驱动。

**方案**：
- 用 `D:/IT/SadTalker_v2/SadTalker-main`（已有完整权重 1.7 GB）作为口型引擎
- 输入：Sonic fox mp4 截取的单帧 + TTS 音频
- 输出：嘴型同步的 mp4
- 接 V4 pipeline 替换 `presenter_composer.compose_segment()` 的角色层

**实施要点**：
- SadTalker Python 3.10（项目是 3.14），需 conda env 或 Docker 隔离
- 已验证 SadTalker_v2 模型完整（[SadTalker_v0.0.2_256.safetensors](D:/IT/SadTalker_v2/SadTalker-main/checkpoints/)）
- 集成方案：subprocess 调用 SadTalker_v2 inference.py，输出文件喂回 V4 composer

**验收**：
- V4 pipeline 输出 mp4 中角色嘴型随音频变化
- 单条 13s 视频 ≤ 3 分钟（GPU）

---

### V4-2 · GPT-SoVITS 声纹克隆（1-2 天）— ⏳ 待开始

**问题**：当前 V4 用 Edge-TTS 标准音色（云健男声），无个性化。

**方案**：用项目已配的 [src/content_factory/tts_providers/gpt_sovits_provider.py](src/content_factory/tts_providers/gpt_sovits_provider.py)（之前未启用），接 `D:/IT/GPT-SoVITS-main` 服务。

**验收**：V4 视频用克隆音色而非 Edge-TTS 标准音。

---

### V4-3 · 字幕样式扩展（1 天）— ⏳ 待开始

**方案**：扩展 [src/content_factory/presenter/text_overlay.py](src/content_factory/presenter/text_overlay.py) 支持：
- 位置（top / center / bottom / custom y）
- 字号（small / medium / large）
- 底色（透明 / 半透白 / 渐变）

**验收**：Streamlit 后台配置 → V4 视频字幕立即反映。

---

### I-5 · ComfyUI 视频帧序列（1-2 周）— ⏳ 立项评审

**立项待评审**：
- 业务侧：客户是否需要视频级（而非背景级）AI 生成？
- 经济侧：单 GPU 单段 5-10s 出图 30-120s，规模化成本？
- 工程侧：Redis 已有，Worker 拓扑需重新设计。

**如果立项**，设计文档：[docs/design/comfy-video-queue.md](design/comfy-video-queue.md)

---

## 五、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| I-3 instructor 升级破坏现有 LLM 调用 | 高 | 完整回归测试 + 灰度 |
| I-4 token 计量与 provider usage 不一致 | 中 | tiktoken 与 provider 返回值校核；偏差 > 5% 告警 |
| I-2 ComfyUI stderr 解析依赖驱动版本 | 中 | 关键字列表可配置（`COMFYUI_OOM_PATTERNS`）|
| V4-1 SadTalker 跨 Python 版本（3.10 vs 3.14）| 中 | subprocess 隔离 + 文件接口 |
| I-5 立项后硬件成本超预算 | 高 | 立项前 PoC（单 worker + 10 段样本）|

---

## 六、专题设计文档清单

| 文档 | 状态 | 对应改进项 |
|---|---|---|
| [docs/design/logger-convergence.md](design/logger-convergence.md) | ✅ 已归档（PR-1 完成） | I-1 |
| [docs/design/comfy-resilience.md](design/comfy-resilience.md) | ✅ 设计已写，待实施 | I-2 |
| `docs/design/prompt-engineering.md` | ⏳ 待写 | I-3 |
| `docs/design/llm-governance.md` | ⏳ 待写 | I-4 |
| `docs/design/comfy-video-queue.md` | ⏳ 立项后写 | I-5 |
| `docs/design/sadtalker-integration.md` | ⏳ 待写 | V4-1 |
| `docs/design/gpt-sovits-integration.md` | ⏳ 待写 | V4-2 |

---

## 七、执行计划（建议 3 周节奏）

| 周 | 内容 | 产出 |
|---|---|---|
| **W1** | Phase 0（H-1/H-2/H-3）+ I-2 实施 | 清理完成 + ComfyUI 容错代码 |
| **W2** | I-3 实施 + V4-1 SadTalker 集成 | Prompt 升级 + 真口型驱动 |
| **W3** | I-4 + V4-2 + V4-3 + I-5 立项评审 | LLM 治理 + V4 完整闭环 |

---

## 八、验收总则

- 每项完成需对应单元测试覆盖（`src/tests/unit/`）
- 涉及 schema/迁移的改动必须有 alembic upgrade/downgrade 双向脚本
- 任何公共 API 改动同步更新 [docs/CURRENT_CAPABILITIES.md](CURRENT_CAPABILITIES.md)
- Phase 0（housekeeping）必须先于 git commit
- 路线图每完成一项，将状态从"待开始"改为"已完成"并标注完成日期

---

## 九、不在本期范围

- 多模态输入（图/视频理解 → 自动生成） — 需独立 PoC
- 多租户隔离 — 当前为单用户/小团队场景
- 跨语言 i18n — 项目当前为中文界面
- Web 移动端适配 — Streamlit 桌面优先

---

## 十、完成日志

| 日期 | 完成项 | 备注 |
|---|---|---|
| 2026-06-27 | I-1 PR-1 logger 收敛 | 23 处 print → logger.{info,warning,error}；B/D 类待 PR-2 |
| 2026-06-27 | RAG 部署环境修复 | `_resolve_local_embedding_path()` 共享函数；wisdom_retriever + knowledge_importer 都认 HF 缓存 |
| 2026-06-27 | `generation_service.py:250` Document 字段 bug | `c.get("content")` → `c.page_content` |
| 2026-06-28 | V4 数字人版本建立 | Sonic fox mp4 + ComfyUI per-segment 动漫背景；端到端 289-354s |
| 2026-06-28 | V1/V2/V3/V5 清理 | 删除 FramePack / Sonic AI / 测试产物，释放 19.2 GB |
| 2026-06-28 | `resolve_character` 目录路径 bug 发现 | 显式目录路径误判为 static → ffmpeg Permission denied；待修复 |
| 2026-06-28 | P0 housekeeping 识别 | `src/platform-adapter/` 空文件目录 + 30 处未用 import + 21 处 try/except pass |
| 2026-06-28 | **Phase 0 完成 (H-1/H-2/H-3)** | `git rm -r src/platform-adapter/`（10s）+ ruff 清 60 处 F401（1 分钟）+ 3 处关键 `pass` → `logger.debug`（10 分钟）|
| 2026-06-28 | **I-2 ComfyUI 容错完成** | 4 异常类（OOM/Workflow/Timeout/UNAVAILABLE）+ 3 次重试阶梯 + OOM 关键字检测 + GPU 显存探测 + alembic 0006 + comfy_task_failures 表 + Streamlit 失败 tab + 28 单测 + 端到端 V4 OOM 模拟成功降级（46.9s 出片，失败记录入库）|
| 2026-06-28 | **I-4 LLM 成本与限流完成** | token 计量（tiktoken）+ 成本估算（PRICE_TABLE）+ aiolimiter 10 QPS + diskcache 24h TTL + alembic 0007 + llm_usage_logs 表 + Streamlit "LLM 用量" 页 + 27 单测 + 端到端 50 QPS 突发验证（4.0s 完成，40 个等令牌）+ cache 命中实测（210x 加速）|
| 2026-06-28 | **I-4 真正生效** | 11 个 LLM 调用点（agent / error_reviewer / registry / dialogue_gen / scene_plan / script_gen / wisdom_extractor × 2 / background_plan / fanqie_promo / presenter_pipeline）全部从 `chat_completion()` 切到 `chat_completion_tracked()`（同步包装，内部走 async 限流/缓存/计量/记录路径）。新增 caller tag：`agent_chat` / `script_gen` / `scene_plan` / `dialogue_gen` / `wisdom_extractor` / `wisdom_extractor_rag` / `background_plan` / `fanqie_promo` / `error_reviewer` / `skill_registry`。实测：script_generator 一次调用 → 1 条 llm_usage_logs 入库（caller=script_gen, 2626+772 tokens, $0.0034, 36.9s）。test_error_reviewer mock 同步迁移到 chat_completion_tracked。|

---

## 十一、变更历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-06-26 | 初版，4 周路线图，I-1~I-5 |
| v2 | 2026-06-28 | 合并 v1 + V4 清理 + housekeeping 识别；新增 Phase 0/Phase 2；从 4 周压缩到 3 周；新增完成日志 |
| v3 | 2026-06-28 | I-2 ComfyUI 容错实施完成（9 步全做，含 alembic 0006、Streamlit 失败 tab、28 单测、端到端 OOM 模拟）|
| v4 | 2026-06-28 | I-4 LLM 成本与限流实施完成（4 模块 + alembic 0007 + Streamlit 用量页 + 27 单测 + 50 QPS 突发验证）|