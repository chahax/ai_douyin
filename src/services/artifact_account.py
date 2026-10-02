"""Resolve ownership from explicit local provenance, never from the selected UI account."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def artifact_account(record: dict, root: Path = ROOT, *, seen=None) -> dict:
    seen = set(seen or ())
    owners = []
    if record.get('account_uuid'):
        owners.append({'account_uuid': str(record['account_uuid']),
                       'account_key': str(record.get('account_key') or '')})
    for key in ('account_context', 'metadata'):
        nested = record.get(key)
        if isinstance(nested, dict) and nested.get('account_uuid'):
            owners.append({'account_uuid': str(nested['account_uuid']),
                           'account_key': str(nested.get('account_key') or '')})
    for key in ('production_manifest', 'source_script', 'source_audit'):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            continue
        path = (root / value).resolve()
        if path in seen or not path.is_relative_to((root / 'data').resolve()) or len(seen) >= 8:
            continue
        try:
            source = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(source, dict):
                owner = artifact_account(source, root, seen=seen | {path})
                if owner.get('account_conflict'):
                    return owner
                if owner['account_uuid']:
                    owners.append(owner)
        except (OSError, ValueError):
            continue
    uuids = {o['account_uuid'] for o in owners}
    if len(uuids) > 1:
        return {'account_uuid': '', 'account_key': '', 'account_conflict': True}
    return next((o for o in owners if o.get('account_key')), owners[0] if owners else
                {'account_uuid': '', 'account_key': ''})
