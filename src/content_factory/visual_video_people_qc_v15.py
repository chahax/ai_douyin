"""Sampled-video people upper-bound brake; never approves a scene or film.

Only the new QC directory is written. Source packet, original H3 result and its
four artifacts remain immutable. Each model request is an independent v14
PEOPLE-only target image with no expected count, guide, identity or history.
"""
from copy import deepcopy
import gc
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
from . import visual_asset_review_v3 as visual
from . import visual_asset_pipeline_v3 as pipeline
from . import visual_split_observation_v14 as people
from . import visual_worker_runtime_v6 as runtime

VERSION='sampled_video_people_upper_bound/v15'
PROJECT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return visual.file_sha(path)
def digest(value):return visual.digest(value)
def artifact(path):return dict(path=str(Path(path).resolve()),sha256=sha(path))
def write(path,value):visual._write(path,value)


def _probe(video):
    result=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height,avg_frame_rate,duration:format=duration',
        '-of','json',str(video)],capture_output=True,text=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    data=json.loads(result.stdout);stream=next(s for s in data['streams'] if s['codec_type']=='video')
    a,b=stream['avg_frame_rate'].split('/');fps=float(a)/float(b)
    value=dict(width=stream['width'],height=stream['height'],fps=fps,seconds=float(stream.get('duration',data['format']['duration'])))
    if (any(type(value[k]) is not int or not 1<=value[k]<=8192 for k in ('width','height')) or
        any(not math.isfinite(value[k]) or value[k]<=0 for k in ('fps','seconds'))):raise ValueError('invalid_video_header')
    return value


def _decoded_rgb(video,seconds):
    # Input seeking matches OBJECTIVE_QA extraction. Compare RGB, not PNG
    # metadata. No GPU decode or new generative media is involved.
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-hwaccel','none','-ss',format(seconds,'.12f'),'-i',str(video),
        '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True,timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return result.stdout


