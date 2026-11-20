"""Real private broker/ledger/coordinator/ManagedGuard; adapter IO only is fake."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time
from types import SimpleNamespace as NS

import pytest
from test_fanqie_backfill_v2 import trial,Adapter,put,no_external

from src.operations_accounts import fanqie_preupload_resume_v1 as api
from src.operations_accounts.browser_control import BrowserControlActor,BrowserCommandResult,BrowserControlRejected
from src.operations_accounts.fanqie_backfill_control import ManagedFanqieGuard,make_backfill_handler
from src.services.fanqie_backfill_coordinator import BackfillCoordinator
from src.services.fanqie_backfill_workflow import BackfillBlocked


@pytest.fixture
def case(trial):
    t=trial;ledger,store,bid=t['ledger'],t['control'],t['bid']
    coordinator=BackfillCoordinator(ledger,store.path,require_strict_contract=True)
    ledger.enqueue(bid);old=ledger.dispatch(bid,store)
    probe=lambda:dict(platform_identity_key='uid:test',verified=True,challenge=False,observed_at=time.time())
    class Mixed(Adapter):
        def observe(self,b):
            value=super().observe(b);value['items'][0]['fill_status']='未填写 回填发文';return value
    before_adapter=Mixed()
    def before_handler(ctx,payload):
        guard=ManagedFanqieGuard(ctx,t['accounts'].bindings(),ledger,probe,accounts=t['accounts'],environment=t['env'])
        try:coordinator.execute(bid,adapter=before_adapter,guard=guard)
        except BackfillBlocked as error:return BrowserCommandResult('failed',dict(reason=str(error),confirmed=False))
        pytest.fail('Original mixed status must fail before upload')
    actor=BrowserControlActor(store,'fanqie:test','fv1','original-worker',{'fanqie_backfill':before_handler})
    actor.start();result=actor.run_next();actor.close()
    assert result['state']=='failed' and result['result']['reason']==api.REASON
    assert before_adapter.uploads==before_adapter.submits==0
    baseline=api._state(ledger,bid);row=baseline['row']
    authority=put(t['tmp']/'parent.json',dict(schema='fanqie_production_trial_user_authorization/v1',user_statement='完整两分钟发布并回填',
        authorized_target=dict(media=t['media'],douyin_account_key='novel_test',book_id=json.loads(row['manifest_json'])['binding']['book_id'])))
    causal=put(t['tmp']/'causal.json',dict(schema=api.CAUSE,
        classification='known_pre_upload_local_guard_failure; not uncertain external upload/submit',
        binding=dict(binding_uuid=bid,status='ready',attempt_count=0),contract={k:row[k] for k in ('business_key','manifest_sha','revision','batch_id')},
        outbox=dict(command_id=old['command_id']),actual_native_row=dict(fill_status='未填写 回填发文',published_links=[]),
        artifacts=dict(raw=put(t['tmp']/'raw-before.json',{'fill_status':'未填写 回填发文'}))))
    fix_source=t['tmp']/'reviewed_fix.py';fix_source.write_text('# reviewed status extraction fixture')
    fix=put(t['tmp']/'fix.json',dict(schema='fanqie_fill_status_fix_acceptance/v1',accepted=True,
        sources=[api.reference(fix_source)],tests=[put(t['tmp']/'fix-test.json',{'passed':True})]))
    def prepare(directory='successor',**change):
        args=dict(authority_ref=authority,causal_ref=causal,fix_acceptance_ref=fix,
            output_directory=t['tmp']/directory,ledger=ledger,store=store);args.update(change)
        return api.prepare(bid,old['command_id'],**args)
    def execute(plan,adapter):
        command=api.enqueue(plan,ledger=ledger,store=store)
        handler=make_backfill_handler(coordinator,t['accounts'].bindings(),lambda ctx:adapter,
            lambda ctx:probe,accounts=t['accounts'],environment=t['env'])
        owner=BrowserControlActor(store,'fanqie:test','fv1','new-worker',{'fanqie_backfill':handler})
        owner.start();value=owner.run_next();owner.close()
        return command,value
    return dict(t=t,ledger=ledger,store=store,bid=bid,old=store.get(old['command_id']),baseline=baseline,
        prepare=prepare,execute=execute,fix_source=fix_source,authority=authority,causal=causal)


def test_real_coordinator_and_guard_allow_one_complete_upload_and_preserve_old_outbox(case):
    x=case;p=x['prepare']();adapter=Adapter();command,result=x['execute'](p,adapter)
    assert result['state']=='succeeded' and result['result']['confirmed'] is True
    assert adapter.uploads==adapter.submits==1 and x['ledger'].get(x['bid'])['attempt_count']==1
    current=api._state(x['ledger'],x['bid'])
    assert current['outbox']==x['baseline']['outbox'] and x['store'].get(x['old']['command_id'])==x['old']
    assert current['events'][:2]==x['baseline']['events']
    assert api.enqueue(p,ledger=x['ledger'],store=x['store'])['command_id']==command['command_id']
    with pytest.raises(BrowserControlRejected):x['prepare']('no-new-slot')


def test_real_guard_accepts_same_attempt_business_unknown_completion_but_never_replays(case):
    x=case;p=x['prepare']();adapter=Adapter(fail='upload',readback=False)
    command,result=x['execute'](p,adapter)
    assert x['ledger'].get(x['bid'])['status']=='outcome_unknown'
    assert result['state']=='succeeded' and result['result']['confirmed'] is False
    assert result['result']['backfill_status']=='outcome_unknown' and adapter.uploads==1
    assert api.enqueue(p,ledger=x['ledger'],store=x['store'])['command_id']==command['command_id']
    with pytest.raises(BrowserControlRejected):x['prepare']('no-unknown-replay')


def test_concurrent_public_enqueue_returns_same_named_successor_only(case):
    x=case;p=x['prepare']()
    def enqueue(_):return api.enqueue(p,ledger=x['ledger'],store=x['store'])
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(enqueue,range(2)))
    assert len({r['command_id'] for r in results})==1
    with x['store']._db() as db:
        assert db.execute("SELECT count(*) FROM browser_control_commands WHERE idempotency_key LIKE 'preupload-resume:%'").fetchone()[0]==1
    assert api._state(x['ledger'],x['bid'])==x['baseline']


@pytest.mark.parametrize('change',['old_unknown','upload_started','manifest','authorization','old_changed','fix_changed','other_live','causal_changed'])
def test_unsafe_or_changed_original_baseline_cannot_enqueue(case,change):
    x=case;p=x['prepare']();ledger,store=x['ledger'],x['store']
    if change=='upload_started':ledger.transition(x['bid'],1,'upload_started',{})
    elif change=='fix_changed':x['fix_source'].write_text('# changed after review')
    elif change=='causal_changed':Path(x['causal']['path']).write_text('{}')
    elif change in ('manifest','authorization'):
        with ledger._db(True) as db:db.execute('UPDATE fanqie_backfill_contracts SET '+('manifest_sha' if change=='manifest' else 'authorization_json')+"='changed' WHERE binding_uuid=?",(x['bid'],))
    elif change=='other_live':store.submit('fanqie:test','fv1','fanqie_login','other-manual',{},10)
    else:
        with store._db(write=True) as db:
            db.execute('UPDATE browser_control_commands SET '+("state='outcome_unknown'" if change=='old_unknown' else 'updated_at=updated_at+1')+' WHERE command_id=?',(x['old']['command_id'],))
    with pytest.raises((BrowserControlRejected,ValueError,KeyError)):api.enqueue(p,ledger=ledger,store=store)


def test_another_plan_for_same_baseline_cannot_consume_second_successor_slot(case):
    x=case;p=x['prepare']();q=x['prepare']('same-baseline-other-plan')
    assert api.read(p)['idempotency_key']==api.read(q)['idempotency_key']
    first=api.enqueue(p,ledger=x['ledger'],store=x['store'])
    with pytest.raises((BrowserControlRejected,ValueError)):api.enqueue(q,ledger=x['ledger'],store=x['store'])
    assert api.enqueue(p,ledger=x['ledger'],store=x['store'])['command_id']==first['command_id']
