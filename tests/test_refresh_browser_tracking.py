import json
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor
from src.scheduler import account_refresh as refresh
from src.scheduler import browser_task_tracking as track


def setup(tmp_path):
    path=tmp_path/'schedule.db'
    run=refresh.claim('a','one',now=100,path=path)
    browser=tmp_path/'browser.db'
    s=BrowserControlStore(browser)
    c=s.submit('a','b','maintenance','one',{'mode':'post-publish'})
    track.attach(c,browser,run_id=run,path=path)
    return path,run,s,c


def test_queue_does_not_expire_as_unknown_or_duplicate(tmp_path):
    path,run,s,c=setup(tmp_path)
    assert refresh.claim('a','one',now=4000,path=path) is None
    snap=refresh.snapshot(path)
    assert snap['runs'][0]['status']=='running'
    assert snap['controls'][0]['state']=='active'
    refresh.finish(run,'failed',{'error_code':'command_wait_timeout'},now=11000,path=path)
    assert refresh.snapshot(path)['runs'][0]['status']=='waiting_original'
    assert refresh.claim('a','one',now=12000,path=path) is None
    assert s.get(c['command_id'])==c


def test_entered_command_retains_unknown_protection(tmp_path):
    path,run,s,c=setup(tmp_path)
    o=s.acquire_owner('a','b','backend:1:abc')
    s.claim_next('a','b',o['owner_id'],o['generation'])
    assert refresh.claim('a','one',now=4000,path=path) is None
    assert refresh.snapshot(path)['runs'][0]['status']=='outcome_unknown'


def test_original_receipt_settles_wait_without_new_dispatch(tmp_path):
    path,run,s,c=setup(tmp_path)
    refresh.finish(run,'failed',{'error_code':'command_wait_timeout'},now=11000,path=path)
    value={'status':'completed','message':'done','run_id':'native','synced_videos':3,'synced_comments':2,'comment_sync_failures':0,'login_healthy':True}
    a=BrowserControlActor(s,'a','b','backend:1:abc',{'maintenance':lambda *args:{'maintenance_result':value}})
    try:a.run_next()
    finally:a.stop_heartbeat()
    track.reconcile(path);track.reconcile(path)
    snap=refresh.snapshot(path)
    assert len(snap['runs'])==1 and snap['runs'][0]['status']=='completed'
    assert json.loads(snap['runs'][0]['detail'])['maintenance_run_id']=='native'


def test_migration_preserves_original_failed_receipt(tmp_path):
    path=tmp_path/'schedule.db';run=refresh.claim('a','one',now=100,path=path)
    refresh.finish(run,'failed',{'error_code':'command_wait_timeout'},now=11000,path=path)
    before=refresh.snapshot(path)['runs'][0]
    s=BrowserControlStore(tmp_path/'browser.db');c=s.submit('a','b','maintenance','original',{'mode':'post-publish'})
    track.attach(c,s.path,run_id=run,path=path)
    assert refresh.claim('a','one',now=20000,path=path) is None
    a=BrowserControlActor(s,'a','b','backend:1:abc',{'maintenance':lambda *args:{}})
    try:a.run_next()
    finally:a.stop_heartbeat()
    track.reconcile(path)
    assert refresh.snapshot(path)['runs'][0]==before


def test_successful_migrated_original_advances_due_without_duplicate(tmp_path):
    import time
    path=tmp_path/'schedule.db';run=refresh.claim('a','one',now=100,path=path)
    refresh.finish(run,'failed',{'error_code':'command_wait_timeout'},now=11000,path=path)
    before=refresh.snapshot(path)['runs'][0]
    s=BrowserControlStore(tmp_path/'browser.db');c=s.submit('a','b','maintenance','original',{'mode':'post-publish'})
    track.attach(c,s.path,run_id=run,path=path)
    value={'status':'completed','message':'done','run_id':'native','synced_videos':3,'synced_comments':2,'comment_sync_failures':0,'login_healthy':True}
    a=BrowserControlActor(s,'a','b','backend:1:abc',{'maintenance':lambda *args:{'maintenance_result':value}})
    try:a.run_next()
    finally:a.stop_heartbeat()
    track.reconcile(path)
    assert refresh.claim('a','one',now=time.time(),path=path) is None
    assert refresh.snapshot(path)['runs'][0]==before
    with refresh.connect(path) as db:
        due=db.execute('SELECT next_due FROM refresh_accounts').fetchone()[0]
        assert due>time.time()+14000
    track.reconcile(path)
    with refresh.connect(path) as db:
        assert db.execute('SELECT next_due FROM refresh_accounts').fetchone()[0]==due
