"""Offline opt-in contract prototype; no production registration or model dispatch.

Direction owns narrative/camera/layout. Local performance owns action groups.
The existing v2 compiler alone derives state and timing. No formal draft adoption.
"""
from __future__ import annotations
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from .creative_stage_contracts import digest
from .creative_workflow_contract import CreativeContractError
from .creative_action_plan_v2 import build_action_plan_schema, schedule_action_plan, compile_action_plan

VERSION = "modular_direction_performance_offline_v1"
DIRECTION = "whole_film_direction_offline_v1"
LOCAL = "local_performance_offline_v1"
INPUT = "local_performance_input_offline_v1"


def _object(properties):
    return {"type":"object","additionalProperties":False,
            "required":list(properties),"properties":properties}


def _text():
    return {"type":"string","minLength":1}


def _fail(code, path, message):
    error=CreativeContractError(code + ": " + message)
    error.detail={"code":code,"path":path,"blocks_handoff":True,
                  "automatic_retry":False,"semantic_approval":False}
    raise error


def _validate(value, schema):
    errors=list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        e=errors[0]
        _fail("MODULE_SCHEMA_INVALID",".".join(map(str,e.absolute_path)),e.message)


def build_direction_schema(context):
    base=build_action_plan_schema(context)["properties"]
    fields=base["beats"]["items"]["properties"]
    character_ids=[c["id"] for c in context["static_visual_manifest"]["characters"]]
    requirement=_object({
        "id":_text(),"subject":{"type":"string","enum":character_ids},
        "stimulus_source":_text(),"relation":{"enum":["before","during","after"]},
        "minimum_seconds":{"type":"number","exclusiveMinimum":0}})
    unit=_object({**{k:deepcopy(fields[k]) for k in (
        "beat_id","purpose","composition","camera","dialogue_mode","cut_reason")},
        "new_information":_text(),"observation_object":_text(),"stimulus":_text(),
        "audience_feeling":_text(),
        "performance_requirements":{"type":"array","items":requirement}})
    n=len(context["script"]["beats"])
    return _object({"schema":{"const":DIRECTION},"context_sha256":{"const":digest(context)},
        "duration_policy":{"const":"floating_local_allocation"},
        "emotional_arc":_text(),
        "causal_chain":{"type":"array","minItems":1,"items":_text()},
        "ending_intent":_text(),
        "initial_state":deepcopy(base["initial_state"]),
        "spatial_contract":deepcopy(base["spatial_contract"]),
        "beats":{"type":"array","minItems":n,"maxItems":n,"items":unit}})


def validate_direction(direction,context):
    _validate(direction,build_direction_schema(context))
    script=context["script"]
    if [b["beat_id"] for b in direction["beats"]] != [b["id"] for b in script["beats"]]:
        _fail("MODULE_BEAT_ORDER","beats","整片规划必须按原剧本覆盖全部拍")
    ids=set()
    for i,unit in enumerate(direction["beats"]):
        legal_sources={f"script.beats.{i}.event"} | {
            f"script.beats.{i}.dialogue.{d}.text" for d in range(len(script["beats"][i]["dialogue"]))}
        for r in unit["performance_requirements"]:
            if r["id"] in ids or r["stimulus_source"] not in legal_sources:
                _fail("MODULE_REQUIREMENT_SOURCE",f"beats.{i}","要求ID重复或刺激引用不属于本拍")
            if r["relation"]=="during" and r["stimulus_source"].endswith(".event"):
                _fail("EXPRESSION_UNSUPPORTED",f"beats.{i}","当前离线适配器不能表达关键动作与表演同时发生")
            ids.add(r["id"])


def build_local_schema(context, direction, beat_id):
    fields=build_action_plan_schema(context)["properties"]["beats"]["items"]["properties"]
    unit=next(u for u in direction["beats"] if u["beat_id"]==beat_id)
    return _object({"schema":{"const":LOCAL},"beat_id":{"const":beat_id},"input_sha256":_text(),
        "duration_seconds":{"type":"number","exclusiveMinimum":0},
        **{k:deepcopy(fields[k]) for k in ("groups","dialogue_performance","reaction","cut_after_event_id","completion_condition")},
        "source_event_anchor":_text(),
        "performance_windows":{"type":"array","items":_object({
            "requirement_id":{"type":"string","enum":[r["id"] for r in unit["performance_requirements"]]},
            "anchor":_text()})}})


