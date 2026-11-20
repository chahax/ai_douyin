"""The authorized S03–S12 batch: serial native tails, one POST per segment."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import msvcrt
import os
from pathlib import Path
import time

from .assistant_seedance_trial import (
    OUT as S01_OUT, ROOT, SOURCE, STORY_ID, STORY_LEDGER, bound, last_frame_integrity,
    now, read, sha, video_metadata,
)
from .creative_stage_contracts import digest, persist
from .media_review_policy import mark_saved_candidate
from .seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceReference

OUT = S01_OUT / 'batch_remaining'
IDS = [f'S{i:02d}' for i in range(3, 13)]
BATCH_ID = 'assistant_seedance_screenplay_remaining_20261016'
INITIAL_TASK = 'cgt-20261016095408-f94dt'
INITIAL_TAIL = '3b3c7848de6adae6a88a993d26c4a5edf54e3e970a960744da813b737877270e'
USER_STATEMENT = '继续可以直接流程全部生成完看看'


@contextmanager
def process_lock(path):
    """OS lock releases on process exit; durable submission claims never do."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'1')
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def durable(path, value, *, immutable=False):
    path = Path(path)
    data = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if immutable and path.exists():
        if read(path) != value:
            raise ValueError('immutable batch artifact changed: ' + path.name)
        return
    temporary = path if immutable else path.with_name(path.name + '.tmp')
    with temporary.open('x' if immutable else 'w', encoding='utf-8') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if not immutable:
        for attempt in range(20):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)


