#!/usr/bin/env python3
"""Generate one locally chained segment when the user explicitly defers review."""
from __future__ import annotations
import argparse, base64, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.seedance_client import SeedanceAPIError, SeedanceClient, SeedanceConfig, SeedanceReference, load_prompt_pack_segment
from src.content_factory.media_review_policy import USER_MANUAL_REVIEW_POLICY_VERSION, mark_saved_candidate
def now(): return datetime.now(timezone.utc).isoformat()
def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_json(path): return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def write_json(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def inside(path, parent):
    try: Path(path).relative_to(parent); return True
    except ValueError: return False
def image_reference(path):
    mime = "png" if path.suffix.lower() == ".png" else "jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return SeedanceReference("image", f"data:image/{mime};base64,{encoded}", "first_frame")
def main():
    parser = argparse.ArgumentParser(description="Generate one full-draft segment with review deferred to the user.")
    parser.add_argument("prompt_pack"); parser.add_argument("--segment", required=True); parser.add_argument("--first-frame", required=True)
    parser.add_argument("--campaign", required=True); parser.add_argument("--output-dir", required=True); parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--wait-timeout", type=float, default=1800); args = parser.parse_args()
    campaign_path = Path(args.campaign).resolve(); campaign = read_json(campaign_path); authorization = campaign.get("full_draft_authorization") or {}
    if campaign.get("review_policy") != "user_manual_review_only": raise ValueError("campaign is not configured for user-only manual review")
    if authorization.get("user_quote") != "直接完整视频来下": raise ValueError("campaign lacks the explicit full-draft authorization")
    frame = Path(args.first_frame).resolve()
    if not frame.is_file(): raise FileNotFoundError(frame)
    if not inside(frame, campaign_path.parent): raise ValueError("first frame must belong to the authorized campaign")
    pack_path = Path(args.prompt_pack).resolve(); pack = read_json(pack_path); segment, prompt, duration = load_prompt_pack_segment(pack, args.segment)
    segment_id = str(segment["id"]).replace("/", "-").replace("\\", "-"); output_dir = Path(args.output_dir).resolve()
    if not inside(output_dir, campaign_path.parent): raise ValueError("output directory must belong to the authorized campaign")
    output_dir.mkdir(parents=True, exist_ok=True); receipt_path = output_dir / "receipt.json"
    if receipt_path.exists(): raise ValueError("receipt exists; refusing to resubmit")
    config = SeedanceConfig.from_env("ark_api", require_key=True)
    if campaign.get("model") and config.model != campaign["model"]: raise ValueError("configured model differs from campaign model")
    frame_hash = sha256(frame)
    with SeedanceClient(config) as client:
        payload = client.build_task_payload(prompt, duration=int(duration), ratio="adaptive", resolution=str(campaign.get("resolution", "480p")), generate_audio=True, watermark=False, return_last_frame=True, seed=args.seed, references=[image_reference(frame)], task_type="first_frame")
        record = {"schema":"manual_review_deferred_segment_receipt/v1","status":"submitting","technical_status":"running","review_policy":"user_manual_review_only","review_policy_version":USER_MANUAL_REVIEW_POLICY_VERSION,"content_status":"not_available","campaign":str(campaign_path),"prompt_pack":str(pack_path),"segment_id":segment["id"],"duration_seconds":int(duration),"seed":args.seed,"first_frame":str(frame),"first_frame_sha256":frame_hash,"created_at":now()}
        write_json(receipt_path, record)
        try: created = client.create_task(payload)
        except Exception as exc:
            explicit_rejection = isinstance(exc, SeedanceAPIError) and exc.status_code == 400
            record.update(status="request_rejected_pre_generation" if explicit_rejection else "submit_outcome_unknown", task_created=False if explicit_rejection else None, error_type=type(exc).__name__, error=str(exc), error_code=getattr(exc,"error_code",None), http_status=getattr(exc,"status_code",None), failed_at=now()); write_json(receipt_path, record); raise
        record.update(status="submitted", task_id=created["id"], created=created); write_json(receipt_path, record)
        print(json.dumps({"segment":segment["id"],"status":"submitted","task_id":created["id"]},ensure_ascii=False),flush=True)
        final = client.wait_for_task(created["id"], timeout_seconds=args.wait_timeout, on_update=lambda task: print(json.dumps({"segment":segment["id"],"task_id":task.get("id"),"status":task.get("status")},ensure_ascii=False),flush=True))
        video = client.download_video(final, output_dir / f"{segment_id}.mp4"); tail = client.download_last_frame(final, output_dir / f"{segment_id}.last.png")
        record.update(final=final,video_path=str(video),video_sha256=sha256(video),last_frame=str(tail),last_frame_sha256=sha256(tail),completed_at=now()); mark_saved_candidate(record); write_json(receipt_path,record)
        print(json.dumps({"segment":segment["id"],"status":record["status"],"video":str(video),"last_frame":str(tail)},ensure_ascii=False),flush=True)
    return 0
if __name__ == "__main__": raise SystemExit(main())
