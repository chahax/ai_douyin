"""Synthetic Ark responses only: no paid request or real media approval."""
import copy
import hashlib
import io
import json
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from PIL import Image

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceClient, SeedanceConfig
from src.content_factory.seedance_frames import bind_frame, reviewed_frame_reference, image_info
from test_reviewed_storyboard_direction import staged


MODEL = 'doubao-seedream-5-0-pro-260628'
CREATED = int(datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp())
URL = 'https://synthetic-cdn.invalid/original.png'


def test_reference_input_is_exact_and_changed_image_rejected(tmp_path):
    import base64
    path = tmp_path / 'layout.png'
    Image.new('RGB', (128, 256), 'gray').save(path)
    raw = path.read_bytes()
    plan = {'reference_image': {'path': 'layout.png', 'sha256': sha(raw),
                                'purpose': 'Synthetic blocking reference, not approved opening'}}
    body = opening._reference_payload({'prompt': 'test'}, plan, tmp_path)
    assert base64.b64decode(body['image'].split(',', 1)[1]) == raw
    Image.new('RGB', (128, 256), 'white').save(path)
    with pytest.raises(ValueError, match='changed'):
        opening._reference_payload({'prompt': 'test'}, plan, tmp_path)


def test_reference_input_rejects_outside_run_and_missing_purpose(tmp_path):
    plan = {'reference_image': {'path': '../outside.png', 'sha256': 'x', 'purpose': 'layout'}}
    with pytest.raises(ValueError):
        opening._reference_payload({}, plan, tmp_path)
    plan['reference_image']['purpose'] = ''
    with pytest.raises(ValueError, match='purpose'):
        opening._reference_payload({}, plan, tmp_path)


def test_reference_guided_image_cannot_claim_text_to_image_trust(tmp_path, monkeypatch):
    monkeypatch.setattr(opening, '_verify_inputs', lambda *args: (
        {}, {'body': {'image': 'synthetic'}}, tmp_path, {}, {}))
    with pytest.raises(ValueError, match='not a text-to-image'):
        opening.trusted_opening_reference(tmp_path, tmp_path / 'opening.original', None, {}, {})


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def prepared(staged, tmp_path, monkeypatch):
    script, source, proof = staged
    config = SeedanceConfig(api_key='synthetic-test-secret', base_url=ARK_BASE_URL,
                            model=ARK_MINI_MODEL, provider='ark_api')
    monkeypatch.setattr(SeedanceConfig, 'from_env', classmethod(lambda cls, *a, **k: config))
    monkeypatch.setattr(
        'src.trend_intelligence.saved_script_review.require_current_saved_script_review',
        lambda path: copy.deepcopy(proof),
    )
    folder = tmp_path / 'video_run'
    manifest = runner.prepare(folder, source, 'Synthetic test only', provider='ark_api')
    direction = runner.read(folder / 'direction_plan.json')
    plan = folder / 'opening_plan.json'
    runner.write(plan, {'schema': opening.PLAN_SCHEMA, 'shot_id': 'S01',
                       'script_sha256': manifest['script_sha256'],
                       'direction_sha256': manifest['direction_sha256'],
                       'prompt': 'Synthetic opening image test, not reviewed media.'})
    attempt = folder / 'opening_attempt_1'
    receipt = opening.prepare_opening_frame(folder, plan, attempt, config, model=MODEL, size='2K')
    return {'folder': folder, 'manifest': manifest, 'direction': direction,
            'plan': plan, 'attempt': attempt, 'config': config, 'receipt': receipt,
            'script': script, 'source': source}


