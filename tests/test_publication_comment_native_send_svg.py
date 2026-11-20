import pytest
from test_publication_observed_scope import context,page,adapter
from test_publication_comment_draft_editor import prepare
from src.operations_accounts.publication_comment import post_authorized_publication_comment

SEND_PATHS=['M17.5 30C23.851 30 29 24.851 29 18.5S23.851 7 17.5 7 6 12.149 6 18.5 11.149 30 17.5 30zm-5.16-13.883a1.16 1.16 0 0 0 1.64 1.64l2.395-2.394v8.838a1.16 1.16 0 0 0 2.321 0v-8.839l1.028 1.028 1.368 1.368a1.16 1.16 0 1 0 1.64-1.641l-4.219-4.22a1.382 1.382 0 0 0-1.954 0l-4.22 4.22h.001z', 'M12.34 16.117a1.16 1.16 0 0 0 1.64 1.64l2.395-2.394v8.838a1.16 1.16 0 0 0 2.321 0v-8.839l1.028 1.028 1.368 1.368a1.16 1.16 0 1 0 1.64-1.641l-4.219-4.22a1.382 1.382 0 0 0-1.954 0l-4.22 4.22h.001z']


def native_icons(page,kind):
    frozen=prepare(page,'normal')
    page.locator('[data-e2e="comments"]').evaluate("""(panel,arg)=>{
      const old=Array.from(panel.children).find(n=>n.textContent==='发送');old.remove();
      const group=document.createElement('div');group.style.cssText='display:flex;width:108px;height:36px';
      const paths=arg.paths.slice();if(arg.kind==='wrong_signature')paths[1]+='z';
      for(let index=0;index<3;index++){
        const control=document.createElement('span');control.style.cssText='display:block;width:36px;height:36px;cursor:pointer';
        control.innerHTML='<svg viewBox="0 0 36 36" width="36" height="36">'+(index===2?paths:['M0 0L5 5']).map(d=>'<path d="'+d+'"></path>').join('')+'</svg>';
        control.onclick=()=>{if(index!==2){window.outsideClicks++;return;}window.submits++;const item=document.createElement('div');item.dataset.e2e='comment-item';const content=document.createElement('span');content.dataset.e2e='comment-content';content.textContent=panel.querySelector('[contenteditable]').innerText;item.appendChild(content);panel.querySelector('[data-e2e="comment-list"]').appendChild(item)};
        group.appendChild(control);
      }
      if(arg.kind==='disabled')group.lastElementChild.setAttribute('aria-disabled','true');
      if(arg.kind==='external')document.body.appendChild(group);
      else panel.insertBefore(group,panel.querySelector('[data-e2e="comment-list"]'));
      if(arg.kind==='duplicate'){const clone=group.cloneNode(true);clone.onclick=()=>window.outsideClicks++;panel.insertBefore(clone,group)}
    }""",{'kind':kind,'paths':SEND_PATHS})
    return frozen


def test_actual_ordered_send_svg_three_icon_group_commits_once_and_replays(page,tmp_path):
    frozen=native_icons(page,'normal')
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='sent_visible'and result['submitted']is True
    assert result['submit_control']=={'source':'observed_native_send_svg','signature':'observed_comment_send_svg/20261019/gen28'}
    assert page.evaluate('window.submits')==1 and page.evaluate('window.outsideClicks')==0
    assert len(list(tmp_path.glob('*.submitted.json')))==1
    assert post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)==result
    assert page.evaluate('window.submits')==1


@pytest.mark.parametrize('kind',['wrong_signature','disabled','external'])
def test_wrong_disabled_or_external_native_signature_never_submits(page,tmp_path,kind):
    frozen=native_icons(page,kind)
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='comment_submit_unavailable'and result['submitted']is False
    assert page.evaluate('window.submits')==0 and page.evaluate('window.outsideClicks')==0
    assert not list(tmp_path.glob('*.submitted.json'))


def test_duplicate_native_signature_is_not_selected(page,tmp_path):
    frozen=native_icons(page,'duplicate')
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='comment_submit_unavailable'and result['submitted']is False
    assert result['submit_diagnostic']['reason']=='native_send_signature_not_unique'
    assert page.evaluate('window.submits')==0 and page.evaluate('window.outsideClicks')==0
    assert not list(tmp_path.glob('*.submitted.json'))
