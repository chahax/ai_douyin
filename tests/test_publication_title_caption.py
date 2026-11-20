import json
from types import SimpleNamespace

import pytest

from test_published_work_discovery import context, page, TITLE, URL
from src.shared.published_work_discovery import discover_published_work


CAPTION='这份申请，我没提 | 离职原因别写反 剧情虚构，非真实事件。 后续简介'


def test_combined_caption_normalizes_typography_but_still_binds_card_and_id(page):
    page.set_content(f'<article><div><span>{CAPTION}</span></div><a href="{URL}">查看作品</a></article>')
    result=discover_published_work(page,TITLE)
    assert result['verified'] and result['publish_url']==URL
    diagnostic=result['diagnostic']
    assert diagnostic['title_candidates']==1
    assert diagnostic['title_candidate_structure'][0]['match']=='complete_title_caption_prefix'
    assert CAPTION not in json.dumps(diagnostic,ensure_ascii=False)


@pytest.mark.parametrize('caption',[
    '前文 '+CAPTION,
    CAPTION.replace('这份申请','另一份申请'),
    CAPTION.replace('别写反 剧情','别写反转 剧情'),
    CAPTION.replace(' 剧情虚构，非真实事件。',' 其他标题后缀 剧情虚构，非真实事件。'),
])
def test_middle_wrong_prefix_and_incomplete_boundary_do_not_match(page,caption):
    page.set_content(f'<article><span>{caption}</span><a href="{URL}">查看作品</a></article>')
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='title_candidate_missing'


def test_equivalent_typography_conflicting_cards_are_not_unique(page):
    page.set_content(f'<article><span>{TITLE}</span><a href="{URL}">查看作品</a></article>'
        f'<article><span>{CAPTION}</span><a href="https://www.douyin.com/video/999">查看作品</a></article>')
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='title_not_unique'
    assert result['diagnostic']['title_candidates']==2


def test_visible_combined_title_without_id_remains_pending_and_never_clicks_edit(page):
    page.set_content(f'<article><span>{CAPTION}</span><button onclick="window.wrongClick=true">编辑作品</button></article>')
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='canonical_id_missing'
    assert result['diagnostic']['canonical_ids']==0 and result['diagnostic']['detail_candidates']==0
    assert page.evaluate('window.wrongClick===undefined')


@pytest.mark.parametrize('loading',[True,False])
def test_loading_and_unknown_layout_are_not_reported_as_not_found(page,tmp_path,monkeypatch,loading):
    page.set_content('<svg width="20" height="20"><path d="M0,0 L10,10"/></svg>'+
        ('<div>加载中，请稍候...</div>' if loading else '<div>内容管理</div>'))
    discovery=discover_published_work(page,TITLE)
    reason='manage_loading' if loading else 'title_candidate_missing'
    assert not discovery['verified'] and discovery['reason']==reason
    assert bool(discovery['diagnostic']['loading_markers'])==loading
    if loading:
        page.locator('div').evaluate("el=>el.innerText='加载中,请稍候…'")
        assert discover_published_work(page,TITLE)['reason']=='manage_loading'
    import src.operations_accounts.publication_reconciliation as module
    import src.operations_accounts.publication_reconciliation_authorization as auth
    import src.operations_accounts.publication_comment as comments
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(auth,'get_verified_reconciliation_inputs',lambda _:dict(
        prepared={'title':TITLE,'hashtags':['劳动法'],'comment':'原批准评论'},authorization={}))
    monkeypatch.setattr(comments,'post_authorized_publication_comment',
        lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('no comment without ID')))
    calls=[]
    def discover(_):calls.append(True);return discovery
    native=SimpleNamespace(wait_for_timeout=lambda _:None,discover_published_work=discover,_cmd=lambda *_a,**_k:None)
    resource=SimpleNamespace(account_uuid='account',account_key='account01',context=SimpleNamespace(),
        reconciliation_session=SimpleNamespace(open_page=lambda _:native),
        runtime=SimpleNamespace(verify_identity=lambda *_a,**_k:SimpleNamespace(healthy=True)))
    result=module.run_reconciliation(SimpleNamespace(task_id='a'*32,resource=resource,check_dispatch=lambda:None),
        {'account_uuid':'account','account_key':'account01','original_command_id':'b'*32})
    assert result['status']=='verification_pending' and result['publish_evidence']['reason']==reason
    assert result['comment']['status']=='not_submitted' and len(calls)==8
