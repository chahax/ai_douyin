import pytest
from test_publication_comment_settlement import context,page,adapter,prepare,unchanged
from src.operations_accounts.publication_comment_settlement import verify_only,_READ_COMMENTS_JS
import json


def add_span(page,text,kind):
    page.evaluate("""arg=>{
      const list=document.querySelector('[data-e2e="comment-list"]');
      function makeItem(){const item=document.createElement('div');item.dataset.e2e='comment-item';
        const leaf=document.createElement('span');leaf.textContent=arg.text;let outer=leaf;
        for(let i=0;i<4;i++){const parent=document.createElement('span');parent.appendChild(outer);outer=parent}
        if(arg.kind==='quote'){const q=document.createElement('blockquote');q.appendChild(outer);outer=q}
        if(arg.kind==='reply'){const reply=document.createElement('div');reply.dataset.e2e='comment-reply';reply.appendChild(outer);outer=reply}
        item.appendChild(outer);return item;}
      const item=makeItem();
      if(arg.kind==='wrong_card')item.dataset.e2e='unrelated-card';
      if(arg.kind==='outside')document.body.appendChild(item);
      else if(arg.kind==='draft'){item.contentEditable='true';list.appendChild(item)}
      else list.appendChild(item);
      if(arg.kind==='duplicate'){list.appendChild(makeItem())}
    }""",{'text':text,'kind':kind})


def read(page,text):return page.evaluate('()=>('+_READ_COMMENTS_JS+')('+json.dumps({'id':'123456','text':text},ensure_ascii=False)+')')


def test_observed_nested_span_comment_settles_without_touching_original_claim(page,tmp_path,monkeypatch):
    frozen,original=prepare(page,tmp_path,monkeypatch);add_span(page,frozen['comment'],'normal')
    result=verify_only(adapter(page),frozen,'123456',evidence_dir=tmp_path/'observed-audit')
    assert result['status']=='matching_comment_already_visible'and result['exact_visible']is True
    assert result['native_read']['match']['source']=='observed_nested_span/20261019'
    assert result['native_read']['match']['span_ancestor_count']==4
    assert result['new_submission']is False and page.evaluate('!window.submits')
    unchanged(frozen,original)


@pytest.mark.parametrize('kind',['wrong_card','outside','draft','quote','reply'])
def test_nested_span_requires_actual_comment_card_not_outside_draft_or_quote(page,tmp_path,monkeypatch,kind):
    frozen,original=prepare(page,tmp_path,monkeypatch);add_span(page,frozen['comment'],kind)
    native=read(page,frozen['comment'])
    assert native['exact_visible']is False and native['known_exact_matches']==0
    assert page.evaluate('!window.submits');unchanged(frozen,original)


def test_duplicate_observed_span_comments_remain_ambiguous(page,tmp_path,monkeypatch):
    frozen,original=prepare(page,tmp_path,monkeypatch);add_span(page,frozen['comment'],'duplicate')
    result=verify_only(adapter(page),frozen,'123456',evidence_dir=tmp_path/'duplicate-audit')
    assert result['status']=='unconfirmed'and result['exact_visible']is False
    assert result['native_read']['reason']=='exact_comment_ambiguous'and result['native_read']['known_exact_matches']==2
    assert result['new_submission']is False and page.evaluate('!window.submits');unchanged(frozen,original)
