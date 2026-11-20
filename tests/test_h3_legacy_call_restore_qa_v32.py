"""Synthetic local protocol/CPU fixtures only. No H3 generation or HTTP."""
from copy import deepcopy
from pathlib import Path
import ast,json,shutil,subprocess
import pytest
from PIL import Image
from scripts import qa_h3_legacy_call_restore_v32 as qa


def put(path,value):qa.write(path,value);return qa.binding(path)

def template(index,text):
    def n(kind,**kw):return dict(class_type=kind,inputs=kw)
    return {
      '119':n('VAELoader',vae_name='minimax_h3_video_vae_int8_convrot.safetensors'),
      '120':n('VAELoader',vae_name='minimax_h3_audio_vae_fp32.safetensors'),
      '127':n('UNETLoader',unet_name='minimax_h3_fl2va_pruned_int8_convrot.safetensors',weight_dtype='default'),
      '128':n('CLIPLoader',clip_name='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',type='minimax',device='default'),
      '123':n('KSamplerSelect',sampler_name='res_multistep'),
      '124':n('BasicScheduler',model=['127',0],scheduler='simple',steps=12,denoise=1),
      '129':n('RandomNoise',noise_seed=2026110700+index),
      'ref_scene':n('LoadImage',image=f'old/S0{index+1}/first.png'),
      'condition':n('MiniMaxH3ImageToVideo',clip=['128',0],vae=['119',0],prompt=text,width=736,height=1312,length=362,first_frame=['ref_scene',0]),
      '126':n('BasicGuider',model=['127',0],conditioning=['condition',0]),
      '125':n('SamplerCustomAdvanced',noise=['129',0],guider=['126',0],sampler=['123',0],sigmas=['124',0],latent_image=['condition',1]),
      '122':n('VAEDecodeTiled',samples=['125',0],vae=['119',0],tile_size=512,overlap=64,temporal_size=64,temporal_overlap=8),
      'pick_first':n('ImageFromBatch',image=['122',0],batch_index=0,length=1),
      'pick_last':n('ImageFromBatch',image=['122',0],batch_index=361,length=1),
      '121':n('VAEDecodeAudio',samples=['125',0],vae=['120',0]),
      '130':n('CreateVideo',images=['122',0],audio=['121',0],fps=24),
      'save_first':n('SaveImage',images=['pick_first',0],filename_prefix='old/first'),
      'save_last':n('SaveImage',images=['pick_last',0],filename_prefix='old/last'),
      'save_audio':n('SaveAudio',audio=['121',0],filename_prefix='old/audio'),
      'save_video':n('SaveVideo',video=['130',0],filename_prefix='old/video',format='mp4',**{'format.codec':'auto'})}


def adapt(source):
    """Test producer emits a declared edit certificate, independent of executor."""
    edits=[]
    for old,new in qa.EDITS.items():
        if old in source:
            start=source.index(old);edits.append(dict(char_start=start,char_end=start+len(old),utf8_byte_start=len(source[:start].encode()),old=old,new=new))
    edits.sort(key=lambda r:r['char_start']);out=source;offset=0
    for row in edits:row['compiled_start']=row['char_start']+offset;offset+=len(row['new'])-len(row['old'])
    for row in reversed(edits):out=out[:row['char_start']]+row['new']+out[row['char_end']:]
    import hashlib
    return out,dict(schema='first_image_prompt_adaptation/v32',source_utf8_sha256=hashlib.sha256(source.encode()).hexdigest(),compiled_utf8_sha256=hashlib.sha256(out.encode()).hexdigest(),edits=edits)


