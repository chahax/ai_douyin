"""Synthetic same-source imports: no paid image/video calls and no invented reviews."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening
from src.content_factory.seedance_frames import bind_frame, reviewed_frame_reference
from test_ark_opening_frame import CREATED, URL, prepared, submit
from test_reviewed_storyboard_direction import staged


@pytest.fixture
def import_case(prepared, monkeypatch):
    case = prepared
    monkeypatch.setattr(opening, '_now', lambda: datetime.fromtimestamp(CREATED + 60, timezone.utc))
    receipt, _, _, _ = submit(case)
    image = Path(receipt['image'])
    evidence = case['folder'] / 'reviewed_evidence.png'
    evidence.write_bytes(image.read_bytes())
    review = {'shot_id': 'S01', 'camera_id': case['direction']['shots'][0]['camera_id'],
        'checks': {'composition': True, 'identity': True, 'opening_state': True},
        'notes': 'Synthetic fixture; no real image was reviewed.',
        'evidence': [str(image.relative_to(case['folder'])), evidence.name]}
    bind_frame(case['folder'], 'S01', image, review, case['manifest'], case['direction'])
    target = case['folder'].parent / 'target_video_run'
    target_manifest = runner.prepare(target, case['source'], 'Synthetic test only', provider='ark_api')
    campaign = case['folder'].parent / 'campaign.json'
    runner.write(campaign, {'current_series_id': 'series_001', 'failed_outputs': 7, 'max_failed_outputs': 10,
        'status': 'awaiting_upstream_revision', 'attempts': [{'id': 'synthetic_old_failed', 'status': 'failed'}],
        'series': [{'id': 'series_001', 'runs': [str(case['folder']), str(target)]}]})
    for folder, manifest in ((case['folder'], case['manifest']), (target, target_manifest)):
        manifest.update(campaign_path=str(campaign), campaign_series_id='series_001')
        runner.write(folder / 'production.json', manifest)
    case.update(target=target, target_manifest=target_manifest, campaign=campaign,
        source_image=image, evidence=evidence, destination=target / 'imported_opening')
    return case


def import_image(case):
    return opening.import_opening_frame(case['target'], case['folder'], case['source_image'],
                                        case['destination'], case['config'])


def reference(case, *, shot='S01'):
    manifest, _ = runner.locked(case['target'])
    direction = runner.read(case['target'] / 'direction_plan.json')
    return reviewed_frame_reference(case['target'], shot, case['destination'] / opening.IMAGE_NAME,
                                    manifest, direction, config=case['config'])


def test_import_preserves_original_bytes_and_review_and_reuses_raw_url_without_any_post(import_case, monkeypatch):
    case = import_case
    originals = {p: p.read_bytes() for p in case['folder'].rglob('*') if p.is_file()}
    campaign_before = case['campaign'].read_bytes()
    def no_request(*args, **kwargs):
        raise AssertionError('Import/reference verification must not perform network requests')
    monkeypatch.setattr(httpx.Client, 'request', no_request)
    record = import_image(case)
    assert record['schema'] == opening.IMPORT_SCHEMA and record['api_calls'] == record['image_generation_calls'] == 0
    assert record['media_review'] == 'inherited_source_frame_review'
    assert record['new_media_review_performed'] is False and record['video_generation_submitted'] is False
    assert (case['destination'] / opening.IMAGE_NAME).read_bytes() == case['source_image'].read_bytes()
    assert not (case['destination'] / opening.RECEIPT_NAME).exists()
    assert not (case['target'] / 'frame_reviews/S01.json').exists()
    assert not (case['target'] / 'S01.json').exists()
    assert originals == {p: p.read_bytes() for p in originals}
    assert case['campaign'].read_bytes() == campaign_before
    ref, binding = reference(case)
    assert ref.kind == 'image' and ref.role == 'first_frame' and ref.source == URL
    assert binding['review_origin'] == 'inherited_source_frame_review'
    assert 'reviewed_at' not in binding and 'checks' not in binding
    assert binding['original_ark_image']['source_frame_review']['sha256'] == runner.sha(case['folder'] / 'frame_reviews/S01.json')
    assert binding['original_ark_image']['source_original']['receipt_sha256'] == runner.sha(case['source_image'].parent / opening.RECEIPT_NAME)


def test_ordinary_runner_preview_records_the_actual_inherited_review_and_import(import_case, monkeypatch):
    from src.content_factory.seedance_client import SeedanceClient
    case = import_case
    import_image(case)
    before = case['campaign'].read_bytes()
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *args: pytest.fail('Preview performed a video call'))
    runner.submit(case['target'], 'S01', SeedanceClient(case['config']), [],
                  first_frame=case['destination'] / opening.IMAGE_NAME, preview=True)
    record = runner.read(case['target'] / 'S01.workflow.preview.json')
    actual_review = case['folder'] / 'frame_reviews/S01.json'
    import_path = case['destination'] / opening.IMPORT_NAME
    assert record['first_frame_review'] == str(actual_review.resolve())
    assert record['first_frame_review_sha256'] == runner.sha(actual_review)
    assert record['first_frame_review_origin'] == 'inherited_source_frame_review'
    assert record['first_frame_import'] == str(import_path.resolve())
    assert record['first_frame_import_sha256'] == runner.sha(import_path)
    assert record['request']['content'][1]['image_url']['url'] == URL
    assert 'execution_prompt' not in record
    assert not (case['target'] / 'frame_reviews/S01.json').exists()
    assert case['campaign'].read_bytes() == before


@pytest.mark.parametrize('change', ['image', 'receipt', 'response', 'review', 'evidence', 'target_image', 'import_url'])
def test_changed_source_review_or_import_is_rejected(import_case, change):
    case = import_case
    import_image(case)
    paths = {'image': case['source_image'], 'receipt': case['source_image'].parent / opening.RECEIPT_NAME,
        'response': case['source_image'].parent / 'response.json', 'review': case['folder'] / 'frame_reviews/S01.json',
        'evidence': case['evidence'], 'target_image': case['destination'] / opening.IMAGE_NAME}
    if change == 'import_url':
        path = case['destination'] / opening.IMPORT_NAME
        data = runner.read(path)
        data['original_url'] = 'https://synthetic.invalid/replaced.png'
        runner.write(path, data)
    else:
        path = paths[change]
        path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        reference(case)


@pytest.mark.parametrize('change', ['script', 'direction', 'series', 'campaign', 'base'])
def test_import_rejects_different_target_source_or_series_before_copy(import_case, change):
    case = import_case
    manifest = runner.read(case['target'] / 'production.json')
    if change == 'script':
        manifest['script_sha256'] = '0' * 64
    elif change == 'direction':
        manifest['direction_sha256'] = '0' * 64
    elif change == 'series':
        manifest['campaign_series_id'] = 'series_002'
    elif change == 'campaign':
        other = case['campaign'].with_name('other_campaign.json')
        other.write_bytes(case['campaign'].read_bytes())
        manifest['campaign_path'] = str(other)
    else:
        manifest['api_base_url'] = 'https://different.invalid/api/v3'
    runner.write(case['target'] / 'production.json', manifest)
    with pytest.raises(ValueError):
        import_image(case)
    assert not case['destination'].exists()


@pytest.mark.parametrize('change', ['unknown', 'unreviewed', 'limit', 'hold'])
def test_import_never_resets_outstanding_task_or_cumulative_guard(import_case, change):
    case = import_case
    campaign = runner.read(case['campaign'])
    if change in ('unknown', 'unreviewed'):
        campaign['attempts'].append({'id': 'synthetic_pending', 'status': 'awaiting_generation_or_review' if change == 'unknown' else 'awaiting_review'})
    elif change == 'limit':
        campaign['failed_outputs'] = 10
    else:
        campaign['holds'] = ['synthetic prerequisite']
    runner.write(case['campaign'], campaign)
    before = case['campaign'].read_bytes()
    with pytest.raises(ValueError):
        import_image(case)
    assert case['campaign'].read_bytes() == before and not case['destination'].exists()


def test_imported_opening_is_rejected_for_s02_even_with_same_camera(import_case):
    import_image(import_case)
    with pytest.raises(ValueError, match='S01-only'):
        reference(import_case, shot='S02')


def test_import_rechecks_original_url_expiry_and_current_key(import_case, monkeypatch):
    case = import_case
    import_image(case)
    monkeypatch.setattr(opening, '_now', lambda: datetime.fromtimestamp(CREATED, timezone.utc) + timedelta(days=1))
    with pytest.raises(ValueError, match='24 hours'):
        reference(case)
    monkeypatch.setattr(opening, '_now', lambda: datetime.fromtimestamp(CREATED + 60, timezone.utc))
    case['config'] = copy.copy(case['config'])
    from dataclasses import replace
    case['config'] = replace(case['config'], api_key='different-synthetic-key')
    with pytest.raises(ValueError, match='account'):
        reference(case)


def test_unreviewed_original_cannot_be_imported(import_case):
    case = import_case
    (case['folder'] / 'frame_reviews/S01.json').unlink()
    with pytest.raises(ValueError, match='Bind and review'):
        import_image(case)
    assert not case['destination'].exists()


def test_imported_source_cannot_be_chained_or_overwritten(import_case):
    case = import_case
    record = import_image(case)
    before = (case['destination'] / opening.IMPORT_NAME).read_bytes()
    with pytest.raises(FileExistsError):
        import_image(case)
    assert (case['destination'] / opening.IMPORT_NAME).read_bytes() == before
    with pytest.raises(ValueError, match='original Seedream'):
        opening._checked_import_source(case['target'], record['image'], case['config'])
