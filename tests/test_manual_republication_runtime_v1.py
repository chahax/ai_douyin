"""Private real Store/Actor protocol tests; no browser, network or service work."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace as NS

import psutil
import pytest

from src.operations_accounts import manual_republication_runtime_v1 as bridge
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor


FLOW = '''import json
def run_action(actor,resource,config,request,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    calls=outdir/'CALLED.json'
    if calls.exists():raise AssertionError('duplicate_action')
    calls.write_text(json.dumps({'thread_id':__import__('threading').get_ident()}))
    return {'schema':'manual_republication_inspection/v1','action':request['action'],
        'view':request['view'],'read_only':True,'uploaded':False,'submitted':False}
'''


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return bridge.reference(path)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'ROOT', tmp_path)
    run = tmp_path / 'data/new_intent'
    run.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'RUN', run)
    monkeypatch.setattr(bridge, 'ARM', run / 'runtime/ARM.json')
    paths = {}
    for key in bridge.SOURCE_PATHS:
        path = tmp_path / ('source_' + key + '.py')
        path.write_text(FLOW if key == 'flow' else '# reviewed ' + key, encoding='utf-8')
        paths[key] = path
    monkeypatch.setattr(bridge, 'SOURCE_PATHS', paths)
    store = BrowserControlStore(tmp_path / 'data/browser.db')
    account, version, owner = 'account:isolated', 'binding-original', 'backend:' + str(os.getpid()) + ':original'
    generation = store.acquire_owner(account, version, owner)['generation']
    command = store.submit(account, version, 'manual', 'original-manual',
        {'account_key': 'original', 'account_uuid': account}, 200)
    tab = 'original-tab'
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='waiting_human',owner_id=?,generation=?,result=? WHERE command_id=?",
                   (owner, generation, json.dumps({'tab_id': tab}), command['command_id']))
    control = tmp_path / 'data/control.db'
    with sqlite3.connect(control) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,state TEXT,revision INTEGER)')
        db.execute('INSERT INTO account_controls VALUES(?,?,?)', (account, 'paused', 12))
    media = run / 'authorized.mp4'
    media.write_bytes(b'protocol-only-media')
    authority = put(run / 'USER_AUTHORIZATION.json', dict(schema='explicit_republication_intent/v1',
        user_statement='publish once with applicable declarations', account_key='original', account_uuid=account,
        expected_public_uid='7589', media=bridge.reference(media), old_post_id='7709043480894524722',
        new_publication_limit=1, model_media_calls_allowed=False, old_records_unchanged=True,
        declaration_requirement='actual declarations'))
    config = dict(schema=bridge.CONFIG_SCHEMA, backend_pid=os.getpid(),
        backend_create_time=psutil.Process().create_time(), account_key='original', account_id=account,
        owner_id=owner, generation=generation, binding_version=version, browser_db=str(store.path),
        control_db=str(control), control_snapshot={'state': 'paused', 'revision': 12},
        manual_command_id=command['command_id'], manual_request_sha256=command['request_sha'],
        tab_id=tab, authority=authority, sources={key: bridge.reference(path) for key, path in paths.items()})
    config_ref = put(run / 'CONFIG.json', config)
    request = dict(schema=bridge.REQUEST_SCHEMA, config=config_ref, action='inspect_site', view='upload')
    request_ref = put(run / 'REQUEST.json', request)
    actor = BrowserControlActor(store, account, version, owner, {})
    actor.generation, actor._thread_id = generation, threading.get_ident()
    resource = NS(account_uuid=account, manual_tasks={command['command_id']: tab}, console_tasks={},
        session=NS(config=NS(headless=False), _proc=NS(poll=lambda: None), worker_failure=lambda: ''))
    events = []
    def previous_poll(actor, resource):
        events.append('original_poll')
    namespace = {'_poll_manual_windows': previous_poll}
    exec(compile('def _host(key): pass', str(paths['host']), 'exec'), namespace)
    thread = NS(name='AccountBrowser-original', _target=namespace['_host'], _args=('original',), is_alive=lambda: True)
    monkeypatch.setattr(bridge.threading, 'enumerate', lambda: [thread])
    return NS(run=run, config=config, config_ref=config_ref, request=request, request_ref=request_ref,
        store=store, actor=actor, resource=resource, command=command, namespace=namespace,
        previous=previous_poll, events=events, control=control, paths=paths)


def plan(c):
    return bridge.prepare(c.config_ref, c.request_ref, c.run / 'inspection_001')


def arm(c, ref=None):
    ref = ref or plan(c)
    put(bridge.ARM, {'schema': 'manual_republication_runtime_arm/v1', 'plan': ref})
    return ref


def test_absent_arm_is_inert_no_db_or_browser(case, monkeypatch):
    monkeypatch.setattr(bridge, '_config', lambda *a: pytest.fail('config read'))
    assert bridge.install_if_armed() == {'status': 'not_armed'}
    assert not case.events


def test_prepare_and_registration_never_execute_then_owner_tick_once(case):
    before = case.store.get(case.command['command_id'])
    ref = arm(case)
    assert bridge.status(ref)['status'] == 'prepared'
    assert bridge.install_if_armed()['status'] == 'callback_registered_waiting_original_actor_tick'
    assert bridge.install_if_armed()['status'] == 'callback_already_registered'
    assert not (Path(ref['path']).parent / 'ACTION_CLAIM.json').exists()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'inspected'
    called = json.loads((Path(ref['path']).parent / 'inspection/CALLED.json').read_text())
    assert called['thread_id'] == threading.get_ident()
    assert case.store.get(case.command['command_id']) == before
    assert case.resource.manual_tasks == {case.command['command_id']: case.config['tab_id']}
    assert case.namespace['_poll_manual_windows'] is case.previous
    assert bridge.install_if_armed()['status'] == 'inspected'
    assert case.events == ['original_poll']


@pytest.mark.parametrize('changes', [dict(action='submit'), dict(url='https://example.org'), dict(eval='anything')])
def test_arbitrary_actions_url_or_code_rejected(case, changes):
    request_ref = put(case.run / 'OTHER_REQUEST.json', dict(case.request, **changes))
    with pytest.raises(ValueError, match='inspection_only'):
        bridge.prepare(case.config_ref, request_ref, case.run / 'other_plan')
    assert not case.events


def test_changed_scope_source_or_auth_refused_before_claim(case):
    ref = arm(case)
    assert bridge.install_if_armed()['status'].startswith('callback_registered')
    case.paths['flow'].write_text(FLOW + '\n# changed', encoding='utf-8')
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert not (Path(ref['path']).parent / 'ACTION_CLAIM.json').exists()
    assert json.loads((Path(ref['path']).parent / 'REFUSED.json').read_text())['action_started'] is False


@pytest.mark.parametrize('change', ['manual_closed', 'wrong_tab', 'control_changed', 'dead_worker'])
def test_original_manual_resource_changes_refuse_no_action(case, change):
    ref = arm(case)
    bridge.install_if_armed()
    if change == 'manual_closed':
        with case.store._db(write=True) as db:
            db.execute("UPDATE browser_control_commands SET state='succeeded' WHERE command_id=?", (case.command['command_id'],))
    elif change == 'wrong_tab':
        case.resource.manual_tasks[case.command['command_id']] = 'another-tab'
    elif change == 'control_changed':
        with sqlite3.connect(case.control) as db:
            db.execute('UPDATE account_controls SET revision=13')
    else:
        case.resource.session._proc.poll = lambda: 1
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'prepared'
    assert not (Path(ref['path']).parent / 'inspection/CALLED.json').exists()


def test_busy_actor_defers_until_same_original_safe_tick(case):
    ref = arm(case)
    bridge.install_if_armed()
    case.actor._stack = [object()]
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'prepared'
    case.actor._stack = []
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'inspected'


def test_wrong_thread_refuses_before_ordinary_page_poll(case):
    ref = arm(case)
    bridge.install_if_armed()
    case.actor._thread_id = threading.get_ident() + 1
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert not case.events
    assert not (Path(ref['path']).parent / 'ACTION_CLAIM.json').exists()


def test_known_call_error_keeps_claim_unknown_and_never_replays(case):
    case.paths['flow'].write_text('def run_action(*args): raise RuntimeError("lost acknowledgement")', encoding='utf-8')
    case.config['sources']['flow'] = bridge.reference(case.paths['flow'])
    case.config_ref = put(case.run / 'CONFIG.json', case.config)
    case.request_ref = put(case.run / 'REQUEST.json', dict(case.request, config=case.config_ref))
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'outcome_unknown'
    assert bridge.install_if_armed()['status'] == 'outcome_unknown'
    assert case.namespace['_poll_manual_windows'] is case.previous


def test_partial_claim_is_unknown_not_reexecuted(case):
    ref = arm(case)
    folder = Path(ref['path']).parent
    (folder / 'ACTION_CLAIM.json').write_bytes(b'{')
    assert bridge.install_if_armed()['status'] == 'outcome_unknown'
    assert not (folder / 'inspection').exists()


@pytest.mark.parametrize('code,expected', [('inspection_creator_surface_unconfirmed', True),
                                         ('private_page_text', False)])
def test_only_reviewed_typed_safe_reason_persisted(case, code, expected):
    case.paths['flow'].write_text('''
class InspectionBlocked(ValueError):
    def __init__(self,code):self.code=code;super().__init__('sensitive text must not persist')
BLOCK_REASONS=frozenset({'inspection_creator_surface_unconfirmed'})
def run_action(*args):raise InspectionBlocked(''' + repr(code) + ')', encoding='utf-8')
    case.config['sources']['flow'] = bridge.reference(case.paths['flow'])
    case.config_ref = put(case.run / 'CONFIG.json', case.config)
    case.request_ref = put(case.run / 'REQUEST.json', dict(case.request, config=case.config_ref))
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    raw = (Path(ref['path']).parent / 'UNKNOWN.json').read_text()
    result = json.loads(raw)
    assert ('reason_code' in result) is expected
    assert result['scope'] == 'read_only_inspection' and result['publication_outcome_changed'] is False
    assert 'sensitive' not in raw and 'private_page_text' not in raw


def test_cached_artifact_tamper_refused_no_reexecution(case):
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    folder = Path(ref['path']).parent
    claim = json.loads((folder / 'ACTION_CLAIM.json').read_text())
    claim['action'] = 'submit'
    (folder / 'ACTION_CLAIM.json').write_text(json.dumps(claim), encoding='utf-8')
    with pytest.raises(ValueError, match='cached_receipt_changed'):
        bridge.status(ref)


def test_cli_prepare_status_no_arm_install_or_dispatch(case, monkeypatch, capsys):
    source = Path(__file__).resolve().parents[1] / 'scripts/run_manual_republication_runtime_v1.py'
    spec = importlib.util.spec_from_file_location('manual_republication_cli_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'runtime', bridge)
    folder = case.run / 'cli_plan'
    assert module.main(['prepare', '--config', case.config_ref['path'], '--request', case.request_ref['path'],
                        '--output-directory', str(folder)]) == 0
    assert module.main(['status', '--plan', str(folder / 'PLAN.json')]) == 0
    assert not bridge.ARM.exists() and not case.events
    assert 'prepared' in capsys.readouterr().out
