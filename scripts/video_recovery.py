from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_recovery import (
        recommend_video_recovery,
        write_video_recovery_report,
    )

    parser = argparse.ArgumentParser(
        description="Recommend one controlled action for a rejected AI-video report."
    )
    parser.add_argument("manifest")
    parser.add_argument("--output")
    args = parser.parse_args()

    report = (
        write_video_recovery_report(args.manifest, args.output)
        if args.output
        else recommend_video_recovery(args.manifest)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
