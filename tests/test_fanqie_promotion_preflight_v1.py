"""Opt-in read preflight protocols; optional local DOM uses a fresh fake site."""
import json
import os
import re
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

from src.platform_adapter import fanqie_promotion_preflight_v1 as m

BOOK='7302660145530539062'
NAME='你敢惹我？我有六个反派儿子'


class Page:
    url=m.CONTENT_URL
    def __init__(self,*,titles=None,modal_count=0,wrong=False,disabled=False):
        self.view=dict(book_titles=[NAME] if titles is None else titles,
            search_controls=[dict(type='text',placeholder='搜索书名',aria_label='',disabled=False)],
            filter_buttons=['全部内容'],visible_modal_count=modal_count)
        self.calls=[];self.opened=0;self.closed=0;self.wrong=wrong;self.disabled=disabled
    def wait_for_timeout(self,ms):assert ms<=300
    def evaluate(self,js):
        self.calls.append(js)
        if js==m.VIEW_JS:return self.view
        if js==m.OPTIONS_JS:return [dict(text='AIGC',disabled=self.disabled)]
        if js==m.CLOSE_JS:self.closed+=1;return {'closed':True}
        if js==m.MODAL_STATE_JS:return {'visible_modal_count':0}
        if 'const wanted=' in js and 'observed_book_ids' in js:
            return dict(ready=False,reason='modal_book_identity_mismatch')if self.wrong else dict(ready=True,book_identity_verified=True,observed_book_ids=[BOOK])
        assert 'cards.length!==1' in js
        self.opened+=1;return dict(opened=True,entry_label='别名推广')


def inspect(page,guard=lambda:None):
    evidence=[]
    result=m.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=guard,
        checkpoint=lambda stage,value:evidence.append((stage,value)))
    return result,evidence


def test_missing_ambiguous_or_existing_modal_only_reports_current_view():
    for page,status in [(Page(titles=['Other book']),'book_not_in_current_view'),
                        (Page(titles=[NAME,NAME]),'book_ambiguous_in_current_view'),
                        (Page(modal_count=1),'existing_modal_requires_review')]:
        result,evidence=inspect(page)
        assert result['status']==status and result['platform_book_availability'] is None
        assert not result['preflight_passed'] and not page.opened and not page.closed
        assert evidence[0][0]=='view_initial' and result['search_executed'] is False


def test_wrong_book_or_disabled_type_never_fills_submits_or_reads_chapter():
    for page,status in [(Page(wrong=True),'modal_book_identity_mismatch'),(Page(disabled=True),'aigc_unavailable'),(Page(),'form_options_verified')]:
        result,_=inspect(page)
        assert result['status']==status and result['modal_close_confirmed']
        assert page.opened==page.closed==1
        assert result['preflight_passed']==(status=='form_options_verified')
        assert not result['alias_filled'] and not result['promotion_submitted'] and result['chapters_read']==0
        # Pure-read inventory may declare a local `value`; reject actual input
        # property assignment/setters rather than that unrelated identifier.
        assert all('set.call' not in js and '.fill(' not in js
                   and not re.search(r'\.value\s*=(?!=)',js) for js in page.calls)


def test_guard_or_wrong_origin_stops_before_DOM():
    page=Page()
    def fenced():raise ValueError('owner changed')
    with pytest.raises(ValueError):inspect(page,fenced)
    assert page.calls==[]
    page.url='https://evil.invalid/page/content?tab_type=2'
    with pytest.raises(ValueError,match='original_novel'):inspect(page)
    assert page.calls==[]


def test_real_owner_queue_preflight_cannot_mix_write_or_chapter_payload(tmp_path,monkeypatch):
    from test_fanqie_managed_promotion_v1 import accounts,Session
    from src.operations_accounts.fanqie_account_control import run_owner
    a,env=accounts.__wrapped__(tmp_path);old=a.latest_command(env['resource_id'])
    invalid=[dict(promotion_request={}),dict(binding_uuid='x',manifest_sha256='x'),
             dict(observer_request={}),dict(snapshot_version='v2'),dict(chapters=1)]
    for extra in invalid:
        with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_promotion_preflight',book_id=BOOK,book_name=NAME,**extra)
    for kind in ['fanqie_promotion_apply','fanqie_backfill_reconcile']:
        with pytest.raises(ValueError):a.queue(env['resource_id'],kind,book_id=BOOK,book_name=NAME)
    assert a.latest_command(env['resource_id'])==old
    class PreflightSession(Session):
        def __init__(self,config):super().__init__(config);self.fixture=Page()
        def evaluate(self,js):return self.fixture.evaluate(js)
    command=a.queue(env['resource_id'],'fanqie_promotion_preflight',book_id=BOOK,book_name=NAME)
    assert command['payload']==dict(environment_key=env['environment_key'],book_id=BOOK,book_name=NAME)
    outcome=run_owner(env['resource_id'],a,session_factory=PreflightSession)
    assert outcome['state']=='succeeded' and outcome['result']['preflight_passed']
    saved=json.loads(Path(outcome['result']['promotion_preflight']['path']).read_bytes())
    assert saved['managed_subject']['task_id']==command['command_id']
    assert saved['managed_subject']['owner_id']==outcome['owner_id']
    assert saved['managed_subject']['generation']==outcome['generation']
    assert saved['chapters_read']==0 and not saved['promotion_submitted']
    assert PreflightSession.instances[-1].config.user_data_dir==env['profile_dir']


