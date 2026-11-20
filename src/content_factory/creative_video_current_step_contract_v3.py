
"""Offline v3: source evidence stays complete; current media instructions are isolated.

This prototype withholds unstructured full-utterance delivery prose rather than
silently rewriting it. A full source-bound performance revision and fresh media
authorization are required before production.
"""
from __future__ import annotations
from copy import deepcopy
from .creative_stage_contracts import digest

CAST = (
    {"role_id":"xiaolin","name":"小林","source_speaker":"小林（虚构劳动者）"},
    {"role_id":"zhou","name":"周姐","source_speaker":"周姐（虚构人事主管）"},
)
KEYS = {
    "badge_location":"工牌位置","paper_location":"纸的位置","paper_facing":"纸的朝向",
    "paper_signed":"签字状态","pen_location":"笔的位置","zhou_position":"周姐的位置",
    "xiaolin_position":"小林的位置",
}
VALUES = {
    "xiaolin_table_corner":"小林桌角","table_middle":"桌面中央",
    "xiaolin_table_side":"小林一侧桌面","face_down":"正面朝下","face_up":"正面朝上",
    "unsigned":"未签字","table_beside_paper":"纸旁桌面",
    "seated_opposite":"对面坐着","seated":"坐着","xiaolin_neck":"小林脖子上",
    "zhou_folder":"周姐文件夹里","in_zhou_folder":"周姐文件夹里",
    "inside_zhou_folder":"周姐文件夹里","moving_to_door":"正走向门口",
    "standing_near_table":"站在桌旁","outside_room":"会议室外",
}
def _speaker_id(name):
    for c in CAST:
        if name==c["source_speaker"]:
            return c["role_id"]
    raise ValueError("speaker is outside the source-bound two-person cast")

def build_contract(definition):
    d=deepcopy(definition);steps=[];deferred=[]
    for p in d["pieces"]:
        r=p["row"]
        kind=r["source_kind"]
        if kind not in ("dialogue","action"):
            raise ValueError("unsupported source kind")
        speaker=_speaker_id(r["speaker"]) if kind=="dialogue" else None
        if kind=="action" and r.get("speaker"):
            raise ValueError("action row must not invent a speaker")
        step={
            "source_ref":r["source_ref"],"source_kind":kind,"part":p["part"],"parts":p["parts"],
            "speaker_id":speaker,"spoken_text":r["original_text"] if kind=="dialogue" else None,
            "current_action":r["active_performance"] if kind=="action" else None,
            "before_nonverbal":r["before_performance"],"after_nonverbal":r["after_performance"],
            "phase_seconds":{
                "before":round(r["active_start"]-r["start"],8),
                "active":round(r["active_end"]-r["active_start"],8),
                "after":round(r["end"]-r["active_end"],8)},
            "start_state":r["start_state"],"end_state":r["end_state"],
            "active_delivery_cues":None,
        }
        steps.append(step)
        if kind=="dialogue":
            deferred.append({"source_ref":r["source_ref"],"part":p["part"],
                             "complete_source_active_performance":p["original_row"]["active_performance"],
                             "reason":"requires source-safe structured nonverbal/delivery fields; do not repeat quoted speech across chunks"})
    return {
        "schema":"creative_video_current_step_contract/v3",
        "segment_id":d["segment_id"],"shot_id":d["shot_id"],"cast":deepcopy(list(CAST)),
        "identity_policy":"same two identities from the selected native service frame; no new cast or duplicates",
        "environment_policy":"inherit native first-frame room layout/light/props; no new location or room redesign",
        "camera_policy":"inherit first-frame composition; no full-shot future action in fragment instructions",
        "audio_identity":{"reference_bound":False,"status":"not verified; native tail frame contains no prior voice"},"captions":{"subtitles":False,"speaker_labels":False,"decorative_screen_text":False,
                    "story_prop_text":"only original paper print within current source action"},
        "duration_seconds":d["duration_seconds"],"steps":steps,
        "source_definition_sha256":digest(d),"source_definition":d,
        "deferred_delivery_source":deferred,
        "production_ready":False,
        "production_blockers":[
            "fresh revision scope/identity anchors and media authorization not bound",
            "complete source-bound performance revision required for isolated active delivery cues",
            "cross-segment voice binding not verified; first-frame-only input contains no audio identity",
        ],
        "review_policy":"human_only","content_quality_passed":False,
    }

def validate_contract(contract, definition):
    if contract!=build_contract(definition):
        raise ValueError("current-step contract differs from source-bound projection")
    if len(contract["cast"])!=2 or len({c["role_id"] for c in contract["cast"]})!=2:
        raise ValueError("exactly two unique source actors required")
    if any(contract["captions"][k] is not False for k in ("subtitles","speaker_labels","decorative_screen_text")):
        raise ValueError("user cancelled generated screen captions")
    return contract

def _state_text(state):
    return "；".join(KEYS.get(k,k)+"："+VALUES.get(v,v) for k,v in state.items())

def render_offline_prompt(contract):
    validate_contract(contract,contract["source_definition"])
    cast={c["role_id"]:c["name"] for c in contract["cast"]}
    rows=contract["steps"]
    lines=[
        f'{contract["duration_seconds"]}秒写实中国职场视频，承接实际输入的服务原始帧。',
        "画面中只有输入帧的同一小林和周姐；角色身份、脸和服装保持一致，不新增人物或分身。",
        "会议室结构、门窗方向、桌面关系、光线和人物起态承接输入帧；不换地点，不重建房间。",
        "本段仅执行下面当前步骤。对白只有标为“唯一对白”的原句，环境/动作说明不能当台词念。",
        "无屏幕字幕、人物姓名标签、台词文字或装饰标题。故事纸张原有印字只在相关动作里呈现。",
        "当前起态："+_state_text(rows[0]["start_state"]),
    ]
    if not any(r["spoken_text"] for r in rows):
        lines.append("本段完全没有对白、旁白或念字，只保留动作声与办公室环境音。")
    t=0.0
    for r in rows:
        phases=r["phase_seconds"]
        if r["parts"]>1:
            lines.append(f'同一发话的连续部分{r["part"]}/{r["parts"]}，接续而不复述之前内容。')
        if phases["before"]>0:
            lines.append(f'{t:.2f}–{t+phases["before"]:.2f}秒，无声准备：{r["before_nonverbal"]}')
            t+=phases["before"]
        if r["spoken_text"]:
            lines.append(f'{t:.2f}–{t+phases["active"]:.2f}秒，{cast[r["speaker_id"]]}唯一对白：「{r["spoken_text"]}」；对方倾听，不抢话。')
        else:
            lines.append(f'{t:.2f}–{t+phases["active"]:.2f}秒，当前动作：{r["current_action"]}')
        t+=phases["active"]
        if phases["after"]>0:
            lines.append(f'{t:.2f}–{t+phases["after"]:.2f}秒，无声反应：{r["after_nonverbal"]}')
            t+=phases["after"]
    lines.append("只用普通话同期声音与自然办公室底噪，无配乐。不提前发生下段事件；未签字状态保持。")
    prompt="\n".join(lines)
    for r in rows:
        if r["spoken_text"] and prompt.count(r["spoken_text"])!=1:
            raise ValueError("spoken text must occur exactly once")
    return prompt

def require_production_ready(contract):
    if contract.get("production_ready") is not True or contract.get("production_blockers"):
        raise ValueError("offline proposal only; full performance revision and new media scope required")