def clients(*, post_error=None, status=200, response=None, download_error=None, image=None):
    if image is None:
        stream = io.BytesIO()
        Image.new('RGB', (320, 480), 'white').save(stream, format='PNG')
        image = stream.getvalue()
    if response is None:
        response = {'model': MODEL, 'created': CREATED, 'data': [{'url': URL}],
                    'usage': {'generated_images': 1}}
    raw = response if isinstance(response, bytes) else json.dumps(response, ensure_ascii=False).encode()
    calls = {'post': [], 'get': []}

    def post(request):
        calls['post'].append(request)
        if post_error:
            raise post_error('Synthetic uncertain response', request=request)
        return httpx.Response(status, content=raw)

    def get(request):
        calls['get'].append(request)
        if download_error:
            raise download_error('Synthetic failed download', request=request)
        return httpx.Response(200, content=image)

    return httpx.Client(transport=httpx.MockTransport(post)), httpx.Client(
        transport=httpx.MockTransport(get)), calls, raw, image


def submit(case, **kwargs):
    http, download, calls, raw, image = clients(**kwargs)
    with http, download:
        result = opening.submit_opening_frame(case['attempt'], case['config'],
                                              http_client=http, download_client=download)
    return result, calls, raw, image


def test_prepare_is_local_pending_and_binds_exact_inputs(prepared):
    case = prepared
    receipt = case['receipt']
    assert receipt['status'] == 'prepared' and receipt['api_calls'] == 0
    assert receipt['media_review'] == 'pending'
    assert receipt['video_generation_submitted'] is False
    assert not (case['attempt'] / 'response.json').exists()
    assert (case['attempt'] / 'plan.original.json').read_bytes() == case['plan'].read_bytes()
    binding = receipt['binding']
    assert binding['shot_sha256'] == sha(opening._bytes(case['script']['shots'][0]))
    assert binding['opening_state_sha256'] == sha(case['script']['shots'][0]['start_frame'].encode())
    assert binding['script_sha256'] == sha(case['source'].read_bytes())
    assert binding['direction_sha256'] == sha((case['folder'] / 'direction_plan.json').read_bytes())
    assert case['config'].api_key not in ''.join(p.read_text() for p in case['attempt'].glob('*.json'))


def test_prepared_reference_is_rechecked_before_provider_call(prepared):
    case = prepared
    image = case['folder'] / 'reference.png'
    Image.new('RGB', (128, 256), 'gray').save(image)
    plan = runner.read(case['plan'])
    plan['reference_image'] = {'path': image.name, 'sha256': sha(image.read_bytes()),
                               'purpose': 'Synthetic composition reference'}
    path = case['folder'] / 'reference_plan.json'
    runner.write(path, plan)
    attempt = case['folder'] / 'reference_attempt'
    opening.prepare_opening_frame(case['folder'], path, attempt, case['config'], model=MODEL, size='2K')
    opening._verify_inputs(attempt, case['config'])
    Image.new('RGB', (128, 256), 'black').save(image)
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError, match='changed'):
        opening.submit_opening_frame(attempt, case['config'], http_client=http, download_client=download)
    assert not calls['post']


def test_single_post_preserves_exact_response_original_image_and_pending_review(prepared):
    receipt, calls, raw, image = submit(prepared)
    assert len(calls['post']) == len(calls['get']) == 1
    post = calls['post'][0]
    assert str(post.url) == ARK_BASE_URL + '/images/generations'
    assert json.loads(post.content) == {'model': MODEL, 'prompt': runner.read(prepared['plan'])['prompt'],
                                      'size': '2K', 'response_format': 'url', 'watermark': False}
    assert post.headers['authorization'] == 'Bearer ' + prepared['config'].api_key
    assert 'authorization' not in calls['get'][0].headers
    assert (prepared['attempt'] / 'response.json').read_bytes() == raw
    assert (prepared['attempt'] / opening.IMAGE_NAME).read_bytes() == image
    assert receipt['response_sha256'] == sha(raw) and receipt['image_sha256'] == sha(image)
    assert receipt['status'] == 'downloaded' and receipt['api_calls'] == 1
    assert receipt['media_review'] == 'pending' and receipt['video_generation_submitted'] is False
    assert not (prepared['folder'] / 'frame_reviews').exists()
    http, download, second_calls, _, _ = clients()
    with http, download, pytest.raises(ValueError, match='already attempted'):
        opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                     http_client=http, download_client=download)
    assert second_calls == {'post': [], 'get': []}


