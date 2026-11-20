"""One explicit diagnostic of the existing publication discovery read.

The original publication, four known failed observations and the instrumented
source are frozen. This never uploads/publishes or resets automatic retry caps.
The optional runtime hook only observes one existing actor's named command.
"""
from dataclasses import replace, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from . import publication_claim_hot_bridge_v1 as bridge
from .browser_control import BrowserControlStore

ROOT = bridge.ROOT
ARM = ROOT / 'data/publication_discovery_diagnostic_v1/ARM.json'
PURPOSE = 'repair_original_publication_discovery_observability'
SCOPE = dict(operation=PURPOSE, max_new_diagnostics=1, automatic_attempt_limit_changed=False,
             upload_allowed=False, publish_click_allowed=False, comment_allowed=False, backfill_allowed=False)
MAX_SAMPLES = 4


def _self_ref():
    return bridge.reference(Path(__file__))


def _read(ref):
    value = bridge._read(ref)
    if not isinstance(value, dict):
        raise ValueError('diagnostic_object_reference_required')
    return value


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _services(store, runtime):
    from . import browser_control_runtime as managed
    return store or managed._store(), runtime or managed._runtime()


def _original_inputs(grant, store, runtime, candidate_reader):
    from . import publication_verification_recovery as core
    from .browser_control_runtime import binding_version
    context = runtime.resolve(grant['account_key'], require_healthy=False)
    original = store.get(grant['original_command_id'])
    _require(original and original['kind'] == 'publish' and original['state'] == 'outcome_unknown'
        and original['account_id'] == grant['account_uuid'] == context.account_uuid
        and original['binding_version'] == binding_version(context)
        and original['payload'].get('account_key') == grant['account_key']
        and original['payload'].get('video_sha256') == grant['media_sha256'], 'diagnostic_original_subject_changed')
    candidate = candidate_reader(grant['candidate_id'])
    frozen = json.loads(candidate['frozen_json'])
    _require(candidate['command_id'] == original['command_id'] and frozen['media']['sha256'] == grant['media_sha256']
        and frozen['account']['account_uuid'] == context.account_uuid, 'diagnostic_candidate_original_mismatch')
    with store._db() as db:
        prior = core._attempts(store, db, original['command_id'])
    _require(len(prior) == 4 and all(r['kind'] == 'publication_verify' and r['state'] == 'failed'
        and r['account_id'] == original['account_id'] and r['binding_version'] == original['binding_version']
        and r['payload']['original_command_id'] == original['command_id']
        and r['result'].get('status') == 'verification_pending' for r in prior), 'diagnostic_four_known_failed_observations_required')
    return context, original, prior, core._source(context, original)


def _grant(grant_ref):
    grant = _read(grant_ref)
    _require(set(grant) == {'schema', 'purpose', 'account_key', 'account_uuid', 'original_command_id',
        'candidate_id', 'media_sha256', 'authority_reference', 'user_statement', 'scope', 'instrumentation'},
        'diagnostic_grant_contract_invalid')
    _require(grant['schema'] == 'publication_discovery_diagnostic_grant/v1' and grant['purpose'] == PURPOSE
        and grant['scope'] == SCOPE and isinstance(grant['user_statement'], str) and grant['user_statement'].strip()
        and grant['instrumentation'] == _self_ref(), 'diagnostic_exact_repair_authority_required')
    _read(grant['authority_reference'])  # Existing instruction evidence, not a newly invented user report.
    return grant