def fixture(root):
    run=root/qa.ROOT;run.mkdir(parents=True);raw=root/qa.RAW;spatial=root/'data/video_generation/spatial_minute_experiments_20261107_v1';rows=[];baseline_rows=[]
    image=spatial/'canonical.png';image.parent.mkdir(parents=True);Image.new('RGB',(736,1312),'gray').save(image)
    guide_result=put(spatial/'canonical_RESULT.json',dict(files=dict(first=qa.binding(image))))
    review=put(spatial/'review.json',dict(reviewed_by='root_agent',accepted_for_guide=True,image=qa.binding(image),native_result=guide_result))
    guide=dict(image=qa.binding(image),native_result=guide_result,role='first',root_review=review)
    for index,sid in enumerate(qa.IDS):
        text='\n'.join(qa.EDITS)+'\n动作保持不变，人物在原房间。\n'+'\n'.join('叶南：“'+q+'”' for q in ['测试对白甲','测试对白乙','测试对白丙'][:qa.COUNTS[index]])
        source=spatial/'sources'/(sid+'.txt');source.parent.mkdir(exist_ok=True);source.write_text(text,encoding='utf-8');compiled,audit=adapt(text)
        target=run/'prompts'/(sid+'.txt');target.parent.mkdir(exist_ok=True);target.write_text(compiled,encoding='utf-8');ap=put(run/'prompts'/(sid+'.audit.json'),audit)
        old=raw/'segments'/sid;graph=template(index,'旧模型实际提示词');pid='old_'+sid
        workflow=put(old/'workflow_api.json',graph);request=put(old/'REQUEST.json',dict(prompt=graph,client_id='oldfixture'))
        history=put(old/'HISTORY.json',{pid:dict(prompt=[1,pid,graph],status=dict(completed=True,status_str='success'),outputs={})})
        result=put(old/'RESULT.json',dict(prompt_id=pid,technical_status='technical_saved'))
        rows.append(dict(id=sid,original_prompt=qa.binding(source),prompt=qa.binding(target),adaptation_audit=ap,template=graph,legacy_actual_call=dict(request=request,workflow=workflow,history=history,result=result,original_native_id=pid)))
        baseline_rows.append(dict(id=sid,prompt=qa.binding(source)))
    baseline=put(spatial/'A_SPEC.json',dict(variant='A',segments=baseline_rows,initial_guide=guide,references=[]))
    pause=put(root/'data/video_generation/old/PAUSE.json',dict(paused=True));legacy=put(raw/'PLAN.json',dict(protected_pause=pause))
    audit=put(root/'data/qa/h3_actual_call_comparison_20261108/ACTUAL_CALL_DIFF.json',dict(synthetic_fixture=True));selection=put(root/'data/qa/selection.json',dict(synthetic_fixture=True))
    auth=put(run/'USER_AUTHORIZATION.json',dict(schema='h3_legacy_call_restore_authorization/v32',user_statement='Synthetic fixture authorization only',engineering_scope_not_user_quoted_numeric_limit=True,max_full_video_submissions=4,max_probe_video_submissions=0,new_cloud_media_calls=0,publication=False,service_restarts=False,downloads=False,unknown_native_replay=False,old_paused_batches_resumed=False,baseline_a_spec=baseline,legacy_raw_plan=legacy,call_difference_audit=audit,selection_evidence=selection))
    plan=dict(schema=qa.SCHEMA,authorization=auth,baseline_a_spec=baseline,legacy_raw_plan=legacy,call_difference_audit=audit,protected_pause=pause,config=dict(input_root=str(root/'input'),output_root=str(root/'output')),settings=dict(width=736,height=1312,frames=362,fps=24,segments=rows,initial_guide=guide),task_mode='fl2va_i2v_first_only',direct_reference_slots=0,upstream_asset_references=[],production_approved=False,publication=False,diagnostic_preview=True)
    put(run/'PLAN.json',plan)
    put(run/'LAUNCH_APPROVAL.json',dict(schema='h3_legacy_call_restore_launch_approval/v32',reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,plan=qa.binding(run/'PLAN.json'),authorization=auth,baseline_selection_by='root_agent',selection_basis=[audit,selection]))
    for sid in qa.IDS:put(run/'shots'/sid/'STATE.json',dict(id=sid,status='prepared',prompt_id=None,plan_sha256=qa.fingerprint(plan)))
    return run


