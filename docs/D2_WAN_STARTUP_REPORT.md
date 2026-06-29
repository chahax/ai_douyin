---
doc_status: report
doc_category: development
date: 2026-06-28
topic: D2 Wan 2.2 i2v Workflow 启动环境排查
---

# D2 Wan 2.2 Workflow — 启动环境排查报告

## 一、背景

V5 小说→纯视频 Pipeline 的 D2 阶段目标是**用 Wan 2.2 i2v 模型生成首末帧锚定的 5s 视频片段**。

原始计划：使用 ComfyUI + [kijai/ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper) 自定义节点，通过 HTTP API 提交 workflow。

本机环境：
- OS: Windows 10 Pro
- GPU: NVIDIA GeForce RTX 5070 Ti (16 GB VRAM)
- Python: **3.14.3**（关键）
- ComfyUI: 0.18.1（自装 venv，`D:/IT/AI_vido/ComfyUI/.venv`）
- Wan 2.2 模型：全部就位（diffusion 9.4G + vae 1.4G + LoRA 27M + text_encoder 6.3G）

## 二、操作记录

### 2.1 ComfyUI 启动 — comfy_aimdo stub

**现象**：ComfyUI 启动时报 `ModuleNotFoundError: No module named 'comfy_aimdo'`

**原因**：`comfy_aimdo` 是 ComfyUI 的可选 AMD GPU 优化模块。项目用的是 NVIDIA GPU，不需要这个包。但 ComfyUI `main.py` 和 `comfy/windows.py` 硬编码了 `import comfy_aimdo.control`。

**操作**：在 ComfyUI venv site-packages 下创建 `comfy_aimdo` stub 包（5 个文件），提供空实现：
```python
# comfy_aimdo/control.py
def init(): pass
def init_device(gpu_idx=0): return False
```

**结果**：ComfyUI 启动成功，HTTP 8190 可访问。

### 2.2 ComfyUI 启动 — insightface + facexlib 缺失

**现象**：`PuLID_ComfyUI` 节点导入失败

**原因**：`pulid.py` 依赖 `insightface` 和 `facexlib`，ComfyUI 自带 venv 未安装。

**操作**：`pip install insightface onnxruntime`（facexlib 版本与 Python 3.14 不兼容，暂未解决）

**结果**：PuLID 节点导入失败（不影响 D2 Wan workflow，留到 D3 处理）

### 2.3 WanVideoWrapper 导入失败 — Python 3.14 相对 import 问题

**现象**：ComfyUI 启动日志显示 `(IMPORT FAILED): ComfyUI-WanVideoWrapper`

**原因**：这是本次排查的核心发现。Python 3.14 废除了 `exec()` 中的相对 import 支持。WanVideoWrapper 有 **200+ 个 `from .xxx import`** 语句分布在 30+ 个文件中。ComfyUI 自定义节点加载机制使用 `exec_module` 方式加载，因此全部相对 import 在 Python 3.14 下不可用。

**尝试的修复路径**（均失败）：
1. ✗ 批量 `sed` 把所有 `from .xxx` 改为 `from xxx`（无前缀）— 但 ComfyUI 主目录有同名 `utils/` 包冲突
2. ✗ 重命名 `utils.py → _wan_utils.py` 避免冲突 — 子目录（taehv、controlnet、fantasyportrait 等）各自仍有跨目录的 `from ..` 引用
3. ✗ 自定义 `importlib.abc.MetaPathFinder` + `Loader` 做 Python 3.14 兼容 hook — 语法错误 + 编码问题 + 子模块递归失败
4. ✗ 用 `sys.meta_path.insert(0, ...)` 注入 hook — 在 ComfyUI 加载时序中 hook 未被正确调用

**实际观察**：ComfyUI 0.18.1 **内置**了 Wan 节点（`comfy_extras/nodes_wan.py`），这些节点已注册为 `WanFirstLastFrameToVideo`、`WanImageToVideo` 等 **27 个节点**，但内置节点**不支持** WanVideoWrapper 的专有功能（4 步加速 LoRA + 首尾帧锚定 + `WanVideoImageToVideoEncode` + `WanVideoSampler`）。

### 2.4 WanVideoWrapper 重装 — 恢复原始代码

**操作**：删除已修改的 `ComfyUI-WanVideoWrapper/`，`git clone` 重新拉取最新代码。

**结果**：恢复到未修改状态。import 问题依旧存在（Python 3.14 兼容性根因）。

## 三、现状总结

| 组件 | 状态 | 说明 |
|---|---|---|
| ComfyUI HTTP Server | ✅ 运行中（port 8190） | Python 3.14 |
| 内置 Wan 节点 | ✅ 27 个节点已注册 | 含 `WanImageToVideo`、`WanFirstLastFrameToVideo` |
| **WanVideoWrapper 完整功能** | ❌ 不可用 | Python 3.14 exec() 不支持相对 import |
| PuLID 节点 | ❌ 不可用 | 依赖 `facexlib`，D3 处理 |
| ComfyUI_Sonic | ❌ 不可用 | 不影响 V5（V5 不需要 Sonic） |
| Wan 2.2 模型权重 | ✅ 全套就位 | 9.4G + 1.4G + 27M + 6.3G |
| Workflow JSON | ✅ 已写 | `assets/workflows/wan22_i2v_4step.json` |
| D2 测试脚本 | ✅ 已写 | `scripts/_d2_test_wan_i2v.py` |

## 四、阻塞点

**Python 3.14 的 `exec()` 不支持相对 import 导致 WanVideoWrapper 无法加载。**

影响：
- D2 Wan 2.2 workflow **无法使用 WanVideoWrapper 专有节点**（4 步 LoRA、首尾帧锚定）
- 内置节点可用但推理时长 ~20-30 步/段（~10 分钟 vs ~1 分钟）

## 五、建议方案

给 ComfyUI 换个 Python 版本启动，**建议 Python 3.10**（已装在 `C:/Python310/python.exe`）。

理由：
1. Python 3.10 支持 `exec()` 中的相对 import，WanVideoWrapper 可直接使用
2. 与 SadTalker_v2（未来 V5-2 阶段需要，也需 Python 3.10）共享同一个 Python
3. 换版本成本 ~10 分钟（新建 venv 或直接指定 `python.exe` 路径）

**操作**：
```bash
# 用 Python 3.10 给 ComfyUI 新建 venv
C:/Python310/python.exe -m venv D:/IT/AI_vido/ComfyUI/.venv_py310
D:/IT/AI_vido/ComfyUI/.venv_py310/Scripts/pip.exe install -r D:/IT/AI_vido/ComfyUI/requirements.txt
# 重装 WanVideoWrapper + PuLID 依赖
# 用新 venv 启动 ComfyUI
```

**成本 vs 收益**：10 分钟换 Wan 2.2 推理从 10 分钟降到 1 分钟（4 步 LoRA 加速）。
