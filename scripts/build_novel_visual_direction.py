"""Add genre, art bible and shot-level visual direction to a novel storyboard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.content_factory.novel_visual_direction import (
    audit_visual_direction,
    enrich_storyboard_visuals,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()

    storyboard = json.loads(args.storyboard.read_text(encoding="utf-8"))
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    source = args.source.read_text(encoding="utf-8")
    package = enrich_storyboard_visuals(storyboard, metadata, source)
    review = audit_visual_direction(package)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    args.review.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "review": review}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if review["decision"] == "passed" else 2)


if __name__ == "__main__":
    main()
