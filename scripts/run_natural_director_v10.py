"""Explicit authorized natural-director text trials; no media dispatch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILURE_STATUSES = {"entry_rejected", "needs_attention", "round_limit_exhausted", "budget_exhausted",
                    "evidence_invalid", "incomplete_artifacts", "blocked", "legacy_dispatch_blocked",
                    "content_revision_exhausted", "director_revision_exhausted", "campaign_review_required",
                    "upstream_writer_revision_required", "awaiting_local_completion"}


def _json_object(path, label):
    path = Path(path)
    if not path.is_file():
        raise ValueError(label + "文件不存在")
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError(label + "含重复字段：" + key)
            value[key] = item
        return value
    def constant(value):
        raise ValueError(label + "不能包含非有限数值：" + value)
    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError(label + "必须是完整JSON对象")
    return value


def _check_authorization_file(path):
    """Validate readable complete JSON only; the runtime owns authorization scope."""
    _json_object(path, "准备自然导演测试所需的实际授权")
    return Path(path)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="核验授权文件并承接原来源、完整稿及总预算，不调用模型")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--parent-run", type=Path, required=True)
    prepare.add_argument("--authorization-path", type=Path, required=True)
    source = commands.add_parser("source-prepare", help="新来源冻结writer-only路线，导演统一进入自然文本v10")
    source.add_argument("--source-run-dir", type=Path, required=True)
    source.add_argument("--authorization-path", type=Path, required=True)
    source.add_argument("--source-kind", choices=("novel", "original"), default="novel")
    source_input = source.add_mutually_exclusive_group(required=True)
    source_input.add_argument("--source-path", type=Path)
    source_input.add_argument("--acquisition-receipt", type=Path)
    source.add_argument("--title")
    source.add_argument("--book-id")
    source.add_argument("--scope")
    source.add_argument("--brief-json", type=Path)
    execute_source = commands.add_parser("source-execute", help="编剧审核与自然导演；已知完整故障经严格核验后各恢复一次")
    execute_source.add_argument("--source-run-dir", type=Path, required=True)
    execute_source.add_argument("--run-dir", type=Path, required=True)
    execute_source.add_argument("--authorization-path", type=Path, required=True)
    for name in ("source-preview", "source-inspect"):
        command = commands.add_parser(name)
        command.add_argument("--source-run-dir", type=Path, required=True)
    for name in ("preview", "execute", "inspect", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = vars(build_parser().parse_args(argv))
    command = args.pop("command")
    try:
        if command in {"prepare", "source-prepare", "source-execute"}:
            _check_authorization_file(args["authorization_path"])
        if command == "source-prepare":
            brief_path = args.pop("brief_json")
            if brief_path:
                args["brief"] = _json_object(brief_path, "创作要求")
            if args["source_kind"] == "original" and args.get("acquisition_receipt"):
                raise ValueError("原创剧情使用创作简报正文，不使用小说采集回执")
        from src.content_factory import natural_director_pipeline_v10 as pipeline
        method = {"recover": "recover_projection", "source-prepare": "prepare_source",
                  "source-execute": "execute_source", "source-preview": "preview_source",
                  "source-inspect": "inspect_source"}.get(command, command)
        if command == "source-execute":
            from src.content_factory import natural_director_source_runner_v11 as source_runner
            result = source_runner.execute_source(**args)
        elif command == "source-prepare":
            from src.content_factory import visual_storytelling_v1 as visual
            binding_path = args["source_run_dir"] / "BINDING.json"
            # Preserve legacy preparation/recovery semantics for frozen runs.
            # Only new sources receive new creative rules automatically.
            frozen = _json_object(binding_path, "原来源绑定") if binding_path.exists() else None
            if frozen is not None and visual.BRIEF_KEY not in (frozen.get("brief") or {}):
                result = pipeline.prepare_source(**args)
            else:
                result = visual.prepare_source(runtime=pipeline, **args)
        else:
            result = getattr(pipeline, method)(**args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False))
        return 1 if result.get("status") in FAILURE_STATUSES else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "entry_rejected", "error": str(exc), "automatic_retry": False,
                          "automatic_media_submit": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
