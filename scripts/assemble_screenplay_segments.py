"""Assemble current-series reviewed originals without submitting any media job."""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory import video_campaign as c
from src.content_factory.script_video_review import REVIEW_CHECKS,build_review_packet
from scripts.run_screenplay_trial import verify_inputs
from scripts.run_script_video import probe


def approved_inputs(campaign_path, visual_preview=False):
    data=c.read(campaign_path); rows=[]; story_sha=None
    for shot in data['shots']:
        candidates=[a for a in data['attempts'] if a.get('series_id')==data['current_series_id'] and a['shot']==shot]
        if not candidates or (not c.attempt_allows_continuation(data,candidates[-1]) if visual_preview else candidates[-1]['status']!='passed'):
            raise ValueError('Every current-series segment must finish actual review: '+shot)
        a=candidates[-1]; folder=Path(a['run_dir']).resolve();r=c.read(folder/(shot+'.json'));m=c.read(folder/'production.json')
        plan=c.read(folder/'trial_plan.json')
        if m.get('trial_schema') in {'reviewed_cohort_segment/v1','reviewed_director_segment/v1','reviewed_reference_director_segment/v1'}:
            if m['trial_schema']=='reviewed_cohort_segment/v1':
                from scripts.run_cohort_video import verify_bundle,execution_prompt
            else:
                from scripts.run_director_video import verify_bundle,execution_prompt
            if c.file_sha(Path(m['bundle'])/'bundle.json')!=m['bundle_sha256']:
                raise ValueError('Reviewed bundle changed')
            bundle,script=verify_bundle(m['bundle'])
            expected_plan={'shot_id':shot,'previous_run':rows[-1]['run_dir'] if rows else None,
                           'bindings':{'story':bundle['script']}}
            expected_shot=next(s for s in script['shots'] if s['shot_id']==shot)
            prompt=execution_prompt(m,expected_shot)
            if (plan!=expected_plan or script!=c.read(folder/'locked_script.json')
                    or c.file_sha(folder/'locked_script.json')!=m['script_sha256']
                    or r['script_sha256']!=m['script_sha256']
                    or (folder/(shot+'.prompt.txt')).read_text(encoding='utf8')!=prompt
                    or c.file_sha(folder/(shot+'.prompt.txt'))!=r['prompt_sha256']
                    or c.file_sha(folder/'request.preview.json')!=m['request_sha256']
                    or r['request']!=c.read(folder/'request.preview.json')):
                raise ValueError('Reviewed source, plan or submitted prompt changed')
        else:
            if c.file_sha(folder/'trial_plan.json')!=m['trial_plan_sha256']:
                raise ValueError('Segment plan changed')
            verify_inputs(plan)
        if story_sha is None:story_sha=r['script_sha256']
        if (r['status']!='downloaded' or r['script_sha256']!=story_sha
                or c.file_sha(r['local_video'])!=r['video_sha256']
                or c.file_sha(r['last_frame'])!=r['last_frame_sha256']
                or c.file_sha(a['review_path'])!=a['review_sha256']):
            raise ValueError('Approved segment bytes changed')
        review=c.read(a['review_path'])
        if ((not c.review_allows_continuation(data,data['current_series_id'],review) if visual_preview else review['decision']!='passed') or review['source_sha256']!=r['video_sha256']
                or review['script_sha256']!=story_sha or set(review['checks'])!=set(REVIEW_CHECKS)
                or (not visual_preview and any(value is not True for value in review['checks'].values()))):
            raise ValueError('Incomplete actual media review')
        if rows and (Path(plan['previous_run']).resolve()!=Path(rows[-1]['run_dir'])
                or r['first_frame_sha256']!=rows[-1]['last_frame_sha256']):
            raise ValueError('Assembly does not follow the approved original-tail chain')
        rows.append({'shot':shot,'run_dir':str(folder),'video':r['local_video'],'video_sha256':r['video_sha256'],
                     'review_path':a['review_path'],'review_sha256':a['review_sha256'],
                     'last_frame_sha256':r['last_frame_sha256'],'source_script_sha256':story_sha})
    return data,rows


