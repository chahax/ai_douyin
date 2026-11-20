import json

from test_published_work_discovery import context,page,TITLE,URL
from src.shared.published_work_discovery import _MODAL_IDENTITY_JS


def test_unknown_div_public_work_is_diagnosed_without_title_only_success(page):
    page.goto(URL)
    page.set_content(f'''<div class="actual-work-region" data-e2e="rendered-work">
        <div class="actual-player"><video></video></div>
        <div class="actual-caption">{TITLE} 剧情虚构，非真实事件。 原片简介</div>
        <input value="INPUT_SECRET"><a href="https://www.douyin.com/video/123456?token=QUERY_SECRET">外链</a>
        </div><iframe src="about:blank" width="20" height="20"></iframe><div>请先登录</div>''')
    evidence=page.evaluate(_MODAL_IDENTITY_JS,{'postId':'123456','title':TITLE})
    assert not evidence['verified']and evidence['reason']=='semantic_work_not_unique'
    layout=evidence['rendered_layout']
    assert layout['total_videos']==1 and layout['visible_videos']==1 and layout['title_leaf_matches']==1
    assert layout['iframe_nodes']==1 and layout['native_ui_markers']==['请先登录']
    assert any('actual-work-region'in ancestor['class_tokens']and ancestor['contains_title']and ancestor['video_nodes']==1
        for candidate in layout['candidates']for ancestor in candidate['ancestors'])
    assert len(layout['candidates'])<=12
    assert all(len(c['ancestors'])<=8 for c in layout['candidates'])
    assert all(len(a.get('children',[]))<=12 for c in layout['candidates']for a in c['ancestors'])
    assert 'INPUT_SECRET'not in json.dumps(layout)and 'QUERY_SECRET'not in json.dumps(layout)
