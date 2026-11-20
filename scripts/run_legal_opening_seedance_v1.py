"""One authorized legal opening through existing submission/review ledgers."""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.creative_legal_director_performance_v1 import compile_complete
from src.content_factory.creative_segment_execution import read, reserve_media_attempt, sha
from src.content_factory.creative_stage_contracts import digest, persist
from src.content_factory.media_review_policy import mark_saved_candidate
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig

BUNDLE = ROOT / "data/production_revisions/legal_director_performance_20261008/round_06/DELIVERABLE_d1"
OUT = ROOT / "data/video_generation/legal_trend_20261008/opening_SH01_v1"
LOGICAL_TASK = "legal_trend_text_trial_20261008_adopted_r8"
USER_STATEMENT = "先做一段"

def now():
    return datetime.now(timezone.utc).isoformat()

def make_plan(bundle=BUNDLE):
    bundle = Path(bundle).resolve()
    manifest = read(bundle / "MANIFEST.json")
    for name, expected in manifest["files"].items():
        if sha(bundle / name) != expected:
            raise ValueError("frozen handoff changed: " + name)
    script = read(bundle / "FULL_SCRIPT.json")
    direction = read(bundle / "WHOLE_FILM_DIRECTION.json")
    performances = read(bundle / "ACTUAL_BEAT_PERFORMANCES.json")
    compiled = read(bundle / "COMPILED_PERFORMANCE.json")
    if compile_complete(script, direction, performances) != compiled:
        raise ValueError("compiled schedule no longer matches complete sources")
    adoption = read(bundle / "HUMAN_SCRIPT_ADOPTION.json")
    review = read(bundle / "FULL_TEXT_REVIEW.json")
    if adoption["script_sha256"] != compiled["script_sha256"]:
        raise ValueError("adopted script binding mismatch")
    if not review["story_preserved"] or review["issues"]:
        raise ValueError("unresolved full-text review")
    shot, row = compiled["shots"][0], compiled["schedule"][0]
    if (shot["shot_id"] != "SH01" or shot["source_refs"] != ["B1.S01"]
            or row["source_ref"] != "B1.S01" or row["source_kind"] != "action"
            or row["speaker"] or shot["duration"] != 9.0):
        raise ValueError("authorization covers only the nine-second opening")
    # Project adopted performance once, in order; no manual action/dialogue patch.
    prompt = "\n".join([
        "9秒竖屏写实职场短片，单个连续镜头。中国当代普通公司，真实室内日光，克制自然的表演。",
        "小林是被约来谈话的劳动者，周姐是人事主管，普通通勤装，两人对坐。深色长方形会议桌，透明玻璃隔断外是模糊办公区。",
        "机位与构图：" + shot["framing"] + " 固定机位，脸、双手和纸笔所在桌面持续可见。",
        "起始停顿：" + row["before_performance"],
        "随后连续完成：" + row["active_performance"],
        "动作完成后留出观察停顿：" + row["after_performance"],
        "本段止于周姐开口前，没有对白、旁白、字幕或配乐，只保留自然办公室底噪及椅子、文件的轻微声响。纸保持正面朝下，小林不拿笔、不签字；镜头不转场，不插入特写。",
    ])
    sources = {name: {"path": str(bundle / name), "sha256": expected}
               for name, expected in manifest["files"].items()}
    sources["handoff_manifest"] = {"path": str(bundle / "MANIFEST.json"), "sha256": sha(bundle / "MANIFEST.json")}
    old = ROOT / "data/video_generation/sequential_workflow_20260908/campaign.json"
    return {
        "schema": "legal_seedance_opening_plan/v1", "logical_task_id": LOGICAL_TASK,
        "segment_id": "SH01", "shot_id": "SH01", "source_refs": ["B1.S01"], "sources": sources,
        "script_content_sha256": compiled["script_sha256"],
        "authorization": {"source": "current_conversation_user_message", "user_statement": USER_STATEMENT,
                          "max_new_submissions": 1, "scope": "current legal film SH01 only",
                          "automatic_retry": False, "later_segments_authorized": False, "publishing_authorized": False},
        "provider": "ark_api", "model": "doubao-seedance-2-0-mini-260615",
        "duration_seconds": 9, "ratio": "9:16", "resolution": "480p",
        "generate_audio": True, "return_last_frame": True, "task_type": "text", "reference_count": 0,
        "prompt": prompt, "prompt_sha256": digest(prompt), "shot_snapshot": shot, "performance_snapshot": row,
        "timing_contract": {"before_seconds": 2, "active_seconds": 5.5, "after_seconds": 1.5,
                            "service_control": "ordered prose; exact timings require human review"},
        "aesthetic_status": "first unconfirmed candidate; no adopted legal-film visual assets",
        "historical_campaign": {"path": str(old), "sha256_before": sha(old)},
        "script_failure_budget": "existing reserve_media_attempt; fixed story identity; ten failures; no reset",
    }

