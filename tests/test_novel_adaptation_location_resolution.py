from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.location_resolution import resolve
from src.content_factory.novel_adaptation import contracts as c
from test_novel_adaptation_scenes import SOURCE


def fixture():
    design={'places':[{'id':'kitchen'}],'props':[{'id':'food','owner':'__OFFSCREEN__'}]}
    handoff={'state':{'props':{'food':'__OFFSCREEN__'}}}
    rows=[{'prop':'food','place':'kitchen','source_ids':['CH1-P001'],
           'prior_location_was_unresolved':True,'reason':'Source establishes location; earlier placeholder was not an observed absence.'}]
    return design,handoff,rows


def review(d,h,p):
    return {'verdict':'accepted','design_sha256':c.digest(d),'handoff_sha256':c.digest(h),
            'source_sha256':c.digest(SOURCE),'proposals_sha256':c.digest(p)}


def test_reviewed_resolution_versions_knowledge_without_rewriting_original():
    d,h,p=fixture();old=deepcopy((d,h,p));out,nh=resolve(d,h,p,SOURCE,review(d,h,p))
    assert (d,h,p)==old and out['props'][0]['owner']=='kitchen'
    assert nh['state']['props']['food']=='kitchen'
    assert nh['opening_resolutions'][0]['prior_state_sha256']==c.digest(h['state'])


@pytest.mark.parametrize('case',['unreviewed','known','explicit_offscreen','source','contained','consumed'])
def test_unknown_resolution_cannot_bypass_state_or_review(case):
    d,h,p=fixture()
    if case=='known':d['props'][0]['owner']=h['state']['props']['food']='kitchen'
    if case=='explicit_offscreen':p[0]['prior_location_was_unresolved']=False
    if case=='source':p[0]['source_ids']=['CH99-P001']
    if case=='contained':h['state']['containers']={'food':'bag'}
    if case=='consumed':h['state']['prop_status']={'food':'consumed'}
    r=review(d,h,p)
    if case=='unreviewed':r['verdict']='needs_revision'
    with pytest.raises(ValueError):resolve(d,h,p,SOURCE,r)
