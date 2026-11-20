"""Read the existing atomic publication_verify settlement without browser IO.

This adapts that producer's proof contract; it never settles an unknown command
or treats a pending moderation card as a published work.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _require(value):
    if not value:
        raise ValueError('publication_verification_evidence_mismatch')


def _source_file(ref, directory):
    _require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'})
    path = Path(ref['path']).resolve()
    _require(path.is_relative_to(directory) and path.is_file())
    raw = path.read_bytes()
    _require(len(raw) <= 16 * 1024 * 1024
        and hashlib.sha256(raw).hexdigest() == ref['sha256'])
    return path, raw


def read_verified_recovery(original, result, command, evidence_root):
    """Validate both settled records, original unknown, and retained UI claim."""
    old = result.get('original_unknown_snapshot')
    _require(isinstance(old, dict) and old.get('state') == 'outcome_unknown'
        and all(old.get(k) == original[k] for k in
            ('command_id', 'account_id', 'binding_version', 'kind'))
        and old.get('payload') == json.loads(original['payload']))
    _require(command['kind'] == 'publication_verify' and command['state'] == 'succeeded'
        and command['account_id'] == original['account_id']
        and command['binding_version'] == original['binding_version']
        and command['command_id'] == result.get('reconciliation_command_id')
        and result.get('post_verified') is True
        and result.get('submission_lock_retained') is True)
    payload = json.loads(command['payload'])
    receipt = json.loads(command['result'] or '{}')
    _require(payload.get('original_command_id') == original['command_id']
        and payload.get('account_uuid') == original['account_id']
        and payload.get('original_snapshot_sha256') == _sha(old)
        and payload.get('source') == result.get('source')
        and receipt.get('status') == 'verified_published'
        and receipt.get('original_command_id') == original['command_id']
        and all(receipt.get(k) == result.get(k) for k in
            ('post_id', 'publish_url', 'publish_evidence'))
        and receipt.get('comment_submitted') is False)
    source = payload.get('source')
    _require(isinstance(source, dict) and set(source) == {'journal', 'submission_lock'})
    directory = (Path(evidence_root) / 'data/publish_runs').resolve()
    journal, raw = _source_file(source['journal'], directory)
    _, lock_raw = _source_file(source['submission_lock'], directory)
    _require(json.loads(lock_raw) == {'journal': str(journal), 'status': 'submission_started'})
    rows = [json.loads(line) for line in raw.decode('utf8').splitlines() if line.strip()]
    prepared = [r for r in rows if r.get('stage') == 'prepared']
    _require(len(prepared) == 1
        and sum(r.get('stage') == 'submission_started' for r in rows) == 1
        and sum(r.get('stage') == 'publish_click_dispatching' for r in rows) == 1)
    request = old['payload']['request']
    first = prepared[0]
    tags = [v.strip().lstrip('#') for v in request.get('hashtags', []) if v.strip().lstrip('#')]
    _require(first.get('account_uuid') == original['account_id']
        and first.get('account') == old['payload'].get('account_key') == payload.get('account_key')
        and first.get('video_sha256') == old['payload'].get('video_sha256')
        and first.get('title') == request['title']
        and first.get('description') == request.get('description', '')
        and first.get('hashtags') == tags
        and first.get('visibility') == request.get('visibility', 'public')
        and first.get('ai_declaration_required') == request.get('ai_generated', True)
        and first.get('fiction_declaration_required') == request.get('fictional_story', True)
        and Path(first.get('video_path', '')).resolve() == Path(request['video_path']).resolve())
    started = datetime.fromisoformat(first['at_bjt']).timestamp()
    _require(old['created_at'] - 5 <= started <= old['updated_at'] + 5)
    evidence = result.get('publish_evidence') or {}
    _require(evidence.get('verified') is True
        and evidence.get('post_id') == result.get('post_id')
        and evidence.get('publish_url') == result.get('publish_url')
        and evidence.get('expected_title') == request['title']
        and evidence.get('expected_hashtags') == tags
        and evidence.get('title_verified') is True
        and evidence.get('hashtags_verified') is True
        and evidence.get('review_status') == 'clear')
    player = evidence.get('player') or {}
    _require(player.get('ready') is True and player.get('error') is False
        and player.get('duration') is True)
    if request.get('ai_generated', True):
        from src.operations_accounts.publication_reconciliation import _active_ai_source
        _require(evidence.get('ai_label_visible') is True and _active_ai_source(rows))
    if request.get('fictional_story', True):
        _require(evidence.get('fiction_notice_visible') is True)
    # The producer uses verified on the detail and post_verified on the outer
    # atomic result. Normalize only after both records and all source proofs pass.
    return {**evidence, 'post_verified': True,
        'reconciliation_command_id': command['command_id'],
        'original_snapshot_sha256': payload['original_snapshot_sha256'],
        'verification_source_sha256': _sha(source)}
