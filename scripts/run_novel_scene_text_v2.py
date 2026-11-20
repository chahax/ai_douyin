"""Explicit CLI for the bounded novel scene/event continuation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.content_factory.novel_scene_text_v2 import prepare, preview, execute, inspect  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preview", "execute", "inspect"))
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--parent-run", type=Path)
    parser.add_argument("--diagnostics", type=Path, help="可选：经核实的旧问题JSON文本列表，只作返修需求")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            if args.parent_run is None:
                parser.error("prepare需要--parent-run")
            diagnostics = json.loads(args.diagnostics.read_text(encoding="utf-8-sig")) if args.diagnostics else None
            if diagnostics is not None and (not isinstance(diagnostics, list) or any(not isinstance(row, str) for row in diagnostics)):
                raise ValueError("诊断必须是JSON文本列表")
            result = prepare(args.parent_run, args.run_dir, diagnostics=diagnostics)
        else:
            result = {"preview": preview, "execute": execute, "inspect": inspect}[args.command](args.run_dir)
    except Exception as exc:
        result = {**inspect(args.run_dir), "status": "needs_attention", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("prepared", "machine_text_complete") else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
