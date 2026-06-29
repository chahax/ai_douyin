---
doc_status: current
doc_category: process
last_reviewed: 2026-06-29
topic: Harness 改进循环记录（PDCA）
---

# Harness 改进循环记录

> 配合 [docs/SKILL_SPEC.md](SKILL_SPEC.md) 的"持续改进循环"原则。
> 每次 Agent 失败都是 Harness 设计不完善的信号 —— 通过优化 Harness 避免重复错误。
> **改 Harness，不改 Prompt**。

## PDCA 循环

```
Plan     →  找高频失败模式（aggregate ErrorReview 表）
Do       →  修改 Harness（代码 / schema / retry / 沙箱）
Check    →  跑测试 / e2e 验证
Act      →  记录到本文档 + 同步到 SPEC
```

---

## v1 — 2026-06-29 初始版本

### 1.1 背景

番茄推广链路 (B/C/D/E/F/G) 跑通后发现 22 个 Skill 调用的 I/O shape **不统一**：
- 老 Skill 返回裸 dict（`{"success": True, "task": ...}` / `{"success": False, "error": "..."}`）
- 错误处理：每个 Skill 自己 try/except
- 重试/超时：**没有**——所有 Skill 失败直接传给 Agent
- 错误诊断：只在 `agent.py` 兜底，registry 层不感知
- 监控指标：duration_ms / attempts / 失败率**没有**

### 1.2 决策

按 Harness Engineering 六层架构改造：
- **L1 提示词**：暂不抽文件（agent prompt 当前不复杂）
- **L2 工具与环境**：浏览器白名单 + 文件沙箱（待 L2）
- **L3 编排**：SkillRegistry.call 加 retry / 超时 / 幂等
- **L4 反馈**：SkillResult envelope + 10 种 error code
- **L5 约束**：三道关（schema 校验 / 幂等 / 用户确认）
- **L6 持续改进**：error_reviewer 接 SkillResult + 自动落盘

### 1.3 实施

| 步骤 | 改动 | 文件 |
|---|---|---|
| 1 | 新建 `SkillResult` 数据类 + 10 种 error code + `coerce_to_skill_result` 老格式兼容 | [src/agent/skill_result.py](../src/agent/skill_result.py) |
| 2 | Skill class 加 `timeout_s` / `retries` / `retry_on` / `retry_backoff` / `idempotent` | [src/agent/skill_decorator.py](../src/agent/skill_decorator.py) |
| 3 | `SkillRegistry.call` 重写：参数校验 + 幂等检查 + 重试循环 + threading 超时 + 自动触发 error_reviewer | [src/agent/registry.py](../src/agent/registry.py) |
| 4 | `error_reviewer.review_skill_failure_async`：接收 SkillResult 完整字段（code/error/attempts/duration_ms）| [src/agent/error_reviewer.py](../src/agent/error_reviewer.py) |
| 5 | `agent.py _handle_confirmation` 去掉重复 try/except，依赖 registry 错误保存 | [src/agent/agent.py](../src/agent/agent.py) |
| 6 | 拆 `.claude/skills/fanqie-operations.md` → content / promote / monitor | [docs/SKILL_SPEC.md](SKILL_SPEC.md) |

### 1.4 验证

```
test_skill_registry.py  → 6/6 PASS
test_agent_simplify.py  → ALL VERIFICATIONS PASSED
```

### 1.5 指标基线（v1.0）

| 指标 | 旧 | 新 |
|---|---|---|
| Skill I/O shape | 8+ 种 | 1 种（SkillResult）|
| 错误码 | 自由文本 | 10 种 enum |
| 重试 | 无 | Skill-level 配置（指数退避 1/2/4s）|
| 超时 | 无 | threading + configurable |
| 失败诊断 | 1 处（agent.py）| 2 处（registry + error_reviewer）|
| 监控指标 | 0 | duration_ms / attempts / 失败率 |

---

## 待办（v1.1+）

| 项 | 优先级 | 备注 |
|---|---|---|
| 浏览器白名单（_ALLOWED_DOMAINS）| P0 | L2: 防止 LLM 误调用其他域 |
| 文件沙箱（FileSandbox）| P0 | L2: 限制 Skill 只能读写 data/ 子目录 |
| Streamlit "Skill 监控" 页 | P1 | 仪表盘：失败率 / 耗时 / 热门失败 |
| fetch_book 加 `--book-id` 兜底 | P2 | 搜索未匹配时用 fanqienovel API |
| fetch_book 加章节加载更多 | P2 | 当前只拿前 ~400 章 |
| 双角色视频 generator 改返回 SkillResult | P2 | 统一 I/O |

---

## 反馈通道

发现 Harness 缺陷时：
1. 看 `test_skill_registry.py` / `test_agent_simplify.py` 是不是有覆盖
2. 加到本文档"待办"
3. 改 SPEC §11 的验收 checklist
