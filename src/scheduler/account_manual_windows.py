"""One visible original-account repair window per human-required incident."""
import math
from pathlib import Path


def _eligible(data, issue):
    uuid, key = issue.get('account_uuid'), issue.get('account_key')
    stamp, incident = issue.get('created_at'), issue.get('id')
    if (not isinstance(incident, int) or isinstance(incident, bool) or incident <= 0
            or not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp)
            or issue.get('status') != 'open' or issue.get('error_code') not in {'human_required', 'verification_ui_unconfirmed'}):
        return False
    controls = [r for r in data.get('controls', []) if r.get('account_uuid') == uuid]
    if (len(controls) != 1 or controls[0].get('account_key') != key
            or controls[0].get('state') != 'paused' or controls[0].get('error_code') != issue.get('error_code')
            or controls[0].get('updated_at') != stamp or controls[0].get('recovery_lease_until')):
        return False
    current = [r for r in data.get('issues', []) if r.get('account_uuid') == uuid and r.get('status') == 'open']
    if not current or max(r['id'] for r in current) != incident:
        return False
    for group in ('accounts', 'smart_accounts', 'playback_accounts'):
        if any(r.get('account_uuid') == uuid and r.get('run_id') for r in data.get(group, [])):
            return False
    for group in ('runs', 'smart_runs', 'playback_runs'):
        if any(r.get('account_uuid') == uuid and (r.get('status') in ('running', 'outcome_unknown')
                or r.get('finished_at') is None) for r in data.get(group, [])):
            return False
    if any(r.get('account_uuid') == uuid and r.get('status') in ('requested', 'probing')
            for r in data.get('handling_requests', [])):
        return False
    return True


def dispatch_human_windows(*, path=None, jobs_path=None, runtime=None):
    from src.scheduler import account_refresh as backend
    from src.operations_accounts import manual_window_jobs as jobs
    path = Path(path) if path is not None else backend.DB
    jobs_path = Path(jobs_path) if jobs_path is not None else path.parent / 'account_manual_windows.db'
    data = backend.snapshot(path=path)
    results = []
    for issue in data.get('issues', []):
        if not _eligible(data, issue):
            continue
        uuid, key, incident = issue['account_uuid'], issue['account_key'], issue['id']
        from .browser_visibility import automatic_window_allowed
        if not automatic_window_allowed(uuid, issue=issue, path=path):
            continue  # Keep the incident and pause; never pop up during hidden viewing.
        original = jobs.get_incident_window_job(incident, uuid, key, path=jobs_path)
        if original is not None:
            continue  # Includes closed, failed and unknown outcomes; no retry.
        if runtime is None:
            from src.operations_accounts.runtime import AccountRuntimeService
            runtime = AccountRuntimeService()
        profile = runtime.profiles.get(key)
        if profile.account_uuid != uuid or profile.account_key != key or profile.status != 'active':
            continue
        if runtime.bindings.get_runtime_state(uuid).lock_owner:
            continue  # Even an expired unknown lease is retained, never stolen.

        def still_actionable(issue=issue, runtime=runtime):
            latest = backend.snapshot(path=path)
            live = next((r for r in latest.get('issues', []) if r.get('id') == issue['id']), {})
            return (_eligible(latest, live) and automatic_window_allowed(issue['account_uuid'], issue=live, path=path)
                and not runtime.bindings.get_runtime_state(issue['account_uuid']).lock_owner)

        results.append(jobs.start_manual_window_job(uuid, key, f'system:human_required:{incident}',
            runtime=runtime, path=jobs_path, incident_id=incident,
            incident_created_at=issue['created_at'], before_open=still_actionable))
    return results
