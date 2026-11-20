"""Precise service-exit recovery CPU tests; all POSTs use a stub service."""
from pathlib import Path
from datetime import datetime,timezone
from copy import deepcopy
import importlib.util
import json
import pytest

from src.content_factory import visual_h3_continuity_minute_v34 as f
from src.content_factory import visual_h3_service_exit_image_successor_v35 as r

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return f.bind(path)
def module():
    path=Path(__file__).with_name('test_visual_h3_continuity_minute_v34.py');spec=importlib.util.spec_from_file_location('v35_v34_fixture',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.fixture
def case(tmp_path,monkeypatch):
    m=module();run,spec,_=m.prepared.__wrapped__(tmp_path,monkeypatch);service=m.Service(monkeypatch);prior=service.request
    def request(cfg,route,value=None):
        if route.startswith('/history/'):
            pid=route.rsplit('/',1)[1];return {pid:service.histories[pid]} if pid in service.histories else {}
        return prior(cfg,route,value)
    monkeypatch.setattr(f.native,'_http',request);monkeypatch.setattr(f.jobs,'_http',request)
    m.source_review(run,'S01');f.prepare_anchor(run,'S01');m.launch(run);m.approve(run,'S01','image');f.tick(run,allow_submit=True)
    job=f._image_job(run,'S01');p=f.read(job/'PLAN.json');claim=f.read(job/'CLAIM.json');pid=f.read(job/'RESPONSE.json')['prompt_id'];at=claim['at']
    home=tmp_path/'service_guard';monkeypatch.setattr(r,'SERVICE_HOME',home);attempt=home/'attempts'/('a'*32)
    command=['python.exe','-B','main.py','--port','8190','--offline','--input-directory',p['config']['input_root'],'--output-directory',p['config']['output_root']]
    process=write(attempt/'PROCESS.json',dict(pid=999991,create_time=at-60,command=command));ex=write(attempt/'EXIT.json',dict(at=datetime.fromtimestamp(at+1,timezone.utc).isoformat(),pid=999991,create_time=at-60,returncode=3))
    write(attempt/'CLAIM.json',dict(epoch=at-61,source_command=command,observation=dict(families=[],port='closed',action='launch')))
    log=attempt/'server.stderr.log';log.write_text('[INFO] got prompt\nRequested to load AutoencoderKL\nFatal Python error: Aborted\nrestore_loaded_backups\npartially_unload\nin encode\n',encoding='utf-8')
    monkeypatch.setattr(r,'_now',lambda:at+60)
    audit=write(tmp_path/'audit.json',dict(schema='service_exit_image_readonly_audit/v35',sampled_at=datetime.fromtimestamp(at+2,timezone.utc).isoformat(),
        original_native_id=pid,source_job=str(job),current_service=dict(history={},queue=dict(queue_running=[],queue_pending=[])),
        local_process_exit=dict(eligible_generation_at_post=[dict(process=process,exit=ex)],old_family=[dict(pid=999991,original_create_time=at-60)],prior_open_interval_excluded_by_later_proven_absence=[])))
    original=[f.bind(job/n) for n in ('PLAN.json','workflow_api.json','REQUEST.json','CLAIM.json','RESPONSE.json','STATE.json')]
    request=r.disposition_request(run,'S01',attempt,audit);request.update(approved_for_successor=True,reviewed_by='CPU protocol root',evidence=['Controlled process-exit receipt and no-output scope, not a model result.'])
    approval=write(run/'segments/S01/ROOT_SERVICE_EXIT_DISPOSITION.json',request)
    write(run/r.OPT,dict(schema='h3_service_exit_image_recovery_opt_in/v35',minute_plan=f.bind(run/'PLAN.json'),dispositions={'S01':approval}))
    launch_revision(run)
    # Explicit CPU preparation freezes the collection-only original protection
    # marker. A current approval is never used as a collection decision.
    r.prepare_successor(run,'S01')
    return dict(m=m,run=run,service=service,original=original,job=job,pid=pid,attempt=attempt,audit=audit,monkeypatch=monkeypatch)

def launch_revision(run):
    value=f.read(run/'ROOT_LAUNCH_APPROVAL.json');value['execution_sources']=f._sources()
    value['execution_sources'].update(service_exit_image_recovery=f.bind(r.__file__),service_exit_image_recovery_cli=f.bind(f.PROJECT/'scripts/run_h3_service_exit_image_successor_v35.py'))
    value['service_exit_recovery_opt_in']=f.bind(run/r.OPT);write(run/'ROOT_LAUNCH_APPROVAL_REVISION_V35.json',value)

def rebind(case,mutate):
    run=case['run'];path=run/'segments/S01/ROOT_SERVICE_EXIT_DISPOSITION.json';value=f.read(path);mutate(value)
    b=write(path,value);opt=f.read(run/r.OPT);opt['dispositions']['S01']=b;write(run/r.OPT,opt);launch_revision(run)

def approve_successor(case):
    run=case['run'];value=r.image_approval_request(run,'S01');value.update(approved_for_dispatch=True,reviewed_by='CPU protocol root',evidence=['Actual prepared successor fixture.'])
    write(run/'segments/S01/ROOT_SERVICE_EXIT_IMAGE_APPROVAL.json',value)

def finish_successor(case):
    run=case['run'];service=case['service'];job=r.successor_job(run,'S01');p=f.read(job/'PLAN.json');g=f.read(job/'workflow_api.json');pid=f.read(job/'RESPONSE.json')['prompt_id'];outputs={}
    from PIL import Image
    for nid,node in g.items():
        if node['class_type']=='SaveImage':
            rel=Path(node['inputs']['filename_prefix']+'_00001_.png');path=Path(p['config']['output_root'])/rel;path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(736,1312),'blue').save(path)
            outputs[nid]=dict(images=[dict(filename=path.name,subfolder=rel.parent.as_posix(),type='output')])
    service.histories[pid]=dict(prompt=[0,pid,g],status=dict(completed=True,status_str='success'),outputs=outputs)
    f.collect_known(run);candidate=r._candidate(run,'S01');report=f.prepare_context_entry(run,'S01');entry=f.core._entries(report['context_spec'])[0];keys=entry['canonical_characters']
    write(run/'segments/S01/SERVICE_EXIT_ANCHOR_REVIEW.json',dict(schema=f.core.REVIEW,reviewed_by='CPU protocol root',target_image=candidate['image'],canonical_characters=keys,
        canonical_room=entry['canonical_room'],completion_known=True,outcome_unknown=False,work_order_sha256=report['work_order_sha256'],source_current_state_matches=True,
        checks=dict(topology_coherent=True,room_identity=True,faces={k:True for k in keys},identities={k:True for k in keys}),evidence=['Accepted fixture only; not production quality.']))
    return candidate

