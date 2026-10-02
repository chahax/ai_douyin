#!/usr/bin/env python3
"""Refine local Qwen/ASR evidence into a detailed script with MiniMax."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.content_factory.video_script_refiner import (  # noqa: E402
    VideoScriptRefinementRequest,
    VideoScriptRefiner,
    build_refinement_preview,
)
from src.shared.config import settings  # noqa: E402
from src.shared.llm_client import LLMClient  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "使用 MiniMax 将 Qwen/ASR 视频证据整理成复刻级剧本。"
            "默认只检查输入并生成预览，不调用模型。"
        )
    )
    parser.add_argument("evidence_dir", help="视频分析证据目录")
    parser.add_argument(
        "--output",
        help="Markdown 输出；默认写入证据目录的 RECONSTRUCTED_SCRIPT.minimax.md",
    )
    parser.add_argument(
        "--model",
        default=settings.VIDEO_SCRIPT_MODEL,
        help="必须与当前 LLM_MODEL 一致",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=settings.VIDEO_SCRIPT_TEMPERATURE,
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="实际调用 MiniMax；不传时不访问网络、不产生费用",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖已有输出；默认保护现有剧本文档",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="允许复用项目 LLM 缓存；默认进行可审计的新调用",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_dir = Path(args.evidence_dir).resolve()
    output = (
        Path(args.output).resolve()
        if args.output
        else evidence_dir / "RECONSTRUCTED_SCRIPT.minimax.md"
    )
    request = VideoScriptRefinementRequest(
        evidence_dir=evidence_dir,
        model=args.model,
        temperature=args.temperature,
    )
    if not args.submit:
        preview = build_refinement_preview(request)
        preview["output"] = str(output)
        preview["mode"] = "dry-run"
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    client = LLMClient()
    refiner = VideoScriptRefiner(client, request)
    metadata = refiner.refine(
        output,
        overwrite=args.overwrite,
        use_cache=args.use_cache,
    )
    print(
        json.dumps(
            {
                "status": "succeeded",
                "model": metadata["model"],
                "output": metadata["output"]["path"],
                "metadata": metadata["metadata_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
