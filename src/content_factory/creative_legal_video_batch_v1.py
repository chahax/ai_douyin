
"""Source-preserving projection and explicit one-film deferred-review tail contract."""
from __future__ import annotations
import copy, math
from pathlib import Path
from .creative_stage_contracts import digest
from .media_review_policy import validate_source_bindings

USER_STATEMENT = "本次改为原始尾帧连续生成，全部完成后统一人工审核"
FRAME_SOURCE = "preceding_service_raw_tail_under_batch_authorization"

def split_row(row, maximum=15):
    """Split only invariant-state dialogue, at its original punctuation."""
    r = copy.deepcopy(row)
    total = r["end"] - r["start"]
    if total <= maximum + 1e-7:
        return [dict(row=r, original_row=copy.deepcopy(row), text_range=[0,len(r["original_text"])], part=1, parts=1)]
    if r["source_kind"] != "dialogue" or r["start_state"] != r["end_state"]:
        raise ValueError("long action/state transition requires a new director contract")
    text = r["original_text"]
    if r["active_performance"].count(text) != 1:
        raise ValueError("full original speech must occur once in performance")
    pre = r["active_start"] - r["start"]
    active = r["active_end"] - r["active_start"]
    post = r["end"] - r["active_end"]
    options = []
    for i,ch in enumerate(text[:-1],1):
        if ch not in "，。；？！：":
            continue
        left = pre + active * i / len(text)
        right = active * (len(text)-i) / len(text) + post
        if 4 <= math.ceil(left-1e-8) <= maximum and 4 <= math.ceil(right-1e-8) <= maximum:
            options.append((abs(left-right), i))
    if not options:
        raise ValueError("no source punctuation split satisfies duration bounds")
    cut = min(options)[1]
    result = []
    for part,(lo,hi) in enumerate(((0,cut),(cut,len(text))),1):
        chunk = copy.deepcopy(r)
        chunk["original_text"] = text[lo:hi]
        chunk["active_performance"] = r["active_performance"].replace(text,text[lo:hi],1)
        chunk["active_start"] = r["active_start"] + active * lo / len(text)
        chunk["active_end"] = r["active_start"] + active * hi / len(text)
        chunk["start"] = r["start"] if part == 1 else chunk["active_start"]
        chunk["end"] = r["end"] if part == 2 else chunk["active_end"]
        chunk["before_performance"] = r["before_performance"] if part == 1 else ""
        chunk["after_performance"] = r["after_performance"] if part == 2 else ""
        result.append(dict(row=chunk,original_row=copy.deepcopy(row),text_range=[lo,hi],part=part,parts=2))
    return result

def project_remaining(compiled):
    schedule = compiled["schedule"]
    if [r["source_ref"] for r in schedule[:4]] != ["B1.S01","B1.S02","B1.S03","B1.S04"]:
        raise ValueError("unexpected already-produced source prefix")
    pieces = [p for row in schedule[4:] for p in split_row(row)]
    groups = []
    for p in pieces:
        r = p["row"]
        if groups and groups[-1][-1]["row"]["shot_id"] == r["shot_id"] and r["end"]-groups[-1][0]["row"]["start"] <= 15+1e-7:
            groups[-1].append(p)
        else:
            groups.append([p])
    shots = {s["shot_id"]:s for s in compiled["shots"]}
    definitions = []
    for i,g in enumerate(groups,1):
        first,last = g[0]["row"],g[-1]["row"]
        for a,b in zip(g,g[1:]):
            if a["row"]["end_state"] != b["row"]["start_state"] or abs(a["row"]["end"]-b["row"]["start"])>1e-6:
                raise ValueError("non-contiguous source state or timing")
        duration = last["end"]-first["start"]
        definitions.append({
            "segment_id":f"LG{i:02d}","shot_id":first["shot_id"],
            "source_refs":list(dict.fromkeys(p["row"]["source_ref"] for p in g)),
            "pieces":g,"source_shot":shots[first["shot_id"]],
            "source_start":first["start"],"source_end":last["end"],
            "source_seconds":round(duration,8),"duration_seconds":max(4,math.ceil(duration-1e-8)),
            "start_state":first["start_state"],"end_state":last["end_state"],
            "timing_method":"original windows retained; split active speech proportional to exact text length; integer service padding at end",
            "actual_timing_verified":False,
        })
    # Every source character and every before/active/after second accounted for.
    for original in schedule[4:]:
        selected = [p for d in definitions for p in d["pieces"] if p["row"]["source_ref"]==original["source_ref"]]
        if "".join(p["row"]["original_text"] for p in selected) != original["original_text"]:
            raise ValueError("source text lost or duplicated")
        if abs(sum(p["row"]["end"]-p["row"]["start"] for p in selected)-(original["end"]-original["start"]))>1e-6:
            raise ValueError("source timing lost or duplicated")
    return definitions

