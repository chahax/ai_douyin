"""Prepare one explicitly authorized source-row segment from an approved tail."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_legal_opening_seedance_v1 import make_plan,BUNDLE,LOGICAL_TASK
from src.content_factory.creative_segment_execution import read,sha,validate,frame_mime
from src.content_factory.creative_stage_contracts import persist
from src.content_factory.media_review_policy import validate_approved_tail
from src.content_factory.creative_legal_video_projection_v1 import select_complete_rows

def build_plan(base,compiled,prior_receipt,segment_id,source_refs):
    prior_receipt=Path(prior_receipt).resolve()
    prior=read(prior_receipt)
    previous_plan=prior["plan_snapshot"]
    if previous_plan["logical_task_id"]!=LOGICAL_TASK:
        raise ValueError("predecessor belongs to another story")
    review_path=prior_receipt.with_name("receipt.human_review.json")
    tail=validate_approved_tail(review_path)
    context_path=prior_receipt.with_name("CONTINUATION_USER_CONTEXT.json")
    context=read(context_path)
    if (context["user_statement"]!="下一段" or context["authorized_segment"]!=segment_id
        or context["authorized_source_refs"]!=source_refs
        or context["new_video_submissions_authorized"]!=1):
        raise ValueError("not the current one-segment user instruction")
    projection=select_complete_rows(compiled,source_refs)
    schedule=compiled["schedule"]
    previous_refs=previous_plan["source_refs"]
    last_index=next(i for i,r in enumerate(schedule) if r["source_ref"]==previous_refs[-1])
    if last_index+1>=len(schedule) or schedule[last_index+1]["source_ref"]!=source_refs[0]:
        raise ValueError("continuation must consume the immediately following complete source row")
    if schedule[last_index]["end_state"]!=projection["start_state"]:
        raise ValueError("preceding source end state mismatch")
    rows=projection["rows"]
    # This renderer covers seated talk before the paper is turned. Later prop
    # transitions require their own source-preserving action renderer.
    if (any(r["source_kind"]!="dialogue" for r in rows)
        or projection["start_state"]!=projection["end_state"]
        or projection["start_state"]["paper_facing"]!="face_down"
        or projection["start_state"]["badge_location"]!="xiaolin_table_corner"
        or projection["start_state"]["xiaolin_position"]!="seated"
        or projection["start_state"]["zhou_position"]!="seated_opposite"):
        raise ValueError("this renderer covers seated dialogue before the paper turn only")
    shot=next(s for s in compiled["shots"] if s["shot_id"]==rows[0]["shot_id"])
    parts=[
        "写实中国职场短片，延续输入首帧中的同一人物、服装、会议室、光线和道具状态，单个连续镜头。",
        "小林是工牌已放在自己桌角的劳动者，周姐是带黑色文件夹来谈话的人事主管；两人仍对坐。",
        "机位与观察对象："+shot["framing"],
        "只完成以下原稿步骤；仅该步骤指定的说话人用普通话说原句一次，另一人倾听不抢话。",
    ]
    for row in rows:
        parts.extend(["发话或行动前的停顿："+row["before_performance"],
                      "随后："+row["active_performance"],
                      "完成后保留反应窗口："+row["after_performance"]])
    parts.append("本段结束于以上反应，不提前发生下一步事件。纸保持正面朝下，工牌、纸笔和文件夹沿用首帧位置，不翻纸、不推纸、不重复摆放。保持同一机位和空间，不转场，不切到桌面；不加字幕、旁白、配乐或其他语言，保留普通话同期对白与低声办公室环境音。")
    prompt="\n".join(parts)
    dialogues=[r["original_text"] for r in rows if r["source_kind"]=="dialogue"]
    if any(prompt.count(line)!=1 for line in dialogues):
        raise ValueError("exact dialogue must enter the actual prompt once")
    order=previous_plan.get("segment_order",[prior["segment_id"]])
    if order[-1]!=prior["segment_id"] or segment_id in order:
        raise ValueError("generation order is not an immediate new segment")
    sources=dict(base["sources"])
    sources["continuation_user_context"]={"path":str(context_path),"sha256":sha(context_path)}
    phases=[{"source_ref":r["source_ref"],"before":round(r["active_start"]-r["start"],6),
             "active":round(r["active_end"]-r["active_start"],6),"after":round(r["end"]-r["active_end"],6)}
            for r in rows]
    return {
        "schema":"creative_seedance_segment_plan/v1","logical_task_id":LOGICAL_TASK,
        "segment_id":segment_id,"shot_id":shot["shot_id"],"segment_order":order+[segment_id],
        "sources":sources,"model":base["model"],"provider":"ark_api","first_frame":tail,
        "opening_frame_source":"preceding_approved_raw_tail",
        "predecessor_review":{"path":str(review_path),"sha256":sha(review_path)},
        "duration_seconds":projection["service_seconds"],"resolution":"480p","ratio":"9:16","seed":20261008,
        "prompt":prompt,"source_refs":source_refs,"script_content_sha256":compiled["script_sha256"],
        "source_shot":shot,"source_performances":rows,"timing_projection":projection,
        "original_phase_seconds":phases,
        "authorization":{"user_statement":"下一段","source":"current_conversation_user_message",
                         "scope":"approve immediately preceding candidate; generate only this segment",
                         "max_new_submissions":1,"context_sha256":sha(context_path),
                         "automatic_retry":False,"subsequent_segments_authorized":False},
        "historical_campaign":base["historical_campaign"],"review_policy":"user_manual_review_only/v1",
        "source_text_or_performance_patched":False,
    }

def prepare(segment_id,source_refs,prior_receipt,output):
    base=make_plan()
    plan=build_plan(base,read(BUNDLE/"COMPILED_PERFORMANCE.json"),prior_receipt,segment_id,source_refs)
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    if (out/"receipt.json").exists():
        raise ValueError("prior submission exists; query original task")
    persist(out/"PLAN.json",plan,immutable=True)
    (out/"PROMPT.txt").write_text(plan["prompt"]+"\n",encoding="utf-8")
    validate(out/"PLAN.json")
    persist(out/"SOURCE_PROJECTION_VERIFICATION.json",{
        "source_refs":source_refs,"source_recomputed_exact":True,"complete_original_rows_preserved":True,
        "immediate_next_source_rows":True,"cross_segment_source_state_equal":True,
        "dialogue_occurrences_in_actual_prompt":[plan["prompt"].count(r["original_text"])
          for r in plan["source_performances"] if r["source_kind"]=="dialogue"],
        "approved_original_tail_sha256":plan["first_frame"]["sha256"],
        "approved_original_tail_mime":frame_mime(plan["first_frame"]["path"]),
        "current_script_logical_task_id":LOGICAL_TASK,"same_story_failure_budget_reset":False,
        "new_paid_calls_before_submit":0,"assistant_viewed_or_listened":False,
    },immutable=True)
    print(json.dumps({"status":"prepared","plan":str(out/"PLAN.json"),"segment_id":segment_id,
                      "duration_seconds":plan["duration_seconds"],
                      "dialogues":[r["original_text"] for r in plan["source_performances"] if r["source_kind"]=="dialogue"],
                      "tail_mime":frame_mime(plan["first_frame"]["path"])},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--segment",required=True)
    ap.add_argument("--source-ref",action="append",required=True)
    ap.add_argument("--predecessor-receipt",required=True)
    ap.add_argument("--output-dir",required=True)
    args=ap.parse_args()
    prepare(args.segment,args.source_ref,args.predecessor_receipt,args.output_dir)

if __name__=="__main__":
    main()

