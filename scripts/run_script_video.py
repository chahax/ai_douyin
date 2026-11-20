"""Run an approved detailed script through the project's Dreamina adapter.

Explicit per-shot submission, durable receipts before spending, resumable query,
and native-audio assembly. This produces review candidates, never publishes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.dreamina_cli import (DreaminaCLIClient, DreaminaCLIConfig,
    dreamina_submit_id, dreamina_report_status)
from src.content_factory.conversation_direction import (validate_plan, compile_prompt,
    require_reviewed_reference, CHECKS)
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference
from src.content_factory.seedance_models import ark_model
from src.content_factory.seedance_frames import bind_frame, reviewed_frame_reference, image_info
from src.content_factory.script_video_review import build_review_packet
from src.content_factory.media_review_policy import mark_saved_candidate
from src.content_factory import video_campaign
from src.content_factory.video_provider_failure import classify_failure
from src.content_factory import reviewed_storyboard_direction
from src.shared.config import settings


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format',
        '-show_streams', '-of', 'json', str(path)]))


def validate_script(script):
    if script.get('schema') != 'detailed_video_script/v4':
        raise ValueError('Expected a complete v4 storyboard')
    if script.get('format_kind') != 'short':
        raise ValueError('This run is restricted to the selected short script')
    cursor = 0
    for index, shot in enumerate(script['shots'], 1):
        seconds = shot['end_seconds'] - shot['start_seconds']
        if shot['shot_id'] != f'S{index:02d}' or shot['start_seconds'] != cursor:
            raise ValueError('Non-contiguous storyboard')
        if seconds != int(seconds) or not 4 <= seconds <= 30:
            raise ValueError('Duration unsupported by this provider')
        if shot['dialogue_mode'] != 'in_scene' or shot['dialogue_speaker'] not in shot['participants']:
            raise ValueError('This run requires visible in-scene speakers')
        for field in ['model_prompt_zh', 'composition', 'lighting', 'camera', 'start_frame', 'end_frame']:
            if not shot.get(field):
                raise ValueError(f'Missing production field: {field}')
        cursor = shot['end_seconds']
    if cursor != script['target_duration_seconds']:
        raise ValueError('Duration mismatch')


def require_project_script_review(script, script_path):
    """Recheck project-generated pairs locally before locking or spending.

    Custom scripts retain their existing validation path. An old model pass or
    a cached preparation proof cannot replace the current pair review.
    """
    generation = script.get('generation') or {}
    if not isinstance(generation, dict):
        raise ValueError('剧本生成来源字段无效，不能确认当前审核')
    if generation.get('method') not in {'llm_script_pair', 'staged_screenplay_bundle'}:
        return None
    from src.trend_intelligence.saved_script_review import require_current_saved_script_review
    source = Path(script_path).resolve()
    if read(source) != script:
        raise ValueError('锁定剧本与当前来源稿不一致，须重新审核并准备')
    return require_current_saved_script_review(source)


def validate_execution_plan(plan, script, script_sha):
    if script.get('generation', {}).get('method') == 'staged_screenplay_bundle':
        return reviewed_storyboard_direction.validate_plan(plan, script, script_sha)
    return validate_plan(plan, script, script_sha)


def compile_execution_prompt(script, shot, plan, **kwargs):
    if plan.get('schema') == reviewed_storyboard_direction.SCHEMA:
        return reviewed_storyboard_direction.compile_prompt(script, shot, plan, **kwargs)
    return compile_prompt(script, shot, plan, **kwargs)


def prepare(folder, script_path, authorization, direction_path=None, provider='dreamina_cli', test_shot=None):
    if (folder / 'production.json').exists():
        raise ValueError('Run already exists; inspect or resume it instead')
    script = read(script_path)
    validate_script(script)
    current_review = require_project_script_review(script, script_path)
    if provider not in {'dreamina_cli','ark_api'}:
        raise ValueError('This storyboard runner supports dreamina_cli or ark_api')
    if test_shot and test_shot not in [s['shot_id'] for s in script['shots']]:
        raise ValueError('Test shot is not present in the locked script')
    direction = read(direction_path) if direction_path else None
    if script.get('generation', {}).get('method') == 'staged_screenplay_bundle' and direction is None:
        direction = reviewed_storyboard_direction.build_plan(script, script_path, current_review)
    if len(script['characters']) == 2 and direction is None:
        raise ValueError('双人对话生成前必须准备固定座位、机位与动作节奏计划')
    if direction:
        validate_execution_plan(direction,script,sha(script_path))
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(script_path, folder / 'locked_script.json')
    shutil.copyfile(script_path.with_suffix('.md'), folder / 'locked_script.md')
    shutil.copyfile(script_path.with_suffix('.audit.json'), folder / 'source.audit.json')
    if direction:
        if direction_path:
            shutil.copyfile(direction_path, folder/'direction_plan.json')
        else:
            write(folder/'direction_plan.json', direction)
    manifest = dict(schema='script_video_run/v1', title=script['title'] + ' · 45 秒短版',
        created_at=now(), status='prepared', script=str(folder/'locked_script.md'),
        script_json=str(folder/'locked_script.json'), source_audit=str(folder/'source.audit.json'),
        source_script=str(script_path), script_sha256=sha(script_path),
        shots=[s['shot_id'] for s in script['shots']], target_duration_seconds=script['target_duration_seconds'],
        authorization=authorization, authorization_at=now(), review_result='pending',
        settings_label='Seedance 2.5 · 480P · 9:16 · 原生对白',
        input_mode='第一镜建立人物和场景；后续镜头使用本批实际生成视频作为人物、场景与声音参考。',
        script_generation_note='使用项目双剧本工作流生成并经用户指定的 45 秒短版；逐镜台词和时间线锁定。',
        video_generation_submitted=False, published=False, provider=provider)
    from src.services.artifact_account import artifact_account
    owner = artifact_account(manifest, ROOT)
    if owner.get('account_conflict'):
        raise ValueError('剧本与来源审计的账号归属冲突')
    manifest.update(owner)
    if current_review:
        manifest['script_editorial_review'] = current_review
    if provider == 'ark_api':
        config=SeedanceConfig.from_env('ark_api',require_key=False)
        ark_model(config.model)
        manifest.update(api_base_url=config.base_url,api_model=config.model,
                        settings_label=f'{config.model} · 480P · 9:16 · 原生对白',billing_mode='ark_api_usage')
    if test_shot:
        shot=next(s for s in script['shots'] if s['shot_id']==test_shot)
        manifest.update(test_shot=test_shot,allowed_shots=[test_shot],shots=[test_shot],
                        title=f"{script['title']} · {test_shot} 首镜测试 · {shot['end_seconds']-shot['start_seconds']:g} 秒")
    write(folder/'production.json', manifest)
    if direction:
        manifest.update(direction_plan=str(folder/'direction_plan.json'),
                        direction_sha256=sha(folder/'direction_plan.json'),
                        input_mode=('机械绑定已审故事和摄影原文；固定原机位光线，逐段审核后用原始尾帧衔接。'
                            if direction.get('schema') == reviewed_storyboard_direction.SCHEMA else
                            '固定南北座位和西侧机位；参考镜头通过空间、身份、节奏及说话人检查后才能用于后续镜头。'))
        write(folder/'production.json',manifest)
    return manifest


def locked(folder):
    manifest = read(folder/'production.json')
    if sha(folder/'locked_script.json') != manifest['script_sha256']:
        raise ValueError('Locked script changed')
    if manifest.get('direction_plan') and sha(folder/'direction_plan.json') != manifest['direction_sha256']:
        raise ValueError('Locked direction plan changed')
    return manifest, read(folder/'locked_script.json')


def compile_default_first_frame_prompt(script, shot, plan):
    return ('从所给首帧开始，保持其中人物外貌、服装、场景与构图，按下文推进动作和对白。\n'
            + compile_execution_prompt(script, shot, plan, timing_mode='ordered', use_input_first_frame=True))


def submit(folder, shot_id, client, references, first_frame=None, preview=False,
           execution_plan=None, execution_review=None):
    if bool(execution_plan) != bool(execution_review):
        raise ValueError('Provide both the explicit execution plan and its independent text review')
    if execution_plan and (shot_id != 'S01' or not first_frame or references):
        raise ValueError('Compact execution is S01-only with its reviewed first frame and no video references')
    manifest, script = locked(folder)
    if not preview and manifest.get('generation_gate') == 'provider_review_required':
        raise ValueError('Provider policy rejection requires provider review; editing a prompt does not clear it')
    if manifest.get('allowed_shots') and shot_id not in manifest['allowed_shots']:
        raise ValueError('This run is authorized only for the selected test shot')
    receipt = folder/f'{shot_id}.json'
    if receipt.exists() and not preview:
        raise ValueError('Receipt already exists; query it, never submit a duplicate')
    if not preview:
        # Recheck on each new paid submission: the source may have been changed
        # or rejected, or the review policy updated since prepare().
        require_project_script_review(script, manifest.get('source_script', ''))
    shot = next(s for s in script['shots'] if s['shot_id'] == shot_id)
    refs = [p.resolve() for p in references]
    if first_frame and (refs or manifest.get('provider') != 'ark_api'):
        raise ValueError('First-frame mode requires Ark and cannot mix reference videos')
    for path in refs:
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('References must come from this run')
    plan = read(folder/'direction_plan.json') if manifest.get('direction_plan') else None
    if len(script['characters']) == 2 and plan is None:
        raise ValueError('当前双人剧本缺少空间与节奏锁定，不能继续使用旧方式提交')
    if plan:
        validate_execution_plan(plan,script,manifest['script_sha256'])
        if (plan.get('schema') == 'reviewed_storyboard_direction/v1'
                and shot_id != script['shots'][0]['shot_id'] and not first_frame):
            raise ValueError('Later reviewed storyboard shots require the preceding approved raw tail as first frame')
        if shot_id != script['shots'][0]['shot_id'] and not (refs or first_frame):
            raise ValueError('后续镜头必须提供已经通过检查的参考视频或首帧')
        for path in refs:
            require_reviewed_reference(folder,path,manifest['direction_sha256'])
    prompt = shot['model_prompt_zh']
    if plan:
        prompt = compile_execution_prompt(script,shot,plan,
                                timing_mode='ordered' if manifest.get('provider')=='ark_api' else 'precise')
    if refs:
        prompt = ('参考视频用于锁定本片人物的身份外貌服装和场景陈设。'
                  '声线只参考其中同一个角色实际发声的部分，不能把参考中另一角色的声音用作本镜说话人的声音；以本镜角色声音设定为准。'
                  '这是后续镜头，按下文指定机位重新取景和推进动作，不复制参考视频里的台词、动作或字幕。'
                  '若有多个参考，第一条锁定人物场景，最后一条提供最近镜头的连续性。只说下文指定的一句对白。\n' + prompt)
    provider=manifest.get('provider','dreamina_cli')
    frame_binding=None
    execution_binding=None
    if provider=='ark_api':
        if client.config.base_url!=manifest['api_base_url'] or client.config.model!=manifest['api_model']:
            raise ValueError('API endpoint or model differs from the locked run')
        frame_refs=[]
        original_sources=[]
        for path in refs:
            ref,source=original_ark_reference(folder,path,client,manifest,preview=preview)
            frame_refs.append(ref);original_sources.append(source)
        if first_frame:
            if plan is None:
                raise ValueError('First-frame bindings require a locked direction plan')
            ref,frame_binding=reviewed_frame_reference(folder,shot_id,first_frame,manifest,plan,config=client.config)
            if frame_binding.get('original_ark_image'):
                original_sources.append(frame_binding['original_ark_image'])
            # Prefer the provider's original tail URL when this is an unmodified model output.
            for candidate in folder.rglob('S[0-9][0-9].json'):
                source_record=read(candidate)
                if source_record.get('last_frame') and Path(source_record['last_frame']).resolve()==Path(first_frame).resolve():
                    ref,source=original_ark_reference(folder,Path(source_record['local_video']),client,manifest,
                                                     field='last_frame_url',preview=preview)
                    original_sources.append(source)
                    break
            frame_refs=[ref]
            if execution_plan:
                from src.content_factory.compact_execution import require_compact_execution
                prompt, execution_binding = require_compact_execution(
                    folder, first_frame, execution_plan, execution_review, client.config)
            else:
                prompt = compile_default_first_frame_prompt(script, shot, plan)
                opening_receipt = folder/'S01.json'
                if (shot_id != 'S01' and plan.get('schema') == 'reviewed_storyboard_direction/v1'
                        and opening_receipt.is_file() and read(opening_receipt).get('execution_prompt')):
                    from src.content_factory.compact_execution import render_compact_prompt
                    prompt, continuation_recipe = render_compact_prompt(
                        shot, script['aspect_ratio'], continuation=True)
        args=client.build_task_payload(prompt,duration=int(shot['end_seconds']-shot['start_seconds']),
                                      ratio='adaptive' if first_frame else script['aspect_ratio'],
                                      resolution='480p',generate_audio=True,references=frame_refs,
                                      task_type='first_frame' if first_frame else 'reference' if refs else 'text',return_last_frame=True)
        credit={}
    else:
        args = client.build_video_arguments(prompt, duration=int(shot['end_seconds']-shot['start_seconds']),
            ratio=script['aspect_ratio'], resolution='480p', reference_videos=refs)
        credit = client.user_credit()
    record = dict(shot=shot_id, status='submit_outcome_unknown', created_at=now(),
        prompt=prompt, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        script_sha256=manifest['script_sha256'], references=[str(p) for p in refs],
        direction_sha256=manifest.get('direction_sha256'),
        reference_sha256=[sha(p) for p in refs], model=client.config.model if provider=='ark_api' else client.config.model_version,
        resolution='480p', aspect=script['aspect_ratio'], duration=shot['end_seconds']-shot['start_seconds'],
        count=1, credits_before=credit.get('total_credit'), provider=provider)
    if provider=='ark_api':
        record['request']=args
        record['original_ark_sources']=original_sources
        if 'continuation_recipe' in locals():
            record.update(continuation_profile='compact_continuation/v1',
                          continuation_recipe=continuation_recipe,
                          subtitle_source=shot['subtitle'], model_subtitles=False)
    if frame_binding:
        inherited_review = frame_binding.get('source_frame_review')
        review_origin = (inherited_review['path'] if inherited_review
                         else str(folder/'frame_reviews'/f'{shot_id}.json'))
        record.update(first_frame=str(Path(first_frame).resolve()),
                      first_frame_sha256=frame_binding['image_info']['sha256'],
                      first_frame_review=review_origin,aspect=args['ratio'])
        if inherited_review:
            imported = frame_binding['original_ark_image']
            record.update(first_frame_review_origin='inherited_source_frame_review',
                          first_frame_review_sha256=inherited_review['sha256'],
                          first_frame_import=imported['import_path'],
                          first_frame_import_sha256=imported['import_sha256'])
    if execution_binding:
        record.update(execution_prompt=execution_binding,
                      first_frame_review=execution_binding['first_frame_review']['path'],
                      subtitle_source=execution_binding['subtitle_source'], model_subtitles=False)
    if preview:
        if provider!='ark_api':
            raise ValueError('Request preview is currently supported for Ark only')
        preview_path=folder/f'{shot_id}.workflow.preview.json'
        write(preview_path,dict(record,status='dry_run',video_generation_submitted=False))
        return {'shot':shot_id,'status':'dry_run','first_frame':bool(frame_binding),'preview':str(preview_path)}
    video_campaign.reserve(folder, manifest, record)
    write(receipt, record)
    try:
        payload = client.create_task(args) if provider=='ark_api' else client.submit_video(args)
        record['provider_response'] = payload
        if provider=='ark_api':
            record['submit_id']=payload.get('id')
            record['status']='submitted' if record['submit_id'] else 'submit_outcome_unknown'
        else:
            record['cost_credits'] = payload.get('credit_count', 0)
            record['submit_id'] = dreamina_submit_id(payload)
            record['status'] = dreamina_report_status(payload) if record['submit_id'] else 'submit_outcome_unknown'
        write(receipt, record)
        if not record['submit_id']:
            raise RuntimeError('No task id; inspect the receipt before any retry')
        manifest.update(status='generating', video_generation_submitted=True)
        write(folder/'production.json', manifest)
        if provider=='ark_api':save_ark_report(folder,record)
        return {'shot':shot_id, 'status':record['status'], 'submit_id':record['submit_id']}
    except Exception as exc:
        record['error'] = str(exc)
        if provider=='ark_api' and getattr(exc,'status_code',None) in {400,401,403,404}:
            code=getattr(exc,'error_code',None)
            if (code in {'AuthenticationError','ModelNotOpen'} or str(code).startswith('InputImageSensitiveContentDetected')) and not record.get('submit_id'):
                record.update(status='request_rejected',http_status=exc.status_code,provider_error_code=code)
                manifest.update(status='request_rejected',generation_error=record['error'],api_request_attempted=True)
                write(folder/'production.json',manifest)
        write(receipt, record)
        video_campaign.reconcile_rejection(manifest, record)
        if provider=='ark_api':save_ark_report(folder,record)
        raise


def original_ark_reference(folder, path, client, manifest, field='video_url', preview=False):
    """Use only an unchanged, locally verified original from this Ark account.

    Official documented input path: /docs/82379/2608626#trust-model-output.
    This does not upload or relabel rejected cross-platform image derivatives.
    """
    path=path.resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError('Original reference must be in this run')
    source=read(path.with_suffix('.json'))
    if (source.get('provider')!='ark_api' or source.get('status')!='downloaded'
            or Path(source.get('local_video','')).resolve()!=path
            or sha(path)!=source.get('video_sha256') or not source.get('submit_id')):
        raise ValueError('Reference is not a verified original Ark output')
    payload=source.get('latest_response',{}) if preview else client.get_task(source['submit_id'])
    if payload.get('status')!='succeeded' or payload.get('model')!=manifest['api_model']:
        raise ValueError('Original reference task is not confirmed under the current account/model')
    created=payload.get('created_at')
    if not isinstance(created,(int,float)) or not 0 <= datetime.now(timezone.utc).timestamp()-created < 30*86400:
        raise ValueError('Original portrait output is outside the documented 30-day validity')
    url=payload.get('content',{}).get(field)
    if not isinstance(url,str) or not url.startswith('https://'):
        raise ValueError('Original task did not provide an HTTPS reference URL')
    if field=='last_frame_url':
        if sha(Path(source['last_frame']))!=source.get('last_frame_sha256'):
            raise ValueError('Original tail image was modified')
        ref=SeedanceReference('image',url,'first_frame')
    else:
        ref=SeedanceReference('video',url,'reference_video')
    return ref,{'task_id':source['submit_id'],'source_video_sha256':source['video_sha256'],
                'content_field':field,'created_at':created,'verified_at':now(),
                'verification':'local_receipt_preview' if preview else 'current_account_task_get',
                'policy':'https://docs.volcengine.com/docs/82379/2608626#trust-model-output'}


def query(folder, shot_id, client):
    receipt = folder/f'{shot_id}.json'
    record = read(receipt)
    if record['status'] == 'downloaded':
        if sha(Path(record['local_video'])) != record['video_sha256']:
            raise ValueError('Downloaded video hash mismatch')
        return {'shot':shot_id, 'status':'downloaded', 'video':record['local_video']}
    if record.get('provider')=='ark_api':
        return query_ark(folder,record,client)
    payload = client.query_result(record['submit_id'])
    record.update(status=dreamina_report_status(payload), last_checked_at=now(), latest_response=payload)
    write(receipt, record)
    if record['status'] == 'succeeded':
        downloads = folder/'downloads'/shot_id
        final = client.query_result(record['submit_id'], download_dir=downloads)
        write(downloads/'response.json', final)
        videos = list(downloads.rglob('*.mp4'))
        if len(videos) != 1:
            raise RuntimeError(f'Expected exactly one downloaded video, found {len(videos)}')
        destination = folder/f'{shot_id}.mp4'
        shutil.copyfile(videos[0], destination)
        media = probe(destination)
        if not any(s['codec_type']=='audio' for s in media['streams']):
            raise RuntimeError('Generated clip is missing native dialogue audio')
        write(folder/f'{shot_id}.probe.json', media)
        record.update(completed_at=now(), local_video=str(destination),
            video_sha256=sha(destination), actual_duration_seconds=float(media['format']['duration']))
        mark_saved_candidate(record, status='downloaded')
        write(receipt, record)
    return {'shot':shot_id, 'status':record['status'], 'submit_id':record['submit_id']}


def save_ark_report(folder, record):
    directory=ROOT/'data/video_generation/seedance';directory.mkdir(parents=True,exist_ok=True)
    report={'schema':'seedance_generation_report/v1','provider':'ark_api','mode':'submit',
            'segment_id':record['shot'],'request':record['request'],'status':record['status'],
            'created_at':record['created_at'],'updated_at':record.get('last_checked_at',record['created_at']),
            'created':record.get('provider_response',{}),'final':record.get('latest_response',{}),
            'video_path':record.get('local_video'),'production_manifest':str(folder/'production.json')}
    from src.services.artifact_account import artifact_account
    report.update(artifact_account(report, ROOT))
    write(directory/f"{folder.name}.{record['shot']}.seedance.json",report)


def query_ark(folder, record, client):
    manifest,_=locked(folder)
    if client.config.base_url!=manifest['api_base_url'] or client.config.model!=manifest['api_model']:
        raise ValueError('API endpoint or model differs from the locked run')
    payload=client.get_task(record['submit_id'])
    record.update(status=payload['status'],last_checked_at=now(),latest_response=payload,usage=payload.get('usage') or {})
    receipt=folder/f"{record['shot']}.json";write(receipt,record)
    save_ark_report(folder,record)
    if payload['status']=='succeeded':
        destination=client.download_video(payload,folder/f"{record['shot']}.mp4")
        media=probe(destination)
        if not any(s['codec_type']=='audio' for s in media['streams']):
            raise RuntimeError('Generated clip is missing requested native audio')
        write(folder/f"{record['shot']}.probe.json",media)
        record.update(completed_at=now(),local_video=str(destination),
                      video_sha256=sha(destination),actual_duration_seconds=float(media['format']['duration']))
        mark_saved_candidate(record, status='downloaded')
        write(receipt,record);save_ark_report(folder,record)
        try:
            save_last_frame(folder, record['shot'], client)
        except Exception as exc:
            # The video is already saved. Retrying this read-only operation must not regenerate it.
            record=read(receipt)
            record['last_frame_download_error']=type(exc).__name__
            write(receipt,record)
        if manifest.get('test_shot')==record['shot']:
            manifest.update(status='test_candidate_ready',test_video=str(destination),
                            completed_at=record['completed_at'],review_result='awaiting_human_review',
                            probe=str(folder/f"{record['shot']}.probe.json"))
            write(folder/'production.json',manifest)
    elif payload['status'] in {'failed','expired','cancelled'}:
        diagnosis = classify_failure(payload)
        write(folder/f"{record['shot']}.provider_failure.json", diagnosis)
        manifest.update(status='test_generation_failed',generation_error=payload.get('error',{}),
                        provider_failure=diagnosis,
                        generation_gate=diagnosis['next_action'])
        write(folder/'production.json',manifest)
    return {'shot':record['shot'],'status':record['status'],'submit_id':record['submit_id']}


def save_last_frame(folder, shot_id, client):
    manifest,_=locked(folder)
    record=read(folder/f'{shot_id}.json')
    if record.get('provider')!='ark_api' or record.get('status')!='downloaded':
        raise ValueError('A downloaded Ark video is required to save its original tail')
    if sha(Path(record['local_video']))!=record['video_sha256']:
        raise ValueError('Source video hash mismatch')
    if client.config.base_url!=manifest['api_base_url'] or client.config.model!=manifest['api_model']:
        raise ValueError('API endpoint or model differs from the locked run')
    payload=record['latest_response']
    if not payload.get('content',{}).get('last_frame_url'):
        return {'shot':shot_id,'last_frame':'not_returned'}
    destination=folder/f'{shot_id}.last_frame.png'
    if record.get('last_frame') and destination.is_file():
        if image_info(destination)['sha256']!=record['last_frame_sha256']:
            raise ValueError('Saved original last frame has changed')
        return {'shot':shot_id,'last_frame':str(destination)}
    client.download_last_frame(payload,destination)
    info=image_info(destination)
    record.update(last_frame=str(destination),last_frame_sha256=info['sha256'],last_frame_saved_at=now())
    record.pop('last_frame_download_error',None)
    write(folder/f'{shot_id}.json',record)
    return {'shot':shot_id,'last_frame':str(destination)}


def retry_failed(folder, shot_id, client):
    receipt = folder/f'{shot_id}.json'
    record = read(receipt)
    if record.get('provider')=='ark_api':
        raise ValueError('Ark failures require explicit inspection; there is no automatic paid retry')
    if record.get('status') != 'failed' or record.get('cost_credits') != 0:
        raise ValueError('Only an explicitly failed, uncharged task can be retried here')
    history = folder/'failed_attempts'
    if list(history.glob(f'{shot_id}.*.json')):
        raise ValueError('One recovery attempt already used; inspect the provider failure')
    result = client.query_result(record['submit_id'])
    if dreamina_report_status(result) != 'failed' or result.get('credit_count',0) != 0:
        raise ValueError('Failure and zero cost not confirmed by provider')
    balance=client.user_credit().get('total_credit')
    if balance is None or balance < record['credits_before']:
        raise ValueError('Balance does not confirm an uncharged failed request')
    record.update(failure_verified_at=now(), failure_response=result, balance_after_failure=balance)
    write(receipt,record)
    history.mkdir(exist_ok=True)
    receipt.rename(history/f"{shot_id}.{record['submit_id']}.json")
    return submit(folder,shot_id,client,[Path(p) for p in record['references']])


def retry_ark_configuration(folder, shot_id, client, authorization):
    """Retry one confirmed limit failure after an explicit user retry instruction."""
    if not authorization or not authorization.strip():
        raise ValueError('Record the explicit user instruction authorizing this retry')
    path=folder/f'{shot_id}.json';record=read(path)
    if record.get('execution_prompt'):
        raise ValueError('Preserve the compact attempt; use an explicitly reviewed new run instead of implicit retry')
    if record.get('provider')!='ark_api' or record.get('status')!='failed' or not record.get('submit_id'):
        raise ValueError('Only a terminal failed Ark task can be recovered')
    result=client.get_task(record['submit_id'])
    if result.get('status')!='failed' or (result.get('error') or {}).get('code')!='SetLimitExceeded':
        raise ValueError('The server has not confirmed the specific configuration failure')
    history=folder/'failed_attempts';history.mkdir(exist_ok=True)
    if list(history.glob(f'{shot_id}.limit.*.json')):
        raise ValueError('One limit recovery was already attempted; inspect before further work')
    record.update(recovery_authorization=authorization,recovery_verified_at=now(),latest_response=result)
    write(path,record)
    destination=history/f"{shot_id}.limit.{record['submit_id']}.json"
    if not destination.resolve().is_relative_to(folder.resolve()):raise ValueError('Invalid task ID in recovery path')
    path.rename(destination)
    manifest=read(folder/'production.json');manifest.pop('generation_error',None)
    write(folder/'production.json',manifest)
    return submit(folder,shot_id,client,[Path(p) for p in record.get('references',[])])


def merge(folder):
    manifest, script = locked(folder)
    video_campaign.require_approved_segments(folder, manifest)
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    filters, concat, assembly_inputs = [], '', []
    for index, shot in enumerate(script['shots']):
        record = read(folder/f"{shot['shot_id']}.json")
        if record['status'] != 'downloaded' or sha(Path(record['local_video'])) != record['video_sha256']:
            raise ValueError('Every shot must have a verified downloaded candidate')
        asset = video_campaign.delivery_asset(folder, manifest, shot['shot_id'])
        assembly_inputs.append(dict(asset, shot=shot['shot_id']))
        args += ['-i', asset['video']]
        filters += [f'[{index}:v]setpts=PTS-STARTPTS,fps=30,setsar=1[v{index}]',
                    f'[{index}:a]asetpts=PTS-STARTPTS,aresample=48000[a{index}]']
        concat += f'[v{index}][a{index}]'
    filters += [concat+f"concat=n={len(script['shots'])}:v=1:a=1[v][a]"]
    output = folder/'short_45s_candidate.mp4'
    args += ['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]',
             '-c:v','libx264','-crf','18','-preset','fast','-c:a','aac','-b:a','192k',
             '-movflags','+faststart',str(output)]
    subprocess.run(args,check=True,capture_output=True)
    media = probe(output)
    write(folder/'merged_probe.json', media)
    manifest.update(status='candidate_ready', merged_video=str(output), probe=str(folder/'merged_probe.json'),
        completed_at=now(), final_sha256=sha(output), review_result='awaiting_human_review', assembly_inputs=assembly_inputs,
        audio_note='保留各镜头模型原生音轨，未另配旁白；合并未裁剪台词或用静帧补时。')
    write(folder/'production.json',manifest)
    return {'status':'candidate_ready','video':str(output),'duration':media['format']['duration']}


def review_packet(folder, shot_id=None, video_path=None):
    """Explicitly prepare local inspection evidence; generation never calls this."""
    manifest, script = locked(folder)
    if shot_id and video_path:
        raise ValueError('Choose a shot or a derivative preview, not both')
    if video_path:
        video = Path(video_path).resolve()
        if not video.is_relative_to(folder) or not video.is_file():
            raise ValueError('Review preview must be an existing video inside this run')
        audit_path = video.with_suffix('.json')
        if not audit_path.is_file():
            raise ValueError('Review preview requires its saved technical receipt')
        audit = read(audit_path)
        expected_video = Path(audit.get('video', '')).resolve()
        expected_hash = audit.get('video_sha256')
        script_hash = audit.get('script_sha256') or audit.get('source_script_sha256')
        if (expected_video != video or expected_hash != sha(video)
                or script_hash != manifest['script_sha256']):
            raise ValueError('Review preview or its script binding changed')
        packet = build_review_packet(
            folder, video, expected_hash, manifest['script_sha256'], audit.get('cuts') or [],
        )
        audit['review_packet'] = str(packet)
        write(audit_path, audit)
    elif shot_id:
        if shot_id not in manifest['shots']:
            raise ValueError('Unknown shot in review request')
        receipt = folder/f'{shot_id}.json'
        record = read(receipt)
        if record.get('status') != 'downloaded':
            raise ValueError('Download the shot before extracting review evidence')
        packet = build_review_packet(folder, Path(record['local_video']), record['video_sha256'], manifest['script_sha256'])
        record['review_packet'] = str(packet)
        write(receipt, record)
    else:
        video = Path(manifest.get('merged_video', ''))
        if not video.is_file() or not manifest.get('final_sha256'):
            raise ValueError('Merge the video before extracting cut inspection evidence')
        cuts, offset = [], 0.
        for i, shot in enumerate(script['shots']):
            if i:
                cuts.append({'time': round(offset, 6), 'from': script['shots'][i-1]['shot_id'], 'to': shot['shot_id']})
            record = read(folder/f"{shot['shot_id']}.json")
            if sha(Path(record['local_video'])) != record['video_sha256']:
                raise ValueError('Shot changed since assembly')
            asset = video_campaign.delivery_asset(folder, manifest, shot['shot_id'])
            assembled = next((s for s in manifest.get('assembly_inputs', []) if s['shot'] == shot['shot_id']), None)
            if assembled and assembled['video_sha256'] != asset['video_sha256']:
                raise ValueError('Selected delivery changed since assembly')
            offset += asset['actual_duration_seconds']
        packet = build_review_packet(folder, video, manifest['final_sha256'], manifest['script_sha256'], cuts)
        manifest['merged_review_packet'] = str(packet)
        write(folder/'production.json', manifest)
    return {'review_packet': str(packet), 'extraction_only': True, 'video_generation_submitted': False}


def review_reference(folder, shot_id, review_path):
    manifest, _ = locked(folder)
    record=read(folder/f'{shot_id}.json')
    if record['status']!='downloaded' or sha(Path(record['local_video'])) != record['video_sha256']:
        raise ValueError('Reference must be a verified downloaded candidate')
    review=read(review_path)
    if (set(review.get('checks',{})) != set(CHECKS)
            or any(type(v) is not bool for v in review['checks'].values())
            or not review.get('notes') or not review.get('evidence')):
        raise ValueError('Reference review must contain all checks, concrete notes and evidence')
    for evidence in review['evidence']:
        path=(folder/evidence).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('Reference review evidence must exist in this run')
    review.update(asset_sha256=record['video_sha256'],direction_sha256=manifest['direction_sha256'],
                  reviewed_at=now(),status='passed' if all(review['checks'].values()) else 'failed')
    directory=folder/'reference_reviews';directory.mkdir(exist_ok=True)
    write(directory/f"{record['video_sha256']}.json",review)
    return {'shot':shot_id,'reference_review':review['status']}


def pace_preview(folder, head_speed=1.5):
    """Speed up only pre-dialogue motion; retain full content and normal speech."""
    if not 1 < head_speed <= 2:
        raise ValueError('Preview motion speed must be greater than 1 and at most 2')
    manifest, script=locked(folder)
    output=folder/'pacing_preview.mp4'
    audit_path=folder/'pacing_preview.json'
    if output.exists() or audit_path.exists():
        raise ValueError('Pacing preview already exists; preserve its review history')
    args=['ffmpeg','-hide_banner','-loglevel','error','-n']
    filters, concat, edits=[], '', []
    for i,shot in enumerate(script['shots']):
        n=shot['shot_id'];record=read(folder/f'{n}.json')
        if record['status']!='downloaded' or sha(folder/f'{n}.mp4') != record['video_sha256']:
            raise ValueError('Preview requires unchanged downloaded clips')
        result=read(folder/f'{n}.transcript.json')['result']
        timestamps=[t for row in result for t in row.get('timestamp',[])]
        if not timestamps:
            raise ValueError('Missing speech timings; do not guess or speed up dialogue')
        head=max(0,min(t[0] for t in timestamps)/1000-0.2)
        if head<=0:
            raise ValueError('No confirmed pre-dialogue interval for this shot')
        args+=['-i',str(folder/f'{n}.mp4')]
        filters += [f'[{i}:v]split=2[hv{i}][bv{i}]',f'[{i}:a]asplit=2[ha{i}][ba{i}]',
            f'[hv{i}]trim=end={head},setpts=(PTS-STARTPTS)/{head_speed},fps=30,setsar=1[xv{i}]',
            f'[ha{i}]atrim=end={head},asetpts=PTS-STARTPTS,atempo={head_speed},aresample=48000[xa{i}]',
            f'[bv{i}]trim=start={head},setpts=PTS-STARTPTS,fps=30,setsar=1[yv{i}]',
            f'[ba{i}]atrim=start={head},asetpts=PTS-STARTPTS,aresample=48000[ya{i}]']
        concat+=f'[xv{i}][xa{i}][yv{i}][ya{i}]'
        edits.append({'shot':n,'source_sha256':record['video_sha256'],'pre_dialogue_end':head,
                      'pre_dialogue_speed':head_speed,'dialogue_speed':1.0,'content_trimmed':False})
    filters += [concat+f"concat=n={2*len(script['shots'])}:v=1:a=1[v][a]"]
    args+=['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264',
           '-crf','18','-preset','fast','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
    subprocess.run(args,check=True,capture_output=True)
    media=probe(output)
    write(folder/'pacing_preview.probe.json',media)
    report={'schema':'script_video_pacing_preview/v1','created_at':now(),
            'video':str(output),'preview_only':True,'video_generation_submitted':False,
            'source_script_sha256':manifest['script_sha256'],'edits':edits,
            'actual_duration_seconds':float(media['format']['duration']),
            'unresolved':['原始视频的座位与机位偏差仍存在','原生字幕错误仍存在'],
            'video_sha256':sha(output)}
    mark_saved_candidate(report)
    report['review_status'] = report['content_status']
    write(audit_path,report)
    manifest['pacing_preview']=str(output)
    manifest['pacing_preview_note']='仅开口前动作段加速1.5倍，对白保持原速；保留原有空间与字幕偏差，用于比较动作节奏。'
    write(folder/'production.json',manifest)
    return {'preview':str(output),'duration':media['format']['duration'],'layout_fixed':False,
            'status':report['content_status']}


def speed_preview(folder, shot_id, speed, authorization):
    """Render a separate, pitch-preserving A/V preview without approving the source."""
    folder = Path(folder).resolve()
    if not math.isfinite(speed) or not 1 < speed <= 1.25:
        raise ValueError('Preview speed must be greater than 1 and at most 1.25')
    if not authorization or not authorization.strip():
        raise ValueError('Record the user pacing request in --authorization')
    manifest, _ = locked(folder)
    if shot_id not in manifest['shots']:
        raise ValueError('Shot must be present in the locked run')
    record = read(folder/f'{shot_id}.json')
    source = Path(record['local_video']).resolve()
    if (record['status'] != 'downloaded' or not source.is_relative_to(folder)
            or sha(source) != record['video_sha256']):
        raise ValueError('Preview requires an unchanged downloaded source inside this run')
    factor = str(float(speed))
    output = folder/f"{shot_id}.speed_{factor.replace('.', 'p')}.mp4"
    audit_path = output.with_suffix('.json')
    if audit_path.exists():
        report = read(audit_path)
        if (report['source_sha256'] != record['video_sha256']
                or report['script_sha256'] != manifest['script_sha256']
                or report['speed'] != speed or sha(output) != report['video_sha256']):
            raise ValueError('Existing preview changed; inspect instead of overwriting')
    else:
        if output.exists():
            raise ValueError('Untracked preview already exists; inspect instead of overwriting')
        before = probe(source)
        if not any(s['codec_type'] == 'audio' for s in before['streams']):
            raise ValueError('Synchronized speech preview requires an audio stream')
        video_filter = f'settb=AVTB,setpts=(PTS-STARTPTS)/{factor}'
        audio_filter = f'asetpts=PTS-STARTPTS,atempo={factor}'
        # Keep every video frame; use fine timestamps so modest speed changes do
        # not drop the last frame or accumulate audio/video rounding drift.
        subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-n', '-i', str(source),
            '-map', '0:v:0', '-map', '0:a:0', '-vf', video_filter, '-af', audio_filter,
            '-fps_mode', 'vfr', '-enc_time_base:v', '1:24000', '-c:v', 'libx264',
            '-crf', '18', '-preset', 'fast', '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', str(output)], check=True, capture_output=True)
        after = probe(output)
        source_duration = float(before['format']['duration'])
        duration = float(after['format']['duration'])
        source_frames = next(s['nb_frames'] for s in before['streams'] if s['codec_type'] == 'video')
        output_frames = next(s['nb_frames'] for s in after['streams'] if s['codec_type'] == 'video')
        if source_frames != output_frames or abs(duration-source_duration/speed) > .1:
            raise ValueError('Unexpected frame loss or duration; inspect the untracked preview')
        if sha(source) != record['video_sha256']:
            raise ValueError('Source changed during rendering')
        report = {'schema': 'script_video_speed_preview/v1', 'created_at': now(),
            'authorization': authorization, 'shot': shot_id, 'source_video': str(source),
            'source_sha256': record['video_sha256'], 'script_sha256': manifest['script_sha256'],
            'video': str(output), 'video_sha256': sha(output), 'speed': speed,
            'source_duration_seconds': source_duration, 'actual_duration_seconds': duration,
            'video_frame_count': int(output_frames), 'video_filter': video_filter,
            'audio_filter': audio_filter, 'content_trimmed': False,
            'preview_only': True,
            'video_generation_submitted': False, 'external_audio_uploaded': False,
            'continuation_frame': record.get('last_frame'),
            'continuation_frame_sha256': record.get('last_frame_sha256'),
            'continuation_note': '原片仍须审核通过；后续生成使用平台原始尾帧，不上传此变速预览。'}
        write(output.with_suffix('.probe.json'), after)
        mark_saved_candidate(report)
        report['review_status'] = report['content_status']
        write(audit_path, report)
    previews = manifest.setdefault('speed_previews', {}).setdefault(shot_id, {})
    previews[factor] = str(audit_path)
    manifest['latest_speed_preview'] = str(output)
    # Rendering does not change raw receipt hashes, campaign decisions or merge inputs.
    write(folder/'production.json', manifest)
    return {'preview': str(output), 'speed': speed,
            'duration': report['actual_duration_seconds'],
            'status': report['content_status'], 'video_generation_submitted': False}


def assembly_speed_preview(folder, speed, authorization, edit_plan_path=None):
    """User-requested edit preview; pending reviews are retained, never approved."""
    folder = Path(folder).resolve()
    if not math.isfinite(speed) or not 1 < speed <= 1.25:
        raise ValueError('Assembly preview speed must be greater than 1 and at most 1.25')
    if not authorization or not authorization.strip():
        raise ValueError('Record the user request for the whole-video preview')
    manifest, script = locked(folder)
    plan, baseline, edits = None, None, {}
    if edit_plan_path:
        edit_plan_path = Path(edit_plan_path).resolve()
        if not edit_plan_path.is_relative_to(folder):
            raise ValueError('Edit plan must be inside this run')
        plan = read(edit_plan_path)
        if plan.get('schema') != 'script_video_rhythm_plan/v1':
            raise ValueError('Unsupported rhythm edit plan')
        if not plan.get('description'):
            raise ValueError('Describe the requested rhythm changes')
        label = plan.get('output_label', '')
        if not re.fullmatch(r'[a-z0-9_]+', label):
            raise ValueError('Use a simple unique output label')
        baseline_path = Path(plan['baseline_report']).resolve()
        if not baseline_path.is_relative_to(folder) or sha(baseline_path) != plan['baseline_report_sha256']:
            raise ValueError('Baseline report changed or is outside this run')
        baseline = read(baseline_path)
        if baseline.get('schema') != 'script_video_assembly_speed_preview/v1':
            raise ValueError('Use a registered whole-speed preview as the rhythm baseline')
        baseline_video = Path(baseline['video']).resolve()
        if (not baseline_video.is_relative_to(folder) or sha(baseline_video) != baseline['video_sha256']
                or baseline['script_sha256'] != manifest['script_sha256']):
            raise ValueError('Baseline video or script changed')
        edits = plan['edits']
        if not edits or set(edits) - {s['shot_id'] for s in script['shots']}:
            raise ValueError('Edit plan contains no edits or unknown shots')
        output = folder/f'whole_video.{label}.mp4'
    else:
        output = folder/f"whole_video.speed_{str(float(speed)).replace('.', 'p')}.mp4"
    if output.exists() or output.with_suffix('.json').exists():
        raise ValueError('Whole-video preview already exists; inspect instead of overwriting')
    args = ['ffmpeg','-hide_banner','-loglevel','verbose','-n']
    inputs, filters, concat, frame_count = [], [], '', 0
    campaign = read(Path(manifest['campaign_path'])) if manifest.get('campaign_path') else None
    for i, shot in enumerate(script['shots']):
        sid = shot['shot_id']; record = read(folder/f'{sid}.json')
        if record['status'] != 'downloaded' or sha(Path(record['local_video'])) != record['video_sha256']:
            raise ValueError('Whole-video preview requires unchanged downloaded clips')
        pending = manifest.get('pending_delivery_review', {})
        if campaign:
            attempts = [a for a in campaign['attempts'] if a['shot']==sid]
            current = attempts[-1] if attempts else {}
            if (current.get('video_sha256') != record['video_sha256']
                    or current.get('status') not in {'passed','awaiting_review'}):
                raise ValueError('Do not assemble an unreviewed or failed generated candidate')
        if pending.get('shot') == sid and pending.get('status') == 'pending':
            asset = video_campaign.preview_asset(folder, manifest, record, pending['audit'])
            if asset['video_sha256'] != pending['video_sha256']:
                raise ValueError('Pending delivery changed')
            review = read(Path(pending['review']))
            if (review['source_sha256'] != asset['video_sha256']
                    or any(v is False for v in review['checks'].values())):
                raise ValueError('Resolve a rejected delivery before making an assembly preview')
            asset['review_status'] = 'pending'
        else:
            if campaign and current['status'] != 'passed':
                raise ValueError('A pending segment needs an explicitly registered edit preview')
            asset = video_campaign.delivery_asset(folder, manifest, sid)
            asset['review_status'] = 'passed' if campaign else 'pending'
        video = Path(asset['video']); media = probe(video)
        rate, end = speed, None
        edit = edits.get(sid, {})
        if baseline:
            previous = next((a for a in baseline['inputs'] if a['shot']==sid), None)
            if not previous or previous['video_sha256'] != asset['video_sha256']:
                raise ValueError('Selected delivery changed since the baseline preview')
            rate = previous['additional_speed']
        if edit:
            if set(edit) - {'video_sha256','reason','additional_speed','keep_end_seconds','tail_review','tail_review_sha256'}:
                raise ValueError('Unsupported rhythm edit field')
            if edit.get('video_sha256') != asset['video_sha256'] or not edit.get('reason'):
                raise ValueError('Bind each edit to its source and record the reason')
            rate = float(edit.get('additional_speed', rate))
            if not math.isfinite(rate) or not .8 <= rate <= 1.25:
                raise ValueError('Per-shot preview rate must be between 0.8 and 1.25')
            if 'keep_end_seconds' in edit:
                end = float(edit['keep_end_seconds'])
                evidence_path = (folder/edit['tail_review']).resolve()
                if (not evidence_path.is_relative_to(folder)
                        or sha(evidence_path) != edit['tail_review_sha256']):
                    raise ValueError('Tail review evidence changed or is outside this run')
                evidence = read(evidence_path)
                speech_end = float(evidence['speech_end_seconds'])
                if (evidence['source_sha256'] != asset['video_sha256']
                        or evidence.get('visual_tail_checked') is not True
                        or evidence.get('speech_end_method') != 'local_audio_energy_and_asr'
                        or not math.isfinite(speech_end) or speech_end < 0
                        or not speech_end + .15 <= end < float(media['format']['duration'])):
                    raise ValueError('Tail edit must retain speech plus a 150 ms margin and have visual evidence')
        source_frames = int(next(s['nb_frames'] for s in media['streams'] if s['codec_type']=='video'))
        kept_frames = source_frames
        if end is not None:
            timestamps = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
                '-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(video)]))
            kept_frames = sum(float(f['best_effort_timestamp_time']) < end for f in timestamps['frames'])
        frame_count += kept_frames
        inputs.append(dict(asset, shot=sid, additional_speed=rate, total_speed=asset['speed']*rate,
            keep_end_seconds=end, source_frame_count=source_frames, retained_frame_count=kept_frames))
        args += ['-i', str(video)]
        vtrim = f'trim=end={end},' if end is not None else ''
        atrim = f'atrim=end={end},' if end is not None else ''
        filters += [f'[{i}:v]{vtrim}settb=AVTB,setpts=(PTS-STARTPTS)/{rate},setsar=1[v{i}]',
                    f'[{i}:a]{atrim}asetpts=PTS-STARTPTS,atempo={rate},aresample=48000[a{i}]']
        concat += f'[v{i}][a{i}]'
    filters.append(concat+f"concat=n={len(inputs)}:v=1:a=1[v][a]")
    args += ['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]',
        '-fps_mode','vfr','-enc_time_base:v','1:24000','-c:v','libx264','-crf','18',
        '-preset','fast','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
    result = subprocess.run(args, check=True, capture_output=True)
    log = result.stderr.decode('utf-8', errors='replace')
    output.with_suffix('.render.log').write_text(log, encoding='utf-8')
    # The concat filter reports actual segment end timestamps in microseconds;
    # atempo and AAC rounding make original duration / speed only an estimate.
    ends = [int(x)/1_000_000 for x in re.findall(r'Segment finished at pts=(\d+)', log)]
    if len(ends) != len(inputs) or ends != sorted(ends):
        raise ValueError('Missing actual cut timestamps; inspect the render log')
    media = probe(output)
    frames = int(next(s['nb_frames'] for s in media['streams'] if s['codec_type']=='video'))
    if frames != frame_count:
        raise ValueError('Frame count changed during preview assembly; inspect before review')
    cuts = [{'time':ends[i-1],'from':inputs[i-1]['shot'],'to':inputs[i]['shot']} for i in range(1,len(inputs))]
    report = {'schema':'script_video_assembly_speed_preview/v1','created_at':now(),
        'authorization':authorization,'video':str(output),'video_sha256':sha(output),
        'script_sha256':manifest['script_sha256'],'additional_speed':speed,
        'inputs':inputs,'cuts':cuts,'duration_seconds':float(media['format']['duration']),
        'video_frames_preserved':frame_count,'preview_only':True,
        'video_generation_submitted':False,'external_audio_uploaded':False,
        'review_note':'用户要求整体提速的本地预览；原逐段审核不变，未检查项不自动通过。'}
    if plan:
        report.update(schema='script_video_assembly_rhythm_preview/v1',
            edit_plan=str(edit_plan_path), edit_plan_sha256=sha(edit_plan_path),
            content_trimmed=any(a['keep_end_seconds'] is not None for a in inputs),
            baseline_video_sha256=baseline['video_sha256'], additional_speed=None,
            intentionally_removed_tail_frames=sum(a['source_frame_count']-a['retained_frame_count'] for a in inputs),
            review_note='按用户指定位置修剪静音停留并调整单段倍率；保留原逐段审核，声音仍待播放确认。')
    mark_saved_candidate(report)
    report['review_status'] = report['content_status']
    write(output.with_suffix('.probe.json'),media)
    write(output.with_suffix('.json'),report)
    manifest.update(pacing_preview=str(output),
        pacing_preview_note=f'整片在当前各段版本基础上再提速{(speed-1)*100:g}%，声画字幕同步，保留原审核状态，待整体播放确认。',
        latest_assembly_preview=str(output),assembly_preview_report=str(output.with_suffix('.json')))
    if plan:
        manifest['pacing_preview_note'] = plan['description']+'；声音待播放确认，原逐段审核不变。'
    write(folder/'production.json',manifest)
    return {'video':str(output),'duration':report['duration_seconds'],'cuts':cuts,
            'status':report['content_status'],'video_generation_submitted':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare','submit','preview','query','save-last-frame','bind-first-frame','retry-failed','retry-ark-configuration','merge','review-reference','review-packet','pace-preview','speed-preview','assembly-speed-preview','assembly-rhythm-preview','attach-campaign','resume-campaign','review-segment'])
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--script')
    parser.add_argument('--authorization')
    parser.add_argument('--shot')
    parser.add_argument('--speed', type=float, default=1.08, help='声画同步提速预览倍率（1 < 倍率 <= 1.25）')
    parser.add_argument('--edit-plan', help='绑定原预览及逐镜输入哈希的局部节奏编辑计划')
    parser.add_argument('--reference-video', action='append', default=[])
    parser.add_argument('--first-frame',help='已审核绑定到目标分镜的本地首帧图片')
    parser.add_argument('--execution-plan', help='显式 S01 compact_execution/v1 或 v2 计划，仅配合已审首帧')
    parser.add_argument('--execution-review', help='绑定本次执行计划与提示词 SHA 的独立文本审核')
    parser.add_argument('--direction-plan')
    parser.add_argument('--provider',choices=['dreamina_cli','ark_api'],default=settings.SEEDANCE_PROVIDER)
    parser.add_argument('--test-shot')
    parser.add_argument('--review-file')
    parser.add_argument('--video', help='Explicit derivative preview for review-packet extraction')
    parser.add_argument('--campaign', help='累计失败次数不随镜头或修订重置的 campaign.json')
    parser.add_argument('--additional-failed-outputs', type=int, default=1,
                        help='人工复核后增加的失败输出容限，限 1–3，默认仅 1')
    args = parser.parse_args()
    if (args.execution_plan or args.execution_review) and args.operation not in {'submit', 'preview'}:
        raise ValueError('Execution-plan opt-in is only supported by submit or preview')
    folder = Path(args.run_dir).resolve()
    if not folder.is_relative_to(ROOT/'data/video_generation'):
        raise ValueError('Run directory must be under project video_generation')
    if args.operation == 'prepare':
        if not args.authorization or not args.script:
            raise ValueError('Script and explicit generation authorization required')
        result=prepare(folder,Path(args.script).resolve(),args.authorization,
                       Path(args.direction_plan).resolve() if args.direction_plan else None,args.provider,args.test_shot)
    elif args.operation == 'merge':
        result=merge(folder)
    elif args.operation == 'review-packet':
        result=review_packet(folder,args.shot,args.video)
    elif args.operation == 'attach-campaign':
        if not args.campaign:
            raise ValueError('Provide --campaign')
        campaign_path = Path(args.campaign).resolve()
        if not campaign_path.is_relative_to(ROOT/'data/video_generation'):
            raise ValueError('Campaign must be inside project video_generation')
        video_campaign.attach(folder, campaign_path)
        result={'campaign':str(campaign_path), 'status':'attached'}
    elif args.operation == 'resume-campaign':
        if not args.authorization:
            raise ValueError('Provide the exact explicit user authorization')
        manifest = read(folder / 'production.json')
        campaign_value = manifest.get('campaign_path')
        if not isinstance(campaign_value, str) or not campaign_value:
            raise ValueError('Attach this prepared run to its campaign before human resume')
        campaign_path = Path(campaign_value).resolve()
        if not campaign_path.is_relative_to(ROOT/'data/video_generation'):
            raise ValueError('Campaign must be inside project video_generation')
        result = video_campaign.authorize_human_resume(campaign_path, folder,
            authorization=args.authorization,
            additional_failed_outputs=args.additional_failed_outputs)
    elif args.operation == 'review-segment':
        if not args.review_file or not args.shot:
            raise ValueError('Provide --shot and --review-file')
        result=video_campaign.review(folder,args.shot,Path(args.review_file))
    elif args.operation=='pace-preview':
        result=pace_preview(folder)
    elif args.operation=='speed-preview':
        result=speed_preview(folder,args.shot,args.speed,args.authorization)
    elif args.operation=='assembly-speed-preview':
        result=assembly_speed_preview(folder,args.speed,args.authorization)
    elif args.operation=='assembly-rhythm-preview':
        if not args.edit_plan:
            raise ValueError('Provide --edit-plan')
        result=assembly_speed_preview(folder,args.speed,args.authorization,args.edit_plan)
    elif args.operation=='review-reference':
        result=review_reference(folder,args.shot,Path(args.review_file))
    elif args.operation=='bind-first-frame':
        if not args.first_frame or not args.review_file:
            raise ValueError('Provide --first-frame and --review-file')
        manifest,_=locked(folder)
        if manifest.get('provider')!='ark_api' or not manifest.get('direction_plan'):
            raise ValueError('Frame bindings require an Ark run with a locked direction plan')
        binding=bind_frame(folder,args.shot,Path(args.first_frame),read(Path(args.review_file)),manifest,read(folder/'direction_plan.json'))
        result={'shot':args.shot,'first_frame':binding['image'],'status':'bound'}
    else:
        provider=read(folder/'production.json').get('provider','dreamina_cli')
        # Original Seedream image previews verify the configured credential fingerprint locally.
        original_image = bool(args.first_frame and (
            Path(args.first_frame).name == 'opening.original'
            or (Path(args.first_frame).parent / 'opening.ark_image.json').exists()))
        client=(SeedanceClient(SeedanceConfig.from_env('ark_api',require_key=args.operation!='preview' or original_image)) if provider=='ark_api'
                else DreaminaCLIClient(DreaminaCLIConfig.from_settings()))
        if args.operation in {'submit','preview'}:
            result=submit(folder,args.shot,client,[Path(p) for p in args.reference_video],
                          Path(args.first_frame) if args.first_frame else None,preview=args.operation=='preview',
                          execution_plan=Path(args.execution_plan) if args.execution_plan else None,
                          execution_review=Path(args.execution_review) if args.execution_review else None)
        elif args.operation=='save-last-frame':
            result=save_last_frame(folder,args.shot,client)
        elif args.operation=='retry-failed':
            result=retry_failed(folder,args.shot,client)
        elif args.operation=='retry-ark-configuration':
            result=retry_ark_configuration(folder,args.shot,client,args.authorization)
        else:
            result=query(folder,args.shot,client)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
