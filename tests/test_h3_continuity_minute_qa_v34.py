"""Synthetic file protocol and real CPU FFmpeg checks; no H3/VL inference."""
from copy import deepcopy
from pathlib import Path
import ast,json,shutil,subprocess
import pytest
from PIL import Image
from scripts import qa_h3_continuity_minute_v34 as qa

def put(p,v):qa.write(p,v);return qa.bind(p)
def text_sha(t):return __import__('hashlib').sha256(t.encode()).hexdigest()

def graph_template():
    def n(k,**kw):return dict(class_type=k,inputs=kw)
    return {'119':n('VAELoader',vae_name='minimax_h3_video_vae_int8_convrot.safetensors'),
      '120':n('VAELoader',vae_name='minimax_h3_audio_vae_fp32.safetensors'),
      '127':n('UNETLoader',unet_name='minimax_h3_fl2va_pruned_int8_convrot.safetensors',weight_dtype='default'),
      '128':n('CLIPLoader',clip_name='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',type='minimax',device='default'),
      '123':n('KSamplerSelect',sampler_name='res_multistep'),'124':n('BasicScheduler',model=['127',0],scheduler='simple',steps=12,denoise=1),
      '129':n('RandomNoise',noise_seed=1),'ref_scene':n('LoadImage',image='old.png'),
      'condition':n('MiniMaxH3ImageToVideo',clip=['128',0],vae=['119',0],prompt='template',width=736,height=1312,length=362,first_frame=['ref_scene',0]),
      '126':n('BasicGuider',model=['127',0],conditioning=['condition',0]),
      '125':n('SamplerCustomAdvanced',noise=['129',0],guider=['126',0],sampler=['123',0],sigmas=['124',0],latent_image=['condition',1]),
      '122':n('VAEDecodeTiled',samples=['125',0],vae=['119',0],tile_size=512,overlap=64,temporal_size=64,temporal_overlap=8),
      'pick_first':n('ImageFromBatch',image=['122',0],batch_index=0,length=1),'pick_last':n('ImageFromBatch',image=['122',0],batch_index=361,length=1),
      '121':n('VAEDecodeAudio',samples=['125',0],vae=['120',0]),'130':n('CreateVideo',images=['122',0],audio=['121',0],fps=24),
      'save_first':n('SaveImage',images=['pick_first',0],filename_prefix='old/first'),'save_last':n('SaveImage',images=['pick_last',0],filename_prefix='old/last'),
      'save_audio':n('SaveAudio',audio=['121',0],filename_prefix='old/audio'),'save_video':n('SaveVideo',video=['130',0],filename_prefix='old/video',format='mp4',**{'format.codec':'auto'})}

def entry(root,sid):
    folder=root/'source'/sid;folder.mkdir(parents=True);refs={}
    for who,color in [('su_mo','gray'),('ye_nan','green'),('ye_xijue','beige'),('room','brown'),('first','gray')]:
        path=folder/(who+'.png');Image.new('RGB',(736,1312),color).save(path);refs[who]=qa.bind(path)
    pieces=[('context','苏墨是父亲。'),('context','叶南是哥哥。'),('context','叶西决是弟弟。'),('context','苏墨坐在床沿，叶南站在床边，叶西决站在床边。'),('camera','0—15秒，'),('action','苏墨转头看向孩子，说：')]
    expected=['测试对白甲','测试对白乙','测试对白丙'][:qa.COUNTS[qa.IDS.index(sid)]]
    pieces.extend(('audio','“'+q+'”') for q in expected);source=''.join(t for _,t in pieces);path=folder/'source.txt';path.write_text(source,encoding='utf-8');spans=[];at=0
    for i,(kind,text) in enumerate(pieces):spans.append(dict(id='s'+str(i),kind=kind,start=at,end=at+len(text),text=text,sha256=text_sha(text)));at+=len(text)
    row=dict(shot_id=sid,handoff_binding=None,source=qa.bind(path),source_scope=dict(start=0,end=len(source)),source_spans=spans,duration=15,
      camera_beats=[dict(start=0,end=15,cut=False,framing='medium',actors={who:dict(visible_parts=['face','torso'],pose='坐在床沿' if who=='su_mo' else '站在床边') for who in ('su_mo','ye_nan','ye_xijue')},source_span_ids=['s5'])],
      audio=[dict(quote_index=i,quote_sha256=text_sha('“'+q+'”'),speaker='su_mo',mode='onscreen',start=i*4,end=i*4+3) for i,q in enumerate(expected)],character_names=dict(su_mo='苏墨',ye_nan='叶南',ye_xijue='叶西决'),canonical_characters={k:refs[k] for k in ('su_mo','ye_nan','ye_xijue')},canonical_room=refs['room'],actual_first_image=refs['first'],source_state_span_ids=['s3'],character_description_span_ids=dict(su_mo=['s0'],ye_nan=['s1'],ye_xijue=['s2']),postproduction_subtitles=False)
    review=dict(schema='h3_continuity_coverage_review/v33',reviewed_by='Synthetic CPU fixture only',target_image=refs['first'],canonical_characters=row['canonical_characters'],canonical_room=refs['room'],completion_known=True,outcome_unknown=False,checks=dict(topology_coherent=True,room_identity=True,faces={k:True for k in row['canonical_characters']},identities={k:True for k in row['canonical_characters']}),evidence=['Synthetic protocol fixture, no production semantic qualification.'])
    row['coverage_review']=put(folder/'review.json',review);return row

