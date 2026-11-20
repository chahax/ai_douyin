import json
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from src.platform_adapter.feed_surface_diagnostic import capture_feed_surface, inspect_worker_page
from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlDeferred, BrowserControlRejected


def test_fixed_read_only_capture_is_bounded_and_records_failures(tmp_path):
    actions=[]
    def command(action, **kwargs):
        actions.append(action)
        if action == 'screenshot':
            assert kwargs['selector'].startswith(':nth-match(')
            raise RuntimeError('private token must not be stored')
        assert action == 'inspect_feed_surface'
        return {'evidence': {'frames': [{'index': 0}]}}
    page=NS(_cmd=command,wait_for_timeout=lambda _:None)
    result=capture_feed_surface(page,tmp_path/'evidence')
    assert actions==['inspect_feed_surface']*3+['screenshot']
    evidence=json.loads((tmp_path/'evidence/EVIDENCE.json').read_text())
    assert not evidence['play_requested'] and not evidence['clicked']
    assert 'private token' not in repr(evidence)
    assert result['sample_count']==3


def test_diagnostic_rejects_arbitrary_url_before_browser():
    with pytest.raises(BrowserControlRejected):
        bridge._adapter_read(NS(), {'method':'inspect_recommendation_surface','params':{'url':'https://example.com'}})


@pytest.mark.parametrize('method,params,allowed', [
    ('inspect_recommendation_surface',{},True),
    ('inspect_recommendation_surface',{'url':'https://example.com'},False),
    ('sync_videos',{},False),('inspect_upload_surface',{},False)])
def test_only_empty_fixed_feed_inspection_can_read_paused_account(monkeypatch,method,params,allowed):
    from src.operations_accounts.runtime import AccountRuntimeContext
    binding=NS(account_uuid='test:one',account_key='one',platform_identity_key='public:123',
        browser_environment_key='env:one',browser_profile_dir='profile/one',storage_state_path='state/one',
        confirmed_by='user',created_at='2026',status='active')
    current=AccountRuntimeContext(binding=binding,profile=NS(profile_version=1,account_uuid='test:one',account_key='one',status='active'),
        browser_environment_key='env:one',browser_profile_dir='profile/one',storage_state_path='state/one')
    runtime=NS(profiles=NS(get=lambda _:current.profile),bindings=NS(get=lambda _:binding,get_runtime_state=lambda _:NS(lock_owner='')))
    resource=NS(context=current,account_key='one',runtime=runtime,manual_tasks={},console_tasks={})
    ctx=NS(resource=resource,account_id='test:one',binding_version=bridge.binding_version(current),
        command={'kind':'read','payload':{'method':method,'params':params,'operation_profile':None}})
    monkeypatch.setattr(bridge,'_legacy_manual_gate',lambda _:None)
    monkeypatch.setattr(bridge,'_controls',lambda _: {'state':'paused'})
    if allowed:
        bridge._admission(ctx,'dispatch')
    else:
        with pytest.raises(BrowserControlDeferred): bridge._admission(ctx,'dispatch')


def test_real_hidden_chrome_reads_frame_without_interacting(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--mute-audio'])
        try:
            page=browser.new_page(viewport={'width':1280,'height':720})
            page.route('**/captcha/test',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body='<meta charset="utf-8"><p>请完成安全验证</p><button id="test">确认</button>'))
            page.set_content('<iframe src="https://example.test/captcha/test" style="width:380px;height:384px"></iframe>')
            page.locator('iframe').wait_for()
            frame=page.frames[-1]
            frame.locator('#test').wait_for()
            evidence=inspect_worker_page(page)
            assert evidence['challenge']['blocking']
            assert '安全验证' in evidence['frames'][0]['content']['text']
            assert evidence['frames'][0]['content']['controls'][0]['tag']=='BUTTON'
            page.locator(':nth-match(:is(iframe[src*="captcha"]), 1)').screenshot(path=str(tmp_path/'frame.png'))
            assert (tmp_path/'frame.png').stat().st_size>0
        finally:
            browser.close()