def assemble(campaign_path,output_dir,captioned=False,visual_preview=False):
    campaign_path=Path(campaign_path).resolve();output_dir=Path(output_dir).resolve()
    if not output_dir.is_relative_to(ROOT/'data/video_generation') or output_dir.exists():
        raise ValueError('Use a new local video output folder')
    data,rows=approved_inputs(campaign_path,visual_preview=visual_preview)
    if captioned:
        from scripts.render_clean_script_captions import audio_hash,frame_times
        for row in rows:
            report_path=Path(row['run_dir'])/(row['shot']+'.clean_captions.json')
            report=c.read(report_path);source=Path(row['video']);asset=Path(report['video']).resolve()
            if (report['status']!='candidate_pending_review' or report['source_sha256']!=row['video_sha256']
                    or not asset.is_relative_to(Path(row['run_dir'])) or c.file_sha(asset)!=report['video_sha256']
                    or audio_hash(asset)!=audio_hash(source) or frame_times(asset)!=frame_times(source)):
                raise ValueError('Caption candidate changed the approved source or its timing')
            row.update(original_video=row['video'],original_video_sha256=row['video_sha256'],
                       video=str(asset),video_sha256=report['video_sha256'],
                       caption_report=str(report_path),caption_report_sha256=c.file_sha(report_path))
    output_dir.mkdir(parents=True);out=output_dir/('complete_captioned.mp4' if captioned else 'complete_original_audio.mp4')
    args=['ffmpeg','-hide_banner','-loglevel','verbose','-n'];filters=[];inputs='';frame_count=0
    for i,row in enumerate(rows):
        media=probe(Path(row['video']));v=next(x for x in media['streams'] if x['codec_type']=='video')
        frame_count+=int(v['nb_frames'])
        args+=['-i',row['video']]
        filters += [f'[{i}:v]setpts=PTS-STARTPTS,setsar=1[v{i}]',f'[{i}:a]asetpts=PTS-STARTPTS,aresample=48000[a{i}]']
        inputs+=f'[v{i}][a{i}]'
    filters += [inputs+f'concat=n={len(rows)}:v=1:a=1[v][a]']
    args+=['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-fps_mode','vfr',
           '-c:v','libx264','-crf','18','-preset','fast','-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)]
    report={'schema':'reviewed_screenplay_assembly/v1','started_at_bjt':c.beijing_now(),'status':'assembling',
            'campaign_path':str(campaign_path),'campaign_sha256':c.file_sha(campaign_path),
            'series_id':data['current_series_id'],'inputs':rows,'media_review':'pending',
            'audio_note':'Original generated dialogue; no external track, no speed change, no cuts or freeze filler. AAC re-encoded for concatenation.',
            'video_generation_calls':0,'captioned_candidate':captioned,
            'review_scope':'visual_preview_audio_pending' if visual_preview else 'full_segment_reviews',
            'audio_review':'pending_user_review' if visual_preview else 'segment_reviews_only'}
    c.write(output_dir/'assembly.json',report)
    result=subprocess.run(args,capture_output=True,check=True)
    log=result.stderr.decode('utf8',errors='replace');(output_dir/'ffmpeg.log').write_text(log,encoding='utf8')
    ends=[int(t)/1000000 for t in re.findall(r'Segment finished at pts=(\d+)',log)]
    media=probe(out);v=next(x for x in media['streams'] if x['codec_type']=='video')
    if len(ends)!=len(rows) or int(v['nb_frames'])!=frame_count:
        raise ValueError('Inspect concat timing/frame-count before review')
    cuts=[{'time':ends[i],'from_shot':rows[i]['shot'],'to_shot':rows[i+1]['shot']} for i in range(len(rows)-1)]
    packet=build_review_packet(output_dir,out,c.file_sha(out),rows[0]['source_script_sha256'],cuts)
    report.update(status='candidate_pending_review',finished_at_bjt=c.beijing_now(),video=str(out),
                  video_sha256=c.file_sha(out),duration_seconds=float(media['format']['duration']),
                  frames_preserved=frame_count,cuts=cuts,review_packet=str(packet))
    c.write(output_dir/'assembly.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--captions',action='store_true')
    p.add_argument('--visual-preview',action='store_true',help='Explicitly authorized visual assembly; audio remains pending')
    a=p.parse_args();r=assemble(a.campaign,a.output_dir,a.captions,a.visual_preview);print(r['video'])