def fixture(root,media=None):
    minute=root/qa.ROOT;minute.mkdir(parents=True);pause=put(root/'old/PAUSE.json',dict(paused=True));base=put(root/'base.json',graph_template());templates={};all_native=[]
    for sid in qa.IDS:
        row=entry(root,sid);compiled=qa.compile_prompt(row);spec=put(minute/'segments'/sid/'EXECUTABLE_SPEC.json',dict(schema='h3_continuity_input/v33',shots=[row]));templates[sid]=put(minute/'templates'/(sid+'.json'),{k:v for k,v in row.items() if k not in ('actual_first_image','coverage_review','reanchor','handoff_binding')})
        run=minute/'visual_h3_v3'/(minute.name+'_'+sid);folder=run/'shots'/sid;scope='visual_h3_v3/'+run.name+'/'+sid;input_name=scope+'/first_frame.png';cfg=dict(width=736,height=1312,input_root=str(root/'input'),output_root=str(root/'output'),base_workflow=base['path'],continuity_input_plan=spec)
        staged=root/'input'/input_name;staged.parent.mkdir(parents=True);shutil.copyfile(row['actual_first_image']['path'],staged)
        proof=dict(schema='h3_continuity_input/v33',plan=spec,entry_sha256=qa.digest(row),first_image=row['actual_first_image'],coverage_review=row['coverage_review'],generation_receipt=None,compiled_prompt_utf8_sha256=compiled['compiled_prompt_utf8_sha256'])
        timing=dict(native_frames=362,requested_seconds=15);binding_sha=qa.digest(dict(sid=sid,source=row['source']));first=dict(row['actual_first_image'],binding_sha256=binding_sha)
        graph=graph_template();graph['ref_scene']['inputs']={'image':input_name};graph['condition']['inputs']['prompt']=compiled['compiled_prompt'];graph['129']['inputs']['noise_seed']=int(qa.digest(dict(shot=binding_sha,frame=first['sha256']))[:14],16)
        for role in qa.ROLES:graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
        shot=dict(id=sid,timing=timing,scope=scope,input_name=input_name,binding_sha256=binding_sha,first_frame=first,graph_sha256=qa.digest(graph),continuity_input=proof,subtitles=dict(enabled=False))
        plan=dict(schema='visual_h3_handoff/v3',upstream_contract='h3_continuity_input/v33',continuity_source_plan=spec,config=cfg,base_workflow_sha256=base['sha256'],protected_pause=pause,shots=[shot],publication=False,old_batch_resume=False)
        put(run/'PLAN.json',plan);put(run/'STATE.json',dict(plan_sha256=qa.digest(plan)));put(folder/'workflow_api.json',graph);put(folder/'REQUEST.json',dict(prompt=graph,client_id='fixture'));put(folder/'CLAIM.json',dict(graph_sha256=qa.digest(graph),first_frame_sha256=first['sha256']));pid='synthetic_new_'+sid;put(folder/'RESPONSE.json',dict(prompt_id=pid,node_errors={}))
        outputs={};files={}
        for role in qa.ROLES:
            suffix='.mp4' if role=='video' else '.flac' if role=='audio' else '.png';name=role+'_00001_'+suffix;original=root/'output'/scope/name;original.parent.mkdir(parents=True,exist_ok=True)
            if media:
                shutil.copyfile(media/('native'+suffix),original)
                if role=='video':
                    with original.open('ab') as stream:stream.write(('SYNTHETIC_'+sid).encode())
            elif suffix=='.png':Image.new('RGB',(736,1312),'gray').save(original)
            else:original.write_bytes((sid+role+'synthetic protocol fixture').encode())
            copy=folder/'artifacts'/name;copy.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,copy);files[role]=dict(path=str(copy),sha256=qa.sha(copy),source_path=str(original));outputs['save_'+role]={'audio' if role=='audio' else 'images':[dict(filename=name,type='output',subfolder=scope)]}
        observed=deepcopy(graph);observed['124']['inputs']['denoise']=1.0;observed['130']['inputs']['fps']=24.0;put(folder/'HISTORY.json',{pid:dict(prompt=[1,pid,observed],status=dict(completed=True,status_str='success'),outputs=outputs)})
        put(folder/'RESULT.json',dict(schema='visual_h3_handoff/v3',shot_id=sid,prompt_id=pid,graph_sha256=qa.digest(graph),first_frame_sha256=first['sha256'],continuity_input=proof,timing=timing,files=files,technical_status='technical_saved',production_approved=False,publication=False));put(folder/'STATE.json',dict(id=sid,status='technical_saved',prompt_id=pid,plan_sha256=qa.digest(plan)))
        put(minute/'segments'/sid/'VIDEO_BINDING.json',dict(schema='h3_continuity_minute_video_binding/v34',segment=sid,shot_id=sid,h3_run=str(run),segment_spec=spec,h3_plan=qa.bind(run/'PLAN.json')));all_native.append(run)
    put(minute/'PLAN.json',dict(schema='h3_continuity_minute/v34',profile=dict(width=736,height=1312,frames=362,fps=24),templates=templates,protected_pause=pause))
    return minute,all_native