def validate_plan(plan):
    if plan["logical_task_id"] != LOGICAL_TASK or plan["segment_id"] != "SH01":
        raise ValueError("not the authorized opening")
    if plan["authorization"]["user_statement"] != USER_STATEMENT or make_plan() != plan:
        raise ValueError("authorization or source-bound opening plan changed")

def request_for(client, plan):
    return client.build_task_payload(plan["prompt"], duration=9, ratio="9:16", resolution="480p",
        generate_audio=True, watermark=False, return_last_frame=True, task_type="text")

def execute(operation, client, out=OUT):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    plan_path, receipt = out / "PLAN.json", out / "receipt.json"
    if operation == "prepare":
        if receipt.exists():
            raise ValueError("already submitted; query original receipt")
        plan = make_plan()
        if plan_path.exists() and read(plan_path) != plan:
            raise ValueError("prepared plan differs; preserve existing binding")
        persist(plan_path, plan)
        (out / "PROMPT.txt").write_text(plan["prompt"] + "\n", encoding="utf-8")
        persist(out / "REQUEST.preview.json", request_for(client, plan))
        return {"status": "prepared", "output": str(out), "duration": 9, "reference_count": 0}
    if operation == "submit":
        plan = read(plan_path)
        validate_plan(plan)
        if client.config.provider != plan["provider"] or client.config.model != plan["model"]:
            raise ValueError("provider/model differs; no automatic switch")
        request = request_for(client, plan)
        if read(out / "REQUEST.preview.json") != request:
            raise ValueError("actual request differs from prepared preview")
        record = {"schema": "legal_seedance_opening_receipt/v1", "status": "submitting",
                  "technical_status": "running", "content_status": "not_available",
                  "provider": plan["provider"], "model": plan["model"], "logical_task_id": LOGICAL_TASK,
                  "segment_id": "SH01", "shot_id": "SH01", "plan": str(plan_path),
                  "plan_sha256": sha(plan_path), "plan_snapshot": plan, "source_bindings": plan["sources"],
                  "request": request, "request_sha256": digest(request), "created_at": now(),
                  "new_submissions": 1, "automatic_retry": False}
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
        try:
            reserve_media_attempt(plan_path, plan, receipt)
        except Exception as exc:
            record.update(status="blocked_before_submit", technical_status="not_submitted",
                          new_submissions=0, error=str(exc))
            persist(receipt, record)
            raise
        try:
            created = client.create_task(request)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            rejected = isinstance(status_code, int) and 400 <= status_code < 500
            record.update(status="request_rejected" if rejected else "submit_outcome_unknown",
                          technical_status="failed" if rejected else "unknown", http_status=status_code,
                          error_code=getattr(exc, "error_code", None), error=str(exc))
            persist(receipt, record)
            raise
        record.update(status="submitted", task_id=created["id"], created=created)
        persist(receipt, record)
        return {"status": record["status"], "task_id": record["task_id"]}
    if operation != "query":
        raise ValueError("unknown operation")
    record = read(receipt)
    if not record.get("task_id"):
        raise ValueError("no task ID: reconcile unknown result; never resubmit")
    if record.get("technical_status") == "succeeded":
        if sha(record["video_path"]) != record["video_sha256"]:
            raise ValueError("saved video changed")
        return {k: record[k] for k in ("status", "task_id", "video_path", "content_status")}
    # Original-ID query/download never invokes create_task.
    task = client.get_task(record["task_id"])
    record.update(latest_response=task, last_queried_at=now(), status=task["status"])
    persist(receipt, record)
    if task["status"] in ("failed", "expired", "cancelled"):
        record.update(technical_status="failed", completed_at=now())
        persist(receipt, record)
    elif task["status"] == "succeeded":
        video = client.download_video(task, out / "SH01.mp4")
        if not video.stat().st_size:
            raise ValueError("empty saved video")
        record.update(video_path=str(video), video_sha256=sha(video), video_bytes=video.stat().st_size)
        if task.get("content", {}).get("last_frame_url"):
            tail = client.download_last_frame(task, out / "SH01.provider_last.png")
            if not tail.stat().st_size:
                raise ValueError("empty provider last frame")
            record.update(last_frame=str(tail), last_frame_sha256=sha(tail),
                          last_frame_source="generation_service_original", tail_status="saved_unapproved")
        else:
            record.update(tail_status="not_returned; continuation blocked", last_frame=None)
        record.update(completed_at=now(), human_decision=None, next_segment_dispatch_allowed=False,
                      historical_campaign_unchanged=sha(record["plan_snapshot"]["historical_campaign"]["path"])
                      == record["plan_snapshot"]["historical_campaign"]["sha256_before"])
        mark_saved_candidate(record)
        persist(receipt, record)
    return {k: record.get(k) for k in ("status", "task_id", "technical_status", "content_status", "video_path", "tail_status")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("operation", choices=["prepare", "submit", "query"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / ".execution.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write("exclusive legal opening receipt writer")
    try:
        with SeedanceClient(SeedanceConfig.from_env("ark_api", require_key=True)) as client:
            print(json.dumps(execute(args.operation, client), ensure_ascii=False))
    finally:
        lock.unlink()

if __name__ == "__main__":
    main()

