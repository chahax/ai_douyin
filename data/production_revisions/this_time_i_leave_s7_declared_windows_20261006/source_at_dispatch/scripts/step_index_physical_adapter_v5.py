"""Independent step-index physical adapter, offline v5, with explicit surface slide.

Original raw_linear_script is read-only. Programs derive slots and cut anchors;
models own typed action proposals. Mechanical validity never proves source
faithfulness or cinematic quality. No provider/media dispatch occurs here.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator
from scripts import modular_step_shot_contract_v3 as source_contract
from scripts.creative_surface_action_v1 import (
    VERSION as ACTION_VERSION,
    build_action_plan_schema,schedule_action_plan,compile_action_plan,_projection as core_projection,
)
from src.content_factory.creative_modular_tool_export import _simple_schema
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION="step_index_physical_adapter_offline_v5"
DIRECTION="step_index_physical_direction_offline_v5"
LOCAL="step_index_physical_local_offline_v5"
INPUT="step_index_physical_input_offline_v5"
RULES=source_contract.RULES+(
    "物理初态在首步骤之前；owner不是holder。局部每action一个unit，可包含多个相继组；"
    "每action组至少一个operations，或明确hold且operations=[]。反应仍绑定原action_ref。"
    "不要填写script_slot或切点，程序按原steps中的对白位置生成；不能新增、重说或改原对白。"
    "单镜最多两句完整对白，关键动作对白并行及跨镜during尚不支持，不改原稿绕过。"
    "slide是沿支持面移动，value=surface:支持面ID:zone；holder须none，不能跨面或伪装take/place/hold。"
    "复合道具仅用显式registry展开的成员ID，不能用集合ID冒充某一张；未动成员保持原态。"
    "状态和时间编译成功仍须全文源/操作审查，不能宣称语义或成片通过。"
)

obj=source_contract.obj
text=source_contract.text

def fail(code,message,path=""):
    e=CreativeContractError(code+": "+message)
    e.detail={"code":code,"path":path,"blocks_handoff":True,"automatic_retry":False,"semantic_approval":False}
    raise e

def _raw_sources(context):
    return source_contract._source_map(context)

def _legacy_source(context):
    """Schema compatibility projection only; estimates never schedule execution."""
    raw=context["raw_linear_script"]
    estimates=None
    if any("duration_seconds" not in b for b in raw["beats"]):
        from scripts.creative_linear_script_v3 import preliminary_timing_estimates
        estimates=preliminary_timing_estimates(raw)
    return {"title":raw.get("title",""),"beats":[
        {"id":b["id"],"duration_seconds":b["duration_seconds"] if "duration_seconds" in b
             else estimates["by_beat_id"][b["id"]]["budget_seconds"],"event":b["event"],
         "dialogue":[{"speaker":step["speaker"],"text":step["text"]}
                     for step in b["steps"] if step["kind"]=="dialogue"]}
        for b in raw["beats"]]}


def _component_members(context):
    bundle=context.get("component_registry")
    if bundle is None:return []
    from scripts.creative_component_registry_v1 import validate_component_bundle
    try:effective=validate_component_bundle(bundle)
    except CreativeContractError as exc:
        fail("STEP_COMPONENT_REGISTRY_INVALID",str(exc),"component_registry")
    if effective!=context["static_visual_manifest"]:
        fail("STEP_COMPONENT_REGISTRY_INVALID","effective manifest与当前状态实体不一致",
             "static_visual_manifest")
    return list(bundle["member_source_map"])


def _validate_component_initial_state(direction,context):
    from scripts.creative_surface_state_v1 import parse_surface_location,support_surface_ids
    members=_component_members(context)
    surfaces=support_surface_ids(context["static_visual_manifest"])
    for member in members:
        state=direction["initial_state"][member]
        if state["holder"]=="none":
            try:parse_surface_location(state["location"],surfaces,"initial_state."+member+".location")
            except CreativeContractError as exc:
                fail("STEP_COMPONENT_INITIAL_STATE",str(exc),"initial_state."+member+".location")


def _core_schema(context):
    return build_action_plan_schema({"script":_legacy_source(context),
        "static_visual_manifest":context["static_visual_manifest"]})

def _known_unsupported(context):
    for beat in context.get("raw_linear_script",{}).get("beats",[]):
        if any(isinstance(x,dict) and x.get("kind")=="simultaneous_dialogue_action"
               for x in beat.get("execution_requirements",[])):
            fail("STEP_PHYSICAL_UNSUPPORTED","源明确要求动作对白并行，现有串行编译器无法表达",beat["id"])

def build_direction_schema(context):
    _known_unsupported(context)
    members=_component_members(context)
    result=source_contract.build_direction_schema(context)
    result["properties"]["schema"]={"enum":[DIRECTION]}
    fields=_core_schema(context)["properties"]
    for key in ("initial_state","spatial_contract"):
        result["properties"][key]=deepcopy(fields[key]);result["required"].append(key)
    for member in members:
        fields=result["properties"]["initial_state"]["properties"][member]["properties"]
        fields["location"]=deepcopy(fields["location"])
        fields["location"]["description"]="holder=none时必须为surface:<已登记支持面ID>:<zone>；手持时为实际手持位置。归属不等于持有。"
    chars=[c["id"] for c in context["static_visual_manifest"]["characters"]]
    refs=[r["ref"] for r in source_contract.source_catalog(context)]
    shot=result["properties"]["beats"]["items"]["properties"]["shots"]["items"]
    for key in ("purpose","composition"):
        shot["properties"][key]=text();shot["required"].append(key)
    shot["properties"]["dialogue_mode"]={"enum":["画内对白","画外对白","混合对白","无对白"]}
    shot["required"].append("dialogue_mode")
    shot["properties"]["performance_requirements"]={"type":"array","items":obj({
        "id":text(),"subject":{"enum":chars},"stimulus_ref":{"type":"string","enum":refs},
        "reaction_ref":{"type":"string","enum":refs},"relation":{"enum":["before","during","after"]},
        "minimum_seconds":{"type":"number","exclusiveMinimum":0}})}
    shot["required"].append("performance_requirements")
    result["description"]=RULES
    return _simple_schema(result)

def _validate(value,schema):
    errors=list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        e=errors[0];fail("STEP_PHYSICAL_SCHEMA_INVALID",e.message,".".join(map(str,e.absolute_path)))

def _source_direction_view(direction):
    result=deepcopy(direction);result["schema"]=source_contract.DIRECTION
    result.pop("initial_state");result.pop("spatial_contract")
    for beat in result["beats"]:
        for shot in beat["shots"]:
            for key in ("purpose","composition","dialogue_mode","performance_requirements"):shot.pop(key)
    return result

def _shots(direction):
    return [s for b in direction["beats"] for s in b["shots"]]

def validate_direction(direction,context):
    _validate(direction,build_direction_schema(context))
    _validate_component_initial_state(direction,context)
    source_contract.validate_direction(_source_direction_view(direction),context)
    sources=_raw_sources(context);owners={r:s["shot_id"] for s in _shots(direction) for r in s["source_step_refs"]}
    ids=set()
    for shot in _shots(direction):
        if sum(sources[r]["kind"]=="dialogue" for r in shot["source_step_refs"])>2:
            fail("STEP_PHYSICAL_UNSUPPORTED","单镜3句以上的穿插顺序不能由现有v2可靠表达；重新分镜，不重写原句",shot["shot_id"])
        for req in shot["performance_requirements"]:
            if req["id"] in ids:fail("STEP_WINDOW_COVERAGE","表演要求ID重复",req["id"])
            ids.add(req["id"])
            if req["reaction_ref"] not in shot["source_step_refs"]:
                fail("STEP_WINDOW_SOURCE","反应来源必须归属当前镜",req["id"])
            if owners[req["stimulus_ref"]]!=shot["shot_id"] and req["relation"]!="after":
                fail("STEP_PHYSICAL_UNSUPPORTED","跨镜仅支持已完成刺激后的after窗口",req["id"])
            if req["relation"]=="during" and (sources[req["stimulus_ref"]]["kind"]!="dialogue"
                    or req["reaction_ref"]!=req["stimulus_ref"]):
                fail("STEP_PHYSICAL_UNSUPPORTED","during只能绑定同一完整对白窗口；原action步骤不能与对白并行",req["id"])

def _input(context,direction,index,state,previous):
    shots=_shots(direction)
    return {"schema":INPUT,"protocol":VERSION,"context":deepcopy(context),"direction":deepcopy(direction),
        "shot_id":shots[index]["shot_id"],"start_state":deepcopy(state),
        "previous_local_sha256":[digest(l) for l in previous],
        "future_shot_ids":[s["shot_id"] for s in shots[index+1:]]}

def _state_by_id(state_text,context):
    state=json.loads(state_text);result={}
    for entity in context["static_visual_manifest"]["characters"]+context["static_visual_manifest"]["props"]:
        matches=[k for k in state if k==entity["id"] or k.startswith(entity["id"]+"(")]
        if len(matches)!=1:fail("STEP_PHYSICAL_STATE_ID","编译状态缺少唯一实体",entity["id"])
        result[entity["id"]]=deepcopy(state[matches[0]])
    return result

def build_local_input(context,direction,completed_locals):
    validate_direction(direction,context);index=len(completed_locals)
    if index>=len(_shots(direction)):fail("STEP_PHYSICAL_COMPLETE","所有镜头已经完成")
    if completed_locals:
        prefix=compile_prefix(context,direction,completed_locals)
        state=_state_by_id(prefix["storyboard"]["shots"][-1]["end_state"],context)
    else:state=deepcopy(direction["initial_state"])
    return _input(context,direction,index,state,completed_locals)

def _local_schema(context,direction,shot_id,input_sha256=None):
    shot=next((s for s in _shots(direction) if s["shot_id"]==shot_id),None)
    if shot is None:fail("STEP_SHOT_ID","未知镜头",shot_id)
    sources=_raw_sources(context);refs=shot["source_step_refs"]
    group=deepcopy(_core_schema(context)["properties"]["beats"]["items"]["properties"]["groups"]["items"])
    group["properties"].pop("script_slot");group["required"].remove("script_slot")
    for key,field in {"action_ref":{"type":"string","enum":[r for r in refs if sources[r]["kind"]=="action"]},
                      "semantic_role":{"enum":["action","reaction"]}}.items():
        group["properties"][key]=field;group["required"].append(key)
    return obj({"schema":{"enum":[LOCAL]},"shot_id":{"enum":[shot_id]},
        "input_sha256":{"enum":[input_sha256]} if input_sha256 is not None else text(),
        "duration_seconds":{"type":"number","exclusiveMinimum":0},
        "dialogue_performance":text(),"step_units":{"type":"array","minItems":len(refs),"maxItems":len(refs),
            "items":obj({"source_step_ref":{"type":"string","enum":refs},"groups":{"type":"array","items":group},
                        "dialogue_ref":{"enum":[None,*[r for r in refs if sources[r]["kind"]=="dialogue"]]}})},
        "performance_windows":{"type":"array","items":obj({
            "requirement_id":{"enum":[r["id"] for r in shot["performance_requirements"]]},"anchor":text()})}})

def build_local_schema(local_input):
    if local_input.get("schema")!=INPUT:fail("STEP_PHYSICAL_INPUT","输入须来自build_local_input")
    result=_simple_schema(_local_schema(local_input["context"],local_input["direction"],
                                        local_input["shot_id"],digest(local_input)))
    result["description"]=RULES
    return result

def build_direction_messages(context):
    return [{"role":"system","content":RULES},{"role":"user","content":json.dumps({
        "context":deepcopy(context),"source_catalog":source_contract.source_catalog(context),
        "request_identity":{"context_sha256":digest(context),"raw_linear_script_sha256":digest(context["raw_linear_script"])}},
        ensure_ascii=False,separators=(",",":"))}]

def build_local_messages(local_input):
    return [{"role":"system","content":RULES},{"role":"user","content":json.dumps({
        "local_input":deepcopy(local_input),"request_identity":{"input_sha256":digest(local_input)}},
        ensure_ascii=False,separators=(",",":"))}]

def _bind_shot(context,shot,local):
    _validate(local,_local_schema(context,{"beats":[{"shots":[shot]}]},shot["shot_id"]))
    sources=_raw_sources(context)
    if [u["source_step_ref"] for u in local["step_units"]]!=shot["source_step_refs"]:
        fail("STEP_LOCAL_COVERAGE","局部步骤缺失、重复或重排",shot["shot_id"])
    total=sum(sources[r]["kind"]=="dialogue" for r in shot["source_step_refs"])
    spoken=0;groups=[];dialogue=[];expected=[]
    for unit in local["step_units"]:
        ref=unit["source_step_ref"];source=sources[ref]
        if source["kind"]=="dialogue":
            if unit["groups"] or unit["dialogue_ref"]!=ref:
                fail("STEP_DIALOGUE_BINDING","对白只能完整引用原句",ref)
            dialogue.append({"speaker":source["speaker"],"text":source["text"]})
            expected.append({"kind":"dialogue","source_ref":ref,"dialogue_index":spoken});spoken+=1
            continue
        if not unit["groups"] or unit["dialogue_ref"] is not None:
            fail("STEP_ACTION_BINDING","每原action须有完整动作组或hold，不能省略",ref)
        slot="before" if spoken==0 else "during" if spoken<total else "after"
        for supplied in unit["groups"]:
            if supplied["action_ref"]!=ref:fail("STEP_ACTION_BINDING","动作组引用不属于所在原action",ref)
            if not math.isfinite(supplied["duration_seconds"]):fail("STEP_ACTION_BINDING","时长须有限",ref)
            if supplied["kind"]=="action" and not supplied["operations"]:
                fail("STEP_ACTION_BINDING","action不能以空操作冒充源动作；无物理动作须明确hold",ref)
            if supplied["kind"]=="hold" and (supplied["operations"] or not supplied["hold_subject"]):
                fail("STEP_ACTION_BINDING","hold必须无操作且有观察人物",ref)
            group={k:deepcopy(v) for k,v in supplied.items() if k not in ("action_ref","semantic_role")}
            group["script_slot"]=slot;groups.append(group)
            expected.append({"kind":"group","source_ref":ref,"group":group,"semantic_role":supplied["semantic_role"]})
    if not expected:fail("STEP_LOCAL_COVERAGE","镜头没有源步骤")
    last=expected[-1];cut=last["group"]["id"] if last["kind"]=="group" else "dialogue_"+str(last["dialogue_index"])
    reaction=local["performance_windows"][0]["anchor"] if local["performance_windows"] else cut
    req=shot["performance_requirements"][0] if shot["performance_requirements"] else None
    chars=context["static_visual_manifest"]["characters"]
    plan={"beat_id":shot["shot_id"],**{k:shot[k] for k in ("purpose","composition","camera","dialogue_mode","cut_reason")},
        "groups":groups,"dialogue_performance":local["dialogue_performance"],
        "reaction":{"anchor":reaction,"subject":req["subject"] if req else chars[0]["id"],"meaning":"源索引绑定的可读表演，语义待审"},
        "cut_after_event_id":cut,"completion_condition":"all_required_events_complete"}
    script={"id":shot["shot_id"],"duration_seconds":local["duration_seconds"],
        "event":"原steps执行投影；事件摘要不是实际动作源","dialogue":dialogue}
    return plan,script,expected

def attach_scheduler_projection(plan,expected_by_shot):
    """Use the core's real projection, retaining all original typed operations.

    face remains in the physical plan/state walker. The legacy event executor
    receives the core projection's performance clause instead of a face op.
    """
    projected=core_projection(plan)
    for row,tokens in zip(projected["beats"],expected_by_shot):
        groups={g["id"]:g for g in row["groups"]}
        for token in tokens:
            if token["kind"]=="group":
                token["scheduler_projection"]=deepcopy(groups[token["group"]["id"]])
    return expected_by_shot


def readback_schedule(scheduled,expected_by_shot,locals_,derived_script,schedule_report):
    """Read actual operations/performance/slots/times against the core projection.

    Original ops stay in source_trace for the semantic reviewer and state checks;
    projection can neither delete a source token nor silently lose face evidence.
    """
    trace=[];offset=0
    if len(scheduled["beats"])!=len(expected_by_shot) or len(schedule_report["beats"])!=len(expected_by_shot):
        fail("STEP_SCHEDULE_ORDER","调度镜数或报告镜数不符")
    for row,expected,local,source,timing in zip(scheduled["beats"],expected_by_shot,locals_,derived_script["beats"],schedule_report["beats"]):
        if row["beat_id"]!=source["id"] or timing["beat_id"]!=source["id"] or local["shot_id"]!=source["id"]:
            fail("STEP_SCHEDULE_ORDER","实际调度镜头ID与来源不符")
        cursor=0;consumed=0;tail_seen=False;bound_end=0
        dialogue_count=len(source["dialogue"])
        for event in row["events"]:
            if abs(event["start"]-cursor)>1e-8 or event["end"]<=event["start"] or not math.isfinite(event["end"]):
                fail("STEP_SCHEDULE_ORDER","实际调度不连续、倒序或时长无效")
            if consumed>=len(expected):
                expected_tail={"start":cursor,"end":local["duration_seconds"],
                    "phase":"after_last_line" if dialogue_count else "no_dialogue",
                    "script_slot":"after","dialogue_index":-1,
                    "performance":"保持已成立末态，不新增动作；余量不能抵扣较早指定的保持时长","operations":[]}
                if tail_seen or event!=expected_tail:
                    fail("STEP_SCHEDULE_ORDER","源步骤后事件不符合唯一程序尾余量",row["beat_id"])
                tail_seen=True;cursor=event["end"];continue
            token=expected[consumed]
            projected=None
            if token["kind"]=="group":
                g=token["group"];projected=token.get("scheduler_projection")
                if projected is None:
                    fail("STEP_SCHEDULE_ORDER","须先绑定真实核心projection，不可猜测face调度",g["id"])
                phase=("no_dialogue" if not dialogue_count else "before_first_line" if g["script_slot"]=="before"
                       else "between_lines" if g["script_slot"]=="during" and dialogue_count>1 else "after_last_line")
                if event["script_slot"]!=projected["script_slot"] or event["operations"]!=projected["operations"] or (
                        event["performance"]!=projected["performance"]) or event["dialogue_index"]!=-1 or event["phase"]!=phase or (
                        abs(event["end"]-event["start"]-g["duration_seconds"])>1e-8):
                    fail("STEP_SCHEDULE_ORDER","实际动作payload/slot/时长与核心projection不符",g["id"])
                anchor=g["id"];group=g
            else:
                di=token["dialogue_index"]
                phase="first_line_delivery" if di==0 else "later_line_delivery"
                if event["script_slot"]!="dialogue_performance" or event["dialogue_index"]!=di or (
                        event["operations"]) or event["performance"]!=local["dialogue_performance"] or event["phase"]!=phase or (
                        abs(event["end"]-event["start"]-timing["actual_dialogue_seconds"][di])>1e-8):
                    fail("STEP_SCHEDULE_ORDER","实际对白窗口payload/时长与原步骤顺序不符",token["source_ref"])
                anchor="dialogue_"+str(di);group=None
            trace.append({"shot_id":row["beat_id"],"source_ref":token["source_ref"],"anchor":anchor,
                "kind":token["kind"],"start":offset+event["start"],"end":offset+event["end"],
                "group":deepcopy(group),"scheduler_projection":deepcopy(projected),
                "actual_scheduled_payload":deepcopy(event),"payload_matched":True,
                "physical_operations":deepcopy(group["operations"]) if group else [],
                "scheduled_operations":deepcopy(event["operations"]),
                "projection_note":"core face ops encoded in performance; original face retained for physical state walker"
                    if group and any(op["kind"]=="face" for op in group["operations"]) else "identity"})
            cursor=event["end"];bound_end=cursor;consumed+=1
        if consumed!=len(expected) or abs(cursor-local["duration_seconds"])>1e-8 or (
                abs(timing["unused_tail_seconds"]-(local["duration_seconds"]-bound_end))>1e-8):
            fail("STEP_SCHEDULE_ORDER","实际调度遗漏步骤、未覆盖声明时长或余量报告不符",row["beat_id"])
        offset+=local["duration_seconds"]
    return trace

def _windows(direction,locals_,trace):
    lookup={(e["shot_id"],e["anchor"]):e for e in trace};source_events={}
    for event in trace:source_events.setdefault(event["source_ref"],[]).append(event)
    checks=[]
    for shot,local in zip(_shots(direction),locals_):
        reqs={r["id"]:r for r in shot["performance_requirements"]};windows=local["performance_windows"]
        if len({w["requirement_id"] for w in windows})!=len(windows) or {w["requirement_id"] for w in windows}!=set(reqs):
            fail("STEP_WINDOW_COVERAGE","每条要求须绑定恰好一次",shot["shot_id"])
        for window in windows:
            req=reqs[window["requirement_id"]];visible=lookup.get((shot["shot_id"],window["anchor"]))
            triggers=source_events.get(req["stimulus_ref"])
            if visible is None or visible["source_ref"]!=req["reaction_ref"]:
                fail("STEP_WINDOW_SOURCE","反应锚点不属于原反应步骤",req["id"])
            if not triggers:fail("STEP_WINDOW_ORDER","刺激尚未执行",req["id"])
            begin=min(e["start"] for e in triggers);end=max(e["end"] for e in triggers);relation=req["relation"]
            legal=(visible["start"]>=end-1e-8 if relation=="after" else visible["end"]<=begin+1e-8 if relation=="before"
                   else visible["kind"]=="dialogue" and visible in triggers)
            if not legal:fail("STEP_WINDOW_ORDER","实际刺激和反应时序不符合要求",req["id"])
            if visible["end"]-visible["start"]+1e-8<req["minimum_seconds"]:
                fail("STEP_WINDOW_TOO_SHORT","真实窗口不足，不能用未绑定尾余量抵扣",req["id"])
            if visible["group"] and (visible["group"]["kind"]!="hold" or visible["group"]["hold_subject"]!=req["subject"]):
                fail("STEP_WINDOW_SUBJECT","反应窗口没有保持指定人物",req["id"])
            checks.append({"requirement_id":req["id"],"start":visible["start"],"end":visible["end"],
                           "relation":relation,"subject":req["subject"],"mechanical_check":"passed"})
    return checks

def _compile(context,direction,locals_,complete):
    validate_direction(direction,context);shots=_shots(direction)
    required=shots if complete else shots[:len(locals_)]
    if not locals_ or len(locals_)>len(shots) or [l.get("shot_id") for l in locals_] != [s["shot_id"] for s in required]:
        fail("STEP_LOCAL_COVERAGE","局部结果必须按镜头顺序覆盖，完整编译不得使用前缀冒充")
    plan={"schema":ACTION_VERSION,"initial_state":deepcopy(direction["initial_state"]),
          "spatial_contract":deepcopy(direction["spatial_contract"]),"beats":[]}
    derived={"title":context["raw_linear_script"].get("title",""),"beats":[]};expected=[]
    for shot,local in zip(shots,locals_):
        row,script,tokens=_bind_shot(context,shot,local)
        plan["beats"].append(row);derived["beats"].append(script);expected.append(tokens)
    derived["duration_seconds"]=sum(l["duration_seconds"] for l in locals_)
    attach_scheduler_projection(plan,expected)
    scheduled,report=schedule_action_plan(plan,derived,context["static_visual_manifest"])
    trace=readback_schedule(scheduled,expected,locals_,derived,report)
    storyboard=compile_action_plan(plan,derived,context["static_visual_manifest"])
    for i,(local,shot) in enumerate(zip(locals_,storyboard["shots"])):
        state=_state_by_id(shot["start_state"],context)
        if local["input_sha256"]!=digest(_input(context,direction,i,state,locals_[:i])):
            fail("STEP_PHYSICAL_STALE_INPUT","原稿、方向、资产、前镜结果或编译首态已改变",local["shot_id"])
    checks=_windows(direction,locals_,trace)
    source_map=[];sources=_raw_sources(context)
    for local in locals_:
        for unit in local["step_units"]:
            ref=unit["source_step_ref"]
            source_map.append({"source_step_ref":ref,"source_step":deepcopy(sources[ref]),
                "shot_id":local["shot_id"],"group_ids":[g["id"] for g in unit["groups"]],
                "dialogue_ref":unit["dialogue_ref"],
                "scheduled_anchors":[e["anchor"] for e in trace if e["source_ref"]==ref],
                "semantic_correspondence":"pending_full_source_operations_review"})
    return {"schema":VERSION,"status":"physical_compiled_pending_semantic_review","complete":complete,
        "source_raw_linear_script":deepcopy(context["raw_linear_script"]),
        "source_raw_sha256":digest(context["raw_linear_script"]),"context_sha256":digest(context),
        "direction_sha256":digest(direction),"locals_sha256":[digest(l) for l in locals_],
        "derived_execution_script":derived,"derived_action_plan":plan,"scheduled_execution":scheduled,
        "source_trace":trace,"source_map":source_map,"source_unit_coverage_status":"complete" if complete else "prefix_only",
        "storyboard":storyboard,"schedule_report":report,"performance_checks":checks,
        "source_reference_coverage_checked":True,"actual_schedule_payload_order_checked":True,
        "physical_state_checked":True,"declared_performance_windows_checked":True,
        "execution_timing_source":"local_duration_and_actual_schedule_only",
        "narrative_estimates_are_actual_execution_windows":False,
        "source_action_semantics_verified":False,"source_reaction_duration_semantics_verified":False,
        "face_readability_verified":False,"semantic_approval":False,"production_ready":False,
        "automatic_media_submit":False,"source_narrative_beat_count":len(context["raw_linear_script"]["beats"]),
        "execution_shot_count":len(locals_),"total_duration_seconds":derived["duration_seconds"],
        "limitations":["source correspondence of natural-language actions to typed operations requires full review",
            "identical scheduler payloads obtain identities from the checked program source binding, not remote event IDs",
            "cross-shot only after windows; no splitting a source step or line; max two dialogues per shot",
            "compiler tail time is recorded and excluded from bound reaction windows"]}

def compile_prefix(context,direction,locals_):return _compile(context,direction,locals_,False)
def compile_complete(context,direction,locals_):return _compile(context,direction,locals_,True)

def make_offline_case():
    context,base,_=source_contract.make_offline_case()
    raw=context["raw_linear_script"];raw["beats"][0]["steps"]=[
        {"kind":"action","speaker":"","text":"乙把手中杯子放到桌上。"},
        {"kind":"dialogue","speaker":"乙","text":"这次你自己做。"},
        {"kind":"action","speaker":"","text":"甲抬眼看乙，并保持两秒。"},
        {"kind":"action","speaker":"","text":"乙拿起桌上的笔。"}]
    context["static_visual_manifest"]={"schema":"static_visual_manifest_v1",
        "render":{"style_option_id":"S01","visual_medium":"二维手绘动画","palette":"灰蓝米白","light_source":"右上暖灯"},
        "characters":[{"id":cid,"name":name,"age_group":"成年","hair":"短发","clothing":"通勤衬衣","body_shape":"成年体型"}
            for cid,name in (("C01","甲"),("C02","乙"))],
        "props":[{"id":"P01","name":"杯子","appearance":"白色杯子","owner_id":"C02"},
                 {"id":"P02","name":"笔","appearance":"黑色笔","owner_id":"C02"}],
        "scene":{"name":"办公室","elements":[{"id":"E01","name":"桌子","appearance":"浅木桌面"},
            {"id":"E02","name":"椅子","appearance":"黑色椅子"}],
            "relations":[{"subject":"E02","relation":"behind","reference":"E01"}]}}
    direction=deepcopy(base);direction["schema"]=DIRECTION;direction["context_sha256"]=digest(context)
    direction["raw_linear_script_sha256"]=digest(raw)
    direction["initial_state"]={"C01":{"posture":"standing","position":"桌左","gaze":"桌面","affect":"平静","facing":"C02"},
        "C02":{"posture":"standing","position":"桌右","gaze":"C01","affect":"平静","facing":"桌面"},
        "P01":{"holder":"C02","location":"右手"},"P02":{"holder":"none","location":"桌面"}}
    direction["spatial_contract"]={"seats":[]}
    shots=_shots(direction);refs=[r["ref"] for r in source_contract.source_catalog(context)]
    for shot in shots:
        shot.update(purpose=shot["new_information"],composition="双人行动与回应可读",
            dialogue_mode="画内对白" if shot["shot_id"]=="S1" else "无对白",performance_requirements=[])
    shots[1]["performance_requirements"]=[{"id":"R1","subject":"C01","stimulus_ref":refs[1],
        "reaction_ref":refs[2],"relation":"after","minimum_seconds":2}]
    def group(gid,ref,kind,seconds,ops,subject="",role="action"):
        return {"id":gid,"action_ref":ref,"semantic_role":role,"kind":kind,"duration_seconds":seconds,
                "hold_subject":subject,"performance":"按原步骤自然完成，具体感染力待审","operations":ops}
    units=[
        [{"source_step_ref":refs[0],"dialogue_ref":None,"groups":[group("G_PLACE",refs[0],"action",1,
            [{"kind":"place","actor":"C02","target":"P01","value":"E01"}])]},
         {"source_step_ref":refs[1],"groups":[],"dialogue_ref":refs[1]}],
        [{"source_step_ref":refs[2],"dialogue_ref":None,"groups":[
            group("G_GAZE",refs[2],"action",0.25,[{"kind":"gaze","actor":"C01","target":"","value":"C02"}],role="reaction"),
            group("G_HOLD",refs[2],"hold",2,[],"C01","reaction")]},
         {"source_step_ref":refs[3],"dialogue_ref":None,"groups":[group("G_TAKE",refs[3],"action",1,
            [{"kind":"take","actor":"C02","target":"P02","value":"右手"}])]}]]
    locals_=[]
    for i,shot in enumerate(shots):
        local_input=build_local_input(context,direction,locals_)
        locals_.append({"schema":LOCAL,"shot_id":shot["shot_id"],"input_sha256":digest(local_input),
            "duration_seconds":4,"dialogue_performance":"乙完整说出原句，语速和声画仍待后续审查",
            "step_units":units[i],"performance_windows":[] if i==0 else [{"requirement_id":"R1","anchor":"G_HOLD"}]})
    return context,direction,locals_

def make_surface_offline_case(*,untimed=False):
    from scripts.creative_component_registry_v1 import build_p03_registry
    c,d,ls=make_offline_case()
    original=deepcopy(c["static_visual_manifest"])
    original["scene"]["elements"][1].update(name="林屿桌",appearance="浅木桌面")
    original["scene"]["elements"].append({"id":"E03","name":"椅子","appearance":"黑色办公椅"})
    original["props"].append({"id":"P03","name":"善后便利贴三张",
        "appearance":"正方形小纸片，分别为浅黄、浅粉、浅蓝底，深灰手写短词（对账/改明细/收尾）",
        "owner_id":"C01"})
    registry=build_p03_registry(original)
    c["component_registry"]=registry
    c["static_visual_manifest"]=deepcopy(registry["effective_manifest"])
    raw=c["raw_linear_script"]["beats"][0]
    raw["steps"][0]["text"]="乙沿桌面把浅黄对账便签推近甲，浅粉和浅蓝不动。"
    raw["steps"][1].update(speaker="甲",text="这次你自己做。")
    raw["steps"][3]["text"]="乙沿同一桌面把浅黄便签收回自己面前，浅粉和浅蓝不动。"
    d["initial_state"]["P01"]={"holder":"none","location":"surface:E02:cup_corner"}
    d["initial_state"]["P02"]={"holder":"none","location":"surface:E02:pen_corner"}
    for member in registry["member_source_map"]:
        d["initial_state"][member]={"holder":"none","location":"surface:E02:lin_center"}
    first=ls[0]["step_units"][0]["groups"][0]
    first.update(id="G_SLIDE_NEAR",performance="浅黄便签沿林屿桌面推向方澄，粉蓝不动",
        operations=[{"kind":"slide","actor":"C02","target":"P03_Y","value":"surface:E02:near_fang"}])
    last=ls[1]["step_units"][1]["groups"][0]
    last.update(id="G_SLIDE_BACK",performance="浅黄便签沿原桌面滑回林屿面前，粉蓝不动",
        operations=[{"kind":"slide","actor":"C02","target":"P03_Y","value":"surface:E02:lin_center"}])
    ls[0]["dialogue_performance"]="甲完整说出原句，关键动作与对白依次进行"
    if untimed:
        for beat in c["raw_linear_script"]["beats"]:beat.pop("duration_seconds",None)
    d["context_sha256"]=digest(c)
    d["raw_linear_script_sha256"]=digest(c["raw_linear_script"])
    for index,local in enumerate(ls):
        local["input_sha256"]=digest(build_local_input(c,d,ls[:index]))
    return c,d,ls


def actual_048_compatibility(receipt_path):
    path=Path(receipt_path);before=path.read_bytes();receipt=json.loads(before.decode("utf-8"))
    if receipt.get("status")!="contract_valid":fail("STEP_PHYSICAL_SOURCE_MISSING","不把未完成回执当有效源")
    user=next(m for m in receipt["request"]["messages"] if m["role"]=="user")
    context=deepcopy(json.loads(user["content"])["context"]);context["raw_linear_script"]=deepcopy(receipt["output"])
    schema=build_direction_schema(context);catalog=source_contract.source_catalog(context)
    report={"schema":"actual_048_step_physical_compatibility_offline/v1","source_receipt":str(path.resolve()),
        "source_receipt_sha256":hashlib.sha256(before).hexdigest(),"source_contract_status":receipt["status"],
        "source_narrative_beats":len(context["raw_linear_script"]["beats"]),"source_steps":len(catalog),
        "source_catalog_valid":True,"direction_tool_schema_valid":True,
        "director_generation":"missing","local_generation":"missing","initial_state":"missing",
        "physical_compile_attempted":False,"planned_shot_compatibility":"unknown_missing_direction",
        "source_semantic_review":"not_assessed_by_this_report","semantic_approval":False,"production_ready":False,
        "limits":["only validates an offline schema and source catalog; no real director/local model requests",
                 "requires actual direction, typed locals, compiled state, schedule trace and full review"]}
    Draft202012Validator.check_schema(schema)
    if path.read_bytes()!=before:fail("STEP_PHYSICAL_SOURCE_CHANGED","只读报告期间源回执改变")
    return context,schema,report

if __name__=="__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser();parser.add_argument("--out-dir");parser.add_argument("--actual-048")
    args=parser.parse_args();context,direction,locals_=make_offline_case()
    result=compile_complete(context,direction,locals_)
    outputs={"fixture_case.json":{"context":context,"direction":direction,"locals":locals_},
        "fixture_direction_schema.json":build_direction_schema(context),"fixture_compiled.json":result}
    if args.actual_048:
        c,s,r=actual_048_compatibility(args.actual_048)
        outputs.update(actual_048_context=c,actual_048_direction_schema=s,actual_048_compatibility=r)
        outputs={name if name.endswith(".json") else name+".json":value for name,value in outputs.items()}
    if args.out_dir:
        directory=Path(args.out_dir).resolve()
        if any(part.lower()=="production_trials" for part in directory.parts):
            raise SystemExit("use a separate QA directory")
        directory.mkdir(parents=True,exist_ok=True)
        for name,value in outputs.items():
            target=directory/name
            if target.exists():raise SystemExit("preserve existing artifacts; use fresh QA directory")
            target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":result["status"],"shots":result["execution_shot_count"],
        "physical_state_checked":True,"semantic_approval":False,"paid_calls":0},ensure_ascii=False,indent=2))
