"""CPU/filesystem and in-memory native-boundary fixtures, never model media."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import pytest
from PIL import Image
from src.content_factory import visual_h3_legacy_call_restore_v32 as f

REAL_RUN=f.RUN;REAL_RAW=f.RAW;REAL_A=f.A_SPEC

def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return f.binding(path)

@pytest.fixture
def case(tmp_path,monkeypatch):
    root=tmp_path/'new_restore';raw=tmp_path/'old_raw';ap=tmp_path/'old_a/A_SPEC.json';audit=tmp_path/'old_a/ACTUAL_CALL_DIFF.json'
    monkeypatch.setattr(f,'RUN',root);monkeypatch.setattr(f,'RAW',raw);monkeypatch.setattr(f,'A_SPEC',ap);monkeypatch.setattr(f,'CALL_AUDIT',audit)
    acceptance=tmp_path/'CPU_ACCEPTANCE.json';put(acceptance,dict(cpu_fixture=True));monkeypatch.setattr(f,'CPU_ACCEPTANCE',acceptance)
    olda=f.native.read(REAL_A);a=deepcopy(olda);segments=[]
    for sid,source in zip(f.IDS,olda['segments']):
        p=tmp_path/'a_sources'/(sid+'.txt');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(Path(source['prompt']['path']).read_bytes())
        segments.append(dict(id=sid,prompt=f.binding(p),original_prompt=source['original_prompt']))
    a['segments']=segments
    image=tmp_path/'canonical.png';Image.new('RGB',(736,1312),'gray').save(image);ib=f.binding(image)
    oldresult=put(tmp_path/'canonical_native_result.json',dict(prompt_id='known_old_canonical',technical_status='technical_saved',files={'first':ib}))
    review=put(tmp_path/'canonical_root_review.json',dict(reviewed_by='root_agent',accepted_for_guide=True,image=ib))
    a['initial_guide']=dict(image=ib,native_result=oldresult,role='first',root_review=review)
    config=dict(service_url='http://127.0.0.1:8190',input_root=str(tmp_path/'inputs'),output_root=str(tmp_path/'outputs'),gpu_lock_root=str(tmp_path/'gpu'),timeout=30)
    for key in ('input_root','output_root','gpu_lock_root'):Path(config[key]).mkdir(parents=True)
    a['config'].update(config);put(ap,a);pause=put(tmp_path/'old_pause.json',dict(paused=True))
    put(raw/'PLAN.json',dict(schema='h3_original_prompt_parity/v19',config=config,protected_pause=pause))
    for sid in f.IDS:
        g=f.native.read(REAL_RAW/'segments'/sid/'workflow_api.json');pid='old_completed_'+sid;folder=raw/'segments'/sid
        put(folder/'workflow_api.json',g);put(folder/'REQUEST.json',dict(prompt=g));put(folder/'RESULT.json',dict(prompt_id=pid))
        put(folder/'HISTORY.json',{pid:dict(prompt=[0,pid,g],status=dict(completed=True,status_str='success'))})
    put(audit,dict(cpu_fixture=True));selection=put(tmp_path/'aligned_audit.json',dict(cpu_fixture=True))
    auth=dict(schema=f.AUTH_SCHEMA,user_statement='分析流程并更新流程重跑流程',engineering_scope_not_user_quoted_numeric_limit=True,max_full_video_submissions=4,max_probe_video_submissions=0,new_cloud_media_calls=0,publication=False,service_restarts=False,downloads=False,unknown_native_replay=False,old_paused_batches_resumed=False,baseline_a_spec=f.binding(ap),legacy_raw_plan=f.binding(raw/'PLAN.json'),call_difference_audit=f.binding(audit),baseline_selection_by='root_agent',selection_evidence=selection)
    put(root/'USER_AUTHORIZATION.json',auth)
    calls=[];history={};queue=dict(queue_running=[],queue_pending=[])
    def http(cfg,path,payload=None):
        calls.append((path,payload))
        if path.startswith('/history/'):return history
        if path=='/prompt':return dict(prompt_id='cpu_native_'+str(sum(x[0]=='/prompt' for x in calls)))
        raise AssertionError(path)
    monkeypatch.setattr(f.native,'_http',http);monkeypatch.setattr(f.native,'_service_paths',lambda cfg:None);monkeypatch.setattr(f.native,'_queue',lambda cfg:deepcopy(queue))
    return dict(root=root,raw=raw,a=a,auth=auth,config=config,calls=calls,history=history,queue=queue)

def approve(case):
    root=case['root'];auth=case['auth']
    return put(root/'LAUNCH_APPROVAL.json',dict(schema=f.APPROVAL_SCHEMA,reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,plan=f.binding(root/'PLAN.json'),authorization=f.binding(root/'USER_AUTHORIZATION.json'),baseline_selection_by='root_agent',selection_basis=[auth['call_difference_audit'],auth['selection_evidence']],execution_sources=dict(executor=f.binding(Path(f.__file__)),cli=f.binding(f.PROJECT/'scripts/run_h3_legacy_call_restore_v32.py')),cpu_acceptance=f.binding(f.CPU_ACCEPTANCE)))

def ready(case):f.prepare(case['root']);approve(case)

def test_actual_prepared_four_sources_readonly_no_media():
    before=f.binding(REAL_RUN/'PLAN.json');value=f.status(REAL_RUN)
    assert value['total']==4 and value['direct_reference_slots']==0 and value['task_mode']=='fl2va_i2v_first_only'
    assert f.binding(REAL_RUN/'PLAN.json')==before

def test_actual_cli_status_reads_prepared_plan_without_mutation():
    before=f.binding(REAL_RUN/'PLAN.json')
    process=subprocess.run([sys.executable,'-X','utf8','scripts/run_h3_legacy_call_restore_v32.py','status'],cwd=f.PROJECT,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert process.returncode==0,process.stdout+process.stderr
    value=json.loads(process.stdout);assert value['task_mode']=='fl2va_i2v_first_only' and value['total']==4
    assert f.binding(REAL_RUN/'PLAN.json')==before

def test_prepare_is_cpu_only_and_idempotent_with_complete_sources(case):
    a=f.prepare(case['root']);before=f.binding(case['root']/'PLAN.json');b=f.prepare(case['root'])
    assert a==b and before==f.binding(case['root']/'PLAN.json') and case['calls']==[]
    assert all(s['status']=='prepared' and s['prompt_id'] is None for s in a['shots'])
    assert not list(case['root'].glob('shots/*/CLAIM.json'))
    p=f.native.read(case['root']/'PLAN.json');assert p['direct_reference_slots']==0 and len(p['upstream_asset_references'])==5
    for row in p['settings']['segments']:
        source=Path(row['original_prompt']['path']).read_bytes().decode('utf-8');text=Path(row['prompt']['path']).read_bytes().decode('utf-8');audit=f.native.read(row['adaptation_audit']['path'])
        assert f.restore_prompt(text,audit)==source
        assert f.spatial.quotes(source)==f.spatial.quotes(text) and '<Picture' not in text and '具名参考' not in text
    assert sum(len(f.native.read(row['adaptation_audit']['path'])['original_quotes']) for row in p['settings']['segments'])==10

def test_source_actions_crlf_and_all_quotes_retained(case):
    source=Path(case['a']['segments'][0]['prompt']['path']).read_bytes().decode('utf-8').replace('\n','\r\n')
    text,audit=f.compile_prompt(source,f.sha(source.encode('utf-8')))
    assert f.restore_prompt(text,audit)==source and '\r\n' in text
    assert '开头立即开始对话。0—5秒' in text and '13—15秒' in text and '他的手轻落在弟弟肩侧' in text

@pytest.mark.parametrize('mutation',['source_sha','phantom_reference','missing_anchor','missing_plain_story'])
def test_adaptation_rejects_undefined_rewrite_or_reference(case,mutation):
    source=Path(case['a']['segments'][0]['prompt']['path']).read_bytes().decode('utf-8')
    if mutation=='phantom_reference':source+='\n<Picture 6>'
    elif mutation=='missing_anchor':source=source.replace('人物与参考图逐一对应：','Other header')
    elif mutation=='missing_plain_story':source=source.replace('画面以纯剧情影像呈现，叙事信息通过表演和声音传达。','')
    with pytest.raises(ValueError):f.compile_prompt(source,'0'*64 if mutation=='source_sha' else f.sha(source.encode('utf-8')))

@pytest.mark.parametrize('field,value',[('max_full_video_submissions',5),('max_full_video_submissions',True),('max_probe_video_submissions',1),('max_probe_video_submissions',False),('new_cloud_media_calls',False),('downloads',True),('service_restarts',True),('unknown_native_replay',True),('old_paused_batches_resumed',True),('engineering_scope_not_user_quoted_numeric_limit',False)])
def test_exact_new_authorization_four_zero_flags(case,field,value):
    case['auth'][field]=value;put(case['root']/'USER_AUTHORIZATION.json',case['auth'])
    with pytest.raises(ValueError,match='four_video_zero_probe'):f.prepare(case['root'])

def test_arbitrary_root_and_bound_source_revision_rejected(case):
    with pytest.raises(ValueError,match='only_new'):f.prepare(case['root'].parent/'other')
    source=f.A_SPEC;v=f.native.read(source);v['seed']=999;put(source,v)
    with pytest.raises(ValueError,match='fixed_a_raw'):f.prepare(case['root'])

def test_legacy_template_requires_real_completed_original_graph(case):
    path=case['raw']/'segments/S03/HISTORY.json';v=f.native.read(path);entry=next(iter(v.values()));entry['prompt'][2]['124']['inputs']['steps']=20;put(path,v)
    with pytest.raises(ValueError,match='completed_actual_legacy'):f.prepare(case['root'])

def test_old_call_profile_cannot_silently_change_to_reference_or_new_seed(case):
    path=case['raw']/'segments/S01/workflow_api.json';g=f.native.read(path);g['condition']['class_type']='MiniMaxH3ReferenceToVideo'
    put(path,g);put(path.with_name('REQUEST.json'),dict(prompt=g));pid='old_completed_S01';put(path.with_name('HISTORY.json'),{pid:dict(prompt=[0,pid,g],status=dict(completed=True,status_str='success'))})
    with pytest.raises(ValueError,match='legacy_first_only'):f.prepare(case['root'])

def test_graph_restores_each_actual_old_sampler_seed_and_only_new_input_fields(case):
    f.prepare(case['root']);p=f.native.read(case['root']/'PLAN.json')
    for i,row in enumerate(p['settings']['segments']):
        old=row['template'];prompt=Path(row['prompt']['path']).read_text(encoding='utf-8');new=f.build_graph(old,prompt,'new_scope/'+row['id'])
        normalized=deepcopy(new);normalized['condition']['inputs']['prompt']=old['condition']['inputs']['prompt'];normalized['ref_scene']['inputs']=old['ref_scene']['inputs']
        for role in f.ROLES:normalized['save_'+role]['inputs']=old['save_'+role]['inputs']
        assert f.native.fingerprint(normalized)==f.native.fingerprint(old)
        assert new['127']['inputs']['unet_name']==f.MODEL and new['129']['inputs']['noise_seed']==2026110700+i
        assert new['condition']['class_type']=='MiniMaxH3ImageToVideo' and new['condition']['inputs']['first_frame']==['ref_scene',0]
        assert not any(x['class_type'] in ('MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide') for x in new.values())

@pytest.mark.parametrize('field',['service_url','input_root','first_guide','asset_refs','geometry_type','source_alias'])
def test_current_plan_cannot_change_bound_local_task_or_assets(case,field):
    f.prepare(case['root']);path=case['root']/'PLAN.json';p=f.native.read(path)
    if field=='service_url':p['config']['service_url']='https://example.invalid'
    elif field=='input_root':p['config']['input_root']=str(case['root']/'other_inputs')
    elif field=='first_guide':p['settings']['initial_guide']['role']='last'
    elif field=='asset_refs':p['upstream_asset_references']=[]
    elif field=='geometry_type':p['settings']['width']=736.0
    elif field=='source_alias':
        row=p['settings']['segments'][0];old=Path(row['original_prompt']['path']);new=old.with_name('source_alias.txt');new.write_bytes(old.read_bytes());row['original_prompt']=f.binding(new)
    put(path,p)
    with pytest.raises(ValueError,match='bound_local|frozen_task'):f._load(case['root'],current=True)
    assert case['calls']==[]

def test_missing_or_wrong_root_launch_approval_blocks_before_native_call(case):
    f.prepare(case['root'])
    with pytest.raises(FileNotFoundError):f.submit_next(case['root'])
    assert case['calls']==[] and not list(case['root'].glob('shots/*/CLAIM.json'))
    approve(case);p=case['root']/'LAUNCH_APPROVAL.json';v=f.native.read(p);v['baseline_selection_by']='user';put(p,v)
    with pytest.raises(ValueError,match='root_plan_selection'):f.submit_next(case['root'])
    assert case['calls']==[]

@pytest.mark.parametrize('mutation',['executor_sha','executor_path','cli_sha','missing','acceptance_path','acceptance_bytes'])
def test_execution_and_acceptance_bindings_reject_before_new_post(case,mutation):
    ready(case);path=case['root']/'LAUNCH_APPROVAL.json';v=f.native.read(path)
    if mutation=='executor_sha':v['execution_sources']['executor']['sha256']='0'*64
    elif mutation=='executor_path':v['execution_sources']['executor']['path']=str(case['root']/'other_executor.py')
    elif mutation=='cli_sha':v['execution_sources']['cli']['sha256']='0'*64
    elif mutation=='missing':del v['execution_sources']
    elif mutation=='acceptance_path':v['cpu_acceptance']['path']=str(case['root']/'other_acceptance.json')
    elif mutation=='acceptance_bytes':f.CPU_ACCEPTANCE.write_bytes(b'changed acceptance')
    put(path,v)
    with pytest.raises(ValueError,match='execution_source|bound_file_changed'):f.submit_next(case['root'])
    assert case['calls']==[] and not list(case['root'].glob('shots/*/CLAIM.json'))

def test_actual_execution_file_hash_drift_is_checked_on_every_new_dispatch(case,monkeypatch):
    ready(case);original=f.native.file_sha;target=Path(f.__file__).resolve()
    def changed(path):return '1'*64 if Path(path).resolve()==target else original(path)
    monkeypatch.setattr(f.native,'file_sha',changed)
    with pytest.raises(ValueError,match='execution_source'):f.submit_next(case['root'])
    assert case['calls']==[]

def test_actual_stage_input_boundary_and_no_multi_reference_payload(case):
    ready(case);f.submit_next(case['root']);folder=case['root']/'shots/S01';req=f.native.read(folder/'REQUEST.json');row=f.native.read(folder/'GRAPH_BINDING.json')
    assert row['first_frame']['sha256']==row['guide']['image']['sha256']
    staged=Path(case['config']['input_root'])/row['input_name'];assert f.binding(staged)['sha256']==row['guide']['image']['sha256']
    assert req['prompt']['condition']['inputs']['prompt']==Path(row['source_prompt']['path']).read_text(encoding='utf-8')
    assert len([n for n in req['prompt'].values() if n['class_type']=='LoadImage'])==1
    assert sum(x[0]=='/prompt' for x in case['calls'])==1

def test_pause_busy_queue_and_runner_lock_prevent_new_dispatch(case):
    ready(case);put(case['root']/'PAUSE.json',dict(paused=True));assert f.submit_next(case['root'])['dispatch']=='paused';assert case['calls']==[]
    (case['root']/'PAUSE.json').unlink();case['queue']['queue_running']=[[0,'other',{}]]
    assert f.submit_next(case['root'])['dispatch']=='waiting_gpu_queue' and not list(case['root'].glob('shots/*/CLAIM.json'))
    with f.jobs.run_lock(case['root'],'RUNNER.lock'):
        with pytest.raises(Exception):f.execute(case['root'],max_seconds=1)

def test_known_id_and_unknown_claim_never_repost(case):
    ready(case);f.submit_next(case['root']);pid=f.status(case['root'])['shots'][0]['prompt_id'];f.submit_next(case['root'])
    assert sum(x[0]=='/prompt' for x in case['calls'])==1
    folder=case['root']/'shots/S01';(folder/'RESPONSE.json').unlink();state=f.native.read(folder/'STATE.json');state.update(status='prepared',prompt_id=None);f.native.write(folder/'STATE.json',state)
    assert f.status(case['root'])['shots'][0]['status']=='outcome_unknown';f.submit_next(case['root'])
    assert sum(x[0]=='/prompt' for x in case['calls'])==1

def test_response_before_state_recovery_and_request_tamper(case):
    ready(case);f.submit_next(case['root']);folder=case['root']/'shots/S01';state=f.native.read(folder/'STATE.json');state.update(status='prepared',prompt_id=None);f.native.write(folder/'STATE.json',state)
    assert f.status(case['root'])['shots'][0]['prompt_id']=='cpu_native_1'
    req=f.native.read(folder/'REQUEST.json');req['client_id']='changed';put(folder/'REQUEST.json',req)
    with pytest.raises(ValueError,match='original_claim_request'):f.status(case['root'])

def test_four_claim_budget_includes_unknown_and_new_scope_only(case):
    for sid in f.IDS:put(case['root']/'shots'/sid/'CLAIM.json',dict(outcome='unknown'))
    with pytest.raises(ValueError,match='four_native'):f._budget(case['root'])

def output_fixture(case,graph,pid,color):
    """Real ffmpeg color/audio is explicitly synthetic CPU data, not model output."""
    scope=graph['save_video']['inputs']['filename_prefix'].rsplit('/',1)[0];dest=Path(case['config']['output_root'])/scope;dest.mkdir(parents=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',f'color=c={color}:s=736x1312:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=32000','-frames:v','362','-t',str(362/24),'-c:v','libx264','-preset','ultrafast','-threads','1','-c:a','aac',str(dest/'video_00001_.mp4')],check=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(dest/'video_00001_.mp4'),'-vn',str(dest/'audio_00001.flac')],check=True)
    outputs={}
    for role,key,name in [('video','images','video_00001_.mp4'),('audio','audio','audio_00001.flac'),('first','images','first_00001_.png'),('last','images','last_00001_.png')]:
        if role in ('first','last'):Image.new('RGB',(736,1312),color).save(dest/name)
        outputs['save_'+role]={key:[dict(filename=name,subfolder=scope,type='output')]}
    return dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'),outputs=outputs)

def test_known_original_collects_through_pause_and_upstream_change(case):
    ready(case);f.submit_next(case['root']);folder=case['root']/'shots/S01';graph=f.native.read(folder/'workflow_api.json');pid=f.status(case['root'])['shots'][0]['prompt_id']
    case['history'][pid]=output_fixture(case,graph,pid,'red');put(case['root']/'PAUSE.json',dict(paused=True))
    approval=case['root']/'LAUNCH_APPROVAL.json';v=f.native.read(approval);v['execution_sources']['executor']['sha256']='0'*64;put(approval,v)
    Path(case['a']['segments'][0]['prompt']['path']).write_bytes(b'upstream changed')
    result=f.poll_collect(case['root']);assert result['technical_saved']==1 and result['paused']
    saved=f.native.read(folder/'RESULT.json');assert saved['schema']==f.SCHEMA and saved['direct_reference_slots']==0
    assert set(saved['files'])==set(f.ROLES) and saved['prompt_id']==pid
    for value in saved['files'].values():assert f.binding(value['path'])['sha256']==value['sha256']
    assert f.submit_next(case['root'])['dispatch']=='paused'

def test_unknown_absent_history_and_wrong_history_refuse_replay(case):
    ready(case);f.submit_next(case['root']);pid=f.status(case['root'])['shots'][0]['prompt_id'];folder=case['root']/'shots/S01'
    case['history'][pid]=dict(prompt=[0,pid,{}],status=dict(completed=True,status_str='success'))
    with pytest.raises(ValueError,match='history_identity'):f.poll_collect(case['root'])
    case['history'].clear();assert f.poll_collect(case['root'])['shots'][0]['status']=='outcome_unknown'
    f.submit_next(case['root']);assert sum(x[0]=='/prompt' for x in case['calls'])==1

def test_cpu_full_serial_four_ids_native_tails_and_complete_av_clock(case,monkeypatch):
    ready(case);ids=[]
    def http(cfg,path,payload=None):
        if path.startswith('/history/'):return case['history']
        assert path=='/prompt';pid='cpu_full_'+str(len(ids));i=len(ids);ids.append(pid)
        case['history'][pid]=output_fixture(case,payload['prompt'],pid,('red','green','blue','yellow')[i]);return dict(prompt_id=pid)
    monkeypatch.setattr(f.native,'_http',http);monkeypatch.setattr(f.time,'sleep',lambda seconds:None)
    value=f.execute(case['root'],max_seconds=600)
    assert value['native_ids']==ids and len(ids)==4 and value['clock']['native_frames']==1448
    assert value['clock']['audio_samples']==2896000 and value['production_approved'] is False
    for previous,current in zip(f.IDS,f.IDS[1:]):
        result=f.native.read(case['root']/'shots'/previous/'RESULT.json');row=f.native.read(case['root']/'shots'/current/'GRAPH_BINDING.json')
        assert row['guide']['image']['sha256']==result['files']['last']['sha256']
        assert row['guide']['native_result']==f.binding(case['root']/'shots'/previous/'RESULT.json')
    assert (case['root']/'job_ids.txt').read_text(encoding='utf-8').count('cpu_full_')==4
