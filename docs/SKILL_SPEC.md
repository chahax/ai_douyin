---
doc_status: design
doc_category: architecture
last_reviewed: 2026-06-29
topic: Skill 规范 — Harness Engineering 六层架构下的 Agent 工业化
references:
  - https://javaguide.cn
  - 知乎 Harness Engineering 系列
  - 菜鸟教程 Agent 工程化
---

# Skill 规范 — Harness Engineering 视角

> **核心命题**：`Agent = LLM + Harness`。Harness 是除模型本身外，支撑 Agent 完成生产任务的全部基础设施与工程体系（系统提示词、工具调用、文件系统、沙箱、编排、反馈、约束）。
>
> 我们的项目（番茄推广 / 抖音运营）按 Harness Engineering 的**六层架构**组织代码与流程，让 LLM 输出**稳定、可预期**。

## 0. 总体框架

### 0.1 为什么需要 Harness

| 痛点 | Harness 解法 |
|---|---|
| LLM 输出不稳定（同样输入不同输出） | 强 schema 约束 + SkillResult envelope |
| 长周期任务状态混乱 | 持久化（task.json / meta.json / ProblemMemory） |
| 错误重复出现 | 异常落盘 + LLM 自动诊断 + Harness 改进 |
| 写操作越权 | 二次确认 + 沙箱（只允许 fanqie 数据目录） |
| 不可观测 | duration_ms / attempts / 失败率指标 |

### 0.2 六层架构映射

```
┌────────────────────────────────────────────────────────────┐
│  Layer 6: 持续改进循环                                       │
│  ProblemMemory 汇总 + LLM 错误诊断 + Harness 迭代            │
├────────────────────────────────────────────────────────────┤
│  Layer 5: 约束与安全机制                                     │
│  参数 schema 校验 + requires_confirmation + 沙箱隔离         │
├────────────────────────────────────────────────────────────┤
│  Layer 4: 反馈与监控                                         │
│  SkillResult envelope + error code + duration/attempts 指标  │
├────────────────────────────────────────────────────────────┤
│  Layer 3: 编排与工作流控制                                   │
│  SkillRegistry.call + retry/timeout + 任务拆分 + 验证回路    │
├────────────────────────────────────────────────────────────┤
│  Layer 2: 工具与执行环境                                     │
│  Skill 抽象 + 浏览器自动化 (BrowserSession) + 文件系统       │
├────────────────────────────────────────────────────────────┤
│  Layer 1: 提示词与上下文管理                                 │
│  system prompt + 分层记忆 + 上下文窗口管理                   │
└────────────────────────────────────────────────────────────┘
```

下面每节按"现状 → 改造 → 实施"组织。

---

## Layer 1: 提示词与上下文管理

### 1.1 现状
- `src/agent/agent.py` 用 `_chat_impl` 拼 system prompt（无版本控制）
- 上下文来自 `MemoryManager`（preference / problem / discarded / normal）
- 长期记忆：`user_profiles` / `conversation_sessions` / `conversation_messages` / `user_memory` / `problem_memory` / `conversation_memory`

### 1.2 设计目标
- system prompt 走**文件**（`src/agent/prompts/*.md`），支持版本控制
- 长上下文：滑动窗口 + RAG 检索 + 分层摘要

### 1.3 实施
- 把 `agent.py` 的 system prompt 抽出到 `src/agent/prompts/system.md`
- 加 `prompt_loader.py`：按 `prompt_name` 加载并支持 `{{var}}` 模板替换
- `MemoryManager` 已有，按 4 层（preference / problem / discarded / normal）继续用
- 加 `ContextWindowManager`：自动截断 + 摘要长对话

---

## Layer 2: 工具与执行环境

### 2.1 现状
- **Skill 抽象**（`src/agent/registry.py` + `skill_decorator.py`）：22 个 Skill，参数 schema 完整
- **浏览器自动化**（`src/platform_adapter/browser_session.py`）：Playwright 包装，支持 goto / click / evaluate / screenshot
- **文件系统**：直接读写 `data/fanqie_promotion/`

### 2.2 设计目标
- Skill 抽象稳定 → LLM 看到的是统一 shape
- 浏览器动作有"白名单"——只允许 fanqie / douyin 域
- 文件系统沙箱——写操作只允许 `data/fanqie_promotion/`