def args(minute,sid):
    mapping=qa.read(minute/'segments'/sid/'VIDEO_BINDING.json');return dict(h3_run=mapping['h3_run'],segment_spec=mapping['segment_spec']['path'])

def test_explicit_mapping_three_faces_native_recipe_and_no_write_on_validate(tmp_path):
    minute,runs=fixture(tmp_path);before={str(p):qa.sha(p) for p in tmp_path.rglob('*') if p.is_file()};value=qa.validate(minute,'S01',project=tmp_path,**args(minute,'S01'))
    assert value['result']['prompt_id']=='synthetic_new_S01' and value['compiled']['required_faces']==['su_mo','ye_nan','ye_xijue']
    assert before=={str(p):qa.sha(p) for p in tmp_path.rglob('*') if p.is_file()}

@pytest.mark.parametrize('mutation',['mapped_run','spec_hash','plan_hash','native_unknown','request','response','claim','history','history_output','first_stage','original_audio','copied_video','canonical','review_unknown','template','pause'])
def test_frozen_mapping_originals_and_false_reviews_fail_before_decode(tmp_path,monkeypatch,mutation):
    minute,runs=fixture(tmp_path);run=runs[0];folder=run/'shots/S01';map_path=minute/'segments/S01/VIDEO_BINDING.json';mapping=qa.read(map_path);plan=qa.read(run/'PLAN.json');spec=qa.read(mapping['segment_spec']['path']);row=spec['shots'][0]
    if mutation=='mapped_run':mapping['h3_run']=str(runs[1]);put(map_path,mapping)
    elif mutation=='spec_hash':mapping['segment_spec']['sha256']='0'*64;put(map_path,mapping)
    elif mutation=='plan_hash':mapping['h3_plan']['sha256']='0'*64;put(map_path,mapping)
    elif mutation=='native_unknown':state=qa.read(folder/'STATE.json');state['status']='outcome_unknown';put(folder/'STATE.json',state)
    elif mutation=='request':data=qa.read(folder/'REQUEST.json');data['prompt']['condition']['inputs']['prompt']+='新增台词';put(folder/'REQUEST.json',data)
    elif mutation=='response':put(folder/'RESPONSE.json',dict(prompt_id='wrong'))
    elif mutation=='claim':data=qa.read(folder/'CLAIM.json');data['first_frame_sha256']='0'*64;put(folder/'CLAIM.json',data)
    elif mutation=='history':data=qa.read(folder/'HISTORY.json');data['synthetic_new_S01']['prompt'][2]['129']['inputs']['noise_seed']=0;put(folder/'HISTORY.json',data)
    elif mutation=='history_output':data=qa.read(folder/'HISTORY.json');data['synthetic_new_S01']['outputs']['save_last']['images'][0]['subfolder']='old';put(folder/'HISTORY.json',data)
    elif mutation=='first_stage':(Path(plan['config']['input_root'])/plan['shots'][0]['input_name']).write_bytes(b'changed')
    elif mutation=='original_audio':Path(qa.read(folder/'RESULT.json')['files']['audio']['source_path']).write_bytes(b'changed')
    elif mutation=='copied_video':Path(qa.read(folder/'RESULT.json')['files']['video']['path']).write_bytes(b'changed')
    elif mutation=='canonical':Path(row['canonical_characters']['su_mo']['path']).write_bytes(b'changed')
    elif mutation=='review_unknown':review=qa.read(row['coverage_review']['path']);review['checks']['identities']['su_mo']=None;put(row['coverage_review']['path'],review)
    elif mutation=='template':path=minute/'templates/S01.json';data=qa.read(path);data['audio'][0]['speaker']='ye_nan';put(path,data)
    elif mutation=='pause':Path(plan['protected_pause']['path']).write_bytes(b'changed')
    monkeypatch.setattr(qa,'command',lambda *a,**k:pytest.fail('tampered native data reached CPU decoder'))
    with pytest.raises((ValueError,KeyError)):qa.qa_segment(minute,'S01',project=tmp_path,**args(minute,'S01'))

