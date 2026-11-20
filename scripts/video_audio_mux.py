from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_audio_mux import mux_portrait_voiceover

    parser = argparse.ArgumentParser(
        description="Loop controlled portrait motion and mux a voiceover track."
    )
    parser.add_argument("manifest", help="Path to video_audio_mux/v1 JSON")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    report = mux_portrait_voiceover(
        args.manifest,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

