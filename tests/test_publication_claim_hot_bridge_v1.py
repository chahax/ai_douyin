"""Isolated owner-thread hot bridge tests; no real ARM/service/browser calls."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import types
from types import SimpleNamespace as NS

import psutil
import pytest

from src.operations_accounts import publication_claim_hot_bridge_v1 as bridge
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return bridge.reference(path)


class OldRejection(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@pytest.fixture
def example(tmp_path, monkeypatch):
    # Isolate reviewed-source mutations in this private project-data directory.
    sources = {}
    paths = {}
    for key, original in bridge.SOURCE_PATHS.items():
        target = tmp_path / ('source_' + key + '.py')
        target.write_bytes(original.read_bytes())
        sources[key] = bridge.reference(target)
        paths[key] = target
    monkeypatch.setattr(bridge, 'SOURCE_PATHS', paths)
    arm = tmp_path / 'new_arm.json'
    monkeypatch.setattr(bridge, 'ARM', arm)
    store = BrowserControlStore(tmp_path / 'control.db')
    owner = 'backend:' + str(os.getpid()) + ':bridge-owner'
    account, version = 'account:bridge-test', 'original-binding'
    acquired = store.acquire_owner(account, version, owner)
    generation = acquired['generation']
    original = store.submit(account, version, 'publish', 'publish:test-media', {'request': {'title': '原视频'}, 'video_sha256': 'test-media'}, 100)
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id=?,generation=?,result=? WHERE command_id=?",
                   (owner, generation, json.dumps({'status': 'submission_unknown'}), original['command_id']))
    original = store.get(original['command_id'])
    queued = store.submit(account, version, 'publication_verify', 'publication-verify:explicit-approved',
        dict(original_command_id=original['command_id'], original_snapshot_sha256=bridge._digest(original),
             account_key='novel-test', attempt=4), 400)
    control = tmp_path / 'refresh.db'
    with sqlite3.connect(control) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,state TEXT)')
        db.execute('INSERT INTO account_controls VALUES(?,?)', (account, 'paused'))
    config = dict(schema='publication_claim_hot_bridge_config/v1', backend_pid=os.getpid(),
        backend_create_time=psutil.Process().create_time(), account_key='novel-test', account_id=account,
        owner_id=owner, generation=generation, binding_version=version, browser_db=str(store.path), control_db=str(control),
        original_command_id=original['command_id'], verification_command_id=queued['command_id'],
        verification_request_sha256=queued['request_sha'], sources=sources)
    config_ref = put(tmp_path / 'CONFIG.json', config)
    events = []
    def previous_claim(*args, **kwargs):
        events.append(('previous_claim', args, kwargs))
        return None
    previous_claim._paused_browser_claim_guard = True
    store.claim_next = previous_claim
    def check_owner():
        events.append('owner_checked')
        with store._db() as db:
            store._owner(db, account, owner, generation, version)
    actor = NS(account_id=account, owner_id=owner, generation=generation, binding_version=version, store=store, _stack=[],
        _assert_thread=lambda: events.append(('owner_thread_checked', threading.get_ident())), _check_owner=check_owner)
    resource = NS(account_uuid=account, manual_tasks={}, console_tasks={}, session=object())
    def previous_poll(actor, resource):
        events.append('previous_poll')
    namespace = {'_poll_manual_windows': previous_poll, 'BrowserControlRejected': OldRejection}
    code = compile('def _host(account_key):\n    return None\n', str(bridge.HOST_PATH), 'exec')
    exec(code, namespace)
    target = namespace['_host']
    thread = NS(name='AccountBrowser-novel-test', _target=target, _args=('novel-test',), is_alive=lambda: True)
    monkeypatch.setattr(bridge.threading, 'enumerate', lambda: [thread])
    return NS(folder=tmp_path, config=config, config_ref=config_ref, original=original, queued=queued,
              store=store, actor=actor, resource=resource, namespace=namespace, previous_poll=previous_poll,
              previous_claim=previous_claim, arm=arm, events=events, control=control, paths=paths)


def arm(example):
    plan = bridge.prepare_plan(example.config_ref, example.folder / 'new_plan')
    put(example.arm, dict(schema='publication_claim_hot_bridge_arm/v1', plan=plan))
    return plan


def install(example):
    plan = arm(example)
    assert bridge.install_if_armed()['status'] == 'callback_registered_waiting_original_actor_tick'
    assert not (example.folder / 'new_plan' / 'ACTOR_INSTALLED_RECEIPT.json').exists()
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    return plan


def claim(example, **kwargs):
    c = example.config
    return example.store.claim_next(c['account_id'], c['binding_version'], c['owner_id'], c['generation'], **kwargs)


def test_absent_arm_is_inert(example):
    assert bridge.install_if_armed() == {'status': 'not_armed'}
    assert example.store.claim_next is example.previous_claim
    assert example.events == []


def test_plan_is_readonly_and_does_not_arm(example):
    before = example.store.get(example.queued['command_id'])
    ref = bridge.prepare_plan(example.config_ref, example.folder / 'plan_only')
    assert Path(ref['path']).is_file() and not example.arm.exists()
    assert example.store.get(example.queued['command_id']) == before
    assert example.store.claim_next is example.previous_claim


def test_ui_receipt_does_not_claim_or_install_actor(example):
    arm(example)
    before = example.store.get(example.queued['command_id'])
    assert bridge.install_if_armed()['status'] == 'callback_registered_waiting_original_actor_tick'
    assert example.store.claim_next is example.previous_claim
    assert example.store.get(example.queued['command_id']) == before
    assert (example.folder / 'new_plan' / 'UI_IMPORT_RECEIPT.json').is_file()
    assert bridge.install_if_armed()['status'] == 'callback_already_registered'


def test_actor_safe_tick_installs_and_only_claims_original_readback(example):
    original = example.store.get(example.original['command_id'])
    queued = example.store.get(example.queued['command_id'])
    install(example)
    receipt = json.loads((example.folder / 'new_plan' / 'ACTOR_INSTALLED_RECEIPT.json').read_text())
    assert receipt['private_store_only'] and receipt['paused_guard_reinstalled']
    assert 'allowed_kinds' in receipt['loaded_claim']['signature']
    assert receipt['loaded_claim']['sys_modules_replaced'] is False
    assert example.store.get(example.queued['command_id']) == queued
    assert example.namespace['_poll_manual_windows'] is example.previous_poll
    selected = claim(example)
    assert selected['command_id'] == queued['command_id'] and selected['state'] == 'running'
    assert selected['owner_id'] == example.config['owner_id']
    assert example.store.get(example.original['command_id']) == original
    with sqlite3.connect(example.control) as db:
        assert db.execute('SELECT state FROM account_controls').fetchone()[0] == 'paused'
    assert example.resource.manual_tasks == example.resource.console_tasks == {}


@pytest.mark.parametrize('busy', ['stack', 'manual', 'console'])
def test_busy_actor_does_not_install(example, busy):
    arm(example)
    bridge.install_if_armed()
    if busy == 'stack':
        example.actor._stack.append(object())
    else:
        getattr(example.resource, busy + '_tasks')['original'] = 'original-tab'
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    assert example.store.claim_next is example.previous_claim
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'
    assert not (example.folder / 'new_plan' / 'ACTOR_INSTALLED_RECEIPT.json').exists()
    assert example.namespace['_poll_manual_windows'] is not example.previous_poll
    example.actor._stack.clear()
    example.resource.manual_tasks.clear()
    example.resource.console_tasks.clear()
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    assert (example.folder / 'new_plan' / 'ACTOR_INSTALLED_RECEIPT.json').is_file()


def test_sources_changed_after_hook_fail_closed(example):
    arm(example)
    bridge.install_if_armed()
    example.paths['core'].write_text('# changed after callback registration', encoding='utf-8')
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    assert example.store.claim_next is example.previous_claim
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'


def test_sources_changed_after_install_do_not_claim(example):
    install(example)
    example.paths['core'].write_text('# changed after actor installed', encoding='utf-8')
    assert claim(example) is None
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'


def test_owner_changed_after_hook_fail_closed(example):
    arm(example)
    bridge.install_if_armed()
    with example.store._db(write=True) as db:
        db.execute('UPDATE browser_control_owners SET generation=generation+1')
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    assert example.store.claim_next is example.previous_claim
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'


def test_verification_changed_after_hook_fail_closed(example):
    arm(example)
    bridge.install_if_armed()
    with example.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET request_sha='changed' WHERE command_id=?", (example.queued['command_id'],))
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    assert example.store.claim_next is example.previous_claim


def test_allowed_mask_excluding_verify_does_not_escalate(example):
    install(example)
    assert claim(example, kinds=('read',)) is None
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'


def test_after_target_finishes_other_routes_delegate_previous(example):
    install(example)
    assert claim(example)['command_id'] == example.queued['command_id']
    assert claim(example) is None
    assert any(isinstance(x, tuple) and x[0] == 'previous_claim' for x in example.events)


def test_loaded_new_exception_is_normalized_and_not_raised_to_host(example, monkeypatch):
    class NewRejection(RuntimeError):
        def __init__(self):
            self.code = 'test-new-class'
    def refused(*args, **kwargs):
        raise NewRejection()
    monkeypatch.setattr(bridge, '_load_claim', lambda config: (refused, NewRejection, dict(test='isolated-exception')))
    install(example)
    assert claim(example) is None
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'
    evidence = json.loads((example.folder / 'new_plan' / 'REFUSED_CLAIM.json').read_text())
    assert evidence['error_type'] == 'OldRejection'


def test_live_process_identity_must_match(example):
    config = dict(example.config, backend_create_time=example.config['backend_create_time'] + 1)
    ref = put(example.folder / 'WRONG_CONFIG.json', config)
    with pytest.raises(ValueError, match='process_identity_changed'):
        bridge.prepare_plan(ref, example.folder / 'wrong_plan')
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'


def test_app_hook_is_before_navigation_and_login_stop():
    source = (bridge.ROOT / 'src/web/app.py').read_text(encoding='utf-8')
    hook = source.index('_install_publication_claim_bridge()')
    assert hook < source.index('navigation = st.navigation(')
    assert hook < source.index('if not render_login_page(')


def test_same_arm_after_install_does_not_layer_wrappers(example):
    install(example)
    installed_claim = example.store.claim_next
    assert bridge.install_if_armed()['status'] == 'actor_install_already_recorded'
    assert example.store.claim_next is installed_claim
    assert example.namespace['_poll_manual_windows'] is example.previous_poll


@pytest.mark.parametrize('stage', ['before_tick', 'after_install'])
def test_changed_arm_fails_closed(example, stage):
    arm(example)
    bridge.install_if_armed()
    if stage == 'after_install':
        example.namespace['_poll_manual_windows'](example.actor, example.resource)
    example.arm.write_text('{}', encoding='utf-8')
    if stage == 'before_tick':
        example.namespace['_poll_manual_windows'](example.actor, example.resource)
        assert example.store.claim_next is example.previous_claim
    else:
        assert claim(example) is None
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'


def test_wrong_actor_thread_refuses_install(example):
    arm(example)
    bridge.install_if_armed()
    example.actor._assert_thread = lambda: (_ for _ in ()).throw(OldRejection('wrong_thread', 'not actor thread'))
    example.namespace['_poll_manual_windows'](example.actor, example.resource)
    assert example.store.claim_next is example.previous_claim
    assert example.store.get(example.queued['command_id'])['state'] == 'queued'
