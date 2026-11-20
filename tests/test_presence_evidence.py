from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.presence_evidence import catalog,compile_access
from src.content_factory.novel_adaptation.contracts import digest

def fixture(kind='camera_cut',certainty='explicit'):
    c={'scenes':[{'id':'S','place':'hall','segments':[{'id':'B','action':'门打开。','camera':'切入厨房。',
        'audio':[{'text':'说话'}],'continuity_obligations':['门随后关闭。']}]}]}
    base={'candidate_sha256':digest(c),'segments':[{'id':'B','moves':[]}],'uncertainties':[]}
    p={'candidate_sha256':digest(c),'access':[{'segment_id':'B','kind':kind,'place':'kitchen',
         'start':'before_audio','end':'audio:0','evidence_ids':['B:camera:0'],'certainty':certainty}], 'uncertainties':[]}
    return c,base,p

def test_camera_cut_cannot_grant_hearing_or_change_location():
    c,b,p=fixture();old=deepcopy(b);out,receipt=compile_access(c,b,p,['hall','kitchen'])
    w=out['segments'][0]['sensory_windows'][0]
    assert w['visible'] and not w['audible'] and w['quote']=='切入厨房。'
    assert b==old and out['segments'][0]['moves']==[]
    assert receipt['semantic_acceptance'] is False

def test_uncertain_and_inferred_access_never_silently_applied():
    for certainty in ('uncertain','inferred'):
        c,b,p=fixture(certainty=certainty);out,r=compile_access(c,b,p,['hall','kitchen'])
        assert 'sensory_windows' not in out['segments'][0] and len(r['unresolved'])==1

def test_compact_schema_does_not_allow_other_segments_evidence_or_anchor():
    c,b,p=fixture();second=deepcopy(c['scenes'][0]['segments'][0]);second['id']='B2'
    second['audio']*=2;c['scenes'][0]['segments'].append(second)
    b['segments'].append({'id':'B2','moves':[]})
    b['candidate_sha256']=p['candidate_sha256']=digest(c)
    p['access'][0]['evidence_ids']=['B2:camera:0']
    with pytest.raises(ValueError,match='access_evidence_wrong_segment'):
        compile_access(c,b,p,['hall','kitchen'])
    p['access'][0]['evidence_ids']=['B:camera:0'];p['access'][0]['end']='audio:1'
    with pytest.raises(ValueError,match='access_anchor_outside_segment'):
        compile_access(c,b,p,['hall','kitchen'])

@pytest.mark.parametrize('case',['unknown_evidence','wrong_audio','reversed','stale','cut_without_camera'])
def test_bad_reference_or_boundary_rejected(case):
    c,b,p=fixture();r=p['access'][0]
    if case=='unknown_evidence':r['evidence_ids']=['B:camera:99']
    elif case=='wrong_audio':r['end']='audio:1'
    elif case=='reversed':r.update(start='audio:0',end='before_audio')
    elif case=='stale':c['scenes'][0]['segments'][0]['action']='changed'
    elif case=='cut_without_camera':r['evidence_ids']=['B:action:0']
    with pytest.raises(ValueError):compile_access(c,b,p,['hall','kitchen'])
