"""Account control bridge: durable requests, one browser owner, borrowed task tabs.

The opt-in switch is a deployment boundary, not permission to steal old workers.
Only the backend pump starts owner threads. CLI/web requests merely persist work.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from types import SimpleNamespace

from .browser_control import (BrowserControlActor, BrowserControlDeferred,
    BrowserControlRejected, BrowserControlStore, BrowserCommandResult)
from .daily_run_policy import daily_limit_reached

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'data/account_browser_control.db'
UPLOAD_INSPECTION_URL = 'https://creator.douyin.com/creator-micro/content/upload'
_active = ContextVar('account_browser_control_command', default=None)
_lease = ContextVar('account_browser_control_operation_lease', default=None)
_hosts = {}
_hosts_lock = threading.RLock()


def enabled():
    explicit = os.environ.get('AI_DOUYIN_BROWSER_CONTROL')
    if explicit is not None:
        return explicit.strip().lower() in {'1', 'true', 'yes', 'on'}
    from src.shared.config import settings
    return bool(getattr(settings, 'AI_DOUYIN_BROWSER_CONTROL', False))


def active_context():
    return _active.get()


def is_managed_account(account_key):
    ctx = active_context()
    return ctx is not None and ctx.resource.account_key == account_key


def background_safe_point(cursor):
    ctx = active_context()
    return ctx.safe_point(cursor) if ctx is not None else 0.0


def binding_version(context):
    b = context.binding
    value = {key: getattr(b, key) for key in ('account_uuid', 'account_key',
        'platform_identity_key', 'browser_environment_key', 'browser_profile_dir',
        'storage_state_path', 'confirmed_by', 'created_at')}
    value['profile_version'] = context.profile.profile_version
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _runtime():
    from .runtime import AccountRuntimeService
    return AccountRuntimeService()


def _store():
    return BrowserControlStore(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB', DB))


def _submit(account_key, kind, payload, key, priority):
    context = _runtime().resolve(account_key, require_healthy=False)
    payload = dict(payload, account_key=account_key, account_uuid=context.account_uuid)
    command = _store().submit(context.account_uuid, binding_version(context), kind,
        key, payload, priority=priority)
    return dict(command, status=command['state'])


def queue_publish_request(account_key, request, *, authorization=None, quota_authorization=None, quota_attempt_index=None):
    """Queue an explicitly authorized immutable file; never opens a browser."""
    if not authorization:
        raise BrowserControlRejected('authorization_required', '发布需要原始明确授权或已批准完整片的引用。')
    if isinstance(authorization, str):
        reference = Path(authorization)
        if reference.is_file():
            authorization = {'path': str(reference.resolve()), 'sha256': _sha(reference)}
        else:
            authorization = {'explicit_user_statement': authorization}
    elif isinstance(authorization, dict):
        authorization = dict(authorization)
        if authorization.get('path') and _sha(authorization['path']) != authorization.get('sha256'):
            raise BrowserControlRejected('authorization_changed', '原授权引用字节不一致。')
    else:
        raise BrowserControlRejected('authorization_invalid', '原授权应为明确文本或冻结文件引用。')
    path = Path(request.video_path).resolve()
    if not path.is_file() or not path.is_relative_to(ROOT):
        raise BrowserControlRejected('video_invalid', '发布成片必须是本项目已有文件。')
    context = _runtime().resolve(account_key, require_healthy=False)
    requested = request.extra_metadata.get('account_uuid')
    if requested and requested != context.account_uuid:
        raise BrowserControlRejected('account_uuid_mismatch', '发布请求与原账号不一致。')
    file_sha = _sha(path)
    payload = dict(request=asdict(request), video_sha256=file_sha, authorization=authorization)
    key = 'publish:' + file_sha
    priority = 100
    if quota_attempt_index is not None and quota_authorization is None:
        raise BrowserControlRejected('quota_authorization_invalid', '运行索引必须绑定本次三槽授权。')
    if quota_authorization is not None:
        from .publication_two_run_authorization import validate_authorization, validate_publication_payload, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7, SCHEMA_V8
        extra = validate_authorization(quota_authorization)
        if (extra['account_uuid'] != context.account_uuid or extra['account_key'] != account_key
                or extra['video']['sha256'] != file_sha or extra['video']['path'] != str(path)
                or authorization.get('path') != extra['prepared']['path']
                or authorization.get('sha256') != extra['prepared']['sha256']):
            raise BrowserControlRejected('quota_authorization_invalid', '额外发布授权与原账号、原成片或PREPARED不一致。')
        payload['quota_authorization'] = dict(quota_authorization)
        validate_publication_payload(extra, payload)
        key = extra['idempotency_keys']['publish']
        if extra['schema'] == SCHEMA_V5:
            from .publication_bounded_retry_authorization import _validate_attempt
            _validate_attempt(extra, quota_authorization, quota_attempt_index)
            payload['quota_attempt_index'] = quota_attempt_index
            key = key[quota_attempt_index - 1]
        elif quota_attempt_index is not None:
            raise BrowserControlRejected('quota_authorization_invalid', '旧授权不接受三槽运行索引。')
        if extra['schema'] in {SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7, SCHEMA_V8}:
            priority = 250  # This explicit publication follows recovery300 ahead of queued manual200.
    return _submit(account_key, 'publish', payload, key, priority)


def queue_prepared_publication(path, *, quota_authorization=None, quota_attempt_index=None):
    """Use the existing explicit full-film acceptance without fabricating a review."""
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not path.is_relative_to(ROOT) or value.get('decision_source') != 'explicit_user_statement'
            or value.get('full_film_accepted_for_publication') is not True
            or not value.get('user_statement') or value.get('ai_generated') is not True
            or value.get('fictional_story') is not True):
        raise BrowserControlRejected('authorization_invalid', '原完整片采用与发布授权不完整。')
    if _sha(value['video']['path']) != value['video']['sha256']:
        raise BrowserControlRejected('video_changed', '已批准成片文件发生变化。')
    context = _runtime().resolve(value['account_key'], require_healthy=False)
    if context.account_uuid != value['account_uuid']:
        raise BrowserControlRejected('account_uuid_mismatch', '原发布授权不属于此账号。')
    from src.platform_adapter.models import PublishRequest
    request = PublishRequest(video_path=value['video']['path'], title=value['title'],
        description=value['description'], hashtags=value['hashtags'], ai_generated=True,
        fictional_story=True, visibility=value['visibility'],
        extra_metadata={'account_uuid': value['account_uuid']})
    authorization = {'path': str(path), 'sha256': _sha(path),
        'explicit_user_statement': value['user_statement'], 'comment': value.get('comment', '')}
    return queue_publish_request(value['account_key'], request, authorization=authorization,
        quota_authorization=quota_authorization, quota_attempt_index=quota_attempt_index)


class BorrowedSession:
    """Session-shaped adapter whose Page is pinned to one managed tab."""
    def __init__(self, resource, role):
        self.origin_context = active_context()
        self.origin_thread = threading.get_ident()
        if self.origin_context is None:
            raise BrowserControlRejected('managed_context_required', '借用浏览器必须属于当前受管任务。')
        self._guard()
        self.resource = resource
        self.owner = resource.ensure_session()
        self.config = self.owner.config
        self._guard()
        from .window_supervision import enabled as supervision_enabled
        persistent = (supervision_enabled(resource) and role == 'maintenance' and not self.config.headless
                      and getattr(self.owner, '_supervision_protocol', 0)==1)
        retained = getattr(resource, 'supervision_tab', None) if persistent else None
        if retained:
            existing = self.owner.list_tabs()
            if not any(r['tab_id'] == retained and not r.get('closed') for r in existing):
                retained = None
        page = self.owner.get_page(retained) if retained else self.owner.new_tab(role)
        self.supervised = persistent
        if persistent:
            resource.supervision_tab = page.tab_id
        self.retained_feed = False
        self._feed_handoff_checked = False
        from src.platform_adapter.browser_session import Page
        self.page = Page(self, page.tab_id)
        self.page.url = 'about:blank'
        self.tab_id = page.tab_id
        self.closed = False

    def __getattr__(self, name):
        raise AttributeError(name)

    def _guard(self):
        if active_context() is not self.origin_context or threading.get_ident() != self.origin_thread:
            raise BrowserControlRejected('late_task_callback', '此借用标签页不属于当前任务或执行线程。')
        self.origin_context.check_dispatch()

    def start(self):
        self._guard()
        return self.owner.start()

    def get_state(self):
        self._guard()
        return self.owner.get_state()

    def is_authenticated(self):
        self._guard()
        return self.owner.is_authenticated()

    def require_authenticated(self):
        self._guard()
        return self.owner.require_authenticated()

    def save_storage_state(self):
        self._guard()
        return self.owner.save_storage_state()

    def get_page(self, tab_id=None):
        if tab_id is not None and tab_id != self.page.tab_id:
            raise BrowserControlRejected('tab_mismatch', '任务不能读取其他标签页。')
        return self.page

    def cmd(self, action, **kwargs):
        if action in {'new_tab', 'list_tabs', 'close_tab', 'close', 'stop', 'wait_for_close', 'window_status', 'save_state', 'minimize_window', 'supervision_window'}:
            raise BrowserControlRejected('owner_command_forbidden', '任务不能管理整个浏览器生命周期。')
        supplied = kwargs.pop('tab_id', self.page.tab_id)
        if supplied not in {None, self.page.tab_id}:
            raise BrowserControlRejected('tab_mismatch', '任务不能操作其他标签页。')
        self._guard()
        from .window_supervision import synchronize, enabled as supervision_enabled
        if supervision_enabled(self.resource):
            synchronize(self.resource, self.origin_context.actor)
        return self.owner.cmd(action, tab_id=self.page.tab_id, **kwargs)

    def open_page(self, url):
        self.owner._check_domain_allowed(url)
        if url == 'https://www.douyin.com/?recommend=1' and not self._feed_handoff_checked:
            self._guard()
            self._feed_handoff_checked = True
            from .retained_feed_session import take_tab
            retained = take_tab(self.resource, self.origin_context)
            if retained:
                # Identity ran in this borrower's separate tab. Take the loaded
                # feed only when the controller actually asks for the homepage.
                self.owner.close_tab(self.page.tab_id)
                from src.platform_adapter.browser_session import Page
                self.page = Page(self, retained)
                self.tab_id = retained
                if self.supervised:
                    self.resource.supervision_tab = retained
                self.retained_feed = True
        if self.retained_feed and url == 'https://www.douyin.com/?recommend=1':
            self.retained_feed = False
            # The playback controller independently checks the live challenge,
            # identity of the active video, readiness and actual time progress.
            state = self.page.locator('html').evaluate('() => ({host:location.hostname,path:location.pathname})')
            if state == {'host':'www.douyin.com','path':'/'}:
                self.keep_background()
                return self.page
        self.page.goto(url)
        self.keep_background()
        return self.page

    def keep_background(self):
        self._guard()
        from .window_supervision import enabled as supervision_enabled
        if supervision_enabled(self.resource):
            return {}  # A user's expanded monitor must not be minimized on navigation.
        from .retained_feed_session import enabled as minimized_enabled
        from src.scheduler.account_refresh import DB
        if (getattr(self.resource,'headless',True) is False
                and minimized_enabled(self.resource.account_uuid,DB)):
            result=self.owner.get_page(self.page.tab_id)._cmd('minimize_window')
            if result.get('minimized') is not True:
                raise RuntimeError('Account window minimization not confirmed')
            return {'minimized':True,'muted':bool(self.config.mute_audio)}
        return {}

    def verify_feed_transition_identity(self):
        """Fresh original identity in this command's separate owner-owned tab."""
        self._guard()
        ctx = self.origin_context
        if (ctx.command.get('kind') != 'maintenance'
                or ctx.command.get('payload', {}).get('mode') != 'playback'):
            raise BrowserControlRejected('feed_transition_scope_mismatch',
                                         '换片核验仅属于当前推荐流观看任务。')
        expected = self.resource.context.binding
        expected_uid = str(getattr(expected, 'public_uid', '') or '')
        proof = dict(schema='feed_transition_identity/v1', account_uuid=ctx.account_id,
            command_id=ctx.task_id, owner_id=ctx.actor.owner_id, generation=ctx.actor.generation,
            binding_version=ctx.binding_version, feed_tab_id=self.page.tab_id,
            expected_public_uid=expected_uid, source='runtime.verify_identity')
        if not expected_uid:
            return dict(proof, healthy=False, status='identity_unavailable', verified_at=time.time())
        identity_session = BorrowedSession(self.resource, 'feed_transition_identity')
        try:
            if identity_session.owner is not self.owner or identity_session.page.tab_id == self.page.tab_id:
                raise BrowserControlRejected('feed_transition_scope_mismatch', '身份核验标签页不属于原浏览器。')
            check = self.resource.runtime.verify_identity(self.resource.context, session=identity_session)
            actual_uid = str(getattr(getattr(check, 'actual', None), 'public_uid', '') or '')
            return dict(proof, healthy=bool(check.healthy and actual_uid == expected_uid),
                status=check.status if not check.healthy else ('active' if actual_uid == expected_uid else 'identity_mismatch'),
                actual_public_uid=actual_uid, verified_at=time.time(),
                identity_tab_id=identity_session.page.tab_id)
        finally:
            # This closes only the new identity tab; never navigate/close the feed.
            identity_session.stop()

    def stop(self):
        if not self.closed:
            if not getattr(self, 'supervised', False):
                self.owner.close_tab(self.page.tab_id)
            self.closed = True


