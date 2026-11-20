"""Use the real atomic producer with isolated fake browser IO and private DB."""
import json
import pytest

from test_publication_verification_recovery import incident, execute
from src.services.publication_evidence import PublicationEvidenceReader

POST = '7700000000000000001'


def settle(i, monkeypatch):
    out, _, _ = execute(i, monkeypatch, discovery={
        'verified': True, 'post_id': POST, 'publish_url': f'https://www.douyin.com/video/{POST}'})
    assert out['state'] == 'succeeded'
    return out


def read(i):
    return PublicationEvidenceReader(i.store.path, evidence_root=i.journal.parents[2]).read(
        i.original['command_id'], 'account:a', 'binding')


def test_actual_atomic_settlement_is_readable_and_read_only(incident, monkeypatch):
    i = incident
    settle(i, monkeypatch)
    original, lock = i.store.get(i.original['command_id']), i.lock.read_bytes()
    before = i.store.path.read_bytes()
    assert read(i)['post_id'] == POST
    assert i.store.path.read_bytes() == before
    assert i.store.get(i.original['command_id']) == original and i.lock.read_bytes() == lock


@pytest.mark.parametrize('mutation', ['other_account', 'missing_verifier', 'receipt_post',
    'old_payload', 'old_snapshot', 'pending_review', 'missing_title', 'missing_ai', 'player_error'])
def test_changed_settlement_proof_rejected(incident, monkeypatch, mutation):
    i = incident; out = settle(i, monkeypatch)
    with i.store._db(write=True) as db:
        if mutation == 'other_account':
            db.execute("UPDATE browser_control_commands SET account_id='other' WHERE command_id=?", (out['command_id'],))
        elif mutation == 'missing_verifier':
            db.execute('DELETE FROM browser_control_commands WHERE command_id=?', (out['command_id'],))
        elif mutation == 'receipt_post':
            db.execute("UPDATE browser_control_commands SET result=json_set(result,'$.post_id','7700000000000000002') WHERE command_id=?", (out['command_id'],))
        else:
            r = i.store.get(i.original['command_id'])['result']
            if mutation == 'old_payload':r['original_unknown_snapshot']['payload']['request']['title'] = 'changed'
            if mutation == 'old_snapshot':r['original_unknown_snapshot']['updated_at'] += 1
            if mutation == 'pending_review':r['publish_evidence']['review_status'] = 'pending'
            if mutation == 'missing_title':r['publish_evidence']['title_verified'] = False
            if mutation == 'missing_ai':r['publish_evidence']['ai_label_visible'] = False
            if mutation == 'player_error':r['publish_evidence']['player']['error'] = True
            db.execute('UPDATE browser_control_commands SET result=? WHERE command_id=?',
                (json.dumps(r, ensure_ascii=False), i.original['command_id']))
    with pytest.raises(ValueError):read(i)


@pytest.mark.parametrize('target', ['journal', 'lock'])
def test_retained_native_claim_must_still_match(incident, monkeypatch, target):
    i = incident; settle(i, monkeypatch)
    path = i.journal if target == 'journal' else i.lock
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError):read(i)


def test_unsettled_original_still_rejected(incident):
    with pytest.raises(ValueError, match='not_verified'):read(incident)
