"""Explicit user-authorized diagnostic continuation; quality failures stay failed.

This adds no submitter. The original v1 executor, source/unknown protections and
four original IDs remain authoritative. Assembly is CPU-only and never grants
production/publication approval.
"""
from pathlib import Path
import subprocess
from . import visual_h3_reference_full_minute_v20 as base

SCHEMA='user_diagnostic_preview_override/v23'


def validate(run,plan):
    file=Path(run)/'USER_PREVIEW_OVERRIDE.json'
    if not file.exists():return None
    value=base.native.read(file);request=base.check(value['request'])
    if (value.get('schema')!=SCHEMA or value.get('runner_plan')!=base.binding(Path(run)/'RUNNER_PLAN.json')
            or value.get('user_statement')!=request.get('user_statement') or not value.get('user_statement')
            or value.get('allow_continue_despite_quality_failure') is not True
            or value.get('allow_unreviewed_diagnostic_segments') is not True
            or value.get('allow_diagnostic_assembly') is not True
            or value.get('production_approved') is not False or value.get('publication') is not False
            or value.get('original_segment_ids')!=list(base.IDS)):
        raise base.MinuteRunError('explicit_original_four_segment_diagnostic_override_required')
    base._check(value['implementation'])
    for row in plan['segments']:
        sid=row['id'];state=base.delivery.status(row['delivery_run'])['shots'][0]
        if sid in value['known_native_ids'] and state.get('prompt_id')!=value['known_native_ids'][sid]:
            raise base.MinuteRunError('preview_override_original_native_id_changed')
        if sid in value['known_results']:
            result,file=base._result(row)
            if base.binding(file)!=value['known_results'][sid]:raise base.MinuteRunError('preview_override_original_result_changed')
        if sid in value['rejected_reviews']:
            rejected=base.check(value['rejected_reviews'][sid])
            actual=Path(run)/'segments'/sid/'ROOT_SEGMENT_REVIEW.json'
            if value['rejected_reviews'][sid]!=base.binding(actual) or rejected.get('approved_for_next') is not False:
                raise base.MinuteRunError('preview_must_preserve_original_quality_rejection')
    return value


def enable(run=base.RUN,*,request):
    run,plan=base._load(run);request_binding=base._bind(request);data=base.check(request_binding)
    if (not Path(request_binding['path']).resolve().is_relative_to(run) or not data.get('user_statement')
            or not data.get('scope') or data.get('do_not_duplicate_execute') is not True):
        raise base.MinuteRunError('explicit_local_user_diagnostic_request_required')
    snapshot=base.status(run);ids={};results={};rejected={}
    for row,item in zip(plan['segments'],snapshot['segments']):
        sid=row['id'];state=item['state']
        if state['status'] in base.TERMINAL_BAD:raise base.MinuteRunError('diagnostic_override_cannot_replay_unknown_or_failed_media')
        if state.get('prompt_id'):ids[sid]=state['prompt_id']
        if state['status']=='technical_saved':results[sid]=base.binding(base._result(row)[1])
        if item['root_review'] is not None and item['root_review']['approved_for_next'] is False:
            rejected[sid]=base.binding(run/'segments'/sid/'ROOT_SEGMENT_REVIEW.json')
    if set(data.get('quality_rejected',[]))!=set(rejected):raise base.MinuteRunError('user_preview_request_rejection_scope_changed')
    value=dict(schema=SCHEMA,request=request_binding,user_statement=data['user_statement'],
               runner_plan=base.binding(run/'RUNNER_PLAN.json'),implementation=base.binding(__file__),
               original_segment_ids=list(base.IDS),known_native_ids=ids,known_results=results,rejected_reviews=rejected,
               allow_continue_despite_quality_failure=True,allow_unreviewed_diagnostic_segments=True,
               allow_diagnostic_assembly=True,quality_rejections_preserved=True,
               production_approved=False,publication=False,media_dispatched=False)
    base.native.freeze(run/'USER_PREVIEW_OVERRIDE.json',value)
    validate(run,plan);return value