### 2.3 实施

#### 2.3.1 Skill 抽象（统一 shape 见 Layer 4）

#### 2.3.2 浏览器沙箱
```python
# 在 BrowserSession 加白名单
class BrowserSession:
    _ALLOWED_DOMAINS = [
        "kol.fanqieopen.com",  # 番茄达人中心
        "fanqienovel.com",     # 番茄小说
        "creator.douyin.com",  # 抖音创作者
        "www.douyin.com",      # 抖音主站
    ]
    
    def open_page(self, url: str) -> "Page":
        from urllib.parse import urlparse
        host = urlparse(url).hostname
        if not any(host.endswith(d) for d in self._ALLOWED_DOMAINS):
            raise PermissionError(f"浏览器沙箱：禁止访问 {host}")
        return self._open_internal(url)
```

#### 2.3.3 文件沙箱
```python
# src/agent/filesystem_sandbox.py

class FileSandbox:
    """只允许读写 data/ 子目录。"""
    ALLOWED_ROOTS = [
        "data/fanqie_promotion/",   # 番茄推广数据
        "data/videos/",             # 视频输出
        "data/asset_collections/",  # 资产
    ]
    
    @classmethod
    def safe_path(cls, path: str) -> Path:
        p = Path(path).resolve()
        for root in cls.ALLOWED_ROOTS:
            try:
                p.relative_to(Path(root).resolve())
                return p
            except ValueError:
                continue
        raise PermissionError(f"文件沙箱：禁止访问 {p}")
```

---

## Layer 3: 编排与工作流控制

### 3.1 现状
- `SkillRegistry.call(name, kwargs)` 直接执行（**无 retry / 无 timeout**）
- `agent.py` 调 Skill 时自己 try/except（重复逻辑）
- 长任务：APScheduler 异步跑（已有 `src/scheduler/`）

### 3.2 设计目标
- **SkillRegistry.call 加重试 + 超时 + 任务拆分 + 验证回路**
- LLM 看不到 try/except——由 Harness 兜底

### 3.3 实施

#### 3.3.1 Skill class 新字段（已在 `skill_decorator.py`）

```python
@dataclass
class Skill:
    name: str
    description: str
    func: Callable
    params: list[SkillParam] = field(default_factory=list)
    requires_confirmation: bool = True
    category: str = "general"
    examples: list[str] = field(default_factory=list)
    
    # NEW — Harness Engineering 编排
    timeout_s: float = 300.0
    retries: int = 0
    retry_on: tuple[str, ...] = ("timeout", "rate_limited")
    retry_backoff: str = "exponential"   # "exponential" | "fixed"
    idempotent: bool = False            # 是否幂等（apply 前查 list 避免重复）
```

#### 3.3.2 SkillRegistry.call 重构

```python
def call(self, name: str, kwargs: dict) -> dict:
    skill = self.get(name)
    if not skill:
        return SkillResult.err("not_found", f"未知 Skill: {name}").to_dict()
    
    # 1) 幂等性检查
    if skill.idempotent:
        self._check_idempotent(name, kwargs)
    
    # 2) 参数校验
    is_valid, err, code = validate_params(skill, kwargs)
    if not is_valid:
        return SkillResult.err("validation_error", err).to_dict()
    
    # 3) 重试循环
    attempts = max(1, skill.retries + 1)
    last_result: SkillResult | None = None
    for attempt in range(attempts):
        start = time.time()
        try:
            raw = self._invoke_skill(skill, kwargs)
        except TimeoutError:
            last_result = SkillResult.err("timeout", f"Skill {name} 超时 (>{skill.timeout_s}s)")
        except Exception as exc:
            last_result = SkillResult.err("skill_error", f"{type(exc).__name__}: {exc}"[:300],
                                          error={"type": type(exc).__name__, "retryable": False})
        else:
            duration = int((time.time() - start) * 1000)
            result = self._coerce_to_skill_result(name, raw)
            result.skill = name
            result.duration_ms = duration
            result.attempts = attempt + 1
            return result.to_dict()
        
        # 失败：决定是否重试
        if attempt < attempts - 1 and last_result and last_result.code in skill.retry_on:
            time.sleep(self._backoff(attempt, skill.retry_backoff))
            continue
        break
    
    # 4) 失败终态
    if last_result:
        if skill.retries and last_result.code in skill.retry_on:
            last_result.code = "max_retries_exceeded"
        last_result.attempts = attempts
        self._save_to_problem_memory(name, kwargs, last_result)
    return last_result.to_dict()
```