def _state_by_id(state_text,context):
    state=json.loads(state_text)
    entities=context["static_visual_manifest"]["characters"]+context["static_visual_manifest"]["props"]
    result={}
    for entity in entities:
        matches=[k for k in state if k==entity["id"] or k.startswith(entity["id"]+"(")]
        if len(matches)!=1:
            _fail("MODULE_BOUNDARY_MISSING",entity["id"],"编译首尾态缺少唯一实体")
        result[entity["id"]]=deepcopy(state[matches[0]])
    return result


def _input(context,direction,index,prior):
    return {"schema":INPUT,"protocol":VERSION,
        "context":deepcopy(context),"direction":deepcopy(direction),
        "beat_id":context["script"]["beats"][index]["id"],
        "previous_compilation_sha256":digest(prior) if prior else None,
        "start_state":_state_by_id(prior["storyboard"]["shots"][-1]["end_state"],context)
                      if prior else deepcopy(direction["initial_state"]),
        "future_beat_ids":[b["id"] for b in context["script"]["beats"][index+1:]]}


def _anchors(local,scheduled):
    result={}
    gi=0
    for event in scheduled["events"]:
        if event["script_slot"]=="dialogue_performance":
            name="dialogue_"+str(event["dialogue_index"])
        elif gi<len(local["groups"]):
            name=local["groups"][gi]["id"];gi+=1
        else:
            continue  # anonymous generated tail hold cannot satisfy a named window
        if name in result:
            _fail("MODULE_ANCHOR_DUPLICATE",name,"动作与对白锚不能重名")
        result[name]=event
    return result


def _check_windows(direction,locals_,scheduled):
    checks=[]
    for i,(unit,local,row) in enumerate(zip(direction["beats"],locals_,scheduled["beats"])):
        anchors=_anchors(local,row)
        group_ids={g["id"] for g in local["groups"]}
        if local["source_event_anchor"] not in group_ids:
            _fail("MODULE_EVENT_ANCHOR",unit["beat_id"],"源事件须绑定模型实际动作组")
        requirements={r["id"]:r for r in unit["performance_requirements"]}
        windows={w["requirement_id"]:w for w in local["performance_windows"]}
        if len(windows)!=len(local["performance_windows"]) or set(windows)!=set(requirements):
            _fail("MODULE_WINDOW_COVERAGE",unit["beat_id"],"每项表演窗口要求必须恰好覆盖一次")
        groups={g["id"]:g for g in local["groups"]}
        for rid,requirement in requirements.items():
            source=requirement["stimulus_source"]
            stimulus=("dialogue_"+source.split(".")[-2]) if ".dialogue." in source else local["source_event_anchor"]
            anchor=windows[rid]["anchor"]
            if anchor not in anchors or stimulus not in anchors:
                _fail("MODULE_WINDOW_ANCHOR",rid,"表演或刺激锚不存在")
            visible,trigger=anchors[anchor],anchors[stimulus]
            relation=requirement["relation"]
            legal=(visible["end"]<=trigger["start"]+1e-8 if relation=="before"
                   else anchor==stimulus and stimulus.startswith("dialogue_") if relation=="during"
                   else visible["start"]>=trigger["end"]-1e-8)
            if not legal:
                _fail("MODULE_STIMULUS_REACTION_ORDER",rid,"表演窗口与刺激的先后关系错误")
            if visible["end"]-visible["start"]+1e-8<requirement["minimum_seconds"]:
                _fail("MODULE_WINDOW_TOO_SHORT",rid,"表演窗口不足，不得用镜尾余量冒充")
            if anchor in groups and groups[anchor]["kind"]=="hold" and groups[anchor]["hold_subject"]!=requirement["subject"]:
                _fail("MODULE_WINDOW_SUBJECT",rid,"保持组人物与要求的观察人物不符")
            checks.append({"requirement_id":rid,"subject":requirement["subject"],"relation":relation,
                "stimulus_anchor":stimulus,"performance_anchor":anchor,
                "window":{"start":visible["start"],"end":visible["end"]},
                "timing_status":"passed","face_readability":"requires_full_semantic_review"})
    return checks


