"""Record an explicit user decision without inspecting media content."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.media_review_policy import record_user_media_decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("decision", choices=("approved", "rejected"))
    parser.add_argument("--user-statement", required=True)
    args = parser.parse_args(argv)
    result = record_user_media_decision(
        args.receipt,
        args.decision,
        args.user_statement,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
