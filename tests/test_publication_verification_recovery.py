"""Original publication recovery: isolated DB/native receipts, no real browser."""
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import publication_verification_recovery as recovery
from src.operations_accounts import browser_boot_recovery as boot
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor, BrowserControlRejected, _json


@pytest.fixture
def incident(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'ROOT', tmp_path)
    now = [500.0]
    store = BrowserControlStore(tmp_path/'control.db', clock=lambda: now[0])
    store.acquire_owner('account:a', 'binding', 'backend:123:abc')
    context = NS(account_uuid='account:a', account_key='novel', binding=NS(platform_identity_key='platform:a'))
    request = {'video_path': str(tmp_path/'approved.mp4'), 'title': '唯一原作品', 'description': '原说明',
               'hashtags': ['话题'], 'visibility': 'public', 'ai_generated': True, 'fictional_story': True}
    original = store.submit(context.account_uuid, 'binding', 'publish', 'publish:original',
        {'account_uuid': context.account_uuid, 'account_key': context.account_key,
         'video_sha256': 'a'*64, 'request': request, 'authorization': {'comment': '原批准评论'}}, 100)
    claimed = store.claim_next(context.account_uuid, 'binding', 'backend:123:abc', 1)
    store.transition(original['command_id'], 'backend:123:abc', 1, 'outcome_unknown',
        result={'status': 'submission_unknown', 'success': False})
    original = store.get(original['command_id'])
    directory = tmp_path/'data/publish_runs'
    directory.mkdir(parents=True)
    key = hashlib.sha256(json.dumps({'platform_identity_key': 'platform:a', 'video_sha256': 'a'*64}, sort_keys=True).encode()).hexdigest()
    journal = directory/(key+'.original.jsonl')
    rows = [dict(stage='prepared', at_bjt=datetime.fromtimestamp(500, timezone.utc).isoformat(),
                 account='novel', account_uuid='account:a', platform_identity_key='platform:a',
                 video_sha256='a'*64, title=request['title'], description='原说明', hashtags=['话题'],
                 video_path=request['video_path'], visibility='public', ai_declaration_required=True, fiction_declaration_required=True),
            {'stage': 'submission_started'},
            {'stage': 'ai_declaration_verified', 'set_selected': True, 'evidence': {'verified': True, 'label': '内容由AI生成'}},
            {'stage': 'ai_declaration_verified', 'set_selected': False, 'evidence': {'verified': True, 'label': '内容由AI生成'}},
            {'stage': 'publish_click_dispatching'}]
    journal.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows)+'\n', encoding='utf8')
    lock = directory/(key+'.submitted.json')
    lock.write_text(json.dumps({'journal': str(journal), 'status': 'submission_started'}), encoding='utf8')
    now[0] = 1000.0
    with store._db(write=True) as db:
        db.execute('UPDATE browser_control_owners SET heartbeat=1000,updated_at=1000')
    return NS(store=store, context=context, original=original, now=now, journal=journal, lock=lock, rows=rows)


def queue(i):
    return recovery.queue_due(i.store, i.context, 'binding')


def valid_evidence(i):
    return dict(verified=True, expected_title=i.original['payload']['request']['title'], expected_hashtags=['话题'],
        title_verified=True, hashtags_verified=True, review_status='clear', ai_label_visible=True,
        fiction_notice_visible=True, player={'ready': True, 'error': False, 'duration': True})


class Page:
    def __init__(self, discovery):
        self.discovery = discovery
        self.visits = []
    def discover_published_work(self, title):
        return self.discovery
    def wait_for_timeout(self, ms): pass
    def goto(self, url): self.visits.append(url)


class Session:
    def __init__(self, page): self.page, self.closed = page, False
    def open_page(self, url): self.page.visits.append(url); return self.page
    def stop(self): self.closed = True


def execute(i, monkeypatch, *, evidence=None, discovery=None):
    with i.store._db(write=True) as db:
        db.execute('UPDATE browser_control_owners SET heartbeat=?,updated_at=?',(i.now[0],i.now[0]))
    queue(i)
    page = Page(discovery or {'verified': True, 'post_id': '123456', 'publish_url': 'https://www.douyin.com/video/123456'})
    session = Session(page)
    monkeypatch.setattr('src.platform_adapter.publish_verification.wait_for_published_video',
                        lambda *a, **kw: evidence if evidence is not None else valid_evidence(i))
    resource = NS(context=i.context, runtime=NS(verify_identity=lambda *a, **kw: NS(healthy=True)))
    # Continue the exact live owner; no reacquisition of a stale generation.
    actor = BrowserControlActor(i.store, 'account:a', 'binding', 'backend:123:abc',
        {recovery.KIND: lambda ctx, payload: recovery.run(ctx, session)}, context=resource)
    actor.generation = 1
    actor._thread_id = __import__('threading').get_ident()
    return actor.run_next(), page, session


