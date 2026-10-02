"""Route a bound assistant issue list through the original creative task budget."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_workflow import CreativeWorkflow  # noqa: E402
from src.content_factory.creative_workflow_inputs import MaterialBundle, load_materials  # noqa: E402


def bound_workflow(run_dir: Path) -> tuple[CreativeWorkflow, MaterialBundle]:
    manifest = json.loads((run_dir / "materials.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    references = [
        Path(files[key]["path"]) for key in sorted(files)
        if key.startswith("reference_")
    ]
    driver = manifest["source_driver"]
    bundle = load_materials(
        source_driver=driver,
        title=manifest["title"],
        novel_path=Path(files["story_source"]["path"]) if driver == "novel" else None,
        metadata_path=Path(files["metadata"]["path"]) if "metadata" in files else None,
        video_path=Path(files["story_video"]["path"]) if driver == "reference_video" else None,
        analysis_path=Path(files["story_analysis"]["path"]) if driver == "reference_video" else None,
        analysis_end_heading=manifest.get("scope", {}).get("analysis_scope_end_heading", ""),
        reference_paths=references,
        brief_path=Path(files["creative_brief"]["path"]) if "creative_brief" in files else None,
        asset_library_path=Path(files["asset_library"]["path"]) if "asset_library" in files else None,
    )
    workflow = CreativeWorkflow(
        run_dir,
        max_calls=state["max_calls"], max_revisions=state["max_revisions"],
        max_contract_repairs=state.get("max_contract_repairs") or 4,
        budget_policy_version=state["budget_policy_version"],
        max_total_tokens=state["max_total_tokens"],
        logical_task_id=state.get("logical_task_id"),
        creative_focus=state.get("creative_focus", ""),
    )
    return workflow, bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="助手主要问题的同任务定向返修；不提交媒体")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--issues-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    workflow, bundle = bound_workflow(args.run_dir)
    try:
        result = workflow.revise_from_assistant(bundle, args.issues_file)
    except Exception as exc:
        result = json.loads((args.run_dir / "state.json").read_text(encoding="utf-8"))
        print(json.dumps({
            "run_dir": str(args.run_dir.resolve()), "status": result.get("status"),
            "assistant_revision_status": result.get("assistant_revision_status"),
            "calls_started": result.get("calls_started"),
            "revision_rounds": result.get("revision_rounds"),
            "error": str(exc), "automatic_media_submit": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "run_dir": str(args.run_dir.resolve()), "status": result["status"],
        "assistant_revision_status": result.get("assistant_revision_status"),
        "calls_started": result["calls_started"],
        "revision_rounds": result["revision_rounds"],
        "automatic_media_submit": False,
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("assistant_revision_status") == "assistant_recheck_pending" else 2


if __name__ == "__main__":
    raise SystemExit(main())
