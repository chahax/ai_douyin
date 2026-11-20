"""Opt-in instance-level locator for one existing publication and its auto reads.

No queue, upload, publication, account recovery or previous-publication repair
is performed here. Only the named owner's discover RPC is replaced. Original
BorrowedSession guards, publication handlers, detail checks and settlement stay
in place. Other RPCs and other commands retain their original return values.
"""
from datetime import datetime
import hashlib
import json
import math
import marshal
import os
from pathlib import Path
import re
import threading
import types
import uuid

from . import publication_claim_hot_bridge_v1 as bridge
from .publication_discovery_diagnostic_v1 import sanitize_discovery, _clean_string

ROOT = bridge.ROOT
ARM = ROOT / 'data/publication_locator_provider_v1/ARM.json'
POLICIES = ROOT / 'data/publication_locator_provider_v1/policies'
LOCATOR = ROOT / 'src/shared/original_work_locator_v1.py'
SOURCE_PATHS = dict(provider=Path(__file__).resolve(), locator=LOCATOR,
    core=ROOT/'src/operations_accounts/browser_control.py',
    recovery=ROOT/'src/operations_accounts/publication_verification_recovery.py',
    app=ROOT/'src/web/app.py', runtime=bridge.HOST_PATH,
    browser_session=ROOT/'src/platform_adapter/browser_session.py')


def _read(ref):
    value = bridge._read(ref)
    if not isinstance(value, dict):
        raise ValueError('locator_provider_object_required')
    return value


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _sources(refs):
    _require(set(refs) == set(SOURCE_PATHS), 'locator_provider_sources_required')
    for name, path in SOURCE_PATHS.items():
        _require(refs[name] == bridge.reference(path), 'locator_provider_source_changed:' + name)


def _load_locator(ref):
    raw = LOCATOR.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'locator_provider_loaded_source_changed')
    module = types.ModuleType('src.shared._reviewed_original_work_locator')
    module.__file__, module.__package__ = str(LOCATOR), 'src.shared'
    exec(compile(raw, str(LOCATOR), 'exec'), module.__dict__)
    function = module.discover_original_work
    return function, dict(source=ref, code_sha256=hashlib.sha256(marshal.dumps(function.__code__)).hexdigest(),
                          canonical_module_replaced=False)


def _candidate_reader(candidate_id):
    from src.services.fanqie_h3_candidate_v1 import CandidateLedger
    from src.services.fanqie_review_service import CLOSED_LOOP_DB_PATH
    return CandidateLedger(CLOSED_LOOP_DB_PATH).get(candidate_id)


def _publisher(command):
    return {k: command[k] for k in ('command_id', 'account_id', 'binding_version', 'kind',
                                   'idempotency_key', 'payload', 'request_sha', 'priority', 'created_at')}


