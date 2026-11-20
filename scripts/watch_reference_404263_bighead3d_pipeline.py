"""Wait for all big-head 3D clips and compose the review-only candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QA = ROOT / "data/qa/reference_404263_bighead3d_full_20260826"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(path: Path, payload: dict[str, object]) -> None:
    payload = {**payload, "updated_at": now(), "publish_allowed": False}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def completed_ids(report_path: Path, clip_dir: Path) -> set[str]:
    if not report_path.is_file():
        return set()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        str(item["id"])
        for item in report
        if item.get("status") == "generated" and (clip_dir / f"{item['id']}.mp4").is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--timeout-hours", type=float, default=24.0)
    args = parser.parse_args()
    qa_root = args.qa_root.resolve()
    project_path = qa_root / "story_project.json"
    video_run = qa_root / "video_run"
    clip_dir = video_run / "clips"
    report_path = video_run / "run_report.json"
    status_path = qa_root / "autopipeline_status.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    required = [str(shot["id"]) for shot in project["shots"]]
    deadline = time.time() + args.timeout_hours * 3600
    write_status(
        status_path,
        {"state": "waiting_for_clips", "completed": 0, "required": len(required), "missing": required},
    )
    while time.time() < deadline:
        done = completed_ids(report_path, clip_dir)
        missing = [shot_id for shot_id in required if shot_id not in done]
        write_status(
            status_path,
            {
                "state": "waiting_for_clips" if missing else "clips_complete",
                "completed": len(done),
                "required": len(required),
                "missing": missing,
            },
        )
        if not missing:
            break
        time.sleep(max(5, min(args.poll_seconds, 60)))
    else:
        write_status(
            status_path,
            {
                "state": "timed_out",
                "completed": len(completed_ids(report_path, clip_dir)),
                "required": len(required),
            },
        )
        return 2

    write_status(status_path, {"state": "composing", "completed": len(required), "required": len(required)})
    composer = ROOT / "scripts/compose_reference_404263_bighead3d_candidate.py"
    result = subprocess.run(
        [sys.executable, str(composer), "--project", str(project_path), "--video-run", str(video_run)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=4 * 3600,
    )
    log_path = qa_root / "autopipeline_compose.log"
    log_path.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        write_status(
            status_path,
            {
                "state": "compose_failed",
                "completed": len(required),
                "required": len(required),
                "returncode": result.returncode,
                "log_path": str(log_path),
            },
        )
        return result.returncode
    final = qa_root / "candidate/reference_404263_bighead3d_full_candidate_v1.mp4"
    manifest = qa_root / "candidate/candidate_v1.manifest.json"
    if not final.is_file() or not manifest.is_file():
        write_status(
            status_path,
            {"state": "compose_output_missing", "final": str(final), "manifest": str(manifest)},
        )
        return 3
    write_status(
        status_path,
        {
            "state": "complete_review_pending",
            "completed": len(required),
            "required": len(required),
            "final": str(final),
            "manifest": str(manifest),
            "release_status": "not_authorized",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
