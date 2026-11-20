"""Pre-browser failure disposition, with real isolated SQLite transitions."""
from contextlib import contextmanager
import json
import sqlite3
import time
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import fanqie_readonly_startup_recovery_v1 as r
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected, _json
from src.platform_adapter.browser_session import BrowserWorkerStartupError, BrowserWorkerStartupTimeout
from test_fanqie_managed_promotion_v1 import accounts


class Accounts:
    def __init__(self, root):
        self.db = root / 'control.db'
        self.evidence = root / 'evidence'
        self.environment = dict(resource_id='fanqie:fixture', binding_version='v1')

    def folder(self, cid):
        path = self.evidence / cid
        path.mkdir(parents=True, exist_ok=True)
        return path

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.db.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)
        db.row_factory = sqlite3.Row
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, resource):
        assert resource == self.environment['resource_id']
        return dict(self.environment)

    def check_association(self, env):
        assert env == self.environment


def freeze(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return r.bind(path)


@pytest.fixture
def original(tmp_path, monkeypatch):
    a = Accounts(tmp_path)
    store = BrowserControlStore(a.db)
    command = store.submit('fanqie:fixture', 'v1', 'fanqie_promotion_list', 'one', {})
    cid = command['command_id']
    now = time.time() - 20
    with a.connection(True) as db:
        db.execute('INSERT INTO browser_control_owners VALUES(?,?,?,?,?,?,?)',
                   ('fanqie:fixture', 'v1', 'owner', 1, 'outcome_unknown', now, now))
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id='owner',generation=1,updated_at=?,result=? WHERE command_id=?",
                   (now, _json(dict(error_type='BrowserWorkerStartupError',
                                   exception_causes=[dict(error_type='FileNotFoundError')],handler_started=True)), cid))
    folder = a.folder(cid)
    freeze(folder / 'WORKER_LAUNCH.json', dict(command_id=cid, created_at=now))
    worker = freeze(folder / 'WORKER_PROCESS.json', dict(command_id=cid, pid=12345))
    (folder / 'worker.log').write_text(
        'browser_worker_start stage=spawning_worker timeout_seconds=45.0\n'
        'browser_worker_start stage=spawning_worker outcome=failed error_type=FileNotFoundError elapsed_ms=4\n'
        'browser_worker_start failure_evidence={"cleanup_verified":true,"ready_received":false,"stage":"spawning_worker"}\n', encoding='utf-8')
    proof = freeze(tmp_path / 'OWNER_EXIT.json', dict(schema='fanqie_readonly_owner_exit/v1',command_id=cid,
        owner_id='owner', generation=1, worker_process=worker, owner_exited=True,
        processes=[dict(pid=12345, exists=False, observed_at_epoch=time.time())]))
    monkeypatch.setattr(r.psutil, 'pid_exists', lambda pid: False)
    return a, store, cid, proof, tmp_path / 'recovery'


def failure(stage='spawning_worker', cause=None, **facts):
    error = BrowserWorkerStartupError(stage)
    error.__cause__ = cause or FileNotFoundError('synthetic Popen failure')
    error.startup_evidence = dict(stage=stage, cleanup_verified=True, ready_received=False, **facts)
    session = NS(_proc=None, _worker_stage=stage, _startup_cleanup_verified=True, active=False)
    return error, session


def test_typed_pre_popen_classification_and_wrapper_only_fail_read(original):
    a, store, cid, _, _ = original
    error, session = failure()
    assert r.classify_startup_failure(error, session, a.folder(cid))['platform_requests_started'] is False
    sessions = []
    def handler(ctx, payload):
        sessions.append(session)
        raise error
    ctx = NS(task_id=cid, command=store.get(cid), binding_version='v1', actor=NS(owner_id='owner',generation=1))
    value = r.readonly_startup_handler(handler, accounts=a, sessions=sessions)(ctx, {})
    assert value.state == 'failed' and value.result['known_local_failure']
    assert store.get(cid)['state'] == 'outcome_unknown'  # wrapper never edits DB itself


@pytest.mark.parametrize('kind', ['fanqie_login', 'fanqie_promotion_apply', 'fanqie_backfill', 'fanqie_backfill_reconcile'])
def test_write_and_login_never_classified(kind, original):
    a, store, cid, _, _ = original
    error, session = failure()
    sessions = []
    def handler(ctx, payload):
        sessions.append(session)
        raise error
    command = dict(store.get(cid), kind=kind)
    with pytest.raises(BrowserWorkerStartupError):
        r.readonly_startup_handler(handler,accounts=a,sessions=sessions)(NS(command=command), {})


