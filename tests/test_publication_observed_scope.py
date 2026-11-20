from types import SimpleNamespace

import pytest

from test_published_work_discovery import context,page,TITLE,URL,MANAGE
from test_publication_cover_open import markup
from src.shared.published_work_discovery import discover_published_work
from src.shared.published_work_scope import read_observed_work_scope
from src.platform_adapter.publish_verification import inspect_published_video
from src.operations_accounts.publication_comment import post_authorized_publication_comment

TAGS=['劳动法','劳动权益','离职避坑','普法知识','AI剧情']
SELF='https://www.douyin.com/user/self?modal_id=123456'


def work_html():
    return f'''<meta charset="utf-8"><div data-e2e="video-detail"><div class="unhashed-common">
      <div data-e2e="player-container" class="video_123456"><video></video></div>
      <div><div data-e2e="detail-video-info"><h1>{TITLE} 剧情虚构，非真实事件。 #劳动法 #劳动权益 #离职避坑 #普法知识 #AI剧情</h1>
      <span id="ai">内容由AI生成</span></div></div></div>
      <div data-e2e="comments"><div data-e2e="comment-input"><textarea style="width:220px;height:40px"></textarea>
      <button style="width:64px;height:30px" onclick="window.submits=(window.submits||0)+1;const n=document.createElement('div');n.setAttribute('data-e2e','comment-item');const s=document.createElement('span');s.setAttribute('data-e2e','comment-content');s.textContent=this.parentElement.querySelector('textarea').value;n.appendChild(s);this.parentElement.parentElement.appendChild(n)">发送</button></div></div></div>
      <script>(()=>{{const v=document.querySelector('video');Object.defineProperty(v,'readyState',{{value:2}});Object.defineProperty(v,'duration',{{value:60}});}})();</script>'''


def load(page,html=None):
    page.goto(URL);page.set_content(html or work_html())


def evidence(page):return inspect_published_video(page,'123456',required_hashtags=TAGS,expected_title=TITLE)


def adapter(page):
    return SimpleNamespace(runtime_context=SimpleNamespace(account_key='account01',account_uuid='fixture:one'),
        _require_runtime_identity=lambda **_:None,session=SimpleNamespace(open_page=lambda _:page))


def command(page):return dict(account_key='account01',account_uuid='fixture:one',authorization={'original':'PREPARED'},
    comment='原批准的法律说明',title=TITLE,hashtags=TAGS,publish_evidence=evidence(page))


def test_actual_semantic_scope_chains_native_discovery_inspection_and_comment_once(page,tmp_path):
    def route(r):
        if r.request.url==URL:body=work_html()
        elif r.request.url==SELF:body='<title>个人作品</title><main>作品页面</main>'
        elif r.request.url==MANAGE:body=''
        else:r.abort();return
        r.fulfill(status=200,content_type='text/html; charset=utf-8',body=body)
    page.context.route('**/*',route)
    page.set_content(markup(f"window.open('{SELF}','_blank')"))
    found=discover_published_work(page,TITLE)
    assert found['verified']and found['diagnostic']['native_popup_resolution']['identity']['scope_source']=='observed_video_detail'
    page.goto(URL)
    checked=evidence(page)
    assert checked['verified']and checked['hashtags_verified']and checked['expected_title']==TITLE
    assert checked['ai_label_origin'].startswith('unknown')
    frozen=command(page);calls=[]
    fresh=page.context.new_page();fresh.goto(URL)
    real=adapter(fresh);real.session.open_page=lambda _:(calls.append(True)or fresh)
    first=post_authorized_publication_comment(real,frozen,'123456',receipt_dir=tmp_path)
    second=post_authorized_publication_comment(real,frozen,'123456',receipt_dir=tmp_path)
    assert first==second and first['status']=='sent_visible'and len(calls)==1
    assert fresh.evaluate('window.submits')==1
    fresh.close()


@pytest.mark.parametrize('kind',['wrong_id','duplicate_scope','duplicate_title','wrong_title','outside_ai','challenge'])
def test_wrong_or_ambiguous_scope_and_outside_declarations_never_verify(page,kind):
    html=work_html()
    if kind=='wrong_id':html=html.replace('class="video_123456"','class="video_999"')
    elif kind=='duplicate_scope':html+=work_html()
    elif kind=='duplicate_title':html=html.replace('</h1>','</h1><h1>另一个标题</h1>')
    elif kind=='wrong_title':html=html.replace(TITLE,'前文 '+TITLE)
    elif kind=='outside_ai':html=html.replace('<span id="ai">内容由AI生成</span>','')+'<span>内容由AI生成</span>'
    else:html+='<div>安全验证</div>'
    load(page,html)
    result=evidence(page)
    assert not result['verified']
    if kind=='outside_ai':assert result['ai_label_visible']is False
    if kind=='challenge':assert result['human_required']is True


def test_two_editors_and_outside_submit_remain_known_not_submitted(page,tmp_path):
    load(page);frozen=command(page)
    page.locator('[data-e2e="comment-input"]').evaluate("el=>{const n=document.createElement('textarea');n.style.cssText='width:220px;height:40px';el.appendChild(n)}")
    first=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert first['status']=='comment_editor_unavailable'and first['submitted']is False
    page.locator('textarea').nth(1).evaluate('n=>n.remove()')
    page.locator('[data-e2e="comment-input"] button').evaluate('n=>n.remove()')
    page.evaluate("()=>{const n=document.createElement('button');n.style.cssText='width:60px;height:30px';n.textContent='发送';n.onclick=()=>window.wrong=true;document.body.appendChild(n)}")
    second=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert second['status']=='comment_submit_unavailable'and second['submitted']is False
    assert not list(tmp_path.glob('*.submitted.json'))and page.evaluate('window.wrong===undefined')


def test_async_id_change_after_fill_is_rejected_before_claim(page,tmp_path):
    load(page);frozen=command(page)
    page.locator('textarea').evaluate("n=>n.oninput=()=>document.querySelector('[data-e2e=player-container]').className='video_999'")
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='work_scope_unverified'and result['submitted']is False
    assert not list(tmp_path.glob('*.submitted.json'))and page.evaluate('window.submits===undefined')


def test_new_scope_cannot_borrow_legacy_article_without_frozen_title(page,tmp_path):
    load(page);frozen=command(page);frozen.pop('title')
    page.evaluate("()=>{document.body.appendChild(document.createElement('article'))}")
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='work_scope_unverified'and result['submitted']is False
    assert not list(tmp_path.glob('*.submitted.json'))


def test_initial_empty_dom_waits_for_observed_work_before_comment(page,tmp_path):
    load(page);frozen=command(page)
    page.set_content('<main>加载中</main>')
    page.evaluate("html=>setTimeout(()=>{document.body.innerHTML=html;const v=document.querySelector('video');Object.defineProperty(v,'readyState',{value:2});Object.defineProperty(v,'duration',{value:60})},150)",work_html())
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='sent_visible'and page.evaluate('window.submits')==1
