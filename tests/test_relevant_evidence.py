import pytest
from copy import deepcopy
from src.content_factory.novel_adaptation import context_projection as p,handoff as h,contracts as c

def fixture():
    source={'chapters':[{'index':1,'text':'如果米提前吃空，会挨打。\n肉像冻了半年。\n十一岁。'}]}
    keys=list(c.catalog(source));prior={'source_sha256':c.digest(source),'evidence':{keys[2]:c.catalog(source)[keys[2]]}}
    packet=p.relevant_packet(source,['当前冲突'],keys[:2],{'当前冲突':[keys[0]]},target_id='next')
    candidate={'screenplay':'当场片段'}
    delta=h.stage_reference_delta(prior,source,packet,candidate,{'used_source_ids':[keys[0],keys[1]]},keys[:2])
    review={'verdict':'accepted','reviewer':'primary_assistant','delta_sha256':c.digest(delta),'open_issues':[]}
    return source,keys,prior,packet,candidate,delta,review

def test_projection_preserves_conditions_and_omits_irrelevant_age():
    s,k,old,pkt,cand,d,rv=fixture()
    assert pkt['evidence'][k[0]]['text']=='如果米提前吃空，会挨打。'
    assert k[2] not in pkt['evidence']
    result=h.commit_reference_delta(old,s,pkt,cand,d,rv)
    assert result['evidence'][k[1]]['text']=='肉像冻了半年。'
    assert result['evidence'][k[2]]==old['evidence'][k[2]]
    assert list(old['evidence'])==[k[2]]

def test_future_or_arbitrary_facts_cannot_enter_projection():
    s,k,*_=fixture()
    for selected in [{'n':[k[2]]},{'n':[k[0]],'summary':'米必然吃空'}]:
        with pytest.raises(c.ContractError):p.relevant_packet(s,['n'],k[:2],selected,target_id='x')

@pytest.mark.parametrize('mutate',['source','packet','candidate','previous','unreviewed','rewrite'])
def test_changed_or_unreviewed_delta_blocked(mutate):
    s,k,old,pkt,cand,d,rv=fixture()
    if mutate=='source':s['chapters'][0]['text']+='改变'
    elif mutate=='packet':pkt['target_id']='other'
    elif mutate=='candidate':cand['screenplay']='另一个片段'
    elif mutate=='previous':old['evidence']={}
    elif mutate=='unreviewed':rv={}
    else:
        d['additions'][k[1]]['text']='肉确实冻了半年'
        rv['delta_sha256']=c.digest(d)
    with pytest.raises(ValueError):h.commit_reference_delta(old,s,pkt,cand,d,rv)

def test_empty_selection_does_not_delete_previous_state():
    s,k,old,pkt,cand,d,rv=fixture()
    empty=p.relevant_packet(s,['n'],k[:2],{'n':[]},target_id='x')
    delta=h.stage_reference_delta(old,s,empty,cand,{'used_source_ids':[]},k[:2])
    rv['delta_sha256']=c.digest(delta)
    result=h.commit_reference_delta(old,s,empty,cand,delta,rv)
    assert result['evidence']==old['evidence']
