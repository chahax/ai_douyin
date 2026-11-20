"""Durable serial generation gate; evidence extraction alone never releases it."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

from .script_video_review import REVIEW_CHECKS, file_sha

LEGACY_SERIES = 'legacy'
RESOLVED_ATTEMPT_STATUSES = {'passed', 'failed', 'request_rejected', 'superseded', 'visual_passed_audio_pending'}
VISUAL_CHECKS = ('identity', 'spatial_layout', 'props_and_hands', 'action_pace', 'cut_continuity')
AUDIO_CHECKS = ('dialogue_pace', 'speaker_voice', 'lip_sync')
BASE_FAILURE_LIMIT = 10
MAX_HUMAN_RESUME_INCREMENT = 3


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def _failed_count(data):
    if data.get('failure_budget_policy') == 'per_script/v1':
        key = _budget_key(data, _current_series(data))
        return sum(_attempt_failed(a) for a in data.get('attempts', [])
                   if _budget_key(data, _attempt_series(a)) == key)
    recorded = data.get('failed_outputs', 0)
    if type(recorded) is not int or recorded < 0:
        raise ValueError('Campaign cumulative failure count is invalid')
    return max(recorded, sum(a['status'] == 'failed' or any(
        row.get('previous_attempt', {}).get('status') == 'failed'
        for row in a.get('reassessment_history', [])) for a in data.get('attempts', [])))


def _attempt_failed(attempt):
    return attempt.get('status') == 'failed' or any(
        row.get('previous_attempt', {}).get('status') == 'failed'
        for row in attempt.get('reassessment_history', []))


def _budget_key(data, series_id):
    series = next((s for s in data.get('series', []) if s['id'] == series_id), {})
    return series.get('script_budget_key', 'historical_shared_budget')


def _screenplay_key(data, series_id):
    series = next((s for s in data.get('series', []) if s['id'] == series_id), {})
    return series.get('screenplay', {}).get('key', _budget_key(data, series_id))


def visual_continuation_authorized(data, series_id):
    series = next((s for s in data.get('series', []) if s['id'] == series_id), {})
    binding = series.get('visual_continuation_authorization')
    if not binding:
        return False
    if file_sha(binding['path']) != binding['sha256']:
        raise ValueError('Visual continuation authorization changed')
    value = read(binding['path'])
    return (value.get('schema') == 'visual_continuation_authorization/v1'
            and value.get('allow_visual_continuation') is True
            and bool(value.get('user_quote')) and value.get('deferred_checks') == list(AUDIO_CHECKS))


def review_allows_continuation(data, series_id, review):
    checks = review.get('checks', {})
    if set(checks) != set(REVIEW_CHECKS):
        return False
    if review.get('decision') == 'passed':
        return all(v is True for v in checks.values()) and all(v is True for v in review.get('creative_checks', {}).values())
    return (review.get('decision') == 'visual_passed_audio_pending'
            and visual_continuation_authorized(data, series_id)
            and all(checks[k] is True for k in VISUAL_CHECKS)
            and all(checks[k] is None or checks[k] is True for k in AUDIO_CHECKS)
            and review.get('creative_checks') == {'visual_storytelling': True})


def attempt_allows_continuation(data, attempt):
    if attempt.get('status') not in ('passed', 'visual_passed_audio_pending'):
        return False
    path = attempt.get('review_path')
    if not path or file_sha(path) != attempt.get('review_sha256'):
        raise ValueError('Continuation review changed')
    review = read(path)
    return (review.get('decision') == attempt['status']
            and review.get('source_sha256') == attempt.get('delivery_video_sha256', attempt.get('video_sha256'))
            and review_allows_continuation(data, _attempt_series(attempt), review))


def lifetime_failed_count(data):
    return max(data.get('lifetime_failed_outputs', 0),
               data.get('failed_outputs', 0) if data.get('failure_budget_policy') != 'per_script/v1' else 0,
               sum(_attempt_failed(a) for a in data.get('attempts', [])))


def script_budget_identity(path):
    """Formatting or photography changes do not create a new script budget."""
    path = Path(path).resolve()
    script = read(path)
    if script.get('schema') == 'cohort_video_script/v1':
        from scripts.run_cohort_video import verify_bundle
        _,verified=verify_bundle(path.parent)
        if verified!=script:raise ValueError('Cohort video script must match its verified source bundle')
    elif script.get('schema') in {'director_video_script/v1','reference_director_video_script/v1'}:
        from scripts.run_director_video import verify_bundle
        _,verified=verify_bundle(path.parent)
        if verified!=script:raise ValueError('Director script must match its reviewed source bundle')
    elif script.get('schema') != 'script_screenplay/v1':
        raise ValueError('New script budget requires a complete project screenplay')
    version = script['version']
    shots = version.get('shots')
    if not isinstance(shots, list) or not shots:
        raise ValueError('New script budget requires actual screenplay shots')
    identity = {'characters': [(c['name'], c['identity']) for c in script['characters']],
                'shots': [{k: shot[k] for k in ('shot_id', 'duration_seconds', 'dialogue_speaker', 'dialogue', 'action')}
                          for shot in shots]}
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'path': str(path), 'sha256': file_sha(path), 'key': key,
            'shots': [s['shot_id'] for s in shots]}


def failure_limit(data):
    """Return the audited effective limit without changing the original cap.

    The campaign's original ten-failure limit remains immutable.  A human can
    explicitly add a small increment after a pause; each increment is chained
    to the prior effective limit so deleting or reordering an authorization is
    detected instead of silently reopening paid generation.
    """
    base = data.get('max_failed_outputs')
    if base != BASE_FAILURE_LIMIT:
        raise ValueError('This campaign requires the original cumulative ten-failure limit')
    rows = data.get('human_resume_authorizations', [])
    if not isinstance(rows, list):
        raise ValueError('Campaign human resume authorizations are invalid')
    current = base
    seen = set()
    for index, row in enumerate(rows, 1):
        if (data.get('failure_budget_policy') == 'per_script/v1'
                and _budget_key(data, row.get('series_id')) != _budget_key(data, _current_series(data))):
            continue
        increment = row.get('additional_failed_outputs') if isinstance(row, dict) else None
        expected_id = f'human_resume_{index:03}'
        if (not isinstance(row, dict) or row.get('schema') != 'human_resume_authorization/v1'
                or row.get('id') != expected_id or row['id'] in seen
                or row.get('original_max_failed_outputs') != base
                or row.get('prior_effective_failure_limit') != current
                or type(increment) is not int
                or not 1 <= increment <= MAX_HUMAN_RESUME_INCREMENT
                or row.get('effective_failure_limit') != current + increment
                or row.get('failed_outputs_at_authorization') != current
                or not isinstance(row.get('authorization'), str) or not row['authorization'].strip()
                or not isinstance(row.get('authorized_at_beijing'), str)
                or not isinstance(row.get('series_id'), str)
                or not isinstance(row.get('shot'), str)
                or not isinstance(row.get('authorized_source_revision_from_sha256'), str)
                or not isinstance(row.get('resulting_script_sha256'), str)):
            raise ValueError('Campaign human resume authorization chain is invalid')
        seen.add(row['id'])
        current += increment
    return current


def _current_series(data):
    current = data.get('current_series_id', LEGACY_SERIES)
    if current != LEGACY_SERIES and not any(s.get('id') == current for s in data.get('series', [])):
        raise ValueError('Campaign current revision series is missing')
    return current


def _attempt_series(attempt):
    return attempt.get('series_id', LEGACY_SERIES)


def _run_series(data, manifest, folder=None, *, current=True):
    series_id = manifest.get('campaign_series_id', LEGACY_SERIES)
    if current and series_id != _current_series(data):
        raise ValueError('Run belongs to an older campaign revision series; prepare and attach a new run')
    if series_id != LEGACY_SERIES:
        series = next((s for s in data.get('series', []) if s.get('id') == series_id), None)
        if series is None or (folder is not None and str(Path(folder).resolve()) not in series.get('runs', [])):
            raise ValueError('Run is not registered in this campaign revision series')
    return series_id


def _downloaded_supersession_proof(campaign_path, data, attempt):
    """A locally complete pending review may be superseded, never marked passed."""
    if attempt.get('status') != 'awaiting_review':
        raise ValueError('Only an awaiting_review attempt can be superseded; reconcile outstanding generation first')
    folder = Path(attempt['run_dir']).resolve()
    if not folder.is_relative_to(campaign_path.parent):
        raise ValueError('Superseded output must remain inside this campaign')
    record_path = folder / f"{attempt['shot']}.json"
    manifest, record = read(folder / 'production.json'), read(record_path)
    video = Path(record.get('local_video', '')).resolve()
    digest = record.get('video_sha256')
    latest = record.get('latest_response')
    if (record.get('status') != 'downloaded' or record.get('campaign_attempt_id') != attempt['id']
            or record.get('shot') != attempt['shot']
            or any(record.get(k) != attempt.get(k) for k in ('script_sha256', 'prompt_sha256'))
            or not isinstance(digest, str) or len(digest) != 64
            or attempt.get('video_sha256') != digest or not video.is_relative_to(folder)
            or not video.is_file() or file_sha(video) != digest
            or Path(manifest.get('campaign_path', '')).resolve() != campaign_path
            or manifest.get('script_sha256') != attempt['script_sha256']
            or manifest.get('api_model') != data['model'] or manifest.get('provider') != data['provider']
            or _run_series(data, manifest, folder, current=False) != _attempt_series(attempt)
            or (latest is not None and (not isinstance(latest, dict) or latest.get('status') != 'succeeded'))):
        raise ValueError('Supersession requires the exact locally downloaded output and matching receipt/video SHA')
    return {'record_path': str(record_path), 'record_sha256': file_sha(record_path),
            'video_path': str(video), 'video_sha256': digest,
            'recorded_status': record['status'], 'task_id': record.get('submit_id'),
            'verification': 'local_download_and_exact_hash_only_not_quality_approval'}


def start_revision(campaign_path, *, authorization, reason, supersede_attempt_ids=(), new_script=None, revised_script=None, visual_authorization=None):
    """Explicitly begin a complete new series without resetting the campaign.

    Existing runs/attempts remain historical. Attach a freshly prepared run after
    this call; ordinary upstream retries use attach() within the same series.
    No provider requests or quality approvals are made here.
    """
    campaign_path = Path(campaign_path).resolve()
    if new_script and revised_script:
        raise ValueError('Choose a new story budget or a same-story revision, never both')
    new_identity = script_budget_identity(new_script) if new_script else None
    revised_identity = script_budget_identity(revised_script) if revised_script else None
    if any(not isinstance(value, str) or not value.strip() for value in (authorization, reason)):
        raise ValueError('A new complete revision requires explicit user authorization and a reason')
    if (not isinstance(supersede_attempt_ids, (tuple, list))
            or any(not isinstance(value, str) or not value for value in supersede_attempt_ids)
            or len(supersede_attempt_ids) != len(set(supersede_attempt_ids))):
        raise ValueError('supersede_attempt_ids must be explicit unique attempt IDs')
    with ledger(campaign_path) as data:
        failed = _failed_count(data)
        lifetime = lifetime_failed_count(data)
        if data.get('max_failed_outputs') != 10 or not data.get('authorization'):
            raise ValueError('This campaign requires the authorized cumulative ten-failure limit')
        if not new_identity and (failed >= failure_limit(data) or data.get('status') == 'paused_for_human_review'):
            raise ValueError('Ten failed generated outputs: pause for human review; revision cannot reset the lock')
        shots = data.get('shots')
        if not isinstance(shots, list) or not shots or len(set(shots)) != len(shots):
            raise ValueError('A complete revision requires the existing campaign shot order')
        if new_identity:
            if new_identity['shots'] != shots and read(new_script).get('schema') not in {'director_video_script/v1','reference_director_video_script/v1'}:
                raise ValueError('New script must preserve the campaign shot order')
            if any(new_identity['key'] in (s.get('script_budget_key'), s.get('screenplay', {}).get('key')) for s in data.get('series', [])):
                raise ValueError('This script already has a budget; retries cannot reset it')
        previous_id = _current_series(data)
        attempts = data.setdefault('attempts', [])
        outstanding = [a for a in attempts if a.get('status') not in RESOLVED_ATTEMPT_STATUSES]
        if {a['id'] for a in outstanding} != set(supersede_attempt_ids):
            raise ValueError('Explicitly identify every outstanding pending review; unknown tasks cannot be superseded')
        proofs = {a['id']: _downloaded_supersession_proof(campaign_path, data, a) for a in outstanding}
        started_at = now()
        series = data.setdefault('series', [])
        if not series:
            series.append({'id': LEGACY_SERIES, 'created_at': data.get('created_at'),
                           'shots': list(shots), 'runs': list(data.get('runs', [])), 'status': data.get('status')})
        previous = next((s for s in series if s.get('id') == previous_id), None)
        if previous is None:
            raise ValueError('Previous campaign series is missing')
        if revised_identity:
            if data.get('failure_budget_policy') != 'per_script/v1' or not previous.get('screenplay'):
                raise ValueError('Same-story revision requires an existing screenplay budget')
            old_binding = previous['screenplay']
            if file_sha(old_binding['path']) != old_binding['sha256']:
                raise ValueError('Previous screenplay changed')
            old_script, new_value = read(old_binding['path']), read(revised_script)
            def core(value):
                return ([(c['name'], c['identity']) for c in value['characters']],
                        [(s['shot_id'], s['dialogue_speaker'], s['dialogue']) for s in value['version']['shots']])
            if revised_identity['shots'] != shots or core(old_script) != core(new_value):
                raise ValueError('Same-story pacing revision must preserve characters, ordered shots and dialogue')
        series_id = f'series_{len(series):03}'
        if any(s.get('id') == series_id for s in series):
            raise ValueError('Revision series identity already exists')
        for attempt in outstanding:
            attempt.update(status='superseded', superseded_from_status=attempt['status'],
                superseded_at=started_at, superseded_by_series_id=series_id,
                supersession={'reason': reason, 'authorization': authorization, 'proof': proofs[attempt['id']]})
        previous.update(superseded_from_status=previous.get('status'), status='superseded',
                        superseded_at=started_at, superseded_by_series_id=series_id)
        # A verified complete director story can have a different number of
        # segments. Prior series keep their original order and all receipts.
        if new_identity:
            shots=list(new_identity['shots'])
            data['shots']=list(shots)
        revision = {'id': series_id, 'previous_series_id': previous_id, 'created_at': started_at,
                    'authorization': authorization, 'reason': reason, 'shots': list(shots), 'runs': [],
                    'superseded_attempt_ids': list(supersede_attempt_ids), 'failed_outputs_at_start': failed,
                    'status': 'active'}
        if visual_authorization:
            proof = Path(visual_authorization).resolve()
            revision['visual_continuation_authorization'] = {'path':str(proof),'sha256':file_sha(proof)}
            if not visual_continuation_authorized({'series':[revision]}, series_id):
                raise ValueError('Explicit visual continuation authorization required')
        if new_identity:
            revision.update(script_budget_key=new_identity['key'], screenplay=new_identity,
                            failure_budget_authorization=authorization)
            data.update(failure_budget_policy='per_script/v1', lifetime_failed_outputs=lifetime)
            failed = 0
        elif data.get('failure_budget_policy') == 'per_script/v1':
            revision['script_budget_key'] = _budget_key(data, previous_id)
            revision['screenplay'] = revised_identity or previous['screenplay']
            if revised_identity:
                revision['same_story_revision'] = {'previous_screenplay':previous['screenplay'],
                    'revised_screenplay':revised_identity, 'failure_budget_reset':False,
                    'authorization':authorization, 'reason':reason}
        series.append(revision)
        data.update(current_series_id=series_id, status='awaiting_next_segment', failed_outputs=failed)
        if data.get('failure_budget_policy') == 'per_script/v1':
            data['effective_failure_limit'] = failure_limit(data)
    return {'series_id': series_id, 'previous_series_id': previous_id, 'failed_outputs': failed,
            'next_shot': shots[0], 'superseded_attempt_ids': list(supersede_attempt_ids), 'created_at': started_at}


@contextmanager
def ledger(path):
    path = Path(path).resolve()
    lock = path.with_suffix('.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError('Campaign is being updated; inspect the lock before resuming') from exc
    try:
        os.close(fd)
        data = read(path)
        if data.get('schema') != 'sequential_video_campaign/v1':
            raise ValueError('Unsupported campaign schema')
        yield data
        data['updated_at'] = now()
        write(path, data)
    finally:
        lock.unlink()


def attach(folder, campaign_path):
    """Opt a prepared run into one persistent campaign, including all retries."""
    folder, campaign_path = Path(folder).resolve(), Path(campaign_path).resolve()
    if not folder.is_relative_to(campaign_path.parent):
        raise ValueError('Campaign runs must remain inside their campaign directory')
    manifest = read(folder / 'production.json')
    if manifest.get('campaign_path'):
        if Path(manifest['campaign_path']).resolve() == campaign_path:
            _run_series(read(campaign_path), manifest, folder)
            return
        raise ValueError('A run cannot switch campaigns or reset its existing failure ledger')
    if manifest.get('video_generation_submitted'):
        raise ValueError('Attach the campaign before any submission')
    with ledger(campaign_path) as data:
        if data.get('max_failed_outputs') != 10 or not data.get('authorization'):
            raise ValueError('This campaign requires the authorized cumulative ten-failure limit')
        if manifest.get('api_model') != data.get('model') or manifest.get('provider') != data.get('provider'):
            raise ValueError('Run model/provider differs from the campaign')
        if data.get('shots') and data['shots'] != manifest['shots']:
            raise ValueError('Targeted revisions must retain the campaign shot order')
        series_id = _current_series(data)
        if data.get('failure_budget_policy') == 'per_script/v1':
            series = next(s for s in data['series'] if s['id'] == series_id)
            actual = script_budget_identity(manifest.get('source_screenplay', ''))
            if actual['key'] != _screenplay_key(data, series_id):
                raise ValueError('Run screenplay differs from this script failure budget')
        if any(str(folder) in s.get('runs', []) and s['id'] != series_id for s in data.get('series', [])):
            raise ValueError('An old run cannot switch into a new revision series')
        data['shots'] = manifest['shots']
        if str(folder) not in data.setdefault('runs', []):
            data['runs'].append(str(folder))
        if series_id != LEGACY_SERIES:
            series = next(s for s in data['series'] if s['id'] == series_id)
            if str(folder) not in series['runs']:
                series['runs'].append(str(folder))
    manifest['campaign_path'] = str(campaign_path)
    manifest['campaign_series_id'] = series_id
    write(folder / 'production.json', manifest)


def _project_script_binding(folder, manifest):
    """Recheck the target run's project-authored script and current M3 review."""
    from src.trend_intelligence.saved_script_review import require_current_saved_script_review
    folder = Path(folder).resolve()
    locked_script = folder / 'locked_script.json'
    source_value = manifest.get('source_script')
    if not isinstance(source_value, str) or not source_value:
        raise ValueError('Human resume requires the prepared project script source')
    source_script = Path(source_value).resolve()
    if (not locked_script.is_file() or not source_script.is_file()
            or file_sha(locked_script) != manifest.get('script_sha256')
            or file_sha(source_script) != manifest.get('script_sha256')
            or read(locked_script) != read(source_script)):
        raise ValueError('Human resume target must retain the exact prepared project script')
    script = read(locked_script)
    if script.get('generation', {}).get('method') != 'staged_screenplay_bundle':
        raise ValueError('Human resume is limited to the project staged screenplay workflow')
    review = require_current_saved_script_review(source_script)
    saved_review = manifest.get('script_editorial_review')
    if (review.get('status') != 'current_passed' or review.get('current_passed') is not True
            or review.get('script_json_sha256') != manifest['script_sha256']
            or not isinstance(saved_review, dict)
            or any(saved_review.get(key) != review.get(key) for key in (
                'status', 'current_passed', 'report_path', 'candidate_sha256',
                'evidence_sha256', 'script_json_sha256'))):
        raise ValueError('Human resume target needs the current project M3 editorial review')
    report = Path(review['report_path']).resolve()
    if not report.is_file():
        raise ValueError('Human resume project review report is missing')
    return {'source_script': str(source_script), 'source_script_sha256': file_sha(source_script),
            'review_report': str(report), 'review_report_sha256': file_sha(report),
            'review_status': review['status'], 'review_candidate_sha256': review['candidate_sha256']}


