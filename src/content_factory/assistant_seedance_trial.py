"""One source-bound assistant screenplay trial; no text-model or retry path."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import zlib

from .creative_stage_contracts import digest, persist
from .media_review_policy import mark_saved_candidate
from .seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceReference

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/video_generation/seedance_assistant_screenplay_20261016'
SOURCE = ROOT / 'data/video_generation/h3_project_script_20261015/revision_02/assistant_authored'
STORY_LEDGER = ROOT / 'data/video_generation/h3_project_script_20261015/STORY_VIDEO_FAILURE_LEDGER.json'
STORY_ID = 'legal_scoped_call634_same_story'
TRIAL_ID = 'assistant_seedance_screenplay_20261016_S01'
USER_STATEMENT = '这个剧本用seedances生成个视频看看'
ACCOUNT_PENDING = 'not_independently_proven_locally; provider adjudication pending'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def bound(binding):
    path = Path(binding['path']).resolve()
    if sha(path) != binding['sha256']:
        raise ValueError('bound source/artifact changed')
    return path


@contextmanager
def exclusive(path):
    with path.open('x', encoding='utf-8') as handle:
        handle.write(now())
        handle.flush()
    try:
        yield
    finally:
        path.unlink()


def validate(plan_path):
    plan = read(plan_path)
    if plan.get('schema') != 'assistant_seedance_single_segment_plan/v1':
        raise ValueError('wrong trial plan schema')
    expected = dict(story_id=STORY_ID, segment_id='S01', provider='ark_api', model=ARK_MINI_MODEL,
                    duration_seconds=15, resolution='720p', ratio='16:9', generate_audio=True,
                    return_last_frame=True)
    if any(plan.get(key) != value or type(plan.get(key)) is not type(value) for key, value in expected.items()):
        raise ValueError('trial identity or fixed generation parameters changed')
    if any(plan.get(key) for key in ('first_frame', 'previous_segment', 'use_previous_video_reference')):
        raise ValueError('only the three selected image references are permitted')
    auth = plan['authorization']
    required = dict(user_statement=USER_STATEMENT, max_new_submissions=1, automatic_retry=False,
                    continuation_authorized=False, publishing_authorized=False)
    if any(auth.get(key) != value or type(auth.get(key)) is not type(value) for key, value in required.items()):
        raise ValueError('single-trial authorization differs')
    for key, name in (('screenplay', 'FULL_SCREENPLAY.md'), ('first_segment', 'FIRST_SEGMENT.json')):
        if bound(plan['sources'][key]) != (SOURCE / name).resolve():
            raise ValueError('trial must use the exact assistant-authored source paths')
    segment = read(SOURCE / 'FIRST_SEGMENT.json')
    if (segment.get('authored_by') != 'primary_assistant' or segment['segment']['id'] != 'S01'
            or segment['segment']['duration_seconds'] != 15):
        raise ValueError('source is not the selected assistant-authored S01')
    prompt = bound(plan['prompt']).read_text(encoding='utf-8').strip()
    if not prompt:
        raise ValueError('empty prompt')
    counter = plan['story_counter']
    if bound(counter) != STORY_LEDGER.resolve() or counter.get('reset') is not False:
        raise ValueError('same-story failure ledger binding differs or resets history')
    ledger = read(STORY_LEDGER)
    if (ledger.get('story_id') != STORY_ID or ledger.get('failure_limit') != 10
            or counter.get('failure_limit') != 10 or counter.get('failures_used') != ledger.get('failures_used')
            or not isinstance(ledger.get('failures_used'), int) or not 0 <= ledger['failures_used'] < 10):
        raise ValueError('same-story failure limit exhausted or changed')
    admission = read(bound(plan['source_admission']))
    if (admission.get('schema') != 'assistant_seedance_reference_admission/v1'
            or admission.get('status') != 'eligible_candidate_for_single_service_trial'):
        raise ValueError('source eligibility has not been confirmed for this single service trial')
    refs = plan['references']
    rows = admission['references']
    if len(refs) != 3 or len(rows) != 3 or [item.get('subject_id') for item in refs] != ['space', 'C01', 'C02']:
        raise ValueError('reference order must be space, C01, C02')
    for index, (item, row) in enumerate(zip(refs, rows)):
        image = bound(item['image'])
        receipt = read(bound(item['provenance']))
        if row.get('asset_id') != item['asset_id'] or row.get('image_sha256') != item['image']['sha256']:
            raise ValueError('admission reference identity differs')
        if index == 0:
            asset = receipt.get('asset', {})
            if (row.get('kind') != 'static_background'
                    or item['asset_id'] != 'h3.scene.supermarket_backroom.20261015.v2'
                    or receipt.get('schema') != 'local_h3_native_image_asset_receipt/v1'
                    or receipt.get('execution_success') is not True
                    or receipt.get('posthoc_mp4_frame_extraction') is not False
                    or asset.get('asset_id') != item['asset_id']
                    or asset.get('sha256') != item['image']['sha256']
                    or Path(asset.get('path', '')).resolve() != image):
                raise ValueError('only the selected static background exception is allowed')
            continue
        created = receipt.get('provider_created')
        if (receipt.get('status') != 'downloaded'
                or receipt.get('model') != 'doubao-seedream-5-0-pro-260628'
                or receipt.get('usage', {}).get('input_images') != 0
                or type(receipt.get('usage', {}).get('input_images')) is not int
                or receipt.get('reference_image') is not None
                or receipt.get('image_sha256') != item['image']['sha256']
                or Path(receipt.get('image', '')).resolve() != image
                or not isinstance(created, (int, float)) or isinstance(created, bool)
                or not 0 <= datetime.now(timezone.utc).timestamp() - created <= 30 * 86400):
            raise ValueError('portrait is not a fresh original Seedream text-to-image artifact')
        generated_at = row.get('generated_at')
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at.replace('Z', '+00:00')).timestamp()
        if (row.get('kind') != 'seedream_portrait_candidate'
                or row.get('origin') != 'ark_seedream_text2image_original' or row.get('original') is not True
                or 'same_account' not in row or row['same_account'] is not None
                or row.get('same_account_verification') != ACCOUNT_PENDING
                or row.get('model') != receipt['model'] or generated_at != created):
            raise ValueError('portrait candidate provenance/account uncertainty differs')
        parentage = row['identity_parentage']
        board = read(bound(parentage['board_receipt']))
        character = next(c for c in segment['world_current']['characters'] if c['id'] == item['subject_id'])
        if (parentage['script_reference_sha256'] != character['reference_sha256']
                or board.get('sha256') != parentage['script_reference_sha256']
                or sha(board['image']) != board['sha256']):
            raise ValueError('script board identity lineage changed')
        parents = [entry for entry in board.get('actual_reference_images', []) if entry.get('role') == 'identity']
        if len(parents) != 1 or parents[0].get('sha256') != item['image']['sha256'] or Path(parents[0]['path']).resolve() != image:
            raise ValueError('selected original is not the exact script board identity parent')
        bound(row['historical_review'])
        # Additional evidence remains source-bound without requiring an old quality approval.
        for binding in row.get('evidence', []):
            bound(binding)
    return plan, prompt


def request_for(client, plan, prompt):
    if (client.config.provider != 'ark_api' or client.config.model != ARK_MINI_MODEL
            or client.config.base_url.rstrip('/') != ARK_BASE_URL):
        raise ValueError('configured provider/model/endpoint differs; no automatic switch')
    refs = []
    reference_rows = []
    admission = read(bound(plan['source_admission']))
    for item, admitted in zip(plan['references'], admission['references']):
        path = bound(item['image'])
        data = path.read_bytes()
        if data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        else:
            raise ValueError('reference is not an original JPEG/PNG byte stream')
        url = 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')
        if hashlib.sha256(url.encode()).hexdigest() != admitted.get('url_sha256'):
            raise ValueError('actual original-byte reference differs from admitted data URL')
        refs.append(SeedanceReference('image', url, 'reference_image'))
        reference_rows.append(dict(subject_id=item['subject_id'], asset_id=item['asset_id'],
                                   sha256=item['image']['sha256'], bytes=len(data), mime=mime,
                                   url_sha256=hashlib.sha256(url.encode()).hexdigest()))
    payload = client.build_task_payload(prompt, duration=15, resolution='720p', ratio='16:9',
                                        generate_audio=True, return_last_frame=True, watermark=False,
                                        references=refs, task_type='reference')
    preview = {key: value for key, value in payload.items() if key != 'content'}
    preview['content'] = [payload['content'][0]] + [dict(type='image_url', role='reference_image', **row) for row in reference_rows]
    return payload, preview


def story_event(kind, receipt_path, *, failure=False, task_id=None):
    with exclusive(STORY_LEDGER.with_suffix('.dispatch.lock')):
        ledger = read(STORY_LEDGER)
        if ledger.get('story_id') != STORY_ID or ledger.get('failure_limit') != 10:
            raise ValueError('same-story failure ledger identity changed')
        events_path = Path(receipt_path).parent / 'MEDIA_EVENTS.json'
        event_record = read(events_path) if events_path.exists() else dict(story_id=STORY_ID, inherited_failures=ledger['failures_used'], failure_limit=10, events=[])
        events = event_record['events']
        if any(event.get('trial_id') == TRIAL_ID and event.get('kind') == kind for event in events):
            if kind == 'seedance_dispatch_reserved':
                raise ValueError('this single trial already has a story-wide dispatch reservation')
            return
        if kind == 'seedance_dispatch_reserved' and ledger['failures_used'] >= 10:
            raise ValueError('same-story failure limit exhausted; no reset')
        if kind == 'seedance_dispatch_reserved':
            # The story-wide marker prevents moving the output directory to reclaim this trial.
            marker = STORY_LEDGER.parent / (TRIAL_ID + '.dispatch_claim.json')
            with marker.open('x', encoding='utf-8') as handle:
                json.dump(dict(trial_id=TRIAL_ID, receipt=str(receipt_path), at=now()), handle)
                handle.flush()
                os.fsync(handle.fileno())
        events.append(dict(at=now(), kind=kind, trial_id=TRIAL_ID, provider='ark_api',
                           receipt=str(receipt_path), task_id=task_id, content_review=None))
        if failure:
            event_record['trial_technical_failures'] = event_record.get('trial_technical_failures', 0) + 1
        event_record['combined_known_failures'] = ledger['failures_used'] + event_record.get('trial_technical_failures', 0)
        event_record['historical_ledger_path'] = str(STORY_LEDGER)
        event_record['historical_ledger_sha256'] = sha(STORY_LEDGER)
        event_record['historical_ledger_unchanged'] = True
        persist(events_path, event_record)


def png_integrity(path):
    """Validate PNG framing/CRCs only; never decode or inspect image pixels."""
    with Path(path).open('rb') as stream:
        if stream.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError('provider last frame is not PNG')
        dimensions = None
        idat = False
        chunks = 0
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError('truncated PNG chunk header')
            length, kind = struct.unpack('>I4s', header)
            if length > Path(path).stat().st_size:
                raise ValueError('PNG chunk length exceeds file')
            data, checksum = stream.read(length), stream.read(4)
            if len(data) != length or len(checksum) != 4 or zlib.crc32(kind + data) != struct.unpack('>I', checksum)[0]:
                raise ValueError('PNG chunk truncated or CRC mismatch')
            chunks += 1
            if chunks == 1:
                if kind != b'IHDR' or length != 13:
                    raise ValueError('PNG lacks initial IHDR')
                dimensions = struct.unpack('>II', data[:8])
                if min(dimensions) <= 0:
                    raise ValueError('invalid PNG dimensions')
            idat = idat or kind == b'IDAT'
            if kind == b'IEND':
                if length or not idat or stream.read(1):
                    raise ValueError('invalid PNG end framing')
                break
    return dict(width=dimensions[0], height=dimensions[1], chunks=chunks, crc_valid=True, pixel_decoding=False)


def jpeg_integrity(path):
    """Check JPEG marker framing, SOF/SOS headers and EOI without pixel decoding."""
    data = Path(path).read_bytes()
    if data[:2] != b'\xff\xd8':
        raise ValueError('provider last frame is not JPEG')
    position, scans, entropy_bytes = 2, 0, 0
    dimensions = None
    components = 0
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while position < len(data):
        if data[position] != 0xFF:
            raise ValueError('invalid JPEG marker framing')
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise ValueError('truncated JPEG marker')
        marker = data[position]
        position += 1
        if marker == 0xD9:
            if dimensions is None or not scans or not entropy_bytes or position != len(data):
                raise ValueError('invalid JPEG EOI framing or missing image scan')
            return dict(format='jpeg', width=dimensions[0], height=dimensions[1], scans=scans,
                        encoding_structure_valid=True, eoi_present=True, pixel_decoding=False)
        if marker == 0x01:
            continue
        if marker in {0x00, 0xD8} or 0xD0 <= marker <= 0xD7 or position + 2 > len(data):
            raise ValueError('invalid or truncated JPEG marker')
        length = struct.unpack('>H', data[position:position + 2])[0]
        if length < 2 or position + length > len(data):
            raise ValueError('truncated JPEG marker segment')
        body = data[position + 2:position + length]
        position += length
        if marker in sof_markers:
            if len(body) < 6:
                raise ValueError('truncated JPEG SOF')
            height, width, components = struct.unpack('>HHB', body[1:6])
            if not width or not height or not components or len(body) != 6 + 3 * components:
                raise ValueError('invalid JPEG SOF dimensions/components')
            dimensions = width, height
        if marker != 0xDA:
            continue
        if dimensions is None or not body or not 1 <= body[0] <= components or len(body) != 4 + 2 * body[0]:
            raise ValueError('invalid JPEG SOS header')
        scans += 1
        while position < len(data):
            if data[position] != 0xFF:
                entropy_bytes += 1
                position += 1
                continue
            start = position
            while position < len(data) and data[position] == 0xFF:
                position += 1
            if position >= len(data):
                raise ValueError('truncated JPEG entropy marker')
            if data[position] == 0x00 or 0xD0 <= data[position] <= 0xD7:
                entropy_bytes += 1
                position += 1
                continue
            position = start
            break
    raise ValueError('truncated JPEG: missing EOI')


def last_frame_integrity(path):
    with Path(path).open('rb') as handle:
        signature = handle.read(8)
    if signature.startswith(b'\xff\xd8'):
        return jpeg_integrity(path)
    if signature == b'\x89PNG\r\n\x1a\n':
        return dict(format='png', **png_integrity(path))
    raise ValueError('provider last frame is neither native JPEG nor PNG')


def video_metadata(path):
    command = ['ffprobe', '-v', 'error', '-count_packets', '-show_entries',
               'format=duration,format_name,size:stream=index,codec_type,codec_name,width,height,nb_read_packets,duration',
               '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=120)
    if result.returncode:
        raise ValueError('ffprobe metadata/packet check failed')
    metadata = json.loads(result.stdout)
    video = [row for row in metadata.get('streams', []) if row.get('codec_type') == 'video']
    audio = [row for row in metadata.get('streams', []) if row.get('codec_type') == 'audio']
    if (len(video) != 1 or not audio or video[0].get('width') != 1280 or video[0].get('height') != 720
            or not 14 <= float(metadata['format']['duration']) <= 16
            or any(int(row.get('nb_read_packets', 0)) <= 0 for row in video + audio)):
        raise ValueError('saved container metadata/packet completeness differs from requested video')
    return metadata


def execute(operation, client, out=OUT):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with exclusive(out / '.execution.lock'):
        return _execute(operation, client, out)


def _execute(operation, client, out):
    plan_path, receipt_path = out / 'PLAN.json', out / 'receipt.json'
    claim_path = out / 'SUBMISSION_CLAIM.json'
    if operation in ('prepare', 'submit'):
        if claim_path.exists() or receipt_path.exists():
            raise ValueError('single trial already claimed; query original task only')
        plan, prompt = validate(plan_path)
        payload, preview = request_for(client, plan, prompt)
        binding = dict(plan_sha256=sha(plan_path), plan_digest=digest(plan), request_sha256=digest(payload),
                       preview_sha256=digest(preview), source_bindings=plan['sources'],
                       prompt_binding=plan['prompt'], admission_binding=plan['source_admission'])
        if operation == 'prepare':
            persist(out / 'REQUEST.actual.json', payload, immutable=True)
            persist(out / 'REQUEST.preview.json', dict(schema='assistant_seedance_request_preview/v1',
                                                      bindings=binding, request=preview), immutable=True)
            return dict(status='prepared_not_submitted', output=str(out), request_sha256=binding['request_sha256'])
        prepared = read(out / 'REQUEST.preview.json')
        if prepared['bindings'] != binding or prepared['request'] != preview or digest(read(out / 'REQUEST.actual.json')) != binding['request_sha256']:
            raise ValueError('actual request differs from source-bound prepared request')
        claim = dict(schema='assistant_seedance_single_submission_claim/v1', trial_id=TRIAL_ID,
                     created_at=now(), **binding)
        # Exclusive immutable claim is durable before any budget mutation or POST.
        with claim_path.open('x', encoding='utf-8') as handle:
            json.dump(claim, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        record = dict(schema='assistant_seedance_trial_receipt/v1', status='submitting',
                      technical_status='unknown', content_status='not_available', trial_id=TRIAL_ID,
                      logical_task_id=STORY_ID, segment_id='S01', provider='ark_api', model=ARK_MINI_MODEL,
                      claim_sha256=sha(claim_path), plan_snapshot=plan, **binding)
        persist(receipt_path, record)
        try:
            story_event('seedance_dispatch_reserved', receipt_path)
            latest, _ = validate(plan_path)
            if digest(latest) != binding['plan_digest']:
                raise ValueError('source-bound plan changed at dispatch admission')
        except Exception:
            record.update(status='blocked_before_submit', technical_status='not_submitted')
            persist(receipt_path, record)
            raise
        try:
            created = client.create_task(payload)
        except Exception as exc:
            status_code = getattr(exc, 'status_code', None)
            rejected = isinstance(status_code, int) and 400 <= status_code < 500
            record.update(status='request_rejected' if rejected else 'submit_outcome_unknown',
                          technical_status='failed' if rejected else 'unknown', error_type=type(exc).__name__,
                          http_status=status_code, error_code=getattr(exc, 'error_code', None),
                          error_message=str(exc))
            persist(receipt_path, record)
            story_event('seedance_request_rejected' if rejected else 'seedance_submit_outcome_unknown', receipt_path, failure=rejected)
            return dict(status=record['status'], technical_status=record['technical_status'])
        persist(out / 'CREATED.original.json', created, immutable=True)
        task_id = created.get('id')
        if not isinstance(task_id, str) or not task_id or not all(c.isalnum() or c in '-_' for c in task_id):
            record.update(status='submit_outcome_unknown', technical_status='unknown')
            persist(receipt_path, record)
            raise ValueError('no valid original task ID; reconcile without resubmitting')
        persist(out / 'TASK_ID.json', dict(task_id=task_id, claim_sha256=sha(claim_path),
                                         created_sha256=sha(out / 'CREATED.original.json')), immutable=True)
        record.update(status='submitted', task_id=task_id, technical_status='running')
        persist(receipt_path, record)
        story_event('seedance_submitted', receipt_path, task_id=task_id)
        return dict(status='submitted', task_id=task_id)
    if operation != 'query':
        raise ValueError('unsupported operation')
    record, claim = read(receipt_path), read(claim_path)
    task_binding = read(out / 'TASK_ID.json')
    if (task_binding['claim_sha256'] != sha(claim_path) or record['claim_sha256'] != sha(claim_path)
            or task_binding['created_sha256'] != sha(out / 'CREATED.original.json')
            or read(out / 'CREATED.original.json').get('id') != task_binding['task_id']
            or record.get('task_id', task_binding['task_id']) != task_binding['task_id']
            or digest(record['plan_snapshot']) != claim['plan_digest']
            or any(record[key] != claim[key] for key in ('plan_sha256', 'request_sha256', 'source_bindings', 'prompt_binding', 'admission_binding'))):
        raise ValueError('original task/claim/receipt identity differs')
    task_id = task_binding['task_id']
    if record.get('technical_status') == 'succeeded':
        if sha(record['video_path']) != record['video_sha256'] or sha(record['last_frame']) != record['last_frame_sha256']:
            raise ValueError('saved provider file changed')
        return dict(status=record['status'], task_id=task_id, video_path=record['video_path'], content_status=record['content_status'])
    # Query uses the original ID even if source files changed after submission.
    task = client.get_task(task_id)
    persist(out / ('QUERY.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'), task, immutable=True)
    if task.get('id') != task_id:
        raise ValueError('provider query returned another task identity')
    record.update(task_id=task_id, latest_response=task, last_queried_at=now(), status=task['status'])
    persist(receipt_path, record)
    if task['status'] in ('failed', 'expired', 'cancelled'):
        record.update(technical_status='failed', content_status='not_available')
        persist(receipt_path, record)
        story_event('seedance_task_failed', receipt_path, failure=True, task_id=task_id)
    elif task['status'] == 'succeeded':
        try:
            for path_key, hash_key, filename, downloader in (
                ('video_path', 'video_sha256', 'S01.original.mp4', client.download_video),
                ('last_frame', 'last_frame_sha256', 'S01.provider_last.png', client.download_last_frame),
            ):
                if path_key in record:
                    if sha(record[path_key]) != record[hash_key]:
                        raise ValueError('previously saved original output changed')
                else:
                    path = downloader(task, out / filename)
                    if not path.stat().st_size:
                        raise ValueError('empty original provider output')
                    record.update({path_key: str(path.resolve()), hash_key: sha(path)})
                    persist(receipt_path, record)
            metadata = video_metadata(record['video_path'])
            frame_encoding = last_frame_integrity(record['last_frame'])
            persist(out / 'FILE_INTEGRITY.json', dict(video_metadata=metadata, last_frame_encoding=frame_encoding,
                                                     video_bytes=Path(record['video_path']).stat().st_size,
                                                     video_sha256=record['video_sha256'], last_frame_sha256=record['last_frame_sha256'],
                                                     pixels_inspected=False, audio_listened=False, asr=False))
            mark_saved_candidate(record)
            record.update(next_segment_dispatch_allowed=False, last_frame_source='generation_service_original',
                          last_frame_format=frame_encoding['format'], human_decision=None, completed_at=now())
        except Exception as exc:
            record.update(status='provider_succeeded_file_validation_pending', technical_status='file_validation_pending',
                          content_status='awaiting_human_review', error_type=type(exc).__name__)
            persist(receipt_path, record)
            raise
        persist(receipt_path, record)
        story_event('seedance_saved_awaiting_human_review', receipt_path, task_id=task_id)
    return {key: record.get(key) for key in ('status', 'task_id', 'technical_status', 'content_status', 'video_path', 'last_frame')}
