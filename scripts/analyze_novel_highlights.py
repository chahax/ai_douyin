#!/usr/bin/env python3
"""Scan a novel for source-grounded promotional highlights."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.trend_intelligence.novel_highlights import (
    NovelHighlightAnalyzer,
    render_highlight_report,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="分段扫描小说全文，输出有原文定位的高光与情绪冲突报告。"
    )
    parser.add_argument("source", type=Path, help="UTF-8 小说文本文件")
    parser.add_argument("--title", default="", help="小说标题")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--driver",
        choices=("novel_highlight", "reference_video"),
        default="novel_highlight",
        help="小说高光驱动或参考视频结构驱动",
    )
    parser.add_argument(
        "--reference-analysis",
        type=Path,
        action="append",
        default=[],
        help="可重复传入视频内容分析 JSON；只提取高光位置和表达节奏",
    )
    parser.add_argument("--chunk-chars", type=int, default=6000)
    parser.add_argument("--overlap-chars", type=int, default=1200)
    parser.add_argument("--min-seconds", type=int, default=45)
    parser.add_argument("--max-seconds", type=int, default=180)
    parser.add_argument(
        "--target-seconds",
        type=float,
        help="覆盖选中高光的推荐时长",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="只输出高光报告，不继续生成分镜脚本",
    )
    return parser.parse_args()


def _load_reference_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict) and isinstance(value.get("analyses"), list):
            rows.extend(
                item for item in value["analyses"] if isinstance(item, dict)
            )
        elif isinstance(value, dict):
            rows.append(value)
        else:
            raise ValueError(f"参考分析必须是 JSON object/list: {path}")
    return rows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _args()
    source = args.source.read_text(encoding="utf-8").strip()
    references = _load_reference_rows(args.reference_analysis)
    analyzer = NovelHighlightAnalyzer(
        chunk_chars=args.chunk_chars,
        overlap_chars=args.overlap_chars,
        min_video_seconds=args.min_seconds,
        max_video_seconds=args.max_seconds,
    )
    report = analyzer.analyze(
        source,
        novel_title=args.title or args.source.stem,
        reference_analyses=references,
        driver_mode=args.driver,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "novel_highlight_analysis.json"
    markdown_path = args.output_dir / "novel_highlight_analysis.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_highlight_report(report), encoding="utf-8")
    selected = report.selected_highlight
    storyboard_path: Path | None = None
    if not args.analysis_only:
        from src.content_factory.novel_splitter import split_novel

        storyboard = split_novel(
            source,
            novel_title=args.title or args.source.stem,
            highlight_report=report,
            target_duration_seconds=args.target_seconds,
            caller="novel_highlight_storyboard",
        )
        storyboard_path = args.output_dir / "novel_highlight_storyboard.json"
        storyboard_path.write_text(
            json.dumps(
                {
                    "schema": "novel_highlight_storyboard/v2",
                    "driver_mode": report.driver_mode,
                    "driver_decision": report.driver_decision,
                    "highlight_id": selected.highlight_id,
                    "storyboard": storyboard.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "schema": report.schema,
                "driver_mode": report.driver_mode,
                "candidate_count": len(report.candidates),
                "selected_highlight_id": selected.highlight_id,
                "selected_title": selected.title,
                "recommended_duration_seconds": selected.recommended_duration_seconds,
                "json": str(json_path.resolve()),
                "markdown": str(markdown_path.resolve()),
                "storyboard": (
                    str(storyboard_path.resolve()) if storyboard_path else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
