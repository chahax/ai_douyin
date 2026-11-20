"""Independent persisted complete -> probe -> original-plan continuation checks."""
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def flow(tmp_path, monkeypatch):
    root = Path(__file__).parents[1]
    def load(name, file):
        spec = importlib.util.spec_from_file_location(name, root / file)
        module = importlib.util.module_from_spec(spec)
        module.__package__ = 'src.scheduler'
        spec.loader.exec_module(module)
        return module
    ar = load('handling_flow_backend', 'src/scheduler/account_refresh.py')
    ap = load('handling_flow_playback', 'src/scheduler/account_playback.py')
    monkeypatch.setitem(sys.modules, 'src.scheduler.account_playback', ap)
    monkeypatch.setattr(ap, '_backend', lambda: ar)
    db = tmp_path / 'flow.db'
    ar.set_playback_policy('A', 'a', True, authorization_reference='user-settings', path=db)
    now = time.time()
    original = ar.claim_playback('A', 'a', now=now, path=db)
    assert ar._prepare_playback_dispatch(original, now=now, path=db)
    ar.finish_playback(original, 'blocked', {
        'error_code': 'human_required', 'message': 'manual verification needed',
        'maintenance_run_id': 'maintenance:original', 'playback_verified_videos': 0,
        'actual_watch_seconds': 0, 'likes_performed': 0, 'comments_sent': 0,
        'external_dispatched': True,
    }, now=now, path=db)
    return ar, ap, db, original


def test_one_completion_checks_original_identity_then_continues_once_without_rewriting_failure(flow, monkeypatch):
    from src.operations_accounts import runtime, maintenance
    ar, ap, db, original = flow
    before = ar.snapshot(db)
    original_row = next(r for r in before['playback_runs'] if r['run_id'] == original)
    assert before['playback_accounts'][0]['next_due'] > time.time()
    probes, calls = [], []
    def probe(key, **kwargs):
        probes.append(key)
        return SimpleNamespace(healthy=True, status='active', expected=SimpleNamespace(account_uuid='A', account_key='a'))
    monkeypatch.setattr(runtime, 'AccountRuntimeService', lambda: SimpleNamespace(probe_recovery=probe))
    def run(key, mode, **kwargs):
        calls.append((key, mode, kwargs))
        return SimpleNamespace(status='completed', error_code='', message='verified playback', run_id='maintenance:next',
                               playback_verified_videos=1, actual_watch_seconds=15, likes_performed=0, comments_sent=0)
    monkeypatch.setattr(maintenance, 'AccountMaintenanceService', lambda: SimpleNamespace(run=run))
    assert ar.complete_account_handling('A', 'a', handled_by='operator', path=db)['accepted']
    assert not ar.complete_account_handling('A', 'a', handled_by='operator', path=db)['accepted']
    assert ap.dispatch_account('A', 'a', path=db) is None
    ar.recover_requested_accounts(path=db)
    ar.recover_requested_accounts(path=db)
    assert probes == ['a']
    assert ar.snapshot(db)['controls'][0]['state'] == 'active'
    continued = ar.claim_playback('A', 'a', path=db)
    assert continued and continued != original
    ap._run_playback(continued, path=db)
    assert ar.claim_playback('A', 'a', path=db) is None
    after = ar.snapshot(db)
    assert next(r for r in after['playback_runs'] if r['run_id'] == original) == original_row
    assert after['playback_policies'] == before['playback_policies']
    assert len(calls) == 1 and calls[0][0:2] == ('a', 'playback')
    options = calls[0][2]['playback_options']
    assert not options.auto_like and not options.auto_comment
    assert next(r for r in after['playback_runs'] if r['run_id'] == continued)['status'] == 'completed'


def test_healthy_different_account_receipt_never_continues_the_original_plan(flow, monkeypatch):
    from src.operations_accounts import runtime
    ar, ap, db, original = flow
    before = ar.snapshot(db)
    monkeypatch.setattr(runtime, 'AccountRuntimeService', lambda: SimpleNamespace(
        probe_recovery=lambda *args, **kwargs: SimpleNamespace(
            healthy=True, status='active', expected=SimpleNamespace(account_uuid='B', account_key='b'))))
    assert ar.complete_account_handling('A', 'a', handled_by='operator', path=db)['accepted']
    ar.recover_requested_accounts(path=db)
    after = ar.snapshot(db)
    assert after['controls'][0]['state'] == 'paused'
    assert after['controls'][0]['error_code'] == 'account_uuid_mismatch'
    assert after['playback_accounts'] == before['playback_accounts']
    assert after['playback_runs'] == before['playback_runs']
    assert ap.dispatch_account('A', 'a', path=db) is None


def test_completion_checks_the_enabled_playback_scanner_without_blocking_unconfigured_accounts():
    from src.web.account_exception_notice import _handling_state
    data = {'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused'}],
            'service': {'playback_schedule': {'status': 'manual_required', 'updated_at': time.time()}},
            'playback_policies': [{'account_uuid': 'B', 'enabled': 1}]}
    assert _handling_state(data, 'A', 'a')[2] is True
    data['playback_policies'].append({'account_uuid': 'A', 'enabled': 1})
    state, message, ready = _handling_state(data, 'A', 'a')
    assert state == 'service_unavailable' and '后台服务异常' in message and ready is False
