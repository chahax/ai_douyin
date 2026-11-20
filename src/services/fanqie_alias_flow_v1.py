"""Durable alias acquisition through the existing dedicated Fanqie executor.

Each distinct alias has its own once-only request. Only evidenced naming
validation permits the next alias. An unknown submission is reconciled once,
then retained; this module never publishes or rewrites a previous claim.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time

from .fanqie_promotion_workspace_v1 import PromotionWorkspace, ref
from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from . import fanqie_promotion_identity_v2 as native

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'fanqie_alias_flow/v1'
TERMINAL = {'record_observed', 'aliases_exhausted', 'outcome_unknown',
            'blocked', 'dispatch_receipt_unknown'}


def validate_candidate_aliases(aliases):
    """Conservative automation candidates under the observed 4–8-character rule.

    Use common Han characters and ASCII Arabic digits. Historical plans remain
    readable; this check applies only when preparing a new acquisition flow.
    """
    if (not isinstance(aliases, list) or not aliases
            or any(not isinstance(alias, str)
                   or re.fullmatch(r'[\u3400-\u4dbf\u4e00-\u9fff0-9]{4,8}', alias) is None
                   for alias in aliases)):
        raise ValueError('alias_candidates_require_4_to_8_common_Han_or_ASCII_digits')
    return aliases


def _read(binding):
    return managed._read(binding)


def _write(path, value, *, immutable=False):
    path = Path(path)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
    if immutable:
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('flow_immutable_record_changed')
        else:
            with path.open('xb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
    else:
        temporary = path.with_suffix('.tmp')
        with temporary.open('wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    return ref(path)


@contextmanager
def _lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'STEP.lock').open('a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('flow_busy') from error
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('flow_busy') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class AliasFlow:
    def __init__(self, directory, *, workspace=None, command_reader=None,
                 snapshot_validator=None, clock=time.time):
        self.directory = Path(directory).resolve()
        if not self.directory.is_relative_to(ROOT / 'data'):
            raise ValueError('flow_directory_must_be_project_data')
        self.workspace = workspace or PromotionWorkspace()
        self.command_reader = command_reader or self._read_command
        self.validate_snapshot = snapshot_validator or native.validate_snapshot
        self.clock = clock

    def _read_command(self, command_id):
        if not self.workspace.accounts.db.is_file():
            raise ValueError('flow_original_executor_database_missing')
        return BrowserControlStore(self.workspace.accounts.db).get(command_id)

    def _save(self, state):
        state['updated_at'] = self.clock()
        _write(self.directory / 'STATE.json', state)
        return state

    def _load(self):
        plan = json.loads((self.directory / 'PLAN.json').read_text(encoding='utf-8'))
        spec = _read(plan['spec'])
        state = json.loads((self.directory / 'STATE.json').read_text(encoding='utf-8'))
        if state['spec'] != plan['spec']:
            raise ValueError('flow_plan_changed')
        self._guard(spec)
        return spec, state

    def _guard(self, spec):
        if spec.get('schema') != VERSION:
            raise ValueError('flow_spec_version_invalid')
        binding = spec['resource_binding']
        backend = spec['backend']
        if (backend != dict(ledger_path=str(self.workspace.path.resolve()),
                            browser_db=str(self.workspace.accounts.db.resolve()))):
            raise ValueError('flow_original_ledger_or_executor_changed')
        if self.workspace._resource_binding(binding['resource_id']) != binding:
            raise ValueError('flow_original_account_binding_changed')
        book = spec['book']
        if (set(book) != {'book_id', 'book_name', 'publish_type', 'promotion_path'}
                or not str(book['book_id']).isdigit() or book['publish_type'] != 'AIGC'
                or book['promotion_path'] != '别名推广' or not book['book_name'].strip()):
            raise ValueError('flow_exact_book_and_aigc_required')
        aliases = spec['aliases']
        observed = spec.get('observe_aliases', [])
        if (not isinstance(aliases, list) or not 1 <= len(aliases) <= 8
                or not isinstance(observed, list) or len(observed) > 8
                or len(set(aliases)) != len(aliases)
                or set(aliases) & set(observed)
                or any(not isinstance(a, str) or not a.strip() or a != a.strip()
                       or len(a) > 30 or any(ord(c) < 32 for c in a) for a in aliases + observed)):
            raise ValueError('flow_explicit_distinct_aliases_required')
        auth = _read(spec['authorization'])
        intent = {k: spec[k] for k in ('resource_binding', 'book', 'aliases', 'observe_aliases',
                                      'candidate', 'original_records', 'backend')}
        if (auth.get('schema') != 'fanqie_alias_flow_authorization/v1'
                or auth.get('confirmed_by') != 'user' or not auth.get('user_statement', '').strip()
                or auth.get('intent') != intent or type(auth.get('max_submissions')) is not int
                or auth.get('max_submissions') != len(aliases)):
            raise ValueError('flow_exact_authorization_required')
        for original in spec['original_records']:
            _read(original)  # Old records are pinned, never settled or overwritten.
        candidate = spec['candidate']
        row = self.workspace._candidates().get(candidate['candidate_id'])
        frozen = json.loads(row['frozen_json'])
        if (frozen['book_id'] != book['book_id'] or frozen['book_name'] != book['book_name']
                or frozen['account']['account_uuid'] != binding['douyin_account_uuid']
                or frozen['media'] != candidate['media']):
            raise ValueError('flow_candidate_book_media_or_account_changed')
        path = Path(candidate['media']['path']).resolve()
        if not path.is_relative_to(ROOT / 'data'):
            raise ValueError('flow_candidate_media_outside_project')
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != candidate['media']['sha256']:
            raise ValueError('flow_candidate_media_changed')

    def prepare(self, spec_binding):
        with _lock(self.directory):
            spec = _read(spec_binding)
            self._guard(spec)
            plan = dict(schema=VERSION, spec=spec_binding)
            if (self.directory / 'STATE.json').exists():
                _write(self.directory / 'PLAN.json', plan, immutable=True)
                return self._load()[1]
            validate_candidate_aliases(spec['aliases'])
            _write(self.directory / 'PLAN.json', plan, immutable=True)
            return self._save(dict(schema=VERSION, spec=spec_binding, phase='need_sync',
                alias_index=0, operations=[], reconciliation=False, last_application=None,
                published=False, media_calls=0))

    def status(self):
        # Does not navigate, queue, migrate, close or otherwise schedule work.
        return self._load()[1]

    def _queue(self, spec, state, kind):
        number = len(state['operations']) + 1
        alias = spec['aliases'][state['alias_index']] if kind == 'apply' else None
        intent = dict(number=number, kind=kind, alias=alias, created_at=self.clock())
        intent_ref = _write(self.directory / ('OP_%03d_INTENT.json' % number), intent, immutable=True)
        op = dict(intent=intent_ref, kind=kind, alias=alias, dispatch='intent_written', command_id=None)
        state['operations'].append(op)
        state['phase'] = 'dispatch_pending'
        self._save(state)  # Durable before any external dispatch; crashes cannot blindly queue again.
        try:
            resource = spec['resource_binding']['resource_id']
            if kind == 'sync':
                result = self.workspace.sync(resource, snapshot_version='v2')
            else:
                book = spec['book']
                statement = _read(spec['authorization'])['user_statement']
                result = self.workspace.apply(resource, book_id=book['book_id'], book_name=book['book_name'],
                    alias=alias, promotion_path=book['promotion_path'], user_statement=statement)
            op['queue_receipt'] = _write(self.directory / ('OP_%03d_QUEUE.json' % number), result, immutable=True)
            if (result.get('status') != 'queued' or result.get('new_request_queued') is not True
                    or not result.get('command_id')):
                op.update(dispatch='blocked', command_id=result.get('command_id'))
                state.update(phase='blocked', reason='original_executor_command_busy')
            else:
                op.update(dispatch='queued', command_id=result['command_id'])
                state['phase'] = 'waiting_' + kind
        except Exception as error:
            op.update(dispatch='unknown', error_type=type(error).__name__)
            state.update(phase='dispatch_receipt_unknown', reason='original_queue_intent_preserved')
        return self._save(state)

    def _command(self, spec, op):
        command = self.command_reader(op['command_id'])
        binding = spec['resource_binding']
        kind = 'fanqie_promotion_list' if op['kind'] == 'sync' else 'fanqie_promotion_apply'
        if (not command or command['command_id'] != op['command_id'] or command['kind'] != kind
                or command['account_id'] != binding['resource_id']
                or command['binding_version'] != binding['binding_version']):
            raise ValueError('flow_original_command_scope_changed')
        if op['kind'] == 'apply':
            request = _read(command['payload']['request'])
            expected = dict(resource_id=binding['resource_id'], binding_version=binding['binding_version'],
                platform_identity_key=binding['platform_identity_key'], **spec['book'], alias=op['alias'])
            if any(request.get(k) != v for k, v in expected.items()):
                raise ValueError('flow_original_application_intent_changed')
        return command

    def _sync_result(self, spec, state, command):
        snapshot_ref = command.get('result', {}).get('promotion_snapshot')
        if command['state'] != 'succeeded' or not snapshot_ref:
            state.update(phase='blocked', reason='original_sync_did_not_complete')
            return
        snapshot = _read(snapshot_ref)
        self.validate_snapshot(snapshot, require_fresh=True)
        binding = spec['resource_binding']
        if (snapshot.get('schema') != 'fanqie_promotion_snapshot/v2'
                or any(snapshot.get(k) != binding[k] for k in
                       ('resource_id', 'binding_version', 'platform_identity_key', 'environment_key'))
                or snapshot.get('identity_verified') is not True
                or snapshot.get('challenge') not in (None, False)
                or not snapshot.get('pagination_complete') or not snapshot.get('table_ready')):
            raise ValueError('flow_complete_original_native_snapshot_required')
        aliases = spec['aliases'] + spec['observe_aliases']
        rows = [row for row in snapshot['rows'] if row.get('book_id') == spec['book']['book_id']
                and row.get('alias') in aliases]
        if rows:
            state.update(phase='record_observed', promotion_snapshot=snapshot_ref, observed_rows=rows,
                         reason='current_flow_record_found_no_more_applications')
            conflicts = [row for row in rows if row.get('book_name') != spec['book']['book_name']
                or row.get('publish_type') != spec['book']['publish_type']
                or row.get('workflow_label') != spec['book']['promotion_path']
                or row.get('workflow_kind') != 'alias_promotion']
            state['record_scope_conflict'] = bool(conflicts)
            if conflicts:
                state['reason'] = 'existing_book_alias_record_scope_conflict_no_reapplication'
            publishable = []
            for row in rows:
                if (row.get('book_name') != spec['book']['book_name']
                        or row.get('publish_type') != spec['book']['publish_type']
                        or row.get('workflow_label') != spec['book']['promotion_path']
                        or row.get('workflow_kind') != 'alias_promotion'):
                    continue
                try:
                    native.assert_publishable(snapshot, row)
                except ValueError:
                    continue
                publishable.append(row)
            state['publishable'] = len(publishable) == 1
            if len(publishable) == 1:
                state['promotion_key'] = native.selection_key(snapshot, publishable[0])
                state['promotion_subject'] = native.authorization_subject(snapshot, publishable[0])
                state['sync_command_id'] = command['command_id']
            return
        state['last_snapshot'] = snapshot_ref
        if state['reconciliation']:
            state.update(phase='outcome_unknown', reason='submitted_once_not_found_in_current_native_list')
        elif state['alias_index'] >= len(spec['aliases']):
            state.update(phase='aliases_exhausted', reason='authorized_alias_candidates_exhausted')
        else:
            state['phase'] = 'need_apply'

    def _application_result(self, spec, state, command):
        result = command.get('result') or {}
        op = state['operations'][-1]
        state['last_application'] = dict(command_id=command['command_id'], alias=op['alias'],
                                          state=command['state'], result=result)
        # Never trust a result string alone: verify the bound fresh UI evidence.
        valid = False
        if (command['state'] == 'failed' and result.get('application_status') == 'alias_validation_failed'
                and result.get('retry_with_new_alias') is True and result.get('alias_reusable') is False):
            feedback = _read(result.get('feedback_ref'))
            from src.platform_adapter.fanqie_form_feedback_v1 import confirmed_alias_validation
            expected = dict(spec['book'], alias=op['alias'])
            valid = confirmed_alias_validation(feedback, expected)
        if valid:
            state['alias_index'] += 1
            state.update(phase='need_sync', reconciliation=False)
        elif result.get('submit_started') is False and result.get('submitted') is not True:
            state.update(phase='blocked', reason=result.get('reason', 'application_precondition_failed'))
        else:
            # Technical success or a success toast does not prove business success.
            state.update(phase='need_sync', reconciliation=True)

    def step(self):
        with _lock(self.directory):
            spec, state = self._load()
            if state['phase'] in TERMINAL:
                return state
            if state['phase'] == 'dispatch_pending':
                state.update(phase='dispatch_receipt_unknown', reason='original_queue_intent_preserved')
                return self._save(state)
            if state['phase'] == 'need_sync':
                return self._queue(spec, state, 'sync')
            if state['phase'] == 'need_apply':
                return self._queue(spec, state, 'apply')
            op = state['operations'][-1]
            if op['dispatch'] != 'queued' or not op['command_id']:
                state.update(phase='dispatch_receipt_unknown', reason='original_queue_intent_preserved')
                return self._save(state)
            command = self._command(spec, op)
            if command['state'] in {'queued', 'running', 'paused', 'waiting_human'}:
                return state
            receipt = _write(self.directory / ('OP_%03d_TERMINAL.json' % len(state['operations'])),
                dict(command_id=command['command_id'], state=command['state'], result=command.get('result'),
                     error_code=command.get('error_code')), immutable=True)
            op['terminal_receipt'] = receipt
            if op['kind'] == 'sync':
                self._sync_result(spec, state, command)
            else:
                self._application_result(spec, state, command)
            return self._save(state)
