import json
from contextlib import nullcontext
import pytest
from src.content_factory.novel_adaptation import audiovisual_transcription as a
from scripts import run_audiovisual_transcription as m

def test_exact_complete_source_without_summary():
    source={'chapters':[{'index':1,'text':'前情\n\n未署名对白'},{'index':2,'text':'目标开篇\n\n目标末尾'}]}
    result=a.packet(source,[1],[2])
    for old,new in zip(source['chapters'],result['chapters']):
        assert '\n\n'.join(p['text'] for p in new['paragraphs'])==old['text']
    assert result['chapters'][1]['paragraphs'][0]['id']=='CH2-P001'
    with pytest.raises(ValueError):a.packet(source,[1],[1])

@pytest.mark.parametrize('unknown',[False,True])
def test_only_transcription_then_same_candidate_review(tmp_path,monkeypatch,unknown):
    run=tmp_path/'r';m.prepare(run,m.Path('data/corpus_production_trials/20261030_faithful_agent_round2'));calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1
            if unknown:
                self.state['pending']=self.state['calls_started'];raise RuntimeError('unknown')
            return {'text':'原生稿\n【说话人待核】原句。'}
    monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert [x[0] for x in calls]==(['transcription'] if unknown else ['transcription','comparison'])
    if not unknown:
        assert calls[1][1]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
        assert not m.read(run/'REVIEW_BINDING.json')['semantic_acceptance']
    with pytest.raises(ValueError):m.execute(run)