#### 3.3.3 任务拆分（workflow）

番茄推广工作流（已有 `docs/FANQIE_PROMOTION_WORKFLOW.md`）：
```text
B 申请推广别名 → C 抓内容 → D 出视频 → E 上传抖音 → F 别名审核 → G 回填视频 URL
```

每个环节 = 1 个 Skill（或几个相关 Skill 的组合）。**失败传播规则**：
- Layer 4 失败 → 状态机标记（pending_review / alias_taken / failed）
- Layer 6 失败 → 写入 ProblemMemory，下次重试时由 LLM 给出修复建议

---

## Layer 4: 反馈与监控

### 4.1 现状
- 每个 Skill 自由返回 dict
- `agent.py` 写 `ProblemMemory`（仅在 catch 时）
- 错误率 / 耗时 / 重试次数：**无指标**

### 4.2 设计目标
- **统一 SkillResult envelope**（所有 Skill 必返）
- **10 种 error code**（机读）
- **自动落盘 ProblemMemory**（失败即写，不靠 agent.py catch）

### 4.3 实施

#### 4.3.1 SkillResult envelope（核心）

```python
# src/agent/skill_result.py

@dataclass
class SkillResult:
    """所有 Skill 调用的标准返回 envelope。"""
    success: bool
    code: str = "ok"
    message: str = ""
    data: dict = field(default_factory=dict)
    error: dict = field(default_factory=dict)
    skill: str = ""
    duration_ms: int = 0
    attempts: int = 1
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def ok(cls, data: dict | None = None, message: str = "", **kw) -> "SkillResult":
        return cls(success=True, code="ok", message=message, data=data or {}, **kw)
    
    @classmethod
    def err(cls, code: str, message: str, error: dict | None = None, **kw) -> "SkillResult":
        return cls(success=False, code=code, message=message, error=error or {}, **kw)
```

#### 4.3.2 标准 error code（10 种）

| code | 含义 | retryable | 默认 message | 兜底 |
|---|---|---|---|---|
| `ok` | 成功 | - | - | - |
| `validation_error` | 输入参数错误 | ❌ | "参数 X 缺失" | 修正参数 |
| `not_found` | 资源不存在 | ❌ | "未找到 X" | 换资源 |
| `auth_required` | 需要登录/认证 | ❌ | "请先完成登录" | 引导 login |
| `paywall` | 付费墙/内容受限 | ❌ | "章节需付费" | 停止后续 |
| `cancelled` | 用户取消 | ❌ | "用户取消" | 不重试 |
| `timeout` | 执行超时 | ✅ | "操作超时" | 退避重试 |
| `rate_limited` | 频率限制 | ✅ | "操作过快" | 退避重试 |
| `skill_error` | 内部异常 | ❌ | "执行出错" | 写 ProblemMemory |
| `max_retries_exceeded` | 重试耗尽 | ❌ | "多次重试仍失败" | 写 ProblemMemory + 告警 |

#### 4.3.3 反馈数据

每次 Skill 调用都带回：
- `duration_ms`：单次耗时
- `attempts`：实际尝试次数（含 retry）
- `code`：状态码
- `message`：人类可读

→ 长期可聚合：
- 失败率（按 Skill / 按 code）
- 平均 / P99 耗时
- 重试率
- ProblemMemory 触发的"修复"次数

#### 4.3.4 异常落盘（自动）

```python
def _save_to_problem_memory(self, skill_name, kwargs, result: SkillResult):
    """Skill 失败时自动落盘。"""
    content = (
        f"Skill {skill_name} 失败\n"
        f"  code: {result.code}\n"
        f"  message: {result.message}\n"
        f"  kwargs: {json.dumps(kwargs, ensure_ascii=False)}\n"
        f"  error: {json.dumps(result.error, ensure_ascii=False)}"
    )
    MemoryLayerManager().append(
        layer="problem",
        user_id="default",
        content=content,
        tags=["skill_failure", skill_name, result.code],
    )
    fire_and_forget(
        review_skill_failure(skill_name=skill_name, kwargs=kwargs, result=result),
        name=f"error-review:{skill_name}",
    )
```