def test_specific_exit_keeps_raw_unknown_claim_and_original_bytes(case):
    run=case['run'];value=r.verify(run,'S01',live=True);assert value['raw_provider_outcome']=='unknown_after_service_exit'
    assert f.budget(run)['image_claimed']==1 and f.budget(run)['image_unknown_claims_raw']==1 and f.budget(run)['image_unknown_claims']==0
    f.collect_known(run);assert [f.bind(x['path']) for x in case['original']]==case['original']
    assert not (case['job']/'HISTORY.json').exists() and not (case['job']/'RESULT.json').exists()

def test_root_successor_gate_then_real_stub_saved_receipt_enters_i2v(case):
    run=case['run'];assert f.tick(run,allow_submit=True)['dispatch']=='root_service_exit_image_approval_required';assert len(case['service'].posts)==1
    approve_successor(case);f.tick(run,allow_submit=True);assert len(case['service'].posts)==2
    f.tick(run,allow_submit=True);assert len(case['service'].posts)==2
    candidate=finish_successor(case);assert f.prepare_video(run,'S01')['status']=='video_prepared'
    assert f.read(run/'segments/S01/VIDEO_BINDING.json')['selected_first']==candidate['image']
    assert f.budget(run)['image_claimed']==2 and not (case['job']/'RESULT.json').exists()
    assert [f.bind(x['path']) for x in case['original']]==case['original']
    case['m'].approve(run,'S01','video');f.tick(run,allow_submit=True);assert len(case['service'].posts)==3
    assert f._video_local(run,'S01')['status']=='submitted'

@pytest.mark.parametrize('mutation',[
    lambda v:v.update(original_native_id='foreign'),lambda v:v.update(approved_for_successor=False),
    lambda v:v.update(max_new_image_successors=2),lambda v:v.update(count_original_submission=False),
    lambda v:v.update(native_provider_outcome='saved'),lambda v:v.update(segment='S02'),
    lambda v:v.update(original_job=str(Path(v['original_job']).parents[2]/'video_unknown')),
    lambda v:v.update(ownership_evidence_is_retrospective=False),lambda v:v.update(evidence=[]),
])
def test_no_generic_unknown_or_video_waiver(case,mutation):
    rebind(case,mutation)
    with pytest.raises((ValueError,KeyError)):r.verify(case['run'],'S01')
    assert len(case['service'].posts)==1

