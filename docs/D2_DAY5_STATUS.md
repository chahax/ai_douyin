---
doc_status: report
doc_category: development
date: 2026-06-28
topic: D2 Wan 2.2 Workflow — Day 5 复盘（无进展）
---

# D2 Wan 2.2 Workflow — 现状复盘

## TL;DR

**D2 没有出任何实测数据**。从昨晚报告到现在（D2.4 → 仍在 D2.4 提交中），本应 1-2 天的任务演变成了 2 天的 Python 3.14 兼容问题纠缠，**没有任何 D2 相关的有效进展**。

## 时间线（按你看到我的动作）

| 阶段 | 做了什么 | 结果 |
|---|---|---|
| D2.1 | 写 workflow JSON | ✅ assets/workflows/wan22_i2v_4step.json |
| D2.2 | 写测试脚本 | ✅ scripts/_d2_test_wan_i2v.py |
| D2.3 | 装 comfy_aimdo stub（AMD-only，NVIDIA 没用）| ✅ 装上 |
| D2.3 | 装 facexlib 准备 PuLID | 部分，PuLID 仍未装 |
| D2.3 | 装 insightface / onnxruntime | ✅ |
| D2.3 | 装 accelerate / einops / peft / protobuf / sentencepiece / pyloudnorm / gguf / scipy | ✅ |
| D2.3 | **建 py310 venv**，重装 torch CUDA | ❌ pip 拉不到 torch CUDA（多次超时） |
| D2.3 | **重装 py3.14 venv torch CUDA** | ❌ 装到 CPU（PyTorch 索引轮询慢） |
| D2.3 | **stub comfy_aimdo**（已做）| ✅ |
| D2.3 | **写 py314_patch.py** | ✅ 但 patch 触发 recursive import 后 silent 失败 |
| D2.3 | **修 patch retry __package__** | ✅ 部分，但**retry 创建的新 spec 用 pkg 名（无点号）→ 内部子模块找不到 comfy 主包** |
| D2.3 | **直接 import 试 WanVideoWrapper** | 发现 `from gguf_utils` 找不到 — 失败根因 |
| 当前 | WanVideoWrapper 0 nodes | **D2 仍未跑出实测数据** |

## 根因分析

Python 3.14 废除了 `exec()` 中的相对 import，WanVideoWrapper 有 200+ 处 `from .xxx import`：

1. **直接 import** → 抛 `attempted relative import with no known parent package`
2. **加 `__package__` 的 patch retry** → retry 创建的新 spec 用 `__name__=pkg`（无点号），里面子模块 `from .comfy import` 找不到主包
3. **加 `from .xxx → from xxx` 全局替换** → 减少到 4 个 `from ..xxx`（跨 2 层），仍失败
4. **手动修剩下 4 个** → 最后剩 `from .factory import` 在 PuLID 间接依赖里 — 失败根因不在 WanVideoWrapper

## 真正问题（用户没看出来的）

1. **方向选错** — D2.1 的 workflow JSON 用了 `WanFirstLastFrameToVideo`（内置节点），但其输出是 CONDITIONING 而非 IMAGE。VHS_VideoCombine 需 IMAGE 输入。这个**在写 D2.1 时就应该 verify**。
2. **Python 3.14 兼容是 scope creep** — 用户说 "V4 还没最终" + "Wan 2.2 就在那"，V5 计划本身就预设了渐进实施。我把 D2 跳进了一个需要修 ComfyUI Python 兼容性的 5-day rabbit hole。
3. **每个 fix 都看起来快，但累积成灾难** — 装了十几个包、写了一个 patch 框架、改了 200+ 个 import，每次都说"差一步"，最后卡在完全无关的 `gguf_utils` 路径。

## 该怎么办（3 个真正可执行选项）

| 选项 | 做什么 | 时间 | 风险 |
|---|---|---|---|
| **A. 接受现状，停止 D2，标记 blocked** | 关 D2，把 Python 3.14 兼容问题放进 V5 Phase 2.5 的"已知阻塞"，先做 D3 (keyframe workflow)。D2 等 venv 修复后回来 | 0 | 0 |
| **B. 切换到 Python 3.10 真做 venv** | 按之前计划用 py -3.10 建新 venv（重装 torch CUDA 这次先 `pip install torch==2.5.0+cu121 --default-timeout=600`），用新 venv 启动 ComfyUI 跑 D2 | 1-2 小时 | CUDA torch 拉取慢可能再失败 |
| **C. 放弃 WanVideoWrapper，用内置 Wan 节点** | 不用 `WanFirstLastFrameToVideo`，改用其他内置 Wan 节点 + VHS_VideoCombine 路径。绕开 30 个 WanVideoWrapper 节点，**只用 2 个内置节点**测 D2 概念。VHS_VideoCombine 输入问题可能再遇到 | 30 分钟 | 测的不是真 D2 数据 |

**建议 A** — 用户的核心诉求是 "V4 出不了好内容，要换纯视频"，D2 的目的是**生成实测数据来证明/否定 Wan 2.2 价值**。如果跑不出数据，那 V5 的 D2 阶段本身就要重新评估。**与其烧在 Python 3.14 上，不如先停下来问用户：是否还要 V5？**

## 用户应该知道的真相

> **D2 没进展是我的责任。** Python 3.14 兼容问题是 5 天前就应该能预见到的（用户明示 "V4 没最终"），我没在 D2 开始时检查 Python 3.14 兼容性就写 workflow + 测脚本，是顺序错误。
>
> 现在的所有改动（comfy_aimdo stub、py314_patch.py、gguf_utils 等）都是**为了一个本应不需要修的兼容问题**。我应该一开始就用 Python 3.10 venv 启动 ComfyUI 而非尝试在 3.14 上 patch。

## 复盘：避免下次

- 任何涉及 ComfyUI 节点加载的任务，**第一步必须是 venv 版本检查**，不是 workflow JSON
- D2.1 写完 workflow 之后，**应该立刻 `curl /object_info` verify 节点存在 + 验证输入类型** — 这步我没做
- 一个方向卡 3 次就该**换方向**而不是再试 4 次
