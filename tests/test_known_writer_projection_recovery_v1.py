"""A failed Windows projection is recovered from existing native bytes only."""
from copy import deepcopy
from pathlib import Path
import runpy
import pytest
from src.content_factory import known_writer_projection_recovery_v1 as repair
H=runpy.run_path(str(Path(__file__).with_name('test_natural_director_pipeline_v10.py')))
pipe=H['pipe']; fx=H['fx']; F=H['F']

def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

@pytest.fixture
def failed_source(tmp_path,monkeypatch):
    canonical=tmp_path/'canonical'
    monkeypatch.setattr(pipe,'CANONICAL_REGISTRY',canonical)
    monkeypatch.setattr(pipe.parent,'CANONICAL_REGISTRY',canonical)
    monkeypatch.setattr(pipe.core,'_legacy_blocks',lambda *a,**kw:[])
    source=tmp_path/'source.txt'; source.write_text('A distinct complete seed for local publication recovery.',encoding='utf-8')
    run=tmp_path/'writer'; authorization=H['auth'](tmp_path,run)
    pipe.prepare_source(run,authorization_path=authorization,source_path=source,source_kind='original',title='Projection recovery case')
    original=Path.replace; fired=False
    def fail(path,target):
        nonlocal fired
        if path.name.startswith('.state-') and Path(target)==run/'state.json' and not fired:
            value=pipe.core._read(path)
            if value.get('stage')=='review_full':
                fired=True
                raise PermissionError('[WinError 5] access denied: '+str(path)+' -> '+str(target))
        return original(path,target)
    monkeypatch.setattr(Path,'replace',fail)
    client=fx.FakeClients([F['success_values']()[0]])
    with pytest.raises(PermissionError): pipe.execute_writer_only(run,clients=client)
    assert len(client.calls)==1 and len(list(run.glob('STATE_*.json')))==5
    assert pipe.core._read(run/'state.json')['status']=='needs_attention'
    return run

def test_readonly_plan_proves_exact_native_and_existing_review_snapshot(failed_source):
    run=failed_source; before=snapshot(run); plan=repair.plan_recovery(run)
    assert plan['status']=='local_recovery_proven' and plan['reported_tokens']==100
    assert plan['target_state']==pipe.core._read(run/'STATE_00004.json')
    assert plan['target_state']['stage']=='review_full' and plan['model_calls_authorized'] is False
    assert snapshot(run)==before

def test_append_checkpoint_preserves_all_history_and_never_calls_writer(failed_source):
    run=failed_source; before=snapshot(run); plan=repair.plan_recovery(run)
    result=repair.apply_recovery(run,reviewed_plan=plan)
    assert result['stage']=='review_full' and result['calls_started']==1 and result['reported_tokens']==100
    assert result['model_calls_started']==0 and (run/'STATE_00006.json').exists()
    for name,raw in before.items():
        if name!='state.json': assert (run/name).read_bytes()==raw
    assert pipe.parent._verify(run)[1]['active']['writer_full']
    client=fx.FakeClients([fx.result(fx.review(),'director')])
    view=pipe.execute_writer_only(run,clients=client)
    assert view['writer_ready'] and view['calls_started']==2 and view['known_reported_tokens']==200
    assert [v['role'] for v in client.calls]==['director']

def test_same_recovery_is_idempotent_before_source_advances(failed_source):
    run=failed_source; plan=repair.plan_recovery(run)
    first=repair.apply_recovery(run,reviewed_plan=plan); before=snapshot(run)
    second=repair.apply_recovery(run,reviewed_plan=plan)
    assert first==second and snapshot(run)==before

@pytest.mark.parametrize('target',['DRAFT_001.md','RESPONSE_001.json','STATE_00004.json'])
def test_changed_native_draft_or_existing_target_blocks_without_writes(failed_source,target):
    run=failed_source; path=run/target
    if target=='STATE_00004.json':
        data=pipe.core._read(path); data['stage']='director_full'
        path.write_text(__import__('json').dumps(data),encoding='utf-8')
    else: path.write_bytes(path.read_bytes()+b' ')
    before=snapshot(run)
    with pytest.raises((ValueError,OSError)): repair.plan_recovery(run)
    assert snapshot(run)==before and not (run/repair.RECORD).exists()

def test_reviewed_plan_change_cannot_apply(failed_source):
    run=failed_source; plan=repair.plan_recovery(run); plan['calls_started']=0; before=snapshot(run)
    with pytest.raises(ValueError,match='变化'): repair.apply_recovery(run,reviewed_plan=plan)
    assert snapshot(run)==before

def test_repeated_local_replace_failure_can_finish_existing_sixth_checkpoint(failed_source,monkeypatch):
    run=failed_source; plan=repair.plan_recovery(run); original=Path.replace; fired=False
    def fail(path,target):
        nonlocal fired
        if path.name.startswith('.state-') and Path(target)==run/'state.json' and not fired:
            fired=True
            raise PermissionError('local replace failed again')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',fail)
    with pytest.raises(PermissionError): repair.apply_recovery(run,reviewed_plan=plan)
    assert (run/'STATE_00006.json').exists() and (run/repair.RECORD).exists()
    monkeypatch.setattr(Path,'replace',original)
    result=repair.apply_recovery(run,reviewed_plan=plan)
    assert result['status']=='recovered' and result['calls_started']==1
    assert len(list(run.glob('REQUEST_*.json')))==1

def test_other_stop_reason_is_not_reclassified_as_local_failure(failed_source):
    run=failed_source; s=pipe.core._read(run/'STATE_00005.json'); s['halt_reason']='Native content rejected'
    for name in ('STATE_00005.json','state.json'):
        (run/name).write_text(__import__('json').dumps(s),encoding='utf-8')
    with pytest.raises(ValueError): repair.plan_recovery(run)
