import json
from types import SimpleNamespace

from test_published_work_discovery import context,page,TITLE,URL,MANAGE
from test_publication_cover_open import markup
from src.shared.published_work_discovery import discover_published_work,_native_modal_id


SELF='https://www.douyin.com/user/self?modal_id=123456&token=TOKEN_SECRET'


def routes(page,caption=TITLE,explicit=True):
    attr=' data-video-id="123456"'if explicit else ''
    work=f'<article{attr}><video></video><figcaption>{caption} 剧情虚构，非真实事件。 原片简介</figcaption></article>'
    if explicit:work+='<div data-video-id="999"><video></video></div>'
    def route(request):
        url=request.request.url
        if url==URL:body=work
        elif url==SELF:body='<title>个人作品</title><main>作品页面</main>'
        elif url==MANAGE:body=''
        else:request.abort();return
        request.fulfill(status=200,content_type='text/html; charset=utf-8',body=body)
    page.context.route('**/*',route)


def test_native_modal_field_requires_actual_canonical_and_same_work_caption(page):
    routes(page)
    before=set(page.context.pages)
    page.set_content(markup(f"window.open('{SELF}','_blank')"))
    result=discover_published_work(page,TITLE)
    resolution=result['diagnostic']['native_popup_resolution']
    assert result['verified'] and result['publish_url']==URL
    assert resolution['candidate_source']=='original_native_self_modal_url'and resolution['identity']['verified']
    assert resolution['identity']['scope_source']=='explicit_id'
    assert resolution['identity']['explicit_id_nodes']==2 and resolution['identity']['matching_id_nodes']==1
    assert resolution['observations'][0]['query_keys']==['modal_id','token']
    assert 'TOKEN_SECRET'not in json.dumps(result,ensure_ascii=False)
    assert set(page.context.pages)==before


def test_wrong_duplicate_unknown_modal_fields_never_supply_a_candidate():
    for url in [SELF.replace('123456','not-a-number'),SELF+'&modal_id=123456',
                SELF+'&modal_id=999',SELF.replace('modal_id=','video_id='),
                SELF.replace('/user/self','/user/other'),SELF+'&video_id=999',
                SELF.replace('www.douyin.com','evil.example')]:
        assert _native_modal_id(url)==''


def test_canonical_route_with_wrong_caption_stays_pending_and_popup_is_cleaned(page):
    routes(page,caption='其他作品',explicit=False)
    before=set(page.context.pages)
    page.set_content(markup(f"window.open('{SELF}','_blank')"))
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='observed_cover_modal_identity_unverified'
    resolution=result['diagnostic']['native_popup_resolution']
    assert resolution['identity']['scope_source']=='semantic_article'and not resolution['identity']['verified']
    assert set(page.context.pages)==before


def test_exact_native_security_marker_stops_service_without_comment(tmp_path,monkeypatch):
    import src.operations_accounts.publication_reconciliation as module
    import src.operations_accounts.publication_autonomous_reconciliation as router
    import src.operations_accounts.publication_comment as comments
    from src.shared.published_work_discovery import _resolve_native_popup
    native=SimpleNamespace(evaluate=lambda _:dict(final_url='https://www.douyin.com/user/self',
        security_verification_markers=['安全验证'],ui_ready=True))
    resolution=_resolve_native_popup(native,TITLE)
    assert resolution['human_required'] and resolution['block_discovery'] and not resolution['verified']
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(router,'get_verified_reconciliation_inputs',lambda _:dict(prepared={'title':TITLE},authorization={}))
    monkeypatch.setattr(comments,'post_authorized_publication_comment',lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('no comment')))
    discovery={'verified':False,'reason':'observed_cover_human_required','diagnostic':{'native_popup_resolution':resolution}}
    fake=SimpleNamespace(wait_for_timeout=lambda _:None,discover_published_work=lambda _:discovery,_cmd=lambda *_a,**_k:None)
    resource=SimpleNamespace(account_uuid='account',account_key='account01',context=SimpleNamespace(),
        reconciliation_session=SimpleNamespace(open_page=lambda _:fake),
        runtime=SimpleNamespace(verify_identity=lambda *_a,**_k:SimpleNamespace(healthy=True)))
    result=module.run_reconciliation(SimpleNamespace(task_id='a'*32,resource=resource,check_dispatch=lambda:None),
        {'account_uuid':'account','account_key':'account01','original_command_id':'b'*32})
    assert result['status']=='human_required'and result['comment']['status']=='not_submitted'