def prepare_scope(spec_ref, output_directory, *, store=None, runtime=None, candidate_reader=None):
    """RO bind an already queued full publication; writes a new scope artifact."""
    from . import browser_control_runtime as managed
    spec = _read(spec_ref)
    _require(set(spec) == {'schema', 'account_key', 'account_uuid', 'candidate_id', 'publish_command_id',
        'media', 'expected_duration_seconds', 'authority_reference', 'user_statement', 'sources'}
        and spec['schema'] == 'publication_locator_provider_spec/v1', 'locator_provider_spec_invalid')
    _sources(spec['sources'])
    _read(spec['authority_reference'])
    _require(isinstance(spec['user_statement'], str) and spec['user_statement'].strip()
        and type(spec['expected_duration_seconds']) in (int, float)
        and math.isfinite(spec['expected_duration_seconds']) and spec['expected_duration_seconds'] > 0,
        'locator_provider_exact_authority_and_duration_required')
    store = store if store is not None else managed._store()
    runtime = runtime if runtime is not None else managed._runtime()
    reader = candidate_reader or _candidate_reader
    candidate = reader(spec['candidate_id'])
    frozen, prepared = json.loads(candidate['frozen_json']), json.loads(candidate['prepared_json'] or '{}')
    command = store.get(spec['publish_command_id'])
    context = runtime.resolve(spec['account_key'], require_healthy=False)
    _require(command and command['kind'] == 'publish' and command['state'] == 'queued'
        and command['owner_id'] is None and command['generation'] is None
        and command['account_id'] == spec['account_uuid'] == context.account_uuid == frozen['account']['account_uuid']
        and command['binding_version'] == frozen['account']['binding_version'] == managed.binding_version(context)
        and candidate['command_id'] == command['command_id'] and frozen['media'] == spec['media']
        and command['payload']['video_sha256'] == spec['media']['sha256']
        and command['payload']['request'] == prepared.get('request')
        and command['payload']['authorization'] == prepared.get('authorization'), 'locator_provider_existing_full_publication_mismatch')
    _require(bridge.reference(spec['media']['path']) == spec['media'], 'locator_provider_media_changed')
    authorization = _read(prepared['authorization'])
    _require(authorization.get('publish_authorized') is True and authorization.get('candidate_id') == spec['candidate_id']
        and authorization.get('media') == spec['media'], 'locator_provider_original_publication_authority_changed')
    directory = Path(output_directory).resolve()
    _require(directory.is_relative_to(ROOT/'data') and not directory.exists(), 'locator_provider_new_scope_directory_required')
    value = dict(schema='publication_locator_provider_scope/v1', specification=spec_ref, publisher=_publisher(command),
        candidate_id=spec['candidate_id'], candidate_subject_sha256=bridge._digest(dict(frozen=frozen, prepared=prepared,
            task_id=candidate['task_id'], video_job_id=candidate['video_job_id'])),
        account_key=spec['account_key'], account_uuid=spec['account_uuid'], binding_version=command['binding_version'],
        platform_identity_key=context.binding.platform_identity_key, media=spec['media'],
        expected_duration_seconds=spec['expected_duration_seconds'], publication_authorization=prepared['authorization'],
        sources=spec['sources'], max_original_auto_verifications=3, queued_new_tasks=0, previous_publication_repair=False)
    directory.mkdir(parents=True)
    return bridge._write_once(directory/'SCOPE.json', value)


def _scope(ref):
    scope = _read(ref)
    _require(scope.get('schema') == 'publication_locator_provider_scope/v1'
        and scope.get('max_original_auto_verifications') == 3 and scope.get('previous_publication_repair') is False,
        'locator_provider_scope_changed')
    spec = _read(scope['specification'])
    _sources(scope['sources'])
    _require(spec['sources'] == scope['sources'] and spec['candidate_id'] == scope['candidate_id']
        and spec['publish_command_id'] == scope['publisher']['command_id'] and spec['media'] == scope['media'],
        'locator_provider_frozen_target_changed')
    _read(spec['authority_reference'])
    _read(scope['publication_authorization'])
    return scope


def prepare_runtime(scope_ref, config_ref, output_directory):
    """RO owner preflight and new PLAN; does not register a policy or ARM."""
    scope, config = _scope(scope_ref), _read(config_ref)
    _require(set(config) == {'schema', 'backend_pid', 'backend_create_time', 'owner_id', 'generation',
        'account_key', 'account_uuid', 'binding_version', 'browser_db', 'sources'}
        and config['schema'] == 'publication_locator_provider_runtime/v1', 'locator_provider_runtime_config_invalid')
    _sources(config['sources'])
    _require(config['sources'] == scope['sources'] and bridge._process(config['backend_pid']) == config['backend_create_time']
        and config['owner_id'].startswith('backend:' + str(config['backend_pid']) + ':')
        and config['account_uuid'] == scope['account_uuid'] and config['account_key'] == scope['account_key']
        and config['binding_version'] == scope['binding_version'], 'locator_provider_original_owner_changed')
    with bridge._ro(config['browser_db']) as db:
        row = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (scope['account_uuid'],)).fetchone()
        command = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (scope['publisher']['command_id'],)).fetchone()
    _require(row and row['owner_id'] == config['owner_id'] and row['generation'] == config['generation']
        and row['binding_version'] == config['binding_version'] and row['state'] == 'active'
        and command and _publisher(bridge._parsed(command)) == scope['publisher'] and command['state'] == 'queued',
        'locator_provider_live_owner_or_queued_target_changed')
    directory = Path(output_directory).resolve()
    _require(directory.is_relative_to(ROOT/'data') and not directory.exists(), 'locator_provider_new_runtime_directory_required')
    directory.mkdir(parents=True)
    return bridge._write_once(directory/'PLAN.json', dict(schema='publication_locator_provider_plan/v1', scope=scope_ref,
        config=config_ref, evidence_directory=str(directory/'observations'), installed=False, new_queue_entries=0))


