"""Record a version-bound assistant review after actually reading the artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_calibration import (  # noqa: E402
    CATEGORIES, OUTCOMES, calibration_status, record_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="绑定助手实际审阅结论；不能代替视频审核")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--category", choices=CATEGORIES, required=True)
    parser.add_argument("--outcome", choices=OUTCOMES, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    args = parser.parse_args()
    review = record_review(args.run_dir, category=args.category,
                           outcome=args.outcome, evidence_file=args.evidence_file)
    print(json.dumps({"recorded": review["outcome"],
                      "calibration": calibration_status(args.run_dir.parent)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
