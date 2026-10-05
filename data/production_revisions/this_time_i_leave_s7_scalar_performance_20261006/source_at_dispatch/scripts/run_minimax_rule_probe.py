"""Authorized, sequential rule experiment. No retry, draft repair, or budget reset."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator
from scripts import prepare_minimax_rule_probe as definition
from src.content_factory.creative_workflow_roles import CreativeRoleClients, role_config
from src.content_factory.creative_response_contract import exception_failure
PROJECT=Path(__file__).resolve().parents[1]
PLAN=definition.OUT/"TEST_PLAN.json"
ROOT=definition.DIAGNOSTIC/"rule_probe_matrix_v3"
LEDGER=ROOT/"CALL_LEDGER.json"
AUTHORIZATION="用户明确回复：允许新增最多18次，完成三轮对比。承接已使用24次，调用上限24提高至42；原500000总token上限不变，不重置旧账本。"
def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value,immutable=False):
    text=json.dumps(value,ensure_ascii=False,indent=2)
    if immutable:
        with path.open("x",encoding="utf-8") as f:f.write(text)
    else:
        tmp=path.with_name(path.name+".tmp")
        tmp.write_text(text,encoding="utf-8");os.replace(tmp,path)
def sources():
    return {str(p.relative_to(PROJECT)).replace("\\","/"):file_hash(p) for p in [
        Path(__file__).resolve(),PROJECT/"scripts/prepare_minimax_rule_probe.py",
        PROJECT/"src/content_factory/creative_workflow_roles.py",
        PROJECT/"src/content_factory/creative_response_contract.py"]}
@contextmanager
def lock():
    ROOT.mkdir(parents=True,exist_ok=True)
    path=definition.DIAGNOSTIC/"DISPATCH.lock"
    with path.open("x",encoding="utf-8") as f:f.write(json.dumps({"pid":os.getpid(),"time":now()}))
    try:yield
    finally:path.unlink()
def parent_snapshot():
    return {str(p.relative_to(definition.PARENT)).replace("\\","/"):file_hash(p)
            for p in definition.PARENT.rglob("*") if p.is_file()}
def safe_endpoint():
    c=role_config("writer");u=urlsplit(c.base_url)
    if u.username or u.password or u.query or u.fragment:
        raise RuntimeError("endpoint contains unsupported identity or query")
    return {"model":c.model,"provider":c.provider,"base_url":c.base_url}
def check(ledger):
    if ledger["schema"]!="minimax_authorized_rule_probe_ledger/v1":raise RuntimeError("ledger schema mismatch")
    if file_hash(PLAN)!=ledger["plan_sha256"] or sources()!=ledger["source_manifest"]:
        raise RuntimeError("experiment source or request matrix changed")
    if parent_snapshot()!=ledger["frozen_parent_snapshot"]:raise RuntimeError("frozen parent changed")
    if safe_endpoint()!=ledger["provider_config"]:raise RuntimeError("provider endpoint/model changed")
    if any(file_hash(Path(path))!=h for path,h in ledger["prior_evidence_sha256"].items()):
        raise RuntimeError("prior budget/response evidence changed")
    expected={c["receipt"] for c in ledger["calls"]}
    present={p.name for p in ROOT.glob("call_[0-9][0-9][0-9]_*.json")}
    if expected!=present:raise RuntimeError("orphan/missing receipt; reconcile original dispatch")
def prepare():
    with lock():
        if LEDGER.exists():check(read(LEDGER));return report()
        if list(ROOT.glob("call_[0-9][0-9][0-9]_*.json")):raise RuntimeError("unreconciled calls exist")
        plan=read(PLAN);old=read(definition.DIAGNOSTIC/"CALL_LEDGER.json")
        result=read(definition.DIAGNOSTIC/"RESULT.json");state=read(definition.PARENT/"state.json")
        if result["effective_calls_started"]!=24 or result["effective_reported_tokens"]!=379026:
            raise RuntimeError("verified starting budget differs")
        if result["unknown_token_reservations"] or state["max_total_tokens"]!=500000:
            raise RuntimeError("unknown outcome or budget changed")
        if parent_snapshot()!=old["parent_snapshot"]:raise RuntimeError("parent frozen record changed")
        if [c["request"] for c in definition.variants()]!=[c["request"] for c in plan["cases"]]:
            raise RuntimeError("requests differ from prepared matrix")
        ledger={"schema":"minimax_authorized_rule_probe_ledger/v1","created_at":now(),
            "authorization":AUTHORIZATION,"parent_run":str(definition.PARENT.resolve()),
            "starting_effective_budget":{"calls_started":24,"reported_tokens":379026,
                                        "max_calls_before_authorization":24,"max_calls":42,"max_total_tokens":500000},
            "max_new_calls":18,"calls":[],"automatic_retry":False,"media_calls":0,
            "old_budget_reset":False,"old_governance_migrated":False,
            "plan_sha256":file_hash(PLAN),"source_manifest":sources(),"provider_config":safe_endpoint(),
            "frozen_parent_snapshot":old["parent_snapshot"],
            "prior_evidence_sha256":{str(path.resolve()):file_hash(path) for path in [
                definition.PARENT/"state.json",definition.PARENT/"CONTINUATION_AUTHORIZATION_24.json",
                definition.DIAGNOSTIC/"CALL_LEDGER.json",definition.DIAGNOSTIC/"RESULT.json",
                *[definition.DIAGNOSTIC/c["receipt"] for c in old["calls"]]]}}
        write(ROOT/"AUTHORIZATION.json",{"authorization":AUTHORIZATION,"starting_budget":ledger["starting_effective_budget"],
              "new_call_limit":18,"plan_sha256":ledger["plan_sha256"],"created_at":ledger["created_at"]},True)
        for rel,h in ledger["source_manifest"].items():
            dst=ROOT/"source_at_dispatch"/rel
            dst.parent.mkdir(parents=True,exist_ok=True)
            raw=(PROJECT/rel).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==h
            with dst.open("xb") as f:f.write(raw)
        write(LEDGER,ledger,True)
    return report()
def usage(ledger):
    total,reserved,ids=0,0,set()
    for c in ledger["calls"]:
        r=read(ROOT/c["receipt"]);meta=r.get("response_metadata",{});n=meta.get("total_tokens")
        if type(n)is int and n>=0:
            key=meta.get("response_id") or ("ordinal",c["ordinal"])
            if key not in ids:total+=n;ids.add(key)
        else:reserved+=c["token_reservation"]
    return total,reserved
def execute(round_no,case_id):
    with lock():
        ledger=read(LEDGER);check(ledger)
        key=f"round_{round_no}_{case_id}"
        existing=next((c for c in ledger["calls"] if c["key"]==key),None)
        if existing:return {"status":"existing_receipt_no_dispatch","key":key,"receipt":existing["receipt"]}
        plan=read(PLAN)
        if round_no not in (1,2,3) or case_id not in "ABCDEF":raise RuntimeError("case outside approved matrix")
        for c in ledger["calls"]:
            r=read(ROOT/c["receipt"])
            if r["status"] in ("pending_response","outcome_unknown") or type(r.get("response_metadata",{}).get("total_tokens")) is not int:
                raise RuntimeError("outcome/usage unknown; no new dispatch until reconciliation")
        case=next(c for c in plan["cases"] if c["case_id"]==case_id)
        actual=ledger["starting_effective_budget"]["calls_started"]+len(ledger["calls"])
        if actual>=42 or len(ledger["calls"])>=18:raise RuntimeError("approved call cap exhausted")
        known,reserved=usage(ledger);reservation=case["conservative_token_reservation"]
        if 379026+known+reserved+reservation>500000:raise RuntimeError("original total token budget insufficient")
        ordinal=actual+1;filename=f"call_{ordinal:03}_r{round_no}_{case_id}.json"
        record={"schema":"minimax_rule_probe_call/v1","ordinal":ordinal,"round":round_no,"case_id":case_id,
            "status":"pending_response","started_at":now(),"request":case["request"],
            "request_sha256":case["request_sha256"],"messages_sha256":plan["messages_sha256"],
            "source_binding_sha256":definition.digest(ledger["source_manifest"]),
            "token_reservation":reservation,"automatic_retry":False,"semantic_approval":False}
        write(ROOT/filename,record,True)
        item={"key":key,"ordinal":ordinal,"round":round_no,"case_id":case_id,"receipt":filename,
              "status":"pending_response","token_reservation":reservation,"response_metadata":{}}
        ledger["calls"].append(item);write(LEDGER,ledger)
        print(json.dumps({"status":"dispatching","ordinal":ordinal,"round":round_no,"case":case_id},ensure_ascii=False),flush=True)
        wire=case["request"]
        try:
            result=CreativeRoleClients().call("writer",wire["messages"],max_tokens=wire["max_completion_tokens"],
                temperature=wire["temperature"],thinking="disabled",
                structured_schema=wire["tools"][0]["function"]["parameters"])
        except Exception as exc:
            failure=exception_failure(exc)
            record.update(status="interface_rejected" if failure["response_received"] else "outcome_unknown",
                          failure=failure,error=str(exc),completed_at=now())
            if getattr(exc,"response_metadata",None)is not None:
                record["response_metadata"]=exc.response_metadata
                record["response_text"]=getattr(exc,"response_text",None)
                record["response_payload"]=getattr(exc,"response_payload",None)
        else:
            record.update(status="response_received",response_text=result.text,
                          response_metadata=result.metadata,response_payload=result.response_payload,completed_at=now())
            write(ROOT/filename,record)
            try:output=json.loads(result.text)
            except (json.JSONDecodeError,TypeError) as exc:
                record.update(status="json_rejected",evaluation={"status":"json_rejected","error":str(exc),
                                                               "automatic_retry":False,"semantic_approval":False})
            else:
                record["output"]=output
                evaluation=definition.evaluate(output)
                errors=list(Draft202012Validator(wire["tools"][0]["function"]["parameters"]).iter_errors(output))
                evaluation["case_schema"]={"passed":not errors,"errors":[
                    {"path":".".join(map(str,e.absolute_path)),"message":e.message} for e in errors]}
                if errors and evaluation["status"]=="probe_contract_valid":
                    evaluation["status"]="case_schema_rejected"
                record.update(status=evaluation["status"],evaluation=evaluation)
        write(ROOT/filename,record)
        item.update(status=record["status"],response_metadata=record.get("response_metadata",{}))
        write(LEDGER,ledger);check(ledger)
        return {"ordinal":ordinal,"round":round_no,"case":case_id,"status":record["status"],
                "completion_tokens":record.get("response_metadata",{}).get("completion_tokens"),
                "total_tokens":record.get("response_metadata",{}).get("total_tokens"),
                "evaluation":record.get("evaluation"),"failure":record.get("failure")}
def report():
    ledger=read(LEDGER);check(ledger);known,reserved=usage(ledger)
    calls=[read(ROOT/c["receipt"]) for c in ledger["calls"]]
    groups={}
    for cid in "ABCDEF":
        rows=[r for r in calls if r["case_id"]==cid]
        groups[cid]={"attempts":len(rows),"valid":sum(r["status"]=="probe_contract_valid" for r in rows),
                    "statuses":[r["status"] for r in rows],
                    "completion_tokens":[r.get("response_metadata",{}).get("completion_tokens") for r in rows],
                    "total_tokens":sum(r.get("response_metadata",{}).get("total_tokens",0) for r in rows)}
    value={"schema":"minimax_rule_probe_result/v1","generated_at":now(),"groups":groups,
        "new_calls":len(calls),"effective_calls_started":24+len(calls),"max_calls":42,
        "new_reported_tokens":known,"effective_reported_tokens":379026+known,
        "unknown_token_reservations":reserved,"max_total_tokens":500000,
        "remaining_calls":18-len(calls),"remaining_tokens_after_reservations":500000-379026-known-reserved,
        "frozen_parent_unchanged":True,"old_budget_reset":False,"semantic_approval":False,
        "no_complete_creative_work_or_media_generated":True,"raw_success_envelopes_saved":True,
        "plan":str(PLAN),"ledger":str(LEDGER),
        "calls":[{"ordinal":r["ordinal"],"round":r["round"],"case_id":r["case_id"],"status":r["status"],
                  "response_metadata":r.get("response_metadata",{}),"evaluation":r.get("evaluation"),
                  "failure":r.get("failure")} for r in calls]}
    write(ROOT/"RESULT.json",value)
    return value
def run_round(number):
    labels=read(PLAN)["repeat_plan"][{1:"first_round",2:"second_round",3:"third_round"}[number]]
    for label in labels:
        result=execute(number,label)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if result["status"]=="outcome_unknown":
            print(json.dumps(report(),ensure_ascii=False),flush=True)
            raise SystemExit(2)
    print(json.dumps(report(),ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    command=sys.argv[1]
    if command=="prepare":print(json.dumps(prepare(),ensure_ascii=False,indent=2))
    elif command=="round":run_round(int(sys.argv[2]))
    elif command=="report":print(json.dumps(report(),ensure_ascii=False,indent=2))
    else:raise SystemExit("prepare | round 1/2/3 | report")
