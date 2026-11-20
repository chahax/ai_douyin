
"""Prepare/run this explicitly authorized legal batch; no automatic resubmission."""
from __future__ import annotations
import argparse,json,sys,time,subprocess,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_legal_opening_seedance_v1 import make_plan,BUNDLE,LOGICAL_TASK
from src.content_factory.creative_legal_video_batch_v1 import project_remaining,render_prompt,USER_STATEMENT,FRAME_SOURCE
from src.content_factory.creative_segment_execution import read,sha,validate,execute_segment,media_reservation_root
from src.content_factory.creative_stage_contracts import persist,digest
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig
from src.content_factory.media_review_policy import validate_source_bindings

FILM=ROOT/"data/video_generation/legal_trend_20261008"
OUT=FILM/"remaining_batch_v1"
ANCHOR=FILM/"continuation_SH03B_v1/receipt.json"
PREFIX=[FILM/p/"receipt.json" for p in ("opening_SH01_v1","continuation_SH02_v1","continuation_SH03A_v1","continuation_SH03B_v1")]
def write_immutable(path,value):
    persist(path,value,immutable=True)
def prepare():
    base=make_plan(); compiled=read(BUNDLE/"COMPILED_PERFORMANCE.json")
    definitions=project_remaining(compiled)
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={"schema":"legal_video_remaining_batch_manifest/v1","logical_task_id":LOGICAL_TASK,
              "script_content_sha256":compiled["script_sha256"],"segments":definitions,
              "prefix_receipts":[{"path":str(p),"sha256":sha(p)} for p in PREFIX],
              "source_bindings":base["sources"],"content_status":"awaiting_human_review"}
    write_immutable(OUT/"BATCH_MANIFEST.json",manifest)
    auth={"schema":"legal_service_tail_batch_authorization/v1","logical_task_id":LOGICAL_TASK,
          "decision_source":"explicit_user_statement","user_statement":USER_STATEMENT,
          "question_call_id":"call_24c6450dd4964cc09a2b677d606f038a",
          "script_content_sha256":compiled["script_sha256"],"manifest_sha256":sha(OUT/"BATCH_MANIFEST.json"),
          "anchor_receipt":str(ANCHOR),"anchor_receipt_sha256":sha(ANCHOR),
          "anchor_last_frame_sha256":read(ANCHOR)["last_frame_sha256"],
          "model":base["model"],"new_segment_ids":[d["segment_id"] for d in definitions],
          "scope":"current legal film remaining source rows B1.S05 through B4.S06; original service tail chain; full batch human review",
          "automatic_retry":False,"content_approval":False,"publishing_authorized":False,
          "budget_reset":False,"failure_limit":10,"new_submissions_max":len(definitions)}
    write_immutable(OUT/"BATCH_USER_AUTHORIZATION.json",auth)
    for p in PREFIX:
        r=read(p);validate_source_bindings(r)
        if r["technical_status"]!="succeeded" or r["content_status"]=="rejected" or sha(r["video_path"])!=r["video_sha256"]:
            raise ValueError("prefix candidate changed or rejected")
    report={"source_rows_remaining":len(compiled["schedule"])-4,"new_segments":len(definitions),
            "remaining_source_seconds":round(sum(d["source_seconds"] for d in definitions),6),
            "remaining_service_seconds":sum(d["duration_seconds"] for d in definitions),
            "exact_text_coverage":True,"source_phase_seconds_preserved":True,
            "split_speech_timing":"proportional source-text projection; actual delivery requires human review",
            "paid_requests_during_prepare":0,"old_budget_not_reset":True}
    write_immutable(OUT/"OFFLINE_SOURCE_VERIFICATION.json",report)
    lines=["# 本次法律片连续生成清单","",f"用户授权：{USER_STATEMENT}","",
           "对白和动作来自已采用的完整交接。长对白只在原标点处拆分，秒数按字数比例投影，真实语速、表演和切点待人工审核。",""]
    for d in definitions:
        lines.extend([f'## {d["segment_id"]} / {d["shot_id"]} / {d["duration_seconds"]}秒',"",render_prompt(d),""])
    (OUT/"ALL_PROMPTS_v2.md").write_text("\n".join(lines),encoding="utf-8")
    return base,manifest,auth,report
