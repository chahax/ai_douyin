"""Four source-driven opening segments; reuse the user's accepted native S02.

Prepare and known-collect never submit. Root observations and bound launch
approvals remain separate from this thin adapter and the frozen producers.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_h3_handoff_v3 as native
from src.content_factory import visual_spatial_stills_v24 as stills
from src.content_factory import visual_opening_frame as opening
from src.content_factory import visual_h3_prompt_parity_v19 as clock
from src.content_factory.visual_spatial_clock_v30 import clock_input

PROJECT=Path(__file__).resolve().parents[1]
RUN=PROJECT/'data/video_generation/h3_story_opening_minute_20261111_v1'
SOURCE=PROJECT/'data/qa/h3_opening_frame_20261110_v1/actual_source_preparation_cpu_complete'
BASE=PROJECT/'data/video_generation/h3_continuity_full_minute_20261109_v1/MINUTE_SPEC.json'
ACCEPTED=PROJECT/'data/video_generation/h3_story_opening_s02_20261110_v1'
ACCEPTED_ID='ad632988-544f-4074-91c5-76ccfff0f88e'
ACCEPTED_SHA='333c204265493be12503173e836094b6bfb06b85a316a32ac242b0d2ecdb12a5'
IDS=('S01','S02','S03','S04')
NEW_IDS=('S01','S03','S04')
SCHEMA='h3_story_opening_minute/v1'
read=native.read
bind=core.binding


def freeze(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    native.freeze(path,value)


def scope(run):
    run=Path(run).resolve()
    if run!=Path(RUN).resolve():raise ValueError('explicit_new_minute_run_required')
    return run


def segment(run,sid):
    if sid not in IDS:raise ValueError('explicit_minute_shot_required')
    return Path(run)/'segments'/sid


def folders(run,sid):
    segment(run,sid)
    name=Path(run).name+'_'+sid
    return Path(run)/'stills'/name,Path(run)/'visual_h3_v3'/name


def import_s02(run):
    result_path=ACCEPTED/'visual_h3_v3/opening_S02/shots/S02/RESULT.json'
    result=read(result_path)
    if result['prompt_id']!=ACCEPTED_ID or result['files']['video']['sha256']!=ACCEPTED_SHA:
        raise ValueError('exact_user_accepted_native_s02_required')
    for value in result['files'].values():core.check({k:value[k] for k in ('path','sha256')})
    old_review=bind(ACCEPTED/'ROOT_RESULT_REVIEW.json')
    accepted=dict(schema='user_accepted_native_baseline/v1',
        user_statement='这个可以了，这个是流程输出那来个1分钟版',
        native_result=bind(result_path),file={k:result['files']['video'][k] for k in ('path','sha256')},
        prompt_id=ACCEPTED_ID,prior_root_review=old_review,
        prior_review_unchanged=True,new_acceptance_does_not_rewrite_prior_quality_record=True)
    freeze(run/'USER_ACCEPTED_BASELINE.json',accepted)
    value=dict(schema=SCHEMA,shot_id='S02',kind='imported_user_accepted_native',
        native_run=str(result_path.parents[2]),native_result=bind(result_path),
        native_records=dict(PLAN=bind(result_path.parents[2]/'PLAN.json'),
            **{name:bind(result_path.parent/(name+'.json')) for name in ('REQUEST','HISTORY','RESULT')}),
        native_files=result['files'],file=accepted['file'],prompt_id=ACCEPTED_ID,
        acceptance=bind(run/'USER_ACCEPTED_BASELINE.json'),new_model_posts=0,
        temporal_trim=False,source_media_unchanged=True,production_approved=False)
    freeze(run/'imported/S02/IMPORT.json',value)
    return value


def prepare(run=RUN):
    run=scope(run);run.mkdir(parents=True,exist_ok=True)
    user=dict(user_statement='这个可以了，这个是流程输出那来个1分钟版',
        engineering_scope_not_user_quoted_numeric_limit=True,
        engineering_limits=dict(image_submissions=3,video_submissions=3,cloud_media=0),
        publication=False,unknown_replay=False,first_frame_policy=opening.POLICY,
        source_case=bind(SOURCE/'SOURCE_CASE.json'),baseline_spec=bind(BASE))
    freeze(run/'ROOT_USER_SCOPE.json',user)
    freeze(run/'USER_AUTHORIZATION.json',dict(user,max_image_submissions=3,new_cloud_media_calls=0))
    accepted=import_s02(run)
    entries=core._entries(user['source_case'])
    if [x['shot_id'] for x in entries]!=list(IDS):raise ValueError('ordered_four_original_segments_required')
    spec=read(BASE);cfg=deepcopy(spec['h3_config']);cfg['runs_root']=str(run/'visual_h3_v3')
    freeze(run/'H3_CONFIG.json',cfg)
    rows=[]
    for entry in entries:
        sid=entry['shot_id'];part=segment(run,sid);core.validate_entry(entry)
        if entry.get('first_frame_policy')!=opening.POLICY:raise ValueError('new_source_first_frame_policy_required')
        freeze(part/'SOURCE_CASE.json',dict(schema=core.SCHEMA,shots=[entry]))
        if sid=='S02':
            rows.append(dict(shot_id=sid,kind='imported_user_accepted_native',
                source_case=bind(part/'SOURCE_CASE.json'),imported=bind(run/'imported/S02/IMPORT.json'),
                native_run=accepted['native_run'],native_result=accepted['native_result']))
            continue
        report=core.evaluate(entry)
        if report['status']!='reanchor_required':raise ValueError('real_new_opening_image_required')
        freeze(part/'REANCHOR_WORK_ORDER.json',report['work_order'])
        image_run,_=folders(run,sid)
        stills.prepare(image_run,handoff=SOURCE/'spatial/HANDOFF.json',
            render_result=SOURCE/'spatial/blender_canonical_v34/RESULT.json',
            inputs=core.check(spec['spatial']['inputs']),authorization=run/'USER_AUTHORIZATION.json',
            config=core.check(spec['spatial']['config']),reference_packing=stills.SCREEN_PACKING)
        _,stills_plan=stills._load(image_run)
        item=next(x for x in stills_plan['items'] if x['id']==sid+'_start')
        request=dict(schema='h3_reanchor_source_state_review_request/v33',
            work_order_sha256=core.digest(report['work_order']),entry_base_sha256=core.digest(core._base(entry)),
            spatial_plan=stills_plan['spatial_plan'],item_id=item['id'],state_sha256=core.digest(item['state']),
            canonical_characters=entry['canonical_characters'],canonical_room=entry['canonical_room'],
            target_stage=item['stage'],opening_frame=opening.contract(entry),
            required_review_file=str(part/'SOURCE_STATE_REVIEW.json'),review_not_yet_observed=True)
        freeze(part/'SOURCE_STATE_REVIEW_REQUEST.json',request)
        freeze(part/'ACTUAL_PROMPT_DRAFT.json',core.compile_prompt(entry))
        rows.append(dict(shot_id=sid,kind='new_native',source_case=bind(part/'SOURCE_CASE.json'),
            native_run=str(folders(run,sid)[1]),
            native_result_path=str(folders(run,sid)[1]/'shots'/sid/'RESULT.json')))
    plan=dict(schema=SCHEMA,source_case=user['source_case'],authority=bind(run/'USER_AUTHORIZATION.json'),
        accepted_baseline=bind(run/'USER_ACCEPTED_BASELINE.json'),segments=rows,
        width=736,height=1312,frames_per_segment=362,fps=24,steps=12,
        expected_frames=1448,expected_audio_rate=48000,expected_audio_samples=2896000,
        temporal_leading_trim=False,publication=False,production_approved=False)
    freeze(run/'PLAN.json',plan)
    return dict(status='source_state_reviews_required',plan=bind(run/'PLAN.json'),new_shots=list(NEW_IDS),model_posts=0)


def prepare_images(run=RUN,sid=None):
    run=scope(run)
    if sid is None:return {s:prepare_images(run,s) for s in NEW_IDS}
    if sid not in NEW_IDS:raise ValueError('only_new_segments_can_generate')
    part=segment(run,sid);image_run,_=folders(run,sid);review=part/'SOURCE_STATE_REVIEW.json'
    if not review.exists():return dict(status='source_state_review_required',model_posts=0)
    base=read(BASE)
    result=core.prepare_reanchor(bind(part/'SOURCE_CASE.json'),sid,image_run,
        handoff=SOURCE/'spatial/HANDOFF.json',render_result=SOURCE/'spatial/blender_canonical_v34/RESULT.json',
        inputs=core.check(base['spatial']['inputs']),authorization=run/'USER_AUTHORIZATION.json',
        config=core.check(base['spatial']['config']),item_id=sid+'_start',source_binding_review=bind(review))
    freeze(part/'IMAGE_RECEIPT_TEMPLATE.json',result['receipt_template'])
    freeze(part/'LAUNCH_REQUEST_IMAGE.json',launch_request(run,'image',sid))
    return result


def prepare_video(run=RUN,sid=None):
    run=scope(run)
    if sid is None:return {s:prepare_video(run,s) for s in NEW_IDS}
    if sid not in NEW_IDS:raise ValueError('only_new_segments_can_generate')
    part=segment(run,sid);image_run,video_run=folders(run,sid)
    path=image_run/'batches'/('reanchor_'+sid)/'CANDIDATES.json'
    candidate=next(x for x in read(path)['items'] if x['id']==sid+'_start')
    review=part/'ANCHOR_REVIEW.json';entry=deepcopy(core._entries(bind(part/'SOURCE_CASE.json'))[0])
    receipt=read(part/'IMAGE_RECEIPT_TEMPLATE.json');receipt['candidates']=bind(path)
    selection=part/'DERIVED_OPENING_SELECTION.json'
    if selection.exists():
        selected=read(selection)
        if selected.get('parent_image')!=candidate['image'] or selected.get('parent_generation_receipt')!=receipt:
            raise ValueError('derived_selection_must_preserve_actual_native_parent')
        first=entry['camera_beats'][0]
        if first['framing']!='face_close' or len(first['actors'])!=1:
            raise ValueError('single_face_close_required_for_opening_crop')
        if any('hands' in actor['visible_parts'] for actor in first['actors'].values()):
            raise ValueError('hand_and_held_prop_opening_must_keep_raw_frame')
        receipt=dict(kind='derived_opening_crop/v1',parent_image=candidate['image'],
            parent_generation_receipt=receipt,crop_result=selected['crop_result'])
        candidate=dict(id=candidate['id'],image=selected['image'],derived_from=candidate['image'],native_output=False)
        review=part/'DERIVED_ANCHOR_REVIEW.json'
    if not review.exists():return dict(status='actual_anchor_review_required',candidate=candidate,required_review_file=str(review),model_posts=0)
    entry['reanchor']=dict(image=candidate['image'],coverage_review=bind(review),
        work_order_sha256=core.digest(read(part/'REANCHOR_WORK_ORDER.json')),generation_receipt=receipt)
    if core.evaluate(entry)['status']!='ready':raise ValueError('actual_source_bound_opening_not_ready')
    freeze(part/'VIDEO_SOURCE_CASE.json',dict(schema=core.SCHEMA,shots=[entry]))
    result=native.prepare_from_continuity(bind(part/'VIDEO_SOURCE_CASE.json'),video_run,read(run/'H3_CONFIG.json'))
    freeze(part/'LAUNCH_REQUEST_VIDEO.json',launch_request(run,'video',sid))
    return result


def launch_request(run,kind,sid):
    if kind not in ('image','video') or sid not in NEW_IDS:raise ValueError('explicit_new_image_or_video_stage_required')
    image_run,video_run=folders(run,sid);part=segment(run,sid)
    job=image_run/'batches'/('reanchor_'+sid) if kind=='image' else video_run
    return dict(schema=SCHEMA,kind=kind,shot_id=sid,
        authority=bind(run/'USER_AUTHORIZATION.json'),minute_plan=bind(run/'PLAN.json'),source=bind(part/'SOURCE_CASE.json'),
        plan=bind(job/'PLAN.json'),code=[bind(x) for x in (__file__,core.__file__,native.__file__,stills.__file__,opening.__file__)],
        graph=bind(job/'workflow_api.json' if kind=='image' else job/'shots'/sid/'workflow_api.json'),
        publication=False,unknown_replay=False)


def require_approval(run,kind,sid):
    expected=launch_request(run,kind,sid);approval=read(segment(run,sid)/('ROOT_LAUNCH_'+kind.upper()+'.json'))
    if (approval.get('request')!=expected or not isinstance(approval.get('approved_by'),str)
            or not approval['approved_by'].strip() or not isinstance(approval.get('evidence'),list)
            or not approval['evidence'] or any(not isinstance(e,str) or not e.strip() for e in approval['evidence'])):
        raise ValueError('actual_plan_and_code_bound_launch_approval_required')


def status(run=RUN):
    run=scope(run);rows=[]
    for sid in NEW_IDS:
        image_run,video_run=folders(run,sid)
        rows.append(dict(shot_id=sid,image=stills.status(image_run,'reanchor_'+sid)
            if (image_run/'batches'/('reanchor_'+sid)/'PLAN.json').exists() else None,
            video=native.status(video_run) if (video_run/'PLAN.json').exists() else None))
    return dict(run=str(run),segments=rows,imported_s02=bind(run/'imported/S02/IMPORT.json'),production_approved=False)


def collect_known(run,kind,sid):
    run=scope(run)
    if kind not in ('image','video') or sid not in NEW_IDS:raise ValueError('explicit_new_image_or_video_stage_required')
    image_run,video_run=folders(run,sid)
    if kind=='image':
        current=stills.status(image_run,'reanchor_'+sid)
        return current if current['status']=='prepared' else stills.tick(image_run,'reanchor_'+sid)
    current=native.poll_collect(video_run)
    if current['status']=='media_review_required':
        result=read(video_run/'shots'/sid/'RESULT.json')
        freeze(segment(run,sid)/'FINAL_RESULT.json',dict(native_result=bind(video_run/'shots'/sid/'RESULT.json'),
            file={k:result['files']['video'][k] for k in ('path','sha256')},prompt_id=result['prompt_id'],
            production_approved=False,postprocessing=[]))
    return current


def execute(run,kind,sid=None,poll_seconds=30,max_seconds=21600):
    run=scope(run)
    if sid is None:
        results={}
        for s in NEW_IDS:
            results[s]=execute(run,kind,s,poll_seconds,max_seconds)
            if results[s]['status'] not in ('saved','media_review_required'):break
        return results
    if kind not in ('image','video') or sid not in NEW_IDS:raise ValueError('explicit_new_image_or_video_stage_required')
    if not 1<=poll_seconds<=60 or not 1<=max_seconds<=21600:raise ValueError('bounded_wait_required')
    image_run,video_run=folders(run,sid)
    if kind=='image':
        current=stills.status(image_run,'reanchor_'+sid)
        if current['status']=='prepared':require_approval(run,kind,sid)
        return stills.execute(image_run,'reanchor_'+sid,poll_seconds,max_seconds)
    deadline=time.monotonic()+max_seconds
    with stills.jobs.run_lock(video_run,'MINUTE_WORKER.lock'):
        while True:
            current=collect_known(run,kind,sid)
            if current['status'] in ('media_review_required','outcome_unknown','blocked_native_failure','blocked_upstream_changed','paused'):
                return current
            if current['status']=='prepared':require_approval(run,kind,sid);native.submit_next(video_run)
            if time.monotonic()>=deadline:return dict(current,bounded_wait_original_id_preserved=True)
            time.sleep(poll_seconds)


def segment_results(run):
    plan=read(run/'PLAN.json')
    for value in (plan['source_case'],plan['authority'],plan['accepted_baseline']):core.check(value)
    for row in plan['segments']:
        core.check(row['source_case'])
        if row['shot_id']=='S02':core.check(row['imported'])
    rows=[]
    for sid in IDS:
        descriptor=read(run/'imported/S02/IMPORT.json') if sid=='S02' else read(segment(run,sid)/'FINAL_RESULT.json')
        if sid=='S02':
            for value in descriptor['native_records'].values():core.check(value)
            core.check(descriptor['acceptance'])
        result=read(core.check(descriptor['native_result']))
        for value in result['files'].values():core.check({k:value[k] for k in ('path','sha256')})
        rows.append(dict(shot_id=sid,native_result=descriptor['native_result'],prompt_id=result['prompt_id'],
            file={k:result['files']['video'][k] for k in ('path','sha256')},kind='imported' if sid=='S02' else 'new'))
    if len({r['prompt_id'] for r in rows})!=4 or len({r['file']['sha256'] for r in rows})!=4:
        raise ValueError('four_distinct_native_videos_required')
    if rows[1]['prompt_id']!=ACCEPTED_ID or rows[1]['file']['sha256']!=ACCEPTED_SHA:
        raise ValueError('exact_user_accepted_native_s02_required')
    return rows


def assemble(run=RUN):
    run=scope(run)
    with stills.jobs.run_lock(run,'ASSEMBLY.lock'):
        rows=segment_results(run);inputs=dict(plan=bind(run/'PLAN.json'),segments=rows);source=core.digest(inputs)
        final=run/'FINAL_RESULT.json';output=run/'H3_STORY_OPENING_MINUTE_736x1312.mp4'
        if final.exists():
            result=read(final);core.check(result['file'])
            if result['assembly_inputs_sha256']!=source:raise ValueError('frozen_assembly_sources_changed')
            return result
        if output.exists():raise ValueError('unreceipted_final_movie_preserved')
        adjustments=[clock_input(r['file']['path'],r['file']['sha256'],frames=362,width=736,height=1312) for r in rows]
        filters=run/'ASSEMBLY_FILTER.txt'
        command,text=clock.assembly_command([r['file']['path'] for r in rows],filters,output,frames=362)
        filters.write_text(text,encoding='utf-8')
        freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,adjustments=adjustments,command=command,
            source_media_unchanged=True,temporal_leading_trim=False,audio_resampled_to_48k=True))
        process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(process.stderr,encoding='utf-8');process.check_returncode()
        timing=clock.verify_clock(clock._probe(output,count=True),frames=1448,width=736,height=1312)
        if segment_results(run)!=rows:raise ValueError('native_results_changed_during_assembly')
        result=dict(schema=SCHEMA,file=bind(output),segments=rows,native_ids=[r['prompt_id'] for r in rows],
            native_results=[r['native_result'] for r in rows],clock=timing,assembly_inputs_sha256=source,
            imported_s02=bind(run/'imported/S02/IMPORT.json'),temporal_leading_trim=False,
            content_status='user_review_pending',production_approved=False,publication=False)
        freeze(final,result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','status','prepare-images','images','prepare-video','video','collect-image','collect-video','assemble'])
    p.add_argument('--run',type=Path,default=RUN);p.add_argument('--shot',choices=NEW_IDS)
    p.add_argument('--poll-seconds',type=int,default=30);p.add_argument('--max-seconds',type=int,default=21600);a=p.parse_args()
    if a.action in ('images','video'):value=execute(a.run,'image' if a.action=='images' else 'video',a.shot,a.poll_seconds,a.max_seconds)
    elif a.action.startswith('collect-'):
        if a.shot is None:p.error('known-collect requires --shot')
        value=collect_known(a.run,a.action.split('-')[1],a.shot)
    elif a.action=='prepare-images':value=prepare_images(a.run,a.shot)
    elif a.action=='prepare-video':value=prepare_video(a.run,a.shot)
    else:value={'prepare':prepare,'status':status,'assemble':assemble}[a.action](a.run)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
