"""Independent offline evidence/entry tests. No service construction or dispatch."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import pytest

PROJECT=Path(__file__).resolve().parents[1]
QA=PROJECT/"data/qa/known_human_resume_independent_20261012"
SPEC=importlib.util.spec_from_file_location("known_local_readonly_sql_support",QA/"known_local_sql_snapshot_support_v1.py")
sqlsupport=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sqlsupport)
from scripts import run_fresh_legal_compact_continuation_v1 as old

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args,**kwargs): raise AssertionError("Network forbidden in independent known-local tests")
    monkeypatch.setattr(socket,"socket",denied)
    monkeypatch.setattr(socket,"create_connection",denied)

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")

@pytest.fixture
def sql_root(tmp_path):
    root=tmp_path/"root";root.mkdir()
    snapshot=old.control.read(QA/"COMPACT_DRAFT03_TASKSTORE_READONLY_SNAPSHOT_01.json")
    live=old.original.DEFAULT_ROOT
    ledger=old.control.read(live/"CALL_LEDGER.json")
    stop=old.control.read(live/old.OPERATOR_DIR/"TEXT_STATE.json")
    write(root/"CALL_LEDGER.json",ledger)
    write(root/"compact_continuation_01/TEXT_STATE.json",stop)
    write(root/ledger["calls"][6]["receipt"],old.control.read(live/ledger["calls"][6]["receipt"]))
    with sqlite3.connect(root/"TASKS.sqlite3") as c:
        c.execute("CREATE TABLE graphs(graph_id TEXT PRIMARY KEY,definition TEXT,sha TEXT,created TEXT)")
        c.execute("CREATE TABLE nodes(graph_id TEXT,node_id TEXT,kind TEXT,dependencies TEXT,current_revision INTEGER)")
        c.execute("CREATE TABLE revisions(graph_id TEXT,node_id TEXT,revision INTEGER,input TEXT,input_sha TEXT,status TEXT,output TEXT,output_sha TEXT,reason TEXT,created TEXT)")
        c.execute("CREATE TABLE attempts(claim_id TEXT PRIMARY KEY,graph_id TEXT,node_id TEXT,revision INTEGER,request_sha TEXT NOT NULL UNIQUE,status TEXT,result_sha TEXT,created TEXT)")
        g=snapshot["graph"];c.execute("INSERT INTO graphs VALUES(?,?,?,?)",[g[k] for k in ("graph_id","definition","sha","created")])
        for r in snapshot["nodes"]:
            c.execute("INSERT INTO nodes VALUES(?,?,?,?,?)",[g["graph_id"]]+[r[k] for k in ("node_id","kind","dependencies","current_revision")])
        for r in snapshot["revisions"]:
            c.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?)",[g["graph_id"]]+[r[k] for k in ("node_id","revision","input","input_sha","status","output","output_sha","reason","created")])
        for r in snapshot["original_prefix_attempts"]:
            c.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",[r[k] for k in ("claim_id","graph_id","node_id","revision","request_sha","status","result_sha","created")])
    return root

def snapshot(root,*,exact=True):
    return sqlsupport.readonly_original_draft_sql_snapshot(root,grant_id=old.original.GRANT_ID,
        source_binding_sha256=old.SOURCE_BINDING,require_exact_attempt_count=exact)

def test_snapshot_reads_without_modifying_sql_or_files(sql_root):
    before={p.relative_to(sql_root).as_posix():p.read_bytes() for p in sql_root.rglob("*") if p.is_file()}
    a=snapshot(sql_root); b=snapshot(sql_root)
    assert a==b and len(a["original_prefix_attempts"])==7 and a["failed_graph_attempts"]==[]
    after={p.relative_to(sql_root).as_posix():p.read_bytes() for p in sql_root.rglob("*") if p.is_file()}
    assert before==after

def test_snapshot_accepts_append_only_for_live_guard(sql_root):
    before=snapshot(sql_root)
    with sqlite3.connect(sql_root/"TASKS.sqlite3") as c:
        c.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",("new-legitimate","new-graph","result",1,"b"*64,"completed","c"*64,"later"))
    with pytest.raises(ValueError,match="exactly seven"):snapshot(sql_root)
    assert snapshot(sql_root,exact=False)==before

@pytest.mark.parametrize("sql",[
    "UPDATE revisions SET status='claimed' WHERE node_id='result'",
    "UPDATE revisions SET output='{}' WHERE node_id='result'",
    "UPDATE revisions SET output_sha='bad' WHERE node_id='result'",
    "UPDATE revisions SET revision=2 WHERE node_id='result'",
    "UPDATE revisions SET status='prepared' WHERE node_id='source'",
    "DELETE FROM nodes WHERE node_id='source'",
    "DELETE FROM revisions WHERE node_id='source'",
    "DELETE FROM attempts WHERE graph_id='call_1ffd2116c45aac7af6bb51d6'",
    "UPDATE graphs SET sha='bad'",
])
def test_snapshot_rejects_sql_boundary_mutation(sql_root,sql):
    with sqlite3.connect(sql_root/"TASKS.sqlite3") as c:c.execute(sql)
    with pytest.raises(ValueError):snapshot(sql_root)

@pytest.mark.parametrize("change",["state_status","draft_counter","claim_label","claim_sha","source","receipt_request","prefix_order","receipt_escape"])
def test_snapshot_rejects_file_identity_changes(sql_root,change):
    lp=sql_root/"CALL_LEDGER.json";sp=sql_root/"compact_continuation_01/TEXT_STATE.json"
    ledger=sqlsupport.read(lp);state=sqlsupport.read(sp)
    if change=="state_status":state["status"]="halt_result_unknown"
    if change=="draft_counter":state["versions"]["draft"]=2
    if change=="claim_label":state["events"][-1]["label"]="fresh_draft_04"
    if change=="claim_sha":state["events"][-1]["request_sha256"]="a"*64
    if change=="source":ledger["source_manifest"]={}
    if change=="prefix_order":ledger["calls"][0]["ordinal"]=522
    if change=="receipt_escape":ledger["calls"][6]["receipt"]="../outside.json"
    if change=="receipt_request":
        rp=sql_root/ledger["calls"][6]["receipt"];r=sqlsupport.read(rp);r["request"]["temperature"]=.123;write(rp,r)
    write(lp,ledger);write(sp,state)
    with pytest.raises(ValueError):snapshot(sql_root)

def test_snapshot_rejects_missing_unique_index(sql_root):
    with sqlite3.connect(sql_root/"TASKS.sqlite3") as c:
        c.execute("ALTER TABLE attempts RENAME TO attempts_old")
        c.execute("CREATE TABLE attempts(claim_id TEXT PRIMARY KEY,graph_id TEXT,node_id TEXT,revision INTEGER,request_sha TEXT,status TEXT,result_sha TEXT,created TEXT)")
        c.execute("INSERT INTO attempts SELECT * FROM attempts_old")
        c.execute("DROP TABLE attempts_old")
    with pytest.raises(ValueError,match="duplicate SQL boundary"):snapshot(sql_root)

def test_snapshot_rejects_failed_graph_attempt_even_if_current_count_check_disabled(sql_root):
    gid=snapshot(sql_root)["graph"]["graph_id"]
    with sqlite3.connect(sql_root/"TASKS.sqlite3") as c:
        c.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",("unexpected",gid,"result",1,"d"*64,"claimed",None,"later"))
    with pytest.raises(ValueError,match="duplicate SQL boundary"):snapshot(sql_root,exact=False)

# New-entry fixtures isolate freeze/claim/routing tests from the already verified SDK and SQL adapters.
from types import SimpleNamespace
import os
import sys
from datetime import datetime,timezone
from scripts import run_fresh_legal_known_draft_continuation_v2 as entry
REAL_INPUTS=old.inputs
REAL_COMPACT_CONTEXT=entry.compact.compact_context
REAL_COMPACT_PAYLOAD=entry.compact.compact_payload
REAL_PROJECTION_EVIDENCE=entry.compact.payload_projection_evidence

@pytest.fixture
def stopped_v2(monkeypatch,tmp_path):
    root=tmp_path/"entry_root";root.mkdir();directory=root/entry.OPERATOR_DIR;prior=root/old.OPERATOR_DIR
    monkeypatch.setattr(entry,"location",lambda value:(root,directory))
    monkeypatch.setattr(old,"verify_operator",lambda root:{})
    monkeypatch.setattr(old.extension,"previous_worker_instance_active",lambda claim:False)
    monkeypatch.setattr(old.extension,"execution_resource_symbols",lambda:{"allowed_python_executables":[str(Path(sys._base_executable).resolve())]})
    spend={"calls_started":520,"reported_tokens":7964215,"calls_with_known_usage":518,"unknown_token_reservations":93117,"pending_ordinals":[70,160],"parent_ledger_sha256":"a"*64}
    ledger={"schema":"fixture","starting_spend":spend,"max_total_tokens":None,"authorization_sha256":"b"*64,
        "source_manifest":{"original.py":"c"*64},"model_configs":{},"calls":[],"automatic_retry":False,"old_budget_reset":False,"old_governance_migrated":False}
    realdigest=entry.control.digest
    monkeypatch.setattr(entry.control,"digest",lambda v:entry.SOURCE_BINDING if v==ledger["source_manifest"] else realdigest(v))
    receipts=[];events=[]
    labels=["fresh_theme_01","fresh_theme_02","fresh_plan_01","fresh_plan_02","fresh_plan_02_format_recovery","fresh_draft_01","fresh_draft_02"]
    for ordinal,label in zip(entry.PREFIX_ORDINALS,labels):
        phase="theme" if ordinal<523 else "plan" if ordinal<526 else "draft"
        request={"model":"MiniMax-M3","role":"writer","input_provenance":{"phase":phase},"messages":[{"role":"system","content":"fixture"},{"role":"user","content":json.dumps({"source_packet":{},"verified_legal_context":{},"reference_fulltext":"R01","expression_standards":{},"production_preferences":{}})}]}
        r={"ordinal":ordinal,"label":label,"request":request,"request_sha256":entry.control.digest(request),"source_binding_sha256":entry.SOURCE_BINDING,
            "status":"contract_valid" if ordinal in (522,525) else "contract_rejected","output":{"immutable_complete_document":ordinal},
            "response_metadata":{"http_status_code":200,"response_body_complete":True,"finish_reason":"tool_calls","total_tokens":ordinal}}
        name=f"call_{ordinal}_{label}.json";write(root/name,r);receipts.append(r)
        ledger["calls"].append({"ordinal":ordinal,"label":label,"receipt":name,"token_reservation":1000,"receipt_sha256":entry.control.sha_file(root/name)})
        events.extend([{"event":"claim","phase":phase,"label":label,"request_sha256":r["request_sha256"],"source_binding_sha256":entry.SOURCE_BINDING},
            {"event":"result","phase":phase,"label":label,"receipt_ordinal":ordinal,"receipt_sha256":entry.control.digest(r)}])
        for name in ("IDENTITY.json","REQUEST_BODY_MANIFEST.json","CAPABILITY_PREFLIGHT.json","RESPONSE_BODY_MANIFEST.json","request_body.raw","response_body.raw"):
            write(root/"call_evidence"/f"call_{ordinal:03}"/name,{"fixture":ordinal})
    events.append({"event":"claim","phase":"draft","label":"fresh_draft_03","request_sha256":receipts[-1]["request_sha256"],"source_binding_sha256":entry.SOURCE_BINDING})
    stopped={"status":"halt_execution_unknown","failure":{"type":"TaskStoreError","redispatch_allowed":False},"source_binding_sha256":entry.SOURCE_BINDING,
        "versions":{"theme":2,"plan":2,"draft":3},"limits":{"theme":3,"plan":3,"draft":3},"receipts":receipts,"events":events,"brief":{},"format_recovery_claims":{"plan":{"consumed":True}}}
    write(root/"CALL_LEDGER.json",ledger);write(root/"USER_SCOPE.json",{"native_limit":3,"format_limit":1})
    for name,value in ((old.FREEZE,{}),(old.CLAIM,{"pid":999999}),("STATE.json",{"status":"halt_execution_unknown"}),("TEXT_STATE.json",stopped),("TEXT_RESULT.json",stopped)):
        write(prior/name,value)
    sql=old.control.read(QA/"COMPACT_DRAFT03_TASKSTORE_READONLY_SNAPSHOT_01.json")
    sql["logical_request_sha256"]=receipts[-1]["request_sha256"]
    sql["wrapped_request_sha256"]=entry.control.digest({"provider_id":receipts[-1]["request"]["model"],"payload":receipts[-1]["request"]})
    write(tmp_path/"sql.json",sql);monkeypatch.setattr(entry,"SQL_EVIDENCE",tmp_path/"sql.json")
    recon={"classification":"known_local_pre_dispatch_duplicate_request","failure_code":"DUPLICATE_DISPATCH","draft03_sql_attempts_count":0,
        "runtime_528_dispatch_started":False,"production_records_modified":False}
    write(tmp_path/"recon.json",recon);monkeypatch.setattr(entry,"RECONCILIATION",tmp_path/"recon.json")
    sql_calls=[]
    def read_sql(root,**kwargs):sql_calls.append(kwargs);return deepcopy(sql)
    monkeypatch.setattr(entry,"evidence_module",lambda:SimpleNamespace(readonly_original_draft_sql_snapshot=read_sql))
    def check(ledger):
        for row in ledger["calls"]:
            path=root/row["receipt"]
            if not path.exists() or row.get("receipt_sha256")!=entry.control.sha_file(path):
                raise ValueError("fixture receipt hash changed")
    rt=SimpleNamespace(ledger=root/"CALL_LEDGER.json",check=check,evidence_path=lambda ordinal:root/"call_evidence"/f"call_{ordinal:03}")
    monkeypatch.setattr(old,"original_runtime",lambda *a,**k:rt)
    sdk_calls=[]
    monkeypatch.setattr(old,"verified_sdk_evidence",lambda rt,r,q:sdk_calls.append(r["ordinal"]))
    monkeypatch.setattr(old,"verify_known_task_history",lambda *a:None)
    monkeypatch.setattr(old,"inputs",lambda root:{"provider_evidence":{},"packet":{},"legal_context":{},"reference_fulltext":"R01","expression_standards":{},"production_preferences":{},"source_binding_sha256":entry.SOURCE_BINDING})
    monkeypatch.setattr(entry.compact,"compact_context",lambda **kw:{"fixture_context":True})
    monkeypatch.setattr(entry.compact,"compact_payload",lambda p,*a,**kw:deepcopy(p))
    monkeypatch.setattr(entry.compact,"payload_projection_evidence",lambda *a,**kw:{"fixture_projection":True})
    monkeypatch.setattr(entry.candidate,"dialogue_window_diagnostics",lambda *a:{"violations":[{"source_ref":"B1.01"}],"fixture":True})
    return SimpleNamespace(root=root,directory=directory,prior=prior,ledger=ledger,stopped=stopped,receipts=receipts,sql=sql,runtime=rt,sdk_calls=sdk_calls,sql_calls=sql_calls)

def freeze_v2(s):return entry.prepare(s.root)

def test_v2_prepare_binds_same_spend_raw_ledger_and_draft3(stopped_v2):
    s=stopped_v2;before={p:p.read_bytes() for p in s.root.rglob("*") if p.is_file()}
    freeze=freeze_v2(s)
    assert all(p.read_bytes()==b for p,b in before.items())
    assert (s.directory/"ORIGINAL_LEDGER_SNAPSHOT.json").read_bytes()==(s.root/"CALL_LEDGER.json").read_bytes()
    assert freeze["original_versions"]=={"theme":2,"plan":2,"draft":3} and freeze["additional_native_draft_capacity"]==0
    assert freeze["unsubmitted_native_draft_slot"]==3 and freeze["draft_format_recovery_maximum"]==1
    assert freeze["original_source_manifest"]==s.ledger["source_manifest"] and freeze["original_ledger_static"]["starting_spend"]==s.ledger["starting_spend"]
    assert not (s.directory/entry.CLAIM).exists() and s.sdk_calls==list(range(521,528))*2
    assert any(c["require_exact_attempt_count"] for c in s.sql_calls)

@pytest.mark.parametrize("mutation",["source","prefix","spend","old_result","active_worker","sql_evidence","reconciliation","unknown_usage"])
def test_v2_prepare_preflight_failure_has_no_operator_or_dispatch(stopped_v2,monkeypatch,mutation):
    s=stopped_v2
    if mutation in ("source","prefix","spend"):
        d=deepcopy(s.ledger)
        if mutation=="source":d["source_manifest"]={"replacement.py":"e"*64}
        if mutation=="prefix":d["calls"][0]["receipt_sha256"]="f"*64
        if mutation=="spend":d["starting_spend"]["reported_tokens"]=0
        write(s.root/"CALL_LEDGER.json",d)
    elif mutation=="old_result":write(s.prior/"TEXT_RESULT.json",{})
    elif mutation=="active_worker":monkeypatch.setattr(old.extension,"previous_worker_instance_active",lambda c:True)
    elif mutation=="sql_evidence":write(entry.SQL_EVIDENCE,{})
    elif mutation=="reconciliation":write(entry.RECONCILIATION,{})
    else:
        r=deepcopy(s.receipts[-1]);r["response_metadata"]["total_tokens"]=None
        write(s.root/s.ledger["calls"][-1]["receipt"],r)
        state=deepcopy(s.stopped);state["receipts"][-1]=r
        for p in ("TEXT_STATE.json","TEXT_RESULT.json"):write(s.prior/p,state)
    with pytest.raises((ValueError,RuntimeError)):entry.prepare(s.root)
    assert not s.directory.exists()

@pytest.mark.parametrize("member",list(entry.OPERATOR_FILES)+["TEXT_STATE.json","TEXT_RESULT.json","ORIGINAL_LEDGER_SNAPSHOT.json","LOCAL_FAILURE_PROOF.json","DIALOGUE_WINDOW_DIAGNOSTICS.json","request_body.raw","response_body.raw"])
def test_v2_missing_required_freeze_member_is_rejected(stopped_v2,member):
    s=stopped_v2;f=freeze_v2(s)
    names=[p for p in f["files"] if p.replace("\\","/").endswith(member)];assert names
    for p in names:f["files"].pop(p)
    write(s.directory/entry.FREEZE,f)
    with pytest.raises(ValueError):entry.verify_operator(s.root)

@pytest.mark.parametrize("key,value",[("original_versions",{"theme":2,"plan":2,"draft":2}),("original_limits",{"theme":3,"plan":3,"draft":4}),
    ("unsubmitted_native_draft_slot",4),("unsubmitted_native_draft_slot",True),("additional_native_draft_capacity",1),
    ("draft_format_recovery_maximum",2),("new_media_calls",1),("automatic_restart",True),("old_budget_reset",True),
    ("external_resource_hashes",{}),("original_calls_prefix",[]),("original_source_manifest",{})])
def test_v2_freeze_capacity_or_resource_tamper_rejected(stopped_v2,key,value):
    s=stopped_v2;f=freeze_v2(s);f[key]=value;write(s.directory/entry.FREEZE,f)
    with pytest.raises(ValueError):entry.verify_operator(s.root)

@pytest.mark.parametrize("field,value",[("code","RESULT_UNKNOWN"),("sql_attempt_count",1),("provider_dispatch_started",True),("ledger_sha256","a"*64),
    ("stop_state_sha256","a"*64),("taskstore_evidence_sha256","a"*64),("result527_sha256","a"*64),("request_sha256","a"*64)])
def test_v2_proof_is_recomputed_even_when_file_hash_updated(stopped_v2,field,value):
    s=stopped_v2;f=freeze_v2(s);p=s.directory/"LOCAL_FAILURE_PROOF.json";proof=entry.control.read(p);proof[field]=value;write(p,proof)
    f["files"][str(p.resolve())]=entry.control.sha_file(p);write(s.directory/entry.FREEZE,f)
    with pytest.raises(ValueError):entry.verify_operator(s.root)

def test_v2_live_guard_allows_current_ledger_append_but_keeps_old_prefix(stopped_v2):
    s=stopped_v2;f=freeze_v2(s);ledger=deepcopy(s.ledger)
    r=deepcopy(s.receipts[-1]);r.update(ordinal=528,label="fresh_draft_03_known_local_revision")
    write(s.root/"new.json",r)
    ledger["calls"].append({"ordinal":528,"label":r["label"],"receipt":"new.json","receipt_sha256":entry.control.sha_file(s.root/"new.json")})
    write(s.root/"CALL_LEDGER.json",ledger)
    assert entry.verify_operator(s.root)==f
    assert s.sql_calls[-1]["require_exact_attempt_count"] is False
    with pytest.raises(ValueError):entry.inspect_local_stop(s.root,preparation=True)

def test_v2_claim_consumed_does_not_prepare_or_overwrite(stopped_v2):
    s=stopped_v2;write(s.directory/entry.CLAIM,{"consumed":True});write(s.directory/"STATE.json",{"winner":True})
    before=(s.directory/"STATE.json").read_bytes()
    with pytest.raises(entry.ContinuationAlreadyClaimed):entry.prepare(s.root)
    with pytest.raises(entry.ContinuationAlreadyClaimed):entry.run(s.root)
    assert (s.directory/"STATE.json").read_bytes()==before

def test_v2_run_claim_race_preserves_winner_state(stopped_v2,monkeypatch):
    s=stopped_v2;freeze_v2(s);realopen=Path.open
    def raced(path,*args,**kw):
        if path==s.directory/entry.CLAIM and args and args[0]=="x":
            write(s.directory/"STATE.json",{"winning_worker":True});raise FileExistsError("raced")
        return realopen(path,*args,**kw)
    monkeypatch.setattr(Path,"open",raced)
    with pytest.raises(entry.ContinuationAlreadyClaimed):entry.run(s.root)
    assert entry.control.read(s.directory/"STATE.json")=={"winning_worker":True}

@pytest.fixture
def worker_v2(stopped_v2,monkeypatch):
    import psutil
    s=stopped_v2;f=freeze_v2(s);now=datetime.now(timezone.utc).timestamp()
    claim={"schema":entry.VERSION+"/claim","pid":os.getpid(),"started_at_utc":datetime.fromtimestamp(now,timezone.utc).isoformat(),
        "operator_freeze_sha256":entry.control.sha_file(s.directory/entry.FREEZE),"source_binding_sha256":entry.SOURCE_BINDING,"automatic_restart":False,"old_budget_reset":False}
    write(s.directory/entry.CLAIM,claim)
    p=SimpleNamespace(is_running=lambda:True,exe=lambda:sys._base_executable,cmdline=lambda:[sys._base_executable,str(PROJECT/entry.OPERATOR_FILES[0])],create_time=lambda:now-.1)
    monkeypatch.setattr(psutil,"Process",lambda pid:p)
    return s,f,p,claim

def test_v2_current_worker_binding_accepts_exact_instance(worker_v2):
    s,f,p,c=worker_v2;entry.verify_worker(s.root,f)

@pytest.mark.parametrize("bad",["pid","freeze","source","restart","exe","entry","future_create","stale_create","dead"])
def test_v2_worker_wrong_instance_stops(worker_v2,bad):
    s,f,p,c=worker_v2
    if bad=="pid":c["pid"]+=1
    if bad=="freeze":c["operator_freeze_sha256"]="b"*64
    if bad=="source":c["source_binding_sha256"]="b"*64
    if bad=="restart":c["automatic_restart"]=True
    if bad=="exe":p.exe=lambda:str(PROJECT/"wrong-python.exe")
    if bad=="entry":p.cmdline=lambda:[sys._base_executable,"wrong_worker.py"]
    if bad=="future_create":p.create_time=lambda:datetime.fromisoformat(c["started_at_utc"]).timestamp()+.1
    if bad=="stale_create":p.create_time=lambda:datetime.fromisoformat(c["started_at_utc"]).timestamp()-301
    if bad=="dead":p.is_running=lambda:False
    write(s.directory/entry.CLAIM,c)
    with pytest.raises(ValueError):entry.verify_worker(s.root,f)


def invoke_ready(s,monkeypatch):
    s.directory.mkdir(exist_ok=True)
    calls=[]
    s.runtime.inherited_guard=lambda:None
    def forbidden_dispatch(*args):calls.append(args);raise AssertionError("dispatch should not occur")
    s.runtime.dispatch=forbidden_dispatch
    monkeypatch.setattr(entry.original.clients,"expected_wire_request",lambda q:deepcopy(q))
    monkeypatch.setattr(entry.original.clients,"CapabilityRoleClients",lambda **kw:(_ for _ in ()).throw(AssertionError("SDK construction forbidden")))
    return calls

def insert_prior_duplicate_request(s,request):
    store=entry.original.task_store.TaskStore(s.root/"TASKS.sqlite3")
    gid="offline-original-request"
    graph={"schema_version":entry.original.task_store.GRAPH_SCHEMA,"graph_id":gid,"nodes":[
        {"node_id":"source","kind":"source","input":{"frozen_source_sha256":entry.SOURCE_BINDING,"request_sha256":entry.control.digest(request)},"depends_on":[]},
        {"node_id":"result","kind":"text","input":{"label":"offline-prior","phase":"draft"},"depends_on":["source"]}]}
    store.register_graph(graph)
    auth={"schema_version":entry.original.task_store.AUTH_SCHEMA,"authorization_id":gid+":scope","graph_id":gid,"node_ids":["result"],"scope":"text","purpose":"dispatch",
        "source_sha256":store.snapshot(gid)["source_sha256"],"max_attempts":4,"prior_attempts":0,"allows_content_revision":False,
        "evidence_ref":str(s.root/"USER_SCOPE.json")+"#draft","evidence_sha256":entry.control.sha_file(s.root/"USER_SCOPE.json")}
    return store.claim(gid,"result",{"provider_id":request["model"],"payload":request},auth)

def test_v2_actual_claim_duplicate_is_known_local_before_sdk(stopped_v2,monkeypatch):
    s=stopped_v2;calls=invoke_ready(s,monkeypatch);q=deepcopy(s.receipts[-1]["request"])
    insert_prior_duplicate_request(s,q)
    before=(s.root/"CALL_LEDGER.json").read_bytes()
    invoke=entry.make_invoke(s.root,s.runtime,s.directory/"TEXT_RESULT.json")
    with pytest.raises(entry.candidate.KnownLocalDispatchError) as ex:invoke("fresh_draft_03_known_local_revision",q,lambda v:v)
    assert ex.value.code=="DUPLICATE_DISPATCH" and ex.value.detail["sql_attempt_count"]==0 and ex.value.detail["provider_dispatch_started"] is False
    assert not calls and (s.root/"CALL_LEDGER.json").read_bytes()==before
    proof=entry.control.read(s.directory/"fresh_draft_03_known_local_revision_LOCAL_STOP.json")
    assert proof["request_sha256"]==entry.control.digest(q)
    with sqlite3.connect(s.root/"TASKS.sqlite3") as c:
        assert c.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM attempts WHERE graph_id=?",(proof["graph_id"],)).fetchone()[0]==0
    assert not (s.root/"call_evidence/call_528").exists()

@pytest.mark.parametrize("error_mode",["different_code","ledger_changed","attempt_inserted"])
def test_v2_unproven_taskstore_failure_remains_generic(stopped_v2,monkeypatch,error_mode):
    s=stopped_v2;calls=invoke_ready(s,monkeypatch);realstore=entry.original.task_store.TaskStore
    class Faulty(realstore):
        def claim(self,*args,**kw):
            if error_mode=="attempt_inserted":super().claim(*args,**kw)
            if error_mode=="ledger_changed":
                value=entry.control.read(s.runtime.ledger);value["fixture_changed"]=True;write(s.runtime.ledger,value)
            raise entry.original.task_store.TaskStoreError("OTHER_UNKNOWN" if error_mode=="different_code" else "DUPLICATE_DISPATCH","offline injected error")
    monkeypatch.setattr(entry.original.task_store,"TaskStore",Faulty)
    invoke=entry.make_invoke(s.root,s.runtime,s.directory/"TEXT_RESULT.json")
    with pytest.raises(entry.original.task_store.TaskStoreError):invoke("fresh_draft_03_known_local_revision",deepcopy(s.receipts[-1]["request"]),lambda v:v)
    assert not calls and not list(s.directory.glob("*_LOCAL_STOP.json"))

def test_v2_guard_failure_occurs_before_claim_or_sdk(stopped_v2,monkeypatch):
    s=stopped_v2;calls=invoke_ready(s,monkeypatch)
    s.runtime.inherited_guard=lambda:(_ for _ in ()).throw(ValueError("frozen guard failed"))
    invoke=entry.make_invoke(s.root,s.runtime,s.directory/"TEXT_RESULT.json")
    with pytest.raises(ValueError,match="frozen guard failed"):invoke("fresh_draft_03_known_local_revision",s.receipts[-1]["request"],lambda v:v)
    with sqlite3.connect(s.root/"TASKS.sqlite3") as c:assert c.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]==0
    assert not calls and not list(s.directory.glob("*_LOCAL_STOP.json"))

def test_v2_error_after_claim_is_not_reclassified_local(stopped_v2,monkeypatch):
    s=stopped_v2;calls=invoke_ready(s,monkeypatch)
    def dispatched(*args):calls.append(args);raise entry.original.task_store.TaskStoreError("DUPLICATE_DISPATCH","offline postclaim failure")
    s.runtime.dispatch=dispatched
    invoke=entry.make_invoke(s.root,s.runtime,s.directory/"TEXT_RESULT.json")
    with pytest.raises(entry.original.task_store.TaskStoreError):invoke("fresh_draft_03_known_local_revision",s.receipts[-1]["request"],lambda v:v)
    assert len(calls)==1 and not list(s.directory.glob("*_LOCAL_STOP.json"))
    with sqlite3.connect(s.root/"TASKS.sqlite3") as c:assert c.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]==1

def test_v2_performance_stage_reads_explicit_new_result(stopped_v2,monkeypatch):
    s=stopped_v2;new=s.directory/"TEXT_RESULT.json";write(new,{"status":"text_ready_for_director","script":{"new":True}})
    write(s.root/"TEXT_RESULT.json",{"status":"halt_required_tool_missing","script":{"old":True}})
    checked=[];seen=[]
    monkeypatch.setattr(old,"verify_accepted_text_binding",lambda d:checked.append(d))
    monkeypatch.setattr(entry.original.parent.old.source,"catalog",lambda script:seen.append(script) or {"a":{},"b":{}})
    assert old.stage("performance_B1",new)==("performance",18)
    assert checked==[s.directory] and seen==[{"new":True}]

def test_v2_production_tail_binds_new_script_and_full_new_guard(stopped_v2,monkeypatch):
    s=stopped_v2;s.directory.mkdir();guards=[];seen={}
    s.runtime.inherited_guard=lambda:guards.append("new+old+worker+accepted")
    monkeypatch.setattr(old,"verify_accepted_text_binding",lambda d:seen.setdefault("accepted_dir",d))
    monkeypatch.setattr(entry.original.text_pipeline,"render_script",lambda script,brief:"offline full new script")
    monkeypatch.setattr(entry.original.revisions,"initial_loop_state",lambda *args,**kw:seen.setdefault("scope_material",kw["stable_scope_material"]) or {})
    monkeypatch.setattr(entry.original,"spend_summary",lambda rt:{"known_fixture":True})
    monkeypatch.setattr(entry.original.shared,"compile_segment_context",lambda *args,**kw:seen.setdefault("opening",args) or {})
    class Coordinator:
        def __init__(self,**kwargs):seen["coordinator"]=kwargs;kwargs["verify_frozen_source"]()
        def run(self,**kwargs):
            seen["run"]=kwargs;seen["coordinator"]["opening_context_builder"]({"source_refs":["NEWREF"]})
            return {"status":"complete_text_production_handoff_ready","complete_text_handoff_ready":True,"direction":{"segments":[{"segment_id":"S001"}]},"planned_prompts":["offline prompt"]}
    monkeypatch.setattr(entry.original.directors,"EndpointFeedbackCoordinator",Coordinator)
    result={"script":{"title":"new adopted by machine only"},"brief":{},"manifest":{"new_manifest":True},"initial":{"new_initial":True},
        "shared_dynamic_initial":{"new_dynamic":True},"source_review_binding":{"new_same_source_binding":True}}
    entry.production_tail(s.root,s.directory,s.runtime,lambda *args:None,result)
    assert seen["accepted_dir"]==s.directory and guards==["new+old+worker+accepted"]
    assert seen["run"]["script"] is result["script"] and seen["run"]["source_review_binding"] is result["source_review_binding"]
    assert seen["opening"]== (result["manifest"],result["script"],result["shared_dynamic_initial"],["NEWREF"])
    state=entry.control.read(s.directory/"STATE.json")
    assert state["schema"]==entry.VERSION+"/state" and state["new_media_calls"]==0 and state["creative_quality_passed"] is False
    assert (s.directory/"DELIVERABLE/FULL_SCRIPT.md").exists() and not (s.root/"DELIVERABLE").exists()


@pytest.fixture
def actual_known_compact_payload():
    root=entry.original.DEFAULT_ROOT
    ledger=entry.control.read(root/"CALL_LEDGER.json")
    receipt=entry.control.read(root/next(r["receipt"] for r in ledger["calls"] if r["ordinal"]==527))
    payload=entry.control.strict_json(receipt["request"]["messages"][1]["content"])
    return deepcopy(payload),REAL_INPUTS(root)

def test_actual_527_known_compact_projection_replay_preserves_every_field(actual_known_compact_payload):
    payload,values=actual_known_compact_payload
    before=deepcopy(payload);inputs=deepcopy(values)
    proof=entry.projection_from_known_compact_payload(payload,values,expected_old_payload_sha256=entry.control.digest(payload))
    assert payload==before and values==inputs
    assert payload["source_packet"]["schema"]==entry.compact.VERSION+"/source_packet"
    assert proof["projected_payload_semantic_sha256"]==entry.control.digest(payload)
    assert proof["native_documents_preserved_completely"] and proof["complete_original_packet_validated"]
    assert proof["fixed_component_key_occurrences"]=={"reference_fulltext":1,"verified_legal_context":1,"expression_standards":1}
    assert proof["model_calls"]==proof["media_calls"]==proof["collection_calls"]==0

@pytest.mark.parametrize("change",["binding","candidate","metadata","reference","standards","legal_facts","preferences","brief","previous_document","revision_targets","full_source"])
def test_actual_527_projection_rejects_source_or_fixed_context_mutation(actual_known_compact_payload,change):
    payload,values=actual_known_compact_payload
    expected=entry.control.digest(payload)
    if change=="binding":payload["source_packet"]["source_identity"]["source_binding_sha256"]="a"*64
    if change=="candidate":payload["source_packet"]["candidate"]["candidate_id"]="changed"
    if change=="metadata":payload["source_packet"]["representative_metadata"][0]["title"]="changed"
    if change=="reference":payload["reference_fulltext"]+="changed"
    if change=="standards":payload["expression_standards"]={"criteria":["changed"]}
    if change=="legal_facts":payload["verified_legal_context"]["facts"].append({"changed":True})
    if change=="preferences":payload["production_preferences"]["max_characters"]=3
    if change=="brief":payload["brief"]["fixture_changed"]=True
    if change=="previous_document":payload["previous_complete_document"]["title"]="changed"
    if change=="revision_targets":payload["revision_requirements"]=[{"target":"changed"}]
    if change=="full_source":values["packet"]["source_sha256"]="a"*64
    with pytest.raises(ValueError):entry.projection_from_known_compact_payload(payload,values,expected_old_payload_sha256=expected)

def test_prepare_actual_527_compact_source_path_is_projected_once_in_qa(stopped_v2,actual_known_compact_payload,monkeypatch):
    s=stopped_v2;payload,values=actual_known_compact_payload
    monkeypatch.setattr(entry.compact,"compact_context",REAL_COMPACT_CONTEXT)
    monkeypatch.setattr(entry.compact,"compact_payload",REAL_COMPACT_PAYLOAD)
    monkeypatch.setattr(entry.compact,"payload_projection_evidence",REAL_PROJECTION_EVIDENCE)
    monkeypatch.setattr(old,"inputs",lambda root:deepcopy(values))
    r=s.receipts[-1];r["request"]["messages"][1]["content"]=json.dumps(payload,ensure_ascii=False)
    r["request_sha256"]=entry.control.digest(r["request"])
    row=s.ledger["calls"][-1];write(s.root/row["receipt"],r);row["receipt_sha256"]=entry.control.sha_file(s.root/row["receipt"])
    s.stopped["events"][-1]["request_sha256"]=r["request_sha256"]
    s.sql["logical_request_sha256"]=r["request_sha256"]
    s.sql["wrapped_request_sha256"]=entry.control.digest({"provider_id":r["request"]["model"],"payload":r["request"]})
    write(entry.SQL_EVIDENCE,s.sql);write(s.root/"CALL_LEDGER.json",s.ledger)
    for name in ("TEXT_STATE.json","TEXT_RESULT.json"):write(s.prior/name,s.stopped)
    before=(s.root/"CALL_LEDGER.json").read_bytes()
    freeze=entry.prepare(s.root)
    projection=entry.control.read(s.directory/"PROJECTION_EVIDENCE.json")
    assert projection["projected_payload_semantic_sha256"]==entry.control.digest(payload)
    assert projection["native_documents_preserved_completely"] and freeze["original_versions"]["draft"]==3
    assert (s.root/"CALL_LEDGER.json").read_bytes()==before and not (s.directory/entry.CLAIM).exists()


@pytest.mark.parametrize("field",["reference_fulltext","verified_legal_context","expression_standards","production_preferences"])
def test_actual_known_projection_rejects_context_difference_even_with_matching_payload_sha(actual_known_compact_payload,field):
    payload,values=actual_known_compact_payload
    if field=="reference_fulltext":payload[field]+="changed"
    elif field=="production_preferences":payload[field]["max_characters"]=3
    elif field=="expression_standards":payload[field]["criteria"].append({"changed":True})
    else:payload[field]["facts"].append({"changed":True})
    # A caller-supplied digest alone cannot substitute altered fixed context for original inputs.
    with pytest.raises(ValueError):entry.projection_from_known_compact_payload(payload,values,expected_old_payload_sha256=entry.control.digest(payload))
