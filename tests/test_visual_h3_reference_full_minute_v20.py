"""Four-part supervisor protocol/CPU clock fixtures, never production media."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import pytest
from src.content_factory import visual_h3_reference_full_minute_v20 as f
REAL_CPU_QA=f._ensure_cpu_qa


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def spans(text):return [dict(start=m.start(),end=m.end(),text=m.group()) for m in re.finditer('“[^”]+”',text)]


@pytest.fixture
def system(tmp_path,monkeypatch):
    run=tmp_path/'h3_reference_full_minute_CPU_fixture';run.mkdir();pause=tmp_path/'old_PAUSE';pause.write_bytes(b'protected old bytes')
    refs=[]
    for kind,who,view in [('character','su','front'),('character','nan','front'),('character','xi','front'),('place','room','front'),('place','room','side')]:
        path=tmp_path/'refs'/(who+'_'+view+'.png');path.parent.mkdir(exist_ok=True);path.write_bytes((who+view).encode())
        refs.append(dict(reference_id=kind+':'+who+':'+view,kind=kind,entity_id=who,view=view,image=f.binding(path)))
    shared=run/'REUSE_MANIFEST.json';write(shared,dict(schema='CPU_fixture_shared_manifest',source='all four use identical reviewed source'))
    segments=[];audit_rows=[];plans={};states={};posts=[];polls=[];qa_calls=[];loads=[]
    for i,sid in enumerate(f.IDS):
        original='原首帧设置。'+sid+'说：“原句'+str(i)+'。”';adapted='按具名参考图。'+sid+'说：“原句'+str(i)+'。”'
        request=run/'original'/(sid+'.json');write(request,dict(content=[dict(type='text',text=original)]))
        old=run/'original'/(sid+'.txt');old.write_bytes(original.encode());draft=run/'drafts'/(sid+'.txt');draft.parent.mkdir(exist_ok=True);draft.write_bytes(adapted.encode())
        source=run/'sources'/(sid+'.prompt.txt');source.parent.mkdir(exist_ok=True);source.write_bytes(adapted.encode())
        row=dict(id=sid,original_request=f.binding(request),original_prompt_file=f.binding(old),original_prompt_utf8_sha256=f._hash_text(original),
            adapted_prompt_file=f.binding(draft),adapted_prompt_utf8_sha256=f._hash_text(adapted),changes=[dict(old='原首帧设置。',new='按具名参考图。',count=1,reason='reference mechanism')],
            original_dialogue_spans=spans(original),adapted_dialogue_spans=spans(adapted),dialogue_texts_equal=True)
        audit_rows.append(row)
        delivery=tmp_path/'visual_h3_ref_v20'/('new_'+sid);folder=delivery/'shots'/sid;folder.mkdir(parents=True)
        bundle=dict(source_shot=dict(visible_cast=['su','nan','xi']),references=deepcopy(refs),bundle_sha256='bundle_'+sid)
        write(folder/'REFERENCE_BUNDLE.json',bundle)
        plan=dict(schema=f.delivery.SCHEMA,reuse_contract='reviewed_donor_assets/v21',reuse_manifest=f.binding(shared),config=dict(width=736,height=1312,video_enabled=True),protected_pause=f.binding(pause),
            shots=[dict(id=sid,timing=dict(native_frames=362,native_seconds=362/24),source_prompt_sha256=f._hash_text(adapted),source_prompt_file=f.binding(source),bundle_sha256='bundle_'+sid)])
        write(delivery/'PLAN.json',plan);plans[str(delivery.resolve())]=plan
        graph=dict(condition=dict(class_type='MiniMaxH3ReferenceToVideo',inputs=dict(width=736,height=1312,
            **{'ref_images.ref_image_'+str(j):['img'+str(j),0] for j in range(5)})),
            **{'127':dict(inputs=dict(unet_name='minimax_h3_ref2va_pruned_int8_convrot.safetensors')),'130':dict(inputs=dict(fps=24))})
        write(folder/'workflow_api.json',graph);(folder/'SOURCE_PROMPT.txt').write_bytes(adapted.encode())
        key=str(delivery.resolve());states[key]=dict(id=sid,status='prepared',prompt_id=None)
        segments.append(dict(id=sid,shot_id=sid,delivery_run=key,source_prompt_file=f.binding(source)))
    audit=run/'AUDIT.json';write(audit,dict(schema='reference_prompt_adaptation/v21',segments=audit_rows))
    approval=run/'APPROVAL.json';write(approval,dict(schema='root_reference_prompt_approval/v21',reviewed_by='root_agent',approved_for_generation=True,audit=f.binding(audit),adapted_prompt_sha256={r['id']:r['adapted_prompt_utf8_sha256'] for r in audit_rows}))
    auth=run/'USER_AUTHORIZATION.json';write(auth,dict(schema='reference_authorization/v21',user_statement='CPU protocol only; no actual service authorized.',max_new_native_submissions=4))

    def load(path,current=False):
        key=str(Path(path).resolve());loads.append((key,current))
        if current:
            for ref in refs:
                if f.binding(ref['image']['path'])!=ref['image']:raise f.MinuteRunError('CPU_fixture_current_donor_asset_changed')
        return Path(key),deepcopy(plans[key])
    def status(path):
        key=str(Path(path).resolve());s=deepcopy(states[key]);return dict(shots=[s],paused=(Path(key)/'PAUSE.json').exists(),video_enabled=plans[key]['config']['video_enabled'])
    def submit(path):
        key=str(Path(path).resolve());s=states[key]
        if s['status']=='prepared':
            # Existing delivery.submit_next owns the final current-source gate.
            f.delivery._load(path,current=True)
            posts.append(key);s.update(status='submitted',prompt_id='protocol_native_'+s['id'])
        return status(path)
    def complete(path):
        key=str(Path(path).resolve());s=states[key];sid=s['id'];s.update(status='technical_saved',prompt_id=s['prompt_id'] or 'protocol_native_'+sid)
        folder=Path(key)/'shots'/sid;artifacts=folder/'artifacts';artifacts.mkdir(exist_ok=True);files={}
        for role,suffix in [('video','.mp4'),('audio','.flac'),('first','.png'),('last','.png')]:
            path=artifacts/(role+suffix);path.write_bytes((sid+' '+role).encode());files[role]=dict(**f.binding(path),source_path=str(tmp_path/'native'/sid/(role+suffix)))
        r=dict(schema=f.delivery.SCHEMA,shot_id=sid,prompt_id=s['prompt_id'],technical_status='technical_saved',source_prompt_sha256=plans[key]['shots'][0]['source_prompt_sha256'],reference_bundle_sha256='bundle_'+sid,files=files)
        write(folder/'RESULT.json',r);return r
    def poll(path):polls.append(str(path));return status(path)
    def fakeqa(run,segment,result):
        folder=run/'segments'/segment['id'];folder.mkdir(parents=True,exist_ok=True);receipt=folder/'CPU_QA_RESULT.json'
        if receipt.exists():return f.native.read(receipt)
        qa_calls.append(segment['id']);q=folder/'OBJECTIVE_QA.json';resultfile=Path(segment['delivery_run'])/'shots'/segment['shot_id']/'RESULT.json'
        write(q,dict(binding=dict(delivery_run=segment['delivery_run'],result_path=str(resultfile),result_sha256=f.native.file_sha(resultfile),source_prompt=segment['source_prompt_file'],prompt_id=result['prompt_id'],video=result['files']['video']),asr_text='CPU fixture'))
        contact=folder/'CONTACT.jpg';contact.write_bytes(b'CPU fixture not a real image')
        value=dict(status='cpu_qa_complete',segment=segment['id'],prompt_id=result['prompt_id'],video_sha256=result['files']['video']['sha256'],manifest=f.binding(q),contact=f.binding(contact),production_approved=False)
        write(receipt,value);return value
    monkeypatch.setattr(f.delivery,'_load',load);monkeypatch.setattr(f.delivery,'status',status);monkeypatch.setattr(f.delivery,'submit_next',submit);monkeypatch.setattr(f.delivery,'poll_collect',poll);monkeypatch.setattr(f,'_ensure_cpu_qa',fakeqa)
    result=dict(run=run,segments=segments,audit=audit,approval=approval,auth=auth,plans=plans,states=states,posts=posts,polls=polls,qa_calls=qa_calls,complete=complete,pause=pause,fakeqa=fakeqa,shared=shared,refs=refs,loads=loads)
    return result


def prepare(s):return f.prepare(s['run'],s['segments'],adaptation_audit=s['audit'],prompt_approval=s['approval'],authorization=s['auth'])


def review(s,index,approved=True):
    run=s['run'];plan=f._load(run)[1];seg=plan['segments'][index];r,_=f._result(seg);cpu=f._ensure_cpu_qa(run,seg,r)
    value=dict(schema='root_reference_segment_review/v20',segment_id=seg['id'],shot_id=seg['shot_id'],prompt_id=r['prompt_id'],
        video={k:r['files']['video'][k] for k in ('path','sha256')},source_prompt_sha256=seg['adapted_prompt_utf8_sha256'],global_references_sha256=plan['global_references_sha256'],
        runner_plan_sha256=f.native.file_sha(run/'RUNNER_PLAN.json'),reviewed_by='root_agent',approved_for_next=approved,
        evidence=dict(contact=cpu['contact'],last={k:r['files']['last'][k] for k in ('path','sha256')},asr=cpu['manifest']))
    write(run/'segments'/seg['id']/'ROOT_SEGMENT_REVIEW.json',value)


def test_prepare_is_cpu_only_accepts_v21_auth_and_copied_adapted_files(system):
    s=system;before=s['pause'].read_bytes();result=prepare(s)
    assert result['technical_saved']==0 and not s['posts'] and not s['polls']
    plan=f._load(s['run'],current=True)[1]
    assert plan['max_submissions']==4 and plan['total_frames']==1448
    assert all(x['source_prompt_file']!=x['audited_adapted_prompt_file'] for x in plan['segments'])
    assert s['pause'].read_bytes()==before and not (s['run']/'PLAN.json').exists()


def test_shared_manifest_optimization_keeps_one_fresh_global_check_and_four_light_graphs(system):
    s=system;prepare(s)
    assert sum(current for _,current in s['loads'])==1
    s['loads'].clear();f._load(s['run'],current=True)
    assert sum(current for _,current in s['loads'])==1
    assert {key for key,_ in s['loads']}=={r['delivery_run'] for r in s['segments']}
    s['loads'].clear();f.tick(s['run'])
    # The one current check belongs to delivery.submit_next, not to redundant
    # per-segment deep validation by the minute supervisor.
    assert [(key,current) for key,current in s['loads'] if current]==[(s['segments'][0]['delivery_run'],True)]
    assert len(s['posts'])==1


def test_prepare_requires_one_exact_shared_reuse_manifest(system):
    s=system;path=Path(s['segments'][3]['delivery_run'])/'PLAN.json';plan=f.native.read(path)
    alternate=s['run']/'S04_different_manifest.json';write(alternate,dict(source='different authority'))
    plan['reuse_manifest']=f.binding(alternate);write(path,plan)
    with pytest.raises(f.MinuteRunError,match='same_reviewed_reuse_manifest'):prepare(s)
    assert not s['posts']


def test_executor_rebind_preserves_and_validates_initial_preparation_audit(system):
    s=system;prepare(s);run=s['run'];p=f.native.read(run/'PREPARATION.json');old=run/'archive'/'PREPARATION.initial.json';write(old,p)
    source=run/'archive'/'executor.initial.py';source.write_bytes(Path(p['executor']['path']).read_bytes())
    xml=run/'CPU_tests.xml';xml.write_text('<testsuite tests="27" failures="0"/>',encoding='utf8')
    p.update(predecessor=dict(preparation=f.binding(old),executor=f.binding(source)),cpu_tests=f.binding(xml))
    write(run/'PREPARATION.json',p)
    assert f._load(run,current=True)[1]['total_frames']==1448
    source.write_bytes(b'changed predecessor source')
    with pytest.raises(f.MinuteRunError,match='bound_file_changed'):f._load(run,current=True)
    assert not s['posts']


@pytest.mark.parametrize('target',['source_copy','audit_adapted','manifest','reference_pixels','last_graph'])
def test_optimized_post_still_rejects_source_manifest_asset_or_other_segment_graph_change(system,target):
    s=system;prepare(s)
    if target=='source_copy':Path(s['segments'][3]['source_prompt_file']['path']).write_bytes(b'changed fourth prompt')
    elif target=='audit_adapted':
        row=f.native.read(s['audit'])['segments'][3];Path(row['adapted_prompt_file']['path']).write_bytes(b'changed audited text')
    elif target=='manifest':s['shared'].write_bytes(b'changed shared authority')
    elif target=='reference_pixels':Path(s['refs'][4]['image']['path']).write_bytes(b'changed room side pixels')
    else:
        path=Path(s['segments'][3]['delivery_run'])/'shots/S04/workflow_api.json';graph=f.native.read(path)
        graph['condition']['inputs']['width']=768;write(path,graph)
    with pytest.raises(f.MinuteRunError):f.tick(s['run'])
    assert not s['posts']


@pytest.mark.parametrize('kind',['v19','short','missing_slot','wrong_model','different_refs'])
def test_incompatible_or_incomplete_reference_segments_cannot_prepare(system,kind):
    s=system;seg=s['segments'][2];path=Path(seg['delivery_run']);plan=s['plans'][str(path)]
    if kind=='v19':plan['schema']='h3_original_prompt_parity/v19'
    elif kind=='short':plan['shots'][0]['timing']=dict(native_frames=209,native_seconds=209/24)
    elif kind=='different_refs':
        b=f.native.read(path/'shots/S03/REFERENCE_BUNDLE.json');b['references'][0]['entity_id']='wrong';write(path/'shots/S03/REFERENCE_BUNDLE.json',b)
    else:
        g=f.native.read(path/'shots/S03/workflow_api.json')
        if kind=='missing_slot':g['condition']['inputs'].pop('ref_images.ref_image_4')
        else:g['127']['inputs']['unet_name']='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
        write(path/'shots/S03/workflow_api.json',g)
    with pytest.raises(f.MinuteRunError):prepare(s)
    assert not s['posts'] and not (s['run']/'RUNNER_PLAN.json').exists()


def test_adaptation_recomputes_dialogue_instead_of_trusting_true_flag(system):
    s=system;a=f.native.read(s['audit']);row=a['segments'][0];file=Path(row['adapted_prompt_file']['path']);text=file.read_text(encoding='utf8').replace('原句0','改句0');file.write_text(text,encoding='utf8')
    row.update(adapted_prompt_file=f.binding(file),adapted_prompt_utf8_sha256=f._hash_text(text),adapted_dialogue_spans=spans(text),dialogue_texts_equal=True);write(s['audit'],a)
    approval=f.native.read(s['approval']);approval.update(audit=f.binding(s['audit']));approval['adapted_prompt_sha256']['S01']=row['adapted_prompt_utf8_sha256'];write(s['approval'],approval)
    with pytest.raises(f.MinuteRunError,match='changed_original_dialogue'):prepare(s)


def test_serial_native_id_resume_waits_for_actual_root_review(system):
    s=system;prepare(s);f.tick(s['run']);assert s['posts']==[s['segments'][0]['delivery_run']]
    # Simulate restart: same native ID is polled, never submitted twice.
    f.tick(s['run']);assert len(s['posts'])==1 and s['polls']
    s['complete'](s['segments'][0]['delivery_run']);state=f.tick(s['run']);assert state['stage']=='waiting_root_review'
    assert (s['run']/'segments/S01/QA_READY.json').exists() and s['qa_calls']==['S01']
    f.tick(s['run']);assert len(s['posts'])==1 and s['qa_calls']==['S01']
    review(s,0);f.tick(s['run']);assert len(s['posts'])==2
    lines=(s['run']/'job_ids.txt').read_text(encoding='utf8').splitlines();assert lines==['S01 protocol_native_S01','S02 protocol_native_S02']


def test_attach_preexisting_saved_S01_never_reposts_and_still_requires_review(system):
    s=system;s['complete'](s['segments'][0]['delivery_run']);prepare(s)
    assert f.tick(s['run'])['stage']=='waiting_root_review' and not s['posts']
    assert (s['run']/'job_ids.txt').read_text(encoding='utf8')=='S01 protocol_native_S01\n'
    review(s,0);f.tick(s['run']);assert s['posts']==[s['segments'][1]['delivery_run']]


def test_single_segment_worker_lock_prevents_total_runner_double_poll(system):
    s=system;prepare(s)
    with f.jobs.run_lock(Path(s['segments'][0]['delivery_run']),'RUNNER.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.tick(s['run'])
    assert not s['posts'] and not s['polls']


def test_CPU_QA_failure_keeps_id_durable_and_retries_only_CPU(system,monkeypatch):
    s=system;prepare(s);s['complete'](s['segments'][0]['delivery_run']);monkeypatch.setattr(f,'_ensure_cpu_qa',REAL_CPU_QA)
    calls=[]
    def failed(command,**kwargs):calls.append(command);return subprocess.CompletedProcess(command,2,stdout='{"error":"CPU QA unavailable"}',stderr='')
    monkeypatch.setattr(f.subprocess,'run',failed)
    with pytest.raises(f.MinuteRunError,match='CPU_QA_failed'):f.tick(s['run'])
    assert 'protocol_native_S01' in (s['run']/'job_ids.txt').read_text(encoding='utf8') and not s['posts']
    plan=f._load(s['run'])[1];seg=plan['segments'][0];r,_=f._result(seg)
    def success(command,**kwargs):
        calls.append(command);payload=s['fakeqa'](s['run'],seg,r)
        return subprocess.CompletedProcess(command,0,stdout=json.dumps(payload),stderr='')
    monkeypatch.setattr(f.subprocess,'run',success)
    value=f.qa(s['run'],'S01');assert value['status']=='cpu_qa_complete' and len(calls)==2 and not s['posts']


def test_unknown_and_root_rejection_never_dispatch_successor(system):
    s=system;prepare(s);f.tick(s['run']);key=s['segments'][0]['delivery_run'];s['states'][key].update(status='outcome_unknown',prompt_id=None)
    assert f.tick(s['run'])['stage']=='blocked_outcome_unknown';assert f.execute(s['run'],max_seconds=1)['stage']=='blocked_outcome_unknown'
    assert len(s['posts'])==1


def test_explicit_bad_root_review_stops_without_semantic_retry(system):
    s=system;prepare(s);f.tick(s['run']);s['complete'](s['segments'][0]['delivery_run']);f.tick(s['run']);review(s,0,False)
    assert f.tick(s['run'])['stage']=='stopped_root_rejected' and len(s['posts'])==1


def test_wait_budget_checked_before_post_and_interrupt_resumes_same_id(system,monkeypatch):
    s=system;prepare(s);ticks=iter([0,2,3,4,5]);monkeypatch.setattr(f.time,'monotonic',lambda:next(ticks))
    result=f.execute(s['run'],max_seconds=1);assert result['stage']=='bounded_wait_ended_original_ids_preserved' and not s['posts']
    monkeypatch.setattr(f.time,'monotonic',lambda:0)
    monkeypatch.setattr(f.time,'sleep',lambda n:(_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):f.execute(s['run'],max_seconds=10)
    assert len(s['posts'])==1 and 'protocol_native_S01' in (s['run']/'job_ids.txt').read_text(encoding='utf8')
    s['complete'](s['segments'][0]['delivery_run']);f.tick(s['run']);assert len(s['posts'])==1


def test_runner_lock_and_old_pause_integrity_are_enforced(system):
    s=system;prepare(s)
    with f.jobs.run_lock(s['run'],'RUNNER.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.tick(s['run'])
    s['pause'].write_bytes(b'changed old pause')
    with pytest.raises(f.MinuteRunError,match='bound_file_changed'):f.tick(s['run'])
    assert not s['posts']


def complete_all(s):
    prepare(s)
    for i in range(4):
        f.tick(s['run']);s['complete'](s['segments'][i]['delivery_run']);f.tick(s['run']);review(s,i)
    assert f.tick(s['run'])['stage']=='all_segments_reviewed'


def final_review(s):
    p=f._load(s['run'])[1];rows=[f._result(x)[0] for x in p['segments']]
    write(s['run']/'ROOT_FINAL_REVIEW.json',dict(schema='root_reference_final_review/v20',reviewed_by='root_agent',approved_for_assembly=True,
        runner_plan_sha256=f.native.file_sha(s['run']/'RUNNER_PLAN.json'),global_references_sha256=p['global_references_sha256'],
        native_ids=[r['prompt_id'] for r in rows],video_sha256=[r['files']['video']['sha256'] for r in rows]))


def test_assembly_refuses_incomplete_or_unreviewed_four_parts(system):
    s=system;prepare(s)
    with pytest.raises(f.MinuteRunError,match='four_saved'):f.assemble(s['run'])


def test_final_gate_and_duplicate_native_output_are_not_bypassed(system):
    s=system;complete_all(s)
    with pytest.raises(f.MinuteRunError,match='final_review'):f.assemble(s['run'])
    seg=s['segments'][3];file=Path(seg['delivery_run'])/'shots/S04/RESULT.json';r=f.native.read(file);r['files']['video']['sha256']=f._result(f._load(s['run'])[1]['segments'][0])[0]['files']['video']['sha256'];write(file,r)
    # The changed video invalidates its earlier root review even before concat.
    with pytest.raises(f.MinuteRunError):f.assemble(s['run'])


def test_assembly_runner_uses_only_four_new_results_and_is_idempotent(system,monkeypatch):
    s=system;complete_all(s);final_review(s)
    calls=[]
    monkeypatch.setattr(f.clock,'_scope',lambda *args:pytest.fail('Old parity namespace forbidden'))
    monkeypatch.setattr(f,'_clock_input',lambda path,sha:dict(decoded_48k_samples=724000,target_samples=724000,trim_tail_samples=0,pad_tail_samples=0))
    def encode(command,**kwargs):
        calls.append(command);Path(command[-1]).write_bytes(b'CPU protocol final, not actual movie')
        return subprocess.CompletedProcess(command,0,stdout='',stderr='')
    monkeypatch.setattr(f.subprocess,'run',encode)
    metadata=dict(streams=[dict(codec_type='video',width=736,height=1312,nb_frames='1448',nb_read_frames='1448',r_frame_rate='24/1',avg_frame_rate='24/1',start_time='0',duration_ts=1448,time_base='1/24'),
        dict(codec_type='audio',sample_rate='48000',channels=2,start_time='0',duration_ts=2896000,time_base='1/48000')],format=dict(duration='60.333333'))
    monkeypatch.setattr(f,'_probe',lambda path:deepcopy(metadata))
    result=f.assemble(s['run']);assert result['clock']['audio_samples']==2896000 and len(result['native_ids'])==4
    assert f.assemble(s['run'])==result and len(calls)==1
    Path(result['file']['path']).write_bytes(b'changed')
    with pytest.raises(f.MinuteRunError,match='bound_file_changed'):f.assemble(s['run'])


def test_real_cpu_concat_helper_has_exact_1448_frame_and_sample_clock(tmp_path,monkeypatch):
    # Small CPU-encoded fixtures, not actual H3 or 736p content acceptance.
    monkeypatch.setattr(f.clock,'_scope',lambda *args:pytest.fail('Old parity run must never be accessed'))
    paths=[]
    for i,color in enumerate(['red','green','blue','yellow']):
        file=tmp_path/(str(i)+'.mp4');subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c='+color+':s=64x80:r=24',
            '-f','lavfi','-i','sine=frequency='+str(400+i*100)+':sample_rate=32000','-frames:v','362','-t',str(362/24),'-c:v','libx264','-preset','ultrafast','-threads','1','-c:a','aac',str(file)],check=True,capture_output=True,timeout=60);paths.append(file)
    filters=tmp_path/'filter.txt';output=tmp_path/'minute.mp4';command,text=f.clock.assembly_command(paths,filters,output,frames=362,preset='ultrafast');filters.write_text(text,encoding='utf8')
    subprocess.run(command,check=True,capture_output=True,timeout=90)
    evidence=f.clock.verify_clock(f._probe(output),frames=1448,width=64,height=80)
    assert evidence['audio_samples']==2896000 and evidence['native_frames']==1448 and evidence['seconds']==1448/24
