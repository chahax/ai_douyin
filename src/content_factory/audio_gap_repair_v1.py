"""CPU envelope repair of user-confirmed ASR gaps; never shorten the video.

No inference or transcription is performed. Recognition windows are evidence,
not a guarantee of listening quality. Claims with no completed receipt are never
automatically executed again. Completed reentry checks files/proofs only.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from . import h3_audio_conformance_v1 as conformance
from .visual_image_jobs_v3 import run_lock

PROJECT=Path(__file__).resolve().parents[2]
VERSION='audio_gap_repair/v1'


def require(ok,reason):
    if not ok:raise ValueError(reason)


def path(value):
    p=Path(value)
    require(p.is_absolute() and '://' not in str(value),'absolute_project_path_required')
    p=p.resolve();require(p.is_relative_to(PROJECT),'path_outside_project');return p


def bind(value):
    p=path(value)
    with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(path=str(p),sha256=digest)


def checked(value):
    require(isinstance(value,dict) and set(value)=={'path','sha256'},'exact_binding_required')
    p=path(value['path']);require(bind(p)==value,'bound_file_changed');return p


def read(value):return json.loads(path(value).read_text(encoding='utf-8-sig'))
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def freeze(value,data):
    p=path(value);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():require(read(p)==data,'frozen_evidence_changed')
    else:
        with p.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    return bind(p)


def _details(spec_binding):
    spec=read(checked(spec_binding))
    require(spec.get('schema')=='audio_gap_repair_spec/v1','supported_gap_spec_required')
    media=spec['media'];checked(media)
    case=read(checked(spec['conformance_case']));report=read(checked(spec['conformance_report']))
    reevaluated=conformance.evaluate_bound(spec['conformance_case'])
    require(report==reevaluated and report.get('input_valid') is True,'valid_recomputed_existing_conformance_required')
    require(report['native_id']==case['native_id']==spec['native_id'] and report['segment_id']==case['segment_id']==spec['segment_id']
            and report['media']==case['media']==media,'conformance_native_media_subject_mismatch')
    coverage=report['expected_coverage'];summary=report['coverage_summary']
    require(coverage and summary['expected_quotes']==summary['fully_recognized_quotes']==len(coverage)
            and all(q['recognized_match'] is True and q['match_kind'] in ('normalized_exact','limited_de_di_homophone')
                    and type(q['actual_start_ms']) is int and type(q['actual_end_ms']) is int
                    and 0<=q['actual_start_ms']<q['actual_end_ms'] for q in coverage),
            'all_full_actual_quote_matches_required')
    issue=read(checked(spec['user_issue']))
    require(issue.get('schema')==conformance.USER_ISSUE_SCHEMA and issue.get('confirmed') is True
            and issue.get('confirmed_by')=='user' and issue.get('native_id')==spec['native_id']
            and issue.get('media')==media and bool(issue.get('description')),'same_media_explicit_user_confirmation_required')
    windows=issue.get('intervals_ms',[])
    require(windows and all(isinstance(w,list) and len(w)==2 and all(type(x) is int for x in w)
            and 0<=w[0]<w[1] for w in windows),'user_confirmed_time_intervals_required')
    pad,fade,protect=(spec[k] for k in ('padding_ms','fade_ms','quote_protection_ms'))
    require(all(type(v) is int for v in (pad,fade,protect)) and 0<=fade<=40 and fade<=pad<=80 and protect>=80,
            'bounded_padding_fade_and_at_least_80ms_quote_protection_required')
    clock=spec['frame_clock'];target=spec['audio_target']
    require(set(clock)=={'frames','fps'} and all(type(v) is int and v>0 for v in clock.values())
            and target==dict(rate=48000,channels=2) and all(type(v) is int for v in target.values()),'explicit_frame_and_48k_stereo_clock_required')
    seconds=Fraction(clock['frames'],clock['fps']);samples=seconds*target['rate']
    require(samples.denominator==1 and seconds<=600,'integral_bounded_effective_audio_samples_required')
    protected=[[max(0,q['actual_start_ms']-protect),q['actual_end_ms']+protect] for q in coverage]
    indices=spec['selected_unmapped_indices']
    require(isinstance(indices,list) and indices and all(type(i) is int for i in indices)
            and len(set(indices))==len(indices),'explicit_unmapped_gap_selection_required')
    patches=[]
    for i in indices:
        require(0<=i<len(report['unmapped_recognized_spans']),'unmapped_gap_index_invalid')
        gap=report['unmapped_recognized_spans'][i];start,end=gap['start_ms'],gap['end_ms']
        require(type(start) is int and type(end) is int and 0<=start<end
                and any(a<=start<end<=b for a,b in windows),'actual_unmapped_gap_must_be_inside_user_confirmed_interval')
        outer=[start-pad,end+pad]
        require(0<=outer[0]<outer[1]<=seconds*1000 and all(outer[1]<=a or outer[0]>=b for a,b in protected),
                'patch_overlaps_actual_matched_quote_protection_or_media_end')
        patches.append(dict(unmapped_index=i,core_ms=[start,end],patch_ms=outer,fade_ms=fade))
    patches.sort(key=lambda x:x['patch_ms'][0])
    require(all(a['patch_ms'][1]<=b['patch_ms'][0] for a,b in zip(patches,patches[1:])),'overlapping_patch_envelopes_refused')
    return dict(spec=spec_binding,native_id=spec['native_id'],segment_id=spec['segment_id'],media=media,
        conformance_case=spec['conformance_case'],conformance_report=spec['conformance_report'],user_issue=spec['user_issue'],
        frame_clock=clock,audio_target=target,effective_samples=int(samples),protected_actual_quotes_ms=protected,
        patches=patches,matching_windows_are_ASR_evidence_not_acoustic_guarantees=True)


def prepare(run,spec_binding):
    run=path(run);run.mkdir(parents=True,exist_ok=True)
    with run_lock(run,'AUDIO_GAP_REPAIR.lock'):
        details=_details(spec_binding)
        require(not path(details['media']['path']).is_relative_to(run),'original_media_must_stay_outside_new_repair_run')
        plan=dict(schema=VERSION,details=details,code=bind(__file__),conformance_code=bind(conformance.__file__),
            video_streamcopy_required=True,video_duration_or_frame_cut_allowed=False,new_ASR_calls=0,new_model_calls=0)
        return dict(status='prepared',plan=freeze(run/'PLAN.json',plan),patches=details['patches'])


def _load(run):
    run=path(run);plan=read(run/'PLAN.json')
    require(plan.get('schema')==VERSION and plan.get('code')==bind(__file__)
            and plan.get('conformance_code')==bind(conformance.__file__),'frozen_repair_code_changed')
    require(plan['details']==_details(plan['details']['spec']),'repair_plan_input_or_actual_windows_changed')
    return run,plan


def _command(run,label,args):
    result=subprocess.run(args,capture_output=True,timeout=600)
    proof=dict(command=args,returncode=result.returncode,stderr=result.stderr.decode('utf-8',errors='replace'),
               stdout_sha256=hashlib.sha256(result.stdout).hexdigest())
    freeze(run/'processes'/(label+'.json'),proof)
    require(result.returncode==0,'CPU_command_failed:'+label)
    return result.stdout


def _probe(run,label,media):
    return json.loads(_command(run,label,['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media)]))


def _frame_rows(text):
    tb=None;rows=[]
    for line in text.splitlines():
        if line.startswith('#tb 0:'):tb=Fraction(line.split(':',1)[1].strip())
        elif line and not line.startswith('#'):
            r=[v.strip() for v in line.split(',')];require(len(r)==6 and tb is not None,'decoded_framehash_parse_failed')
            rows.append(dict(pts=str(int(r[2])*tb),duration=str(int(r[3])*tb),hash=r[5]))
    require(rows,'decoded_framehash_empty');return rows


def _frames(run,label,media):
    data=_command(run,label,['ffmpeg','-nostdin','-v','error','-i',str(media),'-map','0:v:0','-an','-fps_mode','passthrough','-f','framemd5','-'])
    target=run/(label+'.txt');target.write_bytes(data)
    return _frame_rows(data.decode()),bind(target)


def _normalize(decoded,probe,d):
    stream=next(s for s in probe['streams'] if s['codec_type']=='audio')
    require(abs(float(stream.get('start_time','0')))<=1/48000,'nonzero_audio_start_requires_separate_repair')
    require(len(decoded)%4==0,'incomplete_stereo_PCM_samples')
    total=d['effective_samples'];count=len(decoded)//4
    effective=Fraction(int(stream['duration_ts']))*Fraction(stream['time_base'])*48000
    require(effective.denominator==1 and 0<effective<=total and count>=int(effective)
            and count-int(effective)<=4096 and total-int(effective)<=48000/d['frame_clock']['fps'],
            'only_container_codec_tail_and_small_tail_padding_may_be_normalized')
    raw=np.frombuffer(decoded,dtype='<i2').reshape(-1,2)
    output=np.zeros((total,2),dtype='<i2');output[:int(effective)]=raw[:int(effective)]
    return output,dict(decoded_samples=count,container_effective_samples=int(effective),
        removed_codec_tail_samples=count-int(effective),tail_pad_samples=total-int(effective),meaningful_content_trimmed=False)


def _edit(pcm,d):
    out=pcm.copy();mask=np.zeros(len(pcm),dtype=bool);rate=d['audio_target']['rate']
    for p in d['patches']:
        start,end=[ms*rate//1000 for ms in p['patch_ms']];n=p['fade_ms']*rate//1000
        gains=np.zeros(end-start,dtype=np.float64)
        if n:gains[:n]=np.linspace(1,0,n,endpoint=False);gains[-n:]=np.linspace(0,1,n,endpoint=False)
        out[start:end]=np.rint(pcm[start:end].astype(np.float64)*gains[:,None]).astype('<i2');mask[start:end]=True
        a,b=[ms*rate//1000 for ms in p['core_ms']]
        require(np.all(out[a:b]==0),'fullmute_core_not_covered_by_zero_gain')
    require(np.array_equal(out[~mask],pcm[~mask]),'PCM_outside_patch_changed')
    return out,mask


def _level(pcm):
    v=pcm.astype(np.float64)
    return dict(peak=int(np.max(np.abs(v))) if v.size else 0,RMS=float(np.sqrt(np.mean(v*v))) if v.size else 0)


def _audio_metrics(before,patched,after,d):
    expected,mask=_edit(before,d);require(np.array_equal(expected,patched),'edited_PCM_not_exact_planned_envelope')
    # AAC uses overlapping coding windows. Report strict outside metrics too,
    # but test fidelity on a separately named 120ms codec-guarded outside area.
    stable=~mask.copy()
    for p in d['patches']:
        a,b=p['patch_ms'];stable[max(0,(a-120)*48):min(len(stable),(b+120)*48)]=False
    def compare(which):
        x=patched[which].astype(float).reshape(-1);y=after[which].astype(float).reshape(-1)
        require(len(x)>0,'nonempty_AAC_outside_region_required')
        error=float(np.sqrt(np.mean((x-y)**2)));signal=float(np.sqrt(np.mean(x*x)))
        xc=x-x.mean();yc=y-y.mean();den=float(np.linalg.norm(xc)*np.linalg.norm(yc))
        corr=float(np.dot(xc,yc)/den) if den>0 else None
        return dict(samples=int(which.sum()),correlation=corr,RMSE=error,signal_RMS=signal,
                    normalized_RMSE=error/max(signal,1.0))
    strict,guarded=compare(~mask),compare(stable)
    passed=(guarded['signal_RMS']<=1 and guarded['RMSE']<=8) or (
        guarded['correlation'] is not None and guarded['correlation']>=.98 and guarded['normalized_RMSE']<=.15)
    cores=[]
    for p in d['patches']:
        a,b=[ms*48 for ms in p['core_ms']]
        cores.append(dict(core_ms=p['core_ms'],original=_level(before[a:b]),edited=_level(patched[a:b]),final_AAC_decoded=_level(after[a:b])))
    require(passed,'final_AAC_outside_correlation_failed')
    require(all(c['edited']['peak']==0 and c['final_AAC_decoded']['RMS']<=30 for c in cores),'final_AAC_core_not_sufficiently_suppressed')
    return dict(edited_PCM_outside_patch_exact=True,final_AAC_PCM_byte_identical_claim=False,
        final_AAC_strict_outside=strict,final_AAC_outside_codec_guard_120ms=guarded,
        final_AAC_outside_correlation_passed=True,core_levels=cores,hearing_quality_or_speaker_identity_verified=False)


def _cached(run,plan):
    result=read(run/'RESULT.json');require(result.get('schema')==VERSION and result['plan']==bind(run/'PLAN.json'),'cached_result_plan_changed')
    require(result['artifacts']==_artifacts(run),'cached_module_owned_artifact_set_changed')
    for item in result['artifacts']:checked(item)
    proof=read(checked(result['proof']))
    require(proof['input']==plan['details']['media'] and proof['output']==result['file'],'cached_proof_subject_changed')
    before=np.fromfile(checked(proof['normalized_input_PCM']),dtype='<i2').reshape(-1,2)
    patched=np.fromfile(checked(proof['edited_PCM']),dtype='<i2').reshape(-1,2)
    after=np.fromfile(checked(proof['final_decoded_PCM']),dtype='<i2').reshape(-1,2)
    require(_audio_metrics(before,patched,after,plan['details'])==proof['audio_QA'],'cached_audio_proof_changed')
    source=_frame_rows(checked(proof['source_framehash']).read_text())
    final=_frame_rows(checked(proof['output_framehash']).read_text())
    require(source==final and len(source)==plan['details']['frame_clock']['frames'],'cached_video_frame_or_PTS_proof_changed')
    return dict(status='verified_CPU_audio_repair',file=result['file'],receipt=bind(run/'RESULT.json'),proof=result['proof'],
                no_subprocess_on_reentry=True,content_quality_passed=False,human_listening_performed=False)


def _artifacts(run):
    """Only immutable files owned by this module; Root checkpoints stay separate."""
    names=['PLAN.json','EXECUTE_CLAIM.json','AUDIO_GAP_REPAIRED.mp4','PROOF.json',
           'RAW_DECODED_PCM.s16le','NORMALIZED_INPUT_PCM.s16le','EDITED_PCM.s16le',
           'FINAL_AAC_DECODED_PCM.s16le','SOURCE_FRAMEHASH.txt','OUTPUT_FRAMEHASH.txt']
    process_names=['input_probe','SOURCE_FRAMEHASH','decode_input','remux_streamcopy','output_probe','OUTPUT_FRAMEHASH','decode_output']
    return [bind(run/name) for name in names]+[bind(run/'processes'/(name+'.json')) for name in process_names]


def execute(run):
    run=path(run)
    with run_lock(run,'AUDIO_GAP_REPAIR.lock'):
        run,plan=_load(run);d=plan['details']
        if (run/'RESULT.json').exists():return _cached(run,plan)
        claim=run/'EXECUTE_CLAIM.json'
        if claim.exists():return dict(status='outcome_unknown',claim=bind(claim),automatic_retry=False)
        freeze(claim,dict(plan=bind(run/'PLAN.json'),at_epoch=time.time(),CPU_only=True,ASR_calls=0,model_calls=0))
        try:
            media=checked(d['media']);probe=_probe(run,'input_probe',media)
            video=next(s for s in probe['streams'] if s['codec_type']=='video')
            require(sum(s['codec_type']=='video' for s in probe['streams'])==sum(s['codec_type']=='audio' for s in probe['streams'])==1,
                    'one_video_and_one_audio_stream_required')
            tb=Fraction(video['time_base']);require(tb.numerator==1,'supported_video_track_timebase_required')
            source_frames,source_hash=_frames(run,'SOURCE_FRAMEHASH',media)
            require(len(source_frames)==d['frame_clock']['frames'] and all(Fraction(r['pts'])==Fraction(i,d['frame_clock']['fps'])
                    for i,r in enumerate(source_frames)),'actual_video_frame_count_and_PTS_mismatch')
            raw=_command(run,'decode_input',['ffmpeg','-nostdin','-v','error','-i',str(media),'-map','0:a:0','-ar','48000','-ac','2','-f','s16le','-acodec','pcm_s16le','-'])
            (run/'RAW_DECODED_PCM.s16le').write_bytes(raw);before,norm=_normalize(raw,probe,d)
            require(max(b for a,b in d['protected_actual_quotes_ms'])*48<=norm['container_effective_samples'],
                    'protected_quote_margin_outside_actual_effective_audio')
            edited,_=_edit(before,d)
            before.tofile(run/'NORMALIZED_INPUT_PCM.s16le');edited.tofile(run/'EDITED_PCM.s16le')
            output=run/'AUDIO_GAP_REPAIRED.mp4';require(not output.exists(),'unreceipted_output_preserved')
            _command(run,'remux_streamcopy',['ffmpeg','-nostdin','-v','error','-i',str(media),'-f','s16le','-ar','48000','-ac','2',
                '-i',str(run/'EDITED_PCM.s16le'),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
                '-ar','48000','-ac','2','-video_track_timescale',str(tb.denominator),'-map_metadata','0','-movflags','+faststart',str(output)])
            out_probe=_probe(run,'output_probe',output);out_video=next(s for s in out_probe['streams'] if s['codec_type']=='video')
            require(all(out_video[k]==video[k] for k in ('width','height','codec_name')),'copied_video_geometry_or_codec_changed')
            out_frames,out_hash=_frames(run,'OUTPUT_FRAMEHASH',output)
            require(out_frames==source_frames,'video_decoded_framehash_or_PTS_changed')
            decoded=_command(run,'decode_output',['ffmpeg','-nostdin','-v','error','-i',str(output),'-map','0:a:0','-ar','48000','-ac','2','-f','s16le','-acodec','pcm_s16le','-'])
            after,out_norm=_normalize(decoded,out_probe,d);after.tofile(run/'FINAL_AAC_DECODED_PCM.s16le')
            metrics=_audio_metrics(before,edited,after,d);checked(d['media'])
            proof=freeze(run/'PROOF.json',dict(schema='audio_gap_repair_proof/v1',input=d['media'],output=bind(output),
                normalized_input_PCM=bind(run/'NORMALIZED_INPUT_PCM.s16le'),edited_PCM=bind(run/'EDITED_PCM.s16le'),
                final_decoded_PCM=bind(run/'FINAL_AAC_DECODED_PCM.s16le'),source_framehash=source_hash,output_framehash=out_hash,
                input_probe=probe,output_probe=out_probe,input_normalization=norm,output_normalization=out_norm,
                audio_QA=metrics,video_frames_PTS_and_decoded_hashes_unchanged=True,video_streamcopy=True,
                duration_or_story_cut_performed=False,model_calls=0,ASR_calls=0,HTTP_calls=0))
            artifacts=_artifacts(run)
            freeze(run/'RESULT.json',dict(schema=VERSION,status='repaired_pending_listening',plan=bind(run/'PLAN.json'),
                file=bind(output),proof=proof,artifacts=artifacts,overall_video_accepted=False,ASR_calls=0,model_calls=0))
            return _cached(run,plan)
        except Exception as error:
            freeze(run/'ERROR.json',dict(type=type(error).__name__,message=str(error),automatic_retry=False))
            raise


def qa(run):
    run=path(run)
    with run_lock(run,'AUDIO_GAP_REPAIR.lock'):
        run,plan=_load(run)
        require((run/'RESULT.json').exists(),'known_completed_repair_required_for_QA')
        return _cached(run,plan)
