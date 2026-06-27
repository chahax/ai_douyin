---
doc_status: completed
doc_category: design
last_reviewed: 2026-06-27
parent_doc: docs/IMPROVEMENT_ROADMAP.md
implements: I-1
estimated_effort: 0.5d
completion_status: PR-1 完成（2026-06-27）；PR-2/PR-3 待办
---

> 文档状态：PR-1 已实施并验收（2026-06-27）。原估算 16 处 A 类，实际完成 20 处（见 §四 修订记录）。PR-2/PR-3 仍待办。

# I-1 · 日志风格统一 — 设计文档

## 一、目标与边界

**目标**：消除 `src/` 下非 CLI 输出场景的 `print(...)`，统一走 `src.shared.logger`（基于 loguru）。

**不在范围内**：
- `main.py` 中作为 CLI 入口输出 JSON 数据的 `print(json.dumps(...))` 保留 — 是给外部脚本/管道消费的，不是日志。
- 单元测试里的 `print(...)` 保留 — 失败时调试用。
- `if __name__ == "__main__":` 顶层入口里给操作者看的进度行（如 `[抽帧] xxx -> yyy`）保留 — 属于 CLI UX 而非日志。
- `print()` 出现在 `src/` 下其他场景 → **本设计文档范围内**。

## 二、现状盘点（2026-06-27 修订）

按 `print(` 在 `src/` 下命中 67 处，按语义分五类：