def assemble(run=base.RUN):
    run,plan=base._load(run,current=True);override=validate(run,plan)
    if override is None:raise base.MinuteRunError('explicit_user_preview_override_required')
    with base.jobs.run_lock(run,'ASSEMBLY_PREVIEW.lock'):
        snapshot=base.status(run)
        if snapshot['technical_saved']!=4:raise base.MinuteRunError('four_original_saved_segments_required_for_preview')
        # CPU QA does not grant semantic approval and cannot submit new media.
        base._evidence(run,plan,snapshot)
        results=[base._result(row)[0] for row in plan['segments']];videos=[r['files']['video'] for r in results];ids=[r['prompt_id'] for r in results]
        if any(len(set(x))!=4 for x in (ids,[v['sha256'] for v in videos],[v['path'] for v in videos],[v['source_path'] for v in videos])):
            raise base.MinuteRunError('four_distinct_original_native_videos_required')
        quality_failed=[r['id'] for r in snapshot['segments'] if r['root_review'] is not None and r['root_review']['approved_for_next'] is False]
        quality_unreviewed=[r['id'] for r in snapshot['segments'] if r['root_review'] is None]
        inputs=dict(plan=base.binding(run/'RUNNER_PLAN.json'),override=base.binding(run/'USER_PREVIEW_OVERRIDE.json'),
                    results=[base.binding(base._result(r)[1]) for r in plan['segments']],native_ids=ids,video_sha256=[v['sha256'] for v in videos],
                    root_reviews=[base.binding(run/'segments'/r['id']/'ROOT_SEGMENT_REVIEW.json') if r['root_review'] is not None else None for r in snapshot['segments']],
                    cpu_qa=[base.binding(run/'segments'/r['id']/'CPU_QA_RESULT.json') for r in plan['segments']])
        digest=base.native.fingerprint(inputs);output=run/'DIAGNOSTIC_PREVIEW_736x1312.mp4';final=run/'DIAGNOSTIC_PREVIEW_RESULT.json'
        if final.exists():
            result=base.native.read(final);base._check(result['file'])
            if result['assembly_inputs_sha256']!=digest:raise base.MinuteRunError('diagnostic_preview_inputs_changed')
            return result
        if output.exists():raise base.MinuteRunError('unreceipted_diagnostic_output_preserved')
        adjustments=[base._clock_input(v['path'],v['sha256']) for v in videos]
        filters=run/'ASSEMBLY_PREVIEW_FILTER.txt';command,text=base.clock.assembly_command([v['path'] for v in videos],filters,output,frames=base.FRAMES)
        if filters.exists() and filters.read_text(encoding='utf8')!=text:raise base.MinuteRunError('diagnostic_preview_filter_changed')
        filters.write_text(text,encoding='utf8')
        base.native.freeze(run/'ASSEMBLY_PREVIEW_REQUEST.json',dict(inputs=inputs,inputs_sha256=digest,command=command,clock_adjustments=adjustments))
        p=subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1800)
        (run/'ASSEMBLY_PREVIEW.stderr.log').write_text(p.stderr,encoding='utf8');p.check_returncode()
        clock=base.clock.verify_clock(base._probe(output),frames=1448,width=base.WIDTH,height=base.HEIGHT)
        if [base.binding(base._result(r)[1]) for r in plan['segments']]!=inputs['results']:
            raise base.MinuteRunError('diagnostic_sources_changed_during_assembly')
        result=dict(schema='diagnostic_reference_minute/v23',file=base.binding(output),assembly_inputs_sha256=digest,
                    native_ids=ids,clock=clock,quality_failed=quality_failed,quality_unreviewed=quality_unreviewed,
                    content_status='diagnostic_preview_quality_failures_preserved',diagnostic_preview=True,
                    production_approved=False,publication=False,source_clock_adjustments=adjustments)
        base.native.freeze(final,result);base._event(run,'DIAGNOSTIC_PREVIEW_ASSEMBLED',str(output));return result
