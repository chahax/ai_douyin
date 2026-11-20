import json

from test_published_work_discovery import context,page,TITLE,URL
from src.shared.published_work_discovery import discover_published_work


def test_unknown_title_action_is_diagnosed_without_click_or_input_query_secrets(page):
    page.set_content(f'''<article><span>{TITLE}</span>
        <input value="INPUT_SECRET"><button aria-label="编辑作品" title="编辑作品" onclick="window.wrong=true">编辑作品</button>
        <a href="https://creator.douyin.com/creator-micro/content/detail?token=QUERY_SECRET#HASH_SECRET" title="只读入口">未知入口</a>
        <button title="token=ATTRIBUTE_SECRET">更多</button></article>''')
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='canonical_id_missing'
    structure=result['diagnostic']['bound_title_structure']
    controls=[c for a in structure['ancestors']for c in a.get('controls',[])]
    assert any(c['aria_label']=='编辑作品' and c['onclick_attribute'] for c in controls)
    assert any(c['href']=='https://creator.douyin.com/creator-micro/content/detail' and c['href_query_removed'] for c in controls)
    data=json.dumps(structure,ensure_ascii=False)
    for forbidden in ['INPUT_SECRET','QUERY_SECRET','HASH_SECRET','ATTRIBUTE_SECRET','window.wrong','<input']:
        assert forbidden not in data
    assert len(structure['ancestors'])<=6
    assert all(len(a.get('projected_outer_html',''))<=1400 and len(a.get('controls',[]))<=8 for a in structure['ancestors'])
    assert page.evaluate('window.wrong===undefined')


def test_other_work_boundary_does_not_dump_unrelated_caption_or_change_id_rejection(page):
    other='OTHER_WORK_PRIVATE_CAPTION'
    page.set_content(f'<div><span>{TITLE}</span><article><span>{other}</span><a href="{URL}">查看作品</a></article></div>')
    result=discover_published_work(page,TITLE)
    assert not result['verified'] and result['reason']=='independent_card_unbound'
    structure=result['diagnostic']['bound_title_structure']
    assert any(a.get('foreign_work_boundary') for a in structure['ancestors'])
    assert other not in json.dumps(structure,ensure_ascii=False)
