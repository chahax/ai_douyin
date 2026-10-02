"""Export a revised text handoff only after its bound assistant review passes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.revise_creative_from_assistant import bound_workflow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="提升实际复核通过的返修稿；不提交媒体")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    workflow, bundle = bound_workflow(args.run_dir)
    state = workflow.promote_reviewed_assistant_revision(bundle)
    print(json.dumps({
        "run_dir": str(args.run_dir.resolve()), "status": state["status"],
        "revised_handoff_sha256": state["revised_handoff_sha256"],
        "automatic_media_submit": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
