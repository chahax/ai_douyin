"""Readonly lookup owner contracts and isolated ordinary UI query freshness."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from src.platform_adapter import fanqie_promotion_lookup_v1 as m
from src.platform_adapter.fanqie_lookup_controls_v1 import DISCOVER_JS,discover

BOOK='7302660145530539062';NAME='本地精确书';ALIAS='本地已授权别名'
SUBJECT=dict(resource_id='resource',binding_version='version',platform_identity_key='identity',environment_key='env',
    owner_id='owner',generation=1,task_id='fixture')
URL='https://kol.fanqieopen.com/page/promotion-list?tab_type=2'


def put(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True),encoding='utf-8')
    return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def request(tmp_path,page,**changed):
    controls=discover(page)
    source=put(tmp_path/'CONTROLS.json',dict(schema='fanqie_promotion_lookup_step/v1',stage='controls_ready',
        subject=SUBJECT,observation=controls))
    value=dict(schema='fanqie_promotion_lookup_request/v1',purpose='read_only_exact_book_alias_query',
        **{k:SUBJECT[k]for k in m.SCOPE},book_id=BOOK,book_name=NAME,alias=ALIAS,source_controls=source,
        target_input=controls['text_inputs'][0],trigger='Enter')
    value.update(changed);return put(tmp_path/'REQUEST.json',value)


def test_real_owner_discovery_only_has_no_query_or_observer_and_scope_is_bound(tmp_path):
    from test_fanqie_managed_promotion_v1 import accounts,Session
    from src.operations_accounts.fanqie_account_control import run_owner
    a,env=accounts.__wrapped__(tmp_path)
    class LookupSession(Session):
        def evaluate(self,js):
            if js==DISCOVER_JS:return dict(schema='fanqie_lookup_controls/v1',accepted=True,
                text_inputs=[dict(tag='input',type='text',disabled=False,read_only=False)],comboboxes=[dict(visible_text='BookID')])
            if js==m.TABLE_JS:return dict(ready=False,headers=[],rows=[])
            if js not in (DISCOVER_JS,m.TABLE_JS):
                # Owner identity probes use the session command protocol, not DOM.
                raise AssertionError('No other DOM action in discovery-only')
    command=a.queue(env['resource_id'],'fanqie_promotion_lookup',book_id=BOOK,book_name=NAME,lookup_alias=ALIAS)
    result=run_owner(env['resource_id'],a,session_factory=LookupSession)
    assert result['state']=='succeeded' and not result['result']['searched']
    assert result['result']['lookup_status']=='controls_discovered'
    folder=a.folder(command['command_id']);proof=json.loads((folder/'LOOKUP_CONTROLS_READY.json').read_bytes())
    assert proof['subject']['task_id']==command['command_id']and proof['subject']['resource_id']==env['resource_id']
    saved=json.loads(Path(result['result']['promotion_lookup']['path']).read_bytes())
    assert not saved['query_value_read']and not saved['promotion_submitted']and not saved['native_identity_verified']
    assert not list(folder.glob('*OBSERVER*'))and not(folder/'SUBMIT_CLAIM.json').exists()


def test_readonly_lookup_queue_cannot_mix_write_and_CLI_flags_are_explicit(tmp_path,monkeypatch,capsys):
    from test_fanqie_managed_promotion_v1 import accounts
    a,env=accounts.__wrapped__(tmp_path)
    for extra in [dict(promotion_request={}),dict(observer_request={}),dict(chapters=1),dict(locate=True),dict(snapshot_version='v2')]:
        with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_promotion_lookup',book_id=BOOK,book_name=NAME,lookup_alias=ALIAS,**extra)
    with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_promotion_apply',lookup_alias=ALIAS)
    from scripts import run_fanqie_account as cli
    calls=[]
    class Accounts:
        def queue(self,*a,**kw):calls.append((a,kw));return {}
    monkeypatch.setattr(cli,'FanqieAccounts',lambda **kw:Accounts());monkeypatch.setattr(cli,'launch_worker',lambda *a:{})
    monkeypatch.setattr(sys,'argv',['prog','promotion-lookup','--resource','r','--book-id',BOOK,'--book-name',NAME,'--lookup-alias',ALIAS])
    cli.main();assert calls==[(('r','fanqie_promotion_lookup'),dict(book_name=NAME,chapters=0,book_id=BOOK,lookup_alias=ALIAS))]
    monkeypatch.setattr(sys,'argv',['prog','promotion-apply','--resource','r','--lookup-alias',ALIAS])
    with pytest.raises(SystemExit):cli.main()


def test_lookup_prePopen_readonly_kind_never_expands_write_allowlist():
    from src.operations_accounts.fanqie_readonly_startup_recovery_v1 import READONLY_KINDS
    assert 'fanqie_promotion_lookup'in READONLY_KINDS
    assert not {'fanqie_promotion_apply','fanqie_backfill','fanqie_backfill_reconcile','fanqie_login'}&READONLY_KINDS


def html(mode):
    row=f'<tr><td>其他别名</td><td><span class="book-name-iHil3A">其他书</span> ID：8302660145530539062</td><td>AIGC</td><td>强制失效</td><td>可用</td><td>待填写</td></tr>'
    target=f'<tr><td>{ALIAS}</td><td><span class="book-name-iHil3A">{NAME}</span> ID：{BOOK}</td><td>AIGC</td><td>审核中</td><td>可用</td><td>待填写</td></tr>'
    outcome=('<tr><td colspan="6"><div class="arco-empty">暂无数据</div></td></tr>'if mode=='empty'else
        ''if mode=='empty_without_indicator'else row.replace('强制失效','审核中')if mode=='wrong_scope'else target)
    return f'''<meta charset="utf-8"><button role="tab" aria-selected="true">别名管理</button><div role="combobox" id="mode">BookID</div>
     <input id="query" type="text" placeholder="本地测试BookID"><input type="hidden" value="PRIVATE-HIDDEN">
     <div class="arco-table"><table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th><th>书籍状态</th><th>发文详情</th></tr></thead><tbody>{row}</tbody></table><div id="loading" style="display:none" aria-busy="false">正在查询</div></div>
     <table style="display:none"><thead><tr><th>HIDDEN</th></tr></thead><tbody>{target}</tbody></table>
     <script>window.queryCount=window.clicked=0;document.addEventListener('click',()=>clicked++);
      if({json.dumps(mode)}==='initial_loading'){{
       const loading=document.querySelector('#loading');loading.style.display='block';loading.setAttribute('aria-busy','true');
       setTimeout(()=>{{loading.style.display='none';loading.setAttribute('aria-busy','false');}},600);
      }}
      document.querySelector('#query').addEventListener('keydown',e=>{{if(e.key!=='Enter')return;queryCount++;
       if({json.dumps(mode)}==='unchanged')return;
       if({json.dumps(mode)}==='transient_restore'){{const table=document.querySelector('table');table.style.display='none';setTimeout(()=>table.style.display='table',450);return;}}
       const loading=document.querySelector('#loading');loading.style.display='block';loading.setAttribute('aria-busy','true');
       document.querySelector('#query').disabled=true;
       setTimeout(()=>{{document.querySelector('tbody').innerHTML={json.dumps(outcome,ensure_ascii=False)};
        loading.style.display='none';loading.setAttribute('aria-busy','false');document.querySelector('#query').disabled=false;}},450);
      }});</script>'''


@pytest.fixture(scope='module')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright()as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking',
            '--disable-component-update','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:yield browser
        finally:browser.close()


@pytest.fixture
def page(browser):
    context=browser.new_context();page=context.new_page()
    context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html('target')))
    try:yield page
    finally:context.close()


local=pytest.mark.skipif(os.environ.get('RUN_LOCAL_FANQIE_LOOKUP_TEST')!='1',reason='Fresh isolated local DOM opt-in')


@local
@pytest.mark.parametrize('mode,status',[('target','target_observed'),('initial_loading','target_observed'),('empty','not_observed_in_current_query'),
    ('unchanged','query_result_freshness_unconfirmed'),('transient_restore','query_result_freshness_unconfirmed'),
    ('wrong_scope','query_scope_unconfirmed'),('empty_without_indicator','query_empty_state_unconfirmed')])
def test_same_page_one_UI_query_waits_for_new_result_and_never_uses_old_rows(page,tmp_path,mode,status):
    page.goto(URL);page.set_content(html(mode));binding=request(tmp_path,page);steps=[]
    result=m.inspect_lookup(page,book_id=BOOK,book_name=NAME,alias=ALIAS,subject=SUBJECT,guard=lambda:None,
        checkpoint=lambda stage,value:steps.append((stage,value)),lookup_request=binding)
    assert result['status']==status and result['searched']and result['search_count']==1 and result['query_value_read']
    assert page.evaluate('({queryCount,clicked})')==dict(queryCount=1,clicked=0)
    assert result['platform_business_outcome']=='unknown'and not result['native_identity_verified']and not result['publishable']
    if mode in ('unchanged','transient_restore'):
        assert not result['query_result_freshness_confirmed']and not result.get('matches')and result['freshness_basis']is None
    elif mode in ('target','initial_loading'):
        assert result['matches'][0]['alias_status']=='审核中'and result['freshness_basis']=='observed_loading_then_ready'
    else:assert result['matches']==[]and result['query_result_freshness_confirmed']
    if mode=='empty':
        table_after=dict(steps)['table_after']
        assert table_after['empty_placeholders']==[dict(text='暂无数据',colspan=6)]and table_after['rows']==[]
    if mode=='initial_loading':
        evidence=dict(steps)
        assert evidence['table_before']['loading']is True and evidence['table_before']['ready']is False
        assert evidence['table_before_search']['loading']is False and evidence['table_before_search']['ready']is True
    assert 'PRIVATE-HIDDEN'not in json.dumps(steps,ensure_ascii=False)


@local
def test_wrong_BookID_mode_or_changed_SHA_stops_before_fill_or_enter(page,tmp_path):
    page.goto(URL);binding=request(tmp_path,page)
    wrong=request(tmp_path,page,platform_identity_key='another-account')
    with pytest.raises(ValueError,match='scope_changed'):
        m.inspect_lookup(page,book_id=BOOK,book_name=NAME,alias=ALIAS,subject=SUBJECT,guard=lambda:None,
            checkpoint=lambda *a:None,lookup_request=wrong)
    assert page.evaluate('queryCount')==0
    binding=request(tmp_path,page)
    page.evaluate("document.querySelector('#mode').textContent='书名'")
    result=m.inspect_lookup(page,book_id=BOOK,book_name=NAME,alias=ALIAS,subject=SUBJECT,guard=lambda:None,
        checkpoint=lambda *a:None,lookup_request=binding)
    assert result['status']=='query_controls_or_table_unconfirmed'and page.evaluate('queryCount')==0
    assert page.evaluate("document.querySelector('#query').value")==''
    Path(binding['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='evidence_changed'):
        m.inspect_lookup(page,book_id=BOOK,book_name=NAME,alias=ALIAS,subject=SUBJECT,guard=lambda:None,
            checkpoint=lambda *a:None,lookup_request=binding)
    assert page.evaluate('queryCount')==0
