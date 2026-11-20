"""Prepare the authorized SH02 continuation from an approved original tail."""
import json, math, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_legal_opening_seedance_v1 import make_plan, BUNDLE, LOGICAL_TASK
from src.content_factory.creative_segment_execution import read, sha, validate
from src.content_factory.creative_stage_contracts import persist
from src.content_factory.media_review_policy import validate_approved_tail
OUT=ROOT/"data/video_generation/legal_trend_20261008/continuation_SH02_v1"
PRIOR=ROOT/"data/video_generation/legal_trend_20261008/opening_SH01_v1"

def prepare():
    base=make_plan()
    compiled=read(BUNDLE/"COMPILED_PERFORMANCE.json")
    shot,row=compiled["shots"][1],compiled["schedule"][1]
    previous=compiled["schedule"][0]
    if (shot["shot_id"]!="SH02" or shot["source_refs"]!=["B1.S02"]
        or row["source_ref"]!="B1.S02" or row["source_kind"]!="dialogue"
        or row["start_state"]!=previous["end_state"]):
        raise ValueError("source shot, dialogue or cross-segment state mismatch")
    review_path=PRIOR/"receipt.human_review.json"
    tail=validate_approved_tail(review_path)
    context=read(PRIOR/"CONTINUATION_USER_CONTEXT.json")
    if context["user_statement"]!="下一段" or context["authorized_segment"]!="SH02":
        raise ValueError("missing current one-segment user instruction")
    # The adopted active-performance field already contains the exact dialogue.
    # Send it once; do not repeat original_text or synthesize a new action.
    prompt="\n".join([
        "写实中国职场短片，延续输入首帧中的同一人物、服装、会议室、光线和道具状态，单个连续镜头。",
        "周姐是带黑色文件夹来谈话的人事主管，小林是蓝色工牌已放在自己桌角的劳动者；两人仍在会议桌两侧对坐。",
        "机位与观察对象："+shot["framing"],
        "先保留发话前停顿："+row["before_performance"],
        "然后由周姐以普通话说出以下原句，只说一次；小林安静听，不抢话："+row["active_performance"],
        "说完留足约两秒让反应可读："+row["after_performance"],
        "末尾保留安静停顿，结束在小林尚未接话的时刻。纸仍正面朝下，工牌仍在桌角，纸笔与文件夹保持首帧位置，不重复摆放道具或加入新动作。不转场，不加字幕、旁白、配乐或其他语言；保留普通话同期对白与低声办公室环境音。",
    ])
    if prompt.count(row["original_text"])!=1:
        raise ValueError("dialogue must enter the actual prompt exactly once")
    duration=math.ceil(shot["duration"])
    sources=dict(base["sources"])
    sources["continuation_user_context"]={"path":str(PRIOR/"CONTINUATION_USER_CONTEXT.json"),"sha256":sha(PRIOR/"CONTINUATION_USER_CONTEXT.json")}
    plan={
        "schema":"creative_seedance_segment_plan/v1","logical_task_id":LOGICAL_TASK,
        "segment_id":"SH02","shot_id":"SH02","segment_order":["SH01","SH02"],
        "sources":sources,"model":base["model"],"provider":"ark_api",
        "first_frame":tail,"opening_frame_source":"preceding_approved_raw_tail",
        "predecessor_review":{"path":str(review_path),"sha256":sha(review_path)},
        "duration_seconds":duration,"resolution":"480p","ratio":"9:16","seed":20261008,
        "prompt":prompt,"source_refs":["B1.S02"],"script_content_sha256":compiled["script_sha256"],
        "source_shot":shot,"source_performance":row,
        "timing_projection":{"source_seconds":shot["duration"],"service_seconds":duration,
                             "rounding_seconds":round(duration-shot["duration"],6),
                             "rounding_behavior":"quiet end-state hold; no additional story action",
                             "before_seconds":1.2,"active_seconds":6,"after_seconds":2,
                             "precision":"ordered service prose; actual speech and reaction timing require human review"},
        "authorization":{"user_statement":"下一段","source":"current_conversation_user_message",
                         "scope":"approve SH01 and generate one SH02 from its original service tail",
                         "max_new_submissions":1,"automatic_retry":False,"subsequent_segments_authorized":False},
        "historical_campaign":base["historical_campaign"],
        "review_policy":"user_manual_review_only/v1",
    }
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"receipt.json").exists():
        raise ValueError("prior submission exists; query original receipt")
    persist(OUT/"PLAN.json",plan,immutable=True)
    (OUT/"PROMPT.txt").write_text(prompt+"\n",encoding="utf-8")
    validate(OUT/"PLAN.json")
    persist(OUT/"SOURCE_PROJECTION_VERIFICATION.json",{
        "source_refs":["B1.S02"],"source_recomputed_exact":True,"cross_segment_state_equal":True,
        "dialogue_occurrences_in_actual_prompt":1,"approved_original_tail_sha256":tail["sha256"],
        "current_script_logical_task_id":LOGICAL_TASK,"same_story_failure_budget_reset":False,
        "new_paid_calls_before_submit":0,"assistant_viewed_or_listened":False,
    },immutable=True)
    print(json.dumps({"status":"prepared","plan":str(OUT/"PLAN.json"),"duration_seconds":duration,
                      "dialogue":row["original_text"],"tail_sha256":tail["sha256"]},ensure_ascii=False))

if __name__=="__main__":
    prepare()

