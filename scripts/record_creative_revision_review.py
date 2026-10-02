"""Bind the assistant's actual reread of a revised creative draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_calibration import record_revision_review  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="绑定当前返修稿的助手复核结论")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--outcome", choices=("passed", "major_issues"), required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    review = record_revision_review(args.run_dir, outcome=args.outcome,
                                    evidence_file=args.evidence_file)
    print(json.dumps({"recorded": review["outcome"],
                      "draft_sha256": review["draft_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
