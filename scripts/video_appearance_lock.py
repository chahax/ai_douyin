from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_appearance_lock import lock_video_appearance

    parser = argparse.ArgumentParser(
        description="Lock video lighting and color to a reference image."
    )
    parser.add_argument("input_video")
    parser.add_argument("reference_image")
    parser.add_argument("mask_image")
    parser.add_argument("output_video")
    parser.add_argument("--motion-gain", type=float, default=0.35)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    output = lock_video_appearance(
        args.input_video,
        args.reference_image,
        args.mask_image,
        args.output_video,
        motion_gain=args.motion_gain,
        fps=args.fps,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
