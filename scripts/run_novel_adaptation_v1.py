"""Novel acquisition and adaptation text route, independent of account cards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="显式获取番茄正文，默认 1 章，不自动重试")
    fetch.add_argument("--output-dir", type=Path, required=True)
    fetch.add_argument("--book-name", required=True)
    fetch.add_argument("--book-id", default="")
    fetch.add_argument("--chapters", type=int, default=1)
    prepare = sub.add_parser("prepare", help="冻结已保存正文和范围；零模型调用")
    prepare.add_argument("--run-dir", type=Path, required=True)
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-path", type=Path)
    source.add_argument("--acquisition-receipt", type=Path)
    prepare.add_argument("--title")
    prepare.add_argument("--book-id")
    prepare.add_argument("--scope", help="本次实际取得章节或选段范围")
    prepare.add_argument("--registry-dir", type=Path)
    prepare.add_argument("--legacy-parent", type=Path)
    prepare.add_argument("--max-calls", type=int, default=20)
    prepare.add_argument("--max-total-tokens", type=int, default=500000)
    prepare.add_argument("--max-revisions", type=int, default=2)
    for name in ("preview", "inspect", "execute"):
        command = sub.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=True)
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
            from src.content_factory import novel_adaptation_pipeline_v1 as pipeline
            result = getattr(pipeline, command)(**kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") not in {
            "acquisition_failed", "needs_attention", "blocked", "incomplete_artifacts"} else 1
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(json.dumps({"status": "entry_rejected", "error": str(exc),
                          "automatic_media_submit": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