@pytest.mark.parametrize('error', [httpx.ReadTimeout, httpx.ConnectError])
def test_unknown_outcome_is_durable_and_cannot_retry_or_reprepare_same_plan(prepared, error):
    http, download, calls, _, _ = clients(post_error=error)
    with http, download:
        with pytest.raises(error):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
        receipt = runner.read(prepared['attempt'] / opening.RECEIPT_NAME)
        assert receipt['status'] == 'submit_outcome_unknown' and receipt['api_calls'] == 1
        with pytest.raises(ValueError, match='already attempted'):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
        second = prepared['folder'] / 'opening_attempt_2'
        opening.prepare_opening_frame(prepared['folder'], prepared['plan'], second,
                                      prepared['config'], model=MODEL, size='2K')
        with pytest.raises(FileExistsError):
            opening.submit_opening_frame(second, prepared['config'],
                                         http_client=http, download_client=download)
    assert len(calls['post']) == 1 and not calls['get']


@pytest.mark.parametrize('status', [400, 401, 403, 500])
def test_rejection_and_server_error_preserve_response_and_never_retry(prepared, status):
    http, download, calls, raw, _ = clients(status=status, response={'error': 'synthetic'})
    with http, download:
        with pytest.raises(httpx.HTTPStatusError):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
        receipt = runner.read(prepared['attempt'] / opening.RECEIPT_NAME)
        assert receipt['status'] == ('request_rejected' if status < 500 else 'submit_outcome_unknown')
        assert receipt['api_calls'] == 1
        assert (prepared['attempt'] / 'response.json').read_bytes() == raw
        with pytest.raises(ValueError, match='already attempted'):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
    assert len(calls['post']) == 1 and not calls['get']


def test_download_failure_does_not_create_another_paid_request(prepared):
    http, download, calls, raw, _ = clients(download_error=httpx.ReadTimeout)
    with http, download:
        with pytest.raises(httpx.ReadTimeout):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
        receipt = runner.read(prepared['attempt'] / opening.RECEIPT_NAME)
        assert receipt['status'] == 'image_created_pending_download' and receipt['api_calls'] == 1
        assert receipt['response_sha256'] == sha(raw)
        with pytest.raises(ValueError, match='already attempted'):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
    assert len(calls['post']) == len(calls['get']) == 1


def trusted(case, *, now=None, config=None):
    return opening.trusted_opening_reference(
        case['folder'], case['attempt'] / opening.IMAGE_NAME,
        config or case['config'], case['manifest'], case['direction'],
        now=now or datetime.fromtimestamp(CREATED + 60, timezone.utc))


def test_trusted_reference_keeps_original_url_and_does_not_claim_account_lookup(prepared):
    receipt, _, _, _ = submit(prepared)
    reference, proof = trusted(prepared)
    assert reference.source == URL and reference.role == 'first_frame'
    assert proof['image_sha256'] == receipt['image_sha256']
    assert proof['response_sha256'] == receipt['response_sha256']
    assert proof['receipt_sha256'] == sha((prepared['attempt'] / opening.RECEIPT_NAME).read_bytes())
    assert proof['verification'] == 'same_ark_credential_original_text_to_image_receipt'
    assert 'account_id' not in proof
    assert receipt['media_review'] == 'pending'


@pytest.mark.parametrize('age,message', [(-1, '30-day'), (86400, '24 hours'),
                                       (29 * 86400, '24 hours'), (30 * 86400, '30-day')])
def test_original_url_and_trust_windows_are_independently_enforced(prepared, age, message):
    submit(prepared)
    with pytest.raises(ValueError, match=message):
        trusted(prepared, now=datetime.fromtimestamp(CREATED + age, timezone.utc))


def test_original_url_is_valid_just_before_24_hour_boundary(prepared):
    submit(prepared)
    ref, _ = trusted(prepared, now=datetime.fromtimestamp(CREATED + 86399, timezone.utc))
    assert ref.source == URL


