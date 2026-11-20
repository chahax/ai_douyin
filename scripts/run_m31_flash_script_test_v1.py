"""One explicitly requested new-model script and one necessary full review.

Old M3 calls, native candidate limits and material bytes remain immutable.
No format/content recovery, transport retry, director or media dispatch.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import base64
import json
import os
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_fresh_legal_compact_continuation_v1 as old
from scripts import run_fresh_legal_full_flow_v1 as original
from scripts import creative_m31_flash_role_clients_v1 as clients
from src.content_factory import creative_fresh_script_feasibility_v3 as feasibility
from src.content_factory import creative_known_draft_continuation_v2 as windows
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as fresh
from src.content_factory import creative_studio_task_store_v1 as tasks
from src.content_factory.creative_response_contract import fault, validation_failure, response_failure
from scripts.creative_call_evidence_v1 import CallEvidenceJournal
from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError, evidence_exception_failure as exception_failure
from jsonschema import Draft202012Validator, ValidationError

VERSION = "m31_flash_script_test/v1"
ROOT = PROJECT / "data/production_trials/m31_flash_script_test_20261013/round_01"
OLD_ROOT = original.DEFAULT_ROOT
PROFILE = PROJECT / "config/creative_script_model_profile_m31_flash_v1.json"
PLAN = PROJECT / "docs/CREATIVE_M31_FLASH_SCRIPT_TEST_PLAN_20261013.md"
GRANT = "m31_flash_complete_script_20261013_user_requested"
write, read, digest, sha_file, now, strict_json = (control.write, control.read, control.digest,
    control.sha_file, control.now, control.strict_json)


class AlreadyClaimed(RuntimeError):
    pass


def models():
    profile = read(PROFILE)
    return {role:{k:profile[role][k] for k in ("provider","model","base_url")}
            for role in ("writer","director")}


def old_guard():
    old.verify_operator(OLD_ROOT)
    ledger = read(OLD_ROOT / "CALL_LEDGER.json")
    old.verify_known_task_history(OLD_ROOT, [read(OLD_ROOT / row["receipt"]) for row in ledger["calls"]])
    if len(ledger["calls"]) != 8 or ledger["calls"][-1]["ordinal"] != 528:
        raise ValueError("original eight-receipt lineage changed")
    if ledger["starting_spend"]["calls_started"]+len(ledger["calls"]) != 528 or ledger["starting_spend"]["reported_tokens"]+sum(
        read(OLD_ROOT / row["receipt"])["response_metadata"]["total_tokens"] for row in ledger["calls"]) != 9951442:
        raise ValueError("original cumulative consumption changed")
    for rel, sha in ledger["source_manifest"].items():
        if sha_file(PROJECT / rel) != sha or sha_file(OLD_ROOT / "source_at_dispatch" / rel) != sha:
            raise ValueError("original frozen source changed")
    return ledger


def source_gate(current=None):
    # The complete frozen packet is the authority, never its compact projection.
    current = current or datetime.now(timezone.utc)
    return fresh.graph_bridge.validate_packet(read(OLD_ROOT / "source/SOURCE_PACKET.json"),
        now=current.isoformat() if isinstance(current,datetime) else current)


def input_context():
    receipt = read(OLD_ROOT / "call_528_fresh_draft_03_known_local_revision.json")
    payload = strict_json(receipt["request"]["messages"][1]["content"])
    native = read(OLD_ROOT / "call_525_fresh_plan_02_format_recovery.json")["output"]
    if fresh.contract.compile_plan(native, payload["brief"]) != payload["creative_scene_plan"]:
        raise ValueError("accepted complete plan identity changed")
    return receipt, payload


def writer_request():
    receipt, payload = input_context()
    payload["previous_complete_document"] = deepcopy(receipt["output"])
    payload.pop("dialogue_window_diagnostics", None)
    payload["complete_script_feasibility_diagnostics"] = feasibility.diagnose_script(
        receipt["output"], payload["brief"], payload["production_preferences"])
    payload["revision_requirements"] = [{"target":"complete_native_script",
        "requirement":"本次明确新模型测试，提交一份完整原生新稿；同时修复所有单句与整片下界，保留冻结事实、人物关系、行事功能和因果。自然压缩完整对白总量并给动作/反应留时间；不只拆句、不提速、不机械定句数、不复制或拼接失败稿。"}]
    rule = fresh.AUTHOR_RULE + "本次使用M3.1 Flash Preview提交完整新稿。完整读取双诊断；180秒包括说话、动作及反应，不是只算说话。按已给完整计划组织可见冲突、人物目的、有效阻力与结果。"
    request = {"role":"writer", "model":models()["writer"]["model"],
        "messages":[{"role":"system","content":rule},
                    {"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],
        "parameters":deepcopy(read(PROFILE)["writer"]["parameters"]),
        "structured_schema":windows.build_script_schema(payload["brief"]),
        "input_provenance":{"operator_version":VERSION,"original_content_source_sha256":old.SOURCE_BINDING,
            "historical_source_collected_on":"2026-10-12","new_collection_performed":False,
            "reference_fulltext_sha256":digest(payload["reference_fulltext"]),
            "original_failed_ordinal":528,"human_direction_approved":False,"media_authorized":False}}
    if request["messages"][1]["content"].count(payload["reference_fulltext"]) != 1:
        # JSON escapes newlines; check the decoded full request instead.
        def count(value):
            if isinstance(value,str):return int(value == payload["reference_fulltext"])
            if isinstance(value,dict):return sum(count(v) for v in value.values())
            if isinstance(value,list):return sum(count(v) for v in value)
            return 0
        if count(payload) != 1:raise ValueError("reference must enter actual payload exactly once")
    clients.expected_wire_request(request)
    return request


def review_request(native_script):
    _, source = input_context()
    script = fresh.contract.compile_script(native_script, source["brief"])
    context = {k:deepcopy(source[k]) for k in ("source_packet","verified_legal_context","reference_fulltext",
        "expression_standards","production_preferences","automatic_creative_choice_not_user_approval")}
    payload = {**context,"brief":source["brief"],"full_scene_plan":source["creative_scene_plan"],
        "full_current_script":script,"evidence_catalog":fresh.contract.evidence_catalog(script),
        "legal_fact_catalog":fresh.legal_catalog(source["verified_legal_context"]),"quality_criteria":deepcopy(fresh.CRITERIA)}
    return {"role":"director","model":models()["director"]["model"],
        "messages":[{"role":"system","content":fresh.REVIEW_RULE},
                    {"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],
        "parameters":deepcopy(read(PROFILE)["director"]["parameters"]),
        "structured_schema":fresh.review_schema(script,source["brief"],source["creative_scene_plan"],source["verified_legal_context"]),
        "input_provenance":{"operator_version":VERSION,"full_script_sha256":digest(script),
            "native_script_sha256":digest(native_script),"original_content_source_sha256":old.SOURCE_BINDING,
            "human_direction_approved":False,"media_authorized":False}}


class M31Runtime(control.ContinuationRuntime):
    def summary(self):
        current = super().summary()
        current["new_unknown_token_reservations"] = current["unknown_token_reservations"]
        current["inherited_unknown_token_reservations"] = self.inherited.get("unknown_token_reservations", 0)
        current["unknown_token_reservations"] += current["inherited_unknown_token_reservations"]
        current["historical_pending_ordinals"] = deepcopy(self.inherited.get("pending_ordinals", []))
        return current

    def _validate_output(self, receipt, wire, validator):
        try:
            receipt["validation"] = validator(deepcopy(receipt["output"])) or {}
            Draft202012Validator(wire["structured_schema"]).validate(receipt["output"])
            receipt["status"] = "contract_valid"
        except ValidationError as exc:
            receipt.update(status="contract_rejected",failure=fault("MODULE_SCHEMA_INVALID","state_contract","complete_new_response_then_full_validation",received=True),
                validation_error={"message":exc.message,"path":list(exc.absolute_path)})
        except Exception as exc:
            receipt.update(status="contract_rejected",failure=validation_failure(exc),
                validation_error={"message":str(exc),"detail":deepcopy(getattr(exc,"detail",{}))})
        return receipt

    # Static independent transport policy; frozen old entry remains unchanged.
    def dispatch(self,label,wire,validator):
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,90}",label):raise ValueError("safe stage label required")
        if wire.get("role") not in self.models or wire.get("model")!=self.models[wire["role"]]["model"]:raise RuntimeError("role model changed")
        cap=wire.get("parameters",{}).get("max_completion_tokens")
        if type(cap)is not int or not 0<cap<=32000:raise RuntimeError("bounded positive output cap required")
        clients.expected_wire_request(wire)
        if wire["parameters"] != read(PROFILE)[wire["role"]]["parameters"]:
            raise RuntimeError("selected model profile parameters changed")
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
            calls = ledger["calls"]
            if wire["role"] == "writer":
                if calls or label != "m31_complete_script_01":
                    raise RuntimeError("one new-model native script scope exhausted")
            elif len(calls) != 1 or label != "m31_full_review_01" or self.effective_receipt(calls[0])["status"] != "contract_valid":
                raise RuntimeError("review requires the sole accepted complete script")
            elif digest(wire) != digest(review_request(self.effective_receipt(calls[0])["output"])):
                raise RuntimeError("review must bind the sole writer native full script")
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


def get_runtime():
    freeze = read(ROOT / "TEST_FREEZE.json")
    def guard():
        old_guard()
        source_gate()
        if sha_file(OLD_ROOT / "CALL_LEDGER.json") != freeze["old_ledger_sha256"]:
            raise ValueError("old cumulative ledger changed")
        for p, sha in freeze["files"].items():
            if sha_file(p) != sha:raise ValueError("test frozen input changed: " + p)
    return M31Runtime(PROJECT,ROOT,[Path(p) for p in freeze["sources"]],freeze["inherited"],freeze["models"],
        inherited_guard=guard,quota_state=None,shared_lock=PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock")


def prepare():
    if (ROOT / "RUN_CLAIM.json").exists() or (ROOT / "TEST_FREEZE.json").exists():
        raise AlreadyClaimed("test already prepared or claimed; inspect originals")
    ledger = old_guard()
    source_gate()
    inherited = deepcopy(ledger["starting_spend"])
    inherited.update(calls_started=528,reported_tokens=9951442,calls_with_known_usage=526)
    scope = {"schema":VERSION+"/user_scope","user_quote":"剧本生产换M3.1 Flash Preview然后生产个剧本看看",
        "grant_id":GRANT,"native_writer_limit":1,"full_review_limit":1,"old_native_draft_used":3,
        "old_native_draft_limit":3,"additional_native_draft_authorized_by_this_request":1,
        "automatic_retry":False,"format_recovery_allowed":False,"media_authorized":False,
        "starting_spend":inherited,"old_ledger_sha256":sha_file(OLD_ROOT/"CALL_LEDGER.json")}
    write(ROOT/"USER_SCOPE.json",scope,True)
    request = writer_request()
    write(ROOT/"REQUEST_PREVIEW.json",request,True)
    write(ROOT/"EXPECTED_SDK_BODY.json",clients.expected_wire_request(request),True)
    paths = {str((PROJECT/rel).resolve()) for rel in ledger["source_manifest"]}
    paths.update(str(p.resolve()) for p in (Path(__file__),Path(clients.__file__),PROFILE,PLAN,
        Path(feasibility.__file__),ROOT/"USER_SCOPE.json",ROOT/"REQUEST_PREVIEW.json",ROOT/"EXPECTED_SDK_BODY.json",
        OLD_ROOT/"call_528_fresh_draft_03_known_local_revision.json",OLD_ROOT/"call_525_fresh_plan_02_format_recovery.json"))
    freeze = {"schema":VERSION+"/freeze","inherited":inherited,"models":models(),
        "old_ledger_sha256":scope["old_ledger_sha256"],"sources":sorted(paths),
        "files":{p:sha_file(p) for p in sorted(paths)},"media_authorized":False}
    write(ROOT/"TEST_FREEZE.json",freeze,True)
    result=get_runtime().prepare()
    write(ROOT/"STATE.json",{"status":"prepared", "complete_script_ready":False,"human_quality_approved":False})
    return result


def invoke(runtime,label,request,validator):
    runtime.inherited_guard()
    clients.expected_wire_request(request)
    store=tasks.TaskStore(ROOT/"TASKS.sqlite3")
    graph_id="call_"+digest({"grant":GRANT,"label":label})[:24]
    store.register_graph({"schema_version":tasks.GRAPH_SCHEMA,"graph_id":graph_id,"nodes":[
        {"node_id":"source","kind":"source","input":{"source":old.SOURCE_BINDING,"request_sha256":digest(request)},"depends_on":[]},
        {"node_id":"result","kind":"text","input":{"label":label},"depends_on":["source"]}]})
    scope=ROOT/"USER_SCOPE.json"
    authorization={"schema_version":tasks.AUTH_SCHEMA,"authorization_id":graph_id+":scope","graph_id":graph_id,
        "node_ids":["result"],"scope":"text","purpose":"dispatch","source_sha256":store.snapshot(graph_id)["source_sha256"],
        "max_attempts":1,"prior_attempts":0,"allows_content_revision":False,"evidence_ref":str(scope)+"#"+request["role"],"evidence_sha256":sha_file(scope)}
    attempt=store.claim(graph_id,"result",{"provider_id":request["model"],"payload":request},authorization)
    runtime.client_factory=clients.make_client_factory(request)
    receipt=runtime.dispatch(label,request,validator)
    evidence=original.verify_receipt_evidence(runtime,receipt,request)
    outbound=evidence/"request_body.raw"
    if outbound.exists() and strict_json(outbound.read_text(encoding="utf-8")) != clients.expected_wire_request(request):
        raise ValueError("actual SDK request differs from selected model profile")
    raw=evidence/"response_body.raw";body=raw.read_bytes() if raw.exists() else b""
    known,outcome,tool_status=original.classify_receipt(receipt)
    meta=receipt.get("response_metadata",{});total=meta.get("total_tokens");http=meta.get("http_status_code")
    store.accept_result(attempt["claim_id"],{"schema_version":tasks.RESULT_SCHEMA,"claim_id":attempt["claim_id"],
        "request_sha256":attempt["request_sha256"],"service_task_id":None,"outcome":outcome,"result_known":known,
        "usage_known":type(total)is int and total>=0,"usage":{"unit":"reported_tokens","amount":total} if type(total)is int and total>=0 else None,
        "complete":meta.get("response_body_complete") is True,"complete_end":meta.get("finish_reason") in ("stop","tool_calls"),
        "schema_tool_status":tool_status,"contract_valid":receipt["status"]=="contract_valid" if known else None,
        "raw_receipt":{"encoding":"base64","body":base64.b64encode(body).decode(),"sha256":__import__("hashlib").sha256(body).hexdigest(),"http_status":http if type(http)is int else None},
        "output":{"receipt_ordinal":receipt["ordinal"],"native_output":receipt.get("output")}})
    return receipt


def run():
    runtime=get_runtime();runtime.inherited_guard()
    with (ROOT/"RUN_CLAIM.json").open("x",encoding="utf-8") as handle:
        json.dump({"schema":VERSION+"/claim","pid":os.getpid(),"started_at":now(),"automatic_restart":False},handle)
    request=read(ROOT/"REQUEST_PREVIEW.json");_,context=input_context()
    receipt=invoke(runtime,"m31_complete_script_01",request,
        feasibility.make_validator(context["brief"],context["production_preferences"]))
    raw=receipt.get("output");state={"schema":VERSION+"/state","writer_ordinal":receipt["ordinal"],
        "writer_status":receipt["status"],"complete_script_ready":False,"human_quality_approved":False,
        "creative_quality_passed":False,"media_authorized":False,"automatic_retry":False,"spend":runtime.summary()}
    if isinstance(raw,dict):
        write(ROOT/"NATIVE_SCRIPT.json",raw,True)
        try:
            compiled=fresh.contract.compile_script(raw,context["brief"])
            (ROOT/"COMPLETE_SCRIPT_FOR_REVIEW.md").write_text("本次模型完整原稿；具体验收以STATE/全文审查为准，未获用户采用。\n\n"+fresh.render_script(compiled,context["brief"]),encoding="utf-8")
            write(ROOT/"SCRIPT_FEASIBILITY.json",feasibility.diagnose_script(raw,context["brief"],context["production_preferences"]),True)
        except (ValueError,KeyError,TypeError):
            state["complete_render_failed"]=True
    if receipt["status"] != "contract_valid" or not original.classify_receipt(receipt)[0]:
        state["status"]="script_not_accepted_no_retry";write(ROOT/"STATE.json",state);return state
    script=fresh.contract.compile_script(raw,context["brief"])
    review=invoke(runtime,"m31_full_review_01",review_request(raw),
        lambda v:fresh.validate_review(v,script,context["brief"],context["creative_scene_plan"],context["verified_legal_context"]))
    state.update(review_ordinal=review["ordinal"],review_status=review["status"],spend=runtime.summary())
    if review["status"] != "contract_valid" or not original.classify_receipt(review)[0]:
        state["status"]="full_review_not_accepted_no_retry"
    else:
        decision=fresh.decide_review(review["output"],script,context["brief"],context["creative_scene_plan"],context["verified_legal_context"])
        write(ROOT/"FULL_REVIEW.json",review["output"],True);write(ROOT/"DECISION.json",decision,True)
        state.update(status=decision["status"],complete_script_ready=decision["status"]=="text_ready_for_director")
    write(ROOT/"STATE.json",state);return state


def main():
    parser=argparse.ArgumentParser();parser.add_argument("command",choices=("prepare","run","status"));args=parser.parse_args()
    if args.command=="prepare":result=prepare()
    elif args.command=="status":result=read(ROOT/"STATE.json")
    else:
        try:result=run()
        except FileExistsError:raise AlreadyClaimed("existing test claim; never repeat dispatch")
        except Exception as exc:
            write(ROOT/"STATE.json",{"status":"stopped_original_request_requires_reconciliation","error_type":type(exc).__name__,
                "automatic_retry":False,"complete_script_ready":False,"human_quality_approved":False})
            raise
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=="__main__":main()
