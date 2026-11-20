"""Local pre-script proof, exact old records and one successor; no real models."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import types

import psutil
import pytest

from src.content_factory import visual_local_review_recovery_v6 as r
from src.content_factory import visual_residence_appearance_v6 as a
from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_residence_style_v5 as storage
from test_visual_asset_pipeline_v3 import service
from test_visual_residence_appearance_storage_v6 import setup_v6,make_bundle,appearance_result


def write(path,value):p.write(path,value)


@pytest.fixture
def case(tmp_path,service,monkeypatch):
    run,plan,packet,master,source,parent,_=setup_v6(tmp_path,service)
    bundle=make_bundle(run,plan,packet,master,source,parent)
    assert storage.accept_reference(bundle,appearance_result(storage.reference_request(bundle)))
    entity=packet['places'][1];guide=p._environment_guide(run,entity,'front')
    target=tmp_path/'sibling.png';shutil.copyfile(guide['path'],target)
    row=library.register(plan['config']['library'],target,book_id=packet['book_id'],entity_id=entity['id'],kind='place',view='front',
        design_version=entity['design_version'],provenance=dict(environment_guide=guide,source=packet['source'],
            dependencies=[p._asset_identity(master)],dependency_fingerprint=p.fingerprint([p._asset_identity(master)]),
            residence_style=p._style_provenance(bundle,entity)))
    target=p._image_path(plan,row);request=storage.target_request(bundle,entity,target)
    prepared=a._prepared(request);config=dict(provider='transformers_local',timeout=900,max_tokens=1800)
    model=dict(available=True,provider='transformers_local',model='fixture-only-no-model',capabilities=['vision'])
    native_binding=v.digest(dict(config=config,prepared=prepared));style_dir=run/'style_reviews'/'original_target'
    original_request=dict(config=config,prepared=[prepared],request_binding_sha256=native_binding,model_binding=model,review_mode=a.VERSION)
    write(style_dir/'REQUEST.json',original_request);write(style_dir/'CLAIM.json',dict(request_binding_sha256=native_binding))
    exited=dict(exited=True,terminated_on_timeout=True,request_binding_sha256=native_binding)
    error=dict(type='TimeoutExpired',message='Fixture local worker did not initialize within 900 seconds.')
    write(style_dir/'WORKER_EXIT.json',exited);write(style_dir/'WORKER_ERROR.json',error);(style_dir/'worker.log').write_bytes(b'')
    timeout=a._unavailable(prepared,subprocess.TimeoutExpired(['fixture-python'],900),model)
    layout_prepared=v._prepared(dict(target=str(target),layout_guide=guide['path'],expectation=dict(kind='place',view='front',expected_people=0,locate_rois=[])))
    observed=dict(checks={k:True for k in v.PLACE_CHECKS},observations=dict(people_count=0,age_band='unknown',orientation='unknown',
        framing='environment',pose_view='unknown'),issues=[],rois={k:None for k in v.ROI_NAMES},reference_rois={k:None for k in v.ROI_NAMES},
        evidence=['Protocol fixture completed layout, not actual visual approval.'])
    layout=v._finish(layout_prepared,observed,model,[]);layout_dir=run/'reviews'/'completed_layout'
    layout_binding=v.digest(dict(config=config,requests=[layout_prepared]))
    write(layout_dir/'REQUEST.json',dict(config=config,prepared=[layout_prepared],request_binding_sha256=layout_binding,model_binding=model))
    write(layout_dir/'RESULTS.json',dict(request_binding_sha256=layout_binding,results_sha256=v.digest([layout]),results=[layout]))
    write(layout_dir/'WORKER_EXIT.json',dict(exited=True,code=0,request_binding_sha256=layout_binding))
    write(layout_dir/'WORKER_STATE.json',dict(stage='completed'))
    for name,value in [('RESULT.json',layout),('BLIND_NATIVE.json',dict(text='Fixture known native.')),('MODEL_NATIVE.json',dict(text='Fixture known native.'))]:
        write(layout_dir/'item_0000'/name,value)
    old=p._combine_residence_style(layout,dict(request=request,request_sha256=v.digest(request),result=timeout))
    library.review(plan['config']['library'],book_id=row['book_id'],asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
        decision='unavailable',reviewer='fixture-only',checks=old['checks'],evidence=dict(image_sha256=row['sha256'],
            observations=old['visual_evidence'],review=v.digest(old),source_review=old))
    key=f"{row['asset_id']}:v{row['version']}:{row['sha256']}";state=p.read(run/'STATE.json')
    state.update(status='paused',reviews={key:old},review_attempts={key:1});write(run/'STATE.json',state)
    p.set_paused(run,True,actor='fixture-admin',role='admin')
    diagnosis=tmp_path/'DIAGNOSIS.json'
    proof=dict(files=[dict(request_path=str(style_dir/'REQUEST.json'),sha256=r._sha(style_dir/'REQUEST.json'),worker_state_exists=False,
        worker_log_bytes=0,worker_exit=exited,worker_error=error)],processes=[dict(pid=991001,error='NoSuchProcess'),dict(pid=991002,error='NoSuchProcess')],
        earlier_readonly_samples=[dict(pid=991002,status='stopped',user_cpu_seconds=0,system_cpu_seconds=0,
            modules=['C:/Python/python.exe','C:/Windows/System32/ntdll.dll'])])
    write(diagnosis,proof)
    monkeypatch.setattr(r.psutil,'Process',lambda pid:(_ for _ in ()).throw(psutil.NoSuchProcess(pid)))
    @contextmanager
    def no_gpu(*args,**kwargs):yield
    monkeypatch.setattr(p,'gpu_access',no_gpu)
    return types.SimpleNamespace(run=run,key=key,style_dir=style_dir,layout_dir=layout_dir,diagnosis=diagnosis,
        original=deepcopy(old),request=request,config=config,model=model,row=row,plan=plan)


def prepare(c,token='once'):
    return r.prepare_recovery(c.run,c.key,c.style_dir,c.layout_dir,c.diagnosis,
        recovery_id=token,actor='fixture-admin',statement='Explicitly authorized one target-only successor; old unknown retained.')


class Reviewer:
    provider='transformers_local'
    def __init__(self,c,*,unknown=False):self.config=c.config;self.model=c.model;self.calls=[];self.unknown=unknown
    def discover(self):return deepcopy(self.model)
    def review_style_materials(self,*a,**k):pytest.fail('Do not call source/material review.')
    def review_many(self,*a,**k):pytest.fail('Do not repeat accepted layout.')
    def review_residence_appearance(self,request,evidence_dir):
        assert request['mode']=='target';self.calls.append(deepcopy(request));folder=Path(evidence_dir);prepared=a._prepared(request)
        binding=v.digest(dict(config=self.config,prepared=prepared))
        write(folder/'REQUEST.json',dict(config=self.config,prepared=[prepared],request_binding_sha256=binding,model_binding=self.model,review_mode=a.VERSION))
        if self.unknown:return a._unavailable(prepared,v.ReviewOutcomeUnknown('Fixture new unknown'),self.model)
        raw=dict(checks={k:True for k in a.CHECKS},patch_checks=[dict(slot=q['slot'],usable_color=True,visible_finish=True,layout_free=True,
            evidence='Fixture appearance result, not semantic quality.') for q in request['patches']],evidence=['Fixture actual-completion protocol only.'])
        result=a._review_one(prepared,lambda _:dict(text=json.dumps(raw)),self.model,folder/'item_0000')
        write(folder/'item_0000/RESULT.json',result)
        write(folder/'RESULTS.json',dict(request_binding_sha256=binding,results_sha256=v.digest([result]),results=[result]))
        write(folder/'WORKER_STATE.json',dict(stage='completed'));write(folder/'WORKER_EXIT.json',dict(exited=True,code=0,request_binding_sha256=binding))
        write(folder/'WORKER_RUNTIME.json',dict(pid=991003,actual_executable='fixture-base-python',prefix='fixture-venv',request_binding_sha256=binding))
        return result


def test_one_target_successor_reuses_known_layout_keeps_unknown_and_does_not_unpause(case):
    c=case;before={str(f):f.read_bytes() for folder in (c.style_dir,c.layout_dir) for f in folder.rglob('*') if f.is_file()}
    folder=prepare(c);reviewer=Reviewer(c);receipt=r.execute_recovery(folder,reviewer)
    assert receipt['combined_decision']=='accepted' and receipt['original_outcome_known'] is False and len(reviewer.calls)==1
    state=p.read(c.run/'STATE.json');assert state['review_attempts'][c.key]==2 and state['review_history'][c.key]==[c.original]
    assert state['reviews'][c.key]['layout_review']==c.original['layout_review'] and state['status']=='paused' and (c.run/'PAUSE.json').exists()
    assert before=={str(f):f.read_bytes() for folder in (c.style_dir,c.layout_dir) for f in folder.rglob('*') if f.is_file()}
    assert r.execute_recovery(folder,reviewer)==receipt and len(reviewer.calls)==1


def test_new_unknown_consumes_last_attempt_without_combining_or_replaying(case):
    folder=prepare(case);reviewer=Reviewer(case,unknown=True);receipt=r.execute_recovery(folder,reviewer)
    state=p.read(case.run/'STATE.json')
    assert receipt['combined_decision']=='not_combined_original_unknown_preserved' and state['reviews'][case.key]==case.original
    assert state['review_attempts'][case.key]==2 and len(reviewer.calls)==1
    assert r.execute_recovery(folder,reviewer)==receipt and len(reviewer.calls)==1
    with pytest.raises(ValueError,match='budget'):prepare(case,'another')


@pytest.mark.parametrize('marker',['WORKER_RUNTIME.json','WORKER_STATE.json','WORKER_FAILURE.json','RESULTS.json','item_0000/STYLE_CLAIM.json'])
def test_any_python_entry_or_native_inference_marker_refuses_recovery(case,marker):
    write(case.style_dir/marker,dict(fixture=True))
    with pytest.raises(ValueError,match='may_have_entered'):prepare(case)


@pytest.mark.parametrize('defect',['nonempty_log','wrong_request_sha','changed_layout','exhausted_budget','no_pause'])
def test_original_byte_bindings_layout_and_budget_are_required(case,defect):
    if defect=='nonempty_log':(case.style_dir/'worker.log').write_text('Entered Python.')
    elif defect=='wrong_request_sha':
        proof=p.read(case.diagnosis);proof['files'][0]['sha256']='f'*64;write(case.diagnosis,proof)
    elif defect=='changed_layout':
        value=p.read(case.layout_dir/'RESULTS.json');value['results'][0]['checks']['layout']=False;write(case.layout_dir/'RESULTS.json',value)
    elif defect=='exhausted_budget':
        state=p.read(case.run/'STATE.json');state['review_attempts'][case.key]=2;write(case.run/'STATE.json',state)
    else:(case.run/'PAUSE.json').unlink()
    with pytest.raises((ValueError,FileNotFoundError)):prepare(case)


def test_changed_evidence_or_live_original_process_cannot_dispatch_successor(case,monkeypatch):
    folder=prepare(case);reviewer=Reviewer(case)
    monkeypatch.setattr(r.psutil,'Process',lambda pid:types.SimpleNamespace())
    with pytest.raises(ValueError,match='still_exists'):r.execute_recovery(folder,reviewer)
    assert not reviewer.calls and not (folder/'CLAIM.json').exists()


def test_access_denied_exit_probe_is_never_treated_as_no_such_process(case,monkeypatch):
    monkeypatch.setattr(r.psutil,'Process',lambda pid:(_ for _ in ()).throw(psutil.AccessDenied(pid)))
    with pytest.raises(ValueError,match='cannot_confirm'):prepare(case)


def test_reused_pid_is_allowed_only_with_original_identity_and_different_creation_time(case,monkeypatch):
    proof=p.read(case.diagnosis);proof['original_process_identities']=[dict(pid=n,create_time=10,exe='C:/Python/python.exe') for n in (991001,991002)]
    write(case.diagnosis,proof)
    monkeypatch.setattr(r.psutil,'Process',lambda pid:types.SimpleNamespace(create_time=lambda:20,exe=lambda:'C:/unrelated/python.exe'))
    assert prepare(case).is_dir()


def test_claim_without_new_complete_result_never_replays(case):
    folder=prepare(case);write(folder/'CLAIM.json',dict(fixture=True));reviewer=Reviewer(case)
    with pytest.raises(ValueError,match='already_claimed'):r.execute_recovery(folder,reviewer)
    assert not reviewer.calls


def preflight_proof(c):
    original=p.read(c.style_dir/'REQUEST.json');binding=original['request_binding_sha256']
    write(c.style_dir/'CLAIM.json',dict(at=100,request_binding_sha256=binding))
    write(c.style_dir/'WORKER_LAUNCH.json',dict(mode='windows_venv_direct_base'))
    write(c.style_dir/'WORKER_RUNTIME.json',dict(pid=991001,ppid=991003,actual_executable='C:/Python/python.exe',prefix='fixture-venv',
        request_binding_sha256=binding,model_packages_imported={k:False for k in ('torch','transformers','bitsandbytes')}))
    state=dict(pid=991001,stage='loading',at=101);write(c.style_dir/'WORKER_STATE.json',state)
    observations=[dict(pid=991001,ppid=991003,name='python.exe',created_at=10,status='running',cpu_user=500,cpu_system=0,
        module_basenames=['python.exe','python314.dll','ntdll.dll','_psutil_windows.pyd','_imaging.pyd']),
        dict(pid=991002,ppid=991001,name='nvidia-smi.exe',created_at=11,status='stopped',cpu_user=0,cpu_system=0,
        module_basenames=['nvidia-smi.exe','ntdll.dll'])]
    later=[{k:deepcopy(v) for k,v in q.items() if k not in ('ppid','name')} for q in observations]
    proof=dict(at=800,folder=str(c.style_dir),state=state,worker_log_bytes=0,inference_claims=[],read_errors=[],processes=observations,
        additional_observation_at=980,additional_processes=later,after_timeout_at=1010,
        bound_files={n:r._sha(c.style_dir/n) for n in ('REQUEST.json','CLAIM.json','WORKER_LAUNCH.json','WORKER_RUNTIME.json','WORKER_STATE.json','worker.log')},
        worker_source=dict(path=str(v.PROJECT/'scripts/visual_review_worker_v3.py'),sha256=r._sha(v.PROJECT/'scripts/visual_review_worker_v3.py')),
        exit_processes=[dict(pid=q,error='NoSuchProcess') for q in (991001,991002,991003)],
        files=dict(request_path=str(c.style_dir/'REQUEST.json'),sha256=r._sha(c.style_dir/'REQUEST.json'),worker_state_exists=True,
            worker_runtime_exists=True,worker_log_bytes=0,worker_exit=p.read(c.style_dir/'WORKER_EXIT.json'),worker_error=p.read(c.style_dir/'WORKER_ERROR.json')))
    write(c.diagnosis,proof);return proof


def test_bound_loading_resource_preflight_can_run_one_target_successor(case):
    proof=preflight_proof(case);before=case.diagnosis.read_bytes();folder=prepare(case,'resource_once')
    assert p.read(folder/'PLAN.json')['recovery_phase']=='resource_preflight_unstarted'
    reviewer=Reviewer(case);receipt=r.execute_recovery(folder,reviewer)
    assert receipt['combined_decision']=='accepted' and len(reviewer.calls)==1 and case.diagnosis.read_bytes()==before
    assert p.read(case.run/'STATE.json')['review_history'][case.key]==[case.original]


@pytest.mark.parametrize('defect',[
    'torch_dll','cuda_dll','runtime_imported','not_loading','child_progress','no_near_timeout_sample',
    'different_child_creation','identity_conflict','worker_sha','missing_exit','snapshot_sha','native_claim',
])
def test_preflight_branch_requires_all_specific_no_model_and_exit_evidence(case,defect):
    proof=preflight_proof(case)
    if defect=='torch_dll':proof['additional_processes'][0]['module_basenames'].append('torch_cpu.dll')
    elif defect=='cuda_dll':proof['processes'][0]['module_basenames'].append('nvcuda.dll')
    elif defect=='runtime_imported':
        runtime=p.read(case.style_dir/'WORKER_RUNTIME.json');runtime['model_packages_imported']['torch']=True
        write(case.style_dir/'WORKER_RUNTIME.json',runtime);proof['bound_files']['WORKER_RUNTIME.json']=r._sha(case.style_dir/'WORKER_RUNTIME.json')
    elif defect=='not_loading':
        state=dict(proof['state'],stage='ready');write(case.style_dir/'WORKER_STATE.json',state)
        proof['state']=state;proof['bound_files']['WORKER_STATE.json']=r._sha(case.style_dir/'WORKER_STATE.json')
    elif defect=='child_progress':proof['additional_processes'][1]['cpu_user']=1
    elif defect=='no_near_timeout_sample':proof['additional_observation_at']=800
    elif defect=='different_child_creation':proof['additional_processes'][1]['created_at']=12
    elif defect=='identity_conflict':proof['additional_processes'][1]['ppid']=999
    elif defect=='worker_sha':proof['worker_source']['sha256']='f'*64
    elif defect=='missing_exit':proof['exit_processes'].pop()
    elif defect=='snapshot_sha':proof['bound_files']['WORKER_STATE.json']='f'*64
    else:write(case.style_dir/'item_0000/APPEARANCE_CLAIM.json',dict(fixture=True))
    write(case.diagnosis,proof)
    with pytest.raises(ValueError):prepare(case,'reject_preflight')


def test_resource_preflight_without_real_timeout_is_not_a_recovery_lease(case):
    preflight_proof(case);(case.style_dir/'WORKER_EXIT.json').unlink()
    with pytest.raises(FileNotFoundError):prepare(case,'still_running')


def test_preflight_reused_pid_uses_bound_original_creation_identity(case,monkeypatch):
    preflight_proof(case)
    def process(pid):
        if pid==991003:raise psutil.NoSuchProcess(pid)
        return types.SimpleNamespace(create_time=lambda:30,exe=lambda:'C:/unrelated/program.exe')
    monkeypatch.setattr(r.psutil,'Process',process)
    assert prepare(case,'preflight_reused').is_dir()