@pytest.mark.parametrize('file',['RESULT.json','HISTORY.json'])
def test_any_original_native_receipt_prevents_empty_output_recovery(case,file):
    write(case['job']/file,{})
    with pytest.raises(ValueError):r.verify(case['run'],'S01')

def test_partial_output_not_coerced_to_zero(case):
    p=f.read(case['job']/'PLAN.json');where=Path(p['config']['output_root'])/p['config']['allowed_prefix']/p['job_id'];where.mkdir(parents=True);(where/'partial.tmp').write_bytes(b'')
    with pytest.raises(ValueError,match='partial_or_complete'):r.verify(case['run'],'S01')

def test_alive_old_identity_not_waived(case,monkeypatch):
    monkeypatch.setattr(r,'_alive',lambda pid,created:True)
    with pytest.raises(ValueError,match='still_alive'):r.verify(case['run'],'S01')

def test_authoritative_exit_pid_and_creation_must_match(case):
    def mutation(v):
        p=Path(v['service']['exit']['path']);x=f.read(p);x['pid']+=1;v['service']['exit']=write(p,x)
    rebind(case,mutation)
    with pytest.raises(ValueError,match='matching_service_process_exit'):r.verify(case['run'],'S01')

def test_original_id_reappearing_in_history_stops_new_dispatch(case):
    case['service'].histories[case['pid']]=dict(status=dict(completed=False))
    with pytest.raises(ValueError,match='reappeared'):r.verify(case['run'],'S01',live=True)
    assert len(case['service'].posts)==1

def test_sampler_progress_cannot_be_classified_pre_sampling(case):
    def mutation(v):
        p=Path(v['service']['stderr']['path']);p.write_text(p.read_text()+'\n50%|progress\n');v['service']['stderr']=f.bind(p)
    rebind(case,mutation)
    with pytest.raises(ValueError,match='pre_sampling'):r.verify(case['run'],'S01')

def test_unknown_successor_not_retried_or_disposed_by_old_sidecar(case):
    run=case['run'];r.prepare_successor(run,'S01');approve_successor(case);case['service'].drop=True
    f.tick(run,allow_submit=True);assert len(case['service'].posts)==2
    assert f.tick(run,allow_submit=True)['dispatch']=='native_terminal_or_unknown_preserved'
    assert len(case['service'].posts)==2 and f.budget(run)['image_unknown_claims']==1
    assert r.prepare_successor(run,'S01')['status']=='outcome_unknown' and len(case['service'].posts)==2

def test_original_launch_preserved_and_revision_required(case):
    run=case['run'];before=f.bind(run/'ROOT_LAUNCH_APPROVAL.json');(run/'ROOT_LAUNCH_APPROVAL_REVISION_V35.json').unlink()
    with pytest.raises(OSError):f.tick(run,allow_submit=True)
    assert before==f.bind(run/'ROOT_LAUNCH_APPROVAL.json') and len(case['service'].posts)==1

@pytest.mark.parametrize('fault',[None,'prior_launch','source','cpu_acceptance'])
def test_new_r3_launch_strictly_binds_prior_and_does_not_replace_old_approval(case,fault):
    run=case['run'];old=run/'ROOT_LAUNCH_APPROVAL_REVISION_V35.json';old_binding=f.bind(old);before=f.read(old)
    assert f._launch(run,f.read(run/'PLAN.json'))==before
    value=deepcopy(before);value['prior_launch']=old_binding
    if fault=='prior_launch':value['prior_launch']=dict(old_binding,sha256='0'*64)
    elif fault=='source':value['execution_sources']['coordinator']['sha256']='0'*64
    elif fault=='cpu_acceptance':value['cpu_acceptance']['sha256']='0'*64
    write(run/'ROOT_LAUNCH_APPROVAL_REVISION_V35_R3.json',value)
    if fault:
        with pytest.raises(ValueError):f._launch(run,f.read(run/'PLAN.json'))
    else:assert f._launch(run,f.read(run/'PLAN.json'))==value
    assert f.bind(old)==old_binding and len(case['service'].posts)==1

