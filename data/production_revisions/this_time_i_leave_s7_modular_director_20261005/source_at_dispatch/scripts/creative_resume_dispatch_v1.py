"""Explicit authorized continuation with inherited spend and immutable receipts.

This module never edits a prior trial. Output caps remain per-call; the user's
2026-10-04 authorization removes the aggregate text-token cap for this lineage.
"""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from jsonschema import Draft202012Validator, ValidationError
from src.content_factory.creative_response_contract import response_failure, exception_failure, validation_failure, fault
from src.content_factory.creative_workflow_roles import CreativeRoleClients

VERSION = "authorized_creative_continuation/v1"
AUTHORIZATION = "用户2026-10-04明确恢复：继续吧先不设token预算。后续文本调用暂不设总token硬上限；旧49次490913以及原500000历史记录完整承接，不重置账本。保持MiniMax创作、DeepSeek少量文本复审；不含媒体调用或发布。"


def now(): return datetime.now(timezone.utc).isoformat()
def sha_file(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError("duplicate JSON key")
            result[key]=value
        return result
    def constant(value): raise ValueError("nonfinite JSON constant")
    value=json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    if not isinstance(value,dict): raise ValueError("complete JSON object required")
    return value


def write(path,value,immutable=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if immutable:
        if path.exists():
            if read(path)!=value: raise RuntimeError("immutable artifact changed: "+path.name)
            return
        with path.open("x",encoding="utf-8") as f: json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
    else:
        tmp=path.with_name(path.name+".write_"+str(os.getpid()))
        with tmp.open("x",encoding="utf-8") as f: json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
        os.replace(tmp,path)


class ContinuationRuntime:
    def __init__(self,project,root,sources,inherited,models,*,inherited_guard=lambda:None,
                 client_factory=CreativeRoleClients,quota_state=None,shared_lock=None):
        self.project=Path(project).resolve();self.root=Path(root).resolve()
        self.sources=[Path(p).resolve() for p in sources];self.inherited=deepcopy(inherited)
        self.models=deepcopy(models);self.inherited_guard=inherited_guard
        self.client_factory=client_factory;self.quota_state=Path(quota_state) if quota_state else None
        self.ledger=self.root/"CALL_LEDGER.json"
        self.shared_lock=Path(shared_lock) if shared_lock else self.root/"DISPATCH.lock"

    def source_manifest(self):
        result={}
        for path in self.sources:
            rel=path.relative_to(self.project).as_posix()
            result[rel]=sha_file(path)
        return result

    def receipt_names(self):
        names={p.name for p in self.root.glob("call_*.json") if p.name!=self.ledger.name}
        if any(not re.fullmatch(r"call_[0-9]+_[a-zA-Z0-9_]{1,90}\.json", name) for name in names):
            raise RuntimeError("malformed receipt filename; reconcile")
        return names

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True,exist_ok=True)
        path=self.shared_lock;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("x",encoding="utf-8") as f: json.dump({"pid":os.getpid(),"time":now()},f)
        try: yield
        finally: path.unlink()

    def prepare(self):
        self.inherited_guard()
        for field in ("calls_started","reported_tokens"):
            if type(self.inherited.get(field)) is not int or self.inherited[field]<0: raise RuntimeError("inherited spend required")
        with self.lock():
            if self.ledger.exists(): self.check(read(self.ledger));return self.summary()
            if self.receipt_names(): raise RuntimeError("orphan prior dispatch; reconcile")
            auth={"schema":VERSION,"authorization":AUTHORIZATION,"authorized_at":now(),
                  "starting_spend":deepcopy(self.inherited),"max_total_tokens":None,
                  "old_budget_reset":False,"old_governance_migrated":False,"media_calls_authorized":False}
            write(self.root/"AUTHORIZATION.json",auth,True)
            sources=self.source_manifest()
            for rel,h in sources.items():
                target=self.root/"source_at_dispatch"/rel;target.parent.mkdir(parents=True,exist_ok=True)
                with target.open("xb") as f:f.write((self.project/rel).read_bytes())
                assert sha_file(target)==h
            ledger={"schema":VERSION,"starting_spend":deepcopy(self.inherited),"max_total_tokens":None,
                    "authorization_sha256":sha_file(self.root/"AUTHORIZATION.json"),
                    "source_manifest":sources,"model_configs":deepcopy(self.models),"calls":[],
                    "automatic_retry":False,"old_budget_reset":False,"old_governance_migrated":False}
            write(self.ledger,ledger,True)
        return self.summary()

    def check(self,ledger):
        self.inherited_guard()
        if ledger["starting_spend"]!=self.inherited or ledger["max_total_tokens"] is not None: raise RuntimeError("inherited authorization/spend changed")
        if sha_file(self.root/"AUTHORIZATION.json")!=ledger["authorization_sha256"]: raise RuntimeError("authorization changed")
        if self.source_manifest()!=ledger["source_manifest"] or self.models!=ledger["model_configs"]: raise RuntimeError("operator source/model binding changed")
        for rel,h in ledger["source_manifest"].items():
            if sha_file(self.root/"source_at_dispatch"/rel)!=h: raise RuntimeError("source snapshot changed")
        expected={c["receipt"] for c in ledger["calls"]}
        if self.receipt_names()!=expected: raise RuntimeError("orphan/missing receipt; reconcile original request")
        if len(expected)!=len(ledger["calls"]):raise RuntimeError("duplicate ledger receipt")
        for index,c in enumerate(ledger["calls"]):
            if c["ordinal"]!=self.inherited["calls_started"]+index+1:raise RuntimeError("ledger ordinal changed")
            if sha_file(self.root/c["receipt"])!=c["receipt_sha256"]:raise RuntimeError("receipt changed; reconcile")

    def usage(self,ledger):
        total=reserved=0;seen={}
        for c in ledger["calls"]:
            r=read(self.root/c["receipt"]);m=r.get("response_metadata",{});n=m.get("total_tokens")
            if type(n) is int and n>=0:
                rid=m.get("response_id")
                if rid and rid in seen:raise RuntimeError("duplicate response identity; reconcile billing")
                if rid:seen[rid]=n
                total+=n
            else:reserved+=c["token_reservation"]
        return total,reserved

    def summary(self):
        ledger=read(self.ledger);self.check(ledger);spent,reserved=self.usage(ledger)
        return {"schema":VERSION,"new_calls":len(ledger["calls"]),
            "effective_calls_started":self.inherited["calls_started"]+len(ledger["calls"]),
            "new_reported_tokens":spent,"effective_reported_tokens":self.inherited["reported_tokens"]+spent,
            "unknown_token_reservations":reserved,"max_total_tokens":None,"unbounded_aggregate_text_authorized":True,
            "old_budget_reset":False,"old_governance_migrated":False,"media_calls":0,"semantic_approval":False}

    def _quota_guard(self):
        if self.quota_state:
            q=read(self.quota_state)
            if q.get("stop_condition",{}).get("triggered") or str(q.get("task_status","")).startswith("paused"):
                raise RuntimeError("user quota-reset stop is latched; no dispatch")

    def dispatch(self,label,wire,validator):
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,90}",label):raise ValueError("safe stage label required")
        if wire.get("role") not in self.models or wire.get("model")!=self.models[wire["role"]]["model"]:raise RuntimeError("role model changed")
        cap=wire.get("parameters",{}).get("max_completion_tokens")
        if type(cap)is not int or not 0<cap<=32000:raise RuntimeError("bounded positive output cap required")
        if wire["parameters"].get("temperature")!=0.4 or wire["parameters"].get("thinking")!="disabled":raise RuntimeError("unverified model parameters")
        request_sha=digest(wire)
        with self.lock():
            ledger=read(self.ledger);self.check(ledger);self._quota_guard();self.usage(ledger)
            for c in ledger["calls"]:
                r=read(self.root/c["receipt"])
                if r["request_sha256"]==request_sha:
                    # A cached response is never re-dispatched or rewritten. Recheck
                    # today's acceptance against a copy of the original model value.
                    cached=deepcopy(r)
                    if r["status"]=="contract_valid":
                        try:
                            if wire.get("structured_schema") is not None:Draft202012Validator(wire["structured_schema"]).validate(cached["output"])
                            cached["validation"]=validator(deepcopy(cached["output"])) or {}
                        except ValidationError as exc:
                            cached.update(status="contract_rejected",failure=fault("MODULE_SCHEMA_INVALID","state_contract","complete_new_response_then_full_validation",received=True),
                                          validation_error={"message":exc.message,"path":list(exc.absolute_path)},cached_response_rejected_locally=True)
                        except Exception as exc:
                            cached.update(status="contract_rejected",failure=validation_failure(exc),
                                          validation_error={"message":str(exc),"detail":getattr(exc,"detail",{})},cached_response_rejected_locally=True)
                    return cached
                if c["label"]==label:raise RuntimeError("existing label bound to another request; use explicit new stage version")
            for c in ledger["calls"]:
                r=read(self.root/c["receipt"]);m=r.get("response_metadata",{})
                if r["status"] not in ("contract_valid","contract_rejected","interface_rejected") or type(m.get("total_tokens")) is not int or m["total_tokens"]<0:
                    raise RuntimeError("unknown outcome/usage; no new dispatch")
                if r["status"]=="interface_rejected" and r.get("failure",{}).get("response_received") is not True:
                    raise RuntimeError("unknown rejected response; reconcile")
            ordinal=self.inherited["calls_started"]+len(ledger["calls"])+1;name=f"call_{ordinal:03}_{label}.json"
            reservation=len(json.dumps(wire,ensure_ascii=False,allow_nan=False))+cap+1024
            r={"schema":VERSION,"ordinal":ordinal,"label":label,"request":deepcopy(wire),
               "request_sha256":request_sha,"source_binding_sha256":digest(ledger["source_manifest"]),
               "status":"pending_response","started_at":now(),"token_reservation":reservation,
               "automatic_retry":False,"semantic_approval":False}
            write(self.root/name,r,True)
            ledger["calls"].append({"ordinal":ordinal,"label":label,"receipt":name,
                "token_reservation":reservation,"receipt_sha256":sha_file(self.root/name)})
            write(self.ledger,ledger)
            print(json.dumps({"status":"dispatching","ordinal":ordinal,"label":label}),flush=True)
            try:
                p=wire["parameters"]
                result=self.client_factory().call(wire["role"],wire["messages"],max_tokens=cap,temperature=p["temperature"],
                    thinking=p["thinking"],structured_schema=wire.get("structured_schema"))
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
                write(self.root/name,r)
                failure=response_failure(result.metadata,result.text,require_tool=wire.get("structured_schema") is not None)
                if failure:r.update(status="interface_rejected",failure=failure)
                else:
                    try:
                        value=strict_json(result.text)
                    except (json.JSONDecodeError,ValueError) as exc:
                        r.update(status="interface_rejected",failure=fault("INVALID_JSON_RESPONSE","interface","diagnose_output_protocol",received=True),error=str(exc))
                    else:
                        r["output"]=value
                        try:
                            if wire.get("structured_schema") is not None:Draft202012Validator(wire["structured_schema"]).validate(value)
                            r["validation"]=validator(deepcopy(value)) or {};r["status"]="contract_valid"
                        except ValidationError as exc:
                            r.update(status="contract_rejected",failure=fault("MODULE_SCHEMA_INVALID","state_contract","complete_new_response_then_full_validation",received=True),
                                     validation_error={"message":exc.message,"path":list(exc.absolute_path)})
                        except Exception as exc:
                            r.update(status="contract_rejected",failure=validation_failure(exc),validation_error={"message":str(exc),"detail":getattr(exc,"detail",{})})
            write(self.root/name,r);ledger["calls"][-1]["receipt_sha256"]=sha_file(self.root/name);write(self.ledger,ledger)
            write(self.root/"RESULT.json",self.summary())
            return r