def log(out, event, **fields):
    with (out / 'LOG.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(dict(at=now(), event=event, **fields), ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    visible = {key: value for key, value in fields.items() if key in ('segment_id', 'task_id', 'segments', 'next_segment')}
    print(json.dumps(dict(event=event, **visible), ensure_ascii=False), flush=True)


def check_client(client):
    if (client.config.provider != 'ark_api' or client.config.model != ARK_MINI_MODEL
            or client.config.base_url.rstrip('/') != ARK_BASE_URL):
        raise ValueError('configured provider/model/endpoint changed; no fallback')


def file_row(path, segment_id):
    record = read(path)
    if (record.get('segment_id') != segment_id or record.get('technical_status') != 'succeeded'
            or record.get('content_status') != 'awaiting_human_review' or not record.get('task_id')):
        raise ValueError('predecessor is not a technically saved pending-human-review segment')
    if sha(record['video_path']) != record['video_sha256'] or sha(record['last_frame']) != record['last_frame_sha256']:
        raise ValueError('saved original predecessor files changed')
    last_frame_integrity(record['last_frame'])
    keys = ('task_id', 'video_path', 'video_sha256', 'last_frame', 'last_frame_sha256', 'technical_status', 'content_status')
    return dict(segment_id=segment_id, receipt=dict(path=str(Path(path).resolve()), sha256=sha(path)),
                **{key: record[key] for key in keys}, predecessor=record.get('predecessor'),
                first_frame=record.get('first_frame') or record.get('plan_snapshot', {}).get('first_frame'))


def history_count(plan, out, *, dispatch):
    history = plan['history']
    if (history.get('reset') is not False or history.get('failure_limit') != 10
            or Path(history['legacy_ledger']['path']).resolve() != STORY_LEDGER.resolve()):
        raise ValueError('same-story history identity/reset differs')
    if dispatch:
        bound(history['legacy_ledger'])
    legacy = read(STORY_LEDGER)
    count = legacy.get('failures_used')
    if type(count) is not int or count < 0 or legacy.get('failure_limit') != 10 or legacy.get('story_id') != STORY_ID:
        raise ValueError('unknown or invalid historical failure count')
    if len(history['prior_media_events']) != 2:
        raise ValueError('both S01 and S02 histories must be retained')
    for binding, expected in zip(history['prior_media_events'], (S01_OUT / 'MEDIA_EVENTS.json', S01_OUT / 'S02/MEDIA_EVENTS.json')):
        if Path(binding['path']).resolve() != expected.resolve():
            raise ValueError('wrong prior media history')
        if dispatch:
            bound(binding)
        events = read(binding['path'])
        if events.get('story_id') != STORY_ID:
            raise ValueError('prior media story identity differs')
        if 'trial_technical_failures' in events:
            additional = events['trial_technical_failures']
        else:
            combined, inherited = events.get('combined_known_failures'), events.get('inherited_failures')
            if type(combined) is not int or type(inherited) is not int or not 0 <= inherited <= combined:
                raise ValueError('prior media failures lack known evidence; unknown cannot count as zero')
            additional = combined - inherited
        if type(additional) is not int or additional < 0:
            raise ValueError('unknown prior media failures cannot count as zero')
        count += additional
    if dispatch and count != history['known_failures_at_prepare']:
        raise ValueError('historical failure count changed since preparation')
    current = out / 'MEDIA_EVENTS.json'
    if current.exists():
        count += sum(int(event.get('failure') is True) for event in read(current)['events'])
    if dispatch:
        if count >= 10:
            raise ValueError('same-story failure limit exhausted')
        for sid in IDS:
            directory = out / 'segments' / sid
            if (directory / 'SUBMISSION_CLAIM.json').exists():
                if not (directory / 'receipt.json').exists():
                    raise ValueError('claim without known receipt; do not dispatch')
                prior = read(directory / 'receipt.json')
                if prior.get('technical_status') != 'succeeded':
                    raise ValueError('prior failed/pending/unknown claim blocks any new dispatch')
    return count


def validate_plan(out):
    plan = read(out / 'BATCH_PLAN.json')
    expected = dict(schema='assistant_seedance_remaining_batch_plan/v1', story_id=STORY_ID,
                    provider='ark_api', model=ARK_MINI_MODEL, resolution='720p', ratio='16:9',
                    duration_seconds=15, generate_audio=True, return_last_frame=True, max_new_submissions=10,
                    automatic_retries=0, review_status='awaiting_human_review', external_text_model_calls=0)
    if any(plan.get(k) != v or type(plan.get(k)) is not type(v) for k, v in expected.items()):
        raise ValueError('batch identity/parameters/limits differ')
    authorization = read(bound(plan['authorization']))
    required = dict(schema='assistant_seedance_batch_authorization/v1', story_id=STORY_ID,
                    user_statement=USER_STATEMENT, new_segments=IDS, max_new_video_submissions=10,
                    max_submissions_per_segment=1, automatic_retry=False,
                    automatic_model_or_resolution_fallback=False, publishing_authorized=False,
                    external_text_model_calls_authorized=False, old_failures_or_budgets_reset=False,
                    allow_service_original_tail_continuation_before_individual_content_review=True,
                    review_mode='all_segments_and_complete_film_human_review_after_batch',
                    allow_assembly_of_S01_to_S12_for_review=True, human_content_approval=False)
    if any(authorization.get(k) != v or type(authorization.get(k)) is not type(v) for k, v in required.items()):
        raise ValueError('batch authorization scope differs')
    if authorization['screenplay'] != plan['screenplay'] or bound(plan['screenplay']) != (SOURCE / 'FULL_SCREENPLAY.md').resolve():
        raise ValueError('batch screenplay identity differs')
    script = Path(plan['screenplay']['path']).read_text(encoding='utf-8')
    if [row.get('segment_id') for row in plan['segments']] != IDS:
        raise ValueError('batch must contain exactly S03 through S12 in order')
    for index, segment in enumerate(plan['segments'], 3):
        sid = segment['segment_id']
        if (segment.get('ordinal') != index or segment.get('duration_seconds') != 15
                or segment.get('predecessor_segment_id') != f'S{index - 1:02d}'):
            raise ValueError('segment order/timing/predecessor differs')
        source = bound(segment['source'])
        prompt = bound(segment['prompt'])
        if source != out / 'segments' / sid / 'SOURCE.md' or prompt != out / 'segments' / sid / 'PROMPT.txt':
            raise ValueError('segment source/prompt paths differ')
        start = script.index('### ' + sid + '｜')
        end = script.index('### ' + f'S{index + 1:02d}' + '｜') if index < 12 else script.index('\n## ', start)
        text = source.read_text(encoding='utf-8').strip()
        prompt_text = prompt.read_text(encoding='utf-8').strip()
        if text != script[start:end].strip() or not prompt_text:
            raise ValueError('segment source is not the exact full-screenplay section')
        if not segment.get('dialogue') or any(line not in text or line not in prompt_text for line in segment['dialogue']):
            raise ValueError('source dialogue omitted or changed in the request prompt')
    if [row.get('segment_id') for row in plan['existing_segments']] != ['S01', 'S02']:
        raise ValueError('existing segment identities differ')
    for row in plan['existing_segments']:
        record = file_row(bound(row['receipt']), row['segment_id'])
        if (record['task_id'] != row['task_id'] or bound(row['video']) != Path(record['video_path']).resolve()
                or bound(row['native_tail']) != Path(record['last_frame']).resolve()):
            raise ValueError('existing task/video/native tail binding differs')
    initial = plan['existing_segments'][1]
    if initial['task_id'] != INITIAL_TASK or initial['native_tail']['sha256'] != INITIAL_TAIL:
        raise ValueError('batch must begin from the saved Seedance S02 native tail')
    return plan


def request_for(client, segment, predecessor, frame):
    check_client(client)
    if sha(frame) != predecessor['last_frame_sha256']:
        raise ValueError('input bytes do not match predecessor service-native tail')
    info = last_frame_integrity(frame)
    mime = 'image/jpeg' if info['format'] == 'jpeg' else 'image/png'
    raw = Path(frame).read_bytes()
    url = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')
    request = client.build_task_payload(Path(bound(segment['prompt'])).read_text(encoding='utf-8').strip(), duration=15,
                                        ratio='16:9', resolution='720p', generate_audio=True, return_last_frame=True,
                                        watermark=False, references=[SeedanceReference('image', url, 'first_frame')], task_type='first_frame')
    preview = {key: value for key, value in request.items() if key != 'content'}
    preview['content'] = [request['content'][0], dict(type='image_url', role='first_frame', mime=mime,
                                                   source_task_id=predecessor['task_id'], sha256=sha(frame), bytes=len(raw),
                                                   url_sha256=hashlib.sha256(url.encode()).hexdigest())]
    return request, preview


def prepare_segment(out, plan, segment, predecessor, frame, client):
    directory = out / 'segments' / segment['segment_id']
    request, preview = request_for(client, segment, predecessor, frame)
    binding = dict(batch_plan_sha256=sha(out / 'BATCH_PLAN.json'), authorization=plan['authorization'],
                   segment=segment, predecessor=predecessor, request_sha256=digest(request),
                   preview_sha256=digest(preview), first_frame_sha256=predecessor['last_frame_sha256'])
    durable(directory / 'REQUEST.actual.json', request, immutable=True)
    durable(directory / 'REQUEST.preview.json', dict(bindings=binding, request=preview), immutable=True)
    return request, binding


def prepare(out, client):
    plan = validate_plan(out)
    history_count(plan, out, dispatch=True)
    initial = plan['existing_segments'][1]
    predecessor = file_row(initial['receipt']['path'], 'S02')
    request, binding = prepare_segment(out, plan, plan['segments'][0], predecessor, predecessor['last_frame'], client)
    manifest = dict(schema='assistant_seedance_batch_frozen/v1', batch_id=BATCH_ID,
                    plan_sha256=sha(out / 'BATCH_PLAN.json'), plan_digest=digest(plan), plan_snapshot=plan)
    durable(out / 'BATCH_FROZEN.json', manifest, immutable=True)
    durable(out / 'REQUEST_TEMPLATE.json', dict(model=ARK_MINI_MODEL, duration=15, resolution='720p', ratio='16:9',
                                               generate_audio=True, return_last_frame=True, input_role='first_frame',
                                               reference_count=1, max_new_submissions=10, automatic_retry=False,
                                               review_mode='all_segments_and_complete_film_human_review_after_batch'), immutable=True)
    return dict(status='prepared_not_submitted', first_segment='S03', request_sha256=digest(request))


def event(out, sid, kind, *, failure=False, task_id=None):
    path = out / 'MEDIA_EVENTS.json'
    row = read(path) if path.exists() else dict(story_id=STORY_ID, batch_id=BATCH_ID, events=[])
    if any(e['segment_id'] == sid and e['kind'] == kind for e in row['events']):
        return
    row['events'].append(dict(at=now(), segment_id=sid, kind=kind, failure=failure, task_id=task_id))
    durable(path, row)
    log(out, kind, segment_id=sid, task_id=task_id)


def register_id(out, directory, claim):
    response_path = directory / 'CREATE_RESPONSE.json'
    if not response_path.exists():
        raise ValueError('submission claim has no known original task ID; reconcile, never resubmit')
    response = read(response_path)
    task_id = response.get('response', {}).get('id')
    if (response.get('claim_sha256') != sha(directory / 'SUBMISSION_CLAIM.json')
            or response.get('request_sha256') != claim['request_sha256'] or not isinstance(task_id, str)
            or not task_id or not all(c.isalnum() or c in '-_' for c in task_id)):
        raise ValueError('original create response identity is incomplete or changed')
    binding = dict(task_id=task_id, claim_sha256=sha(directory / 'SUBMISSION_CLAIM.json'),
                   create_response_sha256=sha(response_path))
    durable(directory / 'TASK_ID.json', binding, immutable=True)
    path = out / 'job_ids.json'
    jobs = read(path) if path.exists() else dict(schema='assistant_seedance_batch_job_ids/v1', batch_id=BATCH_ID, jobs={})
    sid = claim['segment_id']
    entry = dict(task_id=task_id, claim_sha256=binding['claim_sha256'], receipt=str(directory / 'receipt.json'))
    if sid in jobs['jobs'] and jobs['jobs'][sid] != entry:
        raise ValueError('segment already has another original task identity')
    if sid not in jobs['jobs']:
        jobs['jobs'][sid] = entry
        durable(path, jobs)
        log(out, 'original_task_id_saved', segment_id=sid, task_id=task_id)
    return task_id


def current_native_source(out, segment, predecessor, client):
    directory = out / 'segments' / segment['segment_id']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    task = client.get_task(predecessor['task_id'])
    source_get = directory / ('PREDECESSOR_SERVICE_GET.' + stamp + '.json')
    durable(source_get, task, immutable=True)
    if (task.get('id') != predecessor['task_id'] or task.get('status') != 'succeeded'
            or task.get('model') != ARK_MINI_MODEL
            or not str(task.get('content', {}).get('last_frame_url', '')).startswith('https://')):
        raise ValueError('current credentials did not return the succeeded predecessor native-tail source')
    downloaded = client.download_last_frame(task, directory / ('FIRST_FRAME.service_original.' + stamp))
    if sha(downloaded) != predecessor['last_frame_sha256']:
        raise ValueError('fresh service-original predecessor tail differs from the saved native bytes')
    last_frame_integrity(downloaded)
    proof = dict(service_get=dict(path=str(source_get), sha256=sha(source_get)),
                 downloaded_original=dict(path=str(downloaded), sha256=sha(downloaded)),
                 predecessor=predecessor, current_credential_get_succeeded=True,
                 posthoc_extraction=False, pixel_decoding=False)
    proof_path = directory / ('NATIVE_TAIL_SOURCE.' + stamp + '.json')
    durable(proof_path, proof, immutable=True)
    return downloaded, dict(path=str(proof_path), sha256=sha(proof_path))


def submit_one(out, plan, segment, predecessor, client):
    directory = out / 'segments' / segment['segment_id']
    if (out / 'STOP_REQUESTED.json').exists():
        log(out, 'user_stop_checkpoint', next_segment=segment['segment_id'])
        raise ValueError('user stop requested; no new POST dispatched')
    frame, source_evidence = current_native_source(out, segment, predecessor, client)
    request, binding = prepare_segment(out, plan, segment, predecessor, frame, client)
    sid = segment['segment_id']
    with process_lock(STORY_LEDGER.with_suffix('.batch_dispatch.lock')):
        validate_plan(out)
        known_failures = history_count(plan, out, dispatch=True)
        if (out / 'STOP_REQUESTED.json').exists():
            log(out, 'user_stop_checkpoint', next_segment=sid)
            raise ValueError('user stop requested; no new POST dispatched')
        claims = list((out / 'segments').glob('S*/SUBMISSION_CLAIM.json'))
        if len(claims) >= 10:
            raise ValueError('ten new submission slots already consumed')
        claim_path = directory / 'SUBMISSION_CLAIM.json'
        if claim_path.exists():
            raise ValueError('segment already claimed; only original-ID recovery is permitted')
        marker = STORY_LEDGER.parent / (BATCH_ID + '.' + sid + '.dispatch_claim.json')
        if marker.exists():
            raise ValueError('story-wide segment claim already exists; changing directories cannot reset it')
        claim = dict(schema='assistant_seedance_batch_segment_claim/v1', batch_id=BATCH_ID, segment_id=sid,
                     created_at=now(), source_evidence=source_evidence, known_story_failures=known_failures, **binding)
        # These durable exclusive files are written before the POST; a crash cannot free the slot.
        durable(claim_path, claim, immutable=True)
        durable(marker, dict(claim_path=str(claim_path), claim_sha256=sha(claim_path)), immutable=True)
        record = dict(schema='assistant_seedance_batch_segment_receipt/v1', batch_id=BATCH_ID, segment_id=sid,
                      logical_task_id=STORY_ID, provider='ark_api', model=ARK_MINI_MODEL,
                      status='submitting', technical_status='unknown', content_status='not_available',
                      claim_sha256=sha(claim_path), predecessor=predecessor,
                      first_frame=dict(path=str(frame), sha256=sha(frame), source_task_id=predecessor['task_id']),
                      source_evidence=source_evidence, request_sha256=binding['request_sha256'],
                      batch_plan_sha256=binding['batch_plan_sha256'], source_bindings=dict(screenplay=plan['screenplay']),
                      voice_reference_status='unbound')
        durable(directory / 'receipt.json', record)
        event(out, sid, 'dispatch_reserved')
    if (out / 'STOP_REQUESTED.json').exists():
        record.update(status='user_stopped_before_post', technical_status='not_submitted')
        durable(directory / 'receipt.json', record)
        log(out, 'user_stop_checkpoint', next_segment=sid, claim_preserved=True, post_dispatched=False)
        raise ValueError('user stop arrived before POST; claim preserved for reconciliation')
    try:
        created = client.create_task(request)
    except Exception as exc:
        http_status = getattr(exc, 'status_code', None)
        rejected = isinstance(http_status, int) and 400 <= http_status < 500
        record.update(status='request_rejected' if rejected else 'submit_outcome_unknown',
                      technical_status='failed' if rejected else 'unknown', error_type=type(exc).__name__,
                      error_message=str(exc), http_status=http_status, error_code=getattr(exc, 'error_code', None))
        durable(directory / 'receipt.json', record)
        event(out, sid, record['status'], failure=rejected)
        raise ValueError(record['status'] + '; no automatic new task') from None
    durable(directory / 'CREATE_RESPONSE.json', dict(response=created, claim_sha256=sha(claim_path),
                                                     request_sha256=binding['request_sha256']), immutable=True)
    task_id = register_id(out, directory, claim)
    record.update(task_id=task_id, status='submitted', technical_status='running')
    durable(directory / 'receipt.json', record)
    event(out, sid, 'submitted', task_id=task_id)
    return record


def recover_record(out, directory):
    claim = read(directory / 'SUBMISSION_CLAIM.json')
    if (claim.get('batch_id') != BATCH_ID or claim.get('segment_id') != directory.name
            or digest(read(directory / 'REQUEST.actual.json')) != claim['request_sha256']):
        raise ValueError('saved original claim/request identity differs')
    record = read(directory / 'receipt.json')
    if (record.get('claim_sha256') != sha(directory / 'SUBMISSION_CLAIM.json')
            or record.get('request_sha256') != claim['request_sha256']
            or record.get('predecessor') != claim['predecessor']):
        raise ValueError('saved receipt differs from original claim')
    if record.get('technical_status') == 'failed':
        raise ValueError('known service failure; no automatic retry or new candidate')
    task_id = register_id(out, directory, claim)
    if record.get('task_id', task_id) != task_id:
        raise ValueError('original task ID differs')
    record.update(task_id=task_id)
    durable(directory / 'receipt.json', record)
    return record


def query_until_saved(out, directory, record, client, *, wait_timeout, poll_seconds):
    deadline = time.monotonic() + wait_timeout
    task_id = record['task_id']
    while True:
        task = client.get_task(task_id)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        durable(directory / ('QUERY.' + stamp + '.json'), task, immutable=True)
        if task.get('id') != task_id:
            raise ValueError('query returned another original task identity')
        record.update(status=task['status'], latest_response=task, last_queried_at=now())
        durable(directory / 'receipt.json', record)
        if task['status'] in ('failed', 'expired', 'cancelled'):
            record.update(technical_status='failed', content_status='not_available')
            durable(directory / 'receipt.json', record)
            event(out, directory.name, 'task_failed', failure=True, task_id=task_id)
            raise ValueError('service task failed; batch stopped without retry')
        if task['status'] == 'succeeded':
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('original task still pending; resume queries this ID only')
        time.sleep(poll_seconds)
    for path_key, hash_key, filename, downloader in (
        ('video_path', 'video_sha256', directory.name + '.original.mp4', client.download_video),
        ('last_frame', 'last_frame_sha256', directory.name + '.provider_last.original', client.download_last_frame),
    ):
        if path_key in record:
            if sha(record[path_key]) != record[hash_key]:
                raise ValueError('saved original provider file changed')
        else:
            path = downloader(task, directory / filename)
            if not path.stat().st_size:
                raise ValueError('empty original provider output')
            record.update({path_key: str(path.resolve()), hash_key: sha(path)})
            durable(directory / 'receipt.json', record)
    metadata, encoding = video_metadata(record['video_path']), last_frame_integrity(record['last_frame'])
    durable(directory / 'FILE_INTEGRITY.json', dict(video_metadata=metadata, last_frame_encoding=encoding,
                                                   video_bytes=Path(record['video_path']).stat().st_size,
                                                   video_sha256=record['video_sha256'], last_frame_sha256=record['last_frame_sha256'],
                                                   pixels_inspected=False, audio_listened=False, asr=False))
    mark_saved_candidate(record)
    record.update(last_frame_format=encoding['format'], last_frame_source='generation_service_original',
                  next_segment_dispatch_authority='this_frozen_batch_only_until_S12', human_decision=None, completed_at=now())
    durable(directory / 'receipt.json', record)
    event(out, directory.name, 'saved_awaiting_human_review', task_id=task_id)
    return file_row(directory / 'receipt.json', directory.name)


def run(out, client, *, wait_timeout=1800, poll_seconds=20):
    check_client(client)
    frozen = read(out / 'BATCH_FROZEN.json')
    plan = frozen['plan_snapshot']
    if digest(plan) != frozen['plan_digest']:
        raise ValueError('frozen batch source identity changed')
    rows = [file_row(row['receipt']['path'], row['segment_id']) for row in plan['existing_segments']]
    predecessor = rows[-1]
    for segment in plan['segments']:
        sid = segment['segment_id']
        directory = out / 'segments' / sid
        claim_path = directory / 'SUBMISSION_CLAIM.json'
        if claim_path.exists():
            record = recover_record(out, directory)
            if record['predecessor'] != predecessor:
                raise ValueError('claimed predecessor is not the immediately previous saved segment')
            if record.get('technical_status') == 'succeeded':
                predecessor = file_row(directory / 'receipt.json', sid)
                rows.append(predecessor)
                continue
        else:
            if (directory / 'receipt.json').exists():
                raise ValueError('receipt without its original claim; reconcile before dispatch')
            if sha(out / 'BATCH_PLAN.json') != frozen['plan_sha256'] or validate_plan(out) != plan:
                raise ValueError('source changed; only original-ID recovery is allowed')
            record = submit_one(out, plan, segment, predecessor, client)
        predecessor = query_until_saved(out, directory, record, client, wait_timeout=wait_timeout, poll_seconds=poll_seconds)
        rows.append(predecessor)
    chain = dict(schema='assistant_seedance_completed_file_chain/v1',
                 batch_plan=dict(path=str(out / 'BATCH_PLAN.json'), sha256=frozen['plan_sha256']),
                 authorization=plan['authorization'], segments=rows, content_status='awaiting_human_review')
    durable(out / 'COMPLETED_FILE_CHAIN.json', chain)
    log(out, 'batch_saved_awaiting_human_review', segments=len(rows))
    return dict(status='all_segments_saved_awaiting_human_review', completed_segments=len(rows), chain=str(out / 'COMPLETED_FILE_CHAIN.json'))


def execute(operation, client, out=OUT, *, wait_timeout=1800, poll_seconds=20):
    out = Path(out).resolve()
    if not math.isfinite(wait_timeout) or wait_timeout <= 0 or not math.isfinite(poll_seconds) or poll_seconds < 0:
        raise ValueError('invalid polling bounds')
    with process_lock(out / '.batch.lock'):
        try:
            if operation == 'prepare':
                return prepare(out, client)
            if operation != 'start':
                raise ValueError('unsupported batch operation')
            result = run(out, client, wait_timeout=wait_timeout, poll_seconds=poll_seconds)
            durable(out / 'BATCH_STATUS.json', result)
            return result
        except Exception as exc:
            if operation == 'start':
                durable(out / 'BATCH_STATUS.json', dict(status='stopped_needs_attention', error_type=type(exc).__name__,
                                                        error_message=str(exc), at=now(), automatic_retry=False))
                log(out, 'stopped_needs_attention', error_type=type(exc).__name__, error_message=str(exc))
            raise