def prepare(grant_ref, output_directory, *, store=None, runtime=None, candidate_reader=None):
    """Read-only scope checks and immutable request creation; does not enqueue."""
    grant = _grant(grant_ref)
    store, runtime = _services(store, runtime)
    if candidate_reader is None:
        from src.services.fanqie_h3_candidate_v1 import CandidateLedger
        from src.services.fanqie_review_service import CLOSED_LOOP_DB_PATH
        candidate_reader = CandidateLedger(CLOSED_LOOP_DB_PATH).get
    context, original, prior, source = _original_inputs(grant, store, runtime, candidate_reader)
    directory = Path(output_directory).resolve()
    _require(directory.is_relative_to(ROOT / 'data') and not directory.exists(), 'diagnostic_new_project_evidence_directory_required')
    request = dict(schema='publication_discovery_diagnostic_request/v1', grant=grant_ref, scope=SCOPE,
        purpose=PURPOSE, instrumentation=grant['instrumentation'], original=original, prior=prior, source=source,
        capture_directory=str(directory / 'capture'), max_samples=MAX_SAMPLES,
        account_key=context.account_key, account_uuid=context.account_uuid)
    # The operator statement itself cannot create another slot for this baseline.
    baseline = dict(original=bridge._digest(original), prior=[bridge._digest(x) for x in prior],
                    instrumentation=grant['instrumentation'])
    request['idempotency_key'] = 'publication-discovery-diagnostic:' + original['command_id'] + ':' + bridge._digest(baseline)
    directory.mkdir(parents=True)
    return bridge._write_once(directory / 'REQUEST.json', request)


def _request(ref):
    request = _read(ref)
    _require(request.get('schema') == 'publication_discovery_diagnostic_request/v1' and request.get('scope') == SCOPE
        and request.get('purpose') == PURPOSE and request.get('instrumentation') == _self_ref()
        and request.get('max_samples') == MAX_SAMPLES, 'diagnostic_frozen_request_changed')
    grant = _grant(request['grant'])
    _require(grant['instrumentation'] == request['instrumentation'] and grant['scope'] == SCOPE
        and grant['original_command_id'] == request['original']['command_id']
        and grant['account_uuid'] == request['account_uuid'] == request['original']['account_id']
        and grant['account_key'] == request['account_key'] == request['original']['payload']['account_key']
        and grant['media_sha256'] == request['original']['payload']['video_sha256'], 'diagnostic_frozen_grant_changed')
    prior = request['prior']
    _require(len(prior) == 4 and len({x['command_id'] for x in prior}) == 4
        and all(x['state'] == 'failed' and x['kind'] == 'publication_verify'
            and x['payload']['original_command_id'] == request['original']['command_id']
            and x['result'].get('status') == 'verification_pending' for x in prior), 'diagnostic_frozen_prior_invalid')
    baseline = dict(original=bridge._digest(request['original']), prior=[bridge._digest(x) for x in prior],
                    instrumentation=request['instrumentation'])
    _require(request['idempotency_key'] == 'publication-discovery-diagnostic:' + request['original']['command_id'] + ':' + bridge._digest(baseline)
        and Path(request['capture_directory']).resolve() == Path(ref['path']).parent / 'capture'
        and Path(request['capture_directory']).resolve().is_relative_to(ROOT / 'data'), 'diagnostic_once_key_or_capture_path_changed')
    return request


def enqueue(request_ref, *, store=None, runtime=None):
    """Once-only new diagnostic read, never replay of a publication submission."""
    from . import publication_verification_recovery as core
    from .browser_control_runtime import binding_version
    request = _request(request_ref)
    store, runtime = _services(store, runtime)
    context = runtime.resolve(request['account_key'], require_healthy=False)
    _require(store.get(request['original']['command_id']) == request['original']
        and context.account_uuid == request['account_uuid']
        and binding_version(context) == request['original']['binding_version'], 'diagnostic_original_changed_before_enqueue')
    for old in request['prior']:
        _require(store.get(old['command_id']) == old, 'diagnostic_prior_observation_changed')
    _require(core._source(context, request['original']) == request['source'], 'diagnostic_original_source_changed')
    with store._db() as db:
        existing = db.execute('SELECT command_id FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
                             (context.account_uuid, request['idempotency_key'])).fetchone()
        all_prior = core._attempts(store, db, request['original']['command_id'])
    expected_ids = {x['command_id'] for x in request['prior']}
    allowed_ids = expected_ids | ({existing[0]} if existing else set())
    _require({x['command_id'] for x in all_prior} == allowed_ids, 'diagnostic_other_observation_exists')
    payload = dict(account_uuid=context.account_uuid, account_key=context.account_key,
        original_command_id=request['original']['command_id'], original_snapshot_sha256=core._digest(request['original']),
        source=request['source'], attempt=len(request['prior']) + 1, discovery_diagnostic=request_ref)
    return store.submit(context.account_uuid, binding_version(context), 'publication_verify',
                        request['idempotency_key'], payload, priority=400)


