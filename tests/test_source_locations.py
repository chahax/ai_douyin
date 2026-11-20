import json
from contextlib import nullcontext
from scripts import run_restricted_transcription as m
from src.content_factory.novel_adaptation import restricted_transcription as r,audiovisual_transcription as a

def packet():
    return a.packet({'chapters':[{'index':21,'text':'他们走到商场四楼的火锅店。\n\n回家途中，他们从便利店路过。\n\n这里不是车站。'}]},[],[21])

def test_source_location_rejects_synthesized_hierarchy():
    p=packet();head='场次：1\n'
    valid=r.location_diagnostics(head+'地点：CH21-P002|便利店',p)
    assert valid['references_valid'] and valid['ready_for_semantic_review']
    assert valid['evidence'][0]['original']=='回家途中，他们从便利店路过。'
    assert not valid['semantic_acceptance']
    for bad in ['商场便利店','CH21-P002|商场便利店','CH21-P001|便利店','CH99-P001|便利店','CH21-P002|便利店门口']:
        assert not r.location_diagnostics(head+'地点：'+bad,p)['references_valid']
    assert r.location_diagnostics(head+'地点：CH21-P001|商场四楼的火锅店',p)['references_valid']

def test_unknown_and_negation_not_automatically_accepted():
    pending=r.location_diagnostics('场次：1\n地点：待核',packet())
    assert pending['references_valid'] and not pending['ready_for_semantic_review']
    negative=r.location_diagnostics('场次：1\n地点：CH21-P003|车站',packet())
    assert negative['references_valid'] and not negative['semantic_acceptance']
    assert '不是' in negative['evidence'][0]['original']
    assert not r.location_diagnostics('场次：1',packet())['references_valid']
    assert not r.location_diagnostics('场次：1\n地点：待核\n地点：待核',packet())['references_valid']

def test_location_focus_binds_current_source_and_candidate(tmp_path,monkeypatch):
    run=tmp_path/'r';prior=m.Path('data/corpus_production_trials/20261030_semantic_coverage_focus')
    m.prepare_focus(run,prior,'source_locations');calls=[]
    assert m.read(run/'INPUT.json')==m.read(prior/'INPUT.json')
    assert m.read(run/'PLAN.json')['max_calls']==312
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1
            return {'text':'场次：1\n时间：傍晚\n地点：CH21-P082|便利店\n人物：苏墨\n画面[CH21-P082]：苏墨路过。\n原段：CH21-P082'}
    monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert len(calls)==2
    assert calls[0][1]['chapters']==m.read(prior/'INPUT.json')['chapters']
    assert calls[1][1]['location_diagnostics']['evidence'][0]['source_id']=='CH21-P082'
    assert calls[1][1]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
    assert calls[1][1]['coverage_guidance']==calls[0][1]['coverage_guidance']
    assert not m.read(run/'LOCATION_VALIDATION.json')['semantic_acceptance']
