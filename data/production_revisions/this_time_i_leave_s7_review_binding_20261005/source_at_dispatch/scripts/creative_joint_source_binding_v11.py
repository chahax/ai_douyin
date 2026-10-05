"""Independent full-joint review source binding extension; no dispatch or rewriting.

The v7 review remains unchanged. This extension binds narrative B, execution S
and compiled SH identities and requires meaningful, mapped timing evidence.
Mechanical source proofs never approve action semantics or creative quality.
"""
from copy import deepcopy
import json
import math
from scripts import creative_linear_script_v2 as legacy_linear
from scripts import creative_linear_script_v3 as linear
from scripts import step_index_physical_adapter_v5 as physical
from scripts.creative_script_review_sources_v7 import validate_review_v7
from scripts.creative_surface_action_v1 import schedule_action_plan,compile_action_plan
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

from scripts.creative_review_projection_v11 import project_storyboard

VERSION="creative_joint_source_binding/v11"
FINAL_FIELDS={"script","shots","state_plan","whole_film_direction","execution_script",
              "execution_bindings","declared_performance_window_checks"}
BINDING_FIELDS={"shot_id","source_ref","anchor","kind","start","end"}


class JointSourceBindingError(CreativeContractError):
    def __init__(self,code,message,path=""):
        super().__init__(code+": "+message)
        self.code=code
        self.detail={"code":code,"path":path,"blocks_handoff":True,
                     "automatic_retry":False,"semantic_approval":False}


def fail(code,message,path=""):
    raise JointSourceBindingError(code,message,path)


def close(a,b):
    return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<1e-8


def _lists(ctx):
    if not isinstance(ctx,dict):fail("JOINT_SOURCE_CONTEXT_INVALID","完整context必须为对象")
    try:
        raw=ctx["raw_linear_script"];direction=ctx["whole_film_direction"]
        shots=ctx["shots"]["shots"];execution=ctx["execution_script"]["beats"]
        plan=ctx["state_plan"];bindings=ctx["execution_bindings"]
        if not isinstance(shots,list) or not shots or not isinstance(execution,list) or not isinstance(bindings,list):raise TypeError()
        if not isinstance(plan,dict) or not isinstance(plan.get("beats"),list):raise TypeError()
    except (KeyError,TypeError):fail("JOINT_SOURCE_CONTEXT_INVALID","缺少完整raw/direction/shots/execution/state/bindings")
    return raw,direction,shots,execution,plan,bindings


def _source_fields(raw,bi,refs):
    beat=raw["beats"][bi];total=sum(s["kind"]=="dialogue" for s in beat["steps"]);spoken=0
    fields={f"script.beats.{bi}.duration_seconds",*([f"raw_linear_script.beats.{bi}.duration_seconds"] if "duration_seconds" in beat else [])}
    dialogue_indices={};assigned=set(refs)
    for si,step in enumerate(beat["steps"]):
        ref=f"raw_linear_script.beats.{bi}.steps.{si}"
        if step["kind"]=="dialogue":
            if ref in assigned:
                fields.add(f"script.beats.{bi}.dialogue.{spoken}.text")
                fields.add(ref+".text");dialogue_indices[ref]=spoken
            spoken+=1
        elif ref in assigned:
            slot="before" if spoken==0 else "during" if spoken<total else "after"
            fields.add(f"script.beats.{bi}."+slot);fields.add(ref+".text")
    return sorted(fields),dialogue_indices


