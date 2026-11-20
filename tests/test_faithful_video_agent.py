import json
from contextlib import nullcontext
import pytest
from scripts import run_faithful_video_agent as m

@pytest.mark.parametrize('unknown',[False,True])
def test_complete_pipeline_and_unknown_stop(tmp_path,monkeypatch,unknown):
    prior=m.Path('data/corpus_production_trials/20261029_upstream_methods_probe')
    auth=m.Path('data/corpus_production_trials/20261030_faithful_two_rounds_preflight/DISPOSITION_290.json')
    run=tmp_path/'r';m.prepare(run,prior,auth);calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1
            if unknown and name=='scene_plan':
                self.state['pending']=self.state['calls_started'];raise RuntimeError('unknown')
            return {'text':name}
    monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    state=m.read(run/'STATE.json')
    assert len(calls)==(2 if unknown else 6)
    assert state['retained_unknowns'][-1]['call']==290
    if not unknown:
        assert state['status']=='awaiting_primary_full_review'
        for name,payload in calls:
            if name in ['continuity_review','fidelity_review','handoff']:assert payload['complete_candidate']=='screenplay'
        assert not m.read(run/'handoff_BINDING.json')['semantic_acceptance']
    else:assert state['status']=='outcome_unknown'
    with pytest.raises(ValueError):m.execute(run)

@pytest.mark.parametrize('finish,stream,pending,accepted',[
    ('stop','known',None,True),('length','known',None,False),
    ('stop','unknown',None,False),('stop','known',9,False)])
def test_plain_text_adoption_requires_known_complete(tmp_path,monkeypatch,finish,stream,pending,accepted):
    from src.content_factory.novel_adaptation import stream_evidence
    ledger=object.__new__(m.TextLedger)
    ledger.run=tmp_path;ledger.state={'calls_started':9,'pending':pending}
    original='完整原生正文\n含换行，不改写。'
    m.freeze(tmp_path/'RESPONSE_009.json',{'native':{'choices':[{'finish_reason':finish,'message':{'content':original}}]}})
    def failure(*a):raise RuntimeError('native_tool_submission_missing')
    monkeypatch.setattr(m.DirectLedger,'call',failure)
    monkeypatch.setattr(stream_evidence,'audit_folder',lambda *a:{'completion_evidence':stream})
    if accepted:
        assert ledger.call('stage','writer','',{}, {})=={'text':original}
        assert not m.read(tmp_path/'stage_TEXT_ADOPTION.json')['semantic_acceptance']
    else:
        with pytest.raises(RuntimeError):ledger.call('stage','writer','',{}, {})
        assert not (tmp_path/'stage_DIRECT_DECODED.json').exists()
