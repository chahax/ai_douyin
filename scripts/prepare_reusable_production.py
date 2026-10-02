"""Prepare the next reusable video-production work package without paid calls."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.content_factory.reusable_production import prepare_next_work, register_asset  # noqa: E402


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--asset-library", type=Path, default=ROOT / "data/visual_asset_library/reusable_assets.json")
    parser.add_argument("--register-asset", type=Path, help="登记已有真实图像审核与生成回执的素材描述JSON")
    args = parser.parse_args(argv)
    try:
        if args.register_asset:
            register_asset(args.run_dir, args.register_asset)
        result = prepare_next_work(args.run_dir, args.asset_library)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "needs_attention", "error": str(exc), "automatic_submit": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