| 类别 | 数量 | 代表位置 | 处理 |
|---|---|---|---|
| **A. 错误日志** | **20**（原估 16） | [background_resolver.py:779,789,795,805,809,821,824,826,829,908,919](src/content_factory/presenter/background_resolver.py#L779)（11 处）；[video_composer.py:29,33,36](src/content_factory/video_composer.py#L29) `_run_ffmpeg` 失败（3 处）；[video_composer.py:200,407,580](src/content_factory/video_composer.py#L200) `compose_*` 合成失败（3 处）；[framepack_pipeline.py:38,42,45](src/content_factory/framepack_pipeline.py#L38) `run_ffmpeg` 失败（3 处） | **替换为 logger.error/warning** ✅ PR-1 已完成 |
| **B. 诊断/进度** | ~25 | [framepack_pipeline.py:81-336](src/content_factory/framepack_pipeline.py) 进度行、[video_composer.py:154-578](src/content_factory/video_composer.py) 成功/时长行、[micro_motion.py:175-342](src/content_factory/micro_motion.py) | **顶层 CLI 入口保留；库函数入口替换为 logger.info/debug** — 待 PR-2 |
| **C. CLI 输出（JSON/纯文本结果）** | ~7 | [dialogue_generator.py:263](src/content_factory/dialogue_generator.py#L263)、[wisdom_extractor.py:64](src/content_factory/wisdom_extractor.py#L64)、[script_generator.py:166](src/content_factory/script_generator.py#L166)、[gpt_sovits_provider.py:200](src/content_factory/tts_providers/gpt_sovits_provider.py#L200) | **保留 print（语义是输出）** |
| **D. 单次启动/初始化通知** | ~3 | [database.py:280](src/services/database.py#L280) `数据库已初始化: ...` | **替换为 logger.info** — 待 PR-2 |
| **E. 演示/测试** | ~6 | [wisdom_retriever.py:105-106](src/rag_engine/wisdom_retriever.py#L105)、[book_processor.py:122-125](src/content_factory/book_processor.py#L122)、[tests/test_content_pipeline.py](src/tests/test_content_pipeline.py) | **保留（顶层演示脚本）** |

### 修订记录

- **2026-06-27**：将 `video_composer.py` 中 3 处 `print("[VideoComposer] 合成失败")` 从 B 类改归 A 类。理由：这 3 行位于 `if _run_ffmpeg(cmd): ... else: print("...")` 的 else 分支，**仅在 FFmpeg 失败时触发**，不是诊断进度。原文档把它们归为 B 类是基于"成功路径里也被打印了"的错误判断；实际跑通后确认成功路径走的是 if 分支的 `print(f"完成: ...")`，不互斥。A 类总数从 16 上调至 20。

## 三、转换规则

### 3.1 错误日志（A 类）— **强约束必须改**

```python
# ❌ Before
print(f"[ComfyUI] 启动失败: {e}")

# ✅ After
logger.error(f"ComfyUI 启动失败: {e}")
```

```python
# ❌ Before
print(f"[FFmpeg Error]\n{result.stderr[-1000:]}")

# ✅ After
logger.error(f"FFmpeg 失败:\n{result.stderr[-1000:]}")
```

**判定标准**：打印内容是失败信息、异常堆栈、关键资源缺失 → logger.error。
**例外**：如果调用者没有可写的 logger sink（例如某些 CLI 工具的 stderr 替代场景），保留 print(..., file=sys.stderr)。

### 3.2 诊断/进度（B 类）— **按上下文决定**

**库函数内被其它模块调用** → logger：
```python
# video_composer.py 里的 _run_ffmpeg（被其它模块 import）
def _run_ffmpeg(cmd: list, timeout: int = 600) -> bool:
    """执行 ffmpeg 命令，返回是否成功"""
    try:
        ...
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg 命令执行超时")   # ← 替换
```

**CLI 顶层入口**（`if __name__ == "__main__":`） → 保留 print（UX）：
```python
# framepack_pipeline.py 底部（被作为 `python -m ...` 直接调用）
if __name__ == "__main__":
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()
    print(f"[抽帧] {video_path} -> {frames_dir}")  # ← 保留：操作者看的进度
    ...
```

**判定标准**：函数是 public 还是 module-private？被外部模块 import 调用 → logger；只在 `__main__` 块直接执行 → print。

### 3.3 输出（C 类）— **保留 print**

判断依据：**这一行是程序的产物**，而不是程序的"心跳"。

```python
# dialogue_generator.py:263 — 这是脚本生成的结果，调用方要拿来用
print(json.dumps(result, indent=2, ensure_ascii=False))  # ← 保留
```

**不要**为了"统一风格"把它换成 logger — logger 输出是给人看的诊断，不是结构化数据通道。

### 3.4 初始化通知（D 类）— **替换为 logger.info**

```python
# ❌ Before
print(f"数据库已初始化: {DB_PATH}")

# ✅ After
logger.info(f"数据库已初始化: {DB_PATH}")
```

理由：这类消息频率低且对调试无用，统一收归日志通道便于 `LOG_LEVEL=DEBUG` 时过滤。

### 3.5 演示/测试（E 类）— **保留**

保留是为不破坏现有调试体验。

## 四、落地步骤

### Step 1：建立禁用清单（PR-1，半天） — ✅ **2026-06-27 完成**

在 `src/content_factory/presenter/background_resolver.py`、`src/content_factory/video_composer.py`、`src/content_factory/framepack_pipeline.py` 三个**错误日志集中地**完成 A 类替换。

**原计划**：约 16 处。
**实际**：20 处（PR-1.1 补改 3 处 `合成失败`，修正了原文档的 B/A 误分类）。

改动分布：
| 文件 | A 类改动 | log level |
|---|---|---|
| `background_resolver.py` | 11 处 | 7 × logger.info、1 × logger.warning、3 × logger.error |
| `video_composer.py` `_run_ffmpeg` | 3 处 | logger.error |
| `video_composer.py` `compose_*` 合成失败 | 3 处 | logger.error（带 final_path 参数） |
| `framepack_pipeline.py` `run_ffmpeg` | 3 处 | logger.error |
| **合计** | **20 处** | |

### Step 2：CLI UX 与库代码的边界标记（PR-2）— ⏳ 待办

在每个文件的 `if __name__ == "__main__":` 块**顶部**加一行注释：
```python
# === CLI entry: 保留 print 作为操作者 UX ===
```

便于后续 review 时一眼区分意图。

同步处理 B 类库函数 print 收敛（`framepack_pipeline.py` / `video_composer.py` 进度行、`micro_motion.py` 调试行），以及 D 类（`database.py` 初始化通知）。

### Step 3：CI 自动化校验（PR-3）— ⏳ 待办

在 [scripts/pre_push_check.py](scripts/pre_push_check.py) 新增一条规则：
- 在 `src/` 下 grep `print\(`，排除：
  - `if __name__ == "__main__":` 块内的行
  - `print(json.dumps(` / `print\(.*=.*\)` 这种 CLI 输出
  - `src/tests/` 路径
- 剩余命中数 > 0 → 检查失败。

## 五、验收

### 自动化 — ✅ PR-1 验收通过

```bash
# 1. A 类错误日志归零（在 3 个目标文件范围内）
$ grep -nE "print\(.*Error|print\(.*失败|print\(.*超时|print\(.*\[FFmpeg\]|print\(.*\[ComfyUI\]" \
    src/content_factory/presenter/background_resolver.py \
    src/content_factory/video_composer.py \
    src/content_factory/framepack_pipeline.py 2>&1
# 实际输出：(空)  ✅ 期望 0

# 2. 三个文件 import 验证
$ python -c "import src.content_factory.presenter.background_resolver; import src.content_factory.video_composer; import src.content_factory.framepack_pipeline"
# OK ✅

# 3. 三个文件 ast.parse 语法检查
$ python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in [
    'src/content_factory/presenter/background_resolver.py',
    'src/content_factory/video_composer.py',
    'src/content_factory/framepack_pipeline.py',
]]"
# OK ✅
```

### 实际触发 logger.error 验证 — ✅ 通过

通过 monkeypatch `_run_ffmpeg` 强制返回 False，模拟真实 FFmpeg 失败：

```
2026-06-27 15:09:18 | ERROR | src.content_factory.video_composer:compose_video:200 -
[VideoComposer] 合成失败: data/videos/_test_fail\forced_fail.mp4
```

错误日志**带文件名 + loguru 时间戳通道**，可被历史日志 grep / 时间筛选 / 模块聚合。

### 端到端视频合成验证 — ✅ 通过

成功路径下 `compose_video` 输出 4.01 秒 MP4（259 KB），失败/成功分支 print 互斥，logger 通道工作正常。

### 人工（PR-2 之后补做）

- 启动一次 Streamlit 后台，故意把 ComfyUI 配置改坏，验证日志文件里有 `ComfyUI 启动失败: ...` 字样（而非只在 stdout）。
- 跑一次完整 presenter pipeline，确认日志文件里有 `[抽帧] / [抠图] / [循环]` 等进度行（来自 logger.info）。

> **注**：以上两项人工验证需要 Streamlit 后台跑通才能写日志文件。PR-1 范围内未做（Streamlit 后台不属于 I-1），留到 I-1 收尾或 PR-2 时一起补。

## 六、不在本设计范围内

- loguru sink 配置（文件日志、滚动、远程）— 当前 stdout 单 sink 够用，后续如有需求单独立项。
- 结构化日志（JSON sink）— 当前阶段操作者直接读文本日志，结构化收益不大。
- 第三方库（如 APScheduler、SQLAlchemy）的日志接管 — loguru 默认会接管 stdlib logging，留作 I-4 治理时再处理。

## 七、相关文件

| 文件 | 改动类型 | 状态 |
|---|---|---|
| [src/content_factory/presenter/background_resolver.py](src/content_factory/presenter/background_resolver.py) | A 类（11 处） | ✅ 完成 |
| [src/content_factory/video_composer.py](src/content_factory/video_composer.py) | A 类 6 处（`_run_ffmpeg` 3 + `compose_*` 3） + B 类库函数（~15 处） | ✅ A 类完成 / B 类待 PR-2 |
| [src/content_factory/framepack_pipeline.py](src/content_factory/framepack_pipeline.py) | A 类 3 处（`run_ffmpeg`） + B 类库函数（约 10 处） | ✅ A 类完成 / B 类待 PR-2 |
| [src/content_factory/micro_motion.py](src/content_factory/micro_motion.py) | B 类库函数（约 5 处） | ⏳ PR-2 |
| [src/services/database.py](src/services/database.py) | D 类（1 处） | ⏳ PR-2 |
| [scripts/pre_push_check.py](scripts/pre_push_check.py) | 新增检查规则 | ⏳ PR-3 |