def test_idempotent_queue_no_resubmission_and_preserved_native_claim(incident):
    i = incident
    original, lock = i.store.get(i.original['command_id']), i.lock.read_bytes()
    first = queue(i)
    assert first['kind'] == recovery.KIND and first['payload']['attempt'] == 1
    assert queue(i) is None
    assert i.store.get(i.original['command_id']) == original
    assert i.lock.read_bytes() == lock
    assert i.store.claim_next('account:a', 'binding', 'backend:123:abc', 1)['command_id'] == first['command_id']


def test_real_actor_read_only_exact_work_atomically_settles_both_receipts(incident, monkeypatch):
    i = incident
    out, page, session = execute(i, monkeypatch)
    assert out['state'] == 'succeeded' and out['result']['status'] == 'verified_published'
    original = i.store.get(i.original['command_id'])
    assert original['state'] == 'succeeded' and original['result']['post_id'] == '123456'
    assert original['result']['original_unknown_snapshot'] == i.original
    assert original['result']['comment_pending'] is True
    assert original['result']['comment']['status'] == 'not_submitted_by_readonly_recovery'
    assert session.closed
    assert page.visits == ['https://creator.douyin.com/creator-micro/content/manage', 'https://www.douyin.com/video/123456']
    assert json.loads(i.lock.read_text())['status'] == 'submission_started'
    assert queue(i) is None


@pytest.mark.parametrize('reason', ['title_not_unique', 'title_scan_truncated', 'title_candidate_missing', 'manage_loading'])
def test_ambiguous_missing_or_loading_never_claims_published_or_reuploads(incident, monkeypatch, reason):
    i = incident
    out, page, _ = execute(i, monkeypatch, discovery={'verified': False, 'reason': reason})
    assert out['state'] == 'failed' and out['result']['status'] == 'verification_pending'
    assert i.store.get(i.original['command_id']) == i.original
    assert len(page.visits) == 1 and i.lock.exists()


@pytest.mark.parametrize('field,value', [('review_status','not_clear'), ('title_verified',False), ('hashtags_verified',False),
    ('ai_label_visible',False), ('fiction_notice_visible',False), ('expected_title','别人的作品'), ('player',{'ready':True,'error':True,'duration':True})])
def test_incomplete_detail_evidence_never_settles_original(incident, monkeypatch, field, value):
    i = incident
    proof = valid_evidence(i); proof[field] = value
    out, _, _ = execute(i, monkeypatch, evidence=proof)
    assert out['state'] == 'failed' and out['error_code'] == 'publication_evidence_incomplete'
    assert i.store.get(i.original['command_id']) == i.original


@pytest.mark.parametrize('change', ['binding', 'journal', 'lock', 'title', 'no_click', 'no_active_ai'])
def test_frozen_original_and_native_sources_cannot_be_substituted(incident, change):
    i = incident
    command = queue(i)
    if change == 'binding': i.context.binding.platform_identity_key = 'other'
    elif change == 'lock': i.lock.write_text('{}')
    elif change == 'title':
        i.store.submit('account:a', 'binding', 'publish', 'another-publish', i.original['payload'], 100)
    else:
        rows = list(i.rows)
        if change == 'no_click': rows = rows[:-1]
        elif change == 'no_active_ai': rows = [r for r in rows if r.get('set_selected') is not True]
        else: rows[0] = dict(rows[0], title='替换标题')
        i.journal.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf8')
    with pytest.raises((BrowserControlRejected, OSError, KeyError)):
        recovery.inputs(i.store, command, i.context)
    assert i.store.get(i.original['command_id']) == i.original


def test_retries_bounded_delayed_and_each_new_attempt_has_its_own_id(incident, monkeypatch):
    i = incident
    ids = []
    for attempt in range(3):
        out, _, _ = execute(i, monkeypatch, discovery={'verified':False,'reason':'title_candidate_missing'})
        ids.append(out['command_id'])
        assert queue(i) is None
        i.now[0] += 301
    assert len(set(ids)) == 3 and queue(i) is None
    assert recovery.queue_blocker(i.store,'account:a')['verification_attempts'] == 3