def _compile_prefix(context,direction,locals_):
    validate_direction(direction,context)
    prior=None
    for i,local in enumerate(locals_):
        if i>=len(direction["beats"]):
            _fail("MODULE_BEAT_ORDER","locals","局部模块多于全片拍数")
        bid=direction["beats"][i]["beat_id"]
        _validate(local,build_local_schema(context,direction,bid))
        expected=_input(context,direction,i,prior)
        if local["input_sha256"]!=digest(expected):
            _fail("MODULE_STALE_INPUT",bid,"局部安排的全文、整片规划、资产或前拍编译身份已变化")
        # Adapt freshly bound sources, never overwrite the original script.
        script=deepcopy(context["script"]);script["beats"]=script["beats"][:i+1]
        plan={"schema":"whole_film_action_plan_v2","initial_state":deepcopy(direction["initial_state"]),
              "spatial_contract":deepcopy(direction["spatial_contract"]),"beats":[]}
        for j,item in enumerate(locals_[:i+1]):
            script["beats"][j]["duration_seconds"]=item["duration_seconds"]
            unit=direction["beats"][j]
            row={k:deepcopy(unit[k]) for k in ("beat_id","purpose","composition","camera","dialogue_mode","cut_reason")}
            row.update({k:deepcopy(item[k]) for k in ("groups","dialogue_performance","reaction","cut_after_event_id","completion_condition")})
            plan["beats"].append(row)
        manifest=context["static_visual_manifest"]
        scheduled,report=schedule_action_plan(plan,script,manifest)
        storyboard=compile_action_plan(plan,script,manifest)
        checks=_check_windows(direction,locals_[:i+1],scheduled)
        prior={"schema":"modular_prefix_compilation_offline_v1","protocol":VERSION,
            "context_sha256":digest(context),"direction_sha256":digest(direction),
            "local_sha256":[digest(v) for v in locals_[:i+1]],
            "derived_action_plan":plan,"derived_timing_script":script,
            "storyboard":storyboard,"schedule":report,"performance_checks":checks,
            "source_ownership":{"narrative_camera":"direction","actions_performance":"local",
                "dialogue":"original_script","state_and_time":"compiler"},
            "status":"offline_compiled_pending_full_review","semantic_approval":False}
    return prior


def build_local_input(context,direction,completed_locals):
    validate_direction(direction,context)
    index=len(completed_locals)
    if index>=len(direction["beats"]):
        _fail("MODULE_ALREADY_COMPLETE","locals","全部局部模块已完成")
    prior=_compile_prefix(context,direction,completed_locals) if completed_locals else None
    return _input(context,direction,index,prior)


def compile_complete(context,direction,locals_):
    if len(locals_)!=len(context["script"]["beats"]):
        _fail("MODULE_INCOMPLETE","locals","必须覆盖全片，不能把局部样例作为完整交付")
    result=_compile_prefix(context,direction,locals_)
    result["schema"]="modular_complete_compilation_offline_v1"
    result["requires_complete_model_plan_and_full_review"]=True
    result["automatic_media_submit"]=False
    return result


def invalidation_scope(context,change,*,beat_id=None):
    ids=[b["id"] for b in context["script"]["beats"]]
    if change in ("script","references","selected_assets","direction","initial_state","compiler"):
        start=0;direction_invalid=change!="compiler"
    elif change=="local_performance" and beat_id in ids:
        start=ids.index(beat_id);direction_invalid=False
    else:
        _fail("MODULE_UNKNOWN_CHANGE","change","必须明确变化来源及拍ID")
    return {"direction_invalid":direction_invalid,
        "local_inputs_invalid":ids[start:],"reusable_local_prefix":ids[:start],
        "compiled_prefixes_invalid":ids[start:],
        "complete_plan_full_review_invalid":True,"handoff_invalid":True,"media_previews_invalid":True,
        "existing_media_receipts_preserved":True,"budget_reset":False,
        "semantic_revision_adoption":"complete_new_model_plan_then_full_review"}
