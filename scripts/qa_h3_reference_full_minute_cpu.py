"""CPU-only QA of existing full-minute v20 reference deliveries.

No dispatcher/model API is imported. Native inputs, STATE and RESULT are read-only.
ASR uses the existing offline CPU script and does not grant content approval.
"""
import argparse
from datetime import datetime,timezone
from difflib import SequenceMatcher
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from PIL import Image,ImageDraw

PROJECT=Path(__file__).resolve().parents[1]
VERSION='h3_reference_full_minute_cpu_qa/v1'
IDS=('S01','S02','S03','S04')
COUNTS={'S01':3,'S02':2,'S03':2,'S04':3}
REFERENCES={'character:su_mo:front','character:ye_nan:front','character:ye_xijue:front','place:su_mo_room:front','place:su_mo_room:side'}


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def norm(text):return ''.join(c for c in text if c.isalnum())
def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def freeze(path,value):
    if Path(path).exists():
        if read(path)!=value:raise ValueError('CPU QA input binding changed; preserve existing QA')
    else:write(path,value)
def bound(root,path):
    path=Path(path).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root) or path==root:raise ValueError('QA path outside required scope')
    return path
def minute_root(run,project):
    project=Path(project).resolve();run=bound(project/'data/video_generation',run)
    if run.parent!=project/'data/video_generation' or not re.fullmatch(r'h3_reference_full_minute_[A-Za-z0-9_-]+',run.name):raise ValueError('new reference minute namespace required')
    return run
def command(args,*,log=None,timeout=180):
    p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if log:Path(log).write_text(p.stderr,encoding='utf-8')
    p.check_returncode();return p.stdout
def probe(path):return json.loads(command(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(path)]))