def preflight(ctx):
    """Fail before sending a joint review if any identity/source projection is stale.

    Current final_context fields are explicitly excluded to reconstruct the
    director's original input. Call before adding other extension fields to ctx.
    """
    raw,direction,shots,execution,plan,bindings=_lists(ctx)
    if ctx.get("review_scope")=="storyboard_segment" or ctx.get("scope")=="single_beat":
        fail("JOINT_SOURCE_SCOPE_INVALID","只支持完整联合审查")
    try:
        source_ctx={k:deepcopy(v) for k,v in ctx.items() if k not in FINAL_FIELDS}
        physical.validate_direction(direction,source_ctx)
        names=[c["name"] for c in ctx["static_visual_manifest"]["characters"]]
        expected_script=(linear if ctx.get("linear_script_protocol")==linear.VERSION else legacy_linear).accept_linear_script(raw,raw,character_names=names)
        expected_script.pop("screenplay_markdown")
    except (CreativeContractError,KeyError,TypeError,AttributeError,ValueError) as exc:
        fail("JOINT_SOURCE_PROJECTION_INVALID",str(exc))
    if ctx.get("script")!=expected_script:
        fail("JOINT_SOURCE_PROJECTION_INVALID","script必须是完整原steps的未修改派生正文")
    ds=physical._shots(direction);expected_ids=[s["shot_id"] for s in ds]
    if len(shots)!=len(ds) or len(execution)!=len(ds) or len(plan["beats"])!=len(ds):
        fail("JOINT_SOURCE_ID_MISMATCH","B→S→SH的镜数不一致")
    if [s.get("beat_id") for s in shots]!=expected_ids or [s.get("id") for s in execution]!=expected_ids or (
            [s.get("beat_id") for s in plan["beats"]]!=expected_ids):
        fail("JOINT_SOURCE_ID_MISMATCH","执行脚本/计划/编译镜必须依次绑定同一S ID")
    if any(not isinstance(s.get("id"),str) or not s["id"] for s in shots) or len({s["id"] for s in shots})!=len(shots):
        fail("JOINT_SOURCE_ID_MISMATCH","SH ID必须完整唯一")
    if plan.get("initial_state")!=direction["initial_state"] or plan.get("spatial_contract")!=direction["spatial_contract"]:
        fail("JOINT_SOURCE_INITIAL_STATE_MISMATCH","方向与物理计划初态/空间证据不一致")
    source=physical._raw_sources(source_ctx)
    for i,(d,script,row) in enumerate(zip(ds,execution,plan["beats"])):
        expected_dialogue=[{"speaker":source[r]["speaker"],"text":source[r]["text"]}
                           for r in d["source_step_refs"] if source[r]["kind"]=="dialogue"]
        if script.get("dialogue")!=expected_dialogue:
            fail("JOINT_SOURCE_DIALOGUE_MISMATCH","执行对白必须完整按原steps复制一次",str(i))
        for key in ("purpose","composition","camera","dialogue_mode","cut_reason"):
            if row.get(key)!=d[key]:fail("JOINT_SOURCE_DIRECTION_MISMATCH","物理执行行与分镜安排不一致",str(i)+"."+key)
    try:
        scheduled,report=schedule_action_plan(plan,ctx["execution_script"],ctx["static_visual_manifest"])
        recomputed=compile_action_plan(plan,ctx["execution_script"],ctx["static_visual_manifest"])
    except CreativeContractError as exc:fail("JOINT_SOURCE_PHYSICAL_INVALID",str(exc))
    if project_storyboard(recomputed,ctx)!=ctx["shots"]:
        fail("JOINT_SOURCE_COMPILED_MISMATCH","编译镜头/首尾状态不是当前计划的确定性结果")
    if not close(ctx["execution_script"].get("duration_seconds"),sum(e["duration_seconds"] for e in execution)):
        fail("JOINT_SOURCE_TIMING_MISMATCH","执行总时长与镜头时长不一致")
    grouped={sid:[] for sid in expected_ids}
    for index,binding in enumerate(bindings):
        if not isinstance(binding,dict) or set(binding)!=BINDING_FIELDS or binding.get("shot_id") not in grouped:
            fail("JOINT_SOURCE_BINDING_INVALID","执行绑定形状或S ID无效",str(index))
        grouped[binding["shot_id"]].append((index,binding))
    actual_order=[]
    for binding in bindings:
        if not actual_order or actual_order[-1]!=binding["shot_id"]:actual_order.append(binding["shot_id"])
    if actual_order!=expected_ids:fail("JOINT_SOURCE_BINDING_INVALID","执行绑定缺镜、重排或交错")
    result=[];offset=0;checked=[]
    narrative_owner={s["shot_id"]:(bi,b["beat_id"]) for bi,b in enumerate(direction["beats"]) for s in b["shots"]}
    for i,(d,compiled,script,row,timing) in enumerate(zip(ds,shots,execution,plan["beats"],report["beats"])):
        entries=grouped[d["shot_id"]];required=timing["cut_contract"]["required_events"]
        if len(entries)!=len(required):fail("JOINT_SOURCE_BINDING_INVALID","每个真实动作/对白事件必须绑定一次",d["shot_id"])
        source_order=[];groups={g["id"]:g for g in row["groups"]};spoken=0
        for (global_index,binding),actual,anchor in zip(entries,scheduled["beats"][i]["events"],required):
            ref=binding["source_ref"]
            if ref not in d["source_step_refs"] or binding["anchor"]!=anchor["event_id"] or not (
                    close(binding["start"],offset+actual["start"]) and close(binding["end"],offset+actual["end"])):
                fail("JOINT_SOURCE_BINDING_INVALID","原step、实际事件锚或排时不对应",str(global_index))
            if not source_order or source_order[-1]!=ref:source_order.append(ref)
            step=source[ref]
            if step["kind"]=="dialogue":
                if binding["kind"]!="dialogue" or binding["anchor"]!="dialogue_"+str(spoken) or actual["dialogue_index"]!=spoken:
                    fail("JOINT_SOURCE_BINDING_INVALID","对白重复/重排/冒充动作",str(global_index))
                spoken+=1
            else:
                if binding["kind"]!="group" or binding["anchor"] not in groups:
                    fail("JOINT_SOURCE_BINDING_INVALID","原action必须由真实动作组或hold承担",str(global_index))
                slot="before" if spoken==0 else "during" if spoken<len(script["dialogue"]) else "after"
                if groups[binding["anchor"]]["script_slot"]!=slot:
                    fail("JOINT_SOURCE_BINDING_INVALID","实际动作槽与原对白先后不一致",str(global_index))
            checked.append({**deepcopy(binding),"group":deepcopy(groups.get(binding["anchor"]))})
        if source_order!=d["source_step_refs"]:
            fail("JOINT_SOURCE_BINDING_INVALID","全部原steps必须按原顺序完整兑现，不能删掉或复制",d["shot_id"])
        bi,bid=narrative_owner[d["shot_id"]];source_leaves,_=_source_fields(raw,bi,d["source_step_refs"])
        execution_leaves=[f"execution_script.beats.{i}.duration_seconds",f"shots.shots.{i}.duration_seconds",f"shots.shots.{i}.visible_performance"]
        window_leaves=[f"execution_bindings.{j}.{side}" for j,b in entries for side in ("start","end")]
        dialogue_leaves=[f"execution_script.beats.{i}.dialogue.{j}.text" for j in range(len(script["dialogue"]))]
        result.append({"storyboard_id":compiled["id"],"execution_shot_id":d["shot_id"],"narrative_beat_id":bid,
            "narrative_beat_index":bi,"execution_index":i,"source_step_refs":deepcopy(d["source_step_refs"]),
            "timing_source_leaves":source_leaves,"execution_timing_leaves":execution_leaves+window_leaves,
            "dialogue_text_leaves":dialogue_leaves,
            "dialogue_window_leaves":[f"execution_bindings.{j}.{side}" for j,b in entries if b["kind"]=="dialogue" for side in ("start","end")]
                 +[f"shots.shots.{i}.visible_performance"],
            "continuity_source_leaves":[f"shots.shots.{i}.start_state"]+([f"shots.shots.{i-1}.end_state"] if i else [])})
        offset+=script["duration_seconds"]
    _check_windows(direction,ctx.get("declared_performance_window_checks"),checked)
    return {"schema":VERSION,"context_sha256":digest(ctx),"mapping":result,
            "source_identity_checked":True,"physical_projection_recomputed":True,"semantic_approval":False}