def _same_story_s01_action_revision(before, after):
    """Allow a new formal SHA only when S01 action text is the story change.

    Compilation may restate that action in ``model_prompt_zh`` and refresh
    provenance timestamps.  Dialogue, timing, ending, all other S01 fields and
    every later shot remain exact.
    """
    if (not isinstance(before, dict) or not isinstance(after, dict)
            or before.get('schema') != 'detailed_video_script/v4'
            or after.get('schema') != 'detailed_video_script/v4'):
        raise ValueError('Human resume comparison requires detailed v4 scripts')
    before_top = {k: v for k, v in before.items() if k not in {'generation', 'created_at', 'shots'}}
    after_top = {k: v for k, v in after.items() if k not in {'generation', 'created_at', 'shots'}}
    before_shots, after_shots = before.get('shots'), after.get('shots')
    if (before_top != after_top or not isinstance(before_shots, list)
            or not isinstance(after_shots, list) or len(before_shots) != len(after_shots)
            or not before_shots):
        raise ValueError('Human resume permits the same story with an S01 action revision only')
    if before_shots[1:] != after_shots[1:]:
        raise ValueError('Human resume cannot change later shots, dialogue or story closure')
    ignored = {'action', 'model_prompt_zh'}
    old_s01 = {k: v for k, v in before_shots[0].items() if k not in ignored}
    new_s01 = {k: v for k, v in after_shots[0].items() if k not in ignored}
    if (old_s01 != new_s01 or before_shots[0].get('action') == after_shots[0].get('action')
            or not str(after_shots[0].get('action', '')).strip()):
        raise ValueError('Human resume permits a real S01 action revision, with all frozen fields unchanged')
    return ['shots/S01/action', 'shots/S01/model_prompt_zh']