def register_policy(plan_ref):
    """Explicit metadata admission policy; Root calls this separately from prepare."""
    plan = _read(plan_ref)
    scope = _scope(plan['scope'])
    cid = scope['publisher']['command_id']
    _require(re.fullmatch(r'[a-f0-9]{32}', cid) is not None, 'locator_provider_native_command_id_required')
    POLICIES.mkdir(parents=True, exist_ok=True)
    policy = dict(schema='publication_locator_provider_policy/v1', publish_command_id=cid,
                  account_uuid=scope['account_uuid'], plan=plan_ref)
    bridge._write_once(POLICIES/(cid+'.required.json'), dict(policy, schema='publication_locator_provider_required/v1'))
    return bridge._write_once(POLICIES/(cid+'.json'), policy)


def _origin_id(command):
    return command['command_id'] if command['kind'] == 'publish' else (
        command.get('payload', {}).get('original_command_id') if command['kind'] == 'publication_verify' else None)


def _command_matches(command, scope):
    if command['account_id'] != scope['account_uuid'] or command['binding_version'] != scope['binding_version']:
        return False
    if command['kind'] == 'publish':
        return _publisher(command) == scope['publisher']
    payload = command.get('payload') or {}
    attempt = payload.get('attempt')
    return (command['kind'] == 'publication_verify' and type(attempt) is int and 1 <= attempt <= 3
        and payload.get('original_command_id') == scope['publisher']['command_id']
        and command['idempotency_key'] == 'publication-verify:' + scope['publisher']['command_id'] + ':' + str(attempt)
        and not any(k in payload for k in ('explicit_recheck', 'discovery_diagnostic', 'locator_provider_repair')))


def provider_ready(command, owner_id, generation):
    """Pure file/ref gate: unrelated CID has no policy and retains old behavior."""
    try:
        cid = _origin_id(command)
        if not isinstance(cid, str) or not re.fullmatch(r'[a-f0-9]{32}', cid):
            return True
        policy_path = POLICIES/(cid+'.json')
        marker_path = POLICIES/(cid+'.required.json')
        if not policy_path.exists() and not marker_path.exists():
            return True
        marker = _read(bridge.reference(marker_path))
        policy = _read(bridge.reference(policy_path))
        plan = _read(policy['plan'])
        scope, config = _scope(plan['scope']), _read(plan['config'])
        _sources(config['sources'])
        ready = _read(bridge.reference(Path(policy['plan']['path']).parent/'ACTOR_PROVIDER_READY.json'))
        return bool(policy.get('schema') == 'publication_locator_provider_policy/v1'
            and marker == dict(policy, schema='publication_locator_provider_required/v1')
            and policy['publish_command_id'] == scope['publisher']['command_id'] == cid
            and policy['account_uuid'] == scope['account_uuid'] and _command_matches(command, scope)
            and ready.get('schema') == 'publication_locator_provider_ready/v1'
            and ready.get('plan') == policy['plan'] and ready.get('scope') == plan['scope']
            and ready.get('publish_command_id') == cid
            and ready.get('backend_pid') == config['backend_pid']
            and ready.get('backend_create_time') == config['backend_create_time']
            and ready.get('loaded_locator', {}).get('source') == scope['sources']['locator']
            and ready.get('owner_id') == config['owner_id'] == owner_id
            and ready.get('generation') == config['generation'] == generation
            and ready.get('ensure_session_hook_installed') is True and ready.get('instance_discover_only') is True)
    except Exception:
        return False


