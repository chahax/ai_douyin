"""Novel source to reviewed screenplay and director handoff; no media submission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILURE_STATUSES = {
    "acquisition_failed", "entry_rejected", "needs_attention", "blocked",
    "incomplete_artifacts", "evidence_invalid", "legacy_dispatch_blocked",
    "content_revision_exhausted", "director_revision_exhausted", "budget_exhausted",
}


def _require_v7_binding(run_dir):
    binding = Path(run_dir) / "BINDING.json"
    if not binding.is_file():
        return
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("冻结记录含重复字段，不能派发")
            value[key] = item
        return value
    value = json.loads(binding.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)
    if not isinstance(value, dict) or value.get("schema") != "novel_agent_pipeline/v7":
        raise ValueError("历史或未知冻结版本请通过原入口查看；v7 不能迁移或重新派发")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="获取番茄正文；遇到登录/验证即保存停点")
    fetch.add_argument("--output-dir", type=Path, required=True)
    fetch.add_argument("--book-name", required=True)
    fetch.add_argument("--book-id", default="")
    fetch.add_argument("--chapters", type=int, default=1)
    prepare = sub.add_parser("prepare", help="保存新 v7 来源及范围；不调用模型")
    prepare.add_argument("--run-dir", type=Path, required=True)
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-path", type=Path)
    source.add_argument("--acquisition-receipt", type=Path)
    source.add_argument("--saved-book-metadata", type=Path)
    prepare.add_argument("--title")
    prepare.add_argument("--book-id")
    prepare.add_argument("--scope")
    prepare.add_argument("--target-duration-seconds", type=int,
                         help="目标成片时长；作为创作要求冻结，非实际媒体时长")
    prepare.add_argument("--registry-dir", type=Path)
    prepare.add_argument("--max-calls", type=int, default=20)
    prepare.add_argument("--max-total-tokens", type=int, default=500000)
    prepare.add_argument("--max-revisions", type=int, default=2)
    continuation = sub.add_parser("prepare-director-continuation", help="仅承接明确 v6 导演停点；不增加导演候选，不扩大预算")
    continuation.add_argument("--run-dir", type=Path, required=True)
    continuation.add_argument("--parent-run", type=Path, required=True)
    for name in ("preview", "inspect", "execute", "recover-projection"):
        command = sub.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=True)
        if name == "execute":
            command.add_argument("--engine", choices=("native", "langgraph"), default="native")
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        kwargs = vars(args).copy()
        command = kwargs.pop("command")
        if command == "fetch":
            from src.content_factory.novel_adaptation_acquisition_v1 import fetch_source
            result = fetch_source(**kwargs)
        else:
            from src.content_factory import novel_agent_pipeline_v7 as pipeline
            _require_v7_binding(kwargs["run_dir"])
            if command == "prepare":
                target = kwargs.pop("target_duration_seconds")
                if target is not None:
                    if not 60 <= target <= 900:
                        raise ValueError("目标时长须为60–900秒")
                    kwargs["brief"] = {"target_duration_seconds": target}
                metadata = kwargs.pop("saved_book_metadata")
                if metadata is not None:
                    # Never write bridge artifacts into a frozen legacy run.
                    run = kwargs["run_dir"].resolve()
                    if (run / "BINDING.json").exists():
                        raise ValueError("已有冻结任务请查看原记录；不能重新导入或迁移")
                    from src.content_factory.novel_adaptation_acquisition_v1 import import_saved_book
                    bridge = import_saved_book(metadata, run.parent / "acquisitions_v7" / uuid4().hex)
                    kwargs["acquisition_receipt"] = Path(bridge["receipt_path"])
            if command == "execute" and kwargs.pop("engine") == "langgraph":
                from src.content_factory.novel_agent_graph_v7 import execute_graph
                result = execute_graph(**kwargs)
            else:
                result = getattr(pipeline, command.replace("-", "_"))(**kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False))
        return 1 if result.get("status") in FAILURE_STATUSES else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "entry_rejected", "error": str(exc),
                          "automatic_retry": False, "automatic_media_submit": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
