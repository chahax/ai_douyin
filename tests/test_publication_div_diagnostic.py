import json

from test_published_work_discovery import context,page,TITLE
from src.shared.published_work_discovery import discover_published_work


def test_div_card_exposes_image_and_operation_structure_without_src_or_click(page):
    page.set_content(f'''<div class="work-card_ab12" data-e2e="work-row">
        <div class="cover_xyz" style="cursor:pointer;width:100px;height:60px" onclick="window.clicked=true">
          <img alt="作品封面" src="https://creator.douyin.com/image?token=IMAGE_SECRET" width="80" height="50">
        </div><div class="details"><div>{TITLE} 剧情虚构，非真实事件。 原片简介</div>
          <div class="operation-bar"><div class="edit-control" style="cursor:pointer">编辑作品</div>
          <span class="permission-control" aria-label="设置权限">设置权限</span></div></div></div>''')
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='independent_card_unbound'
    structure=result['diagnostic']['bound_title_structure']
    assert structure['schema']=='bound_title_structure/v2'
    rows=[n for a in structure['ancestors']for n in a.get('local_nodes',[])]
    assert any(n['tag']=='IMG' and n['alt']=='作品封面' and n['rect']['width']==80 for n in rows)
    assert any('cover_xyz'in n['class_tokens'] and n['cursor']=='pointer' and n['image_children']==1 for n in rows)
    assert any(n['own_text']=='编辑作品' and n['cursor']=='pointer' for n in rows)
    assert any(n['aria_label']=='设置权限' and n['own_text']=='设置权限' for n in rows)
    assert any(a.get('data_e2e')=='work-row' for a in structure['ancestors'])
    html=''.join(a.get('projected_outer_html','')for a in structure['ancestors'])
    assert '<img alt="作品封面"'in html and '编辑作品'in html
    serialized=json.dumps(structure,ensure_ascii=False)
    assert 'IMAGE_SECRET'not in serialized and 'src='not in serialized and 'window.clicked'not in serialized
    assert all(len(a.get('local_nodes',[]))<=64 for a in structure['ancestors'])
    assert page.evaluate('window.clicked===undefined')
