from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import revision_handoff as h,prose_patch,contracts as c

def setup():
    original={'title':'test','screenplay':'前段\n错误\n后段','continuity':'旧年龄与楼下'}
    source={'text':'原文'};registry={'age':11}
    plan=prose_patch.prepare(original['screenplay'],[{'quote':'错误','reason':'test'}])
    candidate=h.revise(original,plan,{'edit_0':'正确'},source,registry)
    handoff=h.attach(candidate,'修后状态',source,registry)
    review={'reviewer':'primary_assistant','verdict':'approved','open_issues':[],
      'candidate_sha256':c.digest(candidate),'handoff_sha256':c.digest(handoff)}
    return original,candidate,handoff,source,registry,review

def test_revision_invalidates_old_continuity_preserves_original():
    old,new,hand,s,r,v=setup()
    assert new['continuity'] is None and new['continuity_status']=='invalidated'
    assert old['continuity']=='旧年龄与楼下'
    assert new['screenplay']=='前段\n正确\n后段'
    assert h.release(new,hand,s,r,v)['status']=='released'

@pytest.mark.parametrize('change',['prose','summary','registry','source','review','open_issue'])
def test_stale_or_unreviewed_handoff_never_released(change):
    old,new,hand,s,r,v=setup()
    if change=='prose':new['screenplay']+='新剧情'
    elif change=='summary':hand['summary']='旧摘要'
    elif change=='registry':r['age']=16
    elif change=='source':s['text']='changed'
    elif change=='review':v={}
    else:v['open_issues']=['时间错']
    with pytest.raises(ValueError):h.release(new,hand,s,r,v)

def test_rebuild_rejects_new_registry_without_regeneration():
    old,new,hand,s,r,v=setup();r['age']=16
    with pytest.raises(ValueError):h.attach(new,'summary',s,r)
