import json
from pathlib import Path
import pytest
from scripts import run_integrated_review_followup as f

PRIOR=Path('data/corpus_production_trials/20261031_integrated_revision_deepseek')
HANDOFF=Path('data/qa/deepseek_followup_handoff_20261101.json')


def test_import_binds_review_candidate_and_preserves_completed_parent(tmp_path):
    before=(PRIOR/'STATE.json').read_bytes()
    r=tmp_path/'run'; f.prepare(r,PRIOR,HANDOFF)
    plan=f.read(r/'PLAN.json'); state=f.read(r/'STATE.json')
    assert plan['baseline_calls']==348 and plan['max_calls']==350
    assert state['pending'] is None and state['status']=='awaiting_issue_adjudication'
    assert (r/'ORIGINAL.md').read_bytes()==(PRIOR/'SCREENPLAY.md').read_bytes()
    assert (PRIOR/'STATE.json').read_bytes()==before
    assert len(f.read(r/'review.json')['issues'])==4


def test_stale_review_mapping_rejected_before_run_creation(tmp_path):
    h=f.read(HANDOFF);h['prior_binding']['candidate_digest']='wrong'
    p=tmp_path/'handoff.json';p.write_text(json.dumps(h),encoding='utf-8')
    with pytest.raises(ValueError,match='handoff_binding'):f.prepare(tmp_path/'run',PRIOR,p)
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('file,value', [('PARENT_DEEPSEEK_REVIEW.md','changed'),('review.json','{}'),('DECISIONS.json','{}')])
def test_tampered_inputs_do_not_dispatch(tmp_path,monkeypatch,file,value):
    r=tmp_path/'run';f.prepare(r,PRIOR,HANDOFF)
    (r/file).write_text(value,encoding='utf-8')
    monkeypatch.setattr(f.runner,'execute',lambda *args:pytest.fail('must not dispatch'))
    with pytest.raises(ValueError,match='changed_'):f.execute(r,'repair')


def test_mock_followup_deletion_and_independent_final(tmp_path,monkeypatch):
    r=tmp_path/'run';f.prepare(r,PRIOR,HANDOFF);calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,role,payload));self.state['calls_started']+=1
            value={s['key']:'' if s['key']=='edit_3' else s['quote'] for s in payload['slots']} if name=='patch' else {'text':'mock, no semantic pass'}
            (self.run/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
            return value
    monkeypatch.setattr(f.runner,'DirectLedger',Fake);monkeypatch.setattr(f.runner,'Ledger',Fake)
    monkeypatch.setattr(f.runner,'NativeClient',lambda *a:None)
    monkeypatch.setattr(f.runner,'audit_folder',lambda p:{'completion_evidence':'known'})
    f.execute(r,'repair');f.execute(r,'final')
    assert [x[1] for x in calls]==['writer','director']
    assert set(calls[1][2])=={'source','production_choices','candidate'}
    assert '是否分两趟' not in (r/'SCREENPLAY.md').read_text(encoding='utf-8')
    assert f.read(r/'STATE.json')['calls_started']==350
    assert not f.read(r/'FINAL_REVIEW_BINDING.json')['semantic_accepted']
    with pytest.raises(ValueError,match='stage_not_ready'):f.execute(r,'repair')
