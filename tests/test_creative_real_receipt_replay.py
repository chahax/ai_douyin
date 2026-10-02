"""Offline compatibility check against the retained production run, never live APIs."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.content_factory.creative_workflow import CreativeWorkflow, _hash
from src.content_factory.creative_workflow_inputs import load_materials
from tests.test_creative_workflow import FakeClients


ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = ROOT / "data/creative_workflows/say_no_reviewed_segments_20260927"


def _snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_real_receipts_resume_offline_without_reset_or_invalidation(tmp_path):
    if not (REAL_RUN / "state.json").exists():
        pytest.skip("Retained production receipts are local artifacts, absent from this checkout")
    original_files = _snapshot(REAL_RUN)
    saved = json.loads((REAL_RUN / "state.json").read_text(encoding="utf-8"))
    manifest = json.loads((REAL_RUN / "MATERIALS.json").read_text(encoding="utf-8"))
    bundle = load_materials(
        source_driver=manifest["source_driver"], title=manifest["title"],
        brief_path=Path(manifest["files"]["creative_brief"]["path"]),
        asset_library_path=Path(manifest["files"]["asset_library"]["path"]),
    )
    assert _hash(bundle.manifest) == saved["material_sha256"]
    run = tmp_path / "production_receipt_replay"
    shutil.copytree(REAL_RUN, run)
    stage_files = {}
    for path in run.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("schema") == "creative_stage/v1":
            stage_files[path.name] = path.read_bytes()
    assert stage_files, "Must replay actual model receipts, not an empty fixture"
    receipt_files = {p.name: p.read_bytes() for p in run.glob("*.json")
                     if p.name.startswith(("writer_", "director_", "script_review"))}
    clients = FakeClients([])  # Any attempted call records itself and immediately fails.
    workflow = CreativeWorkflow(
        run, clients=clients,
        creative_focus=saved["creative_focus"], logical_task_id=saved["logical_task_id"],
        max_calls=saved["max_calls"], max_total_tokens=saved["max_total_tokens"],
        max_revisions=saved["max_revisions"],
        max_contract_repairs=saved["max_contract_repairs"],
        budget_policy_version=saved["budget_policy_version"],
    )
    state = workflow.run(bundle)
    assert clients.calls == []
    assert state["status"] == "needs_revision"
    assert state["blocked_segment"] == "B4"
    assert state["calls_started"] == saved["calls_started"] == 30
    assert state["revision_rounds"] == saved["revision_rounds"] == 6
    assert state["contract_repairs_used"] == saved["contract_repairs_used"] == 4
    for key in ("max_calls", "max_revisions", "max_contract_repairs", "max_total_tokens",
                "logical_task_id", "revision_committed", "segmented_director_binding",
                "writer_prompt_binding", "review_policy_version"):
        assert state[key] == saved[key], key
    for name, contents in receipt_files.items():
        assert (run / name).read_bytes() == contents, name
    assert {p.name for p in run.glob("*stale_parent*")} == {
        p.name for p in REAL_RUN.glob("*stale_parent*")}
    assert not (run / "MEDIA_HANDOFF.json").exists()
    assert _snapshot(REAL_RUN) == original_files, "Read-only production source was modified"

