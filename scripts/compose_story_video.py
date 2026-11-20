#!/usr/bin/env python
"""Compose a story_video/v1 manifest from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.story_video import compose_story_video


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("output")
    args = parser.parse_args()
    print(compose_story_video(args.manifest, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
