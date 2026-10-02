"""Offline narrative-beat to shot-unit bridge; no model or media dispatch.

The original script is retained verbatim. A separate execution projection lets
the existing v2 compiler carry state across shots. This prototype assigns one
whole source event to one action shot per narrative beat; other shots can carry
dialogue and explicit holds. Splitting a source event into several action shots,
splitting a line, or cross-shot simultaneous performance is unsupported.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator

from src.content_factory.creative_action_plan_v2 import (
    build_action_plan_schema, schedule_action_plan, compile_action_plan,
)
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = "narrative_multishot_bridge_offline_v2"
DIRECTION = "narrative_multishot_direction_offline_v2"
LOCAL = "narrative_multishot_local_offline_v2"
RULES = (
    "保持完整原叙事剧本，不为镜头拆分改写正文。beats按原拍顺序，每拍shots是镜头数组。"
    "每镜必须写新增信息、观察对象、source_refs和切镜理由；引用填写本拍规范路径。"
    "dialogue_indices为本拍原对白下标数组，从0计，全部镜头依次恰好覆盖每句一次；"
    "不拆一句、不重说对白。每拍恰好一镜event_owner=true，承载完整原事件；"
    "其余镜只承载对白和无状态操作的明确hold反应。当前原型不支持把原事件拆成多镜动作。"
    "performance_requirements是数组，subject填人物ID，stimulus_source为本拍规范路径，"
    "relation用before/during/after；事件不可during，跨镜只支持已完成刺激后的after反应。"
    "每条要求的minimum_seconds为正数，局部performance_windows完整绑定真实锚点。"
    "initial_state是首事件前状态；owner不等于holder；固定座椅ID来自manifest。"
    "出现不能表达的并行或跨镜能力缺口应停止，不能靠删画面、改台词或增加叙事拍迁就。"
)

def obj(properties):
    return {"type":"object","additionalProperties":False,"required":list(properties),"properties":properties}

def text():
    return {"type":"string","minLength":1}

def fail(code, message, path=""):
    e=CreativeContractError(code+": "+message)
    e.detail={"code":code,"path":path,"automatic_retry":False,"blocks_handoff":True,
              "semantic_approval":False,"source_script_rewritten":False}
    raise e

def source_catalog(context):
    out={}
    for i,b in enumerate(context["script"]["beats"]):
        paths=[f"script.beats.{i}.event"]
        paths += [f"script.beats.{i}.{name}" for name in ("before","during","after")
                  if isinstance(b.get(name),str) and b[name]]
        paths += [f"script.beats.{i}.dialogue.{d}.text" for d in range(len(b["dialogue"]))]
        out[b["id"]]=paths
    return out


def ensure_supported_source(context):
    """Stop before tool/model dispatch when this projection would erase sequence."""
    scripts=[context["script"]]
    raw=context.get("raw_linear_script")
    if isinstance(raw,dict):scripts.append(raw)
    for script in scripts:
        for beat in script.get("beats",[]):
            if beat.get("steps"):
                fail("BRIDGE_UNSUPPORTED",
                     "本原型尚未实现按steps/action索引分配镜头，不能用event摘要替代原动作对白顺序",
                     beat.get("id",""))
            if any(isinstance(beat.get(key),str) and beat[key].strip() for key in ("before","during","after")):
                fail("BRIDGE_UNSUPPORTED",
                     "源拍存在详细before/during/after正文，本原型不能证明多动作及对白顺序保持",
                     beat.get("id",""))
            if any(isinstance(r,dict) and r.get("kind")=="simultaneous_dialogue_action"
                   for r in beat.get("execution_requirements",[])):
                fail("BRIDGE_UNSUPPORTED","源要求明确需要关键动作与对白并行，当前桥接无法表达",
                     beat.get("id",""))


def build_direction_tool_schema(context):
    ensure_supported_source(context)
    legacy=build_action_plan_schema(context)["properties"]
    paths=[p for row in source_catalog(context).values() for p in row]
    chars=[c["id"] for c in context["static_visual_manifest"]["characters"]]
    requirement=obj({"id":text(),"subject":{"enum":chars},
        "stimulus_source":{"type":"string","enum":paths},"relation":{"enum":["before","during","after"]},
        "minimum_seconds":{"type":"number","exclusiveMinimum":0}})
    shot=obj({"shot_id":text(),"purpose":text(),"composition":text(),"camera":text(),
        "dialogue_mode":{"enum":["画内对白","画外对白","混合对白","无对白"]},"cut_reason":text(),
        "new_information":text(),"observation_object":text(),
        "source_refs":{"type":"array","minItems":1,"uniqueItems":True,"items":{"type":"string","enum":paths}},
        "event_owner":{"type":"boolean"},
        "dialogue_indices":{"type":"array","uniqueItems":True,"items":{"type":"integer","minimum":0}},
        "performance_requirements":{"type":"array","items":requirement}})
    return {**obj({"schema":{"enum":[DIRECTION]},"context_sha256":{"enum":[digest(context)]},
        "emotional_arc":text(),"causal_chain":{"type":"array","minItems":1,"items":text()},"ending_intent":text(),
        "initial_state":deepcopy(legacy["initial_state"]),"spatial_contract":deepcopy(legacy["spatial_contract"]),
        "beats":{"type":"array","minItems":len(context["script"]["beats"]),"maxItems":len(context["script"]["beats"]),
                 "items":obj({"beat_id":{"enum":[b["id"] for b in context["script"]["beats"]]},
                              "shots":{"type":"array","minItems":1,"items":shot}})}}),
        "description":RULES}

def build_direction_messages(context):
    ensure_supported_source(context)
    return [{"role":"system","content":RULES},
        {"role":"user","content":json.dumps({"context":deepcopy(context),
            "source_catalog":source_catalog(context),"context_sha256":digest(context)},
            ensure_ascii=False,separators=(",",":"))}]

def _validate(value,schema):
    errors=list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        e=errors[0]
        fail("BRIDGE_SCHEMA_INVALID",e.message,".".join(map(str,e.absolute_path)))

def validate_direction(context,direction):
    _validate(direction,build_direction_tool_schema(context))
    original=context["script"]["beats"]
    if [b["beat_id"] for b in direction["beats"]] != [b["id"] for b in original]:
        fail("BRIDGE_BEAT_COVERAGE","叙事拍顺序或覆盖不正确")
    seen_shots=set();seen_requirements=set()
    for index,(source,beat) in enumerate(zip(original,direction["beats"])):
        legal=set(source_catalog(context)[source["id"]])
        if sum(s["event_owner"] for s in beat["shots"])!=1:
            fail("BRIDGE_EVENT_OWNERSHIP","原事件必须恰好归属一个动作镜头",source["id"])
        dialogue=[d for s in beat["shots"] for d in s["dialogue_indices"]]
        if dialogue!=list(range(len(source["dialogue"]))):
            fail("BRIDGE_DIALOGUE_COVERAGE","原对白必须按顺序恰好分配一次，不能重复、遗漏或重排",source["id"])
        for shot in beat["shots"]:
            sid=shot["shot_id"]
            if sid in seen_shots:fail("BRIDGE_SHOT_ID","镜头ID重复",sid)
            seen_shots.add(sid)
            if not set(shot["source_refs"])<=legal:
                fail("BRIDGE_SOURCE_REF","镜头来源必须属于本拍",sid)
            for d in shot["dialogue_indices"]:
                if f"script.beats.{index}.dialogue.{d}.text" not in shot["source_refs"]:
                    fail("BRIDGE_SOURCE_REF","已分配对白必须出现在本镜来源引用",sid)
            if shot["event_owner"] and f"script.beats.{index}.event" not in shot["source_refs"]:
                fail("BRIDGE_SOURCE_REF","动作镜必须引用原事件",sid)
            for requirement in shot["performance_requirements"]:
                if requirement["id"] in seen_requirements:
                    fail("BRIDGE_REQUIREMENT_ID","表演要求ID重复",sid)
                seen_requirements.add(requirement["id"])
                ref=requirement["stimulus_source"]
                if ref not in legal:fail("BRIDGE_SOURCE_REF","刺激引用必须属于本拍",sid)
                if not (ref.endswith(".event") or ".dialogue." in ref):
                    fail("BRIDGE_UNSUPPORTED","before/during/after文本的刺激锚点尚未实现",sid)
                if ref.endswith(".event") and requirement["relation"]=="during":
                    fail("BRIDGE_UNSUPPORTED","当前v2动作编译器不能表达事件与反应并行",sid)
        for req_shot in beat["shots"]:
            for r in req_shot["performance_requirements"]:
                ref=r["stimulus_source"]
                trigger=next((s for s in beat["shots"] if s["event_owner"]),None) if ref.endswith(".event") else next(
                    (s for s in beat["shots"] if int(ref.split(".")[-2]) in s["dialogue_indices"]),None)
                if trigger["shot_id"]!=req_shot["shot_id"] and r["relation"]!="after":
                    fail("BRIDGE_UNSUPPORTED","跨镜只实现已完成刺激之后的after窗口",req_shot["shot_id"])

def _local_schema(context,direction,shot):
    fields=build_action_plan_schema(context)["properties"]["beats"]["items"]["properties"]
    return obj({"schema":{"enum":[LOCAL]},"direction_sha256":{"enum":[digest(direction)]},
        "shot_id":{"enum":[shot["shot_id"]]},"input_sha256":text(),"duration_seconds":{"type":"number","exclusiveMinimum":0},
        **{key:deepcopy(fields[key]) for key in ("groups","dialogue_performance","reaction",
                                               "cut_after_event_id","completion_condition")},
        "source_event_anchor":text(),
        "performance_windows":{"type":"array","items":obj({
            "requirement_id":{"enum":[r["id"] for r in shot["performance_requirements"]]},"anchor":text()})}})

def _anchors(local, scheduled,offset):
    out={};gi=0
    for event in scheduled["events"]:
        if event["script_slot"]=="dialogue_performance":
            key="dialogue_"+str(event["dialogue_index"])
        elif gi<len(local["groups"]):
            key=local["groups"][gi]["id"];gi+=1
        else:continue
        out[key]={"start":offset+event["start"],"end":offset+event["end"]}
    return out

def compile_bridge(context,direction,locals_,*,prefix=False):
    """Compile all shot units; any failure preserves source and model drafts."""
    validate_direction(context,direction)
    shots=[s for b in direction["beats"] for s in b["shots"]]
    required=shots[:len(locals_)] if prefix else shots
    if not locals_ or len(locals_)>len(shots) or [l.get("shot_id") for l in locals_] != [s["shot_id"] for s in required]:
        fail("BRIDGE_LOCAL_COVERAGE","局部结果必须按镜头顺序覆盖；完整交付必须覆盖所有镜头")
    derived=deepcopy(context["script"]);derived["beats"]=[]
    plan={"schema":"whole_film_action_plan_v2","initial_state":deepcopy(direction["initial_state"]),
          "spatial_contract":deepcopy(direction["spatial_contract"]),"beats":[]}
    source_map=[];source_triggers={};offset=0
    for bi,(source,unit) in enumerate(zip(context["script"]["beats"],direction["beats"])):
        for shot in unit["shots"]:
            li=len(derived["beats"])
            if li>=len(locals_):break
            local=locals_[li]
            _validate(local,_local_schema(context,direction,shot))
            if not shot["event_owner"] and any(g["kind"]!="hold" or g["operations"] for g in local["groups"]):
                fail("BRIDGE_UNSUPPORTED","非事件镜目前只支持对白和hold；拆分原事件的多个动作镜尚未实现",shot["shot_id"])
            if shot["event_owner"]:
                actions=[g for g in local["groups"] if g["kind"]=="action"]
                if not actions or local["source_event_anchor"]!=actions[-1]["id"]:
                    fail("BRIDGE_EVENT_ANCHOR","原事件锚点须是动作镜最后一个真实action组，不能用hold冒充事件完成",shot["shot_id"])
            projected={"id":shot["shot_id"],"duration_seconds":local["duration_seconds"],
                       "event":source["event"] if shot["event_owner"] else "观察原拍已发生刺激后的反应，原事件不再执行",
                       "dialogue":[deepcopy(source["dialogue"][d]) for d in shot["dialogue_indices"]]}
            if shot["event_owner"] and source.get("execution_requirements"):
                projected["execution_requirements"]=deepcopy(source["execution_requirements"])
            derived["beats"].append(projected)
            row={k:deepcopy(shot[k]) for k in ("purpose","composition","camera","dialogue_mode","cut_reason")}
            row.update(beat_id=shot["shot_id"],**{k:deepcopy(local[k]) for k in (
                "groups","dialogue_performance","reaction","cut_after_event_id","completion_condition")})
            plan["beats"].append(row)
            source_map.append({"shot_id":shot["shot_id"],"source_beat_id":source["id"],
                "source_refs":deepcopy(shot["source_refs"]),"dialogue_indices":deepcopy(shot["dialogue_indices"]),
                "event_owner":shot["event_owner"]})
            if shot["event_owner"]:source_triggers[f"script.beats.{bi}.event"]=(li,local["source_event_anchor"])
            for relative,original in enumerate(shot["dialogue_indices"]):
                source_triggers[f"script.beats.{bi}.dialogue.{original}.text"]=(li,"dialogue_"+str(relative))
    derived["duration_seconds"]=sum(l["duration_seconds"] for l in locals_)
    scheduled,report=schedule_action_plan(plan,derived,context["static_visual_manifest"])
    storyboard=compile_action_plan(plan,derived,context["static_visual_manifest"])
    for i,(local,compiled_shot) in enumerate(zip(locals_,storyboard["shots"])):
        state=_state_by_id(compiled_shot["start_state"],context)
        expected_input=_shot_input(context,direction,i,state,locals_[:i])
        if local["input_sha256"]!=digest(expected_input):
            fail("BRIDGE_STALE_INPUT","局部镜头的原稿、规划、资产、前镜结果或编译首态已改变",local["shot_id"])
    timeline=[];offset=0
    for local,beat in zip(locals_,scheduled["beats"]):
        timeline.append(_anchors(local,beat,offset));offset+=local["duration_seconds"]
    checks=[]
    for i,(shot,local) in enumerate(zip(shots,locals_)):
        windows=local["performance_windows"]
        expected={r["id"]:r for r in shot["performance_requirements"]}
        if len({w["requirement_id"] for w in windows})!=len(windows) or {w["requirement_id"] for w in windows}!=set(expected):
            fail("BRIDGE_WINDOW_COVERAGE","每条表演要求必须恰好绑定一次",shot["shot_id"])
        for window in windows:
            r=expected[window["requirement_id"]];anchor=window["anchor"]
            if anchor not in timeline[i]:fail("BRIDGE_WINDOW_ANCHOR","反应锚点不存在",shot["shot_id"])
            if r["stimulus_source"] not in source_triggers:
                fail("BRIDGE_WINDOW_ORDER","反应镜的刺激尚未发生，不能将未完成前缀当成完整窗口",r["id"])
            ti,ta=source_triggers[r["stimulus_source"]];trigger=timeline[ti].get(ta)
            if trigger is None:fail("BRIDGE_EVENT_ANCHOR","刺激锚点不存在",r["stimulus_source"])
            visible=timeline[i][anchor]
            relation=r["relation"]
            legal=(visible["start"]>=trigger["end"]-1e-8 if relation=="after"
                   else visible["end"]<=trigger["start"]+1e-8 if relation=="before"
                   else i==ti and anchor==ta and ta.startswith("dialogue_"))
            if not legal:fail("BRIDGE_WINDOW_ORDER","反应与刺激的真实时间关系不符合要求",r["id"])
            if visible["end"]-visible["start"]+1e-8<r["minimum_seconds"]:
                fail("BRIDGE_WINDOW_TOO_SHORT","真实反应窗口不足，尾部余量不能抵扣",r["id"])
            group=next((g for g in local["groups"] if g["id"]==anchor),None)
            if group is not None and (group["kind"]!="hold" or group["hold_subject"]!=r["subject"]):
                fail("BRIDGE_WINDOW_SUBJECT","反应窗口必须保持指定观察人物",r["id"])
            checks.append({"requirement_id":r["id"],"shot_id":shot["shot_id"],"source_shot_id":shots[ti]["shot_id"],
                           "relation":relation,"start":visible["start"],"end":visible["end"],"passed":True})
    return {"schema":VERSION,"status":"offline_compiled_pending_full_review","semantic_approval":False,
        "source_script":deepcopy(context["script"]),"source_script_sha256":digest(context["script"]),
        "context_sha256":digest(context),"direction_sha256":digest(direction),
        "derived_execution_script":derived,"derived_action_plan":plan,"source_map":source_map,
        "storyboard":storyboard,"scheduled_execution":scheduled,"schedule":report,"performance_checks":checks,
        "source_narrative_beat_count":len(context["script"]["beats"]),"execution_shot_count":len(locals_),"all_shots_complete":len(locals_)==len(shots),
        "total_duration_seconds":derived["duration_seconds"],"full_review_required":True,"prefix_only":prefix,
        "automatic_media_submit":False,
         "limitations":["structured steps and detailed before/during/after source text are unsupported and rejected before tool dispatch",
                       "one whole source event per narrative beat has one action-shot owner",
                       "non-owner shots currently support holds and allocated complete dialogue only",
                       "cross-shot only completed-stimulus after windows are implemented",
                       "free prose, action completeness, facial readability and cinematic quality require full review"]}


def _state_by_id(state_text,context):
    state=json.loads(state_text)
    out={}
    for entity in context["static_visual_manifest"]["characters"]+context["static_visual_manifest"]["props"]:
        keys=[k for k in state if k==entity["id"] or k.startswith(entity["id"]+"(")]
        if len(keys)!=1:fail("BRIDGE_STATE_ID","编译状态没有唯一实体",entity["id"])
        out[entity["id"]]=deepcopy(state[keys[0]])
    return out

def _shot_input(context,direction,index,state,completed_locals):
    shots=[s for b in direction["beats"] for s in b["shots"]]
    return {"schema":"narrative_multishot_input_offline_v2","protocol":VERSION,
        "context":deepcopy(context),"direction":deepcopy(direction),"shot_id":shots[index]["shot_id"],
        "start_state":deepcopy(state),"previous_local_sha256":[digest(l) for l in completed_locals],
        "future_shot_ids":[s["shot_id"] for s in shots[index+1:]]}

def build_shot_direction_schema(context):
    return build_direction_tool_schema(context)

def validate_shot_direction(direction,context):
    return validate_direction(context,direction)

def build_shot_local_input(context,direction,completed_locals):
    validate_direction(context,direction)
    shots=[s for b in direction["beats"] for s in b["shots"]]
    if len(completed_locals)>=len(shots):fail("BRIDGE_ALREADY_COMPLETE","所有镜头已完成")
    if completed_locals:
        compiled=compile_bridge(context,direction,completed_locals,prefix=True)
        state=_state_by_id(compiled["storyboard"]["shots"][-1]["end_state"],context)
    else:state=deepcopy(direction["initial_state"])
    return _shot_input(context,direction,len(completed_locals),state,completed_locals)

def build_shot_local_schema(context,direction,shot_id):
    from src.content_factory.creative_modular_tool_export import _simple_schema
    validate_direction(context,direction)
    shot=next((s for b in direction["beats"] for s in b["shots"] if s["shot_id"]==shot_id),None)
    if shot is None:fail("BRIDGE_SHOT_ID","镜头不存在",shot_id)
    schema=_simple_schema(_local_schema(context,direction,shot))
    schema["description"]=(
        "提交本镜完整局部结果，input_sha256照请求身份填写，不能修改start_state或原对白。"
        "event_owner=false只能hold或已分配对白，不执行原事件；groups和operations直接用数组。"
        "动作组结束才改变状态，依赖前提必须拆组；窗口绑定真实组ID或dialogue_N，指定hold人物和完整时长。"
        "跨镜仅支持已发生刺激之后的after；未实现的动作跨镜或并行不能通过改写原剧情规避。")
    return schema

def build_shot_local_messages(local_input):
    if local_input.get("schema")!="narrative_multishot_input_offline_v2":
        fail("BRIDGE_INPUT","局部消息须来自build_shot_local_input")
    return [{"role":"system","content":"提交当前镜完整局部表演，原剧情不改。input_sha256照request_identity填写；首态由编译器决定。"+RULES},
        {"role":"user","content":json.dumps({"local_input":deepcopy(local_input),
            "request_identity":{"input_sha256":digest(local_input)}},ensure_ascii=False,separators=(",",":"))}]

def compile_shot_prefix(context,direction,locals_):
    return compile_bridge(context,direction,locals_,prefix=True)

def compile_shot_complete(context,direction,locals_):
    return compile_bridge(context,direction,locals_)


def make_offline_case():
    """Two original narrative beats, four shots; fixture only, never a production draft."""
    manifest={"schema":"static_visual_manifest_v1",
        "render":{"style_option_id":"S01","visual_medium":"二维手绘动画","palette":"灰蓝米白","light_source":"右上暖灯"},
        "characters":[{"id":cid,"name":name,"age_group":"成年","hair":"短发","clothing":"通勤衬衣","body_shape":"成年体型"}
                      for cid,name in (("C01","甲"),("C02","乙"))],
        "props":[{"id":"P01","name":"文件夹","appearance":"墨蓝A4封面","owner_id":"C02"}],
        "scene":{"name":"办公室","elements":[{"id":"E01","name":"桌子","appearance":"米白桌面"},
                 {"id":"E02","name":"椅子","appearance":"深灰靠背椅"}],
                 "relations":[{"subject":"E02","relation":"behind","reference":"E01"}]}}
    script={"title":"离线多镜桥接样例","duration_seconds":12,"beats":[
        {"id":"B1","duration_seconds":6,"event":"乙拿起桌上的文件夹","dialogue":[{"speaker":"乙","text":"明天见。"}]},
        {"id":"B2","duration_seconds":6,"event":"乙坐下","dialogue":[]}]}
    context={"fixture_only":True,"script":script,"static_visual_manifest":manifest,
         "references":[{"id":"R01","text":"离线表达机制：刺激完成后切到承受者可读反应。"}],"selected_assets":[],
        "fixture_action_dialogue_order":[["action","take"],["dialogue","明天见。"],["action","sit"]]}
    initial={"C01":{"posture":"standing","position":"桌前","gaze":"C02","affect":"平静","facing":"桌面"},
        "C02":{"posture":"standing","position":"桌旁","gaze":"C01","affect":"平静","facing":"桌面"},
        "P01":{"holder":"none","location":"桌面"}}
    direction={"schema":DIRECTION,"context_sha256":digest(context),"emotional_arc":"离开意图到暂缓",
        "causal_chain":["拿起文件夹使离开意图可见","坐下使暂缓成为具体行动"],"ending_intent":"停留在对方反应上",
        "initial_state":initial,"spatial_contract":{"seats":[{"seat_id":"E02","access_positions":["桌旁"],"required_facing":"桌面"}]},
        "beats":[]}
    for i in range(2):
        prefix=f"script.beats.{i}";units=[]
        for n in (1,2):
            shot={"shot_id":f"B{i+1}_S{n}","purpose":"原事件" if n==1 else "让反应可读",
                "composition":"行动中景" if n==1 else "甲的反应近景","camera":"稳定单机位",
                "dialogue_mode":"画内对白" if i==0 and n==1 else "无对白","cut_reason":"新增事实后观察影响",
                "new_information":"既定行动已完成" if n==1 else "甲承受行动后的态度",
                "observation_object":"乙" if n==1 else "甲","source_refs":[prefix+".event"],
                "event_owner":n==1,"dialogue_indices":[0] if i==0 and n==1 else [],
                "performance_requirements":[]}
            if i==0 and n==1:shot["source_refs"].append(prefix+".dialogue.0.text")
            if n==2:shot["performance_requirements"]=[{"id":f"R{i+1}","subject":"C01",
                "stimulus_source":prefix+".dialogue.0.text" if i==0 else prefix+".event",
                "relation":"after","minimum_seconds":2}]
            units.append(shot)
        direction["beats"].append({"beat_id":f"B{i+1}","shots":units})
    locals_=[]
    for i,beat in enumerate(direction["beats"]):
        for n,shot in enumerate(beat["shots"],1):
            gid=f"G{i+1}_{n}"
            operation=({"kind":"take","actor":"C02","target":"P01","value":"右手"} if i==0
                       else {"kind":"sit","actor":"C02","target":"E02","value":"椅上"})
            groups=[{"id":gid,"script_slot":"before","kind":"action" if n==1 else "hold",
                "duration_seconds":1 if n==1 else 2,"hold_subject":"" if n==1 else "C01",
                "performance":"完成原事件" if n==1 else "保持甲可读的反应","operations":[operation] if n==1 else []}]
            locals_.append({"schema":LOCAL,"direction_sha256":digest(direction),"shot_id":shot["shot_id"],
                "duration_seconds":3,"groups":groups,"dialogue_performance":"原说话人自然完整说出原台词",
                "reaction":{"anchor":gid,"subject":"C01","meaning":"观察影响"},
                "cut_after_event_id":"dialogue_0" if i==0 and n==1 else gid,
                "completion_condition":"all_required_events_complete","source_event_anchor":gid,
                "performance_windows":[] if n==1 else [{"requirement_id":f"R{i+1}","anchor":gid}]})
    completed=[]
    for local in locals_:
        local["input_sha256"]=digest(build_shot_local_input(context,direction,completed))
        completed.append(local)
    return context,direction,locals_

if __name__=="__main__":
    import argparse,sys
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser();parser.add_argument("--out-dir")
    args=parser.parse_args();context,direction,locals_=make_offline_case()
    compiled=compile_bridge(context,direction,locals_)
    if args.out_dir:
        output=Path(args.out_dir).resolve()
        if "production_trials" in output.parts:raise SystemExit("offline artifacts cannot be saved in production trials")
        output.mkdir(parents=True,exist_ok=True)
        for name,value in {"case.json":{"context":context,"direction":direction,"locals":locals_},
                           "director_tool_schema.json":build_direction_tool_schema(context),
                           "compiled.json":compiled}.items():
            target=output/name
            if target.exists():raise SystemExit("preserve existing artifacts; choose a fresh output directory")
            target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":compiled["status"],"narrative_beats":2,"shots":4,
                      "reaction_checks":compiled["performance_checks"],"paid_calls":0},ensure_ascii=False,indent=2))
