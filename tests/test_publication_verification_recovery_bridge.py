from types import SimpleNamespace as NS
import pytest

from test_publication_verification_recovery import incident, queue, execute
from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import browser_boot_recovery as boot
from src.operations_accounts.browser_control import BrowserControlDeferred, BrowserControlRejected


def test_backend_pump_queues_only_read_verifier_and_recovers_prior_boot_fence(incident, monkeypatch):
    i = incident
    with i.store._db(write=True)as db:
        db.execute('UPDATE browser_control_owners SET heartbeat=500,updated_at=500')
    monkeypatch.setattr(boot,'_boot_evidence',lambda:{'boot_time':900,'backend_pid':456,'backend_create_time':950})
    monkeypatch.setattr(bridge,'enabled',lambda:True)
    monkeypatch.setattr(bridge,'_store',lambda:i.store)
    monkeypatch.setattr(bridge,'binding_version',lambda context:'binding')
    monkeypatch.setattr(bridge,'_hosts',{})
    runtime=NS(resolve=lambda *a,**kw:i.context,
        profiles=NS(list_active=lambda:[NS(account_uuid='account:a',account_key='novel')]))
    monkeypatch.setattr(bridge,'_runtime',lambda:runtime)
    starts=[]
    monkeypatch.setattr(bridge.threading,'Thread',lambda **kw:NS(start=lambda:starts.append(kw)))
    assert bridge.pump_pending()==1 and starts[0]['args']==('novel',)
    assert i.store.get(i.original['command_id'])==i.original
    assert boot.read_owner(i.store,'account:a')['state']=='released'
    assert [r['kind']for r in i.store.snapshot('account:a')['commands'] if r['state']=='queued']==['publication_verify']


@pytest.mark.parametrize('gate',['paused','disabled','foreign_lease','binding_changed','human_window'])
def test_readonly_pause_exception_retains_all_other_admission_gates(incident, monkeypatch, gate):
    from src.operations_accounts.runtime import AccountRuntimeContext
    i=incident
    queued=queue(i)
    command=i.store.claim_next('account:a','binding','backend:123:abc',1)
    i.context=AccountRuntimeContext(profile=NS(account_key='novel',account_uuid='account:a',status='disabled'if gate=='disabled'else'active'),
        binding=i.context.binding,browser_environment_key='env',browser_profile_dir='profile',storage_state_path='state')
    i.context.binding.status='active'
    state=NS(lock_owner='foreign'if gate=='foreign_lease'else'',day_key='',daily_runs=0,circuit_open_until='')
    runtime=NS(resolve=lambda *a,**kw:i.context,profiles=NS(get=lambda _:i.context.profile),
               bindings=NS(get_runtime_state=lambda _:state,get=lambda _:i.context.binding))
    resource=NS(context=i.context,runtime=runtime,account_key='novel',manual_tasks={'open':'tab'}if gate=='human_window'else{},console_tasks={})
    ctx=NS(resource=resource,command=command,actor=NS(store=i.store),account_id='account:a',binding_version='binding')
    monkeypatch.setattr(bridge,'binding_version',lambda context:'other'if gate=='binding_changed'else'binding')
    monkeypatch.setattr(bridge,'_legacy_manual_gate',lambda context:None)
    monkeypatch.setattr(bridge,'_controls',lambda context:{'state':'paused'})
    if gate=='paused':
        bridge._admission(ctx,'start')
        bridge._admission(ctx,'dispatch')
    else:
        with pytest.raises((BrowserControlRejected,BrowserControlDeferred)):
            bridge._admission(ctx,'start')


@pytest.mark.parametrize('completed',[False,True])
def test_dashboard_reports_actual_verification_and_local_projection_separately(incident,monkeypatch,completed):
    from src.web import account_exception_notice as notice
    from src.operations_accounts.publication_verification_recovery import public_status
    i=incident
    if completed:
        execute(i,monkeypatch)
        with i.store._db(write=True)as db:
            db.execute("UPDATE publication_verified_work_outbox SET error_code='ValueError'")
    else:
        queue(i)
    monkeypatch.setenv('ACCOUNT_BROWSER_CONTROL_DB',str(i.store.path))
    monkeypatch.setattr(bridge,'_store',lambda:i.store)
    messages=[]
    for method in ['info','warning','caption']:
        monkeypatch.setattr(notice.st,method,lambda value:messages.append(value))
    notice._render_publication_recovery_status()
    joined='\n'.join(messages)
    if completed:
        assert '已确认作品 123456' in joined and '本地作品对应失败' in joined and '无需重新发布' in joined
    else:
        assert '第 1 次作品补查已登记' in joined and '已确认作品' not in joined
    summary=str(public_status(i.store))
    assert '原批准评论' not in summary and str(i.journal) not in summary and '唯一原作品' not in summary