def test_CLI_new_flags_are_optin_and_old_book_default_unchanged(monkeypatch,capsys):
    from scripts import run_fanqie_account as cli
    calls=[]
    class Accounts:
        def queue(self,*args,**kwargs):calls.append((args,kwargs));return {'command_id':'fixture'}
    monkeypatch.setattr(cli,'FanqieAccounts',lambda *args,**kwargs:Accounts())
    monkeypatch.setattr(cli,'launch_worker',lambda *args,**kwargs:{'launched':False})
    monkeypatch.setattr(sys,'argv',['prog','promotion-preflight','--resource','r','--book-id',BOOK,'--book-name',NAME])
    cli.main();assert calls[-1]==(('r','fanqie_promotion_preflight'),dict(book_name=NAME,chapters=0,book_id=BOOK))
    monkeypatch.setattr(sys,'argv',['prog','book','--resource','r','--book-name',NAME])
    cli.main();assert calls[-1]==(('r','fanqie_book_inspect'),dict(book_name=NAME,chapters=0))
    monkeypatch.setattr(sys,'argv',['prog','promotion-apply','--resource','r','--book-id',BOOK])
    with pytest.raises(SystemExit):cli.main()
    assert len(calls)==2


def test_new_read_startup_failure_is_known_only_before_worker_not_for_writes(tmp_path):
    from src.operations_accounts import fanqie_readonly_startup_recovery_v1 as r
    from src.platform_adapter.browser_session import BrowserWorkerStartupError
    error=BrowserWorkerStartupError('spawning_worker');error.__cause__=FileNotFoundError('synthetic')
    error.startup_evidence=dict(stage='spawning_worker',cleanup_verified=True,ready_received=False)
    session=NS(_proc=None,_worker_stage='spawning_worker',_startup_cleanup_verified=True,active=False)
    folder=tmp_path/'empty';folder.mkdir();accounts=NS(folder=lambda cid:folder)
    def call(kind):
        sessions=[]
        def handler(ctx,payload):sessions.append(session);raise error
        ctx=NS(task_id='preflight',binding_version='v',actor=NS(owner_id='owner',generation=1),command=dict(kind=kind,account_id='resource'))
        return r.readonly_startup_handler(handler,accounts=accounts,sessions=sessions)(ctx,{})
    result=call('fanqie_promotion_preflight')
    assert result.state=='failed' and result.result['platform_requests_started'] is False
    for kind in ['fanqie_promotion_apply','fanqie_backfill','fanqie_backfill_reconcile','fanqie_login']:
        with pytest.raises(BrowserWorkerStartupError):call(kind)


@pytest.mark.skipif(os.environ.get('RUN_LOCAL_PREFLIGHT_DOM_TEST')!='1',reason='Fresh isolated local DOM opt-in')
def test_real_local_DOM_exact_modal_controls_privacy_and_zero_submit():
    from playwright.sync_api import sync_playwright
    def html(*,wrong=False,duplicate=False,extra=False,prefix=False):
        actual='8302660145530539062'if wrong else BOOK
        card=f'<div class="book-hQ7GYr"><span class="book-title-txt-_CIhYa">{NAME}</span><button onclick="window.opened++;document.querySelector(\'#modal\').style.display=\'block\'">别名推广</button></div>'
        return f'''<meta charset="utf-8"><script>window.opened=window.submitted=window.written=0</script>
          <input type="hidden" value="PRIVATE-HIDDEN"><input type="password" value="PRIVATE-PASSWORD">
          <input type="text" placeholder="手机号登录" value="PRIVATE-ACCOUNT"><input type="text" placeholder="搜索书名或作者" value="">
          <div class="task-menu-second"><span class="task-menu-second-item">全部内容</span></div>{card*(2 if duplicate else 1)}
          <div id="modal" class="arco-modal" style="display:none"><button class="arco-modal-close-icon" onclick="document.querySelector('#modal').style.display='none';document.querySelector('#options').style.display='none'">关闭</button>
          <div class="arco-modal-content"><div>书籍信息</div><div>{'标题前缀'if prefix else ''}{NAME}（{actual}）</div>
          {'<div>另一书籍（9302660145530539062）</div>'if extra else ''}
          <input class="alias-input-EBp1Sw" oninput="window.written++">
          <div class="arco-form-item"><label class="arco-form-item-label">发文类型</label><div class="arco-select" onclick="document.querySelector('#options').style.display='block'">请选择</div></div>
          <button onclick="window.submitted++">提交</button></div></div>
          <div id="options" style="display:none"><div role="option">AIGC</div><div role="option" aria-disabled="true">真人出镜</div></div>'''
    with sync_playwright()as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking','--disable-component-update','--no-first-run','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:
            for wrong,duplicate,extra,prefix,expected in [(False,False,False,False,'form_options_verified'),
                    (True,False,False,False,'modal_book_identity_mismatch'),
                    (False,True,False,False,'book_ambiguous_in_current_view'),
                    (False,False,True,False,'modal_book_identity_mismatch'),
                    (False,False,False,True,'modal_book_identity_mismatch')]:
                context=browser.new_context();page=context.new_page()
                context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html(wrong=wrong,duplicate=duplicate,extra=extra,prefix=prefix)))
                page.goto(m.CONTENT_URL)
                result,steps=inspect(page)
                assert result['status']==expected and result['chapters_read']==0 and not result['promotion_submitted']
                assert page.evaluate('({written:window.written,submitted:window.submitted})')=={'written':0,'submitted':0}
                raw=json.dumps(steps,ensure_ascii=False)
                assert all(secret not in raw for secret in ['PRIVATE-HIDDEN','PRIVATE-PASSWORD','PRIVATE-ACCOUNT','手机号登录'])
                assert result['view_initial']['search_controls']==[dict(type='text',placeholder='搜索书名或作者',aria_label='',disabled=False)]
                assert page.evaluate("document.querySelector('#modal').style.display")=='none'
                context.close()
        finally:browser.close()