def prepare_runtime(request_ref, claim_plan_ref, output_directory):
    """RO preflight for a second, single-handler callback; no ARM/install."""
    request = _request(request_ref)
    claim_plan = _read(claim_plan_ref)
    config = bridge._config(claim_plan['config'])
    original, queued = bridge._rows(config)
    payload = json.loads(queued['payload'])
    _require(payload.get('discovery_diagnostic') == request_ref
        and original['command_id'] == request['original']['command_id']
        and bridge._parsed(original) == request['original'], 'diagnostic_runtime_original_scope_changed')
    directory = Path(output_directory).resolve()
    _require(directory.is_relative_to(ROOT / 'data') and not directory.exists(), 'diagnostic_new_runtime_directory_required')
    value = dict(schema='publication_discovery_diagnostic_runtime/v1', request=request_ref, claim_plan=claim_plan_ref,
        config=claim_plan['config'], original_row_sha256=bridge._digest(original),
        queued_intent_sha256=_intent_sha(queued), verification_command_id=queued['command_id'],
        browser_actions=False, installed=False)
    directory.mkdir(parents=True)
    return bridge._write_once(directory / 'PLAN.json', value)


def _intent_sha(command):
    return bridge._digest({k: command[k] for k in ('command_id', 'account_id', 'binding_version', 'kind',
        'idempotency_key', 'payload', 'request_sha', 'priority', 'created_at')})


def handler_ready(command, owner_id, generation):
    """Pure-RO gate before core may claim this one diagnostic command.

    A UI import or successful claim-bridge install is insufficient. The private
    handler must already have its own exact actor-install/ready receipts.
    """
    try:
        request_ref = command['payload']['discovery_diagnostic']
        request = _request(request_ref)
        path = Path(request_ref['path']).parent / 'HANDLER_READY.json'
        ready = _read(bridge.reference(path))
        plan = _read(ready['runtime_plan'])
        installed = _read(ready['actor_install'])
        config = _read(plan['config'])
        bridge._sources(config)  # File hashes only; no DB/runtime/process query in this claim gate.
        return bool(ready.get('schema') == 'publication_discovery_diagnostic_handler_ready/v1'
            and ready.get('request') == plan['request'] == request_ref
            and ready.get('instrumentation') == request['instrumentation'] == _self_ref()
            and ready.get('command_id') == installed.get('command_id') == plan['verification_command_id'] == command['command_id']
            and ready.get('owner_id') == installed.get('owner_id') == config['owner_id'] == owner_id
            and ready.get('generation') == installed.get('generation') == config['generation'] == generation
            and ready.get('account_uuid') == command['account_id'] == config['account_id']
            and ready.get('binding_version') == command['binding_version'] == config['binding_version']
            and installed.get('backend_pid') == config['backend_pid']
            and installed.get('backend_create_time') == config['backend_create_time']
            and installed.get('plan') == ready['runtime_plan']
            and installed.get('only_private_single_cid_handler') is True
            and command['kind'] == 'publication_verify' and command['state'] == 'queued'
            and command['idempotency_key'] == request['idempotency_key']
            and command['payload'].get('source') == request['source']
            and command['payload'].get('original_snapshot_sha256') == bridge._digest(request['original']))
    except Exception:
        return False


def _clean_string(text, limit=1600):
    text = re.sub(r'(?i)\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*(?:"[^"]*"|\'[^\']*\'|[^\s<>"\']+)', '[redacted]', str(text))
    def url(match):
        value = urlsplit(match[0])
        return (value.scheme + '://' + value.netloc + value.path if value.scheme == 'https'
            and value.netloc in {'creator.douyin.com', 'www.douyin.com', 'douyin.com'}
            and not re.search(r'(?i)token|password|cookie|session|authorization', value.path) else '[url]')
    return re.sub(r'https?://[^\s<>"\']+', url, text)[:limit]