def test_cli_cannot_select_another_existing_segment_or_prior_minute(tmp_path):
    minute,runs=fixture(tmp_path)
    with pytest.raises(ValueError):qa.mapped(minute,'S01',h3_run=runs[1],project=tmp_path)
    with pytest.raises(ValueError):qa.mapped(tmp_path/'data/video_generation/h3_legacy_call_restore_20261108_v1','S01',project=tmp_path)

@pytest.mark.parametrize('field,value',[('actual_seed',0),('actual_seed',False),('prompt_utf8_sha256','0'*64),('selected_first',{'path':'unknown','sha256':'0'*64})])
def test_optional_audit_fields_cannot_contradict_actual_input_or_seed(tmp_path,field,value):
    minute,runs=fixture(tmp_path);path=minute/'segments/S01/VIDEO_BINDING.json';mapping=qa.read(path);mapping[field]=value;put(path,mapping)
    with pytest.raises(ValueError):qa.validate(minute,'S01',project=tmp_path)

def test_initial_actual_context_binding_is_checked_without_inference(tmp_path):
    minute,runs=fixture(tmp_path);path=minute/'segments/S01/VIDEO_BINDING.json';mapping=qa.read(path);spec=qa.read(mapping['segment_spec']['path'])['shots'][0];context=put(minute/'segments/S01/CONTEXT.json',dict(schema='h3_minute_actual_context/v34',shot_id='S01',image=spec['actual_first_image'],origin=dict(kind='approved_initial_context_only'),source_template=qa.read(minute/'PLAN.json')['templates']['S01']));mapping['context']=context;put(path,mapping);qa.validate(minute,'S01',project=tmp_path)
    data=qa.read(context['path']);data['origin']['kind']='arbitrary_old_tail';put(context['path'],data);mapping['context']=qa.bind(context['path']);put(path,mapping)
    with pytest.raises(ValueError):qa.validate(minute,'S01',project=tmp_path)

def test_cut_dense_sampling_uses_planned_cut_plus_actual_risk_windows():
    entry=dict(camera_beats=[dict(start=0,end=12,cut=False),dict(start=12,end=15,cut=True)])
    regions=qa.dense_indices(entry,'S02');assert regions[0]['indices']==list(range(276,301,3))
    assert regions[1]['indices']==list(range(276,337,3))
    assert qa.dense_indices(entry,'S04')[-1]['indices']==list(range(0,121,3))
    assert all('PLANNED' in r['label'] for r in regions[:1])

def test_history_rejects_boolean_and_arbitrary_float_normalization():
    graph=graph_template();native=deepcopy(graph);native['124']['inputs']['denoise']=1.0;native['130']['inputs']['fps']=24.0;qa.native_graph(graph,native)
    native['129']['inputs']['noise_seed']=1.0
    with pytest.raises(ValueError):qa.native_graph(graph,native)
    native=deepcopy(graph);native['124']['inputs']['denoise']=True
    with pytest.raises(ValueError):qa.native_graph(graph,native)

def test_asr_unrecognized_quote_does_not_become_false_detected_or_identity(tmp_path):
    path=tmp_path/'ASR.json';put(path,dict(result=[dict(text='测 试 对 白 甲',timestamp=[[i*100,i*100+100] for i in range(5)])]))
    text,rows=qa.asr_intervals(path,['测试对白甲','孩子未检出心声'])
    assert text=='测试对白甲' and rows[0]['start_ms']==0 and rows[0]['end_ms']==500
    assert rows[1]['start_ms'] is None and rows[1]['exactly_detected'] is False and not any('speaker' in r for r in rows)

