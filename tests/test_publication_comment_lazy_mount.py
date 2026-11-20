from test_publication_observed_scope import context,page,load,command,adapter
from src.operations_accounts.publication_comment import post_authorized_publication_comment


def test_one_native_list_scroll_mounts_editor_then_one_claim_and_submit(page,tmp_path):
    load(page);frozen=command(page)
    original_form=page.locator('[data-e2e="comment-input"]').evaluate('n=>n.outerHTML')
    page.locator('[data-e2e="comments"]').evaluate("n=>{n.style.marginTop='1200px';n.innerHTML='<span style=\"cursor:pointer\">抢首评</span><div data-e2e=\"comment-list\" style=\"width:500px;height:346px\">评论列表</div>'}")
    page.evaluate("""form=>{
      window.scrollCalls=0;window.mounts=0;
      const list=document.querySelector('[data-e2e="comment-list"]'),native=list.scrollIntoView;
      list.scrollIntoView=function(options){window.scrollCalls++;native.call(this,options)};
      new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!window.mounts){
        window.mounts++;list.insertAdjacentHTML('beforebegin',form)}},{threshold:0.2}).observe(list);
    }""",original_form)
    assert page.locator('textarea').count()==0
    first=post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)
    assert first['status']=='sent_visible'and first['editor_wait']['scroll_attempted']is True
    assert first['editor_wait']['reads']<=8
    assert page.evaluate('window.scrollCalls')==1 and page.evaluate('window.mounts')==1
    assert page.evaluate('window.submits')==1 and len(list(tmp_path.glob('*.submitted.json')))==1
    assert post_authorized_publication_comment(adapter(page),frozen,'123456',receipt_dir=tmp_path)==first
    assert page.evaluate('window.scrollCalls')==1 and page.evaluate('window.submits')==1