class _Facade:
    def __init__(self, provider, owner, previous, ctx, allowed):
        self.provider, self.owner, self.previous, self.ctx, self.allowed = provider, owner, previous, ctx, allowed

    def cmd(self, action, **kwargs):
        self.provider.guard(self.ctx, self.owner)
        tab = kwargs.get('tab_id')
        if tab not in self.allowed:
            self.provider.reject('locator_provider_tab_outside_original_read')
        return self.previous(action, **kwargs)


class _Popups:
    def __init__(self, provider, owner, previous, ctx, main):
        self.provider, self.owner, self.previous, self.ctx, self.main = provider, owner, previous, ctx, main
        self.baseline, self.new, self.proven = None, set(), set()
        self.nonce = uuid.uuid4().hex
        self.origin = None

    def _eval(self, tab, script):
        self.provider.guard(self.ctx, self.owner)
        return self.previous('evaluate', tab_id=tab, selector='html', js=script, index=0).get('value')

    def snapshot(self):
        self.provider.guard(self.ctx, self.owner)
        tabs = self.previous('list_tabs')['tabs']
        ids = {x['tab_id'] for x in tabs if not x.get('closed')}
        if self.baseline is None:
            self.baseline = ids
            value = self._eval(self.main, '()=>{const nonce='+json.dumps(self.nonce)+''';
                if(location.origin!=='https://creator.douyin.com')return {ready:false};
                const handler=e=>{if(e.isTrusted===true&&e.source!==null&&e.data?.__locator_provider_nonce===nonce&&
                    ['https://www.douyin.com','https://douyin.com','https://creator.douyin.com'].includes(e.origin))
                    window.__locatorProviderOpenerV1[nonce].received=true;};
                window.__locatorProviderOpenerV1??={};
                window.__locatorProviderOpenerV1[nonce]={received:false,handler};
                addEventListener('message',handler);return {ready:true,origin:location.origin};}''')
            if not value or value.get('ready') is not True:
                self.provider.reject('locator_provider_opener_probe_unavailable')
            self.origin = value['origin']
        self.new |= ids - self.baseline
        return [{'tab_id': x['tab_id'], 'url': x.get('url', ''), 'closed': bool(x.get('closed'))} for x in tabs]

    def page(self, tab_id):
        if len(self.new) != 1 or tab_id not in self.new:
            self.provider.reject('locator_provider_popup_not_unique_or_owned')
        tabs = self.previous('list_tabs')['tabs']
        row = next((x for x in tabs if x['tab_id'] == tab_id and not x.get('closed')), None)
        if not row or row.get('role') != 'unclaimed':
            self.provider.reject('locator_provider_popup_role_not_native')
        sent = self._eval(tab_id, '()=>{if(!window.opener)return false;window.opener.postMessage('
            +json.dumps({'__locator_provider_nonce': self.nonce})+','+json.dumps(self.origin)+');return true;}')
        received = False
        for _ in range(4):
            value = self._eval(self.main, '()=>window.__locatorProviderOpenerV1?.['+json.dumps(self.nonce)+']?.received===true')
            if value is True:
                received = True
                break
        if sent is not True or not received:
            self.provider.reject('locator_provider_popup_opener_unconfirmed')
        self.proven.add(tab_id)
        from src.platform_adapter.browser_session import Page
        return Page(_Facade(self.provider, self.owner, self.previous, self.ctx, {tab_id}), tab_id)

    def close(self, tab_id):
        self.provider.guard(self.ctx, self.owner)
        if len(self.new) != 1 or tab_id not in self.new or tab_id not in self.proven:
            self.provider.reject('locator_provider_popup_close_not_owned')
        return self.previous('close_tab', tab_id=tab_id)

    def cleanup(self):
        if self.origin is None:
            return
        try:
            self._eval(self.main, '()=>{const key='+json.dumps(self.nonce)+''';const p=window.__locatorProviderOpenerV1?.[key];
                if(p){removeEventListener('message',p.handler);delete window.__locatorProviderOpenerV1[key];}return true;}''')
        except Exception:
            pass


