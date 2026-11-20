import json
import pytest
from test_fanqie_account_control import accounts, login, Session
from src.operations_accounts.fanqie_account_control import run_owner
from src.platform_adapter.fanqie_book_inspect import inspect_book, BookInspectionStopped


def test_book_requires_bound_identity_and_exact_title(accounts):
    env=accounts.create('小说','novel')
    with pytest.raises(ValueError): accounts.queue(env['resource_id'],'fanqie_book_inspect',book_name='书')
    with pytest.raises(ValueError): accounts.queue(env['resource_id'],'fanqie_book_inspect',book_name='')


def test_book_identity_mismatch_stops_before_ui(accounts):
    env,cmd,_,_=login(accounts)
    accounts.confirm(cmd['command_id'],'uid:12345','fixture')
    accounts.queue(env['resource_id'],'fanqie_book_inspect',book_name='书')
    result=run_owner(env['resource_id'],accounts,session_factory=lambda c:Session(c,identity='uid:99999'))
    assert result['state']=='failed' and result['result']['reason']=='platform_identity_mismatch'


@pytest.fixture
def local_page(tmp_path):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    session=BrowserSession(BrowserSessionConfig(base_url='about:blank',home_url='about:blank',
        user_data_dir=str(tmp_path/'profile'),storage_state_path=str(tmp_path/'state.json'),headless=True,mute_audio=True,browser_channel='chrome'))
    try: yield session.get_page()
    finally: session.stop()


def install_card(page, title):
    html='<div class="book-hQ7GYr"><b class="book-title-txt-_CIhYa">'+title+'</b><div class="c-promotions"><button onclick="window.promotionClicked=true">别名推广</button></div></div>'
    page.evaluate('() => { document.body.innerHTML='+json.dumps(html)+'; window.promotionClicked=false; }')


@pytest.mark.parametrize('card_title',['别的小说','目标小说续篇',''])
def test_real_page_never_falls_back_to_first_or_substring(local_page,card_title):
    install_card(local_page,card_title)
    with pytest.raises(BookInspectionStopped,match='exact_card_not_unique'):
        inspect_book(local_page,'目标小说',lambda:None,lambda value:None)
    assert not local_page.evaluate('() => window.promotionClicked')


def test_real_page_duplicate_exact_titles_stop(local_page):
    install_card(local_page,'目标小说')
    local_page.evaluate('() => document.body.appendChild(document.querySelector(".book-hQ7GYr").cloneNode(true))')
    with pytest.raises(BookInspectionStopped,match='exact_card_not_unique'):
        inspect_book(local_page,'目标小说',lambda:None,lambda value:None)
    assert not local_page.evaluate('() => window.promotionClicked')


def test_guard_blocks_before_click(local_page):
    install_card(local_page,'目标小说')
    def guard(): raise BookInspectionStopped('owner_lost')
    with pytest.raises(BookInspectionStopped,match='owner_lost'):
        inspect_book(local_page,'目标小说',guard,lambda value:None)
    assert not local_page.evaluate('() => window.promotionClicked')


@pytest.mark.parametrize('condition',['ok','wrong_book','locked','paywall'])
def test_detail_provenance_and_locked_chapter(condition):
    title='目标小说'; book_id='7302660145530539062'
    replies=[{'titles':[title],'text':title}, {'ok':True,'text':title},
      {'ok':True,'text':title+'（'+book_id+'）'}, [{'text':'AIGC','disabled':False}],True,True,
      {'book_id': '1234567890123456789' if condition=='wrong_book' else book_id,'title':title},
      {'ok':False,'reason':'chapter_locked','title':'第一章'} if condition=='locked' else {'ok':True,'title':'第一章'},
      {'book_id':book_id,'item_id':'7302660367757345342','text':('试读结束' if condition=='paywall' else '')+'这是用于测试的正文。'*20}]
    class Page:
        def evaluate(self,js): return replies.pop(0)
        def goto(self,url,**kwargs): assert 'book_id='+book_id in url
        def wait_for_timeout(self,n): pass
    saved=[]
    if condition in ('wrong_book','paywall'):
        with pytest.raises(BookInspectionStopped,match='detail_id_mismatch|chapter_unavailable'):
            inspect_book(Page(),title,lambda:None,lambda value:saved.append(dict(value)))
    else:
        result=inspect_book(Page(),title,lambda:None,lambda value:saved.append(dict(value)))
        assert result['aigc_available'] and not result['promotion_submitted']
        if condition=='locked': assert 'chapter' not in result and len(replies)==1
        else: assert result['chapter']['item_id']=='7302660367757345342'


@pytest.mark.parametrize('stale',[False,True])
def test_multiple_chapters_require_distinct_id_and_content(stale):
    title='目标小说';book='7302660145530539062'
    chapter={'book_id':book,'item_id':'7302660367757345342','text':'第一章正文测试。'*30}
    values=[{'titles':[title]}, {'ok':True}, {'ok':True,'text':title+'（'+book+'）'},
      [{'text':'AIGC','disabled':False}],True,True,{'book_id':book,'title':title},
      {'ok':True,'title':'第一章'},chapter,{'ok':True,'title':'第二章'},
      chapter if stale else {'book_id':book,'item_id':'7302660367757345343','text':'第二章正文测试。'*30},
      {'ok':True,'title':'第三章'}, {'book_id':book,'item_id':'7302660367757345344','text':'第三章正文测试。'*30}]
    class Page:
        count=0
        def evaluate(self,js):
            self.count+=1
            if stale and self.count>=11:return chapter
            return values.pop(0)
        def goto(self,*a,**k):pass
        def wait_for_timeout(self,n):pass
    if stale:
        with pytest.raises(BookInspectionStopped,match='next_chapter_source_unconfirmed'):
            inspect_book(Page(),title,lambda:None,lambda v:None,chapters=3)
    else:
        result=inspect_book(Page(),title,lambda:None,lambda v:None,chapters=3)
        assert [c['title'] for c in result['chapters']]==['第一章','第二章','第三章']
