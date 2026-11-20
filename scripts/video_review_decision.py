from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_review_packet import finalize_video_review

    parser = argparse.ArgumentParser(
        description="Finalize strict manual acceptance for a video review packet."
    )
    parser.add_argument("manifest", help="Path to video_review_decision/v1 JSON")
    args = parser.parse_args()

    report = finalize_video_review(args.manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["composition_eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

