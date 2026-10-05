"""One reserved, source-bound Ark text-to-image opening; never video approval."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .seedance_client import SeedanceConfig, SeedanceReference
from src.services.provider_call_ledger import ProviderCallLedger

PLAN_SCHEMA = 'opening_frame_plan/v1'
RECEIPT_SCHEMA = 'ark_opening_frame_receipt/v1'
IMAGE_NAME = 'opening.original'
RECEIPT_NAME = 'opening.ark_image.json'
IMPORT_SCHEMA = 'ark_opening_frame_import/v1'
IMPORT_NAME = 'opening.ark_image_import.json'
# Populated only with model IDs confirmed in this account's service catalog.
TRUSTED_TEXT_IMAGE_MODELS = frozenset({'doubao-seedream-5-0-pro-260628'})
MAX_IMAGE_BYTES = 30 * 1024 * 1024
PROP_RENDER_SCHEMA = 'opening_prop_names/v1'
_PROP_ID = re.compile(r'(?<![A-Za-z0-9_])P[0-9]+(?![A-Za-z0-9_])')
_PROP_DEFINITION = re.compile(r'(?:^|[；;。\n])\s*(P[1-9][0-9]*)[（(]([^（）()\r\n]+)[）)][:：]')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def _read(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=_unique)


def _write(path, value, *, exclusive=False):
    raw = _bytes(value)
    if exclusive:
        with Path(path).open('xb') as handle:
            handle.write(raw)
    else:
        temporary = Path(path).with_suffix(Path(path).suffix + '.tmp')
        temporary.write_bytes(raw)
        temporary.replace(path)
    return _sha(raw)


def _now():
    return datetime.now(timezone.utc)


def _base(config):
    value = config.base_url.rstrip('/')
    parsed = urlsplit(value)
    if (config.provider != 'ark_api' or not config.api_key or parsed.scheme != 'https'
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.hostname != 'ark.cn-beijing.volces.com' or parsed.path != '/api/v3'):
        raise ValueError('Opening image requires the configured Beijing Ark HTTPS API and key')
    return value


def credential_fingerprint(config):
    """Conservative same-key binding; this is not a claim of an account ID lookup."""
    return _sha(('ark-opening-credential/v1\0' + _base(config) + '\0' + config.api_key).encode())


def _inside(path, folder):
    path, folder = Path(path).resolve(), Path(folder).resolve()
    if not path.is_relative_to(folder):
        raise ValueError('Opening artifact must remain inside this video run')
    return path


def _run_inputs(run_dir):
    from scripts.run_script_video import locked, require_project_script_review, validate_execution_plan
    from .reviewed_storyboard_direction import SCHEMA
    folder = Path(run_dir).resolve()
    manifest, script = locked(folder)
    if manifest.get('provider') != 'ark_api':
        raise ValueError('Opening image requires an Ark video run')
    if manifest.get('trial_schema') == 'reviewed_reference_director_segment/v1':
        from scripts.reference_video_source import verify_bundle
        from scripts.run_director_video import TEXT_CHECKS
        from scripts.run_cohort_scene_flow import require_actual_review
        bundle,verified=verify_bundle(manifest['bundle'])
        if script!=verified or manifest.get('test_shot')!='S01':
            raise ValueError('Only unchanged reference-director S01 can create an opening')
        require_actual_review(folder/'text_review.json',folder/'S01.prompt.txt',TEXT_CHECKS)
        start=script['opening_state'];direction_sha=bundle['review']['sha256']
        shot={'shot_id':'S01','start_frame':start}
        plan={'schema':'reviewed_reference_director_opening/v1','shots':[{'storyboard':shot}],'production_sha256':direction_sha}
        binding={'shot_id':'S01','script_sha256':manifest['script_sha256'],'direction_sha256':direction_sha,
                 'shot_sha256':_sha(_bytes(shot)),'opening_state_sha256':_sha(start.encode('utf-8'))}
        return folder,manifest,plan,binding
    if manifest.get('trial_schema') == 'reviewed_cohort_segment/v1':
        from scripts.run_cohort_video import verify_bundle,TEXT_CHECKS,require_actual_review
        bundle,verified=verify_bundle(manifest['bundle'])
        if script!=verified or manifest.get('test_shot')!='S01':raise ValueError('Only unchanged cohort S01 can create an opening')
        require_actual_review(folder/'text_review.json',folder/'S01.prompt.txt',TEXT_CHECKS)
        design=_read(bundle['bindings']['design']['path'])
        start=design['opening_composition']+'\n'+script['shots'][0]['model_prompt_zh'].split('本段初始持物：',1)[1].splitlines()[0]
        shot={'shot_id':'S01','start_frame':start};direction_sha=bundle['bindings']['design']['sha256']
        plan={'schema':'reviewed_cohort_opening/v1','shots':[{'storyboard':shot}],'production_sha256':direction_sha}
        binding={'shot_id':'S01','script_sha256':manifest['script_sha256'],'direction_sha256':direction_sha,
                 'shot_sha256':_sha(_bytes(shot)),'opening_state_sha256':_sha(start.encode('utf-8'))}
        return folder,manifest,plan,binding
    if manifest.get('trial_schema') == 'reviewed_screenplay_first_shot/v1':
        from scripts.run_screenplay_trial import verify_inputs
        from src.trend_intelligence.script_screenplay import render_state
        trial_path = folder / 'trial_plan.json'
        if _sha(trial_path.read_bytes()) != manifest.get('trial_plan_sha256'):
            raise ValueError('Opening trial plan changed')
        trial = _read(trial_path)
        story, production, _ = verify_inputs(trial)
        if trial.get('shot_id', 'S01') != 'S01' or story != script:
            raise ValueError('Only the unchanged reviewed S01 trial may create an opening image')
        start = render_state(story['version']['initial_state'], story['characters'], story['version']['props'])
        shot = {'shot_id': 'S01', 'start_frame': start}
        direction_sha = trial['bindings']['production']['sha256']
        plan = {'schema': 'reviewed_trial_opening/v1', 'shots': [{'storyboard': shot}],
                'production_sha256': direction_sha}
        binding = {'shot_id': 'S01', 'script_sha256': manifest['script_sha256'],
                   'direction_sha256': direction_sha, 'shot_sha256': _sha(_bytes(shot)),
                   'opening_state_sha256': _sha(start.encode('utf-8'))}
        return folder, manifest, plan, binding
    plan = _read(folder / 'direction_plan.json')
    if plan.get('schema') != SCHEMA:
        raise ValueError('Opening image requires the reviewed storyboard direction')
    validate_execution_plan(plan, script, manifest['script_sha256'])
    proof = require_project_script_review(script, manifest['source_script'])
    if not proof or proof.get('current_passed') is not True:
        raise ValueError('Opening image requires the current passed script review')
    shot = script['shots'][0]
    if shot['shot_id'] != 'S01' or shot['start_seconds'] != 0:
        raise ValueError('Only the actual S01 opening is supported')
    binding = {'shot_id': 'S01', 'script_sha256': manifest['script_sha256'],
               'direction_sha256': manifest['direction_sha256'],
               'shot_sha256': _sha(_bytes(shot)),
               'opening_state_sha256': _sha(shot['start_frame'].encode('utf-8'))}
    return folder, manifest, plan, binding


def _validate_plan(plan, binding):
    required = {'schema', 'shot_id', 'script_sha256', 'direction_sha256', 'prompt'}
    if (not isinstance(plan, dict) or not required.issubset(plan)
            or set(plan) - required - {'provenance', 'reference_image'} or plan['schema'] != PLAN_SCHEMA
            or any(plan[key] != binding[key] for key in ('shot_id', 'script_sha256', 'direction_sha256'))
            or not isinstance(plan['prompt'], str) or not plan['prompt'].strip()):
        raise ValueError('Opening plan must bind S01 and the exact reviewed script/direction')


def _payload(model, size, prompt):
    if not isinstance(model, str) or model not in TRUSTED_TEXT_IMAGE_MODELS:
        raise ValueError('Select an explicitly registered trusted Seedream text-to-image model')
    if not isinstance(size, str) or not size.strip():
        raise ValueError('Image size must be explicitly supplied for this model')
    return {'model': model, 'prompt': prompt, 'size': size,
            'response_format': 'url', 'watermark': False}


def _reference_payload(body, plan, folder):
    """Bind one local visual input; it does not confer output approval."""
    if 'reference_image' not in plan:
        return body
    import base64
    import io
    from PIL import Image
    ref = plan['reference_image']
    if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256', 'purpose'}
            or not isinstance(ref['purpose'], str) or not ref['purpose'].strip()):
        raise ValueError('Reference image requires path, sha256 and explicit purpose')
    path = _inside(folder / ref['path'], folder)
    raw = path.read_bytes()
    if _sha(raw) != ref['sha256'] or len(raw) > 30 * 1024 * 1024:
        raise ValueError('Reference image changed or exceeds local size limit')
    with Image.open(io.BytesIO(raw)) as im:
        fmt = im.format
        width, height = im.size
        im.verify()
    if fmt not in {'PNG', 'JPEG'} or min(width, height) < 15 or width * height > 36000000:
        raise ValueError('Reference must be a valid PNG or JPEG within image limits')
    mime = 'png' if fmt == 'PNG' else 'jpeg'
    return {**body, 'image': 'data:image/' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')}


def render_opening_prompt(prompt, start_frame):
    """Replace production IDs with exact names from the locked opening state only."""
    if not isinstance(prompt, str) or not isinstance(start_frame, str):
        raise ValueError('Opening prompt and locked start_frame must be strings')
    names = {}
    for match in _PROP_DEFINITION.finditer(start_frame):
        prop_id, name = match.groups()
        if prop_id in names:
            raise ValueError('Duplicate prop definition in locked opening state')
        if not name.strip() or _PROP_ID.search(name):
            raise ValueError('Opening prop definition must contain an unambiguous natural name')
        names[prop_id] = name
    counts = {}

    def replace(match):
        prop_id = match.group()
        if prop_id not in names:
            raise ValueError('Opening prompt references an unknown prop ID: ' + prop_id)
        counts[prop_id] = counts.get(prop_id, 0) + 1
        return names[prop_id]

    rendered = _PROP_ID.sub(replace, prompt)
    recipe = {'schema': PROP_RENDER_SCHEMA, 'source_field': 'S01.start_frame',
        'source_sha256': _sha(start_frame.encode('utf-8')),
        'input_prompt_sha256': _sha(prompt.encode('utf-8')),
        'output_prompt_sha256': _sha(rendered.encode('utf-8')),
        'prop_names': names, 'replacements': counts}
    return rendered, recipe


def prepare_opening_frame(run_dir, plan_path, attempt_dir, config, *, model, size):
    """Save a reviewable single-image request without invoking any API."""
    folder, manifest, direction, binding = _run_inputs(run_dir)
    if _base(config) != manifest['api_base_url'].rstrip('/'):
        raise ValueError('Ark base differs from the locked video run')
    source = Path(plan_path).resolve()
    raw = source.read_bytes()
    plan = json.loads(raw, object_pairs_hook=_unique)
    _validate_plan(plan, binding)
    prompt, render_recipe = render_opening_prompt(plan['prompt'], direction['shots'][0]['storyboard']['start_frame'])
    request = {'method': 'POST', 'base_url': _base(config), 'path': '/images/generations',
               'body': _reference_payload(_payload(model, size, prompt), plan, folder)}
    attempt_dir = _inside(attempt_dir, folder)
    if attempt_dir == folder:
        raise ValueError('Use a new opening-image attempt subdirectory')
    attempt_dir.mkdir(parents=True, exist_ok=False)
    (attempt_dir / 'plan.original.json').write_bytes(raw)
    request_sha = _write(attempt_dir / 'request.json', request, exclusive=True)
    receipt = {'schema': RECEIPT_SCHEMA, 'status': 'prepared', 'run_dir': str(folder),
        'binding': binding, 'plan_path': str(source), 'plan_sha256': _sha(raw),
        'render_recipe': render_recipe,
        'request_sha256': request_sha, 'api_base_url': _base(config),
        'credential_fingerprint': credential_fingerprint(config),
        'model': model, 'prepared_at': _now().isoformat(), 'api_calls': 0,
        'image': str(attempt_dir / IMAGE_NAME), 'media_review': 'pending',
        'video_generation_submitted': False}
    _write(attempt_dir / RECEIPT_NAME, receipt, exclusive=True)
    return receipt


def _verify_inputs(attempt_dir, config):
    attempt_dir = Path(attempt_dir).resolve()
    receipt = _read(attempt_dir / RECEIPT_NAME)
    folder, manifest, plan, binding = _run_inputs(receipt['run_dir'])
    _inside(attempt_dir, folder)
    if (receipt.get('schema') != RECEIPT_SCHEMA or receipt.get('binding') != binding
            or receipt.get('api_base_url') != _base(config)
            or manifest['api_base_url'].rstrip('/') != _base(config)
            or receipt.get('credential_fingerprint') != credential_fingerprint(config)
            or receipt.get('image') != str(attempt_dir / IMAGE_NAME)):
        raise ValueError('Opening receipt account, script, direction or image binding changed')
    raw = (attempt_dir / 'plan.original.json').read_bytes()
    if (_sha(raw) != receipt['plan_sha256']
            or Path(receipt['plan_path']).read_bytes() != raw):
        raise ValueError('Opening input plan changed')
    image_plan = json.loads(raw, object_pairs_hook=_unique)
    _validate_plan(image_plan, binding)
    request_raw = (attempt_dir / 'request.json').read_bytes()
    request = json.loads(request_raw, object_pairs_hook=_unique)
    prompt = image_plan['prompt']
    # Receipts written before this renderer retain their actual unmodified request.
    if 'render_recipe' in receipt:
        prompt, expected_recipe = render_opening_prompt(prompt, plan['shots'][0]['storyboard']['start_frame'])
        if receipt['render_recipe'] != expected_recipe:
            raise ValueError('Opening render recipe changed or cannot be replayed from the locked start_frame')
    expected = {'method': 'POST', 'base_url': _base(config), 'path': '/images/generations',
                'body': _reference_payload(_payload(receipt['model'], request['body']['size'], prompt), image_plan, folder)}
    if _sha(request_raw) != receipt['request_sha256'] or request != expected:
        raise ValueError('Opening request changed or contains unapproved image/audio inputs')
    return receipt, request, folder, manifest, plan


def _image_response(raw, model):
    response = json.loads(raw, object_pairs_hook=_unique)
    rows = response.get('data') if isinstance(response, dict) else None
    created = response.get('created') if isinstance(response, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or response.get('model') != model or type(created) is not int or created <= 0
            or rows[0].get('error') or not isinstance(rows[0].get('url'), str)
            or not rows[0]['url'].startswith('https://')):
        raise ValueError('Expected one original image URL, exact model and provider creation time')
    return response, rows[0]['url'], created


def submit_opening_frame(
    attempt_dir,
    config,
    *,
    http_client=None,
    download_client=None,
    ledger_path=None,
    record_calls=None,
):
    """Exactly one paid call; reservations survive every error or unknown outcome."""
    attempt_dir = Path(attempt_dir).resolve()
    receipt, request, folder, _, _ = _verify_inputs(attempt_dir, config)
    if receipt['status'] != 'prepared' or receipt['api_calls'] != 0:
        raise ValueError('Opening request was already attempted; inspect its preserved outcome, never resubmit')
    reservation_dir = folder / 'opening_frame_reservations'
    reservation_dir.mkdir(exist_ok=True)
    reservation = reservation_dir / (receipt['plan_sha256'] + '.json')
    reservation_value = {'schema': 'ark_opening_reservation/v1',
        'attempt_dir': str(attempt_dir), 'plan_sha256': receipt['plan_sha256'],
        'request_sha256': receipt['request_sha256'], 'binding': receipt['binding'],
        'credential_fingerprint': receipt['credential_fingerprint'], 'reserved_at': _now().isoformat()}
    reservation_sha = _write(reservation, reservation_value, exclusive=True)
    receipt.update(status='submit_outcome_unknown', api_calls=1,
                   caller_started_at=_now().isoformat(), reservation_path=str(reservation),
                   reservation_sha256=reservation_sha)
    _write(attempt_dir / RECEIPT_NAME, receipt)
    own_http, own_download = http_client is None, download_client is None
    http = http_client or httpx.Client(timeout=config.timeout_seconds)
    downloader = download_client or httpx.Client(timeout=config.timeout_seconds, follow_redirects=True)
    if record_calls is None:
        record_calls = own_http or ledger_path is not None
    ledger = ProviderCallLedger(ledger_path) if record_calls else None
    call_id = (
        ledger.begin_call(
            provider="ark_api",
            operation="image_generation",
            model=receipt["model"],
            request=request["body"],
            source_path=attempt_dir / RECEIPT_NAME,
            created_at=receipt["caller_started_at"],
        )
        if ledger is not None
        else ""
    )
    try:
        result = http.post(request['base_url'] + request['path'], json=request['body'],
                           headers={'Authorization': 'Bearer ' + config.api_key, 'Content-Type': 'application/json'})
        raw = result.content
        (attempt_dir / 'response.json').write_bytes(raw)
        receipt.update(response_sha256=_sha(raw), response_received_at=_now().isoformat(),
                       http_status=result.status_code)
        _write(attempt_dir / RECEIPT_NAME, receipt)
        result.raise_for_status()
        response, url, created = _image_response(raw, receipt['model'])
        receipt.update(status='image_created_pending_download', original_url=url, provider_created=created,
                       created_at=datetime.fromtimestamp(created, timezone.utc).isoformat(),
                       url_expires_at=datetime.fromtimestamp(created + 86400, timezone.utc).isoformat(),
                       usage=response.get('usage', {}))
        _write(attempt_dir / RECEIPT_NAME, receipt)
        if ledger is not None:
            ledger.mark_submitted(
                call_id,
                status="image_created_pending_download",
                response=response,
                http_status=result.status_code,
            )
        # A fresh unauthenticated media client prevents leaking the Ark key to a CDN.
        with downloader.stream('GET', url) as media:
            media.raise_for_status()
            raw_image = bytearray()
            for chunk in media.iter_bytes():
                raw_image.extend(chunk)
                if len(raw_image) > MAX_IMAGE_BYTES:
                    raise ValueError('Opening image exceeds 30 MiB')
        image_path = attempt_dir / IMAGE_NAME
        with image_path.open('xb') as handle:
            handle.write(raw_image)
        from .seedance_frames import image_info
        receipt.update(status='downloaded', image_info=image_info(image_path),
                       image_sha256=_sha(raw_image), finished_at=_now().isoformat())
        _write(attempt_dir / RECEIPT_NAME, receipt)
        if ledger is not None:
            ledger.mark_submitted(
                call_id,
                status="downloaded",
                response=response,
                http_status=result.status_code,
            )
        return receipt
    except Exception as exc:
        receipt.update(error_type=type(exc).__name__, finished_at=_now().isoformat())
        if isinstance(exc, httpx.HTTPStatusError) and exc.request.url.path == '/api/v3' + request['path']:
            if exc.response.status_code in (400, 401, 403, 404):
                receipt['status'] = 'request_rejected'
        _write(attempt_dir / RECEIPT_NAME, receipt)
        if ledger is not None:
            try:
                ledger.mark_failed(
                    call_id,
                    exc,
                    status=receipt["status"],
                    http_status=receipt.get("http_status"),
                )
            except Exception:
                pass
        raise
    finally:
        if own_http:
            http.close()
        if own_download:
            downloader.close()


def resume_opening_download(attempt_dir, config, *, download_client=None, now=None):
    """Recover only the original CDN download after a known successful creation."""
    attempt_dir = Path(attempt_dir).resolve()
    receipt, _, folder, _, _ = _verify_inputs(attempt_dir, config)
    if receipt.get('status') != 'image_created_pending_download' or receipt.get('api_calls') != 1:
        raise ValueError('Download recovery requires a preserved successful image response; unknown creation cannot retry')
    reservation = _inside(receipt['reservation_path'], folder)
    reservation_raw = reservation.read_bytes()
    reserved = json.loads(reservation_raw, object_pairs_hook=_unique)
    if (_sha(reservation_raw) != receipt['reservation_sha256']
            or reserved.get('attempt_dir') != str(attempt_dir)
            or any(reserved.get(key) != receipt.get(key) for key in
                   ('plan_sha256', 'request_sha256', 'binding', 'credential_fingerprint'))):
        raise ValueError('Opening submission reservation changed')
    raw = (attempt_dir / 'response.json').read_bytes()
    if _sha(raw) != receipt.get('response_sha256') or not 200 <= receipt.get('http_status', 0) < 300:
        raise ValueError('Original successful image response changed')
    _, url, created = _image_response(raw, receipt['model'])
    current = now or _now()
    if (receipt.get('original_url') != url or receipt.get('provider_created') != created
            or receipt.get('url_expires_at') != datetime.fromtimestamp(created + 86400, timezone.utc).isoformat()
            or not 0 <= current.timestamp() - created < 86400):
        raise ValueError('Original image URL changed or its 24-hour download window expired')
    if (attempt_dir / IMAGE_NAME).exists():
        raise ValueError('An original image file already exists; recovery never overwrites media')
    lock = attempt_dir / 'download_recovery.lock'
    _write(lock, {'schema': 'ark_opening_download_lock/v1', 'started_at': _now().isoformat()}, exclusive=True)
    own_download = download_client is None
    downloader = download_client or httpx.Client(timeout=config.timeout_seconds, follow_redirects=True)
    receipt.setdefault('download_recoveries', []).append({'started_at': _now().isoformat(),
        'response_sha256': receipt['response_sha256'], 'status': 'download_outcome_unknown',
        'image_generation_calls': 0})
    event = receipt['download_recoveries'][-1]
    _write(attempt_dir / RECEIPT_NAME, receipt)
    try:
        with downloader.stream('GET', url) as media:
            media.raise_for_status()
            raw_image = bytearray()
            for chunk in media.iter_bytes():
                raw_image.extend(chunk)
                if len(raw_image) > MAX_IMAGE_BYTES:
                    raise ValueError('Opening image exceeds 30 MiB')
        image_path = attempt_dir / IMAGE_NAME
        with image_path.open('xb') as handle:
            handle.write(raw_image)
        from .seedance_frames import image_info
        info = image_info(image_path)
        event.update(status='downloaded', finished_at=_now().isoformat(), image_sha256=info['sha256'])
        receipt.update(status='downloaded', image_info=info, image_sha256=info['sha256'], finished_at=_now().isoformat())
        _write(attempt_dir / RECEIPT_NAME, receipt)
        return receipt
    except Exception as exc:
        event.update(status='download_failed', error_type=type(exc).__name__, finished_at=_now().isoformat())
        _write(attempt_dir / RECEIPT_NAME, receipt)
        raise
    finally:
        if own_download:
            downloader.close()
        lock.unlink()


def trusted_opening_reference(run_dir, image, config, manifest, direction, *, now=None):
    """Verify the original Seedream response and bytes, never relabel a video tail."""
    image = _inside(image, run_dir)
    receipt, request, folder, actual_manifest, actual_direction = _verify_inputs(image.parent, config)
    if 'image' in request['body']:
        raise ValueError('Reference-guided image is not a text-to-image opening; provider eligibility must be resolved before video use')
    if actual_manifest != manifest or actual_direction != direction or folder != Path(run_dir).resolve():
        raise ValueError('Opening target run changed')
    if receipt.get('status') != 'downloaded' or receipt.get('api_calls') != 1:
        raise ValueError('Opening image has no completed original generation receipt')
    reservation = _inside(receipt['reservation_path'], folder)
    reservation_raw = reservation.read_bytes()
    reserved = json.loads(reservation_raw, object_pairs_hook=_unique)
    if (_sha(reservation_raw) != receipt['reservation_sha256']
            or any(reserved.get(key) != receipt.get(key) for key in
                   ('plan_sha256', 'request_sha256', 'binding', 'credential_fingerprint'))
            or reserved.get('attempt_dir') != str(image.parent)):
        raise ValueError('Opening submission reservation changed')
    raw = (image.parent / 'response.json').read_bytes()
    if _sha(raw) != receipt.get('response_sha256'):
        raise ValueError('Original image response changed')
    _, url, created = _image_response(raw, receipt['model'])
    current = now or _now()
    if (not 0 <= current.timestamp() - created < 30 * 86400
            or receipt.get('provider_created') != created or receipt.get('original_url') != url):
        raise ValueError('Original image URL or documented 30-day validity changed')
    if (current.timestamp() >= created + 86400 or receipt.get('url_expires_at') !=
            datetime.fromtimestamp(created + 86400, timezone.utc).isoformat()):
        raise ValueError('Original image URL expired after 24 hours; the 30-day trust window does not extend it')
    from .seedance_frames import image_info
    info = image_info(image)
    if info != receipt.get('image_info') or info['sha256'] != receipt.get('image_sha256'):
        raise ValueError('Original opening image bytes changed')
    proof = {'schema': RECEIPT_SCHEMA, 'receipt_path': str(image.parent / RECEIPT_NAME),
             'receipt_sha256': _sha((image.parent / RECEIPT_NAME).read_bytes()),
             'image_sha256': info['sha256'], 'response_sha256': receipt['response_sha256'],
             'model': receipt['model'], 'created_at': receipt['created_at'],
             'verification': 'same_ark_credential_original_text_to_image_receipt'}
    return SeedanceReference('image', url, 'first_frame'), proof


def _import_campaign(source_folder, source_manifest, target_folder, target_manifest, *, preparing=False):
    """Read the same current series without editing or resetting its history."""
    from .video_campaign import (_run_series, _failed_count, failure_limit,
                                 RESOLVED_ATTEMPT_STATUSES)
    source_path, target_path = source_manifest.get('campaign_path'), target_manifest.get('campaign_path')
    if (not isinstance(source_path, str) or not source_path or not isinstance(target_path, str)
            or Path(source_path).resolve() != Path(target_path).resolve()):
        raise ValueError('Opening import requires the same existing campaign')
    campaign_path = Path(source_path).resolve()
    if not source_folder.is_relative_to(campaign_path.parent) or not target_folder.is_relative_to(campaign_path.parent):
        raise ValueError('Both opening runs must remain inside their campaign directory')
    campaign = _read(campaign_path)
    source_series = _run_series(campaign, source_manifest, source_folder)
    target_series = _run_series(campaign, target_manifest, target_folder)
    if source_series != target_series:
        raise ValueError('Opening import requires the same current campaign series')
    if preparing:
        if (campaign.get('holds') or _failed_count(campaign) >= failure_limit(campaign)
                or campaign.get('status') == 'paused_for_human_review'):
            raise ValueError('Opening import cannot clear campaign holds or the accumulated failure limit')
        if any(row.get('status') not in RESOLVED_ATTEMPT_STATUSES for row in campaign.get('attempts', [])):
            raise ValueError('Reconcile the outstanding campaign generation or review before importing')
    return {'path': str(campaign_path), 'series_id': source_series}


def _checked_import_source(source_run, source_image, config):
    from .seedance_frames import reviewed_frame_reference
    folder, manifest, direction, binding = _run_inputs(source_run)
    image = _inside(source_image, folder)
    if (image.name != IMAGE_NAME or not (image.parent / RECEIPT_NAME).is_file()
            or (image.parent / IMPORT_NAME).exists()):
        raise ValueError('Import directly from an original Seedream receipt, not an imported copy')
    # This rechecks the original response, current key/base, expiry, and actual
    # frame review. No review checks or reviewed_at values are fabricated here.
    reference, review = reviewed_frame_reference(folder, 'S01', image, manifest, direction, config=config)
    original = review.get('original_ark_image')
    if not isinstance(original, dict) or original.get('schema') != RECEIPT_SCHEMA:
        raise ValueError('Source opening has no original image proof')
    review_path = folder / 'frame_reviews/S01.json'
    evidence = []
    for name in review['evidence']:
        path = _inside(folder / name, folder)
        evidence.append({'path': str(path), 'sha256': _sha(path.read_bytes())})
    source = {'run_dir': str(folder), 'image': str(image), 'binding': binding,
        'image_sha256': _sha(image.read_bytes()), 'original_proof': original,
        'frame_review': {'path': str(review_path), 'sha256': _sha(review_path.read_bytes())},
        'frame_review_evidence': evidence}
    return folder, manifest, reference, review, source


def import_opening_frame(run_dir, source_run, source_image, output_dir, config):
    """Copy an already reviewed original image to the same-source current series."""
    folder, manifest, _, binding = _run_inputs(run_dir)
    source_folder, source_manifest, reference, review, source = _checked_import_source(source_run, source_image, config)
    if source_folder == folder or source['binding'] != binding:
        raise ValueError('Opening import requires another run with the exact same script, direction and S01')
    if (manifest.get('api_base_url', '').rstrip('/') != _base(config)
            or manifest.get('api_model') != source_manifest.get('api_model')):
        raise ValueError('Opening import target must use the same Ark base and video model')
    campaign = _import_campaign(source_folder, source_manifest, folder, manifest, preparing=True)
    if manifest.get('status') != 'prepared' or (folder / 'S01.json').exists() or (folder / 'frame_reviews/S01.json').exists():
        raise ValueError('Import into a freshly prepared run without an existing S01 submission or frame binding')
    output = _inside(output_dir, folder)
    if output == folder:
        raise ValueError('Use a new opening-import subdirectory')
    image = output / IMAGE_NAME
    raw = Path(source['image']).read_bytes()
    if _sha(raw) != source['image_sha256']:
        raise ValueError('Source image changed while preparing import')
    record = {'schema': IMPORT_SCHEMA, 'created_at': _now().isoformat(), 'status': 'imported',
        'run_dir': str(folder), 'binding': binding, 'source': source, 'campaign': campaign,
        'image': str(image), 'image_sha256': source['image_sha256'], 'image_info': review['image_info'],
        'api_base_url': _base(config), 'credential_fingerprint': credential_fingerprint(config),
        'original_url': reference.source, 'api_calls': 0, 'image_generation_calls': 0,
        'media_review': 'inherited_source_frame_review', 'new_media_review_performed': False,
        'video_generation_submitted': False}
    output.mkdir(parents=True, exist_ok=False)
    with image.open('xb') as handle:
        handle.write(raw)
    _write(output / IMPORT_NAME, record, exclusive=True)
    return record


def trusted_imported_opening_reference(run_dir, image, config, manifest, direction):
    """Replay an import against the unchanged actual source review and raw URL."""
    from .seedance_frames import image_info
    folder, actual_manifest, actual_direction, binding = _run_inputs(run_dir)
    image = _inside(image, folder)
    record_path = image.parent / IMPORT_NAME
    record = _read(record_path)
    if (actual_manifest != manifest or actual_direction != direction or image.name != IMAGE_NAME
            or (image.parent / RECEIPT_NAME).exists()
            or record.get('schema') != IMPORT_SCHEMA or record.get('status') != 'imported'
            or record.get('run_dir') != str(folder) or record.get('binding') != binding
            or record.get('image') != str(image) or record.get('api_base_url') != _base(config)
            or manifest.get('api_base_url', '').rstrip('/') != _base(config)
            or record.get('credential_fingerprint') != credential_fingerprint(config)
            or record.get('api_calls') != 0 or record.get('image_generation_calls') != 0
            or record.get('new_media_review_performed') is not False
            or record.get('media_review') != 'inherited_source_frame_review'
            or record.get('video_generation_submitted') is not False):
        raise ValueError('Opening import target, account or provenance changed')
    source = record.get('source', {})
    source_folder, source_manifest, reference, source_review, actual_source = _checked_import_source(
        source['run_dir'], source['image'], config)
    campaign = _import_campaign(source_folder, source_manifest, folder, manifest)
    info = image_info(image)
    if (source_folder == folder or actual_source != source or actual_source['binding'] != binding
            or manifest.get('api_model') != source_manifest.get('api_model')
            or record.get('campaign') != campaign or record.get('original_url') != reference.source
            or record.get('image_info') != info or record.get('image_sha256') != info['sha256']
            or info != source_review['image_info'] or info['sha256'] != actual_source['image_sha256']):
        raise ValueError('Imported image or its original source/review bytes changed')
    proof = {'schema': IMPORT_SCHEMA, 'import_path': str(record_path), 'import_sha256': _sha(record_path.read_bytes()),
        'source_original': source['original_proof'], 'source_frame_review': source['frame_review'],
        'image_sha256': info['sha256'], 'verification': 'same_source_same_campaign_original_image_import'}
    inherited_binding = {'schema': 'ark_opening_frame_import_binding/v1', 'shot_id': 'S01',
        'camera_id': direction['shots'][0]['camera_id'], 'image': str(image), 'image_info': info,
        'script_sha256': binding['script_sha256'], 'direction_sha256': binding['direction_sha256'],
        'review_origin': 'inherited_source_frame_review', 'new_media_review_performed': False,
        'source_frame_review': source['frame_review'], 'original_ark_image': proof}
    return reference, inherited_binding