def saved(run,sid,media=None):
    plan=qa.read(run/'PLAN.json');index=qa.IDS.index(sid);segment=plan['settings']['segments'][index];folder=run/'shots'/sid;scope=run.name+'/'+sid;pid='new_'+sid
    if index:
        previous=run/'shots'/qa.IDS[index-1]/'RESULT.json';prior=qa.read(previous)
        guide=dict(image={k:prior['files']['last'][k] for k in ('path','sha256')},native_result=qa.binding(previous),role='last',native_id=prior['prompt_id'],previous_segment=qa.IDS[index-1],policy='actual_previous_native_tail_even_if_semantically_imperfect')
    else:guide=plan['settings']['initial_guide']
    first=folder/'first_input.png';shutil.copyfile(guide['image']['path'],first)
    staged=Path(plan['config']['input_root'])/scope/'first_input.png';staged.parent.mkdir(parents=True);shutil.copyfile(first,staged)
    graph=deepcopy(segment['template']);graph['condition']['inputs']['prompt']=Path(segment['prompt']['path']).read_text(encoding='utf-8');graph['ref_scene']['inputs']['image']=scope+'/first_input.png'
    for role in qa.ROLES:graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    put(folder/'workflow_api.json',graph);request=put(folder/'REQUEST.json',dict(prompt=graph,client_id='fixture'))
    row=dict(id=sid,scope=scope,graph_sha256=qa.fingerprint(graph),guide=guide,first_frame=qa.binding(first),input_name=scope+'/first_input.png',source_prompt=segment['prompt'],original_prompt=segment['original_prompt'],task_mode='fl2va_i2v_first_only',direct_reference_slots=0)
    put(folder/'GRAPH_BINDING.json',row);put(folder/'CLAIM.json',dict(at=1,request=request,graph_sha256=qa.fingerprint(graph),native_post_budget=1));put(folder/'RESPONSE.json',dict(prompt_id=pid,node_errors={}))
    files={};outputs={}
    for role in qa.ROLES:
        suffix='.mp4' if role=='video' else '.flac' if role=='audio' else '.png';name=role+'_00001_'+suffix;source=Path(plan['config']['output_root'])/scope/name;source.parent.mkdir(parents=True,exist_ok=True)
        if media:shutil.copyfile(media/('native'+suffix),source)
        elif suffix=='.png':Image.new('RGB',(736,1312),(50+index*40,70,90)).save(source)
        else:source.write_bytes((sid+role+'synthetic protocol-only fixture').encode())
        dest=folder/'artifacts'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(source,dest);files[role]=dict(path=str(dest),sha256=qa.sha(dest),source_path=str(source));outputs['save_'+role]={'audio' if role=='audio' else 'images':[dict(type='output',filename=name,subfolder=scope)]}
    observed=deepcopy(graph);observed['124']['inputs']['denoise']=1.0;observed['130']['inputs']['fps']=24.0
    put(folder/'HISTORY.json',{pid:dict(prompt=[1,pid,observed],status=dict(completed=True,status_str='success'),outputs=outputs)})
    result=dict(schema=qa.SCHEMA,shot_id=sid,prompt_id=pid,graph_sha256=qa.fingerprint(graph),files=files,guide=guide,first_frame=qa.binding(first),source_prompt=segment['prompt'],original_prompt=segment['original_prompt'],task_mode='fl2va_i2v_first_only',direct_reference_slots=0,technical_status='technical_saved',production_approved=False,publication=False)
    put(folder/'RESULT.json',result);put(folder/'STATE.json',dict(id=sid,status='technical_saved',prompt_id=pid,plan_sha256=qa.fingerprint(plan),graph_sha256=qa.fingerprint(graph),result_sha256=qa.sha(folder/'RESULT.json')))
    return folder


def test_preflight_is_readonly_and_four_actual_recipe_sources_are_bound(tmp_path):
    run=fixture(tmp_path);before={str(p):qa.sha(p) for p in tmp_path.rglob('*') if p.is_file()}
    result=qa.validate_plan(run,project=tmp_path)
    assert [r['id'] for r in result['segments']]==list(qa.IDS)
    assert before=={str(p):qa.sha(p) for p in tmp_path.rglob('*') if p.is_file()}
    assert not (run/'qc').exists()


