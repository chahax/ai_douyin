import json

from test_publication_observed_scope import context,page,load,command,adapter
from src.operations_accounts.publication_comment import post_authorized_publication_comment


def test_self_comment_input_and_unopened_panel_are_diagnosed_without_fill_or_click(page,tmp_path):
    load(page);frozen=command(page)
    page.locator('[data-e2e="comment-input"]').evaluate("n=>{n.innerHTML='';n.setAttribute('contenteditable','true');n.setAttribute('aria-label','留下想法');n.style.cssText='width:220px;height:40px';n.textContent='DRAFT_SECRET'}")
    page.evaluate("""()=>{const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
        dialog.innerHTML='<textarea placeholder="其他窗口" style="width:220px;height:40px"></textarea>';
        document.body.appendChild(dialog);dialog.querySelector('textarea').value='INPUT_SECRET';
        const trigger=document.createElement('button');trigger.textContent='评论';trigger.setAttribute('data-e2e','comment-trigger');
        trigger.setAttribute('aria-label','展开评论');trigger.onclick=()=>window.wrong=true;document.body.appendChild(trigger);
        const nav=document.createElement('button');nav.textContent='登录';document.body.appendChild(nav);
        const hint=document.createElement('span');hint.textContent='登录后评论';document.querySelector('[data-e2e=comments]').appendChild(hint)}""")
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='comment_editor_unavailable'and result['submitted']is False
    diagnostic=result['scope_diagnostic']
    assert diagnostic['page_visible_editors']==2 and diagnostic['detail_visible_editors']==1
    assert diagnostic['outside_dialog_visible_editors']==1
    assert diagnostic['page_visible_login_marker_counts']['登录']==1 and diagnostic['detail_visible_login_marker_counts']['登录']==0
    assert diagnostic['detail_visible_login_marker_counts']['登录后评论']==1
    assert any(n['kind']=='editor'and n['data_e2e']=='comment-input'and n['contenteditable']=='true'and n['in_detail']for n in diagnostic['candidates'])
    assert any(n['data_e2e']=='comment-trigger'and n['fixed_control_text']=='评论'for n in diagnostic['candidates'])
    assert 'DRAFT_SECRET'not in json.dumps(diagnostic)and 'INPUT_SECRET'not in json.dumps(diagnostic)
    assert len(diagnostic['candidates'])<=12
    assert all(len(n['ancestors'])<=3 for n in diagnostic['candidates'])
    assert all(len(a.get('children',[]))<=8 for n in diagnostic['candidates']for a in n['ancestors'])
    receipt=json.loads(next(tmp_path.glob('*.receipt.json')).read_text(encoding='utf-8'))
    assert receipt['scope_diagnostic']==diagnostic and not list(tmp_path.glob('*.submitted.json'))
    assert page.evaluate('window.wrong===undefined')
