from src.scheduler.account_refresh import (
    claim,
    claim_smart,
    finish,
    finish_smart,
    snapshot,
    set_policy,
    set_smart_policy,
)


def test_startup_catches_up_once_not_entire_offline_backlog(tmp_path):
    db = tmp_path/'schedule.db'
    first = claim('A', 'a', now=100, reason='startup_catchup', path=db)
    assert first
    assert claim('A', 'a', now=101, path=db) is None
    finish(first, 'completed', {'videos': 2}, now=110, path=db)
    assert claim('A', 'a', now=120, reason='startup_catchup', path=db) is None
    second = claim('A', 'a', now=10*86400, reason='startup_catchup', path=db)
    finish(second, 'completed', {}, now=10*86400+10, path=db)
    assert len(snapshot(db)['runs']) == 2
    assert claim('A', 'a', now=10*86400+11, path=db) is None


def test_separate_accounts_and_retry_policy(tmp_path):
    db = tmp_path/'schedule.db'
    a = claim('A', 'a', now=100, path=db)
    b = claim('B', 'b', now=100, path=db)
    assert a and b
    finish(a, 'blocked', {}, now=110, path=db)
    finish(b, 'failed', {}, now=110, path=db)
    assert claim('A', 'a', now=2000, path=db) is None
    assert claim('B', 'b', now=2000, path=db)


def test_interruption_is_logged_and_disabled_policy_survives_restart(tmp_path):
    db = tmp_path/'schedule.db'
    claim('A', 'a', now=100, path=db)
    assert claim('A', 'a', now=4000, reason='startup_catchup', path=db)
    assert any(r['status']=='interrupted' for r in snapshot(db)['runs'])
    set_policy(False, 3600, db)
    assert claim('B', 'b', now=10000, path=db) is None
    assert snapshot(db)['policy']['enabled'] == 0


def test_empty_list_requires_explicit_api_success():
    from types import SimpleNamespace
    import pytest
    from src.platform_adapter.sync_workflow import SyncWorkflow
    workflow = SyncWorkflow(None)
    def page(payload, status=200):
        return SimpleNamespace(request=SimpleNamespace(get=lambda url: SimpleNamespace(status=status, json=lambda: payload)))
    for payload in ({}, {'status_code': 8}, {'status_code': 0}):
        with pytest.raises(RuntimeError):
            workflow._fetch_video_page(page(payload))
    with pytest.raises(RuntimeError):
        workflow._fetch_video_page(page({}, 401))
    assert workflow._fetch_video_page(page({'status_code': 0, 'aweme_list': [], 'has_more': False})) == ([], False, 0)


def test_correction_preserves_old_result_and_requests_one_recheck(tmp_path):
    from src.scheduler.account_refresh import request_recheck
    db = tmp_path/'schedule.db'
    first = claim('A', 'a', now=100, path=db)
    finish(first, 'completed', {'videos': 0}, now=110, path=db)
    request_recheck(first, '接口结果需复核', db)
    old = snapshot(db)['runs'][0]
    assert old['status'] == 'completed' and old['correction'] == '接口结果需复核'
    assert claim('A', 'a', now=120, path=db)
    assert claim('A', 'a', now=121, path=db) is None


def test_smart_operations_have_independent_daily_schedule(tmp_path):
    db = tmp_path/'schedule.db'
    metric_run = claim('A', 'a', now=100, path=db)
    smart_run = claim_smart('A', 'a', now=100, path=db)
    assert metric_run and smart_run
    finish(metric_run, 'completed', {'videos': 2}, now=110, path=db)
    finish_smart(smart_run, 'completed', {'topics': ['装修合同']}, now=120, path=db)
    assert claim('A', 'a', now=4*3600+111, path=db)
    assert claim_smart('A', 'a', now=4*3600+121, path=db) is None
    assert claim_smart('A', 'a', now=86400+121, path=db)


def test_smart_policy_can_be_disabled_without_disabling_metric_sync(tmp_path):
    db = tmp_path/'schedule.db'
    set_smart_policy(False, 86400, db)
    assert claim_smart('A', 'a', now=100, path=db) is None
    assert claim('A', 'a', now=100, path=db)
    state = snapshot(db)
    assert state['smart_policy']['enabled'] == 0
    assert state['policy']['enabled'] == 1