@pytest.mark.parametrize('mutation',['width_float','direct_ref_bool','publication','source_sha','old_history','template_seed','quote_edit','audit_extra_edit','pause','canonical_review'])
def test_frozen_authority_source_recipe_and_edit_failures_are_explicit(tmp_path,mutation):
    run=fixture(tmp_path);plan=qa.read(run/'PLAN.json')
    if mutation=='width_float':plan['settings']['width']=736.0
    elif mutation=='direct_ref_bool':plan['direct_reference_slots']=False
    elif mutation=='publication':plan['publication']=True
    elif mutation=='source_sha':plan['settings']['segments'][0]['original_prompt']['sha256']='0'*64
    elif mutation=='old_history':Path(plan['settings']['segments'][0]['legacy_actual_call']['history']['path']).write_bytes(b'{}')
    elif mutation=='template_seed':plan['settings']['segments'][0]['template']['129']['inputs']['noise_seed']=12345
    elif mutation=='quote_edit':Path(plan['settings']['segments'][0]['prompt']['path']).write_text('擅改对白',encoding='utf-8')
    elif mutation=='audit_extra_edit':
        path=Path(plan['settings']['segments'][0]['adaptation_audit']['path']);audit=qa.read(path);audit['edits'][0]['new']='新增剧情';put(path,audit);plan['settings']['segments'][0]['adaptation_audit']=qa.binding(path)
    elif mutation=='pause':Path(plan['protected_pause']['path']).write_bytes(b'changed')
    elif mutation=='canonical_review':Path(plan['settings']['initial_guide']['root_review']['path']).write_bytes(b'{}')
    put(run/'PLAN.json',plan)
    with pytest.raises((ValueError,KeyError)):qa.validate_plan(run,project=tmp_path)


@pytest.mark.parametrize('node,key,value',[('127','unet_name','minimax_h3_ref2va_pruned_int8_convrot.safetensors'),('128','clip_name','wrong.safetensors'),('123','sampler_name','euler'),('124','steps',4),('129','noise_seed',12345),('condition','first_frame',['wrong',0]),('condition','last_frame',['ref_scene',0]),('condition','ref_images.ref_image_0',['ref_scene',0])])
def test_hybrid_or_changed_actual_recipe_is_not_accepted(node,key,value):
    graph=template(0,'text');graph[node]['inputs'][key]=value
    with pytest.raises(ValueError):qa.recipe(graph,0)


def test_history_only_normalizes_two_known_native_float_fields():
    graph=template(0,'text');native=deepcopy(graph);native['124']['inputs']['denoise']=1.0;native['130']['inputs']['fps']=24.0;qa.history_graph(graph,native)
    for node,key,value in [('129','noise_seed',2026110700.0),('124','denoise',True),('124','steps',12.0)]:
        changed=deepcopy(native);changed[node]['inputs'][key]=value
        with pytest.raises(ValueError):qa.history_graph(graph,changed)


def test_first_only_new_identity_and_previous_original_tail_binding(tmp_path):
    run=fixture(tmp_path);saved(run,'S01');saved(run,'S02')
    _,_,result,row=qa.validate_segment(run,'S02',project=tmp_path)
    assert result['guide']['previous_segment']=='S01' and row['direct_reference_slots']==0
    assert result['guide']['image']['sha256']==qa.read(run/'shots/S01/RESULT.json')['files']['last']['sha256']


@pytest.mark.parametrize('mutation',['claim','response','native_history','history_output','staged','first','source_original','video','result_sha','native_unknown','old_native_id','approval'])
def test_saved_original_tampering_never_reaches_cpu_or_reposts(tmp_path,monkeypatch,mutation):
    run=fixture(tmp_path);folder=saved(run,'S01');plan=qa.read(run/'PLAN.json');result=qa.read(folder/'RESULT.json')
    if mutation=='claim':data=qa.read(folder/'CLAIM.json');data['request']['sha256']='0'*64;put(folder/'CLAIM.json',data)
    elif mutation=='response':put(folder/'RESPONSE.json',dict(prompt_id='other'))
    elif mutation=='native_history':data=qa.read(folder/'HISTORY.json');data['new_S01']['prompt'][2]['condition']['inputs']['prompt']='wrong';put(folder/'HISTORY.json',data)
    elif mutation=='history_output':data=qa.read(folder/'HISTORY.json');data['new_S01']['outputs']['save_last']['images'][0]['subfolder']='other';put(folder/'HISTORY.json',data)
    elif mutation=='staged':(Path(plan['config']['input_root'])/(run.name+'/S01/first_input.png')).write_bytes(b'changed')
    elif mutation=='first':(folder/'first_input.png').write_bytes(b'changed')
    elif mutation=='source_original':Path(result['files']['audio']['source_path']).write_bytes(b'changed')
    elif mutation=='video':Path(result['files']['video']['path']).write_bytes(b'changed')
    elif mutation=='result_sha':result['direct_reference_slots']=False;put(folder/'RESULT.json',result)
    elif mutation=='native_unknown':state=qa.read(folder/'STATE.json');state['status']='outcome_unknown';put(folder/'STATE.json',state)
    elif mutation=='old_native_id':result['prompt_id']='old_S01';put(folder/'RESULT.json',result);state=qa.read(folder/'STATE.json');state.update(prompt_id='old_S01',result_sha256=qa.sha(folder/'RESULT.json'));put(folder/'STATE.json',state)
    elif mutation=='approval':data=qa.read(run/'LAUNCH_APPROVAL.json');data['plan']['sha256']='0'*64;put(run/'LAUNCH_APPROVAL.json',data)
    monkeypatch.setattr(qa,'command',lambda *a,**k:pytest.fail('tampered binding reached CPU command'))
    with pytest.raises((ValueError,KeyError)):qa.qa_segment(run,'S01',project=tmp_path)


