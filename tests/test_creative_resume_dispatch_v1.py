"""Offline continuation controls; no provider/network traffic."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from scripts.creative_resume_dispatch_v1 import ContinuationRuntime, read, write
from src.content_factory.creative_workflow_roles import RoleResult, RoleResponseError
from src.content_factory.creative_workflow_contract import CreativeContractError

@pytest.fixture
def case(tmp_path):
    project=tmp_path/'project';project.mkdir();source=project/'new.py';source.write_text('version=1\n')
    quota=project/'quota.json';write(quota,{'stop_condition':{'triggered':False},'task_status':'active'})
    models={'writer':{'model':'MiniMax-M3'},'director':{'model':'deepseek-flash'}}
    provider=SimpleNamespace(calls=[],handler=None)
    def call(*a,**kw):
        provider.calls.append((a,kw));return provider.handler(*a,**kw)
    root=project/'resume';lock=project/'shared'/'DISPATCH.lock'
    runtime=ContinuationRuntime(project,root,[source],{'calls_started':49,'reported_tokens':490913,'legacy_cap':500000},models,
        client_factory=lambda:SimpleNamespace(call=call),quota_state=quota,shared_lock=lock)
    runtime.prepare()
    return SimpleNamespace(r=runtime,root=root,source=source,quota=quota,provider=provider,lock=lock)

def wire(text='one',schema=None):
    return {'role':'writer','model':'MiniMax-M3','messages':[{'role':'user','content':text}],
        'structured_schema':schema,'parameters':{'temperature':.4,'thinking':'disabled','max_completion_tokens':32}}

def response(value=None,tokens=100,rid='fixture',finish='tool_calls',mode='tool_call'):
    m={'response_id':rid,'finish_reason':finish,'output_mode':mode}
    if tokens is not None:m['total_tokens']=tokens
    return RoleResult(json.dumps(value or {}),m,{'fixture_only':True})

def test_inherits_spend_without_rewriting_legacy_cap(case):
    s=case.r.summary();assert s['effective_calls_started']==49 and s['effective_reported_tokens']==490913
    assert s['max_total_tokens'] is None and not s['old_budget_reset']
    assert read(case.r.ledger)['starting_spend']['legacy_cap']==500000 and not case.provider.calls

def test_pending_receipt_and_shared_lock_exist_before_dispatch(case):
    def handler(*a,**kw):
        led=read(case.r.ledger);assert len(led['calls'])==1 and led['calls'][0]['ordinal']==50
        rec=read(case.root/led['calls'][0]['receipt']);assert rec['status']=='pending_response'
        assert rec['token_reservation']>32 and case.lock.is_file()
        return response()
    case.provider.handler=handler;r=case.r.dispatch('draft',wire(),lambda x:{'valid':True})
    assert r['status']=='contract_valid' and not case.lock.exists()
    assert case.r.summary()['effective_reported_tokens']==491013

def test_identical_wire_under_new_label_does_not_redispatch(case):
    case.provider.handler=lambda *a,**kw:response()
    r=case.r.dispatch('draft',wire(),lambda x:{})
    assert case.r.dispatch('renamed',deepcopy(wire()),lambda x:{})==r
    assert len(case.provider.calls)==1

def test_same_label_different_request_is_not_overwritten(case):
    case.provider.handler=lambda *a,**kw:response();case.r.dispatch('draft',wire(),lambda x:{})
    with pytest.raises(RuntimeError,match='another request'):case.r.dispatch('draft',wire('different'),lambda x:{})
    assert len(case.provider.calls)==1

def test_timeout_is_unknown_and_prevents_new_dispatch(case):
    def fail(*a,**kw):raise TimeoutError('outcome not received')
    case.provider.handler=fail;r=case.r.dispatch('draft',wire(),lambda x:{})
    assert r['status']=='outcome_unknown' and case.r.summary()['unknown_token_reservations']>0
    assert case.r.dispatch('cached',wire(),lambda x:{})==r
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('next'),lambda x:{})
    assert len(case.provider.calls)==1

@pytest.mark.parametrize('tokens',[None,-1,True])
def test_unusable_usage_is_not_zero_and_prevents_followup(case,tokens):
    case.provider.handler=lambda *a,**kw:response(tokens=tokens)
    case.r.dispatch('one',wire(),lambda x:{})
    with pytest.raises(RuntimeError,match='unknown outcome'):case.r.dispatch('next',wire('next'),lambda x:{})
    assert case.r.summary()['unknown_token_reservations']>0 and len(case.provider.calls)==1

def test_known_truncation_can_only_be_followed_by_distinct_explicit_request(case):
    case.provider.handler=lambda *a,**kw:response(finish='length')
    r=case.r.dispatch('review',wire(),lambda x:pytest.fail('partial must not be validated'))
    assert r['status']=='interface_rejected' and r['failure']['code']=='RESPONSE_TRUNCATED'
    assert case.r.dispatch('same',wire(),lambda x:{})==r
    case.provider.handler=lambda *a,**kw:response(rid='new')
    second=case.r.dispatch('review_v2',wire('corrected full protocol'),lambda x:{})
    assert second['status']=='contract_valid' and len(case.provider.calls)==2

def test_missing_required_tool_has_interface_branch(case):
    case.provider.handler=lambda *a,**kw:response(mode='content',finish='stop')
    r=case.r.dispatch('one',wire(schema={'type':'object'}),lambda x:pytest.fail('no tool'))
    assert r['status']=='interface_rejected' and r['failure']['code']=='REQUIRED_TOOL_MISSING'

def test_type_error_has_state_contract_branch(case):
    case.provider.handler=lambda *a,**kw:response({'beats':{'item':[]}})
    schema={'type':'object','properties':{'beats':{'type':'array'}},'required':['beats']}
    r=case.r.dispatch('one',wire(schema=schema),lambda x:{})
    assert r['status']=='contract_rejected' and r['failure']['category']=='state_contract'

def test_business_valueerror_is_not_invalid_json(case):
    case.provider.handler=lambda *a,**kw:response()
    def bad(value):raise CreativeContractError('MODULE_STATE: source mismatch')
    r=case.r.dispatch('one',wire(),bad)
    assert r['status']=='contract_rejected' and r['failure']['category']=='state_contract'

def test_source_or_receipt_mutation_blocks_dispatch(case):
    case.source.write_text('version=2\n')
    with pytest.raises(RuntimeError,match='source/model'):case.r.dispatch('one',wire(),lambda x:{})
    assert not case.provider.calls

def test_receipt_mutation_and_orphan_are_blocked(case):
    case.provider.handler=lambda *a,**kw:response();r=case.r.dispatch('one',wire(),lambda x:{})
    row=read(case.r.ledger)['calls'][0];write(case.root/row['receipt'],{**r,'status':'passed'})
    with pytest.raises(RuntimeError,match='receipt changed'):case.r.dispatch('next',wire('next'),lambda x:{})
    assert len(case.provider.calls)==1

def test_latched_quota_stop_is_enforced_before_pending_or_provider(case):
    write(case.quota,{'stop_condition':{'triggered':True},'task_status':'paused'})
    with pytest.raises(RuntimeError,match='stop is latched'):case.r.dispatch('one',wire(),lambda x:{})
    assert not read(case.r.ledger)['calls'] and not case.provider.calls

def test_existing_shared_lock_stops_all_dispatches(case):
    case.lock.parent.mkdir(exist_ok=True);case.lock.write_text('other dispatch')
    with pytest.raises(FileExistsError):case.r.dispatch('one',wire(),lambda x:{})
    assert not read(case.r.ledger)['calls'] and not case.provider.calls


def test_validator_cannot_rewrite_original_model_output(case):
    case.provider.handler=lambda *a,**kw:response({'text':'model original'})
    def mutate(value):
        value['text']='validator edited';return {'checked':True}
    r=case.r.dispatch('one',wire(),mutate)
    assert r['output']['text']=='model original'
    assert json.loads(r['response_text'])==r['output']
    assert case.r.dispatch('cached',wire(),mutate)['output']==r['output']
    assert len(case.provider.calls)==1


def test_cached_valid_response_is_checked_by_current_validator_without_rewrite(case):
    case.provider.handler=lambda *a,**kw:response({'text':'original'})
    r=case.r.dispatch('one',wire(),lambda x:{})
    row=read(case.r.ledger)['calls'][0];prior=(case.root/row['receipt']).read_bytes()
    def reject(value):raise CreativeContractError('MODULE_SOURCE: no longer current')
    cached=case.r.dispatch('different_label',wire(),reject)
    assert cached['status']=='contract_rejected' and cached['cached_response_rejected_locally']
    assert cached['output']==r['output'] and (case.root/row['receipt']).read_bytes()==prior
    assert len(case.provider.calls)==1


def test_four_digit_ordinal_remains_reusable_and_accounted(case):
    inherited=deepcopy(case.r.inherited);inherited['calls_started']=999
    r=ContinuationRuntime(case.r.project,case.r.project/'four_digits',[case.source],inherited,case.r.models,
        client_factory=case.r.client_factory,quota_state=case.quota,shared_lock=case.lock)
    r.prepare();case.provider.handler=lambda *a,**kw:response()
    receipt=r.dispatch('ordinal',wire(),lambda x:{})
    assert receipt['ordinal']==1000 and r.summary()['effective_calls_started']==1000
    assert r.dispatch('cached',wire(),lambda x:{})==receipt
    assert len(case.provider.calls)==1
