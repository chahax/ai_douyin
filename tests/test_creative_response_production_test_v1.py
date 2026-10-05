from pathlib import Path
import json
import httpx,openai,pytest
from scripts import run_creative_response_production_test_v1 as live
from scripts import creative_evidenced_role_clients_v1 as client
from src.content_factory.creative_workflow_roles import RoleConfig

@pytest.fixture
def live_case(tmp_path,monkeypatch):
    project=Path(__file__).resolve().parents[1];root=tmp_path/'live_test'
    calls=[];native=openai.OpenAI
    inner={'probe_id':'receive_layer_20261005_v1','status':'received',
      'items':[{'stimulus':'方澄明确说今晚不行','reaction':'林屿停住并收回笔'}]}
    body={'id':'mock-probe-001','model':'MiniMax-M3','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
      'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'mock-tool-1','type':'function',
        'function':{'name':'submit_creative_json','arguments':json.dumps({'payload_json':json.dumps(inner,ensure_ascii=False)},ensure_ascii=False)}}]}}]}
    def handler(request):
        calls.append(json.loads(request.content));return httpx.Response(200,headers={'x-request-id':'mock-http-probe'},json=body)
    monkeypatch.setattr(openai,'OpenAI',lambda **kwargs:native(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)))
    monkeypatch.setattr(client,'role_config',lambda role:RoleConfig('minimax','MiniMax-M3','https://api.minimaxi.com/v1','dummy-probe-test-key'))
    return project,root,calls


def test_prepare_is_offline_and_preserves_unknown_parent(live_case):
    project,root,calls=live_case
    runtime,wire,parent=live.prepare(project,root)
    assert not calls and runtime.summary()['new_calls']==0
    assert runtime.inherited['unknown_token_reservations']==64010 and runtime.inherited['pending_ordinals']==[70]
    assert live.read(root/'PRODUCTION_TEST_AUTHORIZATION.json')['max_new_calls']==1
    assert wire['parameters']['max_completion_tokens']==1024


def test_one_request_with_usage_inherits_pending_70_and_caches(live_case):
    project,root,calls=live_case
    result=live.execute(project,root)
    assert result['test_document_valid'] and result['effective_calls_started']==71
    assert result['effective_reported_tokens']==709277 and result['unknown_token_reservations']==64010
    assert result['calls_with_known_usage']==70 and not result['original_call70_recovered']
    again=live.execute(project,root)
    assert len(calls)==1 and again['effective_reported_tokens']==709277
    assert not result['creative_quality_passed'] and not result['production_continuation_ready']


def test_scope_rejects_changed_request_and_additional_label(live_case):
    project,root,calls=live_case
    runtime,wire,parent=live.prepare(project,root)
    with pytest.raises(RuntimeError,match='single authorized'):runtime.dispatch('other',wire,live.validate)
    wire['parameters']['max_completion_tokens']=2048
    with pytest.raises(RuntimeError,match='single authorized'):runtime.dispatch(live.LABEL,wire,live.validate)
    assert not calls and not live.read(root/'CALL_LEDGER.json')['calls']
