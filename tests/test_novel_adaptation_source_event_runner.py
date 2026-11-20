import json
from copy import deepcopy
from src.content_factory.corpus_screenplay_v1 import freeze,read
from scripts import prepare_adaptation_source_events as runner
import pytest
from src.content_factory.novel_adaptation.events import select_reviewed_events
from src.content_factory.novel_adaptation.contracts import digest
from test_novel_adaptation_workflow import SOURCE,PACKET,DESIGN


def test_ledger_owned_result_is_not_written_twice(tmp_path,monkeypatch):
    prior=tmp_path/'prior';prepared=tmp_path/'prepared';out=tmp_path/'run'
    prior.mkdir();prepared.mkdir()
    freeze(prior/'STATE.json',{'status':'done','pending':None,'calls_started':10,'reported_tokens':100})
    freeze(prior/'PLAN.json',{'max_calls':10})
    for name,value in [('SOURCE',SOURCE),('PACKET',PACKET),('DESIGN',DESIGN),('BRIEF',{'target_chapters':[1]})]:
        freeze(prepared/(name+'.json'),deepcopy(value))
    class Ledger:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf8')
        def call(self,stage,*args):
            self.state['calls_started']+=1
            value={'events':[]};freeze(self.run/(stage+'.json'),value);return value
    monkeypatch.setattr(runner,'Ledger',Ledger)
    monkeypatch.setattr(runner,'NativeClient',lambda *args:None)
    monkeypatch.setattr('sys.argv',['runner','--prior',str(prior),'--prepared',str(prepared),'--run',str(out)])
    runner.main()
    assert read(out/'STATE.json')['status']=='events_awaiting_primary_review'
    assert read(out/'STATE.json')['calls_started']==11
    assert not (out/'ERROR.json').exists()


def test_source_selection_preserves_native_and_does_not_promote_design():
    native={'events':[{'id':'source','kind':'enter'},{'id':'rice','kind':'transform'}]}
    decisions={'proposal_sha256':digest(native),'source_sha256':digest(SOURCE),
               'verdicts':{'source':'source_required','rice':'design_only'}}
    selected=select_reviewed_events(native,SOURCE,decisions)
    assert selected=={'events':[native['events'][0]]} and len(native['events'])==2
    decisions['verdicts'].pop('rice')
    with pytest.raises(ValueError,match='coverage'):select_reviewed_events(native,SOURCE,decisions)