def test_quote_timing_uses_each_asr_actual_tokens_and_does_not_assign_speaker(tmp_path):
    asr=tmp_path/'ASR.json';put(asr,dict(result=[dict(text='甲 哥 哥 发 传 单 挣 了 十 块 先 给 你 乙',timestamp=[[i*100,(i+1)*100] for i in range(14)])]))
    actual,rows=qa.quote_intervals(asr,['哥哥发传单挣了十块，先给你。','未检出心声'])
    assert actual.startswith('甲哥哥') and rows[0]['start_ms']==100 and rows[0]['end_ms']==1300
    assert not rows[1]['exactly_detected'] and rows[1]['start_ms'] is None
    assert not any('speaker' in row for row in rows)


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    folder=tmp_path_factory.mktemp('V32_SYNTHETIC_CPU_FIXTURE')
    for name,frames in [('native',362),('final',1448)]:
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=gray:s=736x1312:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-frames:v',str(frames),'-t',str(frames/24),'-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-video_track_timescale','12288','-movie_timescale','48000',str(folder/(name+'.mp4'))],check=True,timeout=90)
    Image.new('RGB',(736,1312),'gray').save(folder/'native.png')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(362/24),'-c:a','flac',str(folder/'native.flac')],check=True,timeout=30)
    return folder


def test_real_cpu_decode_native_clock_frames_quote_evidence_and_idempotency(tmp_path,media):
    run=fixture(tmp_path);saved(run,'S01',media);folder=run/'qc/S01/new_S01';folder.mkdir(parents=True)
    text='测试对白甲测试对白乙测试对白丙';put(folder/'ASR.json',dict(result=[dict(text=' '.join(text),timestamp=[[i*200,(i+1)*200] for i in range(len(text))])]))
    result=qa.qa_segment(run,'S01',asr=False,project=tmp_path);report=qa.read(result['manifest']['path'])
    assert report['geometry']['decoded_frames']==362 and report['geometry']['decoded_pts_exact_i_over_24']
    assert report['normalized_matches'] is True and len(report['frames'])==6 and len(report['quote_intervals'][1]['frames'])==5
    assert report['production_approved'] is False and report['input_first_pixel_metric']['semantic_pass'] is None
    assert qa.qa_segment(run,'S01',asr=False,project=tmp_path)==result


def test_real_cpu_final_clock_and_three_join_pairs(tmp_path,media):
    run=fixture(tmp_path)
    for sid in qa.IDS:saved(run,sid)
    final=run/'LEGACY_CALL_RESTORE_736x1312.mp4';shutil.copyfile(media/'final.mp4',final)
    inputs=dict(plan=qa.binding(run/'PLAN.json'),results=[qa.binding(run/'shots'/sid/'RESULT.json') for sid in qa.IDS])
    put(run/'FINAL_RESULT.json',dict(schema=qa.SCHEMA,file=qa.binding(final),native_ids=['new_'+s for s in qa.IDS],assembly_inputs_sha256=qa.fingerprint(inputs),production_approved=False,publication=False))
    result=qa.qa_final(run,project=tmp_path);report=qa.read(result['manifest']['path'])
    assert report['clock']['audio_samples']=='2896000' and report['clock']['decoded_frames']==1448
    assert len(report['joins'])==3 and all(j['pixel_metric']['semantic_pass'] is None for j in report['joins'])
    assert qa.qa_final(run,project=tmp_path)==result


