"""Resume only the proven unsubmitted third native draft, preserving all history."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import argparse
import base64
import json
import os
import sqlite3
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_fresh_legal_compact_continuation_v1 as previous
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_fresh_legal_full_flow_v1 as original
from src.content_factory import creative_known_draft_continuation_v2 as candidate
from src.content_factory import creative_compact_legal_context_v1 as compact

VERSION = "fresh_legal_known_draft_continuation/v2"
OPERATOR_DIR = "known_draft_continuation_02"
FREEZE, CLAIM = "OPERATOR_FREEZE.json", "RUN_CLAIM.json"
SOURCE_BINDING = previous.SOURCE_BINDING
PREFIX_ORDINALS = list(range(521, 528))
QA = PROJECT / "data/qa/known_human_resume_independent_20261012"
SQL_EVIDENCE = QA / "COMPACT_DRAFT03_TASKSTORE_READONLY_SNAPSHOT_01.json"
RECONCILIATION = QA / "COMPACT_DRAFT03_LOCAL_DUPLICATE_RECONCILIATION_01.json"
OPERATOR_FILES = (
    "scripts/run_fresh_legal_known_draft_continuation_v2.py",
    "src/content_factory/creative_known_draft_continuation_v2.py",
    "src/content_factory/creative_known_local_draft_evidence_v2.py",
    "docs/CREATIVE_KNOWN_LOCAL_DRAFT_CONTINUATION_PLAN_20261013.md",
)


class ContinuationAlreadyClaimed(RuntimeError):
    pass


def location(root):
    root, _ = previous.location(root)
    return root, root / OPERATOR_DIR


def evidence_module():
    from src.content_factory import creative_known_local_draft_evidence_v2 as evidence
    return evidence


def inspect_local_stop(root, *, preparation=False):
    root, directory = location(root)
    previous.verify_operator(root)
    prior_dir = root / previous.OPERATOR_DIR
    if previous.extension.previous_worker_instance_active(control.read(prior_dir / previous.CLAIM)):
        raise ValueError("previous worker instance still active")
    ledger = control.read(root / "CALL_LEDGER.json")
    snapshot = ledger if preparation else control.read(directory / "ORIGINAL_LEDGER_SNAPSHOT.json")
    if ([r["ordinal"] for r in snapshot["calls"]] != PREFIX_ORDINALS
        or control.digest(snapshot["source_manifest"]) != SOURCE_BINDING
        or snapshot["starting_spend"]["calls_started"] != 520
        or snapshot["starting_spend"]["reported_tokens"] != 7964215
        or ledger["calls"][:7] != snapshot["calls"]
        or {k:v for k,v in ledger.items() if k != "calls"} != {k:v for k,v in snapshot.items() if k != "calls"}):
        raise ValueError("original source or seven-receipt ledger prefix changed")
    stopped = control.read(prior_dir / "TEXT_STATE.json")
    if stopped != control.read(prior_dir / "TEXT_RESULT.json"):
        raise ValueError("original terminal state/result differs")
    receipts = [control.read(root / r["receipt"]) for r in snapshot["calls"]]
    if stopped.get("receipts") != receipts:
        raise ValueError("original stopped receipt prefix differs")
    runtime = previous.original_runtime(root, ledger)
    runtime.check(ledger)
    for receipt in receipts:
        if not original.text_pipeline._known_complete(receipt, receipt["request"], SOURCE_BINDING):
            raise ValueError("original result or usage is unknown")
        previous.verified_sdk_evidence(runtime, receipt, receipt["request"])
    live_sql = evidence_module().readonly_original_draft_sql_snapshot(root, grant_id=original.GRANT_ID,
        source_binding_sha256=SOURCE_BINDING, require_exact_attempt_count=preparation)
    if live_sql != control.read(SQL_EVIDENCE):
        raise ValueError("actual readonly SQL evidence differs")
    if preparation:
        previous.verify_known_task_history(root, receipts)
        if len(ledger["calls"]) != 7:
            raise ValueError("later dispatch already exists")
    recon = control.read(RECONCILIATION)
    if (recon.get("classification") != "known_local_pre_dispatch_duplicate_request"
        or recon.get("failure_code") != "DUPLICATE_DISPATCH"
        or recon.get("draft03_sql_attempts_count") != 0
        or recon.get("runtime_528_dispatch_started") is not False
        or recon.get("production_records_modified") is not False):
        raise ValueError("independent local boundary reconciliation missing")
    return ledger, stopped, receipts[-1], live_sql


def compile_proof(ledger, stopped, failed, sql, ledger_file_sha):
    if sql["failed_graph_attempts"] or len(sql["duplicate_request_attempts"]) != 1:
        raise ValueError("local duplicate transaction is not known")
    expected_graph = "call_" + control.digest({"grant_id":original.GRANT_ID,"label":"fresh_draft_03"})[:24]
    revisions = {r["node_id"]:r for r in sql["revisions"]}
    if (sql["graph"]["graph_id"] != expected_graph or revisions["result"]["status"] != "prepared"
        or revisions["source"]["status"] != "source_ready"
        or sql["logical_request_sha256"] != control.digest(failed["request"])
        or sql["wrapped_request_sha256"] != control.digest({"provider_id":failed["request"]["model"],"payload":failed["request"]})
        or not any(r["unique"] and r["columns"] == ["request_sha"] for r in sql["attempts_unique_indices"])):
        raise ValueError("duplicate request/SQL boundary changed")
    proof = {"schema":"known_local_draft_failure_proof/v1", "code":"DUPLICATE_DISPATCH",
        "stop_state_sha256":control.digest(stopped),"result527_sha256":control.digest(failed),
        "source_binding_sha256":SOURCE_BINDING,"request_sha256":control.digest(failed["request"]),
        "failed_label":"fresh_draft_03","graph_id":expected_graph,"graph_status":"prepared",
        "sql_attempt_count":0,"ledger_receipt_ordinals":[r["ordinal"] for r in ledger["calls"]],
        "provider_dispatch_started":False,"runtime_boundary_verified":True,
        "ledger_sha256":ledger_file_sha,"taskstore_evidence_sha256":control.digest(sql)}
    candidate.validate_local_failure_proof(proof, stopped, failed, SOURCE_BINDING)
    return proof


def required_files(root, snapshot):
    _, directory = location(root)
    prior_dir = root / previous.OPERATOR_DIR
    paths = [PROJECT / p for p in OPERATOR_FILES]
    paths += [SQL_EVIDENCE, RECONCILIATION, prior_dir / previous.FREEZE, prior_dir / previous.CLAIM,
        prior_dir / "STATE.json", prior_dir / "TEXT_STATE.json", prior_dir / "TEXT_RESULT.json"]
    paths += [directory / p for p in ("ORIGINAL_LEDGER_SNAPSHOT.json","LOCAL_FAILURE_PROOF.json",
        "DIALOGUE_WINDOW_DIAGNOSTICS.json","COMPACT_CONTEXT_PREVIEW.json","PROJECTION_EVIDENCE.json")]
    runtime = previous.original_runtime(root, snapshot)
    for call in snapshot["calls"]:
        paths.append(root / call["receipt"])
        paths.extend(p for p in runtime.evidence_path(call["ordinal"]).iterdir() if p.is_file())
    return {str(p.resolve()) for p in paths}


def execution_symbols():
    resources = previous.extension.execution_resource_symbols()
    return {"allowed_python_executables":resources["allowed_python_executables"],"worker_script":str(Path(__file__).resolve())}


def projection_from_known_compact_payload(old_payload, values, *, expected_old_payload_sha256):
    """Reconstruct only the original full source for verification, never its prose."""
    if control.digest(old_payload) != expected_old_payload_sha256:
        raise ValueError("known compact payload differs from verified original request")
    for field,key in (("reference_fulltext","reference_fulltext"),("verified_legal_context","legal_context"),
        ("expression_standards","expression_standards"),("production_preferences","production_preferences")):
        if old_payload.get(field) != values[key]:
            raise ValueError("known request fixed context differs from frozen source: " + field)
    full_payload = deepcopy(old_payload)
    full_payload["source_packet"] = deepcopy(values["packet"])
    projected = compact.compact_payload(full_payload, SOURCE_BINDING, now=control.now())
    if projected != old_payload:
        raise ValueError("known compact request does not exactly map from frozen full source")
    return compact.payload_projection_evidence(full_payload, projected, SOURCE_BINDING, now=control.now())


def prepare(root):
    root, directory = location(root)
    if (directory / CLAIM).exists():
        raise ContinuationAlreadyClaimed("claim consumed; inspect original result")
    if (directory / FREEZE).exists():
        return verify_operator(root)
    ledger, stopped, failed, sql = inspect_local_stop(root, preparation=True)
    proof = compile_proof(ledger, stopped, failed, sql, control.sha_file(root / "CALL_LEDGER.json"))
    values = previous.inputs(root)
    context = compact.compact_context(**{k:v for k,v in values.items() if k != "provider_evidence"},now=control.now())
    old_payload = control.strict_json(failed["request"]["messages"][1]["content"])
    projection = projection_from_known_compact_payload(old_payload, values,expected_old_payload_sha256=control.digest(old_payload))
    directory.mkdir(exist_ok=False)
    with (directory / "ORIGINAL_LEDGER_SNAPSHOT.json").open("xb") as handle:
        handle.write((root / "CALL_LEDGER.json").read_bytes())
    for name, data in (("LOCAL_FAILURE_PROOF.json",proof),
        ("DIALOGUE_WINDOW_DIAGNOSTICS.json",candidate.dialogue_window_diagnostics(failed.get("document_output",failed.get("output")),stopped["brief"])),
        ("COMPACT_CONTEXT_PREVIEW.json",context),("PROJECTION_EVIDENCE.json",projection)):
        control.write(directory / name,data,True)
    symbols = execution_symbols()
    freeze = {"schema":VERSION+"/freeze","at_utc":control.now(),"files":{p:control.sha_file(p) for p in required_files(root,ledger)},
        "source_binding_sha256":SOURCE_BINDING,"original_grant_id":original.GRANT_ID,
        "original_source_manifest":ledger["source_manifest"],"original_calls_prefix":ledger["calls"],
        "original_ledger_static":{k:v for k,v in ledger.items() if k != "calls"},
        "original_versions":stopped["versions"],"original_limits":stopped["limits"],
        "unsubmitted_native_draft_slot":3,"additional_native_draft_capacity":0,"draft_format_recovery_maximum":1,
        "execution_resource_symbols":symbols,"external_resource_hashes":{p:control.sha_file(p) for p in symbols["allowed_python_executables"]},
        "new_media_calls":0,"automatic_restart":False,"old_budget_reset":False}
    control.write(directory / FREEZE,freeze,True)
    return verify_operator(root)


def verify_operator(root):
    root, directory = location(root)
    freeze = control.read(directory / FREEZE)
    snapshot = control.read(directory / "ORIGINAL_LEDGER_SNAPSHOT.json")
    symbols = execution_symbols()
    if (freeze.get("schema") != VERSION+"/freeze" or freeze.get("source_binding_sha256") != SOURCE_BINDING
        or freeze.get("original_grant_id") != original.GRANT_ID
        or set(freeze.get("files",{})) != required_files(root,snapshot)
        or freeze.get("original_source_manifest") != snapshot["source_manifest"]
        or freeze.get("original_calls_prefix") != snapshot["calls"]
        or freeze.get("original_ledger_static") != {k:v for k,v in snapshot.items() if k != "calls"}
        or freeze.get("original_versions") != {"theme":2,"plan":2,"draft":3}
        or freeze.get("original_limits") != {"theme":3,"plan":3,"draft":3}
        or type(freeze.get("unsubmitted_native_draft_slot")) is not int or freeze["unsubmitted_native_draft_slot"] != 3
        or type(freeze.get("additional_native_draft_capacity")) is not int or freeze["additional_native_draft_capacity"] != 0
        or type(freeze.get("draft_format_recovery_maximum")) is not int or freeze["draft_format_recovery_maximum"] != 1
        or freeze.get("new_media_calls") != 0 or freeze.get("automatic_restart") is not False or freeze.get("old_budget_reset") is not False
        or freeze.get("execution_resource_symbols") != symbols
        or set(freeze.get("external_resource_hashes",{})) != set(symbols["allowed_python_executables"])):
        raise ValueError("new operator freeze members, source, bounds or resources changed")
    original.verify_files(freeze["files"])
    original.verify_files(freeze["external_resource_hashes"])
    _, stopped, failed, sql = inspect_local_stop(root)
    proof = control.read(directory / "LOCAL_FAILURE_PROOF.json")
    if compile_proof(snapshot,stopped,failed,sql,control.sha_file(directory / "ORIGINAL_LEDGER_SNAPSHOT.json")) != proof:
        raise ValueError("local proof cannot be recomputed from immutable evidence")
    return freeze


def verify_worker(root, freeze):
    import psutil
    _, directory = location(root)
    claim = control.read(directory / CLAIM)
    if (claim.get("schema") != VERSION+"/claim" or claim.get("pid") != os.getpid()
        or claim.get("operator_freeze_sha256") != control.sha_file(directory / FREEZE)
        or claim.get("source_binding_sha256") != SOURCE_BINDING
        or claim.get("automatic_restart") is not False or claim.get("old_budget_reset") is not False):
        raise ValueError("current worker claim differs")
    symbols = freeze["execution_resource_symbols"]
    process = psutil.Process(os.getpid())
    args = process.cmdline()
    timestamp = datetime.fromisoformat(claim["started_at_utc"]).timestamp()
    if (not process.is_running() or str(Path(process.exe()).resolve()) not in symbols["allowed_python_executables"]
        or Path(process.exe()).resolve() != Path(sys._base_executable).resolve()
        or not 0 <= timestamp-process.create_time() <= 300
        or len(args)<2 or Path(args[1]).resolve() != Path(symbols["worker_script"])):
        raise ValueError("current worker entry/process instance differs")


def record(directory,status,**values):
    control.write(directory/"STATE.json",{"schema":VERSION+"/state","status":status,"at_utc":control.now(),
        "new_media_calls":0,"creative_quality_passed":False,"automatic_transport_retry":False,"old_budget_reset":False,**values})


def production_tail(root, directory, runtime, invoke, result):
    previous.verify_accepted_text_binding(directory)
    values = previous.inputs(root)
    accepted = directory / "ACCEPTED_TEXT_PENDING_DIRECTOR"
    accepted.mkdir(exist_ok=False)
    (accepted / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
    material = {"full_current_script":result["script"],"shared_manifest":result["manifest"],"planned_initial_state":result["initial"]}
    loop = original.revisions.initial_loop_state([],source_binding_sha256=SOURCE_BINDING,default_limit=3,stable_scope_material=material)
    control.write(directory / "INITIAL_LOOP_STATE.json",loop,True)
    record(directory,"whole_direction_performance_running",title=result["script"]["title"],spend=original.spend_summary(runtime))
    coordinator = original.directors.EndpointFeedbackCoordinator(invoke=invoke,
        persist_state=lambda value:control.write(directory / "LOOP_STATE.json",value),verify_frozen_source=runtime.inherited_guard,
        opening_context_builder=lambda performance:original.shared.compile_segment_context(result["manifest"],result["script"],
            result["shared_dynamic_initial"],performance["source_refs"],bootstrap=True),models=original.text_pipeline.MODEL_POLICY)
    full = coordinator.run(script=result["script"],manifest=result["manifest"],initial=result["initial"],
        reference_fulltext=values["reference_fulltext"],preferences=values["production_preferences"],brief=result["brief"],
        source_review_binding=result["source_review_binding"],state=loop,scope=control.read(root / "USER_SCOPE.json"))
    control.write(directory / "PRODUCTION_RESULT.json",full,True)
    if full["status"] == "complete_text_production_handoff_ready":
        out = directory / "DELIVERABLE"
        out.mkdir(exist_ok=False)
        (out / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"],result["brief"]),encoding="utf-8")
        control.write(out / "COMPLETE_PRODUCTION.json",full,True)
        lines = ["# 整片导演、表演与制作交接","","完整文本机器验收；视频仍待人工审核。",""]
        for segment,prompt in zip(full["direction"]["segments"],full["planned_prompts"]):
            lines += ["## " + segment["segment_id"],json.dumps(segment,ensure_ascii=False,indent=2),"",prompt,""]
        (out / "DIRECTOR_PERFORMANCE_HANDOFF.md").write_text("\n".join(lines),encoding="utf-8")
    record(directory,full["status"],reason=full.get("reason"),title=result["script"]["title"],spend=original.spend_summary(runtime),
        complete_text_handoff_ready=full.get("complete_text_handoff_ready",False),
        deliverable=str(directory / "DELIVERABLE") if (directory / "DELIVERABLE").exists() else None)


def make_invoke(root,runtime,result_path):
    store = original.task_store.TaskStore(root/"TASKS.sqlite3")
    scope = root/"USER_SCOPE.json"
    def invoke(label,request,validator):
        runtime.inherited_guard()
        ledger = control.read(runtime.ledger)
        runtime.check(ledger)
        previous.verify_known_task_history(root,[control.read(root/r["receipt"]) for r in ledger["calls"]])
        original.clients.expected_wire_request(request)
        phase,maximum = previous.stage(label,result_path)
        gid = "call_"+control.digest({"grant_id":original.GRANT_ID,"label":label})[:24]
        graph={"schema_version":original.task_store.GRAPH_SCHEMA,"graph_id":gid,"nodes":[
            {"node_id":"source","kind":"source","input":{"frozen_source_sha256":SOURCE_BINDING,"request_sha256":control.digest(request)},"depends_on":[]},
            {"node_id":"result","kind":"text","input":{"label":label,"phase":phase},"depends_on":["source"]}]}
        store.register_graph(graph)
        auth={"schema_version":original.task_store.AUTH_SCHEMA,"authorization_id":gid+":scope","graph_id":gid,
            "node_ids":["result"],"scope":"text","purpose":"dispatch","source_sha256":store.snapshot(gid)["source_sha256"],
            "max_attempts":maximum,"prior_attempts":0,"allows_content_revision":False,
            "evidence_ref":str(scope)+"#"+phase,"evidence_sha256":control.sha_file(scope)}
        before = control.sha_file(runtime.ledger)
        try:
            attempt = store.claim(gid,"result",{"provider_id":request["model"],"payload":request},auth)
        except original.task_store.TaskStoreError as exc:
            with sqlite3.connect((root/"TASKS.sqlite3").resolve().as_uri()+"?mode=ro",uri=True) as conn:
                count = conn.execute("SELECT COUNT(*) FROM attempts WHERE graph_id=?",(gid,)).fetchone()[0]
            if exc.code == "DUPLICATE_DISPATCH" and count == 0 and control.sha_file(runtime.ledger) == before:
                proof={"schema":VERSION+"/new_local_predispatch_stop","code":exc.code,"graph_id":gid,
                    "request_sha256":control.digest(request),"ledger_sha256":before,"sql_attempt_count":0,
                    "provider_dispatch_started":False,"runtime_boundary_verified":True}
                path=result_path.parent/(label+"_LOCAL_STOP.json")
                control.write(path,proof,True)
                raise candidate.KnownLocalDispatchError(request_sha256=control.digest(request),evidence_sha256=control.digest(proof),detail=proof) from exc
            raise
        runtime.client_factory=lambda:original.clients.CapabilityRoleClients(expected_request=deepcopy(request))
        receipt=runtime.dispatch(label,request,validator)
        evidence=previous.verified_sdk_evidence(runtime,receipt,request)
        meta=receipt.get("response_metadata",{})
        raw_path=evidence/"response_body.raw"
        raw=raw_path.read_bytes() if raw_path.exists() else b""
        http,total=meta.get("http_status_code"),meta.get("total_tokens")
        known,outcome,tool_status=original.classify_receipt(receipt)
        store.accept_result(attempt["claim_id"],{"schema_version":original.task_store.RESULT_SCHEMA,
            "claim_id":attempt["claim_id"],"request_sha256":attempt["request_sha256"],"service_task_id":None,"outcome":outcome,
            "result_known":known,"usage_known":type(total) is int and total>=0,"usage":{"unit":"reported_tokens","amount":total} if type(total) is int and total>=0 else None,
            "complete":meta.get("response_body_complete") is True,"complete_end":meta.get("finish_reason") in ("stop","tool_calls"),
            "schema_tool_status":tool_status,"contract_valid":receipt["status"]=="contract_valid" if known else None,
            "raw_receipt":{"encoding":"base64","body":base64.b64encode(raw).decode("ascii"),"sha256":__import__("hashlib").sha256(raw).hexdigest(),"http_status":http if type(http) is int else None},
            "output":{"original_receipt":str(root/next(r["receipt"] for r in control.read(runtime.ledger)["calls"] if r["ordinal"]==receipt["ordinal"])),
                "receipt_sha256":control.digest(receipt),"native_output":receipt.get("document_output",receipt.get("output"))}})
        return receipt
    return invoke


def run(root):
    root,directory=location(root)
    if (directory/CLAIM).exists():
        raise ContinuationAlreadyClaimed("already claimed; inspect original results")
    inspect_local_stop(root,preparation=True)
    freeze=verify_operator(root)
    claim={"schema":VERSION+"/claim","started_at_utc":control.now(),"pid":os.getpid(),
        "operator_freeze_sha256":control.sha_file(directory/FREEZE),"source_binding_sha256":SOURCE_BINDING,
        "automatic_restart":False,"old_budget_reset":False,"new_media_calls":0}
    try:
        with (directory/CLAIM).open("x",encoding="utf-8") as handle:
            json.dump(claim,handle,ensure_ascii=False,indent=2,allow_nan=False)
    except FileExistsError as exc:
        raise ContinuationAlreadyClaimed("another worker won claim") from exc
    accepted_binding=None
    def guard():
        checked=verify_operator(root)
        verify_worker(root,checked)
        if accepted_binding is not None:
            previous.verify_accepted_text_binding(directory,accepted_binding)
    runtime=previous.original_runtime(root,control.read(root/"CALL_LEDGER.json"),guard)
    runtime.prepare()
    result_path=directory/"TEXT_RESULT.json"
    invoke=make_invoke(root,runtime,result_path)
    proof=control.read(directory/"LOCAL_FAILURE_PROOF.json")
    scope=root/"USER_SCOPE.json"
    def seed_factory(receipt):
        rows=[r for r in control.read(runtime.ledger)["calls"] if r["ordinal"]==receipt["ordinal"]]
        if len(rows)!=1:
            raise ValueError("one native receipt required")
        row=rows[0]
        return previous.modules()[1].compile_missing_tool_seed(receipt,
            receipt_bytes=(root/row["receipt"]).read_bytes(),evidence_directory=runtime.evidence_path(receipt["ordinal"]),
            expected_receipt_sha256=row["receipt_sha256"],expected_source_binding_sha256=SOURCE_BINDING,
            expected_wire=original.clients.expected_wire_request(receipt["request"]),verifier=lambda r,q:previous.verified_sdk_evidence(runtime,r,q))
    pipeline=candidate.KnownDraftContinuation(invoke=invoke,persist_state=lambda value:control.write(directory/"TEXT_STATE.json",value),
        payload_projector=lambda p:compact.compact_payload(p,SOURCE_BINDING,now=control.now()),
        operator_binding={"operator_version":VERSION,"operator_freeze_sha256":control.sha_file(directory/FREEZE),
            "projection_sha256":control.sha_file(directory/"PROJECTION_EVIDENCE.json"),"local_failure_proof_sha256":control.digest(proof),"source_binding_sha256":SOURCE_BINDING},
        format_recovery_authorization={"authorized":True,"source_binding_sha256":SOURCE_BINDING,"evidence_ref":str(scope),"evidence_sha256":control.sha_file(scope)},
        resume_guard=guard,format_seed_factory=seed_factory)
    old=control.read(root/previous.OPERATOR_DIR/"TEXT_STATE.json")
    failed=old["receipts"][-1]
    record(directory,"known_local_draft_continuation_running",versions=old["versions"],spend=original.spend_summary(runtime))
    result=pipeline.run_from_known_local_draft(stop_state=old,result527=failed,local_failure_proof=proof,**previous.inputs(root),now=control.now())
    control.write(result_path,result,True)
    if result["status"]!="text_ready_for_director":
        record(directory,result["status"],versions=result.get("versions"),spend=original.spend_summary(runtime),complete_text_handoff_ready=False)
        return
    accepted_binding=previous.bind_accepted_text(root,directory,result)
    production_tail(root,directory,runtime,invoke,result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("prepare","run","status"))
    parser.add_argument("--root",type=Path,default=original.DEFAULT_ROOT)
    args=parser.parse_args()
    root,directory=location(args.root)
    try:
        if args.command=="prepare":
            freeze=prepare(root)
            print(json.dumps({"status":"prepared","operator_files":len(freeze["files"]),"native_versions":freeze["original_versions"],"new_dispatches":0},ensure_ascii=False))
        elif args.command=="status":
            print(json.dumps(control.read(directory/"STATE.json"),ensure_ascii=False,indent=2))
        else:
            run(root)
    except ContinuationAlreadyClaimed:
        print(json.dumps({"status":"original_continuation_exists","new_dispatches":0}))
        raise SystemExit(2)
    except Exception as exc:
        if args.command=="run" and (directory/CLAIM).exists():
            record(directory,"stopped_exception",exception_type=type(exc).__name__,reason=str(exc)[:1200] if isinstance(exc,(ValueError,RuntimeError)) else "inspect original local evidence")
        raise


if __name__=="__main__":
    main()