def authorize_human_resume(campaign_path, target_folder, *, authorization,
                           additional_failed_outputs=1):
    """Record one explicit post-cap allowance without erasing the ten failures.

    This is a local ledger operation.  It performs no provider request and does
    not mark any video or audio check as passed.
    """
    campaign_path, target_folder = Path(campaign_path).resolve(), Path(target_folder).resolve()
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError('Human resume requires the exact explicit user authorization')
    if (type(additional_failed_outputs) is not int
            or not 1 <= additional_failed_outputs <= MAX_HUMAN_RESUME_INCREMENT):
        raise ValueError('Human resume may add only one to three failed-output allowances')
    if not target_folder.is_relative_to(campaign_path.parent):
        raise ValueError('Human resume target must remain inside this campaign')
    manifest = read(target_folder / 'production.json')
    if (Path(manifest.get('campaign_path', '')).resolve() != campaign_path
            or manifest.get('video_generation_submitted') is True):
        raise ValueError('Prepare and attach an unsubmitted target run before human resume')
    target_binding = _project_script_binding(target_folder, manifest)
    marker_path = campaign_path.with_name('HUMAN_REVIEW_REQUIRED.json')
    if not marker_path.is_file():
        raise ValueError('The original ten-failure human review marker is missing')
    marker = read(marker_path)
    marker_raw_sha = file_sha(marker_path)
    if (not isinstance(marker.get('failures'), list)
            or len(marker['failures']) < BASE_FAILURE_LIMIT
            or any(row.get('status') != 'failed' for row in marker['failures'][:BASE_FAILURE_LIMIT])):
        raise ValueError('The original ten-failure human review marker is invalid')
    with ledger(campaign_path) as data:
        failed_count = _failed_count(data)
        prior_limit = failure_limit(data)
        if failed_count != prior_limit or data.get('status') != 'paused_for_human_review':
            raise ValueError('Human resume is available only at the current audited failure limit')
        if any(a.get('status') not in RESOLVED_ATTEMPT_STATUSES for a in data.get('attempts', [])):
            raise ValueError('Reconcile every outstanding or unknown task before human resume')
        series_id = _run_series(data, manifest, target_folder)
        current_attempts = [a for a in data.get('attempts', []) if _attempt_series(a) == series_id]
        passed = {a['shot'] for a in current_attempts if a.get('status') == 'passed'}
        next_shot = next((shot for shot in data.get('shots', []) if shot not in passed), None)
        failures = [a for a in current_attempts
                    if a.get('status') == 'failed' and a.get('shot') == next_shot]
        if next_shot is None or not failures:
            raise ValueError('Human resume requires the latest failed next segment in the current series')
        previous = failures[-1]
        previous_folder = Path(previous.get('run_dir', '')).resolve()
        previous_script_path = previous_folder / 'locked_script.json'
        if (not previous_folder.is_relative_to(campaign_path.parent)
                or not previous_script_path.is_file()
                or file_sha(previous_script_path) != previous.get('script_sha256')):
            raise ValueError('Human resume source script or latest failed attempt changed')
        target_sha = manifest.get('script_sha256')
        if target_sha == previous['script_sha256']:
            revision = {'kind': 'execution_text_revision_required',
                        'changed_fields': [], 'project_review': target_binding}
        else:
            changed = _same_story_s01_action_revision(read(previous_script_path),
                                                       read(target_folder / 'locked_script.json'))
            revision = {'kind': 'm3_s01_action_revision', 'changed_fields': changed,
                        'project_review': target_binding}
        rows = data.setdefault('human_resume_authorizations', [])
        auth_id = f'human_resume_{len(rows)+1:03}'
        authorized_at = beijing_now()
        row = {'schema': 'human_resume_authorization/v1', 'id': auth_id,
               'authorization': authorization, 'authorized_at_beijing': authorized_at,
               'timezone': 'Asia/Shanghai', 'series_id': series_id, 'shot': next_shot,
               'original_max_failed_outputs': data['max_failed_outputs'],
               'prior_effective_failure_limit': prior_limit,
               'additional_failed_outputs': additional_failed_outputs,
               'effective_failure_limit': prior_limit + additional_failed_outputs,
               'failed_outputs_at_authorization': failed_count,
               'attempt_count_at_authorization': len(data.get('attempts', [])),
               'latest_failed_attempt_id': previous['id'],
               'authorized_source_revision_from_sha256': previous['script_sha256'],
               'resulting_script_sha256': target_sha, 'target_run_dir': str(target_folder),
               'revision': revision,
               'human_review_marker': {'path': str(marker_path), 'sha256': marker_raw_sha,
                                       'recorded_failure_count': len(marker['failures'])},
               'provider_requests_created': 0, 'media_reviews_changed': 0}
        rows.append(row)
        # Revalidate the complete chain before committing it.
        effective_limit = failure_limit(data)
        data.update(status='awaiting_upstream_revision', failed_outputs=failed_count,
                    effective_failure_limit=effective_limit)
    return {'status': 'authorized_for_upstream_revision', 'authorization_id': auth_id,
            'series_id': series_id, 'shot': next_shot, 'failed_outputs': failed_count,
            'original_max_failed_outputs': BASE_FAILURE_LIMIT,
            'effective_failure_limit': effective_limit,
            'authorized_source_revision_from_sha256': previous['script_sha256'],
            'resulting_script_sha256': target_sha, 'authorized_at_beijing': authorized_at,
            'provider_requests_created': 0}


