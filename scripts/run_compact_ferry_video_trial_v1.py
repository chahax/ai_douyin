"""Prepare one compact-ferry S01, submit once, or GET its original task ID."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import compact_ferry_video_trial_v1 as trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "submit", "query", "inspect"))
    parser.add_argument("--run-dir", type=Path, default=trial.DEFAULT_RUN)
    args = parser.parse_args()
    result = getattr(trial, args.operation)(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "evidence_invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
