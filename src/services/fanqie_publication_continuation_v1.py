"""Opt-in continuation of an existing publication into exact native backfill.

This is not a publisher or an account scheduler. It never requests publication
verification, aliases, uploads to Douyin, account recovery, or media generation.
Every effect has a durable intent; a missing receipt is recovered read-only or
left unresolved, never blindly dispatched again.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .fanqie_promotion_workspace_v1 import PromotionWorkspace
from . import fanqie_promotion_identity_v2 as native

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'fanqie_publication_continuation/v1'
LIVE = {'queued', 'running', 'paused', 'waiting_human', 'outcome_unknown'}
MAX_RECONCILIATIONS = 3
RECONCILE_INTERVAL = 300
TERMINAL = {'confirmed', 'blocked'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_ref(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT / 'data'):
        raise ValueError('continuation_artifact_must_be_project_data')
    with path.open('rb') as handle:
        sha = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'path': str(path), 'sha256': sha}


def read_ref(value, *, json_content=True):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'} or file_ref(value['path']) != value:
        raise ValueError('continuation_reference_changed')
    if not json_content:
        return Path(value['path'])
    return json.loads(Path(value['path']).read_text(encoding='utf-8-sig'))


def _write(path, value, *, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if immutable:
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('continuation_immutable_evidence_changed')
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
    return file_ref(path)


@contextmanager
def _lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'STEP.lock').open('a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('continuation_busy') from error
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('continuation_busy') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class PublicationContinuation:
    def __init__(self, directory, *, workspace=None, command_reader=None,
                 candidate_reader=None, backfill_reader=None, publication_reader=None,
                 publication_time_reader=None, snapshot_validator=None,
                 command_finder=None, clock=time.time):
        self.directory = Path(directory).resolve()
        if not self.directory.is_relative_to(ROOT / 'data'):
            raise ValueError('continuation_directory_must_be_project_data')
        self.workspace = workspace or PromotionWorkspace()
        self.command_reader = command_reader or self._read_command
        self.candidate_reader = candidate_reader or self.workspace._candidates().get
        self.backfill_reader = backfill_reader or self.workspace._backfill().get
        self.publication_reader = publication_reader or self._read_publication
        self.time_reader = publication_time_reader or self._read_time
        self.snapshot_validator = snapshot_validator or native.validate_snapshot
        self.command_finder = command_finder or self._find_command
        self.clock = clock

    def _connection(self):
        path = Path(self.workspace.accounts.db).resolve()
        if not path.is_file():
            raise ValueError('continuation_original_executor_missing')
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        return db

    def _read_command(self, command_id):
        with self._connection() as db:
            row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        for field in ('payload', 'result', 'cursor'):
            if isinstance(value.get(field), str):
                value[field] = json.loads(value[field])
        return value

    def _read_publication(self, command_id, account_uuid, binding_version):
        from .publication_evidence import PublicationEvidenceReader
        return PublicationEvidenceReader(self.workspace.accounts.db).read(command_id, account_uuid, binding_version)

    def _read_time(self, command_id, account_uuid, binding_version, *, metadata_command_id=None):
        from .publication_time_evidence_v1 import read_publication_time
        return read_publication_time(self.workspace.accounts.db, command_id, account_uuid, binding_version,
                                     metadata_command_id=metadata_command_id)

    def _save(self, state):
        state['updated_at'] = self.clock()
        _write(self.directory / 'STATE.json', state)
        return state

    def _guard(self, spec):
        fields = {'schema', 'backend', 'candidate_id', 'original_publish_command_id', 'resource_binding',
                  'book', 'media', 'original_authorization', 'official_template'}
        if set(spec) != fields or spec['schema'] != SCHEMA:
            raise ValueError('continuation_spec_contract_invalid')
        if spec['backend'] != {'ledger_path': str(self.workspace.path.resolve()),
                               'browser_db': str(Path(self.workspace.accounts.db).resolve())}:
            raise ValueError('continuation_original_backend_changed')
        binding = spec['resource_binding']
        if self.workspace._resource_binding(binding['resource_id']) != binding:
            raise ValueError('continuation_original_resource_binding_changed')
        candidate = self.candidate_reader(spec['candidate_id'])
        frozen = json.loads(candidate['frozen_json'])
        prepared = json.loads(candidate['prepared_json'] or '{}')
        account = frozen['account']
        if (candidate['candidate_id'] != spec['candidate_id']
                or candidate['command_id'] != spec['original_publish_command_id']
                or not candidate['task_id'] or not candidate['video_job_id']
                or frozen['book_id'] != spec['book']['book_id'] or frozen['book_name'] != spec['book']['book_name']
                or frozen['media'] != spec['media'] or account['account_uuid'] != binding['douyin_account_uuid']
                or prepared.get('promotion', {}).get('binding') != binding):
            raise ValueError('continuation_existing_candidate_scope_changed')
        subject = prepared['promotion']['row']
        if (subject.get('schema') != 'fanqie_promotion_authorization_subject/v2'
                or subject.get('book_id') != spec['book']['book_id']
                or subject.get('book_name') != spec['book']['book_name'] or subject.get('publish_type') != 'AIGC'
                or subject.get('workflow_kind') != 'alias_promotion'
                or subject.get('identity', {}).get('platform_identity_key') != binding['platform_identity_key']):
            raise ValueError('continuation_original_native_subject_required')
        original = self.command_reader(spec['original_publish_command_id'])
        if (not original or original['command_id'] != spec['original_publish_command_id']
                or original['kind'] != 'publish' or original['account_id'] != account['account_uuid']
                or original['binding_version'] != account['binding_version']
                or original['payload'].get('video_sha256') != spec['media']['sha256']
                or original['payload'].get('request') != prepared.get('request')
                or original['payload'].get('authorization') != prepared.get('authorization')):
            raise ValueError('continuation_original_publication_intent_changed')
        auth = read_ref(spec['original_authorization'])
        target = dict(book_id=spec['book']['book_id'], book_name=spec['book']['book_name'],
                      douyin_account_key=account['account_key'], fanqie_resource_id=binding['resource_id'], media=spec['media'])
        if (auth.get('schema') != 'fanqie_production_trial_user_authorization/v1'
                or auth.get('authorized_target') != target or not auth.get('user_statement', '').strip()
                or 'publishing/backfill' not in auth.get('interpretation', '')):
            raise ValueError('continuation_original_whole_flow_authorization_required')
        read_ref(spec['media'], json_content=False)
        read_ref(spec['official_template'], json_content=False)
        read_ref(prepared['authorization'])
        read_ref(prepared['review'])
        immutable = dict(frozen=frozen, prepared=prepared, task_id=candidate['task_id'], video_job_id=candidate['video_job_id'],
                         publication_command_id=original['command_id'], original_payload=original['payload'],
                         account_id=original['account_id'], binding_version=original['binding_version'])
        return candidate, frozen, original, digest(immutable)

    def prepare(self, spec_ref):
        with _lock(self.directory):
            spec = read_ref(spec_ref)
            _, _, _, subject = self._guard(spec)
            plan = dict(schema=SCHEMA, spec=spec_ref, subject_sha256=subject)
            _write(self.directory / 'PLAN.json', plan, immutable=True)
            if (self.directory / 'STATE.json').exists():
                return self._load()[1]
            return self._save(dict(schema=SCHEMA, spec=spec_ref, subject_sha256=subject, phase='waiting_publication',
                                   operations=[], metadata_command_id=None, publication=None, publication_time=None,
                                   publication_handoff=None, preparation=None, backfill_command_id=None,
                                   reconciliations=0, next_reconcile_at=0, confirmed=False))

    def _load(self):
        plan = json.loads((self.directory / 'PLAN.json').read_text(encoding='utf-8'))
        state = json.loads((self.directory / 'STATE.json').read_text(encoding='utf-8'))
        spec = read_ref(plan['spec'])
        _, _, _, subject = self._guard(spec)
        if state['spec'] != plan['spec'] or state['subject_sha256'] != plan['subject_sha256'] or subject != plan['subject_sha256']:
            raise ValueError('continuation_pinned_subject_changed')
        if state['phase'] == 'confirmed':
            if (self._original_receipt(spec) != state['publication']
                    or self._time(spec, state) != state['publication_time']
                    or self._backfill(spec, state)['status'] != 'confirmed'
                    or state['confirmed'] is not True):
                raise ValueError('continuation_confirmed_evidence_changed')
        return spec, state

    def status(self):
        """No filesystem mutation, scheduling, navigation, or authorization."""
        return self._load()[1]

    def _original_receipt(self, spec):
        c = self.candidate_reader(spec['candidate_id'])
        account = json.loads(c['frozen_json'])['account']
        return self.publication_reader(spec['original_publish_command_id'], account['account_uuid'], account['binding_version'])

    def _time(self, spec, state):
        account = json.loads(self.candidate_reader(spec['candidate_id'])['frozen_json'])['account']
        return self.time_reader(spec['original_publish_command_id'], account['account_uuid'], account['binding_version'],
                                metadata_command_id=state['metadata_command_id'])

    def _command(self, spec, operation, command_id):
        command = self.command_reader(command_id)
        kind = operation['kind']
        account = json.loads(self.candidate_reader(spec['candidate_id'])['frozen_json'])['account']
        binding = spec['resource_binding']
        expected_kind = {'metadata': 'read', 'sync': 'fanqie_promotion_list',
                         'dispatch': 'fanqie_backfill', 'reconcile': 'fanqie_backfill_reconcile'}[kind]
        uid, version = ((account['account_uuid'], account['binding_version']) if kind == 'metadata'
                        else (binding['resource_id'], binding['binding_version']))
        if (not command or command['command_id'] != command_id or command['kind'] != expected_kind
                or command['account_id'] != uid or command['binding_version'] != version):
            raise ValueError('continuation_effect_command_scope_changed')
        payload = command['payload']
        if kind == 'metadata':
            key = command.get('idempotency_key', '')
            base = operation['intent_value']['metadata_key']
            if (payload.get('method') != 'sync_videos' or payload.get('params') != {}
                    or not (key == base or key.startswith(base + ':after:') and key != base + ':after:')):
                raise ValueError('continuation_metadata_command_changed')
        else:
            intent = operation['intent_value']
            key = ('fanqie-backfill:' + intent['business_key'] if kind == 'dispatch' else intent['expected_key'])
            if command.get('idempotency_key') != key:
                raise ValueError('continuation_effect_idempotency_key_changed')
            if payload.get('environment_key') != binding['environment_key'] and kind != 'dispatch':
                raise ValueError('continuation_effect_environment_changed')
            if kind == 'sync' and payload.get('snapshot_version') != 'v2':
                raise ValueError('continuation_native_snapshot_required')
            if kind in {'dispatch', 'reconcile'}:
                intent = operation['intent_value']
                if payload.get('binding_uuid') != intent['binding_uuid'] or payload.get('manifest_sha256') != intent['manifest_sha256']:
                    raise ValueError('continuation_original_backfill_command_changed')
        return command

    def _snapshot(self, spec, state):
        snapshot = read_ref(state['promotion_snapshot'])
        self.snapshot_validator(snapshot, require_fresh=True)
        binding = spec['resource_binding']
        prepared = json.loads(self.candidate_reader(spec['candidate_id'])['prepared_json'])
        if any(snapshot.get(k) != binding[k] for k in ('resource_id', 'binding_version', 'platform_identity_key', 'environment_key')):
            raise ValueError('continuation_snapshot_identity_changed')
        matches = []
        for row in snapshot.get('rows', []):
            target = prepared['promotion']['row']
            if row.get('native_kind') != 'promotion_alias' or not row.get('native_record_id'):
                # Unrelated pending rows legitimately have no native identity.
                # A pending row for this exact book/alias is still a blocker.
                if row.get('book_id') == target['book_id'] and row.get('alias') == target['alias']:
                    raise ValueError('continuation_target_native_alias_pending')
                continue
            if native.native_identity(snapshot, row) != target['identity']:
                continue
            if native.authorization_subject(snapshot, row) == target:
                matches.append(row)
        if len(matches) != 1:
            raise ValueError('continuation_exact_native_alias_required')
        native.assert_publishable(snapshot, matches[0])
        return snapshot

    def _backfill(self, spec, state):
        preparation = state['preparation']
        row = self.backfill_reader(preparation['binding_uuid'])
        manifest = read_ref(preparation['manifest'])
        contract = read_ref(preparation['contract'])
        if (json.loads(row['manifest_json']) != manifest or digest(manifest) != row['manifest_sha']
                or json.loads(row['contract_json']) != contract):
            raise ValueError('continuation_backfill_manifest_or_contract_changed')
        candidate = self.candidate_reader(spec['candidate_id'])
        prepared = json.loads(candidate['prepared_json'])
        expected = dict(fanqie_resource_id=spec['resource_binding']['resource_id'],
                        fanqie_binding_version=spec['resource_binding']['binding_version'],
                        account_link_version=spec['resource_binding']['account_link_version'],
                        publication_command_id=spec['original_publish_command_id'], book_id=spec['book']['book_id'],
                        video_job_id=candidate['video_job_id'], media=spec['media'],
                        post_id=state['publication']['post_id'], publish_url=state['publication']['publish_url'],
                        promotion_subject=prepared['promotion']['row'], native_identity=prepared['promotion']['row']['identity'],
                        douyin_account_uuid=spec['resource_binding']['douyin_account_uuid'],
                        douyin_account_key=json.loads(candidate['frozen_json'])['account']['account_key'],
                        douyin_binding_version=json.loads(candidate['frozen_json'])['account']['binding_version'])
        instant = datetime.fromisoformat(state['publication_time']['published_at'].replace('Z', '+00:00'))
        if instant.tzinfo is None:
            raise ValueError('continuation_original_publication_timezone_required')
        publication_date = instant.astimezone(timezone(timedelta(hours=8))).strftime('%Y/%m/%d')
        if (row['task_id'] != candidate['task_id'] or row['publish_id'] != candidate['publish_id']
                or contract.get('schema') != 'fanqie_backfill_contract/v3'
                or any(contract.get(k) != v for k, v in expected.items())
                or manifest['publication']['post_id'] != expected['post_id']
                or manifest['publication']['publish_url'] != expected['publish_url']
                or manifest['binding']['published_date'] != publication_date):
            raise ValueError('continuation_backfill_subject_changed')
        # Public inspect validates the actual workbook, original publication,
        # time proof, native mapping and all registered contract input files.
        inspection = self.workspace.backfill_status(row['binding_uuid'])
        if (inspection.get('inputs_verified') is not True or inspection.get('status') != row['status']
                or inspection.get('manifest_sha256') != row['manifest_sha']
                or inspection.get('post_id') != expected['post_id'] or inspection.get('publish_url') != expected['publish_url']):
            raise ValueError('continuation_registered_backfill_inputs_unverified')
        if state.get('exact_authorization') is not None and json.loads(row['authorization_json'] or '{}') != state['exact_authorization']:
            raise ValueError('continuation_registered_manifest_authorization_changed')
        # The ledger uses canonical semantic SHA, not the manifest file-byte SHA.
        state['manifest_sha256'] = row['manifest_sha']
        state['manifest_file_sha256'] = preparation['manifest']['sha256']
        return row

    def _finish(self, spec, state, operation, result):
        kind = operation['kind']
        if kind in {'metadata', 'sync', 'dispatch', 'reconcile'}:
            cid = result.get('command_id') if kind != 'dispatch' else (result.get('command') or {}).get('command_id')
            if not cid:
                raise ValueError('continuation_command_receipt_missing')
            if kind in {'sync', 'reconcile'} and result.get('new_request_queued') is not True and not result.get('recovered'):
                raise ValueError('continuation_original_executor_busy')
            self._command(spec, operation, cid)
            operation.update(command_id=cid, dispatch='receipt_bound')
            state['phase'] = 'waiting_' + kind
            if kind == 'metadata':
                state['metadata_command_id'] = cid
            if kind == 'dispatch':
                state['backfill_command_id'] = cid
            if kind == 'reconcile':
                state['reconciliations'] += 1
        elif kind == 'attach':
            handoff = read_ref(result)
            candidate = self.candidate_reader(spec['candidate_id'])
            account = json.loads(candidate['frozen_json'])['account']
            expected = dict(schema='fanqie_h3_publication_handoff/v2', candidate_id=spec['candidate_id'],
                command_id=spec['original_publish_command_id'], book_id=spec['book']['book_id'], media=spec['media'],
                task_id=candidate['task_id'], video_job_id=candidate['video_job_id'], publish_id=candidate['publish_id'],
                post_id=state['publication']['post_id'], publish_url=state['publication']['publish_url'],
                published_at=state['publication_time']['published_at'], account_uuid=account['account_uuid'],
                account_key=account['account_key'], binding_version=account['binding_version'])
            if any(handoff.get(k) != v for k, v in expected.items()):
                raise ValueError('continuation_publication_handoff_changed')
            state.update(publication_handoff=result, phase='need_sync')
        elif kind == 'prepare':
            state['preparation'] = result
            self._backfill(spec, state)
            state['phase'] = 'need_authorize'
        elif kind == 'authorize':
            row = self._backfill(spec, state)
            if json.loads(row['authorization_json'] or '{}') != operation['intent_value']['authorization']:
                raise ValueError('continuation_exact_manifest_authorization_missing')
            state['exact_authorization'] = operation['intent_value']['authorization']
            state['phase'] = 'need_dispatch'
        operation['dispatch'] = 'receipt_bound'
        state.pop('reason', None)
        return self._save(state)

    def _effect(self, spec, state, kind, intent, call):
        number = len(state['operations']) + 1
        intent = dict(intent, created_at=self.clock(), kind=kind, number=number,
                      candidate_id=spec['candidate_id'], original_publish_command_id=spec['original_publish_command_id'])
        if kind in {'sync', 'reconcile'}:
            before = self.workspace.accounts.latest_command(spec['resource_binding']['resource_id'])
            intent['expected_key'] = ('fanqie-step:' + (before['command_id'] if before else 'initial') if kind == 'sync' else
                                      'fanqie-backfill-reconcile:' + intent['business_key'] + ':' + (before['command_id'] if before else 'initial'))
        op = dict(number=number, kind=kind, intent_value=intent,
                  intent=_write(self.directory / ('OP_%03d_INTENT.json' % number), intent, immutable=True),
                  dispatch='pending', command_id=None)
        state['operations'].append(op)
        state['phase'] = 'effect_pending'
        self._save(state)
        try:
            result = call()
            op['receipt'] = _write(self.directory / ('OP_%03d_RECEIPT.json' % number), result, immutable=True)
            return self._finish(spec, state, op, result)
        except Exception as error:
            op['error_type'] = type(error).__name__
            state['reason'] = 'effect_receipt_unresolved_no_redispatch'
            return self._save(state)

    def _find_command(self, spec, operation):
        intent = operation['intent_value']
        kind = operation['kind']
        binding = spec['resource_binding']
        account = json.loads(self.candidate_reader(spec['candidate_id'])['frozen_json'])['account']
        uid = account['account_uuid'] if kind == 'metadata' else binding['resource_id']
        key = intent.get('expected_key')
        if kind == 'dispatch':
            row = self.backfill_reader(intent['binding_uuid'])
            key = 'fanqie-backfill:' + row['business_key']
        with self._connection() as db:
            rows = [dict(r) for r in db.execute('SELECT command_id,idempotency_key,created_at FROM browser_control_commands WHERE account_id=?', (uid,))]
        if kind == 'metadata':
            rows = [r for r in rows if r['idempotency_key'] == intent['metadata_key']
                    or r['idempotency_key'].startswith(intent['metadata_key'] + ':after:')]
        else:
            rows = [r for r in rows if r['idempotency_key'] == key]
        if len(rows) != 1:
            return None
        return self._command(spec, operation, rows[0]['command_id'])

    def _recover(self, spec, state):
        """Recover original receipts, never call an external action again."""
        op = state['operations'][-1]
        path = self.directory / ('OP_%03d_RECEIPT.json' % op['number'])
        if path.is_file():
            result = read_ref(file_ref(path))
            return self._finish(spec, state, op, result)
        result = None
        if op['kind'] in {'metadata', 'sync', 'dispatch', 'reconcile'}:
            command = self.command_finder(spec, op)
            if command:
                result = ({'command': command, 'recovered': True} if op['kind'] == 'dispatch' else
                          {'command_id': command['command_id'], 'recovered': True})
        elif op['kind'] == 'prepare':
            registered = Path(op['intent_value']['output_directory']) / 'REGISTERED.json'
            if registered.is_file():
                result = read_ref(file_ref(registered))
        elif op['kind'] == 'authorize':
            row = self._backfill(spec, state)
            if json.loads(row['authorization_json'] or '{}') == op['intent_value']['authorization']:
                result = {'binding_uuid': row['binding_uuid'], 'recovered': True}
        elif op['kind'] == 'attach':
            candidate = self.candidate_reader(spec['candidate_id'])
            if candidate['publish_id']:
                folder = self.workspace.accounts.evidence / 'publication_handoffs'
                matches = []
                for file in folder.glob('HANDOFF_*.json'):
                    value = read_ref(file_ref(file))
                    if value.get('candidate_id') == spec['candidate_id'] and value.get('command_id') == spec['original_publish_command_id']:
                        matches.append(file_ref(file))
                if len(matches) == 1:
                    result = matches[0]
        if result is None:
            state['reason'] = 'effect_receipt_unresolved_no_redispatch'
            return self._save(state)
        op['receipt'] = _write(path, result, immutable=True)
        return self._finish(spec, state, op, result)

    def step(self):
        with _lock(self.directory):
            spec, state = self._load()
            if state['phase'] in TERMINAL:
                return state
            if state['phase'] == 'waiting_publication':
                original = self.command_reader(spec['original_publish_command_id'])
                if original['state'] != 'succeeded':
                    return state  # No new verification, publication, or recovery request.
                try:
                    receipt = self._original_receipt(spec)
                except ValueError as error:
                    if str(error) != 'original_publication_not_verified':
                        raise
                    return state
                state.update(publication=receipt, phase='need_metadata')
                return self._save(state)
            if self._original_receipt(spec) != state['publication']:
                raise ValueError('continuation_original_verified_publication_changed')
            if state['phase'] == 'effect_pending':
                return self._recover(spec, state)
            if state['phase'] == 'need_metadata':
                try:
                    state['publication_time'] = self._time(spec, state)
                except ValueError as error:
                    if str(error) != 'verified_publication_metadata_required':
                        raise
                    return self._effect(spec, state, 'metadata',
                        {'metadata_key': 'h3-publication-metadata:' + spec['original_publish_command_id'] + ':' + state['publication']['post_id']},
                        lambda: self.workspace.request_publication_metadata(spec['candidate_id']))
                state['phase'] = 'need_attach'
                return self._save(state)
            if state['phase'] == 'waiting_metadata':
                command = self._command(spec, state['operations'][-1], state['metadata_command_id'])
                if command['state'] in LIVE:
                    return state
                if command['state'] != 'succeeded':
                    state.update(phase='blocked', reason='original_metadata_read_failed')
                else:
                    state.update(publication_time=self._time(spec, state), phase='need_attach')
                return self._save(state)
            if state['phase'] == 'need_attach':
                return self._effect(spec, state, 'attach', {'metadata_command_id': state['metadata_command_id']},
                    lambda: self.workspace.attach_publication(spec['candidate_id'], spec['original_publish_command_id'],
                                                              metadata_command_id=state['metadata_command_id']))
            if state['phase'] == 'need_sync':
                return self._effect(spec, state, 'sync', {},
                    lambda: self.workspace.sync(spec['resource_binding']['resource_id'], snapshot_version='v2'))
            if state['phase'] == 'waiting_sync':
                command = self._command(spec, state['operations'][-1], state['operations'][-1]['command_id'])
                if command['state'] in LIVE:
                    return state
                if command['state'] != 'succeeded' or not command.get('result', {}).get('promotion_snapshot'):
                    state.update(phase='blocked', reason='original_native_sync_failed')
                else:
                    state['promotion_snapshot'] = command['result']['promotion_snapshot']
                    self._snapshot(spec, state)
                    state['phase'] = 'need_prepare'
                return self._save(state)
            if state['phase'] == 'need_prepare':
                self._snapshot(spec, state)
                if self.workspace.latest_snapshot(spec['resource_binding']['resource_id']) != state['promotion_snapshot']:
                    raise ValueError('continuation_original_fresh_snapshot_replaced')
                directory = str(self.directory / 'backfill_preparation')
                return self._effect(spec, state, 'prepare', {'output_directory': directory},
                    lambda: self.workspace.prepare_backfill(state['publication_handoff'], spec['resource_binding']['resource_id'],
                        spec['official_template']['path'], directory))
            if state['phase'] == 'need_authorize':
                row = self._backfill(spec, state)
                # Re-validate the original date after preparation; never use now.
                if self._time(spec, state) != state['publication_time']:
                    raise ValueError('continuation_original_publication_time_changed')
                statement = canonical(dict(schema='fanqie_backfill_exact_manifest_authorization/v1',
                    original_authorization=spec['original_authorization'], candidate_id=spec['candidate_id'],
                    original_publish_command_id=spec['original_publish_command_id'],
                    binding_uuid=row['binding_uuid'], manifest_sha256=row['manifest_sha'],
                    manifest_file=state['preparation']['manifest'], publication=state['publication'],
                    publication_time=state['publication_time'], promotion_subject=json.loads(row['contract_json'])['promotion_subject']))
                auth = {'manifest_sha256': row['manifest_sha'], 'reference': statement}
                return self._effect(spec, state, 'authorize', {'binding_uuid': row['binding_uuid'], 'authorization': auth},
                    lambda: self.workspace.authorize_backfill(row['binding_uuid'], manifest_sha256=row['manifest_sha'], user_statement=statement))
            if state['phase'] == 'need_dispatch':
                row = self._backfill(spec, state)
                return self._effect(spec, state, 'dispatch',
                    {'binding_uuid': row['binding_uuid'], 'manifest_sha256': row['manifest_sha'], 'business_key': row['business_key']},
                    lambda: self.workspace.dispatch_backfill(row['binding_uuid']))
            if state['phase'] in {'waiting_dispatch', 'waiting_reconcile', 'need_reconcile'}:
                row = self._backfill(spec, state)
                if row['status'] == 'confirmed':
                    state.update(phase='confirmed', confirmed=True)
                    return self._save(state)
                if state['phase'] != 'need_reconcile':
                    command = self._command(spec, state['operations'][-1], state['operations'][-1]['command_id'])
                    if command['state'] in {'queued', 'running', 'paused', 'waiting_human'}:
                        return state
                    if command['state'] == 'outcome_unknown':
                        # A hard-lost executor is different from a completed
                        # handler whose separately persisted business is unknown.
                        # The original broker fence must finish/reconcile first.
                        state['reason'] = 'original_executor_unknown_preserved_no_new_command'
                        return self._save(state)
                    if row['status'] not in {'upload_started', 'uploaded', 'submit_started', 'outcome_unknown', 'accepted', 'verify_pending'}:
                        state.update(phase='blocked', reason='original_backfill_did_not_reach_reconcilable_state')
                        return self._save(state)
                    state['phase'] = 'need_reconcile'
                    if state['operations'][-1]['kind'] == 'reconcile':
                        state['next_reconcile_at'] = command['updated_at'] + RECONCILE_INTERVAL
                        return self._save(state)
                if state['reconciliations'] >= MAX_RECONCILIATIONS or self.clock() < state['next_reconcile_at']:
                    state['reason'] = ('read_only_reconciliation_exhausted' if state['reconciliations'] >= MAX_RECONCILIATIONS
                                       else 'waiting_original_reconciliation_interval')
                    return self._save(state)
                return self._effect(spec, state, 'reconcile',
                    {'binding_uuid': row['binding_uuid'], 'manifest_sha256': row['manifest_sha'], 'business_key': row['business_key']},
                    lambda: self.workspace.reconcile_backfill(spec['resource_binding']['resource_id'], row['binding_uuid'], row['manifest_sha']))
            raise ValueError('continuation_state_unknown')