def _execution_text_revision(folder, manifest, record, previous, script_revision=None):
    """Prove an explicitly reviewed S01 execution revision; a flag is not proof."""
    from .compact_execution import require_compact_execution
    from .seedance_client import SeedanceClient, SeedanceConfig
    from .seedance_frames import reviewed_frame_reference
    supplied = record.get('execution_prompt')
    same_source = record.get('script_sha256') == previous.get('script_sha256')
    if script_revision is not None:
        if (not isinstance(script_revision, dict)
                or script_revision.get('schema') != 'human_resume_authorization/v1'
                or script_revision.get('latest_failed_attempt_id') != previous.get('id')
                or script_revision.get('authorized_source_revision_from_sha256') != previous.get('script_sha256')
                or script_revision.get('resulting_script_sha256') != record.get('script_sha256')
                or script_revision.get('revision', {}).get('kind') not in {
                    'execution_text_revision_required', 'm3_s01_action_revision'}
                or (same_source and script_revision['revision']['kind'] != 'execution_text_revision_required')
                or (not same_source and script_revision['revision']['kind'] != 'm3_s01_action_revision')):
            raise ValueError('Human resume source and resulting script revision do not match')
    if (record.get('shot') != 'S01' or manifest.get('provider') != 'ark_api'
            or record.get('provider') != 'ark_api' or record.get('references')
            or record.get('script_sha256') != manifest.get('script_sha256')
            or (script_revision is None and not same_source)
            or record.get('direction_sha256') != manifest.get('direction_sha256')
            or not isinstance(supplied, dict) or supplied.get('schema') != 'compact_execution_binding/v1'
            or any(not isinstance(supplied.get(key), str) or not supplied[key] for key in ('plan_path', 'review_path'))
            or not isinstance(record.get('first_frame'), str) or not record['first_frame']):
        raise ValueError('Revised S01 requires a real reviewed compact execution plan and original image')
    config = SeedanceConfig.from_env('ark_api')
    prompt, proof = require_compact_execution(folder, record['first_frame'], supplied['plan_path'],
                                               supplied['review_path'], config)
    digest = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    request = record.get('request')
    if (proof != supplied or record.get('prompt') != prompt or record.get('prompt_sha256') != digest
            or proof.get('prompt_sha256') != digest or digest == previous.get('prompt_sha256')
            or record.get('first_frame_sha256') != proof.get('first_frame_sha256')
            or proof.get('script_sha256') != record['script_sha256']
            or proof.get('direction_sha256') != record['direction_sha256']
            or not isinstance(request, dict) or request.get('model') != config.model):
        raise ValueError('Compact execution binding, source, image or actual changed prompt does not match')
    # Verify the actual request references the same original image, not merely
    # a valid review supplied next to an unrelated text or media request.
    direction = read(folder / 'direction_plan.json')
    reference, _ = reviewed_frame_reference(folder, 'S01', record['first_frame'], manifest, direction, config=config)
    shot = direction['shots'][0]['storyboard']
    with SeedanceClient(config) as client:
        expected_request = client.build_task_payload(prompt,
            duration=int(shot['end_seconds'] - shot['start_seconds']), ratio='adaptive',
            resolution='480p', generate_audio=True, references=[reference],
            task_type='first_frame', return_last_frame=True)
    if request != expected_request:
        raise ValueError('Actual request text/image and generation parameters must exactly match the reviewed compact execution')
    result = {'schema': 'video_upstream_revision/v1',
        'type': ('execution_text_revision' if same_source else 'm3_s01_action_and_execution_revision'),
        'source_script_unchanged': same_source, 'previous_failed_attempt_id': previous['id'],
        'previous_prompt_sha256': previous['prompt_sha256'], 'prompt_sha256': digest,
        'script_sha256': record['script_sha256'], 'first_frame_sha256': proof['first_frame_sha256'],
        'plan_path': proof['plan_path'], 'plan_sha256': proof['plan_sha256'],
        'review_path': proof['review_path'], 'review_sha256': proof['review_sha256']}
    if script_revision is not None:
        result.update(human_resume_authorization_id=script_revision['id'],
            authorized_source_revision_from_sha256=script_revision['authorized_source_revision_from_sha256'],
            resulting_script_sha256=script_revision['resulting_script_sha256'],
            source_revision=script_revision['revision'])
    return result


