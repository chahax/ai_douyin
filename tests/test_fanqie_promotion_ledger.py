import hashlib
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_fanqie_backfill_workflow import setup, snapshot, Adapter, URL
from src.services.fanqie_backfill_workflow import BackfillBlocked, digest, read_publication
from src.services.fanqie_promotion_ledger import PromotionLedger, migrate_ledger
from src.services.fanqie_backfill_coordinator import BackfillCoordinator
from src.services.publication_evidence import PublicationEvidenceReader
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected
from src.operations_accounts.platform_bindings import PlatformBindingRepository, install_platform_binding_schema


@pytest.fixture
def ledger(tmp_path, setup):
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE fanqie_books(id INTEGER PRIMARY KEY,fanqie_book_id TEXT);
        CREATE TABLE fanqie_promotion_tasks(id INTEGER PRIMARY KEY,task_uuid TEXT UNIQUE,book_id INTEGER,platform_task_id TEXT,promotion_alias TEXT,publish_type TEXT);
        CREATE TABLE fanqie_publish_records(id INTEGER PRIMARY KEY,task_id INTEGER,douyin_video_id TEXT UNIQUE,douyin_video_url TEXT UNIQUE);
        CREATE TABLE fanqie_bindings(id INTEGER PRIMARY KEY,binding_uuid TEXT UNIQUE,task_id INTEGER,publish_id INTEGER,status TEXT,attempt_count INTEGER,submitted_url TEXT,field_contract_json TEXT,idempotency_key TEXT,created_at TEXT);
        CREATE TABLE fanqie_operation_events(event_uuid TEXT PRIMARY KEY,task_id INTEGER,event_type TEXT,from_status TEXT,to_status TEXT,actor_type TEXT,actor_id TEXT,payload_json TEXT,created_at TEXT,audit_artifact_hash TEXT);
        ''')
        b = setup[0]
        db.execute("INSERT INTO fanqie_books VALUES(1,?)", (b.book_id,))
        db.execute("INSERT INTO fanqie_promotion_tasks VALUES(1,'task-1',1,'alias-1',?,'AIGC')", (b.alias,))
        db.execute("INSERT INTO fanqie_publish_records VALUES(1,1,?,?)", (URL.rsplit('/',1)[1], URL))
    migrate_ledger(path, tmp_path / "before.db")
    store = PromotionLedger(path)
    contract = dict(fanqie_resource_id="fanqie:test", fanqie_binding_version="v1", alias_id="alias-1", platform_task_id="alias-1",
                    promotion_path="fixture-path", account_link_version="v1", identity_evidence="fixture-identity",
                    publication_metadata_evidence="fixture-metadata")
    bid = store.register(1, 1, setup[3], contract)
    return store, bid, contract


def authorize(ledger):
    store, bid, _ = ledger
    store.authorize(bid, manifest_sha=store.get(bid)["manifest_sha"], reference="fixture-user-grant")


class GovernedAdapter(Adapter):
    def __init__(self, b, *, accepted=False, **kwargs):
        super().__init__(b, **kwargs)
        self.accepted = accepted
    def observe(self, b):
        return snapshot(b, alias_id="alias-1", promotion_path="fixture-path",
                        published_links=[URL] if self.submits and self.confirmed else [])
    def upload(self, path, b):
        super().upload(path, b)
        return {"upload_ready": True, "source": "fixture"}
    def submit(self, b):
        super().submit(b)
        return {"accepted": True, "batch_id": "batch-1"} if self.accepted else None


class Guard:
    def check(self, contract):
        pass


def test_migration_preserves_original_rows_and_backup(ledger, tmp_path):
    store, _, _ = ledger
    with sqlite3.connect(tmp_path / "before.db") as old, sqlite3.connect(store.path) as new:
        for name in ['fanqie_books','fanqie_promotion_tasks','fanqie_publish_records']:
            assert old.execute(f'SELECT * FROM {name}').fetchall() == new.execute(f'SELECT * FROM {name}').fetchall()
    with pytest.raises(BackfillBlocked): migrate_ledger(store.path, tmp_path / "before.db")


def test_constructor_never_creates_missing_database(tmp_path):
    path = tmp_path / 'absent.db'
    with pytest.raises(sqlite3.OperationalError): PromotionLedger(path)
    assert not path.exists()


def test_registration_idempotent_and_cross_task_conflict(ledger, setup):
    store, bid, contract = ledger
    assert store.register(1,1,setup[3],contract) == bid
    with pytest.raises(BackfillBlocked): store.register(1,1,setup[3],dict(contract,promotion_path='changed'))


def test_legacy_binding_not_adopted(ledger, setup):
    store, bid, contract = ledger
    with sqlite3.connect(store.path) as db:
        db.execute('DELETE FROM fanqie_backfill_contracts')
    with pytest.raises(BackfillBlocked, match='legacy_backfill'): store.register(1,1,setup[3],contract)


def test_unapproved_preparation_cannot_queue_or_execute(ledger, setup):
    store, bid, _ = ledger
    with pytest.raises(BackfillBlocked): store.enqueue(bid)
    a = GovernedAdapter(setup[0])
    with pytest.raises(BackfillBlocked): BackfillCoordinator(store,setup[1]).execute(bid,adapter=a,guard=Guard())
    assert a.uploads == a.submits == 0


def test_authorization_binds_registered_version(ledger):
    store,bid,_=ledger
    with pytest.raises(BackfillBlocked): store.authorize(bid,manifest_sha='wrong',reference='grant')
    authorize(ledger)
    authorize(ledger)
    assert store.get(bid)['revision']==1


def test_one_cas_winner_for_concurrent_workers(ledger):
    authorize(ledger)
    store,bid,_=ledger
    def claim(_):
        try:
            store.transition(bid,1,'upload_started',{})
            return True
        except BackfillBlocked:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim,range(2))) == [False,True]
    assert store.get(bid)['attempt_count']==1


def test_outbox_recovers_crash_after_control_submit(ledger,tmp_path):
    authorize(ledger)
    store,bid,_=ledger
    control=BrowserControlStore(tmp_path/'control.db')
    store.enqueue(bid)
    first=store.dispatch(bid,control)
    with sqlite3.connect(store.path) as db:
        db.execute('UPDATE fanqie_dispatch_outbox SET command_id=NULL')
    second=store.dispatch(bid,control)
    assert first['command_id']==second['command_id']
    assert len(control.snapshot('fanqie:test')['commands'])==1


@pytest.mark.parametrize('accepted,expected',[(True,'verify_pending'),(False,'outcome_unknown')])
def test_accepted_pending_is_distinct_from_unknown(ledger,setup,accepted,expected):
    authorize(ledger)
    store,bid,_=ledger
    a=GovernedAdapter(setup[0],confirmed=False,accepted=accepted)
    service=BackfillCoordinator(store,setup[1])
    assert service.execute(bid,adapter=a,guard=Guard())['status']==expected
    with pytest.raises(BackfillBlocked):service.execute(bid,adapter=a,guard=Guard())
    assert a.uploads==a.submits==1
    with sqlite3.connect(store.path) as db:
        states=[r[0] for r in db.execute('SELECT to_status FROM fanqie_operation_events ORDER BY rowid')]
    assert states[:5]==['prepared','ready','upload_started','uploaded','submit_started']


@pytest.mark.parametrize('fail',['upload','submit'])
def test_interrupted_external_actions_never_replayed(ledger,setup,fail):
    authorize(ledger)
    store,bid,_=ledger
    a=GovernedAdapter(setup[0],fail=fail)
    service=BackfillCoordinator(store,setup[1])
    assert service.execute(bid,adapter=a,guard=Guard())['status']=='outcome_unknown'
    before=(a.uploads,a.submits)
    a.observe=lambda b:snapshot(b,alias_id='alias-1',promotion_path='fixture-path',published_links=[URL])
    assert service.reconcile(bid,adapter=a,guard=Guard())['status']=='confirmed'
    assert service.reconcile(bid,adapter=a,guard=Guard())['status']=='confirmed'
    assert before==(a.uploads,a.submits)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM fanqie_operation_events WHERE to_status='outcome_unknown'").fetchone()[0]==1


def test_full_success_then_restart_no_resubmit(ledger,setup):
    authorize(ledger)
    store,bid,_=ledger
    a=GovernedAdapter(setup[0])
    assert BackfillCoordinator(store,setup[1]).execute(bid,adapter=a,guard=Guard())['status']=='confirmed'
    with pytest.raises(BackfillBlocked): BackfillCoordinator(PromotionLedger(store.path),setup[1]).execute(bid,adapter=a,guard=Guard())
    assert a.uploads==a.submits==1


def test_stable_alias_and_path_required_before_upload(ledger,setup):
    authorize(ledger)
    store,bid,_=ledger
    a=GovernedAdapter(setup[0]);a.observe=lambda b:snapshot(b)
    with pytest.raises(BackfillBlocked,match='stable_promotion'):BackfillCoordinator(store,setup[1]).execute(bid,adapter=a,guard=Guard())
    assert a.uploads==0


def test_mutable_command_metadata_does_not_change_publication_identity(setup):
    b,path,*_=setup
    before=read_publication(path,b)
    with sqlite3.connect(path) as db:
        db.execute('ALTER TABLE browser_control_commands ADD COLUMN updated_at REAL')
        db.execute('UPDATE browser_control_commands SET updated_at=12345')
    assert read_publication(path,b)==before


def test_reconciled_publication_requires_native_hash_and_matching_command(setup,tmp_path):
    b,path,*_=setup
    rid='b'*32
    proof=dict(post_verified=True,post_id=URL.rsplit('/',1)[1],publish_url=URL)
    outcome=dict(status='verified_published',publish_evidence=proof,comment={'status':'not_requested'})
    frozen=dict(schema='publication_reconciliation_evidence/20261019/v1',account_uuid=b.douyin_account_uuid,
                original_command_id=b.publication_command_id,reconciliation_command_id=rid,result=outcome)
    evidence=tmp_path/'proof.json';evidence.write_text(json.dumps(frozen),encoding='utf8')
    old=dict(command_id=b.publication_command_id,account_id=b.douyin_account_uuid,binding_version=b.binding_version,kind='publish',state='outcome_unknown')
    resolved=dict(status='published',success=True,original_unknown_snapshot=old,reconciliation_command_id=rid,
                  reconciliation_evidence=dict(path=str(evidence),sha256=hashlib.sha256(evidence.read_bytes()).hexdigest()),**proof)
    outcome['evidence_ref']=resolved['reconciliation_evidence']
    with sqlite3.connect(path) as db:
        db.execute('UPDATE browser_control_commands SET result=?',(json.dumps(resolved),))
        db.execute('INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?)',(rid,b.douyin_account_uuid,b.binding_version,'publication_reconcile','succeeded',json.dumps(outcome)))
    reader=PublicationEvidenceReader(path,evidence_root=tmp_path)
    assert reader.read(b.publication_command_id,b.douyin_account_uuid,b.binding_version)['publish_url']==URL
    evidence.write_text('{}')
    with pytest.raises(ValueError,match='changed'):reader.read(b.publication_command_id,b.douyin_account_uuid,b.binding_version)


@pytest.fixture
def identities(tmp_path):
    control=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    install_platform_binding_schema(control.path,tmp_path/'control.before.db')
    root=tmp_path/'evidence';root.mkdir()
    profiles=tmp_path/'profiles'
    def save(name,value):
        path=root/name;path.write_text(json.dumps(value),encoding='utf8')
        return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    live=dict(schema='platform_identity_probe/v1',platform='fanqie',verified=True,challenge=False,
              platform_identity_key='stable-1',environment_key='env-1',identity_source='platform_account_id',observed_at=1000)
    confirmation=dict(schema='platform_identity_confirmation/v1',platform='fanqie',resource_id='fanqie:test',
        platform_identity_key='stable-1',binding_version='v1',environment_key='env-1',profile_dir=str(profiles/'test'),
        decision_source='explicit_user_confirmation',user_statement='fixture confirmation',probe_evidence=save('probe.json',live))
    repo=PlatformBindingRepository(control.path,evidence_root=root,profile_root=profiles,clock=lambda:1000)
    return repo,control,save,confirmation,live


def test_platform_binding_and_generation_guard(identities):
    repo,control,save,confirmation,live=identities
    reference=save('confirmation.json',confirmation)
    assert repo.confirm(reference)['platform_identity_key']=='stable-1'
    assert repo.confirm(reference)['resource_id']=='fanqie:test'
    control.acquire_owner('fanqie:test','v1','owner-1')
    assert repo.guard('fanqie:test','v1','owner-1',1,live)['environment_key']=='env-1'
    with pytest.raises(BrowserControlRejected):repo.guard('fanqie:test','v1','owner-1',2,live)
    with pytest.raises(BrowserControlRejected):repo.guard('fanqie:test','v1','owner-1',1,dict(live,platform_identity_key='other'))


@pytest.mark.parametrize('change',[{'identity_source':'nickname'},{'challenge':True},{'observed_at':0},{'verified':False}])
def test_identity_not_inferred_from_nickname_or_stale_page(identities,change):
    repo,_,save,confirmation,live=identities
    confirmation['probe_evidence']=save('probe-new.json',dict(live,**change))
    with pytest.raises(BrowserControlRejected):repo.confirm(save('confirmation.json',confirmation))
    assert repo.get('fanqie:test') is None


def test_expired_task_can_be_reconciled_without_new_submission(ledger,setup):
    authorize(ledger)
    store,bid,_=ledger
    store.transition(bid,1,'upload_started',{})
    a=GovernedAdapter(setup[0]);a.observe=lambda b:snapshot(b,alias_id='alias-1',promotion_path='fixture-path',
        alias_status='强制失效',published_links=[URL])
    row=BackfillCoordinator(store,setup[1]).reconcile(bid,adapter=a,guard=Guard())
    assert row['status']=='confirmed' and a.uploads==a.submits==0


def test_existing_link_is_durably_closed_without_upload(ledger,setup):
    authorize(ledger)
    store,bid,_=ledger
    a=GovernedAdapter(setup[0]);a.observe=lambda b:snapshot(b,alias_id='alias-1',promotion_path='fixture-path',published_links=[URL])
    assert BackfillCoordinator(store,setup[1]).execute(bid,adapter=a,guard=Guard())['status']=='confirmed'
    assert a.uploads==a.submits==0 and store.get(bid)['attempt_count']==0


def test_tampered_workbook_rehashed_by_caller_still_rejected(setup):
    import zipfile
    from src.services.fanqie_backfill_workflow import validate_workbook, file_sha
    m=setup[3]
    path=Path(m['workbook'])
    with zipfile.ZipFile(path) as z:
        entries={name:z.read(name) for name in z.namelist()}
    entries['xl/worksheets/sheet1.xml']=entries['xl/worksheets/sheet1.xml'].replace(URL.encode(),b'https://www.douyin.com/video/9999999999999999999')
    with zipfile.ZipFile(path,'w') as z:
        for name,value in entries.items():z.writestr(name,value)
    m['workbook_sha256']=file_sha(path)
    with pytest.raises(BackfillBlocked,match='fields_differ'):validate_workbook(m)


def test_managed_guard_checks_original_command_and_bound_identity(identities,ledger,setup):
    from types import SimpleNamespace
    from src.operations_accounts.fanqie_backfill_control import ManagedFanqieGuard
    repo,control,save,confirmation,live=identities
    live['platform_identity_key']=setup[0].fanqie_account
    confirmation['platform_identity_key']=live['platform_identity_key']
    confirmation['probe_evidence']=save('actual-probe.json',live)
    repo.confirm(save('actual-confirmation.json',confirmation))
    control.acquire_owner('fanqie:test','v1','owner-1')
    authorize(ledger)
    store,bid,contract=ledger
    store.enqueue(bid);command=store.dispatch(bid,control)
    ctx=SimpleNamespace(task_id=command['command_id'],actor=SimpleNamespace(store=control,owner_id='owner-1',generation=1))
    guard=ManagedFanqieGuard(ctx,repo,store,lambda:live)
    with pytest.raises(BrowserControlRejected,match='Original'):guard.check(contract)
    control.claim_next('fanqie:test','v1','owner-1',1)
    guard.check(contract)
    with pytest.raises(BrowserControlRejected):guard.check(dict(contract,alias_id='other'))


def test_reconciliation_foreign_or_forged_original_rejected(setup,tmp_path):
    b,path,*_=setup
    with sqlite3.connect(path) as db:
        result=json.loads(db.execute('SELECT result FROM browser_control_commands').fetchone()[0])
        result['reconciliation_command_id']='b'*32
        result['original_unknown_snapshot']={'command_id':'other'}
        db.execute('UPDATE browser_control_commands SET result=?',(json.dumps(result),))
    with pytest.raises(ValueError,match='original_mismatch'):
        PublicationEvidenceReader(path,evidence_root=tmp_path).read(b.publication_command_id,b.douyin_account_uuid,b.binding_version)


def test_missing_uniqueness_fails_closed_and_migration_rolls_back(ledger,tmp_path):
    store,_,_=ledger
    with sqlite3.connect(store.path) as db:
        db.execute('DROP TABLE fanqie_dispatch_outbox')
        db.execute('''CREATE TABLE fanqie_dispatch_outbox(binding_uuid TEXT,dispatch_key TEXT,account_id TEXT,
            binding_version TEXT,payload_json TEXT,command_id TEXT,created_at TEXT)''')
        db.execute('DELETE FROM fanqie_schema_versions')
    with pytest.raises(BackfillBlocked,match='unique_constraints'):
        migrate_ledger(store.path,tmp_path/'incompatible.before.db')
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM fanqie_schema_versions').fetchone()[0]==0


def test_file_selected_without_upload_readiness_never_submits(ledger,setup):
    authorize(ledger)
    store,bid,_=ledger
    a=GovernedAdapter(setup[0]);a.upload=lambda path,b:None
    assert BackfillCoordinator(store,setup[1]).execute(bid,adapter=a,guard=Guard())['status']=='outcome_unknown'
    assert a.submits==0
