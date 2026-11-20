"""Manifest-driven full-script local H3; frozen sources, serial IDs, variable duration."""
import argparse
import copy
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import time


def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


b=module('full_batch_primitives','run_h3_six_children_batch_20261102.py')
c=module('full_validation_primitives','run_h3_batch_validation_resume_20261102.py')
h=b.h
RUN=h.ROOT/'data/video_generation/h3_six_children_full_script_20261102'
PREFIX='six_children_full_script_20261102'
OPENING=h.SEEDANCE/'assets/opening.original.jpeg'
PENDING=h.ROOT/'data/video_generation/h3_six_children_60s_20261102_validation_resume/S02'
PENDING_ID='f3c06d32-e3fc-426f-bd1d-5d7d02b87e62'
SCENE_CONTINUATIONS={'CH01_SC02','CH02_SC01','CH03_SC01'}
ENVIRONMENTS={'CH01_SC01':'adult_room','CH01_SC02':'adult_room','CH01_SC03':'children_room',
 'CH02_SC01':'children_room','CH02_SC02':'kitchen','CH02_SC03':'children_room','CH02_SC04':'kitchen','CH02_SC05':'kitchen',
 'CH03_SC01':'kitchen','CH03_SC02':'doorway','CH03_SC03':'breakfast','CH03_SC04':'home_day',
 'CH03_SC05':'street','CH03_SC06':'alley','CH03_SC07':'alley'}
STYLE='现实向中国家庭伦理剧，生活化写实，中近景与神情特写交织，镜头平顺，信息随着动作与对白持续推进。'
COSTUMES='造型沿原稿：苏墨深色夹克、素色衬衫、深色长裤；叶东洗白旧短袖；叶南旧短袖挽袖；叶北叶寻同款旧衣；叶嫣儿浅色碎花裙、白袜；叶西决破洞旧衣、旧布鞋；高个人贩子深灰旧夹克，矮个人贩子土黄旧夹克。仅当原段安排人物出场时出现。'


def prompt_for(segment,scene,blocks,previous_units,mode):
    sounds=[a for u in segment['units'] for a in u['audio_items']]
    visual=[]
    for unit in segment['units']:
        visible=visible_text(unit)
        if visible:visual.append(visible)
    context=[dict(id=u['id'],text=u['text']) for u in previous_units[-2:]]
    source=dict(duration_seconds=segment['native_seconds'],scene=scene['heading'],
      scene_initial_metadata_context_only=[m['text'] for m in scene['metadata']],
      previous_context_only=context,
      current_visual_source=visual,
      audio_items=[dict(speaker=a['speaker'],channel=a['channel'],text=a['text']) for a in sounds])
    intro=(STYLE+'\n'+COSTUMES+'\n'
      '制作映射：audio_items按顺序逐字出声，人物、声道沿条目保持；导演标签与上下文是表演依据。'
      '长旁白的父段只用于理解，发声范围取当前audio_items。'
      '当下动作推进按current_visual_source，场次初态只在该场开头建立，后续承接前段结束状态。'
      '旁白涉及穿越经历、未来或酷刑往事时，用当前人物神情、环境与手部反应承载，明确画外叙述时空。'
      '绑架救援段保留剧情，通过克制的动作、表情、声音表现危险和救援，伤情用衣物尘土与轻微擦痕表现。'
      '原文未署名的声音保持画外声。对白自然紧凑，动作和反应同步推进。\n')
    if mode=='REF2VA':
        intro+='<Picture 1>提供已有苏墨、叶南、叶西决的造型；其余参考图提供此前已出现人物与场景外观。新场的时空、入场人物和动作依当前场原文建立。\n'
    if segment['id']=='F0001':
        intro+='开场镜头为苏墨闭眼躺在旧木板床上的脸部近景，画框只容苏墨脸部与少量旧枕头。孩子的台词从画外传来，童声衔接后续入镜。\n'
    return intro+json.dumps(source,ensure_ascii=False,indent=2)