def reopen_after_human_reassessment(folder, shot, reassessment_path, acceptance_path):
    """Reopen an unchanged failed output for a new review, preserving history.

    A user-confirmed reassessment is not itself a passing media review. The
    ordinary review gate must still validate every check before continuation.
    """
    folder = Path(folder).resolve()
    manifest, record = read(folder/'production.json'), read(folder/f'{shot}.json')
    campaign_path = Path(manifest['campaign_path']).resolve()
    reassessment_path, acceptance_path = Path(reassessment_path).resolve(), Path(acceptance_path).resolve()
    if not folder.is_relative_to(campaign_path.parent) or any(
            not p.is_relative_to(folder) for p in (reassessment_path, acceptance_path)):
        raise ValueError('Reassessment evidence must belong to this run')
    reassessment, acceptance = read(reassessment_path), read(acceptance_path)
    if (record.get('status') != 'downloaded'
            or file_sha(record['local_video']) != record['video_sha256']
            or reassessment.get('source_video_sha256') != record['video_sha256']
            or reassessment.get('script_sha256') != manifest['script_sha256']
            or reassessment.get('decision') != 'visually_usable_pending_user_sound_confirmation'
            or acceptance.get('source_video_sha256') != record['video_sha256']
            or not acceptance.get('user_quote') or not acceptance.get('continuation_authorization')
            or acceptance.get('checks') != dict.fromkeys(
                ('dialogue_pace', 'speaker_voice', 'lip_sync'), True)):
        raise ValueError('Exact downloaded video and explicit user sound confirmation required')
    _project_script_binding(folder, manifest)
    with ledger(campaign_path) as data:
        series_id = _run_series(data, manifest, folder)
        if data.get('failure_budget_policy') == 'per_script/v1':
            actual = script_budget_identity(manifest.get('source_screenplay', ''))
            if actual['key'] != _screenplay_key(data, series_id):
                raise ValueError('Run screenplay changed after budget attachment')
        attempt = next(a for a in data['attempts'] if a['id'] == record['campaign_attempt_id'])
        if (attempt['status'] != 'failed' or _attempt_series(attempt) != series_id
                or any(a['status'] not in RESOLVED_ATTEMPT_STATUSES for a in data['attempts'])
                or data['attempts'][-1]['id'] != attempt['id']):
            raise ValueError('Only the latest resolved failed output may be reopened')
        old_path = Path(attempt['review_path'])
        if file_sha(old_path) != attempt['review_sha256']:
            raise ValueError('Original failed review changed')
        count, limit = _failed_count(data), failure_limit(data)
        if count != limit or data['status'] != 'paused_for_human_review':
            raise ValueError('Reassessment continuation requires the recorded failure-limit pause')
        marker = campaign_path.with_name('HUMAN_REVIEW_REQUIRED.json')
        if not marker.is_file():
            raise ValueError('Original failure marker is required')
        history = folder/'quality_review_history'/shot
        history.mkdir(parents=True, exist_ok=True)
        archived = history/(attempt['review_sha256']+'.json')
        if archived.exists() and file_sha(archived) != attempt['review_sha256']:
            raise ValueError('Historical review bytes changed')
        if not archived.exists():
            archived.write_bytes(old_path.read_bytes())
        old = dict(attempt)
        attempt.setdefault('reassessment_history', []).append({
            'previous_attempt': old, 'original_review': str(archived),
            'reassessment_path': str(reassessment_path), 'reassessment_sha256': file_sha(reassessment_path),
            'acceptance_path': str(acceptance_path), 'acceptance_sha256': file_sha(acceptance_path),
            'reopened_at': beijing_now()})
        rows = data.setdefault('human_resume_authorizations', [])
        rows.append({'schema': 'human_resume_authorization/v1', 'id': f'human_resume_{len(rows)+1:03}',
            'authorization': acceptance['continuation_authorization'], 'authorized_at_beijing': beijing_now(),
            'series_id': series_id, 'shot': shot, 'original_max_failed_outputs': BASE_FAILURE_LIMIT,
            'prior_effective_failure_limit': limit, 'additional_failed_outputs': 1,
            'effective_failure_limit': limit+1, 'failed_outputs_at_authorization': count,
            'authorized_source_revision_from_sha256': manifest['script_sha256'],
            'resulting_script_sha256': manifest['script_sha256'],
            'scope': 'continue_after_reassessed_output', 'reassessed_attempt_id': attempt['id'],
            'human_review_marker': {'path': str(marker), 'sha256': file_sha(marker)},
            'acceptance_path': str(acceptance_path), 'acceptance_sha256': file_sha(acceptance_path)})
        attempt.update(status='awaiting_review')
        data.update(status='awaiting_review', failed_outputs=count, effective_failure_limit=failure_limit(data))
    return {'status': 'awaiting_review', 'failed_outputs': count, 'effective_failure_limit': limit+1}


