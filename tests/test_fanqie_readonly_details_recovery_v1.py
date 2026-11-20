"""Real private control DB; synthetic stopped read-worker evidence, no browser."""
import json
import pytest
from src.operations_accounts import fanqie_readonly_details_recovery_v1 as recovery
from src.operations_accounts.browser_control import BrowserControlStore


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
    return recovery.bind(path)


@pytest.fixture
def original(tmp_path):
    from test_fanqie_managed_promotion_v1 import accounts
    a, env = accounts.__wrapped__(tmp_path)
    book, name, alias = '7302660145530539062', 'fixture book', 'fixture alias'
    c = a.queue(env['resource_id'], 'fanqie_filled_details', book_id=book, book_name=name, lookup_alias=alias)
    store = BrowserControlStore(a.db)
    owner = store.acquire_owner(env['resource_id'], env['binding_version'], 'private-read-owner')
    c = store.claim_next(env['resource_id'], env['binding_version'], owner['owner_id'], owner['generation'])
    c = store.transition(c['command_id'], c['owner_id'], c['generation'], 'outcome_unknown',
        error_code='handler_exception:DetailsNotConfirmed', result={'error_type':'DetailsNotConfirmed',
        'failure_phase':'handler', 'handler_started':True})
    subject = dict(resource_id=env['resource_id'], binding_version=env['binding_version'],
        environment_key=env['environment_key'], platform_identity_key='uid:12345', owner_id=c['owner_id'],
        generation=c['generation'], task_id=c['command_id'])
    target = dict(book_id=book, book_name=name, alias=alias)
    selected = dict(index=0, label='已填写（1条）', count=1, cells=[alias, name+' id:'+book, '已填写（1条）'])
    panel = dict(schema='fanqie_filled_details_panel/v1', visible_panels=0, panel_observed=False,
        submission_performed=False, location={'origin':'https://kol.fanqieopen.com','path':'/page/promotion-list'})
    observations = {
        'ROW': dict(target=target, selected=selected),
        'CLICK_INTENT': dict(target=target, selected=selected, details_click_limit=1),
        'PANEL_BEFORE': dict(target=target, observation=panel),
        'PANEL': dict(target=target, observations=[panel.copy() for _ in range(20)]),
        'TABLE': dict(target=target, samples=[])}
    folder = a.folder(c['command_id']); folder.mkdir(parents=True, exist_ok=True)
    for stage, value in observations.items():
        put(folder/('FILLED_DETAILS_'+stage+'.json'), dict(schema='fanqie_filled_details_step/v1',
            subject=subject, stage=stage.lower(), observation=value))
    pid = 333333333
    assert not recovery.psutil.pid_exists(pid)
    put(folder/'WORKER_PROCESS.json', dict(command_id=c['command_id'], pid=pid))
    put(folder/'WORKER_LAUNCH.json', dict(command_id=c['command_id'], created_at=0))
    (folder/'worker.log').write_text('browser_worker_start stage=ready\nBrowser session stopped.\n', encoding='utf8')
    acceptance = put(tmp_path/'ACCEPTANCE.json', dict(sources={key:recovery.bind(recovery.ROOT/key)
        for key in recovery.SOURCE_KEYS}))
    intent = put(tmp_path/'INTENT.json', dict(schema='fanqie_existing_filled_details_read_intent/v1',
        only_read_details=True, uploads_allowed=0, submissions_allowed=0, resource_id=env['resource_id'],
        binding_version=env['binding_version'], expected_platform_identity_key='uid:12345',
        book_id=book, book_name=name, alias=alias, source_acceptance=acceptance))
    return a, env, c, intent, tmp_path


def test_exact_read_disposition_keeps_unknown_and_cached_reentry_leaves_new_owner(original):
    a, env, c, intent, folder = original
    plan = recovery.prepare_recovery(a, c['command_id'], intent, folder/'recovery')
    result = recovery.settle_recovery(a, plan)
    assert result['state'] == 'failed'
    assert result['result']['before_snapshot'] == c
    assert result['result']['original_request_replayed'] is False
    store = BrowserControlStore(a.db)
    new_owner = store.acquire_owner(env['resource_id'], env['binding_version'], 'later-read-owner')
    assert recovery.settle_recovery(a, plan) == result
    assert store.operational_snapshot(env['resource_id'])['owner']['owner_id'] == new_owner['owner_id']
    assert store.operational_snapshot(env['resource_id'])['owner']['state'] == 'active'


def test_live_original_process_prevents_disposition(original, monkeypatch):
    a, env, c, intent, folder = original
    monkeypatch.setattr(recovery.psutil, 'pid_exists', lambda pid: True)
    with pytest.raises(ValueError, match='original_readonly_owner_not_exited'):
        recovery.prepare_recovery(a, c['command_id'], intent, folder/'recovery')
    assert BrowserControlStore(a.db).get(c['command_id']) == c


def test_write_kind_cannot_use_readonly_disposition(original):
    a, env, c, intent, folder = original
    with a.connection(True) as db:
        db.execute("UPDATE browser_control_commands SET kind='fanqie_backfill' WHERE command_id=?", (c['command_id'],))
    with pytest.raises(ValueError, match='exact_original_details_read_failure_required'):
        recovery.prepare_recovery(a, c['command_id'], intent, folder/'recovery')
    assert BrowserControlStore(a.db).get(c['command_id'])['state'] == 'outcome_unknown'
