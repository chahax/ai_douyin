from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.deterministic_motion import run_deterministic_motion

    parser = argparse.ArgumentParser(
        description="Render and audit a deterministic_motion/v1 manifest."
    )
    parser.add_argument("manifest")
    parser.add_argument("--report")
    parser.add_argument("--qa-dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()

    result = run_deterministic_motion(
        args.manifest,
        report_path=args.report,
        qa_dir=args.qa_dir,
        dry_run=args.dry_run,
        ffmpeg=args.ffmpeg,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0
    return 0 if result["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