def reserve(folder, manifest, record):
    """Called immediately before writing the paid-submission receipt."""
    if not manifest.get('campaign_path'):
        return
    folder = Path(folder).resolve()
    with ledger(manifest['campaign_path']) as data:
        series_id = _run_series(data, manifest, folder)
        if data.get('failure_budget_policy') == 'per_script/v1':
            actual = script_budget_identity(manifest.get('source_screenplay', ''))
            if actual['key'] != _screenplay_key(data, series_id):
                raise ValueError('Run screenplay changed after budget attachment')
        if data.get('holds'):
            raise ValueError('Resolve the campaign prerequisites before submitting: ' + ', '.join(data['holds']))
        attempts = data.setdefault('attempts', [])
        failed = [a for a in attempts if a['status'] == 'failed']
        failed_count = _failed_count(data)
        effective_limit = failure_limit(data)
        if failed_count >= effective_limit or data.get('status') == 'paused_for_human_review':
            raise ValueError('Ten failed generated outputs or the audited resumed limit reached: pause for human review; no further submission')
        if any(a['status'] not in RESOLVED_ATTEMPT_STATUSES for a in attempts):
            raise ValueError('Review or reconcile the outstanding segment before generating another')
        shot = record['shot']
        current_attempts = [a for a in attempts if _attempt_series(a) == series_id]
        passed = {a['shot'] for a in current_attempts if attempt_allows_continuation(data, a)}
        next_shot = next((s for s in data['shots'] if s not in passed), None)
        if shot != next_shot:
            raise ValueError(f'Generate only the next unapproved segment: {next_shot}')
        prior_failures = [a for a in failed if a['shot'] == shot and _attempt_series(a) == series_id]
        execution_revision = None
        resume_authorization = None
        if failed_count >= BASE_FAILURE_LIMIT and not prior_failures:
            authorizations = [a for a in data.get('human_resume_authorizations', [])
                              if a.get('series_id') == series_id
                              and a.get('resulting_script_sha256') == record['script_sha256']
                              and a.get('scope') == 'continue_after_reassessed_output']
            if not authorizations:
                raise ValueError('Continuation beyond the original cap requires explicit authorization')
            auth = authorizations[-1]
            accepted = next((a for a in current_attempts if a['id'] == auth['reassessed_attempt_id']), None)
            if (not accepted or accepted['status'] != 'passed'
                    or file_sha(auth['acceptance_path']) != auth['acceptance_sha256']
                    or file_sha(auth['human_review_marker']['path']) != auth['human_review_marker']['sha256']):
                raise ValueError('Reassessed approval or authorization evidence changed')
        elif failed_count >= BASE_FAILURE_LIMIT and shot not in passed:
            applicable = [row for row in data.get('human_resume_authorizations', [])
                          if row.get('series_id') == series_id and row.get('shot') == shot
                          and row.get('failed_outputs_at_authorization') <= failed_count
                          < row.get('effective_failure_limit')]
            if applicable:
                resume_authorization = applicable[-1]
                marker = resume_authorization.get('human_review_marker', {})
                marker_path = Path(marker.get('path', '')).resolve()
                if (record.get('script_sha256') != resume_authorization.get('resulting_script_sha256')
                        or not marker_path.is_file() or file_sha(marker_path) != marker.get('sha256')
                        or not prior_failures
                        or prior_failures[-1].get('id') != resume_authorization.get('latest_failed_attempt_id')):
                    raise ValueError('Human resume authorization, original marker or resulting script changed')
                execution_revision = _execution_text_revision(
                    folder, manifest, record, prior_failures[-1], resume_authorization)
            else:
                raise ValueError('The ten-failure pause has no matching explicit human resume authorization')
        elif prior_failures and (manifest.get('trial_schema') == 'reviewed_director_segment/v1'
                or (manifest.get('trial_schema') == 'reviewed_reference_director_segment/v1' and manifest.get('execution_repair'))):
            from scripts.run_director_video import verify_retry
            execution_revision = verify_retry(folder, manifest, record, prior_failures[-1])
        elif prior_failures and manifest.get('trial_schema') == 'reviewed_cohort_segment/v1':
            from scripts.run_cohort_video import verify_retry
            execution_revision = verify_retry(folder, manifest, record, prior_failures[-1])
        elif prior_failures and (record['script_sha256'] == prior_failures[-1]['script_sha256']
                               or record['prompt_sha256'] == prior_failures[-1]['prompt_sha256']):
            if manifest.get('trial_schema') in {'reviewed_screenplay_first_shot/v1', 'reviewed_screenplay_segment/v1'}:
                from scripts.run_screenplay_trial import verify_production_retry
                execution_revision = verify_production_retry(folder, manifest, record, prior_failures[-1])
            elif (shot == 'S01' and record.get('execution_prompt')
                    and record['script_sha256'] == prior_failures[-1]['script_sha256']
                    and record['prompt_sha256'] != prior_failures[-1]['prompt_sha256']):
                execution_revision = _execution_text_revision(folder, manifest, record, prior_failures[-1])
            else:
                raise ValueError('Revise the upstream script for the recorded defect before spending on another candidate')
        if shot != data['shots'][0]:
            previous = next(a for a in reversed(current_attempts) if a['shot'] == data['shots'][data['shots'].index(shot)-1] and attempt_allows_continuation(data, a))
            source = read(Path(previous['run_dir']) / f"{previous['shot']}.json")
            if (source.get('status') != 'downloaded' or source.get('video_sha256') != previous.get('video_sha256')
                    or source.get('campaign_attempt_id') != previous['id']
                    or file_sha(source['local_video']) != previous['video_sha256']):
                raise ValueError('Immediately preceding approved original output changed')
            if source.get('last_frame') and file_sha(source['last_frame']) != source.get('last_frame_sha256'):
                raise ValueError('Immediately preceding original tail frame changed')
            if previous.get('delivery_preview'):
                previous_manifest = read(Path(previous['run_dir'])/'production.json')
                delivery_asset(previous['run_dir'], previous_manifest, previous['shot'])
            if (not source.get('last_frame_sha256')
                    or record.get('first_frame_sha256') != source['last_frame_sha256']):
                raise ValueError('Use the immediately preceding approved segment’s original tail as this first frame')
        attempt_id = f"attempt_{len(attempts)+1:03}"
        record['campaign_attempt_id'] = attempt_id
        record['campaign_series_id'] = series_id
        attempt = {'id': attempt_id, 'run_dir': str(folder), 'shot': shot,
            'series_id': series_id,
            'status': 'awaiting_generation_or_review', 'created_at': now(),
            'script_sha256': record['script_sha256'], 'prompt_sha256': record['prompt_sha256']}
        if execution_revision is not None:
            record['upstream_revision'] = execution_revision
            attempt['upstream_revision'] = execution_revision
        if resume_authorization is not None:
            record['human_resume_authorization_id'] = resume_authorization['id']
            attempt['human_resume_authorization_id'] = resume_authorization['id']
        attempts.append(attempt)
        data.update(status='generating', failed_outputs=failed_count,
                    effective_failure_limit=effective_limit)