def _check_windows(direction,checks,events):
    reqs=[r for d in physical._shots(direction) for r in d["performance_requirements"]]
    if not isinstance(checks,list) or len(checks)!=len(reqs) or {c.get("requirement_id") for c in checks if isinstance(c,dict)}!={r["id"] for r in reqs}:
        fail("JOINT_SOURCE_WINDOW_INVALID","声明反应窗口缺失、重复或不属于当前方向")
    for req in reqs:
        check=next(c for c in checks if c["requirement_id"]==req["id"])
        candidates=[e for e in events if e["source_ref"]==req["reaction_ref"] and close(check.get("start"),e["start"]) and close(check.get("end"),e["end"])]
        stimulus=[e for e in events if e["source_ref"]==req["stimulus_ref"]]
        if len(candidates)!=1 or not stimulus or check.get("relation")!=req["relation"] or check.get("subject")!=req["subject"] or check.get("mechanical_check")!="passed":
            fail("JOINT_SOURCE_WINDOW_INVALID","反应报告必须绑定真实原步骤窗口",req["id"])
        event=candidates[0];begin=min(e["start"] for e in stimulus);end=max(e["end"] for e in stimulus)
        valid=(event["start"]>=end-1e-8 if req["relation"]=="after" else event["end"]<=begin+1e-8 if req["relation"]=="before"
               else event["kind"]=="dialogue" and event["source_ref"]==req["stimulus_ref"])
        group=event["group"]
        if not valid or event["end"]-event["start"]+1e-8<req["minimum_seconds"] or (
                group and (group["kind"]!="hold" or group["hold_subject"]!=req["subject"])):
            fail("JOINT_SOURCE_WINDOW_INVALID","真实反应时序、保持人物或时长不满足声明",req["id"])


