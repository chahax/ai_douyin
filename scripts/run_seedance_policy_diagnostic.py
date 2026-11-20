"""Run a bounded, one-variable Seedance policy diagnostic for an original project.

This does not alter campaign state or approve an output. It preserves every
request and response, stops at the first success, and never retries a policy
failure with an identical request.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_factory.seedance_client import SeedanceAPIError, SeedanceClient, SeedanceConfig, SeedanceReference
from src.content_factory.seedance_frames import image_info
from src.content_factory.video_provider_failure import classify_failure

VARIANTS = ('A_generic_identity', 'B_no_first_frame', 'AB_generic_identity_no_first_frame')
POLICY_CODE = 'OutputVideoSensitiveContentDetected.PolicyViolation'
APPEARANCE_MARKER = '\n所有重新入画人物沿用原稿外貌与服装：\n'
GENERIC_IDENTITY = ('\n父亲是本原创故事中的普通家庭成员，保持约六十岁的自然生活外观；'
                    '不模仿或指向任何现实人物、演员、影视角色或品牌形象。')
WARDROBE_IDENTITY = ('\n父亲是本系列同一位原创普通父亲：约六十岁，花白短发，'
                     '浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。'
                     '保持自然生活外观，不模仿或指向任何现实人物、演员、影视角色或品牌形象。'
                     '\n女儿不在本镜重新入画；只延续输入首帧，不新增人物。')
CAMERA_START = '摄影时间表（本段局部秒数，只规定观察与构图）：\n'
CAMERA_END = '\n人物动作时间表：'
EYELINE_CAMERA = (
    '0—0.35秒，保留输入首帧中的女儿等待画面。\n'
    '0.35—6秒，明确硬切到父亲头肩近景。父亲站在画面右半部，身体与鼻尖均朝画面左侧，'
    '视线落在画外左侧的女儿脸上；女儿保持画外。背景只见门内暖色空间与门框虚化，'
    '父亲眼睛和嘴清晰可读。机位固定，不推拉、不横移、不再次转场。')


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_prompt(record):
    items = [item.get('text') for item in record['request']['content'] if item.get('type') == 'text']
    if len(items) != 1 or not items[0]:
        raise ValueError('Original receipt must contain exactly one text prompt')
    return items[0]


def generic_prompt(original):
    if original.count(APPEARANCE_MARKER) != 1:
        raise ValueError('Cannot isolate the reviewed appearance block')
    return original.split(APPEARANCE_MARKER, 1)[0].rstrip() + GENERIC_IDENTITY


def wardrobe_prompt(original):
    if original.count(APPEARANCE_MARKER) != 1:
        raise ValueError('Cannot isolate the reviewed appearance block')
    return original.split(APPEARANCE_MARKER, 1)[0].rstrip() + WARDROBE_IDENTITY


def eyeline_prompt(original):
    prompt = wardrobe_prompt(original)
    if prompt.count(CAMERA_START) != 1 or prompt.count(CAMERA_END) != 1:
        raise ValueError('Cannot isolate the camera schedule')
    before, remainder = prompt.split(CAMERA_START, 1)
    _, after = remainder.split(CAMERA_END, 1)
    return before + CAMERA_START + EYELINE_CAMERA + CAMERA_END + after


def _data_reference(frame, role='first_frame'):
    info = image_info(frame)
    encoded = base64.b64encode(Path(frame).read_bytes()).decode('ascii')
    return SeedanceReference('image', f"data:{info['mime']};base64,{encoded}", role)


def initialize(output, failed_receipt, first_frame, authorization):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Diagnostic directory already exists')
    failed_receipt, first_frame = Path(failed_receipt).resolve(), Path(first_frame).resolve()
    record = read(failed_receipt)
    error = (record.get('latest_response') or {}).get('error') or {}
    if record.get('status') != 'failed' or error.get('code') != POLICY_CODE:
        raise ValueError('This diagnostic requires the exact terminal output-video copyright receipt')
    if not authorization.strip():
        raise ValueError('Explicit user diagnostic authorization is required')
    original = text_prompt(record)
    generic = generic_prompt(original)
    config = SeedanceConfig.from_env('ark_api', require_key=False)
    if config.model != 'doubao-seedance-2-0-mini-260615':
        raise ValueError('The bounded diagnostic requires the configured Mini model')
    output.mkdir(parents=True)
    plan = {
        'schema': 'seedance_policy_diagnostic/v1',
        'created_at': now(), 'authorization': authorization,
        'source_failure': {'path': str(failed_receipt), 'sha256': sha(failed_receipt),
                           'task_id': record['submit_id'], 'error_code': POLICY_CODE},
        'first_frame': {'path': str(first_frame), **image_info(first_frame)},
        'model': config.model, 'resolution': '480p', 'ratio': '9:16',
        'duration': record['request']['duration'], 'generate_audio': record['request']['generate_audio'],
        'method': 'sequential_single_variable_then_combined',
        'stop_on_first_success': True,
        'variants': [
            {'id': VARIANTS[0], 'prompt': generic, 'use_first_frame': True,
             'changed_factors': ['replace_specific_character_appearance_with_generic_original_identity']},
            {'id': VARIANTS[1], 'prompt': original, 'use_first_frame': False,
             'changed_factors': ['remove_first_frame_reference']},
            {'id': VARIANTS[2], 'prompt': generic, 'use_first_frame': False,
             'changed_factors': ['replace_specific_character_appearance_with_generic_original_identity',
                                 'remove_first_frame_reference']},
        ],
        'status': 'ready', 'next_variant': VARIANTS[0], 'attempts': [],
        'interpretation_limits': [
            'A success suggests the detailed identity block contributed, but does not prove infringement.',
            'B success suggests the first-frame-conditioned generation contributed, but does not prove the frame is infringing.',
            'AB-only success suggests an interaction; generation randomness remains a confounder.',
            'A successful diagnostic output is not a production approval and still requires frame review.',
        ],
    }
    write(output / 'plan.json', plan)
    return plan


def _eligible(plan):
    if any(row['status'] == 'succeeded' for row in plan['attempts']):
        refinement = next((row for row in plan['variants']
            if row['id'] == plan.get('next_variant')
            and row['id'] in {'A2_wardrobe_identity','A3_wardrobe_left_eyeline','S04_continuation',
                             'S03_identity_reentry_r1','S03_identity_reentry_text_r2',
                             'S03_identity_multiref_r3','S01_identity_safe_chain',
                             'S02_identity_safe_chain','S02_identity_safe_chain_r2',
                             'S03_identity_safe_chain','S04_identity_safe_chain',
                             'S04_identity_safe_chain_r2','S04_identity_safe_chain_r3',
                             'S04_identity_safe_chain_r4'}), None)
        if (plan.get('status') == 'ready' and refinement
                and not any(a['variant'] == refinement['id'] for a in plan['attempts'])):
            return refinement
        return None
    if plan['attempts'] and plan['attempts'][-1]['status'] not in {'failed', 'cancelled', 'expired'}:
        raise ValueError('Previous diagnostic request is unresolved; query it instead of submitting')
    if plan['attempts']:
        error = (plan['attempts'][-1].get('response') or {}).get('error') or {}
        if error.get('code') != POLICY_CODE:
            raise ValueError('Previous result differs from the target policy error; stop and inspect')
    used = {row['variant'] for row in plan['attempts']}
    return next((row for row in plan['variants'] if row['id'] not in used), None)


def submit_next(output):
    output = Path(output).resolve(); plan_path = output / 'plan.json'; plan = read(plan_path)
    if sha(plan['source_failure']['path']) != plan['source_failure']['sha256']:
        raise ValueError('Source failure receipt changed')
    variant = _eligible(plan)
    if variant is None:
        plan['status'] = 'stopped_after_success' if any(a['status'] == 'succeeded' for a in plan['attempts']) else 'exhausted'
        plan['next_variant'] = None; write(plan_path, plan); return {'status': plan['status']}
    frame_binding = variant.get('first_frame') or plan['first_frame']
    frame = Path(frame_binding['path'])
    if sha(frame) != frame_binding['sha256']:
        raise ValueError('Diagnostic first frame changed')
    if variant.get('reference_images'):
        refs=[]
        for binding in variant['reference_images']:
            reference=Path(binding['path'])
            if sha(reference)!=binding['sha256']:
                raise ValueError('Diagnostic reference image changed')
            refs.append(_data_reference(reference,'reference_image'))
    else:
        refs = [_data_reference(frame)] if variant['use_first_frame'] else []
    config = SeedanceConfig.from_env('ark_api')
    if config.model != plan['model']:
        raise ValueError('Configured model changed')
    with SeedanceClient(config) as client:
        payload = client.build_task_payload(variant['prompt'], duration=variant.get('duration', plan['duration']),
            references=refs, resolution=plan['resolution'], ratio=plan['ratio'],
            generate_audio=plan['generate_audio'], return_last_frame=True)
        preview = output / f"{variant['id']}.request.json"; write(preview, payload)
        attempt = {'variant': variant['id'], 'status': 'submission_unknown', 'created_at': now(),
                   'changed_factors': variant['changed_factors'], 'request_path': str(preview),
                   'request_sha256': sha(preview)}
        plan['attempts'].append(attempt); plan['status'] = 'submitting'; plan['next_variant'] = variant['id']; write(plan_path, plan)
        try:
            response = client.create_task(payload)
        except SeedanceAPIError as exc:
            response={'status':'failed','error':{
                'code':exc.error_code or f'HTTP_{exc.status_code or "unknown"}',
                'message':str(exc)}}
            attempt.update(status='failed',checked_at=now(),response=response)
            failure=classify_failure(response)
            failure_path=output/f"{variant['id']}.provider_failure.json"
            write(failure_path,failure)
            attempt['failure_record']=str(failure_path)
            plan.update(status='stopped_for_inspection',next_variant=None)
            write(plan_path,plan)
            raise
    attempt.update(status='submitted', task_id=response['id'], submitted_at=now(), response=response)
    plan['status'] = 'running'; write(plan_path, plan)
    return {'variant': variant['id'], 'status': 'submitted', 'task_id': response['id']}


def query_current(output):
    output = Path(output).resolve(); plan_path = output / 'plan.json'; plan = read(plan_path)
    if not plan['attempts']:
        raise ValueError('No diagnostic request has been submitted')
    attempt = plan['attempts'][-1]
    if attempt['status'] in {'failed', 'cancelled', 'expired', 'succeeded'}:
        return {'variant': attempt['variant'], 'status': attempt['status']}
    config = SeedanceConfig.from_env('ark_api')
    with SeedanceClient(config) as client:
        response = client.get_task(attempt['task_id'])
        attempt.update(status=response['status'], checked_at=now(), response=response)
        if response['status'] == 'succeeded':
            video = client.download_video(response, output / f"{attempt['variant']}.mp4")
            attempt.update(video=str(video), video_sha256=sha(video))
            try:
                tail = client.download_last_frame(response, output / f"{attempt['variant']}.last_frame.png")
                attempt.update(last_frame=str(tail), last_frame_sha256=sha(tail))
            except Exception as exc:
                attempt['last_frame_download_error'] = type(exc).__name__
            plan.update(status='stopped_after_success', next_variant=None)
        elif response['status'] in {'failed', 'cancelled', 'expired'}:
            failure = classify_failure(response)
            write(output / f"{attempt['variant']}.provider_failure.json", failure)
            attempt['failure_record'] = str(output / f"{attempt['variant']}.provider_failure.json")
            remaining = [row['id'] for row in plan['variants'] if row['id'] not in {a['variant'] for a in plan['attempts']}]
            plan.update(status='ready' if remaining and (response.get('error') or {}).get('code') == POLICY_CODE else 'stopped_for_inspection',
                        next_variant=remaining[0] if remaining else None)
        else:
            plan['status'] = response['status']
    write(plan_path, plan)
    return {'variant': attempt['variant'], 'status': attempt['status'], 'task_id': attempt['task_id']}


def add_identity_refinement(output, review_path):
    output = Path(output).resolve(); plan_path = output/'plan.json'; plan = read(plan_path)
    review_path = Path(review_path).resolve(); review = read(review_path)
    last = plan['attempts'][-1] if plan['attempts'] else None
    if (plan.get('status') != 'stopped_after_success' or not last
            or last.get('variant') != VARIANTS[0] or last.get('status') != 'succeeded'
            or review.get('schema') != 'policy_diagnostic_visual_review/v1'
            or review.get('variant') != last['variant']
            or review.get('source_sha256') != last.get('video_sha256')
            or review.get('decision') != 'failed' or review.get('checks', {}).get('identity') is not False):
        raise ValueError('Identity refinement requires the first successful diagnostic to fail actual identity review')
    source = read(plan['source_failure']['path']); original = text_prompt(source)
    variant = {'id': 'A2_wardrobe_identity', 'prompt': wardrobe_prompt(original), 'use_first_frame': True,
               'changed_factors': ['replace_specific_face_description_while_retaining_reviewed_hair_and_wardrobe'],
               'review_path': str(review_path), 'review_sha256': sha(review_path)}
    if any(row['id'] == variant['id'] for row in plan['variants']):
        if not any(a['variant'] == variant['id'] for a in plan['attempts']):
            plan.update(status='ready', next_variant=variant['id'], refinement_reason='provider_passed_but_identity_failed')
            write(plan_path, plan)
            return {'status':'ready','next_variant':variant['id']}
        raise ValueError('Identity refinement already exists')
    # A passed the provider check, so B/AB are no longer needed. Keep them as
    # planned history but insert the production-suitability refinement next.
    plan['variants'].insert(1, variant)
    plan.update(status='ready', next_variant=variant['id'], refinement_reason='provider_passed_but_identity_failed')
    write(plan_path, plan)
    return {'status':'ready','next_variant':variant['id']}


def add_eyeline_refinement(output, review_path):
    output=Path(output).resolve(); plan_path=output/'plan.json'; plan=read(plan_path)
    review_path=Path(review_path).resolve(); review=read(review_path)
    last=plan['attempts'][-1] if plan['attempts'] else None
    if (plan.get('status')!='stopped_after_success' or not last
            or last.get('variant')!='A2_wardrobe_identity' or last.get('status')!='succeeded'
            or review.get('schema')!='policy_diagnostic_visual_review/v1'
            or review.get('variant')!=last['variant'] or review.get('source_sha256')!=last.get('video_sha256')
            or review.get('decision')!='failed' or review.get('checks',{}).get('spatial_layout') is not False):
        raise ValueError('Eyeline refinement requires the wardrobe variant to fail actual spatial review')
    original=text_prompt(read(plan['source_failure']['path']))
    variant={'id':'A3_wardrobe_left_eyeline','prompt':eyeline_prompt(original),'use_first_frame':True,
             'changed_factors':['retain_generic_face_and_reviewed_wardrobe','replace_camera_schedule_with_reciprocal_screen_left_eyeline'],
             'review_path':str(review_path),'review_sha256':sha(review_path)}
    if any(v['id']==variant['id'] for v in plan['variants']):
        if not any(a['variant']==variant['id'] for a in plan['attempts']):
            plan.update(status='ready',next_variant=variant['id'],refinement_reason='provider_passed_but_spatial_layout_failed')
            write(plan_path,plan); return {'status':'ready','next_variant':variant['id']}
        raise ValueError('Eyeline refinement already exists')
    insert_at=next(i for i,v in enumerate(plan['variants']) if v['id']=='A2_wardrobe_identity')+1
    plan['variants'].insert(insert_at,variant)
    plan.update(status='ready',next_variant=variant['id'],refinement_reason='provider_passed_but_spatial_layout_failed')
    write(plan_path,plan); return {'status':'ready','next_variant':variant['id']}


def add_s04_continuation(output, review_path, script_path):
    output=Path(output).resolve(); plan_path=output/'plan.json'; plan=read(plan_path)
    review_path=Path(review_path).resolve(); review=read(review_path)
    script_path=Path(script_path).resolve(); script=read(script_path)
    last=plan['attempts'][-1] if plan['attempts'] else None
    if (plan.get('status')!='stopped_after_success' or not last
            or last.get('variant')!='A3_wardrobe_left_eyeline' or last.get('status')!='succeeded'
            or review.get('variant')!=last['variant'] or review.get('source_sha256')!=last.get('video_sha256')
            or review.get('decision')!='visual_passed_audio_pending'
            or any(review.get('checks',{}).get(k) is not True for k in
                   ('identity','spatial_layout','props_and_hands','action_pace','cut_continuity','visual_storytelling'))
            or any(review.get('checks',{}).get(k) is not None for k in ('dialogue_pace','speaker_voice','lip_sync'))):
        raise ValueError('S04 requires the actual visual pass of A3 with audio checks still pending')
    tail=Path(last['last_frame']).resolve()
    if sha(tail)!=last.get('last_frame_sha256') or review.get('original_tail_sha256')!=last.get('last_frame_sha256'):
        raise ValueError('A3 original provider tail changed')
    shots=[s for s in script.get('shots',[]) if s.get('shot_id')=='S04']
    if len(shots)!=1 or script.get('schema')!='reference_director_video_script/v1':
        raise ValueError('Reviewed S04 source is required')
    prompt=shots[0]['model_prompt_zh'].replace(
        '随女儿进入轻微随她转向，始终朝两人之间开阔空间，禁止面壁。',
        '随女儿进入轻微转向，始终正面朝向刚进入的女儿，视线落在女儿脸上。')
    prompt += ('\n人物只沿用本系列当前原创造型：\n'
        '父亲：约六十岁，花白短发，浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。\n'
        '女儿：齐肩黑色直发，浅米色针织长衫，浅蓝牛仔裤。\n'
        '只固定发型与服装，不模仿或指向现实人物、演员、影视角色或品牌形象。')
    variant={'id':'S04_continuation','prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(tail),**image_info(tail)},
             'duration':4,
             'changed_factors':['continue_from_A3_original_tail','positive_father_facing_direction','generic_original_wardrobe_lock'],
             'review_path':str(review_path),'review_sha256':sha(review_path),'script_path':str(script_path),'script_sha256':sha(script_path)}
    if any(v['id']==variant['id'] for v in plan['variants']): raise ValueError('S04 continuation already exists')
    plan['variants'].append(variant);plan.update(status='ready',next_variant=variant['id'],refinement_reason='approved_next_segment')
    write(plan_path,plan);return {'status':'ready','next_variant':variant['id']}


def add_identity_reentry_repair(output, review_path, failure_path, canonical_frame):
    """Repair a character re-entry using that character's earlier approved image.

    The adjacent S02 tail contains only the daughter, so it cannot constrain the
    father's identity.  This branch deliberately starts the reaction shot from a
    crop of the approved S01 father instead of pretending the adjacent tail is an
    identity reference for an off-screen character.
    """
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    failure_path=Path(failure_path).resolve();failure=read(failure_path)
    canonical_frame=Path(canonical_frame).resolve()
    source_attempt=next((row for row in plan.get('attempts',[])
        if row.get('variant')=='A3_wardrobe_left_eyeline' and row.get('status')=='succeeded'),None)
    source_variant=next((row for row in plan.get('variants',[])
        if row.get('id')=='A3_wardrobe_left_eyeline'),None)
    if (plan.get('status')!='stopped_after_success' or not source_attempt or not source_variant
            or review.get('schema')!='policy_diagnostic_visual_review/v1'
            or review.get('variant')!='A3_wardrobe_left_eyeline'
            or review.get('source_sha256')!=source_attempt.get('video_sha256')
            or review.get('decision')!='visual_failed_identity'
            or review.get('checks',{}).get('identity') is not False
            or failure.get('schema')!='character_identity_failure/v1'
            or failure.get('decision')!='visual_failed_identity'
            or failure.get('first_failed_shot')!='S03'
            or failure.get('canonical_character',{}).get('source_shot')!='S01_r2'):
        raise ValueError('Identity re-entry repair requires the bound S03 failure and S01 father baseline')
    if not canonical_frame.is_file():
        raise ValueError('Canonical father frame is missing')
    prompt=source_variant['prompt']
    old_intro=('从紧邻已审上段的原始尾帧开始，保留人物外貌、衣着、场景与身体位置；不重置表情或动作。\n'
               '0—0.125秒保留上段末尾构图，随后按下列镜头切换。')
    new_intro=('输入首帧来自S01已审原片，用作本系列父亲的身份、年龄、发色和服装基准。'
               '本段以同一位父亲继续表演；保持输入首帧可见的深色短发、仅两侧鬓角花白、约六十岁年龄感、脸型和服装。\n'
               '0—0.35秒保留输入首帧父女同框构图，随后硬切到父亲头肩近景。')
    old_camera='0—0.35秒，保留输入首帧中的女儿等待画面。'
    new_camera='0—0.35秒，保留输入首帧中的父女同框，父亲面朝画面左侧的女儿，不新增动作。'
    old_identity=('父亲是本系列同一位原创普通父亲：约六十岁，花白短发，'
                  '浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。')
    new_identity=('父亲是输入首帧中的同一位原创普通父亲：约六十岁，深色短发，白发只分布在两侧鬓角，'
                  '保持同一脸型、五官与年龄感，不变成满头银白或明显更老；'
                  '浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。')
    for old,new in ((old_intro,new_intro),(old_camera,new_camera),(old_identity,new_identity)):
        if prompt.count(old)!=1:
            raise ValueError('Cannot isolate the identity re-entry prompt block')
        prompt=prompt.replace(old,new,1)
    variant={'id':'S03_identity_reentry_r1','prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(canonical_frame),**image_info(canonical_frame)},
             'duration':6,
             'changed_factors':['replace_adjacent_daughter_only_tail_with_S01_father_identity_frame',
                                'lock_dark_hair_with_grey_temples_and_same_apparent_age'],
             'failed_review_path':str(review_path),'failed_review_sha256':sha(review_path),
             'identity_failure_path':str(failure_path),'identity_failure_sha256':sha(failure_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('Identity re-entry repair already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='S03_cross_shot_father_identity_failed')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_reentry_text_repair(output, failed_input_path):
    """Fall back to non-biometric text traits after an identity image is rejected."""
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    failed_input_path=Path(failed_input_path).resolve();failed_input=read(failed_input_path)
    last=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    source_variant=next((row for row in plan.get('variants',[])
        if row.get('id')=='A3_wardrobe_left_eyeline'),None)
    if (plan.get('status')!='stopped_for_inspection' or not last or not source_variant
            or last.get('variant')!='S03_identity_reentry_r1' or last.get('status')!='failed'
            or (last.get('response') or {}).get('error',{}).get('code')!='InputImageSensitiveContentDetected.PrivacyInformation'
            or failed_input.get('schema')!='video_provider_failure/v1'
            or failed_input.get('error_code')!='InputImageSensitiveContentDetected.PrivacyInformation'
            or sha(failed_input_path)!=sha(last['failure_record'])):
        raise ValueError('Text identity repair requires the recorded input-image privacy rejection')
    prompt=source_variant['prompt']
    old=('父亲是本系列同一位原创普通父亲：约六十岁，花白短发，'
         '浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。')
    new=('父亲保持S01已经建立的约六十岁外观：深色短发，白发只在两侧鬓角，'
         '不要满头银白，不要变得更老；浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。')
    if prompt.count(old)!=1:
        raise ValueError('Cannot isolate the text identity block')
    prompt=prompt.replace(old,new,1)
    variant={'id':'S03_identity_reentry_text_r2','prompt':prompt,'use_first_frame':True,'duration':6,
             'changed_factors':['restore_adjacent_S02_raw_tail','lock_non_biometric_hair_distribution_and_apparent_age'],
             'input_image_failure_path':str(failed_input_path),'input_image_failure_sha256':sha(failed_input_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('Text identity repair already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='identity_image_rejected_use_non_biometric_text_traits')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_multiref_repair(output, review_path, canonical_frame, state_frame):
    """Use a full-scene S01 identity reference plus the S02 emotional state reference."""
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    canonical_frame=Path(canonical_frame).resolve();state_frame=Path(state_frame).resolve()
    last=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    source_variant=next((row for row in plan.get('variants',[])
        if row.get('id')=='A3_wardrobe_left_eyeline'),None)
    if (plan.get('status')!='stopped_after_success' or not last or not source_variant
            or last.get('variant')!='S03_identity_reentry_text_r2' or last.get('status')!='succeeded'
            or review.get('schema')!='policy_diagnostic_visual_review/v1'
            or review.get('variant')!=last['variant']
            or review.get('source_sha256')!=last.get('video_sha256')
            or review.get('decision')!='visual_failed_identity'
            or review.get('checks',{}).get('identity') is not False
            or not canonical_frame.is_file() or not state_frame.is_file()
            or str(state_frame)!=str(Path(plan['first_frame']['path']).resolve())
            or sha(state_frame)!=plan['first_frame']['sha256']):
        raise ValueError('Multi-reference repair requires the bound text-only identity failure and original S02 tail')
    prompt=source_variant['prompt']
    old_intro=('从紧邻已审上段的原始尾帧开始，保留人物外貌、衣着、场景与身体位置；不重置表情或动作。\n'
               '0—0.125秒保留上段末尾构图，随后按下列镜头切换。')
    new_intro=('参考图1来自S01同一玄关，锁定父亲的同一张脸、深色短发与鬓角少量白发、约六十岁年龄感和服装；'
               '参考图2来自S02原始尾帧，锁定女儿当前抬眼等待的表情、发型、服装与门框位置。'
               '两张图只用于同一父女和同一场景的连续，不新增人物或剧情。\n'
               '0—0.35秒从参考图2的女儿等待近景开始，随后硬切到参考图1中同一位父亲的头肩近景。')
    old_camera='0—0.35秒，保留输入首帧中的女儿等待画面。'
    new_camera='0—0.35秒，延续参考图2中的女儿抬眼等待近景。'
    old_identity=('父亲是本系列同一位原创普通父亲：约六十岁，花白短发，'
                  '浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。')
    new_identity=('父亲严格沿用参考图1中的同一位原创普通父亲：约六十岁，深色短发，白发只在两侧鬓角，'
                  '保持同一脸型、五官和年龄感；浅灰夹克内搭深蓝圆领衫，下穿深灰长裤。')
    for old,new in ((old_intro,new_intro),(old_camera,new_camera),(old_identity,new_identity)):
        if prompt.count(old)!=1:
            raise ValueError('Cannot isolate the multi-reference prompt block')
        prompt=prompt.replace(old,new,1)
    references=[{'path':str(canonical_frame),**image_info(canonical_frame)},
                {'path':str(state_frame),**image_info(state_frame)}]
    variant={'id':'S03_identity_multiref_r3','prompt':prompt,'use_first_frame':False,
             'reference_images':references,'duration':6,
             'changed_factors':['use_S01_full_scene_as_father_identity_reference',
                                'use_S02_tail_as_daughter_emotional_state_reference'],
             'failed_review_path':str(review_path),'failed_review_sha256':sha(review_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('Multi-reference identity repair already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='text_traits_fixed_hair_and_age_but_face_still_drifted')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_safe_s01(output, script_path):
    """Restart the visual chain with both recurring characters visible at the tail."""
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    script_path=Path(script_path).resolve();script=read(script_path)
    last=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    if (plan.get('status')!='stopped_for_inspection' or not last
            or last.get('variant')!='S03_identity_multiref_r3' or last.get('status')!='failed'
            or (last.get('response') or {}).get('error',{}).get('code')!='InputImageSensitiveContentDetected.PrivacyInformation'
            or script.get('schema')!='reference_director_video_script/v1'):
        raise ValueError('Identity-safe restart requires the recorded multi-reference input rejection')
    shots=[row for row in script.get('shots',[]) if row.get('shot_id')=='S01']
    if len(shots)!=1:
        raise ValueError('Reviewed S01 source is required')
    prompt=shots[0]['model_prompt_zh']
    if prompt.count(CAMERA_START)!=1 or prompt.count(CAMERA_END)!=1:
        raise ValueError('Cannot isolate the S01 camera schedule')
    before,remainder=prompt.split(CAMERA_START,1);_,after=remainder.split(CAMERA_END,1)
    camera=(
        '0—7秒，V01R：固定中景双人构图，不切镜。父亲在画面右侧门内，身体朝左，头部为清楚的三分之二侧脸；'
        '女儿在画面左侧门外，身体朝右，脸部正侧结合。两人的眼睛、嘴、发型与上半身全程清晰可辨，门框与低门槛同时可见。'
        '女儿仍按动作表完成试步、停住和受伤反应；父亲说完后留在画内。机位固定，不推拉、不横移，结尾必须同时保留父亲和女儿清楚可见。')
    prompt=before+CAMERA_START+camera+CAMERA_END+after
    prompt += ('\n本段重新建立本链唯一人物基准。父女在全段和原始尾帧中都必须可见；'
               '后续只从这个同时包含两人的原始尾帧继续。')
    variant={'id':'S01_identity_safe_chain','prompt':prompt,'use_first_frame':False,'duration':7,
             'changed_factors':['replace_daughter_solo_closeup_with_fixed_two_shot',
                                'keep_both_recurring_characters_visible_in_raw_tail'],
             'script_path':str(script_path),'script_sha256':sha(script_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('Identity-safe S01 already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='restart_chain_to_keep_reappearing_characters_in_adjacent_tails')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_safe_continuation(output, review_path, script_path, shot_id):
    """Continue the rebuilt chain while keeping both recurring faces visible."""
    sequence={'S02':('S01_identity_safe_chain',10),'S03':('S02_identity_safe_chain_r2',6),
              'S04':('S03_identity_safe_chain',4)}
    if shot_id not in sequence:
        raise ValueError('Identity-safe continuation supports S02, S03 or S04')
    previous_variant,duration=sequence[shot_id]
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    script_path=Path(script_path).resolve();script=read(script_path)
    last=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    required=('identity','spatial_layout','props_and_hands','action_pace','cut_continuity','visual_storytelling')
    if (plan.get('status')!='stopped_after_success' or not last
            or last.get('variant')!=previous_variant or last.get('status')!='succeeded'
            or review.get('variant')!=previous_variant
            or review.get('source_sha256')!=last.get('video_sha256')
            or review.get('decision')!='visual_passed_audio_pending'
            or any(review.get('checks',{}).get(key) is not True for key in required)
            or any(review.get('checks',{}).get(key) is not None for key in ('dialogue_pace','speaker_voice','lip_sync'))
            or review.get('original_tail_sha256')!=last.get('last_frame_sha256')
            or script.get('schema')!='reference_director_video_script/v1'):
        raise ValueError(f'{shot_id} requires the actual visual pass and raw tail of {previous_variant}')
    tail=Path(last['last_frame']).resolve()
    if sha(tail)!=last.get('last_frame_sha256'):
        raise ValueError('Previous identity-safe raw tail changed')
    shots=[row for row in script.get('shots',[]) if row.get('shot_id')==shot_id]
    if len(shots)!=1:
        raise ValueError(f'Reviewed {shot_id} source is required')
    prompt=shots[0]['model_prompt_zh']
    if prompt.count(CAMERA_START)!=1 or prompt.count(CAMERA_END)!=1:
        raise ValueError(f'Cannot isolate the {shot_id} camera schedule')
    if shot_id=='S02':
        camera=('0—10秒，V03R：固定中近景双人构图，不切镜。女儿位于画面左侧并占较大画面，父亲位于右侧；'
                '女儿眼嘴与抬眼过程清晰，父亲三分之二侧脸、发型和上半身也始终可辨。两人持续面对彼此，门框位置不变。'
                '结尾必须同时保留父亲和女儿清楚可见，不把父亲裁出画面。')
    elif shot_id=='S03':
        camera=('0—6秒，V04R：固定中近景双人构图，不切镜。父亲位于画面右侧并占较大画面，身体与鼻尖朝左看女儿；'
                '女儿位于画面左侧，脸、黑色齐肩发和米色上衣始终可辨。父亲眼嘴清晰，完成低目、抬眼与认错。'
                '结尾必须同时保留父亲和女儿清楚可见。')
    else:
        camera=('0—4秒，V05R：固定全景双人构图，不切镜。门槛位于画面中下部，门槛两侧地面和两人双脚完整可见；'
                '父亲在门内右侧，女儿在门外左侧。完整显示父亲让开、女儿双脚依次跨入并站稳；两人的脸和发型全程仍可辨。')
    before,remainder=prompt.split(CAMERA_START,1);_,after=remainder.split(CAMERA_END,1)
    prompt=before+CAMERA_START+camera+CAMERA_END+after
    prompt += ('\n只沿用输入首帧中的同一对父女：父亲的脸型、深灰短发与鬓角灰白、年龄感和服装不变；'
               '女儿的脸型、黑色齐肩直发、年龄感和服装不变。两人直到本段原始尾帧均保持可见。')
    variant_id=f'{shot_id}_identity_safe_chain'
    variant={'id':variant_id,'prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(tail),**image_info(tail)},'duration':duration,
             'changed_factors':['continue_from_both_characters_visible_raw_tail',
                                'keep_both_recurring_characters_visible_in_raw_tail'],
             'review_path':str(review_path),'review_sha256':sha(review_path),
             'script_path':str(script_path),'script_sha256':sha(script_path)}
    if any(row['id']==variant_id for row in plan['variants']):
        raise ValueError(f'{variant_id} already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant_id,
                refinement_reason=f'approved_identity_safe_{previous_variant}')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant_id}


def add_identity_safe_s02_emotion_repair(output, review_path):
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    failed=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    parent=next((row for row in plan.get('attempts',[])
        if row.get('variant')=='S01_identity_safe_chain' and row.get('status')=='succeeded'),None)
    source=next((row for row in plan.get('variants',[])
        if row.get('id')=='S02_identity_safe_chain'),None)
    if (plan.get('status')!='stopped_after_success' or not failed or not parent or not source
            or failed.get('variant')!='S02_identity_safe_chain' or failed.get('status')!='succeeded'
            or review.get('variant')!=failed['variant']
            or review.get('source_sha256')!=failed.get('video_sha256')
            or review.get('decision')!='visual_failed_emotion_timing'
            or review.get('checks',{}).get('action_pace') is not False
            or review.get('checks',{}).get('visual_storytelling') is not False):
        raise ValueError('S02 emotion repair requires the bound failed S02 visual review')
    tail=Path(parent['last_frame']).resolve()
    if sha(tail)!=parent.get('last_frame_sha256'):
        raise ValueError('Approved S01 raw tail changed')
    prompt=source['prompt'] + (
        '\n本次定点修复：最后一句问完后，7.2—10.0秒女儿的下巴、眼睛和脸部朝向必须持续停在父亲脸上；'
        '这段不再低头、不移开目光、不闭眼回避、不转身。最后一帧仍抬眼等待父亲回答。'
        '父亲保持同框，不说话、不转墙。其他动作、对白、人物、服装、场景和时长不变。')
    variant={'id':'S02_identity_safe_chain_r2','prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(tail),**image_info(tail)},'duration':10,
             'changed_factors':['hold_daughter_gaze_on_father_during_final_reaction_window'],
             'failed_review_path':str(review_path),'failed_review_sha256':sha(review_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('S02 identity-safe emotion repair already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='S02_final_reaction_window_failed')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_safe_s04_action_repair(output, review_path):
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    failed=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    parent=next((row for row in plan.get('attempts',[])
        if row.get('variant')=='S03_identity_safe_chain' and row.get('status')=='succeeded'),None)
    source=next((row for row in plan.get('variants',[])
        if row.get('id')=='S04_identity_safe_chain'),None)
    if (plan.get('status')!='stopped_after_success' or not failed or not parent or not source
            or failed.get('variant')!='S04_identity_safe_chain' or failed.get('status')!='succeeded'
            or review.get('variant')!=failed['variant']
            or review.get('source_sha256')!=failed.get('video_sha256')
            or review.get('decision')!='visual_failed_action'
            or review.get('checks',{}).get('action_pace') is not False
            or review.get('checks',{}).get('spatial_layout') is not False):
        raise ValueError('S04 action repair requires the bound failed S04 visual review')
    tail=Path(parent['last_frame']).resolve()
    if sha(tail)!=parent.get('last_frame_sha256'):
        raise ValueError('Approved S03 raw tail changed')
    prompt=source['prompt']
    if prompt.count(CAMERA_START)!=1 or prompt.count(CAMERA_END)!=1:
        raise ValueError('Cannot isolate the S04 repair camera schedule')
    before,remainder=prompt.split(CAMERA_START,1);_,after=remainder.split(CAMERA_END,1)
    camera=(
        '0—0.25秒，保留输入首帧的父女近景，只作连续承接。\n'
        '0.25秒处明确硬切，无渐变无推拉，切到固定全身全景并保持至4秒结束。全景中门框完整，低平门槛位于画面中下部；'
        '门外地面、门槛和门内地面同时可见。父亲全身在门内右侧，女儿全身在门外左侧，两人的头顶到双脚均在画内。'
        '必须拍到父亲实际向右让开一步，以及女儿右脚跨过门槛、左脚跟进、双脚在门内站稳的完整过程。'
        '硬切后不再切镜、不移动机位、不回到近景。')
    prompt=before+CAMERA_START+camera+CAMERA_END+after
    prompt += ('\n本段无对白，父女均不说话、不持续张嘴。摄影机不能用推远模拟人物进门；'
               '必须由女儿双脚真实移动跨越门槛。人物外观严格沿用输入首帧。')
    variant={'id':'S04_identity_safe_chain_r2','prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(tail),**image_info(tail)},'duration':4,
             'changed_factors':['hard_cut_to_full_body_wide_at_0p25',
                                'require_visible_father_side_step_and_two_foot_threshold_crossing'],
             'failed_review_path':str(review_path),'failed_review_sha256':sha(review_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('S04 identity-safe action repair already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='S04_closeup_hid_required_threshold_action')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_safe_s04_action_repair_r3(output, review_path):
    """Give the closing action enough time and require each footfall to be readable."""
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    failed=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    parent=next((row for row in plan.get('attempts',[])
        if row.get('variant')=='S03_identity_safe_chain' and row.get('status')=='succeeded'),None)
    source=next((row for row in plan.get('variants',[])
        if row.get('id')=='S04_identity_safe_chain_r2'),None)
    if (plan.get('status')!='stopped_after_success' or not failed or not parent or not source
            or failed.get('variant')!='S04_identity_safe_chain_r2' or failed.get('status')!='succeeded'
            or review.get('variant')!=failed['variant']
            or review.get('source_sha256')!=failed.get('video_sha256')
            or review.get('decision')!='visual_failed_action'
            or review.get('checks',{}).get('action_pace') is not False
            or review.get('checks',{}).get('visual_storytelling') is not False):
        raise ValueError('S04 r3 repair requires the bound failed S04 r2 visual review')
    tail=Path(parent['last_frame']).resolve()
    if sha(tail)!=parent.get('last_frame_sha256'):
        raise ValueError('Approved S03 raw tail changed')
    prompt=source['prompt']
    if prompt.count(CAMERA_START)!=1 or prompt.count(CAMERA_END)!=1:
        raise ValueError('Cannot isolate the S04 r3 camera schedule')
    before,remainder=prompt.split(CAMERA_START,1);_,after=remainder.split(CAMERA_END,1)
    camera=(
        '0—0.25秒，保留输入首帧的父女近景，只作连续承接。\n'
        '0.25秒处明确硬切，无渐变无推拉，切到固定全身全景并保持至6秒结束。全景中完整显示门框、门外地面、'
        '低平门槛和门内地面；父亲全身在门内中央偏右，女儿全身在门外左侧，两人头顶到双脚均在画内。\n'
        '0.25—1.70秒，只允许父亲动作：女儿双脚不动；父亲向画面右侧横移清楚可见的一整小步，双脚重新站稳，'
        '让出门内通道，脸始终朝女儿。\n'
        '1.70—2.20秒，父亲停住让路，女儿看他确认，二人双脚都不动。\n'
        '2.20—3.40秒，只允许女儿第一只脚跨过门槛并完整落在门内地面；父亲不动。\n'
        '3.40—4.60秒，女儿第二只脚再跨过门槛，完整落在门内地面，与第一只脚并立；不能留一只脚在门外。\n'
        '4.60—6.00秒，固定全景停留：女儿双脚均在门内、父亲站在右侧让出的空间旁，两人面对彼此，动作结束。\n'
        '整个全景不得切镜、不得移动摄影机、不得遮挡双脚。')
    prompt=before+CAMERA_START+camera+CAMERA_END+after
    prompt += ('\n本次只修复动作可读性并延长到6秒。父亲让路与女儿进门必须严格串行，不能同时动作。'
               '本段无对白，父女均不说话、不持续张嘴。不得用推远、人物滑行或突然换位置代替脚步；'
               '人物外观、发色、年龄、脸型和服装严格沿用输入首帧。')
    variant={'id':'S04_identity_safe_chain_r3','prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(tail),**image_info(tail)},'duration':6,
             'changed_factors':['extend_closing_action_to_six_seconds',
                                'separate_father_side_step_from_two_foot_threshold_crossing',
                                'require_readable_final_both_feet_inside_hold'],
             'failed_review_path':str(review_path),'failed_review_sha256':sha(review_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('S04 identity-safe action repair r3 already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='S04_r2_only_one_foot_crossed_and_father_step_was_unreadable')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def add_identity_safe_s04_wardrobe_repair_r4(output, review_path):
    """Retain the successful doorway action while locking lower-body wardrobe."""
    output=Path(output).resolve();plan_path=output/'plan.json';plan=read(plan_path)
    review_path=Path(review_path).resolve();review=read(review_path)
    failed=plan.get('attempts',[])[-1] if plan.get('attempts') else None
    parent=next((row for row in plan.get('attempts',[])
        if row.get('variant')=='S03_identity_safe_chain' and row.get('status')=='succeeded'),None)
    source=next((row for row in plan.get('variants',[])
        if row.get('id')=='S04_identity_safe_chain_r3'),None)
    if (plan.get('status')!='stopped_after_success' or not failed or not parent or not source
            or failed.get('variant')!='S04_identity_safe_chain_r3' or failed.get('status')!='succeeded'
            or review.get('variant')!=failed['variant']
            or review.get('source_sha256')!=failed.get('video_sha256')
            or review.get('decision')!='visual_failed_continuity'
            or review.get('checks',{}).get('cut_continuity') is not False
            or review.get('checks',{}).get('action_pace') is not True):
        raise ValueError('S04 r4 repair requires the bound failed S04 r3 continuity review')
    tail=Path(parent['last_frame']).resolve()
    if sha(tail)!=parent.get('last_frame_sha256'):
        raise ValueError('Approved S03 raw tail changed')
    prompt=source['prompt'] + (
        '\n本次唯一新增修复是女儿下半身服装连续性。女儿全段必须穿浅蓝色直筒长牛仔裤，裤腿从腰部完整覆盖到脚踝，'
        '双脚必须穿低帮浅色平底鞋；禁止裸腿、赤脚、裙子、短裤、连衣裙、把长上衣误生成裙装或让裤鞋在硬切后消失。'
        '父亲仍穿深灰长裤和黑色便鞋。人物完整服装从近景到全景保持同一套。'
        '父亲侧步与女儿两脚依次进门的既有时间表、机位、时长、脸型、发色和年龄感全部不变。')
    variant={'id':'S04_identity_safe_chain_r4','prompt':prompt,'use_first_frame':True,
             'first_frame':{'path':str(tail),**image_info(tail)},'duration':6,
             'changed_factors':['lock_daughter_full_length_jeans_and_flat_shoes',
                                'retain_successful_serial_doorway_action'],
             'failed_review_path':str(review_path),'failed_review_sha256':sha(review_path)}
    if any(row['id']==variant['id'] for row in plan['variants']):
        raise ValueError('S04 identity-safe wardrobe repair r4 already exists')
    plan['variants'].append(variant)
    plan.update(status='ready',next_variant=variant['id'],
                refinement_reason='S04_r3_action_passed_but_daughter_trousers_and_shoes_disappeared')
    write(plan_path,plan)
    return {'status':'ready','next_variant':variant['id']}


def run(output):
    while True:
        plan = read(Path(output) / 'plan.json')
        if plan['status'] in {'stopped_after_success', 'stopped_for_inspection', 'exhausted'}:
            return {'status': plan['status'], 'attempts': [(a['variant'], a['status']) for a in plan['attempts']]}
        if plan['status'] == 'ready':
            submit_next(output)
        result = query_current(output)
        if result['status'] in {'queued', 'running'}:
            time.sleep(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['init', 'submit', 'query', 'refine-identity', 'refine-eyeline', 'continue-s04', 'repair-identity-reentry', 'repair-identity-text', 'repair-identity-multiref', 'restart-identity-safe-s01', 'continue-identity-safe', 'repair-identity-safe-s02-emotion', 'repair-identity-safe-s04-action', 'repair-identity-safe-s04-action-r3', 'repair-identity-safe-s04-wardrobe-r4', 'run'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--failed-receipt')
    parser.add_argument('--first-frame')
    parser.add_argument('--authorization')
    parser.add_argument('--review')
    parser.add_argument('--script')
    parser.add_argument('--failure')
    parser.add_argument('--canonical-frame')
    parser.add_argument('--shot')
    args = parser.parse_args()
    if args.operation == 'init':
        result = initialize(args.output, args.failed_receipt, args.first_frame, args.authorization or '')
        result = {'status': result['status'], 'next_variant': result['next_variant']}
    elif args.operation == 'submit': result = submit_next(args.output)
    elif args.operation == 'query': result = query_current(args.output)
    elif args.operation == 'refine-identity': result = add_identity_refinement(args.output, args.review)
    elif args.operation == 'refine-eyeline': result = add_eyeline_refinement(args.output, args.review)
    elif args.operation == 'continue-s04': result = add_s04_continuation(args.output, args.review, args.script)
    elif args.operation == 'repair-identity-reentry': result = add_identity_reentry_repair(
        args.output, args.review, args.failure, args.canonical_frame)
    elif args.operation == 'repair-identity-text': result = add_identity_reentry_text_repair(
        args.output, args.failure)
    elif args.operation == 'repair-identity-multiref': result = add_identity_multiref_repair(
        args.output, args.review, args.canonical_frame, args.first_frame)
    elif args.operation == 'restart-identity-safe-s01': result = add_identity_safe_s01(
        args.output, args.script)
    elif args.operation == 'continue-identity-safe': result = add_identity_safe_continuation(
        args.output, args.review, args.script, args.shot)
    elif args.operation == 'repair-identity-safe-s02-emotion': result = add_identity_safe_s02_emotion_repair(
        args.output, args.review)
    elif args.operation == 'repair-identity-safe-s04-action': result = add_identity_safe_s04_action_repair(
        args.output, args.review)
    elif args.operation == 'repair-identity-safe-s04-action-r3': result = add_identity_safe_s04_action_repair_r3(
        args.output, args.review)
    elif args.operation == 'repair-identity-safe-s04-wardrobe-r4': result = add_identity_safe_s04_wardrobe_repair_r4(
        args.output, args.review)
    else: result = run(args.output)
    print(json.dumps(result, ensure_ascii=False))
