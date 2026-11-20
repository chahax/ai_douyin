"""Native-alias backfill contracts; legacy dual-ID v2 remains separate.

All platform meaning comes from the shared snapshot/subject parser. This module
never turns alias IDs into task IDs, invents a promotion path, or opens browsers.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .fanqie_backfill_workflow import BackfillBinding, BackfillBlocked, digest, read_publication
from .publication_time_evidence_v1 import verify_publication_time

CONTRACT_V3 = 'fanqie_backfill_contract/v3'
HANDOFF_V2 = 'fanqie_h3_publication_handoff/v2'
PUBLICATION_V2 = 'fanqie_h3_publication_evidence/v2'
SNAPSHOT_V2 = 'fanqie_promotion_snapshot/v2'
TEXT_FIELDS = ('fanqie_resource_id', 'fanqie_binding_version', 'account_link_version',
    'identity_evidence', 'publication_metadata_evidence', 'book_id',
    'douyin_account_uuid', 'douyin_account_key', 'douyin_binding_version',
    'publication_command_id', 'post_id', 'publish_url', 'native_identity_scope')
SUBJECT_FIELDS = ('native_identity', 'native_identity_scope', 'promotion_subject')


def require(ok, code):
    if not ok:
        raise BackfillBlocked(code)


def read_ref(ref, *, json_content=True):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'exact_backfill_evidence_binding_required')
    p = Path(ref['path'])
    require(p.is_absolute() and p.is_file(), 'backfill_evidence_missing')
    if not json_content:
        with p.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(actual == ref['sha256'], 'backfill_evidence_changed')
        return str(p)
    raw = p.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'backfill_evidence_changed')
    return json.loads(raw) if p.suffix.lower() == '.json' else raw


def snapshot_ref(ref, *, fresh=False, publishable=False):
    from .fanqie_promotion_identity_v2 import validate_snapshot
    snapshot = read_ref(ref)
    require(snapshot.get('schema') == SNAPSHOT_V2, 'native_alias_snapshot_v2_required')
    try:
        validate_snapshot(snapshot, require_fresh=fresh, require_publishable=publishable)
    except (ValueError, KeyError, TypeError) as exc:
        raise BackfillBlocked('native_alias_snapshot_invalid') from exc
    return snapshot


def _identified_rows(snapshot):
    for row in snapshot['rows']:
        if row.get('identity_status') == 'pending' and not row.get('native_record_id'):
            continue
        yield row


def matching_row(snapshot, contract):
    from .fanqie_promotion_identity_v2 import native_identity, authorization_subject
    matches = [row for row in _identified_rows(snapshot)
        if native_identity(snapshot, row) == contract['native_identity']]
    require(len(matches) == 1, 'native_alias_record_missing_or_ambiguous')
    row = matches[0]
    require(authorization_subject(snapshot, row) == contract['promotion_subject'],
            'native_alias_authorization_subject_changed')
    return row


def verify_task(ledger_path, task_id, snapshot, row, contract):
    from .fanqie_h3_candidate_v1 import CandidateLedger
    from .fanqie_promotion_identity_v2 import native_identity, native_identity_scope, authorization_subject
    expected = {'task_id': task_id, 'native_identity': native_identity(snapshot, row),
        'native_identity_scope': native_identity_scope(snapshot, row),
        'promotion_subject': authorization_subject(snapshot, row)}
    require(all(contract.get(k) == expected[k] for k in SUBJECT_FIELDS), 'native_contract_subject_mismatch')
    try:
        actual = CandidateLedger(ledger_path).verify_native_task(task_id, snapshot=snapshot, row=row)
    except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise BackfillBlocked('native_P0_task_mapping_invalid') from exc
    require(actual == expected, 'native_P0_task_mapping_changed')
    return actual


def validate_registration(ledger_path, task_id, manifest, contract):
    require(contract.get('schema') == CONTRACT_V3 and all(isinstance(contract.get(k), str)
        and contract[k].strip() for k in TEXT_FIELDS) and type(contract.get('video_job_id')) is int,
        'complete_backfill_v3_contract_required')
    require(not {'platform_task_id', 'promotion_path', 'alias_id'} & set(contract),
            'native_contract_cannot_borrow_legacy_dual_ID_fields')
    require(manifest.get('promotion_contract_schema') == CONTRACT_V3
        and all(manifest.get(k) == contract.get(k) for k in SUBJECT_FIELDS),
        'native_manifest_version_or_subject_mismatch')
    read_ref(manifest['base_preparation'])
    snapshot = snapshot_ref(contract['promotion_evidence'])
    require(snapshot['resource_id'] == contract['fanqie_resource_id']
        and snapshot['binding_version'] == contract['fanqie_binding_version']
        and snapshot['platform_identity_key'] == manifest['binding']['fanqie_account'],
        'native_snapshot_account_or_environment_changed')
    row = matching_row(snapshot, contract)
    from .fanqie_promotion_identity_v2 import assert_publishable
    try:
        assert_publishable(snapshot, row, now=snapshot['observed_at'])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackfillBlocked('native_preparation_was_not_publishable') from exc
    verify_task(ledger_path, task_id, snapshot, row, contract)
    return snapshot, row


def validate_inputs(ledger, browser_db, binding, manifest, contract, ledger_row):
    snapshot, promotion = validate_registration(ledger.path, ledger_row['task_id'], manifest, contract)
    require(contract['book_id'] == binding.book_id
        and contract['douyin_account_uuid'] == binding.douyin_account_uuid
        and contract['douyin_binding_version'] == binding.binding_version
        and contract['publication_command_id'] == binding.publication_command_id
        and contract['post_id'] == manifest['publication']['post_id']
        and contract['publish_url'] == manifest['publication']['publish_url'], 'backfill_v3_subject_mismatch')
    handoff = read_ref(contract['publication_handoff'])
    metadata = read_ref(contract['publication_evidence']); read_ref(contract['media'], json_content=False)
    require(handoff.get('schema') == HANDOFF_V2 and metadata.get('schema') == PUBLICATION_V2,
            'native_backfill_requires_versioned_publication_evidence')
    for key in SUBJECT_FIELDS:
        require(handoff.get(key) == metadata.get(key) == contract[key], 'native_publication_subject_changed')
    require(handoff.get('task_id') == ledger_row['task_id']
        and handoff.get('publish_id') == ledger_row['publish_id']
        and handoff.get('video_job_id') == contract['video_job_id']
        and handoff.get('publication_evidence') == contract['publication_evidence'],
        'native_publication_handoff_P0_mismatch')
    for value in (handoff, metadata):
        require(value.get('book_id') == binding.book_id and value.get('media') == contract['media']
            and value.get('command_id') == binding.publication_command_id
            and value.get('account_uuid') == binding.douyin_account_uuid
            and value.get('account_key') == contract['douyin_account_key']
            and value.get('binding_version') == binding.binding_version
            and value.get('post_id') == contract['post_id']
            and value.get('publish_url') == contract['publish_url'], 'native_publication_evidence_subject_mismatch')
    require(contract['identity_evidence'] == snapshot['evidence_ref']['path']
        and contract['publication_metadata_evidence'] == contract['publication_evidence']['path'],
        'native_backfill_evidence_reference_changed')
    with sqlite3.connect(Path(ledger.path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('''SELECT p.task_id,p.status,p.video_job_id,p.douyin_video_id,p.douyin_video_url,
            j.task_id video_task_id,j.output_path,j.output_sha256,a.account_uuid,a.account_key
            FROM fanqie_publish_records p JOIN fanqie_video_jobs j ON j.id=p.video_job_id
            JOIN fanqie_douyin_accounts a ON a.id=p.douyin_account_id WHERE p.id=?''',
            (ledger_row['publish_id'],)).fetchone()
    require(row is not None and row['status'] == 'published'
        and row['task_id'] == ledger_row['task_id'] == row['video_task_id']
        and row['video_job_id'] == contract['video_job_id']
        and row['douyin_video_id'] == contract['post_id'] and row['douyin_video_url'] == contract['publish_url']
        and row['account_uuid'] == binding.douyin_account_uuid and row['account_key'] == contract['douyin_account_key']
        and Path(row['output_path']).resolve() == Path(contract['media']['path']).resolve()
        and row['output_sha256'].lower() == contract['media']['sha256'].lower(),
        'native_ledger_publication_media_account_mismatch')
    with sqlite3.connect(Path(browser_db).resolve().as_uri() + '?mode=ro', uri=True) as db:
        original = db.execute('SELECT payload FROM browser_control_commands WHERE command_id=?',
            (binding.publication_command_id,)).fetchone()
    require(original is not None, 'original_publication_payload_missing')
    payload = json.loads(original[0])
    require(payload.get('video_sha256') == contract['media']['sha256']
        and Path(payload.get('request', {}).get('video_path', '')).resolve() == Path(contract['media']['path']).resolve()
        and metadata.get('request_sha256') == digest(payload), 'native_original_publication_media_or_metadata_changed')
    try:
        clock = verify_publication_time(browser_db, metadata['time_evidence'])
        instant = datetime.fromisoformat(clock['published_at'].replace('Z', '+00:00'))
    except (ValueError, KeyError, TypeError) as exc:
        raise BackfillBlocked('verified_original_publication_time_required') from exc
    require(handoff.get('time_evidence') == metadata['time_evidence']
        and clock['publication_command_id'] == binding.publication_command_id
        and clock['account_uuid'] == binding.douyin_account_uuid
        and clock['binding_version'] == binding.binding_version
        and clock['post_id'] == contract['post_id']
        and clock['published_at'] == handoff.get('published_at') == metadata.get('published_at')
        and instant.tzinfo is not None and binding.published_date == instant.astimezone(
            timezone(timedelta(hours=8))).strftime('%Y/%m/%d'), 'native_original_publication_date_mismatch')
    return snapshot, promotion


def observe(adapter, binding, contract, *, require_active=True):
    from .fanqie_promotion_identity_v2 import validate_snapshot, assert_publishable
    snapshot = adapter.observe(binding)
    require(snapshot.get('schema') == SNAPSHOT_V2, 'fresh_native_snapshot_v2_required')
    try:
        validate_snapshot(snapshot, require_fresh=True)
        row = matching_row(snapshot, contract)
        if require_active:
            assert_publishable(snapshot, row)
    except (ValueError, KeyError, TypeError) as exc:
        raise BackfillBlocked('fresh_native_alias_observation_invalid') from exc
    prepared = snapshot_ref(contract['promotion_evidence'])
    require(all(snapshot.get(k) == prepared.get(k) for k in
        ('resource_id', 'binding_version', 'platform_identity_key', 'environment_key')),
        'fresh_native_observation_wrong_environment')
    require(row['book_id'] == binding.book_id and row['alias'] == binding.alias
        and row['publish_type'] == binding.publish_type, 'fresh_native_alias_book_type_mismatch')
    return row


class NativeSnapshotAdapter:
    """Fresh evidence provider owns a separate tab; batch form is untouched."""
    def __init__(self, base, snapshot_provider, *, readonly=False):
        self.base, self.snapshot_provider, self.readonly = base, snapshot_provider, readonly
        self.observations, self.previous = 0, None

    def observe(self, binding):
        self.base._check(binding)
        phase = ('reconcile' if self.readonly else 'preflight' if self.observations == 0
                 else 'pre_submit' if self.observations == 1 else 'post_submit')
        reference = self.snapshot_provider(phase=phase,
            force_refresh=self.readonly or self.observations > 0)
        require(reference != self.previous, 'native_observation_evidence_not_refreshed')
        snapshot = snapshot_ref(reference, fresh=True)
        self.previous, self.observations = reference, self.observations + 1
        return snapshot

    def upload(self, workbook, binding):
        return self.base.upload(workbook, binding)

    def submit(self, binding):
        return self.base.submit(binding)


def prepare_registered(ledger, browser_db, *, publication_handoff_binding, accounts,
                       resource_id, promotion_snapshot_binding, official_template, output_directory):
    from .fanqie_backfill_workflow import prepare
    from .fanqie_promotion_identity_v2 import native_identity, native_identity_scope, authorization_subject, assert_publishable
    handoff = read_ref(publication_handoff_binding)
    require(handoff.get('schema') == HANDOFF_V2, 'native_publication_handoff_v2_required')
    metadata = read_ref(handoff['publication_evidence']); read_ref(handoff['media'], json_content=False)
    require(metadata.get('schema') == PUBLICATION_V2, 'native_publication_evidence_v2_required')
    env = accounts.get(resource_id); linked = accounts.check_association(env)
    identity = accounts.bindings().get(resource_id)
    require(identity and identity.get('status') == 'active'
        and linked['account_uuid'] == handoff['account_uuid']
        and linked['account_key'] == handoff['account_key'], 'publication_not_linked_to_fanqie_environment')
    snapshot = snapshot_ref(promotion_snapshot_binding, fresh=True)
    require(snapshot['resource_id'] == resource_id and snapshot['binding_version'] == env['binding_version']
        and snapshot['platform_identity_key'] == identity['platform_identity_key']
        and snapshot['environment_key'] == env['environment_key'], 'fresh_bound_native_snapshot_required')
    matches = [r for r in _identified_rows(snapshot) if native_identity(snapshot, r) == handoff.get('native_identity')]
    require(len(matches) == 1, 'native_publication_alias_missing_or_ambiguous')
    promotion = matches[0]
    try:
        assert_publishable(snapshot, promotion)
    except (ValueError, KeyError, TypeError) as exc:
        raise BackfillBlocked('current_native_alias_not_publishable') from exc
    subject = authorization_subject(snapshot, promotion)
    native = native_identity(snapshot, promotion); scope = native_identity_scope(snapshot, promotion)
    require(subject == handoff.get('promotion_subject') == metadata.get('promotion_subject')
        and native == metadata.get('native_identity')
        and scope == handoff.get('native_identity_scope') == metadata.get('native_identity_scope')
        and subject['book_id'] == handoff['book_id'] and subject['publish_type'] == 'AIGC',
        'native_handoff_alias_book_type_subject_changed')
    try:
        clock = verify_publication_time(browser_db, metadata['time_evidence'])
        instant = datetime.fromisoformat(clock['published_at'].replace('Z', '+00:00'))
    except (ValueError, KeyError, TypeError) as exc:
        raise BackfillBlocked('verified_original_publication_time_required') from exc
    require(handoff.get('time_evidence') == metadata['time_evidence']
        and clock['published_at'] == handoff['published_at'] and instant.tzinfo is not None,
        'native_handoff_publication_time_changed')
    with sqlite3.connect(Path(accounts.douyin_db).resolve().as_uri() + '?mode=ro', uri=True) as db:
        record = db.execute('''SELECT public_uid FROM account_runtime_bindings
            WHERE account_uuid=? AND account_key=? AND status='active' ''',
            (handoff['account_uuid'], handoff['account_key'])).fetchall()
    require(len(record) == 1 and isinstance(record[0][0], str) and record[0][0].strip(),
            'verified_douyin_display_id_requires_sync')
    binding = BackfillBinding(identity['platform_identity_key'], handoff['account_uuid'],
        handoff['binding_version'], handoff['command_id'], handoff['book_id'], subject['alias'],
        record[0][0], instant.astimezone(timezone(timedelta(hours=8))).strftime('%Y/%m/%d'), 'AIGC')
    publication = read_publication(browser_db, binding)
    require(publication['post_id'] == handoff['post_id'] and publication['publish_url'] == handoff['publish_url'],
            'native_handoff_original_post_changed')
    contract = dict(schema=CONTRACT_V3, fanqie_resource_id=resource_id,
        fanqie_binding_version=env['binding_version'], account_link_version=env['douyin_binding_sha256'],
        identity_evidence=snapshot['evidence_ref']['path'], publication_metadata_evidence=handoff['publication_evidence']['path'],
        native_identity=native, native_identity_scope=scope, promotion_subject=subject,
        book_id=handoff['book_id'], douyin_account_uuid=handoff['account_uuid'],
        douyin_account_key=handoff['account_key'], douyin_binding_version=handoff['binding_version'],
        publication_command_id=handoff['command_id'], post_id=publication['post_id'], publish_url=publication['publish_url'],
        video_job_id=handoff['video_job_id'], media=handoff['media'], promotion_evidence=promotion_snapshot_binding,
        publication_evidence=handoff['publication_evidence'], publication_handoff=publication_handoff_binding)
    verify_task(ledger.path, handoff['task_id'], snapshot, promotion, contract)
    directory = Path(output_directory).resolve()
    require(directory.is_relative_to(Path(__file__).resolve().parents[2] / 'data') and not directory.exists(),
            'new_project_backfill_preparation_required')
    base = prepare(binding, browser_db, official_template, directory)
    base_ref = {'path': str(directory / 'manifest.json'),
                'sha256': hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest()}
    manifest = dict(base, promotion_contract_schema=CONTRACT_V3, native_identity=native,
        native_identity_scope=scope, promotion_subject=subject, base_preparation=base_ref)
    validate_inputs(ledger, browser_db, binding, manifest, contract,
                    {'task_id': handoff['task_id'], 'publish_id': handoff['publish_id']})
    manifest_path, contract_path = directory / 'manifest_v3.json', directory / 'contract_v3.json'
    for path, value in ((manifest_path, manifest), (contract_path, contract)):
        with path.open('x', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
    binding_uuid = ledger.register(handoff['task_id'], handoff['publish_id'], manifest, contract)
    result = dict(schema='fanqie_registered_backfill_preparation/v2', binding_uuid=binding_uuid,
        task_id=handoff['task_id'], publish_id=handoff['publish_id'], publication_handoff=publication_handoff_binding,
        manifest={'path': str(manifest_path), 'sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest()},
        contract={'path': str(contract_path), 'sha256': hashlib.sha256(contract_path.read_bytes()).hexdigest()},
        status='prepared_not_authorized', external_actions_performed=False, submitted=False)
    with (directory / 'REGISTERED.json').open('x', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
    return result