def borrow_session(account_key, *, headless=False):
    ctx = active_context()
    if ctx is None:
        if enabled():
            raise BrowserControlRejected('managed_browser_required', '账号浏览器只能由管控后台owner创建。')
        return None
    if ctx.resource.account_key != account_key:
        raise BrowserControlRejected('account_uuid_mismatch', '不能借用其他账号的浏览器。')
    # A live headless resource cannot silently turn visible. The host chooses the
    # mode at creation; manual requests wait for a clean, known idle migration.
    if not headless and ctx.resource.session is not None and ctx.resource.session.config.headless:
        raise BrowserControlRejected('visible_session_required', '现有无头会话需在已知空闲后正常交还，才能打开可见窗口。')
    return BorrowedSession(ctx.resource, ctx.command['kind'])


@contextmanager
def operation_scope(account_uuid, owner):
    token = _lease.set((account_uuid, owner))
    try:
        yield
    finally:
        _lease.reset(token)


class AccountBrowserResource:
    def __init__(self, context, runtime, *, headless=True):
        self.account_key, self.account_uuid = context.account_key, context.account_uuid
        self.context, self.runtime, self.headless = context, runtime, headless
        self.session = None
        self.manual_tasks = {}
        self.console_tasks = {}

    def ensure_session(self):
        if self.session is None:
            from src.platform_adapter.douyin_warmup import DouyinWarmupService
            state = self.runtime.bindings.get_runtime_state(self.account_uuid)
            if state.lock_owner and _lease.get() != (self.account_uuid, state.lock_owner):
                raise BrowserControlDeferred('legacy_runtime_pending', '原业务尚未交还浏览器。')
            from .retained_feed_session import enabled as minimized_enabled
            from .window_supervision import enabled as supervision_enabled
            from src.scheduler.account_refresh import DB
            supervised = supervision_enabled(self)
            minimized = self.headless and (supervised or minimized_enabled(self.account_uuid, DB))
            self.session = DouyinWarmupService().build_browser_session(self.account_key, headless=False if minimized else self.headless)
            if minimized:
                if supervised:
                    from .interactive_desktop import require_interactive_desktop
                    require_interactive_desktop()
                self.session.config.mute_audio = True
                self.session.config.start_minimized = True
                self.session.start()
                if self.session.get_page()._cmd('minimize_window').get('minimized') is not True:
                    raise RuntimeError('Account window minimization not confirmed')
                self.headless = False
        return self.session

    def shutdown(self):
        if self.session:
            self.session.stop()
            self.session = None
        self.retained_feed_tab = None
        self.supervision_tab = None


def _legacy_manual_gate(context):
    from .manual_window_jobs import has_pending_manual_window_job
    if has_pending_manual_window_job(context.account_uuid, context.account_key, _legacy_only=True):
        raise BrowserControlDeferred('legacy_manual_pending', '旧人工窗口仍在途或未知，不能热接管原worker。')


def _controls(context):
    from src.scheduler.account_refresh import snapshot
    data = snapshot()
    return next((row for row in data['controls'] if row['account_uuid'] == context.account_uuid), None)


def operation_daily_limit(operation, daily_limit, account_uuid):
    """A frozen exception only for its original managed operation and revision."""
    ctx = active_context()
    if ctx is not None and ctx.command['kind']=='publication_comment_settlement':
        from .publication_comment_settlement_control import daily_limit as settlement_limit
        return settlement_limit(ctx,operation,daily_limit,account_uuid,_controls(ctx.resource.context))
    if ctx is not None and ctx.command['kind']=='publication_reconcile':
        from .publication_autonomous_reconciliation import daily_limit as reconciliation_limit
        from .publication_two_run_authorization import control_snapshot
        return reconciliation_limit(ctx,operation,daily_limit,account_uuid,control_snapshot(account_uuid))
    if (ctx is None or daily_limit != 20
            or not ctx.command.get('payload', {}).get('quota_authorization')):
        return daily_limit
    from .publication_two_run_authorization import authorized_daily_limit, control_snapshot
    return authorized_daily_limit(ctx, operation, default=daily_limit, account_uuid=account_uuid,
        control=control_snapshot(account_uuid))