def visible_text(unit):
    text=unit['text'];offset=unit['start'];cursor=0;pieces=[]
    for item in unit['audio_items']:
        a=max(0,item['start']-offset);z=min(len(text),item['end']-offset)
        pieces.append(text[cursor:a]);cursor=z
    pieces.append(text[cursor:]);text=''.join(pieces)
    text=re.sub(r'\*\*【[^】]*(?:旁白|心声|未署名)[^】]*】\*\*','',text)
    text=re.sub(r'\*\*旁白（[^）]*）\*\*[：:]?','',text)
    text=re.sub(r'(?m)^.*（[^）]*(?:心声|内心|旁白)[^）]*）\s*$','',text)
    return text.strip()


def build_graph(base,prompt,segment,mode,references):
    graph=copy.deepcopy(base)
    graph['129']['inputs']['noise_seed']=2026110300+int(segment['id'][1:])
    graph['pick_last']['inputs']['batch_index']=segment['native_frames']-1
    if mode=='REF2VA':
        graph['127']['inputs']['unet_name']='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
        condition=dict(clip=['128',0],vae=['119',0],audio_vae=['120',0],prompt=prompt,width=736,height=1312,
                       length=segment['native_frames'],ref_image_size='match')
        del graph['ref_scene']
        for i,reference in enumerate(references):
            name='reference_'+str(i)
            graph[name]=dict(class_type='LoadImage',inputs=dict(image=reference['input_name']))
            condition['ref_images.ref_image_'+str(i)]=[name,0]
        graph['condition']=dict(class_type='MiniMaxH3ReferenceToVideo',inputs=condition)
    else:
        graph['ref_scene']['inputs']['image']=references[0]['input_name']
        graph['condition']['inputs'].update(prompt=prompt,length=segment['native_frames'])
    for role in ('video','audio','first','last'):
        graph['save_'+role]['inputs']['filename_prefix']=PREFIX+'/'+segment['id']+'/'+role
    return graph


def prepare(run=RUN):
    if (run/'PLAN.json').exists():raise ValueError('already_prepared')
    coverage=h.read(run/'COVERAGE.json')
    base=h.read(b.SERVICE/'workflow_api.json')
    scenes={s['id']:s for s in coverage['scenes']}
    blocks={p['id']:p for s in scenes.values() for p in s['blocks']}
    items=[];previous_units=[];last_environment={};previous_scene=None
    for segment in coverage['segments']:
        identity=segment['id'];scene_id=segment['scene'];first=scene_id!=previous_scene
        mode='FL2VA' if items and (not first or scene_id in SCENE_CONTINUATIONS) else 'REF2VA'
        references=[]
        if not items or mode=='REF2VA':references.append(dict(kind='opening',source=h.binding(OPENING)))
        if items:references.append(dict(kind='segment_tail',segment=items[-1]['id']))
        environment=ENVIRONMENTS[scene_id]
        if mode=='REF2VA' and environment in last_environment and last_environment[environment]!=items[-1]['id']:
            references.append(dict(kind='segment_tail',segment=last_environment[environment]))
        for index,reference in enumerate(references):
            reference['input_name']=PREFIX+'_'+identity+'_ref'+str(index)+('.jpeg' if reference['kind']=='opening' else '.png')
        prompt=prompt_for(segment,scenes[scene_id],blocks,previous_units,mode)
        folder=run/identity;(folder/'deliverables').mkdir(parents=True,exist_ok=True)
        (folder/'PROMPT.txt').write_text(prompt,encoding='utf-8')
        graph=build_graph(base,prompt,segment,mode,references)
        h.durable(folder/'workflow_api.json',graph,immutable=True)
        h.durable(folder/'STATE.json',dict(status='prepared',prompt_id=None,submissions=0))
        items.append(dict(id=identity,chapter=segment['chapter'],scene=scene_id,mode=mode,frames=segment['native_frames'],
                          references=references,prompt=h.binding(folder/'PROMPT.txt'),graph=h.binding(folder/'workflow_api.json'),
                          source_unit_ids=[u['id'] for u in segment['units']],identity_review='unreviewed'))
        previous_units.extend(segment['units']);previous_scene=scene_id;last_environment[environment]=identity
    wrapper=run/'native_validation_traced.py'
    wrapper.write_text("import faulthandler,runpy\nfaulthandler.enable()\nfaulthandler.dump_traceback_later(45,repeat=True)\nrunpy.run_path("+repr(str(b.VALIDATOR))+",run_name='__main__')\n",encoding='utf-8')
    refmodel=h.MODEL_ROOT/'diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors'
    models=h.read(b.SERVICE/'PLAN.json')['models']+[dict(path=str(refmodel),bytes=refmodel.stat().st_size,mtime_ns=refmodel.stat().st_mtime_ns)]
    plan=dict(schema='h3_full_script_manifest/v1',scope='all three existing final chapter scripts',coverage=h.binding(run/'COVERAGE.json'),
      source=coverage['source'],run_chain=coverage['run_chain'],code=h.binding(__file__),base_code=h.binding(b.__file__),
      validation_code=h.binding(c.__file__),helper=h.binding(h.__file__),validator=h.binding(b.VALIDATOR),wrapper=h.binding(wrapper),
      service_environment=h.binding(b.SERVICE/'SERVER_STARTED.json'),models=models,segments=items,
      pending_prior_task=dict(run=str(PENDING),prompt_id=PENDING_ID,graph=h.binding(PENDING/'workflow_api.json')),
      timeout_seconds=300,content_status='awaiting_human_review',identity_review='unreviewed',total_frames=sum(i['frames'] for i in items))
    h.durable(run/'PLAN.json',plan,immutable=True)
    h.durable(run/'STATE.json',dict(status='prepared',active_segment=None,completed=[]))
    return plan


