#!/usr/bin/env python3
"""CLI wrapper for the analysis-document prompt-pack compiler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.content_factory.analysis_prompt_pack import (  # noqa: E402
    DEFAULT_STYLE,
    compile_analysis_prompt_pack,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将视频复刻分析 Markdown 编译为分段视频大模型提示词包。"
    )
    parser.add_argument("document", help="输入分析 Markdown 文件")
    parser.add_argument("--output", required=True, help="输出 JSON 提示词包")
    parser.add_argument("--markdown", help="可选：输出便于人工审核的 Markdown 提示词包")
    parser.add_argument("--style", default=DEFAULT_STYLE, help="全局画面风格")
    parser.add_argument(
        "--model-profile",
        default="generic-image-to-video",
        help="目标模型配置标签，仅写入产物供后续适配器使用",
    )
    parser.add_argument(
        "--production-mode",
        choices=("postproduction", "native_full_video"),
        default="postproduction",
        help="postproduction 生成纯画面；native_full_video 要求模型原生生成对白、口型、字幕和界面",
    )
    parser.add_argument(
        "--generation-min-seconds",
        type=float,
        default=2.0,
        help="单段建议生成最短时长（默认 2 秒）",
    )
    parser.add_argument(
        "--generation-max-seconds",
        type=float,
        default=5.0,
        help="单段建议生成最长时长（默认 5 秒）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pack = compile_analysis_prompt_pack(
        args.document,
        output_path=args.output,
        markdown_path=args.markdown,
        style=args.style,
        model_profile=args.model_profile,
        production_mode=args.production_mode,
        generation_min_seconds=args.generation_min_seconds,
        generation_max_seconds=args.generation_max_seconds,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "schema": pack["schema"],
                "segments": pack["segment_count"],
                "output": str(Path(args.output).resolve()),
                "markdown": str(Path(args.markdown).resolve()) if args.markdown else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