def test_challenge_waits_for_explicit_manual_progress_and_does_not_auto_complete(incident, monkeypatch):
    i = incident
    out, _, _ = execute(i, monkeypatch, discovery={'verified':False,'reason':'observed_cover_human_required'})
    assert out['result']['status'] == 'human_required'
    i.now[0] += 301
    with i.store._db(write=True) as db: db.execute('UPDATE browser_control_owners SET heartbeat=?,updated_at=?',(i.now[0],i.now[0]))
    assert queue(i) is None
    manual = i.store.submit('account:a','binding','manual','manual-one',{'account_key':'novel'},200)
    claimed = i.store.claim_next('account:a','binding','backend:123:abc',1)
    assert claimed['command_id'] == manual['command_id']
    i.store.transition(manual['command_id'],'backend:123:abc',1,'waiting_human',result={})
    assert queue(i) is None
    i.store.complete_waiting(manual['command_id'],'backend:123:abc',1,{'window_closed':True})
    assert queue(i)['payload']['attempt'] == 2
    assert i.store.get(i.original['command_id']) == i.original


def test_previous_boot_can_handoff_only_to_readonly_verifier_not_normal_business(incident, monkeypatch):
    i = incident
    queue(i)
    with i.store._db(write=True) as db: db.execute('UPDATE browser_control_owners SET heartbeat=500,updated_at=500')
    monkeypatch.setattr(boot, '_boot_evidence', lambda: {'boot_time':900,'backend_pid':456,'backend_create_time':950})
    owner = boot.read_owner(i.store,'account:a')
    assert boot.release_previous_boot_owner(i.store,'account:a',owner) is False
    assert recovery.release_previous_boot(i.store,'account:a',owner) is True
    with pytest.raises(BrowserControlRejected): i.store.acquire_owner('account:a','binding','backend:456:def')
    new = recovery.acquire_owner(i.store,'account:a','binding','backend:456:def')
    assert new['generation'] == 2
    cmd = i.store.claim_next('account:a','binding','backend:456:def',2)
    assert cmd['kind'] == recovery.KIND
    assert i.store.get(i.original['command_id']) == i.original


def test_later_reboot_retains_readonly_owner_lineage_and_each_handoff_audit(incident, monkeypatch):
    i=incident
    queue(i)
    with i.store._db(write=True)as db:db.execute('UPDATE browser_control_owners SET heartbeat=500,updated_at=500')
    monkeypatch.setattr(boot,'_boot_evidence',lambda:{'boot_time':900,'backend_pid':456,'backend_create_time':950})
    assert recovery.release_previous_boot(i.store,'account:a',boot.read_owner(i.store,'account:a'))
    recovery.acquire_owner(i.store,'account:a','binding','backend:456:def')
    task=i.store.claim_next('account:a','binding','backend:456:def',2)
    i.store.transition(task['command_id'],'backend:456:def',2,'failed',result={'status':'verification_pending'})
    i.now[0]=2000
    assert queue(i)['payload']['attempt']==2
    monkeypatch.setattr(boot,'_boot_evidence',lambda:{'boot_time':1900,'backend_pid':789,'backend_create_time':1950})
    assert recovery.release_previous_boot(i.store,'account:a',boot.read_owner(i.store,'account:a'))
    assert recovery.acquire_owner(i.store,'account:a','binding','backend:789:aaa')['generation']==3
    with i.store._db()as db:
        assert db.execute('SELECT COUNT(*) FROM publication_verification_handoff_audit').fetchone()[0]==2
    assert i.store.get(i.original['command_id'])==i.original


@pytest.mark.parametrize('change', ['no_boot', 'same_boot', 'owner_changed', 'other_unknown', 'no_queued_verify'])
def test_stale_heartbeat_is_never_sufficient_to_take_over(incident, monkeypatch, change):
    i = incident
    command = queue(i)
    with i.store._db(write=True) as db: db.execute('UPDATE browser_control_owners SET heartbeat=500,updated_at=500')
    monkeypatch.setattr(boot, '_boot_evidence', lambda: None if change=='no_boot' else
        {'boot_time':400 if change=='same_boot' else 900, 'backend_pid':456, 'backend_create_time':950})
    owner = boot.read_owner(i.store,'account:a')
    with i.store._db(write=True) as db:
        if change=='owner_changed': db.execute("UPDATE browser_control_owners SET owner_id='backend:789:aaa'")
        if change=='no_queued_verify': db.execute("UPDATE browser_control_commands SET state='failed' WHERE command_id=?",(command['command_id'],))
        if change=='other_unknown':
            db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(command['command_id'],))
    assert not recovery.release_previous_boot(i.store,'account:a',owner)
    assert i.store.get(i.original['command_id']) == i.original


