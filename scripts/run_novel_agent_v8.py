"""Unified v8 novel/original text workflow; reviewed request previews, no media POST."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION = "novel_agent_pipeline/v8"
FAILURE_STATUSES = {
    "acquisition_failed", "entry_rejected", "needs_attention", "blocked",
    "incomplete_artifacts", "evidence_invalid", "legacy_dispatch_blocked",
    "content_revision_exhausted", "director_revision_exhausted", "budget_exhausted",
    "quality_review_failed", "quality_revision_exhausted",
}


def _require_v8_binding(run_dir):
    path = Path(run_dir) / "BINDING.json"
    if not path.is_file():
        return
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("冻结记录含重复字段，不能派发")
            result[key] = value
        return result
    binding = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)
    if not isinstance(binding, dict) or binding.get("schema") != VERSION:
        raise ValueError("历史或未知冻结版本请通过原入口查看；v8不能迁移或重新派发")


def _load_brief(path):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("创作要求含重复字段：" + key)
            value[key] = item
        return value
    def constant(value):
        raise ValueError("创作要求不能包含非有限数值：" + value)
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                       object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("创作要求必须是完整JSON对象")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="获取番茄正文，登录/验证时保存停点")
    fetch.add_argument("--output-dir", type=Path, required=True)
    fetch.add_argument("--book-name", required=True)
    fetch.add_argument("--book-id", default="")
    fetch.add_argument("--chapters", type=int, default=1)
    prepare = sub.add_parser("prepare", help="冻结v8来源与质量规范，不调用模型")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--source-kind", choices=("novel", "original"), default="novel")
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-path", type=Path)
    source.add_argument("--acquisition-receipt", type=Path)
    source.add_argument("--saved-book-metadata", type=Path)
    prepare.add_argument("--title")
    prepare.add_argument("--book-id")
    prepare.add_argument("--scope")
    prepare.add_argument("--target-duration-seconds", type=int)
    prepare.add_argument("--brief-json", type=Path, help="新创作要求完整JSON对象，原样冻结")
    prepare.add_argument("--max-calls", type=int, default=20)
    prepare.add_argument("--max-total-tokens", type=int, default=500000)
    prepare.add_argument("--max-revisions", type=int, default=2)
    revision = sub.add_parser("prepare-quality-revision", help="显式承接质量修订，继承预算和永久同源claim")
    revision.add_argument("--run-dir", type=Path, required=True)
    revision.add_argument("--parent-run", type=Path, required=True)
    revision.add_argument("--brief-json", type=Path, help="显式新质量修订要求；不修改原预算")
    for name in ("preview", "inspect", "execute", "recover-projection"):
        command = sub.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=True)
        if name == "execute":
            command.add_argument("--engine", choices=("native", "langgraph"), default="native")
    return parser


def main(argv=None):
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
            from src.content_factory import novel_agent_pipeline_v8 as pipeline
            _require_v8_binding(kwargs["run_dir"])
            if command in {"prepare", "prepare-quality-revision"}:
                brief_path = kwargs.pop("brief_json")
                if brief_path:
                    kwargs["brief"] = _load_brief(brief_path)
            if command == "prepare":
                metadata = kwargs.pop("saved_book_metadata")
                if kwargs["source_kind"] == "original" and (metadata or kwargs.get("acquisition_receipt")):
                    raise ValueError("原创剧情使用用户创作简报正文source-path，不能使用小说采集回执或元数据")
                target = kwargs.pop("target_duration_seconds")
                brief = kwargs.get("brief", {})
                if brief.get("source_kind", kwargs["source_kind"]) != kwargs["source_kind"]:
                    raise ValueError("创作要求source_kind与--source-kind冲突")
                if target is not None:
                    if not 60 <= target <= 900:
                        raise ValueError("目标时长须为60–900秒")
                    if "target_duration_seconds" in brief and brief["target_duration_seconds"] != target:
                        raise ValueError("目标时长与创作要求JSON冲突")
                    kwargs["brief"] = {**brief, "target_duration_seconds": target}
                if metadata:
                    run = kwargs["run_dir"].resolve()
                    if (run / "BINDING.json").exists():
                        raise ValueError("已有冻结任务不能重新导入或迁移")
                    from src.content_factory.novel_adaptation_acquisition_v1 import import_saved_book
                    bridge = import_saved_book(metadata, run.parent / "acquisitions_v8" / uuid4().hex)
                    kwargs["acquisition_receipt"] = Path(bridge["receipt_path"])
            if command == "execute" and kwargs.pop("engine") == "langgraph":
                from src.content_factory.novel_agent_graph_v8 import execute_graph
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