def _snapshot(h3_run,packet_file,objective_file):
    h3_run=Path(h3_run).resolve();packet_file=Path(packet_file).resolve();objective_file=Path(objective_file).resolve()
    hp=read(h3_run/'PLAN.json');packet=read(packet_file);qa=read(objective_file)
    if (hp.get('schema')!='visual_h3_handoff/v3' or hp.get('publication') is not False or hp.get('old_batch_resume') is not False or
        read(h3_run/'STATE.json').get('plan_sha256')!=digest(hp)):raise ValueError('original_h3_plan_not_bound')
    if packet.get('schema')!='visual_asset_packet/v3' or len(packet.get('shots',[]))!=1:raise ValueError('single_shot_source_packet_required')
    if packet.get('stage_contract'):
        from . import visual_continuous_stage_v6 as staging
        staging.validate_packet(packet)
    shot=packet['shots'][0];sid=shot['id'];cast=shot.get('visible_cast')
    if not isinstance(cast,list) or any(not isinstance(x,str) or not x for x in cast) or len(cast)!=len(set(cast)):
        raise ValueError('invalid_source_visible_cast')
    if not set(cast)<={c['id'] for c in packet['characters']}:raise ValueError('source_visible_cast_identity_missing')
    source=packet['source']
    if sha(source['path'])!=source['sha256'] or hp.get('source')!=source:raise ValueError('source_text_or_h3_source_changed')
    asset_plan_file=Path(hp['asset_run'])/'PLAN.json';ap=read(asset_plan_file)
    if sha(asset_plan_file)!=hp['asset_plan_sha256'] or ap.get('packet')!=packet:raise ValueError('single_packet_not_original_h3_input')
    rows=[r for r in hp['shots'] if r['id']==sid]
    if len(rows)!=1:raise ValueError('original_h3_shot_missing')
    row=rows[0];folder=h3_run/'shots'/sid;result=read(folder/'RESULT.json');state=read(folder/'STATE.json')
    if (state.get('status')!='technical_saved' or state.get('plan_sha256')!=digest(hp) or
        result.get('schema')!='visual_h3_handoff/v3' or result.get('shot_id')!=sid or
        result.get('prompt_id')!=state.get('prompt_id') or result.get('graph_sha256')!=row['graph_sha256'] or
        result.get('first_frame_sha256')!=row['first_frame']['sha256'] or
        result.get('technical_status')!='technical_saved' or result.get('content_status')!='media_review_required' or
        result.get('publication') is not False or result.get('production_approved') is not False):raise ValueError('original_h3_result_not_known_and_bound')
    if digest(read(folder/'workflow_api.json'))!=row['graph_sha256']:raise ValueError('original_h3_graph_changed')
    files=result.get('files',{})
    if set(files)!={'video','audio','first','last'}:raise ValueError('original_h3_four_outputs_required')
    outputs={}
    for role,item in files.items():
        path=Path(item['path']).resolve()
        if not path.is_relative_to(folder/'artifacts') or sha(path)!=item['sha256']:raise ValueError('original_h3_output_changed')
        outputs[role]=artifact(path)
    binding=qa.get('binding',{})
    if (binding.get('shot_id')!=sid or binding.get('prompt_id')!=result['prompt_id'] or binding.get('source')!=source or
        binding.get('audio')!=shot['audio'] or binding.get('video')!=outputs['video']):raise ValueError('objective_qa_not_source_and_video_bound')
    header=_probe(outputs['video']['path']);seconds=qa.get('seconds')
    if (type(seconds) not in (int,float) or not math.isfinite(seconds) or
        abs(seconds-header['seconds'])>max(.002,1/header['fps']) or
        abs(result['timing']['native_seconds']-seconds)>max(.002,1/header['fps'])):raise ValueError('video_duration_binding_changed')
    samples=qa.get('frames');frames=[];previous=-1
    if not isinstance(samples,list) or not 1<=len(samples)<=120:raise ValueError('bounded_frame_samples_required')
    for i,item in enumerate(samples):
        at=item.get('seconds');path=Path(item['path']).resolve()
        if (type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<header['seconds'] or at<=previous or
            not path.is_relative_to(objective_file.parent) or sha(path)!=item['sha256']):raise ValueError('invalid_or_changed_sample_time_or_image')
        image=visual.image_binding(path)
        if [image['width'],image['height']]!=[header['width'],header['height']]:raise ValueError('sample_dimensions_not_native_video')
        with Image.open(path) as actual:rgb=actual.convert('RGB').tobytes()
        if rgb!=_decoded_rgb(outputs['video']['path'],at):raise ValueError('sample_not_from_bound_video_at_time')
        frames.append(dict(index=i,seconds=at,target=image,rgb_sha256=hashlib.sha256(rgb).hexdigest()));previous=at
    return dict(source=deepcopy(source),shot_id=sid,source_shot_sha256=digest(shot),visible_cast=deepcopy(cast),allowed_people=len(cast),
        h3_run=str(h3_run),packet=artifact(packet_file),objective=artifact(objective_file),h3_plan=artifact(h3_run/'PLAN.json'),
        asset_plan=artifact(asset_plan_file),h3_result=artifact(folder/'RESULT.json'),h3_shot_state=artifact(folder/'STATE.json'),
        h3_graph=artifact(folder/'workflow_api.json'),prompt_id=result['prompt_id'],graph_sha256=result['graph_sha256'],outputs=outputs,
        native_header=header,frames=frames,model_config=visual.VisualReviewClient(ap['config']['visual_review']).config,
        decoder='ffmpeg_cpu_rgb24_input_seek_12dp/v1')


def prepare(qc_run,h3_run,packet_file,objective_file):
    """Freeze source lineage and actual decoded samples; no model dispatch."""
    qc_run=Path(qc_run).resolve();binding=_snapshot(h3_run,packet_file,objective_file)
    for path in [Path(h3_run).resolve(),Path(packet_file).resolve().parent,Path(objective_file).resolve().parent]:
        if qc_run==path or path.is_relative_to(qc_run):raise ValueError('qc_output_may_not_enclose_or_replace_inputs')
    value=dict(schema=VERSION,binding=binding,binding_sha256=digest(binding),production_approved=False,
        approval_scope='sampled_people_upper_bound_only',lower_bound_enforced=False,
        code_sha256={str(Path(path).resolve()):sha(path) for path in
            (__file__,PROJECT/'scripts/run_visual_video_people_qc_v15.py',people.__file__,visual.__file__,runtime.__file__)})
    if qc_run.exists():
        if not (qc_run/'PLAN.json').exists() or read(qc_run/'PLAN.json')!=value:raise ValueError('qc_existing_scope_changed')
        return value
    qc_run.mkdir(parents=True);write(qc_run/'PLAN.json',value);return value


def _current(qc_run):
    plan=read(qc_run/'PLAN.json');binding=plan['binding']
    if plan.get('schema')!=VERSION or plan['binding_sha256']!=digest(binding):raise ValueError('qc_plan_changed')
    if any(sha(path)!=value for path,value in plan['code_sha256'].items()):raise ValueError('qc_code_changed_after_prepare')
    actual=_snapshot(binding['h3_run'],binding['packet']['path'],binding['objective']['path'])
    if actual!=binding:raise ValueError('qc_source_result_frames_or_model_config_changed')
    return plan