def validate(run,review=True):
    plan=h.read(run/'PLAN.json')
    for value in plan.values():
        if isinstance(value,dict) and 'sha256' in value:b.bound_ok(value)
    b.bound_ok(plan['pending_prior_task']['graph'])
    for item in plan['segments']:
        b.bound_ok(item['graph']);b.bound_ok(item['prompt'])
        for ref in item['references']:
            if ref['kind']=='opening':b.bound_ok(ref['source'])
    for model in plan['models']:
        st=Path(model['path']).stat()
        if st.st_size!=model['bytes'] or st.st_mtime_ns!=model['mtime_ns']:raise ValueError('model_changed')
    if review:
        permission=h.read(run/'PRIMARY_DISPATCH_REVIEW.json')
        if permission.get('approved_full_manifest') is not True or permission.get('plan_sha256')!=h.sha(run/'PLAN.json'):
            raise ValueError('full_manifest_review_required')
    return plan


def freeze_inputs(batch,run,previous,client):
    plan=validate(batch)
    item=next(i for i in plan['segments'] if i['id']==run.name)
    frozen=dict(plan=h.binding(batch/'PLAN.json'),graph=item['graph'])
    for index,reference in enumerate(item['references']):
        if reference['kind']=='opening':source=reference['source']
        else:
            prior=batch/reference['segment'];receipt=b.verify_saved(prior,client)
            source=receipt['files']['last']
            frozen['prior_receipt_'+str(index)]=h.binding(prior/'receipt.json')
            frozen['prior_history_'+str(index)]=h.binding(prior/'HISTORY.json')
        target=b.SERVICE/'input'/reference['input_name']
        h.original_copy(source['path'],target)
        frozen['source_'+str(index)]=source;frozen['input_'+str(index)]=h.binding(target)
    h.durable(run/'FROZEN_INPUT.json',frozen,immutable=True)


def native_validate(run):
    # Reuse the isolated timeout-safe subprocess primitive, replacing its old-run
    # authorization lookup with this manifest's own frozen validation contract.
    original=c.validate_continuation
    c.validate_continuation=lambda root,require_review=False:validate(root,review=False)
    try:return c.native_validate(run)
    finally:c.validate_continuation=original


