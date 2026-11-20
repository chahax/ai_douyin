from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_style_gate import run_video_style_gate

    parser = argparse.ArgumentParser(
        description="Check images and accepted videos against one style reference."
    )
    parser.add_argument("manifest")
    parser.add_argument("--report")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    report = run_video_style_gate(
        args.manifest,
        report_path=args.report,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