def _admission(ctx, phase):
    resource = ctx.resource
    if phase == 'dispatch':
        # Per-element fences must not rewrite the warmup account metadata.
        current = replace(resource.context,
            profile=resource.runtime.profiles.get(resource.account_key),
            binding=resource.runtime.bindings.get(resource.account_key))
    else:
        current = resource.runtime.resolve(resource.account_key, require_healthy=False)
    if current.account_uuid != ctx.account_id or binding_version(current) != ctx.binding_version:
        raise BrowserControlRejected('binding_changed', '原身份或浏览器绑定已变化。')
    if current.profile.status != 'active':
        raise BrowserControlRejected('account_disabled', '账号已暂停或停用，不能继续网页操作。')
    _legacy_manual_gate(current)
    state = resource.runtime.bindings.get_runtime_state(current.account_uuid)
    held = _lease.get()
    if state.lock_owner and held != (current.account_uuid, state.lock_owner):
        raise BrowserControlDeferred('legacy_runtime_pending', '原业务锁尚未交还，不清除或借写原锁。')
    kind = ctx.command['kind']
    if kind == 'read' and ctx.command.get('payload', {}).get('method') == 'reveal_manual_window':
        from .manual_window_visibility import check
        check(ctx, ctx.command['payload'])
        resource.context = current
        return  # Only window placement of the still-owned manual tab is allowed.
    feed_diagnostic = (kind == 'read' and ctx.command.get('payload', {}).get('method') == 'inspect_recommendation_surface'
        and ctx.command['payload'].get('params') == {} and ctx.command['payload'].get('operation_profile') is None)
    if kind=='maintenance' and phase=='start' and ctx.command.get('payload',{}).get('mode')=='post-publish':
        from src.scheduler.deployment_maintenance import held_command
        held_command_record=held_command(ctx.command)
        if held_command_record:
            from . import publication_autonomous_reconciliation as autonomous
            if (autonomous.is_v2(held_command_record['authorization'])
                    and autonomous.REGISTRY.exists()
                    and json.loads(autonomous.REGISTRY.read_bytes())==held_command_record['authorization']):
                from .maintenance import AccountMaintenanceService
                limit=AccountMaintenanceService.MODE_LIMITS['post-publish'][0]
                now=datetime.now(timezone.utc)
                if state.day_key==now.date().isoformat() and daily_limit_reached(state.daily_runs, limit):
                    raise BrowserControlDeferred('daily_quota_exceeded',f'原维护请求仍待普通每日额度{limit}，保留原ID与调度游标。')
    if kind not in {'manual', 'recovery'}:
        control = _controls(current)
        from . import publication_autonomous_reconciliation as autonomous
        if kind=='publication_comment_settlement':
            from .publication_comment_settlement_control import get_verified_settlement_inputs
            scoped_pause=autonomous.control_allowed(get_verified_settlement_inputs(ctx.command['payload'])['authorization'])
        else:
            scoped_pause=(kind=='publication_reconcile' and autonomous.is_v2(ctx.command['payload'].get('reconciliation_authorization'))
                and autonomous.control_allowed(autonomous.get_verified_reconciliation_inputs(ctx.command['payload'])['authorization']))
        if kind == 'publication_verify':
            from .publication_verification_recovery import inputs as verification_inputs
            verification_inputs(ctx.actor.store,ctx.command,current)
            scoped_pause = True  # Read-only original verification, never normal business.
        if (current.binding.status != 'active' or (control and control['state'] != 'active' and not scoped_pause and not feed_diagnostic)
                or resource.manual_tasks or getattr(resource, 'console_tasks', {})):
            raise BrowserControlDeferred('human_required', '原账号尚待处理/核验，已保留排队请求。')
    inspection_read = (kind == 'read'
        and ctx.command.get('payload', {}).get('method') in {'inspect_upload_surface', 'inspect_recommendation_surface'})
    if kind=='publication_reconcile':
        from .publication_autonomous_reconciliation import daily_limit as reconciliation_limit
        from .publication_two_run_authorization import control_snapshot
        reconciliation_limit(ctx,'publication-reconciliation',20,current.account_uuid,control_snapshot(current.account_uuid))
    if kind=='publication_comment_settlement':
        from .publication_comment_settlement_control import daily_limit as settlement_limit
        settlement_limit(ctx,'publication-comment-settlement',20,current.account_uuid,control)
    if (kind in {'publish', 'manual', 'recovery','publication_reconcile','publication_comment_settlement','publication_verify'} or inspection_read) and phase == 'start':
        # Known pre-dispatch limits are waiting conditions, not uncertain
        # browser outcomes. The original transactional lease checks again.
        from .repository import _parse_time
        task_name = {'publish': '发布', 'manual': '人工窗口',
            'recovery': '原身份核验', 'publication_verify':'原作品补查'}.get(kind, '上传页检查')
        now = datetime.now(timezone.utc)
        circuit_until = _parse_time(state.circuit_open_until)
        # The original manual-session lease deliberately permits repair during
        # circuit cooldown; recovery and normal business keep that circuit gate.
        if kind != 'manual' and circuit_until is not None and circuit_until > now:
            raise BrowserControlDeferred('circuit_open', f'账号仍在原熔断冷却，{task_name}请求保留原ID等待。')
        operation = {'publish': 'publish', 'recovery': 'identity-recovery'}.get(kind, 'manual-session' if kind == 'manual' else 'inspection-read')
        # Admission runs outside _with_active; pass this exact claimed context.
        from .publication_two_run_authorization import authorized_daily_limit, control_snapshot
        if kind=='publication_reconcile':
            limit=reconciliation_limit(ctx,'publication-reconciliation',20,current.account_uuid,control_snapshot(current.account_uuid))
        elif kind=='publication_comment_settlement':
            limit=settlement_limit(ctx,'publication-comment-settlement',20,current.account_uuid,control)
        else:
            limit=authorized_daily_limit(ctx, operation, account_uuid=current.account_uuid,
                control=control_snapshot(current.account_uuid)) if ctx.command.get('payload', {}).get('quota_authorization') else 20
        daily_runs = state.daily_runs if state.day_key == now.date().isoformat() else 0
        if daily_limit_reached(daily_runs, limit):
            raise BrowserControlDeferred('daily_quota_exceeded', f'账号今日运行次数已达到上限{limit}，{task_name}请求保留原ID等待。')
    resource.context = current


def _with_active(handler):
    def call(ctx, payload):
        token = _active.set(ctx)
        try:
            return handler(ctx, payload)
        finally:
            _active.reset(token)
    return call


def queue_publication_reconciliation(authorization, *, attempt=None):
    from . import publication_autonomous_reconciliation as autonomous
    if autonomous.is_v2(authorization):
        inputs=autonomous.validate_authorization(authorization);auth=inputs['authorization']
        context=_runtime().resolve(auth['account_key'],require_healthy=False)
        return autonomous.queue(_store(),authorization,binding_version(context),attempt)
    if attempt is not None:
        raise BrowserControlRejected('reconciliation_attempt_invalid','原单次核查不接受续查序号。')
    from .publication_reconciliation_authorization import validate_reconciliation_authorization,KEY
    inputs=validate_reconciliation_authorization(authorization); auth=inputs['authorization']
    return _submit(auth['account_key'],'publication_reconcile',{
        'account_uuid':auth['account_uuid'],'account_key':auth['account_key'],
        'original_command_id':auth['original_command_id'],'reconciliation_authorization':dict(authorization)},KEY,400)


@_with_active
def _publication_comment_settlement(ctx,payload):
    from .publication_comment_settlement_workflow import run_settlement
    resource=ctx.resource
    if resource.session is not None and resource.session.config.headless:
        raise BrowserControlRejected('visible_session_required','只读补核使用受控可见窗口。')
    resource.headless=False
    with resource.runtime.operation_lease(resource.context,operation='publication-comment-settlement',daily_limit=20,cooldown_seconds=0):
        resource.ensure_session()
        borrowed=BorrowedSession(resource,'publication-comment-settlement')
        result=None
        try:
            result=run_settlement(ctx,payload,borrowed)
        finally:
            tab_id=getattr(getattr(borrowed,'page',None),'tab_id',None)
            if tab_id and isinstance(result,dict) and result.get('status') in {'verified_published','verification_pending'}:
                borrowed.stop()
            elif tab_id:
                resource.console_tasks[ctx.task_id]=tab_id
    if result.get('status')=='verified_published':
        ctx.actor.store.resolve_publication_reconciliation(ctx.task_id,ctx.actor.owner_id,ctx.actor.generation,result)
        from .publication_autonomous_reconciliation import resume_verified_control
        resume_verified_control(ctx.actor.store,ctx.account_id)
        return result
    return BrowserCommandResult('outcome_unknown',result)