@pytest.mark.parametrize('target', ['plan', 'saved_plan', 'request', 'script', 'direction', 'binding'])
def test_changed_inputs_rejected_before_paid_request(prepared, target):
    locations = {'plan': prepared['plan'], 'saved_plan': prepared['attempt'] / 'plan.original.json',
                 'request': prepared['attempt'] / 'request.json',
                 'script': prepared['folder'] / 'locked_script.json',
                 'direction': prepared['folder'] / 'direction_plan.json',
                 'binding': prepared['attempt'] / opening.RECEIPT_NAME}
    path = locations[target]
    if target == 'binding':
        value = runner.read(path)
        value['binding']['opening_state_sha256'] = '0' * 64
        runner.write(path, value)
    else:
        path.write_bytes(path.read_bytes() + b'\n')
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError):
        opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                     http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}


def test_current_key_must_match_preparation_and_reference(prepared):
    changed = replace(prepared['config'], api_key='different-synthetic-key')
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError, match='account'):
        opening.submit_opening_frame(prepared['attempt'], changed, http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}
    submit(prepared)
    with pytest.raises(ValueError, match='account'):
        trusted(prepared, config=changed)


@pytest.mark.parametrize('target', ['image', 'response', 'reservation', 'provider_url'])
def test_original_artifact_tampering_is_not_trusted(prepared, target):
    receipt, _, _, _ = submit(prepared)
    if target == 'image':
        Image.new('RGB', (320, 480), 'black').save(prepared['attempt'] / opening.IMAGE_NAME, format='PNG')
    elif target == 'response':
        path = prepared['attempt'] / 'response.json'
        path.write_bytes(path.read_bytes() + b'\n')
    elif target == 'reservation':
        from pathlib import Path
        path = Path(receipt['reservation_path'])
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        receipt['original_url'] = 'https://synthetic-cdn.invalid/edited.png'
        runner.write(prepared['attempt'] / opening.RECEIPT_NAME, receipt)
    with pytest.raises(ValueError):
        trusted(prepared)


@pytest.mark.parametrize('changed', [
    {'shot_id': 'S02'}, {'script_sha256': '0' * 64}, {'direction_sha256': '0' * 64},
    {'reference_image': 'unapproved.png'}, {'prompt': '   '},
])
def test_plan_rejects_later_shot_or_unapproved_inputs(prepared, changed):
    value = runner.read(prepared['plan'])
    value.update(changed)
    runner.write(prepared['plan'], value)
    attempt = prepared['folder'] / 'invalid_attempt'
    with pytest.raises(ValueError, match='exact reviewed script|Reference image requires'):
        opening.prepare_opening_frame(prepared['folder'], prepared['plan'], attempt,
                                      prepared['config'], model=MODEL, size='2K')
    assert not attempt.exists()


@pytest.mark.parametrize('response', [
    {'model': MODEL, 'created': CREATED, 'data': [{'url': URL}, {'url': URL}]},
    {'model': 'unregistered-image-model', 'created': CREATED, 'data': [{'url': URL}]},
    {'model': MODEL, 'created': True, 'data': [{'url': URL}]},
    {'model': MODEL, 'created': CREATED, 'data': [{'url': URL, 'error': 'filtered'}]},
    b'{"model":"x","model":"y","created":1,"data":[]}',
])
def test_invalid_provider_result_preserved_without_download_or_retry(prepared, response):
    http, download, calls, raw, _ = clients(response=response)
    with http, download:
        with pytest.raises(ValueError):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
        assert (prepared['attempt'] / 'response.json').read_bytes() == raw
        with pytest.raises(ValueError, match='already attempted'):
            opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                         http_client=http, download_client=download)
    assert len(calls['post']) == 1 and not calls['get']


def test_review_revoked_after_prepare_stops_image_submission(prepared, monkeypatch):
    monkeypatch.setattr(runner, 'require_project_script_review', lambda *args: {'current_passed': False})
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError, match='current passed script review'):
        opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                     http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}


