"""Local, reviewed opening-frame bindings for the locked storyboard workflow."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from src.content_factory.seedance_client import SeedanceReference

FRAME_CHECKS = {'composition', 'identity', 'opening_state'}


def image_info(path):
    path = Path(path)
    data = path.read_bytes()
    if len(data) > 30 * 1024 * 1024:
        raise ValueError('First frame exceeds 30 MiB')
    with Image.open(path) as picture:
        if picture.format not in {'PNG', 'JPEG', 'WEBP'}:
            raise ValueError('First frame must be PNG, JPEG or WEBP')
        mime = Image.MIME[picture.format]
        width, height = picture.size
        picture.verify()
    if not (300 <= width <= 6000 and 300 <= height <= 6000):
        raise ValueError('First frame dimensions must be between 300 and 6000 pixels')
    if not 0.4 <= width / height <= 2.5:
        raise ValueError('First frame aspect ratio is outside model limits')
    return {'sha256': hashlib.sha256(data).hexdigest(), 'mime': mime, 'width': width, 'height': height}


def _camera(plan, shot_id):
    return next(row['camera_id'] for row in plan['shots'] if row['shot_id'] == shot_id)


def bind_frame(folder, shot_id, path, review, manifest, plan):
    folder, path = Path(folder).resolve(), Path(path).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise ValueError('First frame must be a local image inside this run')
    if (review.get('shot_id') != shot_id or review.get('camera_id') != _camera(plan, shot_id)
            or set(review.get('checks', {})) != FRAME_CHECKS
            or any(review['checks'][key] is not True for key in FRAME_CHECKS)
            or not review.get('notes') or not review.get('evidence')):
        raise ValueError('Frame review must match the target shot, camera and all frame checks')
    for evidence in review['evidence']:
        item = (folder / evidence).resolve()
        if not item.is_relative_to(folder) or not item.is_file():
            raise ValueError('Frame review evidence must exist inside this run')
    # A raw tail from a wide shot must not silently become a close-up opening.
    for receipt in folder.glob('S*.json'):
        record = json.loads(receipt.read_text(encoding='utf-8'))
        if not isinstance(record, dict) or not record.get('last_frame'):
            continue
        if Path(record['last_frame']).resolve() == path:
            if record.get('last_frame_sha256') != image_info(path)['sha256']:
                raise ValueError('Provider last frame has changed')
            if _camera(plan, record['shot']) != _camera(plan, shot_id):
                raise ValueError('Camera changes require a matching new opening frame, not the raw previous tail')
    binding = dict(review, schema='seedance_frame_binding/v1', image=str(path),
                   image_info=image_info(path), script_sha256=manifest['script_sha256'],
                   direction_sha256=manifest['direction_sha256'],
                   reviewed_at=datetime.now(timezone.utc).isoformat())
    directory = folder / 'frame_reviews'
    directory.mkdir(exist_ok=True)
    destination = directory / f'{shot_id}.json'
    if destination.exists():
        raise ValueError('Opening frame is already bound; retain its review before revising')
    destination.write_text(json.dumps(binding, ensure_ascii=False, indent=2), encoding='utf-8')
    return binding


def require_preceding_raw_tail(folder, shot_id, path, manifest, plan):
    """Staged fixed-camera continuations use only the preceding approved raw tail."""
    if plan.get('schema') != 'reviewed_storyboard_direction/v1':
        return
    ids = [row['shot_id'] for row in plan['shots']]
    index = ids.index(shot_id)
    if index == 0:
        return
    folder, path = Path(folder).resolve(), Path(path).resolve()
    previous_id = ids[index - 1]
    if not manifest.get('campaign_path'):
        raise ValueError('Later staged shots require the preceding approved raw tail in the campaign')
    campaign = json.loads(Path(manifest['campaign_path']).read_bytes())
    if campaign.get('current_series_id', 'legacy') != manifest.get('campaign_series_id', 'legacy'):
        raise ValueError('The preceding tail belongs to an inactive campaign revision series')
    from .script_video_review import REVIEW_CHECKS
    for source_path in folder.rglob(f'{previous_id}.json'):
        source = json.loads(source_path.read_bytes())
        if not isinstance(source, dict) or Path(source.get('last_frame', '')).resolve() != path:
            continue
        if (source.get('provider') != 'ark_api' or source.get('status') != 'downloaded'
                or source.get('shot') != previous_id or source.get('script_sha256') != manifest['script_sha256']
                or source.get('direction_sha256') != manifest['direction_sha256']
                or source.get('last_frame_sha256') != image_info(path)['sha256']):
            raise ValueError('Immediately preceding original tail binding changed')
        video = Path(source['local_video']).resolve()
        if not video.is_relative_to(folder) or hashlib.sha256(video.read_bytes()).hexdigest() != source.get('video_sha256'):
            raise ValueError('Immediately preceding original video changed')
        approved = next((a for a in campaign.get('attempts', [])
            if a.get('id') == source.get('campaign_attempt_id') and a.get('shot') == previous_id
            and a.get('status') == 'passed' and a.get('video_sha256') == source['video_sha256']
            and a.get('series_id', 'legacy') == manifest.get('campaign_series_id', 'legacy')), None)
        if not approved:
            raise ValueError('Preceding segment has not passed its actual campaign review')
        review_path = Path(approved['review_path']).resolve()
        review_raw = review_path.read_bytes()
        review = json.loads(review_raw)
        expected_source = approved.get('delivery_video_sha256', source['video_sha256'])
        if (not review_path.is_relative_to(folder) or hashlib.sha256(review_raw).hexdigest() != approved.get('review_sha256')
                or review.get('decision') != 'passed' or set(review.get('checks', {})) != set(REVIEW_CHECKS)
                or any(value is not True for value in review['checks'].values())
                or review.get('script_sha256') != manifest['script_sha256']
                or review.get('source_sha256') != expected_source
                or (approved.get('delivery_video_sha256') and review.get('source_original_sha256') != source['video_sha256'])):
            raise ValueError('Preceding segment review changed or does not approve the original output')
        return
    raise ValueError('Later staged shots must use the immediately preceding approved raw tail, not an arbitrary image')


def reviewed_frame_reference(folder, shot_id, path, manifest, plan, *, config=None):
    folder, path = Path(folder).resolve(), Path(path).resolve()
    from .ark_opening_frame import IMPORT_NAME, trusted_imported_opening_reference
    if (path.parent / IMPORT_NAME).exists():
        if shot_id != 'S01' or config is None:
            raise ValueError('Imported opening images are S01-only and require same-account verification')
        return trusted_imported_opening_reference(folder, path, config, manifest, plan)
    binding_path = folder / 'frame_reviews' / f'{shot_id}.json'
    if not binding_path.is_file():
        raise ValueError('Bind and review the first frame before submission')
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    if (not path.is_relative_to(folder) or Path(binding['image']).resolve() != path
            or binding.get('script_sha256') != manifest['script_sha256']
            or binding.get('direction_sha256') != manifest['direction_sha256']
            or binding.get('camera_id') != _camera(plan, shot_id)
            or binding.get('shot_id') != shot_id
            or set(binding.get('checks', {})) != FRAME_CHECKS
            or any(binding['checks'][key] is not True for key in FRAME_CHECKS)
            or not binding.get('reviewed_at') or not binding.get('notes')
            or not binding.get('evidence') or binding['image_info'] != image_info(path)):
        raise ValueError('First frame or its locked shot review has changed')
    for evidence in binding['evidence']:
        item = (folder / evidence).resolve()
        if not item.is_relative_to(folder) or not item.is_file():
            raise ValueError('First frame review evidence is missing')
    require_preceding_raw_tail(folder, shot_id, path, manifest, plan)
    from .ark_opening_frame import IMAGE_NAME, RECEIPT_NAME, trusted_opening_reference
    if path.name == IMAGE_NAME or (path.parent / RECEIPT_NAME).exists():
        if shot_id != plan['shots'][0]['shot_id'] or config is None:
            raise ValueError('Seedream opening image is S01-only and requires same-account Ark verification')
        reference, source_proof = trusted_opening_reference(folder, path, config, manifest, plan)
        return reference, dict(binding, original_ark_image=source_proof)
    source = f"data:{binding['image_info']['mime']};base64," + base64.b64encode(path.read_bytes()).decode('ascii')
    return SeedanceReference('image', source, 'first_frame'), binding
