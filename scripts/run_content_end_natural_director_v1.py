"""New content-ended source preparation; legacy run commands stay unchanged."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory import content_end_pacing_v1 as pacing


def _legacy():
    return importlib.import_module("scripts.run_natural_director_v10")


def build_parser():
    return _legacy().build_parser()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    legacy = _legacy()
    args = vars(legacy.build_parser().parse_args(argv))
    if args.pop("command") != "source-prepare":
        return legacy.main(argv)
    try:
        legacy._check_authorization_file(args["authorization_path"])
        brief_path = args.pop("brief_json")
        if brief_path:
            args["brief"] = legacy._json_object(brief_path, "创作要求")
        if args["source_kind"] == "original" and args.get("acquisition_receipt"):
            raise ValueError("原创剧情使用创作简报正文，不使用小说采集回执")
        result = pacing.prepare_source(**args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False))
        return 1 if result.get("status") in legacy.FAILURE_STATUSES else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status="entry_rejected", error=str(exc), automatic_retry=False,
                             automatic_media_submit=False), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