def collect(run,entry,state):
    graph=h.read(run/'workflow_api.json');frames=graph['condition']['inputs']['length']
    files={}
    for role,kind,suffix in [('video','images','mp4'),('audio','audio','flac'),('first','images','png'),('last','images','png')]:
        rows=entry['outputs']['save_'+role][kind]
        if len(rows)!=1 or rows[0]['type']!='output':raise ValueError('unexpected_output')
        row=rows[0];source=(b.SERVICE/'output'/row.get('subfolder','')/row['filename']).resolve()
        if not source.is_relative_to((b.SERVICE/'output'/PREFIX/run.name).resolve()):raise ValueError('output_escape')
        files[role]=dict(original_service_path=str(source),**h.original_copy(source,run/f'native_{role}.{suffix}'))
    native=h.metadata(files['video']['path']);v,a=b.streams(native)
    if (v['width'],v['height'],int(v['nb_frames']),v['r_frame_rate'])!=(736,1312,frames,'24/1'):raise ValueError('native_metadata_mismatch')
    target=run/'deliverables'/f'{run.name}_720x1280.mp4'
    command=['ffmpeg','-nostdin','-v','warning','-i',files['video']['path'],'-vf','crop=720:1280:8:16','-c:v','libx264','-crf','18',
             '-preset','medium','-c:a','copy','-movflags','+faststart',str(target)]
    b.run_ffmpeg_once(run,'CROP',command,target)
    delivery=h.metadata(target);v,a=b.streams(delivery)
    if (v['width'],v['height'],int(v['nb_frames']),v['r_frame_rate'])!=(720,1280,frames,'24/1'):raise ValueError('delivery_metadata_mismatch')
    receipt=dict(prompt_id=state['prompt_id'],technical_status='succeeded',content_status='awaiting_human_review',identity_review='unreviewed',
                 files=files,delivery=h.binding(target),native_metadata=native,delivery_metadata=delivery,frames=frames)
    h.durable(run/'receipt.json',receipt,immutable=True)
    h.durable(run/'ASSET_KEYFRAMES.json',dict(first=files['first'],last=files['last'],identity_review='unreviewed'),immutable=True)
    state.update(status='saved',delivery=str(target.resolve()));h.durable(run/'STATE.json',state);return receipt


def drain_prior(run,client,sleep=time.sleep):
    plan=validate(run);prior=plan['pending_prior_task'];folder=Path(prior['run']);graph=h.read(folder/'workflow_api.json')
    deadline=time.monotonic()+21600
    while True:
        history=client.get('/history/'+prior['prompt_id'])
        h.durable(run/'PRIOR_TASK_HISTORY.latest.json',history)
        entry=b.check_history(history,prior['prompt_id'],graph)
        if entry and entry['status'].get('status_str')=='error':
            h.durable(run/'PRIOR_TASK_FAILED.json',dict(prompt_id=prior['prompt_id'],history=history),immutable=True)
            raise ValueError('prior_task_failed_requires_review')
        if entry and entry['status'].get('completed'):
            if entry['status']['status_str']!='success':raise ValueError('prior_task_failed_requires_review')
            if not (folder/'receipt.json').exists():
                h.durable(folder/'HISTORY.json',history,immutable=True)
                c.b.collect(folder,entry,h.read(folder/'STATE.json'))
            c.b.verify_saved(folder,client)
            h.durable(run/'PRIOR_TASK_SAVED.json',dict(prompt_id=prior['prompt_id'],receipt=h.binding(folder/'receipt.json'),
                      full_script_coverage_credit=False),immutable=True)
            return
        if time.monotonic()>deadline:raise TimeoutError('prior_task_still_running_no_resubmit')
        sleep(30)


