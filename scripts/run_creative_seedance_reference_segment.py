"""Submit or query one source-bound Seedance reference-image segment."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from src.content_factory.seedance_client import (
    SeedanceAPIError,
    SeedanceClient,
    SeedanceConfig,
    SeedanceReference,
)
from src.content_factory.performance_revision_gate import (
    reserve_performance_video,
    validate_performance_reference_video_plan,
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def validate(plan_path):
    path=Path(plan_path).resolve()
    plan=read(path)
    if plan.get("schema")!="creative_seedance_reference_segment_plan/v1":
        raise ValueError("wrong reference segment plan schema")
    validate_performance_reference_video_plan(plan)
    return path,plan


def references(plan):
    first_frame=plan.get("first_frame")
    if first_frame:
        if plan.get("reference_mode")!="exclusive_first_frame" or plan.get("use_previous_video_reference"):
            raise ValueError("Seedance first-frame mode must be exclusive")
        path=Path(first_frame["path"])
        if sha(path)!=first_frame.get("sha256"):
            raise ValueError("bound first frame changed")
        mime=first_frame.get("mime_type","image/png")
        encoded=base64.b64encode(path.read_bytes()).decode("ascii")
        return [SeedanceReference("image",f"data:{mime};base64,{encoded}","first_frame")]
    result=[]
    if plan.get("use_previous_video_reference"):
        previous=read(plan["previous_segment"]["receipt"]["path"])
        source=previous["final"]["content"]["video_url"]
        result.append(SeedanceReference("video",source,"reference_video"))
    for item in plan["references"]:
        receipt=read(item["receipt"]["path"])
        result.append(SeedanceReference("image",receipt["original_url"],"reference_image"))
    return result


def payload(plan,client):
    return client.build_task_payload(
        plan["prompt"],
        duration=int(plan["duration_seconds"]),
        ratio=plan.get("ratio","9:16"),
        resolution=plan["resolution"],
        generate_audio=bool(plan.get("generate_audio",True)),
        watermark=False,
        return_last_frame=True,
        seed=int(plan["seed"]),
        references=references(plan),
        task_type="first_frame" if plan.get("reference_mode")=="exclusive_first_frame" else "reference",
    )


def request_record(plan,request):
    record={k:v for k,v in request.items() if k!="content"}
    record["content"]=[{"type":"text","text":plan["prompt"]}]
    record["generate_audio"]=bool(plan.get("generate_audio",True))
    first_frame=plan.get("first_frame")
    if first_frame:
        record["content"].append({"type":"image_url","role":"first_frame","source":"approved_previous_segment_last_frame","image_sha256":first_frame["sha256"]})
    else:
        if plan.get("use_previous_video_reference"):
            record["content"].append({
                "type":"video_url",
                "role":"reference_video",
                "receipt_sha256":plan["previous_segment"]["receipt"]["sha256"],
                "source":"approved_previous_seedance_video",
            })
        for item in plan["references"]:
            record["content"].append({
                "type":"image_url",
                "role":"reference_image",
                "asset_id":item["asset_id"],
                "image_sha256":item["image"]["sha256"],
                "receipt_sha256":item["receipt"]["sha256"],
                "source":"trusted_seedream_original_url",
            })
    return record


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("operation",choices=["preview","submit","query"])
    parser.add_argument("plan")
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--wait-timeout",type=float,default=1800)
    args=parser.parse_args()

    plan_path,plan=validate(args.plan)
    output=Path(args.output_dir).resolve()
    output.mkdir(parents=True,exist_ok=True)
    receipt_path=output/"receipt.json"
    config=SeedanceConfig.from_env("ark_api",require_key=args.operation!="preview")
    if plan.get("model") and config.model!=plan["model"]:
        raise ValueError("configured video model differs from reviewed plan")

    with SeedanceClient(config) as client:
        request=payload(plan,client)
        sanitized=request_record(plan,request)
        if args.operation=="preview":
            row={
                "schema":"creative_seedance_reference_segment_receipt/v1",
                "status":"previewed",
                "plan":str(plan_path),
                "plan_sha256":sha(plan_path),
                "request":sanitized,
                "created_at":datetime.now(timezone.utc).isoformat(),
            }
            save(output/"request.preview.json",row)
            print(json.dumps({"status":"previewed","path":str(output/"request.preview.json")},ensure_ascii=False))
            return

        if args.operation=="query":
            if not receipt_path.exists():
                raise ValueError("no submission receipt")
            row=read(receipt_path)
            if row.get("plan_sha256")!=sha(plan_path):
                raise ValueError("submitted plan changed")
        else:
            if receipt_path.exists():
                raise ValueError("receipt exists; query instead of resubmitting")
            reserve_performance_video(plan,receipt_path)
            row={
                "schema":"creative_seedance_reference_segment_receipt/v1",
                "status":"submitting",
                "plan":str(plan_path),
                "plan_sha256":sha(plan_path),
                "request":sanitized,
                "created_at":datetime.now(timezone.utc).isoformat(),
            }
            save(receipt_path,row)
            try:
                created=client.create_task(request)
            except Exception as exc:
                rejected=(isinstance(exc,SeedanceAPIError)
                          and isinstance(exc.status_code,int)
                          and 400<=exc.status_code<500)
                row.update(
                    status="rejected_pre_generation" if rejected else "submit_outcome_unknown",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    error_code=getattr(exc,"error_code",None),
                    http_status=getattr(exc,"status_code",None),
                    task_created=False if rejected else None,
                    generation_gate="provider_review_required" if rejected else "resolve_unknown_submission",
                    failed_at=datetime.now(timezone.utc).isoformat(),
                )
                save(receipt_path,row)
                raise
            row.update(status="submitted",task_id=created["id"],created=created)
            save(receipt_path,row)
            print(json.dumps({"status":"submitted","task_id":created["id"]},ensure_ascii=False),flush=True)

        task=client.wait_for_task(
            row["task_id"],
            timeout_seconds=args.wait_timeout,
            on_update=lambda value:print(json.dumps({
                "task_id":value.get("id"),
                "status":value.get("status"),
            },ensure_ascii=False),flush=True),
        )
        video=client.download_video(task,output/(plan["segment_id"]+".mp4"))
        last=client.download_last_frame(task,output/(plan["segment_id"]+".last.png"))
        row.update(
            status="succeeded",
            final=task,
            video_path=str(video),
            video_sha256=sha(video),
            last_frame=str(last),
            last_frame_sha256=sha(last),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        save(receipt_path,row)
        print(json.dumps({
            "status":"succeeded",
            "video":str(video),
            "last_frame":str(last),
        },ensure_ascii=False))


if __name__=="__main__":
    main()
