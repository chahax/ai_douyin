"""Independent public alias-runner black boxes, isolated P0/native evidence.

The dedicated browser/platform queue boundary alone is substituted. No real
browser, network, codecs, model, account recovery or production ledger runs.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace as NS
import uuid

import pytest

from src.services.fanqie_alias_flow_v1 import AliasFlow
from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace, ref
from src.services.fanqie_h3_candidate_v1 import CandidateLedger, migrate
from src.services import fanqie_promotion_identity_v2 as native
from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from src.platform_adapter.fanqie_promotion_observer_v1 import sanitize_metadata

ROOT = Path(__file__).resolve().parents[1]
BOOK = '1234567890123456780'
NAME = '独立黑盒小说'
NEW = ['新推广甲', '新推广乙']
OLD = '原推广未知'
RUN_SUBPROCESS = subprocess.run


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return ref(path)


def snapshot(folder, binding, records=(), *, identity=None):
    """Actual native+DOM validator, with fully synthetic platform observations."""
    at = time.time()
    subject = {k: binding[k] for k in native.SCOPE}
    if identity is not None:
        subject['platform_identity_key'] = identity
    subject.update(owner_id='fixture-owner', generation=1, task_id='fixture-task')
    source = {k: subject[k] for k in native.SCOPE}
    source.update(observed_at=at, identity_verified=True, challenge=False)
    dom, records_native = [], []
    for index, value in enumerate(records):
        alias = value.get('alias', OLD)
        bid = value.get('book_id', BOOK)
        name = value.get('book_name', NAME)
        pending = value.get('pending', False)
        dom.append(dict(book_id=bid, book_name=name, alias=alias,
            publish_type='AIGC', alias_status='审核中' if pending else '生效中',
            book_status='可用', valid_from='2026-01-01', valid_until='2030-01-01',
            published_links=[], fill_status='未填写'))
        records_native.append(dict(alias_id=str(1234567890123456700 + index),
            book_id=bid, book_name=name, alias_name=alias, task_type=1,
            alias_post_type=29, alias_status=1 if pending else 3, book_status=1,
            alias_start_time='2026-01-01', alias_end_time='2030-01-01'))
    raw = dict(items=dom, table_ready=True, loading=False, pagination_complete=True)
    ev = put(folder/'DOM.json', dict(schema='fanqie_promotion_DOM_evidence/v1',
        normalizer_version='v1.1', raw=raw, subject=source))
    legacy = managed.normalise_snapshot(raw, **source, evidence_ref=ev)
    legacy_ref = put(folder/'LEGACY.json', legacy)
    def capture(endpoint, body):
        return dict(status=200, method='GET', endpoint=dict(origin='https://kol.fanqieopen.com', path=endpoint),
            metadata=sanitize_metadata(body, endpoint_path=endpoint), body_size_evidence=dict(
                source='request.sizes.responseBodySize', completion_event='requestfinished',
                response_body_size=4000, decoded_body_bytes=4000))
    obs = dict(schema='fanqie_promotion_observer/v1', subject=subject,
        page_location=dict(origin='https://kol.fanqieopen.com', path='/page/promotion-list'),
        native_requests_issued=0, native_body_saved=False, observed_at=at + .001,
        captures=[capture(native.PROMOTION_ENDPOINT, dict(code=0, data=dict(total=len(records_native), promotion_list=records_native))),
            capture(native.ENUM_ENDPOINT, dict(code=0, data=dict(kol_alias_post_type=[dict(text='AIGC', value=29)])))])
    obs_ref = put(folder/'OBSERVATION.json', obs)
    return native.prepare_snapshot(legacy_ref, obs_ref, folder/'native', managed_subject=subject)


class WorkspaceEdge(PromotionWorkspace):
    """Real workspace apply request builder/P0, only external queue replaced."""
    def __init__(self, folder):
        self.folder = Path(folder)
        self.config = json.loads((self.folder/'CONFIG.json').read_text(encoding='utf-8'))
        self.path = self.folder/'p0.db'
        self.binding = self.config['binding']
        env = dict(resource_id=self.binding['resource_id'], binding_version=self.binding['binding_version'])
        self.accounts = NS(db=self.folder/'browser.db', evidence=self.folder/'evidence',
            get=lambda resource: env, bindings=lambda: NS(get=lambda resource: dict(
                platform_identity_key=self.binding['platform_identity_key'])))

    def _resource_binding(self, resource):
        assert resource == self.binding['resource_id']
        return deepcopy(self.binding)

    def _queue(self, resource, kind, **kwargs):
        script = json.loads((self.folder/'QUEUE.json').read_text(encoding='utf-8'))
        calls = self.calls()
        outcome = script[len(calls)] if len(calls) < len(script) else {}
        command_id = uuid.uuid4().hex
        payload = dict(environment_key=self.binding['environment_key'], **kwargs)
        if 'promotion_request' in payload:
            payload['request'] = payload.pop('promotion_request')
        command = dict(command_id=command_id, kind=kind, account_id=resource,
            binding_version=self.binding['binding_version'], payload=payload,
            state=outcome.get('state', 'succeeded'), result=outcome.get('result', {}))
        if kind == 'fanqie_promotion_list' and 'promotion_snapshot' not in command['result']:
            command['result']['promotion_snapshot'] = snapshot(self.folder/'snapshots'/command_id,
                self.binding, outcome.get('records', []), identity=outcome.get('identity'))
        put(self.folder/'commands'/(command_id+'.json'), command)
        with (self.folder/'CALLS.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(kind=kind, kwargs=kwargs, command_id=command_id), ensure_ascii=False)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
        if outcome.get('delay'):
            time.sleep(outcome['delay'])
        if outcome.get('hard_exit'):
            os._exit(31)
        if outcome.get('raise_after_queue'):
            raise RuntimeError('fixture interrupted after external queue accepted')
        if outcome.get('blocked'):
            return dict(status='blocked_existing_command', command_id=command_id, new_request_queued=False)
        return dict(status='queued', command_id=command_id, new_request_queued=True)

    def calls(self):
        path = self.folder/'CALLS.jsonl'
        return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def command(self, command_id):
        return json.loads((self.folder/'commands'/(command_id+'.json')).read_text(encoding='utf-8'))


def create(folder, outcomes=()):
    assert folder.resolve().is_relative_to(ROOT/'data')
    folder.mkdir(parents=True)
    binding = dict(resource_id='fanqie:independent', binding_version='fv1', environment_key='fanqie:env',
        platform_identity_key='uid:independent', douyin_account_uuid='account:independent', account_link_version='linked-v1')
    put(folder/'CONFIG.json', dict(binding=binding))
    put(folder/'QUEUE.json', list(outcomes))
    with sqlite3.connect(folder/'p0.db') as db:
        db.executescript((ROOT/'tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text(encoding='utf-8'))
    migrate(folder/'p0.db', folder/'before.db')
    media = put(folder/'media.mp4', 'protocol-only unchanged media fixture')
    script = put(folder/'script.md', 'protocol-only frozen source')
    selection = put(folder/'selection.json', {})
    case = put(folder/'case.json', dict(shots=[dict(authoritative_script=script, script_selection=selection)]))
    generation = put(folder/'generation.json', dict(segments=[dict(source_case=case)]))
    code = put(folder/'source.py', 'protocol-only code fixture')
    plan = put(folder/'assembly_plan.json', dict(code=[code]))
    proof = put(folder/'proof.json', dict(protocol=True))
    result = put(folder/'result.json', dict(file=media, proof=proof, plan=plan))
    book = put(folder/'book.json', dict(book_id=BOOK))
    known = put(folder/'known.json', dict(visual_issues=True))
    handoff = put(folder/'handoff.json', dict(schema='novel_promotion_local_candidate/v1', book_id=BOOK,
        book_name=NAME, account_key='novel_independent', media_binding=media, source_manifest=book,
        source_generation_manifest=generation, technical_proof_binding=proof, assembly_receipt_binding=result,
        known_visual_finding=known, overall_video_quality_passed=False, publish_allowed=False))
    provenance = put(folder/'provenance.json', dict(schema='fanqie_candidate_provenance/v1', book_id=BOOK,
        media=media, script=script, script_selections=[selection], source_cases=[case], source_code=[code],
        book_manifest=book, assembly_result=result))
    qa = put(folder/'qa.json', dict(status='technical_cache_review_passed', file=media, result=result, proof=proof,
        all_frame_pixels_and_PTS_cache_revalidated=True, audio_PCM_and_AAC_metrics_cache_revalidated=True,
        original_sources_SHA_revalidated=True))
    ledger = CandidateLedger(folder/'p0.db')
    cid = ledger.register_pending(handoff, provenance_ref=provenance, technical_review_ref=qa,
        account_binding=dict(account_uuid=binding['douyin_account_uuid'], account_key='novel_independent', binding_version='dv1'))
    old = put(folder/'ORIGINAL_UNKNOWN.json', dict(command_id='original-once', state='outcome_unknown', alias=OLD))
    claim = put(folder/'ORIGINAL_CLAIM.json', dict(command_id='original-once', once_only=True))
    intent = dict(resource_binding=binding, backend=dict(ledger_path=str((folder/'p0.db').resolve()),
        browser_db=str((folder/'browser.db').resolve())), book=dict(book_id=BOOK, book_name=NAME,
        publish_type='AIGC', promotion_path='别名推广'), aliases=NEW, observe_aliases=[OLD],
        candidate=dict(candidate_id=cid, media=media), original_records=[old, claim])
    auth = put(folder/'AUTH.json', dict(schema='fanqie_alias_flow_authorization/v1', confirmed_by='user',
        user_statement='Test fixture: preserve original unknown and run named successors once each',
        intent=intent, max_submissions=len(NEW)))
    spec = put(folder/'SPEC.json', dict(schema='fanqie_alias_flow/v1', authorization=auth, **intent))
    workspace = WorkspaceEdge(folder)
    flow = AliasFlow(folder/'flow', workspace=workspace, command_reader=workspace.command)
    flow.prepare(spec)
    return NS(folder=folder, workspace=workspace, flow=flow, spec=spec, intent=intent,
        cid=cid, ledger=ledger, original=[old, claim], initial_candidate=ledger.get(cid))


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Independent alias flow forbids real external process/network')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def drive(fixture, limit=20):
    for _ in range(limit):
        state = fixture.flow.step()
        if state['phase'] in {'record_observed', 'outcome_unknown', 'blocked', 'aliases_exhausted', 'dispatch_receipt_unknown'}:
            return state
    raise AssertionError('flow did not reach bounded terminal')


def assert_unchanged(x):
    assert x.ledger.get(x.cid) == x.initial_candidate
    assert len(x.ledger.list_candidates()) == 1
    for binding in x.original:
        assert ref(binding['path']) == binding


def naming_feedback(alias=NEW[0]):
    """Bound current-alias visible naming failure, actual shared validator shape."""
    message = dict(source='known_error_list', visible=True, attached=True,
        text='与热门书籍/短剧/作者相似度高')
    baseline = dict(stage='baseline', phase='initial', observed_at=1000,
        book_id=BOOK, book_name=NAME, alias=alias, current_alias='', observed_book_ids=[BOOK],
        same_book=True, same_alias=False, messages=[], source='visible_DOM')
    observed = dict(stage='after_fill', phase='prepared', observed_at=1001,
        book_id=BOOK, book_name=NAME, alias=alias, current_alias=alias, observed_book_ids=[BOOK],
        same_book=True, same_alias=True, messages=[message], source='visible_DOM')
    value = dict(observed, schema='fanqie_alias_validation/v1', classification='alias_validation_failed',
        fresh=True, rule_id='alias_name_similarity_high', known_message=message['text'],
        naming_messages=[dict(message, rule_id='alias_name_similarity_high')],
        freshness='new_visible_naming_validation', observation=observed, reference=baseline,
        server_response_evidence=False, platform_business_outcome_verified=False)
    feedback = dict(result='alias_validation_failed', retry_with_new_alias=True, alias_reusable=False,
        submitted=False, alias_validation=value,
        form_feedback=dict(schema='fanqie_application_form_feedback/v1', clicked=False,
            observations=[baseline, observed], latest=observed, baseline=baseline, pre_click=None))
    from src.platform_adapter.fanqie_form_feedback_v1 import confirmed_alias_validation
    assert confirmed_alias_validation(feedback, dict(book_id=BOOK, book_name=NAME, alias=alias))
    return feedback


@pytest.mark.parametrize('pending', [False, True])
def test_public_flow_stops_on_original_alias_record_without_application(tmp_path, pending):
    x = create(tmp_path/'case', [dict(records=[dict(alias=OLD, pending=pending)])])
    state = drive(x)
    assert state['phase'] == 'record_observed'
    assert state['publishable'] is (not pending)
    assert [c['kind'] for c in x.workspace.calls()] == ['fanqie_promotion_list']
    if not pending:
        assert state['promotion_key'].startswith('native_alias:')
        assert state['promotion_subject']['identity']['native_kind'] == 'promotion_alias'
        assert state['sync_command_id'] == x.workspace.calls()[0]['command_id']
    assert_unchanged(x)


def test_unknown_business_success_gets_one_readonly_reconciliation_never_next_alias(tmp_path):
    x = create(tmp_path/'case', [{}, dict(result=dict(application_status='outcome_unknown', status='application_outcome_unknown')), {}])
    state = drive(x)
    assert state['phase'] == 'outcome_unknown'
    assert [c['kind'] for c in x.workspace.calls()] == ['fanqie_promotion_list', 'fanqie_promotion_apply', 'fanqie_promotion_list']
    assert state['alias_index'] == 0
    for _ in range(3):
        x.flow.step()
    assert len(x.workspace.calls()) == 3
    assert_unchanged(x)


@pytest.mark.parametrize('fault', ['static', 'wrong_alias', 'wrong_book', 'not_fresh'])
def test_unproven_validation_never_selects_successor_alias(tmp_path, fault):
    x = create(tmp_path/'case')
    document = naming_feedback()
    validation = document['alias_validation']
    if fault == 'static': validation['classification'] = 'unverified_form_feedback'
    if fault == 'wrong_alias': validation['alias'] = OLD
    if fault == 'wrong_book': validation['book_id'] = '2234567890123456780'
    if fault == 'not_fresh': validation['fresh'] = False
    feedback = put(x.folder/'FEEDBACK.json', document)
    put(x.folder/'QUEUE.json', [{}, dict(state='failed', result=dict(application_status='alias_validation_failed',
        retry_with_new_alias=True, alias_reusable=False, feedback_ref=feedback)), {}])
    state = drive(x)
    assert state['phase'] == 'outcome_unknown' and state['alias_index'] == 0
    assert len([c for c in x.workspace.calls() if c['kind']=='fanqie_promotion_apply']) == 1
    assert_unchanged(x)


def test_verified_alias_validation_requires_sync_before_next_named_alias(tmp_path):
    x = create(tmp_path/'case')
    feedback = put(x.folder/'FEEDBACK.json', naming_feedback())
    put(x.folder/'QUEUE.json', [{}, dict(state='failed', result=dict(application_status='alias_validation_failed',
        retry_with_new_alias=True, alias_reusable=False, feedback_ref=feedback)), {},
        dict(result=dict(application_status='outcome_unknown')), dict(records=[dict(alias=NEW[1])])])
    state = drive(x)
    assert state['phase'] == 'record_observed' and state['publishable']
    calls = x.workspace.calls()
    assert [c['kind'] for c in calls] == ['fanqie_promotion_list', 'fanqie_promotion_apply',
        'fanqie_promotion_list', 'fanqie_promotion_apply', 'fanqie_promotion_list']
    requests = [managed._read(c['kwargs']['promotion_request']) for c in calls if c['kind']=='fanqie_promotion_apply']
    assert [r['alias'] for r in requests] == NEW
    assert managed._intent_key(requests[0]) != managed._intent_key(requests[1])
    assert_unchanged(x)


@pytest.mark.parametrize('state', ['queued', 'running', 'waiting_human', 'paused'])
def test_pending_original_command_only_polled_without_new_queue(tmp_path, state):
    x = create(tmp_path/'case', [dict(state=state)])
    x.flow.step()
    for _ in range(4):
        assert x.flow.step()['phase'] == 'waiting_sync'
    assert len(x.workspace.calls()) == 1
    assert_unchanged(x)


def test_queue_accepted_then_exception_preserves_unknown_and_never_replays(tmp_path):
    x = create(tmp_path/'case', [dict(raise_after_queue=True)])
    assert x.flow.step()['phase'] == 'dispatch_receipt_unknown'
    for _ in range(4):
        x.flow.step()
    assert len(x.workspace.calls()) == 1
    assert_unchanged(x)


def test_status_is_readonly_and_rejects_current_identity_or_original_hash_change(tmp_path):
    x = create(tmp_path/'case')
    before = (x.folder/'flow/STATE.json').read_bytes()
    for _ in range(3):
        x.flow.status()
    assert before == (x.folder/'flow/STATE.json').read_bytes()
    assert not x.workspace.calls()
    x.workspace.binding['platform_identity_key'] = 'uid:changed'
    with pytest.raises(ValueError, match='binding_changed'):
        x.flow.step()
    x.workspace.binding['platform_identity_key'] = x.intent['resource_binding']['platform_identity_key']
    Path(x.original[0]['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(Exception):
        x.flow.step()
    assert not x.workspace.calls()


def test_wrong_native_identity_and_busy_original_executor_never_apply(tmp_path):
    a = create(tmp_path/'wrong_identity', [dict(identity='uid:other')])
    a.flow.step()
    with pytest.raises(ValueError, match='original_native_snapshot'):
        a.flow.step()
    assert len(a.workspace.calls()) == 1
    b = create(tmp_path/'busy', [dict(blocked=True)])
    assert b.flow.step()['phase'] == 'blocked'
    b.flow.step()
    assert len(b.workspace.calls()) == 1
    assert_unchanged(a)
    assert_unchanged(b)


CHILD = """
import json,sys,time,socket,subprocess
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_fanqie_alias_flow_blackbox_v1 import WorkspaceEdge
from src.services.fanqie_alias_flow_v1 import AliasFlow
def forbidden(*args,**kwargs): raise AssertionError('Local child forbids network and child processes')
socket.socket.connect=forbidden
socket.socket.connect_ex=forbidden
socket.create_connection=forbidden
subprocess.Popen=forbidden
folder=Path(sys.argv[1]); workspace=WorkspaceEdge(folder)
flow=AliasFlow(folder/'flow',workspace=workspace,command_reader=workspace.command)
if len(sys.argv)>2:
    deadline=time.monotonic()+15
    while not (folder/'GO').exists():
        if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
        time.sleep(.01)
