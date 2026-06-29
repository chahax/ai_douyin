# -*- coding: utf-8 -*-
"""
src/agent/filesystem_sandbox.py — 文件系统沙箱

Harness Engineering Layer 5: 约束与安全机制。

只允许 Skill 读写 ALLOWED_ROOTS 下的文件，阻止误写源码 / 配置 / 系统目录。

用法：
    from src.agent.filesystem_sandbox import FileSandbox

    # 写
    path = FileSandbox.safe_path("data/fanqie_promotion/books/foo.json")
    path.write_text("...")

    # 读
    content = FileSandbox.read_text("data/videos/intro.mp4")  # .mp4 不允许

    # 列出允许的根
    FileSandbox.list_allowed_roots()
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


class FileSandboxError(PermissionError):
    """文件沙箱违规。"""


class FileSandbox:
    """只允许读写指定子目录的沙箱。"""

    # 允许的根目录（项目内）
    ALLOWED_ROOTS = (
        "data/fanqie_promotion/",   # 番茄推广数据
        "data/videos/",             # 视频输出
        "data/asset_collections/",  # 资产
        "data/audio/",              # 音频
        "data/articles/",            # 文章
        "logs/",                     # 日志
        "tmp/",                      # 临时文件
    )

    # 禁止的路径（即使在 ALLOWED_ROOTS 下也禁止）
    BLOCKED_PATTERNS = (
        ".git/",
        ".env",
        "node_modules/",
        "__pycache__/",
        ".venv/",
        "site-packages/",
        "secrets",
        "credentials",
    )

    # 禁止的文件扩展名
    BLOCKED_EXTENSIONS = (
        ".exe", ".dll", ".so", ".dylib",
        ".bat", ".sh", ".ps1",  # 脚本（开发脚本可通过 `python scripts/x.py` 跑）
    )

    @classmethod
    def safe_path(cls, path: Union[str, Path]) -> Path:
        """校验并返回 resolved Path。失败抛 FileSandboxError。"""
        p = Path(path).resolve()

        # 1) 检查 BLOCKED_PATTERNS
        path_str = str(p).replace("\\", "/")
        for pat in cls.BLOCKED_PATTERNS:
            if pat in path_str:
                raise FileSandboxError(
                    f"文件沙箱：禁止访问含 '{pat}' 的路径 ({p})"
                )

        # 2) 检查 BLOCKED_EXTENSIONS
        if p.suffix.lower() in cls.BLOCKED_EXTENSIONS:
            raise FileSandboxError(
                f"文件沙箱：禁止写入 {p.suffix} 文件 ({p})"
            )

        # 3) 检查是否在 ALLOWED_ROOTS 下
        for root in cls.ALLOWED_ROOTS:
            try:
                p.relative_to(Path(root).resolve())
                return p
            except ValueError:
                continue

        raise FileSandboxError(
            f"文件沙箱：禁止访问 {p}（不在白名单 {cls.ALLOWED_ROOTS}）"
        )

    @classmethod
    def read_text(cls, path: Union[str, Path], encoding: str = "utf-8") -> str:
        """安全读文件。"""
        return cls.safe_path(path).read_text(encoding=encoding)

    @classmethod
    def write_text(cls, path: Union[str, Path], content: str, encoding: str = "utf-8") -> Path:
        """安全写文件。自动创建父目录。"""
        p = cls.safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return p

    @classmethod
    def read_bytes(cls, path: Union[str, Path]) -> bytes:
        return cls.safe_path(path).read_bytes()

    @classmethod
    def write_bytes(cls, path: Union[str, Path], data: bytes) -> Path:
        p = cls.safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    @classmethod
    def list_allowed_roots(cls) -> list[str]:
        return list(cls.ALLOWED_ROOTS)

    @classmethod
    def is_safe(cls, path: Union[str, Path]) -> bool:
        """检查路径是否安全（不抛异常）。"""
        try:
            cls.safe_path(path)
            return True
        except FileSandboxError:
            return False