@pytest.mark.parametrize('variant', ['worker_pid', 'ready', 'stage', 'timeout', 'proc', 'artifact'])
def test_ambiguous_startup_retains_unknown(variant, original):
    a, _, cid, _, _ = original
    error, session = failure()
    if variant == 'worker_pid': error.startup_evidence['worker_pid'] = 999
    if variant == 'ready': error.startup_evidence['ready_received'] = True
    if variant == 'stage': error, session = failure('launching_browser')
    if variant == 'timeout': error = BrowserWorkerStartupTimeout('spawning_worker', 45)
    if variant == 'proc': session._proc = NS(pid=9)
    if variant == 'artifact': freeze(a.folder(cid) / 'SUBMIT_CLAIM.json', {})
    assert r.classify_startup_failure(error, session, a.folder(cid)) is None


def test_prepare_is_readonly_settle_keeps_original_and_never_replays(original):
    a, store, cid, proof, output = original
    before = store.get(cid)
    log_sha = r.bind(a.folder(cid) / 'worker.log')
    plan = r.prepare_recovery(a, cid, proof, output)
    assert store.get(cid) == before
    after = r.settle_recovery(a, plan)
    assert after['state'] == 'failed' and after['result']['before_snapshot'] == before
    assert after['result']['original_unknown_record_retained'] and not after['result']['original_request_replayed']
    with a.connection() as db:
        assert db.execute('SELECT count(*) FROM browser_control_commands').fetchone()[0] == 1
        assert db.execute('SELECT state FROM browser_control_owners').fetchone()[0] == 'released'
    assert r.bind(a.folder(cid) / 'worker.log') == log_sha
    assert r.settle_recovery(a, plan) == after


@pytest.mark.parametrize('variant', ['live', 'owner_changed', 'command_changed', 'pending', 'log_changed'])
def test_settle_denies_live_changed_or_other_pending(original, monkeypatch, variant):
    a, store, cid, proof, output = original
    plan = r.prepare_recovery(a, cid, proof, output)
    if variant == 'live': monkeypatch.setattr(r.psutil, 'pid_exists', lambda pid: True)
    if variant == 'log_changed': (a.folder(cid) / 'worker.log').write_text('changed',encoding='utf-8')
    if variant == 'pending': store.submit('fanqie:fixture','v1','fanqie_catalog','two',{})
    if variant in ('owner_changed', 'command_changed'):
        with a.connection(True) as db:
            table = 'browser_control_owners' if variant == 'owner_changed' else 'browser_control_commands'
            db.execute(f'UPDATE {table} SET updated_at=updated_at+1')
    with pytest.raises(BrowserControlRejected): r.settle_recovery(a, plan)
    assert store.get(cid)['state'] == 'outcome_unknown'


def test_historical_ready_or_business_evidence_cannot_be_settled(original):
    a, store, cid, proof, output = original
    with (a.folder(cid) / 'worker.log').open('a',encoding='utf-8') as out:
        out.write('browser_worker_start stage=ready elapsed_ms=8\n')
    with pytest.raises(BrowserControlRejected): r.prepare_recovery(a,cid,proof,output)
    assert store.get(cid)['state'] == 'outcome_unknown'


def test_actual_owner_initial_read_failure_releases_owner_without_browser(accounts):
    from src.operations_accounts.fanqie_account_control import run_owner
    a, env = accounts
    class FailedSession:
        _proc = None
        _worker_stage = 'spawning_worker'
        _startup_cleanup_verified = True
        active = False
        def __init__(self, config): self.config = config
        def get_page(self):
            error, _ = failure()
            raise error
        def stop(self): pass
    command = a.queue(env['resource_id'], 'fanqie_promotion_list')
    result = run_owner(env['resource_id'], a, session_factory=FailedSession)
    assert result['command_id'] == command['command_id'] and result['state'] == 'failed'
    assert result['result']['reason'] == r.CODE
    with a.connection() as db:
        assert db.execute('SELECT state FROM browser_control_owners WHERE account_id=?', (env['resource_id'],)).fetchone()[0] == 'released'
    assert not (a.folder(command['command_id']) / 'PROMOTION_SNAPSHOT.json').exists()
