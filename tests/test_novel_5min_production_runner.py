"""CPU control tests for the one production executor; no native media calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

PATH=Path(__file__).resolve().parents[1]/'data/video_generation/novel_5min_20261106_v1/run_production.py'
spec=importlib.util.spec_from_file_location('novel_5min_executor_cpu',PATH)
run=importlib.util.module_from_spec(spec);spec.loader.exec_module(run)


def write(path,value):run.assets.write(path,value)


def plan_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(run,'PROJECT',tmp_path);monkeypatch.setattr(run,'ROOT',tmp_path)
    source=tmp_path/'source.md';source.write_text('Frozen QA source.',encoding='utf-8')
    binding=dict(path=str(source),sha256=run.assets.file_sha(source));shots=[]
    for n in range(1,28):
        sid=f'F{n:04d}';shots.append(dict(id=sid,source_native_frames=270 if n<27 else 272,packet=str(tmp_path/(sid+'.json')),packet_sha256='QA',
            asset_run=str(tmp_path/'data/visual_asset_pipeline/runs'/sid),h3_run=str(tmp_path/'data/video_generation/visual_h3_v3'/sid)))
    parent=tmp_path/'parent.json';write(parent,dict(source=binding,shots=[dict(id=r['id'],source_native_frames=r['source_native_frames']) for r in shots]))
    plan=dict(schema='novel_5min_production/v1',parent=dict(path=str(parent),sha256=run.assets.file_sha(parent)),source=binding,
        publication=False,old_batch_resume=False,width=736,height=1312,fps=24,shots=shots,source_frame_total=7292,source_seconds=7292/24)
    write(tmp_path/'PRODUCTION_PLAN.json',plan);monkeypatch.setattr(run.staging,'validate_packet',lambda _:True)
    monkeypatch.setattr(run.h3,'_timing',lambda s:dict(native_frames=s['source_native_frames']))
    return plan


def silence(monkeypatch):
    monkeypatch.setattr(run,'progress',lambda *a,**k:None);monkeypatch.setattr(run,'sync_native_ids',lambda *a:None);monkeypatch.setattr(run.time,'sleep',lambda _:None)


def test_plan_rejects_duplicate_ids_paths_or_clock(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);assert run.load_plan()==plan
    for key in ('id','asset_run','h3_run'):
        bad=deepcopy(plan);bad['shots'][1][key]=bad['shots'][0][key];write(tmp_path/'PRODUCTION_PLAN.json',bad)
        with pytest.raises(run.Blocked):run.load_plan()
    bad=deepcopy(plan);bad['source_seconds']=300;write(tmp_path/'PRODUCTION_PLAN.json',bad)
    with pytest.raises(run.Blocked,match='timeline'):run.load_plan()


def test_all_streams_frame_then_video_and_stops_before_unreviewed_second(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);events=[]
    monkeypatch.setattr(run,'frame',lambda row:events.append(('frame',row['id'])))
    monkeypatch.setattr(run,'video',lambda row:events.append(('video',row['id'])))
    with pytest.raises(run.Blocked,match='first_sample_native_video_required'):run.execute_rows(plan,plan['shots'],'all')
    assert events==[('frame','F0001'),('video','F0001')]
    monkeypatch.setattr(run,'require_first_sample_review',lambda _:None);events.clear();run.execute_rows(plan,plan['shots'][:2],'all')
    assert events==[('frame','F0001'),('video','F0001'),('frame','F0002'),('video','F0002')]


@pytest.mark.parametrize('phase',['poll','submit','saved'])
def test_video_unknown_stops_without_repost_and_saved_resume_never_posts(tmp_path,monkeypatch,phase):
    plan=plan_fixture(tmp_path,monkeypatch);silence(monkeypatch);row=plan['shots'][0];folder=Path(row['h3_run']);folder.mkdir(parents=True)
    write(folder/'PLAN.json',dict(asset_run=str(Path(row['asset_run']).resolve()),config=dict(video_enabled=True),shots=[dict(id=row['id'])]))
    monkeypatch.setattr(run.h3,'poll_collect',lambda _:dict(status={'poll':'outcome_unknown','saved':'media_review_required','submit':'prepared'}[phase]))
    calls=[];monkeypatch.setattr(run.h3,'submit_next',lambda _:(calls.append('POST') or dict(status='outcome_unknown')))
    if phase=='saved':run.video(row)
    else:
        with pytest.raises(run.Blocked,match='video_halted'):run.video(row)
    assert calls==(['POST'] if phase=='submit' else [])


def test_frame_accepts_existing_pipeline_repair_states_and_keeps_worker_exit(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);silence(monkeypatch);row=plan['shots'][0];packet=dict(qa=True);write(row['packet'],packet);row['packet_sha256']=run.assets.file_sha(row['packet'])
    folder=Path(row['asset_run']);folder.mkdir(parents=True);write(folder/'PLAN.json',dict())
    static=tmp_path/'static.json';write(static,{})
    row.update(first_frame_contract=run.stills.CONTRACT,first_frame_plan=dict(path=str(static),sha256=run.assets.file_sha(static)))
    snapshot=dict(plan=dict(packet=packet,config=dict(visual_review={},first_frame_contract=run.stills.CONTRACT,first_frame_plan=row['first_frame_plan'])),paused=False,state=dict(status='prepared'))
    monkeypatch.setattr(run.assets,'status',lambda _:snapshot);monkeypatch.setattr(run.vision,'VisualReviewClient',lambda _:object())
    states=iter(['first_frame_repairing','first_frame_review_pending','h3_inputs_ready']);monkeypatch.setattr(run.assets,'tick',lambda *a,**k:dict(status=next(states)))
    monkeypatch.setattr(run,'begin_worker',lambda *a:dict(id='worker'));exits=[];monkeypatch.setattr(run,'end_worker',lambda *a:exits.append(a[2]))
    run.frame(row);assert exits==['h3_inputs_ready']


def frame_review_fixture(tmp_path,monkeypatch,*,max_attempts=2):
    """Executor/pipeline boundary only: no visual model or native image request."""
    plan=plan_fixture(tmp_path,monkeypatch);silence(monkeypatch);row=plan['shots'][0]
    packet=dict(qa=True);write(row['packet'],packet);row['packet_sha256']=run.assets.file_sha(row['packet'])
    folder=Path(row['asset_run']);folder.mkdir(parents=True);write(folder/'PLAN.json',{})
    static=tmp_path/'static.json';write(static,{})
    row.update(first_frame_contract=run.stills.CONTRACT,first_frame_plan=dict(path=str(static),sha256=run.assets.file_sha(static)))
    image=folder/'ORIGINAL_COLLECTED_IMAGE.fixture';image.write_bytes(b'CPU integration fixture; not an actual generated PNG')
    sha=run.assets.file_sha(image)
    config=dict(visual_review={},max_review_attempts=max_attempts,first_frame_contract=run.stills.CONTRACT,first_frame_plan=row['first_frame_plan'])
    snapshot=dict(plan=dict(packet=packet,config=config),paused=False,state=dict(status='blocked_first_frame_review'))
    monkeypatch.setattr(run.assets,'status',lambda _:snapshot)
    monkeypatch.setattr(run.vision,'VisualReviewClient',lambda _:object())
    monkeypatch.setattr(run,'begin_worker',lambda *a:dict(id='CPU_fixture_worker'))
    exits=[];monkeypatch.setattr(run,'end_worker',lambda *args:exits.append(args[2]))
    monkeypatch.setattr(run.assets,'prepare',lambda *a,**k:pytest.fail('must not create another image plan'))
    monkeypatch.setattr(run.assets.images,'submit',lambda *a,**k:pytest.fail('executor must not POST a replacement image'))
    state=dict(status='blocked_first_frame_review',jobs=dict(original_image_job=dict(status='collected',kind='first_frame',shot_id=row['id'])),
        first_frames={row['id']:dict(path=str(image),sha256=sha,job_id='original_image_job',review_attempts=1,
            review=dict(decision='unavailable',retryable=True,completion_known=True,outcome_unknown=False))})
    return row,state,image,exits


def test_known_retryable_frame_review_reaches_second_tick_on_same_collected_png(tmp_path,monkeypatch):
    row,state,image,exits=frame_review_fixture(tmp_path,monkeypatch);before=image.read_bytes();calls=[]
    state['first_frames'][row['id']]['review']['subreviews']=[dict(decision='unavailable',retryable=True,completion_known=True,
        outcome_unknown=False,error='room structured output missing required field')]
    ready=deepcopy(state);ready['status']='h3_inputs_ready';ready['first_frames'][row['id']]['review_attempts']=2
    ready['first_frames'][row['id']]['review']['decision']='accepted'
    def tick(folder,**kwargs):
        calls.append(Path(folder));return deepcopy(state if len(calls)==1 else ready)
    monkeypatch.setattr(run.assets,'tick',tick)
    run.frame(row)
    assert calls==[Path(row['asset_run'])]*2 and exits==['h3_inputs_ready']
    assert image.read_bytes()==before and state['first_frames'][row['id']]['job_id']=='original_image_job'


def test_second_known_review_failure_stops_at_original_attempt_limit(tmp_path,monkeypatch):
    row,state,image,exits=frame_review_fixture(tmp_path,monkeypatch);calls=[]
    def tick(*args,**kwargs):
        calls.append(True);result=deepcopy(state);result['first_frames'][row['id']]['review_attempts']=len(calls);return result
    monkeypatch.setattr(run.assets,'tick',tick)
    with pytest.raises(run.Blocked,match='first_frame_halted:blocked_first_frame_review'):run.frame(row)
    assert len(calls)==2 and exits==['failed']


@pytest.mark.parametrize('change,max_attempts',[
    (dict(completion_known=False,outcome_unknown=True),2),
    (dict(outcome_unknown=True),2),
    (dict(completion_known=None),2),
    (dict(retryable=False),2),
    (dict(decision='needs_review'),2),
    (dict(decision='repair_required'),2),
    (dict(attempts=2),2),
    ({},1),
])
def test_other_frame_review_stops_without_loop_or_budget_extension(change,max_attempts,tmp_path,monkeypatch):
    row,state,image,exits=frame_review_fixture(tmp_path,monkeypatch,max_attempts=max_attempts)
    change=deepcopy(change);attempts=change.pop('attempts',1)
    state['first_frames'][row['id']]['review_attempts']=attempts
    state['first_frames'][row['id']]['review'].update(change)
    calls=[]
    def tick(*args,**kwargs):calls.append(True);assert len(calls)==1;return deepcopy(state)
    monkeypatch.setattr(run.assets,'tick',tick)
    with pytest.raises(run.Blocked,match='first_frame_halted:blocked_first_frame_review'):run.frame(row)
    assert len(calls)==1 and exits==['failed']


def test_restart_cannot_fall_back_to_old_dynamic_firstframe_generation(tmp_path,monkeypatch):
    row=plan_fixture(tmp_path,monkeypatch)['shots'][0]
    monkeypatch.setattr(run.assets,'prepare',lambda *a:pytest.fail('must not generate from old dynamic prompt'))
    with pytest.raises(run.Blocked,match='explicit_static_first_frame_plan_required'):run.frame(row)
    static=tmp_path/'static.json';write(static,{})
    row.update(first_frame_contract=run.stills.CONTRACT,first_frame_plan=dict(path=str(static),sha256='wrong'))
    with pytest.raises(run.Blocked,match='static_first_frame_plan_changed'):run.frame(row)


def test_old_prepared_firstframe_plan_cannot_claim_new_static_qualification(tmp_path,monkeypatch):
    row=plan_fixture(tmp_path,monkeypatch)['shots'][0];packet=dict(qa=True);write(row['packet'],packet)
    row['packet_sha256']=run.assets.file_sha(row['packet']);static=tmp_path/'static.json';write(static,{})
    row.update(first_frame_contract=run.stills.CONTRACT,first_frame_plan=dict(path=str(static),sha256=run.assets.file_sha(static)))
    folder=Path(row['asset_run']);folder.mkdir(parents=True);write(folder/'PLAN.json',{})
    monkeypatch.setattr(run.assets,'status',lambda _:dict(plan=dict(packet=packet,config={}),paused=False,state=dict(status='h3_inputs_ready')))
    with pytest.raises(run.Blocked,match='frame_static_contract_changed'):run.frame(row)


def test_new_h3_plan_cannot_fall_back_to_generic_json_or_lower_final_dimensions(tmp_path,monkeypatch):
    row=plan_fixture(tmp_path,monkeypatch)['shots'][0]
    with pytest.raises(run.Blocked,match='explicit_native_h3_profile_required'):run.new_video_config(row)
    file=tmp_path/'native_plan.json';write(file,{})
    profile=dict(native_prompt_contract='official_multimodal/v15',native_prompt_plan=dict(path=str(file),sha256=run.assets.file_sha(file)))
    row['h3_generation']=profile
    assert run.new_video_config(row)==dict(profile,video_enabled=True,width=736,height=1312)
    row['h3_generation']={**profile,'width':288}
    with pytest.raises(run.Blocked,match='explicit_native_h3_profile_required'):run.new_video_config(row)
    row['h3_generation']=profile;file.write_text('changed')
    with pytest.raises(run.Blocked,match='native_h3_prompt_plan_changed'):run.new_video_config(row)


def completed_fixtures(plan):
    values=[]
    for i,row in enumerate(plan['shots']):
        path=Path(row['h3_run'])/'native.mp4';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('native '+row['id']).encode())
        write(Path(row['h3_run'])/'shots'/row['id']/'RESULT.json',{})
        values.append((row,dict(prompt_id='pid_'+str(i),files=dict(video=dict(path=str(path),sha256=run.assets.file_sha(path)))),path))
    return values


def test_incomplete_or_duplicate_native_outputs_cannot_assemble(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);calls=[];monkeypatch.setattr(run.subprocess,'run',lambda *a,**k:calls.append('encoder'))
    with pytest.raises(run.Blocked,match='still_incomplete'):run.assemble(plan)
    assert not calls
    rows=completed_fixtures(plan);byid={r[0]['id']:r for r in rows};monkeypatch.setattr(run,'_completed_row',lambda row:byid[row['id']])
    assert len(run.completed_video_rows(plan))==27
    rows[1][1]['prompt_id']=rows[0][1]['prompt_id']
    with pytest.raises(run.Blocked,match='repeated_native_video_ids'):run.completed_video_rows(plan)
    rows[1][1]['prompt_id']='fixed_unique';rows[1][1]['files']['video']['sha256']=rows[0][1]['files']['video']['sha256']
    with pytest.raises(run.Blocked,match='repeated_native_video_output'):run.completed_video_rows(plan)


def test_native_receipt_requires_all_files_history_timing_and_metadata(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);row=plan['shots'][0];folder=Path(row['h3_run'])/'shots'/row['id'];folder.mkdir(parents=True)
    graph=dict(node='native_graph');graph_sha=run.h3.fingerprint(graph);media={}
    for role in ('video','audio','first','last'):
        path=folder/'artifacts'/role;path.parent.mkdir(exist_ok=True);path.write_bytes(role.encode());media[role]=dict(path=str(path),sha256=run.assets.file_sha(path))
    timing=dict(native_frames=row['source_native_frames']);native_row=dict(id=row['id'],graph_sha256=graph_sha,first_frame=dict(sha256='frame'),timing=timing)
    hplan=dict(asset_run=str(Path(row['asset_run']).resolve()),shots=[native_row]);state=dict(status='technical_saved',prompt_id='pid')
    monkeypatch.setattr(run.h3,'_load',lambda *a,**k:(Path(row['h3_run']),hplan));monkeypatch.setattr(run.h3,'_shot_state',lambda *a:state)
    result=dict(shot_id=row['id'],prompt_id='pid',graph_sha256=graph_sha,first_frame_sha256='frame',production_approved=False,publication=False,old_batch_resume=False,
        technical_status='technical_saved',content_status='media_review_required',files=media,timing=timing,native_metadata=dict(streams=[dict(codec_type='video',width=736,height=1312,r_frame_rate='24/1',nb_frames=row['source_native_frames']),dict(codec_type='audio')]))
    write(folder/'RESULT.json',result);write(folder/'HISTORY.json',dict(pid=dict(prompt=[0,'pid',graph],status=dict(completed=True,status_str='success'))))
    assert run._completed_row(row)[1]==result
    Path(media['audio']['path']).write_bytes(b'changed')
    with pytest.raises(run.h3.HandoffIntegrityError,match='saved_output_changed'):run._completed_row(row)


def test_first_review_is_bound_to_current_original_id_source_and_evidence(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);rows=completed_fixtures(plan);monkeypatch.setattr(run,'_completed_row',lambda _:rows[0])
    with pytest.raises(run.Blocked,match='review_required'):run.require_first_sample_review(plan)
    evidence=tmp_path/'actual_qc.md';evidence.write_text('Audio, visual and exact dialogue reviewed.',encoding='utf-8')
    review=dict(shot_id='F0001',prompt_id=rows[0][1]['prompt_id'],video_sha256=rows[0][1]['files']['video']['sha256'],source=plan['source'],checks=dict(audio=True,visual=True,source_dialogue=True),
        reviewed_by='root_qc',evidence=[dict(path=str(evidence),sha256=run.assets.file_sha(evidence))])
    write(tmp_path/'FIRST_SAMPLE_REVIEW.json',review);run.require_first_sample_review(plan)
    evidence.write_text('Changed review',encoding='utf-8')
    with pytest.raises(run.Blocked,match='evidence_changed'):run.require_first_sample_review(plan)


def test_assembly_commits_verified_receipt_before_move_and_recovers_without_encoding(tmp_path,monkeypatch):
    plan=plan_fixture(tmp_path,monkeypatch);rows=completed_fixtures(plan)
    monkeypatch.setattr(run,'completed_video_rows',lambda _:rows);monkeypatch.setattr(run,'require_first_sample_review',lambda _:None)
    count=[]
    def encoder(command,**kwargs):count.append(command);Path(command[-1]).write_bytes(b'encoded_av')
    monkeypatch.setattr(run.subprocess,'run',encoder)
    inspected=[]
    def timing(path,frames,**kwargs):
        inspected.append(path)
        return dict(native_frames=frames,target_audio_samples=frames*2000,trim_tail_samples=32,pad_tail_samples=0)
    monkeypatch.setattr(run,'_inspect_assembly_clip',timing)
    metadata=dict(streams=[dict(codec_type='video',width=736,height=1312,r_frame_rate='24/1',avg_frame_rate='24/1',nb_frames=7292,nb_read_frames=7292,
        start_time='0.000000',duration_ts=7292*512,time_base='1/12288'),dict(codec_type='audio',start_time='0.000000',sample_rate='48000',channels=2,
        duration_ts=7292*2000,time_base='1/48000')],format=dict(duration=str(7292/24)))
    monkeypatch.setattr(run.subprocess,'check_output',lambda *a,**k:json.dumps(metadata))
    value=run.assemble(plan);assert len(count)==1 and value['native_shots'][0]['id']=='F0001'
    assert len(inspected)==27 and len(value['audio_timing_audit'])==27 and value['conform_contract']==run.CONFORM_CONTRACT
    assert (tmp_path/'ENCODED_RESULT.json').exists()
    (tmp_path/'FINAL_RESULT.json').unlink();again=run.assemble(plan)
    assert again==value and len(count)==1
    Path(rows[0][2]).write_bytes(b'new native');rows[0][1]['files']['video']['sha256']=run.assets.file_sha(rows[0][2])
    with pytest.raises(run.Blocked,match='existing_final_or_inputs_changed'):run.assemble(plan)
    assert len(count)==1


def test_cross_process_worker_lock_is_exclusive_and_releases(tmp_path):
    code='from pathlib import Path; import sys; from src.content_factory.visual_image_jobs_v3 import run_lock,JobBusyError\ntry:\n with run_lock(Path(sys.argv[1]),"WORKER.lock"): print("acquired")\nexcept JobBusyError: print("blocked")'
    with run.jobs.run_lock(tmp_path,'WORKER.lock'):
        result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],cwd=run.ROOT,capture_output=True,text=True,timeout=30)
        assert result.returncode==0 and result.stdout.strip()=='blocked'
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],cwd=run.ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and result.stdout.strip()=='acquired'