def test_native_video_unknown_still_hard_stops_even_for_disposed_image_segment(case):
    run=case['run'];r.prepare_successor(run,'S01');approve_successor(case);f.tick(run,allow_submit=True);finish_successor(case)
    f.prepare_video(run,'S01');case['m'].approve(run,'S01','video');f.tick(run,allow_submit=True)
    assert len(case['service'].posts)==3
    result=f.tick(run,allow_submit=True);assert result['dispatch']=='native_terminal_or_unknown_preserved'
    assert f._video_local(run,'S01')['status']=='outcome_unknown'
    f.tick(run,allow_submit=True);assert len(case['service'].posts)==3 and f.budget(run)['video_claimed']==1

def test_unrelated_image_unknown_not_covered_by_precise_disposition(case):
    run=case['run'];r.prepare_successor(run,'S01');approve_successor(case);plan=f.read(run/'PLAN.json');spec=f.read(run/'MINUTE_SPEC.json');s=spec['spatial']
    other=run/'stills'/'unrelated_unknown'
    f.core.prepare_reanchor(f.bind(run/'segments/S01/CONTEXT_SPEC.json'),'S01',other,handoff=f.check(s['handoff']),render_result=f.check(s['render_result']),
        inputs=f.check(s['inputs']),authorization=f.check(plan['image_authorization']),config=f.check(s['config']),item_id=spec['stage_items']['S01'],source_binding_review=f.bind(run/'segments/S01/SOURCE_STATE_REVIEW.json'))
    write(other/'batches/reanchor_S01/CLAIM.json',dict(unresolved=True))
    assert f.budget(run)['image_unknown_claims']==1
    assert f.tick(run,allow_submit=True)['dispatch']=='native_terminal_or_unknown_preserved' and len(case['service'].posts)==1

def test_raw_ansi_fatal_log_is_authority_not_audit_summary_flags(case):
    def mutation(v):
        p=Path(v['service']['stderr']['path']);p.write_text(p.read_text().replace('[INFO] got prompt','\x1b[32m[INFO]\x1b[0m got prompt'))
        v['service']['stderr']=f.bind(p)
        audit=f.core.read(v['readonly_audit']);audit['last_prompt_observed']=dict(fatal_python_aborted=False,dynamic_restore=False,wddm_warning=False)
        v['readonly_audit']=write(v['readonly_audit']['path'],audit)
    rebind(case,mutation)
    assert r.verify(case['run'],'S01')['raw_provider_outcome']=='unknown_after_service_exit'

@pytest.mark.parametrize('scope',['root','parent','namespace','job','artifacts'])
def test_inventory_permission_error_is_never_zero_outputs(case,monkeypatch,scope):
    job=case['job'];p=f.read(job/'PLAN.json');root=Path(p['config']['output_root'])
    namespace=root/p['config']['allowed_prefix']/f.jobs._slug(p['job_id'])
    namespace.mkdir(parents=True,exist_ok=True);artifacts=job/'artifacts';artifacts.mkdir()
    target={'root':root,'parent':namespace.parent,'namespace':namespace,'job':job,'artifacts':artifacts}[scope]
    real=r.os.scandir
    def deny(path):
        if Path(path)==target:raise PermissionError('Controlled unreadable '+scope)
        return real(path)
    monkeypatch.setattr(r.os,'scandir',deny)
    with pytest.raises(ValueError,match='inventory_unavailable'):r._inventory(job,p)

def test_inventory_absence_requires_readable_exact_parent(case,monkeypatch):
    job=case['job'];p=f.read(job/'PLAN.json');root=Path(p['config']['output_root']);seen=[];real=r.os.scandir
    def record(path):seen.append(Path(path));return real(path)
    monkeypatch.setattr(r.os,'scandir',record)
    namespace=r._inventory(job,p)
    assert root in seen and job in seen and not namespace.exists()

def test_inventory_reparse_entry_is_rejected_without_following(case,monkeypatch):
    job=case['job'];p=f.read(job/'PLAN.json');root=Path(p['config']['output_root'])
    namespace=root/p['config']['allowed_prefix']/f.jobs._slug(p['job_id']);namespace.mkdir(parents=True,exist_ok=True)
    real=r._entry_mode
    def as_link(entry):
        if Path(entry.path)==namespace:raise r.ServiceExitError('original_output_reparse_point_not_followed')
        return real(entry)
    monkeypatch.setattr(r,'_entry_mode',as_link)
    with pytest.raises(ValueError,match='reparse_point_not_followed'):r._inventory(job,p)

