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
import math
import os
from pathlib import Path
import re
from jsonschema import Draft202012Validator, ValidationError
from src.content_factory.creative_response_contract import response_failure, validation_failure, fault
from scripts.creative_evidenced_role_clients_v1 import EvidencedRoleClients as CreativeRoleClients, EvidenceCallError, evidence_exception_failure as exception_failure, parse_saved_response
from scripts.creative_call_evidence_v1 import CallEvidenceJournal
from scripts import creative_json_document_transport_v1 as document_transport

VERSION = "authorized_creative_continuation/v3"
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
    def finite(item):
        if isinstance(item,float) and not math.isfinite(item):raise ValueError("nonfinite JSON numeric overflow")
        if isinstance(item,dict):
            for child in item.values():finite(child)
        elif isinstance(item,list):
            for child in item:finite(child)
    finite(value)
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
            r=self.effective_receipt(c);m=r.get("response_metadata",{});n=m.get("total_tokens")
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

    def _validate_output(self,receipt,wire,validator):
        """Validate the immutable wire value; derived document is never patched."""
        try:
            if wire.get("output_transport"):
                decoded=document_transport.extract_original_inner(receipt["response_text"],wire["inner_document_schema"])
                if "document_output" in receipt and receipt["document_output"]!=decoded["document"]:
                    raise RuntimeError("stored document differs from original wire payload")
                receipt["document_output"]=deepcopy(decoded["document"])
                receipt["document_transport_validation"]={
                    "schema":document_transport.VERSION,
                    "payload_sha256":decoded["payload_sha256"],
                    "document_sha256":decoded["document_sha256"],
                    "metadata":deepcopy(decoded["metadata"]),
                    "original_wire_output_preserved":True,"model_document_repaired":False}
                accepted=decoded["document"]
            else:
                if wire.get("structured_schema") is not None:
                    Draft202012Validator(wire["structured_schema"]).validate(receipt["output"])
                accepted=receipt["output"]
            receipt["validation"]=validator(deepcopy(accepted)) or {}
            receipt["status"]="contract_valid"
        except document_transport.DocTransportError as exc:
            receipt.update(status="contract_rejected" if exc.failure_kind=="state_contract" else "interface_rejected",
                failure=fault(exc.code,exc.failure_kind,"complete_new_response_then_full_validation",received=True),
                validation_error={"message":str(exc),"detail":deepcopy(exc.detail)})
        except ValidationError as exc:
            receipt.update(status="contract_rejected",failure=fault("MODULE_SCHEMA_INVALID","state_contract","complete_new_response_then_full_validation",received=True),
                validation_error={"message":exc.message,"path":list(exc.absolute_path)})
        except Exception as exc:
            receipt.update(status="contract_rejected",failure=validation_failure(exc),
                validation_error={"message":str(exc),"detail":getattr(exc,"detail",{})})
        return receipt

    def evidence_path(self,ordinal):
        return self.root/"call_evidence"/f"call_{ordinal:03}"

    def evidence_identity(self,receipt):
        return {"ordinal":receipt["ordinal"],"label":receipt["label"],
            "request_sha256":receipt["request_sha256"],
            "source_binding_sha256":receipt["source_binding_sha256"],
            "role":receipt["request"]["role"],"model":receipt["request"]["model"]}

    def effective_receipt(self,row):
        original=read(self.root/row["receipt"])
        index_path=self.root/"RECOVERY_INDEX.json"
        if not index_path.exists():return original
        index=read(index_path)
        if index.get("schema")!="creative_response_recovery_index/v1":raise RuntimeError("recovery index changed")
        entry=index.get("recoveries",{}).get(str(row["ordinal"]))
        if not entry:return original
        path=self.root/"recovery"/f"call_{row['ordinal']:03}.json"
        if entry.get("file")!=str(path.relative_to(self.root)) or sha_file(path)!=entry.get("sha256"):
            raise RuntimeError("recovery receipt changed")
        recovered=read(path)
        if recovered.get("schema")!="creative_response_local_recovery/v1" or recovered.get("original_receipt_sha256")!=row["receipt_sha256"]:
            raise RuntimeError("recovery original binding changed")
        effective=recovered["effective_receipt"]
        for key in ("ordinal","label","request","request_sha256","source_binding_sha256","token_reservation"):
            if effective[key]!=original[key]:raise RuntimeError("recovery request or reservation changed")
        journal=CallEvidenceJournal(self.evidence_path(row["ordinal"]),self.evidence_identity(original),create=False)
        body,manifest=journal.load_body()
        if digest(manifest)!=recovered["body_manifest_sha256"] or sha_file(self.evidence_path(row["ordinal"])/"response_body.raw")!=manifest["stored_sha256"]:
            raise RuntimeError("recovery raw evidence changed")
        return effective

    def recover_response(self,ordinal,validator):
        """Explicit local recovery of a complete saved reply; never invokes a client."""
        with self.lock():
            ledger=read(self.ledger);self.check(ledger)
            rows=[row for row in ledger["calls"] if row["ordinal"]==ordinal]
            if len(rows)!=1:raise RuntimeError("original call ordinal missing")
            row=rows[0];original=read(self.root/row["receipt"])
            effective=self.effective_receipt(row)
            if effective!=original:return effective
            if original["status"] not in ("pending_response","outcome_unknown"):
                raise RuntimeError("original call does not need response recovery")
            journal=CallEvidenceJournal(self.evidence_path(ordinal),self.evidence_identity(original),create=False)
            body,manifest=journal.load_body()
            wire=original["request"];recovered=deepcopy(original)
            try:
                result=parse_saved_response(body,manifest,wire["role"],wire["model"],
                    wire["parameters"]["thinking"],wire.get("structured_schema"),journal)
            except EvidenceCallError as exc:
                failure=exception_failure(exc)
                recovered.update(status="interface_rejected" if exc.provider_outcome_known else "outcome_unknown",
                    failure=failure,error=str(exc),response_metadata=exc.response_metadata or {},
                    response_text=exc.response_text,response_payload=exc.response_payload,completed_at=now())
            else:
                recovered.update(response_metadata=result.metadata,response_text=result.text,
                    response_payload=result.response_payload,completed_at=now(),status="response_received")
                failure=response_failure(result.metadata,result.text,require_tool=wire.get("structured_schema") is not None)
                if failure:recovered.update(status="interface_rejected",failure=failure)
                else:
                    try:value=strict_json(result.text)
                    except (json.JSONDecodeError,ValueError):
                        recovered.update(status="interface_rejected",failure=fault("INVALID_JSON_RESPONSE","interface","diagnose_output_protocol",received=True))
                    else:
                        recovered["output"]=value;self._validate_output(recovered,wire,validator)
            recovered["call_evidence"]={"directory":str(self.evidence_path(ordinal).relative_to(self.root)),"identity_sha256":journal.identity_sha256}
            value={"schema":"creative_response_local_recovery/v1","original_receipt_sha256":row["receipt_sha256"],
                "body_manifest_sha256":digest(manifest),"effective_receipt":recovered,
                "provider_called":False,"original_receipt_mutated":False,"budget_reset":False}
            path=self.root/"recovery"/f"call_{ordinal:03}.json"
            # If publication stopped between receipt and index, verify the orphan
            # against the original saved reply instead of making another model call.
            if path.exists():
                stored=read(path)
                old=deepcopy(stored);new=deepcopy(value)
                old["effective_receipt"].pop("completed_at",None)
                new["effective_receipt"].pop("completed_at",None)
                if old!=new:raise RuntimeError("orphan recovery differs from original saved response")
                value=stored
            else:write(path,value,True)
            metadata=value["effective_receipt"].get("response_metadata",{})
            rid=metadata.get("response_id")
            if rid and type(metadata.get("total_tokens")) is int:
                for peer in ledger["calls"]:
                    if peer["ordinal"]==ordinal:continue
                    other=self.effective_receipt(peer).get("response_metadata",{})
                    if other.get("response_id")==rid and type(other.get("total_tokens")) is int:
                        raise RuntimeError("duplicate response identity; reconcile billing")
            index_path=self.root/"RECOVERY_INDEX.json"
            index=read(index_path) if index_path.exists() else {"schema":"creative_response_recovery_index/v1","recoveries":{}}
            if str(ordinal) in index["recoveries"]:raise RuntimeError("recovery already registered")
            index["recoveries"][str(ordinal)]={"file":str(path.relative_to(self.root)),"sha256":sha_file(path)}
            write(index_path,index)
            # Duplicate response identities and missing usage remain hard gates.
            self.usage(ledger)
            write(self.root/"RESULT.json",self.summary())
            return self.effective_receipt(row)

    def dispatch(self,label,wire,validator):
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,90}",label):raise ValueError("safe stage label required")
        if wire.get("role") not in self.models or wire.get("model")!=self.models[wire["role"]]["model"]:raise RuntimeError("role model changed")
        cap=wire.get("parameters",{}).get("max_completion_tokens")
        if type(cap)is not int or not 0<cap<=32000:raise RuntimeError("bounded positive output cap required")
        if wire["parameters"].get("temperature")!=0.4 or wire["parameters"].get("thinking")!="disabled":raise RuntimeError("unverified model parameters")
        if wire.get("output_transport"):
            if wire["output_transport"]!=document_transport.VERSION or wire["role"]!="writer":
                raise RuntimeError("unverified output transport/role")
            if wire.get("structured_schema")!=document_transport.build_envelope_schema():
                raise RuntimeError("document transport envelope schema changed")
            Draft202012Validator.check_schema(wire["inner_document_schema"])
        elif "inner_document_schema" in wire:
            raise RuntimeError("inner schema requires explicit document transport")
        request_sha=digest(wire)
        with self.lock():
            ledger=read(self.ledger);self.check(ledger);self._quota_guard();self.usage(ledger)
            for c in ledger["calls"]:
                r=self.effective_receipt(c)
                if r["request_sha256"]==request_sha:
                    # A cached response is never re-dispatched or rewritten. Recheck
                    # today's acceptance against a copy of the original model value.
                    cached=deepcopy(r)
                    if r["status"]=="contract_valid":
                        self._validate_output(cached,wire,validator)
                        if cached["status"]!="contract_valid":cached["cached_response_rejected_locally"]=True
                    return cached
                if c["label"]==label:raise RuntimeError("existing label bound to another request; use explicit new stage version")
            for c in ledger["calls"]:
                r=self.effective_receipt(c);m=r.get("response_metadata",{})
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
            journal=None
            client_method_entered=False
            try:
                journal=CallEvidenceJournal(self.evidence_path(ordinal),self.evidence_identity(r))
                client=self.client_factory()
                p=wire["parameters"]
                client_method_entered=True
                result=client.call(wire["role"],wire["messages"],max_tokens=cap,temperature=p["temperature"],
                    thinking=p["thinking"],structured_schema=wire.get("structured_schema"),evidence=journal)
            except Exception as exc:
                if not client_method_entered and not isinstance(exc,EvidenceCallError):
                    exc=EvidenceCallError("LOCAL_PREFLIGHT_FAILED",started=False,outcome_known=True,cause_type=type(exc).__name__)
                failure=exception_failure(exc)
                known=failure.get("provider_outcome_known",failure["response_received"])
                status="blocked_before_dispatch" if getattr(exc,"provider_dispatch_started",None) is False else ("interface_rejected" if known else "outcome_unknown")
                r.update(status=status,
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
                        self._validate_output(r,wire,validator)
            if journal is not None:
                r["call_evidence"]={"directory":str(self.evidence_path(ordinal).relative_to(self.root)),"identity_sha256":journal.identity_sha256}
            write(self.root/name,r);ledger["calls"][-1]["receipt_sha256"]=sha_file(self.root/name);write(self.ledger,ledger)
            write(self.root/"RESULT.json",self.summary())
            return r
