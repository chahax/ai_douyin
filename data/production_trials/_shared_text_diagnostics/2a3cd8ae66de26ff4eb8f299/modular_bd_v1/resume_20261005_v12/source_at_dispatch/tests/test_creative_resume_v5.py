from pathlib import Path
import json
import httpx,openai,pytest
from scripts import run_creative_resume_v5 as runner
from scripts import creative_evidenced_role_clients_v1 as client
from src.content_factory.creative_workflow_roles import RoleConfig

@pytest.fixture
def continuation(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path/'v5')
    monkeypatch.setattr(runner,'SHARED_LOCK',tmp_path/'independent_test.lock')
    native=openai.OpenAI;calls=[];state={'timeout':False}
    def handler(request):
        calls.append(json.loads(request.content))
        if state['timeout']:raise httpx.ReadTimeout('offline fixture',request=request)
        body={'id':'offline-v5-response','model':'MiniMax-M3','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
          'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'offline-tool','type':'function',
          'function':{'name':'submit_creative_json','arguments':json.dumps({'payload_json':'{}'})}}]}}]}
        return httpx.Response(200,json=body)
    monkeypatch.setattr(openai,'OpenAI',lambda **kwargs:native(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)))
    monkeypatch.setattr(client,'role_config',lambda role:RoleConfig('minimax','MiniMax-M3','https://api.minimaxi.com/v1','dummy-v5-offline-key'))
    return calls,state


def test_prepare_inherits_both_ledgers_and_exact_reviewed_script(continuation):
    calls,state=continuation;summary=runner.prepare();ctx=runner.context()
    assert not calls and summary['effective_calls_started']==71 and summary['effective_reported_tokens']==710117
    assert summary['unknown_token_reservations']==64010 and summary['inherited_pending_ordinals']==[70]
    assert runner.control.digest(ctx['raw_linear_script'])=='c38f75d6efa1a3a016458e7da8497bc987663b93b76d64be304c2d01c93bd090'
    assert runner.control.digest(ctx['reference_pack'])=='bdcf2cc65056e3903cadae8df9430d11a5a12ff55d20c0c4e1b94b291f2b6de1'
    assert len(runner.control.read(runner.ROOT/'CALL_LEDGER.json')['source_manifest'])==152


def test_original_unknown70_network_request_cannot_be_resent(continuation,monkeypatch):
    calls,state=continuation;runner.prepare()
    old=runner.control.read(runner.source.ROOT/'call_070_direction_s6_r2.json')['request']
    monkeypatch.setattr(runner.source,'wire',lambda *args,**kwargs:dict(old))
    with pytest.raises(RuntimeError,match='cannot resend'):runner.wire('writer',[],{},8000,{})
    assert not calls and not runner.control.read(runner.ROOT/'CALL_LEDGER.json')['calls']


def test_received_invalid_complete_document_is_not_adopted_or_repeated(continuation):
    calls,state=continuation;runner.prepare();receipt=runner.direction(1)
    assert receipt['status']=='contract_rejected' and len(calls)==1
    summary=runner.summary()
    assert summary['effective_calls_started']==72 and summary['effective_reported_tokens']==710122
    assert summary['unknown_token_reservations']==64010 and summary['calls_with_known_usage']==71
    assert runner.direction(1)==receipt and len(calls)==1
    verification=runner.control.read(runner.ROOT/'request_previews/direction_s6_r1_INPUT_VERIFICATION.json')
    assert verification['full_reference_pack_in_actual_messages'] and verification['raw_s6_script_unchanged']
    with pytest.raises(RuntimeError,match='latest stage is not valid'):runner.direction_source(1)


def test_new_unknown_call_blocks_later_dispatch_without_reusing_old_budget(continuation):
    calls,state=continuation;runner.prepare();state['timeout']=True
    receipt=runner.direction(1)
    assert receipt['status']=='outcome_unknown' and len(calls)==1
    assert runner.summary()['unknown_token_reservations']>64010
    assert runner.direction(1)==receipt and len(calls)==1
    with pytest.raises(RuntimeError,match='unknown outcome/usage'):runner.direction(2,feedback={'new_verified_requirement':'different request must stay blocked after unknown'})
    assert len(calls)==1 and runner.summary()['effective_reported_tokens']==710117
