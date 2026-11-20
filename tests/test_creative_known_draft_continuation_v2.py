"""Known-local draft continuation tests; mock pass is not creative quality."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import creative_known_draft_continuation_v2 as candidate
from src.content_factory import creative_studio_task_store_v1 as task_store
from tests import test_creative_known_plan_continuation_v1 as old
from tests import test_creative_fresh_legal_text_pipeline_v1 as fixtures


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket,"connect",lambda *a,**k:pytest.fail("no network"))
    monkeypatch.setattr(socket,"create_connection",lambda *a,**k:pytest.fail("no network"))


def long_script(value):
    value["beats"][0]["steps"][0]["text"] = "问" * 49
    value["beats"][1]["steps"][0]["text"] = "答" * 60
    return value


@pytest.fixture
def stopped(tmp_path):
    source = old.original.__wrapped__(tmp_path)
    service = old.Service(source["case"],{"fresh_draft_01":long_script,"fresh_draft_02":long_script})
    def invoke(label, request, validate):
        if label == "fresh_draft_03":
            raise task_store.TaskStoreError("DUPLICATE_DISPATCH","Revision/request already has an immutable claim")
        return service.invoke(label,request,validate)
    state = old.continuation.KnownPlanContinuation(invoke=invoke,persist_state=service.persist,
        payload_projector=old.project,operator_binding=old.OPERATOR,
        format_recovery_authorization=fixtures.format_auth()).run_from_known_plan(
            resume_state=source["state"],format_seed=source["seed"],**source["case"])
    assert state["status"] == "halt_execution_unknown" and state["versions"] == {"theme":2,"plan":2,"draft":3}
    result = state["receipts"][-1]
    proof = {"schema":"known_local_draft_failure_proof/v1","code":"DUPLICATE_DISPATCH",
        "provider_dispatch_started":False,"runtime_boundary_verified":True,"graph_status":"prepared","sql_attempt_count":0,
        "source_binding_sha256":fixtures.BINDING,"stop_state_sha256":candidate.digest(state),
        "result527_sha256":candidate.digest(result),"ledger_sha256":"d"*64,"taskstore_evidence_sha256":"e"*64,
        "ledger_receipt_ordinals":[r["ordinal"] for r in state["receipts"]],"failed_label":"fresh_draft_03",
        "request_sha256":state["events"][-1]["request_sha256"],"graph_id":"call_fixture"}
    operator = {**old.OPERATOR,"local_failure_proof_sha256":candidate.digest(proof)}
    return {"case":source["case"],"state":state,"result":result,"proof":proof,"operator":operator,"tmp_path":tmp_path}


class Service(fixtures.Service):
    def invoke(self,label,request,validate):
        result = super().invoke(label,request,validate)
        result["ordinal"] = 527 + len(self.calls)
        result["call_evidence"] = {"identity_sha256":candidate.digest(old.identity(result))}
        return result


def execute(stopped,modifications=None,guard=lambda:None,seed_factory=None):
    service = Service(stopped["case"],modifications)
    pipeline = candidate.KnownDraftContinuation(invoke=service.invoke,persist_state=service.persist,
        payload_projector=old.project,operator_binding=stopped["operator"],resume_guard=guard,
        format_recovery_authorization=fixtures.format_auth(),format_seed_factory=seed_factory)
    result = pipeline.run_from_known_local_draft(stop_state=stopped["state"],result527=stopped["result"],
        local_failure_proof=stopped["proof"],**stopped["case"])
    return result,service


@pytest.mark.parametrize("text,allowed", [("汉"*48,True),("汉"*49,False),("a1"*24,True),("a1"*25,False),
    ("汉，"*48+"……?!\n",True),("汉，"*49,False)])
def test_dialogue_schema_and_estimator_use_same_spoken_predicate(stopped,text,allowed):
    raw = fixtures.raw_script();raw["beats"][0]["steps"][0]["text"] = text
    schema = candidate.build_script_schema(stopped["state"]["brief"])
    if allowed:
        Draft202012Validator(schema).validate(raw)
        candidate.validate_script(raw,stopped["state"]["brief"])
    else:
        with pytest.raises(ValidationError):Draft202012Validator(schema).validate(raw)
        with pytest.raises(candidate.ScriptDialogueWindowError) as caught:candidate.validate_script(raw,stopped["state"]["brief"])
        assert caught.value.code == "SCRIPT_DIALOGUE_WINDOW_EXCEEDED"


def test_action_is_not_subject_to_dialogue_character_cap(stopped):
    raw = fixtures.raw_script();raw["beats"][2]["steps"][1]["text"] = "动作"*100
    candidate.validate_script(raw,stopped["state"]["brief"])


def test_typed_window_failure_contains_all_actual_refs_and_equation(stopped):
    raw = stopped["result"]["output"]
    with pytest.raises(candidate.ScriptDialogueWindowError) as caught:candidate.validate_script(raw,stopped["state"]["brief"])
    rows = caught.value.detail["violations"]
    assert [r["source_ref"] for r in rows] == ["B1.S01","B2.S01"]
    assert [r["spoken_character_count"] for r in rows] == [49,60]
    assert rows[0]["field_path"] == "script.beats.0.steps.0.text"
    assert rows[0]["text"] == raw["beats"][0]["steps"][0]["text"] and rows[0]["speaker_id"] == "worker"
    assert rows[0]["estimated_minimum_seconds"] == 49/3.3+.3
    assert rows[0]["maximum_spoken_characters"] == 48 and caught.value.detail["estimated_not_measured"] is True


def test_actual_527_yields_five_typed_diagnostics_without_modifying_frozen_native():
    from scripts import run_fresh_legal_compact_continuation_v1 as entry
    root=entry.original.DEFAULT_ROOT
    path=root/'call_527_fresh_draft_02.json';before=path.read_bytes()
    receipt=json.loads(before.decode('utf-8-sig'))
    state=entry.control.read(root/'compact_continuation_01/TEXT_STATE.json')
    raw=receipt.get('document_output',receipt.get('output'))
    with pytest.raises(candidate.ScriptDialogueWindowError) as caught:candidate.validate_script(raw,state['brief'])
    assert [r['source_ref'] for r in caught.value.detail['violations']] == ['B2.S02','B3.S01','B4.S02','B4.S05','B6.S02']
    assert path.read_bytes()==before


def test_actual_stopped_prefix_and_proven_sql_slot_build_changed_request_offline_only():
    import sqlite3
    from src.content_factory import creative_compact_legal_context_v1 as compact
    from scripts import run_fresh_legal_compact_continuation_v1 as entry
    root=entry.original.DEFAULT_ROOT;directory=root/'compact_continuation_01'
    before=(directory/'TEXT_STATE.json').read_bytes();state=json.loads(before.decode('utf-8-sig'))
    receipt=entry.control.read(root/'call_527_fresh_draft_02.json')
    gid='call_'+candidate.digest({'grant_id':entry.original.GRANT_ID,'label':'fresh_draft_03'})[:24]
    with sqlite3.connect((root/'TASKS.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as conn:
        count=conn.execute('SELECT count(*) FROM attempts WHERE graph_id=?',(gid,)).fetchone()[0]
        status=conn.execute("SELECT status FROM revisions WHERE graph_id=? AND node_id='result'",(gid,)).fetchone()[0]
    assert count==0 and status=='prepared'
    proof={'schema':'known_local_draft_failure_proof/v1','code':'DUPLICATE_DISPATCH','provider_dispatch_started':False,
        'runtime_boundary_verified':True,'graph_status':status,'sql_attempt_count':count,
        'source_binding_sha256':entry.SOURCE_BINDING,'stop_state_sha256':candidate.digest(state),
        'result527_sha256':candidate.digest(receipt),'ledger_sha256':entry.control.sha_file(root/'CALL_LEDGER.json'),
        'taskstore_evidence_sha256':'e'*64,'ledger_receipt_ordinals':[r['ordinal'] for r in state['receipts']],
        'failed_label':'fresh_draft_03','request_sha256':state['events'][-1]['request_sha256'],'graph_id':gid}
    calls=[];snapshots=[]
    def capture(label,request,validator):
        calls.append(request)
        raise RuntimeError('offline capture; no service dispatcher exists')
    pipeline=candidate.KnownDraftContinuation(invoke=capture,persist_state=snapshots.append,
        payload_projector=lambda p:compact.compact_payload(p,entry.SOURCE_BINDING,now='2026-10-12T16:29:23.415468+00:00'),
        operator_binding={**old.OPERATOR,'local_failure_proof_sha256':candidate.digest(proof)},resume_guard=lambda:None,
        format_recovery_authorization={'authorized':True,'source_binding_sha256':entry.SOURCE_BINDING,
            'evidence_ref':'offline original scope witness','evidence_sha256':'f'*64})
    result=pipeline.run_from_known_local_draft(stop_state=state,result527=receipt,local_failure_proof=proof,
        **entry.inputs(root),now='2026-10-12T16:29:23.415468+00:00')
    assert result['status']=='halt_execution_unknown' and result['continuation_new_model_calls']==0
    assert len(calls)==1 and candidate.digest(calls[0])!=receipt['request_sha256']
    payload=json.loads(calls[0]['messages'][1]['content'])
    assert len(payload['dialogue_window_diagnostics']['violations'])==5
    assert payload['brief']==state['brief'] and payload['creative_scene_plan']==state['compiled_plan']
    assert (directory/'TEXT_STATE.json').read_bytes()==before


def test_existing_third_slot_substantive_full_request_then_same_source_review(stopped):
    before=deepcopy(stopped['state'])
    result,service=execute(stopped)
    assert result['status']=='text_ready_for_director' and len(service.calls)==2
    assert result['versions']=={'theme':2,'plan':2,'draft':3}
    assert result['receipts'][:7]==before['receipts'] and result['events'][:len(before['events'])]==before['events']
    assert result['new_model_calls']==9 and result['continuation_new_model_calls']==2
    assert [r['label'] for r in result['receipts'][7:]]==['fresh_draft_03_known_local_revision','fresh_full_review_03_known_local_revision']
    request=service.calls[0];payload=json.loads(request['messages'][1]['content'])
    assert payload['previous_complete_document']==stopped['result']['output']
    assert payload['creative_scene_plan']==before['compiled_plan'] and payload['brief']==before['brief']
    assert payload['dialogue_window_diagnostics']['violations'] and request['structured_schema']==candidate.build_script_schema(before['brief'])
    assert candidate.digest(request)!=before['events'][-1]['request_sha256'] and 'nonce' not in str(request.keys())
    assert result['source_review_binding']['writer_ordinal']==528 and result['source_review_binding']['review_ordinal']==529
    assert result['human_quality_approved'] is False and result['creative_quality_passed'] is False
    assert stopped['state']==before


@pytest.mark.parametrize('fault',['unknown','attempt','binding','stop_sha','receipt_sha','claim','ledger','graph','guard','format_used','version','native_plan'])
def test_unproven_or_changed_slot_never_dispatches(stopped,fault):
    if fault=='unknown':stopped['proof']['code']='OUTCOME_UNKNOWN'
    elif fault=='attempt':stopped['proof']['sql_attempt_count']=1
    elif fault=='binding':stopped['proof']['source_binding_sha256']='f'*64
    elif fault=='stop_sha':stopped['proof']['stop_state_sha256']='f'*64
    elif fault=='receipt_sha':stopped['proof']['result527_sha256']='f'*64
    elif fault=='claim':stopped['proof']['request_sha256']='f'*64
    elif fault=='ledger':stopped['proof']['ledger_receipt_ordinals'].pop()
    elif fault=='graph':stopped['proof']['graph_status']='submitted'
    elif fault=='guard':stopped['proof']['runtime_boundary_verified']=False
    elif fault=='format_used':stopped['state']['format_recovery_claims']['draft']={'original_ordinal':527}
    elif fault=='version':stopped['state']['versions']['draft']=4
    else:stopped['state']['native_plan']['title']='changed'
    stopped['operator']['local_failure_proof_sha256']=candidate.digest(stopped['proof'])
    with pytest.raises(ValueError):execute(stopped)


def test_failed_third_full_draft_cannot_call_fourth(stopped):
    result,service=execute(stopped,{'fresh_draft_03_known_local_revision':long_script})
    assert result['status']=='draft_stalled' and len(service.calls)==1 and result['versions']['draft']==3
    assert result['receipts'][-1]['failure']['code']=='SCRIPT_DIALOGUE_WINDOW_EXCEEDED'


def test_full_review_failure_is_terminal_without_new_native_or_planning(stopped):
    result,service=execute(stopped,{'fresh_full_review_03_known_local_revision':fixtures.fail_dialogue})
    assert result['status']=='creative_stalled' and len(service.calls)==2 and result['versions']=={'theme':2,'plan':2,'draft':3}


def test_unknown_review_is_not_handoff_or_repaired(stopped):
    def unknown(value):value['dialogue_checks'][0]['status']='unknown';return value
    result,service=execute(stopped,{'fresh_full_review_03_known_local_revision':unknown})
    assert result['status']=='halt_review_uncertain' and len(service.calls)==2


def test_unknown_new_usage_blocks_review(stopped):
    def unknown(receipt):receipt['response_metadata']['total_tokens']=None;return receipt
    result,service=execute(stopped,{'receipt:fresh_draft_03_known_local_revision':unknown})
    assert result['status']=='halt_result_or_usage_unknown' and len(service.calls)==1


def test_actual_guard_failure_is_saved_and_no_provider_dispatch(stopped):
    def blocked():raise ValueError('current SQL/SDK differs')
    result,service=execute(stopped,guard=blocked)
    assert result['status']=='halt_additive_preflight_failed' and service.calls==[]


@pytest.mark.parametrize('typed,changed_request',[(True,False),(False,False),(True,True)])
def test_only_verified_same_request_local_exception_has_known_pre_dispatch_classification(stopped,typed,changed_request):
    service=Service(stopped['case'])
    def blocked(label,request,validator):
        if typed:
            raise candidate.KnownLocalDispatchError(request_sha256='f'*64 if changed_request else candidate.digest(request),
                evidence_sha256='c'*64,detail={'code':'DUPLICATE_DISPATCH','graph_id':'call_fixture',
                    'sql_attempt_count':0,'provider_dispatch_started':False,'runtime_boundary_verified':True})
        raise task_store.TaskStoreError('DUPLICATE_DISPATCH','not independently proven predispatch')
    pipeline=candidate.KnownDraftContinuation(invoke=blocked,persist_state=service.persist,
        payload_projector=old.project,operator_binding=stopped['operator'],resume_guard=lambda:None,
        format_recovery_authorization=fixtures.format_auth())
    result=pipeline.run_from_known_local_draft(stop_state=stopped['state'],result527=stopped['result'],
        local_failure_proof=stopped['proof'],**stopped['case'])
    assert result['status']==('halt_known_local_before_dispatch' if typed and not changed_request else 'halt_execution_unknown')
    assert result['versions']['draft']==3 and result['continuation_new_model_calls']==0


def test_draft_missing_tool_can_use_only_original_unused_phase_format_slot(stopped):
    def factory(receipt):
        return old.continuation.compile_missing_tool_seed(receipt,**old.evidence_for(receipt,
            stopped['tmp_path']/'new_evidence',{'request_sha256':receipt['request_sha256']}))
    result,service=execute(stopped,{'receipt:fresh_draft_03_known_local_revision':old.native_missing},seed_factory=factory)
    assert result['status']=='text_ready_for_director' and result['versions']['draft']==3 and len(service.calls)==3
    assert set(result['format_recovery_claims'])=={'plan','draft'}


def test_format_recovery_failure_stops_without_fourth_native(stopped):
    def factory(receipt):
        return old.continuation.compile_missing_tool_seed(receipt,**old.evidence_for(receipt,
            stopped['tmp_path']/'new_evidence',{'request_sha256':receipt['request_sha256']}))
    mods={f'receipt:{label}':old.native_missing for label in ('fresh_draft_03_known_local_revision','fresh_draft_03_known_local_revision_format_recovery')}
    result,service=execute(stopped,mods,seed_factory=factory)
    assert result['status']=='halt_format_recovery_failed' and len(service.calls)==2 and result['versions']['draft']==3
