"""Real SDK with in-memory HTTP transport; no provider, account, or media calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import httpx
import openai
import pytest
from scripts import creative_call_evidence_v1 as journal_module
from scripts import creative_evidenced_role_clients_v1 as client_module
from scripts.creative_resume_dispatch_v3 import ContinuationRuntime, read, write
from src.content_factory.creative_workflow_roles import RoleConfig

SECRET = 'dummy-test-api-key-must-not-be-saved'
SCHEMA = {'type':'object','properties':{'beats':{'type':'array'}},'required':['beats'],'additionalProperties':False}

def wire(text='one',role='writer'):
    return {'role':role,'model':'MiniMax-M3' if role=='writer' else 'deepseek-flash',
        'messages':[{'role':'user','content':text}], 'structured_schema':deepcopy(SCHEMA),
        'parameters':{'max_completion_tokens':8000,'temperature':.4,'thinking':'disabled'}}

def envelope(*, role='writer', usage=True, arguments='{"beats":[]}', finish='tool_calls'):
    result={'id':'offline-response-001','model':'MiniMax-M3' if role=='writer' else 'deepseek-flash',
        'choices':[{'finish_reason':finish,'message':{'role':'assistant','content':None,
          'tool_calls':[{'id':'offline-tool-1','type':'function','function':{'name':'submit_creative_json','arguments':arguments}}]}}],
        'base_resp':{'status_code':0,'status_msg':''},'trace_id':'offline-trace-1'}
    if usage:result['usage']={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}
    return result

@pytest.fixture
def case(tmp_path,monkeypatch):
    project=tmp_path/'project';project.mkdir();source=project/'source.py';source.write_text('version=1\n')
    state=NS(requests=[],initializations=[],handler=None,body=envelope(),status=200,
             headers={'x-request-id':'offline-http-1','Set-Cookie':SECRET,'Authorization':'Bearer '+SECRET})
    native_openai=openai.OpenAI
    def handler(request):
        state.requests.append(json.loads(request.content))
        if state.handler:return state.handler(request)
        return httpx.Response(state.status,headers=state.headers,json=deepcopy(state.body))
    def factory(**kwargs):
        state.initializations.append({k:v for k,v in kwargs.items() if k!='api_key'})
        return native_openai(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False))
    monkeypatch.setattr(openai,'OpenAI',factory)
    monkeypatch.setattr(client_module,'role_config',lambda role:RoleConfig(
        'minimax' if role=='writer' else 'deepseek','MiniMax-M3' if role=='writer' else 'deepseek-flash',
        'https://offline.invalid/v1',SECRET))
    runtime=ContinuationRuntime(project,project/'run',[source],
        {'calls_started':55,'reported_tokens':558395,'legacy_cap':500000},
        {'writer':{'model':'MiniMax-M3'},'director':{'model':'deepseek-flash'}},
        shared_lock=project/'shared'/'DISPATCH.lock')
    runtime.prepare()
    return NS(r=runtime,root=runtime.root,source=source,http=state)

def call(case,request=None,validator=lambda value:{}):
    return case.r.dispatch('first',request or wire(),validator)

def evidence(case):return case.r.evidence_path(56)

def phases(case):return [read(p)['phase'] for p in sorted(evidence(case).glob('event_*.json'))]

@pytest.mark.parametrize('role',['writer','director'])
def test_same_protocol_with_raw_http_evidence_and_no_credentials(case,role):
    case.http.body=envelope(role=role);r=call(case,wire(role=role))
    assert r['status']=='contract_valid' and len(case.http.requests)==1
    request=case.http.requests[0]
    assert request['model']==wire(role=role)['model'] and request['messages']==wire(role=role)['messages']
    assert request['thinking']=={'type':'disabled'} and request['temperature']==.4
    assert request['max_completion_tokens' if role=='writer' else 'max_tokens']==8000
    assert 'stream' not in request and 'response_format' not in request
    assert request['tools'][0]['function']['parameters']==SCHEMA
    assert request['tool_choice']=={'type':'function','function':{'name':'submit_creative_json'}}
    assert 'strict' not in request['tools'][0]['function']
    assert case.http.initializations[0]['max_retries']==0
    assert r['response_metadata']['total_tokens']==5 and r['response_metadata']['http_request_id']=='offline-http-1'
    assert r['response_payload']==case.http.body and r['response_payload']['base_resp']['status_code']==0
    order=phases(case)
    assert order.index('http_headers_received')<order.index('response_body_saved')<order.index('response_metadata_saved')<order.index('result_ready')
    for p in case.root.rglob('*'):
        if p.is_file():assert SECRET.encode() not in p.read_bytes()

@pytest.mark.parametrize('status',[400,401,429,500])
def test_http_error_identity_is_not_silence_and_missing_usage_still_blocks(case,status):
    case.http.status=status;case.http.body={'error':{'message':'bad request','type':'offline_fixture'}}
    r=call(case)
    assert r['status']=='interface_rejected' and r['failure']['code']=='HTTP_ERROR_RESPONSE'
    assert r['failure']['response_received'] is True and r['failure']['provider_outcome_known'] is True
    assert r['response_metadata']['http_status_code']==status and r['response_metadata']['http_request_id']=='offline-http-1'
    assert 'total_tokens' not in r['response_metadata'] and case.r.summary()['unknown_token_reservations']>0
    assert case.r.dispatch('cached',wire(),lambda value:{})==r
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('two'),lambda value:{})
    assert len(case.http.requests)==1 and case.http.initializations[0]['max_retries']==0


def test_http_error_explicit_known_usage_is_preserved_without_automatic_retry(case):
    case.http.status=400;case.http.body={'error':{'message':'offline'},'usage':{'total_tokens':5}}
    r=call(case)
    assert r['failure']['code']=='HTTP_ERROR_RESPONSE' and r['response_metadata']['total_tokens']==5
    assert case.r.summary()['effective_reported_tokens']==558400 and len(case.http.requests)==1

@pytest.mark.parametrize('kind',['timeout','disconnect'])
def test_transport_unknown_retains_reservation_and_never_repeats(case,kind):
    def handler(request):
        if kind=='timeout':raise httpx.ReadTimeout('offline only',request=request)
        raise httpx.ConnectError('offline only',request=request)
    case.http.handler=handler;r=call(case)
    assert r['status']=='outcome_unknown' and r['failure']['response_received'] is False
    assert r['failure']['provider_outcome_known'] is False and case.r.summary()['unknown_token_reservations']>0
    assert case.r.dispatch('same',wire(),lambda value:{})==r
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('two'),lambda value:{})
    assert len(case.http.requests)==1


def test_headers_saved_before_response_body_read(case):
    raw=json.dumps(envelope()).encode()
    class InspectingStream(httpx.SyncByteStream):
        def __iter__(self):
            assert 'http_headers_received' in phases(case)
            assert not (evidence(case)/'RESPONSE_BODY_MANIFEST.json').exists()
            yield raw
    case.http.handler=lambda request:httpx.Response(200,headers=case.http.headers,stream=InspectingStream())
    assert call(case)['status']=='contract_valid'
    assert (evidence(case)/'response_body.raw').read_bytes()==raw


def test_disconnect_after_headers_is_partial_unknown(case):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"partial":'
            raise httpx.ReadError('offline disconnect')
    case.http.handler=lambda request:httpx.Response(200,headers=case.http.headers,stream=BrokenStream())
    r=call(case)
    assert r['status']=='outcome_unknown' and r['failure']['response_received'] is True
    assert r['failure']['provider_outcome_known'] is False
    assert r['response_metadata']['http_request_id']=='offline-http-1'
    assert not (evidence(case)/'RESPONSE_BODY_MANIFEST.json').exists()
    assert case.r.summary()['unknown_token_reservations']>0 and len(case.http.requests)==1

@pytest.mark.parametrize('defect,expected',[
    ('missing_tool','REQUIRED_TOOL_MISSING'),('null_function','UNEXPECTED_TOOL_CALL'),
    ('two_choices','UNEXPECTED_RESPONSE_CHOICES'),('no_choices','NO_RESPONSE_CHOICES'),
    ('wrong_model','MODEL_MISMATCH'),('service_error','PROVIDER_ERROR_RESPONSE'),
    ('empty_arguments','EMPTY_RESPONSE'),('truncated_no_tool','RESPONSE_TRUNCATED'),
    ('wrong_tools_type','UNEXPECTED_TOOL_CALL'),('null_message','MALFORMED_RESPONSE_ENVELOPE')])
def test_received_shape_fault_preserves_id_usage_and_raw_body(case,defect,expected):
    b=case.http.body;m=b['choices'][0]['message']
    if defect=='missing_tool':m['tool_calls']=[]
    elif defect=='null_function':m['tool_calls'][0]['function']=None
    elif defect=='two_choices':b['choices']*=2
    elif defect=='no_choices':b['choices']=[]
    elif defect=='wrong_model':b['model']='other-model'
    elif defect=='service_error':b['base_resp']['status_code']=1000
    elif defect=='empty_arguments':m['tool_calls'][0]['function']['arguments']=''
    elif defect=='truncated_no_tool':b['choices'][0]['finish_reason']='length';m['tool_calls']=[]
    elif defect=='wrong_tools_type':m['tool_calls']={'item':[]}
    elif defect=='null_message':b['choices'][0]['message']=None
    r=call(case,validator=lambda value:pytest.fail('unusable response reached validation'))
    assert r['status']=='interface_rejected' and r['failure']['code']==expected
    assert r['response_metadata']['total_tokens']==5 and r['response_metadata']['response_id']=='offline-response-001'
    assert r['response_payload']==b
    assert read(evidence(case)/'RESPONSE_BODY_MANIFEST.json')['body_complete'] is True
    assert len(case.http.requests)==1 and case.r.summary()['unknown_token_reservations']==0


def test_inner_type_error_stays_contract_fault(case):
    case.http.body=envelope(arguments='{"beats":{"item":[]}}');r=call(case)
    assert r['status']=='contract_rejected' and r['failure']['code']=='MODULE_SCHEMA_INVALID'
    assert r['response_metadata']['total_tokens']==5 and len(case.http.requests)==1

@pytest.mark.parametrize('raw',[b'not json',b'{"id":"a","id":"b","usage":{"total_tokens":5}}',b'{"usage":{"total_tokens":1e309}}'])
def test_bad_raw_envelope_is_saved_without_inventing_usage(case,raw):
    case.http.handler=lambda request:httpx.Response(200,headers=case.http.headers,content=raw)
    r=call(case)
    assert r['failure']['code']=='RESPONSE_ENVELOPE_INVALID' and 'total_tokens' not in r['response_metadata']
    assert (evidence(case)/'response_body.raw').read_bytes()==raw
    assert case.r.summary()['unknown_token_reservations']>0

@pytest.mark.parametrize('usage',[None,True,-1,'5'])
def test_unknown_or_invalid_usage_never_becomes_zero(case,usage):
    case.http.body=envelope(usage=False)
    if usage is not None:case.http.body['usage']={'total_tokens':usage}
    r=call(case)
    assert 'total_tokens' not in r['response_metadata'] and case.r.summary()['unknown_token_reservations']>0
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('two'),lambda value:{})
    assert len(case.http.requests)==1


def test_credentials_echoed_in_error_and_identity_are_redacted(case):
    case.http.status=400;case.http.headers['x-request-id']=SECRET
    case.http.body={'error':{'message':'Bearer '+SECRET},'usage':{'total_tokens':5}}
    r=call(case)
    assert r['failure']['code']=='RESPONSE_CREDENTIAL_REDACTED'
    manifest=read(evidence(case)/'RESPONSE_BODY_MANIFEST.json')
    assert manifest['credential_redacted'] and not manifest['raw_bytes_preserved']
    for p in case.root.rglob('*'):
        if p.is_file():assert SECRET.encode() not in p.read_bytes()
    assert SECRET not in str(r) and len(case.http.requests)==1


def test_configuration_error_proves_not_dispatched(case,monkeypatch):
    def fail(role):raise ValueError('do not echo '+SECRET)
    monkeypatch.setattr(client_module,'role_config',fail)
    r=call(case)
    assert r['status']=='blocked_before_dispatch' and r['failure']['code']=='BLOCKED_BEFORE_DISPATCH'
    assert not case.http.requests and SECRET not in str(r)


def test_crash_after_raw_save_recovers_without_rewriting_or_dispatch(case,monkeypatch):
    record=journal_module.CallEvidenceJournal.record
    def crash(self,phase,details=None):
        if phase=='response_body_saved':raise SystemExit('offline simulated process crash')
        return record(self,phase,details)
    monkeypatch.setattr(journal_module.CallEvidenceJournal,'record',crash)
    with pytest.raises(SystemExit):call(case)
    ledger_before=(case.root/'CALL_LEDGER.json').read_bytes();row=read(case.root/'CALL_LEDGER.json')['calls'][0]
    receipt_path=case.root/row['receipt'];original=receipt_path.read_bytes()
    assert read(receipt_path)['status']=='pending_response' and case.r.summary()['unknown_token_reservations']>0
    monkeypatch.setattr(journal_module.CallEvidenceJournal,'record',record)
    def forbidden(**kwargs):pytest.fail('recovery constructed an SDK/client')
    monkeypatch.setattr(openai,'OpenAI',forbidden)
    r=case.r.recover_response(56,lambda value:{'checked':True})
    assert r['status']=='contract_valid' and r['response_metadata']['total_tokens']==5
    assert receipt_path.read_bytes()==original and (case.root/'CALL_LEDGER.json').read_bytes()==ledger_before
    assert len(case.http.requests)==1 and case.r.summary()['effective_calls_started']==56
    assert case.r.summary()['effective_reported_tokens']==558400 and case.r.summary()['unknown_token_reservations']==0
    assert not case.r.summary()['old_budget_reset'] and read(case.root/'CALL_LEDGER.json')['starting_spend']['legacy_cap']==500000
    assert case.r.recover_response(56,lambda value:pytest.fail('cached recovery revalidated'))==r
    assert case.r.dispatch('same',wire(),lambda value:{})['status']=='contract_valid'
    assert len(case.http.requests)==1


def test_raw_body_tampering_blocks_local_recovery(case,monkeypatch):
    original=client_module.parse_saved_response
    def crash(*args,**kwargs):raise SystemExit('offline crash before parse')
    monkeypatch.setattr(client_module,'parse_saved_response',crash)
    with pytest.raises(SystemExit):call(case)
    monkeypatch.setattr(client_module,'parse_saved_response',original)
    with (evidence(case)/'response_body.raw').open('ab') as f:f.write(b' ')
    with pytest.raises(RuntimeError,match='evidence changed'):case.r.recover_response(56,lambda value:{})
    assert len(case.http.requests)==1 and case.r.summary()['unknown_token_reservations']>0


def test_timeout_has_no_fake_recoverable_response(case):
    case.http.handler=lambda request:(_ for _ in ()).throw(httpx.ReadTimeout('offline',request=request))
    call(case)
    with pytest.raises(FileNotFoundError):case.r.recover_response(56,lambda value:{})
    assert len(case.http.requests)==1 and case.r.summary()['unknown_token_reservations']>0


def test_frozen_sources_still_block_new_dispatch(case):
    case.source.write_text('changed\n')
    with pytest.raises(RuntimeError,match='source/model'):call(case)
    assert not case.http.requests and not read(case.root/'CALL_LEDGER.json')['calls']

@pytest.mark.parametrize('phase',['http_headers_received','response_body_saved','response_metadata_saved','result_ready'])
def test_evidence_phase_storage_failure_keeps_identity_and_no_repeat(case,monkeypatch,phase):
    record=journal_module.CallEvidenceJournal.record
    def fail(self,name,details=None):
        if name==phase:raise OSError('offline storage failure')
        return record(self,name,details)
    monkeypatch.setattr(journal_module.CallEvidenceJournal,'record',fail)
    r=call(case)
    assert r['response_metadata']['http_request_id']=='offline-http-1' and len(case.http.requests)==1
    assert r['status'] in ('interface_rejected','outcome_unknown')
    assert case.r.dispatch('same',wire(),lambda value:{})==r
    if phase in ('response_metadata_saved','result_ready'):
        assert r['response_metadata']['total_tokens']==5 and r['failure']['code']=='RESPONSE_PHASE_SAVE_FAILED'
    else:assert case.r.summary()['unknown_token_reservations']>0
    if phase=='response_body_saved':
        monkeypatch.setattr(journal_module.CallEvidenceJournal,'record',record)
        assert case.r.recover_response(56,lambda value:{})['status']=='contract_valid'
    assert len(case.http.requests)==1

@pytest.mark.parametrize('location',['headers','body'])
def test_http_error_storage_failure_still_preserves_known_http_response(case,monkeypatch,location):
    case.http.status=400;case.http.body={'error':{'message':'offline'}}
    if location=='headers':
        record=journal_module.CallEvidenceJournal.record
        def fail(self,phase,details=None):
            if phase=='http_error_headers_received':raise OSError('offline storage')
            return record(self,phase,details)
        monkeypatch.setattr(journal_module.CallEvidenceJournal,'record',fail)
    else:
        monkeypatch.setattr(journal_module.CallEvidenceJournal,'save_body',lambda *args:(_ for _ in ()).throw(OSError('offline storage')))
    r=call(case)
    assert r['failure']['code']=='HTTP_ERROR_EVIDENCE_SAVE_FAILED' and r['status']=='interface_rejected'
    assert r['failure']['response_received'] and r['failure']['provider_outcome_known']
    assert r['response_metadata']['http_status_code']==400 and r['response_metadata']['http_request_id']=='offline-http-1'
    assert case.r.summary()['unknown_token_reservations']>0 and len(case.http.requests)==1


def crash_before_parse(case,monkeypatch):
    original=client_module.parse_saved_response
    monkeypatch.setattr(client_module,'parse_saved_response',lambda *args,**kwargs:(_ for _ in ()).throw(SystemExit('offline crash')))
    with pytest.raises(SystemExit):call(case)
    monkeypatch.setattr(client_module,'parse_saved_response',original)


def test_crash_between_recovery_receipt_and_index_is_locally_resumed(case,monkeypatch):
    from scripts import creative_resume_dispatch_v3 as dispatch_module
    crash_before_parse(case,monkeypatch)
    ledger_before=(case.root/'CALL_LEDGER.json').read_bytes()
    original_write=dispatch_module.write
    def fail(path,*args,**kwargs):
        if Path(path).name=='RECOVERY_INDEX.json':raise OSError('offline index storage failure')
        return original_write(path,*args,**kwargs)
    monkeypatch.setattr(dispatch_module,'write',fail)
    with pytest.raises(OSError):case.r.recover_response(56,lambda value:{'checked':True})
    path=case.root/'recovery'/'call_056.json';orphan_before=path.read_bytes()
    assert case.r.summary()['unknown_token_reservations']>0
    monkeypatch.setattr(dispatch_module,'write',original_write)
    recovered=case.r.recover_response(56,lambda value:{'checked':True})
    assert recovered['status']=='contract_valid' and path.read_bytes()==orphan_before
    assert (case.root/'CALL_LEDGER.json').read_bytes()==ledger_before
    assert case.r.summary()['effective_reported_tokens']==558400 and len(case.http.requests)==1


def test_recovery_artifact_tampering_blocks_effective_usage(case,monkeypatch):
    crash_before_parse(case,monkeypatch);case.r.recover_response(56,lambda value:{})
    path=case.root/'recovery'/'call_056.json'
    with path.open('ab') as f:f.write(b' ')
    with pytest.raises(RuntimeError,match='recovery receipt changed'):case.r.summary()
    with pytest.raises(RuntimeError,match='recovery receipt changed'):case.r.dispatch('next',wire('next'),lambda value:{})
    assert len(case.http.requests)==1


def test_duplicate_response_identity_is_rejected_before_recovery_registration(case,monkeypatch):
    call(case)
    original=client_module.parse_saved_response
    monkeypatch.setattr(client_module,'parse_saved_response',lambda *args,**kwargs:(_ for _ in ()).throw(SystemExit('offline crash')))
    with pytest.raises(SystemExit):case.r.dispatch('second',wire('second'),lambda value:{})
    monkeypatch.setattr(client_module,'parse_saved_response',original)
    with pytest.raises(RuntimeError,match='duplicate response identity'):case.r.recover_response(57,lambda value:{})
    assert not (case.root/'RECOVERY_INDEX.json').exists()
    assert len(case.http.requests)==2 and case.r.summary()['unknown_token_reservations']>0


def test_journal_creation_failure_is_before_any_http_call(case,monkeypatch):
    from scripts import creative_resume_dispatch_v3 as dispatch_module
    monkeypatch.setattr(dispatch_module,'CallEvidenceJournal',lambda *args,**kwargs:(_ for _ in ()).throw(OSError('offline storage')))
    r=call(case)
    assert r['status']=='blocked_before_dispatch' and r['failure']['code']=='BLOCKED_BEFORE_DISPATCH'
    assert not case.http.requests and case.r.summary()['unknown_token_reservations']>0

@pytest.mark.parametrize('tools',[{},False,0])
def test_wrong_falsey_tool_container_is_a_type_fault(case,tools):
    case.http.body['choices'][0]['message']['tool_calls']=tools
    r=call(case)
    assert r['failure']['code']=='UNEXPECTED_TOOL_CALL' and len(case.http.requests)==1


def test_real_parent_gate_and_offline_candidate_preserve_frozen_production(tmp_path):
    from scripts.prepare_creative_call_evidence_repair_v1 import inspect_original,require_original_ready,prepare_candidate,sha
    project=Path(__file__).resolve().parents[1]
    records=project/'data/production_records/this_time_i_leave_s6_20261005'
    baseline=records/'BASELINE_RECORD.json';code=records/'CODE_BINDING_MANIFEST.json'
    before=read(baseline)['immutable_original_file_hashes']
    observation=inspect_original(project,baseline,code)
    assert observation['verified_original_files']==25 and observation['verified_original_sources']==144
    assert observation['pending_ordinals']==[70] and observation['unknown_usage_ordinals']==[70]
    assert observation['spend']['calls_started']==70 and observation['spend']['reported_tokens']==709272
    assert observation['spend']['unknown_token_reservation']==64010
    with pytest.raises(RuntimeError,match='no new task or dispatch'):require_original_ready(observation)
    output=tmp_path/'offline_candidate'
    candidate=prepare_candidate(project,output,baseline,code)
    assert candidate['status']=='offline_binding_prepared_production_blocked' and candidate['code_source_count']==149
    assert not candidate['dispatch_enabled'] and not candidate['provider_called'] and not candidate['new_execution_task']
    assert not (output/'AUTHORIZATION.json').exists() and not (output/'CALL_LEDGER.json').exists()
    assert prepare_candidate(project,output,baseline,code)==candidate
    assert all(sha(Path(observation['original_run'])/rel)==h for rel,h in before.items())
    for rel,h in candidate['source_manifest'].items():assert sha(output/'source_at_binding'/rel)==h
    with (output/'source_at_binding'/'scripts/creative_resume_dispatch_v3.py').open('ab') as f:f.write(b' ')
    with pytest.raises(RuntimeError,match='candidate source snapshot changed'):prepare_candidate(project,output,baseline,code)