def assembly_group(folder,receipts,label):
    folder.mkdir(parents=True,exist_ok=True)
    inputs=[Path(r['delivery']['path']) for r in receipts];frames=[r['frames'] for r in receipts]
    for receipt in receipts:b.bound_ok(receipt['delivery'])
    listing=folder/(label+'.txt')
    listing.write_text(''.join("file '"+p.as_posix().replace("'","'\\''")+"'\nduration "+f'{n/24:.12f}'+'\n' for p,n in zip(inputs,frames)),encoding='utf-8')
    target=folder/(label+'.mp4')
    command=['ffmpeg','-nostdin','-v','warning','-f','concat','-safe','0','-i',str(listing)]
    for p in inputs:command+=['-i',str(p)]
    filters=[f'[{i+1}:a]apad,atrim=duration={n/24:.12f},asetpts=PTS-STARTPTS[a{i}]' for i,n in enumerate(frames)]
    filters.append(''.join(f'[a{i}]' for i in range(len(inputs)))+f'concat=n={len(inputs)}:v=0:a=1[aout]')
    command+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[aout]','-c:v','copy','-c:a','aac','-b:a','192k',
              '-t',f'{sum(frames)/24:.12f}','-movflags','+faststart',str(target)]
    b.run_ffmpeg_once(folder,label,command,target)
    metadata=h.metadata(target);v,a=b.streams(metadata)
    if (v['width'],v['height'],int(v['nb_frames']),v['r_frame_rate'])!=(720,1280,sum(frames),'24/1'):raise ValueError('assembly_metadata_mismatch')
    if abs(float(v['duration'])-sum(frames)/24)>.001 or abs(float(a['duration'])-sum(frames)/24)>.05:raise ValueError('assembly_av_duration_mismatch')
    packet_command=['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=pts_time','-of','json',str(target)]
    packets=json.loads(subprocess.run(packet_command,capture_output=True,text=True,check=True).stdout)['packets']
    pts=sorted(float(p['pts_time']) for p in packets)
    if len(pts)!=sum(frames) or any(abs(z-a-1/24)>.0001 for a,z in zip(pts,pts[1:])):raise ValueError('assembly_pts_discontinuous')
    result=dict(frames=sum(frames),delivery=h.binding(target),metadata=metadata,pts_continuous=True)
    h.durable(folder/(label+'.receipt.json'),result,immutable=True);return result


def assemble_all(run,receipts):
    # Groups bound Windows command length even for hundreds of segments.
    level=receipts;depth=0
    while len(level)>12:
        level=[assembly_group(run/'assembly',level[i:i+12],f'level{depth}_{i//12:03d}') for i in range(0,len(level),12)]
        depth+=1
    result=assembly_group(run/'deliverables',level,'six_children_full_script_review')
    result.update(technical_status='succeeded',content_status='awaiting_human_review',identity_review='unreviewed',segments=len(receipts))
    h.durable(run/'receipt.json',result,immutable=True);return result


def execute(run=RUN,client=None):
    client=client or h.Client()
    with h.process_lock(run/'.full_script.lock'):
        plan=validate(run)
        if (run/'receipt.json').exists():
            receipt=h.read(run/'receipt.json');b.bound_ok(receipt['delivery']);return receipt
        drain_prior(run,client)
        old_freezer=b.freeze_predecessor;b.freeze_predecessor=freeze_inputs
        receipts=[];previous=None
        try:
            for item in plan['segments']:
                folder=run/item['id']
                h.durable(run/'STATE.json',dict(status='running',active_segment=item['id'],completed=[r['prompt_id'] for r in receipts],total=len(plan['segments'])))
                receipts.append(b.execute_segment(run,folder,previous,client,validate_fn=native_validate,collect_fn=collect))
                previous=folder
            result=assemble_all(run,receipts)
            h.durable(run/'STATE.json',dict(status='saved',active_segment=None,completed=len(receipts),delivery=result['delivery'],content_status='awaiting_human_review'))
            return result
        except Exception as error:
            state=h.read(run/'STATE.json');state.update(status='stopped',error_type=type(error).__name__,error=str(error));h.durable(run/'STATE.json',state);raise
        finally:b.freeze_predecessor=old_freezer


def validate_first(run=RUN):
    validate(run)
    freeze_inputs(run,run/'F0001',None,h.Client())
    native_validate(run/'F0001')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','execute','validate_first']);parser.add_argument('--run',type=Path,default=RUN)
    args=parser.parse_args();globals()[args.command](args.run)
