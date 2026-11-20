"""CPU-only contracts and original-ID recovery; no production media submission."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import uuid
import pytest
from PIL import Image
from src.content_factory import visual_spatial_delivery_v24 as f

REAL_PROJECT=f.PROJECT
REAL_STAGE_INPUT=f.jobs.stage_input


def native_prompt_fixture(quote='“one”'):
    return ('subject_definitions:\n'
            '<Subject 1> is the father in <Picture 1>.\n'
            '<Subject 2> is the older boy in <Picture 2>.\n'
            '<Subject 3> is the younger boy in <Picture 3>.\n'
            '<Subject 4> is the room in <Picture 4> and <Picture 5>.\n\n'
            'summary:\n[reference generation + keyframe completion] A family exchange.\n\n'
            'retention_analysis:\n<Subject 1>: fully_preserved - portrait identity.\n\n'
            'detailed_description:\n[Shot 1] <Subject 3> (S1) says: '
            '<d>[Mandarin Chinese] '+quote+'</d>\n\n'
            'overall_soundscape:\nQuiet room tone.\n\nnon_diegetic_music:\nN/A\n')


def test_explicit_native_format_actual_payload_has_no_legacy_appendix(case):
    spec=case['spec'];spec['prompt_format']='official_ref2va_v29'
    p=Path(spec['segments'][0]['prompt']['path']);text=native_prompt_fixture();p.write_text(text,encoding='utf-8')
    spec['segments'][0]['prompt']=f.binding(p);case['prepare']();f.submit_next(case['run'])
    payload=next(value for path,value in case['calls'] if path=='/prompt')
    graph=payload['prompt'];assert graph['condition']['inputs']['prompt']==text
    assert '参考身份与环境' not in graph['condition']['inputs']['prompt']
    assert sum(k.startswith('ref_images.ref_image_') for k in graph['condition']['inputs'])==5
    assert graph['126']['inputs']['conditioning']==['guide_start',0]
    assert sum(path=='/prompt' for path,_ in case['calls'])==1


def test_native_format_malformed_rejected_before_claim_or_payload(case):
    spec=case['spec'];spec['prompt_format']='official_ref2va_v29'
    p=Path(spec['segments'][0]['prompt']['path']);p.write_text('source “one”',encoding='utf-8');spec['segments'][0]['prompt']=f.binding(p)
    with pytest.raises(ValueError,match='six_english_sections'):case['prepare']()
    assert case['calls']==[] and not (case['run']/'shots/S01/CLAIM.json').exists()


def test_unknown_explicit_format_rejected_before_prepare(case):
    spec=case['spec'];spec['prompt_format']='guessed_format'
    with pytest.raises(ValueError,match='unsupported_explicit_prompt_format'):case['prepare']()
    assert case['calls']==[]


def test_default_prompt_compilation_keeps_exact_legacy_text(case):
    s=case['spec'];seg=s['segments'][0]
    graph=f.build_graph(case['base'],s,seg,'cpu_default',s['initial_guide'],s['seed'])
    source=Path(seg['prompt']['path']).read_text(encoding='utf-8')
    expected=source+'\n\n参考身份与环境：\n'+'\n'.join('<Picture '+str(i+1)+'>：'+r['description'] for i,r in enumerate(s['references']))
    assert graph['condition']['inputs']['prompt']==expected


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return f.binding(path)


@pytest.fixture
def case(tmp_path,monkeypatch):
    project=tmp_path/'project';root=project/'data/video_generation/spatial_minute_experiments_20261107_v1';source=project/'data/video_generation/h3_reference_full_minute_20261107_v1'
    monkeypatch.setattr(f,'PROJECT',project);monkeypatch.setattr(f,'ROOT',root);monkeypatch.setattr(f,'SOURCE',source)
    original=f.native.read(REAL_PROJECT/'data/video_generation/h3_six_children_s01_720p_20261102/workflow_api.json')
    base=put(root/'base.json',original)
    config=dict(service_url='http://127.0.0.1:8190',input_root=str(root/'inputs'),output_root=str(root/'outputs'),gpu_lock_root=str(root/'gpu'),timeout=30)
    for k in ('input_root','output_root','gpu_lock_root'):Path(config[k]).mkdir(parents=True)
    pause=put(root/'old_PAUSE.json',{'paused':True})
    put(project/'data/video_generation/visual_h3_ref_v20/seedance_reference_S01_736_20261107_v1/PLAN.json',dict(config=config,protected_pause=pause))
    provenance=put(root/'provenance.json',dict(test_fixture=True))
    refs=[]
    for i,(kind,entity) in enumerate([('character','su_mo'),('character','ye_nan'),('character','ye_xijue'),('place','su_mo_room'),('place','su_mo_room')]):
        image=root/(str(i)+'.png');image.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(64,80),(i*30,70,90)).save(image)
        b=f.binding(image);review=put(root/('review'+str(i)+'.json'),dict(reviewed_by='root_agent',accepted_for_reference=True,image=b,entity_id=entity,provenance=provenance))
        refs.append(dict(reference_id=str(i),kind=kind,entity_id=entity,image=b,view='front' if i<4 else 'side',display_name=entity,description=entity,provenance=provenance,root_review=review))
    img=refs[0]['image'];oldresult=put(root/'old_result.json',dict(prompt_id='known_original',technical_status='technical_saved',files={'first':img}))
    guide_review=put(root/'guide_review.json',dict(reviewed_by='root_agent',accepted_for_guide=True,image=img))
    guide=dict(image=img,native_result=oldresult,role='first',root_review=guide_review)
    auth=put(root/'USER_AUTHORIZATION.json',dict(schema='spatial_minute_experiment_authorization/v24',user_statement='test fixture authorization',publication=False,new_cloud_media_calls=0,engineering_scope_not_user_quoted_numeric_limit=True,max_full_video_submissions=8,max_probe_video_submissions=2))
    parent=put(source/'RUNNER_PLAN.json',dict(test_fixture=True));segments=[]
    for sid in f.IDS:
        text='source “one”\n';op=source/'sources'/(sid+'.prompt.txt');op.parent.mkdir(parents=True,exist_ok=True);op.write_text(text,encoding='utf-8')
        p=root/'sources'/(sid+'.txt');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text+'named identity description',encoding='utf-8')
        segments.append(dict(id=sid,original_prompt=f.binding(op),prompt=f.binding(p)))
    run=root/'variants/canary_A'
    spec=dict(schema=f.SPEC,variant=run.name,profile='probe',authorization=auth,parent_runner_plan=parent,references=refs,initial_guide=guide,segments=segments[:1],width=288,height=512,frames=124,seed=12345,config=dict(config,base_workflow=base))
    def prepare(value=None):
        value=value or spec;p=root/'SPEC.json';put(p,value);approval=root/'APPROVAL.json';put(approval,dict(reviewed_by='root_agent',approved_for_generation=True,spec=f.binding(p),diagnostic_only=True));return f.prepare(p,approval,run)
    calls=[]
    def http(cfg,path,payload=None):
        calls.append((path,payload))
        if path=='/object_info':return {k:{'input':{}} for k in ('MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide')}
        if path=='/prompt':return {'prompt_id':'native-'+uuid.uuid4().hex}
        if path.startswith('/history/'):return {}
        raise AssertionError(path)
    monkeypatch.setattr(f.native,'_http',http);monkeypatch.setattr(f.native,'_service_paths',lambda cfg:None)
    monkeypatch.setattr(f.native,'_queue',lambda cfg:dict(queue_running=[],queue_pending=[]))
    staged=[];monkeypatch.setattr(f.jobs,'stage_input',lambda *a:staged.append(a))
    return dict(root=root,run=run,spec=spec,full_segments=segments,prepare=prepare,calls=calls,staged=staged,config=config,base=original)


def test_prepare_and_status_never_post(case):
    assert case['prepare']()['shots'][0]['status']=='prepared';assert f.status(case['run'])['technical_saved']==0
    assert case['calls']==[] and case['staged']==[]


@pytest.mark.parametrize('field,value',[('frames',123),('width',736),('profile','unknown'),('variant','arbitrary')])
def test_probe_profile_rejects(case,field,value):
    spec=deepcopy(case['spec']);spec[field]=value
    with pytest.raises(ValueError):case['prepare'](spec)


def test_wrong_quote_rejects(case):
    s=case['spec'];p=Path(s['segments'][0]['prompt']['path']);p.write_text('source “changed”',encoding='utf-8');s['segments'][0]['prompt']=f.binding(p)
    with pytest.raises(ValueError,match='dialogue'):case['prepare']()


def test_probe_cannot_compress_extra_dialogue(case):
    s=case['spec'];op=Path(s['segments'][0]['original_prompt']['path']);op.write_text('“one” “two”',encoding='utf-8');s['segments'][0]['original_prompt']=f.binding(op)
    p=Path(s['segments'][0]['prompt']['path']);p.write_text('“one” “two”',encoding='utf-8');s['segments'][0]['prompt']=f.binding(p)
    with pytest.raises(ValueError,match='dialogue'):case['prepare']()


def test_different_cast_pixels_may_equal_but_slots_independent(case):
    s=case['spec'];r=s['references'][1];r['image']=s['references'][0]['image'];review=f.native.read(r['root_review']['path']);review['image']=r['image'];r['root_review']=put(r['root_review']['path'],review)
    case['prepare']();f.submit_next(case['run']);g=f.native.read(case['run']/'shots/S01/workflow_api.json')
    assert [g['condition']['inputs']['ref_images.ref_image_'+str(i)] for i in range(3)]==[['ref_0',0],['ref_1',0],['ref_2',0]]


def test_swapped_roles_rejected(case):
    s=case['spec'];s['references'][1],s['references'][2]=s['references'][2],s['references'][1]
    with pytest.raises(ValueError,match='ordered'):case['prepare']()


def test_reference_needs_actual_root_review(case):
    s=case['spec'];r=s['references'][0];v=f.native.read(r['root_review']['path']);v['accepted_for_reference']=False;r['root_review']=put(r['root_review']['path'],v)
    with pytest.raises(ValueError,match='reference_review'):case['prepare']()


def test_initial_native_guide_must_be_original_frame(case):
    s=case['spec'];s['initial_guide']['role']='last'
    with pytest.raises((ValueError,KeyError)):case['prepare']()


def test_source_or_reference_changed_blocks_post(case):
    case['prepare']();Path(case['spec']['references'][0]['image']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):f.submit_next(case['run'])
    assert not any(p=='/prompt' for p,_ in case['calls'])


def test_graph_has_actual_reference_and_frame_zero_guide(case):
    case['prepare']();f.submit_next(case['run']);folder=case['run']/'shots/S01';g=f.native.read(folder/'workflow_api.json')
    assert g['condition']['class_type']=='MiniMaxH3ReferenceToVideo'
    assert g['127']['inputs']['unet_name']==f.MODEL
    assert g['guide_start']['inputs']==dict(positive=['condition',0],latent=['condition',1],vae=g['condition']['inputs']['vae'],image=['guide_start_image',0],frame_idx=0)
    assert g['126']['inputs']['conditioning']==['guide_start',0]
    assert g['125']['inputs']['latent_image']==['condition',1]
    assert g['124']['inputs']['steps']==12 and g['pick_last']['inputs']['batch_index']==123
    assert len(case['staged'])==6
    assert not any(k in g['condition']['inputs'] for k in ('first_frame','last_frame'))
    assert f.status(case['run'])['shots'][0]['status']=='submitted'
    assert (case['run']/'job_ids.txt').read_text().count('S01 ')==1


def test_real_stage_input_boundary_copies_all_seven_pngs_with_legal_config(case,monkeypatch):
    """Real Config normalization, PNG verification, hard-link copy and target SHA."""
    spec=case['spec'];spec['segments'][0]['end_guide']=deepcopy(spec['initial_guide']);case['prepare']()
    staged=[]
    def stage(cfg,source,name,sha):
        assert set(cfg)=={'service_url','input_root','output_root','timeout'}
        value=REAL_STAGE_INPUT(cfg,source,name,sha);staged.append(value);return value
    monkeypatch.setattr(f.jobs,'stage_input',stage)
    f.submit_next(case['run'])
    assert len(staged)==7
    for row in staged:
        assert Path(row['staged_path']).is_relative_to(Path(case['config']['input_root']))
        assert f.binding(row['staged_path'])['sha256']==row['sha256']
        assert Path(row['staged_path']).read_bytes()==Path(row['path']).read_bytes()
    assert sum(path=='/prompt' for path,_ in case['calls'])==1


def test_real_stage_input_rejects_wrong_source_sha_and_changed_target(case):
    cfg={k:case['config'][k] for k in ('service_url','input_root','output_root','timeout')}
    source=case['spec']['references'][0]['image'];name='isolated_cpu_boundary/reference.png'
    with pytest.raises(ValueError,match='input_source_sha_mismatch'):
        REAL_STAGE_INPUT(cfg,source['path'],name,'0'*64)
    assert not (Path(cfg['input_root'])/name).exists()
    first=REAL_STAGE_INPUT(cfg,source['path'],name,source['sha256'])
    assert REAL_STAGE_INPUT(cfg,source['path'],name,source['sha256'])==first
    target=Path(first['staged_path']);target.write_bytes(b'existing changed target must survive')
    with pytest.raises(ValueError,match='staged_input_already_differs'):
        REAL_STAGE_INPUT(cfg,source['path'],name,source['sha256'])
    assert target.read_bytes()==b'existing changed target must survive'


def test_real_staged_target_conflict_blocks_post_before_claim(case,monkeypatch):
    case['prepare']();monkeypatch.setattr(f.jobs,'stage_input',REAL_STAGE_INPUT)
    name=f.PREFIX+'/'+case['run'].name+'/S01/references/0.png';target=Path(case['config']['input_root'])/name
    target.parent.mkdir(parents=True);target.write_bytes(b'conflicting staged source')
    with pytest.raises(ValueError,match='staged_input_already_differs'):f.submit_next(case['run'])
    assert f.status(case['run'])['shots'][0]['status']=='prepared'
    assert not (case['run']/'shots/S01/CLAIM.json').exists()
    assert not (case['run']/'shots/S01/REQUEST.json').exists()
    assert not any(path=='/prompt' for path,_ in case['calls'])


def test_optional_end_guide_chains_without_overriding_start(case):
    s=case['spec'];s['segments'][0]['end_guide']=deepcopy(s['initial_guide']);case['prepare']();f.submit_next(case['run'])
    g=f.native.read(case['run']/'shots/S01/workflow_api.json')
    assert g['guide_end']['inputs']['positive']==['guide_start',0]
    assert g['guide_end']['inputs']['frame_idx']==123
    assert g['126']['inputs']['conditioning']==['guide_end',0] and len(case['staged'])==7


def test_known_id_does_not_resubmit(case):
    case['prepare']();f.submit_next(case['run']);pid=f.status(case['run'])['shots'][0]['prompt_id'];f.submit_next(case['run'])
    assert f.status(case['run'])['shots'][0]['prompt_id']==pid
    assert sum(p=='/prompt' for p,_ in case['calls'])==1


def test_unknown_post_is_never_replayed(case,monkeypatch):
    case['prepare']();original=f.native._http
    def http(cfg,path,payload=None):
        if path=='/prompt':raise TimeoutError('unknown')
        return original(cfg,path,payload)
    monkeypatch.setattr(f.native,'_http',http);assert f.submit_next(case['run'])['shots'][0]['status']=='outcome_unknown'
    f.submit_next(case['run']);assert f.status(case['run'])['shots'][0]['status']=='outcome_unknown'


def test_claim_without_response_after_crash_is_unknown(case):
    case['prepare']();f.submit_next(case['run']);folder=case['run']/'shots/S01';(folder/'RESPONSE.json').unlink()
    state=f.native.read(folder/'STATE.json');state.update(status='prepared',prompt_id=None);f.native.write(folder/'STATE.json',state)
    assert f.status(case['run'])['shots'][0]['status']=='outcome_unknown'
    f.submit_next(case['run']);assert sum(p=='/prompt' for p,_ in case['calls'])==1


def test_response_saved_before_state_is_recovered(case):
    case['prepare']();f.submit_next(case['run']);folder=case['run']/'shots/S01';pid=f.native.read(folder/'RESPONSE.json')['prompt_id']
    state=f.native.read(folder/'STATE.json');state.update(status='prepared',prompt_id=None);f.native.write(folder/'STATE.json',state)
    assert f.status(case['run'])['shots'][0]['prompt_id']==pid
    f.submit_next(case['run']);assert sum(p=='/prompt' for p,_ in case['calls'])==1


def test_known_preclaim_crash_reuses_frozen_request_without_false_unknown(case,monkeypatch):
    case['prepare']();original=f.native.freeze
    def freeze(path,value):
        if Path(path).name=='CLAIM.json':raise OSError('known local pre-POST interruption')
        return original(path,value)
    monkeypatch.setattr(f.native,'freeze',freeze)
    with pytest.raises(OSError):f.submit_next(case['run'])
    request=f.native.read(case['run']/'shots/S01/REQUEST.json');assert not any(p=='/prompt' for p,_ in case['calls'])
    monkeypatch.setattr(f.native,'freeze',original);f.submit_next(case['run'])
    assert f.native.read(case['run']/'shots/S01/REQUEST.json')==request
    assert sum(p=='/prompt' for p,_ in case['calls'])==1


def test_authorized_budget_shared_across_variants(case):
    s=case['spec'];a=f.native.read(s['authorization']['path']);a['max_probe_video_submissions']=1;s['authorization']=put(s['authorization']['path'],a)
    case['prepare']();f.submit_next(case['run'])
    b=deepcopy(s);b['variant']='canary_B';spec=case['root']/'SPEC_B.json';put(spec,b);approval=case['root']/'APPROVAL_B.json'
    put(approval,dict(reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,spec=f.binding(spec)))
    run=case['root']/'variants/canary_B';f.prepare(spec,approval,run)
    with pytest.raises(ValueError,match='budget_exhausted'):f.submit_next(run)
    assert not (run/'shots/S01/CLAIM.json').exists()


def test_pause_prevents_new_submit(case):
    case['prepare']();put(case['run']/'PAUSE.json',dict(paused=True));assert f.submit_next(case['run'])['dispatch']=='paused'
    assert case['calls']==[]


def test_busy_queue_waits_without_claim(case,monkeypatch):
    case['prepare']();monkeypatch.setattr(f.native,'_queue',lambda cfg:dict(queue_running=[[0,'other',{}]],queue_pending=[]))
    assert f.submit_next(case['run'])['dispatch']=='waiting_gpu_queue'
    assert not (case['run']/'shots/S01/CLAIM.json').exists()


def test_shared_budget_counts_claim_even_unknown(case):
    s=case['spec'];auth=f.native.read(s['authorization']['path']);auth['max_probe_video_submissions']=0;s['authorization']=put(s['authorization']['path'],auth)
    case['prepare']()
    with pytest.raises(ValueError,match='budget_exhausted'):f.submit_next(case['run'])


def test_request_tamper_detected(case):
    case['prepare']();f.submit_next(case['run']);p=case['run']/'shots/S01/REQUEST.json';v=f.native.read(p);v['prompt']['129']['inputs']['noise_seed']+=1;f.native.write(p,v)
    with pytest.raises(ValueError,match='claim_changed'):f.status(case['run'])


def test_current_native_absent_is_unknown_no_retry(case):
    case['prepare']();f.submit_next(case['run']);assert f.poll_collect(case['run'])['shots'][0]['status']=='outcome_unknown'
    f.submit_next(case['run']);assert sum(p=='/prompt' for p,_ in case['calls'])==1


def test_wrong_native_history_graph_rejected(case,monkeypatch):
    case['prepare']();f.submit_next(case['run']);pid=f.status(case['run'])['shots'][0]['prompt_id']
    monkeypatch.setattr(f.native,'_http',lambda *a:{pid:dict(prompt=[0,pid,{}],status=dict(completed=True,status_str='success'))})
    with pytest.raises(ValueError,match='history_mismatch'):f.poll_collect(case['run'])


def test_known_failed_native_not_replayed(case,monkeypatch):
    case['prepare']();f.submit_next(case['run']);pid=f.status(case['run'])['shots'][0]['prompt_id'];g=f.native.read(case['run']/'shots/S01/workflow_api.json')
    monkeypatch.setattr(f.native,'_http',lambda *a:{pid:dict(prompt=[0,pid,g],status=dict(completed=False,status_str='error',messages=[['execution_interrupted',{}]]))})
    assert f.poll_collect(case['run'])['shots'][0]['status']=='interrupted'
    assert f.submit_next(case['run'])['shots'][0]['status']=='interrupted'


def test_actual_cpu_fixture_collects_originals_through_pause_and_input_change(case,monkeypatch):
    case['prepare']();f.submit_next(case['run']);run=case['run'];folder=run/'shots/S01';pid=f.status(run)['shots'][0]['prompt_id'];g=f.native.read(folder/'workflow_api.json');row=f.native.read(folder/'GRAPH_BINDING.json')
    dest=Path(case['config']['output_root'])/row['scope'];dest.mkdir(parents=True)
    # Clearly synthetic CPU technical fixture, never a production/model result.
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=288x512:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=32000','-frames:v','124','-t',str(124/24),'-c:v','libx264','-preset','ultrafast','-c:a','aac',str(dest/'video_00001_.mp4')],check=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(dest/'video_00001_.mp4'),'-vn',str(dest/'audio_00001.flac')],check=True)
    for role in ('first','last'):Image.new('RGB',(288,512),'blue').save(dest/(role+'_00001_.png'))
    outputs={}
    for role,key,suffix in [('video','images','.mp4'),('audio','audio','.flac'),('first','images','.png'),('last','images','.png')]:
        name=role+'_00001'+('.flac' if role=='audio' else '_'+suffix)
        outputs['save_'+role]={key:[dict(filename=name,subfolder=row['scope'],type='output')]}
    history={pid:dict(prompt=[0,pid,g],status=dict(completed=True,status_str='success'),outputs=outputs)}
    monkeypatch.setattr(f.native,'_http',lambda *a:history)
    put(run/'PAUSE.json',dict(paused=True));Path(case['spec']['references'][0]['image']['path']).write_bytes(b'upstream_changed')
    result=f.poll_collect(run);assert result['technical_saved']==1 and result['paused'] is True
    native=f.native.read(folder/'RESULT.json');assert native['production_approved'] is False and native['prompt_id']==pid
    for artifact in native['files'].values():assert f.binding(artifact['path'])['sha256']==artifact['sha256']
    assert (folder/'HISTORY.json').exists()
    # Actual original native tail, not a planned substitute, feeds the next segment.
    p=f.native.read(run/'PLAN.json')
    tail=f._tail(run,p,1);assert tail['image']['sha256']==native['files']['last']['sha256'] and tail['native_id']==pid


def test_execute_bounds_and_probe_never_assembles(case):
    case['prepare']()
    with pytest.raises(ValueError):f.execute(case['run'],poll_seconds=0)
    with pytest.raises(ValueError,match='probe_is_not_minute'):f.assemble(case['run'])


def test_concurrent_runner_lock_refuses_duplicate(case):
    case['prepare']()
    with f.jobs.run_lock(case['run'],'RUNNER.lock'):
        with pytest.raises(Exception):f.execute(case['run'],max_seconds=1)


def minute(case):
    s=deepcopy(case['spec']);s.update(variant='A',profile='minute',width=736,height=1312,frames=362,segments=case['full_segments'])
    run=case['root']/'variants/A';spec=case['root']/'MINUTE_SPEC.json';put(spec,s);approval=case['root']/'MINUTE_APPROVAL.json'
    put(approval,dict(reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,spec=f.binding(spec)))
    return s,run,spec,approval


def test_full_minute_profile_is_four_original_ordered_sources(case):
    s,run,p,a=minute(case);out=f.prepare(p,a,run)
    assert out['total']==4 and out['profile']=='minute' and out['technical_saved']==0
    s['segments'].reverse();put(p,s);put(a,dict(reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,spec=f.binding(p)))
    with pytest.raises(ValueError,match='four_formal_segments'):f.prepare(p,a,run)


def test_formal_geometry_not_lowres_probe_masquerade(case):
    s,run,p,a=minute(case);s['width']=288;s['height']=512;put(p,s);put(a,dict(reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,spec=f.binding(p)))
    with pytest.raises(ValueError,match='four_formal_segments'):f.prepare(p,a,run)


def test_full_execute_actual_cpu_clock_and_original_tail_chain(case,monkeypatch):
    """Four lavfi color fixtures, real ffmpeg/ffprobe; explicitly not model output."""
    s,run,p,a=minute(case);f.prepare(p,a,run);history={};submits=[]
    def http(cfg,path,payload=None):
        if path=='/object_info':return {k:{'input':{}} for k in ('MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide')}
        if path.startswith('/history/'):return history
        assert path=='/prompt';graph=payload['prompt'];i=len(submits);pid='cpu-fixture-'+str(i);submits.append(pid)
        scope=graph['save_video']['inputs']['filename_prefix'].rsplit('/',1)[0];dest=Path(cfg['output_root'])/scope;dest.mkdir(parents=True)
        color=('red','green','blue','yellow')[i]
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',f'color=c={color}:s=736x1312:r=24','-f','lavfi','-i',f'sine=frequency={440+i*60}:sample_rate=32000','-frames:v','362','-t',str(362/24),'-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',str(dest/'video_00001_.mp4')],check=True)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(dest/'video_00001_.mp4'),'-vn',str(dest/'audio_00001.flac')],check=True)
        outputs={}
        for role,key,suffix in [('video','images','.mp4'),('audio','audio','.flac'),('first','images','.png'),('last','images','.png')]:
            name=role+'_00001'+('.flac' if role=='audio' else '_'+suffix)
            if role in ('first','last'):Image.new('RGB',(736,1312),color).save(dest/name)
            outputs['save_'+role]={key:[dict(filename=name,subfolder=scope,type='output')]}
        history[pid]=dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'),outputs=outputs)
        return {'prompt_id':pid}
    monkeypatch.setattr(f.native,'_http',http);monkeypatch.setattr(f.time,'sleep',lambda _:None)
    value=f.execute(run,max_seconds=600)
    assert len(submits)==4 and value['native_ids']==submits and value['diagnostic_preview'] is True
    assert value['production_approved'] is False and value['clock']['native_frames']==1448
    for previous,current in zip(f.IDS,f.IDS[1:]):
        last=f.native.read(run/'shots'/previous/'RESULT.json')['files']['last'];graph_binding=f.native.read(run/'shots'/current/'GRAPH_BINDING.json')
        assert graph_binding['guide']['image']=={k:last[k] for k in ('path','sha256')}
        assert graph_binding['guide']['previous_segment']==previous
    # Complete/recovery stays idempotent; no fifth POST or new clip after assembly.
    assert f.execute(run,max_seconds=600)['file']==value['file'] and len(submits)==4
