"""Prepare, submit once, or query a source-bound first novel video segment."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "inspect", "submit", "query"):
        item = sub.add_parser(name)
        item.add_argument("--run-dir", type=Path, required=True)
        if name == "prepare":
            item.add_argument("--source-run", type=Path, required=True)
    args = parser.parse_args(argv)
    from src.content_factory import novel_video_trial_v1 as trial
    try:
        result = trial.prepare(args.run_dir, source_run=args.source_run) if args.command == "prepare" else getattr(trial, args.command)(args.run_dir)
    except Exception as exc:
        print(json.dumps({"status": "stopped", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result.get("status") in {"evidence_invalid", "failed", "cancelled", "expired"})


if __name__ == "__main__":
    raise SystemExit(main())