@_with_active
def _publication_reconcile(ctx,payload):
    from .publication_reconciliation import run_reconciliation
    from .publication_autonomous_reconciliation import is_v2
    resource=ctx.resource
    if resource.session is not None and resource.session.config.headless:
        raise BrowserControlRejected('visible_session_required','核查必须使用受控可见窗口。')
    resource.headless=False
    with resource.runtime.operation_lease(resource.context,operation='publication-reconciliation',daily_limit=20,cooldown_seconds=0):
        resource.ensure_session()
        borrowed=BorrowedSession(resource,'publication-reconcile')
        resource.reconciliation_session=borrowed
        result=None
        try:
            result=run_reconciliation(ctx,payload)
        finally:
            # Retain the visible tab. Closure only records UI state, never resolves publication.
            tab_id=getattr(getattr(borrowed,'page',None),'tab_id',None)
            if (tab_id and is_v2(payload.get('reconciliation_authorization')) and isinstance(result,dict)
                    and result.get('status') in {'not_found','verification_pending','verified_published'}):
                borrowed.stop()  # Only this task's tab; all RPCs precede resolve.
            elif tab_id:
                resource.console_tasks[ctx.task_id]=tab_id
            resource.reconciliation_session=None
    if result.get('status')=='verified_published':
        # Last operation after all browser/comment RPCs; unknown evidence guards no longer run afterward.
        try:
            ctx.actor.store.resolve_publication_reconciliation(ctx.task_id,ctx.actor.owner_id,ctx.actor.generation,result)
            if is_v2(payload.get('reconciliation_authorization')):
                from .publication_autonomous_reconciliation import resume_verified_control
                resume_verified_control(ctx.actor.store,ctx.account_id)
        except BrowserControlRejected as exc:
            return BrowserCommandResult('outcome_unknown',dict(result,status='verification_pending',resolution_guard_error=exc.code))
        return result
    return BrowserCommandResult('outcome_unknown',result)


@_with_active
def _maintenance(ctx, payload):
    from .maintenance import AccountMaintenanceService
    from src.platform_adapter.douyin_playback import PlaybackOptions
    kwargs = payload['options']
    if kwargs.get('playback_options') is not None:
        kwargs = dict(kwargs, playback_options=PlaybackOptions(**kwargs['playback_options']))
    result = AccountMaintenanceService(runtime=ctx.resource.runtime).run(payload['account_key'], payload['mode'], **kwargs)
    value = {'maintenance_result': asdict(result)}
    if result.status not in {'completed', 'skipped'}:
        return BrowserCommandResult('failed', value)
    return value


@_with_active
def _publication_verify(ctx, payload):
    from .publication_verification_recovery import run
    resource = ctx.resource
    with resource.runtime.operation_lease(resource.context,
            operation='publication-verification-read', daily_limit=20, cooldown_seconds=0):
        resource.ensure_session()
        session = BorrowedSession(resource, 'publication-verification-read')
        try:
            return run(ctx, session)
        except BrowserControlRejected as exc:
            if exc.code in {'owner_unknown','owner_fenced','command_fenced'}:
                raise
            return BrowserCommandResult('failed', {'status':'verification_blocked','reason':exc.code})
        except Exception as exc:
            # A confirmed tab closure below ends this read, but proves nothing
            # about the original publication. Only bounded read retries follow.
            return BrowserCommandResult('failed', {'status':'verification_pending','reason':'read_failed',
                                                   'error_type':type(exc).__name__})
        finally:
            session.stop()


@contextmanager
def _publication_lease(resource):
    """Nested priority work accounts a run while retaining the original mutex."""
    held = _lease.get()
    if held is None:
        with resource.runtime.operation_lease(resource.context, operation='publish', daily_limit=20, cooldown_seconds=0):
            yield
        return
    now = datetime.now(timezone.utc)
    limit = operation_daily_limit('publish', 20, resource.account_uuid)
    with resource.runtime.bindings.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM account_runtime_state WHERE account_uuid=?', (resource.account_uuid,)).fetchone()
        if not row or held != (resource.account_uuid, row['lock_owner']):
            raise BrowserControlRejected('parent_lease_changed', '后台原运行锁已变化。')
        if row['circuit_open_until'] and row['circuit_open_until'] > now.isoformat():
            raise BrowserControlRejected('circuit_open', '账号仍在熔断冷却。')
        runs = row['daily_runs'] if row['day_key'] == now.date().isoformat() else 0
        if daily_limit_reached(runs, limit):
            raise BrowserControlRejected('daily_quota_exceeded', f'账号今日运行次数已达到上限{limit}。')
        db.execute('UPDATE account_runtime_state SET day_key=?,daily_runs=?,last_run_at=?,updated_at=? WHERE account_uuid=? AND lock_owner=?',
            (now.date().isoformat(), runs+1, now.isoformat(), now.isoformat(), resource.account_uuid, held[1]))
    yield


@_with_active
def _publish(ctx, payload):
    from src.platform_adapter.models import PublishRequest
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    from src.platform_adapter.publish_verification import video_id
    if not payload.get('authorization'):
        raise BrowserControlRejected('authorization_required', '未绑定发布授权。')
    auth = payload['authorization']
    if isinstance(auth, dict) and auth.get('path') and _sha(auth['path']) != auth.get('sha256'):
        raise BrowserControlRejected('authorization_changed', '原发布授权文件已变化。')
    request = PublishRequest(**payload['request'])
    comment_request = ({'video_path': str(Path(request.video_path).resolve()),
        'title': request.title, 'hashtags': request.normalized_hashtags()}
        if isinstance(auth, dict) and auth.get('comment') else None)
    if _sha(request.video_path) != payload['video_sha256']:
        raise BrowserControlRejected('video_changed', '原成片字节已变化。')
    _admission(ctx, 'external_dispatch')
    resource = ctx.resource
    with _publication_lease(resource):
        resource.ensure_session()
        session = BorrowedSession(resource, 'publish')
        try:
            adapter = DouyinAdapter(session=session, runtime_context=resource.context)
            result = adapter.publish_video(request)
            value = asdict(result)
            value['comment_pending'] = bool(isinstance(auth, dict) and auth.get('comment'))
            if result.status in {'submission_unknown', 'published_unverified', 'verification_pending', 'post_publish_verification_pending'}:
                return BrowserCommandResult('outcome_unknown', value)
            if not result.success:
                return BrowserCommandResult('failed', value)
            if video_id(result.publish_url) != result.post_id:
                return BrowserCommandResult('outcome_unknown', dict(value, verification_error='exact_work_missing'))
            from src.content_factory.creative_delivery import journal_evidence
            evidence = journal_evidence(adapter)
            value['publish_evidence'] = evidence
            if result.status != 'published' or not evidence.get('post_verified'):
                return BrowserCommandResult('outcome_unknown', value)
            if isinstance(auth, dict) and auth.get('comment'):
                from .publication_comment import post_authorized_publication_comment
                try:
                    full_evidence = _comment_publish_evidence(adapter, evidence, comment_request,
                        result.post_id, payload['video_sha256'])
                except (OSError, ValueError, TypeError, KeyError):
                    value['comment'] = {'status': 'publish_evidence_unbound', 'submitted': False}
                    return BrowserCommandResult('outcome_unknown', value)
                value['comment_publish_evidence'] = full_evidence
                value['comment'] = post_authorized_publication_comment(adapter,
                    {'account_key': resource.account_key, 'account_uuid': resource.account_uuid,
                     'authorization': auth, 'comment': auth['comment'],
                     'title': comment_request['title'], 'hashtags': comment_request['hashtags'],
                     'publish_evidence': full_evidence}, result.post_id)
                value['comment_pending'] = value['comment'].get('status') not in {'sent_visible', 'matching_comment_already_visible'}
                if value['comment_pending']:
                    return BrowserCommandResult('outcome_unknown', value)
            return value
        finally:
            session.stop()