class _Provider:
    def __init__(self, actor, resource, namespace, plan_ref, plan, scope, config, locator):
        self.actor, self.resource, self.namespace = actor, resource, namespace
        self.plan_ref, self.plan, self.scope, self.config, self.locator = plan_ref, plan, scope, config, locator
        self.previous_ensure = resource.ensure_session
        self.previous_claim = actor.store.claim_next
        self.sessions = {}
        self.counts = {}
        self.found_ids = {}

    def reject(self, code):
        raise self.namespace['BrowserControlRejected'](code, '原发布的定位器作用域已变化；保留原记录。')

    def guard(self, ctx, owner):
        self.actor._assert_thread()
        self.actor._check_owner()
        if (self.namespace['active_context']() is not ctx or ctx.actor is not self.actor or ctx.resource is not self.resource
                or self.resource.session is not owner or self.actor.owner_id != self.config['owner_id']
                or self.actor.generation != self.config['generation'] or ctx.binding_version != self.scope['binding_version']
                or not _command_matches(ctx.command, self.scope)):
            self.reject('locator_provider_context_owner_or_original_changed')
        try:
            _sources(self.scope['sources'])
        except Exception:
            self.reject('locator_provider_source_changed')
        ctx.check_dispatch()

    def evidence(self, ctx, kind, value):
        key = (ctx.task_id, kind)
        self.counts[key] = self.counts.get(key, 0) + 1
        path = Path(self.plan['evidence_directory'])/ctx.task_id/(kind+'_%03d.json' % self.counts[key])
        return bridge._write_once(path, dict(schema='publication_locator_provider_observation/v1',
            plan=self.plan_ref, command_id=ctx.task_id, original_publish_id=self.scope['publisher']['command_id'],
            owner_id=self.actor.owner_id, generation=self.actor.generation, observed=value))

    def safe_evidence(self, ctx, kind, value):
        try:
            return self.evidence(ctx, kind, value)
        except Exception as error:
            bridge._record_failure(Path(self.plan['evidence_directory']), 'provider_observation', error)
            return None

    def _source(self, ctx):
        from . import publication_verification_recovery as core
        if ctx.command['kind'] == 'publication_verify':
            original, _ = core.inputs(ctx.actor.store, ctx.command, ctx.resource.context)
            if _publisher(original) != self.scope['publisher']:
                self.reject('locator_provider_auto_original_mismatch')
            return ctx.command['payload']['source']
        identity = dict(platform_identity_key=self.scope['platform_identity_key'], video_sha256=self.scope['media']['sha256'])
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        lock_path = ROOT/'data/publish_runs'/(key+'.submitted.json')
        lock = _read(bridge.reference(lock_path))
        journal_path = Path(lock['journal']).resolve()
        if journal_path.parent != (ROOT/'data/publish_runs').resolve() or not journal_path.name.startswith(key+'.'):
            self.reject('locator_provider_original_journal_path_mismatch')
        if journal_path.stat().st_size > 16 * 1024 * 1024:
            self.reject('locator_provider_original_journal_too_large')
        rows = [json.loads(line) for line in journal_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        prepared = [x for x in rows if x.get('stage') == 'prepared']
        request = self.scope['publisher']['payload']['request']
        tags = [x.strip().lstrip('#') for x in request.get('hashtags', []) if x.strip().lstrip('#')]
        if (lock.get('status') != 'submission_started' or len(prepared) != 1
                or prepared[0].get('account_uuid') != self.scope['account_uuid']
                or prepared[0].get('account') != self.scope['account_key']
                or prepared[0].get('platform_identity_key') != self.scope['platform_identity_key']
                or prepared[0].get('video_sha256') != self.scope['media']['sha256']
                or any(prepared[0].get(k) != request.get(k) for k in ('title', 'description', 'visibility', 'video_path'))
                or prepared[0].get('hashtags') != tags
                or prepared[0].get('ai_declaration_required') != request.get('ai_generated', True)
                or prepared[0].get('fiction_declaration_required') != request.get('fictional_story', True)
                or datetime.fromisoformat(prepared[0]['at_bjt']).timestamp() < self.scope['publisher']['created_at'] - 5
                or datetime.fromisoformat(prepared[0]['at_bjt']).timestamp() > __import__('time').time() + 5
                or sum(x.get('stage') == 'submission_started' for x in rows) != 1
                or sum(x.get('stage') == 'publish_click_dispatching' for x in rows) != 1
                or sum(x.get('stage') == 'publish_click_returned' for x in rows) != 1):
            self.reject('locator_provider_this_publish_click_unproven')
        from .publication_reconciliation import _active_ai_source
        if not _active_ai_source(rows):
            self.reject('locator_provider_original_ai_declaration_unproven')
        return dict(journal=bridge.reference(journal_path), submission_lock=bridge.reference(lock_path))

    def _duration(self, ctx, owner, previous, tab, kwargs):
        try:
            from src.platform_adapter.browser_session import Page
            page = Page(_Facade(self, owner, previous, ctx, {tab}), tab)
            post_id = kwargs.get('post_id')
            if not isinstance(post_id, str) or not re.fullmatch(r'\d{10,24}', post_id):
                self.reject('locator_provider_duration_post_id_invalid')
            value = page.locator('html').evaluate('()=>{const post_id='+json.dumps(post_id)+r''';
                const u=new URL(location.href),vs=Array.from(document.querySelectorAll('video'));
                return {origin:u.origin,path:u.pathname,post_id,video_count:vs.length,
                    seconds:vs.length===1&&Number.isFinite(vs[0].duration)?vs[0].duration:null};
            }''')
            seconds = value.get('seconds')
            valid = (value.get('origin') == 'https://www.douyin.com' and value.get('path') == '/video/'+str(kwargs.get('post_id'))
                and value.get('video_count') == 1 and type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0
                and self.found_ids.get(ctx.task_id) == kwargs.get('post_id'))
            self.evidence(ctx, 'DURATION', dict(native_player_seconds=seconds if valid else None,
                expected_seconds=self.scope['expected_duration_seconds'], tolerance_seconds=2,
                matches_expected=abs(seconds-self.scope['expected_duration_seconds']) <= 2 if valid else None,
                verified_numeric_duration=valid, source='same_original_public_detail_html_video_duration',
                changes_core_verification=False))
        except Exception as error:
            try:
                self.evidence(ctx, 'DURATION', dict(verified_numeric_duration=False, error_type=type(error).__name__))
            except Exception:
                pass

    def attach(self, owner):
        key = id(owner)
        if key in self.sessions:
            if owner.cmd is not self.sessions[key][2]:
                self.reject('locator_provider_owner_cmd_binding_changed')
            return owner
        previous = owner.cmd
        def cmd(action, **kwargs):
            ctx = self.namespace['active_context']()
            targeted = bool(ctx and _origin_id(ctx.command) == self.scope['publisher']['command_id'])
            if not targeted or action not in {'discover_published_work', 'inspect_published_video'}:
                return previous(action, **kwargs)
            self.guard(ctx, owner)
            tab = kwargs.get('tab_id')
            if not isinstance(tab, str) or not tab:
                self.reject('locator_provider_original_tab_required')
            if action != 'discover_published_work':
                result = previous(action, **kwargs)  # Original return value is untouched.
                self._duration(ctx, owner, previous, tab, kwargs)
                return result
            if kwargs.get('title') != self.scope['publisher']['payload']['request']['title']:
                self.reject('locator_provider_original_title_changed')
            source = self._source(ctx)
            from src.platform_adapter.browser_session import Page
            page = Page(_Facade(self, owner, previous, ctx, {tab}), tab)
            scope = dict(account_uuid=self.scope['account_uuid'], owner_id=self.actor.owner_id,
                         generation=self.actor.generation, command_id=ctx.task_id, tab_id=tab)
            popups = _Popups(self, owner, previous, ctx, tab)
            try:
                result = self.locator(page, kwargs['title'], guard=lambda: self.guard(ctx, owner), scope=scope,
                                      popup_access=popups)
            except Exception as error:
                self.safe_evidence(ctx, 'LOCATOR_FAILURE', dict(error_type=type(error).__name__,
                    reason_code=getattr(error, 'code', ''), popup_count=len(popups.new),
                    popup_opener_proven=bool(popups.proven), original_source=source))
                raise
            finally:
                popups.cleanup()
            self.guard(ctx, owner)
            sanitized = sanitize_discovery(result)
            sanitized['restriction_warning'] = _clean_string(json.dumps(result.get('restriction_warning'), ensure_ascii=False))
            diagnostic = result.get('diagnostic') or {}
            card = diagnostic.get('card_binding') or {}
            native = diagnostic.get('native_modal_identity') or {}
            sanitized['host_locator'] = dict(locator=_clean_string(diagnostic.get('locator', ''), 80),
                review_status_evaluated=diagnostic.get('review_status_evaluated') is True,
                card_status=_clean_string(card.get('card_status', ''), 80),
                binding_ready=card.get('ready') is True, binding_reason=_clean_string(card.get('reason', ''), 100),
                restriction_detail_available=card.get('restriction_detail_available') is True,
                cover_click_dispatched=diagnostic.get('cover_click_dispatched') is True,
                new_popup_count=diagnostic.get('new_popup_count'), popup_opener_proven=bool(popups.proven),
                native_modal_identity_verified=native.get('verified') is True,
                native_modal_identity_reason=_clean_string(native.get('reason', ''), 100))
            sanitized['original_source'] = source
            self.safe_evidence(ctx, 'DISCOVERY', sanitized)
            if result.get('verified') is True:
                self.found_ids[ctx.task_id] = result.get('post_id')
            return {'status': 'ok', 'evidence': result}
        cmd._publication_locator_provider = self.plan_ref
        owner.cmd = cmd
        self.sessions[key] = (owner, previous, cmd)
        return owner

    def install(self):
        def ensure_session():
            self.actor._assert_thread()
            self.actor._check_owner()
            owner = self.previous_ensure()
            self.attach(owner)
            return owner  # Preserve the original object, not a facade.
        self.resource.ensure_session = ensure_session
        self.ensure_wrapper = ensure_session
        if self.resource.session is not None:
            self.attach(self.resource.session)
        def claim(*args, **kwargs):
            if args[:1] == (self.scope['account_uuid'],):
                command = self.actor.store.get(self.scope['publisher']['command_id'])
                if command and command['state'] == 'queued' and not provider_ready(command, args[2], args[3]):
                    kinds = kwargs.get('kinds')
                    kwargs['kinds'] = tuple(k for k in (kinds if kinds is not None else
                        ('manual', 'recovery', 'read', 'official_console')) if k not in {'publish', 'publication_verify'})
            return self.previous_claim(*args, **kwargs)
        self.actor.store.claim_next = claim
        self.claim_wrapper = claim

    def restore(self):
        if self.resource.ensure_session is getattr(self, 'ensure_wrapper', None):
            self.resource.ensure_session = self.previous_ensure
        if self.actor.store.claim_next is getattr(self, 'claim_wrapper', None):
            self.actor.store.claim_next = self.previous_claim
        for owner, previous, wrapper in self.sessions.values():
            if owner.cmd is wrapper:
                owner.cmd = previous


def install_if_armed():
    if not ARM.is_file():
        return {'status': 'not_armed'}
    directory = None
    try:
        arm = json.loads(ARM.read_text(encoding='utf-8'))
        _require(arm.get('schema') == 'publication_locator_provider_arm/v1' and set(arm) == {'schema', 'plan'}, 'locator_provider_arm_invalid')
        arm_ref = bridge.reference(ARM)
        plan = _read(arm['plan']); scope = _scope(plan['scope']); config = _read(plan['config'])
        directory = Path(arm['plan']['path']).parent
        _sources(config['sources'])
        if os.getpid() != config['backend_pid'] or bridge._process(os.getpid()) != config['backend_create_time']:
            return {'status': 'different_process_no_install'}
        if (directory/'ACTOR_PROVIDER_READY.json').exists():
            _require(_read(bridge.reference(directory/'ACTOR_PROVIDER_READY.json')).get('plan') == arm['plan'],
                     'locator_provider_existing_ready_changed')
            return {'status': 'actor_install_already_recorded'}
        matches = [t._target.__globals__ for t in threading.enumerate()
            if t.name == 'AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t, '_target', None), '__name__', '') == '_host'
            and Path(t._target.__code__.co_filename).resolve() == bridge.HOST_PATH
            and getattr(t, '_args', ()) == (config['account_key'],)]
        _require(len(matches) == 1, 'locator_provider_original_thread_not_unique')
        namespace = matches[0]; previous_poll = namespace['_poll_manual_windows']
        if getattr(previous_poll, '_publication_locator_plan', None) == arm['plan']:
            return {'status': 'callback_already_registered'}
        locator, loaded_proof = _load_locator(scope['sources']['locator'])
        def poll(actor, resource):
            if actor.account_id != config['account_uuid'] or actor.owner_id != config['owner_id'] or actor.generation != config['generation']:
                return previous_poll(actor, resource)
            provider = None
            try:
                actor._assert_thread(); actor._check_owner()
                _require(bridge.reference(ARM) == arm_ref and _read(arm['plan']) == plan, 'locator_provider_arm_changed')
                _scope(plan['scope']); _sources(config['sources'])
                if actor._stack or resource.manual_tasks or getattr(resource, 'console_tasks', {}):
                    return previous_poll(actor, resource)
                _require(actor.binding_version == scope['binding_version'] and resource.account_uuid == scope['account_uuid']
                    and Path(actor.store.path).resolve() == Path(config['browser_db']).resolve(), 'locator_provider_original_actor_changed')
                provider = _Provider(actor, resource, namespace, arm['plan'], plan, scope, config, locator)
                provider.install()
                bridge._write_once(directory/'ACTOR_PROVIDER_READY.json', dict(schema='publication_locator_provider_ready/v1',
                    plan=arm['plan'], scope=plan['scope'], owner_id=actor.owner_id, generation=actor.generation,
                    actor_thread_id=threading.get_ident(), backend_pid=os.getpid(), backend_create_time=config['backend_create_time'],
                    ensure_session_hook_installed=True, instance_discover_only=True, owner_session_wrapped_when_present=resource.session is not None,
                    publish_command_id=scope['publisher']['command_id'], loaded_locator=loaded_proof, no_new_commands=True))
                namespace['_poll_manual_windows'] = previous_poll
            except Exception as error:
                if provider is not None:
                    provider.restore()
                namespace['_poll_manual_windows'] = previous_poll
                bridge._record_failure(directory, 'provider_install', error)
            return previous_poll(actor, resource)
        poll._publication_locator_plan = arm['plan']
        namespace['_poll_manual_windows'] = poll
        bridge._write_once(directory/'UI_IMPORT_RECEIPT.json', dict(schema='publication_locator_provider_ui_import/v1',
            plan=arm['plan'], backend_pid=os.getpid(), callback_registered=True, actor_installed=False))
        return {'status': 'callback_registered_waiting_original_actor_tick'}
    except Exception as error:
        if directory:
            bridge._record_failure(directory, 'provider_ui', error)
        return {'status': 'refused', 'error_type': type(error).__name__}
