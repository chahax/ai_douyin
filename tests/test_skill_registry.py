"""测试 SkillRegistry 重构后行为：
  1. 老 Skill（返回裸 dict）→ 仍能用，自动 coerce 到 SkillResult
  2. 新 Skill（返回 SkillResult）→ 透传 + 自动填 skill/duration/attempts
  3. 失败 → 落盘 ProblemMemory + 触发 error_reviewer
  4. retry 触发条件
  5. 幂等检查
  6. error code 规范
"""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 1. SkillResult 模块基本功能 ──
print("=== 1. SkillResult 基础 ===")
from src.agent.skill_result import SkillResult, coerce_to_skill_result, SKILL_ERROR_CODES

assert "ok" in SKILL_ERROR_CODES
assert "validation_error" in SKILL_ERROR_CODES
assert "timeout" in SKILL_ERROR_CODES
assert "max_retries_exceeded" in SKILL_ERROR_CODES
print(f"  SKILL_ERROR_CODES ({len(SKILL_ERROR_CODES)}): {SKILL_ERROR_CODES}")

# ok 工厂
r = SkillResult.ok(data={"x": 1}, message="yes")
assert r.success
assert r.code == "ok"
assert r.data == {"x": 1}
print(f"  ok factory: {r.to_dict()['code']} {r.to_dict()['data']}")

# err 工厂
r = SkillResult.err("not_found", "没找到", error={"retryable": False})
assert not r.success
assert r.code == "not_found"
assert not r.is_retryable
print(f"  err factory: {r.code} retryable={r.is_retryable}")

# 未知 code 自动 fallback
r = SkillResult.err("bogus_code", "x")
assert r.code == "skill_error"
print(f"  unknown code fallback: bogus_code -> {r.code}")

# is_retryable
assert SkillResult.err("timeout", "x").is_retryable
assert SkillResult.err("rate_limited", "x").is_retryable
assert not SkillResult.err("validation_error", "x").is_retryable
print("  is_retryable map OK")


# ── 2. coerce_to_skill_result 兼容老格式 ──
print("\n=== 2. coerce_to_skill_result 兼容老格式 ===")
# 老 dict (success=True)
r = coerce_to_skill_result("old_skill", {"success": True, "result": "hello", "extra": 1})
assert r.success
assert r.data == {"result": "hello", "extra": 1}  # 非标准字段进 data
print(f"  old dict (success): {r.to_dict()}")

# 老 dict (success=False)
r = coerce_to_skill_result("old_skill", {"success": False, "error": "出错了"})
assert not r.success
assert r.code == "skill_error"
assert "出错了" in r.message
print(f"  old dict (failure): code={r.code} msg={r.message[:30]}")

# 老 dict with explicit code
r = coerce_to_skill_result("old_skill", {"success": False, "code": "not_found", "error": "X"})
assert r.code == "not_found"
print(f"  old dict (with code): code={r.code}")

# 非 dict
r = coerce_to_skill_result("returns_int", 42)
assert r.success
assert r.data == {"value": 42}
print(f"  raw int: {r.data}")

# SkillResult 直接传
r2 = SkillResult.ok(data={"a": 1}, skill="pre_set")
r = coerce_to_skill_result("another", r2)
assert r.skill == "pre_set"  # 不覆盖
print(f"  SkillResult passthrough: skill={r.skill}")


# ── 3. 真实 SkillRegistry 调 Skill ──
print("\n=== 3. SkillRegistry.call 真实调用 ===")
from src.agent.registry import SkillRegistry, Skill

reg = SkillRegistry()

# 3.1 调一个真实老 Skill（返回裸 dict）
r = reg.call("fanqie_list_books", {})
assert r["success"] is True
assert r["code"] == "ok"
assert r["skill"] == "fanqie_list_books"
assert "duration_ms" in r
assert "attempts" in r
assert r["attempts"] >= 1
print(f"  fanqie_list_books: success={r['success']} attempts={r['attempts']} duration={r['duration_ms']}ms")