---

## Layer 5: 约束与安全机制

### 5.1 现状
- `Skill.params` 校验输入（已有）
- `Skill.requires_confirmation`（写操作要确认）但 agent.py 流程断断续续
- 浏览器 / 文件**无沙箱**

### 5.2 设计目标
- 任何**写操作**必须经过 3 道关：
  1. **参数 schema 校验**（类型 + 必填 + 范围）
  2. **幂等性检查**（避免重复执行）
  3. **用户确认**（`requires_confirmation=True`）
- 浏览器 / 文件沙箱（Layer 2.3）

### 5.3 实施

#### 5.3.1 三道关

```python
def call(self, name, kwargs):
    skill = self.get(name)
    
    # 关 1: 参数 schema 校验
    is_valid, err, code = validate_params(skill, kwargs)
    if not is_valid:
        return SkillResult.err("validation_error", err).to_dict()
    
    # 关 2: 幂等性检查（仅对 idempotent=True 的 Skill）
    if skill.idempotent:
        dup = self._check_duplicate(skill, kwargs)
        if dup:
            return SkillResult.ok(
                data={"deduplicated": True, "previous_result": dup},
                message=f"检测到重复，跳过执行（{dup}）",
            ).to_dict()
    
    # 关 3: 用户确认（agent.py 层做；registry 不管）
    # （agent 在 execute_plan 阶段就拦截）
    
    # 执行
    ...
```

#### 5.3.2 写操作 vs 只读分类

| 操作类型 | 示例 | requires_confirmation | idempotent |
|---|---|---|---|
| 只读 | `fanqie_list_books` / `fanqie_list_promotions` | False | True |
| 半写 | `fanqie_fetch_book`（写 books/ 目录） | False | True（同名书可覆盖） |
| 写（KOL） | `fanqie_apply_promotion` / `fanqie_bind_douyin_video` | True | True（需先查 list 避免重复） |
| 写（抖音） | `publish_douyin` | True | False（每次发都是新视频） |

---

## Layer 6: 持续改进循环

### 6.1 现状
- `ProblemMemory` 自动落盘
- `error_reviewer.py` 已有 fire-and-forget LLM 诊断
- **但**没有"诊断结果反馈到 Harness 设计"的闭环

### 6.2 设计目标
形成 **PDCA 循环**：
```
Skill 失败
  ↓
[Layer 4] 落盘 ProblemMemory（带 skill_name + kwargs + error）
  ↓
[Layer 6] fire-and-forget LLM 错误诊断
  ↓
LLM 分析根因 + 给出修复建议
  ↓
Harness 改进（修代码 / 改 schema / 加 retry / 改 prompt）
  ↓
[Layer 1-5] 改完后下次不再犯
```

### 6.3 实施

#### 6.3.1 ProblemMemory + error_reviewer 已存在

```python
# src/agent/error_reviewer.py — 已有骨架
async def review_skill_failure(skill_name, skill_kwargs, result: SkillResult):
    """分析 Skill 失败，给出修复建议。"""
    prompt = (
        f"Skill {skill_name} 失败。\n"
        f"code: {result.code}\n"
        f"kwargs: {json.dumps(skill_kwargs, ensure_ascii=False)}\n"
        f"error: {json.dumps(result.error, ensure_ascii=False)}\n\n"
        f"请分析：(1) 根因 (2) 修复建议（代码 / schema / retry / prompt 哪一层）"
    )
    diagnosis = await llm_client.chat(prompt, caller="error_reviewer")
    MemoryLayerManager().append(
        layer="problem",
        user_id="default",
        content=f"[诊断] {skill_name}: {diagnosis}",
        tags=["diagnosis", skill_name],
    )
```

#### 6.3.2 监控 + 仪表盘（Streamlit）

```python
# src/web/app.py 加 "Skill 监控" 页
def render_skill_monitor():
    # 1) 失败率（按 Skill / 按 code）
    # 2) 平均 / P99 耗时
    # 3) 重试率
    # 4) ProblemMemory 触发的诊断数
    # 5) 热门失败（Top 10）
    ...
```