def sanitize_discovery(value):
    """Bounded pre-sanitized structure plus a second credential/query scrub."""
    allowed = {'route', 'title_candidates', 'loading_markers', 'scan_truncated', 'candidates_excessive',
        'title_match_variants', 'bound_title_structure', 'observed_cover', 'native_popup_resolution',
        'cover_open_pages', 'card_tag', 'card_nodes', 'canonical_ids', 'detail_candidates'}
    forbidden = {'token', 'access_token', 'authorization', 'cookie', 'cookies', 'session', 'password',
                 'raw_html', 'outer_html', 'inner_html', 'storage_state', 'headers', 'raw_response'}
    count = [0]
    def clean(item, depth=0):
        count[0] += 1
        if depth > 12 or count[0] > 5000:
            return '[truncated]'
        if isinstance(item, dict):
            return {str(k): clean(v, depth + 1) for k, v in list(item.items())[:48] if str(k).lower() not in forbidden}
        if isinstance(item, list):
            return [clean(x, depth + 1) for x in item[:64]]
        if isinstance(item, str):
            return _clean_string(item)
        if type(item) is float and not math.isfinite(item):
            return '[nonfinite]'
        if item is None or type(item) in (bool, int, float):
            return item
        return '[unsupported]'
    result = dict(schema='publication_discovery_sanitized/v1', verified=value.get('verified') is True,
        reason=_clean_string(value.get('reason', ''), 100), post_id=value.get('post_id', '') if re.fullmatch(r'\d{10,24}', str(value.get('post_id', ''))) else '',
        publish_url=_clean_string(value.get('publish_url', ''), 150),
        diagnostic=clean({k: v for k, v in (value.get('diagnostic') or {}).items() if k in allowed}),
        complete_raw_response_saved=False, cookie_or_session_saved=False)
    _require(len(json.dumps(result, ensure_ascii=False).encode()) <= 256 * 1024, 'diagnostic_sanitized_structure_budget_exceeded')
    return result


class CaptureComplete(Exception):
    pass


class Capture:
    def __init__(self, directory, subject, guard):
        self.directory = Path(directory)
        self.subject = subject
        self.guard = guard
        self.refs = []
        self.previous = None
        self.stable = 0

    def observed(self, value):
        self.guard()
        clean = sanitize_discovery(value)
        number = len(self.refs) + 1
        ref = bridge._write_once(self.directory / ('SAMPLE_%02d.json' % number),
            dict(schema='publication_discovery_observation/v1', subject=self.subject, observed_at=time.time(),
                 source='exact_worker_discover_published_work_result', discovery=clean))
        self.refs.append(ref)
        fingerprint = bridge._digest(clean)
        self.stable = self.stable + 1 if fingerprint == self.previous else 1
        self.previous = fingerprint
        if clean['verified']:
            return
        if (clean['reason'] == 'independent_card_unbound' and self.stable >= 2) or number >= MAX_SAMPLES:
            raise CaptureComplete(clean['reason'] or 'diagnostic_sample_budget_reached')

    def summary(self, result):
        return bridge._write_once(self.directory / 'SUMMARY.json', dict(
            schema='publication_discovery_capture_summary/v1', subject=self.subject, samples=self.refs,
            sample_count=len(self.refs), observation_budget=MAX_SAMPLES, result=result,
            browser_commands_added=False, upload_or_publish_called=False))


class ObservedPage:
    def __init__(self, original, capture):
        self.original, self.capture = original, capture

    def discover_published_work(self, title):
        value = self.original.discover_published_work(title)
        self.capture.observed(value)
        return value

    def __getattr__(self, name):
        return getattr(self.original, name)


class ObservedSession:
    def __init__(self, original, capture):
        self.original, self.capture = original, capture

    def open_page(self, url):
        return ObservedPage(self.original.open_page(url), self.capture)

    def __getattr__(self, name):
        return getattr(self.original, name)


