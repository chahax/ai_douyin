import json
from pathlib import Path

import pytest

from src.web import h3_manifest_progress as view, h3_recovery_control as ctl


def put(path,val):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(val),encoding='utf8')


@pytest.mark.parametrize('heartbeat',[2000,True,float('nan'),float('inf'),'1000',None])
def test_future_or_invalid_supervisor_time_cannot_claim_protection(tmp_path,heartbeat):
    put(tmp_path/'STATE.json',dict(status='monitoring',heartbeat_epoch=heartbeat))
    data=view.load_supervisor(tmp_path,now=1000,process_alive=lambda _:True)
    assert not data['protected']


def saved(path,name,id):
    path.mkdir(parents=True,exist_ok=True)
    file=path/(name+'.mp4')
    file.write_bytes(b'fixture')
    put(path/'STATE.json',dict(status='saved',prompt_id=id))
    put(path/'receipt.json',dict(prompt_id=id,technical_status='succeeded',delivery=dict(path=str(file))))
    return path


@pytest.fixture
def run(tmp_path,monkeypatch):
    run=tmp_path/ctl.NEW
    old=saved(tmp_path/ctl.OLD/'F0001','F0001','one')
    replacement=saved(run/'A1/F0002','F0002','two')
    items=[dict(id='F0001',frames=100,prior=dict(path=str(old/'receipt.json'),sha256=ctl.digest(old/'receipt.json'))),
           dict(id='F0002',frames=150),dict(id='F0003',frames=100),dict(id='F0004',frames=150)]
    put(run/'PLAN.json',dict(schema='h3_restart_continuation/v1',segments=items))
    put(run/'PRIMARY_REVIEW.json',dict(approved=True,config_sha256=ctl.digest(run/'PLAN.json')))
    put(run/'STATE.json',dict(status='running',active_segment='F0003'))
    put(run/'segments/F0002/STATE.json',dict(status='saved',folder=str(replacement),prompt_id='two'))
    put(run/'segments/F0003/STATE.json',dict(status='submitted',folder=str(run/'A0/F0003'),prompt_id='three'))
    put(run/'A0/F0003/STATE.json',dict(status='submitted',prompt_id='three'))
    put(run/'A0/F0003/SUBMISSION_CLAIM.json',dict(source='fixture'))
    monkeypatch.setattr(ctl,'live_runner',lambda _:False)
    return run


def test_read_history_and_new_selection_without_writes(run):
    files={p:p.stat().st_mtime_ns for p in run.rglob('*')}
    data=view.load(run)
    assert data['completed']==2 and data['total']==4 and not data['errors']
    assert [x['status'] for x in data['rows']]==['saved','saved','submitted','prepared']
    assert data['rows'][0]['video'].parent==run.parent/ctl.OLD/'F0001'
    assert data['rows'][1]['video'].parent==run/'A1/F0002'
    assert data['rows'][2]['prompt_id']=='three'
    assert files=={p:p.stat().st_mtime_ns for p in run.rglob('*')}


def test_rejects_foreign_folder(run):
    put(run/'segments/F0002/STATE.json',dict(status='saved',folder=str(run.parent),prompt_id='two'))
    assert view.load(run)['completed']==1


def test_refuses_prior_changed_and_video_escape(run):
    old=run.parent/ctl.OLD/'F0001'
    with (old/'receipt.json').open('a') as f:f.write(' ')
    put(run/'A1/F0002/receipt.json',dict(technical_status='succeeded',prompt_id='two',delivery={'path':str(old/'F0001.mp4')}))
    assert view.load(run)['completed']==0


def test_admin_roundtrip_keeps_id_and_original_before(run):
    ctl.control(run,'pause','alice','admin')
    mark=ctl.load_json(run/'PAUSE.json')
    put(run/'STATE.json',dict(status='blocked',error='manual_pause',active_segment='F0003'))
    ctl.control(run,'resume','alice','admin',mark['id'])
    assert not (run/'PAUSE.json').exists()
    assert ctl.load_json(run/'STATE.json')['status']=='paused'
    assert ctl.load_json(run/'A0/F0003/STATE.json')['prompt_id']=='three'
    audit=run/'dashboard_controls'/mark['id']
    assert ctl.load_json(next(audit.glob('*RESUME_INTENT.json')))['before']['error']=='manual_pause'
    assert ctl.load_json(audit/'RELEASED_PAUSE.json')==mark


@pytest.mark.parametrize('role,user',[('viewer','ops'),('editor','ops'),('admin','')])
def test_admin_required(run,role,user):
    with pytest.raises(PermissionError):
        ctl.control(run,'pause',user,role)
    assert not (run/'PAUSE.json').exists()


@pytest.mark.parametrize('failure',['unknown_claim','bounded_restarts_exhausted','native_error'])
def test_resume_never_unblocks_other_failure(run,failure):
    ctl.control(run,'pause','alice','admin')
    put(run/'STATE.json',dict(status='blocked',error=failure,active_segment='F0003'))
    with pytest.raises(ValueError):
        ctl.control(run,'resume','alice','admin',ctl.load_json(run/'PAUSE.json')['id'])
    assert (run/'PAUSE.json').exists() and ctl.load_json(run/'STATE.json')['error']==failure


def test_changed_anchor_or_live_runner_keeps_marker(run,monkeypatch):
    ctl.control(run,'pause','alice','admin')
    mark=ctl.load_json(run/'PAUSE.json')
    monkeypatch.setattr(ctl,'live_runner',lambda _:True)
    with pytest.raises(ValueError,match='退出'):ctl.control(run,'resume','alice','admin',mark['id'])
    monkeypatch.setattr(ctl,'live_runner',lambda _:False)
    put(run/'A0/F0003/SUBMISSION_CLAIM.json',dict(source='other'))
    with pytest.raises(ValueError,match='变化'):ctl.control(run,'resume','alice','admin',mark['id'])


def test_unowned_marker_and_stale_ui_id_fail(run):
    ctl.control(run,'pause','alice','admin')
    mark=ctl.load_json(run/'PAUSE.json')
    with pytest.raises(ValueError):ctl.control(run,'resume','alice','admin','a'*32)
    put(run/'PAUSE.json',dict(mark,actor='changed'))
    with pytest.raises(ValueError):ctl.control(run,'resume','alice','admin',mark['id'])
    assert (run/'PAUSE.json').exists()