def _payload(frame):
    return dict(prompt=people.PEOPLE_PROMPT,images=[dict(role='target_people',binding=deepcopy(frame['target']))],schema=people.people_schema())


def _unavailable(frame,error,*,unknown=False,dispatched=False):
    return dict(index=frame['index'],seconds=frame['seconds'],target_sha256=frame['target']['sha256'],people_count=None,evidence=[],
        status='unavailable',completion_known=not unknown,outcome_unknown=unknown,inference_dispatched=dispatched,error_type=type(error).__name__,error=str(error))


def _batch(request,infer,folder):
    results=[];aborted=False
    for frame in request['frames']:
        if aborted:results.append(_unavailable(frame,visual.ReviewOutcomeUnknown('prior frame outcome unknown; not submitted'),unknown=True));continue
        payload=_payload(frame);stem=f"FRAME_{frame['index']:04}"
        try:
            native=visual._native_call(infer,payload,folder,stem);answer=people.people_answer(visual._parse_content(native['text']))
            value=dict(index=frame['index'],seconds=frame['seconds'],target_sha256=frame['target']['sha256'],people_count=answer['people_count'],evidence=answer['evidence'],
                status='observed',completion_known=True,outcome_unknown=False,inference_dispatched=True,request_sha256=digest(payload),
                native_sha256=sha(folder/(stem+'_NATIVE.json')),model_binding=request['model_binding'])
        except visual.ReviewOutcomeUnknown as error:value=_unavailable(frame,error,unknown=True,dispatched=True);aborted=True
        except (ValueError,OSError,KeyError) as error:value=_unavailable(frame,error,dispatched=True)
        results.append(value)
    return dict(schema=VERSION,request_binding_sha256=request['request_binding_sha256'],results=results,results_sha256=digest(results),
        completion_known=all(r['completion_known'] for r in results),outcome_unknown=any(r['outcome_unknown'] for r in results))


