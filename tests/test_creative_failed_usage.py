from types import SimpleNamespace as NS
import json
import pytest
import src.content_factory.creative_workflow_roles as roles
from scripts.reconcile_creative_failure_usage import reconcile
import scripts.run_three_cycle_text_production as runner


def test_truncated_provider_response_preserves_safe_usage(monkeypatch):
    import openai
    response = NS(id='paid-response',model='MiniMax-M3',usage=NS(total_tokens=24569,prompt_tokens=None,completion_tokens=None),
                  choices=[NS(finish_reason='length',message=NS(content=None,tool_calls=[]))])
    monkeypatch.setattr(roles,'role_config',lambda _: roles.RoleConfig('minimax','MiniMax-M3','https://fixture.invalid','fixture'))
    monkeypatch.setattr(openai,'OpenAI',lambda **_: NS(chat=NS(completions=NS(create=lambda **_:response))))
    with pytest.raises(roles.RoleResponseError) as captured:
        roles.CreativeRoleClients().call('writer',[],thinking='adaptive',structured_schema={'type':'object'})
    meta=captured.value.response_metadata
    assert meta['total_tokens']==24569 and meta['response_id']=='paid-response'
    assert meta['finish_reason']=='length'
    assert 'prompt_tokens' not in meta and 'completion_tokens' not in meta


def test_workflow_failure_and_historical_reconciliation_count_once(tmp_path):
    from src.content_factory.creative_workflow import CreativeWorkflow
    class Failed:
        def call(self,*args,**kwargs):
            raise roles.RoleResponseError('failed',{'response_id':'paid-response','total_tokens':24569})
    workflow=CreativeWorkflow(tmp_path,clients=Failed())
    workflow.state={'calls_started':1};workflow._active_stage_name='director_state_plan__00'
    with pytest.raises(roles.RoleResponseError): workflow._call_model('writer',[])
    assert workflow._reported_tokens()==24569
    path=tmp_path/'director_state_plan__00.json'
    original=json.dumps({'error':'writer API missing; response_id=paid-response; total_tokens=24569'}).encode()
    path.write_bytes(original)
    reconcile(path);reconcile(path)
    assert path.read_bytes()==original
    assert workflow._reported_tokens()==24569
    runner._write(tmp_path/'success.json',{'response_metadata':{'response_id':'another','total_tokens':2724}})
    assert workflow._reported_tokens()==27293


def test_archived_paid_receipts_remain_in_budget_and_duplicate_ids_count_once(tmp_path):
    from src.content_factory.creative_workflow import CreativeWorkflow
    workflow = CreativeWorkflow(tmp_path, clients=NS())
    workflow.state = {"calls_started": 3}
    old = {"response_metadata": {"response_id": "old-paid", "total_tokens": 19000}}
    latest = {"response_metadata": {"response_id": "new-paid", "total_tokens": 7000},
              "prior_attempts": [{"response_metadata": {"response_id": "prior-paid", "total_tokens": 5000}}]}
    (tmp_path / "old.json").write_text(json.dumps(old), encoding="utf-8")
    (tmp_path / "new.json").write_text(json.dumps(latest), encoding="utf-8")
    assert workflow._reported_tokens() == 31000
    archive = tmp_path / "history" / "failed_plan"
    archive.mkdir(parents=True)
    (tmp_path / "old.json").replace(archive / "old.json")
    assert workflow._reported_tokens() == 31000
    (archive / "copy.json").write_text(json.dumps(latest), encoding="utf-8")
    assert workflow._reported_tokens() == 31000
    workflow._save()
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["reported_tokens"] == 31000
