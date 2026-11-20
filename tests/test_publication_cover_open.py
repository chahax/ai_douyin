from test_published_work_discovery import context,page,TITLE,URL
from src.shared.published_work_discovery import discover_published_work


def markup(action='',extra_cover='',title=TITLE,cover_text=''):
    return f'''<div class="video-card-sfaSzz video-card-new-e033na video-card-v2-AelUxA">
      <div class="video-card-content-Xt386b">
        <div class="video-card-cover-QkeRHf" style="cursor:pointer;width:120px;height:160px" onclick="{action}">
          <div class="video-card-top-eL6bwF"></div><div class="video-card-bottom-cq09K3"></div>{cover_text}</div>
        {extra_cover}<div><div>{title} 剧情虚构，非真实事件。 简介</div>
        <div>已发布</div><span>编辑作品</span><span>设置权限</span><span>作品置顶</span><span>删除作品</span></div>
      </div></div>'''


def test_observed_native_cover_opens_exact_canonical_without_editing(page):
    before=set(page.context.pages)
    page.set_content(markup(f"window.open('{URL}','_blank')"))
    result=discover_published_work(page,TITLE)
    assert result['verified'] and result['publish_url']==URL
    assert result['reason']=='observed_title_card_cover_canonical_id'
    assert result['diagnostic']['observed_cover']['click_dispatched']
    assert result['diagnostic']['observed_cover']['new_page_closed']
    assert set(page.context.pages)==before


def test_other_card_multiple_covers_and_edit_disguise_do_not_click(page):
    attempts=[
        '<div>'+TITLE+'</div>'+markup('window.wrong=true',title='其他作品'),
        markup('window.wrong=true',extra_cover='<div class="video-card-cover-duplicate" style="cursor:pointer;width:120px;height:160px"></div>'),
        markup('window.wrong=true',cover_text='<span>编辑作品</span>'),
    ]
    for html in attempts:
        page.set_content(html)
        assert not discover_published_work(page,TITLE)['verified']
        assert page.evaluate('window.wrong===undefined')


def test_noncanonical_cover_result_records_dialog_and_is_never_clicked_twice(page):
    page.set_content(markup("window.clicks=(window.clicks||0)+1;document.getElementById('detail').hidden=false")+
        '<div id="detail" role="dialog" aria-label="作品查看" hidden style="position:absolute;left:300px;top:0"><h2>作品查看</h2><button>关闭</button></div>')
    first=discover_published_work(page,TITLE)
    assert not first['verified'] and first['reason']=='observed_cover_exact_url_not_unique'
    diagnostic=first['diagnostic']['cover_open_pages'][0]
    assert diagnostic['visible_dialogs'][0]['headings']==['作品查看']
    assert diagnostic['native_controls'][0]['text']=='关闭'
    second=discover_published_work(page,TITLE)
    assert not second['verified'] and second['reason']=='detail_click_already_dispatched'
    assert page.evaluate('window.clicks')==1
