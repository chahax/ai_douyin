from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.uncertainty_review import inventory,identity,evaluate
from src.content_factory.novel_adaptation.contracts import digest


def fixture():
    a={'candidate':{'action':'孩子仍在房间'},'presence':{'uncertainties':['孩子是否离场']},
       'projection':{'uncertainties':['碗是否消失']}}
    r={'artifact_hashes':identity(a),'dispositions':[{'id':x['id'],'decision':'retained_limit',
       'reason':'当前证据仅限定本次状态，不能证明整个故事。',
       'evidence':[{'artifact':'candidate','path':'/action','value_sha256':digest(a['candidate']['action'])}]}
       for x in inventory(a)]}
    return a,r


def test_bound_dispositions_keep_notes_and_do_not_become_acceptance():
    a,r=fixture();old=deepcopy(a);result=evaluate(a,r)
    assert a==old and result['counts']['retained_limit']==2
    assert not result['semantic_acceptance']


@pytest.mark.parametrize('case',['stale','missing','duplicate','no_evidence','changed_evidence','bad_path'])
def test_stale_incomplete_or_unverifiable_dispositions_are_rejected(case):
    a,r=fixture()
    if case=='stale':a['candidate']['action']='孩子离场'
    elif case=='missing':r['dispositions'].pop()
    elif case=='duplicate':r['dispositions'][1]=r['dispositions'][0]
    elif case=='no_evidence':r['dispositions'][0]['evidence']=[]
    elif case=='changed_evidence':r['dispositions'][0]['evidence'][0]['value_sha256']='wrong'
    else:r['dispositions'][0]['evidence'][0]['path']='/missing'
    with pytest.raises((ValueError,KeyError)):evaluate(a,r)