#### 6.3.3 Harness 改进流程（人工闭环）

- 每周一次 review `ProblemMemory`
- 找高频失败模式
- **修改 Harness**（不是修改 prompt！）：
  - 改 Skill 代码（修 bug）
  - 改 Skill schema（加约束）
  - 改 retry 配置（提高 retry_on 覆盖）
  - 改安全机制（加 idempotent / 加沙箱）

> 核心原则：**改 Harness，不改 Prompt**。Prompt 调整是兜底，根因在环境设计。

---

## 实施步骤（增量迁移，不破坏现有）

| 步骤 | 改动 | 影响 |
|---|---|---|
| 1 | 新建 `src/agent/skill_result.py`（SkillResult 数据类） | 无 |
| 2 | Skill class 加 `timeout_s` / `retries` / `retry_on` / `retry_backoff` / `idempotent` | 向后兼容 |
| 3 | `SkillRegistry.call` 重构：参数校验 + 重试 + 超时 + SkillResult 包装 + ProblemMemory 自动落盘 | 行为更稳健 |
| 4 | 改 22 个 Skill 函数返回 `SkillResult`（按优先级） | 内部接口统一 |
| 5 | 浏览器白名单 + 文件沙箱（Layer 2） | 限制访问范围 |
| 6 | 写 `docs/SKILL_SPEC.md`（本文） | 文档化 |
| 7 | 拆 `.claude/skills/fanqie-operations.md` → content / promote / monitor | 职责清晰 |
| 8 | 简化 `agent.py`：去掉重复 try/except | 代码精简 |
| 9 | 加 `tests/test_skill_result.py` + `tests/test_skill_registry.py` | 单元测试 |
| 10 | Streamlit 加 "Skill 监控" 页 | 可视化 |
| 11 | `error_reviewer` 接收 SkillResult 完整字段 | 诊断更精准 |
| 12 | 写 `docs/HARNESS_ITERATION_LOG.md`（改进记录） | PDCA 闭环 |

## 验收标准

- [ ] 所有 Skill 返回 `SkillResult`（不再返回裸 dict）
- [ ] 失败时 ProblemMemory 有完整记录
- [ ] LLM 看到统一 envelope（success/code/message/data/error/skill/duration_ms/attempts）
- [ ] 超时熔断工作（timeout_s=300 默认）
- [ ] 重试退避工作（指数退避 1s/2s/4s）
- [ ] 浏览器白名单 + 文件沙箱生效
- [ ] 错误码可机读（10 种）
- [ ] 单元测试覆盖率 > 80%
- [ ] `.claude/skills/` 拆分清晰
- [ ] Streamlit "Skill 监控" 页可用
- [ ] 每次失败都有诊断记录（LLM 错误分析）
- [ ] PDCA 循环：每月 review 失败模式 → 改 Harness

## 与现有模块的关系

| 模块 | 现状 | 改进 |
|---|---|---|
| `src/agent/registry.py` | 基础注册 + 校验 + call | 加 retry/timeout/ProblemMemory/幂等 |
| `src/agent/skill_decorator.py` | Skill + SkillParam + ParamType | 加 timeout/retries/idempotent 字段 |
| `src/agent/agent.py` | 自己 try/except + 写 ProblemMemory | 删除重复逻辑，依赖 registry |
| `src/agent/error_reviewer.py` | fire-and-forget LLM 诊断 | 接收 SkillResult 替代 dict |
| `src/memory/problem_memory.py` | 已有 | 接受新 SkillResult 字段 |
| `src/platform_adapter/browser_session.py` | 浏览器自动化 | 加域名白名单 |
| `src/agent/filesystem_sandbox.py` | 不存在 | 新建 |
| `src/agent/prompts/system.md` | 不存在 | 新建（system prompt 抽文件） |
| `src/web/app.py` | 管理后台 | 加 Skill 监控页 |
| `docs/SKILL_SPEC.md` | 不存在 | 本文 |
| `.claude/skills/` | 5 个文件 | 拆 fanqie-* 到 3 个 |
| `tests/` | 缺 Skill 测试 | 加单元测试 |