def validate_joint_review(review,ctx):
    proof=preflight(ctx)
    validate_review_v7(review,ctx)
    mapping={m["storyboard_id"]:m for m in proof["mapping"]}
    for row in review["coverage"]:
        m=mapping[row["id"]];checks=row["checks"]
        refs={r["path"] for r in checks["timing"]["evidence_refs"]}
        if not refs.intersection(m["timing_source_leaves"]):
            fail("JOINT_TIMING_SOURCE_MISSING","timing必须引用对应原拍的实际正文或时长，ID/event/trigger不够",row["id"])
        if not refs.intersection(m["execution_timing_leaves"]):
            fail("JOINT_TIMING_EXECUTION_MISSING","timing必须对照本执行镜的实际时长/窗口，不能借别镜或上游估时",row["id"])
        dialogue=checks["dialogue_timing"]
        if m["dialogue_text_leaves"]:
            refs={r["path"] for r in dialogue["evidence_refs"]}
            if dialogue["status"]=="not_applicable" or not refs.intersection(m["dialogue_text_leaves"]) or not refs.intersection(m["dialogue_window_leaves"]):
                fail("JOINT_DIALOGUE_SOURCE_MISSING","对白镜须引用本镜真实台词和实际说话窗口，不能跳过",row["id"])
        continuity={r["path"] for r in checks["continuity"]["evidence_refs"]}
        if any(path not in continuity for path in m["continuity_source_leaves"]):
            fail("JOINT_CONTINUITY_SOURCE_MISSING","连续性须对照本镜首态与上一镜尾态，ID不能代替状态",row["id"])
    return {"schema":VERSION,"review_source_binding_checked":True,
            "review_sha256":digest(review),"context_sha256":proof["context_sha256"],"semantic_approval":False}


def build_messages_addendum(ctx):
    proof=preflight(ctx)
    return ("独立v9来源映射（不替换既有完整审核或结论）：B是原叙事拍，S是执行镜，SH是编译镜。"
        "issues.location仍用现有B/SH编号，不用S编号。coverage仍按SH全片逐行。"
        "每镜timing在既有证据之外，须至少一个对应timing_source_leaves与一个execution_timing_leaves真实叶子；"
        "只能引原实际正文/时长，不能仅ID、event或trigger。对白镜dialogue_timing须本镜dialogue_text_leaves"
        "和dialogue_window_leaves各一条，不能not_applicable。continuity须下列全部首/前尾状态叶子。"
        "这些是最低来源关系，不是结论；核对原文与真实排时、typed操作，保留全部issues/status/reason，不能机械引用后默认通过。"
        "其余检查继续原v7规则，无需把所有字段重复六次。映射："+json.dumps(proof["mapping"],ensure_ascii=False,separators=(",",":")))
