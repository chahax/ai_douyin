"""Download recovery uses synthetic CDN GETs; never a second image API call."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening
from test_ark_opening_frame import CREATED, clients, prepared
from test_reviewed_storyboard_direction import staged


def pending(case):
    http, download, calls, raw, _ = clients(download_error=httpx.ReadTimeout)
    with http, download, pytest.raises(httpx.ReadTimeout):
        opening.submit_opening_frame(case['attempt'], case['config'], http_client=http, download_client=download)
    assert len(calls['post']) == 1
    return raw


def test_recover_download_preserves_request_response_and_single_paid_call(prepared):
    raw = pending(prepared)
    request = (prepared['attempt'] / 'request.json').read_bytes()
    http, download, calls, _, image = clients()
    with http, download:
        result = opening.resume_opening_download(prepared['attempt'], prepared['config'],
            download_client=download, now=datetime.fromtimestamp(CREATED + 30, timezone.utc))
    assert calls['post'] == [] and len(calls['get']) == 1
    assert calls['get'][0].method == 'GET' and 'authorization' not in calls['get'][0].headers
    assert result['status'] == 'downloaded' and result['api_calls'] == 1
    assert result['media_review'] == 'pending' and result['video_generation_submitted'] is False
    assert result['download_recoveries'][-1]['image_generation_calls'] == 0
    assert (prepared['attempt'] / 'request.json').read_bytes() == request
    assert (prepared['attempt'] / 'response.json').read_bytes() == raw
    assert (prepared['attempt'] / opening.IMAGE_NAME).read_bytes() == image
    with pytest.raises(ValueError, match='preserved successful'):
        opening.resume_opening_download(prepared['attempt'], prepared['config'])


def test_unknown_creation_cannot_be_recovered_as_a_download(prepared):
    http, download, _, _, _ = clients(post_error=httpx.ReadTimeout)
    with http, download, pytest.raises(httpx.ReadTimeout):
        opening.submit_opening_frame(prepared['attempt'], prepared['config'], http_client=http, download_client=download)
    with pytest.raises(ValueError, match='unknown creation'):
        opening.resume_opening_download(prepared['attempt'], prepared['config'])


@pytest.mark.parametrize('change', ['expired', 'response', 'reservation', 'image_exists'])
def test_download_recovery_rejects_changed_proof_expiry_or_overwrite(prepared, change):
    pending(prepared)
    current = datetime.fromtimestamp(CREATED + 30, timezone.utc)
    receipt = runner.read(prepared['attempt'] / opening.RECEIPT_NAME)
    if change == 'expired':
        current += timedelta(days=1)
    elif change == 'response':
        (prepared['attempt'] / 'response.json').write_bytes(b'{}')
    elif change == 'reservation':
        from pathlib import Path
        Path(receipt['reservation_path']).write_bytes(b'{}')
    else:
        (prepared['attempt'] / opening.IMAGE_NAME).write_bytes(b'unchanged sentinel')
    http, download, calls, _, _ = clients()
    with http, download, pytest.raises(ValueError):
        opening.resume_opening_download(prepared['attempt'], prepared['config'], download_client=download, now=current)
    assert not calls['post'] and not calls['get']
    if change == 'image_exists':
        assert (prepared['attempt'] / opening.IMAGE_NAME).read_bytes() == b'unchanged sentinel'
