"""Offline state/SQLite fault tests; never import or invoke a service client."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

from src.content_factory.creative_studio_task_store_v1 import TaskStore, TaskStoreError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in task store tests")
    monkeypatch.setattr(socket,"socket",denied)
    monkeypatch.setattr(socket,"create_connection",denied)


def graph():
    return {"schema_version":"creative_studio_dag/v1","graph_id":"test-graph","nodes":[
        {"node_id":"script","kind":"source","input":{"native_script":"完整剧本","source_receipt":"offline-fixture"},"depends_on":[]},
        {"node_id":"director","kind":"text","input":{"stage":"whole_direction"},"depends_on":["script"]},
        {"node_id":"compile","kind":"compile","input":{"stage":"deterministic_compile"},"depends_on":["director"]},
        {"node_id":"video","kind":"media","input":{"stage":"single_video"},"depends_on":["compile"]},
        {"node_id":"downstream","kind":"text","input":{"stage":"after_video"},"depends_on":["video"]},
        {"node_id":"unrelated","kind":"text","input":{"stage":"independent"},"depends_on":["script"]},
    ],"provenance":{"fixture_only":True,"legacy_used":7,"legacy_maximum":7,"production_permission":False}}


@pytest.fixture
def store(tmp_path):
    value=TaskStore(tmp_path/"studio.sqlite3")
    value.register_graph(graph())
    return value


def auth(store, node="director", *, purpose="dispatch", cap=3, prior=0, revision=False, auth_id=None):
    kind={n["node_id"]:n["kind"] for n in store.snapshot("test-graph")["nodes"]}[node]
    scope={"source":"source","text":"text","review":"text","media":"media","compile":"offline"}[kind]
    return {"schema_version":"creative_studio_authorization/v1","authorization_id":auth_id or node+"-"+purpose,"graph_id":"test-graph","node_ids":[node],"scope":scope,"purpose":purpose,"source_sha256":store.snapshot("test-graph")["source_sha256"],"max_attempts":cap,"prior_attempts":prior,"allows_content_revision":revision,"evidence_ref":"explicit-offline-test-only","evidence_sha256":"a"*64}


def request(node="director", version=1):
    return {"provider_id":"local_compiler" if node=="compile" else "mock_provider","payload":{"node":node,"version":version}}


def raw(body="原始服务回执\r\n", status=200, binary=False):
    data=body if isinstance(body,bytes) else body.encode("utf-8")
    return {"encoding":"base64" if binary else "utf-8","body":base64.b64encode(data).decode("ascii") if binary else data.decode("utf-8"),"sha256":hashlib.sha256(data).hexdigest(),"http_status":status}


def result(attempt, *, outcome="completed", usage_known=True, result_known=True, task_id=None, output=None):
    local=attempt["provider_id"]=="local_compiler"
    return {"schema_version":"creative_studio_result/v1","claim_id":attempt["claim_id"],"request_sha256":attempt["request_sha256"],"service_task_id":task_id if task_id is not None else attempt["service_task_id"],"outcome":outcome,"result_known":result_known,"usage_known":usage_known,"usage":({"unit":"provider_units","amount":0} if local else {"unit":"reported_tokens","amount":17}) if usage_known else None,"complete":True,"complete_end":True,"schema_tool_status":"not_applicable" if local or attempt["node_id"]=="video" else "accepted","contract_valid":False if outcome=="content_rejected" else True,"raw_receipt":raw(status=None if local else 200),"output":{"native":"完整原生版本"} if output is None else output}


def claim(store,node="director",**kwargs):
    return store.claim("test-graph",node,request(node),auth(store,node,**kwargs),expected_revision=1)


def complete(store,node="director"):
    attempt=claim(store,node)
    return store.accept_result(attempt["claim_id"],result(attempt))


def statuses(store):
    return {n["node_id"]:n["status"] for n in store.snapshot("test-graph")["nodes"]}


def test_graph_replay_is_frozen_and_detached(store):
    initial=store.snapshot("test-graph")
    assert store.register_graph(graph())==initial
    changed=graph(); changed["nodes"][0]["input"]["native_script"]="changed"
    with pytest.raises(TaskStoreError,match="immutable"):
        store.register_graph(changed)
    initial["nodes"][0]["input"]["external"]="mutate"
    assert all("external" not in n["input"] for n in store.snapshot("test-graph")["nodes"])


@pytest.mark.parametrize("change",["duplicate","cycle","missing","source_dep","kind_type","extra"])
def test_graph_rejects_invalid_contract(tmp_path,change):
    value=graph()
    if change=="duplicate": value["nodes"].append(deepcopy(value["nodes"][0]))
    if change=="cycle": value["nodes"][1]["depends_on"]=["compile"]
    if change=="missing": value["nodes"][1]["depends_on"]=["not_there"]
    if change=="source_dep": value["nodes"][0]["depends_on"]=["director"]
    if change=="kind_type": value["nodes"][1]["kind"]=[]
    if change=="extra": value["nodes"][1]["status"]="passed"
    with pytest.raises(TaskStoreError): TaskStore(tmp_path/"invalid.sqlite3").register_graph(value)


def test_foreign_database_not_modified(tmp_path):
    path=tmp_path/"old.sqlite3"
    with sqlite3.connect(path) as con: con.execute("CREATE TABLE old_ledger (tokens INTEGER)"); con.execute("INSERT INTO old_ledger VALUES (7964215)")
    before=path.read_bytes()
    with pytest.raises(TaskStoreError) as exc: TaskStore(path)
    assert exc.value.code=="FOREIGN_DATABASE" and path.read_bytes()==before


@pytest.mark.parametrize("field,value",[("max_attempts",True),("max_attempts","3"),("prior_attempts",-1),("allows_content_revision","true"),("source_sha256","b"*64),("scope",["text"]),("purpose","anything"),("evidence_sha256","none")])
def test_strict_authorization_and_source(store,field,value):
    grant=auth(store); grant[field]=value
    with pytest.raises(TaskStoreError): store.claim("test-graph","director",request(),grant)
    assert not store.snapshot("test-graph")["attempts"]


def test_inherited_zero_capacity_is_not_reset(store):
    grant=auth(store,cap=7,prior=7)
    assert store.register_authorization(grant)["remaining_attempts"]==0
    with pytest.raises(TaskStoreError) as exc: store.claim("test-graph","director",request(),grant)
    assert exc.value.code=="AUTHORIZATION_EXHAUSTED"
    restart=TaskStore(store.db_path)
    altered=deepcopy(grant); altered["prior_attempts"]=0
    with pytest.raises(TaskStoreError) as exc: restart.register_authorization(altered)
    assert exc.value.code=="AUTHORIZATION_IDENTITY_CONFLICT"
    assert restart.snapshot("test-graph")["authorizations"][0]["remaining_attempts"]==0


def test_claim_commits_before_send_and_cannot_repeat(store):
    attempt=claim(store)
    assert TaskStore(store.db_path).recover("test-graph")["actions"][0]["action"]=="stop_claim_unknown"
    for grant in (auth(store),auth(store,auth_id="new-does-not-reset")):
        with pytest.raises(TaskStoreError): store.claim("test-graph","director",request(),grant)
    assert len(store.snapshot("test-graph")["attempts"])==1


def test_grant_alias_cannot_reset_same_external_capacity(store):
    claim(store,cap=1)
    alias=auth(store,"unrelated",cap=1,auth_id="renamed-grant")
    with pytest.raises(TaskStoreError) as exc: store.claim("test-graph","unrelated",request("unrelated"),alias)
    assert exc.value.code=="AUTHORIZATION_EXHAUSTED"
    alias["max_attempts"]=99
    with pytest.raises(TaskStoreError) as exc: store.register_authorization(alias)
    assert exc.value.code=="AUTHORIZATION_SCOPE_BUDGET_CONFLICT"


def test_graph_alias_cannot_reset_same_external_capacity(store):
    claim(store,cap=1)
    second=graph(); second["graph_id"]="renamed-graph"
    store.register_graph(second)
    grant=auth(store,cap=1,auth_id="grant-in-second-directory")
    grant["graph_id"]="renamed-graph"
    with pytest.raises(TaskStoreError) as exc: store.claim("renamed-graph","director",request(version=999),grant)
    assert exc.value.code=="AUTHORIZATION_EXHAUSTED"
    assert not store.snapshot("renamed-graph")["attempts"]


def test_real_thread_race_has_one_claim(store):
    grant=auth(store)
    def worker(index):
        try: return TaskStore(store.db_path).claim("test-graph","director",request(),grant)["claim_id"]
        except TaskStoreError: return None
    with ThreadPoolExecutor(max_workers=12) as pool: results=list(pool.map(worker,range(12)))
    assert sum(r is not None for r in results)==1
    assert len(store.snapshot("test-graph")["attempts"])==1


WORKER="""
import json,os,socket,sys
socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden'))
from src.content_factory.creative_studio_task_store_v1 import TaskStore,TaskStoreError
db,fixture,mode=sys.argv[1:]
data=json.load(open(fixture,encoding='utf-8'))
def fault(stage):
    if stage=='after_claim_insert' and mode=='crash': os._exit(87)
