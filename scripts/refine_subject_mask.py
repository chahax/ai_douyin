from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_mask import refine_subject_mask

    parser = argparse.ArgumentParser(description="Fill holes and feather a subject mask.")
    parser.add_argument("input", help="Input mask image")
    parser.add_argument("output", help="Output mask image")
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--grow", type=int, default=0)
    parser.add_argument("--feather", type=float, default=0.0)
    args = parser.parse_args()

    with Image.open(args.input) as image:
        refined = refine_subject_mask(
            image,
            threshold=args.threshold,
            grow=args.grow,
            feather=args.feather,
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    refined.save(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
