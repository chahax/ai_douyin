from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_tool_inventory import scan_video_tool_inventory

    parser = argparse.ArgumentParser(description="Scan local AI-video tool readiness.")
    parser.add_argument("--comfyui-root", default=r"D:\IT\AI_vido\ComfyUI")
    parser.add_argument(
        "--framepack-root",
        default=r"D:\IT\FramePack",
    )
    parser.add_argument("--liveportrait-root", default=r"D:\IT\LivePortrait")
    parser.add_argument("--sadtalker-root", default=r"D:\IT\SadTalker")
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args()

    report = scan_video_tool_inventory(
        comfyui_root=args.comfyui_root,
        framepack_root=args.framepack_root,
        liveportrait_root=args.liveportrait_root,
        sadtalker_root=args.sadtalker_root,
    )
    content = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