STATE_LABELS = {
"xiaolin_table_corner":"小林桌角","table_middle":"桌面中央","face_down":"正面朝下",
"face_up":"正面朝上","unsigned":"未签字","table_beside_paper":"纸旁桌面",
"seated_opposite":"对面坐着","seated":"坐着",
}
def render_prompt(definition, version=2):
    d=definition; shot=d["source_shot"]
    parts=[
        f'{d["duration_seconds"]}秒竖屏写实中国职场短片，承接输入原始尾帧中的同一人物、服装、会议室、光线与当前道具。',
        "小林是劳动者，周姐是人事主管。输入首帧是上一段结束瞬间，从该瞬间自然继续。",
        ("本段叙事新增信息："+shot["new_information"]) if version==1 else "本段仅推进下方源表演列出的事件；整镜背景说明不作为额外对白。",
        ("观察对象："+shot["observation_target"]) if version==1 else "持续观察当前说话人的表情及对方反应，行动时保留相关手与道具可见。",
        ("导演目标构图：" if version==1 else "整镜构图参考（其中动作仅在下方指定的步骤发生）：")+shot["framing"],
        "依照源表演保持同一谈话空间，构图需要变化时自然调整机位，段内不插入其他地点。",
        "起始状态："+ "；".join(f'{k}={STATE_LABELS.get(v,v)}' for k,v in d["start_state"].items()),
        "依次完成以下表演；指定说话人用自然普通话说所列原句一次，另一人倾听。保留说前与说后反应，不抢话、不快进。",
    ]
    t=0.0
    for p in d["pieces"]:
        r=p["row"]
        if p["parts"]>1:
            parts.append(f'同一原句的连续部分{p["part"]}/{p["parts"]}，延续表演，不重复前一部分对白与准备动作。')
        for a,b,prose,label in [
            (r["start"],r["active_start"],r["before_performance"],"发话/行动前"),
            (r["active_start"],r["active_end"],r["active_performance"],"发话/行动"),
            (r["active_end"],r["end"],r["after_performance"],"完成后的反应"),
        ]:
            if b-a>1e-7:
                parts.append(f'{t:.2f}–{t+b-a:.2f}秒，{label}：{prose}')
                t+=b-a
    parts.append("结束于本段最后反应窗口，不提前发生下一事件。道具只按以上步骤变化；保持未签字，不新增签字、和解或承诺兑现。只保留普通话同期对白与办公室自然环境声，无其他语言、字幕、旁白、配乐。")
    for p in d["pieces"]:
        r=p["row"]
        if r["source_kind"]=="dialogue" and "\u300c"+r["original_text"]+"\u300d" not in "\n".join(parts):
            # Source occasionally uses a different quote style; exact speech still required.
            if r["original_text"] not in "\n".join(parts):
                raise ValueError("speech missing from actual prompt")
    prompt="\n".join(parts)
    if version==2:
        for p in d["pieces"]:
            r=p["row"]
            if r["source_kind"]=="dialogue" and prompt.count(r["original_text"])!=1:
                raise ValueError("exact current speech must occur once in actual prompt")
    return prompt

def validate_deferred_tail(plan, frame):
    """This branch grants continuation, never grants a content approval."""
    from .creative_segment_execution import read,sha
    auth_binding=plan["batch_authorization"]; manifest_binding=plan["batch_manifest"]
    for b in (auth_binding,manifest_binding,plan["predecessor_receipt"]):
        if sha(b["path"])!=b["sha256"]:
            raise ValueError("batch or predecessor binding changed")
    auth=read(auth_binding["path"]); manifest=read(manifest_binding["path"])
    if (auth.get("schema")!="legal_service_tail_batch_authorization/v1"
        or auth.get("decision_source")!="explicit_user_statement"
        or auth.get("user_statement")!=USER_STATEMENT
        or auth.get("logical_task_id")!=plan["logical_task_id"]
        or auth.get("script_content_sha256")!=plan["script_content_sha256"]
        or auth.get("automatic_retry") is not False
        or auth.get("content_approval") is not False
        or auth.get("manifest_sha256")!=manifest_binding["sha256"]):
        raise ValueError("not the explicit source-bound batch authorization")
    definitions=project_remaining(read(plan["sources"]["COMPILED_PERFORMANCE.json"]["path"]))
    if manifest["segments"]!=definitions:
        raise ValueError("batch projection changed")
    order=["SH03B"]+[d["segment_id"] for d in definitions]
    if plan["segment_order"]!=order or plan["segment_id"] not in order[1:]:
        raise ValueError("batch generation order changed")
    definition=definitions[order.index(plan["segment_id"])-1]
    if (plan["segment_definition"]!=definition or plan["prompt"]!=render_prompt(definition,plan.get("prompt_projection_version",1))
        or plan["duration_seconds"]!=definition["duration_seconds"]
        or plan["model"]!=auth["model"] or plan["resolution"]!="480p" or plan["ratio"]!="9:16"):
        raise ValueError("prepared segment differs from authorized source projection")
    prior=read(plan["predecessor_receipt"]["path"])
    validate_source_bindings(prior)
    if (prior.get("technical_status")!="succeeded"
        or prior.get("content_status") not in ("awaiting_human_review","approved")
        or prior.get("logical_task_id")!=plan["logical_task_id"]
        or prior.get("segment_id")!=order[order.index(plan["segment_id"])-1]
        or prior.get("model")!=plan["model"]):
        raise ValueError("predecessor is not the saved adjacent same-film candidate")
    if order.index(plan["segment_id"])==1:
        if sha(plan["predecessor_receipt"]["path"])!=auth["anchor_receipt_sha256"]:
            raise ValueError("batch anchor changed")
    elif prior["plan_snapshot"].get("batch_authorization")!=auth_binding:
        raise ValueError("predecessor is outside this batch")
    for path_key,hash_key in (("video_path","video_sha256"),("last_frame","last_frame_sha256")):
        if sha(prior[path_key])!=prior[hash_key]:
            raise ValueError("predecessor provider bytes changed")
    if (Path(prior["last_frame"]).resolve()!=Path(frame).resolve()
        or prior["last_frame_sha256"]!=plan["first_frame"]["sha256"]
        or prior.get("final",{}).get("status")!="succeeded"
        or not prior.get("final",{}).get("content",{}).get("last_frame_url")):
        raise ValueError("input is not the service original last frame")
    previous_state=(prior["plan_snapshot"].get("segment_definition",{}).get("end_state")
                    or prior["plan_snapshot"]["timing_projection"]["end_state"])
    if previous_state!=definition["start_state"]:
        raise ValueError("cross-segment source state mismatch")

