"""CPU-only checks of explicit v34 minute mappings and actual H3 originals.

No dispatcher imports or HTTP. The pure v33 text compiler is used to compare
frozen source/camera/audio bytes with the actual native request, never to infer
visual approval. CPU samples and ASR do not identify people or detect subtitles.
"""
import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib,json,re,sys,uuid
from pathlib import Path
from PIL import Image,ImageDraw
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.qa_h3_reference_full_minute_cpu import command,probe,transcribe
from src.content_factory.visual_h3_continuity_input_v33 import compile_prompt

PROJECT=Path(__file__).resolve().parents[1]
ROOT='data/video_generation/h3_continuity_full_minute_20261109_v1'
IDS=('S01','S02','S03','S04');COUNTS=(3,2,2,3);ROLES=('video','audio','first','last')
SCHEMA='h3_continuity_minute_cpu_qa/v34'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def bind(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def inside(root,p):
    root=Path(root).resolve();p=Path(p).resolve()
    if p==root or not p.is_relative_to(root):raise ValueError('outside explicit QA scope')
    return p
def check(value,root):
    if not isinstance(value,dict) or set(value)!={'path','sha256'}:raise ValueError('physical binding required')
    p=inside(root,value['path'])
    if bind(p)!=value:raise ValueError('bound source changed')
    return p
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def freeze(p,v):
    if Path(p).exists():
        if digest(read(p))!=digest(v):raise ValueError('CPU evidence changed; preserve original report')
    else:write(p,v)
def bound_tree(value,project):
    if isinstance(value,dict):
        if {'path','sha256'}<=set(value):check({k:value[k] for k in ('path','sha256')},project)
        for v in value.values():bound_tree(v,project)
    elif isinstance(value,list):
        for v in value:bound_tree(v,project)
def norm(t):return ''.join(c for c in t if c.isalnum())

def native_graph(expected,observed):
    value=deepcopy(observed)
    for node,key in [('124','denoise'),('130','fps')]:
        actual=value.get(node,{}).get('inputs',{}).get(key);wanted=expected.get(node,{}).get('inputs',{}).get(key)
        if type(actual) is float and type(wanted) is int and actual==wanted:value[node]['inputs'][key]=wanted
    if digest(value)!=digest(expected):raise ValueError('actual native history graph changed')

def mapped(minute,sid,*,h3_run=None,segment_spec=None,project=PROJECT):
    project=Path(project).resolve();minute=Path(minute).resolve()
    if minute!=project/ROOT or sid not in IDS:raise ValueError('explicit new minute and ordered segment required')
    path=minute/'segments'/sid/'VIDEO_BINDING.json';mapping=read(path)
    if mapping.get('schema')!='h3_continuity_minute_video_binding/v34' or mapping.get('segment')!=sid or mapping.get('shot_id')!=sid:raise ValueError('explicit video mapping schema/shot required')
    run=inside(minute/'visual_h3_v3',mapping['h3_run'])
    if run!=minute/'visual_h3_v3'/(minute.name+'_'+sid):raise ValueError('new per-segment native namespace required')
    spec=check(mapping['segment_spec'],project);inside(minute/'segments'/sid,spec)
    if check(mapping['h3_plan'],project)!=run/'PLAN.json':raise ValueError('mapped native PLAN differs')
    if h3_run is not None and Path(h3_run).resolve()!=run:raise ValueError('CLI native run differs from mapping')
    if segment_spec is not None and Path(segment_spec).resolve()!=spec:raise ValueError('CLI segment spec differs from mapping')
    return minute,run,spec,mapping,path

def validate(minute,sid,*,h3_run=None,segment_spec=None,project=PROJECT):
    project=Path(project).resolve();minute,run,spec,mapping,mapping_path=mapped(minute,sid,h3_run=h3_run,segment_spec=segment_spec,project=project)
    plan=read(run/'PLAN.json');cfg=plan['config'];spec_value=read(spec)
    if spec_value.get('schema')!='h3_continuity_input/v33' or len(spec_value.get('shots',[]))!=1 or spec_value['shots'][0]['shot_id']!=sid:raise ValueError('one source-bound v33 segment required')
    entry=spec_value['shots'][0];compiled=compile_prompt(entry)
    minute_plan=read(minute/'PLAN.json');profile=minute_plan.get('profile',{})
    if minute_plan.get('schema')!='h3_continuity_minute/v34' or tuple(profile.get(k) for k in ('width','height','frames','fps'))!=(736,1312,362,24):raise ValueError('frozen minute profile differs')
    template=read(check(minute_plan['templates'][sid],project))
    if digest({k:v for k,v in entry.items() if k not in ('actual_first_image','coverage_review','reanchor','handoff_binding')})!=digest(template):raise ValueError('accepted segment changed the frozen source/camera/audio template')
    if not compiled['source_coverage_complete'] or entry['duration']!=15 or len(entry['audio'])!=COUNTS[IDS.index(sid)]:raise ValueError('complete 15s source with original dialogue required')
    source=check(entry['source'],project).read_text(encoding='utf-8');scope=entry['source_scope'];source=source[scope['start']:scope['end']]
    source_quotes=re.findall('“[^”]*”|「[^」]*」',source);expected=[source_quotes[a['quote_index']][1:-1] for a in entry['audio']]
    if (plan.get('schema')!='visual_h3_handoff/v3' or plan.get('upstream_contract')!='h3_continuity_input/v33'
        or plan.get('continuity_source_plan')!=bind(spec) or cfg.get('continuity_input_plan')!=bind(spec)
        or plan.get('publication') is not False or plan.get('old_batch_resume') is not False or len(plan['shots'])!=1):raise ValueError('native continuity PLAN contract differs')
    row=plan['shots'][0];folder=run/'shots'/sid;state=read(folder/'STATE.json');result=read(folder/'RESULT.json');graph=read(folder/'workflow_api.json');pid=result.get('prompt_id')
    if (row['id']!=sid or state.get('id')!=sid or state.get('status')!='technical_saved' or state.get('plan_sha256')!=digest(plan)
        or read(run/'STATE.json').get('plan_sha256')!=digest(plan) or result.get('technical_status')!='technical_saved'
        or result.get('shot_id')!=sid or not isinstance(pid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',pid) or state.get('prompt_id')!=pid
        or result.get('production_approved') is not False or result.get('publication') is not False or result.get('schema')!='visual_h3_handoff/v3'):raise ValueError('new native terminal identity differs')
    if (row['timing']['native_frames']!=362 or row['timing']['requested_seconds']!=15 or result.get('timing')!=row['timing']
        or cfg.get('width')!=736 or cfg.get('height')!=1312 or row.get('subtitles',{}).get('enabled') is not False):raise ValueError('native geometry/timing/subtitle track changed')
    proof=row['continuity_input'];selected=entry.get('reanchor',{}).get('image',entry['actual_first_image']);review_ref=entry.get('reanchor',{}).get('coverage_review',entry['coverage_review']);review=read(check(review_ref,project))
    if ('selected_first' in mapping and mapping['selected_first']!=selected or 'prompt_utf8_sha256' in mapping and mapping['prompt_utf8_sha256']!=compiled['compiled_prompt_utf8_sha256']):raise ValueError('optional mapped selected image/prompt differs')
    if 'context' in mapping:
        context=read(check(mapping['context'],project));origin=context.get('origin',{})
        if context.get('schema')!='h3_minute_actual_context/v34' or context.get('shot_id')!=sid or context.get('image')!=entry['actual_first_image'] or context.get('source_template')!=minute_plan['templates'][sid]:raise ValueError('actual context/template mapping differs')
        if sid!='S01':
            previous=IDS[IDS.index(sid)-1];prior_path=minute/'visual_h3_v3'/(minute.name+'_'+previous)/'shots'/previous/'RESULT.json';prior=read(check(origin['native_result'],project))
            if Path(origin['native_result']['path']).resolve()!=prior_path or origin.get('kind')!='actual_previous_native_tail' or origin.get('previous_segment')!=previous or origin.get('native_id')!=prior['prompt_id'] or origin.get('role')!='last' or context['image']!={k:prior['files']['last'][k] for k in ('path','sha256')}:raise ValueError('context is not this minute predecessor original tail')
        elif origin.get('kind')!='approved_initial_context_only':raise ValueError('initial context role differs')
    if (proof.get('schema')!='h3_continuity_input/v33' or proof.get('plan')!=bind(spec) or proof.get('entry_sha256')!=digest(entry)
        or proof.get('first_image')!=selected or proof.get('coverage_review')!=review_ref or proof.get('compiled_prompt_utf8_sha256')!=compiled['compiled_prompt_utf8_sha256']
        or result.get('continuity_input')!=proof or {k:row['first_frame'][k] for k in ('path','sha256')}!=selected or result.get('first_frame_sha256')!=selected['sha256']):raise ValueError('actual reviewed first-image/continuity proof differs')
    check(selected,project);bound_tree(entry['canonical_characters'],project);check(entry['canonical_room'],project)
    checks=review.get('checks',{});keys=set(entry['canonical_characters'])
    if (review.get('schema')!='h3_continuity_coverage_review/v33' or review.get('target_image')!=selected
        or review.get('canonical_characters')!=entry['canonical_characters'] or review.get('canonical_room')!=entry['canonical_room']
        or review.get('completion_known') is not True or review.get('outcome_unknown') is not False or checks.get('topology_coherent') is not True
        or checks.get('room_identity') is not True or set(checks.get('faces',{}))!=keys or set(checks.get('identities',{}))!=keys
        or any(checks['faces'][c] is not True or checks['identities'][c] is not True for c in compiled['required_faces'])):raise ValueError('required actual image review is false/unknown/mismatched')
    if entry.get('reanchor'):
        anchor=entry['reanchor'];bound_tree(anchor['generation_receipt'],project)
        if proof.get('generation_receipt') is None or anchor.get('work_order_sha256')!=review.get('work_order_sha256') or review.get('source_current_state_matches') is not True:raise ValueError('same-work-order reanchor evidence required')
    if plan['protected_pause']!=minute_plan['protected_pause']:raise ValueError('protected pause differs from minute')
    check(plan['protected_pause'],project);base=read(cfg['base_workflow'])
    if sha(cfg['base_workflow'])!=plan['base_workflow_sha256']:raise ValueError('native base recipe changed')
    expected_graph=deepcopy(base);input_name=row['input_name'];output_scope=row['scope']
    if output_scope!='visual_h3_v3/'+run.name+'/'+sid or input_name not in [output_scope+'/first_frame.png',output_scope+'/first_frame.jpeg',output_scope+'/first_frame.jpg']:raise ValueError('native input/output scope changed')
    expected_graph['ref_scene']['inputs']={'image':input_name};ci=expected_graph['condition']['inputs'];ci.pop('last_frame',None);ci.update(prompt=compiled['compiled_prompt'],length=362,first_frame=['ref_scene',0],width=736,height=1312)
    expected_graph['129']['inputs']['noise_seed']=int(digest(dict(shot=row['binding_sha256'],frame=selected['sha256']))[:14],16)
    expected_graph['pick_first']['inputs']['batch_index']=0;expected_graph['pick_last']['inputs']['batch_index']=361
    for role in ROLES:expected_graph['save_'+role]['inputs']['filename_prefix']=output_scope+'/'+role
    if (graph['condition']['class_type']!='MiniMaxH3ImageToVideo' or graph['127']['inputs']['unet_name']!='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
        or graph['128']['inputs']['clip_name']!='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'
        or [k for k,n in graph.items() if n['class_type']=='LoadImage']!=['ref_scene']
        or any(n['class_type'] in ('MiniMaxH3AddGuide','MiniMaxH3ReferenceToVideo') for n in graph.values())
        or any(k.startswith('ref_') or k=='last_frame' for k in graph['condition']['inputs'])
        or graph['124']['inputs']['steps']!=12 or graph['130']['inputs']['fps']!=24 or digest(graph)!=digest(expected_graph)
        or digest(graph)!=row['graph_sha256'] or result.get('graph_sha256')!=row['graph_sha256']):raise ValueError('actual first-only native graph or compiled prompt changed')
    if 'actual_seed' in mapping and (type(mapping['actual_seed']) is not int or mapping['actual_seed']!=graph['129']['inputs']['noise_seed']):raise ValueError('mapped actual seed differs')
    request=read(folder/'REQUEST.json');claim=read(folder/'CLAIM.json');response=read(folder/'RESPONSE.json')
    if (digest(request.get('prompt'))!=digest(graph) or claim.get('graph_sha256')!=digest(graph) or claim.get('first_frame_sha256')!=selected['sha256'] or response.get('prompt_id')!=pid or response.get('node_errors')):raise ValueError('original POST claim/request/response differs')
    if sha(inside(cfg['input_root'],Path(cfg['input_root'])/input_name))!=selected['sha256']:raise ValueError('actual staged native first image changed')
    history=read(folder/'HISTORY.json')[pid]
    if history['prompt'][1]!=pid or history['status'].get('completed') is not True or history['status'].get('status_str')!='success':raise ValueError('successful original native history required')
    native_graph(graph,history['prompt'][2])
    if set(result.get('files',{}))!=set(ROLES):raise ValueError('four native originals required')
    for role in ROLES:
        item=result['files'][role];path=inside(folder/'artifacts',item['path']);original=inside(cfg['output_root'],item['source_path']);record=history['outputs']['save_'+role]['audio' if role=='audio' else 'images']
        if len(record)!=1 or record[0].get('type')!='output' or record[0].get('filename')!=path.name or record[0].get('subfolder','').replace('\\','/')!=output_scope or original.parent!=Path(cfg['output_root'])/output_scope or original.name!=path.name or sha(path)!=item['sha256'] or sha(original)!=item['sha256']:raise ValueError('actual native original/source/history SHA differs')
        if role in ('first','last'):
            with Image.open(path) as image:
                if image.size!=(736,1312):raise ValueError('native endpoint image dimensions differ')
    return dict(minute=minute,run=run,spec=spec,entry=entry,compiled=compiled,expected_quotes=expected,plan=plan,row=row,folder=folder,result=result,mapping_path=mapping_path)

def extract(video,path,index):
    if not Path(path).exists():command(['ffmpeg','-nostdin','-v','error','-hwaccel','none','-i',str(video),'-vf',f'select=eq(n\\,{index})','-frames:v','1',str(path)])
    return bind(path)
def card(path,label):
    canvas=Image.new('RGB',(276,540),'white')
    with Image.open(path) as image:image=image.convert('RGB');image.thumbnail((276,492));canvas.paste(image,((276-image.width)//2,0))
    ImageDraw.Draw(canvas).text((5,498),label,fill='black');return canvas
def board(cards,path,cols=4):
    canvas=Image.new('RGB',(276*cols,540*((len(cards)+cols-1)//cols)),'#ddd')
    for i,image in enumerate(cards):canvas.paste(image,((i%cols)*276,(i//cols)*540))
    if not Path(path).exists():canvas.save(path,quality=94)
    return bind(path)
def clock(video,frames,*,final=False):
    metadata=probe(video);v=next(s for s in metadata['streams'] if s['codec_type']=='video');a=next(s for s in metadata['streams'] if s['codec_type']=='audio');target=Fraction(frames,24)
    if (v['width'],v['height'],int(v['nb_frames']),int(v['nb_read_frames']),v['r_frame_rate'],v['avg_frame_rate'])!=(736,1312,frames,frames,'24/1','24/1') or Fraction(v['start_time'])!=0 or Fraction(a['start_time'])!=0:raise ValueError('actual decoded geometry/rate/origins differ')
    duration=Fraction(v['duration_ts'])*Fraction(v['time_base']);samples=Fraction(a['duration_ts'])*Fraction(a['time_base'])*int(a['sample_rate'])
    if abs(duration-target)>Fraction(1,1000):raise ValueError('native container tail quantization beyond 1ms')
    rows=json.loads(command(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp','-of','json',str(video)]))['frames']
    if len(rows)!=frames or any(Fraction(r['best_effort_timestamp'])*Fraction(v['time_base'])!=Fraction(i,24) for i,r in enumerate(rows)):raise ValueError('decoded PTS is not exact i/24')
    if final and (duration!=target or int(a['sample_rate'])!=48000 or int(a['channels'])!=2 or samples!=2896000 or abs(Fraction(metadata['format']['duration'])-target)>Fraction(1,1000)):raise ValueError('final exact stream clocks differ')
    return dict(width=736,height=1312,frames=frames,decoded_frames=frames,fps=24,seconds=float(target),container_seconds=float(duration),decoded_pts_exact_i_over_24=True,audio_rate=int(a['sample_rate']),effective_audio_samples=str(samples),video_start=0,audio_start=0),metadata

def dense_indices(entry,sid):
    regions=[]
    for i,beat in enumerate(entry['camera_beats']):
        if beat.get('cut') is True:regions.append(dict(label='PLANNED camera cut '+str(i),start=max(0,float(beat['start'])-.5),end=min(361/24,float(beat['start'])+.5)))
    if sid=='S02':regions.append(dict(label='S02 local 11.5-14.0 inspection',start=11.5,end=14.0))
    if sid=='S04':regions.append(dict(label='S04 local 0-5 face inspection',start=0.,end=5.))
    for r in regions:r['indices']=list(range(round(r['start']*24),min(361,round(r['end']*24))+1,3))
    return regions
def asr_intervals(path,expected):
    chars=[];times=[]
    for row in read(path)['result']:
        tokens=row.get('text','').split();stamps=row.get('timestamp',[])
        if len(tokens)!=len(stamps):raise ValueError('ASR token/timestamp mismatch')
        for word,stamp in zip(tokens,stamps):
            for c in norm(word):chars.append(c);times.append(stamp)
    text=''.join(chars);rows=[]
    for i,quote in enumerate(expected):
        target=norm(quote);at=text.find(target);rows.append(dict(quote_index=i,text=quote,exactly_detected=at>=0,start_ms=times[at][0] if at>=0 else None,end_ms=times[at+len(target)-1][1] if at>=0 else None))
    return text,rows

def qa_segment(minute,sid,*,h3_run,segment_spec,asr=False,project=PROJECT):
    v=validate(minute,sid,h3_run=h3_run,segment_spec=segment_spec,project=project);result=v['result'];pid=result['prompt_id'];folder=v['minute']/'qc'/sid/pid;folder.mkdir(parents=True,exist_ok=True);video=result['files']['video']
    bindings=dict(mapping=bind(v['mapping_path']),h3_plan=bind(v['run']/'PLAN.json'),segment_spec=bind(v['spec']),result=bind(v['folder']/'RESULT.json'),request=bind(v['folder']/'REQUEST.json'),history=bind(v['folder']/'HISTORY.json'),native_id=pid,video={k:video[k] for k in ('path','sha256')},input_image={k:v['row']['first_frame'][k] for k in ('path','sha256')},actual_seed=read(v['folder']/'workflow_api.json')['129']['inputs']['noise_seed'],seed_policy='sealed_v33_shot_binding_and_first_image_sha_derived_not_legacy_seed_replay');freeze(folder/'BINDING.json',bindings)
    geometry,metadata=clock(video['path'],362);freeze(folder/'PROBE.json',metadata);frames=[];cards=[]
    for i in (0,36,108,180,252,324):
        item=dict(**extract(video['path'],folder/f'actual_{i:03d}.png',i),frame_index=i,seconds=i/24);frames.append(item);cards.append(card(item['path'],f'ACTUAL n={i} t={i/24:.3f}s'))
    last={k:result['files']['last'][k] for k in ('path','sha256')};contact=board(cards+[card(last['path'],'ACTUAL native last')],folder/'CONTACT.jpg')
    input_board=board([card(bindings['input_image']['path'],'ACTUAL reviewed input PNG'),card(frames[0]['path'],'ACTUAL decoded first')],folder/'INPUT_VS_ACTUAL_FIRST.jpg',2)
    dense=[]
    for ri,region in enumerate(dense_indices(v['entry'],sid)):
        samples=[dict(**extract(video['path'],folder/f'actual_{i:03d}.png',i),frame_index=i,seconds=i/24) for i in region['indices']]
        dense.append(dict(**region,actual_frames=samples,contact=board([card(s['path'],f'ACTUAL n={s["frame_index"]} t={s["seconds"]:.3f}s\nPlanned cut; no detected identity/text') for s in samples],folder/f'DENSE_{ri:02d}.jpg')))
    wav=folder/'embedded_audio_16k.wav'
    if not wav.exists():command(['ffmpeg','-nostdin','-v','error','-hwaccel','none','-i',video['path'],'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)])
    transcript=folder/'ASR.json'
    if asr and not transcript.exists():transcribe(project,wav,transcript,folder)
    levels=folder/'audio_levels.log'
    if not levels.exists():command(['ffmpeg','-nostdin','-hide_banner','-hwaccel','none','-i',video['path'],'-vn','-af','silencedetect=noise=-38dB:d=0.5,volumedetect','-f','null','-'],log=levels)
    raw=levels.read_text(encoding='utf-8');signal={k:float(m.group(1)) if (m:=re.search(k+r':\s*(-?[\d.]+) dB',raw)) else None for k in ('mean_volume','max_volume')};actual=None;intervals=[];quote_board=None
    if transcript.exists():
        actual,intervals=asr_intervals(transcript,v['expected_quotes']);cards=[]
        for row in intervals:
            if not row['exactly_detected']:continue
            row['frames']=[]
            for fraction in (.1,.3,.5,.7,.9):
                i=min(361,max(0,round((row['start_ms']+(row['end_ms']-row['start_ms'])*fraction)*24/1000)));item=dict(**extract(video['path'],folder/f'actual_{i:03d}.png',i),frame_index=i,seconds=i/24);row['frames'].append(item);cards.append(card(item['path'],f'ACTUAL quote{row["quote_index"]+1} n={i}\nSpeaker/mouth NOT identified'))
        if cards:quote_board=board(cards,folder/'QUOTE_INTERVAL_ACTUAL_CONTACT.jpg',5)
        freeze(folder/'ASR_QUOTE_INTERVALS.json',dict(asr=bind(transcript),video=bindings['video'],native_id=pid,quotes=intervals,contact=quote_board,unrecognized_is_not_proof_of_omission=True,production_approved=False))
    report=dict(schema=SCHEMA,binding=bindings,geometry=geometry,signal=signal,silence_events=[line for line in raw.splitlines() if 'silence_' in line],expected_quoted_speech=v['expected_quotes'],asr_text=actual,normalized_matches=actual==norm(''.join(v['expected_quotes'])) if actual is not None else None,quote_intervals=intervals,frames=frames,native_last=last,contact=contact,input_vs_actual_first=input_board,dense_regions=dense,quote_contact=quote_board,visual_observation=dict(status='root_review_required',actual_identity=None,head_body_topology=None,native_subtitles=None,lip_sync=None),production_approved=False)
    validate(minute,sid,h3_run=h3_run,segment_spec=segment_spec,project=project);freeze(folder/'OBJECTIVE_QA.json',report)
    return dict(status='cpu_qa_complete',segment=sid,native_id=pid,video_sha256=video['sha256'],manifest=bind(folder/'OBJECTIVE_QA.json'),contact=contact,quote_contact=quote_board,dense_contacts=[r['contact'] for r in dense],production_approved=False)

def qa_final(minute,*,project=PROJECT):
    values=[validate(minute,sid,project=project) for sid in IDS];minute=values[0]['minute'];final=read(minute/'FINAL_RESULT.json');results=[v['result'] for v in values];ids=[r['prompt_id'] for r in results];inputs=dict(plan=bind(minute/'PLAN.json'),results=[bind(v['folder']/'RESULT.json') for v in values]);videos=[{k:r['files']['video'][k] for k in ('path','sha256')} for r in results]
    if (final.get('schema')!='h3_continuity_minute/v34' or final.get('native_ids')!=ids or len(set(ids))!=4 or len({v['sha256'] for v in videos})!=4 or final.get('segment_results')!=inputs['results'] or final.get('source_videos')!=videos or final.get('assembly_inputs_sha256')!=digest(inputs) or final.get('production_approved') is not False or final.get('publication') is not False):raise ValueError('four distinct new originals/final assembly binding differs')
    movie=check(final['file'],project)
    if movie!=minute/'H3_CONTINUITY_MINUTE_736x1312.mp4':raise ValueError('explicit new minute file required')
    source_clocks=[dict(video=v,clock=clock(v['path'],362)[0]) for v in videos]
    geometry,metadata=clock(movie,1448,final=True);folder=minute/'qc/final';folder.mkdir(parents=True,exist_ok=True);cards=[];joins=[]
    for i in (361,723,1085):
        frames=[dict(**extract(movie,folder/f'actual_{n:04d}.png',n),frame_index=n,seconds=n/24) for n in (i,i+1)];joins.append(dict(frames=frames,semantic_continuity=None));cards.extend(card(r['path'],f'ACTUAL JOIN n={r["frame_index"]} t={r["seconds"]:.3f}s') for r in frames)
    join_board=board(cards,folder/'JOINS_CONTACT.jpg',2);dense=[]
    for start,end in [(24,29),(47,52)]:
        samples=[dict(**extract(movie,folder/f'actual_{i:04d}.png',i),frame_index=i,seconds=i/24) for i in range(start*24,end*24+1,3)]
        dense.append(dict(start=start,end=end,actual_frames=samples,contact=board([card(r['path'],f'ACTUAL n={r["frame_index"]} {r["seconds"]:.3f}s\nIdentity / heads / text NOT classified') for r in samples],folder/f'DENSE_{start}_{end}.jpg',5)))
    report=dict(schema=SCHEMA,file=final['file'],final_result=bind(minute/'FINAL_RESULT.json'),original_native_ids=ids,assembly_inputs=inputs,source_clocks=source_clocks,clock=geometry,joins=joins,join_contact=join_board,dense_regions=dense,visual_observation=dict(status='root_review_required',actual_identity=None,head_body_topology=None,native_subtitles=None,lip_sync=None),production_approved=False)
    freeze(folder/'PROBE.json',metadata);freeze(folder/'FINAL_OBJECTIVE_QA.json',report)
    return dict(status='final_cpu_qa_complete',manifest=bind(folder/'FINAL_OBJECTIVE_QA.json'),clock=geometry,join_contact=join_board,dense_contacts=[r['contact'] for r in dense],production_approved=False)

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('action',choices=['segment','final']);p.add_argument('--minute-root',type=Path,required=True);p.add_argument('--segment',choices=IDS);p.add_argument('--h3-run',type=Path);p.add_argument('--segment-spec',type=Path);p.add_argument('--asr',action='store_true');p.add_argument('--project-root',type=Path,default=PROJECT);a=p.parse_args(argv)
    if a.action=='segment':
        if not all([a.segment,a.h3_run,a.segment_spec]):p.error('segment, h3-run and segment-spec required')
        value=qa_segment(a.minute_root,a.segment,h3_run=a.h3_run,segment_spec=a.segment_spec,asr=a.asr,project=a.project_root)
    else:value=qa_final(a.minute_root,project=a.project_root)
    print(json.dumps(value,ensure_ascii=False));return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:
        print(json.dumps(dict(status='cpu_qa_failed',type=type(e).__name__,message=str(e),no_media_retry=True),ensure_ascii=False));raise SystemExit(2)
