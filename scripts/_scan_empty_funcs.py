"""一次性扫描：找 src/ 下函数体只有 docstring 的"空壳"函数"""
import ast
import os
import sys

results = []
for root, dirs, files in os.walk('src'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fname in files:
        if not fname.endswith('.py'):
            continue
        p = os.path.join(root, fname)
        try:
            with open(p, encoding='utf-8') as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # 函数体只有 docstring
            if (
                len(node.body) == 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                results.append((p, node.lineno, node.name))

if not results:
    print("✓ 未发现空壳函数")
else:
    print(f"⚠ 发现 {len(results)} 个空壳函数：")
    for p, l, n in results:
        print(f"  {p}:{l}  {n}()")
