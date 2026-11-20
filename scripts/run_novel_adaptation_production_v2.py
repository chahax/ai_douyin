"""Explicit production acceptance of the authorized acquired novel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preview", "execute", "inspect"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args(argv)
    from src.content_factory import novel_adaptation_production_v2 as pipeline
    try:
        kwargs = {"authorization": args.authorization} if args.command == "prepare" else {}
        if args.command == "prepare" and not args.authorization:
            parser.error("prepare requires --authorization")
        result = getattr(pipeline, args.command)(args.run_dir, **kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") in {"prepared", "text_ready_for_director", "running"} else 1
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "entry_rejected", "error": str(exc), "automatic_media_submit": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
