"""Retire a finished host only after its resources and commands are accounted for."""
from .browser_control import _json


def _table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS browser_host_retirements(
        account_id TEXT NOT NULL, owner_id TEXT NOT NULL, generation INTEGER NOT NULL,
        original_owner TEXT NOT NULL, evidence TEXT NOT NULL, error_type TEXT NOT NULL,
        retired_at REAL NOT NULL, PRIMARY KEY(account_id,owner_id,generation))''')


def retry_allowed(store, account_id):
    with store._db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='browser_host_retirements'").fetchone():
            return True
        times = [r[0] for r in db.execute('''SELECT retired_at FROM browser_host_retirements
            WHERE account_id=? AND error_type!='' AND retired_at>?''', (account_id, store.clock()-86400))]
    return len(times) < 2 and (not times or store.clock()-max(times) >= 300)


def retire(store, account_id, owner_id, generation, *, evidence, error_type=''):
    """Caller must prove host/worker termination, never infer it from an expired TTL."""
    if evidence.get('host_stopped') is not True or evidence.get('worker_stopped') is not True:
        return False
    with store._db(write=True) as db:
        row = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone()
        if not row or row['owner_id'] != owner_id or row['generation'] != generation:
            return False
        if row['state'] == 'released':
            return True
        from .publication_autonomous_reconciliation import unresolved
        if unresolved(store,db,account_id,('running','paused','waiting_human','outcome_unknown')):
            return False
        _table(db)
        db.execute('INSERT INTO browser_host_retirements VALUES(?,?,?,?,?,?,?)',
            (account_id,owner_id,generation,_json(dict(row)),_json(evidence),error_type,store.clock()))
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",
                   (store.clock(),account_id))
        return True


def retire_host(actor, resource, *, error_type=''):
    """Runs on the exiting host; preserve all uncertain work and human tabs."""
    if getattr(resource,'_retirement_unverified',False):
        return False
    if actor._stack or resource.manual_tasks or resource.console_tasks:
        return False
    from .publication_autonomous_reconciliation import unresolved
    with actor.store._db() as db:
        if unresolved(actor.store,db,actor.account_id,('running','paused','waiting_human','outcome_unknown')):
            return False
    session = resource.session
    proc = None
    children = []
    if session is not None:
        # Unknown session implementations cannot supply termination evidence.
        if not hasattr(session, '_proc'):
            return False
        proc = session._proc
        if proc is None and getattr(session,'_worker_stage','not_started') != 'not_started' and not getattr(session,'_startup_cleanup_verified',False):
            return False
        if proc is not None and proc.poll() is None:
            import psutil
            children = psutil.Process(proc.pid).children(recursive=True)
            tabs = session.list_tabs()
            if any(t.get('role') in {'manual','official_console'} and not t.get('closed') for t in tabs):
                return False
        # Keep a failed cleanup sticky even if shutdown clears resource.session.
        resource._retirement_unverified = True
        resource.shutdown()
        if proc is not None:
            proc.wait(timeout=5)
            if proc.poll() is None:
                return False
        if any(p.is_running() for p in children):
            return False
        resource._retirement_unverified = False
    actor.stop_heartbeat()
    return retire(actor.store,actor.account_id,actor.owner_id,actor.generation,
        evidence={'host_stopped':True,'worker_stopped':True,'source':'host_finally',
                  'worker_pid':getattr(proc,'pid',None)},error_type=error_type)