def test_no_executor_or_http_imports_and_observer_rejects_wrong_identity(tmp_path):
    tree=ast.parse(Path(qa.__file__).read_text(encoding='utf-8'));names=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):names.extend(a.name for a in node.names)
        elif isinstance(node,ast.ImportFrom):names.append(node.module or '')
    assert not any(any(w in n for w in ('urllib','requests','content_factory','executor','torch')) for n in names)
    run=fixture(tmp_path)
    with pytest.raises(ValueError):qa.observe(run,tmp_path/'data/qa/observer','nativeid','0'*64,max_seconds=1,project=tmp_path)
    assert not (tmp_path/'data/qa/observer').exists()


@pytest.mark.parametrize('status',['outcome_unknown','failed','interrupted','rejected'])
def test_native_failure_stops_only_cpu_observer_and_preserves_original_state(tmp_path,status):
    run=fixture(tmp_path);state=run/'shots/S01/STATE.json';data=qa.read(state);data.update(status=status,prompt_id='known_original');put(state,data);before=qa.binding(state);directory=tmp_path/'data/qa/observer'
    with pytest.raises(ValueError,match='original native task stopped'):
        qa.observe(run,directory,'known_original',qa.sha(qa.__file__),max_seconds=1,project=tmp_path)
    report=qa.read(directory/'PROGRESS.json')
    assert report['status']=='cpu_observer_stopped' and qa.binding(state)==before
    assert report['known_native_ids']=={'S01':'known_original'} and not (run/'shots/S01/CLAIM.json').exists()
    identity=qa.binding(directory/'OBSERVER.json')
    with pytest.raises(FileExistsError):qa.observe(run,directory,'known_original',qa.sha(qa.__file__),max_seconds=1,project=tmp_path)
    assert qa.binding(directory/'OBSERVER.json')==identity


def test_bound_observer_returns_without_claiming_running_video_or_changing_native_state(tmp_path):
    run=fixture(tmp_path);state=run/'shots/S01/STATE.json';data=qa.read(state);data.update(status='running',prompt_id='known_original');put(state,data);before=qa.binding(state);directory=tmp_path/'data/qa/observer'
    qa.observe(run,directory,'known_original',qa.sha(qa.__file__),max_seconds=1,project=tmp_path)
    report=qa.read(directory/'PROGRESS.json')
    assert report['status']=='bounded_wait_original_ids_preserved' and report['completed']==[] and qa.binding(state)==before
    assert not (run/'qc').exists() and not (run/'shots/S01/CLAIM.json').exists()


def test_observer_known_original_id_cannot_silently_switch(tmp_path):
    run=fixture(tmp_path);state=run/'shots/S01/STATE.json';data=qa.read(state);data.update(status='running',prompt_id='different');put(state,data)
    with pytest.raises(ValueError,match='original native ID changed'):qa.observe(run,tmp_path/'data/qa/observer','known_original',qa.sha(qa.__file__),max_seconds=1,project=tmp_path)


def test_real_cli_unknown_task_writes_only_cpu_evidence_then_exits(tmp_path):
    run=fixture(tmp_path);state=run/'shots/S01/STATE.json';data=qa.read(state);data.update(status='outcome_unknown',prompt_id='known_original');put(state,data);before={str(p):qa.sha(p) for p in run.rglob('*') if p.is_file()};directory=tmp_path/'data/qa/observer'
    project=Path(qa.PROJECT);process=subprocess.run([str(project/'.venv/Scripts/python.exe'),'-X','utf8','-B',str(Path(qa.__file__).resolve()),'observe','--run',str(run),'--project-root',str(tmp_path),'--observer-dir',str(directory),'--first-native-id','known_original','--helper-sha256',qa.sha(qa.__file__),'--max-seconds','1'],capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert process.returncode==2 and json.loads(process.stdout)['status']=='cpu_qa_failed'
    assert before=={str(p):qa.sha(p) for p in run.rglob('*') if p.is_file()}
    assert qa.read(directory/'PROGRESS.json')['status']=='cpu_observer_stopped'
