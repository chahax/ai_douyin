"""CPU/filesystem black boxes; real native evidence, fake managed platform edge.

Only temporary project-data ledgers and receipts are mutated. No production
DB, browser, platform, service, model, media encoder, or network is used.
"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace as NS
import uuid

import pytest

from src.services.fanqie_publication_continuation_v1 import (
    PublicationContinuation, canonical, digest, file_ref,
)
from src.services import fanqie_promotion_identity_v2 as native
from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from src.platform_adapter.fanqie_promotion_observer_v1 import sanitize_metadata

ROOT = Path(__file__).resolve().parents[1]
BOOK, NAME = '1234567890123456780', '黑盒小说'
POST = '1234567890123456789'
URL = 'https://www.douyin.com/video/' + POST
CID = 'original-publication'


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return file_ref(path)


def native_snapshot(folder, binding, *, different_alias=False, unrelated_pending=False, target_pending=False, unrelated_incomplete=False):
    at = time.time()
    alias = '旧屋改命故事'
    source = {k: binding[k] for k in native.SCOPE}
    subject = dict(source, owner_id='test-owner', generation=1, task_id='test-task')
    source.update(observed_at=at, identity_verified=True, challenge=False)
    row = dict(book_id=BOOK, book_name=NAME, alias=alias, publish_type='AIGC', alias_status='生效中',
               book_status='可用', valid_from='2026-01-01', valid_until='2030-01-01',
               published_links=[], fill_status='未填写')
    if target_pending:
        row['alias_status'] = '审核中'
    items = [row]
    if unrelated_pending or unrelated_incomplete:
        items.append(dict(row, book_id='9999999999999999999', book_name='无关审核书籍', alias='无关审核别名', alias_status='审核中'))
    raw = dict(items=items, table_ready=True, loading=False, pagination_complete=True)
    ev = put(folder / 'DOM.json', dict(schema='fanqie_promotion_DOM_evidence/v1', normalizer_version='v1.1', raw=raw, subject=source))
    legacy = put(folder / 'LEGACY.json', managed.normalise_snapshot(raw, **source, evidence_ref=ev))
    record = dict(alias_id='9876543210123456781' if different_alias else '9876543210123456780', book_id=BOOK,
                  book_name=NAME, alias_name=alias, task_type=1, alias_post_type=6, alias_status=3,
                  book_status=1, alias_start_time='2026-01-01', alias_end_time='2030-01-01')
    # Keep pagination complete while deliberately leaving just a DOM/native
    # join pending. A missing native row would make the entire table incomplete.
    if target_pending:
        record['alias_name'] = '尚未关联词'
    records = [record]
    if unrelated_pending or unrelated_incomplete:
        other = dict(record, alias_id='9876543210123456782', book_id='9999999999999999999',
                     book_name='无关审核书籍', alias_name='无关审核别名' if unrelated_incomplete else '尚未关联词')
        if unrelated_incomplete:
            other.pop('task_type')
        records.append(other)
    def capture(endpoint, body):
        return dict(status=200, method='GET', endpoint=dict(origin='https://kol.fanqieopen.com', path=endpoint),
                    metadata=sanitize_metadata(body, endpoint_path=endpoint), body_size_evidence=dict(
                        source='request.sizes.responseBodySize', completion_event='requestfinished',
                        response_body_size=4000, decoded_body_bytes=4000))
    observation = put(folder / 'OBS.json', dict(schema='fanqie_promotion_observer/v1', subject=subject,
        page_location=dict(origin='https://kol.fanqieopen.com', path='/page/promotion-list'), native_requests_issued=0,
        native_body_saved=False, observed_at=at + .001, captures=[
            capture(native.PROMOTION_ENDPOINT, dict(code=0, data=dict(total=len(records), promotion_list=records))),
            capture(native.ENUM_ENDPOINT, dict(code=0, data=dict(kol_alias_post_type=[dict(text='AIGC', value=6)])))]))
    return native.prepare_snapshot(legacy, observation, folder / 'native', managed_subject=subject)


class FakeWorkspace:
    """Persistent fake edge, so independent processes share the same receipts."""
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / 'p0.db'
        self.config = json.loads((self.folder / 'CONFIG.json').read_text(encoding='utf-8'))
        self.binding = self.config['binding']
        self.accounts = NS(db=self.folder / 'browser.db', evidence=self.folder / 'evidence', latest_command=self.latest_command)

    def _resource_binding(self, resource):
        assert resource == self.binding['resource_id']
        return deepcopy(self.binding)

    def _candidates(self):
        return NS(get=self.candidate)

    def _backfill(self):
        return NS(get=self.backfill)

    def candidate(self, cid):
        value = json.loads((self.folder / 'CANDIDATE.json').read_text(encoding='utf-8'))
        assert cid == value['candidate_id']
        return value

    def backfill(self, bid):
        value = json.loads((self.folder / 'BACKFILL.json').read_text(encoding='utf-8'))
        assert bid == value['binding_uuid']
        return value

    def save_backfill(self, value):
        put(self.folder / 'BACKFILL.json', value)

    def backfill_status(self, bid):
        row = self.backfill(bid)
        return dict(inputs_verified=True, status=row['status'], manifest_sha256=row['manifest_sha'],
                    post_id=POST, publish_url=URL)

    def command(self, cid):
        with sqlite3.connect(self.accounts.db) as db:
            db.row_factory = sqlite3.Row
            r = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (cid,)).fetchone()
        if not r:
            return None
        value = dict(r)
        value['payload'] = json.loads(value['payload'])
        value['result'] = json.loads(value['result'])
        return value

    def store_command(self, command):
        raw = {**command, 'payload': canonical(command['payload']), 'result': canonical(command.get('result') or {})}
        with sqlite3.connect(self.accounts.db) as db:
            db.execute('INSERT OR REPLACE INTO browser_control_commands VALUES(:command_id,:account_id,:binding_version,:kind,:state,:payload,:result,:idempotency_key,:created_at,:updated_at)', raw)
        return command

    def latest_command(self, resource):
        with sqlite3.connect(self.accounts.db) as db:
            r = db.execute('SELECT command_id FROM browser_control_commands WHERE account_id=? ORDER BY created_at DESC LIMIT 1', (resource,)).fetchone()
        return self.command(r[0]) if r else None

    def calls(self):
        p = self.folder / 'CALLS.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []

    def record(self, kind):
        with (self.folder / 'CALLS.jsonl').open('a', encoding='utf-8') as out:
            out.write(canonical({'kind': kind}) + '\n')
            out.flush()
            os.fsync(out.fileno())

    def maybe_crash(self, kind):
        if self.config.get('crash_kind') == kind and not (self.folder / ('CRASHED_' + kind)).exists():
            put(self.folder / ('CRASHED_' + kind), True)
            raise RuntimeError('edge accepted effect then receipt was lost')

    def queued(self, kind, key, payload, *, metadata=False, state='succeeded', result=None):
        command = dict(command_id=uuid.uuid4().hex, account_id='douyin:test' if metadata else self.binding['resource_id'],
                       binding_version='douyin-version' if metadata else self.binding['binding_version'],
                       kind=kind, state=state, payload=payload, result=result or {}, idempotency_key=key,
                       created_at=time.time(), updated_at=time.time())
        return self.store_command(command)

    def publication(self, command_id, uid, version):
        command = self.command(command_id)
        if command['state'] != 'succeeded' or command['result'].get('post_verified') is not True:
            raise ValueError('original_publication_not_verified')
        assert uid == 'douyin:test' and version == 'douyin-version'
        return dict(post_id=POST, publish_url=URL, receipt_sha256='verified-original-receipt')

    def publication_time(self, command_id, uid, version, *, metadata_command_id=None):
        command = self.command(command_id)
        if not command['result'].get('published_at') and not metadata_command_id:
            raise ValueError('verified_publication_metadata_required')
        if metadata_command_id:
            assert self.command(metadata_command_id)['state'] == 'succeeded'
        return dict(schema='publication_time_evidence/v1', published_at='2026-11-17T09:37:00+08:00',
                    source='verified_sync_videos' if metadata_command_id else 'original_publish',
                    publication_command_id=command_id, post_id=POST, account_uuid=uid, binding_version=version,
                    source_command_id=metadata_command_id or command_id)

    def request_publication_metadata(self, candidate_id):
        self.record('metadata')
        cmd = self.queued('read', 'h3-publication-metadata:' + CID + ':' + POST,
                          dict(method='sync_videos', params={}), metadata=True)
        self.maybe_crash('metadata')
        return dict(command_id=cmd['command_id'], state=cmd['state'])

    def attach_publication(self, candidate_id, command_id, *, metadata_command_id=None):
        self.record('attach')
        candidate = self.candidate(candidate_id)
        candidate.update(publish_id=7, dispatch_state='published')
        put(self.folder / 'CANDIDATE.json', candidate)
        handoff = dict(schema='fanqie_h3_publication_handoff/v2', candidate_id=candidate_id, command_id=command_id,
            book_id=BOOK, media=json.loads(candidate['frozen_json'])['media'], task_id=2, video_job_id=5, publish_id=7,
            post_id=POST, publish_url=URL, published_at='2026-11-17T09:37:00+08:00',
            account_uuid='douyin:test', account_key='novel:test', binding_version='douyin-version')
        ref = put(self.accounts.evidence / 'publication_handoffs' / 'HANDOFF_test.json', handoff)
        self.maybe_crash('attach')
        return ref

    def sync(self, resource, *, snapshot_version):
        self.record('sync')
        before = self.latest_command(resource)
        ref = native_snapshot(self.folder / ('sync_' + uuid.uuid4().hex), self.binding,
                              different_alias=self.config.get('wrong_native', False),
                              unrelated_pending=self.config.get('unrelated_pending', False),
                              target_pending=self.config.get('target_pending', False),
                              unrelated_incomplete=self.config.get('unrelated_incomplete', False))
        put(self.folder / 'LATEST_SNAPSHOT.json', ref)
        cmd = self.queued('fanqie_promotion_list', 'fanqie-step:' + (before['command_id'] if before else 'initial'),
            dict(environment_key=self.binding['environment_key'], snapshot_version=snapshot_version), result=dict(promotion_snapshot=ref))
        self.maybe_crash('sync')
        return dict(command_id=cmd['command_id'], status='queued', new_request_queued=True)

    def latest_snapshot(self, resource):
        return json.loads((self.folder / 'LATEST_SNAPSHOT.json').read_text(encoding='utf-8'))

    def prepare_backfill(self, handoff_ref, resource, template, output_directory):
        self.record('prepare')
        directory = Path(output_directory)
        assert not directory.exists()
        candidate = self.candidate('candidate-test')
        prepared = json.loads(candidate['prepared_json'])
        manifest = dict(schema='fake-workbook-preparation/v1', publication=dict(post_id=POST, publish_url=URL),
                        binding=dict(published_date='2026/11/17'))
        contract = dict(schema='fanqie_backfill_contract/v3', fanqie_resource_id=resource,
            fanqie_binding_version=self.binding['binding_version'], account_link_version=self.binding['account_link_version'],
            publication_command_id=CID, book_id=BOOK, video_job_id=5, media=json.loads(candidate['frozen_json'])['media'],
            post_id=POST, publish_url=URL, promotion_subject=prepared['promotion']['row'],
            native_identity=prepared['promotion']['row']['identity'], douyin_account_uuid='douyin:test',
            douyin_account_key='novel:test', douyin_binding_version='douyin-version')
        mref, cref = put(directory / 'manifest_v3.json', manifest), put(directory / 'contract_v3.json', contract)
        value = dict(binding_uuid='backfill-test', business_key='business-test', manifest_json=canonical(manifest),
                     manifest_sha=digest(manifest), contract_json=canonical(contract), task_id=2, publish_id=7,
                     authorization_json=None, status='prepared')
        self.save_backfill(value)
        result = dict(schema='fanqie_registered_backfill_preparation/v2', binding_uuid='backfill-test',
                      manifest=mref, contract=cref, task_id=2, publish_id=7, status='prepared_not_authorized')
        put(directory / 'REGISTERED.json', result)
        self.maybe_crash('prepare')
        return result

    def authorize_backfill(self, binding_uuid, *, manifest_sha256, user_statement):
        self.record('authorize')
        row = self.backfill(binding_uuid)
        assert row['manifest_sha'] == manifest_sha256
        row.update(authorization_json=canonical(dict(manifest_sha256=manifest_sha256, reference=user_statement)), status='ready')
        self.save_backfill(row)
        self.maybe_crash('authorize')

    def dispatch_backfill(self, binding_uuid):
        self.record('dispatch')
        row = self.backfill(binding_uuid)
        row['status'] = 'outcome_unknown' if self.config.get('unknown_backfill') else 'confirmed'
        self.save_backfill(row)
        command = self.queued('fanqie_backfill', 'fanqie-backfill:' + row['business_key'],
            dict(binding_uuid=binding_uuid, manifest_sha256=row['manifest_sha']), state='outcome_unknown' if self.config.get('hard_unknown') else 'succeeded')
        self.maybe_crash('dispatch')
        return dict(command=command, launch=dict(status='fake-edge'))

    def reconcile_backfill(self, resource, binding_uuid, manifest_sha256):
        self.record('reconcile')
        row = self.backfill(binding_uuid)
        if self.config.get('reconcile_confirms', True):
            row['status'] = 'confirmed'
            self.save_backfill(row)
        before = self.latest_command(resource)
        key = 'fanqie-backfill-reconcile:' + row['business_key'] + ':' + (before['command_id'] if before else 'initial')
        command = self.queued('fanqie_backfill_reconcile', key,
            dict(environment_key=self.binding['environment_key'], binding_uuid=binding_uuid, manifest_sha256=manifest_sha256))
        self.maybe_crash('reconcile')
        return dict(command_id=command['command_id'], status='queued', new_request_queued=True)


def runner(folder, *, clock=time.time):
    ws = FakeWorkspace(folder)
    return PublicationContinuation(Path(folder) / 'flow', workspace=ws, publication_reader=ws.publication,
                                   publication_time_reader=ws.publication_time, clock=clock)


@pytest.fixture
def example(tmp_path):
    binding = dict(resource_id='fanqie:test', binding_version='fanqie-version', environment_key='fanqie:browser',
                   platform_identity_key='uid:123456', douyin_account_uuid='douyin:test', account_link_version='link-version')
    put(tmp_path / 'CONFIG.json', dict(binding=binding))
    with sqlite3.connect(tmp_path / 'browser.db') as db:
        db.execute('CREATE TABLE browser_control_commands(command_id TEXT PRIMARY KEY,account_id TEXT,binding_version TEXT,kind TEXT,state TEXT,payload TEXT,result TEXT,idempotency_key TEXT,created_at REAL,updated_at REAL)')
    media = tmp_path / 'original.mp4'
    media.write_bytes(b'fake edge original frozen media; not a playable generated asset')
    template = tmp_path / 'official.xlsx'
    template.write_bytes(b'fake official template edge')
    snapshot = native_snapshot(tmp_path / 'initial', binding)
    value = json.loads(Path(snapshot['path']).read_text(encoding='utf-8'))
    subject = native.authorization_subject(value, value['rows'][0])
    request = dict(video_path=str(media), title='原发布标题', description='AI虚构小说故事', hashtags=['小说', 'AI生成'], ai_generated=True, fictional_story=True)
    pubauth = put(tmp_path / 'PUBLISH_AUTH.json', dict(schema='fake-publish-authorization'))
    review = put(tmp_path / 'REVIEW.json', dict(accepted_for_publication=True, quality_passed=False))
    frozen = dict(book_id=BOOK, book_name=NAME, media=file_ref(media), account=dict(account_uuid='douyin:test', account_key='novel:test', binding_version='douyin-version'))
    prepared = dict(promotion=dict(binding=binding, row=subject), request=request, authorization=pubauth, review=review)
    put(tmp_path / 'CANDIDATE.json', dict(candidate_id='candidate-test', task_id=2, video_job_id=5, publish_id=None,
        command_id=CID, dispatch_state='queued', frozen_json=canonical(frozen), prepared_json=canonical(prepared)))
    auth = put(tmp_path / 'USER_SCOPE.json', dict(schema='fanqie_production_trial_user_authorization/v1',
        user_statement='测试通过后继续完整推广流程', interpretation='Exact publishing/backfill after eligibility is verified.',
        authorized_target=dict(book_id=BOOK, book_name=NAME, douyin_account_key='novel:test', fanqie_resource_id=binding['resource_id'], media=file_ref(media))))
    spec = dict(schema='fanqie_publication_continuation/v1', backend=dict(ledger_path=str(tmp_path / 'p0.db'), browser_db=str(tmp_path / 'browser.db')),
                candidate_id='candidate-test', original_publish_command_id=CID, resource_binding=binding,
                book=dict(book_id=BOOK, book_name=NAME), media=file_ref(media), original_authorization=auth, official_template=file_ref(template))
    spec_ref = put(tmp_path / 'SPEC.json', spec)
    ws = FakeWorkspace(tmp_path)
    ws.store_command(dict(command_id=CID, account_id='douyin:test', binding_version='douyin-version', kind='publish', state='outcome_unknown',
        payload=dict(video_sha256=file_ref(media)['sha256'], request=request, authorization=pubauth), result=dict(status='submission_unknown'),
        idempotency_key='publish:' + file_ref(media)['sha256'], created_at=time.time(), updated_at=time.time()))
    return NS(folder=tmp_path, spec=spec, spec_ref=spec_ref, ws=ws)


def verify(example, *, dated=False):
    command = example.ws.command(CID)
    command.update(state='succeeded', result=dict(status='published', success=True, post_verified=True, post_id=POST, publish_url=URL))
    if dated:
        command['result']['published_at'] = '2026-11-17T09:37:00+08:00'
    example.ws.store_command(command)


def configure(example, **changes):
    config = json.loads((example.folder / 'CONFIG.json').read_text(encoding='utf-8'))
    put(example.folder / 'CONFIG.json', dict(config, **changes))


def finish(example, *, steps=30, clock=time.time):
    flow = runner(example.folder, clock=clock)
    for _ in range(steps):
        state = flow.step()
        if state['phase'] == 'confirmed':
            return state
    return state


def test_pending_status_and_steps_do_not_schedule(example):
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    before = (example.folder / 'flow' / 'STATE.json').read_bytes()
    for _ in range(3):
        assert flow.step()['phase'] == 'waiting_publication'
        assert flow.status()['phase'] == 'waiting_publication'
    assert (example.folder / 'flow' / 'STATE.json').read_bytes() == before
    assert example.ws.calls() == []


def test_succeeded_command_without_verified_work_still_waits(example):
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    command = example.ws.command(CID)
    command['state'] = 'succeeded'
    example.ws.store_command(command)
    assert flow.step()['phase'] == 'waiting_publication'
    assert example.ws.calls() == []


def test_complete_public_sequence_and_semantic_sha(example):
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    state = finish(example)
    assert state['confirmed'] and state['phase'] == 'confirmed'
    assert [x['kind'] for x in example.ws.calls()] == ['metadata', 'attach', 'sync', 'prepare', 'authorize', 'dispatch']
    assert state['manifest_sha256'] != state['manifest_file_sha256']
    assert state['manifest_sha256'] == example.ws.backfill('backfill-test')['manifest_sha']
    auth = json.loads(example.ws.backfill('backfill-test')['authorization_json'])
    assert auth['manifest_sha256'] == state['manifest_sha256']
    assert json.loads(auth['reference'])['original_authorization'] == example.spec['original_authorization']
    assert json.loads(auth['reference'])['publication_time']['published_at'] == '2026-11-17T09:37:00+08:00'
    before = example.ws.calls()
    assert finish(example)['phase'] == 'confirmed'
    assert example.ws.calls() == before


def test_original_date_skips_extra_metadata(example):
    runner(example.folder).prepare(example.spec_ref)
    verify(example, dated=True)
    assert finish(example)['confirmed']
    assert 'metadata' not in [x['kind'] for x in example.ws.calls()]


@pytest.mark.parametrize('kind', ['metadata', 'sync', 'prepare', 'authorize', 'dispatch', 'attach'])
def test_lost_receipt_recovers_exact_once(example, kind):
    configure(example, crash_kind=kind)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    assert finish(example, steps=35)['confirmed']
    assert [x['kind'] for x in example.ws.calls()].count(kind) == 1


def test_unknown_backfill_only_readonly_reconcile(example):
    configure(example, unknown_backfill=True)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    state = finish(example)
    assert state['confirmed']
    calls = [x['kind'] for x in example.ws.calls()]
    assert calls.count('dispatch') == 1 and calls.count('reconcile') == 1
    assert not any(x in calls for x in ['apply', 'upload', 'publish', 'recovery'])


def test_hard_unknown_executor_keeps_original_fence(example):
    configure(example, unknown_backfill=True, hard_unknown=True)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    state = finish(example)
    assert state['phase'] == 'waiting_dispatch' and not state['confirmed']
    assert state['reason'] == 'original_executor_unknown_preserved_no_new_command'
    calls = [x['kind'] for x in example.ws.calls()]
    assert calls.count('dispatch') == 1 and 'reconcile' not in calls


def test_unknown_readback_exhaustion_never_resubmits(example):
    configure(example, unknown_backfill=True, reconcile_confirms=False)
    now = [time.time()]
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    for _ in range(4):
        state = finish(example, steps=20, clock=lambda: now[0])
        now[0] += 301
    assert state['reconciliations'] == 3
    assert not state['confirmed'] and state['reason'] == 'read_only_reconciliation_exhausted'
    calls = [x['kind'] for x in example.ws.calls()]
    assert calls.count('dispatch') == 1 and calls.count('reconcile') == 3


@pytest.mark.parametrize('field', ['candidate_id', 'book', 'media'])
def test_wrong_scope_rejected_before_any_effect(example, field):
    spec = deepcopy(example.spec)
    spec[field] = {'book_id': '999', 'book_name': NAME} if field == 'book' else {'path': spec['media']['path'], 'sha256': 'f' * 64} if field == 'media' else 'different-candidate'
    changed = put(example.folder / 'WRONG.json', spec)
    with pytest.raises((ValueError, AssertionError)):
        runner(example.folder).prepare(changed)
    assert example.ws.calls() == []


@pytest.mark.parametrize('field', ['original_authorization', 'official_template', 'media'])
def test_tampered_pinned_ref_rejected(example, field):
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    Path(example.spec[field]['path']).write_bytes(b'changed')
    with pytest.raises((ValueError, json.JSONDecodeError)):
        flow.step()
    assert example.ws.calls() == []


def test_mutated_prepared_intent_rejected(example):
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    candidate = example.ws.candidate('candidate-test')
    p = json.loads(candidate['prepared_json'])
    p['request']['title'] = 'different title'
    candidate['prepared_json'] = canonical(p)
    put(example.folder / 'CANDIDATE.json', candidate)
    with pytest.raises(ValueError, match='publication_intent_changed'):
        flow.step()
    assert example.ws.calls() == []


def test_wrong_native_alias_does_not_prepare(example):
    configure(example, wrong_native=True)
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    verify(example)
    with pytest.raises(ValueError, match='exact_native_alias_required'):
        finish(example)
    assert 'prepare' not in [x['kind'] for x in example.ws.calls()]


def test_unrelated_pending_row_does_not_block_exact_alias(example):
    configure(example, unrelated_pending=True)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    assert finish(example)['confirmed']


def test_target_pending_row_still_blocks_backfill(example):
    configure(example, target_pending=True)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    with pytest.raises(ValueError, match='target_native_alias_pending'):
        finish(example)
    assert 'prepare' not in [x['kind'] for x in example.ws.calls()]


def test_unrelated_identified_row_missing_fields_does_not_block_target(example):
    configure(example, unrelated_incomplete=True)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    assert finish(example)['confirmed']


def test_effect_no_receipt_and_no_original_id_does_not_retry(example, monkeypatch):
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    verify(example)
    flow.step()
    monkeypatch.setattr(flow.workspace, 'request_publication_metadata', lambda *_: (_ for _ in ()).throw(RuntimeError('before queue or unknown')))
    assert flow.step()['phase'] == 'effect_pending'
    for _ in range(4):
        assert runner(example.folder).step()['reason'] == 'effect_receipt_unresolved_no_redispatch'
    assert example.ws.calls() == []


def test_two_processes_share_once_intents(example):
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    script = '''import importlib.util,sys,time
s=importlib.util.spec_from_file_location('fixture_module',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
for i in range(45):
 try:
  v=m.runner(sys.argv[2]).step()
  if v['phase']=='confirmed':break
 except ValueError as e:
  if str(e)!='continuation_busy':raise
 time.sleep(.01)
'''
    args = [sys.executable, '-c', script, str(Path(__file__).resolve()), str(example.folder)]
    a = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    b = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    aa, ae = a.communicate(timeout=40)
    ba, be = b.communicate(timeout=40)
    assert a.returncode == b.returncode == 0, (aa, ae, ba, be)
    assert runner(example.folder).status()['phase'] == 'confirmed'
    assert [x['kind'] for x in example.ws.calls()] == ['metadata', 'attach', 'sync', 'prepare', 'authorize', 'dispatch']


@pytest.mark.parametrize('tamper', ['manifest_file', 'ledger_status', 'original_publication'])
def test_confirmed_cache_is_revalidated_readonly(example, tamper):
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    state = finish(example)
    assert state['confirmed']
    before = example.ws.calls()
    if tamper == 'manifest_file':
        Path(state['preparation']['manifest']['path']).write_text('{}', encoding='utf-8')
    elif tamper == 'ledger_status':
        row = example.ws.backfill('backfill-test')
        row['status'] = 'outcome_unknown'
        example.ws.save_backfill(row)
    else:
        command = example.ws.command(CID)
        command['state'] = 'outcome_unknown'
        example.ws.store_command(command)
    with pytest.raises(ValueError):
        runner(example.folder).status()
    assert example.ws.calls() == before


@pytest.mark.parametrize('kind', ['metadata', 'sync', 'dispatch'])
def test_wrong_direct_receipt_idempotency_key_is_rejected(example, kind, monkeypatch):
    method_name = {'metadata': 'request_publication_metadata', 'sync': 'sync', 'dispatch': 'dispatch_backfill'}[kind]
    original = getattr(FakeWorkspace, method_name)
    def wrong_key(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        cid = result['command']['command_id'] if kind == 'dispatch' else result['command_id']
        command = self.command(cid)
        command['idempotency_key'] += ':unrelated'
        self.store_command(command)
        return result
    monkeypatch.setattr(FakeWorkspace, method_name, wrong_key)
    runner(example.folder).prepare(example.spec_ref)
    verify(example)
    with pytest.raises(ValueError, match='command_changed|idempotency_key_changed'):
        finish(example)
    assert [x['kind'] for x in example.ws.calls()].count(kind) == 1


def test_registered_authorization_cannot_change_before_dispatch(example):
    flow = runner(example.folder)
    flow.prepare(example.spec_ref)
    verify(example)
    for _ in range(20):
        state = flow.step()
        if state['phase'] == 'need_dispatch':
            break
    assert state['phase'] == 'need_dispatch'
    row = example.ws.backfill('backfill-test')
    auth = json.loads(row['authorization_json'])
    auth['reference'] = 'different authorization'
    row['authorization_json'] = canonical(auth)
    example.ws.save_backfill(row)
    with pytest.raises(ValueError, match='manifest_authorization_changed'):
        flow.step()
    assert 'dispatch' not in [x['kind'] for x in example.ws.calls()]