def reconcile_rejection(manifest, record):
    if not manifest.get('campaign_path') or record.get('status') != 'request_rejected' or record.get('submit_id'):
        return
    with ledger(manifest['campaign_path']) as data:
        series_id = _run_series(data, manifest)
        attempt = next(a for a in data['attempts'] if a['id'] == record['campaign_attempt_id'])
        if _attempt_series(attempt) != series_id or attempt['status'] in {'passed', 'failed', 'superseded'}:
            raise ValueError('Cannot rewrite a completed or superseded campaign attempt')
        attempt.update(status='request_rejected', provider_error_code=record.get('provider_error_code'), resolved_at=now())
        failed_count = _failed_count(data)
        data.update(status=('awaiting_upstream_revision' if failed_count >= BASE_FAILURE_LIMIT
                            else 'awaiting_next_segment'),
                    failed_outputs=failed_count, effective_failure_limit=failure_limit(data))


def require_approved_segments(folder, manifest):
    if not manifest.get('campaign_path'):
        return
    data = read(manifest['campaign_path'])
    series_id = _run_series(data, manifest, folder)
    for shot in manifest['shots']:
        approved = [a for a in data['attempts'] if a['shot'] == shot and a['status'] == 'passed'
                    and _attempt_series(a) == series_id]
        if not approved:
            raise ValueError(f'{shot} has not passed segment review; assembly is not released')
        record = read(Path(folder)/f'{shot}.json')
        if (approved[-1]['video_sha256'] != record.get('video_sha256')
                or approved[-1]['id'] != record.get('campaign_attempt_id')):
            raise ValueError(f'{shot} has not passed segment review; assembly is not released')
        delivery_asset(folder, manifest, shot)


def preview_asset(folder, manifest, record, audit_path):
    """Resolve a registered derivative while retaining the raw provider provenance."""
    folder, audit_path = Path(folder).resolve(), Path(audit_path).resolve()
    registered = manifest.get('speed_previews', {}).get(record['shot'], {}).values()
    if not audit_path.is_relative_to(folder) or str(audit_path) not in registered:
        raise ValueError('Delivery preview must be registered in this run')
    audit = read(audit_path)
    video = Path(audit['video']).resolve()
    packet = Path(audit['review_packet']).resolve()
    if (audit.get('schema') != 'script_video_speed_preview/v1'
            or audit.get('source_sha256') != record['video_sha256']
            or audit.get('script_sha256') != manifest['script_sha256']
            or audit.get('content_trimmed') is not False
            or not video.is_relative_to(folder) or not packet.is_relative_to(folder)
            or file_sha(video) != audit['video_sha256']
            or file_sha(record['local_video']) != record['video_sha256']):
        raise ValueError('Delivery preview or its original source changed')
    return {'video': str(video), 'video_sha256': audit['video_sha256'],
            'actual_duration_seconds': audit['actual_duration_seconds'],
            'review_packet': str(packet), 'speed': audit['speed'],
            'source_video_sha256': record['video_sha256'],
            'delivery_preview': str(audit_path), 'delivery_audit_sha256': file_sha(audit_path)}


def delivery_asset(folder, manifest, shot):
    """Assembly follows the approved delivery; raw receipts and tails stay immutable."""
    folder = Path(folder).resolve()
    record = read(folder/f'{shot}.json')
    if manifest.get('campaign_path'):
        data = read(manifest['campaign_path'])
        series_id = _run_series(data, manifest, folder, current=False)
        approvals = [a for a in data['attempts'] if a['shot'] == shot and a['status'] == 'passed'
                     and _attempt_series(a) == series_id]
        if approvals and approvals[-1].get('delivery_preview'):
            approved = approvals[-1]
            asset = preview_asset(folder, manifest, record, approved['delivery_preview'])
            if (asset['delivery_audit_sha256'] != approved['delivery_audit_sha256']
                    or asset['video_sha256'] != approved['delivery_video_sha256']):
                raise ValueError('Approved delivery changed; inspect before assembly')
            return asset
    if file_sha(record['local_video']) != record['video_sha256']:
        raise ValueError('Original delivery changed')
    return {'video': record['local_video'], 'video_sha256': record['video_sha256'],
            'actual_duration_seconds': record['actual_duration_seconds'], 'speed': 1.,
            'source_video_sha256': record['video_sha256'], 'review_packet': record['review_packet']}


