"""Bounded private Store/Actor tests, with a file-only stand-in upload flow."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace as NS

import psutil
import pytest

from src.operations_accounts import manual_republication_runtime_v2 as bridge
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor


FLOW = '''import json
from pathlib import Path
def run_action(actor,resource,config,request,outdir):
    root=Path(config['authority']['path']).parent
    assert (root/'UPLOAD_CLAIM.json').is_file()
    outdir.mkdir(parents=True,exist_ok=True)
    selected=root/'FILE_SELECTED.json'
    if selected.exists():raise AssertionError('second selection')
    selected.write_text(json.dumps({'thread':__import__('threading').get_ident()}))
    metadata=json.loads(Path(config['metadata']['path']).read_text(encoding='utf-8'))
    return {'schema':'manual_republication_prepare_upload/v1','action':'prepare_upload',
      'uploaded':True,'submitted':False,'declaration_selected':False,'metadata_readback_matched':True,
      'upload_ready':True,'upload_attempted':True,'upload_completion_verified':True,'hashtag_readback_verified':True,
      'title_readback':{'content':metadata['title']},'description_readback':{'content':metadata['description']}}
'''


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return bridge.reference(path)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'ROOT', tmp_path)
    monkeypatch.setattr(bridge.files, 'ROOT', tmp_path)
    run = tmp_path / 'data/explicit_new_intent'
    run.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'RUN', run)
    monkeypatch.setattr(bridge, 'ARM', run / 'runtime_v2/ARM.json')
    monkeypatch.setattr(bridge, 'UPLOAD_CLAIM', run / 'UPLOAD_CLAIM.json')
    paths = {}
    for key, original in bridge.SOURCE_PATHS.items():
        path = tmp_path / 'src/operations_accounts' / (key + '.py')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original.read_bytes() if key == 'guard_v1' else
                         (FLOW if key == 'flow_v2' else '# source ' + key).encode())
        paths[key] = path
    monkeypatch.setattr(bridge, 'SOURCE_PATHS', paths)
    store = BrowserControlStore(tmp_path / 'data/browser.db')
    account, version, owner = 'account:isolated', 'original-binding', 'backend:' + str(os.getpid()) + ':owner'
    generation = store.acquire_owner(account, version, owner)['generation']
    manual = store.submit(account, version, 'manual', 'manual-original',
        {'account_key': 'original', 'account_uuid': account}, 200)
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='waiting_human',owner_id=?,generation=?,result=? WHERE command_id=?",
            (owner, generation, json.dumps({'tab_id': 'original-tab'}), manual['command_id']))
    control = tmp_path / 'data/control.db'
    with sqlite3.connect(control) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,state TEXT,revision INTEGER)')
        db.execute('INSERT INTO account_controls VALUES(?,?,?)', (account, 'paused', 59))
    media = run / 'unchanged.mp4'
    media.write_bytes(b'protocol-media-never-uploaded')
    authority = put(run / 'USER_AUTHORIZATION.json', dict(schema='explicit_republication_intent/v1',
        user_statement='publish again with declarations', account_key='original', account_uuid=account,
        expected_public_uid='7589', media=bridge.reference(media), old_post_id='7709043480894524722',
        new_publication_limit=1, model_media_calls_allowed=False, old_records_unchanged=True,
        declaration_requirement='actual applicable native controls'))
    op = put(run / 'BACKEND_OPERATION_AUTHORIZATION.json', dict(schema='original_session_backend_operator_authorization/v1',
        parent_authority=authority, user_statement='use original browser owner', later_writes_require_reviewed_stage_plan=True,
        no_new_profile_or_owner_takeover=True, no_direct_private_platform_posting_endpoint=True,
        preserve_original_unknown_locks=True))
    metadata = put(run / 'PUBLICATION_METADATA_V2.json', dict(schema='manual_republication_metadata/v1',
        account_uuid=account, account_key='original', media=bridge.reference(media), title='exact title',
        description='本视频含小说推广信息。剧情虚构，非真实事件。画面声音由AI生成。',
        hashtags=['小说推文', '穿书', '小说剧情', 'AI短剧', 'AI生成'], ai_generated=True,
        fictional_story=True, visibility='public'))
    config = dict(schema=bridge.CONFIG_SCHEMA, backend_pid=os.getpid(), backend_create_time=psutil.Process().create_time(),
        account_key='original', account_id=account, owner_id=owner, generation=generation, binding_version=version,
        browser_db=str(store.path), control_db=str(control), control_snapshot={'state': 'paused', 'revision': 59},
        manual_command_id=manual['command_id'], manual_request_sha256=manual['request_sha'], tab_id='original-tab',
        authority=authority, operator_authority=op, metadata=metadata,
        sources={key: bridge.reference(path) for key, path in paths.items()})
    config_ref = put(run / 'CONFIG.json', config)
    request = dict(schema=bridge.REQUEST_SCHEMA, config=config_ref, action='prepare_upload')
    request_ref = put(run / 'REQUEST.json', request)
    actor = BrowserControlActor(store, account, version, owner, {})
    actor.generation, actor._thread_id = generation, threading.get_ident()
    resource = NS(account_uuid=account, manual_tasks={manual['command_id']: 'original-tab'}, console_tasks={},
        session=NS(config=NS(headless=False), _proc=NS(poll=lambda: None), worker_failure=lambda: ''))
    events = []
    def previous(actor, resource):
        events.append('previous_poll')
    namespace = {'_poll_manual_windows': previous}
    exec(compile('def _host(key): pass', str(paths['host']), 'exec'), namespace)
    thread = NS(name='AccountBrowser-original', _target=namespace['_host'], _args=('original',), is_alive=lambda: True)
    monkeypatch.setattr(bridge.threading, 'enumerate', lambda: [thread])
    return NS(run=run, config=config, config_ref=config_ref, request=request, request_ref=request_ref,
        store=store, actor=actor, resource=resource, manual=manual, namespace=namespace, previous=previous,
        events=events, control=control, paths=paths, media=media)


def plan(c, name='plan_001', request_ref=None):
    return bridge.prepare(c.config_ref, request_ref or c.request_ref, c.run / name)


def arm(c, ref=None):
    ref = ref or plan(c)
    put(bridge.ARM, dict(schema='manual_republication_runtime_arm/v2', plan=ref))
    return ref


def test_absent_arm_inert_no_config_or_io(case, monkeypatch):
    monkeypatch.setattr(bridge, '_config', lambda *args: pytest.fail('config read'))
    assert bridge.install_if_armed() == {'status': 'not_armed'}
    assert not case.events and not bridge.UPLOAD_CLAIM.exists()


def test_original_actor_once_global_claim_precedes_preparation(case):
    before = case.store.get(case.manual['command_id'])
    ref = arm(case)
    assert bridge.install_if_armed()['status'].startswith('callback_registered')
    assert not bridge.UPLOAD_CLAIM.exists() and not (case.run / 'FILE_SELECTED.json').exists()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'prepared_no_submission'
    assert json.loads((case.run / 'FILE_SELECTED.json').read_text())['thread'] == threading.get_ident()
    claim = json.loads(bridge.UPLOAD_CLAIM.read_text())
    assert claim['metadata'] == case.config['metadata'] and claim['submissions_allowed'] == 0
    assert case.store.get(case.manual['command_id']) == before
    assert case.namespace['_poll_manual_windows'] is case.previous
    assert bridge.install_if_armed()['status'] == 'prepared_no_submission'


def test_unimplemented_actions_and_arbitrary_fields_rejected(case):
    for index, change in enumerate([dict(action='submit_once'), dict(action='set_declarations'),
                                    dict(action='inspect_form'), dict(url='https://example.org'), dict(eval='code')]):
        bad = put(case.run / f'bad_{index}.json', dict(case.request, **change))
        with pytest.raises(ValueError, match='prepare_only'):
            plan(case, f'bad_plan_{index}', bad)
    assert not bridge.UPLOAD_CLAIM.exists()


def test_changed_request_or_directory_cannot_get_second_upload_slot(case):
    first = plan(case)
    copied_request = put(case.run / 'REQUEST_COPY.json', case.request)
    second = plan(case, 'another_plan', copied_request)
    arm(case, first)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(second)['status'] == 'upload_slot_already_claimed'
    put(bridge.ARM, {'schema': 'manual_republication_runtime_arm/v2', 'plan': second})
    assert bridge.install_if_armed()['status'] == 'upload_slot_already_claimed'
    with pytest.raises(ValueError, match='slot_already_claimed'):
        plan(case, 'third')
    assert (case.run / 'FILE_SELECTED.json').exists()


def test_lost_upload_ack_is_unknown_never_replayed(case):
    case.paths['flow_v2'].write_text(FLOW.replace("return {'schema'", "raise RuntimeError('ack lost')\n    return {'schema'"), encoding='utf-8')
    case.config['sources']['flow_v2'] = bridge.reference(case.paths['flow_v2'])
    case.config_ref = put(case.run / 'CONFIG.json', case.config)
    case.request_ref = put(case.run / 'REQUEST.json', dict(case.request, config=case.config_ref))
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'outcome_unknown'
    assert bridge.install_if_armed()['status'] == 'outcome_unknown'
    with pytest.raises(ValueError, match='slot_already_claimed'):
        plan(case, 'newdir')
    assert (case.run / 'FILE_SELECTED.json').exists()


def test_partial_global_claim_blocks_every_plan(case):
    ref = arm(case)
    bridge.UPLOAD_CLAIM.write_bytes(b'{')
    assert bridge.install_if_armed()['status'] == 'outcome_unknown'
    assert not (case.run / 'FILE_SELECTED.json').exists()


def test_wrong_thread_never_calls_original_poll_or_flow(case):
    ref = arm(case)
    bridge.install_if_armed()
    case.actor._thread_id = threading.get_ident() + 1
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert not case.events and not bridge.UPLOAD_CLAIM.exists()
    assert bridge.status(ref)['status'] == 'prepared'


def test_source_mutation_after_registration_refused_before_claim(case):
    arm(case)
    bridge.install_if_armed()
    case.paths['flow_v2'].write_text(FLOW + '\n# changed', encoding='utf-8')
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert not bridge.UPLOAD_CLAIM.exists() and not (case.run / 'FILE_SELECTED.json').exists()


def test_changed_authorized_media_rejected_before_plan(case):
    case.media.write_bytes(b'changed')
    with pytest.raises(ValueError, match='authorized_media_changed'):
        plan(case)
    assert not bridge.UPLOAD_CLAIM.exists()


def test_control_or_page_change_refused_before_file_selection(case):
    arm(case)
    bridge.install_if_armed()
    case.resource.manual_tasks[case.manual['command_id']] = 'other-tab'
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert not bridge.UPLOAD_CLAIM.exists() and not (case.run / 'FILE_SELECTED.json').exists()


def test_completed_result_tamper_fails_cache_no_rerun(case):
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    result = Path(ref['path']).parent / 'RESULT.json'
    data = json.loads(result.read_text(encoding='utf-8'))
    data['preparation']['submitted'] = True
    result.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='cached_receipt_changed'):
        bridge.status(ref)
    assert bridge.install_if_armed()['status'] == 'refused'


@pytest.mark.parametrize('change', ["'upload_ready':False", "'title_readback':{'content':'wrong title'}"])
def test_incomplete_or_wrong_readback_cannot_be_prepared(case, change):
    code = FLOW.replace("'upload_ready':True", change) if 'upload_ready' in change else FLOW.replace(
        "'title_readback':{'content':metadata['title']}", change)
    case.paths['flow_v2'].write_text(code, encoding='utf-8')
    case.config['sources']['flow_v2'] = bridge.reference(case.paths['flow_v2'])
    case.config_ref = put(case.run / 'CONFIG.json', case.config)
    case.request_ref = put(case.run / 'REQUEST.json', dict(case.request, config=case.config_ref))
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'outcome_unknown'
    assert bridge.UPLOAD_CLAIM.exists() and not (Path(ref['path']).parent / 'RESULT.json').exists()


def test_cli_prepare_and_status_cannot_arm_or_execute(case, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[1] / 'scripts/run_manual_republication_runtime_v2.py'
    spec = importlib.util.spec_from_file_location('manual_upload_cli_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'runtime', bridge)
    folder = case.run / 'cli_plan'
    assert module.main(['prepare', '--config', case.config_ref['path'], '--request', case.request_ref['path'],
                        '--output-directory', str(folder)]) == 0
    assert module.main(['status', '--plan', str(folder / 'PLAN.json')]) == 0
    assert 'prepared' in capsys.readouterr().out
    assert not bridge.ARM.exists() and not bridge.UPLOAD_CLAIM.exists()