def test_queued_window_projection_identifies_original_unknown_without_open_claim(incident, monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    i = incident
    with i.store._db(write=True) as db: db.execute('UPDATE browser_control_owners SET heartbeat=500,updated_at=500')
    monkeypatch.setattr(bridge,'_store',lambda:i.store)
    cmd = i.store.submit('account:a','binding','manual','manual-one',{'account_key':'novel'},200)
    view = bridge._manual_public(cmd)
    assert view['phase'] == 'queued' and view['handoff_ready'] is False
    assert view['blocking_command_id'] == i.original['command_id']
    assert view['queue_blocker'] == 'publication_verification_pending' and view['owner_stale']


def test_local_projection_retries_without_browser_and_does_not_lose_verified_receipt(incident, monkeypatch):
    from src.services import video_service
    i = incident
    out, _, _ = execute(i, monkeypatch)
    calls=[]
    def unavailable(**kw):
        calls.append(kw)
        raise OSError('isolated unavailable DB')
    monkeypatch.setattr(video_service,'bind_verified_publication',unavailable)
    recovery.project_verified_works(i.store,'account:a')
    assert i.store.get(i.original['command_id'])['state']=='succeeded'
    recovery.project_verified_works(i.store,'account:a')
    assert len(calls)==1
    i.now[0]+=301
    monkeypatch.setattr(video_service,'bind_verified_publication',lambda **kw:calls.append(kw) or True)
    recovery.project_verified_works(i.store,'account:a')
    recovery.project_verified_works(i.store,'account:a')
    assert len(calls)==2 and calls[1]['post_id']=='123456'
    with i.store._db()as db:
        assert db.execute('SELECT state FROM publication_verified_work_outbox').fetchone()[0]=='completed'


@pytest.fixture
def video_database(tmp_path,monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    from src.services import video_service
    path=tmp_path/'videos.db'
    @contextmanager
    def connection():
        with sqlite3.connect(path)as db:
            db.row_factory=sqlite3.Row
            yield db
    with connection()as db:
        db.execute('''CREATE TABLE videos(id INTEGER PRIMARY KEY,local_id TEXT,video_id TEXT,title TEXT,
            description TEXT,status TEXT,last_synced_at TEXT,created_at TEXT,account_uuid TEXT,account_key TEXT,
            stats_views INTEGER DEFAULT 0,stats_likes INTEGER DEFAULT 0,stats_comments INTEGER DEFAULT 0)''')
    monkeypatch.setattr(video_service,'get_db',connection)
    return video_service,connection


def test_exact_work_projection_preserves_existing_metrics_and_pending_local_identity(video_database):
    service,connection=video_database
    with connection()as db:
        db.execute("INSERT INTO videos(local_id,title,status,account_uuid,stats_views,stats_likes) VALUES('local-original','原作品','pending_review','account:a',123,45)")
    kwargs=dict(account_uuid='account:a',account_key='novel',command_id='original',post_id='123456',title='原作品',description='原说明')
    service.bind_verified_publication(**kwargs)
    service.bind_verified_publication(**kwargs)
    with connection()as db:
        rows=db.execute('SELECT * FROM videos').fetchall()
        assert len(rows)==1 and rows[0]['video_id']=='123456' and rows[0]['local_id']=='local-original'
        assert rows[0]['stats_views']==123 and rows[0]['stats_likes']==45 and rows[0]['status']=='published'


@pytest.mark.parametrize('conflict',['duplicate_pending','foreign_exact_id','conflicting_pending_id'])
def test_projection_never_guesses_ambiguous_or_other_account_records(video_database,conflict):
    service,connection=video_database
    with connection()as db:
        if conflict=='foreign_exact_id':
            db.execute("INSERT INTO videos(title,video_id,account_uuid,status) VALUES('原作品','123456','other','published')")
        else:
            db.execute("INSERT INTO videos(title,video_id,account_uuid,status) VALUES('原作品',?,'account:a','pending_review')",('999' if conflict=='conflicting_pending_id'else None,))
            if conflict=='duplicate_pending':
                db.execute("INSERT INTO videos(title,account_uuid,status) VALUES('原作品','account:a','pending_review')")
        before=[tuple(r)for r in db.execute('SELECT * FROM videos')]
    with pytest.raises(ValueError):
        service.bind_verified_publication(account_uuid='account:a',account_key='novel',command_id='original',post_id='123456',title='原作品',description='原说明')
    with connection()as db:
        assert [tuple(r)for r in db.execute('SELECT * FROM videos')]==before
