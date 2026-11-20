"""Private-DDL integration using immutable real composite production evidence.

No production DB access, platform, subprocess, network or media processing.
The real 8 native records remain read-only; deliberate mutations are local copies.
"""
import copy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess

import pytest

from src.services import fanqie_composite_candidate_v2 as v2
from src.services.fanqie_h3_candidate_v1 import CandidateBlocked, CandidateLedger, migrate, read_ref

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'data/production_trials/fanqie_full_two_minutes_20261117_v1/candidate_package_v2'
ACCOUNT = dict(account_uuid='account:9158f1d29f70eff9819c46b4', account_key='novel_account_02',
    binding_version='8132c743df4e628fec8dcbec22de03dc419ab7ff0e0f11ac535c550d5cbfce49')


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('No subprocess or network is permitted in provenance tests')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    original = sqlite3.connect
    def connect(path, *args, **kwargs):
        value = str(path).split('?', 1)[0]
        from urllib.parse import unquote, urlparse
        if value.startswith('file:'):
            value = unquote(urlparse(value).path).lstrip('/')
        assert Path(value).resolve().is_relative_to(tmp_path.resolve()), 'Non-private database access'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)


@pytest.fixture
def case(tmp_path):
    h = v2.bind(PACKAGE / 'HANDOFF.json')
    p = v2.bind(PACKAGE / 'PROVENANCE.json')
    qa = v2.bind(PACKAGE / 'TECHNICAL_REVIEW.json')
    def save(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
        return v2.bind(path)
    def changed(mutate):
        handoff, provenance = copy.deepcopy(read_ref(h)), copy.deepcopy(read_ref(p))
        generation = copy.deepcopy(read_ref(handoff['source_generation_manifest']))
        mutate(handoff, provenance, generation)
        handoff['source_generation_manifest'] = save('generation.json', generation)
        return save('handoff.json', handoff), save('provenance.json', provenance)
    def validate(hr=h, pr=p, qr=qa, account=ACCOUNT):
        return v2.validate_candidate(hr, provenance_ref=pr, technical_review_ref=qr, account_binding=account)
    return locals()


def test_real_eight_native_cases_register_new_pending_without_old_review(case, tmp_path):
    x = case
    db = tmp_path / 'p0.db'
    with sqlite3.connect(db) as conn:
        conn.executescript((ROOT / 'tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text(encoding='utf8'))
    migrate(db, tmp_path / 'backup.db')
    store = CandidateLedger(db, clock=lambda: 1000)
    parts = read_ref(x['p'])['parts']; rear = parts[1]['prior_candidate']
    old_id = store.register_pending(rear['handoff'], provenance_ref=rear['provenance'],
        technical_review_ref=rear['technical_review'], account_binding=ACCOUNT)
    old_row = store.get(old_id)
    cid = store.register_pending(x['h'], provenance_ref=x['p'], technical_review_ref=x['qa'], account_binding=ACCOUNT)
    assert cid != old_id and store.get(old_id) == old_row
    assert store.register_pending(x['h'], provenance_ref=x['p'], technical_review_ref=x['qa'], account_binding=ACCOUNT) == cid
    row = store.get(cid)
    assert row['media_sha'] == '0922fc871e71abab664efe3726bfebe2f600b34dcefc2029bdea01ee1d913d6d'
    assert all(row[k] is None for k in ('task_id', 'video_job_id', 'publish_id', 'command_id', 'review_json', 'prepared_json'))
    assert row['dispatch_state'] == 'not_started'
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM fanqie_h3_candidates').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM fanqie_promotion_tasks').fetchone()[0] == 0
    assert len({s['native_id'] for part in parts for s in part['segments']}) == 8
    assert parts[0]['chapter_attribution'] == 'not_established'
    edited = parts[1]['segments'][2]
    assert edited['native_id'] == '8e4e3a4b-8975-4856-b46f-724e0c9f8dac'
    assert read_ref(edited['derivative_result'])['native_id'].startswith('local-audio-edit-')


def test_order_cannot_be_reversed_with_rehashed_metadata(case):
    def mutate(h, p, g):
        p['parts'].reverse(); g['parts'] = p['parts']
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='complete_ordered_two_parts'):
        case['validate'](hr, pr)


def test_front_inline_cannot_claim_authoritative_chapter_script(case):
    def mutate(h, p, g):
        p['parts'][0]['script_mode'] = 'authoritative_script'
        p['parts'][0]['chapter_attribution'] = 'chapter_1_verified'
        g['parts'] = p['parts']
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='legacy_inline_scene_mode_required'):
        case['validate'](hr, pr)


