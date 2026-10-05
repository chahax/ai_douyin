"""Source-order contract only: linear steps to shots, version 3.

No model dispatch, physical compilation, source rewriting, or draft adoption.
Action text remains owned by raw_linear_script; reaction remains kind=action.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION="linear_step_shot_source_contract_offline_v3"
DIRECTION="linear_step_shot_direction_offline_v3"
LOCAL="linear_step_shot_local_bindings_offline_v3"
RULES=(
    "原raw_linear_script.steps是唯一播放顺序，event仅为摘要，不作为动作源。"
    "整片情绪、因果、结尾方向独立填写；每拍shots数组只分配镜头。"
    "source_step_refs填写raw_linear_script.beats.N.steps.M完整路径，每镜是本拍连续步骤区间，"
    "全部镜依次恰好覆盖原步骤一次，不拆步骤、不复制、不跨拍重排，不改原text或speaker。"
    "动作组action_ref只绑定kind=action的原步骤；反应也仍为原action，可标semantic_role=reaction。"
    "对白只引用原dialogue步骤，不重新输出台词。"
    "本合同只验证源覆盖与先后，物理动作、反应时长、状态及成片感染力仍待后续编译和全文审查。"
)

def obj(properties):
    return {"type":"object","additionalProperties":False,"required":list(properties),"properties":properties}

def text():return {"type":"string","minLength":1}

def fail(code,message,path=""):
    e=CreativeContractError(code+": "+message)
    e.detail={"code":code,"path":path,"blocks_handoff":True,"automatic_retry":False,
              "semantic_approval":False,"physical_compile_attempted":False}
    raise e

def source_catalog(context):
    raw=context.get("raw_linear_script")
    if not isinstance(raw,dict) or not isinstance(raw.get("beats"),list) or not raw["beats"]:
        fail("STEP_SOURCE_REQUIRED","必须提供完整raw_linear_script；不能从event摘要推导步骤")
    entries=[]
    seen=set()
    for bi,beat in enumerate(raw["beats"]):
        if not isinstance(beat.get("id"),str) or not beat["id"] or beat["id"] in seen:
            fail("STEP_SOURCE_INVALID","原拍ID须唯一")
        seen.add(beat["id"])
        if not isinstance(beat.get("steps"),list) or not beat["steps"]:
            fail("STEP_SOURCE_INVALID","原拍必须有完整steps",beat["id"])
        for si,step in enumerate(beat["steps"]):
            if not isinstance(step,dict) or set(step)!={"kind","speaker","text"}:
                fail("STEP_SOURCE_INVALID","原步骤字段必须为kind/speaker/text",beat["id"])
            if step["kind"] not in ("action","dialogue") or not isinstance(step["text"],str) or not step["text"].strip():
                fail("STEP_SOURCE_INVALID","只接受完整action/dialogue原步骤",beat["id"])
            if not isinstance(step["speaker"],str) or (step["kind"]=="action" and step["speaker"]!="") or (
                    step["kind"]=="dialogue" and not step["speaker"].strip()):
                fail("STEP_SOURCE_INVALID","原步骤说话人不合法",beat["id"])
            entries.append({"ref":f"raw_linear_script.beats.{bi}.steps.{si}","beat_id":beat["id"],
                "beat_index":bi,"step_index":si,"kind":step["kind"]})
    return entries

def _source_map(context):
    return {r["ref"]:context["raw_linear_script"]["beats"][r["beat_index"]]["steps"][r["step_index"]]
            for r in source_catalog(context)}

def build_direction_schema(context):
    catalog=source_catalog(context);raw=context["raw_linear_script"]
    shot=obj({"shot_id":text(),"source_step_refs":{"type":"array","minItems":1,"uniqueItems":True,
        "items":{"type":"string","enum":[r["ref"] for r in catalog]}},
        "new_information":text(),"observation_object":text(),"camera":text(),"cut_reason":text()})
    return {**obj({"schema":{"enum":[DIRECTION]},"context_sha256":{"enum":[digest(context)]},
        "raw_linear_script_sha256":{"enum":[digest(raw)]},"emotional_arc":text(),
        "causal_chain":{"type":"array","minItems":1,"items":text()},"ending_intent":text(),
        "beats":{"type":"array","minItems":len(raw["beats"]),"maxItems":len(raw["beats"]),
                 "items":obj({"beat_id":{"enum":[b["id"] for b in raw["beats"]]},
                              "shots":{"type":"array","minItems":1,"items":shot}})}}),"description":RULES}

def _validate(value,schema):
    errors=list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        e=errors[0];fail("STEP_SCHEMA_INVALID",e.message,".".join(map(str,e.absolute_path)))

def validate_direction(direction,context):
    _validate(direction,build_direction_schema(context))
    raw=context["raw_linear_script"];catalog=source_catalog(context)
    if [b["beat_id"] for b in direction["beats"]] != [b["id"] for b in raw["beats"]]:
        fail("STEP_BEAT_COVERAGE","全部原拍必须按原顺序覆盖")
    ids=set()
    for beat in direction["beats"]:
        expected=[r["ref"] for r in catalog if r["beat_id"]==beat["beat_id"]]
        allocated=[]
        for shot in beat["shots"]:
            if shot["shot_id"] in ids:fail("STEP_SHOT_ID","镜头ID重复",shot["shot_id"])
            ids.add(shot["shot_id"]);refs=shot["source_step_refs"]
            if any(r not in expected for r in refs):
                fail("STEP_CROSS_BEAT","镜头步骤不属于本拍",shot["shot_id"])
            positions=[expected.index(r) for r in refs]
            if positions!=list(range(positions[0],positions[0]+len(positions))):
                fail("STEP_NONCONTIGUOUS","每镜只能承担连续的原步骤区间",shot["shot_id"])
            allocated.extend(refs)
        if allocated!=expected:
            fail("STEP_SOURCE_COVERAGE","原步骤必须恰好一次、按原顺序分配；不能省略、复制或重排",beat["beat_id"])

def build_local_input(context,direction,shot_id):
    validate_direction(direction,context)
    shot=next((s for b in direction["beats"] for s in b["shots"] if s["shot_id"]==shot_id),None)
    if shot is None:fail("STEP_SHOT_ID","镜头不在方向中",shot_id)
    return {"schema":"linear_step_shot_input_offline_v3","context":deepcopy(context),
        "direction":deepcopy(direction),"shot_id":shot_id,
        "physical_start_state_status":"requires_compiler_derived_state"}

def build_local_schema(context,direction,shot_id):
    source=_source_map(context);local_input=build_local_input(context,direction,shot_id)
    shot=next(s for b in direction["beats"] for s in b["shots"] if s["shot_id"]==shot_id)
    refs=shot["source_step_refs"];action_refs=[r for r in refs if source[r]["kind"]=="action"]
    dialogue_refs=[r for r in refs if source[r]["kind"]=="dialogue"]
    chars=[c["id"] for c in context.get("static_visual_manifest",{}).get("characters",[])]
    group=obj({"id":text(),"action_ref":{"type":"string","enum":action_refs},
        "semantic_role":{"enum":["action","reaction"]},"kind":{"enum":["action","hold"]},
        "duration_seconds":{"type":"number","exclusiveMinimum":0},"hold_subject":{"enum":["",*chars]}})
    return {**obj({"schema":{"enum":[LOCAL]},"input_sha256":{"enum":[digest(local_input)]},
        "shot_id":{"enum":[shot_id]},"step_units":{"type":"array","minItems":len(refs),"maxItems":len(refs),
            "items":obj({"source_step_ref":{"type":"string","enum":refs},
                "groups":{"type":"array","items":group},
                "dialogue_ref":{"enum":[None,*dialogue_refs]}})}}),
        "description":RULES+"每原步骤一个step_unit；action的groups非空、dialogue_ref=null；"
            "dialogue的groups=[]且dialogue_ref等于自身引用。不得添加text/speaker或物理operations来冒充编译。"}

def validate_local(local,context,direction):
    _validate(local,build_local_schema(context,direction,local["shot_id"]))
    shot=next(s for b in direction["beats"] for s in b["shots"] if s["shot_id"]==local["shot_id"])
    source=_source_map(context)
    if [u["source_step_ref"] for u in local["step_units"]]!=shot["source_step_refs"]:
        fail("STEP_LOCAL_COVERAGE","局部单元必须逐一按导演分配顺序覆盖原步骤")
    for unit in local["step_units"]:
        ref=unit["source_step_ref"];step=source[ref]
        if step["kind"]=="dialogue":
            if unit["groups"] or unit["dialogue_ref"]!=ref:
                fail("STEP_DIALOGUE_BINDING","对白只引用原步骤一次，不能附加动作或重写台词",ref)
        else:
            if not unit["groups"] or unit["dialogue_ref"] is not None:
                fail("STEP_ACTION_BINDING","每action须有绑定动作组，不能冒充对白或删掉",ref)
            for group in unit["groups"]:
                if group["action_ref"]!=ref:
                    fail("STEP_ACTION_BINDING","动作组只能绑定所在原action步骤",ref)
                if not math.isfinite(group["duration_seconds"]):
                    fail("STEP_ACTION_BINDING","时长必须有限",ref)
                if (group["kind"]=="hold") != bool(group["hold_subject"]):
                    fail("STEP_ACTION_BINDING","hold须有观察人物，action的hold_subject为空",ref)

def build_direction_messages(context):
    return [{"role":"system","content":RULES},
        {"role":"user","content":json.dumps({"context":deepcopy(context),"source_catalog":source_catalog(context)},
                                          ensure_ascii=False,separators=(",",":"))}]

def build_local_messages(local_input):
    return [{"role":"system","content":RULES},
        {"role":"user","content":json.dumps({"local_input":deepcopy(local_input),
            "request_identity":{"input_sha256":digest(local_input)}},ensure_ascii=False,separators=(",",":"))}]

def project_complete(context,direction,locals_):
    """Prove references/order only. This deliberately does NOT call a state compiler."""
    validate_direction(direction,context)
    shots=[s for b in direction["beats"] for s in b["shots"]]
    if [l.get("shot_id") for l in locals_] != [s["shot_id"] for s in shots]:
        fail("STEP_LOCAL_COVERAGE","全片局部单元须按镜头完整覆盖")
    source=_source_map(context);execution=[];mapping=[];group_ids=set()
    for shot,local in zip(shots,locals_):
        validate_local(local,context,direction)
        for unit in local["step_units"]:
            ref=unit["source_step_ref"]
            for group in unit["groups"]:
                if group["id"] in group_ids:fail("STEP_GROUP_ID","动作组ID全片重复",group["id"])
                group_ids.add(group["id"])
            execution.append({"shot_id":shot["shot_id"],"source_step_ref":ref,
                "source_step":deepcopy(source[ref]),"groups":deepcopy(unit["groups"]),
                "dialogue_ref":unit["dialogue_ref"]})
            mapping.append({"source_step_ref":ref,"shot_id":shot["shot_id"],"kind":source[ref]["kind"],
                "source_step_sha256":digest(source[ref]),"group_ids":[g["id"] for g in unit["groups"]]})
    if [e["source_step_ref"] for e in execution] != [r["ref"] for r in source_catalog(context)]:
        fail("STEP_SOURCE_COVERAGE","执行投影改变原步骤顺序或覆盖")
    return {"schema":VERSION,"status":"source_order_valid_pending_physical_binding",
        "raw_linear_script":deepcopy(context["raw_linear_script"]),
        "raw_linear_script_sha256":digest(context["raw_linear_script"]),"context_sha256":digest(context),
        "direction_sha256":digest(direction),"ordered_execution":execution,"source_map":mapping,
        "source_coverage_passed":True,"source_order_passed":True,"source_text_rewritten":False,
        "dialogue_once_in_original_order":True,"event_summary_used_as_action":False,
        "physical_compile_attempted":False,"physical_state_verified":False,"action_semantics_verified":False,
        "reaction_timing_verified":False,"semantic_approval":False,"production_ready":False,
        "automatic_media_submit":False,
        "compiler_boundary":{"required_next":["typed operations grounded in each original action_ref",
            "compiler-derived start state and physical preconditions per shot",
            "prove v2 scheduled action/dialogue trace equals original steps order",
            "reaction duration/subject/trigger windows and full semantic review"],
            "unsupported_without_new_adapter":["direct use of event-owner v2 bridge for multi-step beats",
                "splitting one source step across shots","critical action/dialogue simultaneity"],
            "reason":"现有v2接受before/during/after组与对白窗口；需要源steps索引适配及排程回读校验，不能直接把本投影当物理通过"}}

def make_offline_case():
    raw={"title":"单拍多镜顺序夹具","premise":"拒绝后各自承担","selected_candidate_id":"FIXTURE",
        "beats":[{"id":"B1","duration_seconds":8,"event":"仅摘要，不用于生成动作","trigger":"听后反应承接选择",
                  "steps":[{"kind":"action","speaker":"","text":"乙把杯子放到桌上。"},
                    {"kind":"dialogue","speaker":"乙","text":"这次你自己做。"},
                    {"kind":"action","speaker":"","text":"甲听完后停两秒，看着乙。"},
                    {"kind":"action","speaker":"","text":"乙拿起笔，开始核对。"}]}]}
    c={"fixture_only":True,"raw_linear_script":raw,
       "static_visual_manifest":{"characters":[{"id":"C01","name":"甲"},{"id":"C02","name":"乙"}]},
       "references":[{"id":"R01","text":"离线夹具：对白后先观察承受者，再推进下一行动。"}],"selected_assets":[]}
    refs=[r["ref"] for r in source_catalog(c)]
    d={"schema":DIRECTION,"context_sha256":digest(c),"raw_linear_script_sha256":digest(raw),
        "emotional_arc":"明确边界后由双方承受","causal_chain":["对白后先见反应","反应后再见行动"],
        "ending_intent":"把变化落在具体行动上","beats":[{"beat_id":"B1","shots":[
            {"shot_id":"S1","source_step_refs":refs[:2],"new_information":"选择被说清",
             "observation_object":"乙","camera":"中景","cut_reason":"对白完成后看承受者"},
            {"shot_id":"S2","source_step_refs":refs[2:],"new_information":"双方开始承受结果",
             "observation_object":"甲后转乙","camera":"连续观察","cut_reason":"新的实际行动完成"}]}]}
    locals_=[]
    for si,shot in enumerate(d["beats"][0]["shots"]):
        units=[]
        for ref in shot["source_step_refs"]:
            index=refs.index(ref);step=raw["beats"][0]["steps"][index]
            groups=[] if step["kind"]=="dialogue" else [{"id":f"G{index}","action_ref":ref,
                "semantic_role":"reaction" if index==2 else "action","kind":"hold" if index==2 else "action",
                "duration_seconds":2 if index==2 else 1,"hold_subject":"C01" if index==2 else ""}]
            units.append({"source_step_ref":ref,"groups":groups,"dialogue_ref":ref if step["kind"]=="dialogue" else None})
        locals_.append({"schema":LOCAL,"shot_id":shot["shot_id"],
            "input_sha256":digest(build_local_input(c,d,shot["shot_id"])),"step_units":units})
    return c,d,locals_

if __name__=="__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser();parser.add_argument("--out-dir")
    args=parser.parse_args();c,d,l=make_offline_case();r=project_complete(c,d,l)
    if args.out_dir:
        path=Path(args.out_dir).resolve()
        if any(p.lower()=="production_trials" for p in path.parts):raise SystemExit("use a separate QA directory")
        path.mkdir(parents=True,exist_ok=True)
        for name,value in {"case.json":{"context":c,"direction":d,"locals":l},
            "director_tool_schema.json":build_direction_schema(c),"source_projection.json":r}.items():
            target=path/name
            if target.exists():raise SystemExit("preserve prior artifact; choose a fresh directory")
            target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":r["status"],"steps":len(r["ordered_execution"]),"shots":len(l),
        "source_order_passed":True,"physical_compile_attempted":False,"paid_calls":0},ensure_ascii=False,indent=2))
