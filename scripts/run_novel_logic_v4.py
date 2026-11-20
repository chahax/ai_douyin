"""Local P0/P1 diagnostics.  There is deliberately no production execute action."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError(f"Nonfinite JSON value: {value}")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"),
                      object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("diagnose", "benchmark"):
        command = sub.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--output", type=Path)
    replay = sub.add_parser("replay-v3")
    replay.add_argument("--run-dir", type=Path, required=True)
    replay.add_argument("--output", type=Path)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "replay-v3":
            if args.output and args.output.resolve().is_relative_to(args.run_dir.resolve()):
                raise ValueError("Replay output must be outside the preserved production run")
            from src.content_factory.novel_logic_replay_v4 import replay_saved_v3
            result = replay_saved_v3(args.run_dir)
            success = result["status"] == "saved_evidence_verified"
        else:
            from src.content_factory.novel_logic_workflow_v4 import evaluate_bundle, evaluate_corpus
            if args.output and args.input.resolve() == args.output.resolve():
                raise ValueError("Do not overwrite the input evidence")
            value = _load(args.input)
            if args.command == "diagnose":
                result = evaluate_bundle(value)
                success = not result["gate"]["stop_reasons"]
            else:
                result = evaluate_corpus(value)
                success = result["status"] == "fixtures_passed"
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        print(text, end="")
        return 0 if success else 1
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "diagnostic_rejected", "error": str(exc),
                          "production_dispatch_allowed": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
