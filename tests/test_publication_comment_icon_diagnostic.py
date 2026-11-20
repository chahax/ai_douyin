import json
import pytest
from test_publication_observed_scope import context,page,adapter
from test_publication_comment_draft_editor import prepare
from src.operations_accounts.publication_comment import post_authorized_publication_comment


def test_unlabelled_submit_icon_is_diagnosed_without_claim_or_click(page,tmp_path):
    frozen=prepare(page,'normal')
    page.locator('[data-e2e="comments"]').evaluate("""panel=>{
      const send=Array.from(panel.children).find(n=>n.textContent==='发送');send.textContent='';
      send.innerHTML='<svg data-icon="native-arrow-fixture" viewBox="0 0 24 24" width="24" height="24"><title>原生发送图标</title><path d="M12 20V4M5 11L12 4L19 11"></path><use href="#native-arrow"></use><use href="https://example.invalid/token?access_token=SECRET"></use></svg>';
      const input=panel.querySelector('[contenteditable]');input.setAttribute('data-private','DO_NOT_DUMP');
      panel.querySelector('[data-e2e="comment-list"]').insertAdjacentHTML('beforeend','<button aria-label="不该采集"><svg data-icon="outside-list"><path d="M0 0L1 1"></path></svg></button>');
    }""")
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='comment_submit_unavailable'and result['submitted']is False
    icons=result['submit_diagnostic']['icons'];assert icons['schema']=='scoped_draft_submit_icon_diagnostic/v1'
    assert len(icons['candidates'])==1
    actual=icons['candidates'][0]
    assert actual['data_icon']=='native-arrow-fixture'and actual['svg']['view_box']=='0 0 24 24'
    assert actual['svg']['paths'][0]['d']=='M12 20V4M5 11L12 4L19 11'
    assert actual['svg']['uses']==[{'fragment':'#native-arrow','non_fragment_omitted':False},{'fragment':None,'non_fragment_omitted':True}]
    assert len(actual['ancestors'])<=2 and actual['ancestors'][0]['cursor_pointer']is True
    assert page.evaluate('window.submits')==0 and not list(tmp_path.glob('*.submitted.json'))
    persisted=json.loads(next(tmp_path.glob('*.receipt.json')).read_text(encoding='utf-8'))
    assert persisted['submit_diagnostic']==result['submit_diagnostic']and persisted['ui_evidence_path']
    dumped=json.dumps(icons,ensure_ascii=False)
    assert all(secret not in dumped for secret in ['SECRET','DO_NOT_DUMP','outside-list',frozen['comment'],'https://'])


@pytest.mark.parametrize('inside',[True,False])
def test_explicit_native_comment_submit_icon_requires_same_panel(page,tmp_path,inside):
    frozen=prepare(page,'normal')
    page.locator('[data-e2e="comments"]').evaluate("""(panel,inside)=>{
      const send=Array.from(panel.children).find(n=>n.textContent==='发送');send.setAttribute('data-e2e','comment-submit');
      send.innerHTML='<svg viewBox="0 0 24 24" width="24" height="24"><path d="M12 20V4M5 11L12 4L19 11"></path></svg>';
      if(!inside)document.body.appendChild(send);
    }""",inside)
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']==('sent_visible'if inside else'comment_submit_unavailable')
    assert page.evaluate('window.submits')==(1 if inside else 0)
    assert len(list(tmp_path.glob('*.submitted.json')))==(1 if inside else 0)
    if inside:
        assert post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)==result
        assert page.evaluate('window.submits')==1
    else:assert result['submitted']is False
