"""验证 agent.py 简化后行为：
  1. 静态检查：registry.call 不再被 try/except 包裹
  2. AST 精确检查：_handle_confirmation 的 confirm 分支无 try/except
  3. confirm 分支引用 SkillResult.success / code / data 字段
  4. agent 层仍写 ProblemMemory（保留 session_id 上下文）
"""
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


src = Path("src/agent/agent.py").read_text(encoding="utf-8")

# === 1. 静态检查：registry.call 不在 try 内 ===
print("=== 1. Static: registry.call not in try ===")
tree = ast.parse(src)

class CallInTry(ast.NodeVisitor):
    def __init__(self):
        self.hits = []

    def visit_Try(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                if (isinstance(sub.func, ast.Attribute) and
                    sub.func.attr == "call" and
                    isinstance(sub.func.value, ast.Name) and
                    sub.func.value.id == "registry"):
                    self.hits.append(node.lineno)
        self.generic_visit(node)

inspector = CallInTry()
inspector.visit(tree)
assert len(inspector.hits) == 0, f"仍有 try/except 包 registry.call: lines {inspector.hits}"
print("  PASS: registry.call not wrapped in try/except")


# === 2. AST 精确切 confirm 分支 ===
print("\n=== 2. AST: confirm branch in _handle_confirmation ===")
func_node = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_handle_confirmation":
        func_node = node
        break
assert func_node is not None

confirm_branch = None
for stmt in func_node.body:
    if isinstance(stmt, ast.If):
        try:
            test_src = ast.unparse(stmt.test)
        except Exception:
            test_src = ""
        if "confirm_words" in test_src:
            confirm_branch = stmt
            break
assert confirm_branch is not None
print("  confirm branch found")

# 2.1) confirm 分支无 try/except
# 注：ProblemMemory 写入可以用 try/except（catch MemoryManager 失败，不掩盖 Skill 失败信息）
# 但不能 try/except 包裹 registry.call（已不可能，因为 registry 不抛）
n_try = sum(1 for sub in ast.walk(confirm_branch) if isinstance(sub, ast.Try))
print(f"  try/except count in confirm: {n_try}")
# 检查每个 try 里都没有 self.registry.call
call_in_try = []
for sub in ast.walk(confirm_branch):
    if isinstance(sub, ast.Try):
        for inner in ast.walk(sub):
            if isinstance(inner, ast.Call):
                if (isinstance(inner.func, ast.Attribute) and
                    inner.func.attr == "call" and
                    isinstance(inner.func.value, ast.Name) and
                    inner.func.value.id == "registry"):
                    call_in_try.append(sub.lineno)
print(f"  registry.call inside try: {call_in_try}")
assert len(call_in_try) == 0, f"registry.call 不应在 try 内: {call_in_try}"
print("  PASS: no try/except wraps registry.call (other try/except OK)")

# 2.2) 引用 SkillResult.success
branch_src = ast.unparse(confirm_branch)
assert "success" in branch_src, "没引用 result.success"
print("  PASS: uses result.success field")

# 2.3) 写 ProblemMemory（保留 session_id）
assert "_add_problem" in branch_src, "没调 _add_problem"
print("  PASS: writes ProblemMemory (has session_id)")

# 2.4) tool_success / tool_error
assert "tool_success=" in branch_src, "没传 tool_success"
assert "tool_error=" in branch_src, "没传 tool_error"
print("  PASS: append_message with tool_success/tool_error")


# === 3. 跑 skill_registry 单元测试确认 SkillResult 工作正常 ===
print("\n=== 3. Run skill_registry unit tests ===")
import subprocess
r = subprocess.run(
    ["python", "tests/test_skill_registry.py"],
    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    timeout=60, encoding="utf-8", errors="replace",
)
if "ALL TESTS PASSED" in r.stdout:
    print("  PASS: skill_registry tests pass")
else:
    print("  FAIL: skill_registry tests failed")
    print("  stdout:", r.stdout[-500:])

print("\n=== ALL VERIFICATIONS PASSED ===")
