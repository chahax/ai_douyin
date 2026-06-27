---
doc_status: planning
doc_category: design
last_reviewed: 2026-06-26
parent_doc: docs/IMPROVEMENT_ROADMAP.md
implements: I-2
estimated_effort: 1–2d
---

> 文档状态：设计文档，待评审。配套实现 PR 完成后归档为 completed。

# I-2 · ComfyUI 容错设计文档

## 一、问题陈述

当前 ComfyUI 集成位于 [src/content_factory/presenter/background_resolver.py:721](src/content_factory/presenter/background_resolver.py#L721)，只用于动漫数字人视频的背景图生成。每次 presenter pipeline 触发时：

1. **失败原因全丢**：所有 `except Exception: return False`（L899）吞掉了真实错误。
2. **stderr 物理不可见**：ComfyUI 子进程 `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`（L814-815），**GPU OOM / 模型加载失败 / 工作流错误全部进黑洞**。
3. **无重试**：单次失败直接放弃，OOM 是 GPU 偶发问题，应该有机会退避重试。
4. **无降级显式化**：失败后 pipeline 不知情，可能传一个空路径给后续步骤导致更糟的崩溃；且没有任何信号告诉上层"这段视频是兜底出来的"。
5. **无失败记录**：失败次数、原因、显存状态无法事后分析，调优靠猜。

## 二、目标

**让 ComfyUI 单点失败不再悄无声息，并在可重试的失败上自动恢复；不可恢复时显式抛异常由 pipeline 决策。**

具体目标：

| ID | 目标 | 量化 |
|---|---|---|
| G1 | OOM 自动识别 | 检测延迟 < 30s |
| G2 | 失败自动重试 | 默认 3 次，指数退避，可由 `COMFYUI_MAX_RETRIES` 覆盖 |
| G3 | 重试前置显存探测 | 第 2 次重试前若显存仍 > 90%，长退避 15s |
| G4 | 显式降级信号 | 重试耗尽后抛 `ComfyBackgroundUnavailableError`，pipeline 拿到 `error_class` 做分支决策 |
| G5 | 失败可观测 | 每条失败原因写入 `comfy_task_failures` 表，含 OOM 关键字、stderr 摘要、显存快照 |
| G6 | 调用方改动 ≤ 5 行 | pipeline 用 try/except 包住一处调用，默认 `strict_background=False` 保持向后兼容 |

## 三、架构

```
presenter_pipeline.run()
    └─→ try:
            background_resolver.resolve_grouped_backgrounds()
                └─→ _create_comfy_background_with_retry()
                        ├─ attempt 1: 默认 preset
                        │   └─ ComfyOOMError → sample_gpu_memory() + 长退避
                        ├─ attempt 2: 降 steps
                        │   └─ ComfyOOMError → sample_gpu_memory() + 长退避
                        ├─ attempt 3: 降分辨率
                        │   └─ ComfyOOMError / Workflow / Timeout
                        ├─ 任何一次异常 → comfy_task_failures 表 + logger.error
                        └─ 重试耗尽 → 抛 ComfyBackgroundUnavailableError
    └─→ except ComfyBackgroundUnavailableError as exc:
            ├─ strict_background=True → 中止 pipeline
            └─ strict_background=False → backgrounds=[None]*len(scenes)，继续走 FFmpeg 单色兜底
```

## 四、关键设计

### 4.1 stderr 接管

**Before**：
```python
comfy_process = subprocess.Popen(
    [...],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
```

**After**：
```python
comfy_process = subprocess.Popen(
    [...],
    stdout=subprocess.PIPE,   # ← 改了
    stderr=subprocess.PIPE,   # ← 改了
    text=True,
    bufsize=1,                # 行缓冲
)
```

启动一个守护线程 `_drain_subprocess_stdio(process, log_buffer)`，把 stdout/stderr 同时：
1. 写入 `log_buffer`（deque(maxlen=200) 滚动保存）
2. 通过 logger.debug 转发（按 LOG_LEVEL 控制）

OOM 抛错时把 log_buffer 摘要（含最近 50 行 stderr）一并写入 `comfy_task_failures.stderr_tail`。

### 4.2 OOM 关键字列表

**核心关键字**（跨平台、跨 ComfyUI 版本稳定）：
```python
OOM_PATTERNS = (
    "CUDA out of memory",
    "OutOfMemoryError",
    "OutOfMemory",            # PyTorch 短名
    "torch.cuda.OutOfMemory",
    "CUDA_ERROR_OUT_OF_MEMORY",
)
```

**平台相关扩展**（按需追加，不要硬塞）：
- AMD ROCm：`HIP out of memory`, `hipMalloc`
- Apple MPS：`MPS backend out of memory`
- Intel XPU：`SYCL out of memory`

**配置化**：[src/shared/config.py](src/shared/config.py) 加：
```python
COMFYUI_OOM_PATTERNS: str = "CUDA out of memory,OutOfMemoryError,OutOfMemory"
```

`backgroud_resolver` 启动时按逗号切分，覆盖默认值。

### 4.3 重试与降级阶梯

```python
@dataclass
class ComfyAttempt:
    width: int = 768
    height: int = 1344
    batch_size: int = 1
    steps: int = 28      # settings.COMFYUI_STEPS 默认

RETRY_PRESETS = [
    ComfyAttempt(width=768,  height=1344, batch_size=1, steps=28),  # attempt 1: 默认
    ComfyAttempt(width=768,  height=1344, batch_size=1, steps=20),  # attempt 2: 降 steps
    ComfyAttempt(width=640,  height=1120, batch_size=1, steps=20),  # attempt 3: 降分辨率
]

MAX_RETRIES = int(os.getenv("COMFYUI_MAX_RETRIES", "3"))
```

每次抛 `ComfyOOMError` → 切下一个 preset + `tenacity.wait_exponential(multiplier=2, min=2, max=30)`。

**第 2 次进入 attempt 之前主动采样显存**（仅 OOM 触发路径上执行，正常重试不采样）：

```python
def _maybe_sample_gpu_before_retry(prev_error: ComfyOOMError) -> None:
    used, total = sample_gpu_memory()
    if used is None or total is None:
        return                                       # nvidia-smi 不在 PATH，静默
    ratio = used / total
    logger.warning(
        f"GPU 显存占用 {used}/{total} MB ({ratio:.0%})，"
        f"仍占满通常意味着别的进程未释放，重试可能再次 OOM"
    )
    if ratio > 0.9:
        # 长退避：给别的进程释放时间
        time.sleep(15)
```

非 OOM 错误（工作流 JSON 错、模型不存在）**不重试**，直接抛 `ComfyWorkflowError`。

### 4.4 兜底：抛异常 + pipeline 决策

**不生成静态背景**。所有重试耗尽后抛 `ComfyBackgroundUnavailableError`，由 pipeline 显式决策。

**新增异常类型**（[src/content_factory/presenter/exceptions.py](src/content_factory/presenter/exceptions.py) 新增）：

```python
class ComfyBackgroundError(Exception):
    """所有 ComfyUI 背景生成失败的基类。"""
    error_class: str = "UNKNOWN"          # OOM / WORKFLOW / HTTP / TIMEOUT / UNAVAILABLE
    attempts: int = 0
    last_stderr_tail: str = ""

class ComfyOOMError(ComfyBackgroundError):
    error_class = "OOM"

class ComfyWorkflowError(ComfyBackgroundError):
    error_class = "WORKFLOW"

class ComfyTimeoutError(ComfyBackgroundError):
    error_class = "TIMEOUT"

class ComfyBackgroundUnavailableError(ComfyBackgroundError):
    """所有重试 + 降级均失败后抛出。pipeline 拿到此异常做最后决策。"""
    error_class = "UNAVAILABLE"
```

**调用方改动**（[src/content_factory/presenter_pipeline.py](src/content_factory/presenter_pipeline.py) 共 5 行）：

```python
# Before — 现版只接受 bool 失败
backgrounds = self._bg_resolver.resolve_grouped_backgrounds(
    requested="", scenes=scenes, work_dir=work_dir,
    character=request.character,
    use_comfy=request.use_comfy_background,
)

# After — 显式异常分支
try:
    backgrounds = self._bg_resolver.resolve_grouped_backgrounds(
        requested="", scenes=scenes, work_dir=work_dir,
        character=request.character,
        use_comfy=request.use_comfy_background,
    )
except ComfyBackgroundUnavailableError as exc:
    # 决策点 1：中止整段视频
    if request.strict_background:                   # 新增 dataclass 字段，默认 False
        logger.error(f"严格背景模式：中止 pipeline，{exc.attempts} 次尝试均失败")
        return PresenterResult(success=False, error=str(exc), error_class=exc.error_class)
    # 决策点 2：跳过背景（用透明背景合成，单色 fallback 由 FFmpeg 在 video_composer 层兜底）
    logger.warning(f"ComfyUI 不可用，跳过背景生成（{exc.attempts} 次尝试失败）")
    backgrounds = [None] * len(scenes)
```

**关键不变量**：
- `PresenterResult` 新增 `error_class` 字段，调用方（CLI / Streamlit / Agent Skill）可基于此判断重试策略。
- 现有"忽略失败继续跑"的默认行为通过 `strict_background=False` 保留，向后兼容。
- Streamlit 任务调度页看到 `error_class=UNAVAILABLE` 时给出明确提示，不静默吞掉。

### 4.5 失败持久化 schema

新增 alembic 迁移 `0006_comfy_task_failures.py`：

```python
op.create_table(
    "comfy_task_failures",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("task_name", sa.String(64)),       # e.g. "presenter_bg_xxx"
    sa.Column("prompt_id", sa.String(64), nullable=True),  # ComfyUI prompt_id
    sa.Column("attempt_no", sa.Integer()),        # 第几次重试
    sa.Column("error_class", sa.String(32)),      # OOM / WORKFLOW / HTTP / TIMEOUT
    sa.Column("stderr_tail", sa.Text()),          # 最近 50 行 stderr
    sa.Column("width", sa.Integer()),
    sa.Column("height", sa.Integer()),
    sa.Column("batch_size", sa.Integer()),
    sa.Column("steps", sa.Integer()),
    sa.Column("gpu_mem_used_mb", sa.Integer(), nullable=True),  # 调用时 nvidia-smi 采样
    sa.Column("gpu_mem_total_mb", sa.Integer(), nullable=True),
    sa.Column("duration_ms", sa.Integer()),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
)
```

模型：[src/content_factory/models.py](src/content_factory/models.py) 新增 `ComfyTaskFailure`。

Streamlit 调度页加一个新 tab："ComfyUI 失败记录"，按时间倒序展示。

### 4.6 GPU 显存采样

失败瞬间用 `nvidia-smi --query-gpu=memory.used,memory.total --format=csv` 采样（Windows 通过 `subprocess.run` 调用）：

```python
def sample_gpu_memory() -> tuple[int | None, int | None]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None, None
        used, total = out.stdout.strip().split(",")
        return int(used), int(total)
    except Exception:
        return None, None
```

`nvidia-smi` 不在 PATH 时静默返回 (None, None)，不阻塞主流程。

## 五、API 兼容性

**外部调用接口签名不变**，但内部会抛异常而非返回 bool/False。

```python
# presenter_pipeline.py 调用方代码改动 ≤ 5 行（try/except 一处）
try:
    backgrounds = self._bg_resolver.resolve_grouped_backgrounds(
        requested="", scenes=scenes, work_dir=work_dir,
        character=request.character,
        use_comfy=request.use_comfy_background,
    )
except ComfyBackgroundUnavailableError as exc:
    ...
```

**内部数据结构变化**（`background_resolver` 返回值）：

```python
@dataclass
class ComfyBackgroundResult:
    success: bool
    error_class: str = ""       # OOM / WORKFLOW / HTTP / TIMEOUT / UNAVAILABLE
    error_message: str = ""
    attempts: int = 0
```

`ComfyBackgroundResult` 是内部类型，**仅在 `_create_comfy_background` 内部各层之间流转**，从 `resolve_grouped_backgrounds` 入口开始一律改为抛异常。这意味着 `background_resolver` 模块有**两套 API 风格**：
- 旧接口（`resolve_background` 单图）→ 保留 `bool` 返回（向后兼容，给低层 helper 用）
- 新接口（`resolve_grouped_backgrounds` 批量）→ 抛异常

**`PresenterRequest` 新增字段**：

```python
@dataclass
class PresenterRequest:
    ...
    strict_background: bool = False   # 默认 False，向后兼容；True 时 ComfyUI 不可用直接中止 pipeline
```

**`PresenterResult` 新增字段**：

```python
@dataclass
class PresenterResult:
    success: bool
    ...
    error_class: str = ""       # "" 表示无错；UNAVAILABLE 表示 ComfyUI 不可用但 pipeline 走 None 背景完成
```

调用方（CLI / Streamlit / Agent Skill）可通过 `error_class` 字段判断是否需要人工介入或重新调度。

## 六、测试方案

### 6.1 单元测试

[src/tests/unit/test_comfy_resilience.py](src/tests/unit/test_comfy_resilience.py) 新增：

1. **test_oom_pattern_detection**：传入各种 stderr 字符串，验证 OOM 匹配。
2. **test_retry_escalation**：mock `_submit_to_comfy` 抛 OOM 三次，验证第三次抛 `ComfyBackgroundUnavailableError` 而非静默兜底。
3. **test_gpu_sample_before_retry**：mock `nvidia-smi` 返回 95% 占用，验证第二次重试前 sleep 15s。
4. **test_max_retries_env_override**：设置 `COMFYUI_MAX_RETRIES=2`，验证只跑两次。
5. **test_workflow_error_no_retry**：mock 抛 `ComfyWorkflowError`（非 OOM），验证**不重试**直接抛 `ComfyBackgroundUnavailableError`。
6. **test_failure_recorded**：mock 失败，验证 `comfy_task_failures` 表有正确记录（含 `error_class`）。
7. **test_strict_background_aborts**：设 `request.strict_background=True`，验证 `ComfyBackgroundUnavailableError` 时返回 `PresenterResult(success=False)` 而非走 None 背景继续。
8. **test_default_keeps_running**：设 `request.strict_background=False`（默认），验证异常被吞、pipeline 用 None 背景继续、`PresenterResult.error_class='UNAVAILABLE'`。

### 6.2 手工验收

- 跑一次 presenter pipeline，故意把 `COMFYUI_CHECKPOINT` 改成一个不存在的文件名 → 应抛 `ComfyWorkflowError`，无 ComfyUI 输出图，pipeline 走 None 背景完成（或严格模式下中止）。
- 跑一次 pipeline，把 `COMFYUI_PORT` 改成 9999（无服务） → 应 60s 启动超时后抛 `ComfyBackgroundUnavailableError`。
- 设 `COMFYUI_MAX_RETRIES=1` 重跑，确认最多一次尝试。
- (进阶) 在真 GPU 上跑一个超分辨率工作流触发 OOM → 验证阶梯降级到 attempt 3，最终抛异常；`comfy_task_failures` 表能看到三次尝试记录。

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| stderr PIPE 满导致 ComfyUI 阻塞 | 中 | 高 | 守护线程必须立即 drain，不能缓存 |
| OOM 关键字漏匹配 → 不重试 | 中 | 中 | 配置化关键字；首次实跑后用真实 OOM 样本回灌测试 |
| `strict_background=False` 默认值让用户察觉不到降级 | 中 | 中 | `PresenterResult.error_class='UNAVAILABLE'` 必填，Streamlit 调度页加显式提示 banner |
| 多 GPU 节点上 nvidia-smi 返回多行 | 低 | 低 | 取第一行（CUDA_VISIBLE_DEVICES 已隔离当前进程可见的 GPU） |
| 重试期间 presenter 状态不一致 | 低 | 中 | 重试是同步阻塞在 `_create_comfy_background` 内，pipeline 状态机不会被打断 |
| nvidia-smi 不在 PATH（Windows 常见） | 中 | 低 | `sample_gpu_memory` 返回 (None, None) 静默跳过，不阻塞重试 |

## 八、不在本设计范围

- WebSocket 监听 ComfyUI 进度 → 当前是 `/history/{pid}` 轮询，足够；WebSocket 改造单独立项。
- 多 ComfyUI 实例并行 → 当前单 GPU 单 ComfyUI 进程，需求未出现。
- ComfyUI 服务自身健康监控（独立守护）→ I-5 视频队列时一并做。
- 自动 fallback 视觉背景（FFmpeg / 预渲染库）→ 本期**不做**，由 pipeline 拿 `None` 背景继续或中止决策；后续如发现 `strict_background=False` 路径下视频质量不可接受，再单独评估补一个 fallback 资产库（独立设计 doc）。

## 九、落地步骤

| 步骤 | 改动 | 验证 |
|---|---|---|
| 1 | `background_resolver.py` 改 PIPE + 守护线程 | 启动 ComfyUI 后日志有 ComfyUI 输出 |
| 2 | 新增 `src/content_factory/presenter/exceptions.py`（4 个异常类） | 单测覆盖 |
| 3 | 新增 `OOMDetector` + `ComfyAttempt` preset + `sample_gpu_memory` | 单测覆盖 |
| 4 | `_create_comfy_background_with_retry` 串 retry + 第 2 次前显存探测 + 异常分类 | 模拟 OOM 三次验证抛 `ComfyBackgroundUnavailableError` |
| 5 | alembic `0006_comfy_task_failures.py` + 模型 | `alembic upgrade head && downgrade base` 双向通过 |
| 6 | `PresenterRequest.strict_background` 字段 + `PresenterResult.error_class` 字段 | 现有调用方 default false 不破坏 |
| 7 | `presenter_pipeline.py` 改 5 行 try/except | pipeline 跑通，失败时优雅降级 |
| 8 | Streamlit 新增"ComfyUI 失败记录" tab + `error_class=UNAVAILABLE` banner | 看到真实失败记录 |
| 9 | 单测文件（8 个 case 覆盖） | `pytest -q` 全绿 |

## 十、相关文件

| 文件 | 改动 |
|---|---|
| [src/content_factory/presenter/background_resolver.py](src/content_factory/presenter/background_resolver.py) | PIPE、retry、显存探测、异常分类 |
| [src/content_factory/presenter/exceptions.py](src/content_factory/presenter/exceptions.py) | **新增**（4 个异常类） |
| [src/content_factory/presenter/models.py](src/content_factory/presenter/models.py) | `PresenterRequest.strict_background`、`PresenterResult.error_class` |
| [src/content_factory/presenter_pipeline.py](src/content_factory/presenter_pipeline.py) | 改 ~5 行 try/except |
| [src/content_factory/models.py](src/content_factory/models.py) | 新增 `ComfyTaskFailure` |
| [src/shared/config.py](src/shared/config.py) | 新增 `COMFYUI_OOM_PATTERNS`、`COMFYUI_MAX_RETRIES` |
| [alembic/versions/0006_comfy_task_failures.py](alembic/versions/) | **新增** |
| [src/tests/unit/test_comfy_resilience.py](src/tests/unit/) | **新增**（8 个 case） |
| [src/web/pages/comfy_failures.py](src/web/pages/)（如已存在则编辑） | 新增失败记录 tab + UNAVAILABLE banner |