def _comment_publish_evidence(adapter, summary, frozen_request, post_id, video_sha256):
    """Return only the actual final same-request journal proof, never a summary."""
    reference = summary.get('journal')
    journal = getattr(adapter.publish_workflow, '_journal_path', None)
    if (not isinstance(reference, dict) or not journal
            or Path(reference['path']).resolve() != Path(journal).resolve()):
        raise ValueError('Original publication journal is missing')
    data = Path(journal).read_bytes()
    if hashlib.sha256(data).hexdigest() != reference.get('sha256'):
        raise ValueError('Original publication journal changed')
    rows = [json.loads(line) for line in data.decode('utf8').splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('Original publication journal is malformed')
    prepared = [row for row in rows if row.get('stage') == 'prepared']
    checked = [row for row in rows if row.get('stage') == 'post_publish_checked']
    if len(prepared) != 1 or not checked:
        raise ValueError('Original publication proof is incomplete')
    source = prepared[0]
    if (source.get('title') != frozen_request['title'] or source.get('hashtags') != frozen_request['hashtags']
            or source.get('video_sha256') != video_sha256
            or str(Path(source.get('video_path', '')).resolve()) != frozen_request['video_path']):
        raise ValueError('Publication proof belongs to a different frozen request')
    evidence = checked[-1].get('evidence')
    if not isinstance(evidence, dict) or evidence.get('verified') is not True:
        raise ValueError('Final publication proof is not verified')
    ids = [evidence[key] for key in ('expected_post_id', 'post_id') if key in evidence]
    if (not ids or any(str(value) != str(post_id) for value in ids)
            or evidence.get('expected_title') != frozen_request['title']
            or not isinstance(evidence.get('expected_hashtags'), list)
            or evidence['expected_hashtags'] != frozen_request['hashtags']):
        raise ValueError('Exact published work proof differs from the frozen request')
    return evidence


@_with_active
def _manual(ctx, payload):
    from .manual_handling import resolve_manual_handling_target, _pause_for_handling
    from src.scheduler.account_refresh import snapshot
    from src.platform_adapter.douyin_challenge import confirmed_douyin_challenge
    resource = ctx.resource
    data = snapshot()
    if payload.get('incident_id') is not None:
        from src.scheduler.browser_visibility import automatic_window_allowed
        from src.scheduler.account_manual_windows import _eligible
        incident = next((row for row in data.get('issues', [])
            if row.get('id') == payload['incident_id']), {})
        if (incident.get('account_uuid') != resource.account_uuid
                or incident.get('account_key') != resource.account_key
                or not _eligible(data, incident)):
            raise BrowserControlRejected('incident_no_longer_actionable', '原异常已不再是当前待处理事件，未打开网页。')
        if not automatic_window_allowed(resource.account_uuid, issue=incident):
            raise BrowserControlRejected('automatic_window_disabled', '此账号仅按已保存的验证窗口规则开窗，原异常与暂停保持。')
    from .interactive_desktop import require_interactive_desktop
    require_interactive_desktop()
    if resource.session is not None and resource.session.config.headless:
        # Idle here: the actor stack has no running background operation. The
        # original lease gate already proved no pending work. Rebuild is explicit.
        resource.shutdown()
    resource.headless = False
    target = resolve_manual_handling_target(resource.context.profile,
        account_uuid=resource.account_uuid, account_key=resource.account_key, snapshot=data)
    _pause_for_handling(resource.account_uuid, resource.account_key)
    with resource.runtime.operation_lease(resource.context, operation='manual-session',
            daily_limit=20, cooldown_seconds=0, allow_manual_verification=True):
        session = resource.ensure_session()
        # Verification windows may be visible while ordinary viewing stays
        # hidden. Keep the exception window silent as well.
        session.config.mute_audio = True
        ctx.check_dispatch()
        try:
            page = session.new_tab('manual')
        except Exception as exc:
            from src.platform_adapter.browser_session import BrowserWorkerStartupError, BrowserWorkerStartupTimeout
            from src.shared.browser_startup_diagnostics import clean
            if not isinstance(exc, (BrowserWorkerStartupError, BrowserWorkerStartupTimeout)):
                raise
            proof = clean(exc.startup_evidence)
            # Only this brand-new, never-ready attempt may be a known failure.
            # A lost ready browser/RPC or unproven cleanup remains unknown.
            known = (proof.get('ready_received') is False and proof.get('cleanup_verified') is True
                     and proof.get('stage') not in {None, 'ready'}
                     and getattr(session, '_proc', object()) is None
                     and getattr(session, '_startup_cleanup_verified', False) is True)
            return BrowserCommandResult('failed' if known else 'outcome_unknown',
                {'status': 'manual_window_not_opened' if known else 'startup_cleanup_unconfirmed',
                 'error_code': exc.code, 'error_type': type(exc).__name__,
                 'startup_evidence': proof, 'window_open_confirmed': False,
                 'identity_verified': False, 'account_resume_requested': False})
        ctx.check_dispatch()
        navigation_failed = False
        try:
            navigation_evidence = _open_manual_target(page, target.url)
        except Exception as exc:
            from src.platform_adapter.browser_session import BrowserNavigationTimeout
            if (not isinstance(exc, BrowserNavigationTimeout) or exc.page is not page
                    or getattr(target, 'source', '') != 'recommend_feed'):
                raise
            # A known navigation timeout in this exact read-only handling tab
            # does not make publication/other business outcomes known. Keep the
            # original page for live observation, without another navigation.
            navigation_evidence = exc.navigation_evidence
            navigation_failed = True
        # The target comes from the old receipt, but this is a new navigation.
        # Its current verification surface must be observed independently.
        ctx.check_dispatch()
        class CurrentManualPage:
            # The confirmation helper can issue several probe/wait RPCs. Each
            # retains the original actor admission fence on the same page.
            def probe_douyin_challenge(self):
                ctx.check_dispatch()
                return page.probe_douyin_challenge()

            def wait_for_timeout(self, milliseconds):
                ctx.check_dispatch()
                return page.wait_for_timeout(milliseconds)

        try:
            if navigation_failed:
                raise RuntimeError('recommendation_navigation_not_ready')
            observed = confirmed_douyin_challenge(CurrentManualPage())
        except Exception:
            # Exception messages can contain page content or URL parameters.
            current = {'status': 'verification_unknown', 'surface_state': 'unknown',
                'error_code': 'challenge_probe_failed'}
        else:
            current = {name: observed[name] for name in ('version', 'blocking',
                'surface_state', 'frame_count', 'actionable_frames', 'visible_dialogs',
                'observations', 'confirmations')}
            current['status'] = ('challenge_controls_confirmed'
                if observed['blocking'] and observed['surface_state'] == 'challenge_ready'
                    and observed['confirmations'] >= 2 else
                'current_no_challenge' if not observed['blocking']
                    and observed['surface_state'] == 'clear' else 'verification_unknown')
        ctx.check_dispatch()
        current['observed_at'] = datetime.now(timezone.utc).isoformat()
    resource.manual_tasks[ctx.task_id] = page.tab_id
    # Retain the task/tab fence even if display acknowledgement is unavailable.
    # A display failure is never permission to open a second profile.
    ctx.check_dispatch()
    try:
        display = page._cmd('reveal_manual_window')
    except Exception:
        display = {'restored': False}
    message = {
        'challenge_controls_confirmed': '当前已连续识别到验证提示和可操作控件；请按网页提示人工处理。',
        'current_no_challenge': '当前未检测到验证控件；不代表旧异常已解决或账号已恢复，请核对页面。',
        'verification_unknown': '当前验证界面仍在加载、不可读取或未确认；尚不能确认有可操作控件，请核对页面加载情况。',
    }[current['status']]
    return BrowserCommandResult('waiting_human', {'phase': 'window_open_waiting_handling',
        'window_visibility': {'restored': display.get('restored') is True},
        'tab_id': page.tab_id, 'navigation': 'new_target_navigation',
        'navigation_evidence': navigation_evidence,
        'target': {'source': getattr(target, 'source', 'fallback'),
            'run_id': getattr(target, 'run_id', ''),
            'maintenance_run_id': getattr(target, 'maintenance_run_id', ''),
            'url_sha256': hashlib.sha256(target.url.encode('utf-8')).hexdigest()},
        'current_verification': current,
        'message': '已在原账号环境重新打开处理目标。' + message +
            '处理后点击完成，由后台核验原身份；本次探测不会自动恢复。'})


def _open_manual_target(page, url):
    """Keep a committed original page for human inspection, without navigating twice."""
    from src.platform_adapter.browser_session import BrowserNavigationTimeout
    try:
        page.goto(url)
    except BrowserNavigationTimeout as exc:
        evidence = exc.navigation_evidence
        if (exc.page is not page or not evidence['target_matched']
                or not evidence['navigation_committed']
                or evidence['ready_state'] not in {'interactive', 'complete'}):
            raise
        # This only proves the target document opened. The caller separately
        # observes verification controls and still returns waiting_human.
        return evidence
    return {}


@_with_active
def _official_console(ctx, payload):
    """Original official-console action in the owner; no account pause/resume."""
    from .manual_handling import CREATOR_CONTENT_URL
    resource = ctx.resource
    if resource.session is not None and resource.session.config.headless:
        resource.shutdown()  # No running business or protected human task here.
    resource.headless = False
    with resource.runtime.operation_lease(resource.context, operation='official_console',
            daily_limit=100, cooldown_seconds=0, lock_seconds=1800):
        identity_session = BorrowedSession(resource, 'official_identity')
        try:
            check = resource.runtime.verify_identity(resource.context, session=identity_session)
            if not check.healthy:
                raise BrowserControlRejected(check.status, '专属环境身份核验未通过：' + check.message)
        finally:
            identity_session.stop()
        session = resource.ensure_session()
        ctx.check_dispatch()
        page = session.new_tab('official_console')
        ctx.check_dispatch()
        page.goto(CREATOR_CONTENT_URL)
    resource.console_tasks[ctx.task_id] = page.tab_id
    return BrowserCommandResult('waiting_human', {'phase': 'official_console_open',
        'tab_id': page.tab_id, 'account_pause_changed': False,
        'message': '官方管理页已在原账号环境打开；操作完成后关闭此标签页即可交还，不需要点击处理完成。'})


def official_console_snapshot(account_key):
    rows = _window_commands(account_key, 'official_console')
    return max(rows, key=lambda row: row['created_at']) if rows else None


def queue_official_console(account_uuid, account_key, requested_by):
    context = _runtime().resolve(account_key)
    if context.account_uuid != account_uuid or not isinstance(requested_by, str) or not requested_by.strip():
        raise BrowserControlRejected('account_uuid_mismatch', '官方窗口需要原账号和实际操作者。')
    rows = _window_commands(account_key, 'official_console')
    existing = next((row for row in rows if row['kind'] == 'official_console'
        and row['state'] in {'queued', 'running', 'waiting_human', 'paused', 'outcome_unknown'}), None)
    history = [row for row in rows if row['kind'] == 'official_console']
    previous = max(history, key=lambda row: row['created_at']) if history else None
    # Two UI callers that observed the same previous terminal state submit the
    # same key; core's atomic uniqueness prevents a pair of queued windows.
    key = 'official-console:after:' + (previous['command_id'] if previous else 'initial')
    return existing or _submit(account_key, 'official_console', {'requested_by': requested_by}, key, 20)


@_with_active
def _recovery(ctx, payload):
    resource = ctx.resource
    result = resource.runtime.probe_recovery(resource.account_key, headless=resource.headless)
    if result.healthy and payload.get('identity_probe_only') is not True:
        for task_id in list(resource.manual_tasks):
            ctx.actor.store.complete_waiting(task_id, ctx.actor.owner_id, ctx.actor.generation,
                result={'identity_verified': True, 'manual_tab_preserved': True})
            resource.manual_tasks.pop(task_id)
    output = {'healthy': result.healthy, 'status': result.status, 'message': result.message,
        'expected_account_uuid': result.expected.account_uuid}
    if getattr(result, 'navigation_evidence', None) is not None:
        from src.shared.browser_navigation import clean_navigation_evidence
        output['navigation_evidence'] = clean_navigation_evidence(result.navigation_evidence)
    return output


@_with_active
def _adapter_read(ctx, payload):
    if payload.get('method') == 'reveal_manual_window':
        from .manual_window_visibility import reveal
        return reveal(ctx, payload)
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    from src.platform_adapter.models import CommentQuery, PublishRequest
    method = payload['method']
    if method not in {'sync_videos', 'fetch_comments', 'verify_published_video', 'inspect_upload_surface', 'inspect_recommendation_surface'}:
        raise BrowserControlRejected('method_not_allowed', '此入口仅接受明确的账号只读操作。')
    if method in {'inspect_upload_surface', 'inspect_recommendation_surface'} and (
            not isinstance(payload.get('params'), dict) or payload['params']):
        raise BrowserControlRejected('inspection_params_invalid', '上传页检查仅接受空参数，不能指定网址、脚本或保存路径。')
    resource = ctx.resource
    params = dict(payload['params'])
    if method == 'fetch_comments':
        params['query'] = CommentQuery(**params['query'])
    if method == 'verify_published_video':
        params['request'] = PublishRequest(**params['request'])
    operation_profile = payload.get('operation_profile')
    if operation_profile is not None:
        if method != 'sync_videos' or operation_profile not in {'creator_metrics_ui', 'creator_metrics_cli'}:
            raise BrowserControlRejected('operation_profile_invalid', '此操作不能借用其他业务的配额。')
        lease_options = dict(operation='creator_metrics', daily_limit=100, cooldown_seconds=60,
            lock_seconds=600 if operation_profile == 'creator_metrics_ui' else 1800)
    else:
        lease_options = dict(operation='browser-read:' + method, daily_limit=20, cooldown_seconds=0)
    with resource.runtime.operation_lease(resource.context, **lease_options):
        session = BorrowedSession(resource, 'read:' + method)
        try:
            if method == 'inspect_recommendation_surface':
                if not resource.headless or (resource.session is not None and not resource.session.config.headless):
                    raise BrowserControlRejected('diagnostic_requires_headless', '推荐流诊断只允许隐藏静音环境。')
                check = resource.runtime.verify_identity(resource.context, session=session)
                if not check.healthy:
                    raise BrowserControlRejected(check.status, check.message)
                if not isinstance(ctx.task_id, str) or len(ctx.task_id) != 32 or any(c not in '0123456789abcdef' for c in ctx.task_id):
                    raise BrowserControlRejected('inspection_command_invalid', 'Invalid diagnostic command ID')
                from src.platform_adapter.douyin_recommendation_playback import FEED_URL
                from src.platform_adapter.feed_surface_diagnostic import capture_feed_surface
                page = session.open_page(FEED_URL)
                diagnostic = capture_feed_surface(page, ROOT/'data/feed_surface_diagnostics'/ctx.task_id)
                return {'read_result': dict(diagnostic, status='inspected', account_uuid=ctx.account_id,
                    inspected_url=FEED_URL, identity_healthy=True, account_pause_changed=False)}
            if method == 'inspect_upload_surface':
                # The owner and business lease are unchanged. Only this fixed
                # empty upload surface is visited after the original identity
                # check; no PublishWorkflow upload or form action is invoked.
                check = resource.runtime.verify_identity(resource.context, session=session)
                if not check.healthy:
                    raise BrowserControlRejected(check.status, check.message)
                command_id = ctx.task_id
                if (not isinstance(command_id, str) or len(command_id) != 32
                        or any(char not in '0123456789abcdef' for char in command_id)):
                    raise BrowserControlRejected('inspection_command_invalid', '检查证据必须绑定原管控任务编号。')
                ctx.check_dispatch()
                page = session.open_page(UPLOAD_INSPECTION_URL)
                page.wait_for_timeout(2000)
                from src.platform_adapter.upload_surface_diagnostic import capture_upload_surface
                diagnostic = capture_upload_surface(page,
                    ROOT / 'data/publication_upload_inspections' / command_id)
                return {'read_result': dict(diagnostic, status='inspected',
                    method=method, inspected_url=UPLOAD_INSPECTION_URL,
                    account_uuid=ctx.account_id, upload_started=False,
                    platform_submission_started=False)}
            adapter = DouyinAdapter(session=session, runtime_context=resource.context)
            result = getattr(adapter, method)(**params)
            return {'read_result': asdict(result) if is_dataclass(result) else result}
        finally:
            session.stop()


def managed_adapter_call(account_key, method, params, *, operation_profile=None):
    if method not in {'sync_videos', 'fetch_comments', 'verify_published_video', 'inspect_upload_surface'}:
        raise BrowserControlRejected('method_not_allowed', '此入口不接受发布、互动或任意浏览器命令。')
    if method == 'inspect_upload_surface' and (not isinstance(params, dict) or params):
        raise BrowserControlRejected('inspection_params_invalid', '上传页检查仅接受空参数。')
    if operation_profile is not None and (method != 'sync_videos'
            or operation_profile not in {'creator_metrics_ui', 'creator_metrics_cli'}):
        raise BrowserControlRejected('operation_profile_invalid', '此操作不能借用其他业务的配额。')
    params = {key: asdict(value) if is_dataclass(value) else value for key, value in params.items()}
    command = _submit(account_key, 'read', {'method': method, 'params': params,
        'operation_profile': operation_profile},
        'read:' + uuid.uuid4().hex, 10)
    result = _await(command)
    if result['state'] != 'succeeded':
        raise BrowserControlRejected(result.get('error_code') or result['state'], '账号只读任务未能完成，原请求已保留。')
    value = result['result']['read_result']
    if method == 'sync_videos':
        from src.platform_adapter.models import SyncResult, VideoItem, VideoStats
        videos = []
        for row in value.get('videos', []):
            row = dict(row)
            if row.get('stats') is not None:
                row['stats'] = VideoStats(**row['stats'])
            videos.append(VideoItem(**row))
        return SyncResult(**dict(value, videos=videos))
    if method == 'fetch_comments':
        from src.platform_adapter.models import CommentSyncResult, CommentRecord
        return CommentSyncResult(**dict(value,
            comments=[CommentRecord(**row) for row in value.get('comments', [])]))
    return value


def queue_inspect_upload(account_key):
    """Persist one fixed read request; browser execution remains backend-only."""
    return _submit(account_key, 'read', {'method': 'inspect_upload_surface',
        'params': {}, 'operation_profile': None}, 'inspect-upload:' + uuid.uuid4().hex, 10)


def queue_manual_window(account_uuid, account_key, requested_by, *, incident_id=None, allow_automatic_resume=True):
    if type(allow_automatic_resume) is not bool:
        raise ValueError('allow_automatic_resume must be a boolean')
    context = _runtime().resolve(account_key, require_healthy=False)
    if context.account_uuid != account_uuid or not requested_by:
        raise BrowserControlRejected('account_uuid_mismatch', '人工窗口需要原账号和实际操作者。')
    key = 'manual:incident:' + str(incident_id) if incident_id else 'manual:request:' + uuid.uuid4().hex
    rows = _window_commands(account_key, 'manual')
    existing = next((row for row in reversed(rows) if row['kind'] == 'manual'
        and row['state'] in {'queued', 'running', 'waiting_human', 'outcome_unknown', 'paused'}), None)
    payload = {'requested_by': requested_by, 'incident_id': incident_id}
    if not allow_automatic_resume:
        payload['allow_automatic_resume'] = False
    result = existing or _submit(account_key, 'manual', payload, key, 200)
    return dict(_manual_public(result), reused=existing is not None)


def _manual_public(command):
    state = command['state']
    finished = command.get('result') or {}
    mapped = {'queued': 'starting', 'waiting_human': 'running',
        'succeeded': 'verified' if finished.get('identity_verified') else 'closed',
        'paused': 'outcome_unknown'}.get(state, state)
    public = dict(job_id=command['command_id'], account_uuid=command['account_id'],
        account_key=command['payload']['account_key'], state=mapped,
        phase='window_open_waiting_handling' if state == 'waiting_human' else state,
        handoff_ready=state == 'waiting_human', managed=True,
        error_code=command.get('error_code') or '', error_type='',
        created_at=command['created_at'], updated_at=command['updated_at'],
        finished_at=command['updated_at'] if state in {'succeeded', 'failed'} else None)
    if state in {'failed', 'outcome_unknown'} and isinstance(finished.get('startup_evidence'), dict):
        from src.shared.browser_startup_diagnostics import clean
        public['startup_evidence'] = clean(finished['startup_evidence'])
        if finished.get('error_type') in {'BrowserWorkerStartupError', 'BrowserWorkerStartupTimeout'}:
            public['error_type'] = finished['error_type']
            public['error_code'] = 'browser_start_failed' if public['error_type'] == 'BrowserWorkerStartupError' else 'browser_start_timeout'
    if state == 'queued':
        from .publication_verification_recovery import queue_blocker
        try:
            public.update(queue_blocker(_store(),command['account_id']))
        except Exception:
            public.update(queue_blocker='status_unavailable')
    if state == 'waiting_human' and isinstance(finished.get('current_verification'), dict):
        evidence = finished['current_verification']
        surface = evidence.get('surface_state')
        if not isinstance(surface, str) or surface not in {'clear', 'challenge_ready', 'loading', 'load_failed',
                'blank', 'unavailable', 'unconfirmed'}:
            surface = 'unknown'
        safe = {'surface_state': surface}
        for name in ('frame_count', 'actionable_frames', 'visible_dialogs', 'observations', 'confirmations'):
            value = evidence.get(name)
            if type(value) is int and 0 <= value <= 10000:
                safe[name] = value
        status = ('challenge_controls_confirmed'
            if evidence.get('blocking') is True and surface == 'challenge_ready'
                and safe.get('confirmations') == 2 else
            'current_no_challenge' if evidence.get('blocking') is False
                and surface == 'clear' else 'verification_unknown')
        safe['status'] = status
        public.update(phase='window_' + status, current_verification=safe)
        target = finished.get('target')
        source = target.get('source') if isinstance(target, dict) else None
        public['target_source'] = source if isinstance(source, str) and source in {'fallback', 'blocked_search',
            'creator_content', 'playback_video', 'recorded_research_keyword', 'recommend_feed'} else 'unresolved'
        if source == 'recommend_feed':
            from .clear_feed_resume import latest_observation
            from src.scheduler.account_refresh import DB as scheduler_db
            try:
                live=latest_observation(command['account_id'],command['command_id'],scheduler_db)
            except Exception:
                live={'stage':'observation_stale'}
            if live:
                public.update(phase='feed_'+live['stage'],feed_observation=live)
    if state == 'waiting_human' and (finished.get('window_visibility') or {}).get('restored') is False:
        public['phase'] = 'window_display_unconfirmed'
    if state == 'succeeded' and finished.get('close_reason') == 'proven_previous_host_boot':
        public.update(phase='closed_by_previous_boot', session_saved=False)
    return public


def manual_window_snapshot(account_uuid, account_key, *, incident_id=None):
    profile = _runtime().profiles.get(account_key)
    if profile.account_uuid != account_uuid:
        raise BrowserControlRejected('account_uuid_mismatch', '人工窗口原账号不一致。')
    path = Path(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB', DB))
    if not path.exists():
        return None
    store = _store()
    data = store.manual_status_snapshot(account_uuid)
    rows = [row for row in data['commands'] if row['kind'] == 'manual'
        and (incident_id is None or row['payload'].get('incident_id') == incident_id)]
    if not rows:
        return None
    from .manual_window_status import present_manual_liveness
    command = max(rows, key=lambda row: (row['created_at'], row['command_id']))
    public = present_manual_liveness(_manual_public(command), command, data['owner'],
                                     now=store.clock(), ttl=store.owner_ttl)
    if public.get('phase') == 'window_owner_unconfirmed':
        try:
            from .manual_boot_closure import preview
            public['previous_boot_cleanup'] = preview(store, account_uuid, account_key, command['command_id'],
                _manual_binding_version(account_uuid, account_key))
        except Exception:
            public['previous_boot_cleanup'] = {'available': False}
    return public


def _manual_binding_version(account_uuid, account_key):
    runtime = _runtime()
    profile, binding = runtime.profiles.get(account_key), runtime.bindings.get(account_key)
    if (profile.account_uuid != account_uuid or binding.account_uuid != account_uuid
            or binding.account_key != account_key):
        raise BrowserControlRejected('account_uuid_mismatch', '原人工窗口绑定不一致。')
    return binding_version(SimpleNamespace(profile=profile, binding=binding))


def close_manual_before_previous_boot(account_uuid, account_key, job_id, proof_sha, requested_by):
    """Explicit UI acknowledgement; no browser, account resume or task replay."""
    from .manual_boot_closure import settle
    return settle(_store(), account_uuid, account_key, job_id,
                  _manual_binding_version(account_uuid, account_key), proof_sha, requested_by)


def _window_commands(account_key, kind):
    profile = _runtime().profiles.get(account_key)
    path = Path(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB', DB))
    if not path.exists():
        return []
    return _store().commands_of_kind(profile.account_uuid, kind)


def snapshot(account_key):
    profile = _runtime().profiles.get(account_key)
    path = Path(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB', DB))
    if not path.exists():
        return {'account_id': profile.account_uuid, 'owner': None, 'commands': []}
    return _store().snapshot(profile.account_uuid)


def operational_snapshot(account_key):
    profile = _runtime().profiles.get(account_key)
    path = Path(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB', DB))
    if not path.exists():
        return {'account_id': profile.account_uuid, 'owner': None, 'commands': []}
    return _store().operational_snapshot(profile.account_uuid)


def _release_changed_binding(actor, resource, current_context):
    """Fence a new configuration before claim_next can reject its queued work."""
    if binding_version(current_context) == actor.binding_version:
        return 'unchanged'
    data = actor.store.snapshot(resource.account_uuid)
    unresolved = any(row['state'] in {'running', 'paused', 'waiting_human', 'outcome_unknown'}
        for row in data['commands'])
    protected = resource.manual_tasks or getattr(resource, 'console_tasks', {}) or (resource.session and any(
        row.get('role') in {'manual', 'official_console'} and not row.get('closed') for row in resource.session.list_tabs()))
    if unresolved or protected:
        return 'waiting_original'
    resource.shutdown()
    actor.close()
    return 'released'


def _poll_manual_windows(actor, resource):
    if resource.session:
        failure_probe = getattr(resource.session, "worker_failure", None)
        failure = failure_probe() if callable(failure_probe) else ""
        if failure:
            # This runs between handlers. Only retire a dead resource after all
            # dispatched tasks have known terminal results; never replay them.
            from .publication_autonomous_reconciliation import unresolved
            with actor.store._db() as db:
                pending = unresolved(actor.store, db, resource.account_uuid,
                    ("running", "paused", "waiting_human", "outcome_unknown"))
            if pending or resource.manual_tasks or resource.console_tasks:
                raise BrowserControlRejected("worker_lost_unresolved",
                    "浏览器失效且原任务尚未结清，保留原任务与owner，不自动恢复。")
            resource.shutdown()
            resource.headless = True
            return
        # A verified manual task has already left manual_tasks while its page
        # remains visible. Its later normal closure must still retire the worker.
        if getattr(resource.session, '_proc', object()) is None:
            return  # Known never-started session; do not start a worker to poll.
        status = resource.session.window_status()
        from .manual_tab_closure import settle_closed_manual_tabs
        if settle_closed_manual_tabs(actor,resource,status):
            return
        # A console is returned by closing only its own tab. Other user tabs,
        # especially a platform-verification page, remain owned and untouched.
        closed_tabs = {row['tab_id'] for row in status.get('tabs', []) if row.get('closed') is True}
        for task_id, tab_id in list(getattr(resource, 'console_tasks', {}).items()):
            if tab_id in closed_tabs or status.get('context_closed') is True:
                current=actor.store.get(task_id)
                if current and current['state']=='waiting_human':
                    actor.store.complete_waiting(task_id, actor.owner_id, actor.generation,
                        result={'official_tab_closed': True, 'account_pause_changed': False})
                resource.console_tasks.pop(task_id)
        if status.get('closed') is True or status.get('context_closed') is True:
            for task_id in list(resource.manual_tasks):
                actor.store.complete_waiting(task_id, actor.owner_id, actor.generation,
                    result={'window_closed': True, 'identity_verified': False})
                resource.manual_tasks.pop(task_id)
            resource.shutdown()
            resource.headless = True


def _has_pending_original_work(store, account_uuid):
    """Idle checks need live original work, not full historical receipt bodies."""
    from .publication_autonomous_reconciliation import unresolved
    with store._db() as db:
        return bool(unresolved(store, db, account_uuid,
            ('queued', 'running', 'paused', 'waiting_human', 'outcome_unknown')))


def _host(account_key):
    runtime = _runtime()
    context = runtime.resolve(account_key, require_healthy=False)
    resource = AccountBrowserResource(context, runtime)
    store = _store()
    reconciliation_auth=store.pending_reconciliation_authorization(context.account_uuid)
    acquirer=(lambda account,binding,owner:store.acquire_reconciliation_owner(account,binding,owner,reconciliation_auth)) if reconciliation_auth else None
    if acquirer is None:
        from .publication_verification_recovery import acquire_owner as acquire_verification_owner, needs_owner
        if needs_owner(store,context.account_uuid):
            acquirer=lambda account,binding,owner:acquire_verification_owner(store,account,binding,owner)
    actor = BrowserControlActor(store, context.account_uuid, binding_version(context),
        f'backend:{os.getpid()}:{uuid.uuid4().hex}',
        {'maintenance': _maintenance, 'publish': _publish, 'manual': _manual,
         'recovery': _recovery, 'read': _adapter_read, 'official_console': _official_console,
         'publication_reconcile':_publication_reconcile,
         'publication_verify':_publication_verify,
         'publication_comment_settlement':_publication_comment_settlement},
        admission=_admission, context=resource,owner_acquirer=acquirer)
    exit_error = ''
    try:
        actor.start()
        from .paused_browser_claims import install as install_paused_claim_guard
        install_paused_claim_guard(actor, resource)
        idle_since = time.monotonic()
        # Keep manual tabs and the shared context alive; all work remains serial.
        while True:
            _poll_manual_windows(actor, resource)
            from .window_supervision import synchronize, keep_idle_window
            synchronize(resource, actor)
            from .manual_window_visibility import reconcile_closed_displays
            reconcile_closed_displays(store, context.account_uuid)
            if resource.session and resource.manual_tasks:
                from .clear_feed_resume import poll as poll_clear_feed
                try:
                    poll_clear_feed(actor, resource)
                except Exception:
                    # Probe/DB failures never mean the verification page is clear.
                    from loguru import logger
                    logger.exception('Clear-feed handback could not be confirmed')
            from .publication_autonomous_reconciliation import queue_continuation
            queue_continuation(store,context.account_uuid)
            from .publication_verification_recovery import queue_due, project_verified_works
            project_verified_works(store,context.account_uuid)
            queue_due(store,resource.context,actor.binding_version)
            current_context = replace(resource.context,
                profile=runtime.profiles.get(account_key), binding=runtime.bindings.get(account_key))
            migration = _release_changed_binding(actor, resource, current_context)
            if migration == 'waiting_original':
                time.sleep(1)
                continue
            if migration == 'released':
                return  # Next backend scan starts a fresh generation/binding.
            result = actor.run_next()
            if result is not None and result['state'] != 'queued':
                idle_since = time.monotonic()
            if (result is None and resource.session and not resource.manual_tasks and not resource.console_tasks
                    and time.monotonic() - idle_since >= 120 and not keep_idle_window(resource)):
                # Failed startup has no worker. An idle RPC would throw and strand
                # the owner even though the failed command already has a receipt.
                tabs = [] if getattr(resource.session, '_proc', object()) is None else resource.session.list_tabs()
                if not any(tab.get('role') in {'manual', 'official_console'} and not tab.get('closed') for tab in tabs):
                    if not _has_pending_original_work(store, resource.account_uuid):
                        from .browser_host_retirement import retire_host
                        if not retire_host(actor,resource):
                            raise BrowserControlRejected('host_cleanup_unconfirmed','无法确认原worker已退出，保留控制权。')
                        return
            time.sleep(1 if result is None or result['state'] == 'queued' else 0.05)
    except BaseException as exc:
        exit_error = type(exc).__name__
        raise
    finally:
        try:
            from .browser_host_retirement import retire_host
            retire_host(actor,resource,error_type=exit_error)
        except Exception:
            # Missing cleanup proof keeps the fence; never claim a clean exit.
            from loguru import logger
            logger.exception('Browser host retirement could not be verified')
        finally:
            actor.stop_heartbeat()
            with _hosts_lock:
                _hosts.pop(context.account_uuid, None)


_last_pump_report = {'started': 0, 'blocked_accounts': []}


def pump_status():
    return dict(_last_pump_report)


def pump_pending():
    """Backend-only drain hook. UI/CLI must not call this to acquire a profile."""
    if not enabled():
        return 0
    store = _store()
    count = 0
    blocked = []
    for account in store.list_pending_accounts():
        account_uuid = account['account_id'] if isinstance(account, dict) else account
        if account_uuid.startswith('fanqie:'):
            continue  # Independent platform owner; never reconcile it as Douyin.
        profile = next((p for p in _runtime().profiles.list_active() if p.account_uuid == account_uuid), None)
        if profile is None:
            continue
        from .publication_verification_recovery import queue_due, release_previous_boot, has_unknown_publication, project_verified_works
        try:
            project_verified_works(store,account_uuid)
            if has_unknown_publication(store,account_uuid):
                current_context = _runtime().resolve(profile.account_key,require_healthy=False)
                queue_due(store,current_context,binding_version(current_context))
        except (BrowserControlRejected, OSError, ValueError, KeyError, TypeError):
            blocked.append(account_uuid)
            continue
        with _hosts_lock:
            if account_uuid in _hosts:
                continue
            from .browser_boot_recovery import read_owner,release_previous_boot_owner
            owner = read_owner(store,account_uuid)
            if owner and owner['state'] != 'released':
                # A stale heartbeat alone is insufficient. Only a proven
                # prior-boot, idle owner can be released with its audit intact.
                if not (release_previous_boot_owner(store,account_uuid,owner)
                        or release_previous_boot(store,account_uuid,owner)):
                    if store.clock() - owner['heartbeat'] > store.owner_ttl:
                        blocked.append(account_uuid)
                    continue
            with store._db() as db:
                if not db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state='queued' LIMIT 1", (account_uuid,)).fetchone():
                    continue
            from .browser_host_retirement import retry_allowed
            if not retry_allowed(store,account_uuid):
                blocked.append(account_uuid)
                continue
            context = next((p for p in _runtime().profiles.list_active() if p.account_uuid == account_uuid), None)
            if context is None:
                continue
            thread = threading.Thread(target=_host, args=(context.account_key,), daemon=True,
                name='AccountBrowser-' + context.account_key)
            _hosts[account_uuid] = thread
            thread.start()
            count += 1
    global _last_pump_report
    _last_pump_report = {'started': count, 'blocked_accounts': blocked}
    return count


def _await(command, timeout=10800):
    store = _store()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = store.get(command['command_id'])
        if (current['state'] in {'succeeded', 'failed', 'outcome_unknown', 'waiting_human'}
                or (current['state'] == 'paused' and current.get('error_code'))):
            return current
        time.sleep(0.2)
    raise BrowserControlRejected('command_wait_timeout', '原请求仍保留原ID，未重派；请查询管控状态。')


def managed_maintenance(service, account_key, mode, options):
    """Existing schedulers keep their original run/quotas; business runs on owner."""
    payload_options = dict(options)
    if payload_options.get('playback_options') is not None:
        payload_options['playback_options'] = asdict(payload_options['playback_options'])
    payload_options['research_keywords'] = list(payload_options['research_keywords']) if payload_options.get('research_keywords') else None
    command = _submit(account_key, 'maintenance', {'mode': mode, 'options': payload_options},
        'maintenance:' + uuid.uuid4().hex, 0)
    from src.scheduler.browser_task_tracking import attach
    attach(command, os.environ.get('ACCOUNT_BROWSER_CONTROL_DB', DB))
    result = _await(command)
    if not isinstance(result.get('result'), dict) or 'maintenance_result' not in result['result']:
        raise BrowserControlRejected(result.get('error_code') or result['state'], '后台任务已保留原管控ID，请查看原记录。')
    from .maintenance import AccountMaintenanceResult
    return AccountMaintenanceResult(**result['result']['maintenance_result'])


def managed_recovery(account_key):
    from .publication_two_run_authorization import registered_recovery
    context = _runtime().resolve(account_key, require_healthy=False)
    extra = registered_recovery(account_key)
    if extra is None:
        payload, key = {}, 'recovery:' + uuid.uuid4().hex
    else:
        reference, value = extra
        payload = {'quota_authorization': reference, 'identity_probe_only': True}
        key = value['idempotency_keys']['recovery']
    command = _submit(account_key, 'recovery', payload, key, 300)
    result = _await(command)
    if result['state'] != 'succeeded':
        raise BrowserControlRejected(result.get('error_code') or result['state'], '原身份核验未能完成，保留原请求。')
    context = _runtime().resolve(account_key, require_healthy=False)
    from .runtime import RuntimeIdentityCheck
    data = result['result']
    return RuntimeIdentityCheck(data['healthy'], data['status'], data['message'], context.binding,
        navigation_evidence=data.get('navigation_evidence'))