def validate_segment(run,sid,delivery,source_prompt,project):
    run=minute_root(run,project)
    if sid not in IDS:raise ValueError('unknown minute segment')
    delivery=bound(Path(project).resolve()/'data/video_generation/visual_h3_ref_v20',delivery)
    plan=read(delivery/'PLAN.json')
    if plan.get('schema')!='visual_h3_reference_delivery/v20' or len(plan.get('shots',[]))!=1:raise ValueError('one true v20 reference delivery required')
    row=plan['shots'][0];native_id=row['id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',native_id):raise ValueError('unsafe native shot id')
    folder=delivery/'shots'/native_id;state=read(folder/'STATE.json');result=read(folder/'RESULT.json')
    if state.get('status')!='technical_saved' or result.get('technical_status')!='technical_saved':raise ValueError('native technical save required before CPU QA')
    pid=result.get('prompt_id')
    if not isinstance(pid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',pid) or state.get('prompt_id')!=pid or result.get('shot_id')!=native_id:raise ValueError('native ID/result binding mismatch')
    if state.get('result_sha256')!=sha(folder/'RESULT.json'):raise ValueError('native RESULT changed')
    if (plan['config'].get('width'),plan['config'].get('height'),row.get('timing',{}).get('native_frames'))!=(736,1312,362):raise ValueError('formal reference minute geometry required; no old/probe reuse')
    if set(row.get('input_mapping',{}))!=REFERENCES:raise ValueError('all three actors and same-room front/side required')
    graph=read(folder/'workflow_api.json');condition=graph['condition']
    if condition.get('class_type')!='MiniMaxH3ReferenceToVideo' or any(k in condition['inputs'] for k in ('first_frame','last_frame')):raise ValueError('true reference mode required')
    if graph['127']['inputs'].get('unet_name')!='minimax_h3_ref2va_pruned_int8_convrot.safetensors':raise ValueError('reference checkpoint required')
    loaded=[n['inputs'].get('image') for n in graph.values() if n.get('class_type')=='LoadImage']
    if len(loaded)!=5 or set(loaded)!=set(row['input_mapping'].values()):raise ValueError('five actual independent reference inputs required')
    if fingerprint(graph)!=row['graph_sha256'] or result.get('graph_sha256')!=row['graph_sha256'] or result.get('reference_bundle_sha256')!=row['bundle_sha256']:raise ValueError('native graph/reference binding changed')
    source=bound(run,source_prompt or run/'drafts'/(sid+'.adapted.prompt.txt'))
    if sha(source)!=row['source_prompt_sha256'] or result.get('source_prompt_sha256')!=row['source_prompt_sha256']:raise ValueError('source prompt binding changed')
    quotes=re.findall('[“「]([^”」]+)[”」]',source.read_text(encoding='utf-8'))
    if len(quotes)!=COUNTS[sid]:raise ValueError('original quote coverage changed')
    if set(result.get('files',{}))!={'video','audio','first','last'}:raise ValueError('native originals incomplete')
    for value in result['files'].values():
        path=bound(folder/'artifacts',value['path'])
        if not path.is_file() or sha(path)!=value['sha256']:raise ValueError('native original file hash changed')
    protected=plan.get('protected_pause')
    if protected and sha(protected['path'])!=protected['sha256']:raise ValueError('protected legacy pause changed')
    return run,delivery,folder,plan,result,source,quotes


def transcribe(project,wav,out,folder):
    project=Path(project).resolve();script=project/'scripts/transcribe_video_local.py'
    if '"device": "cpu"' not in script.read_text(encoding='utf-8'):raise ValueError('explicit CPU ASR setting required')
    env=os.environ.copy();env.update(CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONIOENCODING='utf-8')
    for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='2'
    old_logs=[folder/name for name in ('ASR.stdout.log','ASR.stderr.log') if (folder/name).exists()]
    if old_logs:
        archive=folder/'ASR_ATTEMPTS'/uuid.uuid4().hex;archive.mkdir(parents=True)
        for path in old_logs:shutil.copyfile(path,archive/path.name)
    with (folder/'ASR.stdout.log').open('w',encoding='utf-8') as stdout,(folder/'ASR.stderr.log').open('w',encoding='utf-8') as stderr:
        subprocess.run([str(project/'.venv/Scripts/python.exe'),'-X','utf8',str(script),str(wav),str(out),'--without-punctuation','--hotword','苏墨 叶南 叶西决 二哥 哥哥 白面包'],cwd=project,env=env,stdout=stdout,stderr=stderr,timeout=600,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def qa_segment(run,sid,delivery,*,source_prompt=None,asr=False,project=PROJECT):
    run,delivery,native_folder,plan,result,source,quotes=validate_segment(run,sid,delivery,source_prompt,project)
    pid=result['prompt_id'];folder=run/'qc'/sid/pid;folder.mkdir(parents=True,exist_ok=True)
    video=result['files']['video'];binding=dict(route='true reference-image delivery/v20; formal full-minute, not v19 or low-resolution probe',segment=sid,native_shot_id=result['shot_id'],
        delivery_run=str(delivery),result_path=str(native_folder/'RESULT.json'),result_sha256=sha(native_folder/'RESULT.json'),plan_sha256=sha(delivery/'PLAN.json'),
        source_prompt=dict(path=str(source),sha256=sha(source)),prompt_id=pid,video=video,reference_bundle_sha256=result['reference_bundle_sha256'],reference_ids=sorted(REFERENCES))
    freeze(folder/'BINDING.json',binding)
    metadata=probe(video['path']);freeze(folder/'PROBE.json',metadata)
    v=next(s for s in metadata['streams'] if s['codec_type']=='video');a=next(s for s in metadata['streams'] if s['codec_type']=='audio')
    if (v['width'],v['height'],int(v['nb_frames']),int(v['nb_read_frames']),v['r_frame_rate'],v['avg_frame_rate'])!=(736,1312,362,362,'24/1','24/1'):raise ValueError('actual native geometry/frame count mismatch')
    if abs(float(v['duration'])-362/24)>.001:raise ValueError('actual native duration mismatch')
    frames=[];cards=[]
    for i,fraction in enumerate((0,.1,.3,.5,.7,.9)):
        t=fraction*362/24;path=folder/f'frame_{i:02d}.png'
        if not path.exists():command(['ffmpeg','-nostdin','-v','error','-hwaccel','none','-ss',str(t),'-i',video['path'],'-frames:v','1',str(path)])
        with Image.open(path) as image:
            if image.size!=(736,1312):raise ValueError('CPU sampled frame size mismatch')
            card=Image.new('RGB',(368,682),'white');card.paste(image.convert('RGB').resize((368,656)),(0,26));ImageDraw.Draw(card).text((4,6),f'R {sid} {t:.3f}s',fill='black');cards.append(card)
        frames.append(dict(path=str(path),sha256=sha(path),seconds=t))
    last=folder/'native_last.png'
    if not last.exists():shutil.copyfile(result['files']['last']['path'],last)
    if sha(last)!=result['files']['last']['sha256']:raise ValueError('native last copy changed')
    with Image.open(last) as image:
        card=Image.new('RGB',(368,682),'white');card.paste(image.convert('RGB').resize((368,656)),(0,26));ImageDraw.Draw(card).text((4,6),sid+' R native LAST',fill='black');cards.append(card)
    contact=folder/'CONTACT.jpg'
    if not contact.exists():
        canvas=Image.new('RGB',(736,2728),'white')
        for i,card in enumerate(cards):canvas.paste(card,((i%2)*368,(i//2)*682))
        canvas.save(contact,quality=93)
    wav=folder/'embedded_audio_16k.wav'
    if not wav.exists():command(['ffmpeg','-nostdin','-v','error','-i',video['path'],'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)])
    levels=folder/'audio_levels.log'
    if not levels.exists():command(['ffmpeg','-nostdin','-hide_banner','-i',video['path'],'-vn','-af','silencedetect=noise=-38dB:d=0.5,volumedetect','-f','null','-'],log=levels)
    raw=levels.read_text(encoding='utf-8');signal={k:float(m.group(1)) if (m:=re.search(k+r':\s*(-?[\d.]+) dB',raw)) else None for k in ('mean_volume','max_volume')}
    transcript=folder/'ASR.json'
    if asr and not transcript.exists():transcribe(project,wav,transcript,folder)
    words=''.join(r.get('text','') for r in read(transcript).get('result',[]) if isinstance(r,dict)) if transcript.exists() else None
    source_text=norm(''.join(quotes));actual=norm(words) if words is not None else None;diff=[]
    if actual is not None:
        for kind,i,j,m,n in SequenceMatcher(None,source_text,actual,autojunk=False).get_opcodes():
            if kind!='equal':diff.append(dict(kind=kind,expected=source_text[i:j],recognized=actual[m:n]))
    output=dict(schema=VERSION,binding=binding,expected_quoted_speech=quotes,
        geometry=dict(width=v['width'],height=v['height'],frames=int(v['nb_frames']),decoded_frames=int(v['nb_read_frames']),fps=v['r_frame_rate'],seconds=float(v['duration'])),
        audio_metadata={k:a.get(k) for k in ('codec_name','sample_rate','channels','duration')},signal=signal,silence_events=[line for line in raw.splitlines() if 'silence_' in line],
        frames=frames,native_last=dict(path=str(last),sha256=sha(last)),contact=dict(path=str(contact),sha256=sha(contact)),
        asr_status='completed' if words is not None else 'not_requested',asr_text=words,asr_normalized=actual,asr_differences=diff,normalized_matches=source_text==actual if actual is not None else None,
        quoted_speech_exactly_detected=[dict(text=q,exactly_detected=norm(q) in actual if actual is not None else None) for q in quotes],
        S03_child_inner_voice_exactly_detected=norm('他一定在想怎么打我') in actual if sid=='S03' and actual is not None else None,
        scope='CPU samples and CPU ASR only; unrecognized speech is not proof of omission; root visual/listening review required. No OCR, VL, GPU or media dispatch.',production_approved=False)
    manifest=folder/'OBJECTIVE_QA.json';write(manifest,output)
    # Recheck all authoritative inputs before returning a bindable ready receipt.
    validate_segment(run,sid,delivery,source,project)
    return dict(status='cpu_qa_complete',segment=sid,prompt_id=pid,video_sha256=video['sha256'],manifest=dict(path=str(manifest),sha256=sha(manifest)),contact=output['contact'],production_approved=False)


def qa_final(run,video,expected_sha256,*,project=PROJECT):
    run=minute_root(run,project);video=bound(run,video)
    if sha(video)!=expected_sha256:raise ValueError('assembled video hash changed')
    data=probe(video);v=next(s for s in data['streams'] if s['codec_type']=='video');a=next(s for s in data['streams'] if s['codec_type']=='audio')
    target=Fraction(1448,24);audio_samples=Fraction(a['duration_ts'])*Fraction(a['time_base'])*int(a['sample_rate'])
    if ((v['width'],v['height'],int(v['nb_frames']),int(v['nb_read_frames']),v['r_frame_rate'],v['avg_frame_rate'])!=(736,1312,1448,1448,'24/1','24/1')
        or Fraction(v['start_time'])!=0 or Fraction(a['start_time'])!=0 or Fraction(v['duration_ts'])*Fraction(v['time_base'])!=target
        or int(a['sample_rate'])!=48000 or int(a['channels'])!=2 or audio_samples!=2896000
        or abs(Fraction(data['format']['duration'])-target)>Fraction(1,1000)):raise ValueError('assembled frame/sample/origin clock mismatch')
    folder=run/'qc';folder.mkdir(parents=True,exist_ok=True)
    out=dict(schema=VERSION,route='formal reference delivery minute, not prior raw or probe',file=dict(path=str(video),sha256=expected_sha256),native_frames=1448,decoded_frames=1448,width=736,height=1312,fps=24,
        seconds=float(target),video_start=0,audio_start=0,audio_rate=48000,stream_audio_samples=int(audio_samples),target_clock_matches=True,production_approved=False)
    path=folder/'FINAL_OBJECTIVE_QA.json';write(path,out)
    return dict(status='final_cpu_qa_complete',manifest=dict(path=str(path),sha256=sha(path)),clock=out,production_approved=False)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['segment','final']);parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--segment',choices=IDS);parser.add_argument('--delivery-run',type=Path);parser.add_argument('--source-prompt',type=Path);parser.add_argument('--asr',action='store_true')
    parser.add_argument('--video',type=Path);parser.add_argument('--expected-sha256');parser.add_argument('--project-root',type=Path,default=PROJECT)
    args=parser.parse_args(argv)
    if args.action=='segment':
        if not args.segment or not args.delivery_run:parser.error('segment and delivery-run required')
        result=qa_segment(args.run,args.segment,args.delivery_run,source_prompt=args.source_prompt,asr=args.asr,project=args.project_root)
    else:
        if not args.video or not args.expected_sha256:parser.error('video and expected-sha256 required')
        result=qa_final(args.run,args.video,args.expected_sha256,project=args.project_root)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps(dict(status='cpu_qa_failed',type=type(error).__name__,message=str(error),no_media_retry=True),ensure_ascii=False));raise SystemExit(2)