@pytest.fixture(scope='module')
def media(tmp_path_factory):
    path=tmp_path_factory.mktemp('V34_CPU_SYNTHETIC_MEDIA')
    for name,frames in [('native',362),('final',1448)]:
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=gray:s=736x1312:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-frames:v',str(frames),'-t',str(frames/24),'-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-video_track_timescale','12288','-movie_timescale','48000',str(path/(name+'.mp4'))],check=True,timeout=90)
    Image.new('RGB',(736,1312),'gray').save(path/'native.png');subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(362/24),'-c:a','flac',str(path/'native.flac')],check=True,timeout=30)
    return path

def test_real_cpu_native_contacts_asr_intervals_and_risk_window_are_idempotent(tmp_path,media):
    minute,runs=fixture(tmp_path,media);sid='S02';pid='synthetic_new_'+sid;folder=minute/'qc'/sid/pid;folder.mkdir(parents=True);text='测试对白甲测试对白乙';put(folder/'ASR.json',dict(result=[dict(text=' '.join(text),timestamp=[[i*200,i*200+200] for i in range(len(text))])]))
    result=qa.qa_segment(minute,sid,project=tmp_path,**args(minute,sid));report=qa.read(result['manifest']['path'])
    assert len(report['frames'])==6 and len(report['dense_regions'][0]['actual_frames'])==21 and len(report['quote_intervals'][1]['frames'])==5
    assert report['geometry']['decoded_frames']==362 and report['normalized_matches'] is True
    assert all(v is None for k,v in report['visual_observation'].items() if k!='status') and report['production_approved'] is False
    assert qa.qa_segment(minute,sid,project=tmp_path,**args(minute,sid))==result

def test_real_cli_receipt_and_readonly_unknown_error(tmp_path,media):
    minute,runs=fixture(tmp_path,media);native=qa.read(runs[0]/'shots/S01/STATE.json');native['status']='outcome_unknown';put(runs[0]/'shots/S01/STATE.json',native);before={str(p):qa.sha(p) for p in minute.rglob('*') if p.is_file()};parameters=args(minute,'S01');argv=[str(qa.PROJECT/'.venv/Scripts/python.exe'),'-X','utf8','-B',str(Path(qa.__file__).resolve()),'segment','--minute-root',str(minute),'--segment','S01','--h3-run',parameters['h3_run'],'--segment-spec',parameters['segment_spec'],'--project-root',str(tmp_path)]
    failed=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert failed.returncode==2 and json.loads(failed.stdout)['no_media_retry'] is True
    assert before=={str(p):qa.sha(p) for p in minute.rglob('*') if p.is_file()}
    native['status']='technical_saved';put(runs[0]/'shots/S01/STATE.json',native);done=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert done.returncode==0,done.stdout+done.stderr
    value=json.loads(done.stdout);assert value['status']=='cpu_qa_complete' and Path(value['manifest']['path']).is_file() and value['native_id']=='synthetic_new_S01'

def test_real_cpu_full_minute_clock_sources_joins_and_dense_final_windows(tmp_path,media):
    minute,runs=fixture(tmp_path,media);results=[qa.bind(r/'shots'/sid/'RESULT.json') for r,sid in zip(runs,qa.IDS)];values=[qa.read(r['path']) for r in results];output=minute/'H3_CONTINUITY_MINUTE_736x1312.mp4';shutil.copyfile(media/'final.mp4',output);inputs=dict(plan=qa.bind(minute/'PLAN.json'),results=results)
    put(minute/'FINAL_RESULT.json',dict(schema='h3_continuity_minute/v34',file=qa.bind(output),native_ids=[v['prompt_id'] for v in values],segment_results=results,source_videos=[{k:v['files']['video'][k] for k in ('path','sha256')} for v in values],assembly_inputs_sha256=qa.digest(inputs),production_approved=False,publication=False))
    result=qa.qa_final(minute,project=tmp_path);report=qa.read(result['manifest']['path'])
    assert report['clock']['decoded_frames']==1448 and report['clock']['effective_audio_samples']=='2896000'
    assert len(report['joins'])==3 and len(report['source_clocks'])==4
    assert [(r['start'],r['end'],len(r['actual_frames'])) for r in report['dense_regions']]==[(24,29,41),(47,52,41)]
    assert all(j['semantic_continuity'] is None for j in report['joins']) and report['visual_observation']['native_subtitles'] is None
    assert qa.qa_final(minute,project=tmp_path)==result

def test_script_imports_no_dispatcher_http_or_old_validator():
    tree=ast.parse(Path(qa.__file__).read_text(encoding='utf-8'));names=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):names.extend(x.name for x in node.names)
        elif isinstance(node,ast.ImportFrom):names.append(node.module or '')
    assert not any(any(s in name for s in ['urllib','requests','handoff','minute_v34','qa_h3_legacy_call_restore_v32','torch']) for name in names)
