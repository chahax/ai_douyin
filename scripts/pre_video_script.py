"""Generate a short/long script pair from recent analysed video types and print only it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.trend_intelligence.pre_video_script import (  # noqa: E402
    PreVideoScriptRequest,
    PreVideoScriptService,
    render_script_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="先核验同批来源音画表达，再比较高表现表达方式并生成短长双剧本。"
    )
    parser.add_argument("--account-key", required=True)
    parser.add_argument(
        "--recent-video-types",
        required=True,
        help="逗号分隔的近期展示类型，例如 mixed,talking_head",
    )
    parser.add_argument("--window-days", type=int, default=None, help="可选：只保留已知发布时间在最近 N 天的来源")
    parser.add_argument("--min-relevance", type=float, default=50.0)
    parser.add_argument("--max-source-videos", type=int, default=20)
    parser.add_argument(
        "--high-traffic-percentile",
        type=float,
        default=0.70,
        help="相对高流量分位阈值，0.70 表示取筛选结果的前 30%%",
    )
    parser.add_argument("--short-seconds", type=int, default=45)
    parser.add_argument("--long-seconds", type=int, default=180)
    parser.add_argument("--collection-run-id", default="")
    parser.add_argument("--script-reference-source-id", action="append", default=[],
                        help="可重复：仅向编剧展开指定来源原证据，保留完整20源门禁、概览与高值对照")
    parser.add_argument("--staged-screenplay-bundle", default="",
                        help="核验已审故事与摄影工件后仅作最终双稿复核；失败退回原阶段，不自动改写")
    parser.add_argument("--output-dir", default="data/pre_video_scripts")
    parser.add_argument("--check-sources-only", action="store_true", help="仅核对采样与音画证据，打印缺失清单，不调用编剧或视频接口")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    types = tuple(
        value.strip()
        for value in args.recent_video_types.replace("，", ",").split(",")
        if value.strip()
    )
    try:
        request = PreVideoScriptRequest(
                account_key=args.account_key,
                recent_video_types=types,
                window_days=args.window_days,
                min_relevance=args.min_relevance,
                max_source_videos=args.max_source_videos,
                high_traffic_percentile=args.high_traffic_percentile,
                short_seconds=args.short_seconds,
                long_seconds=args.long_seconds,
                collection_run_id=args.collection_run_id,
                script_reference_source_ids=tuple(args.script_reference_source_id),
                staged_screenplay_bundle_path=args.staged_screenplay_bundle,
                output_dir=args.output_dir,
            )
        service = PreVideoScriptService()
        if args.check_sources_only:
            report = service.source_media_readiness(request, verify_artifacts=True)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['ready'] else 2
        artifact = service.generate(request)
    except (KeyError, ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for label, item in (("短视频版", artifact.short), ("长视频版", artifact.long)):
        print(f"# {label}\n\n" + render_script_markdown(item.script))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
