import hashlib
import json
from pathlib import Path
import pytest
from test_publication_observed_scope import context,page,load,command,adapter
import src.operations_accounts.publication_comment_settlement as settlement


def prepare(page,tmp_path,monkeypatch):
    load(page);frozen=command(page);monkeypatch.setattr(settlement,'ROOT',tmp_path)
    identity={'account_uuid':frozen['account_uuid'],'post_id':'123456','comment_sha256':hashlib.sha256(frozen['comment'].encode()).hexdigest()}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    old=tmp_path/'data/publish_comments';old.mkdir(parents=True)
    claim=old/f'{key}.submitted.json';receipt=old/f'{key}.receipt.json'
    claim.write_text(json.dumps({'identity':identity,'status':'submission_started'}),encoding='utf-8')
    receipt.write_text(json.dumps({'schema':'authorized_publication_comment/v1','identity':identity,'post_url':'https://www.douyin.com/video/123456',
        'comment':frozen['comment'],'status':'outcome_unknown','submitted':None,'submission_lock_retained':True}),encoding='utf-8')
    ref=lambda p:{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    frozen.update(original_comment_command_id='a'*32,source_claim=ref(claim),source_unknown_receipt=ref(receipt))
    page.locator('[data-e2e="comments"]').evaluate("""panel=>{
      const list=document.createElement('div');list.dataset.e2e='comment-list';list.style.cssText='width:500px;min-height:200px';panel.appendChild(list);
      window.readonlyScrolls=0;const native=list.scrollIntoView;list.scrollIntoView=function(o){window.readonlyScrolls++;native.call(this,o)};
    }""")
    return frozen,(claim.read_bytes(),receipt.read_bytes())


def unchanged(frozen,original):
    assert Path(frozen['source_claim']['path']).read_bytes()==original[0]
    assert Path(frozen['source_unknown_receipt']['path']).read_bytes()==original[1]


def test_delayed_known_exact_comment_is_read_only_settled_without_resend(page,tmp_path,monkeypatch):
    frozen,original=prepare(page,tmp_path,monkeypatch)
    page.evaluate("""text=>setTimeout(()=>{const item=document.createElement('div');item.dataset.e2e='comment-item';item.dataset.commentId='987654';
      const span=document.createElement('span');span.dataset.e2e='comment-content';span.textContent=text;item.appendChild(span);document.querySelector('[data-e2e="comment-list"]').appendChild(item)},300)""",frozen['comment'])
    result=settlement.verify_only(adapter(page),frozen,'123456',evidence_dir=tmp_path/'audit')
    assert result['status']=='matching_comment_already_visible'and result['exact_visible']is True
    assert result['new_submission']is False and result['ownership_verified']is False
    assert result['publish_evidence']['post_verified']and result['publish_evidence']['player_verified']
    assert 'ai_active_source_verified'not in result['publish_evidence']
    assert len(result['observations'])>=2 and len(result['observations'])<=8
    assert page.evaluate('window.readonlyScrolls')==1 and page.evaluate('!window.submits')
    ref=result['readonly_evidence_ref'];native=json.loads(Path(ref['path']).read_text(encoding='utf-8'))
    assert hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()==ref['sha256']
    assert native=={key:value for key,value in result.items()if key!='readonly_evidence_ref'}
    unchanged(frozen,original)


@pytest.mark.parametrize('kind',['draft_only','unknown_layout'])
def test_draft_or_unknown_selector_exact_text_remains_unconfirmed_with_diagnostic(page,tmp_path,monkeypatch,kind):
    frozen,original=prepare(page,tmp_path,monkeypatch)
    page.locator('textarea').evaluate('(n,text)=>n.value=text',frozen['comment'])
    page.evaluate("""arg=>{
      const panel=document.querySelector('[data-e2e="comments"]');
      panel.insertAdjacentHTML('beforeend','<span>评论字数超过限制</span><div role="alert">发布失败</div>');
      if(arg.kind==='unknown_layout'){const item=document.createElement('div');item.dataset.e2e='comment-level-1';
        const span=document.createElement('span');span.dataset.e2e='native-unknown-text';span.textContent=arg.text;item.appendChild(span);panel.querySelector('[data-e2e="comment-list"]').appendChild(item)}
      const outside=document.createElement('div');outside.dataset.e2e='comment-item';const content=document.createElement('span');content.dataset.e2e='comment-content';content.textContent=arg.text;outside.appendChild(content);document.body.appendChild(outside);
    }""",{'kind':kind,'text':frozen['comment']})
    result=settlement.verify_only(adapter(page),frozen,'123456',evidence_dir=tmp_path/'audit')
    assert result['status']=='unconfirmed'and result['exact_visible']is False and result['new_submission']is False
    diag=result['native_read']['diagnostic']
    assert diag['approved_text_leaf_count']==(1 if kind=='unknown_layout'else 0)
    assert {item['text']for item in diag['visible_errors']}=={'评论字数超过限制','发布失败'}
    if kind=='unknown_layout':
        assert diag['approved_text_candidates'][0]['data_e2e']=='native-unknown-text'
        assert diag['approved_text_candidates'][0]['ancestors'][0]['data_e2e']=='comment-level-1'
    assert page.evaluate('!window.submits')and page.evaluate('window.readonlyScrolls')==1
    unchanged(frozen,original)


def test_wrong_native_work_id_stops_without_any_comment_mutation(page,tmp_path,monkeypatch):
    frozen,original=prepare(page,tmp_path,monkeypatch)
    page.locator('[data-e2e="player-container"]').evaluate("n=>n.className='video_999'")
    result=settlement.verify_only(adapter(page),frozen,'123456',evidence_dir=tmp_path/'audit')
    assert result['status']=='unconfirmed'and result['reason']=='work_identity_changed'
    assert page.evaluate('!window.submits')and page.evaluate('window.readonlyScrolls')==0
    unchanged(frozen,original)
