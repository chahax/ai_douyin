"""Governed backfill execution over the authoritative P0 ledger.

No automatic production registration: a managed Fanqie resource/probe must be
installed first. Retries here are read-only reconciliation, never resubmission.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .fanqie_backfill_workflow import (
    BackfillBinding, BackfillBlocked, digest, read_publication, validate_snapshot, validate_workbook,
)
from .publication_time_evidence_v1 import verify_publication_time

CONTRACT_V2 = 'fanqie_backfill_contract/v2'
V2_TEXT_FIELDS = ('fanqie_resource_id', 'fanqie_binding_version', 'platform_task_id', 'alias_id',
    'promotion_path', 'account_link_version', 'identity_evidence', 'publication_metadata_evidence',
    'book_id', 'douyin_account_uuid', 'douyin_account_key', 'douyin_binding_version',
    'publication_command_id', 'post_id', 'publish_url')


def _require(ok, code):
    if not ok:
        raise BackfillBlocked(code)


def _read_ref(ref):
    _require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'exact_backfill_evidence_binding_required')
    path = Path(ref['path'])
    _require(path.is_absolute() and path.is_file(), 'backfill_evidence_missing')
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'backfill_evidence_changed')
    if path.suffix.lower() != '.json':
        return raw
    value = json.loads(raw)
    _require(isinstance(value, dict), 'backfill_evidence_object_required')
    return value


def _stable_row(row, contract):
    for field in ('alias_id', 'promotion_path', 'platform_task_id'):
        _require(row.get(field) == contract[field], 'stable_promotion_identity_or_path_missing:' + field)
    _require(row.get('stable_identity_status') == 'verified', 'promotion_identity_requires_sync')
    evidence = row.get('stable_identity_evidence', {})
    for field in ('alias_id', 'promotion_path', 'platform_task_id'):
        sources = evidence.get(field)
        _require(isinstance(sources, list) and sources and all(s.get('value') == row[field]
            and s.get('kind') in {'dom_attribute', 'dom_column', 'href_query', 'platform_response'}
            for s in sources), 'explicit_native_promotion_identity_evidence_required:' + field)


def _promotion_ref(reference):
    from src.operations_accounts.fanqie_managed_promotion_v1 import validate_snapshot as validate_standard_snapshot
    from src.operations_accounts.browser_control import BrowserControlRejected
    snapshot = _read_ref(reference)
    try:
        validate_standard_snapshot(snapshot)
    except (BrowserControlRejected, ValueError, KeyError, TypeError) as error:
        raise BackfillBlocked('promotion_snapshot_raw_subject_or_rows_changed') from error
    return snapshot


def _v2_publication_inputs(ledger, browser_db, binding, manifest, contract, row):
    _require(contract.get('schema') == CONTRACT_V2 and all(isinstance(contract.get(k), str)
        and contract[k].strip() for k in V2_TEXT_FIELDS) and type(contract.get('video_job_id')) is int,
        'complete_backfill_v2_contract_required')
    _require(contract['book_id'] == binding.book_id
        and contract['douyin_account_uuid'] == binding.douyin_account_uuid
        and contract['douyin_binding_version'] == binding.binding_version
        and contract['publication_command_id'] == binding.publication_command_id
        and contract['post_id'] == manifest['publication']['post_id']
        and contract['publish_url'] == manifest['publication']['publish_url'], 'backfill_v2_subject_mismatch')
    media = contract['media']; _read_ref(media)
    metadata = _read_ref(contract['publication_evidence'])
    _require(metadata.get('schema') == 'fanqie_h3_publication_evidence/v1'
        and metadata.get('command_id') == binding.publication_command_id
        and metadata.get('media') == media and metadata.get('book_id') == binding.book_id
        and metadata.get('post_id') == contract['post_id'] and metadata.get('publish_url') == contract['publish_url']
        and metadata.get('account_uuid') == binding.douyin_account_uuid
        and metadata.get('account_key') == contract['douyin_account_key']
        and metadata.get('binding_version') == binding.binding_version,
        'publication_metadata_subject_mismatch')
    _require(contract['publication_metadata_evidence'] == contract['publication_evidence']['path'],
        'publication_metadata_reference_changed')
    promotion = _promotion_ref(contract['promotion_evidence'])
    _require(promotion.get('schema') == 'fanqie_promotion_snapshot/v1'
        and promotion.get('resource_id') == contract['fanqie_resource_id']
        and promotion.get('binding_version') == contract['fanqie_binding_version']
        and promotion.get('platform_identity_key') == binding.fanqie_account
        and promotion.get('identity_verified') is True and promotion.get('challenge') is False
        and promotion.get('table_ready') is True and promotion.get('pagination_complete') is True,
        'promotion_evidence_subject_mismatch')
    _read_ref(promotion['evidence_ref'])
    _require(contract['identity_evidence'] == promotion['evidence_ref']['path'], 'identity_reference_changed')
    matches = [r for r in promotion.get('rows', []) if r.get('book_id') == binding.book_id
        and r.get('alias') == binding.alias and r.get('publish_type') == binding.publish_type]
    _require(len(matches) == 1, 'promotion_evidence_row_ambiguous')
    _stable_row(matches[0], contract)
    with sqlite3.connect(Path(ledger.path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        record = db.execute('''SELECT t.id task_id,t.platform_task_id,t.promotion_alias,t.publish_type,
            b.fanqie_book_id,p.id publish_id,p.status,p.video_job_id,p.douyin_video_id,p.douyin_video_url,
            j.task_id video_task_id,j.output_path,j.output_sha256,a.account_uuid,a.account_key
            FROM fanqie_publish_records p JOIN fanqie_promotion_tasks t ON p.task_id=t.id
            JOIN fanqie_books b ON b.id=t.book_id JOIN fanqie_video_jobs j ON j.id=p.video_job_id
            JOIN fanqie_douyin_accounts a ON a.id=p.douyin_account_id WHERE p.id=?''', (row['publish_id'],)).fetchone()
    _require(record is not None and record['status'] == 'published'
        and record['task_id'] == row['task_id'] == record['video_task_id']
        and record['video_job_id'] == contract['video_job_id']
        and str(record['fanqie_book_id']) == binding.book_id
        and record['platform_task_id'] == contract['platform_task_id']
        and record['promotion_alias'] == binding.alias and record['publish_type'] == binding.publish_type
        and record['douyin_video_id'] == contract['post_id'] and record['douyin_video_url'] == contract['publish_url']
        and record['account_uuid'] == binding.douyin_account_uuid
        and record['account_key'] == contract['douyin_account_key']
        and Path(record['output_path']).resolve() == Path(media['path']).resolve()
        and record['output_sha256'].lower() == media['sha256'].lower(), 'ledger_publication_media_account_task_mismatch')
    with sqlite3.connect(Path(browser_db).resolve().as_uri() + '?mode=ro', uri=True) as db:
        raw = db.execute('SELECT payload,result FROM browser_control_commands WHERE command_id=?',
                         (binding.publication_command_id,)).fetchone()
    _require(raw is not None, 'original_publication_payload_missing')
    payload = json.loads(raw[0]); request = payload.get('request', {})
    _require(payload.get('video_sha256') == media['sha256']
        and Path(request.get('video_path', '')).resolve() == Path(media['path']).resolve(),
        'original_publication_media_SHA_mismatch')
    _require(metadata.get('request_sha256') == digest(payload), 'original_publication_metadata_changed')
    try:
        time_evidence = verify_publication_time(browser_db, metadata['time_evidence'])
    except (ValueError, KeyError, TypeError) as error:
        raise BackfillBlocked('verified_original_publication_time_required') from error
    _require(time_evidence['publication_command_id'] == binding.publication_command_id
        and time_evidence['account_uuid'] == binding.douyin_account_uuid
        and time_evidence['binding_version'] == binding.binding_version
        and time_evidence['post_id'] == contract['post_id']
        and time_evidence['published_at'] == metadata.get('published_at'), 'publication_time_subject_mismatch')
    try:
        published = datetime.fromisoformat(time_evidence['published_at'].replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as error:
        raise BackfillBlocked('verified_original_publication_date_required') from error
    _require(published.tzinfo is not None and binding.published_date == published.astimezone(
        timezone(timedelta(hours=8))).strftime('%Y/%m/%d'), 'original_publication_date_mismatch')


class BackfillCoordinator:
    def __init__(self, ledger, browser_db, *, require_strict_contract=False):
        self.ledger, self.browser_db = ledger, browser_db
        self.require_strict_contract = require_strict_contract

    def _inputs(self, binding_uuid):
        row = self.ledger.get(binding_uuid)
        manifest = json.loads(row["manifest_json"])
        binding = BackfillBinding(**manifest["binding"])
        if digest(manifest) != row["manifest_sha"]:
            raise BackfillBlocked("registered_preparation_changed")
        validate_workbook(manifest)
        if read_publication(self.browser_db, binding) != manifest["publication"]:
            raise BackfillBlocked("original_publication_evidence_changed")
        contract = json.loads(row['contract_json'])
        if contract.get('schema') == 'fanqie_backfill_contract/v3':
            from .fanqie_backfill_native_v3 import validate_inputs
            validate_inputs(self.ledger, self.browser_db, binding, manifest, contract, row)
        elif self.require_strict_contract or contract.get('schema') == CONTRACT_V2:
            _v2_publication_inputs(self.ledger, self.browser_db, binding, manifest, contract, row)
        return row, manifest, binding, contract

    def _observe(self, adapter, binding, contract, *, require_active=True):
        if contract.get('schema') == 'fanqie_backfill_contract/v3':
            from .fanqie_backfill_native_v3 import observe
            return observe(adapter, binding, contract, require_active=require_active)
        snapshot = adapter.observe(binding)
        row = validate_snapshot(binding, snapshot, require_active=require_active)
        # A text alias alone cannot identify a production promotion task.
        if row.get("alias_id") != contract["alias_id"] or row.get("promotion_path") != contract["promotion_path"]:
            raise BackfillBlocked("stable_promotion_identity_or_path_missing")
        if self.require_strict_contract or contract.get('schema') == CONTRACT_V2:
            _stable_row(row, contract)
        return row

    def inspect(self, binding_uuid):
        """Read-only status with full internal input/publication validation."""
        row, manifest, binding, contract = self._inputs(binding_uuid)
        result = dict(binding_uuid=binding_uuid, status=row['status'], revision=row['revision'],
            manifest_sha256=row['manifest_sha'], book_id=binding.book_id,
            platform_task_id=contract.get('platform_task_id'), post_id=manifest['publication']['post_id'],
            publish_url=manifest['publication']['publish_url'], inputs_verified=True,
            confirmed=row['status'] == 'confirmed',
            requires_read_only_reconciliation=row['status'] in
                {'outcome_unknown', 'accepted', 'verify_pending', 'upload_started', 'uploaded', 'submit_started'},
            external_actions_performed=False)
        if contract.get('schema') == 'fanqie_backfill_contract/v3':
            result.update(native_identity=contract['native_identity'], promotion_subject=contract['promotion_subject'])
        return result

    def execute(self, binding_uuid, *, adapter, guard):
        row, manifest, binding, contract = self._inputs(binding_uuid)
        if row["status"] != "ready" or not row["authorization_json"]:
            raise BackfillBlocked("original_backfill_not_ready_no_replay")
        # guard is an application-owned managed resource, not a request argument.
        guard.check(contract)
        current = self._observe(adapter, binding, contract)
        url = manifest["publication"]["publish_url"]
        if url in current.get("published_links", []):
            return self.ledger.transition(binding_uuid, row["revision"], "confirmed", {
                "post_id": manifest["publication"]["post_id"], "publish_url": url,
                "source": "existing_exact_task_readback", "submitted_by_this_attempt": False})
        if current.get("published_links"):
            raise BackfillBlocked('capability_missing:append_to_populated_promotion_not_verified')
        if current.get("fill_status") != "未填写":
            raise BackfillBlocked("existing_backfill_requires_reconciliation")
        row = self.ledger.transition(binding_uuid, row["revision"], "upload_started", {})
        try:
            upload = adapter.upload(manifest["workbook"], binding)
            if not isinstance(upload, dict) or upload.get("upload_ready") is not True:
                raise BackfillBlocked("upload_readiness_unverified")
            # UI readiness is recorded separately from batch acceptance.
            row = self.ledger.transition(binding_uuid, row["revision"], "uploaded", upload)
            guard.check(contract)
            current = self._observe(adapter, binding, contract)
            if current.get("published_links") or current.get("fill_status") != "未填写":
                row = self.ledger.transition(binding_uuid, row["revision"], "failed_known", {"reason": "promotion_changed_before_submit", "submitted": False})
                return row
            row = self.ledger.transition(binding_uuid, row["revision"], "submit_started", {})
            accepted = adapter.submit(binding)
            if isinstance(accepted, dict) and accepted.get("accepted") is True and accepted.get("batch_id"):
                row = self.ledger.transition(binding_uuid, row["revision"], "accepted", {"batch_id": accepted["batch_id"]})
            guard.check(contract)
            current = self._observe(adapter, binding, contract)
            if url in current.get("published_links", []):
                row = self.ledger.transition(binding_uuid, row["revision"], "confirmed", {"post_id": manifest["publication"]["post_id"], "publish_url": url, "source": "exact_task_readback"})
            else:
                state = "verify_pending" if row["status"] == "accepted" else "outcome_unknown"
                row = self.ledger.transition(binding_uuid, row["revision"], state, {"reason": "exact_link_not_yet_observed"})
        except Exception as exc:
            # CAS failure or disk error must not overwrite another executor's
            # progress. A hard crash leaves the durable *_started stage intact.
            row = self.ledger.transition(binding_uuid, row["revision"], "outcome_unknown", {"error_type": type(exc).__name__})
        return row

    def reconcile(self, binding_uuid, *, adapter, guard):
        row, manifest, binding, contract = self._inputs(binding_uuid)
        if row["status"] == "confirmed":
            return row
        if row["status"] not in {"ready", "outcome_unknown", "accepted", "verify_pending", "submit_started", "upload_started", "uploaded"}:
            raise BackfillBlocked("backfill_not_reconcilable")
        guard.check(contract)
        current = self._observe(adapter, binding, contract, require_active=False)
        url = manifest["publication"]["publish_url"]
        if url not in current.get("published_links", []):
            return row  # absence on one page is never proof of no submission
        if row["status"] in {"upload_started", "uploaded"}:
            row = self.ledger.transition(binding_uuid, row["revision"], "outcome_unknown", {"reason": "independent_readback_after_interruption"})
        return self.ledger.transition(binding_uuid, row["revision"], "confirmed", {
            "post_id": manifest["publication"]["post_id"], "publish_url": url,
            "source": "readonly_reconciliation"})


def prepare_registered_backfill(ledger, browser_db, *, publication_handoff_binding,
        accounts, resource_id, promotion_snapshot_binding, official_template, output_directory):
    """Build and register one exact post workbook; never authorize or dispatch.

    IDs, media, publication date and account come from the verified publication
    handoff/current repositories. No caller-written contract or default identity.
    """
    from .fanqie_backfill_workflow import prepare
    handoff = _read_ref(publication_handoff_binding)
    if handoff.get('schema') == 'fanqie_h3_publication_handoff/v2':
        from .fanqie_backfill_native_v3 import prepare_registered
        return prepare_registered(ledger, browser_db, publication_handoff_binding=publication_handoff_binding,
            accounts=accounts, resource_id=resource_id, promotion_snapshot_binding=promotion_snapshot_binding,
            official_template=official_template, output_directory=output_directory)
    _require(handoff.get('schema') == 'fanqie_h3_publication_handoff/v1', 'verified_publication_handoff_required')
    required = ('candidate_id', 'task_id', 'publish_id', 'video_job_id', 'book_id', 'media',
        'command_id', 'account_uuid', 'account_key', 'binding_version', 'published_at',
        'post_id', 'publish_url', 'publication_evidence')
    _require(all(k in handoff for k in required), 'publication_handoff_fields_missing')
    metadata = _read_ref(handoff['publication_evidence']); _read_ref(handoff['media'])
    _require(handoff.get('time_evidence') == metadata.get('time_evidence'), 'publication_handoff_time_evidence_mismatch')
    try:
        time_evidence = verify_publication_time(browser_db, metadata['time_evidence'])
    except (ValueError, KeyError, TypeError) as error:
        raise BackfillBlocked('verified_original_publication_time_required') from error
    _require(time_evidence['published_at'] == handoff['published_at'], 'handoff_publication_date_changed')
    env = accounts.get(resource_id)
    linked = accounts.check_association(env)
    identity = accounts.bindings().get(resource_id)
    _require(identity and identity.get('status') == 'active'
        and linked['account_uuid'] == handoff['account_uuid']
        and linked['account_key'] == handoff['account_key'], 'publication_not_linked_to_fanqie_environment')
    snapshot = _promotion_ref(promotion_snapshot_binding)
    _require(snapshot.get('schema') == 'fanqie_promotion_snapshot/v1'
        and snapshot.get('resource_id') == resource_id
        and snapshot.get('binding_version') == env['binding_version']
        and snapshot.get('platform_identity_key') == identity['platform_identity_key']
        and snapshot.get('environment_key') == env['environment_key']
        and snapshot.get('identity_verified') is True and snapshot.get('challenge') is False
        and snapshot.get('table_ready') is True and snapshot.get('pagination_complete') is True
        and isinstance(snapshot.get('observed_at'), (int, float))
        and 0 <= time.time() - snapshot['observed_at'] <= 60, 'fresh_bound_promotion_snapshot_required')
    _read_ref(snapshot['evidence_ref'])
    with sqlite3.connect(Path(ledger.path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        task = db.execute('SELECT * FROM fanqie_promotion_tasks WHERE id=?', (handoff['task_id'],)).fetchone()
    _require(task is not None and task['publish_type'] == 'AIGC', 'original_AIGC_promotion_task_required')
    matches = [r for r in snapshot['rows'] if r.get('book_id') == handoff['book_id']
        and r.get('alias') == task['promotion_alias'] and r.get('platform_task_id') == task['platform_task_id']]
    _require(len(matches) == 1, 'exact_platform_task_not_unique')
    promotion = matches[0]
    _require(promotion.get('publish_type') == 'AIGC' and promotion.get('alias_status') == '生效中'
        and promotion.get('book_status') == '可用', 'current_promotion_not_active_AIGC')
    with sqlite3.connect(Path(accounts.douyin_db).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        account = db.execute('SELECT public_uid FROM account_runtime_bindings WHERE account_uuid=? AND account_key=? AND status=?',
            (handoff['account_uuid'], handoff['account_key'], 'active')).fetchone()
    _require(account and isinstance(account['public_uid'], str) and account['public_uid'].strip(),
        'verified_douyin_display_id_requires_sync')
    try:
        instant = datetime.fromisoformat(handoff['published_at'].replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as error:
        raise BackfillBlocked('verified_original_publication_date_required') from error
    _require(instant.tzinfo is not None, 'publication_date_timezone_required')
    date = instant.astimezone(timezone(timedelta(hours=8))).strftime('%Y/%m/%d')
    binding = BackfillBinding(identity['platform_identity_key'], handoff['account_uuid'],
        handoff['binding_version'], handoff['command_id'], handoff['book_id'], task['promotion_alias'],
        account['public_uid'], date, 'AIGC')
    publication = read_publication(browser_db, binding)
    _require(publication['post_id'] == handoff['post_id'] and publication['publish_url'] == handoff['publish_url'],
        'handoff_original_post_mismatch')
    contract = dict(schema=CONTRACT_V2, fanqie_resource_id=resource_id,
        fanqie_binding_version=env['binding_version'], platform_task_id=promotion.get('platform_task_id'),
        alias_id=promotion.get('alias_id'), promotion_path=promotion.get('promotion_path'),
        account_link_version=env['douyin_binding_sha256'], identity_evidence=snapshot['evidence_ref']['path'],
        publication_metadata_evidence=handoff['publication_evidence']['path'], book_id=handoff['book_id'],
        douyin_account_uuid=handoff['account_uuid'], douyin_account_key=handoff['account_key'],
        douyin_binding_version=handoff['binding_version'], publication_command_id=handoff['command_id'],
        post_id=publication['post_id'], publish_url=publication['publish_url'],
        video_job_id=handoff['video_job_id'], media=handoff['media'],
        promotion_evidence=promotion_snapshot_binding, publication_evidence=handoff['publication_evidence'])
    _stable_row(promotion, contract)
    directory = Path(output_directory).resolve()
    _require(directory.is_relative_to(Path(__file__).resolve().parents[2] / 'data'), 'preparation_output_must_be_project_data')
    # Existing output is preserved. Registration itself deduplicates the post.
    _require(not directory.exists(), 'existing_preparation_preserved')
    manifest = prepare(binding, browser_db, official_template, directory)
    _v2_publication_inputs(ledger, browser_db, binding, manifest, contract,
                          dict(task_id=handoff['task_id'], publish_id=handoff['publish_id']))
    contract_path = directory / 'contract.json'
    with contract_path.open('x', encoding='utf-8') as stream:
        json.dump(contract, stream, ensure_ascii=False, indent=2)
    binding_uuid = ledger.register(handoff['task_id'], handoff['publish_id'], manifest, contract)
    result = dict(schema='fanqie_registered_backfill_preparation/v1', binding_uuid=binding_uuid,
        task_id=handoff['task_id'], publish_id=handoff['publish_id'], publication_handoff=publication_handoff_binding,
        manifest=dict(path=str(directory / 'manifest.json'), sha256=hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest()),
        contract=dict(path=str(contract_path), sha256=hashlib.sha256(contract_path.read_bytes()).hexdigest()),
        status='prepared_not_authorized', external_actions_performed=False, submitted=False)
    with (directory / 'REGISTERED.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result