def bind_synthetic_review(case, shot, image):
    return bind_frame(case['folder'], shot, image, {
        'shot_id': shot, 'camera_id': case['direction']['shots'][0]['camera_id'],
        'checks': {'composition': True, 'identity': True, 'opening_state': True},
        'notes': 'Synthetic test fixture only, not actual image or audio certification.',
        'evidence': [str(image.relative_to(case['folder']))],
    }, case['manifest'], case['direction'])


def test_generated_image_is_blocked_before_independent_frame_review(prepared, monkeypatch):
    submit(prepared)
    monkeypatch.setattr(opening, '_now', lambda: datetime.fromtimestamp(CREATED + 60, timezone.utc))
    image = prepared['attempt'] / opening.IMAGE_NAME
    with pytest.raises(ValueError, match='Bind and review'):
        reviewed_frame_reference(prepared['folder'], 'S01', image, prepared['manifest'],
                                 prepared['direction'], config=prepared['config'])
    bind_synthetic_review(prepared, 'S01', image)
    ref, binding = reviewed_frame_reference(prepared['folder'], 'S01', image, prepared['manifest'],
                                             prepared['direction'], config=prepared['config'])
    assert ref.source == URL
    assert binding['original_ark_image']['image_sha256'] == image_info(image)['sha256']
    assert runner.read(prepared['attempt'] / opening.RECEIPT_NAME)['media_review'] == 'pending'
    with pytest.raises(ValueError, match='same-account'):
        reviewed_frame_reference(prepared['folder'], 'S01', image, prepared['manifest'], prepared['direction'])


def preceding_tail(case):
    """Build a fully synthetic approved S01 chain; no real video is decoded."""
    from src.content_factory.script_video_review import REVIEW_CHECKS
    folder = case['folder']
    tail = folder / 'S01.raw_tail.png'
    Image.new('RGB', (320, 480), 'blue').save(tail)
    video = folder / 'S01.synthetic.mp4'
    video.write_bytes(b'Synthetic placeholder; not a real or reviewed video.')
    review = folder / 'S01.synthetic_review.json'
    runner.write(review, {'decision': 'passed', 'script_sha256': case['manifest']['script_sha256'],
                         'source_sha256': sha(video.read_bytes()),
                         'checks': {key: True for key in REVIEW_CHECKS},
                         'notes': 'Synthetic gate test only; no actual media review.'})
    campaign = folder / 'synthetic_campaign.json'
    runner.write(campaign, {'current_series_id': 'series_001',
                           'attempts': [{'id': 'synthetic_001', 'shot': 'S01', 'status': 'passed',
                                       'series_id': 'series_001', 'video_sha256': sha(video.read_bytes()),
                                       'review_path': str(review), 'review_sha256': sha(review.read_bytes())}]})
    case['manifest'].update(campaign_path=str(campaign), campaign_series_id='series_001')
    runner.write(folder / 'production.json', case['manifest'])
    runner.write(folder / 'S01.json', {'shot': 'S01', 'status': 'downloaded', 'provider': 'ark_api',
                                    'campaign_attempt_id': 'synthetic_001',
                                    'script_sha256': case['manifest']['script_sha256'],
                                    'direction_sha256': case['manifest']['direction_sha256'],
                                    'local_video': str(video), 'video_sha256': sha(video.read_bytes()),
                                    'last_frame': str(tail), 'last_frame_sha256': image_info(tail)['sha256']})
    return tail, campaign


def test_s02_cannot_use_opening_image_even_with_its_own_frame_review(prepared):
    submit(prepared)
    preceding_tail(prepared)
    image = prepared['attempt'] / opening.IMAGE_NAME
    bind_synthetic_review(prepared, 'S02', image)
    with pytest.raises(ValueError, match='immediately preceding approved raw tail'):
        reviewed_frame_reference(prepared['folder'], 'S02', image, prepared['manifest'],
                                 prepared['direction'], config=prepared['config'])


