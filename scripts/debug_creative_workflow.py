"""Inspect, compare and annotate a creative workflow without model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_stage_debug import CreativeStageCommandService


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="创作阶段调试：只读检查、版本比较或绑定反馈，不调用模型",
    )
    value.add_argument("run_dir", type=Path)
    commands = value.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect")
    commands.add_parser("stop")
    commands.add_parser("resume")
    compare = commands.add_parser("compare")
    compare.add_argument("--stage", required=True)
    compare.add_argument("--base-sha256")
    compare.add_argument("--target-sha256")
    compare.add_argument("--base-input-sha256")
    compare.add_argument("--target-input-sha256")
    feedback = commands.add_parser("feedback")
    feedback.add_argument("--stage", required=True)
    feedback.add_argument("--message", required=True)
    feedback.add_argument("--expected-output-sha256")
    feedback.add_argument("--expected-input-sha256")
    feedback.add_argument(
        "--disposition",
        choices=("must_fix", "suggestion"),
        default="must_fix",
    )
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    service = CreativeStageCommandService(args.run_dir)
    if args.command in ("stop", "resume"):
        from src.content_factory.creative_execution_control import command
        result = command(args.run_dir, args.command)
    elif args.command == "inspect":
        result = service.inspect()
    elif args.command == "compare":
        result = service.compare(
            args.stage,
            base_sha256=args.base_sha256,
            target_sha256=args.target_sha256, base_input_sha256=args.base_input_sha256,
            target_input_sha256=args.target_input_sha256,
        )
    else:
        result = service.feedback(
            args.stage,
            args.message,
            disposition=args.disposition, expected_output_sha256=args.expected_output_sha256,
            expected_input_sha256=args.expected_input_sha256,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
