import json
from contextlib import nullcontext
from pathlib import Path
import pytest
from scripts import try_adaptation_project_methods as m

@pytest.mark.parametrize('failure',[None,'known','unknown'])
def test_arm_isolation_and_no_unknown_replay(tmp_path,monkeypatch,failure):
    m.prepare(tmp_path/'run');run=tmp_path/'run';calls=[]
    class FakeLedger:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload.copy()))
            self.state['calls_started']+=1
            if failure and name=='baseline_plan':
                if failure=='unknown':self.state['pending']=self.state['calls_started']
                raise RuntimeError(failure)
            return {'text':name}
    monkeypatch.setattr(m,'DirectLedger',FakeLedger)
    monkeypatch.setattr(m,'NativeClient',lambda *a:None)
    monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    state=json.loads((run/'STATE.json').read_text(encoding='utf-8'))
    assert len(calls)==(9 if failure is None else 8 if failure=='known' else 2)
    if failure=='unknown':assert state['status']=='outcome_unknown'
    else:
        assert state['pending'] is None
        for name,payload in calls:
            arm=name.rsplit('_',1)[0]
            assert all(v.startswith(arm+'_') for v in payload['this_arm_prior_results'].values())
            assert 'checks' not in payload and 'EVALUATION_FROZEN' not in payload
    with pytest.raises(ValueError,match='not_fresh'):m.execute(run)

def test_pinned_sources_and_equal_stage_counts(tmp_path):
    run=tmp_path/'run';m.prepare(run)
    methods=m.read(run/'METHODS.json');plan=m.read(run/'PLAN.json')
    assert [len(v) for v in methods.values()]==[3,3,3]
    assert plan['max_calls']-plan['baseline_calls']==9
    assert [x['index'] for x in m.read(run/'INPUT.json')['chapters']]==[19,20]
    assert m.read(run/'UPSTREAM_MANIFEST.json')
