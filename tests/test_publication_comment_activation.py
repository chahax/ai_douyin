from test_publication_observed_scope import context,page,load,command,adapter
from src.operations_accounts.publication_comment import post_authorized_publication_comment


def prepare(page,kind):
    load(page);frozen=command(page)
    form=page.locator('[data-e2e="comment-input"]').evaluate('n=>n.outerHTML')
    page.locator('[data-e2e="comments"]').evaluate("n=>{n.innerHTML='<div data-e2e=comment-list style=\"width:500px;height:220px\">暂无评论</div>'}")
    page.evaluate("""arg=>{
      window.activationClicks=0;window.otherClicks=0;
      const panel=document.querySelector('[data-e2e="comments"]'),list=panel.querySelector('[data-e2e="comment-list"]');
      const prompt=document.createElement('span');prompt.textContent=arg.kind==='placeholder'?'留下你的精彩评论吧':'抢首评';
      prompt.style.cssText='display:block;width:220px;height:40px;cursor:pointer';panel.appendChild(prompt);
      prompt.onclick=()=>{window.activationClicks++;if(arg.kind==='changed_id'){
        document.querySelector('[data-e2e="player-container"]').className='video_999';return;}
        list.insertAdjacentHTML('beforebegin',arg.form)};
      if(arg.kind==='duplicate'){const other=prompt.cloneNode(true);other.onclick=()=>window.otherClicks++;panel.appendChild(other)}
      if(arg.kind==='placeholder'){const fallback=document.createElement('span');fallback.textContent='抢首评';
        fallback.style.cssText='display:block;width:90px;height:40px;cursor:pointer';fallback.onclick=()=>window.otherClicks++;panel.appendChild(fallback)}
    }""",{'kind':kind,'form':form})
    return frozen


def test_placeholder_activation_mounts_editor_and_sole_submit_replay(page,tmp_path):
    frozen=prepare(page,'placeholder')
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='sent_visible'
    assert result['editor_wait']['activation']['kind']=='placeholder'
    assert page.evaluate('window.activationClicks')==1 and page.evaluate('window.otherClicks')==0
    assert page.evaluate('window.submits')==1 and len(list(tmp_path.glob('*.submitted.json')))==1
    assert post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)==result
    assert page.evaluate('window.activationClicks')==1 and page.evaluate('window.submits')==1


def test_duplicate_first_comment_trigger_never_activates_or_claims(page,tmp_path):
    frozen=prepare(page,'duplicate')
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='comment_editor_unavailable' and result['submitted'] is False
    assert result['editor_wait']['reason']=='activation_not_unique'
    assert page.evaluate('window.activationClicks')==0 and page.evaluate('window.otherClicks')==0
    assert not list(tmp_path.glob('*.submitted.json'))


def test_activation_that_changes_work_id_cannot_submit_or_retry(page,tmp_path):
    frozen=prepare(page,'changed_id')
    result=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert result['status']=='work_scope_unverified' and result['submitted'] is False
    assert result['editor_wait']['reason']=='after_activation_identity_changed'
    assert page.evaluate('window.activationClicks')==1
    assert not list(tmp_path.glob('*.submitted.json'))