def test_entry_stat_error_and_reparse_attribute_are_rejected():
    from types import SimpleNamespace
    class Denied:
        path='controlled';
        def stat(self,**kwargs):raise PermissionError('controlled')
    with pytest.raises(ValueError,match='entry_unavailable'):r._entry_mode(Denied())
    class Reparse:
        path='controlled'
        def stat(self,**kwargs):
            assert kwargs=={'follow_symlinks':False}
            return SimpleNamespace(st_mode=r.stat.S_IFDIR,st_file_attributes=1024)
    with pytest.raises(ValueError,match='reparse_point_not_followed'):r._entry_mode(Reparse())

@pytest.fixture(scope='module')
def cpu_av(tmp_path_factory):return module().media.__wrapped__(tmp_path_factory)

def submitted_video(case):
    run=case['run'];approve_successor(case);f.tick(run,allow_submit=True);finish_successor(case)
    f.prepare_video(run,'S01');case['m'].approve(run,'S01','video');f.tick(run,allow_submit=True)
    assert f._video_local(run,'S01')['status']=='submitted' and len(case['service'].posts)==3

@pytest.mark.parametrize('changed',['opt_in','disposition','removed_opt_in','removed_disposition'])
def test_changed_approval_still_collects_known_video_without_original_poll_or_new_post(case,cpu_av,monkeypatch,changed):
    submitted_video(case);run=case['run'];case['service'].finish_video(run,'S01',cpu_av)
    path=run/r.OPT if changed.endswith('opt_in') else run/'segments/S01/ROOT_SERVICE_EXIT_DISPOSITION.json'
    if changed.startswith('removed_'):path.unlink()
    else:path.write_text('{deliberately invalid current approval',encoding='utf-8')
    def forbidden(*args,**kwargs):raise AssertionError('Current opt-in must not decide collection')
    monkeypatch.setattr(r,'configured',forbidden);polls=[];real=f.native.poll_collect;image_poll=f.jobs.poll
    def video_poll(path):polls.append(Path(path));return real(path)
    def guarded_image_poll(path):
        assert Path(path)!=case['job'],'Original submitted image must remain byte-identical'
        return image_poll(path)
    monkeypatch.setattr(f.native,'poll_collect',video_poll);monkeypatch.setattr(f.jobs,'poll',guarded_image_poll)
    result=f.collect_known(run)
    assert result['technical_saved']==1 and polls==[f._video_run(run,'S01')]
    actual=f.read(f._video_run(run,'S01')/'shots/S01/RESULT.json')
    assert actual['technical_status']=='technical_saved' and set(actual['files'])=={'video','audio','first','last'}
    assert all(f.check({key:binding[key] for key in ('path','sha256')}).is_file() for binding in actual['files'].values())
    blocked=f.tick(run,allow_submit=True)
    assert blocked['status']=='blocked_current_inputs' and len(case['service'].posts)==3
    assert f.read(run/'INPUT_INVALID.json')['new_dispatch_blocked'] is True
    assert [f.bind(x['path']) for x in case['original']]==case['original']

@pytest.mark.parametrize('marker_failure',['missing','unreadable','changed'])
def test_bad_local_marker_blocks_new_dispatch_but_collects_known_video_and_never_polls_original(case,cpu_av,monkeypatch,marker_failure):
    submitted_video(case);run=case['run'];case['service'].finish_video(run,'S01',cpu_av);marker=r._protection_path(run,'S01')
    if marker_failure=='missing':marker.unlink()
    elif marker_failure=='changed':write(marker,dict(schema='tampered'))
    else:
        real=f.read
        def deny(path):
            if Path(path)==marker:raise PermissionError('Controlled marker failure')
            return real(path)
        monkeypatch.setattr(f,'read',deny)
    image_poll=f.jobs.poll
    def guarded_image_poll(path):
        assert Path(path)!=case['job'],'Missing/unreadable marker cannot fall back to original poll'
        return image_poll(path)
    monkeypatch.setattr(f.jobs,'poll',guarded_image_poll)
    result=f.collect_known(run)
    assert result['technical_saved']==1 and result['collection_input_errors'][0]['preserve_original'] is True
    assert f.tick(run,allow_submit=True)['dispatch']=='blocked_collection_configuration'
    assert len(case['service'].posts)==3 and [f.bind(x['path']) for x in case['original']]==case['original']
    assert f.read(run/'COLLECTION_INPUT_INVALID.json')['new_dispatch_blocked'] is True
