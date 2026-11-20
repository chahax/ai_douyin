from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import h3_recover_validator_f0051_20261104 as v
import h3_activate_validator_f0051_20261104 as activate


@pytest.fixture
def case(tmp_path):
    folder=tmp_path/'A0/F0051'
    folder.mkdir(parents=True)
    cmd=['python','validator','--graph','F0051']
    save=v.r.monitor.save
    save(folder/'STATE.json',dict(status='prepared',prompt_id=None,submissions=0))
    save(folder/'VALIDATION_PROCESS.json',dict(status='failed',returncode=v.CODE,command=cmd))
    save(folder/'VALIDATION_COMMAND.json',cmd)
    save(tmp_path/'STATE.json',dict(status='blocked',active_segment='F0051',completed=50,
         error=str(subprocess.CalledProcessError(v.CODE,cmd))))
    return tmp_path,folder


def test_exact_pre_submission_fault(case):
    assert v.eligible(*case)['active_segment']=='F0051'


@pytest.mark.parametrize('path',['REQUEST.actual.json','SUBMISSION_CLAIM.json','SUBMISSION_RESPONSE.json','job_ids.txt','NATIVE_VALIDATION.json'])
def test_prior_attempt_blocks(case,path):
    (case[1]/path).write_text('{}')
    with pytest.raises(v.r.Blocked):v.eligible(*case)


@pytest.mark.parametrize('field,value',[('status','running'),('error','manual_pause'),('active_segment','F0052'),('completed',51)])
def test_other_block_preserved(case,field,value):
    state=v.r.h.read(case[0]/'STATE.json')
    state[field]=value
    v.r.monitor.save(case[0]/'STATE.json',state)
    with pytest.raises(v.r.Blocked):v.eligible(*case)


def test_pause_and_accepted_id_block(case):
    stop=case[0]/'PAUSE.json'
    stop.write_text('{}')
    with pytest.raises(v.r.Blocked):v.eligible(*case)
    stop.unlink()
    v.r.monitor.save(case[1]/'STATE.json',dict(status='submitted',prompt_id='existing',submissions=1))
    with pytest.raises(v.r.Blocked):v.eligible(*case)


def test_retry_budget_once(case,monkeypatch):
    marker=case[0]/'RETRY_CLAIM'
    marker.write_text('earlier')
    original=case[0]/'interrupted'
    v.r.monitor.save(original/'VALIDATION_PROCESS.json',dict(pid=12345))
    monkeypatch.setattr(v,'INTERRUPTED',original)
    monkeypatch.setattr(v.r.psutil,'pid_exists',lambda _:False)
    monkeypatch.setattr(v,'inspect',lambda: {})
    monkeypatch.setattr(v,'CASE',case[0])
    with pytest.raises(FileExistsError):v.retry()
    assert marker.read_text()=='earlier'


@pytest.mark.parametrize('field,value',[('graph_sha256','other'),('valid',False),('node_errors',{'x':1}),('node_execution_performed',True)])
def test_rejects_different_validation(case,field,value):
    report=dict(valid=True,node_errors={},graph_sha256='test',node_execution_performed=False)
    report[field]=value
    p=case[0]/'new_report.json'
    v.r.monitor.save(p,report)
    with pytest.raises(v.r.Blocked):v.verify_report(p,'test')


def test_archive_switch_preserves_original_bytes_and_inputs(case,monkeypatch):
    run,t=case
    casehome=run/'recovery'
    stage=casehome/'new/F0051'
    archive=casehome/'archive/F0051'
    stage.mkdir(parents=True)
    for name in ('STATE.json','VALIDATION_PROCESS.json'):
        (stage/name).write_bytes((t/name).read_bytes())
    v.r.monitor.save(stage/'VALIDATION_PROCESS.json',dict(status='completed',returncode=0))
    (stage/'workflow_api.json').write_text('{}')
    v.r.monitor.save(stage/'NATIVE_VALIDATION.json',dict(valid=True,node_errors={},node_execution_performed=False,graph_sha256=v.r.h.sha(stage/'workflow_api.json')))
    snapshot=activate.tree(t)
    before=dict(block=v.r.h.read(run/'STATE.json'))
    v.r.monitor.save(casehome/'BEFORE.json',before)
    v.r.monitor.save(casehome/'RETRY_RESULT.json',dict(valid=True))
    config=casehome/'PLAN.json'
    cfg=dict(old_state=before['block'],old_tree=snapshot,new_tree=activate.tree(stage))
    v.r.monitor.save(config,cfg)
    for k,value in dict(RUN=run,TARGET=t,CASE=casehome,STAGE=stage,ARCHIVE=archive,CONFIG=config).items():
        monkeypatch.setattr(activate,k,value)
    monkeypatch.setattr(v.r,'OLD',run/'old')
    monkeypatch.setattr(v.r.monitor,'assert_config',lambda _:cfg)
    monkeypatch.setattr(activate,'check_idle',lambda:None)
    monkeypatch.setattr(v,'inspect',lambda:before)
    monkeypatch.setattr(v.r.b,'validate_frozen',lambda _:None)
    monkeypatch.setattr(v.r,'validate_native',lambda _:None)
    activate.apply()
    assert activate.tree(archive)==snapshot and v.r.h.read(archive/'VALIDATION_PROCESS.json')['returncode']==v.CODE
    assert v.r.h.read(t/'VALIDATION_PROCESS.json')['returncode']==0 and v.r.h.read(run/'STATE.json')['status']=='prepared'
    assert v.r.h.read(casehome/'APPLIED.json')['media_submissions']==0