def build_plan(base,manifest,definition,prior_path):
    prior=read(prior_path)
    bindings={"batch_authorization":{"path":str(OUT/"BATCH_USER_AUTHORIZATION.json"),"sha256":sha(OUT/"BATCH_USER_AUTHORIZATION.json")},
              "batch_manifest":{"path":str(OUT/"BATCH_MANIFEST.json"),"sha256":sha(OUT/"BATCH_MANIFEST.json")},
              "predecessor_receipt":{"path":str(prior_path.resolve()),"sha256":sha(prior_path)}}
    return {"schema":"creative_seedance_segment_plan/v1","logical_task_id":LOGICAL_TASK,
            "segment_id":definition["segment_id"],"shot_id":definition["shot_id"],
            "segment_order":["SH03B"]+[d["segment_id"] for d in manifest["segments"]],
            "sources":{**base["sources"],**bindings},"script_content_sha256":manifest["script_content_sha256"],
            "provider":"ark_api","model":base["model"],"resolution":"480p","ratio":"9:16","seed":20261008,
            "duration_seconds":definition["duration_seconds"],"generate_audio":True,"return_last_frame":True,
            "first_frame":{"path":prior["last_frame"],"sha256":prior["last_frame_sha256"]},
            "opening_frame_source":FRAME_SOURCE,**bindings,
            "source_refs":definition["source_refs"],"segment_definition":definition,
            "prompt":render_prompt(definition),"prompt_projection_version":2,"content_status":"awaiting_human_review",
            "authorization":{"user_statement":USER_STATEMENT,"automatic_retry":False,"content_approval":False},
            "historical_campaign":base["historical_campaign"]}
def progress(manifest,current=None,error=None):
    rows=[]
    for d in manifest["segments"]:
        path=OUT/d["segment_id"]/"receipt.json"
        r=read(path) if path.exists() else {}
        rows.append({"segment_id":d["segment_id"],"shot_id":d["shot_id"],
                     "task_id":r.get("task_id"),"technical_status":r.get("technical_status","not_submitted"),
                     "content_status":r.get("content_status","not_available"),"video_path":r.get("video_path"),
                     "usage":r.get("final",{}).get("usage")})
    value={"schema":"legal_video_batch_progress/v1","logical_task_id":LOGICAL_TASK,
           "current":current,"segments":rows,"saved":sum(r["technical_status"]=="succeeded" for r in rows),
           "remaining":sum(r["technical_status"]!="succeeded" for r in rows),
           "automatic_retry":False,"content_status":"awaiting_human_review","error":error}
    persist(OUT/"PROGRESS.json",value)
    return value
def run():
    base,manifest,auth,report=prepare()
    print(json.dumps({"event":"batch_preflight",**report},ensure_ascii=False),flush=True)
    config=SeedanceConfig.from_env("ark_api",require_key=True)
    if config.model!=base["model"] or config.provider!="ark_api":
        raise ValueError("configured provider/model differs; no automatic switch")
    prior=ANCHOR
    with SeedanceClient(config) as client:
        for definition in manifest["segments"]:
            sid=definition["segment_id"];folder=OUT/sid;folder.mkdir(exist_ok=True)
            receipt=folder/"receipt.json";plan_path=folder/"PLAN.json"
            if not receipt.exists():
                plan=build_plan(base,manifest,definition,prior)
                write_immutable(plan_path,plan)
                (folder/"PROMPT.txt").write_text(plan["prompt"]+"\n",encoding="utf-8")
                validate(plan_path)
                execute_segment(plan_path,folder,"preview",client)
                operation="submit"
            else:
                r=read(receipt)
                if r.get("technical_status")=="failed":
                    raise ValueError("failed segment; no automatic retry")
                if not r.get("task_id"):
                    raise ValueError("existing submission has unknown outcome/no ID; never resubmit")
                operation="query"
            while True:
                try:
                    record=execute_segment(plan_path,folder,operation,client,wait_timeout=40)
                except TimeoutError:
                    record=read(receipt)
                    if not record.get("task_id"):
                        raise
                except Exception as exc:
                    if receipt.exists():
                        record=read(receipt)
                        if record.get("task_id"):
                            task=client.get_task(record["task_id"])
                            if task.get("status") in ("failed","expired","cancelled"):
                                record.update(final=task,technical_status="failed",status="failed",error=str(exc))
                                persist(receipt,record)
                    progress(manifest,sid,str(exc))
                    raise
                status=progress(manifest,sid)
                print(json.dumps({"event":"segment_state","segment_id":sid,"task_id":record.get("task_id"),
                                  "technical_status":record.get("technical_status"),"saved":status["saved"],
                                  "remaining":status["remaining"]},ensure_ascii=False),flush=True)
                if record.get("technical_status")=="succeeded":
                    if record["content_status"]!="awaiting_human_review":
                        raise ValueError("new batch output received unexpected approval")
                    break
                if not record.get("task_id"):
                    raise ValueError("unknown submission: stop; no automatic resubmission")
                operation="query"
            prior=receipt
    print(json.dumps({"event":"all_segments_saved","count":len(manifest["segments"])},ensure_ascii=False),flush=True)
