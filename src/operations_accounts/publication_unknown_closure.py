"""One explicit human disposal decision; external publication remains unknown."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from .browser_control import BrowserControlRejected, _json

ROOT = Path(__file__).resolve().parents[2]
AUTH_SCHEMA = 'publication_single_retry_user_authorization/20261019/v1'
ARCHIVE_SCHEMA = 'archived_unknown_publication_lock/20261019/v1'


def _reject():
    raise BrowserControlRejected('publication_closure_invalid', '人工结清批准、原未知快照或原提交证据不匹配，未处理。')


def snapshot_sha256(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def file_reference(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        _reject()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def _bound(reference):
    if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}
            or not isinstance(reference['path'], str) or not isinstance(reference['sha256'], str)
            or file_reference(reference['path']) != reference):
        _reject()
    return Path(reference['path'])


def _json_ref(reference):
    value = json.loads(_bound(reference).read_bytes())
    if not isinstance(value, dict):
        _reject()
    return value


def validate_closure_authorization(before, authorization, *, archived_lock=None):
    value = _json_ref(authorization)
    if (value.get('schema') != AUTH_SCHEMA or value.get('decision_source') != 'explicit_user_statement'
            or not isinstance(value.get('user_statement'), str) or not value['user_statement'].strip()
            or not isinstance(value.get('approval_question'), str) or not value['approval_question'].strip()
            or value.get('operator_close_unknown_publication') is not True
            or value.get('archive_submission_lock') is not True
            or value.get('retain_original_history') is not True or value.get('original_outcome_known') is not False
            or type(value.get('additional_publication_runs')) is not int or value['additional_publication_runs'] != 1
            or type(value.get('additional_recovery_runs')) is not int or value['additional_recovery_runs'] != 0
            or value.get('new_media_authorized') is not False
            or value.get('original_command_id') != before['command_id']
            or before['kind'] != 'publish' or before['state'] != 'outcome_unknown'
            or not isinstance(before.get('result'), dict) or before['result'].get('status') != 'submission_unknown'
            or before['result'].get('post_id') or before['result'].get('publish_url')
            or value.get('account_uuid') != before['account_id']
            or value.get('account_key') != before['payload'].get('account_key')
            or value.get('video', {}).get('path') != before['payload'].get('request', {}).get('video_path')
            or value.get('video', {}).get('sha256') != before['payload'].get('video_sha256')
            or value.get('prepared', {}).get('path') != before['payload'].get('authorization', {}).get('path')
            or value.get('prepared', {}).get('sha256') != before['payload'].get('authorization', {}).get('sha256')):
        _reject()
    _bound(value['video'])
    prepared = _json_ref(value['prepared'])
    if (prepared.get('account_uuid') != value['account_uuid'] or prepared.get('account_key') != value['account_key']
            or prepared.get('video') != value['video']):
        _reject()
    report = _json_ref(value['human_report'])
    reported_snapshot = report.get('original_command_snapshot')
    if isinstance(reported_snapshot, dict) and 'task_id' not in reported_snapshot:
        reported_snapshot = dict(reported_snapshot, task_id=reported_snapshot.get('command_id'))
    if (report.get('decision_source') != 'explicit_user_statement'
            or report.get('observation_type') != 'human_report_work_not_found'
            or not report.get('user_statement') or not report.get('question')
            or report.get('account_uuid') != value['account_uuid'] or report.get('account_key') != value['account_key']
            or report.get('original_command_id') != before['command_id']
            or reported_snapshot != before):
        _reject()
    journal_path = _bound(value['journal'])
    expected_lock_path = Path(value['submission_lock']['path']).resolve()
    runs = (ROOT / 'data/publish_runs').resolve()
    if journal_path.parent != runs or expected_lock_path.parent != runs:
        _reject()
    lock = _json_ref(archived_lock or value['submission_lock'])
    if archived_lock is not None and archived_lock['sha256'] != value['submission_lock']['sha256']:
        _reject()
    if lock.get('journal') != str(journal_path) or lock.get('status') != 'submission_started':
        _reject()
    rows = [json.loads(line) for line in journal_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows or rows[0].get('stage') != 'prepared':
        _reject()
    first = rows[0]
    key = hashlib.sha256(json.dumps({'platform_identity_key': first.get('platform_identity_key'),
        'video_sha256': first.get('video_sha256')}, sort_keys=True).encode()).hexdigest()
    if (not first.get('platform_identity_key') or expected_lock_path.name != key + '.submitted.json'
            or not journal_path.name.startswith(key + '.')
            or first.get('account_uuid') != value['account_uuid'] or first.get('account') != value['account_key']
            or first.get('video_sha256') != value['video']['sha256'] or first.get('video_path') != value['video']['path']
            or first.get('title') != before['payload']['request'].get('title')
            or not before['created_at'] <= datetime.fromisoformat(first['at_bjt']).timestamp() <= before['updated_at']
            or not any(row.get('stage') == 'submission_started' for row in rows)
            or not any(row.get('stage') == 'submission_unknown' for row in rows)):
        _reject()
    return value


def _write_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        handle.write(_json(value))
        handle.flush()
        os.fsync(handle.fileno())


def archive_submission_lock(store, command_id, owner_id, generation, *, expected_snapshot_sha256,
                            authorization, destination):
    """Move only the exact human-closed lock; preserve intent on any unknown I/O."""
    destination = Path(destination).resolve()
    if (not destination.is_relative_to((ROOT / 'data').resolve())
            or store.path != (ROOT / 'data/account_browser_control.db').resolve()):
        _reject()
    with store._db(write=True) as db:
        row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone()
        closed = store._command(row)
        if (not closed or closed['kind'] != 'publish' or closed['state'] != 'failed'
                or closed['error_code'] != 'operator_closed_external_outcome_unknown'
                or closed['owner_id'] != owner_id or closed['generation'] != generation
                or snapshot_sha256(closed) != expected_snapshot_sha256):
            _reject()
        store._owner(db, closed['account_id'], owner_id, generation, closed['binding_version'])
        if db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown') LIMIT 1",
                (closed['account_id'],)).fetchone():
            _reject()
        result = closed['result']
        if (result.get('original_outcome_known') is not False or result.get('authorization') != authorization
                or result.get('before_snapshot_sha256') != snapshot_sha256(result['before_snapshot'])):
            _reject()
        value = validate_closure_authorization(result['before_snapshot'], authorization)
        source = _bound(value['submission_lock'])
        intent_path = destination.with_name(destination.name + '.intent.json')
        receipt_path = destination.with_name(destination.name + '.receipt.json')
        if destination.exists() or intent_path.exists() or receipt_path.exists() or source == destination:
            _reject()
        destination.parent.mkdir(parents=True, exist_ok=True)
        intent = {'schema': ARCHIVE_SCHEMA, 'phase': 'intent', 'command_id': command_id,
            'authorization': authorization, 'closed_snapshot': closed,
            'closed_snapshot_sha256': expected_snapshot_sha256, 'control_db': str(store.path),
            'journal': value['journal'], 'original_lock': value['submission_lock'],
            'archive': {'path': str(destination), 'sha256': value['submission_lock']['sha256']}}
        _write_new(intent_path, intent)
        # Windows rename refuses an existing target. POSIX uses exclusive link
        # creation to preserve the same no-overwrite bound before unlinking.
        if os.name == 'nt':
            os.rename(source, destination)
        else:
            os.link(source, destination)
            source.unlink()
        if file_reference(destination) != intent['archive'] or source.exists():
            _reject()
        receipt = dict(intent, phase='archived', intent=file_reference(intent_path))
        _write_new(receipt_path, receipt)
        return file_reference(receipt_path)


def validate_archived_publication_retry(authorization, archive_receipt):
    receipt = _json_ref(archive_receipt)
    closed = receipt.get('closed_snapshot')
    if (receipt.get('schema') != ARCHIVE_SCHEMA or receipt.get('phase') != 'archived'
            or not isinstance(closed, dict) or closed.get('kind') != 'publish' or closed.get('state') != 'failed'
            or closed.get('error_code') != 'operator_closed_external_outcome_unknown'
            or receipt.get('closed_snapshot_sha256') != snapshot_sha256(closed)
            or receipt.get('command_id') != closed['command_id'] or receipt.get('authorization') != authorization
            or closed.get('result', {}).get('authorization') != authorization):
        _reject()
    from .browser_control import BrowserControlStore
    db_path = (ROOT / 'data/account_browser_control.db').resolve()
    if receipt.get('control_db') != str(db_path):
        _reject()
    current = BrowserControlStore(db_path).get(closed['command_id'])
    if current != closed:
        _reject()
    _bound(receipt['intent'])
    _bound(receipt['archive'])
    before = closed['result']['before_snapshot']
    if (closed['result'].get('original_outcome_known') is not False
            or closed['result'].get('before_snapshot_sha256') != snapshot_sha256(before)):
        _reject()
    value = validate_closure_authorization(before, authorization, archived_lock=receipt['archive'])
    if receipt.get('journal') != value['journal'] or receipt.get('original_lock') != value['submission_lock']:
        _reject()
    return value
