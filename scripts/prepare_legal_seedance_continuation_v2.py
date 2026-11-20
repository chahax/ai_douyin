"""Prepare only SH03A from SH02's approved original service tail."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_legal_opening_seedance_v1 import make_plan,BUNDLE,LOGICAL_TASK
from src.content_factory.creative_segment_execution import read,sha,validate,frame_mime
from src.content_factory.creative_stage_contracts import persist
from src.content_factory.media_review_policy import validate_approved_tail
from src.content_factory.creative_legal_video_projection_v1 import select_complete_rows
OUT=ROOT/"data/video_generation/legal_trend_20261008/continuation_SH03A_v1"
PRIOR=ROOT/"data/video_generation/legal_trend_20261008/continuation_SH02_v1"

def prepare():
    base=make_plan()
    compiled=read(BUNDLE/"COMPILED_PERFORMANCE.json")
    shot=compiled["shots"][2]
    projection=select_complete_rows(compiled,["B1.S03"])
    row=projection["rows"][0]
    if shot["shot_id"]!="SH03" or row["shot_id"]!="SH03" or projection["service_seconds"]!=6:
        raise ValueError("current authorization covers only first complete SH03 row")
    review_path=PRIOR/"receipt.human_review.json"
    tail=validate_approved_tail(review_path)
    context=read(PRIOR/"CONTINUATION_USER_CONTEXT.json")
    if (context["user_statement"]!="下一段" or context["authorized_segment"]!="SH03A"
            or context["authorized_source_refs"]!=["B1.S03"]):
        raise ValueError("missing current one-segment instruction")
    prompt="\n".join([
        "写实中国职场短片，延续输入首帧中同一人物、服装、会议室、光线和道具状态，单个连续镜头。",
        "小林是工牌已放在自己桌角的劳动者，周姐是带黑色文件夹来谈话的人事主管；两人仍对坐。",
        "机位与观察对象："+shot["framing"],
        "先保留质疑前的停顿："+row["before_performance"],
        "接着仅小林用普通话说以下原句一次，周姐倾听不抢话："+row["active_performance"],
        "说完保留双方反应窗口："+row["after_performance"],
        "本段结束在周姐准备接话但还未说出下一句的时刻。保持同一机位和空间，不转场，不切到桌面。纸保持正面朝下，工牌、纸笔和文件夹沿用首帧位置，不重复摆放。不加字幕、旁白、配乐或其他语言，保留普通话同期对白和低声办公室环境音。",
    ])
    if prompt.count(row["original_text"])!=1:
        raise ValueError("actual prompt must contain exact dialogue once")
    sources=dict(base["sources"])
    sources["continuation_user_context"]={"path":str(PRIOR/"CONTINUATION_USER_CONTEXT.json"),
                                         "sha256":sha(PRIOR/"CONTINUATION_USER_CONTEXT.json")}
    plan={
        "schema":"creative_seedance_segment_plan/v1","logical_task_id":LOGICAL_TASK,
        "segment_id":"SH03A","shot_id":"SH03","segment_order":["SH01","SH02","SH03A"],
        "sources":sources,"model":base["model"],"provider":"ark_api",
        "first_frame":tail,"opening_frame_source":"preceding_approved_raw_tail",
        "predecessor_review":{"path":str(review_path),"sha256":sha(review_path)},
        "duration_seconds":6,"resolution":"480p","ratio":"9:16","seed":20261008,
        "prompt":prompt,"source_refs":["B1.S03"],"script_content_sha256":compiled["script_sha256"],
        "source_shot":shot,"source_performance":row,"timing_projection":projection,
        "original_phase_seconds":{"before":1.5,"active":3,"after":1.5},
        "shot_segment_split":{"source_shot":"SH03","source_shot_seconds":15.2,
                              "current_generation_segment":"SH03A","current_refs":["B1.S03"],
                              "remaining_unsubmitted_refs":["B1.S04"],"remaining_source_seconds":9.2,
                              "reason":"Mini maximum 15s; split between complete original performance rows",
                              "source_text_or_performance_patched":False},
        "authorization":{"user_statement":"下一段","source":"current_conversation_user_message",
                         "scope":"approve SH02; generate one SH03A from its original service tail",
                         "max_new_submissions":1,"automatic_retry":False,"subsequent_segments_authorized":False},
        "historical_campaign":base["historical_campaign"],"review_policy":"user_manual_review_only/v1",
    }
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"receipt.json").exists():
        raise ValueError("prior submission exists; query original task")
    persist(OUT/"PLAN.json",plan,immutable=True)
    (OUT/"PROMPT.txt").write_text(prompt+"\n",encoding="utf-8")
    validate(OUT/"PLAN.json")
    persist(OUT/"SOURCE_PROJECTION_VERIFICATION.json",{
        "source_refs":["B1.S03"],"source_recomputed_exact":True,"complete_original_row_preserved":True,
        "cross_segment_state_equal":True,"dialogue_occurrences_in_actual_prompt":1,
        "approved_original_tail_sha256":tail["sha256"],"approved_original_tail_mime":frame_mime(tail["path"]),
        "current_script_logical_task_id":LOGICAL_TASK,"same_story_failure_budget_reset":False,
        "new_paid_calls_before_submit":0,"assistant_viewed_or_listened":False,
    },immutable=True)
    print(json.dumps({"status":"prepared","plan":str(OUT/"PLAN.json"),"duration_seconds":6,
                      "dialogue":row["original_text"],"tail_mime":frame_mime(tail["path"])},ensure_ascii=False))

if __name__=="__main__":
    prepare()