def install_if_armed():
    if not ARM.is_file():
        return {'status': 'not_armed'}
    directory = None
    try:
        arm = json.loads(ARM.read_text(encoding='utf-8'))
        _require(set(arm) == {'schema', 'plan'} and arm['schema'] == 'publication_discovery_diagnostic_arm/v1', 'diagnostic_arm_invalid')
        arm_ref = bridge.reference(ARM)
        plan = _read(arm['plan'])
        directory = Path(arm['plan']['path']).parent
        request = _request(plan['request'])
        config = bridge._config(plan['config'])
        _require(plan['schema'] == 'publication_discovery_diagnostic_runtime/v1'
            and _read(plan['claim_plan'])['config'] == plan['config'], 'diagnostic_runtime_plan_changed')
        if os.getpid() != config['backend_pid']:
            return {'status': 'different_process_no_install'}
        installed = directory / 'ACTOR_HANDLER_INSTALLED.json'
        if installed.exists():
            _require(json.loads(installed.read_text(encoding='utf-8'))['plan'] == arm['plan'], 'diagnostic_existing_install_changed')
            return {'status': 'actor_install_already_recorded'}
        matches = [getattr(t, '_target').__globals__ for t in threading.enumerate()
            if t.name == 'AccountBrowser-' + config['account_key'] and t.is_alive()
            and getattr(getattr(t, '_target', None), '__name__', '') == '_host'
            and Path(t._target.__code__.co_filename).resolve() == bridge.HOST_PATH
            and getattr(t, '_args', ()) == (config['account_key'],)]
        _require(len(matches) == 1, 'diagnostic_original_thread_not_unique')
        namespace = matches[0]
        previous_poll = namespace['_poll_manual_windows']
        if getattr(previous_poll, '_publication_diagnostic_plan', None) == arm['plan']:
            return {'status': 'callback_already_registered'}

        def validate_plan():
            _require(bridge.reference(ARM) == arm_ref and _read(arm['plan']) == plan, 'diagnostic_arm_or_plan_changed')
            _request(plan['request'])
            bridge._config(plan['config'])

        def poll(actor, resource):
            if actor.account_id != config['account_id'] or actor.owner_id != config['owner_id'] or actor.generation != config['generation']:
                return previous_poll(actor, resource)
            previous_handler = None
            selective = None
            try:
                actor._assert_thread()
                actor._check_owner()
                validate_plan()
                if actor._stack or resource.manual_tasks or getattr(resource, 'console_tasks', {}):
                    return previous_poll(actor, resource)
                _require(actor.binding_version == config['binding_version'] and resource.account_uuid == config['account_id']
                    and Path(actor.store.path).resolve() == Path(config['browser_db']).resolve(), 'diagnostic_actor_scope_changed')
                original, queued = bridge._rows(config)
                _require(bridge._digest(original) == plan['original_row_sha256'] and _intent_sha(queued) == plan['queued_intent_sha256']
                    and json.loads(queued['payload']).get('discovery_diagnostic') == plan['request'], 'diagnostic_original_command_changed')
                previous_handler = actor.handlers['publication_verify']
                claim_fn, _, code_proof = bridge._load_claim(config)
                core_globals = claim_fn.__globals__
                core_globals['BrowserCommandResult'] = namespace['BrowserCommandResult']
                core_globals['BrowserControlRejected'] = namespace['BrowserControlRejected']
                run = core_globals['run']
                old_result, old_rejection = namespace['BrowserCommandResult'], namespace['BrowserControlRejected']

                def scoped(ctx, payload):
                    ctx.check_dispatch()
                    _request(plan['request'])
                    current = ctx.actor.store.get(ctx.task_id)
                    _require(current['state'] == 'running' and current['owner_id'] == config['owner_id']
                        and current['generation'] == config['generation']
                        and _intent_sha({**current, 'payload': bridge._json(current['payload'])}) == plan['queued_intent_sha256'],
                        'diagnostic_running_original_changed')
                    subject = dict(account_uuid=actor.account_id, owner_id=actor.owner_id, generation=actor.generation,
                        verification_command_id=ctx.task_id, original_command_id=config['original_command_id'],
                        request=plan['request'], instrumentation=request['instrumentation'])
                    capture = Capture(request['capture_directory'], subject, ctx.check_dispatch)
                    result = None
                    with resource.runtime.operation_lease(resource.context,
                            operation='publication-verification-read', daily_limit=20, cooldown_seconds=0):
                        resource.ensure_session()
                        session = ObservedSession(namespace['BorrowedSession'](resource, 'publication-verification-read'), capture)
                        try:
                            result = run(ctx, session)
                        except CaptureComplete as complete:
                            result = old_result('failed', {'status': 'verification_pending', 'reason': str(complete), 'diagnostic_observation_completed': True})
                        except old_rejection as error:
                            if error.code in {'owner_unknown', 'owner_fenced', 'command_fenced'}:
                                raise
                            result = old_result('failed', {'status': 'verification_blocked', 'reason': error.code})
                        except Exception as error:
                            result = old_result('failed', {'status': 'verification_pending', 'reason': 'read_failed', 'error_type': type(error).__name__})
                        finally:
                            session.stop()
                            summary = None
                            try:
                                summary = capture.summary({'state': getattr(result, 'state', 'succeeded' if isinstance(result, dict) else 'unknown'),
                                    'reason': (getattr(result, 'result', {}) or {}).get('reason', '')})
                            except Exception as error:
                                bridge._record_failure(capture.directory, 'capture_write', error)
                                if not isinstance(result, dict) or result.get('status') != 'verified_published':
                                    result = old_result('failed', {'status': 'verification_pending',
                                        'reason': 'diagnostic_evidence_write_failed', 'error_type': type(error).__name__})
                            if actor.handlers.get('publication_verify') is selective:
                                actor.handlers['publication_verify'] = previous_handler
                    if summary is not None and is_dataclass(result) and result.state != 'succeeded':
                        return replace(result, result=dict(result.result or {}, diagnostic_capture=summary))
                    return result  # Successful core settlement receipt is untouched.

                wrapped = namespace['_with_active'](scoped)
                def selective(ctx, payload):
                    if ctx.task_id != config['verification_command_id']:
                        return previous_handler(ctx, payload)
                    try:
                        return wrapped(ctx, payload)
                    finally:
                        if actor.handlers.get('publication_verify') is selective:
                            actor.handlers['publication_verify'] = previous_handler
                actor.handlers['publication_verify'] = selective
                namespace['_poll_manual_windows'] = previous_poll
                installed_ref = bridge._write_once(installed, dict(schema='publication_discovery_diagnostic_actor_install/v1',
                    plan=arm['plan'], backend_pid=os.getpid(), owner_id=actor.owner_id, generation=actor.generation,
                    backend_create_time=config['backend_create_time'],
                    actor_thread_id=threading.get_ident(), command_id=config['verification_command_id'],
                    core_claim_source=code_proof, core_run_code_sha256=hashlib.sha256(run.__code__.co_code).hexdigest(),
                    only_private_single_cid_handler=True, core_sources_modified=False, browser_actions=False))
                bridge._write_once(Path(plan['request']['path']).parent / 'HANDLER_READY.json', dict(
                    schema='publication_discovery_diagnostic_handler_ready/v1', request=plan['request'],
                    instrumentation=request['instrumentation'], runtime_plan=arm['plan'], actor_install=installed_ref,
                    command_id=config['verification_command_id'], account_uuid=config['account_id'],
                    binding_version=config['binding_version'], owner_id=actor.owner_id, generation=actor.generation))
            except Exception as error:
                if previous_handler is not None and actor.handlers.get('publication_verify') is selective:
                    actor.handlers['publication_verify'] = previous_handler
                namespace['_poll_manual_windows'] = previous_poll
                bridge._record_failure(directory, 'diagnostic_install', error)
            return previous_poll(actor, resource)

        poll._publication_diagnostic_plan = arm['plan']
        namespace['_poll_manual_windows'] = poll
        bridge._write_once(directory / 'UI_IMPORT_RECEIPT.json', dict(schema='publication_discovery_diagnostic_ui_import/v1',
            plan=arm['plan'], backend_pid=os.getpid(), callback_registered=True, actor_installed=False))
        return {'status': 'callback_registered_waiting_actor_tick'}
    except Exception as error:
        if directory:
            bridge._record_failure(directory, 'diagnostic_ui_import', error)
        return {'status': 'refused', 'error_type': type(error).__name__}
