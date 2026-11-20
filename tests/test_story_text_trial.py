import pytest
from scripts.run_story_text_trial import prepare
from src.content_factory.corpus_screenplay_v1 import freeze,read,digest
from test_story_text import SOURCE,PACKET

def setup(tmp_path):
    prior=tmp_path/'prior';prior.mkdir()
    state={'status':'outcome_unknown','pending':135,'calls_started':135,'reported_tokens':100}
    freeze(prior/'STATE.json',state);freeze(prior/'SOURCE.json',SOURCE)
    freeze(prior/'PLAN.json',{'max_calls':140,'inference':{'writer_effort':'xhigh'}})
    packet=tmp_path/'packet.json';freeze(packet,PACKET)
    return prior,packet,state

def test_explicit_authorization_preserves_unknown_and_cumulative_count(tmp_path):
    prior,packet,state=setup(tmp_path);auth=tmp_path/'auth.json'
    freeze(auth,{'authorized':True,'call':135,'original_state_sha256':digest(state),'original_unknown_preserved':True})
    run=tmp_path/'new';prepare(run,prior,packet,auth,[1])
    assert read(prior/'STATE.json')==state
    new=read(run/'STATE.json')
    assert new['calls_started']==135 and new['reported_tokens']==100 and new['pending'] is None
    assert new['retained_unknowns'][0]['usage'] is None and not new['reported_usage_complete']
    assert read(run/'PLAN.json')['max_calls']==140

def test_unknown_without_specific_authorization_does_not_create_trial(tmp_path):
    prior,packet,state=setup(tmp_path)
    with pytest.raises(ValueError,match='authorization_missing'):prepare(tmp_path/'new',prior,packet,None,[1])
    assert not (tmp_path/'new').exists()


def test_next_known_run_does_not_erase_carried_unknown_usage(tmp_path):
    import json
    prior,packet,state=setup(tmp_path)
    state.update(status='needs_attention',pending=None,calls_started=136,
                 retained_unknowns=[{'call':135,'usage':None}])
    (prior/'STATE.json').write_text(json.dumps(state),encoding='utf-8')
    prepare(tmp_path/'next',prior,packet,None,[1])
    new=read(tmp_path/'next/STATE.json')
    assert new['retained_unknowns']==state['retained_unknowns'] and not new['reported_usage_complete']
