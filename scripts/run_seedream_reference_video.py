"""Generate one Seedance video from reviewed Seedream character and background images."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_factory.seedance_client import (
    SeedanceAPIError,
    SeedanceClient,
    SeedanceConfig,
    SeedanceReference,
)
from src.content_factory.seedance_frames import image_info

SCHEMA = "seedream_reference_video_plan/v1"
MODEL = "doubao-seedance-2-0-mini-260615"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")


def validate(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = load(plan_path)
    required = {"schema", "segment_id", "model", "duration_seconds", "resolution", "ratio", "seed", "prompt", "images"}
    if not isinstance(plan, dict) or set(plan) != required or plan.get("schema") != SCHEMA:
        raise ValueError("wrong plan schema")
    if plan["model"] != MODEL or plan["resolution"] != "480p" or plan["ratio"] != "9:16":
        raise ValueError("this test is locked to Seedance 2.0 Mini 480p 9:16")
    if not 4 <= int(plan["duration_seconds"]) <= 15 or not isinstance(plan["prompt"], str):
        raise ValueError("invalid duration or prompt")
    if not 1 <= len(plan["images"]) <= 9:
        raise ValueError("Seedance 2.0 reference image count must be 1..9")
    checked = []
    data_root = (ROOT / "data" / "video_generation").resolve()
    for row in plan["images"]:
        required_image = {"path", "sha256", "purpose", "source_image", "source_image_sha256",
                          "source_review", "source_review_sha256"}
        if not isinstance(row, dict) or not required_image.issubset(row) or set(row) - required_image - {"crop_manifest", "crop_manifest_sha256"}:
            raise ValueError("invalid image binding")
        image = Path(row["path"]).resolve()
        source = Path(row["source_image"]).resolve()
        review_path = Path(row["source_review"]).resolve()
        for item in (image, source, review_path):
            item.relative_to(data_root)
            if not item.is_file():
                raise FileNotFoundError(item)
        if digest(image) != row["sha256"] or digest(source) != row["source_image_sha256"]:
            raise ValueError("image bytes changed")
        if digest(review_path) != row["source_review_sha256"]:
            raise ValueError("source review changed")
        review = load(review_path)
        if review.get("decision") != "passed" or review.get("image_sha256") != row["source_image_sha256"]:
            raise ValueError("source image is not approved")
        if "crop_manifest" in row:
            manifest_path = Path(row["crop_manifest"]).resolve()
            manifest_path.relative_to(data_root)
            if digest(manifest_path) != row.get("crop_manifest_sha256"):
                raise ValueError("crop manifest changed")
            manifest = load(manifest_path)
            matches = [angle for char in manifest.get("characters", []) for angle in char.get("angles", [])
                       if Path(angle.get("path", "")).resolve() == image and angle.get("sha256") == row["sha256"]]
            if len(matches) != 1:
                raise ValueError("crop is not bound by the manifest")
        info = image_info(image)
        raw = image.read_bytes()
        checked.append((row, SeedanceReference("image", "data:" + info["mime"] + ";base64," +
                                               base64.b64encode(raw).decode("ascii"), "reference_image")))
    return plan_path, plan, checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "submit"))
    parser.add_argument("plan")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--wait-timeout", type=float, default=1800)
    args = parser.parse_args(argv)
    plan_path, plan, checked = validate(args.plan)
    output = Path(args.output_dir).resolve()
    output.relative_to((ROOT / "data" / "video_generation").resolve())
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / "receipt.json"
    if receipt_path.exists():
        raise ValueError("receipt already exists; never resubmit")
    config = replace(SeedanceConfig.from_env("ark_api", require_key=args.operation == "submit"), model=MODEL)
    refs = [reference for _, reference in checked]
    with SeedanceClient(config) as client:
        request = client.build_task_payload(
            plan["prompt"], duration=int(plan["duration_seconds"]), ratio=plan["ratio"],
            resolution=plan["resolution"], generate_audio=True, watermark=False,
            return_last_frame=True, seed=int(plan["seed"]), references=refs, task_type="reference"
        )
        request_record = {key: value for key, value in request.items() if key != "content"}
        request_record["content"] = [{"type": "text", "text": plan["prompt"]}] + [
            {"type": "image_url", "role": "reference_image", "image_sha256": row["sha256"],
             "purpose": row["purpose"]} for row, _ in checked
        ]
        receipt = {"schema": "seedream_reference_video_receipt/v1",
                   "status": "previewed" if args.operation == "preview" else "submit_outcome_unknown",
                   "plan": str(plan_path), "plan_sha256": digest(plan_path),
                   "request": request_record, "created_at": datetime.now(timezone.utc).isoformat(),
                   "api_calls": 0}
        save(receipt_path, receipt)
        if args.operation == "preview":
            print(json.dumps({"status": "previewed", "receipt": str(receipt_path)}, ensure_ascii=False))
            return 0
        receipt["api_calls"] = 1
        save(receipt_path, receipt)
        try:
            created = client.create_task(request)
        except SeedanceAPIError as exc:
            message = str(exc)
            flagged = sorted({int(value) for value in re.findall(r"content\[(\d+)\]", message)})
            receipt.update(
                status="rejected_pre_generation" if "HTTP 400:" in message and "InputImageSensitiveContentDetected.PrivacyInformation" in message else "submit_outcome_unknown",
                rejection={
                    "error_type": type(exc).__name__,
                    "message": message,
                    "flagged_content_indices": flagged,
                    "privacy_information": "PrivacyInformation" in message,
                    "task_created": False if "HTTP 400:" in message and "InputImageSensitiveContentDetected.PrivacyInformation" in message else None,
                },
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            save(receipt_path, receipt)
            raise
        receipt.update(status="submitted", task_id=created["id"], created=created)
        save(receipt_path, receipt)
        print(json.dumps({"status": "submitted", "task_id": created["id"]}, ensure_ascii=False), flush=True)
        task = client.wait_for_task(created["id"], timeout_seconds=args.wait_timeout,
                                    on_update=lambda t: print(json.dumps({"task_id": t.get("id"),
                                                                         "status": t.get("status")}), flush=True))
        video = client.download_video(task, output / (plan["segment_id"] + ".mp4"))
        last = client.download_last_frame(task, output / (plan["segment_id"] + ".last.png"))
        receipt.update(status="succeeded", final=task, video=str(video), video_sha256=digest(video),
                       last_frame=str(last), last_frame_sha256=digest(last),
                       completed_at=datetime.now(timezone.utc).isoformat())
        save(receipt_path, receipt)
        print(json.dumps({"status": "succeeded", "video": str(video), "last_frame": str(last)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
