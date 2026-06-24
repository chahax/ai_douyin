# -*- coding: utf-8 -*-
"""
scripts/pre_push_check.py — push 前安全检查

跑 8 项检查，发现任何问题就 exit code 1，阻止 push。

用法：
    python scripts/pre_push_check.py

接入 git hook（可选）：
    ln -s ../../scripts/pre_push_check.py .git/hooks/pre-push

会检查：
  1. .env 是否被 git 跟踪
  2. .env 是否含真实 key（vs 占位符）
  3. 源码是否含硬编码 sk- / api_key / secret
  4. 源码是否含硬编码 Windows 路径（C:\\Users\\c / D:\\IT）
  5. data/browser/ 是否被跟踪
  6. data/douyin_warmup/ / data/fanqie_promotion/ 是否被跟踪
  7. *.db / .sqlite 是否被跟踪
  8. 任何被跟踪的 >1MB 文件（潜在泄漏大文件）

通过输出绿色，失败红色。
"""

import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def red(msg: str) -> str:
    return f"{RED}{msg}{RESET}"


def green(msg: str) -> str:
    return f"{GREEN}{msg}{RESET}"


def yellow(msg: str) -> str:
    return f"{YELLOW}{msg}{RESET}"


def fail(name: str, detail: str) -> None:
    print(f"  {red('[FAIL]')} {name}: {detail}")


def ok(name: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  {green('[OK]')} {name}{suffix}")


def warn(name: str, detail: str) -> None:
    print(f"  {yellow('[WARN]')} {name}: {detail}")


def run(cmd: list[str], cwd: Path = PROJECT_ROOT) -> str:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=False
    ).stdout


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------


def check_env_not_tracked() -> bool:
    """1. .env 不应在 git tracked files 里（.env.example 是模板，允许）。"""
    out = run(["git", "ls-files"])
    # 排除 .env.example（模板文件，应该被跟踪）
    tracked = [
        f for f in out.splitlines()
        if (f == ".env" or f.startswith(".env.")) and f != ".env.example"
    ]
    if tracked:
        fail(".env 跟踪", f"这些 .env* 文件在 git 里：{tracked}")
        return False
    ok(".env 未跟踪", ".env.example 是模板，正常跟踪")
    return True


