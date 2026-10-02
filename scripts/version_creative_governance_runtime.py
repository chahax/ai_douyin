"""Create a new frozen governance pack with current runtime-source hashes only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "data/creative_governance/20261002_v22_platform_refactor_workbench"
DEFAULT_OUTPUT = ROOT / "data/creative_governance/20261002_v23_feedback_consistency"
NEW_RUNTIME_SOURCES = (
    "src/content_factory/creative_workflow.py",
    "src/content_factory/creative_stage_debug.py",
    "src/content_factory/media_review_policy.py",
    "src/scheduler/queue.py",
    "scripts/debug_creative_workflow.py",
    "src/content_factory/creative_stage_runtime.py",
    "src/content_factory/creative_state_store.py",
    "src/content_factory/creative_calibration.py",
    "src/content_factory/creative_stage_contracts.py",
    "src/content_factory/creative_execution_control.py",
    "src/content_factory/creative_segment_execution.py",
    "src/content_factory/creative_media_workbench.py",
    "src/content_factory/creative_delivery.py",
    "src/content_factory/creative_quality_evidence.py",
    "src/web/creative_workflow_dashboard.py",
    "src/web/creative_workbench_panel.py",
    "scripts/run_creative_seedance_segment.py",
    "scripts/compile_creative_seedance_segments.py",
    "scripts/creative_workbench.py",
    "src/platform_adapter/douyin_adapter.py",
    "src/platform_adapter/publish_workflow.py",
    "src/platform_adapter/publish_verification.py",
    "src/platform_adapter/models.py",
    "src/platform_adapter/ai_content_declaration.py",
    "src/platform_adapter/browser_session.py",
    "src/services/content_performance.py",
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def version_runtime_binding(base: Path, output: Path) -> dict:
    base = base.resolve()
    output = output.resolve()
    if not base.is_dir():
        raise FileNotFoundError(base)
    if output.exists():
        raise RuntimeError("Frozen output already exists; choose a new version directory")
    if not base.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        raise RuntimeError("Governance packs must remain below the repository root")

    shutil.copytree(base, output)
    created = datetime.now(timezone.utc).isoformat()
    runtime_path = output / "runtime_sources.json"
    previous_runtime_hash = file_hash(runtime_path)
    runtime = read_json(runtime_path)
    source_paths = [row["path"] for row in runtime["sources"]]
    for source_path in NEW_RUNTIME_SOURCES:
        if source_path not in source_paths:
            source_paths.append(source_path)
    runtime["created_at"] = created
    runtime["sources"] = [
        {"path": source_path, "sha256": file_hash(ROOT / source_path)}
        for source_path in source_paths
    ]
    runtime["supersedes"] = str(base.relative_to(ROOT)).replace("\\", "/")
    runtime["change"] = (
        "F01/P1 in-flight feedback consistency: serialized versioned state commits, immutable "
        "feedback/control command replay and crash recovery, dispatch permits, exact consumed-feedback "
        "resolution and late-feedback rebasing; existing budgets, histories and human review policy retained."
    )
    runtime["revision_note"] = (
        f"Historical {base.name} pack remains unchanged. Existing runs remain historical "
        "and must not be silently rebound; see MIGRATION.md for explicit restart/revalidation."
    )
    write_json(runtime_path, runtime)

    receipt = {
        "schema_version": "creative_governance_runtime_upgrade/v1",
        "created_at": created,
        "base_directory": str(base.relative_to(ROOT)).replace("\\", "/"),
        "base_artifact_manifest_sha256": file_hash(base / "artifact_manifest.json"),
        "base_runtime_sources_sha256": previous_runtime_hash,
        "runtime_sources_sha256": file_hash(runtime_path),
        "semantic_rules_changed": False,
        "quality_claim_added": False,
        "media_review_performed": False,
        "existing_task_migration": (
        f"{base.name} task state is never silently rebound. Completed runs remain immutable history. "
        f"Keep in-progress {base.name} runs under their original frozen environment. "
        "The current CLI binds the same intent to its original run and budget; no automatic "
        "same-intent cross-version migration is exposed. A source/hash mismatch stops before "
        "dispatch. Do not change the creative focus, delete a registry claim, or create a new "
        "directory merely to obtain fresh quota. New independent stories use the existing "
        "registration entry. Any future migration must carry cumulative budget, receipts and "
        "unresolved feedback and revalidate every adopted artifact before external effects."
        ),
    }
    write_json(output / "runtime_upgrade_receipt.json", receipt)
    (output / "MIGRATION.md").write_text(
        f"# {base.name} → {output.name} task migration\n\n"
        f"{base.name} is immutable history and is not silently rebound. Completed runs "
        f"remain historical records. An archived {base.name} run retains its original task identity, "
        "budget and receipts. The current CLI binds the same intent to its original run directory. "
        "There is no automatic same-intent cross-version migration command. Restore the old "
        "frozen runtime environment to continue that run, or keep it read-only. Source/hash "
        "mismatch must stop before dispatch. Do not delete claims, change focus for the same "
        "story or create a directory to reset quota. New independent stories use the existing "
        "registration entry and bind the new governance pack.\n\n"
        "A future explicit migration must preserve cumulative calls/tokens/revision/video "
        "failure budgets, link every historical receipt and unresolved feedback, revalidate "
        "carried artifacts and obtain human reapproval wherever candidate identity changes. "
        "This release does not perform such a migration or modify historical user tasks.\n",
        encoding="utf-8",
    )

    documentation = output / "implementation_documents"
    documentation.mkdir(exist_ok=True)
    for source in ("docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md", "docs/CREATIVE_STAGE_DEBUGGING.md",
                   "docs/CURRENT_CAPABILITIES.md", "docs/SYSTEM_ARCHITECTURE.md", "README.md"):
        shutil.copyfile(ROOT / source, documentation / Path(source).name)
    write_json(output / "platform_refactor_contract.json", {
        "schema": "creative_platform_refactor_contract/v1", "priorities": ["P1", "P2", "P3", "P4"],
        "source_direction_report": "data/qa/creative_platform_refactor_20261002/direction_report.html",
        "direction_report_sha256": file_hash(ROOT / "data/qa/creative_platform_refactor_20261002/direction_report.html"),
        "stage_input_schema": "creative_stage_input/v1", "stage_result_schema": "creative_stage_result/v1",
        "automatic_media_review": False, "automatic_paid_submit": False, "quality_improvement_verified": False,
        "state_command_schema": "creative_state_command/v1",
        "source_implementation_review": "data/qa/creative_platform_refactor_20261002/implementation_review_v22/review_report.html",
        "implementation_review_sha256": file_hash(ROOT / "data/qa/creative_platform_refactor_20261002/implementation_review_v22/review_report.html"),
        "historical_packs_retained": ["20261002_v22_platform_refactor_workbench", "20261002_v21_platform_refactor_multi_feedback", "20261002_v20_platform_refactor_repair_resume"]})
    manifest_path = output / "artifact_manifest.json"
    manifest = read_json(manifest_path)
    manifest["created_at"] = created
    manifest["supersedes"] = str(base.relative_to(ROOT)).replace("\\", "/")
    manifest["change"] = "Versioned F01/P1 feedback consistency runtime and implementation contract rebind."
    manifest["artifacts"] = [
        {
            "path": str(path.relative_to(output)).replace("\\", "/"),
            "sha256": file_hash(path),
        }
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != manifest_path
    ]
    write_json(manifest_path, manifest)
    return {
        "output": str(output.relative_to(ROOT)).replace("\\", "/"),
        "artifact_count": len(manifest["artifacts"]),
        "runtime_source_count": len(runtime["sources"]),
        "artifact_manifest_sha256": file_hash(manifest_path),
        "runtime_sources_sha256": file_hash(runtime_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline versioning only; never invokes models, video, or publishing APIs."
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(version_runtime_binding(args.base, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