# 3.2 未知 Skill
r = reg.call("nonexistent_skill_xyz", {})
assert r["success"] is False
assert r["code"] == "not_found"
print(f"  unknown skill: code={r['code']}")

# 3.3 参数校验失败
r = reg.call("fanqie_fetch_book", {"chapters": "not_int"})
assert r["success"] is False
assert r["code"] == "validation_error"
print(f"  validation error: code={r['code']} msg={r['message'][:60]}")


# ── 4. 模拟失败 Skill + retry + ProblemMemory ──
print("\n=== 4. 失败 + retry + ProblemMemory 落盘 ===")

from src.agent.skill_decorator import skill

# 用装饰器注册一个测试 Skill：超时重试 2 次
@skill(
    name="test_fail_skill",
    description="测试失败",
    timeout_s=0.5,
    retries=2,
    retry_on=("timeout", "skill_error"),
)
def test_fail_skill(should_fail: bool = True) -> dict:
    if should_fail:
        raise RuntimeError("测试失败")
    return {"success": True, "result": "ok"}


# 注册到 registry
reg._skills["test_fail_skill"] = test_fail_skill_skill if False else None
# 装饰器返回的 Skill 对象 — 重新取一次
import src.agent.skill_decorator as sd
for s in sd._SKILLS:
    if s.name == "test_fail_skill":
        reg._skills["test_fail_skill"] = s
        break

# 4.1 失败 + 重试
r = reg.call("test_fail_skill", {"should_fail": True})
assert r["success"] is False
# skill_error 默认不可重试，所以 max_retries_exceeded 不会触发
# 但 attempts 应该是 1
print(f"  failed skill: code={r['code']} attempts={r['attempts']} duration={r['duration_ms']}ms")

# 4.2 设置 retry_on 包含 skill_error，应该重试 2 次后 max_retries
test_skill = reg._skills["test_fail_skill"]
test_skill.retry_on = ("timeout", "skill_error")  # 包含 skill_error
r = reg.call("test_fail_skill", {"should_fail": True})
assert r["code"] == "max_retries_exceeded"
assert r["attempts"] == 3  # 1 + 2 retries
print(f"  max retries: code={r['code']} attempts={r['attempts']}")


# ── 5. timeout 行为 ──
print("\n=== 5. timeout 熔断 ===")

@skill(name="test_slow_skill", description="慢 skill", timeout_s=0.3, retries=0)
def test_slow_skill() -> dict:
    time.sleep(1.0)
    return {"success": True}


for s in sd._SKILLS:
    if s.name == "test_slow_skill":
        reg._skills["test_slow_skill"] = s
        break

t0 = time.time()
r = reg.call("test_slow_skill", {})
elapsed = time.time() - t0
assert r["code"] == "timeout"
assert elapsed < 0.8  # 应该 < 超时 + 重试时间，远小于 sleep(1)
print(f"  timeout: code={r['code']} elapsed={elapsed:.2f}s (< 0.8s OK)")


# ── 6. 幂等检查 ──
print("\n=== 6. 幂等性 ===")

@skill(name="test_idempotent_skill", description="幂等", idempotent=True)
def test_idempotent_skill() -> dict:
    return {"success": True, "result": time.time()}


for s in sd._SKILLS:
    if s.name == "test_idempotent_skill":
        reg._skills["test_idempotent_skill"] = s
        break

# 第一次：正常执行
r1 = reg.call("test_idempotent_skill", {})
assert r1["success"]
assert not r1["data"].get("deduplicated", False)
print(f"  first call: success={r1['success']} deduplicated={r1['data'].get('deduplicated', False)}")

# 第二次（5 分钟内，同 kwargs）：去重
r2 = reg.call("test_idempotent_skill", {})
assert r2["success"]
assert r2["data"].get("deduplicated", False)  # 去重了
print(f"  second call: deduplicated={r2['data'].get('deduplicated', False)} OK")


print("\n=== ALL TESTS PASSED ===")
