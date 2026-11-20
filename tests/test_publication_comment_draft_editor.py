import pytest
from test_publication_observed_scope import context,page,load,command,adapter
from src.operations_accounts.publication_comment import post_authorized_publication_comment


def prepare(page,kind):
    load(page);frozen=command(page)
    page.locator('[data-e2e="comments"]').evaluate("""(panel,kind)=>{
      window.submits=0;window.inputs=0;window.outsideClicks=0;
      panel.innerHTML='<div class="DraftEditor-root"><div class="public-DraftEditorPlaceholder-root">留下你的精彩评论吧</div><div class="DraftEditor-editorContainer"><div class="notranslate public-DraftEditor-content" role="combobox" contenteditable="true" style="width:500px;min-height:30px"><div><br></div></div></div></div><div data-e2e="comment-list" style="width:500px;height:180px">暂无评论</div>';
      const editor=panel.querySelector('[contenteditable]');
      editor.addEventListener('input',()=>{window.inputs++;if(kind==='wrong_id')document.querySelector('[data-e2e="player-container"]').className='video_999'});
      const send=document.createElement(kind==='normal_span'?'span':'div');send.textContent='发送';send.style.cssText='display:block;width:70px;height:30px;cursor:pointer';
      send.onclick=()=>{window.submits++;const item=document.createElement('div');item.dataset.e2e='comment-item';const content=document.createElement('span');content.dataset.e2e='comment-content';content.textContent=editor.innerText;item.appendChild(content);panel.querySelector('[data-e2e="comment-list"]').appendChild(item)};
      if(kind==='external'){document.body.appendChild(send);send.onclick=()=>window.outsideClicks++}
      else panel.insertBefore(send,panel.querySelector('[data-e2e="comment-list"]'));
      if(kind==='multiple'){const other=send.cloneNode(true);other.onclick=()=>window.outsideClicks++;panel.insertBefore(other,send)}
      if(kind==='duplicate'){const other=editor.cloneNode(true);panel.querySelector('.DraftEditor-editorContainer').appendChild(other)}
    }""",kind)
    return frozen


@pytest.mark.parametrize('tag',['div','span'])
def test_exact_draft_panel_types_and_sole_commit_is_idempotent(page,tmp_path,tag):
    frozen=prepare(page,'normal_span'if tag=='span'else'normal')
    first=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert first['status']=='sent_visible' and first['submitted']is True
    assert page.evaluate('window.inputs')>=1 and page.evaluate('window.submits')==1
    assert len(list(tmp_path.glob('*.submitted.json')))==1
    assert post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)==first
    assert page.evaluate('window.submits')==1


@pytest.mark.parametrize('kind',['duplicate','wrong_id'])
def test_duplicate_draft_or_changed_work_never_claims_or_submits(page,tmp_path,kind):
    frozen=prepare(page,kind)
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']==('comment_editor_unavailable'if kind=='duplicate'else'work_scope_unverified')
    assert result['submitted']is False and page.evaluate('window.submits')==0
    assert not list(tmp_path.glob('*.submitted.json'))


@pytest.mark.parametrize('kind',['external','multiple'])
def test_external_or_multiple_draft_send_targets_are_not_clicked(page,tmp_path,kind):
    frozen=prepare(page,kind)
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='comment_submit_unavailable' and result['submitted']is False
    assert result['submit_diagnostic']['reason']=='submit_not_unique_or_usable'
    assert result['ui_evidence_path'] and page.evaluate('window.submits')==0 and page.evaluate('window.outsideClicks')==0
    assert not list(tmp_path.glob('*.submitted.json'))