def _worker(request_file,output_file):
    """Pinned local Qwen runtime; only independent people payloads."""
    request_file=Path(request_file).resolve();folder=request_file.parent;request=read(request_file)
    if Path(output_file).resolve()!=folder/'RESULTS.json' or request_file!=folder/'REQUEST.json' or (folder/'RESULTS.json').exists():
        raise ValueError('qc_worker_evidence_layout_changed')
    if read(folder/'CLAIM.json')['request_binding_sha256']!=request['request_binding_sha256']:raise ValueError('qc_worker_claim_changed')
    if (request['request_binding_sha256']!=digest({k:value for k,value in request.items() if k!='request_binding_sha256'}) or
        request.get('people_prompt')!=people.PEOPLE_PROMPT or request.get('people_schema')!=people.people_schema()):
        raise ValueError('qc_worker_request_changed')
    runtime.save_runtime(folder,request['request_binding_sha256']);write(folder/'WORKER_STATE.json',dict(stage='loading',at=time.time(),pid=os.getpid()))
    cfg=request['config'];actual=visual.model_binding(cfg.get('model_path',visual.DEFAULT_MODEL))
    if any(request['model_binding'].get(k)!=value for k,value in actual.items()):raise ValueError('people_vision_model_changed')
    model=processor=torch=None;calls=0
    try:
        from src.trend_intelligence.content_analysis.resource_policy import probe_resources
        resources=probe_resources()
        if resources['available_ram_gib']<6 or resources['available_vram_gib'] is None or resources['available_vram_gib']<5:
            raise visual.ReviewUnavailable('people vision requires >=6GiB RAM and >=5GiB free VRAM')
        import torch
        from transformers import AutoProcessor,Qwen3VLForConditionalGeneration,BitsAndBytesConfig
        if not torch.cuda.is_available():raise visual.ReviewUnavailable('people vision CUDA unavailable')
        torch.set_num_threads(2);torch.manual_seed(0);processor=AutoProcessor.from_pretrained(actual['model'],local_files_only=True)
        processor.image_processor.size={'shortest_edge':65536,'longest_edge':cfg.get('image_max_pixels',262144)}
        quant=cfg.get('quantization','nf4');options={}
        if quant=='nf4':options['quantization_config']=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
        elif quant!='bf16':raise ValueError('unsupported people vision quantization')
        model=Qwen3VLForConditionalGeneration.from_pretrained(actual['model'],dtype=torch.bfloat16,device_map='cuda:0',local_files_only=True,low_cpu_mem_usage=True,attn_implementation='sdpa',**options).eval()
        write(folder/'WORKER_STATE.json',dict(stage='ready',at=time.time(),pid=os.getpid(),model_binding=actual))
        def infer(payload):
            nonlocal calls
            content=[dict(type='text',text=payload['prompt']+'\nJSON_SCHEMA:\n'+json.dumps(payload['schema'],ensure_ascii=False)),
                dict(type='image',image=Image.open(io.BytesIO(visual._png(payload['images'][0]))).convert('RGB'))]
            inputs=processor.apply_chat_template([dict(role='user',content=content)],tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt').to(model.device)
            if inputs.input_ids.shape[-1]>12288:raise visual.ReviewProtocolError('people input capacity exceeded')
            calls+=1
            with torch.inference_mode():out=model.generate(**inputs,max_new_tokens=cfg['max_tokens'],do_sample=False,use_cache=True)
            tokens=out[0,inputs.input_ids.shape[-1]:];eos=model.generation_config.eos_token_id;eos=[eos] if isinstance(eos,int) else eos or []
            if not len(tokens) or int(tokens[-1]) not in eos:raise visual.ReviewProtocolError('people output missing terminal marker')
            return dict(text=processor.tokenizer.decode(tokens,skip_special_tokens=True),model=actual['model'],usage=dict(prompt_tokens=int(inputs.input_ids.shape[-1]),completion_tokens=len(tokens)),image_count=1,quantization=quant)
        result=_batch(request,infer,folder)
        if visual.model_binding(actual['model'])!=actual:raise ValueError('people model files changed during observation')
        write(folder/'RESULTS.json',result)
    except Exception as error:
        write(folder/'WORKER_ERROR.json',dict(type=type(error).__name__,message=str(error),inference_calls=calls));raise
    finally:
        if model is not None:del model
        if processor is not None:del processor
        gc.collect()
        if torch is not None and torch.cuda.is_available():torch.cuda.empty_cache()


def observe(qc_run):
    """Single-use batch. Existing complete results return without inference."""
    qc_run=Path(qc_run).resolve()
    with pipeline.images.run_lock(qc_run):
        plan=_current(qc_run);folder=qc_run/'observation';folder.mkdir(exist_ok=True)
        if (folder/'RESULTS.json').exists():return read(folder/'RESULTS.json')
        if (folder/'CLAIM.json').exists():raise visual.ReviewOutcomeUnknown('original people batch outcome unknown; no replay')
        cfg=plan['binding']['model_config'];client=visual.VisualReviewClient(cfg);model=client.discover()
        if not model.get('available'):raise visual.ReviewUnavailable(model.get('error','people vision unavailable'))
        request=dict(schema=VERSION,config=client.config,frames=deepcopy(plan['binding']['frames']),model_binding=model,
            people_prompt=people.PEOPLE_PROMPT,people_schema=people.people_schema())
        request['request_binding_sha256']=digest(request);pipeline.freeze(folder/'REQUEST.json',request)
        asset_plan=read(plan['binding']['asset_plan']['path'])
        with pipeline.gpu_access(asset_plan):
            with (folder/'CLAIM.json').open('x',encoding='utf-8') as stream:json.dump(dict(at=time.time(),request_binding_sha256=request['request_binding_sha256']),stream)
            if client.provider!='transformers_local':result=_batch(request,client._infer_http,folder);write(folder/'RESULTS.json',result)
            else:
                env=os.environ.copy();env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(folder/'cache'),PYTHONUTF8='1')
                command=[sys.executable,'-B',str(PROJECT/'scripts/run_visual_video_people_qc_v15.py'),'worker','--request',str(folder/'REQUEST.json'),'--output',str(folder/'RESULTS.json')]
                options,receipt=runtime.prepare(command,env);runtime.save_launch(folder,receipt)
                try:
                    with (folder/'worker.log').open('ab') as log:process=subprocess.run(command,cwd=PROJECT,**options,stdout=log,stderr=subprocess.STDOUT,
                        timeout=cfg['timeout']*len(request['frames']),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    write(folder/'WORKER_EXIT.json',dict(exited=True,code=process.returncode,request_binding_sha256=request['request_binding_sha256']))
                except subprocess.TimeoutExpired:
                    write(folder/'WORKER_EXIT.json',dict(exited=True,terminated_on_timeout=True,request_binding_sha256=request['request_binding_sha256']));raise visual.ReviewOutcomeUnknown('people worker timed out; original claim retained')
                if process.returncode or not (folder/'RESULTS.json').exists():
                    failure=read(folder/'WORKER_ERROR.json') if (folder/'WORKER_ERROR.json').exists() else {}
                    if failure.get('inference_calls')==0 and not list(folder.glob('FRAME_*_CLAIM.json')):
                        values=[_unavailable(frame,visual.ReviewUnavailable(failure.get('message','worker failed before inference'))) for frame in request['frames']]
                        result=dict(schema=VERSION,request_binding_sha256=request['request_binding_sha256'],results=values,results_sha256=digest(values),
                            completion_known=True,outcome_unknown=False,preflight_failure=artifact(folder/'WORKER_ERROR.json'))
                        write(folder/'RESULTS.json',result)
                    else:raise visual.ReviewOutcomeUnknown('people worker failed; retained native claims must be audited')
                result=read(folder/'RESULTS.json')
        _current(qc_run);return result


def apply(qc_run):
    """Record a brake, never mutate H3 state or claim identity/layout approval."""
    qc_run=Path(qc_run).resolve()
    with pipeline.images.run_lock(qc_run):
        plan=_current(qc_run);binding=plan['binding'];folder=qc_run/'observation';request=read(folder/'REQUEST.json');batch=read(folder/'RESULTS.json')
        expected={k:value for k,value in request.items() if k!='request_binding_sha256'}
        if (request.get('schema')!=VERSION or request['request_binding_sha256']!=digest(expected) or
            read(folder/'CLAIM.json')['request_binding_sha256']!=request['request_binding_sha256'] or request['frames']!=binding['frames'] or
            request['config']!=binding['model_config'] or request['people_prompt']!=people.PEOPLE_PROMPT or request['people_schema']!=people.people_schema() or
            batch.get('request_binding_sha256')!=request['request_binding_sha256'] or batch.get('results_sha256')!=digest(batch['results']) or
            len(batch['results'])!=len(binding['frames'])):raise ValueError('people_native_batch_binding_changed')
        violations=[];uncertain=[];observations=[]
        for frame,value in zip(binding['frames'],batch['results']):
            if any(value.get(key)!=frame[key] for key in ('index','seconds')) or value.get('target_sha256')!=frame['target']['sha256']:raise ValueError('people_frame_result_changed')
            stem=f"FRAME_{frame['index']:04}";count=None
            if value.get('status')=='observed':
                native=read(folder/(stem+'_NATIVE.json'));payload=_payload(frame)
                if (read(folder/(stem+'_REQUEST.json'))!=payload or read(folder/(stem+'_CLAIM.json'))['request_sha256']!=digest(payload) or
                    value.get('request_sha256')!=digest(payload) or
                    value.get('native_sha256')!=sha(folder/(stem+'_NATIVE.json')) or value.get('model_binding')!=request['model_binding'] or
                    value.get('completion_known') is not True or value.get('outcome_unknown') is not False):raise ValueError('people_frame_native_proof_changed')
                answer=people.people_answer(visual._parse_content(native['text']));count=answer['people_count']
                if value.get('people_count')!=count or value.get('evidence')!=answer['evidence']:raise ValueError('people_count_changed_after_native')
            elif value.get('people_count') is not None:raise ValueError('unavailable_people_count_must_remain_unknown')
            item=dict(index=frame['index'],seconds=frame['seconds'],target_sha256=frame['target']['sha256'],people_count=count,
                completion_known=value.get('completion_known') is True,outcome_unknown=value.get('outcome_unknown') is True)
            observations.append(item)
            if count is None:uncertain.append(item)
            elif count>binding['allowed_people']:violations.append(item)
        decision='hard_rejected_people_upper_bound' if violations else 'needs_review_unknown' if uncertain else 'needs_semantic_review'
        result=dict(schema=VERSION,decision=decision,hard_reject=bool(violations),allowed_people=binding['allowed_people'],visible_cast=binding['visible_cast'],
            shot_id=binding['shot_id'],prompt_id=binding['prompt_id'],video_sha256=binding['outputs']['video']['sha256'],source=binding['source'],
            observations=observations,violations=violations,unknown=uncertain,sampled_people_upper_bound_pass=not violations and not uncertain,
            lower_bound_enforced=False,semantic_review_required=True,identity_approved=False,environment_approved=False,duration_approved=False,production_approved=False,
            outcome_unknown=any(r['outcome_unknown'] for r in observations),completion_known=all(r['completion_known'] for r in observations),
            plan_sha256=sha(qc_run/'PLAN.json'),request_sha256=sha(folder/'REQUEST.json'),native_results_sha256=sha(folder/'RESULTS.json'),
            scope='sampled frames only; no guarantee between samples; no identity, room, motion or audio approval',original_h3_records_modified=False)
        output=qc_run/'DECISION.json'
        if output.exists() and read(output)!=result:raise ValueError('immutable_people_decision_changed')
        if not output.exists():write(output,result)
        return result