def test_s02_requires_current_series_passed_tail_and_unchanged_review(prepared):
    tail, campaign = preceding_tail(prepared)
    bind_synthetic_review(prepared, 'S02', tail)
    ref, _ = reviewed_frame_reference(prepared['folder'], 'S02', tail,
                                      prepared['manifest'], prepared['direction'])
    assert ref.role == 'first_frame'
    original = runner.read(campaign)
    for field, wrong in [('status', 'awaiting_review'), ('series_id', 'old_series')]:
        changed = copy.deepcopy(original)
        changed['attempts'][0][field] = wrong
        runner.write(campaign, changed)
        with pytest.raises(ValueError, match='not passed'):
            reviewed_frame_reference(prepared['folder'], 'S02', tail,
                                     prepared['manifest'], prepared['direction'])
    runner.write(campaign, original)
    review = prepared['folder'] / 'S01.synthetic_review.json'
    review.write_bytes(review.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='review changed'):
        reviewed_frame_reference(prepared['folder'], 'S02', tail,
                                 prepared['manifest'], prepared['direction'])


def test_video_runner_requires_image_review_before_create_task(prepared, monkeypatch):
    submit(prepared)
    image = prepared['attempt'] / opening.IMAGE_NAME
    calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='Bind and review'):
        runner.submit(prepared['folder'], 'S01', SeedanceClient(prepared['config']), [], first_frame=image)
    assert calls == [] and not (prepared['folder'] / 'S01.json').exists()


def test_video_preview_uses_trusted_url_and_never_creates_video(prepared, monkeypatch):
    submit(prepared)
    image = prepared['attempt'] / opening.IMAGE_NAME
    bind_synthetic_review(prepared, 'S01', image)
    monkeypatch.setattr(opening, '_now', lambda: datetime.fromtimestamp(CREATED + 60, timezone.utc))
    calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *args: calls.append(args))
    result = runner.submit(prepared['folder'], 'S01', SeedanceClient(prepared['config']), [],
                           first_frame=image, preview=True)
    preview = runner.read(prepared['folder'] / 'S01.workflow.preview.json')
    assert result['status'] == 'dry_run' and calls == []
    assert preview['video_generation_submitted'] is False
    assert preview['request']['generate_audio'] is True
    assert preview['request']['return_last_frame'] is True
    image_rows = [row for row in preview['request']['content'] if row['type'] == 'image_url']
    assert image_rows == [{'type': 'image_url', 'image_url': {'url': URL}, 'role': 'first_frame'}]
    assert preview['original_ark_sources'][0]['verification'] == 'same_ark_credential_original_text_to_image_receipt'
    assert not (prepared['folder'] / 'S01.json').exists()


def test_video_runner_rejects_s02_generated_image_before_create_task(prepared, monkeypatch):
    submit(prepared)
    preceding_tail(prepared)
    image = prepared['attempt'] / opening.IMAGE_NAME
    bind_synthetic_review(prepared, 'S02', image)
    calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='immediately preceding approved raw tail'):
        runner.submit(prepared['folder'], 'S02', SeedanceClient(prepared['config']), [], first_frame=image)
    assert calls == [] and not (prepared['folder'] / 'S02.json').exists()


def test_actual_first_shot_binding_cannot_be_changed_to_s02(prepared):
    value = runner.read(prepared['plan'])
    value['shot_id'] = 'S02'
    raw = opening._bytes(value)
    (prepared['attempt'] / 'plan.original.json').write_bytes(raw)
    prepared['plan'].write_bytes(raw)
    receipt = runner.read(prepared['attempt'] / opening.RECEIPT_NAME)
    receipt['plan_sha256'] = sha(raw)
    runner.write(prepared['attempt'] / opening.RECEIPT_NAME, receipt)
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError, match='bind S01'):
        opening.submit_opening_frame(prepared['attempt'], prepared['config'],
                                     http_client=http, download_client=download)
    assert calls == {'post': [], 'get': []}
