from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_candidate_benchmark import (
        run_video_candidate_benchmark,
    )

    parser = argparse.ArgumentParser(
        description="Audit and rank controlled-video candidates.",
    )
    parser.add_argument("manifest", help="video_candidate_benchmark/v1 JSON")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()

    result = run_video_candidate_benchmark(
        args.manifest,
        output_dir=args.output_dir,
        report_path=args.report,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
