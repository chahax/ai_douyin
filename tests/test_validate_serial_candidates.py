import json
import pytest
from scripts.validate_serial_candidates import prepare

def write(p,value):p.write_text(json.dumps(value),encoding='utf-8')

@pytest.mark.parametrize('continuation',[False,True])
def test_prepare_preserves_candidates_unknowns_and_budget(tmp_path,continuation):
    prior=tmp_path/'prior';prior.mkdir();run=tmp_path/'new'
    state={'status':'needs_attention','pending':None,'calls_started':261,'reported_tokens':12,'retained_unknowns':[{'call':135,'usage':None}]}
    plan={'version':'complete_candidate_validation_v1' if continuation else 'old','max_calls':264,'inference':{'writer_max_tokens':8192}}
    write(prior/'STATE.json',state);write(prior/'PLAN.json',plan)
    for name in ['SOURCE','REGISTRY']:write(prior/(name+'.json'),{})
    for n in (1,7):write(prior/f'CANDIDATE_{n:02}.json',{'screenplay':'未改变','continuity':'旧资料也需审核'})
    original=(prior/'STATE.json').read_bytes();prepare(run,prior)
    actual=json.loads((run/'PLAN.json').read_text(encoding='utf-8'))
    assert actual['max_calls']==(264 if continuation else 265)
    assert actual['inference']['writer_max_tokens']==16384
    assert json.loads((run/'STATE.json').read_text(encoding='utf-8'))['retained_unknowns']==state['retained_unknowns']
    assert (prior/'STATE.json').read_bytes()==original
    assert (run/'CANDIDATE_01.json').read_text(encoding='utf-8').find('旧资料也需审核')>=0
