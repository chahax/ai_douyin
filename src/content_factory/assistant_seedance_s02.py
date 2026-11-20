"""Single S02 continuation from the user-confirmed S01 service-native tail."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from .assistant_seedance_trial import (
    OUT as S01_OUT, SOURCE, STORY_ID, STORY_LEDGER, bound, exclusive,
    last_frame_integrity, now, read, sha, video_metadata,
)
from .creative_stage_contracts import digest, persist
from .media_review_policy import mark_saved_candidate
from .seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceReference

OUT = S01_OUT / 'S02'
TRIAL_ID = 'assistant_seedance_screenplay_20261016_S02'
PRIOR_ID = 'cgt-20261016093324-czthg'
PRIOR_VIDEO_SHA = '9ef1fae17e87ae524c5a2e1e6ecbf4c2c582977e86be58d4936d4916778e7af3'
PRIOR_TAIL_SHA = 'e8c909945f7fd3eb0779b2bb3b1f1b4ce02d718bfa0617b82079f5a3f5c3949d'


def inherited_failures(plan, *, dispatch=True):
    counter = plan['story_counter']
    if Path(counter['path']).resolve() != STORY_LEDGER.resolve() or counter.get('reset') is not False:
        raise ValueError('same-story ledger changed or reset requested')
    if dispatch:
        bound(counter)
    legacy = read(STORY_LEDGER)
    if (legacy.get('story_id') != STORY_ID or type(legacy.get('failures_used')) is not int
            or legacy.get('failure_limit') != 10 or counter.get('failure_limit') != 10
            or (dispatch and legacy['failures_used'] != counter.get('failures_used'))):
        raise ValueError('same-story failure counter identity differs')
    if Path(plan['prior_media_events']['path']).resolve() != (S01_OUT / 'MEDIA_EVENTS.json').resolve():
        raise ValueError('prior media history changed')
    if dispatch:
        bound(plan['prior_media_events'])
    previous = read(plan['prior_media_events']['path'])
    additional = previous.get('trial_technical_failures', 0)
    if previous.get('story_id') != STORY_ID or type(additional) is not int or additional < 0:
        raise ValueError('invalid prior same-story media history')
    total = legacy['failures_used'] + additional
    if total < 0 or (dispatch and total >= 10):
        raise ValueError('same-story failure limit exhausted; history cannot reset')
    return total


def validate(plan_path):
    plan_path = Path(plan_path).resolve()
    out = plan_path.parent
    plan = read(plan_path)
    if plan.get('schema') != 'assistant_seedance_continuation_plan/v1':
        raise ValueError('wrong S02 plan schema')
    expected = dict(story_id=STORY_ID, segment_id='S02', provider='ark_api', model=ARK_MINI_MODEL,
                    duration_seconds=15, resolution='720p', ratio='16:9', generate_audio=True,
                    return_last_frame=True)
    if any(plan.get(k) != v or type(plan.get(k)) is not type(v) for k, v in expected.items()):
        raise ValueError('S02 identity or fixed generation parameters differ')
    if plan.get('references') or plan.get('use_previous_video_reference') or plan.get('last_frame'):
        raise ValueError('formal first-frame mode cannot mix other references')
    auth = plan['authorization']
    expected_auth = dict(user_statement='继续', max_new_submissions=1, automatic_retry=False,
                         continuation_authorized=False, publishing_authorized=False)
    if any(auth.get(k) != v or type(auth.get(k)) is not type(v) for k, v in expected_auth.items()):
        raise ValueError('only the single S02 continuation is authorized')
    script_path = bound(plan['sources']['screenplay'])
    segment_path = bound(plan['sources']['segment'])
    if script_path != (SOURCE / 'FULL_SCREENPLAY.md').resolve() or segment_path != out / 'SOURCE_S02.md':
        raise ValueError('S02 must use the selected assistant-authored source files')
    script = script_path.read_text(encoding='utf-8')
    original_s02 = script[script.index('### S02｜'):script.index('### S03｜')].strip()
    if segment_path.read_text(encoding='utf-8').strip() != original_s02:
        raise ValueError('S02 source is not the exact full-screenplay section')
    prompt = bound(plan['prompt']).read_text(encoding='utf-8').strip()
    if not prompt:
        raise ValueError('empty S02 prompt')
    user_path = bound(plan['user_continuation'])
    if user_path != out / 'USER_CONTINUATION.json':
        raise ValueError('wrong user continuation artifact')
    user = read(user_path)
    user_expected = dict(schema='assistant_seedance_user_continuation/v1', user_statement='继续',
                         prior_task_id=PRIOR_ID, prior_video_sha256=PRIOR_VIDEO_SHA,
                         prior_native_tail_sha256=PRIOR_TAIL_SHA, accepted_prior_segment_for_continuation=True,
                         authorized_next_segment='S02', max_new_submissions=1, automatic_retry=False,
                         batch_continuation_authorized=False, publishing_authorized=False)
    if any(user.get(k) != v or type(user.get(k)) is not type(v) for k, v in user_expected.items()):
        raise ValueError('user continuation does not bind the delivered S01 and S02 scope')
    if (user.get('full_screenplay_sha256') != plan['sources']['screenplay']['sha256']
            or user.get('source_s02_sha256') != plan['sources']['segment']['sha256']):
        raise ValueError('source differs from the user continuation binding')
    prior = read(S01_OUT / 'receipt.json')
    if (prior.get('task_id') != PRIOR_ID or prior.get('technical_status') != 'succeeded'
            or prior.get('video_sha256') != PRIOR_VIDEO_SHA or sha(prior['video_path']) != PRIOR_VIDEO_SHA
            or prior.get('last_frame_sha256') != PRIOR_TAIL_SHA or sha(prior['last_frame']) != PRIOR_TAIL_SHA
            or Path(user['prior_video_path']).resolve() != Path(prior['video_path']).resolve()
            or Path(user['prior_native_tail_path']).resolve() != Path(prior['last_frame']).resolve()):
        raise ValueError('delivered S01 receipt/video/native tail identity differs')
    frame = bound(plan['first_frame'])
    if (frame != out / 'S01.service_native_tail.original.jpg'
            or plan['first_frame']['sha256'] != PRIOR_TAIL_SHA
            or plan['first_frame'].get('source_task_id') != PRIOR_ID):
        raise ValueError('first frame must be the exact S01 native tail, never H3 or an extracted frame')
    get_path = bound(plan['service_source'])
    tail_path = bound(plan['native_tail_binding'])
    if get_path != out / 'SOURCE_SERVICE_GET.json' or tail_path != out / 'NATIVE_TAIL_BINDING.json':
        raise ValueError('wrong current-credential source evidence paths')
    service, tail = read(get_path), read(tail_path)
    if (service.get('id') != PRIOR_ID or service.get('status') != 'succeeded'
            or service.get('model') != ARK_MINI_MODEL
            or not str(service.get('content', {}).get('last_frame_url', '')).startswith('https://')):
        raise ValueError('current-credential original S01 GET is not succeeded with its native last-frame URL')
    if (tail.get('prior_task_id') != PRIOR_ID or tail.get('native_tail_sha256') != PRIOR_TAIL_SHA
            or Path(tail['native_tail_path']).resolve() != frame
            or tail.get('current_credential_original_task_get_succeeded') is not True
            or tail.get('same_bytes_as_original_S01_download') is not True
            or tail.get('posthoc_extraction') is not False or tail.get('pixel_decoding') is not False
            or Path(tail['service_get_path']).resolve() != get_path
            or tail.get('service_get_sha256') != plan['service_source']['sha256']
            or Path(tail['user_continuation_path']).resolve() != user_path
            or tail.get('user_continuation_sha256') != plan['user_continuation']['sha256']):
        raise ValueError('fresh service native-tail provenance differs')
    last_frame_integrity(frame)
    inherited_failures(plan)
    return plan, prompt


def request_for(client, plan, prompt):
    if (client.config.provider != 'ark_api' or client.config.model != ARK_MINI_MODEL
            or client.config.base_url.rstrip('/') != ARK_BASE_URL):
        raise ValueError('configured provider/model/endpoint differs')
    frame = bound(plan['first_frame'])
    encoding = last_frame_integrity(frame)
    mime = 'image/jpeg' if encoding['format'] == 'jpeg' else 'image/png'
    raw = frame.read_bytes()
    url = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')
    request = client.build_task_payload(prompt, duration=15, ratio='16:9', resolution='720p',
                                        generate_audio=True, return_last_frame=True, watermark=False,
                                        references=[SeedanceReference('image', url, 'first_frame')], task_type='first_frame')
    preview = {key: value for key, value in request.items() if key != 'content'}
    preview['content'] = [request['content'][0], dict(type='image_url', role='first_frame',
                                                   source_task_id=PRIOR_ID, sha256=sha(frame), bytes=len(raw), mime=mime,
                                                   url_sha256=hashlib.sha256(url.encode()).hexdigest())]
    return request, preview


def media_event(kind, receipt_path, plan, *, failure=False, task_id=None):
    with exclusive(STORY_LEDGER.with_suffix('.dispatch.lock')):
        inherited = inherited_failures(plan, dispatch=kind == 'seedance_dispatch_reserved')
        path = receipt_path.parent / 'MEDIA_EVENTS.json'
        row = read(path) if path.exists() else dict(story_id=STORY_ID, inherited_failures=inherited,
                                                   failure_limit=10, trial_technical_failures=0, events=[])
        if any(e.get('kind') == kind for e in row['events']):
            if kind == 'seedance_dispatch_reserved':
                raise ValueError('S02 already reserved; do not resubmit')
            return
        if kind == 'seedance_dispatch_reserved':
            if inherited + row['trial_technical_failures'] >= 10:
                raise ValueError('same-story failure limit exhausted')
            marker = STORY_LEDGER.parent / (TRIAL_ID + '.dispatch_claim.json')
            with marker.open('x', encoding='utf-8') as handle:
                json.dump(dict(trial_id=TRIAL_ID, receipt=str(receipt_path), created_at=now()), handle)
                handle.flush()
                os.fsync(handle.fileno())
        row['events'].append(dict(at=now(), kind=kind, trial_id=TRIAL_ID, provider='ark_api',
                                  receipt=str(receipt_path), task_id=task_id, content_review=None))
        row['trial_technical_failures'] += int(failure)
        row['combined_known_failures'] = inherited + row['trial_technical_failures']
        row['historical_ledger_unchanged'] = True
        row['prior_media_events_unchanged'] = True
        persist(path, row)


def execute(operation, client, out=OUT):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with exclusive(out / '.execution.lock'):
        if operation == 'query':
            return query(client, out)
        if operation not in ('prepare', 'submit'):
            raise ValueError('unsupported S02 operation')
        claim_path, receipt_path = out / 'SUBMISSION_CLAIM.json', out / 'receipt.json'
        if claim_path.exists() or receipt_path.exists():
            raise ValueError('S02 already claimed; query its original task only')
        plan_path = out / 'PLAN.json'
        plan, prompt = validate(plan_path)
        request, preview = request_for(client, plan, prompt)
        binding = dict(plan_sha256=sha(plan_path), plan_digest=digest(plan), request_sha256=digest(request),
                       preview_sha256=digest(preview), source_bindings=plan['sources'],
                       user_continuation=plan['user_continuation'], source_service_get=plan['service_source'],
                       native_tail_binding=plan['native_tail_binding'], prompt_binding=plan['prompt'],
                       predecessor_receipt_sha256=sha(S01_OUT / 'receipt.json'))
        if operation == 'prepare':
            persist(out / 'REQUEST.actual.json', request, immutable=True)
            persist(out / 'REQUEST.preview.json', dict(schema='assistant_seedance_s02_request_preview/v1',
                                                      bindings=binding, request=preview), immutable=True)
            return dict(status='prepared_not_submitted', segment_id='S02', request_sha256=binding['request_sha256'])
        prepared = read(out / 'REQUEST.preview.json')
        if (prepared.get('bindings') != binding or prepared.get('request') != preview
                or digest(read(out / 'REQUEST.actual.json')) != binding['request_sha256']):
            raise ValueError('S02 actual request differs from its frozen preview')
        claim = dict(schema='assistant_seedance_s02_claim/v1', trial_id=TRIAL_ID, created_at=now(), **binding)
        with claim_path.open('x', encoding='utf-8') as handle:
            json.dump(claim, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        record = dict(schema='assistant_seedance_s02_receipt/v1', status='submitting', technical_status='unknown',
                      content_status='not_available', trial_id=TRIAL_ID, logical_task_id=STORY_ID,
                      segment_id='S02', provider='ark_api', model=ARK_MINI_MODEL, claim_sha256=sha(claim_path),
                      plan_snapshot=plan, voice_reference_status='unbound', **binding)
        persist(receipt_path, record)
        try:
            media_event('seedance_dispatch_reserved', receipt_path, plan)
            latest, _ = validate(plan_path)
            if digest(latest) != binding['plan_digest']:
                raise ValueError('S02 source changed at dispatch admission')
        except Exception:
            record.update(status='blocked_before_submit', technical_status='not_submitted')
            persist(receipt_path, record)
            raise
        try:
            created = client.create_task(request)
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            rejected = isinstance(status, int) and 400 <= status < 500
            record.update(status='request_rejected' if rejected else 'submit_outcome_unknown',
                          technical_status='failed' if rejected else 'unknown', error_type=type(exc).__name__,
                          error_message=str(exc), http_status=status, error_code=getattr(exc, 'error_code', None))
            persist(receipt_path, record)
            media_event(record['status'], receipt_path, plan, failure=rejected)
            return dict(status=record['status'], technical_status=record['technical_status'])
        persist(out / 'CREATED.original.json', created, immutable=True)
        task_id = created.get('id')
        if not isinstance(task_id, str) or not task_id or not all(c.isalnum() or c in '-_' for c in task_id):
            record.update(status='submit_outcome_unknown', technical_status='unknown')
            persist(receipt_path, record)
            raise ValueError('no valid original S02 task ID; reconcile without resubmitting')
        persist(out / 'TASK_ID.json', dict(task_id=task_id, claim_sha256=sha(claim_path),
                                         created_sha256=sha(out / 'CREATED.original.json')), immutable=True)
        record.update(task_id=task_id, status='submitted', technical_status='running')
        persist(receipt_path, record)
        media_event('seedance_submitted', receipt_path, plan, task_id=task_id)
        return dict(status='submitted', segment_id='S02', task_id=task_id)


def query(client, out):
    receipt_path, claim_path = out / 'receipt.json', out / 'SUBMISSION_CLAIM.json'
    record, claim = read(receipt_path), read(claim_path)
    task_binding = read(out / 'TASK_ID.json')
    if (record['claim_sha256'] != sha(claim_path) or task_binding['claim_sha256'] != sha(claim_path)
            or task_binding['created_sha256'] != sha(out / 'CREATED.original.json')
            or read(out / 'CREATED.original.json').get('id') != task_binding['task_id']
            or record.get('task_id', task_binding['task_id']) != task_binding['task_id']
            or digest(record['plan_snapshot']) != claim['plan_digest']
            or any(record[k] != claim[k] for k in ('plan_sha256', 'request_sha256', 'source_bindings',
                                                 'user_continuation', 'source_service_get', 'native_tail_binding',
                                                 'prompt_binding', 'predecessor_receipt_sha256', 'preview_sha256'))):
        raise ValueError('original S02 task/claim/receipt identity differs')
    task_id = task_binding['task_id']
    if record.get('technical_status') == 'succeeded':
        if sha(record['video_path']) != record['video_sha256'] or sha(record['last_frame']) != record['last_frame_sha256']:
            raise ValueError('saved original S02 output changed')
        return {k: record.get(k) for k in ('status', 'task_id', 'video_path', 'last_frame', 'content_status')}
    task = client.get_task(task_id)
    persist(out / ('QUERY.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'), task, immutable=True)
    if task.get('id') != task_id:
        raise ValueError('query returned another task identity')
    record.update(task_id=task_id, status=task['status'], latest_response=task, last_queried_at=now())
    persist(receipt_path, record)
    if task['status'] in ('failed', 'expired', 'cancelled'):
        record.update(technical_status='failed', content_status='not_available')
        persist(receipt_path, record)
        media_event('seedance_task_failed', receipt_path, record['plan_snapshot'], failure=True, task_id=task_id)
    elif task['status'] == 'succeeded':
        try:
            for path_key, hash_key, filename, downloader in (
                ('video_path', 'video_sha256', 'S02.original.mp4', client.download_video),
                ('last_frame', 'last_frame_sha256', 'S02.provider_last.original', client.download_last_frame),
            ):
                if path_key in record:
                    if sha(record[path_key]) != record[hash_key]:
                        raise ValueError('previously saved S02 output changed')
                else:
                    path = downloader(task, out / filename)
                    if not path.stat().st_size:
                        raise ValueError('empty original provider output')
                    record.update({path_key: str(path.resolve()), hash_key: sha(path)})
                    persist(receipt_path, record)
            metadata = video_metadata(record['video_path'])
            encoding = last_frame_integrity(record['last_frame'])
            persist(out / 'FILE_INTEGRITY.json', dict(video_metadata=metadata, last_frame_encoding=encoding,
                                                     video_bytes=Path(record['video_path']).stat().st_size,
                                                     video_sha256=record['video_sha256'], last_frame_sha256=record['last_frame_sha256'],
                                                     pixels_inspected=False, audio_listened=False, asr=False))
            mark_saved_candidate(record)
            record.update(last_frame_format=encoding['format'], last_frame_source='generation_service_original',
                          next_segment_dispatch_allowed=False, human_decision=None, completed_at=now())
        except Exception as exc:
            record.update(status='provider_succeeded_file_validation_pending', technical_status='file_validation_pending',
                          content_status='awaiting_human_review', error_type=type(exc).__name__, error_message=str(exc))
            persist(receipt_path, record)
            raise
        persist(receipt_path, record)
        media_event('seedance_saved_awaiting_human_review', receipt_path, record['plan_snapshot'], task_id=task_id)
    return {k: record.get(k) for k in ('status', 'task_id', 'technical_status', 'content_status', 'video_path', 'last_frame')}
