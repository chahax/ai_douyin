"""Explicit B+D modular text trial; inherited spend, no parent migration or blind retry."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator, ValidationError
from scripts import run_minimax_rule_probe as previous
from src.content_factory.creative_full_script_revision import PROMPT as FULL_REVISION, accept_full_script
from src.content_factory.creative_modular_contract import build_local_input, validate_direction, _compile_prefix, compile_complete
from src.content_factory.creative_response_contract import exception_failure, validation_failure, fault
from src.content_factory.creative_review_v6 import build_review_prompt, validate_review_v6
from src.content_factory.creative_workflow_contract import WRITER_TOOL_SCHEMAS, validate_script, parse_json_object
from src.content_factory.creative_workflow_roles import CreativeRoleClients, role_config
from src.content_factory.creative_modular_tool_export import (
    build_direction_tool_schema, build_local_tool_schema,
    build_direction_request_messages, build_local_request_messages,
)

PROJECT = Path(__file__).resolve().parents[1]
ROOT = previous.definition.DIAGNOSTIC / "modular_bd_v1"
LEDGER = ROOT / "CALL_LEDGER.json"
AUTHORIZATION = "用户2026-10-03同意前述合同与分模块推进，并明确：行minmax额度直接使用不用申请。新增MiniMax文本调用不逐次申请；累计账本及原500000总token上限继续承接。原MiniMax创作、DeepSeek全文审查分工按已同意的流程保持。"
BATCH_CALL_CEILING = 16
SOURCE_ISSUES = [
    {"id":"SOURCE_PROP_LOCATION","location":"B1/B2/B5",
     "evidence":"原B1 event说挎包露出票根与便签，before/during及B2却位于方澄桌角；B5林屿从桌角收走同一批便签。",
     "request":"完整新稿明确票根和便签各自初始位置、每次变更及结尾取用条件，不让导演补拿取掩盖歧义。"},
    {"id":"SOURCE_OBSERVATION_SEQUENCE","location":"B3",
     "evidence":"原稿同时要求方澄中近景拒绝与林屿手部近景停笔，trigger写同时被看见。",
     "request":"明确实际观察机位与刺激反应先后；保留重要对白前中后的表演重点，不把动作全部拖到对白之后。多镜或并行确属创作需要就明确写出，不为编译器删掉叙事要求。"},
]
def now():
    return datetime.now(timezone.utc).isoformat()
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def digest(value):
    return previous.definition.digest(value)
def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value, immutable=False):
    previous.write(Path(path), value, immutable)
def source_manifest():
    paths = [Path(__file__).resolve(), PROJECT/"scripts/run_minimax_rule_probe.py",
             PROJECT/"scripts/prepare_minimax_rule_probe.py", PROJECT/"src/shared/config.py"]
    paths += list((PROJECT/"src/content_factory").glob("*.py"))
    return {str(p.relative_to(PROJECT)).replace("\\","/"):file_hash(p) for p in sorted(set(paths))}
def model_configs():
    result={}
    for role in ("writer","director"):
        c=role_config(role); u=urlsplit(c.base_url)
        if u.username or u.password or u.query or u.fragment:
            raise RuntimeError("unsafe endpoint identity/query")
        result[role]={"provider":c.provider,"model":c.model,"base_url":c.base_url}
    return result
@contextmanager
def lock():
    ROOT.mkdir(parents=True, exist_ok=True)
    path=previous.definition.DIAGNOSTIC/"DISPATCH.lock"
    with path.open("x",encoding="utf-8") as f:
        f.write(json.dumps({"pid":os.getpid(),"time":now()}))
    try:
        yield
    finally:
        path.unlink()
def check(ledger):
    previous.check(previous.read(previous.LEDGER))
    if source_manifest()!=ledger["source_manifest"]:
        raise RuntimeError("source binding changed")
    if model_configs()!=ledger["model_configs"]:
        raise RuntimeError("model endpoint changed")
    for path,h in ledger["prior_evidence_sha256"].items():
        if file_hash(path)!=h:
            raise RuntimeError("prior evidence changed")
    if file_hash(ROOT/"ORIGINAL_CONTEXT.json")!=ledger["original_context_sha256"]:
        raise RuntimeError("context changed")
    actual={p.name for p in ROOT.glob("call_[0-9][0-9][0-9]_*.json")}
    expected={c["receipt"] for c in ledger["calls"]}
    if actual!=expected:
        raise RuntimeError("orphan/missing receipt; reconcile original dispatch")
    for call in ledger["calls"]:
        if file_hash(ROOT/call["receipt"])!=call["receipt_sha256"]:
            raise RuntimeError("received/pending receipt changed")
def prepare():
    with lock():
        if LEDGER.exists():
            check(read(LEDGER)); return summary()
        previous.check(previous.read(previous.LEDGER))
        budget=previous.read(previous.ROOT/"RESULT.json")
        if (budget["effective_calls_started"],budget["effective_reported_tokens"],budget["unknown_token_reservations"])!=(42,398343,0):
            raise RuntimeError("starting spend differs")
        if list(ROOT.glob("call_[0-9][0-9][0-9]_*.json")):
            raise RuntimeError("unreconciled prior requests")
        context=read(previous.definition.DIAGNOSTIC/"CONTEXT.json")
        write(ROOT/"ORIGINAL_CONTEXT.json",context,True)
        old=previous.read(previous.LEDGER)
        prior_paths=[previous.LEDGER,previous.ROOT/"RESULT.json",previous.ROOT/"AUTHORIZATION.json",
                     *[previous.ROOT/c["receipt"] for c in old["calls"]]]
        ledger={"schema":"modular_bd_text_probe_ledger/v1","created_at":now(),
            "authorization":AUTHORIZATION,"original_parent_run":old["parent_run"],
            "starting_spend":{"calls_started":42,"reported_tokens":398343,"max_total_tokens":500000},
            "assistant_batch_call_ceiling":BATCH_CALL_CEILING,"calls":[],
            "source_manifest":source_manifest(),"model_configs":model_configs(),
            "original_context_sha256":file_hash(ROOT/"ORIGINAL_CONTEXT.json"),
            "prior_evidence_sha256":{str(p.resolve()):file_hash(p) for p in prior_paths},
            "automatic_retry":False,"old_budget_reset":False,"old_governance_migrated":False,"media_calls":0}
        write(ROOT/"AUTHORIZATION.json",{"authorization":AUTHORIZATION,
            "starting_spend":ledger["starting_spend"],"assistant_batch_call_ceiling":BATCH_CALL_CEILING,
            "ceiling_is_local_execution_guard_not_user_specified_quantity":True,"created_at":ledger["created_at"]},True)
        for rel,h in ledger["source_manifest"].items():
            dst=ROOT/"source_at_dispatch"/rel
            dst.parent.mkdir(parents=True,exist_ok=True)
            raw=(PROJECT/rel).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==h
            with dst.open("xb") as f:
                f.write(raw)
        write(LEDGER,ledger,True)
    return summary()
def usage(ledger):
    total,reserved,ids=0,0,set()
    for c in ledger["calls"]:
        r=read(ROOT/c["receipt"]); meta=r.get("response_metadata",{}); n=meta.get("total_tokens")
        if type(n)is int and n>=0:
            key=meta.get("response_id") or ("ordinal",c["ordinal"])
            if key not in ids:
                total+=n;ids.add(key)
        else:
            reserved+=c["token_reservation"]
    return total,reserved
def request(role,messages,schema,max_tokens):
    c=role_config(role)
    return {"role":role,"model":c.model,"messages":messages,"structured_schema":schema,
            "parameters":{"max_completion_tokens":max_tokens,"temperature":0.4,"thinking":"disabled"}}
def dispatch(label, wire, validator, retain_review_tokens=0):
    with lock():
        ledger=read(LEDGER);check(ledger)
        key=digest({"label":label,"request":wire})
        existing=next((c for c in ledger["calls"] if c["key"]==key),None)
        if existing:
            return read(ROOT/existing["receipt"])
        for c in ledger["calls"]:
            r=read(ROOT/c["receipt"])
            if r["status"] not in ("contract_valid","contract_rejected") or type(r.get("response_metadata",{}).get("total_tokens")) is not int:
                raise RuntimeError("unknown outcome/usage; no new dispatch")
        if len(ledger["calls"])>=ledger["assistant_batch_call_ceiling"]:
            raise RuntimeError("local batch call ceiling reached")
        known,reserved=usage(ledger)
        reservation=len(json.dumps(wire,ensure_ascii=False))+wire["parameters"]["max_completion_tokens"]+1024
        if ledger["starting_spend"]["reported_tokens"]+known+reserved+reservation+retain_review_tokens>500000:
            raise RuntimeError("original 500000 token budget insufficient for request plus retained full-review allowance")
        ordinal=42+len(ledger["calls"])+1
        name=f"call_{ordinal:03}_{label}.json"
        r={"schema":"modular_bd_call/v1","label":label,"ordinal":ordinal,"request":wire,
           "request_sha256":digest(wire),"source_binding_sha256":digest(ledger["source_manifest"]),
           "status":"pending_response","started_at":now(),"token_reservation":reservation,
           "retained_full_review_tokens":retain_review_tokens,"automatic_retry":False,"semantic_approval":False}
        write(ROOT/name,r,True)
        ledger["calls"].append({"key":key,"ordinal":ordinal,"label":label,"receipt":name,
                              "token_reservation":reservation,"receipt_sha256":file_hash(ROOT/name)})
        write(LEDGER,ledger)
        print(json.dumps({"status":"dispatching","ordinal":ordinal,"label":label}),flush=True)
        try:
            p=wire["parameters"]
            result=CreativeRoleClients().call(wire["role"],wire["messages"],max_tokens=p["max_completion_tokens"],
                temperature=p["temperature"],thinking="disabled",structured_schema=wire["structured_schema"])
        except Exception as exc:
            failure=exception_failure(exc)
            r.update(status="interface_rejected" if failure["response_received"] else "outcome_unknown",
                     failure=failure,error=str(exc),completed_at=now())
            if getattr(exc,"response_metadata",None)is not None:
                r.update(response_metadata=exc.response_metadata,response_text=getattr(exc,"response_text",None),
                         response_payload=getattr(exc,"response_payload",None))
        else:
            r.update(status="response_received",response_metadata=result.metadata,response_text=result.text,
                     response_payload=result.response_payload,completed_at=now())
            write(ROOT/name,r)
            try:
                value=parse_json_object(result.text)
                r["output"]=value
                if wire["structured_schema"] is not None:
                    Draft202012Validator(wire["structured_schema"]).validate(value)
                validation=validator(value)
                r.update(status="contract_valid",validation=validation)
            except Exception as exc:
                if isinstance(exc,ValidationError):
                    failure=fault("MODULE_SCHEMA_INVALID","state_contract","complete_new_draft_then_full_review",received=True)
                    detail={"code":"MODULE_SCHEMA_INVALID","path":".".join(map(str,exc.absolute_path))}
                else:
                    failure=validation_failure(exc)
                    detail=getattr(exc,"detail",{})
                r.update(status="contract_rejected",failure=failure,
                         validation_error={"message":str(exc),"detail":detail})
        write(ROOT/name,r)
        ledger["calls"][-1].update(status=r["status"],response_metadata=r.get("response_metadata",{}),
                                    receipt_sha256=file_hash(ROOT/name))
        write(LEDGER,ledger);check(ledger)
        return r
def summary():
    ledger=read(LEDGER);check(ledger);known,reserved=usage(ledger)
    calls=[read(ROOT/c["receipt"]) for c in ledger["calls"]]
    value={"schema":"modular_bd_summary/v1","generated_at":now(),"new_calls":len(calls),
        "effective_calls_started":42+len(calls),"new_reported_tokens":known,
        "effective_reported_tokens":398343+known,"unknown_token_reservations":reserved,
        "max_total_tokens":500000,"remaining_tokens":500000-398343-known-reserved,
        "assistant_batch_call_ceiling":ledger["assistant_batch_call_ceiling"],
        "old_budget_reset":False,"old_governance_migrated":False,"frozen_parent_unchanged":True,
        "media_calls":0,"semantic_approval":False,
        "calls":[{"ordinal":r["ordinal"],"label":r["label"],"status":r["status"],
                  "usage":r.get("response_metadata",{}),"failure":r.get("failure"),
                  "validation_error":r.get("validation_error")} for r in calls]}
    write(ROOT/"RESULT.json",value)
    return value
def get_call(label):
    ledger=read(LEDGER);check(ledger)
    matches=[c for c in ledger["calls"] if c["label"]==label]
    if len(matches)!=1:
        raise RuntimeError("missing/nonunique upstream call "+label)
    value=read(ROOT/matches[0]["receipt"])
    if value["status"]!="contract_valid":
        raise RuntimeError("upstream not validated "+label)
    return value
def revised_context(index):
    original=read(ROOT/"ORIGINAL_CONTEXT.json")
    accepted=accept_full_script(original["script"],get_call(f"draft_v{index}")["output"])
    context=deepcopy(original);context["script"]=accepted
    context["script_revision_source"]={"call_label":f"draft_v{index}","complete_model_authored":True,
                                      "original_script_sha256":digest(original["script"])}
    return context
def draft(index):
    context=read(ROOT/"ORIGINAL_CONTEXT.json")
    issues=deepcopy(SOURCE_ISSUES)
    previous_script=context["script"]
    if index>1:
        ledger=read(LEDGER)
        item=next(c for c in ledger["calls"] if c["label"]==f"draft_v{index-1}")
        prior=read(ROOT/item["receipt"])
        if prior["status"]=="contract_valid":
            previous_script=get_call(f"draft_v{index-1}")["output"]
            review=get_call(f"script_review_v{index-1}")["output"]
            issues+=review["issues"]
        elif prior["status"]=="contract_rejected":
            previous_script=prior.get("output") or context["script"]
            issues.append({"id":"PREVIOUS_FULL_DRAFT_CONTRACT_REJECTED",
                           "validation_error":prior.get("validation_error"),
                           "request":"重新提交完整剧本，修正结构与字段类型；禁止补丁或拼接。"})
        else:
            raise RuntimeError("cannot revise an unknown or interface-rejected draft")
    schema=deepcopy(WRITER_TOOL_SCHEMAS["writer_script"])
    schema["description"]="完整剧本对象，beats直接为数组，每拍含before/during/after、dialogue数组。播放顺序before→首句对白→during→第二句对白→after；event/trigger仅摘要。时长可浮动，不用填充动作凑秒数。"
    payload={"context":context,"previous_script":previous_script,"issues":issues,"revision_mode":"full_script"}
    messages=[{"role":"system","content":FULL_REVISION+" 用指定工具提交完整新稿，不写分析。参考全文在context.reference_pack。"},
              {"role":"user","content":json.dumps(payload,ensure_ascii=False)}]
    def validate(value):
        accepted=accept_full_script(context["script"],value)
        validate_script(deepcopy(accepted),context["script"]["selected_candidate_id"],"","original")
        if len({b["id"] for b in value["beats"]})!=len(value["beats"]):
            raise ValueError("duplicate beat ids")
        return {"complete_new_script":True,"semantic_approval":False,"requires_full_review":True}
    return dispatch(f"draft_v{index}",request("writer",messages,schema,4096),validate,14000)
def script_review(index):
    context=revised_context(index)
    messages=[{"role":"system","content":build_review_prompt(context)},
              {"role":"user","content":json.dumps(context,ensure_ascii=False)}]
    def validate(value):
        validate_review_v6(value,context)
        return {"evidence_valid":True,"story_preserved":value["story_preserved"],
                "requires_assistant_evidence_verification":True,"semantic_approval":False}
    return dispatch(f"script_review_v{index}",request("director",messages,None,6000),validate,14000)
def evidence_decision(index, approved, evidence):
    review=get_call(f"script_review_v{index}")
    if approved and (review["output"]["issues"] or not review["output"]["story_preserved"]):
        raise RuntimeError("cannot approve unresolved required issues")
    context=revised_context(index)
    value={"schema":"modular_bd_assistant_review_decision/v1","review_sha256":digest(review["output"]),
           "context_sha256":digest(context),"approved_for_direction":approved,"evidence":evidence,
           "decision_source":"assistant_verified_text_evidence","media_approval":False}
    path=ROOT/f"SCRIPT_REVIEW_DECISION_v{index}.json"
    if path.exists():
        if read(path)!=value:
            raise RuntimeError("review decision differs")
    else:
        write(path,value,True)
    return value
def direction(index, version):
    context=revised_context(index)
    decision=read(ROOT/f"SCRIPT_REVIEW_DECISION_v{index}.json")
    if decision["context_sha256"]!=digest(context) or not decision["approved_for_direction"]:
        raise RuntimeError("full script review not verified")
    if decision["review_sha256"]!=digest(get_call(f"script_review_v{index}")["output"]):
        raise RuntimeError("review identity changed")
    messages=build_direction_request_messages(context)
    if version>1:
        ledger=read(LEDGER)
        old=next(c for c in ledger["calls"] if c["label"]==f"direction_s{index}_v{version-1}")
        received=read(ROOT/old["receipt"])
        rejected_locals=[read(ROOT/c["receipt"]) for c in ledger["calls"]
            if c["label"].startswith(f"local_s{index}_d{version-1}_")
            and read(ROOT/c["receipt"])["status"]=="contract_rejected"]
        if received["status"]!="contract_rejected" and not rejected_locals:
            raise RuntimeError("complete new direction requires a known direction/local rejection")
        messages.append({"role":"user","content":json.dumps({"previous_complete_direction":received.get("output"),
            "direction_validation_error":received.get("validation_error"),
            "rejected_local_contracts":[{"output":r.get("output"),"error":r.get("validation_error")} for r in rejected_locals],
            "instruction":"基于完整context重新提交整个整片规划，不返回补丁、不局部回填；核对全部拍与初态。新的direction使全部旧局部输入失效。"},ensure_ascii=False)})
    def validate(value):
        validate_direction(value,context)
        return {"complete_direction_contract_valid":True,"semantic_approval":False}
    return dispatch(f"direction_s{index}_v{version}",request("writer",messages,build_direction_tool_schema(context),6000),validate,14000)
def get_local(index,version,beat_number):
    base=f"local_s{index}_d{version}_b{beat_number}"
    ledger=read(LEDGER);check(ledger)
    rows=[c for c in ledger["calls"] if c["label"]==base or c["label"].startswith(base+"_v")]
    if not rows:
        raise RuntimeError("missing local "+base)
    latest=max(rows,key=lambda c:c["ordinal"])
    return get_call(latest["label"])
def local(index,version,beat_number,revision=1):
    context=revised_context(index);d=get_call(f"direction_s{index}_v{version}")["output"]
    locals_=[get_local(index,version,i+1)["output"] for i in range(beat_number-1)]
    inp=build_local_input(context,d,locals_)
    if inp["beat_id"]!=context["script"]["beats"][beat_number-1]["id"]:
        raise RuntimeError("local beat order changed")
    base=f"local_s{index}_d{version}_b{beat_number}"
    feedback=None
    if revision>1:
        previous_label=base if revision==2 else base+f"_v{revision-1}"
        ledger=read(LEDGER)
        item=next(c for c in ledger["calls"] if c["label"]==previous_label)
        old=read(ROOT/item["receipt"])
        if old["status"]!="contract_rejected":
            raise RuntimeError("local revision requires known rejected complete local output")
        feedback={"previous_complete_local":old.get("output"),"validation_error":old.get("validation_error"),
                  "instruction":"重新生成当前拍完整局部表演，不返回补丁；不改上游剧本、direction或编译首态。全部groups重新核对前提和窗口。"}
    messages=build_local_request_messages(inp,revision_feedback=feedback)
    def validate(value):
        prefix=_compile_prefix(context,d,locals_+[value])
        write(ROOT/f"PREFIX_s{index}_d{version}_{beat_number:02}_lv{revision}.json",prefix,True)
        complete_path=None
        if beat_number==len(context["script"]["beats"]):
            complete=compile_complete(context,d,locals_+[value])
            complete_path=ROOT/f"COMPLETE_s{index}_d{version}_{digest(complete)[:12]}.json"
            if complete_path.exists():
                if read(complete_path)!=complete:
                    raise RuntimeError("complete compilation artifact changed")
            else:
                write(complete_path,complete,True)
        return {"compiled_prefix_beats":beat_number,"semantic_approval":False,
                "complete_artifact":str(complete_path) if complete_path else None}
    label=base if revision==1 else base+f"_v{revision}"
    return dispatch(label,request("writer",messages,
        build_local_tool_schema(context,d,inp["beat_id"]),4096),validate,14000)

def final_review(index,version):
    context=revised_context(index)
    d=get_call(f"direction_s{index}_v{version}")["output"]
    locals_=[get_local(index,version,i+1)["output"] for i in range(len(context["script"]["beats"]))]
    expected=compile_complete(context,d,locals_)
    path=ROOT/f"COMPLETE_s{index}_d{version}_{digest(expected)[:12]}.json"
    complete=read(path)
    if complete!=expected:
        raise RuntimeError("complete artifact differs from current verified direction and local outputs")
    context.update(script=complete["derived_timing_script"],shots=complete["storyboard"],
                   state_plan=complete["derived_action_plan"],whole_film_direction=get_call(f"direction_s{index}_v{version}")["output"])
    messages=[{"role":"system","content":build_review_prompt(context)},
              {"role":"user","content":json.dumps(context,ensure_ascii=False)}]
    def validate(value):
        validate_review_v6(value,context)
        return {"full_text_review_evidence_valid":True,"story_preserved":value["story_preserved"],
                "requires_assistant_evidence_verification":True,"semantic_approval":False}
    return dispatch(f"final_review_s{index}_d{version}",request("director",messages,None,7000),validate)

if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd=sys.argv[1]
    if cmd=="prepare": result=prepare()
    elif cmd=="draft": result=draft(int(sys.argv[2]))
    elif cmd=="script-review": result=script_review(int(sys.argv[2]))
    elif cmd=="direction": result=direction(int(sys.argv[2]),int(sys.argv[3]))
    elif cmd=="local": result=local(int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]) if len(sys.argv)>5 else 1)
    elif cmd=="final-review": result=final_review(int(sys.argv[2]),int(sys.argv[3]))
    elif cmd=="report": result=summary()
    else: raise SystemExit("prepare | draft N | script-review N | direction N V | local N V B | final-review N V | report")
    if cmd not in ("prepare","report"):
        print(json.dumps({k:result.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")},ensure_ascii=False,indent=2),flush=True)
        print(json.dumps(summary(),ensure_ascii=False),flush=True)
    else: print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
