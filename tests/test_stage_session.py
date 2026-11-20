import pytest
from src.content_factory.corpus_screenplay_v1 import freeze,read
from src.content_factory.novel_adaptation.stage_session import prepare,step,inspect


def setup(tmp_path):
    root=tmp_path/'session'
    prepare(root,[{'name':x,'success_states':['done'],'artifacts':['OUTPUT.json']} for x in ('author','review')],
            {'status':'done','pending':None,'calls_started':8,'reported_tokens':100},10)
    return root


def handler(folder,state,plan):
    folder.mkdir()
    freeze(folder/'OUTPUT.json',{'native':'unchanged'})
    freeze(folder/'STATE.json',{'status':'done','pending':None,'calls_started':state['calls_started']+1,
                               'reported_tokens':state['reported_tokens']+10})


def test_two_stages_resume_and_share_cumulative_budget(tmp_path):
    root=setup(tmp_path)
    assert step(root,{'author':handler})['calls_started']==9
    assert step(root,{'review':handler})['status']=='stages_complete_awaiting_acceptance'
    final=inspect(root);assert final['calls_started']==10 and final['reported_tokens']==120
    assert step(root,{})==final


def test_crash_after_native_completion_reuses_known_result_without_dispatch(tmp_path):
    root=setup(tmp_path)
    def crash(*args):handler(*args);raise RuntimeError('after native save')
    with pytest.raises(RuntimeError):step(root,{'author':crash})
    result=step(root,{})
    assert len(result['completed'])==1 and result['calls_started']==9


def test_unknown_or_missing_native_state_never_dispatches_again(tmp_path):
    root=setup(tmp_path)
    def crash(*args):raise RuntimeError('unknown')
    with pytest.raises(RuntimeError):step(root,{'author':crash})
    assert step(root,{'author':lambda *args:pytest.fail('must not retry')})['status']=='pending_execution_outcome'


def test_unknown_native_call_is_counted_without_claiming_zero_usage_or_retry(tmp_path):
    root=setup(tmp_path)
    def unknown(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'outcome_unknown','pending':9,
            'calls_started':9,'reported_tokens':100})
    result=step(root,{'author':unknown})
    assert result['calls_started']==9 and result['pending_stage']==0
    assert result['pending_call_id']==9 and result['usage_complete'] is False
    assert inspect(root)==result
    count=len(list((root/'journal').glob('*.json')))
    assert step(root,{'author':lambda *a:pytest.fail('must not retry')})==result
    assert len(list((root/'journal').glob('*.json')))==count


def test_running_native_accounting_cannot_exceed_session_ceiling(tmp_path):
    root=setup(tmp_path)
    def invalid(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'running','pending':11,
            'calls_started':11,'reported_tokens':100})
    with pytest.raises(ValueError,match='stage_accounting_invalid'):step(root,{'author':invalid})


def test_later_known_receipt_reconciles_original_stage_without_new_dispatch(tmp_path):
    import json
    root=setup(tmp_path)
    def waiting(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'running','pending':9,
            'calls_started':9,'reported_tokens':100})
    step(root,{'author':waiting})
    folder=root/'00_author'
    freeze(folder/'OUTPUT.json',{'native':'later original receipt'})
    # Simulate the same worker finishing, not a scheduler rewriting its record.
    (folder/'STATE.json').write_text(json.dumps({'status':'done','pending':None,
        'calls_started':9,'reported_tokens':112}),encoding='utf-8')
    result=step(root,{'author':lambda *a:pytest.fail('duplicate dispatch')})
    assert result['status']=='ready' and result['calls_started']==9
    assert result['reported_tokens']==112 and 'pending_call_id' not in result
    assert len(result['completed'])==1


def test_terminal_failure_not_retried_and_tampered_result_rejected(tmp_path):
    root=setup(tmp_path);step(root,{'author':handler})
    (root/'00_author'/'OUTPUT.json').write_text('{}')
    with pytest.raises(ValueError,match='artifact_changed'):step(root,{'review':handler})


def test_known_failure_is_terminal_and_preserves_call_usage(tmp_path):
    root=setup(tmp_path)
    def failed(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'needs_attention','pending':None,
            'calls_started':9,'reported_tokens':115})
    result=step(root,{'author':failed})
    assert result['status']=='needs_attention' and result['calls_started']==9
    assert step(root,{'author':lambda *a:pytest.fail('terminal retry')})==result


def test_failed_native_evidence_is_checked_on_subsequent_inspection(tmp_path):
    root=setup(tmp_path)
    def failed(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'needs_attention','pending':None,
            'calls_started':9,'reported_tokens':115})
        freeze(folder/'ERROR.json',{'message':'original failure'})
    result=step(root,{'author':failed})
    assert 'ERROR.json' in result['failure_evidence']['artifacts']
    (root/'00_author'/'ERROR.json').write_text('{"message":"hidden"}')
    with pytest.raises(ValueError,match='failed_stage_evidence_changed'):inspect(root)


def test_unknown_status_without_pending_id_never_becomes_known_failure(tmp_path):
    root=setup(tmp_path)
    def malformed(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'outcome_unknown','pending':None,
            'calls_started':9,'reported_tokens':100})
    result=step(root,{'author':malformed})
    assert result['status']=='pending_execution_outcome' and not result['usage_complete']
    assert result['pending_stage']==0
    with pytest.raises(ValueError,match='baseline_unsettled'):
        prepare(tmp_path/'invalid',[{'name':'a'}],{'status':'outcome_unknown','pending':None,
            'calls_started':9,'reported_tokens':100},10)
