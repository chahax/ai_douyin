"""One source-driven opening sample using the existing image and H3 producers.

prepare/status never submit. Actual observations and launch approvals are
separate files; this adapter does not create a visual approval or retry a job.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_h3_handoff_v3 as native
from src.content_factory import visual_spatial_stills_v24 as stills
from src.content_factory import visual_opening_frame as opening

PROJECT=Path(__file__).resolve().parents[1]
RUN=PROJECT/'data/video_generation/h3_story_opening_s02_20261110_v1'
SOURCE=PROJECT/'data/qa/h3_opening_frame_20261110_v1/actual_source_preparation_cpu_complete'
BASE=PROJECT/'data/video_generation/h3_continuity_full_minute_20261109_v1/MINUTE_SPEC.json'
SID='S02'
read=native.read
bind=core.binding
freeze=native.freeze


def scope(run):
    run=Path(run).resolve()
    if run!=Path(RUN).resolve():raise ValueError('explicit_new_opening_sample_required')
    return run


def folders(run):
    return run/'stills'/'opening_S02', run/'visual_h3_v3'/'opening_S02'


def prepare(run=RUN):
    run=scope(run);run.mkdir(parents=True,exist_ok=True)
    user=dict(user_statement='新流程生成',engineering_scope_not_user_quoted_numeric_limit=True,
              engineering_limits=dict(image_submissions=1,video_submissions=1,cloud_media=0),
              publication=False,unknown_replay=False,first_frame_policy=opening.POLICY,
              source_case=bind(SOURCE/'SOURCE_CASE.json'),baseline_spec=bind(BASE))
    freeze(run/'ROOT_USER_SCOPE.json',user)
    freeze(run/'USER_AUTHORIZATION.json',dict(user,max_image_submissions=1,new_cloud_media_calls=0))
    entry=deepcopy(next(x for x in core._entries(user['source_case']) if x['shot_id']==SID))
    if entry.get('first_frame_policy')!=opening.POLICY:raise ValueError('new_source_first_frame_policy_required')
    core.validate_entry(entry)
    freeze(run/'SOURCE_CASE.json',dict(schema=core.SCHEMA,shots=[entry]))
    report=core.evaluate(entry)
    if report['status']!='reanchor_required':raise ValueError('real_new_opening_image_required')
    freeze(run/'REANCHOR_WORK_ORDER.json',report['work_order'])
    spec=read(BASE);cfg=deepcopy(spec['h3_config']);cfg['runs_root']=str(run/'visual_h3_v3')
    freeze(run/'H3_CONFIG.json',cfg)
    image_run,_=folders(run)
    result=stills.prepare(image_run,handoff=SOURCE/'spatial/HANDOFF.json',
        render_result=SOURCE/'spatial/blender_canonical_v34/RESULT.json',
        inputs=core.check(spec['spatial']['inputs']),authorization=run/'USER_AUTHORIZATION.json',
        config=core.check(spec['spatial']['config']),reference_packing=stills.SCREEN_PACKING)
    _,plan=stills._load(image_run);item=next(x for x in plan['items'] if x['id']=='S02_start')
    if item['visible_cast']!=['su_mo'] or len(item['references'])!=2:raise ValueError('only_first_shot_cast_pixels_required')
    request=dict(schema='h3_reanchor_source_state_review_request/v33',
        work_order_sha256=core.digest(report['work_order']),entry_base_sha256=core.digest(core._base(entry)),
        spatial_plan=plan['spatial_plan'],item_id=item['id'],state_sha256=core.digest(item['state']),
        canonical_characters=entry['canonical_characters'],canonical_room=entry['canonical_room'],
        target_stage=item['stage'],opening_frame=opening.contract(entry),
        required_review_file=str(run/'SOURCE_STATE_REVIEW.json'),review_not_yet_observed=True)
    freeze(run/'SOURCE_STATE_REVIEW_REQUEST.json',request)
    draft=core.compile_prompt(entry);draft_path=run/'ACTUAL_PROMPT_DRAFT.json'
    if draft_path.exists() and read(draft_path)!=draft:
        draft_path=run/'ACTUAL_PROMPT_DRAFT_REVISION.json'
    freeze(draft_path,draft)
    return dict(status='source_state_review_required',run=str(run),stills=result,
                source_state_review_request=bind(run/'SOURCE_STATE_REVIEW_REQUEST.json'),model_posts=0)


def prepare_images(run=RUN):
    run=scope(run);image_run,_=folders(run)
    review=run/'SOURCE_STATE_REVIEW.json'
    if not review.exists():return dict(status='source_state_review_required',model_posts=0)
    base=read(BASE)
    result=core.prepare_reanchor(bind(run/'SOURCE_CASE.json'),SID,image_run,
        handoff=SOURCE/'spatial/HANDOFF.json',render_result=SOURCE/'spatial/blender_canonical_v34/RESULT.json',
        inputs=core.check(base['spatial']['inputs']),authorization=run/'USER_AUTHORIZATION.json',
        config=core.check(base['spatial']['config']),item_id='S02_start',source_binding_review=bind(review))
    freeze(run/'IMAGE_RECEIPT_TEMPLATE.json',result['receipt_template'])
    freeze(run/'LAUNCH_REQUEST_IMAGE.json',launch_request(run,'image'))
    return result


def prepare_video(run=RUN):
    run=scope(run);image_run,video_run=folders(run)
    candidates=read(image_run/'batches/reanchor_S02/CANDIDATES.json')
    candidate=next(x for x in candidates['items'] if x['id']=='S02_start')
    review=run/'ANCHOR_REVIEW.json'
    entry=deepcopy(core._entries(bind(run/'SOURCE_CASE.json'))[0])
    receipt=read(run/'IMAGE_RECEIPT_TEMPLATE.json')
    receipt['candidates']=bind(image_run/'batches/reanchor_S02/CANDIDATES.json')
    selection=run/'DERIVED_OPENING_SELECTION.json'
    if selection.exists():
        selected=read(selection)
        if selected.get('parent_image')!=candidate['image'] or selected.get('parent_generation_receipt')!=receipt:
            raise ValueError('derived_selection_must_preserve_actual_native_parent')
        receipt=dict(kind='derived_opening_crop/v1',parent_image=candidate['image'],
            parent_generation_receipt=receipt,crop_result=selected['crop_result'])
        candidate=dict(id=candidate['id'],image=selected['image'],derived_from=candidate['image'],native_output=False)
        review=run/'DERIVED_ANCHOR_REVIEW.json'
    if not review.exists():return dict(status='actual_anchor_review_required',candidate=candidate,required_review_file=str(review),model_posts=0)
    entry['reanchor']=dict(image=candidate['image'],coverage_review=bind(review),
        work_order_sha256=core.digest(read(run/'REANCHOR_WORK_ORDER.json')),generation_receipt=receipt)
    report=core.evaluate(entry)
    if report['status']!='ready':raise ValueError('actual_source_bound_opening_not_ready')
    freeze(run/'VIDEO_SOURCE_CASE.json',dict(schema=core.SCHEMA,shots=[entry]))
    result=native.prepare_from_continuity(bind(run/'VIDEO_SOURCE_CASE.json'),video_run,read(run/'H3_CONFIG.json'))
    freeze(run/'LAUNCH_REQUEST_VIDEO.json',launch_request(run,'video'))
    return result


def launch_request(run,kind):
    if kind not in ('image','video'):raise ValueError('explicit_image_or_video_stage_required')
    image_run,video_run=folders(run)
    job=image_run/'batches/reanchor_S02' if kind=='image' else video_run
    files=[__file__,core.__file__,native.__file__,stills.__file__,opening.__file__]
    return dict(schema='h3_story_opening_sample_launch/v1',kind=kind,
        authority=bind(run/'USER_AUTHORIZATION.json'),source=bind(run/'SOURCE_CASE.json'),
        plan=bind(job/'PLAN.json'),code=[bind(x) for x in files],
        graph=bind(job/'workflow_api.json' if kind=='image' else job/'shots/S02/workflow_api.json'),
        publication=False,unknown_replay=False)


def require_approval(run,kind):
    expected=launch_request(run,kind)
    approval=read(run/('ROOT_LAUNCH_'+kind.upper()+'.json'))
    if (approval.get('request')!=expected or not approval.get('approved_by')
            or not isinstance(approval.get('evidence'),list) or not approval['evidence']):
        raise ValueError('actual_plan_and_code_bound_launch_approval_required')


def status(run=RUN):
    run=scope(run);image_run,video_run=folders(run)
    return dict(run=str(run),image=stills.status(image_run,'reanchor_S02')
        if (image_run/'batches/reanchor_S02/PLAN.json').exists() else None,
        video=native.status(video_run) if (video_run/'PLAN.json').exists() else None,
        production_approved=False)


def execute(run,kind,poll_seconds=30,max_seconds=14400):
    run=scope(run)
    if kind not in ('image','video'):raise ValueError('explicit_image_or_video_stage_required')
    if not 1<=poll_seconds<=60 or not 1<=max_seconds<=21600:raise ValueError('bounded_wait_required')
    image_run,video_run=folders(run)
    if kind=='image':
        if not (image_run/'batches/reanchor_S02/PLAN.json').exists():prepare_images(run)
        current=stills.status(image_run,'reanchor_S02')
        if current['status']=='prepared':require_approval(run,'image')
        return stills.execute(image_run,'reanchor_S02',poll_seconds,max_seconds)
    deadline=time.monotonic()+max_seconds
    with stills.jobs.run_lock(video_run,'SAMPLE_WORKER.lock'):
        while True:
            current=native.poll_collect(video_run)
            if current['status'] in ('media_review_required','outcome_unknown','blocked_native_failure','blocked_upstream_changed','paused'):
                if current['status']=='media_review_required':
                    result=read(video_run/'shots/S02/RESULT.json')
                    freeze(run/'FINAL_RESULT.json',dict(native_result=bind(video_run/'shots/S02/RESULT.json'),
                        file={k:result['files']['video'][k] for k in ('path','sha256')},
                        prompt_id=result['prompt_id'],production_approved=False,postprocessing=[]))
                return current
            if current['status']=='prepared':
                require_approval(run,'video');native.submit_next(video_run)
            if time.monotonic()>=deadline:return dict(current,bounded_wait_original_id_preserved=True)
            time.sleep(poll_seconds)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','status','prepare-images','images','prepare-video','video'])
    p.add_argument('--run',type=Path,default=RUN);p.add_argument('--poll-seconds',type=int,default=30)
    p.add_argument('--max-seconds',type=int,default=14400);a=p.parse_args()
    if a.action in ('images','video'):v=execute(a.run,'image' if a.action=='images' else 'video',a.poll_seconds,a.max_seconds)
    else:v={'prepare':prepare,'status':status,'prepare-images':prepare_images,'prepare-video':prepare_video}[a.action](a.run)
    print(json.dumps(v,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