def test_substituted_old_front_s02_attempt_rejected(case):
    def mutate(h, p, g):
        p['parts'][0]['segments'][1]['native_id'] = '4251-old-unknown'
        g['parts'] = p['parts']
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='selected_native_attempt_changed'):
        case['validate'](hr, pr)


def test_rear_cpu_edit_cannot_disguise_original_model_media(case):
    def mutate(h, p, g):
        p['parts'][1]['segments'][2]['derivative_result'] = None
        g['parts'] = p['parts']
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='rear_selected_native_or_derivative_changed'):
        case['validate'](hr, pr)


def test_missing_case_and_wrong_timeline_rejected(case):
    def mutate(h, p, g):
        g['source_cases'].pop()
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='eight_actual_native_scene_bindings_required'):
        case['validate'](hr, pr)
    def timeline(h, p, g):
        p['parts'][0]['segments'][2]['frame_range'] = [0, 362]; g['parts'] = p['parts']
    hr, pr = case['changed'](timeline)
    with pytest.raises(CandidateBlocked, match='composite_scene_timeline_changed'):
        case['validate'](hr, pr)


def test_old_one_minute_technical_review_cannot_approve_full_media(case):
    rear = read_ref(case['p'])['parts'][1]['prior_candidate']
    with pytest.raises(CandidateBlocked, match='same_composite_media_technical_review_required'):
        case['validate'](qr=rear['technical_review'])


def test_registration_index_cannot_silently_rewrite_original_scene(case):
    text = Path(read_ref(read_ref(case['p'])['script'], json_content=False)).read_text(encoding='utf8')
    path = case['tmp_path'] / 'rewritten.md'; path.write_text(text + '\nInvented extra scene', encoding='utf8')
    def mutate(h, p, g):
        p['script'] = v2.bind(path)
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='composite_registration_index_not_verbatim'):
        case['validate'](hr, pr)


def test_source_span_hash_is_verified_not_just_metadata(case):
    source = case['tmp_path'] / 'source.txt'; source.write_text('原文动作与对白', encoding='utf8')
    value = dict(schema='h3_continuity_input/v33', shots=[dict(shot_id='S01', source=v2.bind(source),
        source_scope=dict(start=0, end=7), source_spans=[dict(start=0, end=7, text='原文动作与对白', sha256='f'*64)],
        audio=[{'text': '原话'}], camera_beats=[{'text': '动作'}])])
    ref = case['save']('bad-span.json', value)
    with pytest.raises(CandidateBlocked, match='composite_inline_source_span_changed'):
        v2._scene(ref, 'S01')


@pytest.mark.parametrize('bad', ['missing_first', 'changed_audio_sha'])
def test_native_four_actual_artifacts_cannot_be_omitted_or_changed(case, bad):
    segment = copy.deepcopy(read_ref(case['p'])['parts'][0]['segments'][0])
    native = read_ref(segment['native_result'])
    if bad == 'missing_first':
        native['files'].pop('first')
    else:
        native['files']['audio']['sha256'] = 'f' * 64
    segment['native_result'] = case['save']('changed-native.json', native)
    with pytest.raises(CandidateBlocked, match='composite_native_four_artifacts_required|artifact_changed'):
        v2._native(segment, '7302660145530539062')


def test_new_account_subject_and_media_cannot_reuse_package(case):
    with pytest.raises(CandidateBlocked, match='composite_candidate_subject_mismatch'):
        case['validate'](account={**ACCOUNT, 'account_key': 'different'})
    def mutate(h, p, g):
        h['media_binding'] = p['parts'][0]['media']; p['media'] = h['media_binding']
    hr, pr = case['changed'](mutate)
    with pytest.raises(CandidateBlocked, match='composite_assembly_subject_or_code_changed'):
        case['validate'](hr, pr)