def assemble():
    manifest=read(OUT/"BATCH_MANIFEST.json");auth=read(OUT/"BATCH_USER_AUTHORIZATION.json")
    if auth["manifest_sha256"]!=sha(OUT/"BATCH_MANIFEST.json"):
        raise ValueError("assembly authorization changed")
    if manifest["prefix_receipts"] != [{"path":str(p),"sha256":sha(p)} for p in PREFIX]:
        raise ValueError("original four candidate receipts changed")
    for definition in manifest["segments"]:
        validate(OUT/definition["segment_id"]/"PLAN.json")
    receipts=PREFIX+[OUT/d["segment_id"]/"receipt.json" for d in manifest["segments"]]
    candidates=[];metadata=[]
    for p in receipts:
        r=read(p);validate_source_bindings(r)
        if r["technical_status"]!="succeeded" or r["content_status"]=="rejected" or sha(r["video_path"])!=r["video_sha256"]:
            raise ValueError("not an intact saved candidate")
        probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-show_streams","-of","json",r["video_path"]],text=True,encoding="utf-8"))
        metadata.append({"segment_id":r["segment_id"],"metadata":probe})
        candidates.append({"receipt":str(p),"receipt_sha256":sha(p),"video_path":r["video_path"],
                           "video_sha256":r["video_sha256"],"content_status":r["content_status"]})
    expected=None
    total_duration=0.0
    for item in metadata:
        streams=item["metadata"]["streams"]
        videos=[s for s in streams if s["codec_type"]=="video"]
        audios=[s for s in streams if s["codec_type"]=="audio"]
        if len(videos)!=1 or len(audios)!=1:
            raise ValueError("source must contain one video and one audio stream")
        v,a=videos[0],audios[0]
        signature=(v["codec_name"],v["width"],v["height"],v["r_frame_rate"],v.get("pix_fmt"),
                   a["codec_name"],a["sample_rate"],a["channels"])
        if expected is not None and signature!=expected:
            raise ValueError("source streams differ; preserve candidates and review assembly format")
        expected=signature
        total_duration+=float(item["metadata"]["format"]["duration"])
    concat=OUT/"concat.txt"
    concat.write_text("\n".join("file '"+r["video_path"].replace("\\","/").replace("'","'\\''")+"'" for r in candidates)+"\n",encoding="utf-8")
    output=OUT/"LEGAL_FULL_REVIEW_v1.mp4"
    if output.exists():
        raise ValueError("assembly already exists; preserve existing file")
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-n","-f","concat","-safe","0","-i",str(concat),
                    "-map","0:v:0","-map","0:a:0","-c","copy","-movflags","+faststart",str(output)],check=True)
    final=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_format","-show_streams","-of","json",str(output)],text=True,encoding="utf-8"))
    if output.stat().st_size==0:
        raise ValueError("empty assembly")
    if abs(float(final["format"]["duration"])-total_duration)>0.5:
        raise ValueError("assembled duration differs from complete source sequence")
    persist(OUT/"ASSEMBLY_RECEIPT.json",{"schema":"legal_full_review_assembly/v1","technical_status":"succeeded",
            "content_status":"awaiting_human_review","video_path":str(output),"video_sha256":sha(output),
            "video_bytes":output.stat().st_size,"candidate_count":len(candidates),"candidates":candidates,
            "metadata":final,"source_segment_metadata":metadata,"sum_source_durations":total_duration,"content_inspected":False,
            "assembly":"concat original provider video/audio; stream copy; no trimming; no extracted frames",
            "batch_authorization_sha256":sha(OUT/"BATCH_USER_AUTHORIZATION.json")})
    print(json.dumps({"video_path":str(output),"seconds":final["format"]["duration"],"segments":len(candidates),
                     "content_status":"awaiting_human_review"},ensure_ascii=False),flush=True)
def main():
    ap=argparse.ArgumentParser();ap.add_argument("operation",choices=["prepare","run","assemble"]);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    lock=OUT/".batch.lock"
    with lock.open("x",encoding="utf-8") as handle:handle.write("one batch writer")
    try:
        if args.operation=="prepare":print(json.dumps(prepare()[3],ensure_ascii=False))
        elif args.operation=="run":run()
        else:assemble()
    finally:lock.unlink()
if __name__=="__main__":main()

