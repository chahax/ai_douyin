from test_published_work_discovery import context,page,TITLE,URL
from src.shared.published_work_discovery import _MODAL_IDENTITY_JS


def test_h1_and_large_player_common_container_is_diagnosed_without_acceptance(page):
    page.goto(URL)
    caption='<span>'*7+TITLE+' 剧情虚构，非真实事件。 原片简介'+'</span>'*7
    page.set_content('<div class="actual-common-work"><div class="xgplayer"><video></video>'+
        '<i></i>'*260+'</div><div class="caption-region"><h1 class="actual-title">'+caption+
        '</h1></div><span>内容由AI生成</span></div>')
    result=page.evaluate(_MODAL_IDENTITY_JS,{'postId':'123456','title':TITLE})
    assert not result['verified']and result['reason']=='semantic_work_not_unique'
    rendered=result['rendered_layout']
    assert rendered['matching_title_h1s']==1
    h1=next(c for c in rendered['candidates']if c['kind']=='title_h1')
    assert h1['ancestors'][0]['tag']=='H1'
    video=next(c for c in rendered['candidates']if c['kind']=='video')
    assert any(a.get('scope_truncated')and 'xgplayer'in a['class_tokens']for a in video['ancestors'])
    assert any('actual-common-work'in a['class_tokens']for a in video['ancestors'])
    common=rendered['common_scope'][0]
    assert 'actual-common-work'in common['class_tokens']and common['descendant_nodes']>240
    assert common['h1_nodes']==1 and common['visible_video_nodes']==1
    assert common['fixed_visible_marker_counts']['内容由AI生成']==1
    assert common['fixed_visible_marker_counts']['剧情虚构，非真实事件。']==1
    assert len(rendered['common_scope'])<=3
    assert all(len(c['ancestors'])<=8 for c in rendered['candidates'])
    assert all(len(a.get('children',[]))<=12 for c in rendered['candidates']for a in c['ancestors'])