store=TaskStore(db,fault_hook=fault)
try:
    a=store.claim('test-graph','director',data['request'],data['authorization'])
    if mode=='commit-crash': os._exit(88)
    print(json.dumps({'claim_id':a['claim_id']}))
except TaskStoreError as exc: print(json.dumps({'error':exc.code}))
"""


def child_fixture(store,tmp_path):
    path=tmp_path/"worker.json"
    path.write_text(json.dumps({"request":request(),"authorization":auth(store)}),encoding="utf-8")
    return path


def test_real_process_race_has_one_claim(store,tmp_path):
    path=child_fixture(store,tmp_path)
    processes=[subprocess.Popen([sys.executable,"-c",WORKER,str(store.db_path),str(path),"claim"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
    reports=[]
    for process in processes:
        stdout,stderr=process.communicate(timeout=30)
        assert process.returncode==0,stderr
        reports.append(json.loads(stdout))
    assert sum("claim_id" in r for r in reports)==1
    assert len(store.snapshot("test-graph")["attempts"])==1


def test_process_death_before_commit_rolls_back(store,tmp_path):
    path=child_fixture(store,tmp_path)
    child=subprocess.run([sys.executable,"-c",WORKER,str(store.db_path),str(path),"crash"],capture_output=True,timeout=30)
    assert child.returncode==87
    restart=TaskStore(store.db_path)
    assert not restart.snapshot("test-graph")["attempts"]
    assert statuses(restart)["director"]=="prepared"
    assert claim(restart)["attempt_index"]==1


def test_process_death_after_commit_never_reissues(store,tmp_path):
    path=child_fixture(store,tmp_path)
    child=subprocess.run([sys.executable,"-c",WORKER,str(store.db_path),str(path),"commit-crash"],capture_output=True,timeout=30)
    assert child.returncode==88
    restart=TaskStore(store.db_path)
    assert restart.recover("test-graph")["actions"][0]["may_dispatch_new_request"] is False
    with pytest.raises(TaskStoreError): claim(restart)
    assert restart.snapshot("test-graph")["authorizations"][0]["local_attempts"]==1


def test_original_id_recovery_and_submission_idempotency(store):
    attempt=claim(store); receipt=raw('原id回执')
    submitted=store.record_submission(attempt["claim_id"],"original-id",receipt)
    assert submitted["status"]=="submitted"
    assert store.record_submission(attempt["claim_id"],"original-id",receipt)==submitted
    store.mark_unknown(attempt["claim_id"],raw("GET timeout",None),"poll_disconnected")
    restart=TaskStore(store.db_path)
    recovery=restart.recover("test-graph")["actions"][0]
    assert recovery["action"]=="query_original_task" and recovery["service_task_id"]=="original-id"
    assert not recovery["may_dispatch_new_request"] and not recovery["may_cancel_original_task"]
    with pytest.raises(TaskStoreError): restart.record_submission(attempt["claim_id"],"new-id",receipt)
    current=restart.snapshot("test-graph")["attempts"][0]
    accepted=restart.accept_result(attempt["claim_id"],result(current))
    assert accepted["current_applied"] and not restart.recover("test-graph")["actions"]
    assert len(restart.node_history("test-graph","director")["attempts"][0]["events"])==4


def test_unknown_without_id_preserves_raw_and_stops(store):
    attempt=claim(store)
    receipt=raw(b"\x00\xff\r\n",None,True)
    store.mark_unknown(attempt["claim_id"],receipt,"transport_result_unknown")
    assert store.recover("test-graph")["actions"][0]["action"]=="reconcile_unknown_without_task_id"
    events=store.node_history("test-graph","director")["attempts"][0]["events"]
    assert events[-1]["body"]["raw_receipt"]==receipt
    with pytest.raises(TaskStoreError): store.revise_node("test-graph","director",{"new":1},auth(store,purpose="revision",revision=True))


@pytest.mark.parametrize("field,value",[("outcome","生成完成"),("outcome",["completed"]),("complete","true"),("complete_end",1),("result_known","known"),("schema_tool_status","passed"),("schema_tool_status",{}),("contract_valid","true")])
def test_results_never_accept_keyword_or_type_guesses(store,field,value):
    attempt=claim(store); output=result(attempt); output[field]=value
    with pytest.raises(TaskStoreError): store.accept_result(attempt["claim_id"],output)
    assert statuses(store)["director"]=="claimed"


@pytest.mark.parametrize("mutation",["request","claim","task","raw","http","termination","schema","usage_negative","usage_bool","usage_float_tokens"])
def test_result_identity_and_qualification_gate(store,mutation):
    attempt=claim(store); attempt=store.record_submission(attempt["claim_id"],"original-id",raw())
    value=result(attempt)
    if mutation=="request": value["request_sha256"]="b"*64
    if mutation=="claim": value["claim_id"]="another"
    if mutation=="task": value["service_task_id"]="replacement-id"
    if mutation=="raw": value["raw_receipt"]["sha256"]="c"*64
    if mutation=="http": value["raw_receipt"]["http_status"]=None
    if mutation=="termination": value["complete_end"]=False
    if mutation=="schema": value["schema_tool_status"]="missing"
    if mutation=="usage_negative": value["usage"]["amount"]=-1
    if mutation=="usage_bool": value["usage"]["amount"]=True
    if mutation=="usage_float_tokens": value["usage"]["amount"]=17.0
    with pytest.raises(TaskStoreError): store.accept_result(attempt["claim_id"],value)
    assert statuses(store)["director"]=="submitted"


def test_unknown_usage_blocks_content_revision(store):
    attempt=claim(store)
    value=result(attempt,outcome="content_rejected",usage_known=False)
    assert store.accept_result(attempt["claim_id"],value)["attempt"]["status"]=="result_unknown"
    assert store.recover("test-graph")["actions"][0]["action"]=="stop_usage_unknown"
    with pytest.raises(TaskStoreError): store.revise_node("test-graph","director",{"feedback":"new"},auth(store,purpose="revision",revision=True))


@pytest.mark.parametrize("next_known,next_amount",[(False,None),(True,0),(True,18)])
def test_unknown_known_usage_cannot_regress_or_change(store,next_known,next_amount):
    attempt=claim(store)
    first=result(attempt,outcome="unknown",result_known=False)
    store.accept_result(attempt["claim_id"],first)
    second=result(attempt,outcome="unknown",result_known=False,usage_known=next_known)
    if next_known: second["usage"]["amount"]=next_amount
    with pytest.raises(TaskStoreError) as exc: store.accept_result(attempt["claim_id"],second)
    assert exc.value.code=="KNOWN_USAGE_CONFLICT"
    snap=store.snapshot("test-graph")
    assert snap["usage_totals"]=={"reported_tokens":17} and snap["attempts"][0]["result"]==first
    history=store.node_history("test-graph","director")["attempts"][0]["events"]
    assert history[-1]["kind"]=="conflicting_result" and history[-1]["body"]==second


def test_known_content_revision_is_new_identity_with_bound_capacity(store):
    first=claim(store,cap=2)
    rejected=result(first,outcome="content_rejected")
    store.accept_result(first["claim_id"],rejected)
    with pytest.raises(TaskStoreError): store.revise_node("test-graph","director",{"revision":2},auth(store,purpose="revision"))
    revised=store.revise_node("test-graph","director",{"revision":2,"feedback":rejected["output"]},auth(store,purpose="revision",revision=True))
    assert {n["node_id"]:n["current_revision"] for n in revised["nodes"]}["director"]==2
    second=store.claim("test-graph","director",request(version=2),auth(store,cap=2),expected_revision=2)
    assert second["claim_id"]!=first["claim_id"] and second["identity_sha256"]!=first["identity_sha256"] and second["attempt_index"]==2
    store.accept_result(second["claim_id"],result(second,outcome="content_rejected"))
    store.revise_node("test-graph","director",{"revision":3},auth(store,purpose="revision",revision=True))
    with pytest.raises(TaskStoreError) as exc: store.claim("test-graph","director",request(version=3),auth(store,cap=2))
    assert exc.value.code=="AUTHORIZATION_EXHAUSTED"
    assert store.snapshot("test-graph")["usage_totals"]=={"reported_tokens":34}


def test_protocol_missing_tool_failure_cannot_be_content_retry(store):
    attempt=claim(store)
    rejected=result(attempt,outcome="protocol_rejected"); rejected["schema_tool_status"]="missing"; rejected["contract_valid"]=False
    store.accept_result(attempt["claim_id"],rejected)
    with pytest.raises(TaskStoreError): store.revise_node("test-graph","director",{"new":2},auth(store,purpose="revision",revision=True))
    assert store.snapshot("test-graph")["usage_totals"]=={"reported_tokens":17}


def test_http200_task_failed_is_explicit_failure_not_content_retry(store):
    attempt=claim(store); attempt=store.record_submission(attempt["claim_id"],"task-failed",raw())
    failed=result(attempt,outcome="external_failed"); failed["provider_task_state"]="failed"
    assert store.accept_result(attempt["claim_id"],failed)["attempt"]["status"]=="external_failed"
    with pytest.raises(TaskStoreError): store.revise_node("test-graph","director",{"new":3},auth(store,purpose="revision",revision=True))


def test_source_change_invalidates_descendants_without_cancelling_old_attempt(store):
    original=claim(store)
    submitted=store.record_submission(original["claim_id"],"old-provider-task",raw())
    source_auth=auth(store,"script",purpose="revision")
    store.revise_node("test-graph","script",{"native_script":"完整新来源","source_receipt":"offline-fixture-2"},source_auth)
    assert statuses(store)["director"]=="invalidated" and statuses(store)["video"]=="invalidated"
    assert store.snapshot("test-graph")["attempts"][0]["status"]=="submitted"
    late=store.accept_result(original["claim_id"],result(submitted))
    assert late["late_result"] and not late["current_applied"]
    assert statuses(store)["director"]=="invalidated"
    assert store.snapshot("test-graph")["usage_totals"]=={"reported_tokens":17}
    assert store.node_history("test-graph","director")["revisions"][0]["status"]=="submitted"
    assert store.node_history("test-graph","director")["attempts"][0]["result"]["output"]=={"native":"完整原生版本"}
    with pytest.raises(TaskStoreError): store.register_authorization(auth(store)|{"authorization_id":original["authorization_id"],"source_sha256":source_auth["source_sha256"]})


def test_source_change_does_not_unlock_unknown_by_new_revision(store):
    attempt=claim(store)
    store.mark_unknown(attempt["claim_id"],raw("timeout",None),"unknown")
    store.revise_node("test-graph","script",{"native_script":"new"},auth(store,"script",purpose="revision"))
    with pytest.raises(TaskStoreError) as exc: store.revise_node("test-graph","director",{"new_request_source":2},auth(store,purpose="revision",revision=True))
    assert exc.value.code=="ORIGINAL_ATTEMPT_UNRESOLVED"
    assert len(store.recover("test-graph")["actions"])==1


def test_source_change_keeps_unrelated_branch_valid_when_changed_director(store):
    complete(store,"unrelated")
    first=claim(store); store.accept_result(first["claim_id"],result(first,outcome="content_rejected"))
    store.revise_node("test-graph","director",{"feedback":2},auth(store,purpose="revision",revision=True))
    snap=store.snapshot("test-graph")
    assert statuses(store)["unrelated"]=="completed" and statuses(store)["compile"]=="invalidated"
    assert next(n for n in snap["nodes"] if n["node_id"]=="unrelated")["current_revision"]==1


def test_offline_compiler_accepts_no_http_zero_usage_only(store):
    complete(store)
    completed=complete(store,"compile")
    assert completed["attempt"]["status"]=="completed"
    assert store.snapshot("test-graph")["usage_totals"]=={"reported_tokens":17,"provider_units":0}


def test_network_provider_cannot_use_compile_bypass(store):
    complete(store)
    value=request("compile"); value["provider_id"]="network-provider"
    with pytest.raises(TaskStoreError) as exc: store.claim("test-graph","compile",value,auth(store,"compile"))
    assert exc.value.code=="PROVIDER_KIND_MISMATCH"


@pytest.mark.parametrize("field,value",[("http_status",200),("service_task_id","fake-network-id")])
def test_local_compile_cannot_manufacture_service_evidence(store,field,value):
    complete(store); attempt=claim(store,"compile")
    output=result(attempt)
    if field=="http_status": output["raw_receipt"][field]=value
    else: output[field]=value
    with pytest.raises(TaskStoreError) as exc: store.accept_result(attempt["claim_id"],output)
    assert exc.value.code=="INVALID_LOCAL_RESULT"


def test_media_save_is_human_pending_and_blocks_downstream(store,tmp_path):
    complete(store); complete(store,"compile")
    attempt=claim(store,"video"); attempt=store.record_submission(attempt["claim_id"],"media-original",raw())
    file=tmp_path/"saved.mp4"; file.write_bytes(b"offline opaque media bytes - not opened")
    output={"saved_files":[{"path":str(file),"sha256":hashlib.sha256(file.read_bytes()).hexdigest(),"size_bytes":file.stat().st_size}]}
    accepted=store.accept_result(attempt["claim_id"],result(attempt,output=output))
    assert accepted["attempt"]["status"]=="awaiting_human_review"
    with pytest.raises(TaskStoreError) as exc: claim(store,"downstream")
    assert exc.value.code=="DEPENDENCY_NOT_READY"
    assert "passed" not in statuses(store).values()


def test_media_file_incomplete_rejected_without_inspection(store,tmp_path):
    complete(store); complete(store,"compile")
    attempt=claim(store,"video")
    output={"saved_files":[{"path":str(tmp_path/"missing.mp4"),"sha256":"a"*64,"size_bytes":12}]}
    with pytest.raises(TaskStoreError) as exc: store.accept_result(attempt["claim_id"],result(attempt,task_id="media-original",output=output))
    assert exc.value.code=="MEDIA_FILE_INCOMPLETE"


def test_result_idempotency_never_double_counts_usage(store):
    attempt=claim(store); value=result(attempt)
    assert store.accept_result(attempt["claim_id"],value)["idempotent"] is False
    assert TaskStore(store.db_path).accept_result(attempt["claim_id"],value)["idempotent"] is True
    assert store.snapshot("test-graph")["usage_totals"]=={"reported_tokens":17}
    changed=deepcopy(value); changed["output"]={"replacement":"not allowed"}
    with pytest.raises(TaskStoreError): store.accept_result(attempt["claim_id"],changed)
    assert len(store.node_history("test-graph","director")["attempts"][0]["events"])==2


@pytest.mark.parametrize("stage",["after_claim_insert","after_submission_record","after_result_record","after_revision_invalidation"])
def test_transaction_faults_leave_no_partial_state(store,stage):
    class Crash(Exception): pass
    def fault(observed):
        if observed==stage: raise Crash(observed)
    attempt=None
    if stage in {"after_submission_record","after_result_record"}: attempt=claim(store)
    before=store.snapshot("test-graph")
    store.fault_hook=fault
    with pytest.raises(Crash):
        if stage=="after_claim_insert": claim(store)
        elif stage=="after_submission_record": store.record_submission(attempt["claim_id"],"original",raw())
        elif stage=="after_result_record": store.accept_result(attempt["claim_id"],result(attempt))
        else: store.revise_node("test-graph","script",{"new":"source"},auth(store,"script",purpose="revision"))
    assert TaskStore(store.db_path).snapshot("test-graph")==before


def test_same_service_id_cannot_bind_another_attempt(store):
    one=claim(store); two=claim(store,"unrelated")
    store.record_submission(one["claim_id"],"unique-native-task",raw())
    with pytest.raises(TaskStoreError) as exc: store.record_submission(two["claim_id"],"unique-native-task",raw())
    assert exc.value.code=="SERVICE_TASK_ALREADY_BOUND"
