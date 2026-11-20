"""Private broker/owner RPC tests and real isolated Chrome opener checks."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from playwright.sync_api import sync_playwright

from test_publication_claim_hot_bridge_v1 import example, OldRejection
from src.operations_accounts import publication_locator_provider_v1 as api
from src.operations_accounts import publication_claim_hot_bridge_v1 as bridge
from src.operations_accounts import browser_control_runtime as managed

POST = '1234567890123456789'
URL = 'https://www.douyin.com/video/' + POST


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return bridge.reference(path)


class Owner:
    def __init__(self):
        self.calls = []
        self.duration = 120.667
        self.response = {'original_response_object': True}

    def cmd(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == 'evaluate':
            return {'status': 'ok', 'value': dict(origin='https://www.douyin.com', path='/video/'+POST,
                post_id=POST, video_count=1, seconds=self.duration)}
        if action == 'discover_published_work':
            return {'status': 'ok', 'evidence': {'legacy_worker_called': True}}
        return self.response


@pytest.fixture
def prepared(example, monkeypatch):
    e = example
    monkeypatch.setattr(api, 'ROOT', e.folder)
    monkeypatch.setattr(api, 'ARM', e.folder/'data/ARM.json')
    monkeypatch.setattr(api, 'POLICIES', e.folder/'data/policies')
    refs, paths = {}, {}
    for name, original in api.SOURCE_PATHS.items():
        path = e.folder/('provider_source_'+name+'.py')
        path.write_bytes(original.read_bytes())
        refs[name], paths[name] = bridge.reference(path), path
    monkeypatch.setattr(api, 'SOURCE_PATHS', paths)
    monkeypatch.setattr(api, 'LOCATOR', paths['locator'])
    media = e.folder/'full.mp4'; media.write_bytes(b'synthetic full-video bytes only')
    media_ref = bridge.reference(media)
    auth = put(e.folder/'PUBLISH.json', dict(publish_authorized=True, candidate_id='new-full', media=media_ref))
    request = dict(title='完整新视频', description='AI虚构剧情', hashtags=['小说'], visibility='public',
                   video_path=str(media), ai_generated=True, fictional_story=True)
    command = e.store.submit(e.config['account_id'], e.config['binding_version'], 'publish',
        'publish:'+media_ref['sha256'], dict(account_key=e.config['account_key'], account_uuid=e.config['account_id'],
        request=request, authorization=auth, video_sha256=media_ref['sha256']), 100)
    frozen = dict(media=media_ref, book_id='1234567890123456789',
                  account=dict(account_uuid=e.config['account_id'], account_key=e.config['account_key'], binding_version=e.config['binding_version']))
    candidate = dict(command_id=command['command_id'], frozen_json=json.dumps(frozen),
        prepared_json=json.dumps(dict(request=request, authorization=auth)), task_id=2, video_job_id=6)
    context = NS(account_uuid=e.config['account_id'], account_key=e.config['account_key'],
                 binding=NS(platform_identity_key='public_uid:75891235130'))
    monkeypatch.setattr(managed, 'binding_version', lambda ctx: e.config['binding_version'])
    authority = put(e.folder/'USER.json', dict(user_statement='弃用旧片，只发布新两分钟完整版。'))
    spec = dict(schema='publication_locator_provider_spec/v1', account_key=e.config['account_key'],
        account_uuid=e.config['account_id'], candidate_id='new-full', publish_command_id=command['command_id'],
        media=media_ref, expected_duration_seconds=120.667, authority_reference=authority,
        user_statement='仅将新原始发布与其自动只读核验接入受管定位器。', sources=refs)
    e.spec = put(e.folder/'SPEC.json', spec)
    before = e.store.get(command['command_id'])
    e.scope_ref = api.prepare_scope(e.spec, e.folder/'data/scope', store=e.store,
        runtime=NS(resolve=lambda key, **kw: context), candidate_reader=lambda cid: candidate)
    assert e.store.get(command['command_id']) == before
    config = {k: e.config[k] for k in ('backend_pid','backend_create_time','owner_id','generation','account_key','binding_version','browser_db')}
    config.update(schema='publication_locator_provider_runtime/v1', account_uuid=e.config['account_id'], sources=refs)
    e.provider_config = config
    e.provider_config_ref = put(e.folder/'PROVIDER_CONFIG.json', config)
    e.plan_ref = api.prepare_runtime(e.scope_ref, e.provider_config_ref, e.folder/'data/runtime')
    e.plan = json.loads(Path(e.plan_ref['path']).read_text(encoding='utf-8'))
    e.scope = json.loads(Path(e.scope_ref['path']).read_text(encoding='utf-8'))
    e.command = command
    e.owner = Owner()
    e.resource.session = e.owner
    e.resource.ensure_session = lambda: e.resource.session
    e.current = [None]
    e.namespace['active_context'] = lambda: e.current[0]
    e.resource.context = context
    e.locator_calls = []
    def locator(page, title, *, guard, scope, popup_access):
        guard()
        e.locator_calls.append((title, scope))
        assert page.tab_id == scope['tab_id']
        return dict(schema='published_work_discovery/v1', verified=True, post_id=POST, publish_url=URL,
            reason='exact_title_card_native_canonical_id', restriction_warning='流量减少',
            diagnostic=dict(locator='host_rpc_original_work/v1', review_status_evaluated=False,
                card_binding=dict(ready=True, card_status='流量减少', restriction_detail_available=True),
                cover_click_dispatched=True, new_popup_count=1))
    e.locator = locator
    monkeypatch.setattr(api, '_load_locator', lambda ref: (locator, dict(source=ref, code_sha256='fixture-loader', canonical_module_replaced=False)))
    e.paths = paths
    return e


def activate(e):
    api.register_policy(e.plan_ref)
    put(api.ARM, dict(schema='publication_locator_provider_arm/v1', plan=e.plan_ref))
    assert api.install_if_armed()['status'] == 'callback_registered_waiting_original_actor_tick'
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    assert (e.folder/'data/runtime/ACTOR_PROVIDER_READY.json').is_file()


def context(e, command=None):
    value = dict(command or e.command, state='running', owner_id=e.config['owner_id'], generation=e.config['generation'])
    ctx = NS(actor=e.actor, resource=e.resource, command=value, task_id=value['command_id'],
             binding_version=e.config['binding_version'], check_dispatch=e.actor._check_owner)
    e.current[0] = ctx
    return ctx


def journal(e, *, click=True):
    identity = dict(platform_identity_key=e.scope['platform_identity_key'], video_sha256=e.scope['media']['sha256'])
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    folder = e.folder/'data/publish_runs'; folder.mkdir(parents=True, exist_ok=True)
    request = e.command['payload']['request']
    prepared = dict(stage='prepared', at_bjt=datetime.fromtimestamp(e.command['created_at'], timezone.utc).isoformat(),
        account=e.scope['account_key'], account_uuid=e.scope['account_uuid'], platform_identity_key=e.scope['platform_identity_key'],
        video_sha256=e.scope['media']['sha256'], **request,
        ai_declaration_required=True, fiction_declaration_required=True)
    rows = [prepared, dict(stage='submission_started'),
        dict(stage='ai_declaration_verified', set_selected=True, evidence=dict(verified=True, label='内容由AI生成')),
        dict(stage='ai_declaration_verified', set_selected=False, evidence=dict(verified=True, label='内容由AI生成'))]
    if click:
        rows += [dict(stage='publish_click_dispatching', attempt=1), dict(stage='publish_click_returned', attempt=1)]
    path = folder/(key+'.original.jsonl')
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows)+'\n', encoding='utf-8')
    put(folder/(key+'.submitted.json'), dict(status='submission_started', journal=str(path)))


def test_policy_is_explicit_and_requires_actor_ready(prepared):
    e = prepared
    assert not api.POLICIES.exists()
    assert api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])
    api.register_policy(e.plan_ref)
    assert not api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])
    assert len(list(api.POLICIES.glob('*.json'))) == 2
    assert e.store.get(e.command['command_id'])['state'] == 'queued'


@pytest.mark.parametrize('missing', ['policy', 'marker', 'ready'])
def test_registered_policy_missing_any_component_fails_closed(prepared, missing):
    e = prepared; activate(e)
    cid = e.command['command_id']
    assert api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])
    path = api.POLICIES/(cid+('.json' if missing == 'policy' else '.required.json')) if missing != 'ready' else e.folder/'data/runtime/ACTOR_PROVIDER_READY.json'
    path.unlink()
    assert not api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])


def test_actor_install_and_same_arm_do_not_layer(prepared):
    e = prepared
    original_cmd, original_ensure = e.owner.cmd, e.resource.ensure_session
    api.register_policy(e.plan_ref); put(api.ARM, dict(schema='publication_locator_provider_arm/v1', plan=e.plan_ref))
    api.install_if_armed()
    assert e.owner.cmd == original_cmd and e.resource.ensure_session is original_ensure
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    installed = e.owner.cmd
    assert e.owner.cmd != original_cmd
    assert api.install_if_armed()['status'] == 'actor_install_already_recorded'
    assert e.owner.cmd is installed and e.resource.ensure_session() is e.owner


def test_only_new_target_discovery_uses_provider_other_rpcs_unchanged(prepared):
    e = prepared; activate(e); journal(e); context(e)
    result = e.owner.cmd('discover_published_work', title=e.command['payload']['request']['title'], tab_id='task-tab')
    assert result['evidence']['verified'] and len(e.locator_calls) == 1
    assert not any(x[0] == 'discover_published_work' for x in e.owner.calls)
    assert e.owner.cmd('upload_original_file', tab_id='task-tab') is e.owner.response
    assert e.owner.cmd('click_original_publish', tab_id='task-tab') is e.owner.response
    context(e, e.original)
    assert e.owner.cmd('discover_published_work', title='old discarded title', tab_id='old-tab')['evidence']['legacy_worker_called']
    assert len(e.locator_calls) == 1
    artifact = next((e.folder/'data/runtime/observations'/e.command['command_id']).glob('DISCOVERY_*.json'))
    observed = json.loads(artifact.read_text(encoding='utf-8'))['observed']
    assert observed['host_locator']['card_status'] == '流量减少'
    assert observed['host_locator']['review_status_evaluated'] is False


def test_discovery_requires_this_original_click(prepared):
    e = prepared; activate(e); journal(e, click=False); context(e)
    with pytest.raises(OldRejection, match='作用域'):
        e.owner.cmd('discover_published_work', title=e.command['payload']['request']['title'], tab_id='task-tab')
    assert e.locator_calls == []


@pytest.mark.parametrize('change', ['title', 'metadata', 'owner', 'source'])
def test_target_scope_changes_reject_without_legacy_fallback(prepared, change):
    e = prepared; activate(e); journal(e); ctx = context(e)
    title = e.command['payload']['request']['title']
    if change == 'title': title = 'different title'
    elif change == 'metadata':
        ctx.command = json.loads(json.dumps(ctx.command)); ctx.command['payload']['request']['description'] = 'changed'
    elif change == 'owner': e.actor.generation += 1
    else: e.paths['locator'].write_text('# source changed', encoding='utf-8')
    with pytest.raises(OldRejection):
        e.owner.cmd('discover_published_work', title=title, tab_id='task-tab')
    assert not any(x[0] == 'discover_published_work' for x in e.owner.calls)


def test_session_replacement_is_wrapped_and_old_session_rejected(prepared):
    e = prepared; activate(e); journal(e); context(e)
    old = e.owner
    new = Owner(); e.resource.session = new
    assert e.resource.ensure_session() is new
    assert new.cmd('discover_published_work', title=e.command['payload']['request']['title'], tab_id='task-tab')['evidence']['verified']
    with pytest.raises(OldRejection):
        old.cmd('discover_published_work', title=e.command['payload']['request']['title'], tab_id='task-tab')


@pytest.mark.parametrize('seconds,match', [(120.667, True), (121.0, True), (60.0, False)])
def test_real_locator_evaluate_api_records_numeric_duration_without_altering_reply(prepared, seconds, match):
    e = prepared; activate(e); journal(e); context(e)
    e.owner.duration = seconds
    e.owner.cmd('discover_published_work', title=e.command['payload']['request']['title'], tab_id='task-tab')
    result = e.owner.cmd('inspect_published_video', post_id=POST, tab_id='task-tab')
    assert result is e.owner.response
    artifact = next((e.folder/'data/runtime/observations'/e.command['command_id']).glob('DURATION_*.json'))
    observed = json.loads(artifact.read_text(encoding='utf-8'))['observed']
    assert observed['verified_numeric_duration'] and observed['native_player_seconds'] == seconds
    assert observed['matches_expected'] is match
    assert any(x[0] == 'evaluate' and x[1]['selector'] == 'html' for x in e.owner.calls)


def test_ready_owner_source_mismatch_and_nonoptin_unchanged(prepared):
    e = prepared; activate(e)
    assert not api.provider_ready(e.command, 'different-owner', e.config['generation'])
    assert not api.provider_ready(e.command, e.config['owner_id'], e.config['generation']+1)
    assert api.provider_ready(e.original, e.config['owner_id'], e.config['generation'])
    e.paths['provider'].write_text('# changed', encoding='utf-8')
    assert not api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])


@pytest.mark.parametrize('field', ['schema', 'publish_command_id', 'backend_pid', 'backend_create_time', 'loaded_locator'])
def test_ready_receipt_fields_are_bound_to_the_same_runtime(prepared, field):
    e = prepared; activate(e)
    assert api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])
    path = e.folder/'data/runtime/ACTOR_PROVIDER_READY.json'
    ready = json.loads(path.read_text(encoding='utf-8'))
    ready[field] = {} if field == 'loaded_locator' else 'different'
    put(path, ready)
    assert not api.provider_ready(e.command, e.config['owner_id'], e.config['generation'])


def test_only_original_auto_three_are_in_scope(prepared):
    e = prepared; activate(e)
    auto = dict(e.command, command_id='a'*32, kind='publication_verify',
        idempotency_key='publication-verify:'+e.command['command_id']+':1',
        payload=dict(original_command_id=e.command['command_id'], attempt=1))
    assert api.provider_ready(auto, e.config['owner_id'], e.config['generation'])
    auto['payload']['attempt'] = 4
    assert not api.provider_ready(auto, e.config['owner_id'], e.config['generation'])


def test_observation_disk_failure_does_not_change_discovery_reply(prepared, monkeypatch):
    e = prepared; activate(e); journal(e); context(e)
    monkeypatch.setattr(api._Provider, 'evidence', lambda *a, **kw: (_ for _ in ()).throw(OSError('fixture disk failure')))
    assert e.owner.cmd('discover_published_work', title=e.command['payload']['request']['title'], tab_id='task-tab')['evidence']['verified']


class ChromeRPC:
    def __init__(self, context, main):
        self.context, self.main, self.pages = context, main, {'main': main}
        self.closed = []

    def cmd(self, action, **kwargs):
        for page in self.context.pages:
            if page not in self.pages.values(): self.pages['popup-'+str(len(self.pages))] = page
        if action == 'list_tabs':
            return {'tabs': [dict(tab_id=k, role='publication' if k == 'main' else 'unclaimed', closed=p.is_closed(), url=p.url if not p.is_closed() else '') for k, p in self.pages.items()]}
        page = self.pages[kwargs['tab_id']]
        if action == 'evaluate':
            # Exact existing worker RPC shape: _Locator.evaluate(js) only.
            return {'value': page.locator(kwargs['selector']).nth(kwargs.get('index', 0)).evaluate(kwargs['js'])}
        if action == 'close_tab':
            self.closed.append(kwargs['tab_id']); page.close(); return {'closed': True}
        raise AssertionError(action)


@pytest.fixture(scope='module')
def chrome(tmp_path_factory):
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(str(tmp_path_factory.mktemp('provider_chrome')),
            channel='chrome', headless=True, args=['--mute-audio'])
        browser.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body='<!doctype html><html><body>isolated local fixture</body></html>'))
        yield browser
        browser.close()


@pytest.mark.parametrize('opener', ['same', 'other', 'noopener'])
def test_real_chrome_native_opener_proof_and_no_close_on_rejection(chrome, opener):
    main = chrome.new_page(); main.goto('https://creator.douyin.com/creator-micro/content/manage')
    rpc = ChromeRPC(chrome, main)
    provider = NS(guard=lambda ctx, owner: None,
        reject=lambda code: (_ for _ in ()).throw(OldRejection(code, code)))
    popups = api._Popups(provider, rpc, rpc.cmd, object(), 'main')
    popups.snapshot()
    other = chrome.new_page() if opener == 'other' else None
    if other:
        other.goto('https://creator.douyin.com/another-task')
        rpc.cmd('list_tabs')
        # This pre-existing other task is part of the baseline, not the popup.
        popups.baseline = {x['tab_id'] for x in rpc.cmd('list_tabs')['tabs']}
    source = other or main
    with chrome.expect_page() as opened:
        source.evaluate("()=>window.open('https://www.douyin.com/video/"+POST+"','_blank',"+json.dumps('noopener' if opener == 'noopener' else '')+")")
    popup = opened.value; popup.wait_for_load_state()
    after = popups.snapshot(); new = [x['tab_id'] for x in after if x['tab_id'] not in popups.baseline and not x['closed']]
    assert len(new) == 1
    if opener == 'same':
        assert popups.page(new[0]).tab_id == new[0]
        popups.close(new[0]); assert popup.is_closed()
    else:
        with pytest.raises(OldRejection, match='opener_unconfirmed'):
            popups.page(new[0])
        assert not popup.is_closed() and rpc.closed == []
        popup.close()
    popups.cleanup(); main.close()
    if other: other.close()


def test_real_chrome_forged_message_event_is_not_trusted(chrome):
    main = chrome.new_page(); main.goto('https://creator.douyin.com/creator-micro/content/manage')
    rpc = ChromeRPC(chrome, main)
    provider = NS(guard=lambda ctx, owner: None,
        reject=lambda code: (_ for _ in ()).throw(OldRejection(code, code)))
    popups = api._Popups(provider, rpc, rpc.cmd, object(), 'main')
    popups.snapshot()
    main.evaluate('(nonce)=>dispatchEvent(new MessageEvent("message",{data:{__locator_provider_nonce:nonce},origin:"https://www.douyin.com",source:window}))', popups.nonce)
    assert main.evaluate('(nonce)=>window.__locatorProviderOpenerV1[nonce].received', popups.nonce) is False
    popups.cleanup(); main.close()