def review(folder, shot, review_path):
    folder = Path(folder).resolve()
    manifest, record = read(folder/'production.json'), read(folder/f'{shot}.json')
    if not manifest.get('campaign_path'):
        raise ValueError('This run is not attached to a sequential campaign')
    if record['status'] != 'downloaded' or file_sha(record['local_video']) != record['video_sha256']:
        raise ValueError('Review requires the unchanged generated output')
    result = read(review_path)
    asset = (preview_asset(folder, manifest, record, result['delivery_preview'])
             if result.get('delivery_preview') else
             {'video_sha256': record['video_sha256'], 'review_packet': record['review_packet'],
              'actual_duration_seconds': record['actual_duration_seconds']})
    packet = read(asset['review_packet'])
    packet_dir = Path(asset['review_packet']).parent.resolve()
    if (result.get('source_sha256') != asset['video_sha256']
            or result.get('script_sha256') != manifest['script_sha256']
            or packet['source_sha256'] != asset['video_sha256']
            or (result.get('delivery_preview') and result.get('source_original_sha256') != record['video_sha256'])):
        raise ValueError('Review must match this output and current script')
    checks = result.get('checks', {})
    if set(checks) != set(REVIEW_CHECKS) or any(v is not None and type(v) is not bool for v in checks.values()):
        raise ValueError('Checks must be true, false, or null for not yet inspected')
    creative = result.get('creative_checks', {})
    if (not isinstance(creative, dict) or set(creative) - {'visual_storytelling'}
            or any(v is not None and type(v) is not bool for v in creative.values())):
        raise ValueError('Unknown creative check or invalid verdict')
    # Artistic rejection is distinct from technical failure. It cannot approve
    # missing audio/video checks, and uses the same evidence and failure budget.
    checks = {**checks, **creative}
    decision = ('failed' if any(v is False for v in checks.values()) else
                'passed' if all(v is True for v in checks.values()) else 'pending')
    if decision == 'pending' and result.get('decision') == 'visual_passed_audio_pending':
        data = read(manifest['campaign_path'])
        if not review_allows_continuation(data, manifest['campaign_series_id'], result):
            raise ValueError('Visual-only continuation needs explicit scope authorization and complete visual review')
        decision = 'visual_passed_audio_pending'
    if result.get('decision') == 'passed' and decision != 'passed':
        raise ValueError('Passing requires explicit verdicts for every check; unverified is not passed')
    if result.get('decision') != decision:
        raise ValueError('Decision disagrees with the individual checks')
    observations = result.get('observations', [])
    inspected = {name for name, value in checks.items() if value is not None}
    if not isinstance(observations, list) or {o.get('check') for o in observations} != inspected:
        raise ValueError('Record seconds and evidence for each inspected check; leave uninspected checks null')
    for item in packet['evidence']:
        path = (packet_dir/item['file']).resolve()
        if not path.is_relative_to(packet_dir) or file_sha(path) != item['sha256']:
            raise ValueError('Packet evidence was modified after extraction')
    for observation in observations:
        timestamp = observation.get('time_seconds')
        if (type(timestamp) not in (float, int) or not 0 <= timestamp <= asset['actual_duration_seconds']
                or not str(observation.get('notes', '')).strip() or not observation.get('evidence')):
            raise ValueError('Each observation requires valid seconds, concrete notes and existing evidence')
        for item in observation['evidence']:
            path = (folder/item).resolve()
            if not path.is_relative_to(folder) or not path.is_file():
                raise ValueError('Observation evidence must exist inside the run')
    review_sha = file_sha(review_path)
    with ledger(manifest['campaign_path']) as data:
        series_id = _run_series(data, manifest, folder)
        attempt = next(a for a in data['attempts'] if a['id'] == record['campaign_attempt_id'])
        if _attempt_series(attempt) != series_id or attempt['status'] == 'superseded':
            raise ValueError('A superseded or older-series attempt cannot be reviewed into the active series')
        if attempt['status'] in {'passed', 'failed'}:
            if attempt.get('review_sha256') == review_sha:
                return {'decision': attempt['status'], 'failed_outputs': data['failed_outputs']}
            raise ValueError('A recorded review is immutable; preserve it for the human audit')
        destination = folder/f'{shot}.quality_review.json'
        history = folder/'quality_review_history'/shot
        history.mkdir(parents=True, exist_ok=True)
        # Preserve the reviewed bytes: reserializing changes the bound SHA.
        review_raw = Path(review_path).read_bytes()
        if hashlib.sha256(review_raw).hexdigest() != review_sha:
            raise ValueError('Review changed during registration')
        (history/f'{review_sha}.json').write_bytes(review_raw)
        destination.write_bytes(review_raw)
        attempt.update(status='awaiting_review' if decision == 'pending' else decision,
                       reviewed_at=now(), video_sha256=record['video_sha256'],
                       review_path=str(destination), review_sha256=review_sha,
                       failed_checks=[k for k, value in checks.items() if value is False],
                       uninspected_checks=[k for k, value in checks.items() if value is None])
        if result.get('delivery_preview'):
            attempt.update(delivery_preview=asset['delivery_preview'],
                           delivery_audit_sha256=asset['delivery_audit_sha256'],
                           delivery_video_sha256=asset['video_sha256'],
                           review_scope='selected_speed_delivery',
                           original_speed_audio_approved=False)
        failures = [a for a in data['attempts'] if a['status'] == 'failed']
        failed_count = _failed_count(data)
        effective_limit = failure_limit(data)
        data['failed_outputs'] = failed_count
        data['lifetime_failed_outputs'] = lifetime_failed_count(data)
        data['effective_failure_limit'] = effective_limit
        data['status'] = ('paused_for_human_review' if failed_count >= effective_limit
                          else 'awaiting_next_segment' if decision in ('passed','visual_passed_audio_pending')
                          else 'awaiting_review' if decision == 'pending' else 'awaiting_upstream_revision')
        if failed_count >= effective_limit:
            original_marker = Path(manifest['campaign_path']).with_name('HUMAN_REVIEW_REQUIRED.json')
            marker = (original_marker if failed_count == BASE_FAILURE_LIMIT and not original_marker.exists()
                      else Path(manifest['campaign_path']).with_name(
                          f'HUMAN_REVIEW_REQUIRED_{failed_count:03}.json'))
            if data.get('failure_budget_policy') == 'per_script/v1':
                budget = _budget_key(data, series_id)
                marker = original_marker.with_name(f'HUMAN_REVIEW_REQUIRED_{budget[:16]}_{failed_count:03}.json')
                failures = [a for a in failures if _budget_key(data, _attempt_series(a)) == budget]
            payload = {'created_at': beijing_now(),
                'reason': f'累计{failed_count}个生成输出未通过，停止后续付费提交',
                'failed_outputs': failed_count, 'effective_failure_limit': effective_limit,
                'original_max_failed_outputs': data['max_failed_outputs'], 'failures': failures}
            if marker.exists():
                if read(marker) != payload:
                    raise ValueError('Existing human review marker is immutable; inspect the campaign audit')
            else:
                write(marker, payload)
    return {'decision': decision, 'failed_outputs': failed_count}