try:
    result=flow.step(); print(json.dumps({'phase':result['phase']}))
except ValueError as error:
    if str(error)!='flow_busy': raise
    print(json.dumps({'phase':'flow_busy'}))
"""


def local_children(monkeypatch, runs):
    """Only permit this exact local Python stub, never a browser or helper."""
    original = subprocess.Popen
    # autouse replaced subprocess.Popen; obtain the actual implementation from
    # its immutable original class saved below rather than globally allowing I/O.
    monkeypatch.setattr(subprocess, 'Popen', REAL_POPEN)
    try:
        return runs()
    finally:
        monkeypatch.setattr(subprocess, 'Popen', original)


REAL_POPEN = subprocess.Popen


def test_hard_process_exit_after_queue_never_replays_on_new_process(tmp_path, monkeypatch):
    x = create(tmp_path/'case', [dict(hard_exit=True)])
    def run():
        result = RUN_SUBPROCESS([sys.executable, '-c', CHILD, str(x.folder)], cwd=ROOT,
            capture_output=True, text=True, timeout=25, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert result.returncode == 31
    local_children(monkeypatch, run)
    assert len(x.workspace.calls()) == 1
    assert x.flow.step()['phase'] == 'dispatch_receipt_unknown'
    assert len(x.workspace.calls()) == 1
    assert_unchanged(x)


def test_two_processes_same_public_step_dispatch_exactly_once(tmp_path, monkeypatch):
    x = create(tmp_path/'case', [dict(delay=1.2)])
    def run():
        children = [REAL_POPEN([sys.executable, '-c', CHILD, str(x.folder), 'barrier'], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) for _ in range(2)]
        (x.folder/'GO').write_text('go', encoding='ascii')
        outputs = [p.communicate(timeout=25) for p in children]
        put(x.folder/'CHILD_RESULTS.json', dict(returncodes=[p.returncode for p in children], outputs=outputs))
        assert all(p.returncode==0 for p in children), outputs
        phases = [json.loads(out[0])['phase'] for out in outputs]
        assert sorted(phases) == ['flow_busy','waiting_sync'], outputs
    local_children(monkeypatch, run)
    assert len(x.workspace.calls()) == 1
    assert x.flow.status()['phase'] == 'waiting_sync'
    assert_unchanged(x)
