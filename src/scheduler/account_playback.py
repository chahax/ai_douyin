"""Bounded automatic playback dispatch; no interaction or creative-service permissions."""
import logging
import math
import sqlite3
import threading
from collections.abc import Mapping
from src.shared.browser_navigation import clean_navigation_evidence

MAX_WORKERS = 2
_slots = threading.BoundedSemaphore(MAX_WORKERS)
_activity_lock = threading.Lock()
_active_workers = 0

DEFAULT_OPTIONS = dict(max_videos=20, per_video_seconds=90, total_minutes=20,
                       min_relevance_score=60.0, auto_like=False, auto_comment=False)


def normalize_options(options=None):
    if options is not None and not isinstance(options, Mapping):
        raise ValueError('自动播放配置必须是字典')
    values = dict(DEFAULT_OPTIONS)
    supplied = dict(options or {})
    if supplied.keys() - values.keys():
        raise ValueError('自动播放包含不支持的配置字段')
    values.update(supplied)
    if values['auto_like'] is not False or values['auto_comment'] is not False:
        raise ValueError('自动计划不允许开启点赞或评论')
    for name, upper in (('max_videos', 100), ('per_video_seconds', 600), ('total_minutes', 120)):
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
            raise ValueError(f'{name}须为1至{upper}的整数')
    relevance = values['min_relevance_score']
    if isinstance(relevance, bool) or not isinstance(relevance, (float, int)) or not math.isfinite(relevance) or not 0 <= relevance <= 100:
        raise ValueError('相关度阈值须在0至100之间')
    values['min_relevance_score'] = float(relevance)
    return values


def playback_lease_seconds(total_minutes):
    # Matches maintenance.playback_lease_seconds, without importing browser clients at UI render time.
    return max(3600, int(total_minutes) * 60 + 1800)


def _backend():
    from src.scheduler import account_refresh
    return account_refresh


def _publish_activity(path):
    with _activity_lock:
        active = _active_workers
    _backend().update_service_status('playback', 'running' if active else 'healthy',
                                    message=f'自动播放后台已接线，执行中 {active}/{MAX_WORKERS}；按持久账号设置检查到期。', path=path)


def _safe_publish_activity(path):
    try:
        _publish_activity(path)
    except Exception as exc:
        logging.getLogger(__name__).warning('Playback heartbeat unavailable (%s)', type(exc).__name__)


def _run_playback(run_id, *, path):
    backend = _backend()
    try:
        request = backend._prepare_playback_dispatch(run_id, path=path)
        if request is None:
            return
        from src.operations_accounts.maintenance import AccountMaintenanceService
        from src.platform_adapter.douyin_playback import PlaybackOptions
        options = normalize_options(request['options'])
        result = AccountMaintenanceService().run(
            request['account_key'], 'playback', headless=True,
            playback_options=PlaybackOptions(**options),
            authorization_reference=request['authorization_reference'])
        unexpected_interaction = bool(result.likes_performed or result.comments_sent)
        backend.finish_playback(run_id, 'failed' if unexpected_interaction else result.status, dict(
            message=result.message, error_code='interaction_policy_violation' if unexpected_interaction else getattr(result, 'error_code', ''),
            maintenance_status=result.status,
            maintenance_run_id=result.run_id,
            failure_stage=getattr(result, 'failure_stage', ''),
            navigation_evidence=(clean_navigation_evidence(result.navigation_evidence)
                if getattr(result, 'navigation_evidence', None) else {}),
            playback_verified_videos=result.playback_verified_videos,
            actual_watch_seconds=result.actual_watch_seconds,
            likes_performed=result.likes_performed, comments_sent=result.comments_sent,
            requested_max_videos=options['max_videos'], external_dispatched=True,
        ), path=path)
    except Exception as exc:
        # Preserve only the structured classification, never arbitrary auth payloads.
        backend.finish_playback(run_id, 'failed', dict(
            message='自动播放执行异常，已暂停账号并保留原运行记录。',
            error_code=backend._exception_code(exc), error_type=type(exc).__name__), path=path)


def _worker(run_id, path):
    global _active_workers
    try:
        _run_playback(run_id, path=path)
    finally:
        with _activity_lock:
            _active_workers -= 1
        _slots.release()
        _safe_publish_activity(path)


def dispatch_account(account_uuid, account_key, *, reason='periodic', path):
    """Reserve a physical worker slot before claiming: there is no unbounded work queue."""
    global _active_workers
    if not _slots.acquire(blocking=False):
        return None
    backend = _backend()
    run_id = None
    counted = False
    try:
        run_id = backend.claim_playback(account_uuid, account_key, reason=reason, path=path)
        if run_id is None:
            _slots.release()
            return None
        with _activity_lock:
            _active_workers += 1
            counted = True
        thread = threading.Thread(target=_worker, args=(run_id, path), daemon=True,
                                  name=f'AccountPlayback-{account_key}')
        thread.start()
    except Exception:
        if counted:
            with _activity_lock:
                _active_workers -= 1
        _slots.release()
        if run_id is not None:
            # thread.start failed, so the service was definitely never called.
            backend.finish_playback(run_id, 'cancelled', dict(
                message='自动播放线程未能启动，本轮没有派发平台任务。',
                error_code='worker_start_failed', external_dispatched=False), path=path)
        raise
    # A reporting outage after thread.start must never release or cancel its live run.
    _safe_publish_activity(path)
    return run_id


def dispatch_due_accounts(*, reason='periodic', path=None):
    backend = _backend()
    if path is None:
        path = backend.DB
    from src.operations_accounts import AccountProfileRepository, AccountBindingRepository
    backend.update_service_status('playback_schedule', 'running', message='正在检查自动播放到期计划。', path=path)
    profiles = AccountProfileRepository()
    bindings = AccountBindingRepository(profiles.db_path)
    for profile in profiles.list_active():
        try:
            binding = bindings.get_optional(profile.account_key)
            if binding is None or getattr(binding, 'status', 'active') != 'active':
                continue
            dispatch_account(profile.account_uuid, profile.account_key, reason=reason, path=path)
        except Exception as exc:
            # One account's policy/worker problem must not stop scanning the others.
            logging.getLogger(__name__).warning('Playback account scan failed (%s, %s)',
                                                profile.account_key, type(exc).__name__)
            with backend.connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT * FROM account_controls WHERE account_uuid=?',
                                      (profile.account_uuid,)).fetchone()
                if existing:
                    if existing['account_key'] != profile.account_key:
                        raise ValueError('账号UUID与原账号标识不一致')
                    if existing['state'] == 'paused':
                        # A scanner/SQLite outage is not a new platform incident.
                        # Preserve the original human/unknown cause and its revision.
                        continue
                sqlite_code = getattr(exc, 'sqlite_errorcode', 0)
                error_code = ('scheduler_database_busy' if isinstance(exc, sqlite3.Error)
                              and sqlite_code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                              else backend._exception_code(exc))
                backend._pause(db, profile.account_uuid, profile.account_key,
                               '自动播放调度异常，请人工核对本地记录；未重新派发原运行。',
                               error_code, backend.time.time())
    backend.update_service_status('playback_schedule', 'healthy', message='本轮自动播放到期扫描完成。', path=path)
    _safe_publish_activity(path)
