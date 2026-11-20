"""Durable random windows with real local SQLite admission; no platform calls."""
import datetime
import importlib.util
import json
from pathlib import Path

import pytest

from src.scheduler import playback_random_schedule as schedule


def timestamp(hour, minute=0, day=20):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=schedule.ZONE).timestamp()


@pytest.fixture
def backend(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('random_test_backend',
        Path(__file__).parents[1] / 'src/scheduler/account_refresh.py')
    ar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ar)
    monkeypatch.setattr(ar.time, 'time', lambda: timestamp(8))
    return ar, tmp_path / 'schedule.db'


def configure(ar, db, uuid='A', **kwargs):
    ar.set_playback_policy(uuid, uuid.lower(), True, authorization_reference='random-user-request',
        schedule={'mode': 'random_daily_three'}, path=db, **kwargs)


def due(ar, db, uuid='A'):
    return next(x['next_due'] for x in ar.snapshot(db)['playback_accounts'] if x['account_uuid'] == uuid)


def test_save_and_reopen_preserve_draw_and_revision(backend):
    ar, db = backend
    configure(ar, db)
    before = ar.snapshot(db)
    configure(ar, db)
    assert ar.snapshot(db) == before
    assert timestamp(9) <= due(ar, db) < timestamp(12)
    for now in (timestamp(8), timestamp(9), timestamp(10)):
        with ar.connect(db) as connection:
            config = schedule.read(connection, 'A')
            assert schedule.next_due(connection, 'A', config, now) == due(ar, db)


def test_claim_once_per_window_and_three_per_day(backend):
    ar, db = backend
    configure(ar, db)
    previous = None
    for low, high in ((9, 12), (14, 17), (19, 22)):
        moment = due(ar, db)
        assert timestamp(low) <= moment < timestamp(high)
        assert ar.claim_playback('A', 'a', now=moment-1, path=db) is None
        run = ar.claim_playback('A', 'a', now=moment, path=db)
        assert run and run != previous
        assert ar.claim_playback('A', 'a', now=moment+1, path=db) is None
        ar.finish_playback(run, 'completed', {}, now=moment+10, path=db)
        assert ar.claim_playback('A', 'a', now=moment+11, path=db) is None
        previous = run
    assert timestamp(9, day=21) <= due(ar, db) < timestamp(12, day=21)
    assert len(ar.snapshot(db)['playback_runs']) == 3


def test_missed_windows_have_no_backlog_and_account_draws_are_separate(backend):
    ar, db = backend
    configure(ar, db)
    configure(ar, db, 'B')
    assert due(ar, db, 'A') != due(ar, db, 'B')
    assert ar.claim_playback('A', 'a', now=timestamp(18), path=db) is None
    assert timestamp(19) <= due(ar, db) < timestamp(22)
    assert ar.claim_playback('A', 'a', now=timestamp(23), path=db) is None
    assert timestamp(9, day=21) <= due(ar, db) < timestamp(12, day=21)
    assert not ar.snapshot(db)['playback_runs']


def test_immediate_legacy_attempt_counts_and_known_failure_stays_paused(backend):
    ar, db = backend
    ar.set_playback_policy('A', 'a', True, authorization_reference='immediate', path=db)
    run = ar.claim_playback('A', 'a', now=timestamp(10), path=db)
    ar.finish_playback(run, 'blocked', {'error_code': 'human_required'}, now=timestamp(10, 1), path=db)
    configure(ar, db)
    assert timestamp(14) <= due(ar, db) < timestamp(17)
    assert ar.claim_playback('A', 'a', now=timestamp(16), path=db) is None
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'paused'
    assert state['playback_runs'][0]['run_id'] == run
    assert state['playback_runs'][0]['status'] == 'blocked'


def test_inflight_edit_keeps_original_frozen_snapshot_and_unknown_gate(backend):
    ar, db = backend
    configure(ar, db)
    run = ar.claim_playback('A', 'a', now=due(ar, db), path=db)
    original = ar.snapshot(db)['playback_runs'][0]
    ar.set_playback_policy('A', 'a', True, authorization_reference='fixed', path=db)
    state = ar.snapshot(db)
    assert state['playback_accounts'][0]['run_id'] == run
    assert state['playback_runs'][0] == original
    assert 'schedule' not in state['playback_policies'][0]
    assert ar.claim_playback('A', 'a', now=timestamp(23), path=db) is None
    assert ar.snapshot(db)['playback_runs'][0]['status'] == 'outcome_unknown'


def test_invalid_mode_and_interactions_rejected_without_configuration(backend):
    ar, db = backend
    with pytest.raises(ValueError):
        ar.set_playback_policy('A', 'a', True, authorization_reference='invalid',
            schedule={'mode': 'unlimited'}, path=db)
    with pytest.raises(ValueError):
        configure(ar, db, options={'auto_like': True})
    assert ar.snapshot(db)['playback_policies'] == []


def test_frozen_random_request_has_interactions_off(backend):
    ar, db = backend
    configure(ar, db)
    run = ar.claim_playback('A', 'a', now=due(ar, db), path=db)
    with ar.connect(db) as connection:
        row = connection.execute('SELECT policy_snapshot FROM playback_runs WHERE run_id=?', (run,)).fetchone()
    policy = json.loads(row[0])
    assert policy['schedule']['mode'] == 'random_daily_three'
    assert policy['options']['auto_like'] is False
    assert policy['options']['auto_comment'] is False
