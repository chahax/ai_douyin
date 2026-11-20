"""Independent existing-file CPU audit for the four new v32 I2V originals.

No executor imports, HTTP, GPU, dispatch or semantic approval. A local observer
may run only after root supplies an actual original first native ID.
"""
import argparse
from copy import deepcopy
from difflib import SequenceMatcher
from fractions import Fraction
import hashlib,json,os,re,sys,time,uuid
from pathlib import Path
from PIL import Image,ImageDraw,ImageStat,ImageChops

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.qa_h3_reference_full_minute_cpu import command,probe,transcribe

PROJECT=Path(__file__).resolve().parents[1]
ROOT='data/video_generation/h3_legacy_call_restore_20261108_v1'
RAW='data/video_generation/h3_seedance_prompt_parity_60s_20261107_v1'
SCHEMA='h3_legacy_call_restore/v32'
QA_SCHEMA='h3_legacy_call_restore_cpu_qa/v32'
IDS=('S01','S02','S03','S04')
ROLES=('video','audio','first','last')
COUNTS=(3,2,2,3)
EDITS={
 '场景是苏墨的房间，人物外观、服装与场景环境采用本段具名参考图。':'场景是苏墨的房间，人物外观、服装与场景环境承接本段首图。',
 '人物与参考图逐一对应：':'首图中的人物与服装：',
 '苏墨是<Picture 1>中的成年父亲':'苏墨是首图中的成年父亲',
 '叶南是<Picture 2>中的哥哥':'叶南是首图中的哥哥',
 '叶西决是<Picture 3>中的弟弟':'叶西决是首图中的弟弟',
 '人物造型与房间环境以具名参考图为准。':'人物造型与房间环境以本段首图为准。'}

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def binding(path):return dict(path=str(Path(path).resolve()),sha256=sha(path))
def fingerprint(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def inside(root,path):
    root=Path(root).resolve();path=Path(path).resolve()
    if path==root or not path.is_relative_to(root):raise ValueError('outside required CPU audit scope')
    return path
def check(value,project):
    if not isinstance(value,dict) or set(value)!={'path','sha256'}:raise ValueError('explicit physical file binding required')
    path=inside(project,value['path'])
    if not path.is_file() or binding(path)!=value:raise ValueError('bound file changed')
    return path
def freeze(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if fingerprint(read(path))!=fingerprint(value):raise ValueError('CPU evidence changed; preserve original evidence')
    else:write(path,value)
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def normalized(t):return ''.join(c for c in t if c.isalnum())
def quotes(t):return re.findall('[“「]([^”」]+)[”」]',t)
def run_path(run,project):
    if Path(run).resolve()!=(Path(project).resolve()/ROOT):raise ValueError('only the new v32 run may be audited')
    return Path(run).resolve()

def history_graph(expected,observed):
    """Only native integer-to-float normalization on two known fields allowed."""
    value=deepcopy(observed)
    for node,key in [('124','denoise'),('130','fps')]:
        actual=value.get(node,{}).get('inputs',{}).get(key);wanted=expected.get(node,{}).get('inputs',{}).get(key)
        if type(actual) is float and type(wanted) is int and actual==wanted:value[node]['inputs'][key]=wanted
    if fingerprint(value)!=fingerprint(expected):raise ValueError('actual native history graph differs')

def verify_prompt(source,compiled,audit):
    if (audit.get('schema')!='first_image_prompt_adaptation/v32' or audit.get('source_utf8_sha256')!=hashlib.sha256(source.encode()).hexdigest()
        or audit.get('compiled_utf8_sha256')!=hashlib.sha256(compiled.encode()).hexdigest()):raise ValueError('prompt adaptation digest differs')
    edits=audit.get('edits');expected=[]
    for old,new in EDITS.items():
        count=source.count(old)
        if count>1:raise ValueError('duplicate source reference anchor')
        if count:
            start=source.index(old);expected.append(dict(char_start=start,char_end=start+len(old),utf8_byte_start=len(source[:start].encode()),old=old,new=new))
    expected.sort(key=lambda r:r['char_start']);offset=0
    for row in expected:row['compiled_start']=row['char_start']+offset;offset+=len(row['new'])-len(row['old'])
    if fingerprint(edits)!=fingerprint(expected):raise ValueError('adaptation includes undeclared changes or wrong offsets')
    restored=compiled
    for row in reversed(expected):
        pos=row['compiled_start']
        if restored[pos:pos+len(row['new'])]!=row['new']:raise ValueError('compiled replacement differs')
        restored=restored[:pos]+row['old']+restored[pos+len(row['new']):]
    if restored!=source or quotes(source)!=quotes(compiled) or re.search(r'<Picture\s|具名参考|参考图',compiled):raise ValueError('actions/quotes changed or phantom references remain')
    return quotes(source)

def recipe(graph,index):
    required={'119':('VAELoader',{'vae_name':'minimax_h3_video_vae_int8_convrot.safetensors'}),
      '120':('VAELoader',{'vae_name':'minimax_h3_audio_vae_fp32.safetensors'}),
      '127':('UNETLoader',{'unet_name':'minimax_h3_fl2va_pruned_int8_convrot.safetensors','weight_dtype':'default'}),
      '128':('CLIPLoader',{'clip_name':'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors','type':'minimax','device':'default'}),
      '123':('KSamplerSelect',{'sampler_name':'res_multistep'}),
      '124':('BasicScheduler',{'model':['127',0],'scheduler':'simple','steps':12,'denoise':1}),
      '129':('RandomNoise',{'noise_seed':2026110700+index})}
    for key,(kind,inputs) in required.items():
        if fingerprint(graph.get(key))!=fingerprint(dict(class_type=kind,inputs=inputs)):raise ValueError('legacy sampling/model recipe differs')
    ci=graph['condition']['inputs']
    if (graph['condition']['class_type']!='MiniMaxH3ImageToVideo' or set(ci)!={'clip','vae','prompt','width','height','length','first_frame'}
        or ci['clip']!=['128',0] or ci['vae']!=['119',0] or ci['first_frame']!=['ref_scene',0]
        or any(type(ci[k]) is not int for k in ('width','height','length')) or (ci['width'],ci['height'],ci['length'])!=(736,1312,362)
        or [k for k,v in graph.items() if v.get('class_type')=='LoadImage']!=['ref_scene']
        or any(v.get('class_type') in ('MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide') for v in graph.values())
        or graph['pick_first']['inputs']['batch_index']!=0 or graph['pick_last']['inputs']['batch_index']!=361
        or type(graph['130']['inputs']['fps']) is not int or graph['130']['inputs']['fps']!=24):raise ValueError('first-only I2V topology differs')

def validate_plan(run,*,project=PROJECT):
    project=Path(project).resolve();run=run_path(run,project);plan=read(run/'PLAN.json');settings=plan['settings']
    if (plan.get('schema')!=SCHEMA or plan.get('task_mode')!='fl2va_i2v_first_only' or type(plan.get('direct_reference_slots')) is not int or plan['direct_reference_slots']!=0
        or plan.get('production_approved') is not False or plan.get('publication') is not False or plan.get('diagnostic_preview') is not True
        or any(type(settings[k]) is not int for k in ('width','height','frames','fps')) or tuple(settings[k] for k in ('width','height','frames','fps'))!=(736,1312,362,24)
        or [r['id'] for r in settings['segments']]!=list(IDS)):raise ValueError('new v32 four-segment diagnostic plan required')
    auth_path=check(plan['authorization'],project)
    if auth_path!=run/'USER_AUTHORIZATION.json':raise ValueError('fixed v32 authority path required')
    auth=read(auth_path)
    if (auth.get('schema')!='h3_legacy_call_restore_authorization/v32' or not auth.get('user_statement')
        or auth.get('engineering_scope_not_user_quoted_numeric_limit') is not True
        or any(type(auth.get(k)) is not int or auth[k]!=v for k,v in [('max_full_video_submissions',4),('max_probe_video_submissions',0),('new_cloud_media_calls',0)])
        or any(auth.get(k) is not False for k in ('publication','service_restarts','downloads','unknown_native_replay','old_paused_batches_resumed'))):raise ValueError('finite new four-native authorization required')
    for key,expected in [('baseline_a_spec',project/'data/video_generation/spatial_minute_experiments_20261107_v1/A_SPEC.json'),('legacy_raw_plan',project/RAW/'PLAN.json'),('call_difference_audit',project/'data/qa/h3_actual_call_comparison_20261108/ACTUAL_CALL_DIFF.json')]:
        if check(plan[key],project)!=expected or plan[key]!=auth[key]:raise ValueError('fixed baseline/call-difference binding differs')
    baseline=read(check(plan['baseline_a_spec'],project));raw=read(check(plan['legacy_raw_plan'],project));check(plan['protected_pause'],project)
    if baseline['variant']!='A' or settings['initial_guide']!=baseline['initial_guide'] or plan['upstream_asset_references']!=baseline['references'] or plan['protected_pause']!=raw['protected_pause']:raise ValueError('canonical opening/upstream assets or protected pause differs')
    guide=settings['initial_guide'];check(guide['image'],project);native=read(check(guide['native_result'],project));review=read(check(guide['root_review'],project))
    if guide.get('role')!='first' or {k:native['files']['first'][k] for k in ('path','sha256')}!=guide['image'] or review.get('reviewed_by')!='root_agent' or review.get('accepted_for_guide') is not True or review.get('image')!=guide['image'] or review.get('native_result')!=guide['native_result']:raise ValueError('canonical source/actual guide review differs')
    checks=[]
    for index,row in enumerate(settings['segments']):
        sid=IDS[index];source=check(row['original_prompt'],project).read_text(encoding='utf-8');compiled=check(row['prompt'],project).read_text(encoding='utf-8');audit=read(check(row['adaptation_audit'],project))
        if row['original_prompt']!=baseline['segments'][index]['prompt'] or check(row['prompt'],project)!=run/'prompts'/(sid+'.txt'):raise ValueError('current episode prompt source differs')
        expected_quotes=verify_prompt(source,compiled,audit)
        if len(expected_quotes)!=COUNTS[index]:raise ValueError('original dialogue coverage differs')
        evidence=row['legacy_actual_call'];old=project/RAW/'segments'/sid
        for key,name in [('request','REQUEST.json'),('workflow','workflow_api.json'),('history','HISTORY.json'),('result','RESULT.json')]:
            if check(evidence[key],project)!=old/name:raise ValueError('actual old baseline evidence path differs')
        old_result=read(old/'RESULT.json');pid=old_result['prompt_id'];entry=read(old/'HISTORY.json')[pid];graph=read(old/'workflow_api.json')
        if evidence['original_native_id']!=pid or old_result.get('technical_status')!='technical_saved' or read(old/'REQUEST.json')['prompt']!=graph or fingerprint(row['template'])!=fingerprint(graph):raise ValueError('old executed template binding differs')
        if entry['prompt'][1]!=pid or entry['status'].get('completed') is not True or entry['status'].get('status_str')!='success':raise ValueError('old baseline successful native history required')
        history_graph(graph,entry['prompt'][2]);recipe(graph,index)
        checks.append(dict(id=sid,legacy_actual_call=evidence,template_sha256=fingerprint(graph),prompt=row['prompt'],original_prompt=row['original_prompt'],quotes=expected_quotes))
    return dict(run=run,plan=plan,segments=checks)

def validate_segment(run,sid,*,project=PROJECT):
    checked=validate_plan(run,project=project);run=checked['run'];plan=checked['plan']
    if sid not in IDS:raise ValueError('known segment required')
    approval=read(run/'LAUNCH_APPROVAL.json');auth=read(check(plan['authorization'],project));basis=approval.get('selection_basis',[])
    if (approval.get('schema')!='h3_legacy_call_restore_launch_approval/v32' or approval.get('reviewed_by')!='root_agent' or approval.get('approved_for_generation') is not True
        or approval.get('diagnostic_only') is not True or approval.get('plan')!=binding(run/'PLAN.json') or approval.get('authorization')!=plan['authorization']
        or approval.get('baseline_selection_by')!='root_agent' or not isinstance(basis,list) or auth['call_difference_audit'] not in basis or auth['selection_evidence'] not in basis):raise ValueError('root selected launch approval differs')
    for value in basis:check(value,project)
    index=IDS.index(sid);segment=plan['settings']['segments'][index];folder=run/'shots'/sid
    state=read(folder/'STATE.json');result=read(folder/'RESULT.json');row=read(folder/'GRAPH_BINDING.json');pid=result.get('prompt_id')
    if (state.get('status')!='technical_saved' or result.get('technical_status')!='technical_saved' or not isinstance(pid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',pid)
        or state.get('prompt_id')!=pid or state.get('id')!=sid or result.get('shot_id')!=sid or result.get('schema')!=SCHEMA
        or state.get('plan_sha256')!=fingerprint(plan) or state.get('result_sha256')!=sha(folder/'RESULT.json')):raise ValueError('new native terminal/result identity differs')
    if pid in [r['legacy_actual_call']['original_native_id'] for r in plan['settings']['segments']]:raise ValueError('old original cannot be a new native result')
    scope=run.name+'/'+sid;graph=deepcopy(segment['template']);graph['condition']['inputs']['prompt']=check(segment['prompt'],project).read_text(encoding='utf-8');graph['ref_scene']['inputs']['image']=scope+'/first_input.png'
    for role in ROLES:graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    guide=plan['settings']['initial_guide']
    if index:
        previous=run/'shots'/IDS[index-1]/'RESULT.json';prior=read(previous);prior_state=read(previous.parent/'STATE.json')
        if prior_state.get('status')!='technical_saved' or prior_state.get('result_sha256')!=sha(previous) or prior_state.get('prompt_id')!=prior['prompt_id']:raise ValueError('previous original native tail is not saved')
        guide=dict(image={k:prior['files']['last'][k] for k in ('path','sha256')},native_result=binding(previous),role='last',native_id=prior['prompt_id'],previous_segment=IDS[index-1],policy='actual_previous_native_tail_even_if_semantically_imperfect')
    check(guide['image'],project);first=folder/'first_input.png';expected=dict(id=sid,scope=scope,graph_sha256=fingerprint(graph),guide=guide,first_frame=binding(first),input_name=scope+'/first_input.png',source_prompt=segment['prompt'],original_prompt=segment['original_prompt'],task_mode='fl2va_i2v_first_only',direct_reference_slots=0)
    if (fingerprint(row)!=fingerprint(expected) or sha(first)!=guide['image']['sha256'] or sha(inside(plan['config']['input_root'],Path(plan['config']['input_root'])/expected['input_name']))!=sha(first)
        or fingerprint(read(folder/'workflow_api.json'))!=fingerprint(graph) or fingerprint(read(folder/'REQUEST.json')['prompt'])!=fingerprint(graph)
        or state.get('graph_sha256')!=fingerprint(graph) or result.get('graph_sha256')!=fingerprint(graph)):raise ValueError('new first-image/actual request/graph binding differs')
    claim=read(folder/'CLAIM.json');response=read(folder/'RESPONSE.json')
    if claim.get('request')!=binding(folder/'REQUEST.json') or claim.get('graph_sha256')!=fingerprint(graph) or type(claim.get('native_post_budget')) is not int or claim['native_post_budget']!=1 or response.get('prompt_id')!=pid or response.get('node_errors'):raise ValueError('original submit claim/response differs')
    entry=read(folder/'HISTORY.json')[pid]
    if entry['prompt'][1]!=pid or entry['status'].get('completed') is not True or entry['status'].get('status_str')!='success':raise ValueError('successful original native history required')
    history_graph(graph,entry['prompt'][2])
    if result.get('guide')!=guide or result.get('first_frame')!=expected['first_frame'] or result.get('source_prompt')!=segment['prompt'] or result.get('original_prompt')!=segment['original_prompt'] or result.get('task_mode')!='fl2va_i2v_first_only' or type(result.get('direct_reference_slots')) is not int or result.get('direct_reference_slots')!=0 or set(result['files'])!=set(ROLES):raise ValueError('result input profile or four originals differs')
    for role in ROLES:
        item=result['files'][role];path=inside(folder/'artifacts',item['path']);source=inside(plan['config']['output_root'],item['source_path']);suffix='.mp4' if role=='video' else '.flac' if role=='audio' else '.png';rec=entry['outputs']['save_'+role]['audio' if role=='audio' else 'images']
        if (len(rec)!=1 or rec[0].get('type')!='output' or rec[0].get('filename')!=path.name or rec[0].get('subfolder','').replace('\\','/')!=scope
            or not path.name.startswith(role+'_') or path.suffix!=suffix or source.parent!=Path(plan['config']['output_root'])/scope or source.name!=path.name or sha(path)!=item['sha256'] or sha(source)!=item['sha256']):raise ValueError('native original/history/output source differs')
    return checked,folder,result,row

def extract(video,path,index):
    if not Path(path).exists():command(['ffmpeg','-nostdin','-v','error','-hwaccel','none','-i',str(video),'-vf',f'select=eq(n\\,{index})','-frames:v','1',str(path)])
    return binding(path)
def card(path,label):
    image=Image.new('RGB',(368,710),'white')
    with Image.open(path) as src:src=src.convert('RGB');src.thumbnail((368,656));image.paste(src,((368-src.width)//2,0))
    ImageDraw.Draw(image).text((6,661),label,fill='black');return image
def contact(cards,path,columns=3):
    canvas=Image.new('RGB',(columns*368,((len(cards)+columns-1)//columns)*710),'#ddd')
    for i,img in enumerate(cards):canvas.paste(img,((i%columns)*368,(i//columns)*710))
    if not Path(path).exists():canvas.save(path,quality=94)
    return binding(path)
def metric(a,b):
    with Image.open(a) as x,Image.open(b) as y:
        x=x.convert('RGB');y=y.convert('RGB')
        if x.size!=y.size:raise ValueError('pixel comparison needs equal dimensions')
        stat=ImageStat.Stat(ImageChops.difference(x,y));return dict(mae=sum(stat.mean)/765,rmse=sum(stat.rms)/765,semantic_pass=None)
def clock(video,frames,*,final=False):
    metadata=probe(video);v=next(s for s in metadata['streams'] if s['codec_type']=='video');a=next(s for s in metadata['streams'] if s['codec_type']=='audio')
    if ((v['width'],v['height'],int(v['nb_frames']),int(v['nb_read_frames']),v['r_frame_rate'],v['avg_frame_rate'])!=(736,1312,frames,frames,'24/1','24/1') or Fraction(v['start_time'])!=0 or Fraction(a['start_time'])!=0):raise ValueError('decoded native geometry/frame rate/origins differ')
    expected=Fraction(frames,24);duration=Fraction(v['duration_ts'])*Fraction(v['time_base'])
    if abs(duration-expected)>Fraction(1,1000):raise ValueError('container tail beyond 1ms quantization')
    pts=json.loads(command(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp','-of','json',str(video)]))['frames']
    if len(pts)!=frames or any(Fraction(row['best_effort_timestamp'])*Fraction(v['time_base'])!=Fraction(i,24) for i,row in enumerate(pts)):raise ValueError('actual decoded PTS is not exact i/24')
    samples=Fraction(a['duration_ts'])*Fraction(a['time_base'])*int(a['sample_rate'])
    if final and (duration!=expected or int(a['sample_rate'])!=48000 or int(a['channels'])!=2 or samples!=2896000 or abs(Fraction(metadata['format']['duration'])-expected)>Fraction(1,1000)):raise ValueError('assembled exact video/audio sample clock differs')
    return dict(width=736,height=1312,native_frames=frames,decoded_frames=frames,fps=24,seconds=float(expected),container_seconds=float(duration),tail_quantization_seconds=float(duration-expected),decoded_pts_exact_i_over_24=True,audio_rate=int(a['sample_rate']),audio_samples=str(samples),video_start=0,audio_start=0),metadata

def quote_intervals(asr,expected):
    chars=[];times=[]
    for row in read(asr)['result']:
        tokens=row.get('text','').split();stamps=row.get('timestamp',[])
        if len(tokens)!=len(stamps):raise ValueError('ASR tokens lack matching timestamps')
        for token,stamp in zip(tokens,stamps):
            for c in normalized(token):chars.append(c);times.append(stamp)
    actual=''.join(chars);rows=[]
    for index,quote in enumerate(expected):
        target=normalized(quote);at=actual.find(target)
        rows.append(dict(quote_index=index,text=quote,exactly_detected=at>=0,start_ms=times[at][0] if at>=0 else None,end_ms=times[at+len(target)-1][1] if at>=0 else None))
    return actual,rows

def qa_segment(run,sid,*,asr=False,project=PROJECT):
    checked,native,result,row=validate_segment(run,sid,project=project);run=checked['run'];pid=result['prompt_id'];folder=run/'qc'/sid/pid;folder.mkdir(parents=True,exist_ok=True)
    video=result['files']['video'];bound=dict(plan=binding(run/'PLAN.json'),result=binding(native/'RESULT.json'),request=binding(native/'REQUEST.json'),claim=binding(native/'CLAIM.json'),history=binding(native/'HISTORY.json'),graph_binding=binding(native/'GRAPH_BINDING.json'),segment=sid,prompt_id=pid,video={k:video[k] for k in ('path','sha256')},source_prompt=row['source_prompt'],original_prompt=row['original_prompt'],task_mode='fl2va_i2v_first_only',direct_reference_slots=0,legacy_actual_call=checked['segments'][IDS.index(sid)]['legacy_actual_call'])
    freeze(folder/'BINDING.json',bound);geometry,metadata=clock(video['path'],362);freeze(folder/'PROBE.json',metadata)
    frames=[dict(**extract(video['path'],folder/f'frame_{i:03d}.png',i),frame_index=i,seconds=i/24) for i in (0,36,108,180,252,324)]
    last=result['files']['last'];first=result['files']['first']
    for item in (first,last,row['guide']['image']):
        with Image.open(item['path']) as image:
            if image.size!=(736,1312):raise ValueError('endpoint/first input dimensions differ')
    board=contact([card(x['path'],f'ACTUAL n={x["frame_index"]} t={x["seconds"]:.3f}s') for x in frames]+[card(last['path'],'ACTUAL native last output')],folder/'CONTACT.jpg')
    guide_board=contact([card(row['guide']['image']['path'],'ACTUAL input first image'),card(frames[0]['path'],'ACTUAL MP4 decoded frame 0')],folder/'INPUT_VS_ACTUAL_FIRST.jpg',2)
    wav=folder/'embedded_audio_16k.wav'
    if not wav.exists():command(['ffmpeg','-nostdin','-v','error','-hwaccel','none','-i',video['path'],'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)])
    transcript=folder/'ASR.json'
    if asr and not transcript.exists():transcribe(project,wav,transcript,folder)
    levels=folder/'audio_levels.log'
    if not levels.exists():command(['ffmpeg','-nostdin','-hide_banner','-hwaccel','none','-i',video['path'],'-vn','-af','silencedetect=noise=-38dB:d=0.5,volumedetect','-f','null','-'],log=levels)
    raw=levels.read_text(encoding='utf-8');signal={k:float(m.group(1)) if (m:=re.search(k+r':\s*(-?[\d.]+) dB',raw)) else None for k in ('mean_volume','max_volume')}
    expected=checked['segments'][IDS.index(sid)]['quotes'];actual=None;intervals=[];quote_board=None
    if transcript.exists():
        actual,intervals=quote_intervals(transcript,expected);cards=[]
        for utterance in intervals:
            if not utterance['exactly_detected']:continue
            utterance['frames']=[]
            for fraction in (.1,.3,.5,.7,.9):
                i=min(361,max(0,round((utterance['start_ms']+(utterance['end_ms']-utterance['start_ms'])*fraction)*24/1000)))
                item=dict(**extract(video['path'],folder/f'quote_{utterance["quote_index"]+1:02d}_{i:03d}.png',i),frame_index=i,seconds=i/24);utterance['frames'].append(item);cards.append(card(item['path'],f'ACTUAL quote{utterance["quote_index"]+1} n={i} {i/24:.3f}s\nSpeaker/mouth state NOT identified'))
        if cards:quote_board=contact(cards,folder/'QUOTE_INTERVAL_ACTUAL_CONTACT.jpg',5)
        freeze(folder/'ASR_QUOTE_INTERVALS.json',dict(asr=binding(transcript),prompt_id=pid,video=bound['video'],quotes=intervals,contact=quote_board,scope='Approximate CPU ASR timestamps only; no acoustic identity or listening/semantic approval.',production_approved=False))
    output=dict(schema=QA_SCHEMA,binding=bound,geometry=geometry,audio_metadata={k:next(s for s in metadata['streams'] if s['codec_type']=='audio').get(k) for k in ('codec_name','sample_rate','channels','duration')},signal=signal,silence_events=[line for line in raw.splitlines() if 'silence_' in line],expected_quoted_speech=expected,asr_text=actual,normalized_matches=normalized(''.join(expected))==actual if actual is not None else None,quote_intervals=intervals,frames=frames,native_last={k:last[k] for k in ('path','sha256')},contact=board,input_vs_actual_first=guide_board,input_first_pixel_metric=metric(row['guide']['image']['path'],frames[0]['path']),quote_contact=quote_board,scope='CPU decoding, timing, local ASR and actual frames. No actual speaker/identity/mouth-state recognition, no listening review, no production approval.',production_approved=False)
    validate_segment(run,sid,project=project);freeze(folder/'OBJECTIVE_QA.json',output)
    return dict(status='cpu_qa_complete',segment=sid,prompt_id=pid,video_sha256=video['sha256'],manifest=binding(folder/'OBJECTIVE_QA.json'),contact=board,quote_contact=quote_board,input_vs_actual_first=guide_board,production_approved=False)

def qa_final(run,*,project=PROJECT):
    checked=validate_plan(run,project=project);run=checked['run'];results=[validate_segment(run,sid,project=project)[2] for sid in IDS];final=read(run/'FINAL_RESULT.json');ids=[r['prompt_id'] for r in results]
    inputs=dict(plan=binding(run/'PLAN.json'),results=[binding(run/'shots'/sid/'RESULT.json') for sid in IDS])
    if (final.get('schema')!=SCHEMA or final.get('native_ids')!=ids or len(set(ids))!=4 or len({r['files']['video']['sha256'] for r in results})!=4 or final.get('assembly_inputs_sha256')!=fingerprint(inputs) or final.get('production_approved') is not False or final.get('publication') is not False):raise ValueError('four new originals/final assembly binding differs')
    video=check(final['file'],project)
    if video!=run/'LEGACY_CALL_RESTORE_736x1312.mp4':raise ValueError('only new v32 final movie allowed')
    geometry,metadata=clock(video,1448,final=True);folder=run/'qc/final';folder.mkdir(parents=True,exist_ok=True);cards=[];joins=[]
    for before in (361,723,1085):
        a=extract(video,folder/f'join_{before:04d}.png',before);b=extract(video,folder/f'join_{before+1:04d}.png',before+1);cards.extend([card(a['path'],f'ACTUAL before join n={before}'),card(b['path'],f'ACTUAL after join n={before+1}')]);joins.append(dict(before=a,after=b,pixel_metric=metric(a['path'],b['path'])))
    board=contact(cards,folder/'JOINS_CONTACT.jpg',2);output=dict(schema=QA_SCHEMA,final_result=binding(run/'FINAL_RESULT.json'),file=final['file'],original_native_ids=ids,assembly_inputs=inputs,clock=geometry,joins=joins,join_contact=board,production_approved=False,scope='Independent CPU exact decoded clock and seam samples; pixel changes are not semantic continuity approval.')
    freeze(folder/'PROBE.json',metadata);freeze(folder/'FINAL_OBJECTIVE_QA.json',output)
    return dict(status='final_cpu_qa_complete',manifest=binding(folder/'FINAL_OBJECTIVE_QA.json'),join_contact=board,clock=geometry,production_approved=False)

def observe(run,directory,first_native_id,helper_sha256,*,max_seconds=21600,project=PROJECT):
    import psutil
    checked=validate_plan(run,project=project);run=checked['run'];directory=inside(Path(project)/'data/qa',directory)
    if type(max_seconds) is not int or not 1<=max_seconds<=28800 or not re.fullmatch('[A-Za-z0-9_-]{1,100}',first_native_id) or sha(__file__)!=helper_sha256:raise ValueError('bounded tested observer and original first ID required')
    directory.mkdir(parents=True,exist_ok=True);own=psutil.Process(os.getpid());identity=dict(pid=own.pid,create_time=own.create_time(),command=own.cmdline(),executable=own.exe(),run=str(run),helper=binding(__file__),first_native_id=first_native_id,max_seconds=max_seconds,poll_seconds=30,no_http_gpu_post=True)
    with (directory/'OBSERVER_CLAIM.json').open('x',encoding='utf-8') as f:json.dump(identity,f,ensure_ascii=False,indent=2)
    write(directory/'OBSERVER.json',identity);deadline=time.monotonic()+max_seconds;completed=[];known={IDS[0]:first_native_id}
    def save(status,**extra):write(directory/'PROGRESS.json',dict(status=status,observer_pid=own.pid,known_native_ids=known,completed=completed,no_media_retry=True,production_approved=False,**extra))
    try:
        for sid in IDS:
            while True:
                if sha(__file__)!=helper_sha256:raise ValueError('frozen helper changed during observation')
                state=read(run/'shots'/sid/'STATE.json');pid=state.get('prompt_id')
                if pid:
                    if sid in known and known[sid]!=pid:raise ValueError('original native ID changed')
                    if pid in [p for s,p in known.items() if s!=sid]:raise ValueError('native ID reused across shots')
                    known[sid]=pid
                if state['status'] in ('outcome_unknown','failed','interrupted','rejected'):raise ValueError('original native task stopped: '+state['status'])
                if state['status']=='technical_saved':
                    args=[str(Path(project)/'.venv/Scripts/python.exe'),'-X','utf8','-B',str(Path(__file__).resolve()),'segment','--run',str(run),'--segment',sid,'--asr','--project-root',str(Path(project))]
                    result=json.loads(command(args,log=directory/(sid+'.CPU.stderr.log'),timeout=1200));completed.append(result);save('segment_cpu_qa_complete',segment=sid);print(json.dumps(result,ensure_ascii=False),flush=True);break
                if time.monotonic()>=deadline:save('bounded_wait_original_ids_preserved',segment=sid);return
                time.sleep(min(30,max(.01,deadline-time.monotonic())))
        while not (run/'FINAL_RESULT.json').exists():
            if time.monotonic()>=deadline:save('bounded_wait_final_preserved');return
            time.sleep(min(30,max(.01,deadline-time.monotonic())))
        if sha(__file__)!=helper_sha256:raise ValueError('frozen helper changed before final CPU QA')
        result=qa_final(run,project=project);save('completed',final=result);print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as error:
        save('cpu_observer_stopped',error=dict(type=type(error).__name__,message=str(error)));raise

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','segment','final','observe']);p.add_argument('--run',type=Path,required=True);p.add_argument('--segment',choices=IDS);p.add_argument('--asr',action='store_true');p.add_argument('--project-root',type=Path,default=PROJECT);p.add_argument('--observer-dir',type=Path);p.add_argument('--first-native-id');p.add_argument('--helper-sha256');p.add_argument('--max-seconds',type=int,default=21600);a=p.parse_args(argv)
    if a.action=='segment':
        if not a.segment:p.error('--segment required')
        value=qa_segment(a.run,a.segment,asr=a.asr,project=a.project_root)
    elif a.action=='final':value=qa_final(a.run,project=a.project_root)
    elif a.action=='preflight':
        checked=validate_plan(a.run,project=a.project_root);value=dict(status='readonly_cpu_preflight_complete',plan=binding(checked['run']/'PLAN.json'),segments=checked['segments'],dispatch=False,production_approved=False)
    else:
        if not a.observer_dir or not a.first_native_id or not a.helper_sha256:p.error('observer-dir, first-native-id, helper-sha256 required')
        observe(a.run,a.observer_dir,a.first_native_id,a.helper_sha256,max_seconds=a.max_seconds,project=a.project_root);return 0
    print(json.dumps(value,ensure_ascii=False));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps(dict(status='cpu_qa_failed',type=type(error).__name__,message=str(error),no_media_retry=True),ensure_ascii=False));raise SystemExit(2)