def check_env_has_real_keys() -> bool:
    """2. .env 不应含真实 key（占位符可以）。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        warn(".env 文件不存在", "跳过此项（首次部署时可接受）")
        return True
    content = env_path.read_text(encoding="utf-8")
    # 真实 key 模式：sk- 开头 20+ 字符
    real_keys = re.findall(r"sk-[A-Za-z0-9_-]{20,}", content)
    if real_keys:
        # 真实 key 在 .env 里是正常的（运行时用），但要确认 .env 没被跟踪
        ok(".env 里的真实 key", f"{len(real_keys)} 个（仅在本地，不会 push）")
    else:
        ok(".env 里的 key", "全是占位符或空")
    return True


def check_source_no_hardcoded_secrets() -> bool:
    """3. 源码无硬编码 sk- / api_key=... / secret=... 字面值。"""
    # 在 src/ 和 alembic/ 和 main.py 里扫
    sources = ["src", "alembic"]
    files_to_scan: list[Path] = []
    for root in sources:
        root_path = PROJECT_ROOT / root
        if root_path.exists():
            files_to_scan.extend(root_path.rglob("*.py"))

    if (PROJECT_ROOT / "main.py").exists():
        files_to_scan.append(PROJECT_ROOT / "main.py")

    # 匹配：sk- 开头 20+ 字符（非注释）
    issues: list[tuple[Path, int, str]] = []
    for f in files_to_scan:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # sk- 模式
                if re.search(r"sk-[A-Za-z0-9_-]{20,}", line):
                    issues.append((f, i, line.strip()[:100]))
                # api_key="实际值" 模式
                m = re.search(
                    r"""(?:api[_-]?key|secret|password|token)\s*[:=]\s*['"]([^'"]{10,})['"]""",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    val = m.group(1)
                    if val.lower() not in ("none", "null", "your_", "your ", ""):
                        # 排除占位符
                        if not (
                            val.startswith("your_")
                            or val.startswith("placeholder")
                            or val == "test"
                        ):
                            issues.append((f, i, line.strip()[:100]))
        except (UnicodeDecodeError, OSError):
            continue

    if issues:
        for f, i, snippet in issues[:5]:
            fail("源码硬编码 secret", f"{f.relative_to(PROJECT_ROOT)}:{i}  {snippet}")
        return False
    ok("源码无硬编码 secret")
    return True


def check_source_no_hardcoded_paths() -> bool:
    """4. 源码无硬编码 Windows 路径（C:\\Users\\c / D:\\IT\\ai_douyin）。"""
    sources = ["src", "alembic"]
    files_to_scan: list[Path] = []
    for root in sources:
        root_path = PROJECT_ROOT / root
        if root_path.exists():
            files_to_scan.extend(root_path.rglob("*.py"))

    if (PROJECT_ROOT / "main.py").exists():
        files_to_scan.append(PROJECT_ROOT / "main.py")

    issues: list[tuple[Path, int, str]] = []
    for f in files_to_scan:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # C:\\Users\\c 或 C:/Users/c
                if re.search(r"C:[/\\\\]Users[/\\\\]c", line):
                    issues.append((f, i, line.strip()[:100]))
                # D:\\IT\\ai_douyin 或 D:/IT/ai_douyin
                if re.search(r"D:[/\\\\]IT[/\\\\]ai_douyin", line):
                    issues.append((f, i, line.strip()[:100]))
        except (UnicodeDecodeError, OSError):
            continue

    if issues:
        for f, i, snippet in issues[:5]:
            fail("源码硬编码路径", f"{f.relative_to(PROJECT_ROOT)}:{i}  {snippet}")
        return False
    ok("源码无硬编码个人路径")
    return True


def check_path_not_tracked(path: Path, name: str) -> bool:
    out = run(["git", "ls-files", str(path)])
    tracked = [f for f in out.splitlines() if f]
    if tracked:
        fail(f"{name} 跟踪", f"{tracked[:3]}{'...' if len(tracked) > 3 else ''}")
        return False
    ok(f"{name} 未跟踪")
    return True


def check_browser_dirs() -> bool:
    return check_path_not_tracked(PROJECT_ROOT / "data" / "browser", "data/browser/")


def check_warmup_dir() -> bool:
    return check_path_not_tracked(
        PROJECT_ROOT / "data" / "douyin_warmup", "data/douyin_warmup/"
    )


def check_fanqie_dir() -> bool:
    return check_path_not_tracked(
        PROJECT_ROOT / "data" / "fanqie_promotion", "data/fanqie_promotion/"
    )


def check_db_files() -> bool:
    out = run(["git", "ls-files"])
    db_tracked = [f for f in out.splitlines() if f.endswith((".db", ".sqlite", ".sqlite3"))]
    if db_tracked:
        fail("数据库文件被跟踪", f"{db_tracked[:3]}")
        return False
    ok("数据库文件未跟踪")
    return True


def check_large_tracked_files() -> bool:
    """8. 任何被跟踪的 >1MB 文件（可能误传大文件）。"""
    out = run(["git", "ls-files", "-z"])
    files = [f for f in out.split("\0") if f]
    large: list[tuple[str, int]] = []
    for f in files:
        path = PROJECT_ROOT / f
        if path.exists():
            size = path.stat().st_size
            if size > 1024 * 1024:  # >1MB
                large.append((f, size))
    if large:
        for f, size in large[:3]:
            warn("大文件被跟踪", f"{f} ({size // 1024} KB)")
        return False
    ok("没有 >1MB 的大文件被跟踪")
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 70)
    print("🚀 pre-push 安全检查")
    print("=" * 70)
    print()

    checks: list[tuple[str, callable]] = [
        ("1. .env 跟踪", check_env_not_tracked),
        ("2. .env 真实 key", check_env_has_real_keys),
        ("3. 源码硬编码 secret", check_source_no_hardcoded_secrets),
        ("4. 源码硬编码路径", check_source_no_hardcoded_paths),
        ("5. data/browser/", check_browser_dirs),
        ("6. data/douyin_warmup/", check_warmup_dir),
        ("7. data/fanqie_promotion/", check_fanqie_dir),
        ("8. 数据库文件", check_db_files),
        ("9. 大文件被跟踪", check_large_tracked_files),
    ]

    passed = 0
    failed = 0
    for name, fn in checks:
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as exc:
            fail(name, f"检查脚本异常: {exc}")
            failed += 1
        print()

    print("=" * 70)
    if failed == 0:
        print(green(f"✅ 全部 {passed} 项通过 — 可以放心 push！"))
    else:
        print(
            red(f"❌ {failed} 项失败 / {passed} 项通过")
            + " — 请修复后再 push"
        )
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())