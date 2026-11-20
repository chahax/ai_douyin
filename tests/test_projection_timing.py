from copy import deepcopy
import pytest
from test_narrative_props import fixture
from src.content_factory.novel_adaptation.contracts import digest
from src.content_factory.novel_adaptation.projection_timing import retime


def setup():
    c,p,plan,e=fixture();c['scenes'][0]['segments'][0]['audio']=[{'kind':'inner','speaker':'a','text':'先想一想'}]
    p['candidate_sha256']=e['candidate_sha256']=digest(c)
    d={'artifact_hashes':{'candidate':digest(c),'presence':digest(p),'projection':digest(e)},
       'segment_id':'B','evidence':{'path':'/scenes/0/segments/0/action','quote':'甲从盆中取出白菜。'},
       'changes':[{'kind':'event','index':0,'before':{'phase':'start','after_audio_index':None},
                   'after':{'phase':'after_audio','after_audio_index':0}}]}
    return c,p,e,d


def test_only_explicit_timing_changes_no_event_or_prose_rewrite():
    c,p,e,d=setup();original=deepcopy((c,p,e))
    np,ne,r=retime(c,p,e,d)
    assert (c,p,e)==original and np==p
    expected=deepcopy(e);expected['segments'][0]['events'][0]['event'].update(phase='after_audio',after_audio_index=0)
    assert ne==expected and r['prose_unchanged'] and not r['semantic_acceptance']


@pytest.mark.parametrize('case',['stale','quote','anchor','extra','duplicate','before'])
def test_bad_or_stale_timing_directive_cannot_change_state(case):
    c,p,e,d=setup()
    if case=='stale':d['artifact_hashes']['presence']='old'
    elif case=='quote':d['evidence']['quote']='没有的动作'
    elif case=='anchor':d['changes'][0]['after']['after_audio_index']=1
    elif case=='extra':d['changes'][0]['after']['actor']='other'
    elif case=='duplicate':d['changes']*=2
    else:d['changes'][0]['before']['phase']='end'
    with pytest.raises(ValueError):retime(c,p,e,d)
