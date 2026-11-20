from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.narrative_presence import replay
from src.content_factory.novel_adaptation.contracts import digest,ContractError

def fixture():
    c={'scenes':[{'id':'S','place':'room','entry_continuity':'甲在屋内，乙走进来。','exit_continuity':'两人仍在屋内。',
        'segments':[{'id':'B','visible_people':['b'],'action':'乙走进来。','continuity_obligations':[],
                     'audio':[{'kind':'dialogue','speaker':'b','text':'你好'}]}]}]}
    p={'candidate_sha256':digest(c),'initial_locations':{'a':'room','b':'hall'},'segments':[{'id':'B','moves':[
        {'person':'b','origin':'hall','destination':'room','phase':'start','after_audio_index':None,
         'evidence_field':'action','quote':'乙走进来。'}]}],'uncertainties':[]}
    return c,p

def test_offcamera_person_still_present_and_hears_dialogue():
    c,p=fixture();r=replay(c,p,['a','b'],['room','hall'])
    assert r['end_state']['locations']['a']=='room'
    assert r['trace'][0]['audio_audiences'][0]['present']==['a','b']
    assert len(r['end_state']['information']['a'])==1

@pytest.mark.parametrize('case',['missing_move','stale','wrong_origin','fake_quote','anchor','duplicate'])
def test_invalid_projection_rejected(case):
    c,p=fixture();m=p['segments'][0]['moves'][0]
    if case=='missing_move':p['segments'][0]['moves']=[]
    elif case=='stale':c['scenes'][0]['segments'][0]['action']='改稿'
    elif case=='wrong_origin':m['origin']='room'
    elif case=='fake_quote':m['quote']='乙离开。'
    elif case=='anchor':m.update(phase='after_audio',after_audio_index=3)
    elif case=='duplicate':p['segments']*=2
    with pytest.raises(ValueError):replay(c,p,['a','b'],['room','hall'])

def test_replay_does_not_mutate_projection():
    c,p=fixture();old=deepcopy(p);replay(c,p,['a','b'],['room','hall']);assert p==old


def test_program_binding_uses_request_identity_without_mutating_model_result():
    from src.content_factory.novel_adaptation.narrative_presence import bind_body
    c,p=fixture();body=deepcopy(p);del body['candidate_sha256'];old=deepcopy(body)
    assert bind_body(c,body,digest(c),['a','b'],['room','hall'])==p
    assert body==old
    with pytest.raises(ValueError):bind_body(c,body,'old-request',['a','b'],['room','hall'])
    with pytest.raises(ValueError):bind_body(c,p,digest(c),['a','b'],['room','hall'])
