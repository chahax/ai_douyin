from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_smoothness import run_video_smoothness

    parser = argparse.ArgumentParser(
        description="Interpolate an accepted video and verify cadence improvement."
    )
    parser.add_argument("manifest")
    parser.add_argument("--report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    report = run_video_smoothness(
        args.manifest,
        report_path=args.report,
        dry_run=args.dry_run,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.dry_run or report["status"] == "no_action":
        return 0
    return 0 if report["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
