from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import run_integrated_effort_trial as m
from src.content_factory.novel_adaptation import integrated_screenplay as n

PRIOR=Path('data/corpus_production_trials/20261031_minimax_max_audio_review')


def fake_ledger(monkeypatch, calls, unknown_at=None):
    class Fake:
        def __init__(self,run,plan,state,client): self.run,self.plan,self.state=run,plan,state
        def save(self):
            (self.run/'STATE.json').write_text(json.dumps(self.state,ensure_ascii=False),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,deepcopy(self.plan['inference']),deepcopy(payload),prompt))
            self.state['calls_started']+=1
            self.state['pending']=self.state['calls_started']
            if len(calls)==unknown_at: raise RuntimeError('request_unknown_no_replay')
            self.state['pending']=None
            return {'text':'未署名的孩子声音：“嗯嗯。”\n孩子点头。\n这处改写无需原文逐字跨度门。' if name.startswith('screenplay') else '未通过，仍需人工核查。'}
    monkeypatch.setattr(m,'TextLedger',Fake)
    monkeypatch.setattr(m,'NativeClient',lambda *args:None)


def test_identical_complete_inputs_only_generation_effort_changes(tmp_path,monkeypatch):
    calls=[];fake_ledger(monkeypatch,calls)
    run=tmp_path/'trial';before=(PRIOR/'STATE.json').read_bytes()
    m.prepare(run,PRIOR);m.execute(run)
    assert len(calls)==8
    writers=calls[::2];reviews=calls[1::2]
    assert [x[1]['writer_effort'] for x in writers]==list(n.EFFORTS)
    assert {x[1]['writer_effort'] for x in reviews}=={'max'}
    assert {x[1]['writer_max_tokens'] for x in calls}=={32768}
    assert all(x[2]==writers[0][2] and x[3]==writers[0][3] for x in writers)
    assert writers[0][2]['source']==m.read(PRIOR/'INPUT.json')
    assert set(writers[0][2])=={'source','production_choices'}
    for effort,review in zip(n.EFFORTS,reviews):
        assert review[2]['candidate']==(run/effort/'SCREENPLAY.md').read_text('utf-8')
        assert not m.read(run/effort/'REVIEW_BINDING.json')['semantic_accepted']
    assert (PRIOR/'STATE.json').read_bytes()==before
    assert m.read(run/'STATE.json')['calls_started']==337
    with pytest.raises(ValueError,match='not_fresh'):m.execute(run)


def test_unknown_stops_other_variants_without_replay(tmp_path,monkeypatch):
    calls=[];fake_ledger(monkeypatch,calls,unknown_at=2)
    run=tmp_path/'trial';m.prepare(run,PRIOR);m.execute(run)
    assert len(calls)==2
    state=m.read(run/'STATE.json')
    assert state['status']=='outcome_unknown' and state['pending']==331
    assert (run/'medium/SCREENPLAY.md').exists() and not (run/'high').exists()
    with pytest.raises(ValueError,match='not_fresh'):m.execute(run)


def test_source_change_stops_before_dispatch(tmp_path,monkeypatch):
    calls=[];fake_ledger(monkeypatch,calls)
    run=tmp_path/'trial';m.prepare(run,PRIOR)
    packet=m.read(run/'INPUT.json');packet['chapters'][0]['paragraphs'][0]['text']='偷偷替换'
    (run/'INPUT.json').write_text(json.dumps(packet),encoding='utf-8')
    with pytest.raises(ValueError,match='changed_source'):m.execute(run)
    assert not calls


def test_natural_prose_is_protocol_only_not_literal_gate_or_semantic_pass():
    value={'text':'背景：地点未明确。\n场景一\n几个孩子应声，随即点头。'}
    assert n.validate_result(value)['protocol_passed']
    assert not n.validate_result(value)['semantic_accepted']
    with pytest.raises(ValueError,match='empty'):n.validate_result({'text':'   '})
    with pytest.raises(Exception):n.validate_result({'items':[]})
